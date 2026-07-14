"""
hana_pedidos.py — Conector de pedidos abiertos (OV) desde SAP HANA.
Traverso S.A. · Sistema de Planificación de Producción.

PROPÓSITO
    Leer las notas de venta ABIERTAS (no facturadas) desde SAP Business One
    (HANA) y devolverlas como demanda comprometida diaria por SKU, lista para
    netear contra el forecast en el optimizador.

    Fuentes (mismo HANA, mismo SP, distinto schema):
        SBO_TRAVERSO  → etiqueta BD = "TR"
        SBO_MONTANER  → etiqueta BD = "MO"
    La base mergeada se trata como UNA sola empresa (mismos SKU, bodegas y
    líneas). La etiqueta BD existe SOLO para deduplicar (los correlativos de
    documento son independientes por empresa y pueden colisionar); tras la
    agrupación desaparece y el modelo ve una única demanda por SKU.

ALCANCE (deliberado)
    - LECTURA PURA. No persiste nada, no toca Postgres/optimizer/cron.
    - Devuelve CAJAS. La conversión a unidades (× upc) la hace el enganche al
      modelo, no este módulo.
    - Proyección MÍNIMA: descarta RUT, cliente, dirección, vendedor (PII que el
      modelo no necesita y no debe circular ni loguearse).

CONVENCIONES DE NEGOCIO (decisiones confirmadas, ver Manual)
    - `Cantidad` del SP = saldo pendiente de entrega (cubre ~99% de casos;
      desviación aceptada y monitoreada por logística).
    - Entrega y factura ocurren en la misma fecha: lo abierto = no facturado.
    - Pedidos vencidos (fecha de entrega < hoy) siguen siendo compromisos vivos
      (un encargado anula en SAP los que no se entregarán). Se ARRASTRAN al
      primer día del horizonte (día 0), no se descartan.

Uso standalone (prueba, read-only):
    read -rs HANA_PWD && export HANA_PWD
    docker exec -e HANA_PWD="$HANA_PWD" traverso_forecast python3 /app/hana_pedidos.py
"""

import os
import logging
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from hdbcli import dbapi

logger = logging.getLogger(__name__)


# =============================================================================
# Configuración
# =============================================================================

HANA_ADDRESS = "180.2.1.57"
HANA_PORT    = 30015
HANA_USER    = "CONSULTA_SAP"          # read-only; password vive en env HANA_PWD
HANA_PWD_ENV = "HANA_PWD"

# Timeouts de red (ms). Sin esto, si HANA no responde, conectar()/CALL quedan
# colgados indefinidamente -> el cron de las 6 AM se cuelga sin generar plan.
# Con timeout, la conexión falla en ~10s -> el fail-safe del enganche devuelve {}
# y el plan se genera SIN pedidos (degradación elegante, no cuelgue).
HANA_CONNECT_TIMEOUT_MS = 10000    # apertura de conexión
HANA_COMM_TIMEOUT_MS    = 30000    # espera de respuesta del SP (CALL)

SP_NOMBRE = "EPV_Notas_de_ventas_abiertas_V2"

# (schema, etiqueta BD). Añadir una 3ª empresa aquí no requiere más cambios.
FUENTES: list[tuple[str, str]] = [
    ("SBO_TRAVERSO", "TR"),
    ("SBO_MONTANER", "MO"),
]

# Columnas del SP que SÍ usamos. El resto se descarta (PII).
COL_NUMERO_DOC    = "Numero Doc"
COL_ARTICULO      = "Codigo Articulo"
COL_FECHA_ENTREGA = "Fecha Entrega"
COL_CANTIDAD      = "Cantidad"
COLUMNAS_REQUERIDAS = [COL_NUMERO_DOC, COL_ARTICULO, COL_FECHA_ENTREGA, COL_CANTIDAD]

# Verificaciones defensivas de esquema (§4.6: confirmar, no asumir en runtime).
N_COLUMNAS_ESPERADO = 22       # ambos schemas verificados con 22 columnas idénticas
DIAS_VENCIDA_ALERTA = 15       # log de alerta si una vencida supera este umbral


# -----------------------------------------------------------------------------
# Clasificación de SKU que NO están en mrp_sku_params
# -----------------------------------------------------------------------------
# Semántica FAIL-LOUD: un SKU de OV que no matchea el modelo se excluye del plan,
# pero NO todos los "sin match" son iguales. Distinguimos:
#
#   - PLANTA sin planificar (bundles + omisión): es demanda de producción propia
#     que hoy no se puede mapear. Se EXCLUYE pero se reporta NOMINALMENTE en cada
#     corrida (alerta), para que no se pierda de vista hasta resolverla.
#   - Fuera de alcance (importado / maquila): no se produce en planta, no hay nada
#     que planificar. Se excluye y se AUDITA agregado (cuántos SKU / cuántas cajas),
#     sin ruido nominal.
#
# Cualquier "sin match" que NO esté acá abajo se trata como PLANTA sin planificar
# (grita), no como fuera de alcance. Así, un SKU de planta nuevo u omitido salta
# solo; un importado nuevo genera a lo sumo un falso positivo (investigar y sumar),
# nunca un silencio. Fallar ruidoso > fallar callado.
#
# INTERINO: esta lista vive en código. El hogar correcto es una clasificación en
# BD (p.ej. tabla mrp_sku_no_planificable con motivo). Pendiente, ver snapshot.

SKU_BUNDLE = frozenset({          # combos de SKU individuales que SÍ están en MRP;
    "280010252",                  # requieren explosión a componentes (mini-BOM).
    "280010253",
    "280010254",
    "280010255",
    "280010256",
    "110011275",
})
SKU_PENDIENTE_CARGA = frozenset({ # producción propia omitida de la carga inicial.
    "200110145",
})
SKU_PLANTA_SIN_PLANIFICAR = SKU_BUNDLE | SKU_PENDIENTE_CARGA

MOTIVO_EXCLUSION = {
    **{s: "bundle (explotar a componentes)" for s in SKU_BUNDLE},
    **{s: "pendiente de carga en mrp_sku_params" for s in SKU_PENDIENTE_CARGA},
}


# =============================================================================
# Conexión
# =============================================================================

def conectar(password: str | None = None) -> dbapi.Connection:
    """Abre una conexión HANA. El password se toma del argumento o del entorno
    (`HANA_PWD`) — nunca se hardcodea ni se loguea."""
    pwd = password if password is not None else os.environ.get(HANA_PWD_ENV)
    if not pwd:
        raise RuntimeError(
            f"Falta el password de HANA. Definí la variable de entorno {HANA_PWD_ENV} "
            f"(ej.: `read -rs {HANA_PWD_ENV} && export {HANA_PWD_ENV}`)."
        )
    return dbapi.connect(
        address=HANA_ADDRESS,
        port=HANA_PORT,
        user=HANA_USER,
        password=pwd,
        encrypt=True,
        sslValidateCertificate=False,   # spike: evita fallo por CA no instalada en el container
        connectTimeout=HANA_CONNECT_TIMEOUT_MS,          # ms; falla rápido si HANA no está
        communicationTimeout=HANA_COMM_TIMEOUT_MS,       # ms; no espera indefinido en el CALL
    )


# =============================================================================
# Lectura de una fuente (un schema)
# =============================================================================

def _leer_fuente(conn: dbapi.Connection, schema: str, etiqueta_bd: str) -> list[dict]:
    """Ejecuta el SP de un schema y devuelve filas proyectadas a lo mínimo.

    Cada fila: {"bd", "doc", "sku", "fecha" (date|None), "cantidad" (Decimal)}.
    Descarta todas las demás columnas (PII incluida).
    """
    cur = conn.cursor()
    try:
        cur.execute(f'CALL "{schema}"."{SP_NOMBRE}"')
        cols = [d[0] for d in cur.description]

        # Verificación defensiva de esquema
        if len(cols) != N_COLUMNAS_ESPERADO:
            logger.warning(
                "Schema %s: %d columnas (esperado %d) — posible cambio en el SP.",
                schema, len(cols), N_COLUMNAS_ESPERADO,
            )
        faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in cols]
        if faltantes:
            raise RuntimeError(
                f"Schema {schema}: faltan columnas requeridas {faltantes}. "
                f"Columnas recibidas: {cols}"
            )

        # Índices por NOMBRE (robusto a reordenamientos de columnas)
        i_doc   = cols.index(COL_NUMERO_DOC)
        i_sku   = cols.index(COL_ARTICULO)
        i_fecha = cols.index(COL_FECHA_ENTREGA)
        i_cant  = cols.index(COL_CANTIDAD)

        filas = []
        for r in cur.fetchall():
            fecha = r[i_fecha]
            if isinstance(fecha, datetime):
                fecha = fecha.date()
            filas.append({
                "bd":       etiqueta_bd,
                "doc":      r[i_doc],
                "sku":      str(r[i_sku]).strip(),
                "fecha":    fecha,                       # date | None
                "cantidad": Decimal(str(r[i_cant] or 0)),
            })
        logger.info("Fuente %s (%s): %d líneas leídas.", etiqueta_bd, schema, len(filas))
        return filas
    finally:
        cur.close()


# =============================================================================
# Merge + agrupación + arrastre → demanda comprometida diaria
# =============================================================================

def obtener_pedidos_abiertos(
    conn: dbapi.Connection,
    hoy: date | None = None,
    skus_validos: set[str] | None = None,
) -> dict[str, dict[date, float]]:
    """Lee TR + MO, fusiona duplicados y devuelve demanda comprometida por día.

    Args:
        conn:         conexión HANA abierta.
        hoy:          primer día del horizonte (día 0). Default: date.today().
                      Los pedidos vencidos (fecha < hoy) o sin fecha se arrastran aquí.
        skus_validos: si se pasa (p.ej. claves de mrp_sku_params), los SKU que no
                      matcheen se EXCLUYEN del resultado y se loguean (no se pierden
                      en silencio). Si es None, se devuelven todos (modo prueba).

    Returns:
        {sku: {fecha: cajas_comprometidas}} — unificado, en CAJAS, sin BD ni PII.
    """
    hoy = hoy or date.today()

    # 1. Leer y concatenar todas las fuentes
    filas: list[dict] = []
    conteo_fuente: dict[str, int] = {}
    for schema, etiqueta in FUENTES:
        f = _leer_fuente(conn, schema, etiqueta)
        conteo_fuente[etiqueta] = len(f)
        filas.extend(f)

    # 2. Agrupar por clave sintética (BD, Doc, SKU): MAX saldo, fecha = mínima.
    #    MAX (no Σ) dentro de la misma OV: la query fuente duplica líneas del
    #    mismo SKU en una OV (bug en revisión con TI); las líneas debieran ser
    #    iguales -> tomar la mayor. El sumado entre OV distintas se preserva en
    #    el paso 3. (fecha única por doc verificada; min = salvaguarda defensiva).
    saldo_grupo: dict[tuple, Decimal] = defaultdict(Decimal)
    fecha_grupo: dict[tuple, date | None] = {}
    for r in filas:
        clave = (r["bd"], r["doc"], r["sku"])
        # dedup por máximo dentro de (bd, doc, sku): no sumar líneas repetidas
        if r["cantidad"] > saldo_grupo.get(clave, Decimal(0)):
            saldo_grupo[clave] = r["cantidad"]
        f_actual = fecha_grupo.get(clave, "NA")
        if r["fecha"] is not None:
            if f_actual == "NA" or f_actual is None or r["fecha"] < f_actual:
                fecha_grupo[clave] = r["fecha"]
        elif f_actual == "NA":
            fecha_grupo[clave] = None

    n_fusiones = len(filas) - len(saldo_grupo)

    # 3. Arrastre + construcción de la demanda diaria por SKU
    demanda: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    n_arrastradas = 0
    n_alerta_vieja = 0
    n_fecha_nula = 0
    for clave, saldo in saldo_grupo.items():
        _bd, _doc, sku = clave
        fecha = fecha_grupo.get(clave)

        if fecha is None:
            # Compromiso sin fecha → día 0 (conservador: no se ignora)
            n_fecha_nula += 1
            fecha_efectiva = hoy
        elif fecha < hoy:
            # Vencida viva → arrastre a día 0
            n_arrastradas += 1
            dias = (hoy - fecha).days
            if dias > DIAS_VENCIDA_ALERTA:
                n_alerta_vieja += 1
            fecha_efectiva = hoy
        else:
            fecha_efectiva = fecha

        demanda[sku][fecha_efectiva] += float(saldo)

    # 4. Filtro de match + clasificación de exclusiones (auditable, fail-loud).
    excl_atender: dict[str, float] = {}   # planta sin planificar (bundle / pend. carga)
    excl_fuera:   dict[str, float] = {}   # presumido importado / maquila
    if skus_validos is not None:
        for sku in list(demanda.keys()):
            if sku not in skus_validos:
                cajas = sum(demanda[sku].values())
                if sku in SKU_PLANTA_SIN_PLANIFICAR:
                    excl_atender[sku] = cajas
                else:
                    excl_fuera[sku] = cajas
                del demanda[sku]

    # 5. Resumen (visible en el log del cron; sin PII)
    total_cajas = sum(c for fechas in demanda.values() for c in fechas.values())
    logger.info(
        "Pedidos abiertos | fuentes: %s | líneas: %d | claves: %d | fusiones: %d | "
        "arrastradas(día0): %d | fecha nula: %d | SKU planificados: %d | cajas: %.1f",
        conteo_fuente, len(filas), len(saldo_grupo), n_fusiones,
        n_arrastradas, n_fecha_nula, len(demanda), total_cajas,
    )
    if n_alerta_vieja:
        logger.warning(
            "%d pedido(s) vencido(s) hace > %d días arrastrado(s) a día 0. "
            "¿Proceso de anulación en SAP al día?", n_alerta_vieja, DIAS_VENCIDA_ALERTA,
        )
    if skus_validos is not None:
        # Fuera de alcance: agregado, sin ruido nominal.
        if excl_fuera:
            logger.info(
                "Fuera de alcance (importado/maquila): %d SKU | %.0f cajas NO planificadas.",
                len(excl_fuera), sum(excl_fuera.values()),
            )
        # Planta sin planificar: NOMINAL, es lo que hay que atender.
        if excl_atender:
            logger.warning(
                "DEMANDA DE PLANTA SIN PLANIFICAR: %d SKU | %.0f cajas. Atender:",
                len(excl_atender), sum(excl_atender.values()),
            )
            for sku, cajas in sorted(excl_atender.items(), key=lambda x: -x[1]):
                logger.warning("  %s  %.0f cj  (%s)", sku, cajas,
                               MOTIVO_EXCLUSION.get(sku, "?"))

    # Convertir defaultdicts anidados a dicts planos
    return {sku: dict(fechas) for sku, fechas in demanda.items()}


def obtener_ov_split(
    conn: dbapi.Connection,
    hoy: date | None = None,
    skus_validos: set[str] | None = None,
) -> tuple[dict[str, dict[date, float]], dict[str, float]]:
    """Igual que obtener_pedidos_abiertos, pero SEPARA la OV en dos:

        futuras      -> {sku: {fecha: cajas}}  con fecha_entrega >= hoy.
                        Son DEMANDA en su fecha (se netean contra el forecast).
        comprometido -> {sku: cajas}           con fecha_entrega < hoy (o sin fecha).
                        Son stock ya APARTADO por notas de venta vencidas no
                        despachadas. NO son demanda a producir: se RESTAN del
                        stock_inicial (el stock físico no distingue reservado).

    Decisión de negocio (Germán, 10-07): el inventario de SQL Server no baja hasta
    despacho/factura; una OV vencida-abierta reserva stock existente. Tratarla como
    demanda en día 0 (lo que hacía obtener_pedidos_abiertos) inflaba día 0 y forzaba
    producción inexistente. Acá se reclasifica como rebaja de stock.

    Borde: fecha == hoy -> futura (vence hoy, es demanda de hoy), NO comprometido.

    Misma lectura/agrupado/clasificación fail-loud que obtener_pedidos_abiertos;
    una sola ejecución del SP.
    """
    hoy = hoy or date.today()

    # 1. Leer y concatenar todas las fuentes (idéntico a obtener_pedidos_abiertos)
    filas: list[dict] = []
    conteo_fuente: dict[str, int] = {}
    for schema, etiqueta in FUENTES:
        f = _leer_fuente(conn, schema, etiqueta)
        conteo_fuente[etiqueta] = len(f)
        filas.extend(f)

    # 2. Agrupar por (BD, Doc, SKU): MAX saldo (dedup dentro de la misma OV,
    #    bug de duplicación de la query fuente), fecha mínima. Ver paso 2 de
    #    obtener_pedidos_abiertos. Sumado entre OV distintas se preserva en paso 3.
    saldo_grupo: dict[tuple, Decimal] = defaultdict(Decimal)
    fecha_grupo: dict[tuple, date | None] = {}
    for r in filas:
        clave = (r["bd"], r["doc"], r["sku"])
        # dedup por máximo dentro de (bd, doc, sku): no sumar líneas repetidas
        if r["cantidad"] > saldo_grupo.get(clave, Decimal(0)):
            saldo_grupo[clave] = r["cantidad"]
        f_actual = fecha_grupo.get(clave, "NA")
        if r["fecha"] is not None:
            if f_actual == "NA" or f_actual is None or r["fecha"] < f_actual:
                fecha_grupo[clave] = r["fecha"]
        elif f_actual == "NA":
            fecha_grupo[clave] = None

    # 3. Split: futuras (>= hoy) como demanda diaria; vencidas (< hoy) como comprometido
    futuras: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    comprometido: dict[str, float] = defaultdict(float)
    n_venc = 0
    n_fut = 0
    n_alerta_vieja = 0
    for clave, saldo in saldo_grupo.items():
        _bd, _doc, sku = clave
        fecha = fecha_grupo.get(clave)
        if fecha is None or fecha < hoy:
            # Vencida o sin fecha -> stock comprometido (rebaja), NO demanda
            comprometido[sku] += float(saldo)
            n_venc += 1
            if fecha is not None and (hoy - fecha).days > DIAS_VENCIDA_ALERTA:
                n_alerta_vieja += 1
        else:
            futuras[sku][fecha] += float(saldo)
            n_fut += 1

    # 4. Filtro de match + clasificación fail-loud (sobre AMBOS diccionarios)
    excl_atender: dict[str, float] = {}
    excl_fuera:   dict[str, float] = {}
    if skus_validos is not None:
        skus_ov = set(futuras.keys()) | set(comprometido.keys())
        for sku in skus_ov:
            if sku not in skus_validos:
                cajas = sum(futuras.get(sku, {}).values()) + comprometido.get(sku, 0.0)
                if sku in SKU_PLANTA_SIN_PLANIFICAR:
                    excl_atender[sku] = cajas
                else:
                    excl_fuera[sku] = cajas
                futuras.pop(sku, None)
                comprometido.pop(sku, None)

    # 5. Resumen
    tot_fut = sum(c for fechas in futuras.values() for c in fechas.values())
    tot_comp = sum(comprometido.values())
    logger.info(
        "OV split | fuentes: %s | claves: %d | futuras(demanda): %d grupos, %.0f cj | "
        "comprometido(rebaja stock, vencidas): %d grupos, %.0f cj | "
        "SKU futuras: %d | SKU comprometido: %d",
        conteo_fuente, len(saldo_grupo), n_fut, tot_fut, n_venc, tot_comp,
        len(futuras), len(comprometido),
    )
    if n_alerta_vieja:
        logger.warning(
            "%d OV vencida(s) hace > %d días (comprometen stock). "
            "¿Anulación en SAP al día?", n_alerta_vieja, DIAS_VENCIDA_ALERTA,
        )
    if skus_validos is not None:
        if excl_fuera:
            logger.info("Fuera de alcance (importado/maquila): %d SKU | %.0f cj.",
                        len(excl_fuera), sum(excl_fuera.values()))
        if excl_atender:
            logger.warning("DEMANDA DE PLANTA SIN PLANIFICAR: %d SKU | %.0f cj. Atender:",
                           len(excl_atender), sum(excl_atender.values()))
            for sku, cajas in sorted(excl_atender.items(), key=lambda x: -x[1]):
                logger.warning("  %s  %.0f cj  (%s)", sku, cajas,
                               MOTIVO_EXCLUSION.get(sku, "?"))

    return (
        {sku: dict(fechas) for sku, fechas in futuras.items()},
        dict(comprometido),
    )


# =============================================================================
# main de prueba — read-only, imprime resumen para comparar contra los Excel
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 64)
    print("Prueba conector HANA — pedidos abiertos (TR + MO)")
    print("=" * 64)

    conn = conectar()
    try:
        # Modo prueba: sin skus_validos (no toca Postgres). El match contra
        # mrp_sku_params se activa en la integración pasando skus_validos.
        demanda = obtener_pedidos_abiertos(conn, hoy=date.today(), skus_validos=None)
    finally:
        conn.close()

    n_skus   = len(demanda)
    n_fechas = len({f for fechas in demanda.values() for f in fechas})
    total    = sum(c for fechas in demanda.values() for c in fechas.values())

    print()
    print(f"SKU comprometidos : {n_skus}")
    print(f"Fechas distintas  : {n_fechas}")
    print(f"Total cajas       : {total:,.1f}")
    print()
    print("Muestra (primeros 5 SKU, hasta 3 fechas c/u):")
    for sku in sorted(demanda)[:5]:
        fechas = sorted(demanda[sku].items())[:3]
        detalle = ", ".join(f"{f.isoformat()}={c:,.0f}cj" for f, c in fechas)
        print(f"  {sku}: {detalle}")

    print()
    print("=" * 64)
    print("OK — lectura pura, nada persistido. Comparar totales contra los Excel.")
    print("=" * 64)
