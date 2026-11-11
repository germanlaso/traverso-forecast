"""
revisar_params_42h.py — Revisión de parámetros por el cambio a jornada de 42 h (9-9-8-8-8).

Para cada SKU activo, contra su línea PREFERIDA (y avisando de las alternativas), con la
capacidad del calendario (mrp_lineas.turnos_config):
  ERROR   batch mínimo > día más largo           -> no se puede programar ningún día
  ALTA    batch mínimo > día más corto (8 h)     -> solo cabe lunes y martes
  MEDIA   batch mínimo > 90% del día más corto   -> frágil ante cualquier detención
  ALTA    cap. bodega < batch mínimo propuesto   -> la propuesta choca con la bodega

Propuesta de batch: el mayor múltiplo de u/caja que cabe en el día más corto
(o en el 90% del día más corto, para el caso frágil), considerando el factor de velocidad.
Las propuestas van al panel de parámetros como RECOMENDACIÓN IA (no se aplican solas):
quedan con un motivo prellenado y, al usarlas, el cambio queda en el historial.

Uso (dentro del contenedor):
  python3 /app/revisar_params_42h.py            # solo muestra
  python3 /app/revisar_params_42h.py --aplicar  # crea las recomendaciones en el panel
"""
import argparse
import json
from collections import defaultdict

import sqlalchemy as sa

import params_diagnostico as pd_
from db_mrp import engine

FUENTE = "Cambio jornada 42 h semanales (11-11-2026)"
UMBRAL_FRAGIL = 0.90


def _n(x):   # 20400 -> "20.400"
    return f"{int(x):,}".replace(",", ".")


def _h(x):   # 7.99 -> "8,0"
    return f"{x:.1f}".replace(".", ",")


def revisar():
    with engine.connect() as c:
        lineas = {r.codigo: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_lineas WHERE activa"))}
        prods = {r.sku: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params WHERE activo"))}
        pares = defaultdict(list)
        for r in c.execute(sa.text("SELECT sku, linea, preferida, factor_velocidad FROM mrp_sku_lineas")):
            pares[r.sku].append(dict(r._mapping))
    sin_cal = [l for l, L in lineas.items() if not pd_._turnos_config(L.get("turnos_config"))]
    hallazgos = []
    for sku, p in prods.items():
        bmin = int(p.get("batch_min_u") or 0)
        upc = int(p.get("u_por_caja") or 1) or 1
        if bmin <= 0 or not pares.get(sku):
            continue
        ps = sorted(pares[sku], key=lambda x: (not x["preferida"], x["linea"]))
        pref = ps[0]
        L = lineas.get(pref["linea"])
        if L is None:
            continue
        der = pd_.derivados_linea(L)
        f = float(pref.get("factor_velocidad") or 1.0) or 1.0
        vel = der["velocidad_u_hr"] * f
        if vel <= 0:
            continue
        cap_max, cap_min = der["cap_dia_u"] * f, der["cap_dia_min_u"] * f
        h_batch = bmin / vel
        if bmin > cap_max + 1e-6:
            nivel, prioridad, objetivo = "ERROR", "alta", cap_min
            texto = f"no cabe en ningún día (día más largo {der['horas_dia']:g} h)"
        elif bmin > cap_min + 1e-6:
            nivel, prioridad, objetivo = "ALTA", "alta", cap_min
            texto = f"solo cabe en los días de {der['horas_dia']:g} h (lunes y martes), no en los de {der['horas_dia_min']:g} h"
        elif bmin > UMBRAL_FRAGIL * cap_min and float(L.get("horas_turno") or 0) * int(L.get("turnos_dia") or 1) > der["horas_dia_min"] + 1e-6:
            # solo si la fragilidad es NUEVA: la línea perdió horas en sus días cortos con el cambio
            # (las líneas que ya eran de 8 h tenían la misma holgura antes: no es efecto del cambio)
            nivel, prioridad, objetivo = "MEDIA", "media", UMBRAL_FRAGIL * cap_min
            texto = (f"usa el {bmin / cap_min:.0%} de un día de {der['horas_dia_min']:g} h: "
                     f"frágil ante cualquier detención")
        else:
            continue
        propuesto = int(objetivo // upc) * upc
        cap_bod = int(p.get("cap_bodega_u") or 999999)
        otras = [x["linea"] for x in ps[1:]]
        motivo = (f"Cambio a jornada de 42 h semanales (9-9-8-8-8): el batch mínimo actual "
                  f"({_n(bmin)} u = {_h(h_batch)} h en {pref['linea']}) {texto}. "
                  f"Se propone {_n(propuesto)} u ({_h(propuesto / vel)} h), que cabe todos los días."
                  + (f" También corre en {', '.join(otras)}: verificar." if otras else "")
                  + (" Atención: la cap. bodega es menor que el batch propuesto." if cap_bod < propuesto else ""))
        hallazgos.append({"sku": sku, "descripcion": p.get("descripcion"), "linea": pref["linea"], "nivel": nivel,
                          "prioridad": prioridad, "batch_actual_u": bmin, "batch_actual_h": round(h_batch, 2),
                          "batch_propuesto_u": propuesto, "batch_propuesto_h": round(propuesto / vel, 2),
                          "cap_bodega_u": cap_bod, "motivo": motivo})
    orden = {"ERROR": 0, "ALTA": 1, "MEDIA": 2}
    hallazgos.sort(key=lambda h: (orden[h["nivel"]], h["linea"], h["sku"]))
    return hallazgos, sin_cal


def aplicar(hallazgos):
    n = 0
    with engine.begin() as c:
        for h in hallazgos:
            n += c.execute(sa.text("""
                INSERT INTO mrp_params_recomendaciones
                    (entidad, clave, linea, campo, valor_actual, valor_sugerido, rango, motivo, prioridad, fuente)
                VALUES ('sku', :s, '', 'batch_min_u', :va, :vs, :r, :m, :p, :f)
                ON CONFLICT ON CONSTRAINT uq_params_reco DO NOTHING"""),
                {"s": h["sku"], "va": h["batch_actual_u"], "vs": h["batch_propuesto_u"],
                 "r": f"≤ {h['batch_propuesto_h']} h de línea", "m": h["motivo"][:2000],
                 "p": h["prioridad"], "f": FUENTE}).rowcount
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="crea las recomendaciones en el panel")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    hz, sin_cal = revisar()
    if sin_cal:
        print("ATENCIÓN: líneas sin turnos_config (se evalúan con el legado):", sin_cal)
    if a.json:
        print(json.dumps(hz, ensure_ascii=False, indent=2))
    else:
        por = defaultdict(int)
        for h in hz:
            por[h["nivel"]] += 1
        print(f"Hallazgos: {len(hz)}  |  " + "  ".join(f"{k}={v}" for k, v in sorted(por.items())))
        for h in hz:
            print(f"  [{h['nivel']:5}] {h['linea']:12} {h['sku']:10} {str(h['descripcion'])[:34]:34} "
                  f"{h['batch_actual_u']:>7} u ({h['batch_actual_h']:>4} h) -> {h['batch_propuesto_u']:>7} u "
                  f"({h['batch_propuesto_h']:>4} h)" + ("  ⚠ cap. bodega" if h["cap_bodega_u"] < h["batch_propuesto_u"] else ""))
    if a.aplicar:
        print(f"Recomendaciones creadas en el panel: {aplicar(hz)} (fuente: {FUENTE})")
