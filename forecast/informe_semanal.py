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

SEMANAS_TENDENCIA = 4


def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _lunes_anterior(hoy: date) -> date:
    return hoy - timedelta(days=hoy.weekday() + 7)


# ── 1. Datos ──────────────────────────────────────────────────────────────────
def compilar(lunes: date) -> dict:
    import kpi_operacion as _k
    import analisis_linea as _al
    domingo = lunes + timedelta(days=6)
    semanas = [lunes - timedelta(days=7 * i) for i in range(SEMANAS_TENDENCIA - 1, -1, -1)]
    kp = {s: _k.calcular_semana(s) for s in semanas}
    ult = kp[lunes]
    lineas = []
    for x in ult["lineas"]:
        k = x["kpi"]
        tend = []
        for s in semanas:
            y = next((z for z in kp[s]["lineas"] if z["linea"] == x["linea"]), None)
            tend.append(_r(y["kpi"]["cumplimiento_vs_sap"], 3) if y else None)
        lineas.append({"linea": x["linea"], "categoria": x.get("categoria"),
                       "cumplimiento": _r(k["cumplimiento_vs_sap"], 3), "ocupacion_real": _r(k["ocupacion_real"], 3),
                       "ocupacion_programada": _r(k["ocupacion_programada_sap"], 3), "eficiencia": _r(k["eficiencia"], 3),
                       "cobertura_bitacora": _r(x.get("cobertura_bitacora"), 3),
                       "horas_paradas": _r((x["horas"].get("parada_planificada") or 0) + (x["horas"].get("parada_no_planificada") or 0)),
                       "cumplimiento_4sem": tend})
    resumen = ult["resumen"]
    tendencia = [{"semana": s.isoformat(), "semana_iso": s.isocalendar()[1],
                  "cumplimiento": _r(kp[s]["resumen"]["cumplimiento_global_vs_sap"], 3),
                  "cj_real": _r(kp[s]["resumen"]["cj_real"], 0), "cj_sap": _r(kp[s]["resumen"]["cj_programado_sap"], 0)}
                 for s in semanas]

    with engine.connect() as c:
        plan, piezas, lin_p, sku_lineas, sku_params = _al._cargar_desde_bd(c)
        try:
            demo = _al.capacidad_demostrada(date.today())
        except Exception:
            demo = {}
        carga = _al.calcular_carga(piezas["detalle_diario"], piezas["uso_linea"], piezas["alertas"], lin_p,
                                   sku_lineas, sku_params, 4, demo, piezas.get("entradas_fijas"))
        semaforo = [{"linea": x["linea"], "semaforo": x["semaforo"], "motivos": x["motivos"],
                     "carga_3sem": x["max_carga_requerida_3sem"],
                     "demostrada": (x.get("capacidad_demostrada") or {}).get("top3")} for x in carga["lineas"]]
        # riesgo de quiebre: próximas 4 semanas del plan vigente
        q = defaultdict(lambda: {"dias": 0, "deficit_u": 0.0, "primer": None})
        ini = carga["hoy"]
        fin = (date.fromisoformat(ini) + timedelta(days=28)).isoformat()
        bajo_ss = set()
        for a in piezas["alertas"] or []:
            f = a.get("fecha")
            if not f or not (ini <= f < fin):
                continue
            if a.get("tipo") == "QUIEBRE":
                d = q[a["sku"]]
                d["dias"] += 1
                d["deficit_u"] = max(d["deficit_u"], float(a.get("deficit_u") or 0))
                d["primer"] = min(d["primer"] or f, f)
            elif a.get("tipo") == "BAJO_SS":
                bajo_ss.add(a.get("sku"))
        pref = {}
        for r in sku_lineas:
            if r.get("preferida"):
                pref[r["sku"]] = r["linea"]
        quiebres = sorted(({"sku": s, "descripcion": (sku_params.get(s) or {}).get("descripcion"), "linea": pref.get(s),
                            "mto": bool((sku_params.get(s) or {}).get("mto")), "primer_quiebre": v["primer"], "dias": v["dias"],
                            "deficit_cj": round(v["deficit_u"] / ((sku_params.get(s) or {}).get("u_por_caja") or 1))}
                           for s, v in q.items()), key=lambda z: (z["primer_quiebre"], -z["deficit_cj"]))
        p = {"d": lunes, "h": domingo + timedelta(days=1)}

        def filas(sql, prm=None):
            try:
                return [dict(r._mapping) for r in c.execute(sa.text(sql), prm or p)]
            except Exception:
                c.rollback()
                return []
        casos = filas("""SELECT id, linea, origen, estado, decision, decision_motivo, creado_en,
                                recomendacion->>'resumen' AS resumen, recomendacion->>'causa_principal' AS causa
                         FROM mrp_analisis_casos WHERE creado_en >= :d AND creado_en < :h AND estado <> 'error'
                         ORDER BY creado_en""")
        pendientes = filas("""SELECT a.id, k.linea, a.palanca, a.accion FROM mrp_analisis_acciones a
                              JOIN mrp_analisis_casos k ON k.id = a.caso_id WHERE a.estado = 'aceptada' ORDER BY a.creado_en""", {})
        cambios = filas("""SELECT campo, count(*) AS n, count(DISTINCT COALESCE(sku, linea)) AS elementos,
                                  string_agg(DISTINCT editor, ', ') AS editores
                           FROM mrp_params_historial WHERE ts >= :d AND ts < :h AND revertido_por IS NULL
                           GROUP BY campo ORDER BY n DESC""")
        interv = filas("""SELECT palanca, linea, veredicto, aprendizaje FROM mrp_intervenciones
                          WHERE evaluado_en >= :d AND evaluado_en < :h ORDER BY evaluado_en""")
        bitacora = filas("""SELECT e.linea, t.categoria, count(*) AS eventos, COALESCE(sum(e.duracion_min), 0) AS minutos
                            FROM mrp_eventos_linea e JOIN mrp_eventos_tipos t ON t.codigo = e.tipo
                            WHERE NOT e.anulado AND e.fecha >= :d AND e.fecha < :h GROUP BY 1, 2 ORDER BY 1, 2""")
        capacidad = filas("""SELECT clave AS linea, valor_empirico AS mejores, p50 AS normal, confianza
                             FROM mrp_conocimiento_empirico WHERE entidad = 'linea' AND metrica = 'capacidad_semanal_pct'
                             ORDER BY valor_empirico DESC""", {})
    return {
        "semana": {"desde": lunes.isoformat(), "hasta": domingo.isoformat(), "iso": lunes.isocalendar()[1], "anio": lunes.isocalendar()[0]},
        "plan": {"id": plan.id, "creado": plan.created_at.isoformat()},
        "kpi": {"cumplimiento": _r(resumen["cumplimiento_global_vs_sap"], 3), "cj_real": _r(resumen["cj_real"], 0),
                "cj_sap": _r(resumen["cj_programado_sap"], 0), "adopcion_app": _r(resumen["adopcion_app_sobre_sap"], 3),
                "skus_quiebre_4sem": len(quiebres), "skus_bajo_ss_4sem": len(bajo_ss),
                "lineas_rojo": sum(1 for x in semaforo if x["semaforo"] == "rojo"),
                "lineas_con_bitacora": resumen.get("lineas_con_bitacora"), "lineas_total": resumen.get("lineas_total")},
        "tendencia": tendencia, "lineas": lineas, "semaforo": semaforo, "quiebres": quiebres[:20],
        "casos": casos, "acciones_pendientes": pendientes, "cambios_parametros": cambios,
        "intervenciones_evaluadas": interv, "bitacora": bitacora, "capacidad_demostrada": capacidad,
    }


# ── 2. Lectura IA ─────────────────────────────────────────────────────────────
SYSTEM_IA = """Eres el analista de operaciones de Traverso (alimentos, Chile) y escribes el informe semanal de
producción para gerencia y planificación. Recibes datos ya calculados por el sistema.
Reglas:
- Usa SOLO las cifras de los datos; no recalcules ni inventes. Cita la semana o la línea de cada cifra.
- El objetivo supremo es evitar quiebres de stock.
- Las recomendaciones son "analizar..." o "revisar...", nunca órdenes. Máximo 4, priorizadas.
- Menciona los límites de los datos cuando importen (p. ej. poca cobertura de la bitácora).
- Español claro, sin jerga del sistema. Frases cortas.
Responde SOLO con un JSON válido:
{"titulo": "...", "resumen_ejecutivo": "3 a 5 frases",
 "alertas": [{"severidad": "critica|alta|media", "titulo": "...", "detalle": "...", "accion": "..."}],
 "recomendaciones": [{"titulo": "...", "detalle": "...", "responsable": "Planificación|Producción|Comercial|Gerencia"}],
 "lecturas": {"cumplimiento": "...", "ocupacion": "...", "riesgo": "...", "decisiones": "...", "aprendizaje": "..."}}"""


def lectura_ia(datos: dict) -> dict:
    try:
        import claude_api as _ca
        if not _ca.configurado():
            return {"disponible": False, "motivo": "API de Claude no configurada."}
        r = _ca.generar(SYSTEM_IA, "DATOS DE LA SEMANA:\n" + json.dumps(datos, ensure_ascii=False, default=str), max_tokens=12000)
        t = r["texto"].strip()
        i, j = t.find("{"), t.rfind("}")
        out = json.loads(t[i:j + 1])
        out["_meta"] = {k: r[k] for k in ("modelo", "tokens_in", "tokens_out", "costo_usd", "segundos")}
        out["disponible"] = True
        return out
    except Exception as e:
        log.error(f"Lectura IA no disponible: {e}")
        return {"disponible": False, "motivo": str(e)[:300]}


# ── 3. HTML ───────────────────────────────────────────────────────────────────
def _e(x):
    return _h.escape("" if x is None else str(x))


def _pct(v):
    return "–" if v is None else f"{v * 100:.0f}%"


def _n(v):
    return "–" if v is None else f"{v:,.0f}".replace(",", ".")


def _celda_cumpl(v):
    if v is None:
        return '<td class="num muted">–</td>'
    cls = "bad" if v < 0.7 else ("warn" if v < 0.9 or v > 1.3 else "ok")
    return f'<td class="num h {cls}">{_pct(v)}</td>'


def render_html(datos: dict, ia: dict) -> str:
    s = datos["semana"]
    k = datos["kpi"]
    titulo = ia.get("titulo") if ia.get("disponible") else f"Informe de Operación · Sem {s['iso']}"
    sev = {"critica": "Crítica", "alta": "Alta", "media": "Media"}
    alertas = "".join(f'<div class="alerta {a.get("severidad", "media")}"><div class="sev">{_e(sev.get(a.get("severidad"), a.get("severidad")))}</div>'
                      f'<b>{_e(a.get("titulo"))}</b><p>{_e(a.get("detalle"))}</p><p class="acc">→ {_e(a.get("accion"))}</p></div>'
                      for a in (ia.get("alertas") or []))
    recs = "".join(f'<li><b>{_e(r.get("titulo"))}</b> <span class="muted">· {_e(r.get("responsable"))}</span><br>{_e(r.get("detalle"))}</li>'
                   for r in (ia.get("recomendaciones") or []))
    lec = ia.get("lecturas") or {}
    sems = [f"S{t['semana_iso']}" for t in datos["tendencia"]]
    filas_lin = "".join(
        f'<tr><td><b>{_e(x["linea"])}</b></td>{"".join(_celda_cumpl(v) for v in x["cumplimiento_4sem"])}'
        f'<td class="num">{_pct(x["ocupacion_real"])}</td><td class="num">{_pct(x["eficiencia"])}</td>'
        f'<td class="num">{_pct(x["cobertura_bitacora"])}</td></tr>'
        for x in sorted(datos["lineas"], key=lambda z: (z["cumplimiento"] is None, z["cumplimiento"] or 0)))
    tend = "".join(f'<div class="barra"><div class="b" style="height:{min(100, (t["cumplimiento"] or 0) * 80):.0f}px"></div>'
                   f'<span>{_pct(t["cumplimiento"])}</span><small>S{t["semana_iso"]}</small></div>' for t in datos["tendencia"])
    SEM = {"rojo": ("bad", "No cumple"), "ambar": ("warn", "En riesgo"), "verde": ("ok", "OK")}
    filas_sem = "".join(
        f'<tr><td><b>{_e(x["linea"])}</b></td><td><span class="pill {SEM[x["semaforo"]][0]}">{SEM[x["semaforo"]][1]}</span></td>'
        f'<td class="num">{_pct(x["carga_3sem"])}</td><td class="num">{_pct(x["demostrada"])}</td><td class="small">{_e(" ".join(x["motivos"]))}</td></tr>'
        for x in datos["semaforo"] if x["semaforo"] != "verde")
    filas_q = "".join(
        f'<tr><td>{_e(q["sku"])}</td><td>{_e(q["descripcion"])}{" <span class=pill>MTO</span>" if q["mto"] else ""}</td><td>{_e(q["linea"])}</td>'
        f'<td class="num">{_e((q["primer_quiebre"] or "")[8:10] + "-" + (q["primer_quiebre"] or "")[5:7])}</td><td class="num">{q["dias"]}</td>'
        f'<td class="num">{_n(q["deficit_cj"])}</td></tr>' for q in datos["quiebres"])
    filas_casos = "".join(
        f'<tr><td>#{c["id"]}</td><td>{_e(c["linea"])}</td><td>{_e(c["origen"])}</td><td>{_e(c["decision"] or "pendiente")}</td>'
        f'<td class="small">{_e(c["causa"] or c["resumen"] or "")}</td></tr>' for c in datos["casos"])
    filas_cambios = "".join(f'<tr><td>{_e(c["campo"])}</td><td class="num">{c["n"]}</td><td class="num">{c["elementos"]}</td><td>{_e(c["editores"])}</td></tr>'
                            for c in datos["cambios_parametros"])
    filas_iv = "".join(f'<tr><td>{_e(i["palanca"])}</td><td>{_e(i["linea"])}</td><td>{_e(i["veredicto"])}</td><td class="small">{_e(i["aprendizaje"])}</td></tr>'
                       for i in datos["intervenciones_evaluadas"])
    meta = ia.get("_meta") or {}
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(titulo)}</title>
<style>
:root{{--bg:#F8F7F4;--card:#fff;--text:#2C2C2A;--muted:#888780;--line:#D3D1C7;--teal:#1D9E75;--ok:#E1F5EE;--okt:#0F6E56;
--warn:#FAEEDA;--warnt:#854F0B;--bad:#FCEBEB;--badt:#A32D2D;--purple:#534AB7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1d1d1b;--card:#262624;--text:#ecebe6;--muted:#a3a29b;--line:#45443f;
--ok:#173d31;--okt:#8fd9bf;--warn:#4a3a1c;--warnt:#f2cc8a;--bad:#4d2424;--badt:#f5a3a3;--purple:#a79ff0}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Arial,Helvetica,sans-serif}}
.wrap{{max-width:1500px;margin:0 auto;padding:18px}}
h1{{font-size:24px;margin:0 0 2px}} h2{{font-size:17px;margin:0 0 6px}} .muted{{color:var(--muted)}} .small{{font-size:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}} .kpi{{flex:1 1 150px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.kpi b{{display:block;font-size:22px}} .kpi span{{font-size:12px;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(460px,100%),1fr));gap:12px}}
.alertas{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:10px}}
.alerta{{border:1px solid var(--line);border-left:5px solid var(--warnt);border-radius:8px;padding:10px;background:var(--card)}}
.alerta.critica{{border-left-color:var(--badt)}} .alerta.media{{border-left-color:var(--purple)}}
.alerta p{{margin:4px 0;font-size:13px}} .alerta .acc{{color:var(--okt)}} .sev{{font-size:11px;text-transform:uppercase;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}} th{{text-align:left;color:var(--muted);font-size:11px;border-bottom:1px solid var(--line);padding:5px 6px}}
td{{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}} .num{{text-align:right;white-space:nowrap}}
.h.ok{{background:var(--ok);color:var(--okt)}} .h.warn{{background:var(--warn);color:var(--warnt)}} .h.bad{{background:var(--bad);color:var(--badt)}}
.pill{{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:9px;background:var(--line)}}
.pill.ok{{background:var(--ok);color:var(--okt)}} .pill.warn{{background:var(--warn);color:var(--warnt)}} .pill.bad{{background:var(--bad);color:var(--badt)}}
.barras{{display:flex;gap:14px;align-items:flex-end;height:120px;padding-top:6px}} .barra{{display:flex;flex-direction:column;align-items:center;font-size:12px}}
.barra .b{{width:34px;background:var(--teal);border-radius:4px 4px 0 0}} .barra small{{color:var(--muted)}}
.scroll{{overflow-x:auto}} ul{{margin:4px 0 0 18px;padding:0}} li{{margin-bottom:6px}}
@media print{{@page{{size:A4 landscape;margin:10mm}} body{{background:#fff}} .card,.kpi,.alerta{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
<div class="muted small">TRAVERSO · PLANIFICACIÓN DE PRODUCCIÓN · INFORME AUTOMÁTICO</div>
<h1>{_e(titulo)}</h1>
<div class="muted">Semana {s['iso']} · {s['desde'][8:10]}-{s['desde'][5:7]} al {s['hasta'][8:10]}-{s['hasta'][5:7]}-{s['anio']} · Plan vigente #{datos['plan']['id']}</div>
<div class="kpis">
 <div class="kpi"><span>Cumplimiento vs SAP</span><b>{_pct(k['cumplimiento'])}</b><span>{_n(k['cj_real'])} de {_n(k['cj_sap'])} cj</span></div>
 <div class="kpi"><span>Adopción del plan de la app</span><b>{_pct(k['adopcion_app'])}</b><span>de lo programado en SAP</span></div>
 <div class="kpi"><span>SKU con quiebre proyectado</span><b>{k['skus_quiebre_4sem']}</b><span>próximas 4 semanas</span></div>
 <div class="kpi"><span>SKU bajo SS</span><b>{k['skus_bajo_ss_4sem']}</b><span>stock de seguridad, próx. 4 sem</span></div>
 <div class="kpi"><span>Líneas que no cumplen</span><b>{k['lineas_rojo']}</b><span>semáforo del Análisis de Línea</span></div>
 <div class="kpi"><span>Líneas con bitácora</span><b>{k['lineas_con_bitacora']} / {k['lineas_total']}</b><span>registro de detenciones</span></div>
</div>
<div class="card"><h2>Resumen ejecutivo</h2><p>{_e(ia.get('resumen_ejecutivo') or 'Lectura IA no disponible: el informe muestra solo los datos.')}</p></div>
{f'<div class="card"><h2>Alertas</h2><div class="alertas">{alertas}</div></div>' if alertas else ''}
{f'<div class="card"><h2>Recomendaciones (a analizar)</h2><ul>{recs}</ul></div>' if recs else ''}
<div class="grid">
 <div class="card"><h2>Cumplimiento: tendencia</h2><p class="small muted">{_e(lec.get('cumplimiento'))}</p><div class="barras">{tend}</div></div>
 <div class="card"><h2>Riesgo de quiebre (plan vigente, 4 semanas)</h2><p class="small muted">{_e(lec.get('riesgo'))}</p>
  <div class="scroll"><table><tr><th>SKU</th><th>Producto</th><th>Línea</th><th class="num">Desde</th><th class="num">Días</th><th class="num">Déficit cj</th></tr>{filas_q or '<tr><td colspan=6 class=muted>Sin quiebres proyectados.</td></tr>'}</table></div></div>
</div>
<div class="card"><h2>Cumplimiento y ocupación por línea</h2><p class="small muted">{_e(lec.get('ocupacion'))}</p>
 <div class="scroll"><table><tr><th>Línea</th>{''.join(f'<th class="num">{x}</th>' for x in sems)}<th class="num">Ocupación real</th><th class="num">Eficiencia</th><th class="num">Bitácora</th></tr>{filas_lin}</table></div>
 <p class="small muted">Cumplimiento = cajas producidas ÷ programadas en SAP. Eficiencia solo en días con registro en la bitácora. Rojo &lt; 70%, ámbar 70–90% o &gt; 130%.</p></div>
<div class="grid">
 <div class="card"><h2>Líneas que no cumplen o están en riesgo</h2>
  <div class="scroll"><table><tr><th>Línea</th><th>Estado</th><th class="num">Carga 3 sem</th><th class="num">Demostrada</th><th>Motivo</th></tr>{filas_sem or '<tr><td colspan=5 class=muted>Todas las líneas en verde.</td></tr>'}</table></div></div>
 <div class="card"><h2>Análisis y decisiones de la semana</h2><p class="small muted">{_e(lec.get('decisiones'))}</p>
  <div class="scroll"><table><tr><th>Caso</th><th>Línea</th><th>Origen</th><th>Decisión</th><th>Causa</th></tr>{filas_casos or '<tr><td colspan=5 class=muted>Sin casos esta semana.</td></tr>'}</table></div>
  <p class="small">Acciones aceptadas pendientes: <b>{len(datos['acciones_pendientes'])}</b></p></div>
</div>
<div class="grid">
 <div class="card"><h2>Cambios de parámetros</h2><table><tr><th>Campo</th><th class="num">Cambios</th><th class="num">SKU o líneas</th><th>Quién</th></tr>{filas_cambios or '<tr><td colspan=4 class=muted>Sin cambios.</td></tr>'}</table></div>
 <div class="card"><h2>Lo aprendido esta semana</h2><p class="small muted">{_e(lec.get('aprendizaje'))}</p>
  <table><tr><th>Palanca</th><th>Línea</th><th>Veredicto</th><th>Lección</th></tr>{filas_iv or '<tr><td colspan=4 class=muted>Sin intervenciones evaluadas esta semana.</td></tr>'}</table></div>
</div>
<p class="small muted">Generado automáticamente por el Sistema de Planificación de Producción. Las cifras provienen del motor de KPIs, del plan vigente
y de los registros de la app; la lectura y las recomendaciones son de IA{f" ({_e(meta.get('modelo'))}, US$ {meta.get('costo_usd')})" if meta else ""} y deben validarse con Producción.
Para PDF: imprimir desde el navegador (A4 apaisado).</p>
</div></body></html>"""


# ── 4. Guardado y API ─────────────────────────────────────────────────────────
def generar(lunes: date, con_ia: bool = True, creado_por: str = "Sistema (automático)") -> dict:
    datos = compilar(lunes)
    ia = lectura_ia(datos) if con_ia else {"disponible": False, "motivo": "Generado sin IA."}
    html_ = render_html(datos, ia)
    titulo = ia.get("titulo") if ia.get("disponible") else f"Informe de Operación · Sem {datos['semana']['iso']}"
    with engine.begin() as c:
        iid = c.execute(sa.text("""INSERT INTO mrp_informes (semana_iso, anio, desde, hasta, titulo, html, datos, ia, costo_usd, creado_por)
                                   VALUES (:s, :a, :d, :h, :t, :html, CAST(:dat AS JSONB), CAST(:ia AS JSONB), :c, :p) RETURNING id"""),
                        {"s": datos["semana"]["iso"], "a": datos["semana"]["anio"], "d": datos["semana"]["desde"],
                         "h": datos["semana"]["hasta"], "t": titulo, "html": html_, "dat": json.dumps(datos, default=str),
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
