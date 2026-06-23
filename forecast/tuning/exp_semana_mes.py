#!/usr/bin/env python3
"""
exp_semana_mes.py — Mide si un REGRESOR de 'semana del mes' mejora el forecast.

Diagnostico previo (diag_semana_del_mes.py) confirmo: las semanas tardias del mes
venden ~8% mas que las tempranas, transversal a todos los canales (sem1 floja,
sem4 pico, sem5 caida). Prophet NO modela esto explicitamente hoy.

Este experimento agrega regresores binarios de posicion-en-el-mes y compara
WMAPE del grupo sano CON vs SIN, usando el mismo pipeline real (train_model,
make_forecast, _cap_forecast) y el mecanismo de regresores existente
({"name","dates"}). Backtesting rolling-origin identico a eval_forecast_error.

Como los regresores ya existentes (de categoria) tambien se pasan, el regresor
de semana-del-mes se SUMA a los de categoria del SKU: medimos su aporte marginal.

Diseno del regresor: una dummy por posicion ordinal (sem1, sem2, sem4, sem5).
Se omite sem3 como nivel de referencia (~promedio). Prophet aprende un
coeficiente por dummy, capturando el perfil no-lineal observado.

USO (background recomendado, ~tiempo similar a 2 barridos del orquestador):
  docker cp exp_semana_mes.py traverso_forecast:/tmp/exp_semana_mes.py
  docker exec -d traverso_forecast sh -c \
    "cd /app && python3 /tmp/exp_semana_mes.py --top 100 --activos-semanas 4 \
     > /app/exp_semana_mes.log 2>&1"
  docker exec traverso_forecast sh -c "grep -v cmdstanpy /app/exp_semana_mes.log | tail -40"
"""
import sys, argparse
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from datetime import date, timedelta

from db import load_sales, get_sku_list
from forecaster import prepare_prophet_df, train_model, make_forecast, _cap_forecast
from seasonality import get_category_regressors

HORIZON = 4
N_CUTOFFS = 6
MIN_TRAIN = 8
UMBRAL_SANO = 50.0
YEARS = range(2021, 2030)

# ── Regresores de semana-del-mes: se construyen desde las fechas REALES de los
#    datos (alineadas a domingo en este pipeline), no fechas teoricas, para que
#    la dummy alinee exactamente con el 'ds' del prophet_df. Se rellena en main()
#    una vez cargados los datos. La posicion ordinal usa el dia del mes.
def _construir_reg_semana_mes(todas_las_fechas):
    """todas_las_fechas: iterable de Timestamp (las ds que aparecen en datos +
    futuro). Devuelve lista de regresores {name,dates} con dummies por posicion
    ordinal del mes (sem1,2,4,5; sem3 = referencia)."""
    import pandas as pd
    fechas = pd.to_datetime(pd.Index(sorted(set(todas_las_fechas))))
    pos = {1: [], 2: [], 4: [], 5: []}
    for d in fechas:
        p = min((d.day - 1) // 7 + 1, 5)
        if p in pos:
            pos[p].append(d.strftime("%Y-%m-%d"))
    return [{"name": f"semmes_{k}", "dates": v} for k, v in pos.items()]

# ── Backtesting rolling-origin (identico a eval_forecast_error) ─────────────
def _backtest(prophet_df, regressors):
    n = len(prophet_df)
    if n < MIN_TRAIN + HORIZON:
        return None
    ultimo = n - HORIZON
    primero = max(MIN_TRAIN, ultimo - N_CUTOFFS + 1)
    filas = []
    for c in range(primero, ultimo + 1):
        train = prophet_df.iloc[:c]
        test  = prophet_df.iloc[c:c + HORIZON]
        if len(train) < MIN_TRAIN or test.empty:
            continue
        try:
            m = train_model(train, regressors=regressors)
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
    a = g.groupby("mes").agg(real=("real", "sum"), pred=("pred", "sum"))
    s = a["real"].abs().sum()
    return 100.0 * (a["real"] - a["pred"]).abs().sum() / s if s else np.nan

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--activos-semanas", type=int, default=4)
    ap.add_argument("--min-semanas", type=int, default=20)
    args = ap.parse_args()

    print("=== EXPERIMENTO: regresor semana-del-mes ===", flush=True)
    df = load_sales()
    ranking = get_sku_list().copy()
    ranking["_ult"] = pd.to_datetime(ranking["ultima_venta"])
    fmax = ranking["_ult"].max()
    ranking = ranking[ranking["_ult"] >= fmax - pd.Timedelta(weeks=args.activos_semanas)]
    elegibles = ranking[ranking["semanas_con_venta"] >= args.min_semanas]
    top = elegibles.head(args.top)
    cat_por_sku = dict(zip(top["sku"], top["categoria"].fillna("(sin_cat)")))
    skus = top["sku"].tolist()
    print(f"[universo] {len(skus)} SKUs | fecha max {fmax.date()}\n", flush=True)

    series = {}
    for sku in skus:
        try:
            pdf = prepare_prophet_df(df, sku, canal=None, zona=None)
            if len(pdf) < MIN_TRAIN + HORIZON:
                continue
            regs_cat = list(get_category_regressors(cat_por_sku.get(sku, "")) or [])
            series[sku] = (pdf, regs_cat)
        except Exception:
            continue
    print(f"[universo] {len(series)} evaluables\n", flush=True)

    # Construir el regresor de semana-del-mes desde las fechas REALES de los datos
    # mas el horizonte futuro (para que la dummy alinee con ds en train y forecast).
    todas = set()
    for s, (pdf, _) in series.items():
        todas |= set(pdf["ds"])
        ult = pdf["ds"].max()
        for k in range(1, HORIZON + 1):
            todas.add(ult + pd.Timedelta(weeks=k))
    reg_semana_mes = _construir_reg_semana_mes(todas)
    print(f"[regresor] semana-del-mes: "
          f"{', '.join(r['name']+'='+str(len(r['dates'])) for r in reg_semana_mes)}\n", flush=True)

    vol = {s: series[s][0]["y"].sum() for s in series}

    # SIN regresor semana-mes (solo categoria) = baseline. Define grupo sano.
    print("[1/2] baseline (solo regresores de categoria)...", flush=True)
    base = {}
    for i, (s, (pdf, regs_cat)) in enumerate(series.items(), 1):
        base[s] = _backtest(pdf, regs_cat)
        if i % 25 == 0:
            print(f"  {i}/{len(series)}", flush=True)
    sano = {s for s, d in base.items() if not np.isnan(_wmape(d)) and _wmape(d) <= UMBRAL_SANO}
    print(f"[baseline] sano={len(sano)}\n", flush=True)

    # CON regresor semana-mes (categoria + semmes)
    print("[2/2] con regresor semana-del-mes...", flush=True)
    conreg = {}
    for i, (s, (pdf, regs_cat)) in enumerate(series.items(), 1):
        conreg[s] = _backtest(pdf, regs_cat + reg_semana_mes)
        if i % 25 == 0:
            print(f"  {i}/{len(series)}", flush=True)
    print(flush=True)

    def pond(dfs, conjunto, fn):
        num = den = 0.0
        for s in conjunto:
            w = fn(dfs[s])
            if not np.isnan(w):
                num += w * vol[s]; den += vol[s]
        return num / den if den else float("nan")

    bs, bm = pond(base, sano, _wmape), pond(base, sano, _wmape_mes)
    cs, cm = pond(conreg, sano, _wmape), pond(conreg, sano, _wmape_mes)
    mej = sum(1 for s in sano if not np.isnan(_wmape(conreg[s]))
              and _wmape(conreg[s]) - _wmape(base[s]) < -0.5)
    emp = sum(1 for s in sano if not np.isnan(_wmape(conreg[s]))
              and _wmape(conreg[s]) - _wmape(base[s]) > 0.5)

    print("=" * 60, flush=True)
    print("RESULTADO — grupo SANO, ponderado por volumen", flush=True)
    print("=" * 60, flush=True)
    print(f"{'config':<28}{'WMAPE sem':>12}{'WMAPE mes':>12}", flush=True)
    print(f"{'sin semmes (base)':<28}{bs:>11.2f}%{bm:>11.2f}%", flush=True)
    print(f"{'con semmes':<28}{cs:>11.2f}%{cm:>11.2f}%", flush=True)
    print(f"\ndelta sem: {cs-bs:+.2f} pts   delta mes: {cm-bm:+.2f} pts", flush=True)
    print(f"SKUs mejoran/empeoran (sem): {mej}/{emp}", flush=True)
    print(flush=True)
    if cs - bs < -1.0 and mej > emp:
        print("VEREDICTO: el regresor semana-del-mes MEJORA el grupo sano. Señal real.", flush=True)
    elif cs - bs < -0.3 and mej > emp:
        print("VEREDICTO: mejora leve y consistente. Marginal, evaluar costo/beneficio.", flush=True)
    else:
        print("VEREDICTO: NO mejora robusto (ya capturado por estacionalidad anual, o redistribuye).", flush=True)
    print("=== FIN ===", flush=True)

if __name__ == "__main__":
    main()
