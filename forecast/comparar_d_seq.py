# -*- coding: utf-8 -*-
"""comparar_d_seq.py (24-11-2026) - SOLO LECTURA. Corre la Pasada D en modo standalone sobre
un plan extraido (extraer_comparacion_planes.py) e imprime metricas y la secuencia de una linea.

La version de la D la decide la variable de entorno N2_D_SEQ_V2 (0 = actual, 1 = secuencia v2).
Correrlo dos veces (0 y 1) sobre el mismo archivo para comparar. No persiste nada.

Uso (dentro del container):
    N2_D_SEQ_V2=0 python3 /tmp/comparar_d_seq.py /tmp/plan.json.gz --linea "L1Pet LV" --dias 14
"""
import argparse
import logging
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, "/app")
import pasada_d as P  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("cmp")
ap.add_argument("--cual", default="base")
ap.add_argument("--linea", default="L1Pet LV")
ap.add_argument("--dias", type=int, default=14)
a = ap.parse_args()
logging.basicConfig(level=logging.WARNING)

D = P.Datos.desde_cmp(a.cmp, a.cual)
PC = {k: v for k, v in D.prodC.items() if v > 0.5}
t0 = time.time()
PD, log, desde, vent = P.optimizar(D)
print(f"== Pasada D {'v2 (N2_D_SEQ_V2=1)' if P.SEQ_V2 else 'ACTUAL (N2_D_SEQ_V2=0)'} | desde {desde} | "
      f"{len(log)} linea-semanas | {time.time() - t0:.0f}s")
print(f"control (quiebres, bajo SS, alertas): {P._contar(D, PC)} -> {P._contar(D, PD)}")
lineas = sorted(D.L)
eC, eD = P.evaluar(D, PC, vent, lineas), P.evaluar(D, PD, vent, lineas)
print(f"{'metrica':14} {'entrada':>10} {'D':>10}")
for k in ("abiertos", "ocup", "arr_sku", "of_sku_sem", "inv_semana", "h_cambio", "viol", "lavados",
          "cambio_fam_fin", "quiebres", "bajo_ss", "unidades"):
    print(f"{k:14} {eC.get(k, 0):10.2f} {eD.get(k, 0):10.2f}")

# Secuencia de la linea pedida (mismo orden intradia que usa la D al escribir las OF)
norm = lambda x: str(x).upper().replace(" ", "").replace("_", "")
lin = next((l for l in D.L if norm(a.linea) in norm(l) or norm(a.linea) in norm(D.L[l].get("nombre", ""))), None)
if lin is None:
    print(f"\nLinea '{a.linea}' no encontrada. Disponibles: {sorted(D.L)}")
    sys.exit(0)
d0 = P._d(desde)
hasta = (d0 + timedelta(days=a.dias)).isoformat()
por_dia = defaultdict(dict)
for (s, l, f), u in PD.items():
    if l == lin and u > 0.5 and desde <= f < hasta:
        por_dia[f][s] = u
print(f"\nSecuencia {lin} ({desde} a {hasta}):")
ultimo = None
dias = sorted(por_dia)
for i, f in enumerate(dias):
    siguen = frozenset(por_dia[dias[i + 1]]) if i + 1 < len(dias) else frozenset()
    orden, h, v = P.mejor_orden(D.A, por_dia[f], ultimo, siguen)
    txt = " -> ".join(f"{(D.sp[s].get('descripcion') or s)[:28]} ({por_dia[f][s] / D.A[s]['upc']:.0f} cj)" for s in orden)
    print(f"  {f} [{h:.1f} h cambio, {v} viol]: {txt}")
    ultimo = orden[-1] if orden else ultimo
