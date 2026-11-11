"""
informe_semanal.py — Informe de Operación SEMANAL automático (tanda 4, 11-11-2026).

Cada lunes (crontab 08:30 Chile) arma el informe de la última semana cerrada (lun-dom):
  1. DATOS (sin IA): KPIs de la semana y tendencia de 4 semanas (kpi_operacion), semáforo y
     riesgo de quiebre del plan vigente (analisis_linea), casos y decisiones de Análisis de
     Línea, cambios de parámetros, intervenciones evaluadas, capacidad demostrada y bitácora.
  2. LECTURA IA (Claude): resumen ejecutivo, alertas y recomendaciones ("analizar...", nunca
     obligatorias), usando SOLO las cifras compiladas. Sin API -> el informe sale igual, sin lectura.
  3. HTML autocontenido (claro/oscuro, imprimible a PDF desde el navegador), guardado en la
     tabla mrp_informes y servido por /informes/{id}/html (pestaña Control -> Informe IA).

Uso:
  python3 /app/informe_semanal.py                 # semana cerrada anterior
  python3 /app/informe_semanal.py --lunes 2026-11-02 --sin-ia
"""
import argparse
import html as _h
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from db_mrp import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("informe_semanal")
router = APIRouter(prefix="/informes", tags=["Informes"])



def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _lunes_anterior(hoy: date) -> date:
    return hoy - timedelta(days=hoy.weekday() + 7)


# ── 1. Datos (mismo esquema que el informe interactivo Sem 37–45) ───────────────
SEMANAS_PERIODO = 9
SEMANAS_CAPACIDAD = 12      # capacidad demostrada: misma ventana que el conocimiento empírico
DIAS_INMEDIATO = 6
ETIQ_CAMPO = {"batch_min_u": "Batch mínimo", "cap_bodega_u": "Cap. bodega", "factor_velocidad": "Factor de velocidad",
              "turnos_dia": "Turnos", "velocidad_u_hr": "Velocidad de línea"}


def _ddmm(d):
    return f"{d.day:02d}/{d.month:02d}"


def _div(a, b):
    return (a / b) if b else None


def compilar(lunes: date) -> dict:
    import calendario as _cal
    import kpi_operacion as _k
    import analisis_linea as _al
    import mrp as _mrp
    ult_dom = lunes + timedelta(days=6)
    semanas = [lunes - timedelta(days=7 * i) for i in range(SEMANAS_PERIODO - 1, -1, -1)]
    semanas_cap = [lunes - timedelta(days=7 * i) for i in range(SEMANAS_CAPACIDAD - 1, -1, -1)]
    ini = semanas[0]
    kp = {s_: _k.calcular_semana(s_) for s_ in semanas_cap}
    per = _k.calcular_periodo(ini, ult_dom)
    nsem = len(semanas)

    # ── semanas (totales) ──
    S = []
    for s_ in semanas:
        r = kp[s_]
        heq = sum(x["horas"]["heq_producidas"] or 0 for x in r["lineas"])
        heq_sap = sum(x["horas"]["heq_programadas_sap"] or 0 for x in r["lineas"])
        nom = sum(x["horas"]["nominal"] or 0 for x in r["lineas"])
        S.append({"sem": s_.isocalendar()[1], "ini": _ddmm(s_), "app": r["resumen"]["cj_programado_app"],
                  "sap": r["resumen"]["cj_programado_sap"], "real": r["resumen"]["cj_real"],
                  "cumpl": r["resumen"]["cumplimiento_global_vs_sap"], "ocR": _div(heq, nom), "ocP": _div(heq_sap, nom),
                  "adop": r["resumen"]["adopcion_app_sobre_sap"]})

    with engine.connect() as c:
        plan, piezas, lin_p, sku_lineas, sku_params = _al._cargar_desde_bd(c)
        try:
            demo = _al.capacidad_demostrada(date.today())
        except Exception:
            demo = {}
        carga = _al.calcular_carga(piezas["detalle_diario"], piezas["uso_linea"], piezas["alertas"], lin_p,
                                   sku_lineas, sku_params, 4, demo, piezas.get("entradas_fijas"))
        full = {r.sku: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params"))}
        hoy_plan = date.fromisoformat(carga["hoy"])
        fin_fut = hoy_plan + timedelta(days=28)
        pref = {}
        for r in sku_lineas:
            if r.get("preferida") or r["sku"] not in pref:
                pref[r["sku"]] = r["linea"] if r.get("preferida") else pref.get(r["sku"], r["linea"])

        # ── próximas 4 semanas: PROGRAMADO (OF sugeridas + aprobadas) y REQUERIDO (demanda), mismo
        #    cálculo que el semáforo del Análisis de Línea, en % de la capacidad nominal ──
        fut, req, d95, dias_fut = {}, {}, {}, 0
        for x in carga["lineas"]:
            hn = sum(f["horas_nominales"] for f in x["semanas"]) or 0
            fut[x["linea"]] = (sum(f["horas_programadas"] for f in x["semanas"]) / hn) if hn else 0.0
            req[x["linea"]] = (sum(f["horas_requeridas"] for f in x["semanas"]) / hn) if hn else 0.0
            d95[x["linea"]] = 0
            dias_fut = max(dias_fut, sum(f["dias_habiles"] for f in x["semanas"]))

        # ── alertas del plan: quiebres y bajo SS (4 semanas) ──
        q = defaultdict(lambda: {"dias": 0, "def_u": 0.0, "primer": None})
        bajo_ss, exb = set(), defaultdict(int)
        for a in piezas["alertas"] or []:
            f = a.get("fecha")
            if not f or not (hoy_plan.isoformat() <= f < fin_fut.isoformat()):
                continue
            t = a.get("tipo")
            if t == "QUIEBRE":
                x = q[a["sku"]]; x["dias"] += 1; x["def_u"] = max(x["def_u"], float(a.get("deficit_u") or 0))
                x["primer"] = min(x["primer"] or f, f)
            elif t == "BAJO_SS":
                bajo_ss.add(a["sku"])
            elif t == "EXCESO_BODEGA":
                exb[a["sku"]] += 1

        # ── faltantes del último corte ──
        falt_fecha, falt = None, {}
        try:
            falt_fecha = c.execute(sa.text("SELECT max(fecha) FROM mrp_faltantes")).scalar()
            if falt_fecha:
                for r in c.execute(sa.text("""SELECT sku, max(descripcion) AS d, sum(faltante_cj) AS cj FROM mrp_faltantes
                                              WHERE fecha = :f AND faltante_cj > 0 GROUP BY sku"""), {"f": falt_fecha}):
                    falt[r.sku] = {"desc": r.d, "cj": float(r.cj)}
        except Exception:
            c.rollback()

        def upc(s_):
            return float((full.get(s_) or {}).get("u_por_caja") or 1) or 1.0

        quiebres = []
        for s_, v in q.items():
            dd = piezas["detalle_diario"].get(s_, {})
            d0 = dd.get(hoy_plan.isoformat(), {})
            dem = [float(x.get("demanda_corr_u") or x.get("forecast_u") or 0) for f, x in dd.items()
                   if hoy_plan.isoformat() <= f < fin_fut.isoformat()]
            dia = (date.fromisoformat(v["primer"]) - hoy_plan).days
            lin = pref.get(s_)
            quiebres.append({"sku": s_, "desc": (full.get(s_) or {}).get("descripcion"), "linea": lin, "fut": fut.get(lin, 0),
                             "fecha": v["primer"], "dia": dia, "dias": v["dias"], "def_cj": round(v["def_u"] / upc(s_)),
                             "disp_cj": round(float(d0.get("stock_disp_u") or d0.get("stock_ini_disp_u") or 0) / upc(s_)),
                             "dem_cj": round(sum(dem) / len(dem) / upc(s_), 1) if dem else 0,
                             "mto": bool((full.get(s_) or {}).get("mto")), "rp": False,
                             "falt": (falt.get(s_) or {}).get("cj"), "tipo": "Inmediato" if dia < DIAS_INMEDIATO else "Capacidad"})
        quiebres.sort(key=lambda z: (z["fecha"], -z["def_cj"]))

        # ── recomendaciones abiertas, casos, cambios, intervenciones ──
        p = {"d": lunes, "h": ult_dom + timedelta(days=1)}

        def filas(sql, prm=None):
            try:
                return [dict(r._mapping) for r in c.execute(sa.text(sql), p if prm is None else prm)]
            except Exception:
                c.rollback()
                return []
        recos = filas("""SELECT prioridad, campo, entidad, clave, linea, valor_actual, valor_sugerido, fuente, motivo
                         FROM mrp_params_recomendaciones WHERE estado = 'abierta'
                         ORDER BY CASE prioridad WHEN 'alta' THEN 0 WHEN 'media-alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, clave""", {})
        casos = filas("""SELECT id, linea, origen, estado, decision, recomendacion->>'causa_principal' AS causa
                         FROM mrp_analisis_casos WHERE creado_en >= :d AND creado_en < :h AND estado <> 'error' ORDER BY id""")
        pend = filas("SELECT count(*) AS n FROM mrp_analisis_acciones WHERE estado = 'aceptada'", {})
        cambios = filas("""SELECT campo, count(*) AS n, count(DISTINCT COALESCE(sku, linea)) AS elementos,
                                  string_agg(DISTINCT editor, ', ') AS editores
                           FROM mrp_params_historial WHERE ts >= :d AND ts < :h AND revertido_por IS NULL GROUP BY campo ORDER BY n DESC""")
        interv = filas("""SELECT palanca, linea, veredicto, aprendizaje FROM mrp_intervenciones
                          WHERE evaluado_en >= :d AND evaluado_en < :h ORDER BY evaluado_en""")
        tc_unicos = filas("SELECT count(DISTINCT t_cambio_hrs) AS n FROM mrp_sku_lineas", {})

    # ── líneas ──
    lineas = []
    per_l = {x["linea"]: x for x in per["lineas"]}
    for cod, L in sorted(lin_p.items()):
        if not L.get("activa", True):
            continue
        cs = [next((x["kpi"]["cumplimiento_vs_sap"] for x in kp[s_]["lineas"] if x["linea"] == cod), None) for s_ in semanas]
        oc = [next((x["kpi"]["ocupacion_real"] for x in kp[s_]["lineas"] if x["linea"] == cod), None) for s_ in semanas]

        def tramo(ws):
            rr = sum(next((x["cajas"]["real"] for x in kp[s_]["lineas"] if x["linea"] == cod), 0) or 0 for s_ in ws)
            ss_ = sum(next((x["cajas"]["programado_sap"] for x in kp[s_]["lineas"] if x["linea"] == cod), 0) or 0 for s_ in ws)
            return _div(rr, ss_)
        pl = per_l.get(cod) or {}
        ocs = [v for v in oc if v is not None]
        # capacidad demostrada: mejores semanas y máximo en la MISMA ventana (12 semanas, real SAP)
        oc12 = [v for v in (next((x["kpi"]["ocupacion_real"] for x in kp[s_]["lineas"] if x["linea"] == cod), None)
                            for s_ in semanas_cap) if v is not None]
        top = sorted(oc12)[-3:]
        tc = L.get("_tc")
        h_sem = _cal.horas_semana_patron(tc, float(L.get("horas_turno") or 0), int(L.get("turnos_dia") or 1), int(L.get("dias_semana") or 5))
        if tc:
            patron = "-".join(f"{sum(float(t['horas'][i]) for t in tc):g}" for i in range(5))
            param = f"{h_sem:g} h/sem ({patron}) · {float(L.get('velocidad_u_hr') or 0):,.0f} u/h".replace(",", ".")
        else:
            param = (f"{h_sem:g} h/sem ({L.get('turnos_dia')} turno × {float(L.get('horas_turno') or 0):g} h × {L.get('dias_semana')} días)"
                     f" · {float(L.get('velocidad_u_hr') or 0):,.0f} u/h").replace(",", ".")
        lineas.append({"linea": cod, "cat": (pl.get("categoria") or "—"), "cumpl_sem": cs, "oc_sem": oc,
                       "ocR": (pl.get("kpi") or {}).get("ocupacion_real") or 0, "ocP": (pl.get("kpi") or {}).get("ocupacion_programada_sap") or 0,
                       "cumpl": (pl.get("kpi") or {}).get("cumplimiento_vs_sap"), "cumpl4": tramo(semanas[-4:]), "cumpl_ini": tramo(semanas[:4]),
                       "fut": fut.get(cod, 0), "req": req.get(cod, 0), "d95": d95.get(cod, 0), "h_sem": h_sem,
                       "q": sum(1 for x in quiebres if x["linea"] == cod), "ss": sum(1 for s_ in bajo_ss if pref.get(s_) == cod),
                       "max_oc": max(oc12) if oc12 else 0, "top3": (sum(top) / len(top)) if top else 0,
                       "param": param,
                       "con_bit": bool(pl.get("con_bitacora")), "efic": (pl.get("kpi") or {}).get("eficiencia"),
                       "cob": pl.get("cobertura_bitacora")})

    # ── desvíos por SKU (período) ──
    agg = defaultdict(lambda: {"app": 0.0, "sap": 0.0, "real": 0.0, "wb": 0, "w": 0, "linea": None})
    for s_ in semanas:
        for x in kp[s_]["conciliacion_sku"]:
            if x["clase"] != "LINEA":
                continue
            a = agg[x["sku"]]
            a["app"] += x["cj_programado_app"] or 0; a["sap"] += x["cj_programado_sap"] or 0; a["real"] += x["cj_real"] or 0
            a["linea"] = x["linea_atribuida"]
            if (x["cj_programado_sap"] or 0) > 0:
                a["w"] += 1
                if (x["cumplimiento_vs_sap"] or 0) < 0.7:
                    a["wb"] += 1
    desvios = sorted(({"sku": k_, "desc": (full.get(k_) or {}).get("descripcion"), "linea": v["linea"], "app": v["app"], "sap": v["sap"],
                       "real": v["real"], "cumpl": _div(v["real"], v["sap"]), "wb": v["wb"], "w": v["w"]}
                      for k_, v in agg.items() if v["sap"] > 0), key=lambda z: -(z["sap"] - z["real"]))[:15]

    # ── cap. bodega < batch + SS ──
    cap_b = []
    for s_, pr in full.items():
        if not pr.get("activo"):
            continue
        cap, bmin = float(pr.get("cap_bodega_u") or 999999), float(pr.get("batch_min_u") or 0)
        if cap >= 999999 or bmin <= 0:
            continue
        dd = piezas["detalle_diario"].get(s_, {})
        dem = [float(x.get("forecast_u") or 0) for f, x in dd.items() if hoy_plan.isoformat() <= f < fin_fut.isoformat()]
        ss = float(pr.get("ss_dias") or 0) * (sum(dem) / len(dem) if dem else 0)
        if bmin + ss > cap:
            cap_b.append({"sku": s_, "desc": pr.get("descripcion"), "linea": pref.get(s_), "cap": cap, "bmin": bmin,
                          "ss": round(ss), "need": round(bmin + ss), "exb": exb.get(s_, 0), "q": s_ in q})
    cap_b.sort(key=lambda z: -(z["need"] / z["cap"]))

    # ── fuera del turno nominal (período) ──
    ft = []
    for x in per["lineas"]:
        L = lin_p.get(x["linea"]) or {}
        pdd = x.get("produccion_diaria_heq") or {}
        h_ref = max([_al.horas_dia_linea(L, ini + timedelta(days=i)) for i in range(7)] or [0]) or \
            float(L.get("horas_turno") or 0) * int(L.get("turnos_dia") or 1)
        h_sem_l = _cal.horas_semana_patron(L.get("_tc"), float(L.get("horas_turno") or 0), int(L.get("turnos_dia") or 1),
                                          int(L.get("dias_semana") or 5))
        fs = [(f, v) for f, v in pdd.items() if v > 0.5 and (date.fromisoformat(f).weekday() >= 5 or _cal.es_feriado(date.fromisoformat(f)))]
        sobre = [v for v in pdd.values() if h_ref and v > 1.1 * h_ref]
        if fs or sobre:
            ft.append({"linea": x["linea"], "h_sem": h_sem_l, "h_dia": h_ref, "dias_fs": len(fs), "h_fs": round(sum(v for _, v in fs)),
                       "dias_sobre": len(sobre), "max_h": max(pdd.values()) if pdd else 0})
    ft.sort(key=lambda z: -(z["dias_fs"] * 2 + z["dias_sobre"]))

    # ── bitácora última semana ──
    bit = []
    for x in kp[lunes]["lineas"]:
        det = (x["horas"].get("parada_planificada") or 0) + (x["horas"].get("parada_no_planificada") or 0)
        explicada = (x.get("dias_con_bitacora") or 0) > 0
        bit.append({"linea": x["linea"], "cumpl": x["kpi"]["cumplimiento_vs_sap"], "dias": x.get("dias_con_bitacora") or 0,
                    "det_h": det if explicada else None, "explicada": explicada,
                    "lectura": (f"{det:.1f} h de detención registradas.".replace(".", ",") if explicada else "Sin registro: la desviación queda por explicar.")})
    bit.sort(key=lambda z: (not z["explicada"], z["cumpl"] if z["cumpl"] is not None else 9))

    # ── período y calidad de datos ──
    cal_on = _mrp.capacidad_calendario_activa()
    fer = [d for d in (ini + timedelta(days=i) for i in range((ult_dom - ini).days + 1)) if _cal.es_feriado(d) and d.weekday() < 5]
    nota_nominal = ("Horas nominales según la jornada configurada por línea, sin feriados." if cal_on else
                    "Horas nominales = turnos × horas × días hábiles" + (f"; no descuentan los feriados {', '.join(_ddmm(d) for d in fer)}." if fer else "."))
    n_bit = sum(1 for l in lineas if l["con_bit"])
    calidad = [["Bitácora", f"{n_bit} de {len(lineas)} líneas con registro en el período; en las demás, las desviaciones quedan por explicar."],
               ["Horas nominales", nota_nominal + (" Calendario de capacidad (42 h) activo." if cal_on else " Calendario de capacidad (42 h) aún no activo.")],
               ["Setup", "t_cambio_hrs con un solo valor para todos los SKU: el plan no distingue cambio de producto de cambio de formato."
                if ((tc_unicos or [{}])[0].get("n") or 0) <= 1 else "t_cambio_hrs diferenciado por SKU-línea."],
               ["Forecast", "Ver pestaña Precisión del forecast; SKU con poca historia pueden proyectar picos de lanzamiento."]]
    sem_ini, sem_fin = semanas[0].isocalendar()[1], semanas[-1].isocalendar()[1]
    cumpl_per = _div(sum(x["real"] or 0 for x in S), sum(x["sap"] or 0 for x in S))
    prev = S[:-1]
    nota_horas = ("Horas por semana según el calendario de capacidad (jornada 42 h) que usa el plan." if cal_on else
                  "Horas por semana que usa hoy el plan (anteriores al cambio de jornada: el calendario de 42 h aún no está activo).")
    D = {
        "meta": {"periodo": f"Sem {sem_ini} a {sem_fin} · {_ddmm(ini)} al {_ddmm(ult_dom)}-{ult_dom.year} · foco en la Sem {sem_fin}",
                 "sem_eval": f"Sem {sem_fin} ({_ddmm(lunes)} al {_ddmm(ult_dom)}-{ult_dom.year})",
                 "plan_label": f"plan #{plan.id}, próximas 4 semanas ({_ddmm(hoy_plan)} al {_ddmm(fin_fut - timedelta(days=1))})",
                 "inicio_plan": hoy_plan.isoformat(), "nota_horas": nota_horas,
                 "ventana_cap": f"últimas {SEMANAS_CAPACIDAD} semanas (Sem {semanas_cap[0].isocalendar()[1]}–{sem_fin})",
                 "periodo_corto": f"Sem {sem_ini}–{sem_fin}", "generado": date.today().strftime("%d-%m-%Y"),
                 "plan": f"Plan vigente {plan.id} · {plan.created_at:%d-%m-%Y %H:%M}", "plan_id": plan.id,
                 "horizonte": f"{_ddmm(hoy_plan)} al {_ddmm(fin_fut - timedelta(days=1))}", "dias_fut": dias_fut,
                 "tramo_ini": f"Sem {semanas[0].isocalendar()[1]}–{semanas[3].isocalendar()[1]}",
                 "tramo_fin": f"Sem {semanas[-4].isocalendar()[1]}–{sem_fin}",
                 "faltantes_fecha": falt_fecha.strftime("%d-%m") if falt_fecha else None, "nota_nominal": nota_nominal,
                 "semana_iso": sem_fin, "anio": lunes.isocalendar()[0], "desde": lunes.isoformat(), "hasta": ult_dom.isoformat()},
        "semanas": S,
        "kpi": {"sap": sum(x["sap"] or 0 for x in S), "real": sum(x["real"] or 0 for x in S), "app": sum(x["app"] or 0 for x in S),
                "cumpl": cumpl_per, "cumpl_ult": S[-1]["cumpl"],
                "cumpl_prev": _div(sum(x["real"] or 0 for x in prev), sum(x["sap"] or 0 for x in prev)),
                "adop_ult": S[-1]["adop"], "adop_per": per["resumen"]["adopcion_app_sobre_sap"],
                "ocR_ult": S[-1]["ocR"], "ocP_ult": S[-1]["ocP"],
                "ocR_prev": _div(sum((x["ocR"] or 0) for x in prev), len(prev)),
                "adop": _div(sum((x["adop"] or 0) * (x["sap"] or 0) for x in S), sum(x["sap"] or 0 for x in S)),
                "ocR": _div(sum((x["ocR"] or 0) for x in S), nsem), "ocP": _div(sum((x["ocP"] or 0) for x in S), nsem),
                "quiebres": len(quiebres), "quiebres_mto": sum(1 for x in quiebres if x["mto"]), "bajo_ss": len(bajo_ss),
                "lineas_sat": sum(1 for l in lineas if l["fut"] >= 0.845), "faltantes_hoy": len(falt),
                "faltantes_cj": round(sum(v["cj"] for v in falt.values()))},
        "lineas": lineas, "quiebres": quiebres,
        "faltantes": [{"sku": k_, "desc": v["desc"], "cj": v["cj"], "linea": pref.get(k_)} for k_, v in falt.items()],
        "desvios": desvios, "cap_bodega": cap_b, "fuera_turno": ft, "bit_lineas": bit,
        "lineas_bitacora": [{"linea": l["linea"], "ocR": l["ocR"], "efic": l["efic"], "cob": l["cob"]} for l in lineas if l["con_bit"]],
        "recos": [{"prioridad": r["prioridad"], "campo": ETIQ_CAMPO.get(r["campo"], r["campo"]),
                   "donde": r["clave"] + (f" · {r['linea']}" if r.get("linea") and r["linea"] != r["clave"] else ""),
                   "vigente": r["valor_actual"], "sugerido": r["valor_sugerido"], "fuente": r["fuente"], "motivo": r["motivo"]} for r in recos],
        "casos": casos, "acciones_pendientes": (pend or [{}])[0].get("n") or 0, "cambios": cambios, "interv": interv,
        "calidad": calidad,
    }
    return D


# ── 2. Lectura IA ─────────────────────────────────────────────────────────────
SYSTEM_IA = """Eres el analista de operaciones de Traverso (alimentos, Chile) y escribes el informe semanal de
producción para gerencia y planificación. Recibes datos ya calculados por el sistema (período de varias semanas con
foco en la última semana cerrada, y el riesgo del plan vigente para las próximas 4 semanas).
Reglas:
- Usa SOLO las cifras de los datos; no recalcules ni inventes.
- PERÍODOS: cada cifra pertenece a uno de estos períodos y SIEMPRE debes decir cuál: "en la semana evaluada (Sem N)",
  "en la tendencia (Sem A–B)", "en el plan vigente para las próximas 4 semanas" o "en el último corte de faltantes".
  Nunca mezcles cifras de períodos distintos en una misma frase sin nombrar cada período.
- FUENTES: "ocupación real" y "cumplimiento" vienen de la producción real reportada en SAP (Terminal Report): dilo así.
  "Programado" = OF sugeridas + aprobadas del plan; "requerido" = lo que exige la demanda (forecast + OV).
- UNIDADES: las cantidades son CAJAS (cj), nunca unidades.
- Sin jerga del sistema: no uses nombres de campos (top3, fut, req, ocR...). Di, por ejemplo,
  "en sus 3 mejores semanas produjo 154% de su capacidad nominal".
- El objetivo supremo es evitar quiebres de stock.
- Las recomendaciones son "analizar..." o "revisar...", nunca órdenes. Máximo 4, priorizadas por efecto en evitar quiebres.
- Si una línea produce sobre su capacidad parametrizada (top3 > 1,05), lo más probable son extensiones de turno o fines de semana.
- Menciona los límites de los datos cuando importen (p. ej. poca cobertura de la bitácora).
- Español claro, sin jerga del sistema. Frases cortas. Escribe "SS (stock de seguridad)" y "MTO (a pedido)" la primera vez.
Responde SOLO con un JSON válido:
{"titulo": "...", "resumen_ejecutivo": "3 a 5 frases",
 "alertas": [{"severidad": "critica|alta|media", "titulo": "...", "detalle": "...", "accion": "..."}],
 "recomendaciones": [{"titulo": "...", "detalle": "...", "responsable": "Planificación|Producción|Comercial|Gerencia"}],
 "lecturas": {"cumplimiento": "...", "ocupacion": "...", "riesgo": "...", "decisiones": "..."}}"""


def _para_ia(D: dict) -> dict:
    """Versión compacta para la IA (sin series largas que no aportan)."""
    M = D["meta"]
    return {"periodos": {"semana_evaluada": M["sem_eval"], "tendencia": M["periodo_corto"], "riesgo": M["plan_label"],
                         "capacidad_demostrada": M["ventana_cap"]},
            "unidades": "cantidades en cajas (cj); porcentajes como fracción (0,886 = 88,6%)",
            "kpi_semana_evaluada": {"cumplimiento": D["kpi"]["cumpl_ult"], "cumplimiento_8_semanas_anteriores": D["kpi"]["cumpl_prev"],
                                    "adopcion_app": D["kpi"]["adop_ult"], "ocupacion_real_sap": D["kpi"]["ocR_ult"],
                                    "ocupacion_programada_sap": D["kpi"]["ocP_ult"]},
            "kpi_tendencia": {"cumplimiento": D["kpi"]["cumpl"], "adopcion_app": D["kpi"]["adop_per"], "ocupacion_real_sap": D["kpi"]["ocR"],
                              "cajas_reales_sap": D["kpi"]["real"], "cajas_programadas_sap": D["kpi"]["sap"]},
            "kpi_plan_riesgo": {"skus_con_quiebre": D["kpi"]["quiebres"], "de_ellos_mto": D["kpi"]["quiebres_mto"], "skus_bajo_ss": D["kpi"]["bajo_ss"]},
            "faltantes_ultimo_corte": {"fecha": M["faltantes_fecha"], "skus": D["kpi"]["faltantes_hoy"], "cajas": D["kpi"]["faltantes_cj"]},
            "semanas": D["semanas"],
            "lineas": [{"linea": l["linea"], "categoria": l["cat"], "cumplimiento_semana_evaluada": (l["cumpl_sem"] or [None])[-1],
                        "cumplimiento_tendencia": l["cumpl"], "cumplimiento_ultimas_4_semanas": l["cumpl4"],
                        "cumplimiento_primeras_4_semanas": l["cumpl_ini"], "ocupacion_real_sap_tendencia": l["ocR"],
                        "programado_proximas_4_semanas": l["fut"], "requerido_por_demanda_proximas_4_semanas": l["req"],
                        "promedio_3_mejores_semanas_real_sap": l["top3"], "mejor_semana_real_sap": l["max_oc"],
                        "capacidad_nominal": l["param"], "skus_con_quiebre": l["q"], "skus_bajo_ss": l["ss"], "tiene_bitacora": l["con_bit"]}
                       for l in D["lineas"]],
            "quiebres": D["quiebres"][:20], "desvios": D["desvios"][:10], "cap_bodega": D["cap_bodega"][:10],
            "fuera_turno": D["fuera_turno"], "recos": D["recos"][:15], "casos": D["casos"], "cambios": D["cambios"],
            "intervenciones": D["interv"], "faltantes": D["faltantes"], "calidad": D["calidad"]}


def lectura_ia(D: dict) -> dict:
    try:
        import claude_api as _ca
        if not _ca.configurado():
            return {"disponible": False, "motivo": "API de Claude no configurada."}
        r = _ca.generar(SYSTEM_IA, "DATOS:\n" + json.dumps(_para_ia(D), ensure_ascii=False, default=str), max_tokens=12000)
        t = r["texto"].strip()
        i, j = t.find("{"), t.rfind("}")
        out = json.loads(t[i:j + 1])
        out["_meta"] = {k: r[k] for k in ("modelo", "tokens_in", "tokens_out", "costo_usd", "segundos")}
        out["disponible"] = True
        return out
    except Exception as e:
        log.error(f"Lectura IA no disponible: {e}")
        return {"disponible": False, "motivo": str(e)[:300]}


# ── 3. HTML: plantilla interactiva (forecast/informe_template.html) ───────────
PLANTILLA = "/app/informe_template.html"


def render_html(D: dict, ia: dict) -> str:
    import os
    ruta = PLANTILLA if os.path.exists(PLANTILLA) else os.path.join(os.path.dirname(__file__), "informe_template.html")
    with open(ruta, encoding="utf-8") as f:
        tpl = f.read()
    datos = json.dumps({**D, "ia": ia}, ensure_ascii=False, default=str).replace("</", "<\\/")
    titulo = _h.escape(ia.get("titulo") or f"Informe de Operación · Sem {D['meta']['semana_iso']}")
    return tpl.replace("__DATA__", datos).replace("<h1>Informe de Operación</h1>", f"<h1>{titulo}</h1>", 1)


# ── 4. Guardado y API ─────────────────────────────────────────────────────────
def generar(lunes: date, con_ia: bool = True, creado_por: str = "Sistema (automático)") -> dict:
    datos = compilar(lunes)
    ia = lectura_ia(datos) if con_ia else {"disponible": False, "motivo": "Generado sin IA."}
    html_ = render_html(datos, ia)
    titulo = ia.get("titulo") if ia.get("disponible") else f"Informe de Operación · Sem {datos['meta']['semana_iso']}"
    with engine.begin() as c:
        iid = c.execute(sa.text("""INSERT INTO mrp_informes (semana_iso, anio, desde, hasta, titulo, html, datos, ia, costo_usd, creado_por)
                                   VALUES (:s, :a, :d, :h, :t, :html, CAST(:dat AS JSONB), CAST(:ia AS JSONB), :c, :p) RETURNING id"""),
                        {"s": datos["meta"]["semana_iso"], "a": datos["meta"]["anio"], "d": datos["meta"]["desde"],
                         "h": datos["meta"]["hasta"], "t": titulo, "html": html_, "dat": json.dumps(datos, default=str),
                         "ia": json.dumps(ia, default=str), "c": (ia.get("_meta") or {}).get("costo_usd"), "p": creado_por}).scalar()
    return {"id": iid, "titulo": titulo, "ia": ia.get("disponible"), "costo_usd": (ia.get("_meta") or {}).get("costo_usd")}


class SolicitudInforme(BaseModel):
    lunes: Optional[str] = None
    con_ia: bool = True
    solicitado_por: str = "app"


@router.get("/lista")
def lista():
    with engine.connect() as c:
        try:
            filas = c.execute(sa.text("""SELECT id, semana_iso, anio, desde, hasta, titulo, creado_en, creado_por, costo_usd
                                         FROM mrp_informes ORDER BY creado_en DESC LIMIT 60""")).fetchall()
        except Exception:
            return {"informes": []}
    return {"informes": [dict(r._mapping) for r in filas]}


@router.get("/{iid}/html", response_class=HTMLResponse)
def ver_html(iid: int):
    with engine.connect() as c:
        h = c.execute(sa.text("SELECT html FROM mrp_informes WHERE id = :i"), {"i": iid}).scalar()
    if h is None:
        raise HTTPException(404, "Informe no encontrado.")
    return HTMLResponse(h)


@router.post("/generar")
def generar_api(body: SolicitudInforme):
    lunes = date.fromisoformat(body.lunes) if body.lunes else _lunes_anterior(date.today())
    if lunes.weekday() != 0:
        raise HTTPException(422, "La fecha debe ser un lunes.")
    return generar(lunes, body.con_ia, body.solicitado_por)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lunes", help="lunes de la semana (YYYY-MM-DD); por defecto la semana cerrada anterior")
    ap.add_argument("--sin-ia", action="store_true")
    a = ap.parse_args()
    lunes = date.fromisoformat(a.lunes) if a.lunes else _lunes_anterior(date.today())
    r = generar(lunes, not a.sin_ia)
    log.info(f"Informe #{r['id']} · {r['titulo']} · IA={r['ia']} · US$ {r['costo_usd']}")
