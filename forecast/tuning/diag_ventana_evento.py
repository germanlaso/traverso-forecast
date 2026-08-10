"""
diag_ventana_evento.py — Re-deriva la ventana del evento del competidor.
SOLO LECTURA.

CONTEXTO
--------
El 05-08-2026 se validó a mano, desde la pestaña de exploración, una ventana de
evento para 250010495 que bajó el forecast de oct-nov de 2.776 a ~844 cj/sem
manteniendo septiembre en 950-1.092. Ese set de domingos NUNCA quedó registrado
en un script: se tipeó en un formulario. Este diagnóstico lo re-deriva de forma
reproducible y auditable.

MÉTODO (el mismo del 05-08)
---------------------------
Para cada domingo del rango candidato se compara la venta real contra la MISMA
SEMANA ISO de los otros años disponibles en la historia del modelo. Las semanas
cuyo ratio supera el umbral son las que integran el evento. Se reporta además el
ratio contra el nivel pre-evento como control.

Por qué semana ISO y no "mismo mes": el pico del competidor no respeta bordes de
mes, y el cierre del 05-08 dejó constancia de que el rango grueso sep-nov
SOBRE-CORRIGE (septiembre cayó a 181 cj). La granularidad correcta es la semana.

UNIDADES
--------
Todo en CAJAS/semana — es la unidad de `m.history` (misma que evento2024.py).

GARANTÍAS
---------
No entrena, no llama a save_model/train_model/run_sku_pipeline, no escribe en la
BD, no crea archivos. Solo `load_model` + lectura de `m.history` + prints.

USO
---
    python3 /tmp/diag_ventana_evento.py                      # 250010495, umbral 1.8
    python3 /tmp/diag_ventana_evento.py 250010495 1.5
    python3 /tmp/diag_ventana_evento.py 260010495 1.5 2024-08-01 2025-02-28
"""
import sys

import pandas as pd

from forecaster import load_model, make_key

# ── Parámetros ────────────────────────────────────────────────────────────────
SKU     = sys.argv[1] if len(sys.argv) > 1 else "250010495"
UMBRAL  = float(sys.argv[2]) if len(sys.argv) > 2 else 1.8
DESDE   = sys.argv[3] if len(sys.argv) > 3 else "2024-08-01"
HASTA   = sys.argv[4] if len(sys.argv) > 4 else "2025-01-31"

# Nivel pre-evento, como control (mismas fechas que evento2024.py)
PRE_DESDE, PRE_HASTA = "2024-05-01", "2024-08-31"

# Mínimo de años de comparación para que un ratio ISO sea confiable
MIN_ANIOS_COMP = 1


def tramos_contiguos(domingos: list[pd.Timestamp]) -> list[tuple]:
    """Agrupa domingos consecutivos (paso de 7 días) en tramos [inicio, fin].

    Un domingo aislado devuelve un tramo de una sola semana (inicio == fin).
    """
    if not domingos:
        return []
    ds = sorted(domingos)
    tramos = []
    ini = prev = ds[0]
    for d in ds[1:]:
        if (d - prev).days == 7:
            prev = d
            continue
        tramos.append((ini, prev))
        ini = prev = d
    tramos.append((ini, prev))
    return tramos


def main() -> None:
    cached = load_model(make_key(SKU, None, None))
    if not cached:
        print(f"SKU {SKU}: sin modelo entrenado en caché. Nada que analizar.")
        return
    model, meta = cached

    h = model.history.copy()
    h["ds"] = pd.to_datetime(h["ds"])
    h = h[["ds", "y"]].sort_values("ds").reset_index(drop=True)

    print(f"=== VENTANA DE EVENTO — SKU {SKU} (cajas/semana) ===")
    print(f"historia del modelo: {h['ds'].min():%Y-%m-%d} -> {h['ds'].max():%Y-%m-%d}"
          f"  ({len(h)} semanas)")
    trained = (meta or {}).get("trained_at") if isinstance(meta, dict) else None
    print(f"modelo entrenado:    {trained or '?'}")
    print(f"rango candidato:     {DESDE} -> {HASTA}   | umbral ratio ISO >= {UMBRAL}")

    # Nivel pre-evento (control)
    pre = h[(h["ds"] >= PRE_DESDE) & (h["ds"] <= PRE_HASTA)]["y"]
    nivel_pre = float(pre.mean()) if len(pre) else 0.0
    print(f"nivel pre-evento:    {nivel_pre:,.0f} cj/sem "
          f"({PRE_DESDE} -> {PRE_HASTA}, n={len(pre)})")

    # Índice semana ISO -> {año: y}
    h["iso_sem"] = h["ds"].apply(lambda d: d.isocalendar()[1])
    h["anio"]    = h["ds"].dt.year

    cand = h[(h["ds"] >= DESDE) & (h["ds"] <= HASTA)].copy()
    if cand.empty:
        print("\nEl rango candidato no tiene semanas en la historia del modelo.")
        return

    anios_hist = sorted(h["anio"].unique())
    print(f"años en la historia: {anios_hist}")
    print()

    print(f"{'domingo':<12}{'ISO':>4}{'real':>9}{'base_ISO':>10}{'n':>3}"
          f"{'r_ISO':>7}{'r_pre':>7}  evento")
    print("-" * 66)

    seleccionados = []
    for _, row in cand.iterrows():
        d, y, iso, anio = row["ds"], float(row["y"]), row["iso_sem"], row["anio"]

        # misma semana ISO en OTROS años
        otros = h[(h["iso_sem"] == iso) & (h["anio"] != anio)]["y"]
        n_comp = len(otros)
        base_iso = float(otros.mean()) if n_comp else float("nan")

        r_iso = (y / base_iso) if (n_comp and base_iso > 0) else float("nan")
        r_pre = (y / nivel_pre) if nivel_pre > 0 else float("nan")

        es_evento = (
            n_comp >= MIN_ANIOS_COMP
            and base_iso > 0
            and r_iso >= UMBRAL
        )
        if es_evento:
            seleccionados.append(d)

        f_iso = f"{r_iso:>7.2f}" if r_iso == r_iso else f"{'-':>7}"
        f_pre = f"{r_pre:>7.2f}" if r_pre == r_pre else f"{'-':>7}"
        f_bas = f"{base_iso:>10,.0f}" if base_iso == base_iso else f"{'-':>10}"
        print(f"{d:%Y-%m-%d}  {iso:>4}{y:>9,.0f}{f_bas}{n_comp:>3}"
              f"{f_iso}{f_pre}  {'SI' if es_evento else ''}")

    print()
    print(f"semanas que superan el umbral: {len(seleccionados)} de {len(cand)}")

    tr = tramos_contiguos(seleccionados)
    if not tr:
        print("Ninguna semana supera el umbral. Probá un umbral más bajo.")
        return

    print()
    print(f"=== TRAMOS -> filas de mrp_eventos ({len(tr)}) ===")
    print("El usuario declara PERÍODOS en fechas naturales; estos ya son domingos,")
    print("así que semana_viz_inicio() los deja idénticos (idempotente).")
    print()
    for i, (a, b) in enumerate(tr, 1):
        n_sem = int((b - a).days / 7) + 1
        print(f"  {i}. fecha_desde={a:%Y-%m-%d}  fecha_hasta={b:%Y-%m-%d}"
              f"   ({n_sem} sem)")

    print()
    print("Semanas EXCLUIDAS dentro del rango cubierto por los tramos")
    print("(las que el 05-08 se habían identificado a mano):")
    cubiertos = set()
    for a, b in tr:
        d = a
        while d <= b:
            cubiertos.add(d)
            d += pd.Timedelta(days=7)
    huecos = [d for d in cand["ds"]
              if tr[0][0] <= d <= tr[-1][1] and d not in cubiertos]
    if huecos:
        for d in huecos:
            iso = d.isocalendar()[1]
            print(f"  {d:%Y-%m-%d}  (ISO {iso})")
    else:
        print("  ninguna — el evento resultó contiguo con este umbral.")

    print()
    print("Recordatorio: esto NO valida el forecast corregido. El criterio de")
    print("aceptación sigue siendo correr el pipeline con estos tramos y verificar")
    print("oct-nov ~844 cj/sem con septiembre en 950-1.092.")


if __name__ == "__main__":
    main()
