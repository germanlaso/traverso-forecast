"""
analisis_diagnostico.py — Análisis de Línea (MVP 1). Pieza 2: DIAGNÓSTICO + PALANCAS + IA + CASO.

Flujo de "Analizar línea" (inmediato):
  1. Síntomas: carga requerida vs programada vs demostrada (analisis_linea.calcular_carga).
  2. Diagnóstico determinista: causas clasificadas con evidencia.
  3. Palancas en ORDEN DE ESFUERZO (decisión 11-11-26), modelo analítico de horas (acumulativas:
     cada nivel suma a los anteriores; se informa el primer nivel cuya combinación cubre la necesidad):
        1 parámetros (batch / cap. bodega)  2 extensión de turno / turno adicional
        3 línea alternativa                 4 ampliación (brecha estructural, no se simula)
     Se marca la primera palanca que cubre el déficit.
  4. Recomendación IA (Claude): explica en lenguaje de planta, usando además lo aprendido
     (mrp_intervenciones evaluadas y casos anteriores de la línea).
  5. Todo queda en mrp_analisis_casos (aprendizaje). Nunca aplica cambios: las acciones de
     parámetros se envían al panel como recomendaciones, con la decisión humana.

Modelo analítico (MVP 1, declarado en cada caso): balance de horas por semana sobre la línea
preferida; no modela secuencia ni campañas. La validación con solver queda para el análisis
programado (MVP 2).
"""
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import analisis_linea as _al
from db_mrp import engine as _engine

router = APIRouter(prefix="/analisis", tags=["Analisis de linea"])

UMBRAL_LINEA_ALT = 0.80      # una línea alternativa debe quedar bajo este uso tras absorber
HORIZONTE_SEM = _al.SEMANAS_ALERTA


# ── Carga de datos ────────────────────────────────────────────────────────────
def _datos(c):
    plan, piezas, lineas, sku_lineas, sku_params = _al._cargar_desde_bd(c)
    piezas["ofts"] = c.execute(sa.text("SELECT snapshot->'ofts' FROM mrp_planes WHERE id = :i"),
                               {"i": plan.id}).scalar() or []
    full = {r.sku: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params"))}
    return plan, piezas, lineas, sku_lineas, full


def _familia(codigo: str) -> str:
    """Doypack 2 -> doypack · Sachetera 4P -> sachetera · L2Pet LV -> lpet (hipótesis de compatibilidad)."""
    c = codigo.lower()
    if c.startswith("doypack"):
        return "doypack"
    if c.startswith("sachetera"):
        return "sachetera"
    if re.match(r"l\d+pet", c):
        return "lpet"
    return c


# ── Diagnóstico + palancas (núcleo puro) ──────────────────────────────────────
def diagnosticar(linea: str, carga: dict, piezas: dict, lineas: dict, sku_lineas: list, params: dict) -> dict:
    ln = next((x for x in carga["lineas"] if x["linea"] == linea), None)
    if ln is None:
        raise ValueError(f"Línea sin datos: {linea}")
    L = lineas[linea]
    h_dia = float(L["turnos_dia"] or 0) * float(L["horas_turno"] or 0)
    vel_l = float(L["velocidad_u_hr"] or 0)
    hoy = date.fromisoformat(carga["hoy"])
    evaluables = [f for f in ln["semanas"] if f["dias_habiles"] >= 3][:HORIZONTE_SEM]
    fin = date.fromisoformat(evaluables[-1]["semana"]) + timedelta(days=6) if evaluables else hoy + timedelta(days=20)

    fac = {(r["sku"], r["linea"]): float(r.get("factor_velocidad") or 1) for r in sku_lineas}
    lineas_sku = defaultdict(list)
    for r in sku_lineas:
        lineas_sku[r["sku"]].append(r["linea"])

    def vel(sku, lin=linea):
        return float(lineas[lin]["velocidad_u_hr"] or 0) * fac.get((sku, lin), 1.0)

    # SKU en quiebre (no MTO) y su déficit en horas de línea
    # déficit máximo DENTRO del horizonte de análisis (los quiebres de fin de plan no dimensionan palancas)
    def_ventana = defaultdict(float)
    for a in piezas.get("alertas") or []:
        if a.get("tipo") == "QUIEBRE" and a.get("fecha") and hoy.isoformat() <= a["fecha"] <= fin.isoformat():
            def_ventana[a["sku"]] = max(def_ventana[a["sku"]], float(a.get("deficit_u") or 0))
    qs = [{**q, "deficit_u": def_ventana[q["sku"]],
           "deficit_cj": round(def_ventana[q["sku"]] / ((params.get(q["sku"], {}) or {}).get("u_por_caja") or 1))}
          for q in ln["quiebres"].get("capacidad", []) + ln["quiebres"].get("inmediato", [])
          if q["primer_quiebre"] <= fin.isoformat()]
    skus_q = []
    for q in qs:
        p = params.get(q["sku"], {})
        v = vel(q["sku"]) or vel_l
        bmin = float(p.get("batch_min_u") or 0)
        skus_q.append({**q, "deficit_h": round(q["deficit_u"] / v, 1) if v else None,
                       "batch_min_u": bmin, "batch_h": round(bmin / v, 1) if v else None,
                       "u_por_caja": p.get("u_por_caja"), "lineas_asignadas": lineas_sku.get(q["sku"], []),
                       "cap_bodega_u": p.get("cap_bodega_u"), "ss_dias": p.get("ss_dias")})
    deficit_h = round(sum(x["deficit_h"] or 0 for x in skus_q), 1)

    # Fragmentación: horas libres en días hábiles con algo programado, que no alcanzan para el batch.
    # Incluye las OF aprobadas (no están en uso_linea), con su SKU desde mrp_ordenes (o u/caja mediano si falta).
    uso = piezas["uso_linea"].get(linea, {}) or {}
    _upcs = sorted(float((params.get(r["sku"]) or {}).get("u_por_caja") or 1) for r in sku_lineas if r["linea"] == linea)
    _upc_med = _upcs[len(_upcs) // 2] if _upcs else 1.0
    h_aprob_dia = defaultdict(float)
    for e in piezas.get("entradas_fijas") or []:
        if e.get("linea") == linea and e.get("fecha_lanzamiento") and vel_l:
            sk = e.get("sku")
            upc_e = float((params.get(sk) or {}).get("u_por_caja") or 0) if sk else 0.0
            vel_e = vel(sk) if sk else vel_l
            h_aprob_dia[e["fecha_lanzamiento"]] += float(e.get("cantidad_cajas") or 0) * (upc_e or _upc_med) / (vel_e or vel_l)
    batch_q = min([x["batch_h"] for x in skus_q if x["batch_h"]] or [h_dia])
    restos, restos_inutiles, dias_libres = 0.0, 0.0, 0
    d = hoy
    while d <= fin:
        if d.weekday() < int(L["dias_semana"] or 5):
            u = min(1.0, float(uso.get(d.isoformat(), 0) or 0) / 100.0 + h_aprob_dia.get(d.isoformat(), 0.0) / (h_dia or 1))
            libre = max(0.0, 1 - u) * h_dia
            if u <= 0.01:
                dias_libres += 1
            restos += libre
            if 0 < libre < batch_q:
                restos_inutiles += libre
        d += timedelta(days=1)

    # Horas por semana: déficit de capacidad nominal
    sobrecarga = [{"semana_iso": f["semana_iso"], "horas_extra": round(max(0.0, f["horas_requeridas"] - f["horas_nominales"]), 1)}
                  for f in evaluables]
    horas_extra_sem = max([s["horas_extra"] for s in sobrecarga] or [0])
    demo = ln.get("capacidad_demostrada") or {}
    cap_nom_sem = h_dia * int(L["dias_semana"] or 5)
    holgura_demostrada_h = max(0.0, (demo.get("top3") or 1.0) - 1.0) * cap_nom_sem   # horas/sem extra ya demostradas

    # OF del plan en la línea (granularidad real del plan)
    ofs = [o for o in piezas.get("ofts", []) if o["linea"] == linea and hoy.isoformat() <= o["fecha_lanzamiento"] <= fin.isoformat()]
    h_of = [o["cantidad_unidades"] / (vel(o["sku"]) or vel_l) for o in ofs if vel(o["sku"]) or vel_l]

    # ── Causas ────────────────────────────────────────────────────────────────
    causas = []
    mc = ln["max_carga_requerida_3sem"]
    if mc > _al.UMBRAL_ROJO:
        if demo.get("top3") and mc <= demo["top3"]:
            causas.append({"codigo": "CAPACIDAD_PARAMETRIZADA", "titulo": "La capacidad real alcanza; la parametrizada no",
                           "evidencia": f"Carga requerida {mc:.0%} vs capacidad demostrada {demo['top3']:.0%} (promedio 3 mejores semanas). El plan usa 1 turno nominal."})
        else:
            causas.append({"codigo": "CAPACIDAD", "titulo": "La demanda supera la capacidad de la línea",
                           "evidencia": f"Carga requerida {mc:.0%}; capacidad demostrada {demo.get('top3', 0):.0%}."})
    gruesos = [x for x in skus_q if x["batch_h"] and x["batch_h"] >= 0.8 * h_dia]
    if gruesos or (deficit_h and restos_inutiles >= 0.5 * deficit_h):
        causas.append({"codigo": "GRANULARIDAD", "titulo": "Batch del tamaño de un día completo",
                       "evidencia": f"{len(gruesos)} SKU en quiebre con batch ≥ 80% del turno; {restos_inutiles:.0f} h libres en restos de día que no alcanzan para un batch."})
    sin_alt = [x["sku"] for x in skus_q if len(x["lineas_asignadas"]) <= 1]
    if sin_alt:
        causas.append({"codigo": "SIN_ALTERNATIVA", "titulo": "SKU en quiebre sin línea alternativa",
                       "evidencia": f"{len(sin_alt)} de {len(skus_q)} SKU en quiebre solo pueden correr en {linea}."})
    if ln["quiebres"].get("inmediato"):
        causas.append({"codigo": "PEDIDOS", "titulo": "Quiebres inmediatos por pedidos sobre stock",
                       "evidencia": f"{len(ln['quiebres']['inmediato'])} SKU con quiebre en la semana 1."})
    if (ln.get("reposicion_ss") or {}).get("pct_capacidad_3sem", 0) > 0.3:
        causas.append({"codigo": "SS_ELEVADO", "titulo": "Reponer el SS exige mucha capacidad",
                       "evidencia": f"Reponer el SS (stock de seguridad) requiere {ln['reposicion_ss']['horas']} h = {ln['reposicion_ss']['pct_capacidad_3sem']:.0%} de 3 semanas de línea."})
    if skus_q and mc < _al.UMBRAL_AMBAR and not gruesos:
        causas.append({"codigo": "PRIORIDAD_SOLVER", "titulo": "Quiebre con capacidad disponible",
                       "evidencia": f"Carga {mc:.0%} pero hay quiebres: revisar prioridad o secuencia en el plan."})

    # ── Palancas en orden de esfuerzo (modelo analítico, horas TOTALES del horizonte) ──
    n_sem = max(1, len(evaluables))
    necesidad_h = round(max(deficit_h, sum(s_["horas_extra"] for s_ in sobrecarga)), 1)
    palancas, acumulado = [], 0.0

    def _agregar(p, aporte_h):
        nonlocal acumulado
        acumulado += max(0.0, aporte_h)
        p["aporte_h"] = round(max(0.0, aporte_h), 1)
        p["acumulado_h"] = round(acumulado, 1)
        p["cubre_acumulado"] = necesidad_h > 0 and acumulado >= necesidad_h - 1e-6
        palancas.append(p)

    # 1. Parámetros: batch a medio día recupera restos de día inutilizables
    rec_batch = min(restos_inutiles, necesidad_h) if gruesos else 0.0
    _agregar({
        "nivel": 1, "palanca": "parametros", "titulo": "Reducir batch mínimo (prueba: medio día)",
        "skus": [{"sku": x["sku"], "descripcion": x["descripcion"], "batch_actual_u": x["batch_min_u"],
                  "batch_propuesto_u": round(x["batch_min_u"] / 2 / (x["u_por_caja"] or 1)) * (x["u_por_caja"] or 1)}
                 for x in gruesos],
        "costo": f"+{len(gruesos)} cambios de SKU aprox. por ciclo" if gruesos else "—",
        "nota": ("Recupera restos de día que hoy no alcanzan para un batch. Mínimo técnico real pendiente de Producción."
                 if gruesos else "No aplica: no hay batch grueso en los SKU en quiebre."),
    }, rec_batch)
    # 2. Turnos: hasta lo ya demostrado; si no hay historia, hasta +25% razonable (≈ +2 h/día)
    tope_turno_sem = max(holgura_demostrada_h, 0.25 * cap_nom_sem)
    falta = max(0.0, necesidad_h - acumulado)
    aporte_t = min(falta, tope_turno_sem * n_sem)
    _agregar({
        "nivel": 2, "palanca": "turnos", "titulo": "Extensión de turno o turno adicional",
        "horas_semana": round(aporte_t / n_sem, 1),
        "equivale_a": (f"{aporte_t / n_sem / max(1, int(L['dias_semana'] or 5)):.1f} h extra por día "
                       f"o {aporte_t / n_sem / h_dia:.1f} sábados por semana") if h_dia else "—",
        "ya_demostrado_h_sem": round(holgura_demostrada_h, 1),
        "costo": f"{aporte_t:.0f} h de línea en {n_sem} semanas",
        "nota": ("La línea ya sostuvo esa capacidad en sus mejores semanas." if aporte_t / n_sem <= holgura_demostrada_h + 1e-6
                 else "Supera lo que la línea ha demostrado sostener: confirmar dotación con Producción."),
    }, aporte_t)
    # 3. Línea alternativa: asignadas no preferidas o misma familia (hipótesis)
    candidatas = []
    for x in carga["lineas"]:
        if x["linea"] == linea or _familia(x["linea"]) != _familia(linea):
            continue
        Lx = lineas[x["linea"]]
        cap_x = float(Lx["turnos_dia"] or 0) * float(Lx["horas_turno"] or 0) * int(Lx["dias_semana"] or 5)
        libre = max(0.0, UMBRAL_LINEA_ALT - x["max_carga_requerida_3sem"]) * cap_x
        asignada = any(x["linea"] in s_["lineas_asignadas"] for s_ in skus_q)
        candidatas.append({"linea": x["linea"], "carga_3sem": x["max_carga_requerida_3sem"], "horas_libres_sem": round(libre, 1),
                           "estado": "asignada" if asignada else "hipótesis (requiere validar formato)"})
    candidatas.sort(key=lambda z: -z["horas_libres_sem"])
    falta = max(0.0, necesidad_h - acumulado)
    aporte_a = min(falta, sum(z["horas_libres_sem"] for z in candidatas[:2]) * n_sem)
    _agregar({
        "nivel": 3, "palanca": "linea_alternativa", "titulo": "Mover SKU a una línea alternativa",
        "candidatas": candidatas[:3],
        "costo": "Validar compatibilidad de formato y cambios en la línea receptora",
        "nota": "Las líneas sin asignación previa son hipótesis por familia de línea." if candidatas else "No hay líneas de la misma familia.",
    }, aporte_a)
    # 4. Ampliación: lo que queda
    brecha = max(0.0, necesidad_h - acumulado)
    _agregar({
        "nivel": 4, "palanca": "ampliacion", "titulo": "Ampliación de capacidad (brecha estructural)",
        "horas_semana_faltantes": round(brecha / n_sem, 1),
        "equivale_a": f"{brecha / n_sem / h_dia:.1f} turnos-día por semana" if h_dia else "—",
        "costo": "Inversión",
        "nota": "Solo se informa: base para evaluar inversión." if brecha > 0 else "No hay brecha estructural con las palancas 1 a 3.",
    }, brecha)
    primera = next((p["nivel"] for p in palancas if p["cubre_acumulado"]), None)

    return {
        "linea": linea, "hoy": carga["hoy"], "semaforo": ln["semaforo"], "motivos": ln["motivos"],
        "metodo": "Modelo analítico de horas (MVP 1): no modela secuencia ni campañas; validar con el plan.",
        "sintomas": {"max_carga_requerida_3sem": mc, "capacidad_demostrada": demo, "semanas": evaluables,
                     "reposicion_ss": ln.get("reposicion_ss"), "parametros_linea": ln["parametros"]},
        "evidencia": {"skus_quiebre": skus_q, "deficit_h": deficit_h, "horas_extra_semana": horas_extra_sem,
                      "necesidad_h_horizonte": necesidad_h, "semanas_horizonte": n_sem,
                      "restos_libres_h": round(restos, 1), "restos_inutiles_h": round(restos_inutiles, 1),
                      "dias_sin_programa": dias_libres, "of_plan": {"n": len(ofs), "setups": sum(1 for o in ofs if o.get("paga_setup")),
                      "horas_promedio": round(sum(h_of) / len(h_of), 1) if h_of else None}},
        "causas": causas, "palancas": palancas,
        "primera_palanca_suficiente": primera,   # primer nivel en que las palancas 1..n acumuladas cubren la necesidad
    }


# ── Recomendación IA ──────────────────────────────────────────────────────────
SYSTEM_IA = """Eres el analista de planificación de producción de Traverso (alimentos, Chile).
Recibes el diagnóstico de UNA línea de producción, calculado por el sistema, y lo aprendido de casos anteriores.
Reglas:
- No recalcules cifras: usa solo las que vienen en los datos y cita de dónde sale cada afirmación.
- El objetivo supremo es evitar quiebres de stock.
- Recomienda en orden de esfuerzo: 1 parámetros, 2 extensión de turno o turno adicional, 3 línea alternativa, 4 ampliación.
  Si una palanca de menor esfuerzo basta, no recomiendes las de mayor esfuerzo como primera acción.
- Si las señales sugieren que el problema puede venir del forecast (SKU nuevo, poca historia, picos de lanzamiento,
  forecast muy por encima de lo vendido), dilo explícitamente antes de proponer mover capacidad.
- Usa lo aprendido (intervenciones evaluadas) cuando aplique, citándolo.
- Lenguaje claro para un planificador o un jefe de producción, sin jerga técnica del sistema.
- Máximo 3 acciones. Nunca afirmes que algo se aplicó: el sistema solo recomienda.
Responde SOLO con un objeto JSON válido, sin texto antes ni después, con esta forma:
{"resumen": "2-3 frases", "causa_principal": "...", "explicacion": "párrafo breve",
 "alerta_forecast": "texto o null",
 "acciones": [{"orden": 1, "palanca": "parametros|turnos|linea_alternativa|ampliacion|forecast|otro",
               "accion": "...", "efecto_esperado": "...", "costo_o_riesgo": "...",
               "cambios_parametros": [{"sku": "...", "campo": "batch_min_u|cap_bodega_u", "valor": 0}]}],
 "supuestos": ["..."], "pregunta_para_produccion": "texto o null"}"""


def _aprendizaje(c, linea):
    inter = [dict(r._mapping) for r in c.execute(sa.text("""
        SELECT palanca, linea, veredicto, aprendizaje, contexto FROM mrp_intervenciones
        WHERE veredicto <> 'pendiente' ORDER BY evaluado_en DESC NULLS LAST LIMIT 10"""))]
    casos = [dict(r._mapping) for r in c.execute(sa.text("""
        SELECT creado_en::date AS fecha, recomendacion->>'resumen' AS resumen, decision, decision_motivo
        FROM mrp_analisis_casos WHERE linea = :l AND estado NOT IN ('error') ORDER BY creado_en DESC LIMIT 3"""), {"l": linea})]
    return {"intervenciones_evaluadas": inter, "casos_anteriores_linea": casos}


def _json_de(texto: str) -> dict:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


def recomendar_ia(diag: dict, aprendizaje: dict) -> dict:
    import claude_api as _ca
    if not _ca.configurado():
        return {"disponible": False, "motivo": "API de Claude no configurada."}
    usuario = ("DIAGNÓSTICO DE LA LÍNEA (calculado por el sistema):\n" + json.dumps(diag, ensure_ascii=False, default=str)
               + "\n\nLO APRENDIDO HASTA HOY:\n" + json.dumps(aprendizaje, ensure_ascii=False, default=str))
    r = _ca.generar(SYSTEM_IA, usuario, max_tokens=8000)
    try:
        out = _json_de(r["texto"])
    except Exception:
        out = {"resumen": r["texto"][:1500], "acciones": [], "formato_invalido": True}
    out["_meta"] = {k: r[k] for k in ("modelo", "tokens_in", "tokens_out", "costo_usd", "segundos")}
    out["disponible"] = True
    return out


# ── Endpoints ─────────────────────────────────────────────────────────────────
class SolicitudAnalisis(BaseModel):
    solicitado_por: str
    con_ia: bool = True


class Decision(BaseModel):
    decision: str            # aceptada | parcial | descartada
    motivo: str
    editor: str
    pin: str
    enviar_al_panel: bool = True


@router.post("/lineas/{linea}/analizar")
def analizar_linea(linea: str, body: SolicitudAnalisis):
    if not body.solicitado_por or len(body.solicitado_por.strip()) < 3:
        raise HTTPException(422, "Indica quién solicita el análisis.")
    with _engine.begin() as c:
        plan, piezas, lineas, sku_lineas, params = _datos(c)
        if linea not in lineas:
            raise HTTPException(404, f"Línea no encontrada: {linea}")
        cid = c.execute(sa.text("""INSERT INTO mrp_analisis_casos (linea, origen, solicitado_por, plan_id, estado)
                                   VALUES (:l, 'manual', :p, :pl, 'ejecutando') RETURNING id"""),
                        {"l": linea, "p": body.solicitado_por.strip(), "pl": plan.id}).scalar()
    try:
        try:
            demo = _al.capacidad_demostrada(date.today())
        except Exception:
            demo = {}
        carga = _al.calcular_carga(piezas["detalle_diario"], piezas["uso_linea"], piezas["alertas"], lineas,
                                   sku_lineas, params, 6, demo, piezas.get("entradas_fijas"))
        diag = diagnosticar(linea, carga, piezas, lineas, sku_lineas, params)
        with _engine.connect() as c:
            apr = _aprendizaje(c, linea)
        rec = recomendar_ia(diag, apr) if body.con_ia else {"disponible": False, "motivo": "Solicitado sin IA."}
        with _engine.begin() as c:
            c.execute(sa.text("""UPDATE mrp_analisis_casos SET estado = 'listo', sintomas = CAST(:s AS JSONB),
                                 diagnostico = CAST(:d AS JSONB), escenarios = CAST(:e AS JSONB),
                                 recomendacion = CAST(:r AS JSONB) WHERE id = :i"""),
                      {"s": json.dumps(diag["sintomas"], default=str), "e": json.dumps(diag["palancas"], default=str),
                       "d": json.dumps({k: diag[k] for k in ("causas", "evidencia", "metodo", "motivos",
                                                             "primera_palanca_suficiente", "semaforo")}, default=str),
                       "r": json.dumps(rec, default=str), "i": cid})
    except Exception as e:
        with _engine.begin() as c:
            c.execute(sa.text("UPDATE mrp_analisis_casos SET estado = 'error', error = :e WHERE id = :i"),
                      {"e": f"{type(e).__name__}: {e}"[:2000], "i": cid})
        raise HTTPException(500, f"El análisis falló (caso #{cid}): {e}")
    return obtener_caso(cid)


@router.get("/casos")
def listar_casos(linea: Optional[str] = None, limit: int = 30):
    sql = """SELECT id, linea, creado_en, origen, solicitado_por, plan_id, estado, decision,
                    diagnostico->>'semaforo' AS semaforo, recomendacion->>'resumen' AS resumen
             FROM mrp_analisis_casos WHERE 1=1"""
    p = {"lim": max(1, min(limit, 200))}
    if linea:
        sql += " AND linea = :l"; p["l"] = linea
    sql += " ORDER BY creado_en DESC LIMIT :lim"
    with _engine.connect() as c:
        return {"casos": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.get("/casos/{cid}")
def obtener_caso(cid: int):
    with _engine.connect() as c:
        r = c.execute(sa.text("SELECT * FROM mrp_analisis_casos WHERE id = :i"), {"i": cid}).first()
    if r is None:
        raise HTTPException(404, "Caso no encontrado.")
    return dict(r._mapping)


@router.post("/casos/{cid}/decision")
def decidir(cid: int, body: Decision):
    import params_edicion as _pe
    if body.decision not in ("aceptada", "parcial", "descartada"):
        raise HTTPException(422, "Decisión inválida.")
    _pe._verificar_identidad(body.editor, body.motivo)
    creadas = 0
    with _engine.begin() as c:
        _pe._verificar_pin(c, body.pin)
        caso = c.execute(sa.text("SELECT * FROM mrp_analisis_casos WHERE id = :i FOR UPDATE"), {"i": cid}).first()
        if caso is None:
            raise HTTPException(404, "Caso no encontrado.")
        if body.decision != "descartada" and body.enviar_al_panel:
            for a in (caso.recomendacion or {}).get("acciones", []) or []:
                for cp in a.get("cambios_parametros") or []:
                    if cp.get("campo") not in ("batch_min_u", "cap_bodega_u") or not cp.get("sku"):
                        continue
                    creadas += c.execute(sa.text("""
                        INSERT INTO mrp_params_recomendaciones (entidad, clave, linea, campo, valor_actual, valor_sugerido,
                                                                rango, motivo, prioridad, fuente)
                        SELECT 'sku', :s, '', :c,
                               CASE :c WHEN 'batch_min_u' THEN p.batch_min_u ELSE p.cap_bodega_u END, :v, NULL, :m, 'alta', :f
                        FROM mrp_sku_params p WHERE p.sku = :s
                        ON CONFLICT ON CONSTRAINT uq_params_reco DO NOTHING"""),
                        {"s": cp["sku"], "c": cp["campo"], "v": cp.get("valor"), "m": a.get("accion", "")[:900],
                         "f": f"Análisis de línea #{cid} ({caso.linea})"}).rowcount
        c.execute(sa.text("""UPDATE mrp_analisis_casos SET decision = :d, decision_por = :p, decision_motivo = :m,
                             decision_en = now(), estado = CASE WHEN :d = 'descartada' THEN 'descartado' ELSE 'en_decision' END
                             WHERE id = :i"""), {"d": body.decision, "p": body.editor.strip(), "m": body.motivo.strip(), "i": cid})
    return {"id": cid, "decision": body.decision, "recomendaciones_creadas": creadas}
