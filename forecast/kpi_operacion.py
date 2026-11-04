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

UMBRAL_EFICIENCIA_ALTA = 1.05   # sobre esto: capacidad nominal probablemente subparametrizada
ESTADOS_PROGRAMADO_APP = ("APROBADA", "MODIFICADA")

SQL_LINEAS = (
    "SELECT codigo, nombre, turnos_dia, horas_turno, dias_semana, velocidad_u_hr "
    "FROM mrp_lineas WHERE activa"
)
SQL_SKU_LINEAS = "SELECT sku, linea, preferida, factor_velocidad FROM mrp_sku_lineas"
SQL_SKU_PARAMS = "SELECT sku, u_por_caja FROM mrp_sku_params"

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


def calcular_semana(desde: date) -> dict:
    hasta = desde + timedelta(days=6)
    p = {"desde": desde, "hasta": hasta}

    q_app = sa.text(SQL_PROG_APP).bindparams(sa.bindparam("estados", expanding=True))
    with _engine.connect() as c:
        lineas = {r.codigo: r for r in c.execute(sa.text(SQL_LINEAS))}
        sku_lin = defaultdict(list)
        for r in c.execute(sa.text(SQL_SKU_LINEAS)):
            sku_lin[r.sku].append(r)
        upc = {r.sku: r.u_por_caja for r in c.execute(sa.text(SQL_SKU_PARAMS))}
        filas_tr = list(c.execute(sa.text(SQL_TR), p))
        filas_sap = list(c.execute(sa.text(SQL_PROG_SAP), p))
        filas_app = list(c.execute(q_app, {**p, "estados": list(ESTADOS_PROGRAMADO_APP)}))
        filas_ev = list(c.execute(sa.text(SQL_EVENTOS), p))

    adv = {k: set() for k in (
        "sku_sin_linea", "sku_linea_ambigua", "sku_sin_upc",
        "linea_inactiva_o_desconocida", "velocidad_invalida", "evento_linea_desconocida",
    )}

    def atribuir(sku):
        opciones = sku_lin.get(sku, [])
        if not opciones:
            adv["sku_sin_linea"].add(sku)
            return None
        if len(opciones) > 1:
            adv["sku_linea_ambigua"].add(sku)
            pref = [o for o in opciones if o.preferida]
            return (pref or opciones)[0].linea
        return opciones[0].linea

    def h_eq(sku, linea, cj):
        u = upc.get(sku)
        if u is None or float(u) <= 0:
            adv["sku_sin_upc"].add(sku)
            return None
        L = lineas.get(linea)
        if L is None:
            adv["linea_inactiva_o_desconocida"].add(linea)
            return None
        f = next((o.factor_velocidad for o in sku_lin.get(sku, []) if o.linea == linea), 1.0)
        vel = float(L.velocidad_u_hr or 0) * float(f or 0)
        if vel <= 0:
            adv["velocidad_invalida"].add(sku + "@" + linea)
            return None
        return float(cj) * float(u) / vel

    acc = {cod: defaultdict(float) for cod in lineas}
    diario = {cod: defaultdict(float) for cod in lineas}
    por_sku = defaultdict(lambda: defaultdict(float))
    linea_sku = {}

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
        lin = atribuir(r.sku)
        linea_sku[r.sku] = lin
        por_sku[r.sku]["cj_real"] += float(r.cj)
        sumar("heq_real", "cj_real", r.sku, lin, r.cj, r.fecha_tr)

    for r in filas_sap:
        lin = atribuir(r.sku)
        linea_sku[r.sku] = lin
        por_sku[r.sku]["cj_prog_sap"] += float(r.cj)
        por_sku[r.sku]["n_of_sap"] += r.n_of
        sumar("heq_prog_sap", "cj_prog_sap", r.sku, lin, r.cj)

    for r in filas_app:
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
        nominal = float((L.turnos_dia or 0) * (L.horas_turno or 0) * (L.dias_semana or 0))
        pp, pn, sp = a["parada_plan_h"], a["parada_noplan_h"], a["sin_programa_h"]
        disponible = max(nominal - pp, 0.0)
        cap_real = max(disponible - pn, 0.0)
        operada = max(cap_real - sp, 0.0)
        heq, heq_sap, heq_app = a["heq_real"], a["heq_prog_sap"], a["heq_prog_app"]
        no_expl = max(nominal - heq - pp - pn - sp, 0.0)
        con_bitacora = a["n_eventos"] > 0
        ocup_sap = _ratio(heq_sap, nominal)
        eficiencia = _ratio(heq, nominal)

        alertas = []
        if eficiencia is not None and eficiencia > UMBRAL_EFICIENCIA_ALTA:
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
                "eficiencia": eficiencia,
                "rendimiento": _ratio(heq, operada) if con_bitacora else None,
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
        tot["app"] += app
        tot["sap"] += sap
        tot["real"] += real
        tot["sap_" + cat] += sap
        tot["real_" + cat] += real
        conciliacion.append({
            "sku": sku,
            "linea_atribuida": linea_sku.get(sku),
            "categoria": cat,
            "cj_programado_app": _r2(app),
            "cj_programado_sap": _r2(sap),
            "cj_real": _r2(real),
            "desvio_sap_vs_app_cj": _r2(sap - app),
            "cumplimiento_vs_sap": _ratio(real, sap),
            "n_of_sap": int(v["n_of_sap"]),
            "n_of_app": int(v["n_of_app"]),
        })

    resumen = {
        "cj_programado_app": _r2(tot["app"]),
        "cj_programado_sap": _r2(tot["sap"]),
        "cj_real": _r2(tot["real"]),
        "cumplimiento_global_vs_sap": _ratio(tot["real"], tot["sap"]),
        "adopcion_app_sobre_sap": _ratio(tot["sap_ambos"], tot["sap"]),
        "produccion_fuera_de_app_pct": _ratio(tot["real_solo_sap"] + tot["real_sin_programa"], tot["real"]),
        "n_skus_por_categoria": {
            k: sum(1 for x in conciliacion if x["categoria"] == k)
            for k in ("ambos", "solo_sap", "solo_app", "sin_programa")
        },
        "lineas_con_bitacora": sum(1 for x in res_lineas if x["con_bitacora"]),
        "lineas_total": len(res_lineas),
    }

    return {
        "semana": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "resumen": resumen,
        "lineas": res_lineas,
        "conciliacion_sku": conciliacion,
        "advertencias": {k: sorted(x for x in v if x) for k, v in adv.items() if v},
        "definiciones": {
            "unidad_horas": "horas-equivalentes a velocidad nominal: cj*u_por_caja/(velocidad_u_hr*factor_velocidad)",
            "eficiencia": "heq_producidas / nominal",
            "rendimiento": "heq_producidas / operada (solo con bitácora)",
            "ocupacion_programada_sap": "heq_programadas_sap / nominal",
            "capacidad_ociosa": "1 - ocupacion_programada_sap",
            "capacidad_real_vs_teorica": "(nominal - paradas planificadas - no planificadas) / nominal (solo con bitácora)",
            "semana_sap": "OF SAP asignada a la semana del centro de su tramo planificado",
            "semana_real": "fecha_tr del recibo",
        },
    }


@router.get("/semana")
def kpi_semana(desde: Optional[date] = Query(None)):
    return calcular_semana(desde or semana_default())


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
        print("Semana", r["semana"]["desde"], "a", r["semana"]["hasta"])
        print(f"{'linea':<14}{'nom_h':>7}{'heq':>8}{'efic':>7}{'ocupSAP':>8}{'cumpl':>7}{'ev':>4}  alertas")
        for x in r["lineas"]:
            h, k = x["horas"], x["kpi"]
            print(f"{x['linea']:<14}{h['nominal']:>7.1f}{h['heq_producidas']:>8.1f}"
                  f"{_pct(k['eficiencia']):>7}{_pct(k['ocupacion_programada_sap']):>8}"
                  f"{_pct(k['cumplimiento_vs_sap']):>7}{x['n_eventos']:>4}  {len(x['alertas'])}")
        print("Resumen:", json.dumps(r["resumen"], ensure_ascii=False, default=str))
        print("Advertencias:", {k: len(v) for k, v in r["advertencias"].items()})
