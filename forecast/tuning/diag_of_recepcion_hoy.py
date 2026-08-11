#!/usr/bin/env python3
"""
diag_of_recepcion_hoy.py — ¿Cuántas OF aprobadas con `fecha_entrada_real == hoy`
quedan fuera del plan SIN estar en el stock? SOLO LECTURA.

EL PROBLEMA
-----------
`cron_plan.py` L281 filtra las entradas fijas con `fer > hoy_str`. La
justificación documentada (L483-487, decidida el 29-07-2026) es:

    "Una OF con fecha_entrada_real == hoy YA está contabilizada en el stock que
     leímos hoy. Sumarla como entrada futura sería DOBLE CONTEO."

La lógica es correcta SI la premisa se cumple. El 11-08-2026 apareció un caso
donde NO se cumple: `251010105` tiene `OFM-000097` con `fer = 2026-08-11` por
900 cj, y el stock físico del plan es 368 cj. Es aritméticamente imposible que
la OF esté contabilizada.

Consecuencia: el plan ve 900 cj menos de las que van a existir, reporta QUIEBRE
el 17-08 (-102,5 cj, exactamente 900 menos que los 797,5 del modal) y genera
producción para cubrirlo. En una línea al 100% de uso, esa producción fantasma
le saca capacidad a SKU que sí la necesitan.

QUÉ MIDE ESTO
-------------
Para cada OF aprobada con `fer == hoy` (el `hoy` del plan vigente):
  · cantidad de la OF vs stock físico del SKU en el plan
  · si stock < cantidad_OF, la premisa está VIOLADA: la OF no puede estar dentro
  · días de QUIEBRE del SKU que desaparecerían si la OF se contara
  · cajas de OFT que el plan generó para ese SKU (producción posiblemente fantasma)

NO propone cambiar `>` por `>=`: la advertencia del 29-07 es correcta y el doble
conteo produce quiebres REALES, que es el error peligroso. Esto mide si conviene
VERIFICAR la premisa (con el mismo balance de inventario que ya usa la alerta
RECEPCION_PENDIENTE) en vez de asumirla.

USO
---
    python3 /app/tuning/diag_of_recepcion_hoy.py
    python3 /app/tuning/diag_of_recepcion_hoy.py --fecha 2026-08-11
"""
import argparse
import json
import sys
from datetime import date

sys.path.insert(0, "/app")

from sqlalchemy import text

from db_mrp import SessionLocal, listar_aprobadas_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", default=None,
                    help="dia a evaluar (default: la fecha del stock del plan vigente)")
    args = ap.parse_args()

    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, created_at, timestamp_stock, snapshot "
            "FROM mrp_planes WHERE vigente LIMIT 1")).mappings().first()
    if row is None:
        raise SystemExit("No hay plan vigente.")
    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        snap = json.loads(snap)

    hoy = args.fecha or str(row["timestamp_stock"])[:10]
    print(f"=== PLAN {row['id']} — OF con recepcion el {hoy} ===")
    print(f"    plan creado {row['created_at']} | stock del {row['timestamp_stock']}")
    print()

    dd = snap.get("detalle_diario") or {}
    encab = snap.get("encabezado_sku") or {}

    # OF aprobadas con fer == hoy: las que el filtro `fer > hoy_str` descarta
    aprob = listar_aprobadas_db()
    hoy_of = []
    for a in aprob:
        fer = str(a.get("fecha_entrada_real") or a.get("semana_necesidad") or "")[:10]
        if fer == hoy:
            hoy_of.append((a, fer))

    if not hoy_of:
        print("Ninguna OF aprobada tiene recepcion hoy. No hay nada que revisar.")
        return

    print(f"{len(hoy_of)} OF aprobada(s) con recepcion hoy, todas EXCLUIDAS del plan")
    print()
    print(f"{'sku':<12}{'OF':<17}{'of_cj':>8}{'stock_cj':>10}{'premisa':>10}"
          f"{'q_plan':>8}{'q_con_of':>10}{'oft_cj':>9}")
    print("-" * 84)

    n_violada = 0
    tot_of_cj = tot_oft_cj = 0.0
    n_q_evit = 0
    detalle_violadas = []

    for a, fer in sorted(hoy_of, key=lambda x: str(x[0].get("sku"))):
        sku = str(a.get("sku"))
        of_cj = float(a.get("cantidad_real_cj") or 0)
        e = encab.get(sku) or {}
        upc = int(e.get("u_por_caja") or 1)
        stock_u = float(e.get("stock_fisico_u") or 0)
        stock_cj = stock_u / upc if upc else 0.0
        of_u = of_cj * upc

        # La premisa "la OF ya esta en el stock" es imposible si el stock es
        # MENOR que la propia OF.
        violada = stock_cj + 0.5 < of_cj

        serie = dd.get(sku) or {}
        q_plan = sum(1 for c in serie.values() if c.get("estado") == "QUIEBRE")
        # quiebres que desaparecerian si la OF se contara como entrada ese dia:
        # a partir de `hoy` el stock disponible seria +of_u
        q_con_of = 0
        for f, c in serie.items():
            if c.get("estado") != "QUIEBRE":
                continue
            sd = c.get("stock_disp_u")
            if sd is None:
                continue
            if f[:10] >= hoy and sd + of_u >= 0:
                continue          # el quiebre desaparece
            q_con_of += 1
        oft_cj = sum(float(c.get("oft_cajas") or 0) for c in serie.values())

        if violada:
            n_violada += 1
            tot_of_cj += of_cj
            tot_oft_cj += oft_cj
            n_q_evit += (q_plan - q_con_of)
            detalle_violadas.append((sku, of_cj, serie, of_u, hoy))

        print(f"{sku:<12}{str(a.get('numero_of'))[:16]:<17}{of_cj:>8,.0f}"
              f"{stock_cj:>10,.0f}{'VIOLADA' if violada else 'ok':>10}"
              f"{q_plan:>8}{q_con_of:>10}{oft_cj:>9,.0f}")

    print("-" * 84)
    print(f"OF con premisa VIOLADA (stock < cantidad de la OF): {n_violada} de {len(hoy_of)}")
    if n_violada:
        print(f"  cajas no contabilizadas          : {tot_of_cj:,.0f} cj")
        print(f"  dias de QUIEBRE que desaparecen  : {n_q_evit}")
        print(f"  OFT del plan en esos SKU         : {tot_oft_cj:,.0f} cj "
              f"(candidata a produccion fantasma)")

    # Detalle dia por dia de los casos violados
    for sku, of_cj, serie, of_u, _h in detalle_violadas:
        upc = int((encab.get(sku) or {}).get("u_por_caja") or 1)
        print()
        print(f"--- {sku}: dias en QUIEBRE y su magnitud con/sin la OF de {of_cj:,.0f} cj ---")
        print(f"{'fecha':<12}{'st_disp_cj':>12}{'con_OF_cj':>11}{'oft_cj':>8}  estado con la OF")
        for f in sorted(serie):
            c = serie[f]
            if c.get("estado") != "QUIEBRE":
                continue
            sd = c.get("stock_disp_u")
            if sd is None:
                continue
            con = (sd + of_u) if f[:10] >= hoy else sd
            print(f"{f[:10]:<12}{sd / upc:>12,.1f}{con / upc:>11,.1f}"
                  f"{float(c.get('oft_cajas') or 0):>8,.0f}"
                  f"  {'ya no es quiebre' if con >= 0 else 'sigue en quiebre'}")

    print()
    print("LECTURA:")
    print("  · 'premisa VIOLADA' = el stock fisico del SKU es MENOR que la propia OF,")
    print("    asi que la OF no puede estar contabilizada en el (L483-487 de cron_plan).")
    print("  · Si hay pocas OF violadas, es un caso borde. Si son varias, el supuesto")
    print("    del 29-07 no se sostiene y conviene VERIFICARLO por balance de")
    print("    inventario, como ya hace la alerta RECEPCION_PENDIENTE para `fer` de ayer.")
    print("  · Verificar NO es lo mismo que cambiar `>` por `>=`: contar una OF que SI")
    print("    esta en el stock produce quiebres REALES, que es el error peligroso.")


if __name__ == "__main__":
    main()
