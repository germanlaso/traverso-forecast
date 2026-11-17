"""
recomendar_margen_bodega.py — Recomendaciones de capacidad de bodega por margen estrecho entre el
stock de seguridad (SS) y la bodega (17-11-2026, chat de eficiencia de línea).

Por qué: para ordenar la semana (una OF por SKU, de claro a oscuro), el plan debe poder producir
un SKU una vez y cubrir varios días. Eso exige que entre el SS y la capacidad de bodega quepan al
menos ~7 días de demanda. Con menos, el stock solo se puede mantener produciendo casi a diario
(ej. L1Pet LV, semana 48: Vinagre Blanco 30x500 en 4 OF de 400 cj). Si la bodega es MENOR que el
SS, las dos reglas son incompatibles.

Qué hace: con el plan VIGENTE (snapshot: detalle diario de las próximas 4 semanas), para cada SKU
con producción planificada y capacidad de bodega finita calcula
    margen (días) = (cap. bodega − SS máximo de las 4 semanas) ÷ demanda diaria promedio
y si es < 7 días deja una RECOMENDACIÓN en el panel de Parámetros (no aplica nada):
    campo cap_bodega_u, sugerido = SS máximo + 7 días de demanda (redondeado a 1.000 u)
    prioridad: alta si el margen es negativo; media si < 3 días; baja si < 7.
El motivo menciona la alternativa (bajar el SS), que no se edita en el panel.
Si la recomendación de un SKU sigue abierta, se actualiza; si ya no corresponde (margen ≥ 7 días),
se descarta sola. Las descartadas o aplicadas por un usuario no se reabren.

Uso (dentro del contenedor):
  python3 /app/recomendar_margen_bodega.py            # solo muestra
  python3 /app/recomendar_margen_bodega.py --aplicar  # crea / actualiza / cierra en el panel
"""
import argparse
import json
import math
from datetime import date, timedelta

import sqlalchemy as sa

from db_mrp import engine

FUENTE = "Eficiencia de línea · margen SS–bodega"
MARGEN_MIN_DIAS = 7.0
DIAS_VENTANA = 28
CAP_INFINITA = 999999
DEM_MIN_U_DIA = 50          # SKU con demanda despreciable: no se evalúan


def _n(x):
    return f"{int(round(x)):,}".replace(",", ".")


def _d1(x):
    return f"{x:.1f}".replace(".", ",")


def calcular(detalle, params, ofts, hoy, prefer):
    """detalle: {sku: {fecha: {...}}} del snapshot; params: {sku: fila de mrp_sku_params}."""
    con_prod = {o["sku"] for o in ofts}
    ini, fin = (hoy + timedelta(1)).isoformat(), (hoy + timedelta(DIAS_VENTANA)).isoformat()
    out = []
    for sku, serie in detalle.items():
        p = params.get(sku)
        if not p or sku not in con_prod:
            continue
        cap = float(p.get("cap_bodega_u") or 0)
        if cap <= 0 or cap >= CAP_INFINITA:
            continue
        dias = [v for f, v in serie.items() if ini <= f <= fin]
        if not dias:
            continue
        dem = sum(float(v.get("demanda_corr_u") or 0) for v in dias) / DIAS_VENTANA
        if dem < DEM_MIN_U_DIA:
            continue
        ss_max = max(float(v.get("ss_u") or 0) for v in dias)
        if ss_max <= 0:
            continue
        margen = (cap - ss_max) / dem
        if margen >= MARGEN_MIN_DIAS:
            out.append({"sku": sku, "ok": True, "margen": margen})
            continue
        minimo = ss_max + MARGEN_MIN_DIAS * dem
        sugerido = math.ceil(minimo / 1000.0) * 1000
        ss_d, cap_d = ss_max / dem, cap / dem
        prioridad = "alta" if margen < 0 else ("media" if margen < 3 else "baja")
        if margen < 0:
            inicio = (f"La capacidad de bodega ({_n(cap)} u, {_d1(cap_d)} días) es MENOR que el stock de seguridad "
                      f"({_n(ss_max)} u, {_d1(ss_d)} días): las dos reglas son incompatibles y el plan debe producir "
                      f"este SKU casi a diario.")
        else:
            inicio = (f"Entre el stock de seguridad ({_n(ss_max)} u, {_d1(ss_d)} días) y la capacidad de bodega "
                      f"({_n(cap)} u, {_d1(cap_d)} días) caben solo {_d1(margen)} días de demanda: el plan debe "
                      f"producir este SKU cada pocos días.")
        motivo = (f"{inicio} Así no puede agrupar la semana en una sola OF ni respetar la secuencia de claro a oscuro. "
                  f"Sugerido: bodega para el SS más 7 días de demanda ({_n(dem)} u/día). "
                  f"Alternativa, si no hay espacio: bajar el SS de ≈{_d1(ss_d)} a ≈{_d1(max(ss_d - (MARGEN_MIN_DIAS - margen), 0))} "
                  f"días (se ajusta en los parámetros de SS, no en este panel).")
        out.append({"sku": sku, "ok": False, "margen": margen, "cap": cap, "sugerido": float(sugerido),
                    "rango": f"≥ {_n(minimo)} u (SS {_n(ss_max)} + 7 días de demanda)",
                    "motivo": motivo, "prioridad": prioridad, "linea": prefer.get(sku, ""),
                    "desc": p.get("descripcion") or ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT id, snapshot FROM mrp_planes WHERE vigente LIMIT 1")).first()
        if row is None:
            print("sin plan vigente"); return
        snap = row.snapshot if isinstance(row.snapshot, dict) else json.loads(row.snapshot)
        params = {r.sku: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params"))}
        prefer = {r.sku: r.linea for r in c.execute(sa.text(
            "SELECT sku, linea FROM mrp_sku_lineas WHERE preferida"))}
    hoy = date.fromisoformat(str((snap.get("resumen") or {}).get("fecha_inicio") or date.today())[:10])
    res = calcular(snap.get("detalle_diario") or {}, params, snap.get("ofts") or [], hoy, prefer)
    recos = sorted([r for r in res if not r["ok"]], key=lambda r: r["margen"])
    ok = {r["sku"] for r in res if r["ok"]}
    print(f"Plan vigente #{row.id} · {len(res)} SKU evaluados · {len(recos)} con margen < {MARGEN_MIN_DIAS:.0f} días")
    for r in recos:
        print(f"  [{r['prioridad']:5}] {r['sku']} {r['desc'][:36]:36} {r['linea']:12} margen {r['margen']:6.1f} d "
              f"| bodega {_n(r['cap'])} -> {_n(r['sugerido'])}")
    if not a.aplicar:
        print("(solo muestra; --aplicar para dejarlas en el panel)")
        return
    n_new = n_upd = n_cerr = 0
    with engine.begin() as c:
        for r in recos:
            n = c.execute(sa.text("""
                INSERT INTO mrp_params_recomendaciones (entidad, clave, linea, campo, valor_actual, valor_sugerido,
                                                        rango, motivo, prioridad, fuente)
                VALUES ('sku', :s, :l, 'cap_bodega_u', :va, :vs, :rg, :m, :p, :f)
                ON CONFLICT ON CONSTRAINT uq_params_reco DO UPDATE
                   SET valor_actual = EXCLUDED.valor_actual, valor_sugerido = EXCLUDED.valor_sugerido,
                       rango = EXCLUDED.rango, motivo = EXCLUDED.motivo, prioridad = EXCLUDED.prioridad
                 WHERE mrp_params_recomendaciones.estado = 'abierta'
                RETURNING (xmax = 0) AS nueva"""),
                {"s": r["sku"], "l": r["linea"], "va": r["cap"], "vs": r["sugerido"], "rg": r["rango"],
                 "m": r["motivo"][:1900], "p": r["prioridad"], "f": FUENTE}).first()
            if n is not None:
                n_new += 1 if n.nueva else 0
                n_upd += 0 if n.nueva else 1
        # abiertas de esta fuente cuyo SKU ya tiene margen suficiente: se descartan solas
        if ok:
            n_cerr = c.execute(sa.text("""
                UPDATE mrp_params_recomendaciones
                   SET estado = 'descartada', estado_por = 'Sistema', estado_en = now(),
                       motivo = motivo || ' | Cerrada automáticamente: el margen entre SS y bodega ya supera 7 días.'
                 WHERE fuente = :f AND estado = 'abierta' AND entidad = 'sku' AND clave = ANY(:ok)"""),
                {"f": FUENTE, "ok": sorted(ok)}).rowcount
    print(f"Panel de parámetros: {n_new} nuevas · {n_upd} actualizadas · {n_cerr} cerradas (ya no aplican)")


if __name__ == "__main__":
    main()
