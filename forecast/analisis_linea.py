"""
analisis_linea.py — Análisis de Línea (MVP 1). Pieza 1: CARGA REQUERIDA y SEMÁFORO.

Tres miradas por línea y semana (todas en % de la capacidad nominal):
  · carga requerida  = horas que exige la demanda del plan (forecast + OV corregida)
                       ÷ horas nominales                                                  -> lo que se NECESITA
  · reposición de SS = horas para reponer el SS (stock de seguridad) que hoy falta; se informa APARTE
                       (no entra al semáforo: con SS de 15 días sobre demanda de temporada puede ser
                       enorme y taparía la señal de la demanda)
  · uso programado   = horas que el plan vigente logró asignar (uso_linea)                  -> lo que se PROGRAMÓ
  · capacidad demostrada = lo que la línea sostuvo en sus mejores semanas reales (TR)      -> lo que PUEDE

La brecha carga requerida vs uso programado es la alerta temprana.

Semáforo (decisión 11-11-26):
  ROJO   carga requerida > 95% en alguna de las próximas 3 semanas, o quiebre de un SKU
         no MTO desde la semana 2 (evitable por capacidad)
  ÁMBAR  carga requerida > 85% en las próximas 3 semanas, o quiebre inmediato (semana 1:
         pedidos sobre stock / recepciones)
  VERDE  resto

Simplificaciones declaradas (MVP 1): la demanda se asigna a la línea PREFERIDA del SKU; la
capacidad nominal cuenta lunes a viernes (los feriados no se descuentan); el semáforo usa solo
semanas con al menos 3 días hábiles (la semana en curso puede quedar corta).
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from db_mrp import engine as _engine

router = APIRouter(prefix="/analisis", tags=["Analisis de linea"])

UMBRAL_ROJO = 0.95
UMBRAL_AMBAR = 0.85
SEMANAS_ALERTA = 3
DIAS_INMEDIATO = 6            # quiebre antes de 6 días = semana 1 (inmediato)
SEMANAS_DEMOSTRADA = 8        # ventana para capacidad demostrada
_CACHE_DEMO = {}              # {fecha: {linea: {...}}} — se recalcula una vez al día


def horas_dia_linea(L: dict, d: date) -> float:
    """(11-11-2026) Horas de la línea ese día, igual que el solver: patrón por día/turno y
    excepciones si el calendario está activo (claves _tc/_exc que pone _cargar_desde_bd);
    si no, horas_turno x turnos en días hábiles (sin feriados)."""
    import calendario as _cal
    return _cal.horas_linea_dia(d, float(L.get("horas_turno") or 0), int(L.get("turnos_dia") or 0),
                                L.get("_tc"), L.get("_exc"))


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def capacidad_demostrada(hoy: date) -> dict:
    """Ocupación real de las últimas semanas cerradas (motor de KPIs): promedio de las 3 mejores,
    mediana y máximo, por línea. Es el 'dato empírico' frente a la capacidad nominal (teórica)."""
    if hoy in _CACHE_DEMO:
        return _CACHE_DEMO[hoy]
    # (11-11-2026) primero el conocimiento empírico guardado (12 semanas, con confianza);
    # si no está al día, se recalcula aquí con 8 semanas como antes.
    try:
        import conocimiento_empirico as _ce
        guardado = _ce.leer_capacidad_demostrada()
        if guardado:
            _CACHE_DEMO.clear()
            _CACHE_DEMO[hoy] = guardado
            return guardado
    except Exception:
        pass
    import kpi_operacion as _k
    lunes = _lunes(hoy) - timedelta(days=7 * SEMANAS_DEMOSTRADA)
    serie = defaultdict(list)
    for _ in range(SEMANAS_DEMOSTRADA):
        r = _k.calcular_semana(lunes)
        for x in r["lineas"]:
            v = x["kpi"]["ocupacion_real"]
            if v is not None:
                serie[x["linea"]].append(v)
        lunes += timedelta(days=7)
    out = {}
    for l, vals in serie.items():
        s = sorted(vals)
        out[l] = {"top3": round(sum(s[-3:]) / min(3, len(s)), 4), "mediana": round(s[len(s) // 2], 4),
                  "maximo": round(s[-1], 4), "n_semanas": len(s)}
    _CACHE_DEMO.clear()
    _CACHE_DEMO[hoy] = out
    return out


def calcular_carga(detalle: dict, uso_linea: dict, alertas: list, lineas: dict, sku_lineas: list,
                   sku_params: dict, semanas: int = 6, demostrada: Optional[dict] = None,
                   entradas: Optional[list] = None) -> dict:
    """Núcleo puro (sin BD): recibe las piezas del snapshot del plan y los parámetros."""
    fechas = sorted({f for dd in detalle.values() for f in dd})
    if not fechas:
        raise ValueError("El plan no tiene detalle diario.")
    hoy = date.fromisoformat(fechas[0])
    lunes0 = _lunes(hoy)
    lim = lunes0 + timedelta(days=7 * semanas)

    pref, factor = {}, {}
    for r in sku_lineas:
        factor[(r["sku"], r["linea"])] = float(r.get("factor_velocidad") or 1.0)
        if r.get("preferida"):
            pref[r["sku"]] = r["linea"]
        else:
            pref.setdefault(r["sku"], r["linea"])

    req = defaultdict(lambda: defaultdict(float))      # linea -> semana -> horas requeridas
    req_ss = defaultdict(float)                        # linea -> horas de reposición SS (sem 1)
    skus_linea = defaultdict(set)
    sin_vel = set()
    for sku, dd in detalle.items():
        lin = pref.get(sku)
        L = lineas.get(lin)
        p = sku_params.get(sku, {})
        if L is None or not p.get("activo", True):
            continue
        vel = float(L.get("velocidad_u_hr") or 0) * factor.get((sku, lin), 1.0)
        if vel <= 0:
            sin_vel.add(sku)
            continue
        skus_linea[lin].add(sku)
        for f, v in dd.items():
            d = date.fromisoformat(f)
            if d >= lim:
                continue
            dem = v.get("demanda_corr_u")
            if dem is None:
                dem = (v.get("forecast_u") or 0) + (v.get("pedidos_u") or 0)
            req[lin][_lunes(d)] += float(dem) / vel
        v0 = dd.get(fechas[0], {})
        faltante_ss = max(0.0, float(v0.get("ss_u") or 0) - float(v0.get("stock_ini_disp_u") or 0))
        req_ss[lin] += faltante_ss / vel

    q_por_linea = defaultdict(lambda: {"capacidad": [], "inmediato": [], "mto": []})
    vistos = {}
    for a in alertas or []:
        if a.get("tipo") != "QUIEBRE" or not a.get("fecha"):
            continue
        sku = a.get("sku")
        if sku in vistos:
            vistos[sku]["dias"] += 1
            vistos[sku]["deficit_u"] = max(vistos[sku]["deficit_u"], a.get("deficit_u") or 0)
            continue
        vistos[sku] = {"sku": sku, "primer_quiebre": a["fecha"], "dias": 1, "deficit_u": a.get("deficit_u") or 0}
    for sku, q in vistos.items():
        lin = pref.get(sku)
        if lin is None:
            continue
        p = sku_params.get(sku, {})
        upc = p.get("u_por_caja") or 1
        item = {**q, "descripcion": p.get("descripcion"), "deficit_cj": round(q["deficit_u"] / upc)}
        dias = (date.fromisoformat(q["primer_quiebre"]) - hoy).days
        tipo = "mto" if p.get("mto") else ("inmediato" if dias < DIAS_INMEDIATO else "capacidad")
        q_por_linea[lin][tipo].append(item)

    # OF APROBADAS (entradas_fijas): uso_linea solo cuenta las OF tentativas del solver; las aprobadas
    # también ocupan línea (p. ej. el día en curso). El snapshot no guarda el SKU de la aprobada: se
    # completa desde mrp_ordenes por numero_of (_cargar_desde_bd). Si falta, se usa el u/caja mediano
    # de la línea (aproximación).
    upc_linea = {}
    for lin_, skus_ in skus_linea.items():
        v_ = sorted(float((sku_params.get(x) or {}).get("u_por_caja") or 1) for x in skus_)
        upc_linea[lin_] = v_[len(v_) // 2] if v_ else 1.0
    h_aprob = defaultdict(lambda: defaultdict(float))     # linea -> fecha -> horas
    for e in entradas or []:
        lin_, f_ = e.get("linea"), e.get("fecha_lanzamiento")
        L_ = lineas.get(lin_)
        if not lin_ or not f_ or L_ is None or not float(L_.get("velocidad_u_hr") or 0):
            continue
        sku_ = e.get("sku")
        upc_ = float((sku_params.get(sku_) or {}).get("u_por_caja") or 0) if sku_ else 0.0
        vel_ = float(L_["velocidad_u_hr"]) * (factor.get((sku_, lin_), 1.0) if sku_ else 1.0)
        h_aprob[lin_][f_] += float(e.get("cantidad_cajas") or 0) * (upc_ or upc_linea.get(lin_, 1.0)) / vel_

    salida = []
    for lin, L in sorted(lineas.items()):
        if not L.get("activa", True):
            continue
        h_dia = float(L.get("turnos_dia") or 0) * float(L.get("horas_turno") or 0)
        dias_sem = int(L.get("dias_semana") or 5)
        import calendario as _cal
        h_sem_tipo = _cal.horas_semana_patron(L.get("_tc"), float(L.get("horas_turno") or 0),
                                              int(L.get("turnos_dia") or 0), dias_sem)
        uso = uso_linea.get(lin, {}) or {}
        filas = []
        for i in range(semanas):
            ls = lunes0 + timedelta(days=7 * i)
            dias = [ls + timedelta(days=k) for k in range(7)]
            hd = {d: horas_dia_linea(L, d) for d in dias}
            habiles = [d for d in dias if hd[d] > 0 and d >= hoy]
            cap_h = sum(hd[d] for d in habiles)
            h_req = req[lin].get(ls, 0.0)
            h_prog = sum(min(hd[d], float(uso.get(d.isoformat(), 0) or 0) / 100.0 * hd[d]
                                 + h_aprob[lin].get(d.isoformat(), 0.0))
                         for d in dias if d >= hoy and hd[d] > 0)
            filas.append({
                "semana": ls.isoformat(), "semana_iso": ls.isocalendar()[1], "dias_habiles": len(habiles),
                # semana en curso: solo cuentan los días hábiles que quedan (capacidad Y demanda)
                "parcial": any(d < hoy and hd[d] > 0 for d in dias),
                "desde": habiles[0].isoformat() if habiles else None,
                "hasta": habiles[-1].isoformat() if habiles else None,
                "horas_nominales": round(cap_h, 1), "horas_requeridas": round(h_req, 1),
                "horas_programadas": round(h_prog, 1),
                "carga_requerida": round(h_req / cap_h, 4) if cap_h else None,
                "uso_programado": round(h_prog / cap_h, 4) if cap_h else None,
            })
        evaluables = [f for f in filas if f["dias_habiles"] >= 3][:SEMANAS_ALERTA]
        prox = [f["carga_requerida"] for f in evaluables if f["carga_requerida"] is not None]
        max_carga = max(prox) if prox else 0.0
        q = q_por_linea[lin]
        motivos = []
        if max_carga > UMBRAL_ROJO:
            sem = next(f for f in evaluables if (f["carga_requerida"] or 0) == max_carga)
            motivos.append(f"Carga requerida de {max_carga:.0%} en la Sem {sem['semana_iso']} (umbral {UMBRAL_ROJO:.0%}).")
        if q["capacidad"]:
            motivos.append(f"{len(q['capacidad'])} SKU con quiebre desde la semana 2 (por capacidad).")
        if motivos:
            semaforo = "rojo"
        else:
            if max_carga > UMBRAL_AMBAR:
                motivos.append(f"Carga requerida de {max_carga:.0%} (sobre {UMBRAL_AMBAR:.0%}).")
            if q["inmediato"]:
                motivos.append(f"{len(q['inmediato'])} SKU con quiebre inmediato (semana 1: pedidos o recepciones).")
            semaforo = "ambar" if motivos else "verde"
        demo = (demostrada or {}).get(lin)
        salida.append({
            "linea": lin, "semaforo": semaforo, "motivos": motivos, "n_skus": len(skus_linea[lin]),
            "max_carga_requerida_3sem": round(max_carga, 4),
            "reposicion_ss": {"horas": round(req_ss[lin], 1),
                              "pct_capacidad_3sem": round(req_ss[lin] / (h_sem_tipo * SEMANAS_ALERTA), 4)
                              if h_sem_tipo else None},
            "capacidad_demostrada": demo,
            "carga_vs_demostrada": round(max_carga / demo["top3"], 4) if demo and demo["top3"] else None,
            "parametros": {"turnos_dia": L.get("turnos_dia"), "horas_turno": L.get("horas_turno"),
                           "dias_semana": dias_sem, "velocidad_u_hr": L.get("velocidad_u_hr"),
                           "horas_semana": h_sem_tipo, "turnos_config": L.get("_tc")},
            "semanas": filas,
            "quiebres": {k: sorted(v, key=lambda x: x["primer_quiebre"]) for k, v in q.items()},
        })
    orden = {"rojo": 0, "ambar": 1, "verde": 2}
    salida.sort(key=lambda x: (orden[x["semaforo"]], -x["max_carga_requerida_3sem"]))
    return {"hoy": hoy.isoformat(), "semanas": semanas, "lineas": salida,
            "advertencias": {"sku_sin_velocidad": sorted(sin_vel)} if sin_vel else {},
            "umbrales": {"rojo": UMBRAL_ROJO, "ambar": UMBRAL_AMBAR, "semanas_alerta": SEMANAS_ALERTA}}


def _cargar_desde_bd(c):
    plan = c.execute(sa.text("SELECT id, created_at FROM mrp_planes WHERE vigente LIMIT 1")).first()
    if plan is None:
        raise HTTPException(503, "No hay plan vigente.")
    piezas = {}
    for k in ("detalle_diario", "uso_linea", "alertas", "entradas_fijas"):
        piezas[k] = c.execute(sa.text("SELECT snapshot->:k FROM mrp_planes WHERE id = :i"),
                              {"k": k, "i": plan.id}).scalar() or {}
    # completar el SKU de cada OF aprobada (el snapshot no lo trae) desde mrp_ordenes
    ofs = [e.get("numero_of") for e in piezas.get("entradas_fijas") or [] if e.get("numero_of")]
    if ofs:
        sku_of = {r.numero_of: r.sku for r in c.execute(sa.text(
            "SELECT numero_of, sku FROM mrp_ordenes WHERE numero_of = ANY(:o)"), {"o": ofs})}
        for e in piezas["entradas_fijas"]:
            e["sku"] = sku_of.get(e.get("numero_of"))
    lineas = {r.codigo: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_lineas"))}
    # (11-11-2026) calendario de capacidad (mismo criterio que el solver)
    import mrp as _mrp
    if _mrp.capacidad_calendario_activa():
        excs = _mrp.cargar_excepciones_capacidad()
        for cod, L in lineas.items():
            L["_tc"] = _mrp._normalizar_turnos_config(L.get("turnos_config"))
            L["_exc"] = excs.get(cod) or None
    sku_lineas = [dict(r._mapping) for r in c.execute(sa.text("SELECT sku, linea, preferida, factor_velocidad FROM mrp_sku_lineas"))]
    sku_params = {r.sku: dict(r._mapping) for r in c.execute(sa.text(
        "SELECT sku, descripcion, u_por_caja, mto, activo FROM mrp_sku_params"))}
    return plan, piezas, lineas, sku_lineas, sku_params


@router.get("/lineas")
def carga_lineas(semanas: int = Query(6, ge=1, le=8), linea: Optional[str] = None):
    """Semáforo y carga requerida vs programada vs demostrada, por línea y semana."""
    with _engine.connect() as c:
        plan, piezas, lineas, sku_lineas, sku_params = _cargar_desde_bd(c)
    try:
        demo = capacidad_demostrada(date.today())
    except Exception:
        demo = {}
    r = calcular_carga(piezas["detalle_diario"], piezas["uso_linea"], piezas["alertas"], lineas,
                       sku_lineas, sku_params, semanas, demo, piezas.get("entradas_fijas"))
    if linea:
        r["lineas"] = [x for x in r["lineas"] if x["linea"] == linea]
    r["plan"] = {"id": plan.id, "creado": plan.created_at.isoformat()}
    return r
