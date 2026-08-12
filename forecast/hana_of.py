"""
hana_of.py — Conector de Órdenes de Fabricación + Terminal Report desde SAP HANA.
Traverso S.A. · Sistema de Planificación de Producción · Conciliación OF/TR.

PROPÓSITO
    Leer las OF ingresadas a SAP con su estado de recepción (Terminal Report) y
    persistirlas en Postgres (mrp_of_sap) para medir, SIN tocar el solver:
      · Cumplimiento de OF (producido vs planificado).
      · Recepción diaria (parciales en el tiempo).
      · Consistencia plan↔SAP (agregado SKU-día; ancla en Fecha inicio planificada).
    Ver DISENO_conciliacion_of.md.

FUENTE (verificada con dato 12-08-2026)
    CALL "SBO_TRAVERSO"."SP_OF_TERMINAL_REPORT"()  — SP sin parámetros.
    Ventana MÓVIL de ~6 meses (feb→hoy), ~9.900 filas, estable (no crece).
    Grano: UNA FILA POR RECIBO (evento de TR). Una OF con varios lotes → varias
    filas con el mismo (OF, TR) pero distinto BatchNum.

CONTRATO DEL DATO — CENTINELAS TEXTUALES (lección 12-08)
    El SP marca ausencia con TEXTO, no con NULL. Verificado:
      · OF sin recibir  -> TERMINAL REPORT(RECIBO) = "Pendiente", Cant Producida = 0.
      · Línea no cargada -> Linea de produccion   = "Sin Asignar" (98,9% del dato).
    Detección de PENDIENTE robusta: `cant_producida == 0`, NO el texto del TR (que
    ya cambió una vez: NULL -> "Pendiente" al agregar columnas). Los centinelas se
    normalizan a NULL/'' al persistir (_norm_centinela).

CLAVE (verificada con dato)
    (orden_produccion, terminal_report, batchnum) es única sobre TODO el dataset
    (0 colisiones, incluidas las 443 pendientes). El BatchNum resuelve los 24 pares
    (OF,TR) que el lote duplicaba. Las pendientes comparten TR="Pendiente"/bn=''
    pero cada OF pendiente es una sola fila -> no colisionan.

ALCANCE (deliberado)
    - NO persiste Precio (costo, sensible) ni Comentarios salvo que una métrica lo
      pida (criterio PII de hana_pedidos.py).
    - Devuelve/persiste en las UNIDADES del SP (a confirmar cajas vs unidades contra
      u_por_caja al construir las vistas; ver DISENO §8).

Uso standalone (prueba, imprime resumen sin persistir):
    docker exec -e HANA_PWD="$HANA_PWD" traverso_forecast python3 /app/hana_of.py
"""

import logging
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from hdbcli import dbapi

logger = logging.getLogger(__name__)


# =============================================================================
# Configuración — idéntica a hana_pedidos.py (misma HANA, mismo usuario RO)
# =============================================================================

HANA_ADDRESS = "180.2.1.57"
HANA_PORT    = 30015
HANA_USER    = "CONSULTA_SAP"
HANA_PWD_ENV = "HANA_PWD"

# Timeouts de red (ms). Sin esto, un HANA que no responde cuelga el cron sin avisar
# (misma lección que hana_pedidos.py L58-61: falla silenciosa peor que error).
HANA_CONNECT_TIMEOUT_MS = 10000
HANA_COMM_TIMEOUT_MS    = 60000   # el SP de OF barre ~6 meses; más holgado que OV

SCHEMA    = "SBO_TRAVERSO"
SP_NOMBRE = "SP_OF_TERMINAL_REPORT"

# Columnas del SP (18, verificado 12-08-2026). Índice por NOMBRE, no por posición.
COL_ORDEN       = "ORDEN PRODUCCION"
COL_TR          = "TERMINAL REPORT(RECIBO)"
COL_FECHA_INI   = "Fecha inicio planificada"
COL_FECHA_FIN   = "Fecha fin planificada"
COL_LINEA       = "Linea de produccion"
COL_FECHA_TR    = "Fecha de contabilizacion"
COL_REF_BASE    = "Referencia de documento base"
COL_SKU         = "Numero de articulo"
COL_DESC        = "Descripcion articulo"
COL_PLANIF      = "Cantidad Planificada"
COL_PRODUC      = "Cantidad Producida"
COL_ALMACEN     = "Codigo de almacen"
COL_BATCHNUM    = "BatchNum"
COL_LOTE        = "ItemCode Lote"
COL_VCTO_LOTE   = "FECHA VCTO LOTE"
COL_CANT_LOTE   = "Cant Lote"

COLUMNAS_REQUERIDAS = [COL_ORDEN, COL_TR, COL_SKU, COL_PLANIF, COL_PRODUC,
                       COL_FECHA_INI, COL_FECHA_TR, COL_BATCHNUM]
N_COLUMNAS_ESPERADO = 18

# Valores centinela que el SP usa por "vacío". Se normalizan a None/'' al persistir.
# Si el SP cambia el texto (ya pasó: NULL -> "Pendiente"), la detección de pendiente
# por cant_producida==0 sigue funcionando igual.
CENTINELAS = {"", "none", "nan", "pendiente", "sin asignar", "null"}


# =============================================================================
# Conexión — calcada de hana_pedidos.conectar()
# =============================================================================

def conectar(password: str | None = None) -> dbapi.Connection:
    """Abre conexión HANA. Password del argumento o del entorno; nunca hardcode."""
    pwd = password if password is not None else os.environ.get(HANA_PWD_ENV)
    if not pwd:
        raise RuntimeError(
            f"Falta el password de HANA. Definí {HANA_PWD_ENV} "
            f"(ej.: `read -rs {HANA_PWD_ENV} && export {HANA_PWD_ENV}`)."
        )
    return dbapi.connect(
        address=HANA_ADDRESS, port=HANA_PORT, user=HANA_USER, password=pwd,
        encrypt=True, sslValidateCertificate=False,
        connectTimeout=HANA_CONNECT_TIMEOUT_MS,
        communicationTimeout=HANA_COMM_TIMEOUT_MS,
    )


# =============================================================================
# Normalización / casteo
# =============================================================================

def _norm_texto(v) -> str:
    """Trim + centinela->'' . Deja el texto tal cual si es un valor real."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in CENTINELAS else s


def _norm_decimal(v) -> Decimal:
    """Cantidad -> Decimal. Texto/formateado/centinela -> Decimal(0).
    Patrón de hana_pedidos: Decimal(str(x or 0)); acá con guarda de formato."""
    if v is None:
        return Decimal(0)
    s = str(v).strip()
    if s.lower() in CENTINELAS:
        return Decimal(0)
    # separador de miles/decimal: el SP entrega '15000' o '2342.71'. Si algún día
    # llega con coma de miles, se limpia acá (no romper por eso).
    s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        logger.warning("Cantidad no parseable: %r -> 0", v)
        return Decimal(0)


def _norm_fecha(v) -> date | None:
    """Fecha -> date | None. El cursor hdbcli suele entregar datetime; si viniera
    texto 'DD-MM-YYYY' (p. ej. releído de CSV) también se parsea. Centinela->None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if s.lower() in CENTINELAS:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.warning("Fecha no parseable: %r -> None", v)
    return None


# =============================================================================
# Lectura del SP
# =============================================================================

def leer_of_tr(conn: dbapi.Connection) -> list[dict]:
    """Ejecuta el SP y devuelve una lista de filas-recibo normalizadas.

    Cada dict:
      orden_produccion, terminal_report, sku, descripcion,
      cant_planificada (Decimal), cant_producida (Decimal),
      fecha_ini_planif (date|None), fecha_fin_planif (date|None),
      fecha_tr (date|None), linea (str), batchnum, lote,
      fecha_vcto_lote (date|None), cant_lote (Decimal),
      codigo_almacen, es_granel (bool), pendiente (bool)

    NO agrega: el que persiste decide el grano. Grano de salida = recibo (1:1 con
    las filas del SP).
    """
    cur = conn.cursor()
    try:
        cur.execute(f'CALL "{SCHEMA}"."{SP_NOMBRE}"')
        cols = [d[0] for d in cur.description]

        if len(cols) != N_COLUMNAS_ESPERADO:
            logger.warning("SP %s: %d columnas (esperado %d) — ¿cambió el SP?",
                           SP_NOMBRE, len(cols), N_COLUMNAS_ESPERADO)
        faltan = [c for c in COLUMNAS_REQUERIDAS if c not in cols]
        if faltan:
            raise RuntimeError(
                f"SP {SP_NOMBRE}: faltan columnas requeridas {faltan}. "
                f"Columnas recibidas: {cols}"
            )

        ix = {c: cols.index(c) for c in cols}

        def g(row, col):
            return row[ix[col]] if col in ix else None

        filas = []
        n_pend = 0
        for r in cur.fetchall():
            orden = _norm_texto(g(r, COL_ORDEN))
            if not orden:
                continue  # sin OF no hay fila útil
            sku = _norm_texto(g(r, COL_SKU))
            producida = _norm_decimal(g(r, COL_PRODUC))
            # PENDIENTE por cantidad, NO por el texto del TR (contrato inestable)
            pendiente = producida == 0
            if pendiente:
                n_pend += 1
            # TR: se guarda el valor real; si es centinela ("Pendiente") -> ''
            tr = _norm_texto(g(r, COL_TR))
            filas.append({
                "orden_produccion": orden,
                "terminal_report":  tr,
                "sku":              sku,
                "descripcion":      _norm_texto(g(r, COL_DESC)),
                "cant_planificada": _norm_decimal(g(r, COL_PLANIF)),
                "cant_producida":   producida,
                "fecha_ini_planif": _norm_fecha(g(r, COL_FECHA_INI)),
                "fecha_fin_planif": _norm_fecha(g(r, COL_FECHA_FIN)),
                "fecha_tr":         _norm_fecha(g(r, COL_FECHA_TR)),
                "linea":            _norm_texto(g(r, COL_LINEA)),
                "batchnum":         _norm_texto(g(r, COL_BATCHNUM)),
                "lote":             _norm_texto(g(r, COL_LOTE)),
                "fecha_vcto_lote":  _norm_fecha(g(r, COL_VCTO_LOTE)),
                "cant_lote":        _norm_decimal(g(r, COL_CANT_LOTE)),
                "codigo_almacen":   _norm_texto(g(r, COL_ALMACEN)),
                "es_granel":        sku.startswith("9"),
                "pendiente":        pendiente,
            })
        logger.info("SP %s: %d filas-recibo (%d pendientes / producida=0).",
                    SP_NOMBRE, len(filas), n_pend)
        return filas
    finally:
        cur.close()


# =============================================================================
# main de prueba — read-only, NO persiste
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=" * 64)
    print("Prueba conector HANA — OF + Terminal Report (read-only)")
    print("=" * 64)

    conn = conectar()
    try:
        filas = leer_of_tr(conn)
    finally:
        conn.close()

    ofs = {f["orden_produccion"] for f in filas}
    pend = [f for f in filas if f["pendiente"]]
    granel = [f for f in filas if f["es_granel"]]
    con_linea = [f for f in filas if f["linea"]]

    print()
    print(f"Filas-recibo      : {len(filas):,}")
    print(f"OF distintas      : {len(ofs):,}")
    print(f"Pendientes (p=0)  : {len(pend):,}")
    print(f"Granel (9x)       : {len(granel):,}")
    print(f"Con línea real    : {len(con_linea):,}  ({100*len(con_linea)/max(1,len(filas)):.1f}%)")

    # verificación de clave (of, tr, batchnum) única
    claves = [(f["orden_produccion"], f["terminal_report"], f["batchnum"]) for f in filas]
    print(f"Clave (of,tr,bn)  : {len(claves):,} filas / {len(set(claves)):,} únicas "
          f"-> {'OK única' if len(claves)==len(set(claves)) else 'HAY COLISIONES'}")

    print()
    print("Muestra (3 recibidas + 2 pendientes):")
    for f in [x for x in filas if not x["pendiente"]][:3] + pend[:2]:
        print(f"  OF {f['orden_produccion']} TR {f['terminal_report'] or '(pend)':>10} "
              f"{f['sku']} plan={f['cant_planificada']} prod={f['cant_producida']} "
              f"ini={f['fecha_ini_planif']} tr={f['fecha_tr']} bn={f['batchnum'] or '-'}")
    print("=" * 64)
    print("OK — lectura pura, nada persistido.")
    print("=" * 64)
