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


def ordenes_por_semana(snap: dict, sku: str) -> dict:
    """Cajas a producir por semana, del vista_dashboard.ordenes."""
    ords = ((snap.get("vista_dashboard") or {}).get("ordenes") or [])
    out = defaultdict(float)
    for o in ords:
        if str(o.get("sku")) != str(sku):
            continue
        sem = o.get("semana_necesidad") or o.get("semana") or "?"
        out[str(sem)[:10]] += float(o.get("cantidad_cajas") or 0)
    return out


def demanda_por_semana(snap: dict, sku: str) -> tuple[dict, str]:
    """Demanda semanal. Busca la clave real en el snapshot en vez de suponerla."""
    # 1) intento en el detalle diario
    serie = (snap.get("detalle_diario") or {}).get(sku) or {}
    if serie:
        muestra = next(iter(serie.values()))
        for k in ("demanda_u", "demanda", "consumo_u", "salidas_u", "venta_u"):
            if k in muestra:
                out = defaultdict(float)
                for fecha, c in serie.items():
                    out[semana(fecha)] += float(c.get(k) or 0)
                return out, f"detalle_diario.{k}"
    # 2) intento en la proyeccion por SKU del dashboard
    proy = ((snap.get("vista_dashboard") or {}).get("proyeccion_por_sku") or {}).get(sku)
    if isinstance(proy, list) and proy:
        m = proy[0]
        for k in ("demanda_cj", "demanda", "forecast_cj", "forecast", "demanda_u"):
            if k in m:
                out = defaultdict(float)
                for p in proy:
                    sem = str(p.get("semana") or p.get("ds") or "?")[:10]
                    out[sem] += float(p.get(k) or 0)
                return out, f"proyeccion_por_sku.{k}"
    return {}, "(no encontrada)"


def estructura(snap: dict, sku: str) -> None:
    print("--- claves del snapshot ---")
    print("  raiz:", ", ".join(sorted(snap.keys())[:14]))
    serie = (snap.get("detalle_diario") or {}).get(sku) or {}
    if serie:
        print("  detalle_diario[dia]:", ", ".join(sorted(next(iter(serie.values())).keys())))
    proy = ((snap.get("vista_dashboard") or {}).get("proyeccion_por_sku") or {}).get(sku)
    if isinstance(proy, list) and proy:
        print("  proyeccion_por_sku[i]:", ", ".join(sorted(proy[0].keys())))
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

    # ── Demanda semanal ───────────────────────────────────────────────────────
    da, fa = demanda_por_semana(A["snap"], sku)
    db_, fb = demanda_por_semana(B["snap"], sku)
    print(f"--- DEMANDA SEMANAL (fuente: {fa}) ---")
    if not da and not db_:
        print("  No se encontro una clave de demanda en el snapshot.")
        print("  Ver la seccion 'claves del snapshot' de arriba y avisar cual es.")
    else:
        oa, ob = ordenes_por_semana(A["snap"], sku), ordenes_por_semana(B["snap"], sku)
        sem2 = sorted(set(da) | set(db_) | set(oa) | set(ob))
        print(f"{'semana':<12}{f'dem {args.a}':>12}{f'dem {args.b}':>12}{'delta':>10}"
              f"{'%':>8}   {f'prod {args.a}':>12}{f'prod {args.b}':>12}")
        print("-" * 80)
        sa = sb = 0.0
        for s_ in sem2:
            x, y = da.get(s_, 0.0), db_.get(s_, 0.0)
            sa += x
            sb += y
            d = y - x
            pct = (100.0 * d / x) if x else float("nan")
            spct = f"{pct:+.1f}%" if pct == pct else "  —"
            print(f"{s_:<12}{x:>12,.0f}{y:>12,.0f}{d:>+10,.0f}{spct:>8}   "
                  f"{oa.get(s_, 0):>12,.0f}{ob.get(s_, 0):>12,.0f}")
        print("-" * 80)
        dt = sb - sa
        pt = (100.0 * dt / sa) if sa else float("nan")
        spt = f"{pt:+.1f}%" if pt == pt else "  —"
        print(f"{'TOTAL':<12}{sa:>12,.0f}{sb:>12,.0f}{dt:>+10,.0f}{spt:>8}   "
              f"{sum(oa.values()):>12,.0f}{sum(ob.values()):>12,.0f}")

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
