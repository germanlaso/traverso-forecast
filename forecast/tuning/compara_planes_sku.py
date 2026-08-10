#!/usr/bin/env python3
"""
compara_planes_sku.py — Compara DOS planes para UN SKU. SOLO LECTURA.

Para qué: el plan 137 (cron de las 06:00) y el 138 (corrida con eventos) se
generaron el mismo día con el mismo stock. La única diferencia intencional es la
corrección del forecast del ketchup. Esto muestra en qué se traduce.

OJO CON LA ATRIBUCIÓN: entre 137 y 138 cambiaron TRES cosas, no una —
  1. la corrección del evento en 250010495 (lo que buscábamos)
  2. la Pasada A convergió (gap 5,81 -> OPTIMAL 0,0), así que el Q* del 137
     era una cota superior, no el óptimo
  3. las OV abiertas de HANA pasaron de 179 a 186 SKU con pedido
Las diferencias que se ven abajo son el efecto CONJUNTO. Para el SKU corregido
la lectura es limpia (nadie más le toca el forecast); para los demás SKU de la
misma línea, no.

SOLO SELECT. No escribe, no promueve, no toca el plan vigente.

USO
---
    python3 /app/tuning/compara_planes_sku.py
    python3 /app/tuning/compara_planes_sku.py --a 137 --b 138 --sku 250010495
    python3 /app/tuning/compara_planes_sku.py --a 137 --b 138 --sku 250010495 --linea
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, "/app")

from sqlalchemy import text

from db_mrp import SessionLocal

ESTADOS = ("QUIEBRE", "RIESGO", "BAJO_SS", "OK")


def semana(fecha_iso: str) -> str:
    d = date.fromisoformat(fecha_iso[:10])
    return (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()   # domingo


def cargar(plan_id: int) -> dict:
    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, horizonte_sem, status, gap, aceptable, vigente, "
            "timestamp_stock, created_at, snapshot "
            "FROM mrp_planes WHERE id = :i"), {"i": plan_id}).mappings().first()
    if row is None:
        raise SystemExit(f"No existe el plan {plan_id}.")
    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        snap = json.loads(snap)
    return {"meta": dict(row), "snap": snap}


def quiebres_por_semana(snap: dict, sku: str) -> dict:
    serie = (snap.get("detalle_diario") or {}).get(sku) or {}
    out = defaultdict(lambda: defaultdict(int))
    for fecha, c in serie.items():
        out[semana(fecha)][c.get("estado") or "?"] += 1
    return out


# Claves reales del snapshot (confirmadas el 10-08-2026 en el plan 137).
# Separarlas permite AISLAR los confundidos entre planes:
#   forecast_u     -> lo que cambia la correccion del evento
#   pedidos_u      -> OV de HANA: aca vive el cambio de 179 a 186 SKU con pedido
#   demanda_corr_u -> lo que el MRP realmente consume
CLAVES_DEMANDA = [("forecast_u", "fc"), ("pedidos_u", "ped"),
                  ("demanda_corr_u", "corr")]


def series_por_semana(snap: dict, sku: str) -> dict:
    """Agrega por semana (domingo) cada clave de demanda + los OFT en cajas."""
    serie = (snap.get("detalle_diario") or {}).get(sku) or {}
    out = {k: defaultdict(float) for k, _ in CLAVES_DEMANDA}
    out["oft_cajas"] = defaultdict(float)
    for fecha, c in serie.items():
        sem = semana(fecha)
        for k, _ in CLAVES_DEMANDA:
            out[k][sem] += float(c.get(k) or 0)
        out["oft_cajas"][sem] += float(c.get("oft_cajas") or 0)
    return out


def estructura(snap: dict, sku: str) -> None:
    print("--- claves del snapshot ---")
    print("  raiz:", ", ".join(sorted(snap.keys())[:14]))
    serie = (snap.get("detalle_diario") or {}).get(sku) or {}
    if serie:
        print("  detalle_diario[dia]:", ", ".join(sorted(next(iter(serie.values())).keys())))
    ords = ((snap.get("vista_dashboard") or {}).get("ordenes") or [])
    mio = [o for o in ords if str(o.get("sku")) == str(sku)]
    if mio:
        print("  ordenes[i]:", ", ".join(sorted(mio[0].keys())[:14]))
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=int, default=137)
    ap.add_argument("--b", type=int, default=138)
    ap.add_argument("--sku", default="250010495")
    ap.add_argument("--linea", action="store_true",
                    help="resumen de quiebres de TODA la linea del SKU")
    args = ap.parse_args()

    A, B = cargar(args.a), cargar(args.b)
    sku = args.sku

    print(f"=== PLAN {args.a} vs PLAN {args.b} — SKU {sku} ===")
    for et, P in ((f"plan {args.a}", A), (f"plan {args.b}", B)):
        m = P["meta"]
        print(f"  {et:<10} creado {m['created_at']} | status={m['status']} "
              f"gap={m['gap']} | aceptable={m['aceptable']} | vigente={m['vigente']}")
        print(f"{'':<12} stock del {m['timestamp_stock']}")
    print()

    estructura(A["snap"], sku)

    # ── Quiebres ──────────────────────────────────────────────────────────────
    qa, qb = quiebres_por_semana(A["snap"], sku), quiebres_por_semana(B["snap"], sku)
    semanas = sorted(set(qa) | set(qb))
    print(f"--- DIAS POR ESTADO, por semana (SKU {sku}) ---")
    if not semanas:
        print("  Sin detalle diario para este SKU en ninguno de los dos planes.")
    else:
        print(f"{'semana':<12}{'QUIEBRE':>18}{'RIESGO':>16}{'BAJO_SS':>16}{'OK':>14}")
        print(f"{'':<12}{f'{args.a} -> {args.b}':>18}{f'{args.a} -> {args.b}':>16}"
              f"{f'{args.a} -> {args.b}':>16}{f'{args.a} -> {args.b}':>14}")
        print("-" * 76)
        tot = {e: [0, 0] for e in ESTADOS}
        for sem in semanas:
            celdas = []
            for e, w in zip(ESTADOS, (18, 16, 16, 14)):
                x, y = qa.get(sem, {}).get(e, 0), qb.get(sem, {}).get(e, 0)
                tot[e][0] += x
                tot[e][1] += y
                marca = "" if x == y else ("  v" if y < x else "  ^")
                celdas.append(f"{f'{x} -> {y}{marca}':>{w}}")
            print(f"{sem:<12}" + "".join(celdas))
        print("-" * 76)
        celdas = [f"{f'{tot[e][0]} -> {tot[e][1]}':>{w}}"
                  for e, w in zip(ESTADOS, (18, 16, 16, 14))]
        print(f"{'TOTAL':<12}" + "".join(celdas))
    print()

    # ── Demanda semanal ──────────────────────────────────────────────────────
    sa_, sb_ = series_por_semana(A["snap"], sku), series_por_semana(B["snap"], sku)
    sems = sorted(set(sa_["forecast_u"]) | set(sb_["forecast_u"]))
    print(f"--- DEMANDA SEMANAL en UNIDADES (SKU {sku}) ---")
    if not sems:
        print("  Sin detalle diario para este SKU.")
    else:
        print(f"{'semana':<12}{'fc ' + str(args.a):>10}{'fc ' + str(args.b):>10}"
              f"{'delta%':>9}{'ped ' + str(args.a):>10}{'ped ' + str(args.b):>10}"
              f"{'corr ' + str(args.a):>11}{'corr ' + str(args.b):>11}"
              f"{'oft ' + str(args.a):>10}{'oft ' + str(args.b):>10}")
        print("-" * 103)
        tot = {k: [0.0, 0.0] for k in ("forecast_u", "pedidos_u",
                                       "demanda_corr_u", "oft_cajas")}
        for s_ in sems:
            fx, fy = sa_["forecast_u"][s_], sb_["forecast_u"][s_]
            px, py = sa_["pedidos_u"][s_], sb_["pedidos_u"][s_]
            cx, cy = sa_["demanda_corr_u"][s_], sb_["demanda_corr_u"][s_]
            ox, oy = sa_["oft_cajas"][s_], sb_["oft_cajas"][s_]
            for k, (x, y) in zip(tot, ((fx, fy), (px, py), (cx, cy), (ox, oy))):
                tot[k][0] += x
                tot[k][1] += y
            pct = (100.0 * (fy - fx) / fx) if fx else float("nan")
            spct = f"{pct:+.1f}%" if pct == pct else "  —"
            print(f"{s_:<12}{fx:>10,.0f}{fy:>10,.0f}{spct:>9}"
                  f"{px:>10,.0f}{py:>10,.0f}{cx:>11,.0f}{cy:>11,.0f}"
                  f"{ox:>10,.0f}{oy:>10,.0f}")
        print("-" * 103)
        fx, fy = tot["forecast_u"]
        pct = (100.0 * (fy - fx) / fx) if fx else float("nan")
        spct = f"{pct:+.1f}%" if pct == pct else "  —"
        print(f"{'TOTAL':<12}{fx:>10,.0f}{fy:>10,.0f}{spct:>9}"
              f"{tot['pedidos_u'][0]:>10,.0f}{tot['pedidos_u'][1]:>10,.0f}"
              f"{tot['demanda_corr_u'][0]:>11,.0f}{tot['demanda_corr_u'][1]:>11,.0f}"
              f"{tot['oft_cajas'][0]:>10,.0f}{tot['oft_cajas'][1]:>10,.0f}")
        print()
        print("COMO LEER: `fc` es el forecast, lo unico que cambia la correccion del")
        print("evento. `ped` son las OV de HANA: si cambio, ahi esta el confundido de")
        print("179 -> 186 SKU con pedido, ajeno al evento. `corr` es lo que consume el")
        print("MRP. `oft` son las cajas a producir que decidio el optimizador.")

    # ── Opcional: toda la linea ───────────────────────────────────────────────
    if args.linea:
        print()
        print("--- QUIEBRES POR SKU en el detalle diario (ambos planes) ---")
        print("Incluye SKU que NO tienen evento: sus cambios son reasignacion de")
        print("capacidad, no correccion de forecast. Confundido con las OV nuevas.")
        ddA = A["snap"].get("detalle_diario") or {}
        ddB = B["snap"].get("detalle_diario") or {}
        filas = []
        for s_ in sorted(set(ddA) | set(ddB)):
            na = sum(1 for c in (ddA.get(s_) or {}).values() if c.get("estado") == "QUIEBRE")
            nb = sum(1 for c in (ddB.get(s_) or {}).values() if c.get("estado") == "QUIEBRE")
            if na or nb:
                filas.append((nb - na, s_, na, nb))
        filas.sort()
        print(f"{'sku':<13}{args.a:>6}{args.b:>6}{'delta':>8}")
        print("-" * 33)
        for d, s_, na, nb in filas:
            marca = " <-- este SKU" if s_ == sku else ""
            print(f"{s_:<13}{na:>6}{nb:>6}{d:>+8}{marca}")
        print("-" * 33)
        print(f"{'TOTAL':<13}{sum(f[2] for f in filas):>6}"
              f"{sum(f[3] for f in filas):>6}"
              f"{sum(f[3]-f[2] for f in filas):>+8}")


if __name__ == "__main__":
    main()
