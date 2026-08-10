#!/usr/bin/env python3
"""
exp_evento_holdout.py — Test OUT-OF-SAMPLE de las ventanas de evento contra
VENTAS REALES. NO PERSISTE NADA.

POR QUÉ ESTE TEST EXISTE
------------------------
Los tres experimentos anteriores (`exp_ventana_evento.py`,
`exp_ventana_evento_fases.py`) leen DOS NÚMEROS AGREGADOS de un único forecast a
2026, sobre ventanas elegidas a mano, contra un target (844 cj/sem) que no
reproduce: su baseline de 2.776 no se obtiene ni con el pickle (2.410) ni
reentrenando (2.507).

Y el test de cortes dejó una confusión que no se puede resolver con ese diseño:
`asim` colapsa solo con cortes pegados a 09-29/10-06, que es a la vez (a) la
costura de las ventanas de medición y (b) un quiebre estructural real de la serie
2024 (semanas 33-39 media 913 vs semanas 40-52 media 1.852, un escalón de 2,0x).
Misma fecha, dos explicaciones. El diseño no las separa.

Este test cambia la vara: el target son VENTAS EFECTIVAS y las semanas de prueba
NO están en el entrenamiento.

DISEÑO
------
  H_eco : entrena hasta 2025-09-28  ->  predice 2025-10-01 .. 2025-11-30
          Es la ventana DONDE APARECE EL ECO. Sin corrección el modelo debería
          sobrepredecir (replica el pico de oct-nov 2024). El real fue 639.

  H_ctrl: entrena hasta 2025-06-29  ->  predice 2025-07-01 .. 2025-08-31
          CONTROL: el eco no debería estar acá. Si un candidato mejora H_eco y
          casi no mueve H_ctrl, la corrección es real y focalizada. Si mueve las
          dos por igual, solo está bajando el nivel general (y entonces el
          problema es de TENDENCIA, no de evento -> otro pendiente).

En los dos casos el evento de 2024 queda COMPLETO dentro del entrenamiento, que
es la condición para que el regresor pueda aprender su coeficiente.

CÓMO SE DECIDE
--------------
Gana el candidato con menor |sesgo| en H_eco y sesgo en H_ctrl parecido al de
`sin_evento`. Un candidato que arregla H_eco destruyendo H_ctrl está sobrecorrigiendo.

GARANTÍAS
---------
No llama a save_model / run_sku_pipeline. El cap (`_cap_forecast`) se calcula
sobre el TRAMO DE ENTRENAMIENTO, no sobre la serie completa: usar la serie
completa filtraría información del futuro al pasado.

Los candidatos se IMPORTAN de exp_ventana_evento_fases.py para que no haya dos
definiciones que puedan divergir.

USO
---
    python3 /app/tuning/exp_evento_holdout.py
    python3 /app/tuning/exp_evento_holdout.py --solo sin_evento,dos_fases_contiguo

Correr EN SERIE: `docker stats` en ~0% antes de lanzar.
"""
import argparse
import sys

import pandas as pd

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tuning")

from db import load_sales
from forecaster import (get_categoria, make_forecast, prepare_prophet_df,
                        train_model, _cap_forecast)
from seasonality import get_regressors

# Fuente única de verdad de los candidatos (importar NO ejecuta su main())
from exp_ventana_evento_fases import CANDIDATOS, domingos

HOLDOUTS = [
    # (etiqueta, fin_entrenamiento, test_desde, test_hasta)
    ("H_eco",  "2025-09-28", "2025-10-01", "2025-11-30"),
    ("H_ctrl", "2025-06-29", "2025-07-01", "2025-08-31"),
]


def wmape(real: pd.Series, pred: pd.Series) -> float:
    s = real.abs().sum()
    return 100.0 * (real - pred).abs().sum() / s if s else float("nan")


def correr(prophet_df, regressors, especs, fin_train, t_desde, t_hasta):
    """Entrena con datos <= fin_train y evalúa en [t_desde, t_hasta]."""
    df = prophet_df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    train = df[df["ds"] <= fin_train].reset_index(drop=True)
    test = df[(df["ds"] >= t_desde) & (df["ds"] <= t_hasta)].reset_index(drop=True)
    if len(train) < 20 or test.empty:
        return None

    eventos, n_sem, n_act = [], 0, 0
    ds_train = set(train["ds"].dt.strftime("%Y-%m-%d"))
    for e in especs:
        fechas = domingos(e["tramos"])
        # solo las fechas que caen dentro del entrenamiento pueden aportar
        eventos.append({"name": e["name"], "dates": fechas})
        n_sem += len(fechas)
        n_act += len(ds_train & set(fechas))
    ev = eventos or None

    model = train_model(train, regressors=regressors, extra_events=ev)
    # periodos necesarios para llegar desde el fin de train hasta t_hasta
    n_per = int((pd.Timestamp(t_hasta) - train["ds"].max()).days / 7) + 2
    fc = make_forecast(model, n_per, regressors, ev)
    fc = _cap_forecast(fc, train)          # cap sobre TRAIN, no sobre la serie completa
    fc["ds"] = pd.to_datetime(fc["ds"])

    m = test.merge(fc[["ds", "yhat"]], on="ds", how="inner")
    if m.empty:
        return None
    return {
        "n_test": len(m),
        "n_sem": n_sem,
        "n_act": n_act,
        "real": float(m["y"].mean()),
        "pred": float(m["yhat"].mean()),
        "sesgo": 100.0 * (m["yhat"].mean() / m["y"].mean() - 1.0) if m["y"].mean() else float("nan"),
        "wmape": wmape(m["y"], m["yhat"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", default="250010495")
    ap.add_argument("--solo", default="")
    args = ap.parse_args()

    pedidos = [c.strip() for c in args.solo.split(",") if c.strip()] or list(CANDIDATOS)
    malos = [c for c in pedidos if c not in CANDIDATOS]
    if malos:
        print(f"Desconocidos: {malos}\nDisponibles: {list(CANDIDATOS)}")
        return

    print(f"=== HOLDOUT OUT-OF-SAMPLE — SKU {args.sku} (cajas/semana) ===")
    print("Target = ventas reales. Las semanas de prueba NO están en el entrenamiento.")
    print("NO se persiste ningún modelo.")
    print()

    df = load_sales()
    categoria = get_categoria(df, args.sku)
    regressors = get_regressors(categoria)
    prophet_df = prepare_prophet_df(df, args.sku, canal=None, zona=None)
    print(f"categoria: {categoria} | historia: {len(prophet_df)} sem")

    for etiqueta, fin_train, t_desde, t_hasta in HOLDOUTS:
        print()
        print(f"--- {etiqueta}: entrena <= {fin_train} | prueba {t_desde} .. {t_hasta} ---")
        print(f"{'candidato':<22}{'act':>5}{'real':>8}{'pred':>8}"
              f"{'sesgo%':>9}{'wmape%':>9}")
        print("-" * 61)
        base_sesgo = None
        for nombre in pedidos:
            try:
                r = correr(prophet_df, regressors, CANDIDATOS[nombre],
                           fin_train, t_desde, t_hasta)
            except Exception as e:
                print(f"{nombre:<22}ERROR {type(e).__name__}: {e}")
                continue
            if r is None:
                print(f"{nombre:<22}sin datos suficientes")
                continue
            if r["n_sem"] and r["n_act"] == 0:
                print(f"{nombre:<22}{r['n_act']:>5}  REGRESOR INERTE en este holdout")
                continue
            if nombre == "sin_evento":
                base_sesgo = r["sesgo"]
            print(f"{nombre:<22}{r['n_act']:>5}{r['real']:>8,.0f}{r['pred']:>8,.0f}"
                  f"{r['sesgo']:>+9.1f}{r['wmape']:>9.1f}")
        if base_sesgo is not None:
            print(f"  (sesgo de referencia sin_evento: {base_sesgo:+.1f}%)")

    print()
    print("CÓMO LEER:")
    print("  · sesgo% = pred/real - 1. POSITIVO = sobrepredice (eco sin corregir).")
    print("    En H_eco se espera sesgo muy positivo para `sin_evento`.")
    print("  · Gana el candidato con |sesgo| más bajo en H_eco Y sesgo en H_ctrl")
    print("    parecido al de `sin_evento`. Si un candidato arregla H_eco pero")
    print("    empuja H_ctrl muy negativo, está sobrecorrigiendo.")
    print("  · Si NINGÚN candidato mejora H_eco frente a `sin_evento`, la hipótesis")
    print("    del eco es falsa y el problema es de tendencia, no de evento.")
    print("  · wmape% es sensible a la grumosidad semanal (pedidos a saltos):")
    print("    puede quedar alto incluso con sesgo ~0. El sesgo es lo que importa")
    print("    para planificación, porque el MRP agrega por semana y por horizonte.")


if __name__ == "__main__":
    main()
