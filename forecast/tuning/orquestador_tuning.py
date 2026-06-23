#!/usr/bin/env python3
"""
orquestador_tuning.py — Barrido autónomo de palancas de forecast (Traverso).

Corre DENTRO del container (reusa el pipeline real: db.py, forecaster.py,
seasonality.py) y mide error con cross-validation rolling-origin reentrenando
por ventana, igual que eval_forecast_error.py. Aplica el cap de produccion.

Prophet aqui es DETERMINISTA (modo MAP, sin mcmc ni seed aleatoria): confirmado
que dos corridas iguales dan resultado identico. Por eso NO hay replicas: cada
combinacion se corre una vez y el resultado es exacto.

PALANCAS (se barren de a UNA, no en producto cartesiano, para no sobreajustar):
  A) Ventana de entrenamiento: entrenar solo con las ultimas N semanas.
     Prueba la hipotesis "datos viejos estorban la tendencia".
     Valores: 52, 78, 104, full (toda la historia = comportamiento actual).
  B) changepoint_range: cuan atras permite Prophet cambios de tendencia.
     Valores: 0.8 (default Prophet), 0.9, 0.95.
  C) seasonality_prior_scale: fuerza de la estacionalidad (hoy fijo 10).
     Valores: 1, 10, 25.

Para cada combinacion reporta WMAPE sem y mes, SEPARANDO:
  - grupo SANO (<=50% en baseline)  <- donde las palancas pueden pagar
  - COLA (>50%)                      <- causa raiz distinta (quiebre/intermitencia)
  - GLOBAL                            <- contaminado por la cola, solo referencia

Baseline = configuracion actual de produccion: ventana full, changepoint_range
default de train_model, seasonality_prior_scale=10, cps=0.05.

USO (en background, te vas y volves al veredicto):
  docker cp orquestador_tuning.py traverso_forecast:/tmp/orquestador_tuning.py
  docker exec -d traverso_forecast sh -c \
    "cd /app && python3 /tmp/orquestador_tuning.py --top 100 --activos-semanas 4 \
     > /app/orq_tuning.log 2>&1"
  # seguir progreso:
  docker exec traverso_forecast tail -f /app/orq_tuning.log
"""
import sys, argparse
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from prophet import Prophet

from db import load_sales, get_sku_list
from forecaster import (prepare_prophet_df, make_forecast, _cap_forecast,
                        _apply_regressors)
from seasonality import get_category_regressors

HORIZON = 4
N_CUTOFFS = 6
MIN_TRAIN = 8
UMBRAL_SANO = 50.0

# ── Construccion de modelo parametrizable ───────────────────────────────────
# Replica train_model() pero exponiendo changepoint_range y seasonality_prior,
# que la firma original no permite variar. Mantiene el resto IGUAL a produccion.
def _build_model(prophet_df, regressors,
                 cps=0.05, changepoint_range=0.8, seasonality_prior=10.0):
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=cps,
        changepoint_range=changepoint_range,
        seasonality_prior_scale=seasonality_prior,
        interval_width=0.90,
        seasonality_mode="multiplicative",
    )
    m.add_country_holidays(country_name="CL")
    df_train = prophet_df.copy()
    if regressors:
        df_train = _apply_regressors(m, df_train, list(regressors))
    m.fit(df_train)
    return m

# ── Backtesting rolling-origin con ventana opcional ─────────────────────────
def _backtest(prophet_df, regressors, *, ventana=None,
              cps=0.05, changepoint_range=0.8, seasonality_prior=10.0):
    """Devuelve DataFrame (ds, real, pred) acumulado sobre los cutoffs.
    ventana=None -> usa toda la historia (iloc[:c], = produccion actual).
    ventana=N    -> usa solo las ultimas N semanas (iloc[c-N:c])."""
    n = len(prophet_df)
    if n < MIN_TRAIN + HORIZON:
        return None
    ultimo = n - HORIZON
    primero = max(MIN_TRAIN, ultimo - N_CUTOFFS + 1)
    origenes = list(range(primero, ultimo + 1))
    filas = []
    for c in origenes:
        ini = 0 if ventana is None else max(0, c - ventana)
        train = prophet_df.iloc[ini:c]
        test  = prophet_df.iloc[c:c + HORIZON]
        if len(train) < MIN_TRAIN or test.empty:
            continue
        try:
            m = _build_model(train, regressors, cps=cps,
                             changepoint_range=changepoint_range,
                             seasonality_prior=seasonality_prior)
            fc = make_forecast(m, periods=HORIZON, regressors=regressors)
            fc = _cap_forecast(fc, train)
            pred = fc.iloc[-HORIZON:][["ds", "yhat"]].reset_index(drop=True)
        except Exception:
            continue
        for j in range(len(test)):
            filas.append((test.iloc[j]["ds"], float(test.iloc[j]["y"]),
                          float(pred.iloc[j]["yhat"]) if j < len(pred) else np.nan))
    if not filas:
        return None
    return pd.DataFrame(filas, columns=["ds", "real", "pred"]).dropna()

def _wmape(df):
    if df is None or df.empty:
        return np.nan
    s = df["real"].abs().sum()
    return 100.0 * (df["real"] - df["pred"]).abs().sum() / s if s else np.nan

def _wmape_mes(df):
    if df is None or df.empty:
        return np.nan
    g = df.copy()
    g["mes"] = pd.to_datetime(g["ds"]).dt.to_period("M")
    agg = g.groupby("mes").agg(real=("real", "sum"), pred=("pred", "sum"))
    s = agg["real"].abs().sum()
    return 100.0 * (agg["real"] - agg["pred"]).abs().sum() / s if s else np.nan

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--activos-semanas", type=int, default=4)
    ap.add_argument("--min-semanas", type=int, default=20)
    args = ap.parse_args()

    print("=== ORQUESTADOR DE TUNING — Traverso ===", flush=True)
    print(f"top={args.top} activos={args.activos_semanas}sem  H={HORIZON} cutoffs={N_CUTOFFS}\n", flush=True)

    print("[carga] ventas desde datalake...", flush=True)
    df = load_sales()

    # Ranking + filtro de actividad: copia EXACTA de eval_forecast_error.py
    # (get_sku_list() no recibe args; el filtro usa 'ultima_venta' del ranking).
    ranking = get_sku_list()
    ranking = ranking.copy()
    ranking["_ult"] = pd.to_datetime(ranking["ultima_venta"])
    fecha_max = ranking["_ult"].max()
    corte = fecha_max - pd.Timedelta(weeks=args.activos_semanas)
    ranking = ranking[ranking["_ult"] >= corte]
    print(f"[carga] fecha max datos = {fecha_max.date()} | corte = {corte.date()}", flush=True)

    elegibles = ranking[ranking["semanas_con_venta"] >= args.min_semanas].copy()
    top = elegibles.head(args.top)
    skus = top["sku"].tolist()
    cat_por_sku = dict(zip(top["sku"], top["categoria"].fillna("(sin_cat)")))
    print(f"[universo] {len(skus)} SKUs activos con >= {args.min_semanas} sem\n", flush=True)

    # Pre-cachear prophet_df + categoria + regresores por SKU (se reusa en todo el barrido)
    series = {}
    for sku in skus:
        try:
            pdf = prepare_prophet_df(df, sku, canal=None, zona=None)
            if len(pdf) < MIN_TRAIN + HORIZON:
                continue
            cat = cat_por_sku.get(sku, "(sin_cat)")
            series[sku] = (pdf, cat, get_category_regressors(cat))
        except Exception:
            continue
    print(f"[universo] {len(series)} SKUs evaluables\n", flush=True)

    # Config de palancas. La BASE es produccion actual.
    BASE = dict(ventana=None, cps=0.05, changepoint_range=0.8, seasonality_prior=10.0)
    barridos = {
        "A_ventana":            [("full", {}), ("104", {"ventana":104}),
                                 ("78", {"ventana":78}), ("52", {"ventana":52})],
        "B_changepoint_range":  [("0.8", {}), ("0.9", {"changepoint_range":0.9}),
                                 ("0.95", {"changepoint_range":0.95})],
        "C_seasonality_prior":  [("10", {}), ("1", {"seasonality_prior":1.0}),
                                 ("25", {"seasonality_prior":25.0})],
    }

    # Baseline una sola vez (wmape sem por SKU -> define grupo sano)
    print("[baseline] corriendo configuracion de produccion...", flush=True)
    base_sem = {}
    base_df_por_sku = {}
    for i, (sku, (pdf, cat, regs)) in enumerate(series.items(), 1):
        d = _backtest(pdf, regs, **BASE)
        base_df_por_sku[sku] = d
        base_sem[sku] = _wmape(d)
        if i % 25 == 0:
            print(f"  baseline {i}/{len(series)}", flush=True)
    sanos = {s for s, w in base_sem.items() if not np.isnan(w) and w <= UMBRAL_SANO}
    cola  = {s for s, w in base_sem.items() if not np.isnan(w) and w > UMBRAL_SANO}
    vol = {s: series[s][0]["y"].sum() for s in series}
    print(f"[baseline] sano={len(sanos)} cola={len(cola)}\n", flush=True)

    def agg_pond(dfs_por_sku, conjunto, fn):
        num = den = 0.0
        for s in conjunto:
            d = dfs_por_sku.get(s)
            w = fn(d)
            if not np.isnan(w):
                num += w * vol[s]; den += vol[s]
        return num / den if den else float("nan")

    base_sano_sem = agg_pond(base_df_por_sku, sanos, _wmape)
    base_sano_mes = agg_pond(base_df_por_sku, sanos, _wmape_mes)
    base_glob_sem = agg_pond(base_df_por_sku, set(series), _wmape)

    veredicto = []
    for palanca, valores in barridos.items():
        print("=" * 70, flush=True)
        print(f"PALANCA {palanca}", flush=True)
        print("=" * 70, flush=True)
        print(f"{'valor':<10}{'sano_sem':>10}{'sano_mes':>10}{'glob_sem':>10}{'mej/emp':>10}", flush=True)
        for etiqueta, override in valores:
            cfg = {**BASE, **override}
            dfs = {}
            for sku, (pdf, cat, regs) in series.items():
                dfs[sku] = _backtest(pdf, regs, **cfg)
            ss = agg_pond(dfs, sanos, _wmape)
            sm = agg_pond(dfs, sanos, _wmape_mes)
            gs = agg_pond(dfs, set(series), _wmape)
            mej = sum(1 for s in sanos
                      if not np.isnan(_wmape(dfs[s])) and _wmape(dfs[s]) - base_sem[s] < -0.5)
            emp = sum(1 for s in sanos
                      if not np.isnan(_wmape(dfs[s])) and _wmape(dfs[s]) - base_sem[s] > 0.5)
            es_base = (cfg == BASE)
            tag = "  <- BASE" if es_base else ""
            print(f"{etiqueta:<10}{ss:>9.2f}%{sm:>9.2f}%{gs:>9.2f}%{f'{mej}/{emp}':>10}{tag}", flush=True)
            veredicto.append((palanca, etiqueta, ss, sm, gs, mej, emp, es_base))
        print(flush=True)

    # ── Veredicto ───────────────────────────────────────────────────────────
    print("=" * 70, flush=True)
    print("VEREDICTO (sobre grupo SANO, ponderado por volumen)", flush=True)
    print("=" * 70, flush=True)
    print(f"Baseline produccion: sano_sem={base_sano_sem:.2f}%  sano_mes={base_sano_mes:.2f}%  glob_sem={base_glob_sem:.2f}%\n", flush=True)
    for palanca in barridos:
        filas = [v for v in veredicto if v[0] == palanca]
        mejor = min(filas, key=lambda r: r[2])  # menor sano_sem
        base_fila = next(r for r in filas if r[7])
        delta = mejor[2] - base_fila[2]
        if mejor[7]:
            print(f"{palanca}: el mejor es la BASE. Esta palanca NO mejora el grupo sano.", flush=True)
        elif delta < -1.0 and mejor[5] > mejor[6]:
            print(f"{palanca}: GANA '{mejor[1]}' -> sano_sem {mejor[2]:.2f}% ({delta:+.2f} pts), "
                  f"mej/emp {mejor[5]}/{mejor[6]}. Señal real.", flush=True)
        else:
            print(f"{palanca}: '{mejor[1]}' baja {delta:+.2f} pts pero mej/emp {mejor[5]}/{mejor[6]} "
                  f"-> redistribuye, no mejora robusto.", flush=True)
    print("\n=== FIN ===", flush=True)

if __name__ == "__main__":
    main()
