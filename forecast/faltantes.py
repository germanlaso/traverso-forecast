"""
faltantes.py — Motor de cálculo de "Faltantes por Quiebre"
Traverso S.A. · Informe de faltantes

Definición (cerrada con negocio):
  Faltante = lo que un cliente tenía programado recibir un día D y NO se le entregó,
  cuando esa no-entrega es atribuible a stock. Es un análisis EX-POST: no simulamos la
  asignación logística (eso lo hace el WMS); solo clasificamos, para cada no-entrega,
  si se debió a falta de stock o no.

  Por cada línea de OV (cliente) con no-entrega el día D:
    - programado_D  = Σ Cant NV de las líneas de ese cliente/SKU con Fecha Entrega NV = D.
    - entregado_D   = Σ Cant Ent (TODAS las entregas, incl. tardías → opción 2: una
                      entrega posterior reduce el faltante; mide quiebre NO resuelto).
    - no_entregado_D= max(0, programado_D − entregado_D).   [solo se analiza si > 0]

  Stock (cajas) del SKU el día D, en las bodegas del proyecto {VESP01,BSUR01,VARA01}:
    - stock_total       = Σ lotes NO vencidos (vcto >= D, o sin vcto).
    - stock_apto        = Σ lotes con VU restante >= umbral de (cliente, SKU):
                            · Si el par está en la tabla de logística (mrp_vu_cliente_sku):
                              VU restante >= mínimo en DÍAS absolutos de esa tabla.
                            · Si no: VU restante >= 50% de la VU total (MesDuracion × 30).

  CAUSA de la no-entrega (columna del informe):
    - stock_total < programado                         → 'sin_stock'
        (no alcanzaba ni contando todo el stock: problema de producción/abastecimiento)
    - stock_total >= programado > stock_apto           → 'vu_insuficiente'
        (había producto, pero no con la frescura requerida: problema de rotación)
    - stock_apto >= programado                         → NO es faltante por stock (se ignora)

Fuentes (todas ya usadas por el sistema):
  - OV/entregas: SAP HANA, SP EPV_Faltantes_NV_FC_V4 (schemas TR+MO), vía hana_pedidos.
  - Stock diario por lote (con FECHA VCTO): SQL Server, dbo.Stock_Lote_Fecha.
  - Vida útil por SKU (meses): SQL Server, dbo.MaestraArticuloV2 (solo PT='Y').
  - VU mínima por cliente×SKU (días): Postgres, mrp_vu_cliente_sku (tabla de logística).

Notas de datos:
  - STOCK y Cant NV/Ent están en cajas → comparación directa, sin conversión.
  - Día sin snapshot de stock: se usa el snapshot anterior más cercano (estimado=True).
  - Exclusiones: SKU contables (SKU_EXCLUIDOS) y unitarios (sin "x" en la descripción).
  - VU=0 o SKU sin VU en maestro: no se filtra por VU (solo se descartan vencidos);
    su stock_apto == stock_total → nunca dará 'vu_insuficiente'.

Uso:
    read -rs HANA_PWD && export HANA_PWD
    python3 faltantes.py [YYYY-MM-DD]
    python3 faltantes.py --desde D1 --hasta D2 [--persistir]
    python3 faltantes.py --ventana 14 --persistir
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

BODEGAS_PROYECTO = ["VESP01", "BSUR01", "VARA01"]

# (27-07-2026) Consolidación de stock Traverso + Montaner.
# Produce siempre Traverso, pero cuando la venta se hace por Montaner el producto
# se transfiere a una bodega de Montaner: misma bodega física y mismo nombre, pero
# registrada en OTRA base de datos. Las OV ya venían consolidadas (hana_pedidos lee
# SBO_TRAVERSO y SBO_MONTANER), el stock no -> faltantes falsos en los SKU Montaner.
# Ej. 121011175 al 27-07: el informe veía 12 cj; el stock real era 1.026 cj.
#
# Vacío -> sólo Traverso. Default DBMontanerV2 (no requiere tocar docker-compose).
SQL_DB_TRAVERSO = os.environ.get("SQL_DATABASE", "DBTraversoV2").strip()
SQL_DB_MONTANER = os.environ.get("SQL_DB_MONTANER", "DBMontanerV2").strip()
# SKU excluidos del informe: contables (arriendo, reciclaje, recup. gastos)
# y otros no medibles como faltante por definición de negocio.
SKU_EXCLUIDOS = {
    "1000000000", "1061000000", "1061000001",   # contables
    "500170200", "141041660", "141041650",       # excluidos por logística/negocio
}

# Clientes excluidos del informe: sus OV NO cuentan como faltante.
# Motivo: corresponden a "castigo a transportistas por pérdida de producto", no a
# una entrega física, por lo que contarlas sería un falso positivo. Los códigos
# deben coincidir con el cod_cliente que persiste el motor (formato SAP: guion, DV
# y 'C' final). Se comparan normalizados (.strip().upper()) para evitar un no-match
# silencioso si HANA devuelve el código con otro formato.
# TODO: a futuro administrar esta lista desde el dashboard (tabla mrp_clientes_excluidos),
#       reemplazando esta constante.
CLIENTES_EXCLUIDOS = {
    "76383478-6C",   # TRANSPORTE SUPERTRANS LIMITADA
    "76503787-5C",   # TRANSPORTES ANTILLANCA SPA
}

# Umbral de vida útil para despacho:
#  - Si el par (cliente, SKU) está en la tabla de logística (mrp_vu_cliente_sku),
#    se usa su mínimo en DÍAS absolutos.
#  - Si no está, se usa PCT_VU_DEFAULT de la VU total del maestro (MesDuracion×30).
PCT_VU_DEFAULT = 0.50
DIAS_POR_MES = 30


def _as_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(v):
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return 0.0


def _es_unitario(descripcion):
    d = (descripcion or "")
    return ("x" not in d) and ("X" not in d)


# ── Canal por cliente ─────────────────────────────────────────────────────────

def _umbral_dias(cod_cliente, sku, meses_vu, vu_tabla):
    """Días mínimos de VU restante para que un lote sea apto para (cliente, sku).
      - Si (cliente, sku) está en la tabla de logística → su mínimo en días absolutos.
      - Si no → PCT_VU_DEFAULT × VU_total del maestro (meses_vu × 30).
    Devuelve None si no hay forma de fijar umbral (SKU sin VU y sin fila en tabla):
    en ese caso no se filtra por VU (apto = total, solo se descartan vencidos)."""
    md = vu_tabla.get((cod_cliente, sku))
    if md is not None:
        return md
    vu_total = (meses_vu or 0) * DIAS_POR_MES
    return PCT_VU_DEFAULT * vu_total if vu_total > 0 else None


# ── Vida útil por SKU ─────────────────────────────────────────────────────────

def _leer_vida_util(engine):
    """{sku: meses_vu} de PT='Y' (mayor MesDuracion si hay varias Bd)."""
    vu = {}
    with engine.connect() as c:
        res = c.execute(text("""
            SELECT LTRIM(RTRIM([ItemCode])) AS sku, [MesDuracion] AS meses
            FROM dbo.MaestraArticuloV2 WHERE [PT] = 'Y'
        """))
        for sku, meses in res.fetchall():
            s = str(sku).strip()
            m = int(meses) if meses is not None else 0
            if s not in vu or m > vu[s]:
                vu[s] = m
    logger.info("Vida útil: %d SKU PT.", len(vu))
    return vu


# ── Stock por lote ────────────────────────────────────────────────────────────

def _leer_stock_lotes(engine, desde, hasta):
    """lotes_por_dia[fecha][sku] = [(stock_cj, fecha_vcto|None)], y set de días."""
    # Un SELECT por empresa, unidos con UNION ALL. NO se deduplica: el mismo lote
    # se reparte entre ambas BD con cantidades distintas (no es una copia), así que
    # las filas se acumulan y se suman aguas abajo en lotes[fecha][sku].
    #
    # La consolidación es POR FECHA de forma natural: Montaner sólo aporta filas en
    # los días que tenga snapshot (su tabla existe desde el 27-07-2026), de modo que
    # los recálculos hacia atrás dan exactamente lo mismo que antes.
    #
    # REPLACE([STOCK], ',', '.') funciona con los dos formatos: Traverso escribe
    # "12,000000" (coma decimal) y Montaner "913.000000" (punto), que queda intacto.
    _sel = """
        SELECT
            TRY_CONVERT(date, LTRIM(RTRIM([FECHA DESCARGA INFO])), 105) AS f,
            LTRIM(RTRIM([CODIGO]))                                      AS sku,
            TRY_CONVERT(float, REPLACE([STOCK], ',', '.'))              AS stock_cj,
            TRY_CONVERT(date, LTRIM(RTRIM([FECHA VCTO])), 105)          AS vcto
        FROM {bd}.dbo.Stock_Lote_Fecha
        WHERE [BODEGA] IN :bod
          AND TRY_CONVERT(date, LTRIM(RTRIM([FECHA DESCARGA INFO])), 105) BETWEEN :d1 AND :d2
    """
    _bds = [SQL_DB_TRAVERSO] + ([SQL_DB_MONTANER] if SQL_DB_MONTANER else [])
    q = text(" UNION ALL ".join(_sel.format(bd=b) for b in _bds)) \
        .bindparams(bindparam("bod", expanding=True))

    lotes = defaultdict(lambda: defaultdict(list))
    dias = set()
    n_filas = 0
    with engine.connect() as c:
        for f, sku, cj, vcto in c.execute(
                q, {"bod": BODEGAS_PROYECTO, "d1": desde, "d2": hasta}).fetchall():
            if f is None:
                continue
            fd = f if isinstance(f, date) else _as_date(f)
            vd = vcto if (vcto is None or isinstance(vcto, date)) else _as_date(vcto)
            lotes[fd][str(sku).strip()].append((float(cj or 0.0), vd))
            dias.add(fd)
            n_filas += 1
    logger.info("Stock por lote: %d filas de %s (%d días).",
                n_filas, " + ".join(_bds), len(dias))
    return lotes, dias


def _lotes_del_dia(lotes, dias_disp, dias_ord, sku, fecha):
    if fecha in dias_disp:
        return lotes[fecha].get(sku, []), False
    prev = None
    for d in dias_ord:
        if d <= fecha:
            prev = d
        else:
            break
    if prev is None:
        return [], True
    return lotes[prev].get(sku, []), True


def _stock_total_y_apto(lotes_sku, fecha, umbral_dias):
    """(stock_total_no_vencido, stock_apto). umbral_dias = VU restante mínima para ser
    apto; si None → no se filtra por VU (apto = total). Vencidos nunca cuentan."""
    total = 0.0
    apto = 0.0
    for cj, vcto in lotes_sku:
        if vcto is None:
            total += cj
            apto += cj
            continue
        restante = (vcto - fecha).days
        if restante < 0:
            continue
        total += cj
        if umbral_dias is None or restante >= umbral_dias:
            apto += cj
    return total, apto


# ── OV desde HANA ─────────────────────────────────────────────────────────────

_COL = {
    "bd": "BD", "nv": "Num NV", "sku": "Codigo SAP", "desc": "Descripcion",
    "cant_nv": "Cant NV", "cant_ent": "Cant Ent",
    "fprog": "Fecha Entrega NV", "fent": "Fecha Ent",
    "cod_cli": "Cod Cliente", "nom_cli": "Nom Cliente",
}
_COLS_REQ = ["bd", "nv", "sku", "cant_nv", "cant_ent", "fprog", "fent"]


def _leer_ov(conn):
    grupos = {}
    for schema, etiqueta in FUENTES:
        cur = conn.cursor()
        try:
            cur.execute(f'CALL "{schema}"."{SP_NOMBRE}"')
            cols = [d[0] for d in cur.description]
            faltan = [_COL[k] for k in _COLS_REQ if _COL[k] not in cols]
            if faltan:
                raise RuntimeError(f"{schema}.{SP_NOMBRE}: faltan columnas {faltan}")
            ix = {k: cols.index(_COL[k]) for k in _COL if _COL[k] in cols}
            n = 0
            for r in cur.fetchall():
                sku = str(r[ix["sku"]]).strip()
                if not sku:
                    continue
                clave = (etiqueta, r[ix["nv"]], sku)
                g = grupos.get(clave)
                if g is None:
                    g = {"fecha_prog": _as_date(r[ix["fprog"]]),
                         "programado": _num(r[ix["cant_nv"]]),
                         "entregas": [],
                         "descripcion": (str(r[ix["desc"]]).strip() if "desc" in ix and r[ix["desc"]] else ""),
                         "cod_cli": (str(r[ix["cod_cli"]]).strip() if "cod_cli" in ix and r[ix["cod_cli"]] else ""),
                         "nom_cli": (str(r[ix["nom_cli"]]).strip() if "nom_cli" in ix and r[ix["nom_cli"]] else "")}
                    grupos[clave] = g
                else:
                    fp = _as_date(r[ix["fprog"]])
                    if fp is not None and (g["fecha_prog"] is None or fp < g["fecha_prog"]):
                        g["fecha_prog"] = fp
                    cn = _num(r[ix["cant_nv"]])
                    if cn > g["programado"]:
                        g["programado"] = cn
                ent = _num(r[ix["cant_ent"]])
                if ent:
                    g["entregas"].append((_as_date(r[ix["fent"]]), ent))
                n += 1
            logger.info("OV %s (%s): %d filas leídas.", etiqueta, schema, n)
        finally:
            cur.close()
    return grupos


def _agregar_ov(grupos, desde, hasta):
    por_cli = defaultdict(lambda: {"programado": 0.0, "no_entregado": 0.0})
    prog_sd = defaultdict(float)
    desc = {}
    nom = {}
    for (_bd, _nv, sku), g in grupos.items():
        fp = g["fecha_prog"]
        if fp is None or fp < desde or fp > hasta:
            continue
        if sku in SKU_EXCLUIDOS or _es_unitario(g["descripcion"]):
            continue
        if g["cod_cli"].strip().upper() in CLIENTES_EXCLUIDOS:
            continue  # castigo a transportistas por pérdida de producto (no es entrega física)
        entregado_total = sum(c for (_fe, c) in g["entregas"])
        no_ent = g["programado"] - entregado_total
        if no_ent < 0:
            no_ent = 0.0
        cc = g["cod_cli"]
        a = por_cli[(sku, fp, cc)]
        a["programado"] += g["programado"]
        a["no_entregado"] += no_ent
        prog_sd[(sku, fp)] += g["programado"]
        if g["descripcion"]:
            desc[sku] = g["descripcion"]
        if g["nom_cli"]:
            nom[cc] = g["nom_cli"]
    return por_cli, prog_sd, desc, nom


# ── Cálculo principal ─────────────────────────────────────────────────────────

def calcular_faltantes(desde, hasta, conn, engine):
    grupos = _leer_ov(conn)
    por_cli, prog_sd, desc, nom = _agregar_ov(grupos, desde, hasta)

    vu = _leer_vida_util(engine)
    from db_mrp import get_vu_cliente_sku
    vu_tabla = get_vu_cliente_sku()
    logger.info("VU cliente×SKU (logística): %d pares.", len(vu_tabla))
    lotes, dias_disp = _leer_stock_lotes(engine, desde, hasta)
    dias_ord = sorted(dias_disp)

    filas = []
    for (sku, fecha, cod_cli), a in por_cli.items():
        no_ent = a["no_entregado"]
        if no_ent <= 0:
            continue
        programado_sd = prog_sd[(sku, fecha)]
        umbral = _umbral_dias(cod_cli, sku, vu.get(sku, 0), vu_tabla)
        lotes_sku, estimado = _lotes_del_dia(lotes, dias_disp, dias_ord, sku, fecha)
        stock_total, stock_apto = _stock_total_y_apto(lotes_sku, fecha, umbral)

        if stock_total < programado_sd:
            causa = "sin_stock"
        elif stock_apto < programado_sd:
            causa = "vu_insuficiente"
        else:
            continue

        filas.append({
            "fecha":           fecha.isoformat(),
            "sku":             sku,
            "descripcion":     desc.get(sku, ""),
            "cod_cliente":     cod_cli,
            "nom_cliente":     nom.get(cod_cli, ""),
            "stock_ini_cj":    round(stock_total, 2),
            "programado_cj":   round(programado_sd, 2),
            "no_entregado_cj": round(no_ent, 2),
            "faltante_cj":     round(no_ent, 2),
            "stock_estimado":  estimado,
            "causa":           causa,
        })
    filas.sort(key=lambda x: (x["fecha"], x["sku"], -x["faltante_cj"]))
    return filas


# ── Persistencia y ejecución ──────────────────────────────────────────────────

def persistir(filas):
    from db_mrp import upsert_faltantes
    return upsert_faltantes(filas)


def ejecutar(desde, hasta, persistir_bd=False):
    conn = conectar()
    try:
        engine = get_engine()
        filas = calcular_faltantes(desde, hasta, conn, engine)
    finally:
        conn.close()
    if persistir_bd and filas:
        n = persistir(filas)
        logger.info("Persistidas %d filas en mrp_faltantes.", n)
    return filas


def _parse_args(argv):
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("fecha", nargs="?", default=None)
    p.add_argument("--desde"); p.add_argument("--hasta")
    p.add_argument("--ventana", type=int)
    p.add_argument("--persistir", action="store_true")
    a = p.parse_args(argv)
    ayer = date.today() - timedelta(days=1)
    if a.ventana:
        return ayer - timedelta(days=a.ventana - 1), ayer, a.persistir
    if a.desde or a.hasta:
        d1 = datetime.strptime(a.desde, "%Y-%m-%d").date() if a.desde else ayer
        d2 = datetime.strptime(a.hasta, "%Y-%m-%d").date() if a.hasta else ayer
        return d1, d2, a.persistir
    if a.fecha:
        d = datetime.strptime(a.fecha, "%Y-%m-%d").date()
        return d, d, a.persistir
    return ayer, ayer, a.persistir


def _main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    desde, hasta, persistir_bd = _parse_args(sys.argv[1:])

    print("=" * 78)
    modo = "PERSISTIENDO" if persistir_bd else "read-only (prueba)"
    print(f"Faltantes por quiebre — {desde.isoformat()} a {hasta.isoformat()}  [{modo}]")
    print("=" * 78)

    filas = ejecutar(desde, hasta, persistir_bd=persistir_bd)

    if not filas:
        print("Sin faltantes en el rango (o sin entregas programadas).")
    else:
        tot = sum(f["faltante_cj"] for f in filas)
        n_sku = len(set(f["sku"] for f in filas))
        n_dias = len(set(f["fecha"] for f in filas))
        por_causa = defaultdict(float)
        for f in filas:
            por_causa[f["causa"]] += f["faltante_cj"]
        print(f"Filas: {len(filas)} | días: {n_dias} | SKU: {n_sku} | total: {tot:,.0f} cj")
        print("  por causa: " + " | ".join(f"{k}={v:,.0f} cj" for k, v in por_causa.items()))
        if desde == hasta:
            print(f"{'SKU':<12}{'stock':>7}{'prog':>7}{'falta':>7} est {'causa':<16}{'cliente':<24}desc")
            for f in filas:
                print(f"{f['sku']:<12}{f['stock_ini_cj']:>7.0f}{f['programado_cj']:>7.0f}"
                      f"{f['faltante_cj']:>7.0f}  {'*' if f['stock_estimado'] else ' '} "
                      f"{f['causa']:<16}{f['nom_cliente'][:24]:<24}{f['descripcion'][:24]}")
        else:
            por_dia = defaultdict(float)
            for f in filas:
                por_dia[f["fecha"]] += f["faltante_cj"]
            for fch in sorted(por_dia):
                print(f"  {fch}: {por_dia[fch]:,.0f} cj")
    print("=" * 78)
    print("Persistido en mrp_faltantes." if persistir_bd else "Lectura pura, nada persistido.")
    print("=" * 78)


if __name__ == "__main__":
    _main()
