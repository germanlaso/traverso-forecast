"""
analisis_programado.py — Análisis de Línea PROGRAMADO (MVP 2, tanda 3, 11-11-2026).

Valida con el SOLVER REAL la palanca recomendada en un caso (el MVP 1 la estima con un modelo
analítico de horas). Cada validación corre el plan completo, sin promover, con el escenario
aplicado EN MEMORIA (escenarios.py), y lo compara con corridas base de la misma noche:

    base       (sin cambios)  x 2 semillas  -> compartidas por todas las validaciones de la noche
    escenario  (con palanca)  x 2 semillas  -> por validación

Dos semillas separan el efecto de la palanca del ruido propio del solver (lo que vimos con los
planes 333 y 334). Todo pasa por la COLA del solver (nunca en paralelo) y respeta una VENTANA:
no se inicia una corrida que no alcance a terminar antes del cron del plan.

Uso:
  python3 /app/analisis_programado.py --listar          # qué hay programado
  python3 /app/analisis_programado.py                   # ejecuta (crontab 21:00 Chile = 00:00 UTC)
"""
import argparse
import json
import logging
import os
import re
import subprocess
import time
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db_mrp import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analisis_programado")
router = APIRouter(prefix="/analisis", tags=["Analisis de linea"])

SEMILLAS = [42, 7]
TL_A, TL_C = 900, 1200                 # tiempos del solver por corrida de validación (s)
VENTANA_HASTA_UTC = "0720"             # no iniciar corridas después (cron del plan: 09:00 UTC)
MAX_VALIDACIONES_NOCHE = 4
# mismas banderas que el cron de producción (crontab 09:00 UTC)
FLAGS = {"N2_ENABLED": "1", "SS_COBERTURA": "1", "N2_BARRERA_MODO": "quiebre", "N2_WORKERS_C": "8",
         "CAMPANA_GRANEL_ENABLED": "1", "CAMPANA_FORMATO_ENABLED": "1", "QUIEBRE_INTRADIA_SOLVER": "1",
         "N2_BARRERA_SOBRE": "fin", "EVENTOS_ENABLED": "1", "N2_QBR_MAG_MODO": "off", "N2_ESCALA_A": "1",
         "N2_A_GAP_EVENTOS": "6", "N2_DIAG_LOG_SOLVER": "1", "N2_CAP_EFECTIVA": "1", "PYTHONPATH": "/app"}


# ── Escenario desde un caso ───────────────────────────────────────────────────
def construir_escenario(caso: dict, nivel: Optional[int] = None) -> tuple[int, dict, str]:
    pal = {p["nivel"]: p for p in (caso.get("escenarios") or [])}
    diag = caso.get("diagnostico") or {}
    nivel = int(nivel or diag.get("primera_palanca_suficiente") or 2)
    nivel = max(1, min(nivel, 3))
    esc, partes = {}, []
    hoy = date.today()
    if nivel >= 1 and pal.get(1, {}).get("skus"):
        esc["batch_min_u"] = {x["sku"]: int(x["batch_propuesto_u"]) for x in pal[1]["skus"] if x.get("batch_propuesto_u")}
        if esc["batch_min_u"]:
            partes.append(f"batch mínimo reducido en {len(esc['batch_min_u'])} SKU")
    if nivel >= 2 and pal.get(2) and float(pal[2].get("horas_semana") or 0) > 0:
        h_dia = round(float(pal[2]["horas_semana"]) / 5.0, 2)
        esc["horas_extra"] = {caso["linea"]: {"desde": (hoy + timedelta(days=1)).isoformat(),
                                              "hasta": (hoy + timedelta(days=21)).isoformat(), "horas": h_dia}}
        partes.append(f"+{h_dia:g} h por día hábil en {caso['linea']} por 3 semanas")
    if nivel >= 3 and pal.get(3, {}).get("candidatas"):
        alt = pal[3]["candidatas"][0]["linea"]
        skus_q = [x["sku"] for x in (diag.get("evidencia") or {}).get("skus_quiebre", [])]
        if skus_q:
            esc["sku_lineas_extra"] = [{"sku": s, "linea": alt} for s in skus_q]
            partes.append(f"{len(skus_q)} SKU en quiebre habilitados en {alt} (hipótesis)")
    if not esc:
        raise HTTPException(422, "El caso no trae palancas aplicables para validar (niveles 1 a 3).")
    return nivel, esc, "; ".join(partes)


# ── Endpoints ─────────────────────────────────────────────────────────────────
class SolicitudValidacion(BaseModel):
    solicitado_por: str
    nivel: Optional[int] = None


@router.post("/casos/{cid}/validar")
def programar_validacion(cid: int, body: SolicitudValidacion):
    if not body.solicitado_por or len(body.solicitado_por.strip()) < 3:
        raise HTTPException(422, "Indica quién solicita la validación.")
    with engine.begin() as c:
        r = c.execute(sa.text("SELECT * FROM mrp_analisis_casos WHERE id = :i"), {"i": cid}).first()
        if r is None:
            raise HTTPException(404, "Caso no encontrado.")
        caso = dict(r._mapping)
        ya = c.execute(sa.text("SELECT id FROM mrp_analisis_validaciones WHERE caso_id = :i AND estado IN ('programada','ejecutando')"),
                       {"i": cid}).scalar()
        if ya:
            raise HTTPException(409, f"El caso ya tiene la validación #{ya} programada.")
        nivel, esc, desc = construir_escenario(caso, body.nivel)
        vid = c.execute(sa.text("""INSERT INTO mrp_analisis_validaciones (caso_id, linea, nivel, escenario, descripcion,
                                       semillas, solicitado_por) VALUES (:c, :l, :n, CAST(:e AS JSONB), :d, :s, :p) RETURNING id"""),
                        {"c": cid, "l": caso["linea"], "n": nivel, "e": json.dumps(esc), "d": desc, "s": SEMILLAS,
                         "p": body.solicitado_por.strip()}).scalar()
    return {"id": vid, "nivel": nivel, "descripcion": desc, "aviso": "Se ejecuta esta noche desde las 21:00 (cola del solver)."}


@router.get("/validaciones")
def listar_validaciones(caso_id: Optional[int] = None, limit: int = 30):
    sql, p = "SELECT * FROM mrp_analisis_validaciones WHERE 1=1", {"l": limit}
    if caso_id:
        sql += " AND caso_id = :c"; p["c"] = caso_id
    sql += " ORDER BY id DESC LIMIT :l"
    with engine.connect() as c:
        return {"validaciones": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.post("/validaciones/{vid}/cancelar")
def cancelar_validacion(vid: int):
    with engine.begin() as c:
        n = c.execute(sa.text("UPDATE mrp_analisis_validaciones SET estado = 'cancelada', fin = now() "
                              "WHERE id = :i AND estado = 'programada'"), {"i": vid}).rowcount
    if not n:
        raise HTTPException(409, "Solo se pueden cancelar validaciones programadas (no en ejecución).")
    return {"id": vid, "estado": "cancelada"}


# ── Ejecución nocturna ────────────────────────────────────────────────────────
def _en_ventana() -> bool:
    ahora = int(time.strftime("%H%M", time.gmtime()))
    return not (int(VENTANA_HASTA_UTC) <= ahora < 1200)


def _correr(semilla: int, escenario: Optional[dict], desc: str) -> Optional[int]:
    env = {**os.environ, **FLAGS, "N2_SEED_A": str(semilla), "N2_TL_C": str(TL_C),
           "COLA_DESCRIPCION": desc[:280], "COLA_VENTANA_HASTA": VENTANA_HASTA_UTC}
    env.pop("ESCENARIO_JSON", None)
    if escenario:
        env["ESCENARIO_JSON"] = json.dumps(escenario)
    t0 = time.time()
    r = subprocess.run(["python3", "-u", "/app/cron_plan.py", "--horizonte", "8", "--time-limit", str(TL_A),
                        "--no-promote", "--skip-refresh"], env=env, cwd="/app", capture_output=True, text=True,
                       timeout=4 * 3600)
    salida = (r.stdout or "") + (r.stderr or "")
    m = re.findall(r"plan_id=(\d+)", salida)
    log.info(f"  corrida '{desc}' semilla {semilla}: rc={r.returncode} plan={m[-1] if m else None} ({(time.time() - t0) / 60:.0f} min)")
    if r.returncode != 0 or not m:
        log.error("  últimas líneas: " + " | ".join(salida.strip().splitlines()[-4:]))
        return None
    return int(m[-1])


def _metricas_linea(c, plan_id: int, linea: str) -> dict:
    import evaluar_intervenciones as _ev
    skus = {r.sku for r in c.execute(sa.text("SELECT sku FROM mrp_sku_lineas WHERE linea = :l AND preferida"), {"l": linea})}
    m = _ev._metricas(_ev._snapshot(c, plan_id), skus, linea)
    return {"quiebre": m["alcance"]["quiebre"], "bajo_ss": m["alcance"]["bajo_ss"],
            "exceso_bodega": m["alcance"]["exceso_bodega"], **(m.get("linea") or {})}


def _resultado(c, linea: str, base: dict, escn: dict) -> dict:
    por_semilla, deltas = [], []
    for s in SEMILLAS:
        if str(s) in base and str(s) in escn:
            mb, me = _metricas_linea(c, base[str(s)], linea), _metricas_linea(c, escn[str(s)], linea)
            d = me["quiebre"] - mb["quiebre"]
            deltas.append(d)
            por_semilla.append({"semilla": s, "base": mb, "escenario": me, "delta_quiebre": d,
                                "delta_setups": (me.get("setups") or 0) - (mb.get("setups") or 0),
                                "delta_uso": round((me.get("uso_pct") or 0) - (mb.get("uso_pct") or 0), 1)})
    if not deltas:
        return {"error": "Sin pares base/escenario completos."}
    prom = sum(deltas) / len(deltas)
    base_q = sum(x["base"]["quiebre"] for x in por_semilla) / len(por_semilla)
    consistente = all(d < 0 for d in deltas) or all(d > 0 for d in deltas) or all(d == 0 for d in deltas)
    if prom < 0 and consistente:
        veredicto = "evita_quiebres"
    elif prom > 0 and consistente:
        veredicto = "empeora"
    else:
        veredicto = "no_concluyente"
    texto = (f"Días-SKU con quiebre de la línea: {base_q:.0f} sin la palanca → {base_q + prom:.0f} con ella "
             f"({prom:+.1f} en promedio; {', '.join(f'{d:+d}' for d in deltas)} según semilla).")
    return {"veredicto": veredicto, "delta_quiebre_promedio": round(prom, 1), "base_quiebre_promedio": round(base_q, 1),
            "consistente_entre_semillas": consistente, "por_semilla": por_semilla, "texto": texto}


def ejecutar():
    with engine.connect() as c:
        pend = [dict(r._mapping) for r in c.execute(sa.text(
            "SELECT * FROM mrp_analisis_validaciones WHERE estado = 'programada' ORDER BY creado_en LIMIT :n"),
            {"n": MAX_VALIDACIONES_NOCHE})]
    if not pend:
        log.info("Sin validaciones programadas.")
        return
    log.info(f"Validaciones programadas: {len(pend)} | semillas {SEMILLAS} | TL A={TL_A}s C={TL_C}s")
    base = {}
    for s in SEMILLAS:
        if not _en_ventana():
            log.warning("Fuera de ventana: se deja para la próxima noche.")
            return
        pid = _correr(s, None, f"validacion base semilla {s}")
        if pid:
            base[str(s)] = pid
    if not base:
        log.error("No se pudo correr la base: se reintenta la próxima noche.")
        return
    for v in pend:
        if not _en_ventana():
            log.warning(f"Fuera de ventana: validación #{v['id']} queda para la próxima noche.")
            break
        with engine.begin() as c:
            c.execute(sa.text("UPDATE mrp_analisis_validaciones SET estado = 'ejecutando', inicio = now() WHERE id = :i"), {"i": v["id"]})
        escn = {}
        for s in SEMILLAS:
            if not _en_ventana():
                break
            pid = _correr(s, v["escenario"], f"validacion #{v['id']} caso #{v['caso_id']} {v['linea']} semilla {s}")
            if pid:
                escn[str(s)] = pid
        with engine.begin() as c:
            if not escn:
                c.execute(sa.text("UPDATE mrp_analisis_validaciones SET estado = 'programada', inicio = NULL WHERE id = :i"),
                          {"i": v["id"]})
                continue
            res = _resultado(c, v["linea"], base, escn)
            c.execute(sa.text("""UPDATE mrp_analisis_validaciones SET estado = :e, fin = now(), planes = CAST(:p AS JSONB),
                                 resultado = CAST(:r AS JSONB), error = :err WHERE id = :i"""),
                      {"e": "error" if res.get("error") else "lista", "p": json.dumps({"base": base, "escenario": escn}),
                       "r": json.dumps(res, default=str), "err": res.get("error"), "i": v["id"]})
            log.info(f"  validación #{v['id']}: {res.get('veredicto')} — {res.get('texto') or res.get('error')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    a = ap.parse_args()
    if a.listar:
        for v in listar_validaciones()["validaciones"]:
            print(v["id"], v["estado"], v["linea"], f"nivel {v['nivel']}", v["descripcion"])
    else:
        ejecutar()
