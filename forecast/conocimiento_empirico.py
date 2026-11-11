"""
conocimiento_empirico.py — Capa de APRENDIZAJE: parámetro teórico vs dato empírico.

Primera métrica (MVP 1): CAPACIDAD DEMOSTRADA por línea.
  valor_teorico   = 1,0 (100% de la capacidad nominal: turnos x horas x velocidad, o el
                    calendario de 42 h si está activo, igual que los KPIs)
  valor_empirico  = promedio de las 3 mejores semanas de ocupación real (lo que la línea
                    SOSTUVO), con p10 / p50 / p90 de las semanas con producción
  n_obs           = semanas con producción en la ventana
  confianza       = alta (>= 8 semanas) · media (4-7) · baja (< 4)

Se guarda en mrp_conocimiento_empirico (entidad 'linea', métrica 'capacidad_semanal_pct') y
lo leen el semáforo y el Análisis de Línea (en vez de recalcular 8 semanas en cada consulta).
Correr una vez al día, después del cron del plan:
  docker exec traverso_forecast python3 /app/conocimiento_empirico.py --semanas 12
"""
import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter

from db_mrp import engine as _engine

router = APIRouter(prefix="/aprendizaje", tags=["Aprendizaje"])

METRICA_CAP = "capacidad_semanal_pct"


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _confianza(n):
    return "alta" if n >= 8 else "media" if n >= 4 else "baja"


def calcular_capacidad_demostrada(hoy: Optional[date] = None, semanas: int = 12) -> dict:
    """Ocupación real semanal por línea en las últimas `semanas` semanas CERRADAS (lun-dom)."""
    import kpi_operacion as _k
    hoy = hoy or date.today()
    lunes = hoy - timedelta(days=hoy.weekday()) - timedelta(days=7 * semanas)
    serie = defaultdict(list)
    for _ in range(semanas):
        r = _k.calcular_semana(lunes)
        for x in r["lineas"]:
            v = x["kpi"]["ocupacion_real"]
            if v is not None and v > 0:
                serie[x["linea"]].append((lunes, float(v)))
        lunes += timedelta(days=7)
    out = {}
    for l, pares in serie.items():
        vals = [v for _, v in pares]
        top = sorted(vals)[-3:]
        out[l] = {"valor_empirico": round(sum(top) / len(top), 4), "p10": _pct(vals, .1), "p50": _pct(vals, .5),
                  "p90": _pct(vals, .9), "maximo": max(vals), "n_obs": len(vals),
                  "ventana_desde": pares[0][0], "ventana_hasta": pares[-1][0] + timedelta(days=6),
                  "confianza": _confianza(len(vals))}
    return out


def guardar_capacidad(datos: dict) -> int:
    n = 0
    with _engine.begin() as c:
        for l, d in datos.items():
            nota = (f"Promedio de las 3 mejores semanas; máximo {d['maximo']:.0%}. "
                    f"Sobre 100% = produjo más que la capacidad nominal (extensiones, fines de semana).")
            n += c.execute(sa.text("""
                INSERT INTO mrp_conocimiento_empirico (entidad, clave, metrica, valor_teorico, valor_empirico,
                    p10, p50, p90, n_obs, ventana_desde, ventana_hasta, confianza, nota, actualizado_en)
                VALUES ('linea', :l, :m, 1.0, :v, :p10, :p50, :p90, :n, :d, :h, :conf, :nota, now())
                ON CONFLICT ON CONSTRAINT uq_conocimiento DO UPDATE SET
                    valor_teorico = EXCLUDED.valor_teorico, valor_empirico = EXCLUDED.valor_empirico,
                    p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90, n_obs = EXCLUDED.n_obs,
                    ventana_desde = EXCLUDED.ventana_desde, ventana_hasta = EXCLUDED.ventana_hasta,
                    confianza = EXCLUDED.confianza, nota = EXCLUDED.nota, actualizado_en = now()"""),
                {"l": l, "m": METRICA_CAP, "v": d["valor_empirico"], "p10": d["p10"], "p50": d["p50"], "p90": d["p90"],
                 "n": d["n_obs"], "d": d["ventana_desde"], "h": d["ventana_hasta"], "conf": d["confianza"],
                 "nota": nota}).rowcount
    return n


def leer_capacidad_demostrada(max_dias: int = 3) -> dict:
    """{linea: {top3, mediana, maximo, n_semanas, confianza}} desde la tabla, si está al día
    (actualizada hace <= max_dias). {} si no hay datos frescos: el llamador recalcula."""
    try:
        with _engine.connect() as c:
            filas = c.execute(sa.text("""SELECT clave, valor_empirico, p50, p90, n_obs, confianza, actualizado_en
                                         FROM mrp_conocimiento_empirico
                                         WHERE entidad = 'linea' AND metrica = :m
                                           AND actualizado_en >= now() - make_interval(days => :d)"""),
                              {"m": METRICA_CAP, "d": max_dias}).fetchall()
    except Exception:
        return {}
    return {r.clave: {"top3": r.valor_empirico, "mediana": r.p50, "p90": r.p90, "n_semanas": r.n_obs,
                      "confianza": r.confianza, "fuente": "conocimiento_empirico"} for r in filas}


@router.get("/conocimiento")
def conocimiento(entidad: Optional[str] = None, metrica: Optional[str] = None):
    sql = "SELECT * FROM mrp_conocimiento_empirico WHERE 1=1"
    p = {}
    if entidad:
        sql += " AND entidad = :e"; p["e"] = entidad
    if metrica:
        sql += " AND metrica = :m"; p["m"] = metrica
    sql += " ORDER BY entidad, clave, metrica"
    with _engine.connect() as c:
        return {"conocimiento": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.get("/intervenciones")
def intervenciones(veredicto: Optional[str] = None):
    sql = "SELECT * FROM mrp_intervenciones WHERE 1=1"
    p = {}
    if veredicto:
        sql += " AND veredicto = :v"; p["v"] = veredicto
    sql += " ORDER BY creado_en DESC"
    with _engine.connect() as c:
        return {"intervenciones": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.post("/conocimiento/recalcular")
def recalcular(semanas: int = 12):
    datos = calcular_capacidad_demostrada(semanas=semanas)
    return {"lineas": len(datos), "guardadas": guardar_capacidad(datos)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--semanas", type=int, default=12)
    a = ap.parse_args()
    d = calcular_capacidad_demostrada(semanas=a.semanas)
    n = guardar_capacidad(d)
    for l, x in sorted(d.items(), key=lambda z: -z[1]["valor_empirico"]):
        print(f"{l:13} demostrada {x['valor_empirico']:.0%}  p50 {x['p50']:.0%}  p90 {x['p90']:.0%}  "
              f"n={x['n_obs']:>2}  confianza {x['confianza']}")
    print(f"Guardadas: {n} líneas en mrp_conocimiento_empirico ({METRICA_CAP}).")
