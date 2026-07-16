"""
faltantes.py — Motor de cálculo de "Faltantes por Quiebre"
Traverso S.A. · Informe de faltantes

Definición (cerrada con negocio):
  Para cada (SKU, día D) con entregas programadas:
    - stock_ini_D  = Σ stock (cajas) de las bodegas del proyecto {VESP01,BSUR01,VARA01}
                     en el snapshot de stock de D (dbo.Stock_Lote_Fecha).
    - programado_D = Σ Cant NV de las líneas de OV con Fecha Entrega NV = D.
    - entregado_a_D= Σ Cant Ent de esas líneas cuya Fecha Ent <= D  (entregas tardías
                     NO cuentan como entregadas en D → cuentan como faltante en D).
    - no_entregado_D = max(0, programado_D − entregado_a_D).
  REGLA: si stock_ini_D < programado_D  →  faltante_D = no_entregado_D  (si no, 0).

Fuentes:
  - OV/entregas: SAP HANA, SP EPV_Faltantes_NV_FC_V4 (schemas TR + MO). Se reutiliza
    la conexión de hana_pedidos.conectar(). NO se filtra por Estado NV: un faltante
    histórico puede estar en una NV hoy "Cerrado" que se entregó tarde.
  - Stock diario: SQL Server, dbo.Stock_Lote_Fecha (un snapshot por día, UMED=CJ, ya
    en cajas). Se reutiliza db.get_engine(). STOCK es texto con coma decimal → se
    convierte y suma en SQL con TRY_CONVERT.

Notas de datos:
  - STOCK y Cant NV/Cant Ent están AMBOS en cajas → comparación directa, sin conversión.
  - Día sin snapshot de stock: se usa el snapshot del día anterior más cercano y la fila
    se marca (estimado=True). "Día sin snapshot" = el día completo no existe en la tabla,
    NO un SKU sin filas (ese caso es stock 0 legítimo).
  - Se emiten solo filas con faltante > 0, incluyendo programado_cj de contexto.

Uso (prueba, read-only, no persiste nada):
    read -rs HANA_PWD && export HANA_PWD
    python3 faltantes.py [YYYY-MM-DD]      # default: ayer
"""

import os
import sys
import logging
from datetime import date, datetime, timedelta
from collections import defaultdict

from sqlalchemy import text, bindparam

from hana_pedidos import conectar, SP_NOMBRE, FUENTES
from db import get_engine

logger = logging.getLogger(__name__)

# Bodegas del proyecto cuyo stock se suma como disponible para despacho.
BODEGAS_PROYECTO = ["VESP01", "BSUR01", "VARA01"]

# Columnas del SP que usamos (por nombre, robusto a reordenamientos).
_COL_BD          = "BD"
_COL_NUM_NV      = "Num NV"
_COL_SKU         = "Codigo SAP"          # SIEMPRE Codigo SAP (no Codigo Flex)
_COL_DESC        = "Descripcion"
_COL_CANT_NV     = "Cant NV"
_COL_CANT_ENT    = "Cant Ent"
_COL_FECHA_PROG  = "Fecha Entrega NV"    # fecha comprometida de entrega
_COL_FECHA_ENT   = "Fecha Ent"           # fecha de cada entrega (despacho)
_COL_COD_CLI     = "Cod Cliente"
_COL_NOM_CLI     = "Nom Cliente"
_COLS_REQ = [_COL_BD, _COL_NUM_NV, _COL_SKU, _COL_CANT_NV, _COL_CANT_ENT,
             _COL_FECHA_PROG, _COL_FECHA_ENT]


def _as_date(v):
    """Normaliza un valor de fecha del SP (datetime|date|None) a date|None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    # fallback: texto YYYY-MM-DD o DD-MM-YYYY
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(v):
    """Convierte Cant NV/Ent a float (maneja None, Decimal, texto)."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return 0.0


# ── OV desde HANA ─────────────────────────────────────────────────────────────

def _leer_ov(conn):
    """
    Lee ambos schemas del SP y agrega por (BD, Num NV, SKU):
      programado  = max(Cant NV)   (se repite por fila de entrega)
      fecha_prog  = min(Fecha Entrega NV)  (defensivo; debería ser única por línea)
      entregas    = lista de (fecha_ent, cant_ent)
      descripcion = última vista
    Devuelve: dict[(bd,nv,sku)] -> {fecha_prog, programado, entregas, descripcion}
    """
    grupos = {}
    for schema, etiqueta in FUENTES:
        cur = conn.cursor()
        try:
            cur.execute(f'CALL "{schema}"."{SP_NOMBRE}"')
            cols = [d[0] for d in cur.description]
            faltan = [c for c in _COLS_REQ if c not in cols]
            if faltan:
                raise RuntimeError(f"{schema}.{SP_NOMBRE}: faltan columnas {faltan}")
            ix = {c: cols.index(c) for c in _COLS_REQ}
            ix_desc = cols.index(_COL_DESC) if _COL_DESC in cols else None
            ix_cod  = cols.index(_COL_COD_CLI) if _COL_COD_CLI in cols else None
            ix_nom  = cols.index(_COL_NOM_CLI) if _COL_NOM_CLI in cols else None
            n = 0
            for r in cur.fetchall():
                sku = str(r[ix[_COL_SKU]]).strip()
                if not sku:
                    continue
                clave = (etiqueta, r[ix[_COL_NUM_NV]], sku)
                g = grupos.get(clave)
                if g is None:
                    g = {"fecha_prog": _as_date(r[ix[_COL_FECHA_PROG]]),
                         "programado": _num(r[ix[_COL_CANT_NV]]),
                         "entregas": [],
                         "descripcion": (str(r[ix_desc]).strip() if ix_desc is not None and r[ix_desc] else ""),
                         "cod_cli": (str(r[ix_cod]).strip() if ix_cod is not None and r[ix_cod] else ""),
                         "nom_cli": (str(r[ix_nom]).strip() if ix_nom is not None and r[ix_nom] else "")}
                    grupos[clave] = g
                else:
                    fp = _as_date(r[ix[_COL_FECHA_PROG]])
                    if fp is not None and (g["fecha_prog"] is None or fp < g["fecha_prog"]):
                        g["fecha_prog"] = fp
                    cn = _num(r[ix[_COL_CANT_NV]])
                    if cn > g["programado"]:
                        g["programado"] = cn      # idénticos; max defensivo
                ent = _num(r[ix[_COL_CANT_ENT]])
                if ent:
                    g["entregas"].append((_as_date(r[ix[_COL_FECHA_ENT]]), ent))
                n += 1
            logger.info("OV %s (%s): %d filas leídas.", etiqueta, schema, n)
        finally:
            cur.close()
    return grupos


def _agregar_ov_por_sku_dia(grupos, desde, hasta):
    """
    Colapsa los grupos (bd,nv,sku) dentro de [desde, hasta] a DOS niveles:
      - tot[(sku,fecha)]              = {programado_total}  (para evaluar el quiebre,
                                         que es a nivel SKU/día: stock es pool común)
      - por_cli[(sku,fecha,cod_cli)]  = {no_entregado, nom_cli}  (desglose por cliente:
                                         cada cliente aporta SU no-entregado)
    Una NV es de un solo cliente → el cliente es constante dentro del grupo (bd,nv,sku).
    Devuelve: tot, por_cli, desc[sku]
    """
    tot     = defaultdict(lambda: {"programado": 0.0})
    por_cli = defaultdict(lambda: {"no_entregado": 0.0, "nom_cli": ""})
    desc = {}
    for (_bd, _nv, sku), g in grupos.items():
        fp = g["fecha_prog"]
        if fp is None or fp < desde or fp > hasta:
            continue
        entregado_a_fp = sum(c for (fe, c) in g["entregas"] if fe is not None and fe <= fp)
        no_ent = g["programado"] - entregado_a_fp
        if no_ent < 0:
            no_ent = 0.0
        tot[(sku, fp)]["programado"] += g["programado"]
        pc = por_cli[(sku, fp, g["cod_cli"])]
        pc["no_entregado"] += no_ent
        pc["nom_cli"] = g["nom_cli"]
        if g["descripcion"]:
            desc[sku] = g["descripcion"]
    return tot, por_cli, desc


# ── Stock desde SQL Server ────────────────────────────────────────────────────

def _leer_stock(engine, desde, hasta):
    """
    Carga el stock (cajas) de las bodegas del proyecto entre [desde, hasta], sumado
    por (fecha, SKU). STOCK es texto con coma decimal → REPLACE + TRY_CONVERT float.
    FECHA DESCARGA INFO es texto DD-MM-YYYY → TRY_CONVERT(date, ..., 105).
    Devuelve: stock_por_dia[fecha][sku] = cajas, y set de días con snapshot.
    """
    q = text("""
        SELECT
            TRY_CONVERT(date, LTRIM(RTRIM([FECHA DESCARGA INFO])), 105) AS f,
            LTRIM(RTRIM([CODIGO]))                                      AS sku,
            SUM(TRY_CONVERT(float, REPLACE([STOCK], ',', '.')))         AS stock_cj
        FROM dbo.Stock_Lote_Fecha
        WHERE [BODEGA] IN :bod
          AND TRY_CONVERT(date, LTRIM(RTRIM([FECHA DESCARGA INFO])), 105) BETWEEN :d1 AND :d2
        GROUP BY TRY_CONVERT(date, LTRIM(RTRIM([FECHA DESCARGA INFO])), 105), LTRIM(RTRIM([CODIGO]))
    """).bindparams(bindparam("bod", expanding=True))

    stock = defaultdict(dict)   # fecha -> {sku: cajas}
    dias = set()
    with engine.connect() as c:
        for f, sku, cj in c.execute(q, {"bod": BODEGAS_PROYECTO, "d1": desde, "d2": hasta}).fetchall():
            if f is None:
                continue
            fd = f if isinstance(f, date) else _as_date(f)
            stock[fd][str(sku).strip()] = float(cj or 0.0)
            dias.add(fd)
    return stock, dias


def _stock_del_dia(stock, dias_disponibles, dias_ordenados, sku, fecha):
    """
    Stock del SKU en `fecha`. Si el día completo no tiene snapshot, usa el día
    anterior más cercano disponible y marca estimado=True.
    Devuelve (stock_cj, estimado).
    """
    if fecha in dias_disponibles:
        return stock[fecha].get(sku, 0.0), False
    # día sin snapshot: buscar el anterior más cercano
    prev = None
    for d in dias_ordenados:          # ascendente
        if d <= fecha:
            prev = d
        else:
            break
    if prev is None:
        return 0.0, True
    return stock[prev].get(sku, 0.0), True


# ── Cálculo principal ─────────────────────────────────────────────────────────

def calcular_faltantes(desde, hasta, conn, engine):
    """
    Calcula faltantes por quiebre en [desde, hasta] (date, date).
    Devuelve lista de dicts con faltante_cj > 0:
      {fecha, sku, descripcion, stock_ini_cj, programado_cj, no_entregado_cj,
       faltante_cj, stock_estimado}
    """
    grupos = _leer_ov(conn)
    tot, por_cli, desc = _agregar_ov_por_sku_dia(grupos, desde, hasta)

    stock, dias_disp = _leer_stock(engine, desde, hasta)
    dias_ord = sorted(dias_disp)

    # 1) evaluar quiebre a nivel SKU/día (stock es pool común, no por cliente)
    quiebre = {}   # (sku,fecha) -> (hay_quiebre, stock_ini, estimado, programado)
    for (sku, fecha), a in tot.items():
        programado = a["programado"]
        if programado <= 0:
            continue
        stock_ini, estimado = _stock_del_dia(stock, dias_disp, dias_ord, sku, fecha)
        quiebre[(sku, fecha)] = (stock_ini < programado, stock_ini, estimado, programado)

    # 2) emitir una fila por (sku, fecha, cliente) cuando hay quiebre y ese cliente
    #    tiene no-entregado > 0. stock/programado son del SKU/día (se repiten como contexto).
    filas = []
    for (sku, fecha, cod_cli), pc in por_cli.items():
        q = quiebre.get((sku, fecha))
        if not q or not q[0]:
            continue
        no_ent = pc["no_entregado"]
        if no_ent <= 0:
            continue
        _, stock_ini, estimado, programado = q
        filas.append({
            "fecha":            fecha.isoformat(),
            "sku":              sku,
            "descripcion":      desc.get(sku, ""),
            "cod_cliente":      cod_cli,
            "nom_cliente":      pc["nom_cli"],
            "stock_ini_cj":     round(stock_ini, 2),
            "programado_cj":    round(programado, 2),
            "no_entregado_cj":  round(no_ent, 2),
            "faltante_cj":      round(no_ent, 2),
            "stock_estimado":   estimado,
        })
    filas.sort(key=lambda x: (x["fecha"], x["sku"], -x["faltante_cj"]))
    return filas


# ── Prueba standalone (un día) ────────────────────────────────────────────────

def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) > 1:
        d = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        d = date.today() - timedelta(days=1)   # ayer (día cerrado)

    print("=" * 70)
    print(f"Prueba faltantes por quiebre — día {d.isoformat()}  (read-only)")
    print("=" * 70)

    conn = conectar()
    try:
        engine = get_engine()
        filas = calcular_faltantes(d, d, conn, engine)
    finally:
        conn.close()

    if not filas:
        print("Sin faltantes ese día (o sin entregas programadas).")
    else:
        tot = sum(f["faltante_cj"] for f in filas)
        n_sku = len(set(f["sku"] for f in filas))
        print(f"Filas (sku x cliente): {len(filas)} | SKU distintos: {n_sku} | total faltante: {tot:,.0f} cj")
        print(f"{'SKU':<12} {'stock':>7} {'prog':>7} {'falta':>7} est  {'cliente':<26} descripción")
        for f in filas:
            print(f"{f['sku']:<12} {f['stock_ini_cj']:>7.0f} {f['programado_cj']:>7.0f} "
                  f"{f['faltante_cj']:>7.0f}  {'*' if f['stock_estimado'] else ' '}  "
                  f"{f['nom_cliente'][:26]:<26} {f['descripcion'][:28]}")
    print("=" * 70)
    print("OK — lectura pura, nada persistido.")
    print("=" * 70)


if __name__ == "__main__":
    _main()
