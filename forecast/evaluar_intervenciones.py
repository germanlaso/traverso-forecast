"""
evaluar_intervenciones.py — Evaluación AUTOMÁTICA de intervenciones (capa de aprendizaje, MVP 2).

Cada intervención aplicada (cambio de parámetros desde el panel, turno, línea alternativa...)
se mide sola contra el plan:
  · ANTES   = el último plan vigente antes de aplicar el cambio
  · DESPUÉS = el plan vigente a los 7 días (evaluación preliminar) y a los 14 (veredicto)
  · ALCANCE = los SKU de la intervención (o los de la línea, si no trae SKU)
  · CONTROL = todos los demás SKU: su variación muestra cuánto cambia el plan solo por
              stock, OV y forecast. El efecto se mide como diferencia contra el control.

Indicadores en una ventana de 4 semanas desde el inicio de cada plan:
  días-SKU con quiebre, días-SKU bajo SS (stock de seguridad), alertas de exceso de bodega
  y, para la línea: cambios de SKU (setups), OF tentativas, horas por OF y uso.

Veredicto (a los 14 días; a los 7 queda como preliminar en la evidencia):
  funciono                          mejora el indicador principal de la palanca, sin empeorar quiebres
  funciono_con_efecto_secundario    mejora el principal pero empeoran los quiebres del alcance
  no_funciono                       el principal empeora o no mejora y los quiebres empeoran
  no_concluyente                    cambios dentro del ruido (menos de 1 día-SKU o 10%)
Principal por palanca: batch -> setups de la línea · cap. bodega -> exceso de bodega ·
turnos / línea alternativa / forecast / otro -> quiebres del alcance.

Uso (dentro del contenedor; crontab 08:10 Chile):
  python3 /app/evaluar_intervenciones.py --dry-run
  python3 /app/evaluar_intervenciones.py
"""
import argparse
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from db_mrp import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("evaluar_intervenciones")

VENTANA_DIAS = 28
DIAS_PRELIMINAR = 7
DIAS_FINAL = 14
RUIDO_ABS = 1.0      # días-SKU
RUIDO_REL = 0.10     # 10%


def _plan_antes(c, ts):
    r = c.execute(sa.text("SELECT id, created_at FROM mrp_planes WHERE created_at < :t ORDER BY created_at DESC LIMIT 1"),
                  {"t": ts}).first()
    return r


def _plan_vigente(c):
    return c.execute(sa.text("SELECT id, created_at FROM mrp_planes WHERE vigente LIMIT 1")).first()


def _snapshot(c, pid):
    out = {}
    for k in ("alertas", "ofts", "uso_linea", "detalle_diario"):
        out[k] = c.execute(sa.text("SELECT snapshot->:k FROM mrp_planes WHERE id = :i"), {"k": k, "i": pid}).scalar() or {}
    fechas = sorted({f for dd in (out["detalle_diario"] or {}).values() for f in dd})
    out["inicio"] = fechas[0] if fechas else None
    out.pop("detalle_diario")
    return out


def _metricas(snap, skus: set, linea: str | None) -> dict:
    ini = snap["inicio"]
    if not ini:
        return {}
    fin = (date.fromisoformat(ini) + timedelta(days=VENTANA_DIAS)).isoformat()
    cnt = Counter()
    for a in snap["alertas"] or []:
        f = a.get("fecha")
        if not f or not (ini <= f < fin):
            continue
        dentro = a.get("sku") in skus
        clave = {"QUIEBRE": "quiebre", "BAJO_SS": "bajo_ss", "EXCESO_BODEGA": "exceso_bodega"}.get(a.get("tipo"))
        if clave:
            cnt[(clave, dentro)] += 1
    m = {"alcance": {k: cnt[(k, True)] for k in ("quiebre", "bajo_ss", "exceso_bodega")},
         "control": {k: cnt[(k, False)] for k in ("quiebre", "bajo_ss", "exceso_bodega")}}
    if linea:
        ofs = [o for o in (snap["ofts"] or []) if o.get("linea") == linea and ini <= str(o.get("fecha_lanzamiento")) < fin]
        uso = [float(v) for f, v in ((snap["uso_linea"] or {}).get(linea) or {}).items()
               if ini <= f < fin and date.fromisoformat(f).weekday() < 5]
        m["linea"] = {"ofts": len(ofs), "setups": sum(1 for o in ofs if o.get("paga_setup")),
                      "unidades_por_of": round(sum(float(o.get("cantidad_unidades") or 0) for o in ofs) / len(ofs)) if ofs else None,
                      "uso_pct": round(sum(uso) / len(uso), 1) if uso else None}
    return m


def _efecto(antes: float, despues: float, ctrl_antes: float, ctrl_despues: float) -> float:
    """Variación del alcance descontando la variación proporcional del control (negativo = mejora)."""
    factor = (ctrl_despues / ctrl_antes) if ctrl_antes else 1.0
    esperado = antes * factor
    return round(despues - esperado, 1)


def _significativo(efecto: float, base: float) -> bool:
    return abs(efecto) >= RUIDO_ABS and (base == 0 or abs(efecto) / max(base, 1) >= RUIDO_REL)


def evaluar_una(c, iv: dict, hoy: date) -> dict | None:
    aplicado = iv["aplicado_en"]
    if aplicado is None:
        return None
    dias = (hoy - aplicado.date()).days
    if dias < DIAS_PRELIMINAR:
        return None
    ev = iv.get("evidencia") or {}
    etapa = "final" if dias >= DIAS_FINAL else "preliminar"
    if etapa == "preliminar" and ev.get("eval_7d"):
        return None
    pa, pd = _plan_antes(c, aplicado), _plan_vigente(c)
    if pa is None or pd is None or pa.id == pd.id:
        return {"etapa": etapa, "error": "No hay planes antes y después para comparar."}
    linea = iv.get("linea") if iv.get("linea") not in (None, "", "varias") else None
    skus = set(iv.get("skus") or [])
    if not skus and linea:
        skus = {r.sku for r in c.execute(sa.text("SELECT sku FROM mrp_sku_lineas WHERE linea = :l AND preferida"), {"l": linea})}
    sa_, sd_ = _snapshot(c, pa.id), _snapshot(c, pd.id)
    ma, md = _metricas(sa_, skus, linea), _metricas(sd_, skus, linea)
    if not ma or not md:
        return {"etapa": etapa, "error": "Planes sin detalle diario."}
    ef = {k: _efecto(ma["alcance"][k], md["alcance"][k], ma["control"][k], md["control"][k])
          for k in ("quiebre", "bajo_ss", "exceso_bodega")}
    palanca = iv["palanca"]
    if palanca == "param_batch" and linea and ma.get("linea") and md.get("linea"):
        principal = ("setups de la línea", md["linea"]["setups"] - ma["linea"]["setups"], ma["linea"]["setups"])
    elif palanca == "param_cap_bodega":
        principal = ("alertas de exceso de bodega", ef["exceso_bodega"], ma["alcance"]["exceso_bodega"])
    else:
        principal = ("días-SKU con quiebre", ef["quiebre"], ma["alcance"]["quiebre"])
    nombre, delta, base = principal
    mejora = delta < 0 and _significativo(delta, base)
    empeora = delta > 0 and _significativo(delta, base)
    q_empeora = ef["quiebre"] > 0 and _significativo(ef["quiebre"], ma["alcance"]["quiebre"])
    if mejora and not q_empeora:
        veredicto = "funciono"
    elif mejora and q_empeora:
        veredicto = "funciono_con_efecto_secundario"
    elif empeora or (q_empeora and not mejora):
        veredicto = "no_funciono"
    else:
        veredicto = "no_concluyente"
    texto = (f"{nombre}: {'baja' if delta < 0 else 'sube' if delta > 0 else 'sin cambio'} {abs(delta):g} "
             f"(base {base:g}); quiebres del alcance vs control: {ef['quiebre']:+g} días-SKU.")
    return {"etapa": etapa, "dias": dias, "plan_antes": pa.id, "plan_despues": pd.id,
            "metricas_antes": ma, "metricas_despues": md, "efecto_vs_control": ef,
            "principal": {"indicador": nombre, "delta": delta, "base": base},
            "veredicto": veredicto, "texto": texto,
            "metodo": f"antes/después con grupo de control (resto de SKU), ventana {VENTANA_DIAS} días, 1 corrida por plan"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    hoy = date.today()
    with engine.begin() as c:
        ivs = [dict(r._mapping) for r in c.execute(sa.text(
            "SELECT * FROM mrp_intervenciones WHERE veredicto = 'pendiente' AND aplicado_en IS NOT NULL ORDER BY aplicado_en"))]
        log.info(f"Intervenciones pendientes con cambio aplicado: {len(ivs)}")
        for iv in ivs:
            r = evaluar_una(c, iv, hoy)
            if r is None:
                continue
            if r.get("error"):
                log.warning(f"  #{iv['id']} {iv['palanca']} {iv.get('linea')}: {r['error']}")
                continue
            log.info(f"  #{iv['id']} {iv['palanca']} {iv.get('linea')} [{r['etapa']}, {r['dias']} d]: {r['veredicto']} — {r['texto']}")
            if a.dry_run:
                continue
            ev = dict(iv.get("evidencia") or {})
            ev["eval_7d" if r["etapa"] == "preliminar" else "eval_14d"] = r
            if r["etapa"] == "preliminar":
                c.execute(sa.text("UPDATE mrp_intervenciones SET evidencia = CAST(:e AS JSONB) WHERE id = :i"),
                          {"e": json.dumps(ev, default=str), "i": iv["id"]})
            else:
                c.execute(sa.text("""UPDATE mrp_intervenciones SET evidencia = CAST(:e AS JSONB), veredicto = :v,
                                     efecto_observado = CAST(:o AS JSONB), aprendizaje = COALESCE(aprendizaje, :t),
                                     evaluado_en = now(), evaluado_por = 'Sistema (automático)' WHERE id = :i"""),
                          {"e": json.dumps(ev, default=str), "v": r["veredicto"], "o": json.dumps(r["efecto_vs_control"]),
                           "t": f"{r['texto']} (evaluación automática a {r['dias']} días)", "i": iv["id"]})


if __name__ == "__main__":
    main()
