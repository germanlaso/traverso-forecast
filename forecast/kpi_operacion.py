"""
Motor de KPIs de la operación semanal por línea — Módulo Evaluación de la Operación.

Contrato de datos verificado con dato (04-11-2026):
  - mrp_of_sap viene en CAJAS (mediana plan*upc/batch_min_u = 1.19 vs plan/batch_min_u = 0.10;
    OF 50180: 2000 cj plan / 2114 cj prod).
  - cant_producida se REPITE en las filas de lote de un mismo TR (35 TR multilote, 35 repetidos)
    -> MAX por (OF, TR) y recién ahí SUM. Sumar por fila duplica.
  - cant_planificada se repite por fila -> MAX por OF.
  - mrp_of_sap.linea vacía en el 100% de las OF (8 semanas) -> línea atribuida vía mrp_sku_lineas
    (235 SKU 1 línea, 13 SKU 2 líneas -> 'ambigua', se usa la preferida y se informa).
  - ~120 SKU producidos no están en el catálogo -> mrp_operacion_sku_linea (tabla propia del
    módulo, no la lee el solver). Solo clase LINEA entra a KPIs; IMPORTADO_ETIQUETADO
    (Kikkoman/Melitta), MAQUILA (mayonesas salvo 300x8), ARMADO, SEMIELABORADO y POR_CLASIFICAR se informan aparte y NO se
    suman a los totales (mezclarían bolsas/unidades con cajas de PT).
  - Granel (es_granel) fuera de los KPIs de línea.
  - Plan app = última versión por numero_of en mrp_aprobaciones con estado APROBADA/MODIFICADA,
    cantidad en cajas (cantidad_real_cj; nunca cantidad_real_u, ver incidente upc=1).

Todo se mide en horas-equivalentes: h_eq = cj * u_por_caja / (velocidad_u_hr * factor_velocidad).
Fail-loud: lo que no se puede medir va a 'advertencias', nunca se reporta como 0.

Uso:
  GET /operacion/semana?desde=YYYY-MM-DD   (default: semana completa anterior, lunes a domingo)
  python3 kpi_operacion.py --desde 2026-10-26 [--json]
"""
import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, Query

from db_mrp import engine as _engine

router = APIRouter(prefix="/operacion", tags=["operacion"])

UMBRAL_OCUPACION_ALTA = 1.05    # ocupación real sobre esto: capacidad nominal probablemente subparametrizada
ESTADOS_PROGRAMADO_APP = ("APROBADA", "MODIFICADA")

# Categoría desde la tabla propia del módulo (mrp_lineas.area mezcla planta/línea y no sirve).
SQL_LINEAS = (
    "SELECT l.codigo, l.nombre, COALESCE(ol.categoria, 'SIN CATEGORÍA') AS categoria, "
    "       l.turnos_dia, l.horas_turno, l.dias_semana, l.velocidad_u_hr "
    "FROM mrp_lineas l LEFT JOIN mrp_operacion_lineas ol ON ol.codigo = l.codigo "
    "WHERE l.activa"
)
SQL_SKU_LINEAS = "SELECT sku, linea, preferida, factor_velocidad FROM mrp_sku_lineas"
SQL_SKU_PARAMS = "SELECT sku, u_por_caja FROM mrp_sku_params"
SQL_SKU_OVERRIDE = (
    "SELECT sku, clase, linea, u_por_caja, factor_velocidad, validado "
    "FROM mrp_operacion_sku_linea"
)
CLASES_FUERA = ("IMPORTADO_ETIQUETADO", "MAQUILA", "ARMADO", "SEMIELABORADO", "POR_CLASIFICAR")

# Producción real: MAX por (OF, TR) porque cant_producida se repite entre lotes del mismo TR.
SQL_TR = """
SELECT sku, fecha_tr, SUM(prod_tr) AS cj FROM (
    SELECT orden_produccion, terminal_report, sku, fecha_tr, MAX(cant_producida) AS prod_tr
    FROM mrp_of_sap
    WHERE terminal_report <> '' AND NOT es_granel
      AND fecha_tr BETWEEN :desde AND :hasta
    GROUP BY 1, 2, 3, 4
) t
GROUP BY 1, 2
"""

# Programado SAP: la OF completa cae en la semana de su centro del tramo planificado.
SQL_PROG_SAP = """
SELECT sku, SUM(plan) AS cj, COUNT(*) AS n_of FROM (
    SELECT orden_produccion, sku, MAX(cant_planificada) AS plan,
           MIN(fecha_ini_planif) AS ini, MAX(COALESCE(fecha_fin_planif, fecha_ini_planif)) AS fin
    FROM mrp_of_sap
    WHERE NOT es_granel AND fecha_ini_planif IS NOT NULL
    GROUP BY 1, 2
) o
WHERE ini + ((fin - ini) / 2) BETWEEN :desde AND :hasta
GROUP BY 1
"""

# Programado app: última versión de cada OF; cuenta si quedó APROBADA o MODIFICADA.
SQL_PROG_APP = """
SELECT o.sku, o.linea, SUM(COALESCE(a.cantidad_real_cj, o.cantidad_sugerida_cj)) AS cj,
       COUNT(*) AS n_of
FROM (
    SELECT DISTINCT ON (numero_of) numero_of, estado, cantidad_real_cj, fecha_lanzamiento_real
    FROM mrp_aprobaciones
    ORDER BY numero_of, version DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
) a
JOIN mrp_ordenes o ON o.numero_of = a.numero_of
WHERE a.estado IN :estados
  AND COALESCE(a.fecha_lanzamiento_real, o.fecha_lanzamiento) BETWEEN :desde AND :hasta
GROUP BY 1, 2
"""

SQL_EVENTOS = """
SELECT e.linea, t.categoria, SUM(COALESCE(e.duracion_min, 0)) AS minutos, COUNT(*) AS n
FROM mrp_eventos_linea e JOIN mrp_eventos_tipos t ON t.codigo = e.tipo
WHERE NOT e.anulado AND e.fecha BETWEEN :desde AND :hasta
GROUP BY 1, 2
"""

CATEGORIA_A_CAMPO = {
    "PARADA_PLANIFICADA": "parada_plan_h",
    "PARADA_NO_PLANIFICADA": "parada_noplan_h",
    "SIN_PROGRAMA": "sin_programa_h",
    "INFORMATIVO": None,
}


def semana_default(hoy: Optional[date] = None) -> date:
    """Lunes de la última semana completa (lunes a domingo)."""
    hoy = hoy or date.today()
    return hoy - timedelta(days=hoy.weekday()) - timedelta(days=7)


def _ratio(n, d):
    return round(n / d, 4) if d else None


def _r2(x):
    return round(x, 2)


def dias_laborables(desde: date, hasta: date, dias_semana: int) -> int:
    """Días del rango con weekday < dias_semana (5 = lunes a viernes). Feriados NO se descuentan."""
    n, d = 0, desde
    while d <= hasta:
        if d.weekday() < (dias_semana or 0):
            n += 1
        d += timedelta(days=1)
    return n


def calcular_semana(desde: date) -> dict:
    return calcular_periodo(desde, desde + timedelta(days=6))


def calcular_periodo(desde: date, hasta: date) -> dict:
    p = {"desde": desde, "hasta": hasta}

    q_app = sa.text(SQL_PROG_APP).bindparams(sa.bindparam("estados", expanding=True))
    with _engine.connect() as c:
        lineas = {r.codigo: r for r in c.execute(sa.text(SQL_LINEAS))}
        sku_lin = defaultdict(list)
        for r in c.execute(sa.text(SQL_SKU_LINEAS)):
            sku_lin[r.sku].append(r)
        upc = {r.sku: r.u_por_caja for r in c.execute(sa.text(SQL_SKU_PARAMS))}
        override = {r.sku: r for r in c.execute(sa.text(SQL_SKU_OVERRIDE))}
        filas_tr = list(c.execute(sa.text(SQL_TR), p))
        filas_sap = list(c.execute(sa.text(SQL_PROG_SAP), p))
        filas_app = list(c.execute(q_app, {**p, "estados": list(ESTADOS_PROGRAMADO_APP)}))
        filas_ev = list(c.execute(sa.text(SQL_EVENTOS), p))

    adv = {k: set() for k in (
        "sku_sin_clasificar", "sku_por_clasificar", "sku_linea_ambigua", "sku_sin_upc",
        "linea_inactiva_o_desconocida", "velocidad_invalida", "evento_linea_desconocida",
        "sku_linea_sin_validar",
    )}

    def clase_de(sku):
        """LINEA si está en el catálogo o clasificado LINEA; si no, su clase fuera de línea."""
        if sku in sku_lin:
            return "LINEA"
        ov = override.get(sku)
        if ov is None:
            adv["sku_sin_clasificar"].add(sku)   # SKU nuevo: re-ejecutar migrate_operacion_sku_linea.sql
            return "POR_CLASIFICAR"
        if ov.clase == "POR_CLASIFICAR":
            adv["sku_por_clasificar"].add(sku)
        if ov.clase == "LINEA" and not ov.validado:
            adv["sku_linea_sin_validar"].add(sku)
        return ov.clase

    def atribuir(sku):
        opciones = sku_lin.get(sku, [])
        if not opciones:
            ov = override.get(sku)
            return ov.linea if ov is not None and ov.clase == "LINEA" else None
        if len(opciones) > 1:
            adv["sku_linea_ambigua"].add(sku)
            pref = [o for o in opciones if o.preferida]
            return (pref or opciones)[0].linea
        return opciones[0].linea

    def h_eq(sku, linea, cj):
        u = upc.get(sku) if sku in upc else getattr(override.get(sku), "u_por_caja", None)
        if u is None or float(u) <= 0:
            adv["sku_sin_upc"].add(sku)
            return None
        L = lineas.get(linea)
        if L is None:
            adv["linea_inactiva_o_desconocida"].add(linea)
            return None
        f = next((o.factor_velocidad for o in sku_lin.get(sku, []) if o.linea == linea), None)
        if f is None:
            ov = override.get(sku)
            f = ov.factor_velocidad if ov is not None and ov.linea == linea else 1.0
        vel = float(L.velocidad_u_hr or 0) * float(f or 0)
        if vel <= 0:
            adv["velocidad_invalida"].add(sku + "@" + linea)
            return None
        return float(cj) * float(u) / vel

    acc = {cod: defaultdict(float) for cod in lineas}
    diario = {cod: defaultdict(float) for cod in lineas}
    por_sku = defaultdict(lambda: defaultdict(float))
    linea_sku = {}
    clase_sku = {}
    fuera = {k: defaultdict(float) for k in CLASES_FUERA}

    def es_linea(sku, campo_cj, cj):
        """Registra la clase; si es fuera de línea acumula aparte y devuelve False."""
        cl = clase_sku.setdefault(sku, clase_de(sku))
        if cl == "LINEA":
            return True
        fuera[cl][campo_cj] += float(cj or 0)
        return False

    def sumar(campo_h, campo_cj, sku, linea, cj, fecha=None):
        if linea is None:
            return
        h = h_eq(sku, linea, cj)
        if linea not in acc:
            return
        acc[linea][campo_cj] += float(cj)
        if h is None:
            acc[linea]["cj_sin_medir"] += float(cj)
            return
        acc[linea][campo_h] += h
        if fecha is not None:
            diario[linea][fecha.isoformat()] += h

    for r in filas_tr:
        if not es_linea(r.sku, "cj_real", r.cj):
            por_sku[r.sku]["cj_real"] += float(r.cj)
            continue
        lin = atribuir(r.sku)
        linea_sku[r.sku] = lin
        por_sku[r.sku]["cj_real"] += float(r.cj)
        sumar("heq_real", "cj_real", r.sku, lin, r.cj, r.fecha_tr)

    for r in filas_sap:
        if not es_linea(r.sku, "cj_prog_sap", r.cj):
            por_sku[r.sku]["cj_prog_sap"] += float(r.cj)
            continue
        lin = atribuir(r.sku)
        linea_sku[r.sku] = lin
        por_sku[r.sku]["cj_prog_sap"] += float(r.cj)
        por_sku[r.sku]["n_of_sap"] += r.n_of
        sumar("heq_prog_sap", "cj_prog_sap", r.sku, lin, r.cj)

    for r in filas_app:
        if not es_linea(r.sku, "cj_prog_app", r.cj):
            por_sku[r.sku]["cj_prog_app"] += float(r.cj or 0)
            continue
        lin = r.linea or atribuir(r.sku)
        linea_sku.setdefault(r.sku, lin)
        por_sku[r.sku]["cj_prog_app"] += float(r.cj or 0)
        por_sku[r.sku]["n_of_app"] += r.n_of
        sumar("heq_prog_app", "cj_prog_app", r.sku, lin, r.cj or 0)

    for r in filas_ev:
        if r.linea not in acc:
            adv["evento_linea_desconocida"].add(r.linea)
            continue
        acc[r.linea]["n_eventos"] += r.n
        campo = CATEGORIA_A_CAMPO.get(r.categoria)
        if campo:
            acc[r.linea][campo] += float(r.minutos) / 60.0

    # --- KPIs por línea ---
    res_lineas = []
    for cod in sorted(lineas):
        L, a = lineas[cod], acc[cod]
        nominal = float((L.turnos_dia or 0) * (L.horas_turno or 0)
                        * dias_laborables(desde, hasta, L.dias_semana))
        pp, pn, sp = a["parada_plan_h"], a["parada_noplan_h"], a["sin_programa_h"]
        disponible = max(nominal - pp, 0.0)
        cap_real = max(disponible - pn, 0.0)
        operada = max(cap_real - sp, 0.0)
        heq, heq_sap, heq_app = a["heq_real"], a["heq_prog_sap"], a["heq_prog_app"]
        no_expl = max(nominal - heq - pp - pn - sp, 0.0)
        con_bitacora = a["n_eventos"] > 0
        ocup_sap = _ratio(heq_sap, nominal)
        ocupacion_real = _ratio(heq, nominal)

        alertas = []
        if ocupacion_real is not None and ocupacion_real > UMBRAL_OCUPACION_ALTA:
            alertas.append("Producción sobre capacidad nominal: revisar turnos_dia, dias_semana "
                           "o velocidad_u_hr de la línea (el solver ve menos capacidad que la real).")
        if heq == 0 and heq_sap > 0:
            alertas.append("Programa SAP en la semana sin producción registrada (TR).")
        if heq == 0 and heq_sap == 0 and not con_bitacora:
            alertas.append("Sin programa, sin producción y sin eventos registrados.")
        if a["cj_sin_medir"] > 0:
            alertas.append("Hay cajas sin convertir a horas (ver advertencias).")

        res_lineas.append({
            "linea": cod,
            "nombre": L.nombre,
            "categoria": L.categoria,
            "con_bitacora": con_bitacora,
            "n_eventos": int(a["n_eventos"]),
            "horas": {
                "nominal": _r2(nominal),
                "parada_planificada": _r2(pp),
                "parada_no_planificada": _r2(pn),
                "sin_programa": _r2(sp),
                "disponible": _r2(disponible),
                "capacidad_real": _r2(cap_real),
                "operada": _r2(operada),
                "heq_producidas": _r2(heq),
                "heq_programadas_sap": _r2(heq_sap),
                "heq_programadas_app": _r2(heq_app),
                "no_explicadas": _r2(no_expl),
            },
            "cajas": {
                "real": _r2(a["cj_real"]),
                "programado_sap": _r2(a["cj_prog_sap"]),
                "programado_app": _r2(a["cj_prog_app"]),
                "sin_medir": _r2(a["cj_sin_medir"]),
            },
            "kpi": {
                "ocupacion_real": ocupacion_real,
                "eficiencia": _ratio(heq, operada) if con_bitacora else None,
                "ocupacion_programada_sap": ocup_sap,
                "ocupacion_programada_app": _ratio(heq_app, nominal),
                "capacidad_ociosa": round(max(1 - ocup_sap, 0), 4) if ocup_sap is not None else None,
                "capacidad_real_vs_teorica": _ratio(cap_real, nominal) if con_bitacora else None,
                "cumplimiento_vs_sap": _ratio(heq, heq_sap),
            },
            "brecha_nominal_pct": {
                "sin_programa": _ratio(sp, nominal),
                "paradas": _ratio(pp + pn, nominal),
                "no_explicada": _ratio(no_expl, nominal),
            },
            "produccion_diaria_heq": {k: _r2(v) for k, v in sorted(diario[cod].items())},
            "alertas": alertas,
        })

    # --- Conciliación app vs SAP vs TR por SKU ---
    conciliacion = []
    tot = defaultdict(float)
    for sku in sorted(por_sku):
        v = por_sku[sku]
        app, sap, real = v["cj_prog_app"], v["cj_prog_sap"], v["cj_real"]
        if sap > 0 and app > 0:
            cat = "ambos"
        elif sap > 0:
            cat = "solo_sap"
        elif app > 0:
            cat = "solo_app"
        else:
            cat = "sin_programa"   # producido sin OF con centro de tramo en la semana
        clase = clase_sku.get(sku, "LINEA")
        conciliacion.append({
            "sku": sku,
            "clase": clase,
            "linea_atribuida": linea_sku.get(sku) if clase == "LINEA" else None,
            "categoria": cat,
            "cj_programado_app": _r2(app),
            "cj_programado_sap": _r2(sap),
            "cj_real": _r2(real),
            "desvio_sap_vs_app_cj": _r2(sap - app),
            "cumplimiento_vs_sap": _ratio(real, sap),
            "n_of_sap": int(v["n_of_sap"]),
            "n_of_app": int(v["n_of_app"]),
        })
        if clase != "LINEA":
            continue
        tot["app"] += app
        tot["sap"] += sap
        tot["real"] += real
        tot["sap_" + cat] += sap
        tot["real_" + cat] += real

    resumen = {
        "cj_programado_app": _r2(tot["app"]),
        "cj_programado_sap": _r2(tot["sap"]),
        "cj_real": _r2(tot["real"]),
        "cumplimiento_global_vs_sap": _ratio(tot["real"], tot["sap"]),
        "adopcion_app_sobre_sap": _ratio(tot["sap_ambos"], tot["sap"]),
        "produccion_fuera_de_app_pct": _ratio(tot["real_solo_sap"] + tot["real_sin_programa"], tot["real"]),
        "n_skus_por_categoria": {
            k: sum(1 for x in conciliacion if x["categoria"] == k and x["clase"] == "LINEA")
            for k in ("ambos", "solo_sap", "solo_app", "sin_programa")
        },
        "fuera_de_lineas": {
            cl: {
                "cj_real": _r2(v["cj_real"]),
                "cj_programado_sap": _r2(v["cj_prog_sap"]),
                "cj_programado_app": _r2(v["cj_prog_app"]),
                "n_skus": sum(1 for s_, c_ in clase_sku.items() if c_ == cl),
            }
            for cl, v in fuera.items() if any(v.values())
        },
        "lineas_con_bitacora": sum(1 for x in res_lineas if x["con_bitacora"]),
        "lineas_total": len(res_lineas),
    }

    return {
        "semana": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},   # alias histórico
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "resumen": resumen,
        "lineas": res_lineas,
        "conciliacion_sku": conciliacion,
        "advertencias": {k: sorted(x for x in v if x) for k, v in adv.items() if v},
        "definiciones": {
            "unidad_horas": "horas-equivalentes a velocidad nominal: cj*u_por_caja/(velocidad_u_hr*factor_velocidad)",
            "ocupacion_real": "heq_producidas / nominal",
            "eficiencia": "heq_producidas / operada; operada = nominal - paradas - sin programa (solo con bitácora)",
            "ocupacion_programada_sap": "heq_programadas_sap / nominal",
            "capacidad_ociosa": "1 - ocupacion_programada_sap",
            "capacidad_real_vs_teorica": "(nominal - paradas planificadas - no planificadas) / nominal (solo con bitácora)",
            "semana_sap": "OF SAP asignada a la semana del centro de su tramo planificado",
            "semana_real": "fecha_tr del recibo",
            "totales_resumen": "solo SKU clase LINEA; el resto va en resumen.fuera_de_lineas",
        },
    }


@router.get("/semana")
def kpi_semana(desde: Optional[date] = Query(None)):
    return calcular_semana(desde or semana_default())


# Producción real por SKU y día (Terminal Report) para la grilla de Detalle Producción.
# Misma regla que SQL_TR: MAX por (OF, TR) porque cant_producida se repite entre lotes.
SQL_REAL_DIARIO = """
SELECT sku, fecha_tr AS fecha, SUM(prod_tr) AS cj FROM (
    SELECT orden_produccion, terminal_report, sku, fecha_tr, MAX(cant_producida) AS prod_tr
    FROM mrp_of_sap
    WHERE terminal_report <> '' AND NOT es_granel AND fecha_tr BETWEEN :desde AND :hasta
    GROUP BY 1, 2, 3, 4
) t
GROUP BY 1, 2
ORDER BY 2, 1
"""


@router.get("/real_diario")
def real_diario(desde: date = Query(...), hasta: date = Query(...)):
    from fastapi import HTTPException
    if desde > hasta or (hasta - desde).days > 62:
        raise HTTPException(422, "Rango inválido (máximo 62 días).")
    with _engine.connect() as c:
        filas = [{"sku": r.sku, "fecha": r.fecha.isoformat(), "cj": float(r.cj)}
                 for r in c.execute(sa.text(SQL_REAL_DIARIO), {"desde": desde, "hasta": hasta})]
        ultima = c.execute(sa.text(
            "SELECT MAX(fecha_tr) FROM mrp_of_sap WHERE terminal_report <> ''")).scalar()
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
            "ultima_fecha_tr": ultima.isoformat() if ultima else None, "real": filas}


# ============================================================================
# Dashboard de rendimiento (menú Control): período filtrado + evolutivo semanal
# ============================================================================
MAX_DIAS_DASHBOARD = 182   # 26 semanas

SQL_EVENTOS_DETALLE = """
SELECT e.linea, e.tipo, t.nombre AS tipo_nombre, t.categoria,
       SUM(COALESCE(e.duracion_min, 0)) AS minutos, COUNT(*) AS n
FROM mrp_eventos_linea e JOIN mrp_eventos_tipos t ON t.codigo = e.tipo
WHERE NOT e.anulado AND e.fecha BETWEEN :desde AND :hasta
GROUP BY 1, 2, 3, 4
ORDER BY minutos DESC
"""


def _lineas_sel(resultado, linea, categoria):
    return {
        x["linea"] for x in resultado["lineas"]
        if (not linea or x["linea"] == linea) and (not categoria or x["categoria"] == categoria)
    }


def _resumir(resultado, sel):
    """Totales de un resultado de calcular_periodo restringidos a las líneas 'sel'."""
    ls = [x for x in resultado["lineas"] if x["linea"] in sel]

    def H(k):
        return sum(x["horas"][k] for x in ls)

    conc = [c for c in resultado["conciliacion_sku"]
            if c["clase"] == "LINEA" and c["linea_atribuida"] in sel]

    def C(k, cats=None):
        return sum(c[k] for c in conc if cats is None or c["categoria"] in cats)

    nominal = H("nominal")
    sap, app, real = C("cj_programado_sap"), C("cj_programado_app"), C("cj_real")
    return {
        "cj_programado_app": _r2(app),
        "cj_programado_sap": _r2(sap),
        "cj_real": _r2(real),
        "adopcion_app_sobre_sap": _ratio(C("cj_programado_sap", {"ambos"}), sap),
        "cumplimiento_vs_sap": _ratio(real, sap),
        "produccion_fuera_de_app_pct": _ratio(C("cj_real", {"solo_sap", "sin_programa"}), real),
        "horas_nominales": _r2(nominal),
        "heq_producidas": _r2(H("heq_producidas")),
        "heq_programadas_sap": _r2(H("heq_programadas_sap")),
        "heq_programadas_app": _r2(H("heq_programadas_app")),
        "horas_parada_planificada": _r2(H("parada_planificada")),
        "horas_parada_no_planificada": _r2(H("parada_no_planificada")),
        "horas_sin_programa": _r2(H("sin_programa")),
        "ocupacion_real": _ratio(H("heq_producidas"), nominal),
        "eficiencia": _ratio(sum(x["horas"]["heq_producidas"] for x in ls if x["con_bitacora"]),
                             sum(x["horas"]["operada"] for x in ls if x["con_bitacora"])),
        "ocupacion_programada_sap": _ratio(H("heq_programadas_sap"), nominal),
        "ocupacion_programada_app": _ratio(H("heq_programadas_app"), nominal),
        "n_lineas": len(ls),
        "lineas_con_bitacora": sum(1 for x in ls if x["con_bitacora"]),
    }


@router.get("/dashboard")
def dashboard(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    linea: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
):
    from fastapi import HTTPException   # import local: el módulo también corre como CLI

    hasta = hasta or (semana_default() + timedelta(days=6))
    desde = desde or (hasta - timedelta(days=8 * 7 - 1))
    if desde > hasta:
        raise HTTPException(422, "El rango es inválido: 'desde' es posterior a 'hasta'.")
    if (hasta - desde).days + 1 > MAX_DIAS_DASHBOARD:
        raise HTTPException(422, "El rango máximo es de 26 semanas.")
    linea = linea or None
    categoria = categoria or None

    periodo = calcular_periodo(desde, hasta)
    sel = _lineas_sel(periodo, linea, categoria)
    if (linea or categoria) and not sel:
        raise HTTPException(422, "No hay líneas activas para el filtro seleccionado.")
    hay_filtro = bool(linea or categoria)

    with _engine.connect() as c:
        eventos = [dict(r._mapping) for r in
                   c.execute(sa.text(SQL_EVENTOS_DETALLE), {"desde": desde, "hasta": hasta})
                   if r.linea in sel]

    # Evolutivo: semanas completas lunes-domingo que tocan el rango
    evolutivo, evo_lineas = [], defaultdict(list)
    lunes = desde - timedelta(days=desde.weekday())
    while lunes <= hasta:
        domingo = lunes + timedelta(days=6)
        r = calcular_periodo(lunes, domingo)
        iso_anio, iso_sem, _ = lunes.isocalendar()
        fila = {"semana": lunes.isoformat(), "semana_iso": iso_sem, "anio_iso": iso_anio,
                "parcial": lunes < desde or domingo > hasta or domingo >= date.today()}
        fila.update(_resumir(r, sel))
        evolutivo.append(fila)
        for x in r["lineas"]:
            if x["linea"] in sel:
                evo_lineas[x["linea"]].append({
                    "semana": lunes.isoformat(),
                    "ocupacion_real": x["kpi"]["ocupacion_real"],
                    "eficiencia": x["kpi"]["eficiencia"],
                    "ocupacion_programada_sap": x["kpi"]["ocupacion_programada_sap"],
                    "cumplimiento_vs_sap": x["kpi"]["cumplimiento_vs_sap"],
                    "heq_producidas": x["horas"]["heq_producidas"],
                })
        lunes += timedelta(days=7)

    conc = [x for x in periodo["conciliacion_sku"]
            if not hay_filtro or (x["clase"] == "LINEA" and x["linea_atribuida"] in sel)]

    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "filtros": {"linea": linea, "categoria": categoria},
        "opciones": {
            "lineas": [{"codigo": x["linea"], "categoria": x["categoria"]} for x in periodo["lineas"]],
            "categorias": sorted({x["categoria"] for x in periodo["lineas"] if x["categoria"]}),
        },
        "resumen": _resumir(periodo, sel),
        "fuera_de_lineas": {} if hay_filtro else periodo["resumen"]["fuera_de_lineas"],
        "lineas": [x for x in periodo["lineas"] if x["linea"] in sel],
        "conciliacion_sku": conc,
        "eventos": eventos,
        "evolutivo": evolutivo,
        "evolutivo_lineas": dict(evo_lineas),
        "advertencias": periodo["advertencias"],
        "definiciones": periodo["definiciones"],
    }


def _pct(x):
    return "   -  " if x is None else f"{x * 100:5.0f}%"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="KPIs de operación semanal por línea")
    ap.add_argument("--desde", type=date.fromisoformat, default=None, help="lunes de la semana (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", help="imprime el JSON completo")
    args = ap.parse_args()
    r = calcular_semana(args.desde or semana_default())

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        _d = date.fromisoformat(r["semana"]["desde"])
        print("Sem", _d.isocalendar()[1], "·", r["semana"]["desde"], "a", r["semana"]["hasta"])
        print(f"{'linea':<14}{'nom_h':>7}{'heq':>8}{'ocupR':>7}{'ocupSAP':>8}{'cumpl':>7}{'ev':>4}  alertas")
        for x in r["lineas"]:
            h, k = x["horas"], x["kpi"]
            print(f"{x['linea']:<14}{h['nominal']:>7.1f}{h['heq_producidas']:>8.1f}"
                  f"{_pct(k['ocupacion_real']):>7}{_pct(k['ocupacion_programada_sap']):>8}"
                  f"{_pct(k['cumplimiento_vs_sap']):>7}{x['n_eventos']:>4}  {len(x['alertas'])}")
        fl = r["resumen"].pop("fuera_de_lineas")
        print("Resumen (solo LINEA):", json.dumps(r["resumen"], ensure_ascii=False, default=str))
        print("Fuera de líneas:", json.dumps(fl, ensure_ascii=False, default=str))
        print("Advertencias:", {k: len(v) for k, v in r["advertencias"].items()})
