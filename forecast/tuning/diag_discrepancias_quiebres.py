#!/usr/bin/env python3
"""
diag_discrepancias_quiebres.py — Verifica con datos las 4 discrepancias
reportadas entre el Mapa de Quiebres, el gráfico modal y el log del cron.
SOLO LECTURA.

LAS 4 DISCREPANCIAS
-------------------
  1. Mapa dice 38 días de quiebre, el log del cron dice Q*=27
  2. El encabezado del Mapa dice 6 recepciones pendientes, el log dice 7
  3. SKU 141010600: Mapa 2 días de quiebre, modal 1
  4. SKU 251010105: Mapa -103 cj / 1 día, modal stock mínimo +256 cj y 0 días

HIPÓTESIS (de leer el código, a confirmar acá)
---------------------------------------------
  1. Q* NO son días de quiebre del plan. Es la cota que la Pasada A demuestra
     inevitable. El Mapa cuenta días del plan final que produjo la Pasada C.
     Además `stock_disp <= stock_fin` SIEMPRE (la demanda del día se sirve con
     el stock inicial; la producción entra al cierre), así que los quiebres
     intradía son un SUPERCONJUNTO de los de cierre.

  2. main.py L1311 saca `recepcion_pendiente` de `alertas`, pero L1358 descarta
     del Mapa los SKU sin NINGÚN día en problema. Un SKU con recepción
     pendiente y 0 días en problema no aparece.

  3. El snapshot marca QUIEBRE con un criterio; el modal (L1098) usa
     `stock_disp < 0` ESTRICTO. Un día con `stock_disp == 0` exacto se contaría
     en uno y no en el otro. El cartel "-0 cj" del Mapa es la pista: `def_cj =
     ceil(abs(stock_disp_u)/upc)` solo da 0 si `stock_disp_u` es 0 exacto.

  4. Dos variables distintas. El Mapa muestra `def_cj` sobre `stock_disp_u`
     (intradía, L1371); el "STOCK MÍNIMO" del modal sale de `stock_fin_u`
     (cierre, L1133). Y el modal RECALCULA con las OF aprobadas vivas, así que
     una OF aprobada después del plan puede borrar el quiebre.

USO
---
    python3 /app/tuning/diag_discrepancias_quiebres.py
    python3 /app/tuning/diag_discrepancias_quiebres.py --plan 140 --skus 141010600,251010105
"""
import argparse
import json
import sys
from collections import defaultdict

sys.path.insert(0, "/app")

from sqlalchemy import text

from db_mrp import SessionLocal


def cargar(plan_id=None):
    q = ("SELECT id, status, gap, vigente, timestamp_stock, snapshot "
         "FROM mrp_planes WHERE " + ("id = :i" if plan_id else "vigente") + " LIMIT 1")
    with SessionLocal() as s:
        row = s.execute(text(q), {"i": plan_id} if plan_id else {}).mappings().first()
    if row is None:
        raise SystemExit("No hay plan.")
    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        snap = json.loads(snap)
    return dict(row), snap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=int, default=None)
    ap.add_argument("--skus", default="141010600,251010105")
    args = ap.parse_args()

    meta, snap = cargar(args.plan)
    dd = snap.get("detalle_diario") or {}
    alertas = snap.get("alertas") or []
    encab = snap.get("encabezado_sku") or {}

    print(f"=== PLAN {meta['id']} (vigente={meta['vigente']}) ===")
    print(f"    status={meta['status']} gap={meta['gap']} | stock del {meta['timestamp_stock']}")
    print(f"    {len(dd)} SKU en detalle_diario | {len(alertas)} alertas")
    print()

    # ── 1) Días de quiebre: cuántos y medidos sobre qué ───────────────────────
    print("--- 1) DÍAS DE QUIEBRE vs Q* ---")
    n_q = n_disp_neg = n_disp_cero = n_disp_pos = n_fin_neg = 0
    skus_q = set()
    for sku, serie in dd.items():
        for f, c in serie.items():
            if c.get("estado") != "QUIEBRE":
                continue
            n_q += 1
            skus_q.add(sku)
            sd = c.get("stock_disp_u")
            sf = c.get("stock_fin_u")
            if sd is not None:
                if sd < 0:    n_disp_neg += 1
                elif sd == 0: n_disp_cero += 1
                else:         n_disp_pos += 1
            if sf is not None and sf < 0:
                n_fin_neg += 1
    print(f"  días con estado=QUIEBRE en el snapshot : {n_q}")
    print(f"  SKU con al menos un día en QUIEBRE     : {len(skus_q)}")
    print(f"    de esos días, stock_disp_u  < 0      : {n_disp_neg}")
    print(f"    de esos días, stock_disp_u == 0      : {n_disp_cero}   <-- el criterio")
    print(f"    de esos días, stock_disp_u  > 0      : {n_disp_pos}")
    print(f"    de esos días, stock_fin_u   < 0      : {n_fin_neg}   <-- comparable a Q*")
    print()
    print("  Q* de la Pasada A (del log del cron) NO es esta cuenta: es la cota de")
    print("  quiebres INEVITABLES sobre stock_fin. Si `stock_fin_u < 0` se acerca a")
    print("  Q* y el total es mayor, la diferencia es intradía, no un error.")
    print()

    # ── 2) Recepción pendiente ────────────────────────────────────────────────
    print("--- 2) RECEPCIÓN PENDIENTE: log vs Mapa ---")
    rp = sorted({a.get("sku") for a in alertas
                 if a.get("tipo") == "RECEPCION_PENDIENTE" and a.get("sku")})
    print(f"  alertas tipo RECEPCION_PENDIENTE: {len(rp)} SKU")
    print(f"{'sku':<13}{'en detalle':>11}{'peor estado':>14}  entra al Mapa")
    print("  " + "-" * 52)
    n_visibles = 0
    ORDEN = {"OK": 0, "BAJO_SS": 1, "RIESGO": 2, "QUIEBRE": 3}
    for sku in rp:
        serie = dd.get(sku)
        if not serie:
            print(f"{sku:<13}{'NO':>11}{'—':>14}  no (sin detalle)")
            continue
        peor = max((ORDEN.get(c.get("estado"), 0) for c in serie.values()), default=0)
        nombre = [k for k, v in ORDEN.items() if v == peor][0]
        # main.py L1358: los SKU sin ningún día en problema quedan fuera del Mapa
        visible = peor > 0
        n_visibles += 1 if visible else 0
        print(f"{sku:<13}{'sí':>11}{nombre:>14}  {'sí' if visible else 'NO (peor=OK)'}")
    print("  " + "-" * 52)
    print(f"  visibles en el Mapa: {n_visibles} de {len(rp)}")
    print("  Si sale 6 de 7, la discrepancia queda explicada: main.py L1358 descarta")
    print("  del Mapa los SKU sin ningún día en problema.")
    print()

    # ── 3 y 4) Los dos SKU en detalle ─────────────────────────────────────────
    for sku in [x.strip() for x in args.skus.split(",") if x.strip()]:
        print(f"--- SKU {sku} — {(encab.get(sku) or {}).get('descripcion', '?')} ---")
        serie = dd.get(sku)
        if not serie:
            print("  sin detalle diario en este plan.")
            print()
            continue
        upc = int((encab.get(sku) or {}).get("u_por_caja") or 1)
        print(f"  u_por_caja = {upc}")
        print(f"{'fecha':<12}{'estado':<10}{'st_disp_u':>11}{'st_fin_u':>10}"
              f"{'ss_u':>9}{'oft_cj':>8}{'entr_apr':>10}{'def_cj':>8}")
        print("  " + "-" * 76)
        n_qs = mins_disp = None
        n_qs = 0
        min_disp = min_fin = None
        for f in sorted(serie):
            c = serie[f]
            sd, sf = c.get("stock_disp_u"), c.get("stock_fin_u")
            est = c.get("estado") or "?"
            if est == "QUIEBRE":
                n_qs += 1
            if sd is not None:
                min_disp = sd if min_disp is None else min(min_disp, sd)
            if sf is not None:
                min_fin = sf if min_fin is None else min(min_fin, sf)
            # def_cj tal como lo calcula el Mapa (main.py L1371-1377)
            base = sd if sd is not None else sf
            import math
            dcj = int(math.ceil(abs(base) / upc)) if (est == "QUIEBRE" and base is not None and upc) else 0
            marca = "  <<<" if est == "QUIEBRE" else ""
            if est != "OK":
                print(f"{f[:10]:<12}{est:<10}{(sd if sd is not None else 0):>11,}"
                      f"{(sf if sf is not None else 0):>10,}{(c.get('ss_u') or 0):>9,}"
                      f"{(c.get('oft_cajas') or 0):>8,.0f}"
                      f"{(c.get('entrada_aprobada_u') or 0):>10,}{dcj:>8}{marca}")
        print("  " + "-" * 76)
        print(f"  días en QUIEBRE (snapshot)        : {n_qs}")
        print(f"  mínimo stock_disp_u (intradía)    : {min_disp:,} u = "
              f"{(min_disp / upc if upc else 0):,.0f} cj   <- lo que muestra el Mapa")
        print(f"  mínimo stock_fin_u  (cierre)      : {min_fin:,} u = "
              f"{(min_fin / upc if upc else 0):,.0f} cj   <- el STOCK MÍNIMO del modal")
        print()

    print("=" * 78)
    print("NOTA: el modal usa /plan/proyeccion_diaria_live, que RECALCULA el balance")
    print("con las OF aprobadas VIVAS de mrp_aprobaciones. Si se aprobó una OF")
    print("después de que corrió el plan, la curva del modal puede no tener un")
    print("quiebre que el snapshot sí tiene. Para descartar eso, comparar la columna")
    print("entr_apr de arriba contra las aprobaciones vigentes del SKU.")


if __name__ == "__main__":
    main()
