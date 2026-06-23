#!/usr/bin/env python3
"""
exp_realineacion_regresores.py — Mide el impacto de ACTIVAR los regresores de
categoria, que hoy estan INERTES por desfase de dia de semana. SOLO LECTURA del
codigo de produccion: realinea las fechas en memoria, NO modifica seasonality.py.

HALLAZGO QUE MOTIVA ESTO:
  seasonality.py genera las fechas de regresores en LUNES (d - d.weekday()).
  El pipeline (prepare_prophet_df) usa DOMINGOS como inicio de semana (ds weekday=6).
  _apply_regressors pone la dummy en 1 solo si ds esta EXACTO en la lista de fechas.
  => interseccion 0 => las dummies son columnas de ceros => Prophet las ignora.
  Verificado: VINAGRES 'verano_vinagre' tiene 0 fechas coincidentes con el ds real.
  Esto afecta a TODAS las categorias (vinagres, salsas, sopas, limon, etc.).

QUE MIDE:
  Para el grupo sano, compara WMAPE:
    - INERTE  : regresores tal como estan hoy (lunes, dummy=0). = produccion actual.
    - ACTIVADO: mismas fechas corridas 1 dia atras (lunes->domingo), dummy se activa.
  El fix real en seasonality.py seria generar domingos; aqui lo simulamos restando
  1 dia a cada fecha, que es exactamente la conversion lunes->domingo de esa semana.

USO (background recomendado):
  docker cp exp_realineacion_regresores.py traverso_forecast:/tmp/exp_realin.py
  docker exec -d traverso_forecast sh -c \
    "cd /app && python3 /tmp/exp_realin.py --top 100 --activos-semanas 4 \
     > /app/exp_realin.log 2>&1"
  docker exec traverso_forecast sh -c "grep -v cmdstanpy /app/exp_realin.log | tail -40"
"""
import sys, argparse
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from datetime import timedelta

from db import load_sales, get_sku_list
from forecaster import prepare_prophet_df, train_model, make_forecast, _cap_forecast
from seasonality import get_category_regressors

HORIZON = 4
N_CUTOFFS = 6
MIN_TRAIN = 8
UMBRAL_SANO = 50.0

def realinear(regs):
    """Devuelve copia de los regresores con cada fecha corrida 1 dia atras
    (lunes -> domingo de la misma semana), para alinear con el ds del pipeline."""
    out = []
    for r in regs:
        fechas_dom = [(pd.Timestamp(f) - timedelta(days=1)).strftime("%Y-%m-%d")
                      for f in r["dates"]]
        out.append({**r, "dates": fechas_dom})
    return out

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

def _wmape(d):
    if d is None or d.empty: return np.nan
    s = d["real"].abs().sum()
    return 100.0 * (d["real"] - d["pred"]).abs().sum() / s if s else np.nan

def _wmape_mes(d):
    if d is None or d.empty: return np.nan
    g = d.copy(); g["mes"] = pd.to_datetime(g["ds"]).dt.to_period("M")
    a = g.groupby("mes").agg(real=("real","sum"), pred=("pred","sum"))
    s = a["real"].abs().sum()
    return 100.0 * (a["real"] - a["pred"]).abs().sum() / s if s else np.nan

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--activos-semanas", type=int, default=4)
    ap.add_argument("--min-semanas", type=int, default=20)
    args = ap.parse_args()

    print("=== EXPERIMENTO: realineacion de regresores (lunes->domingo) ===\n", flush=True)
    df = load_sales()
    ranking = get_sku_list().copy()
    ranking["_ult"] = pd.to_datetime(ranking["ultima_venta"])
    fmax = ranking["_ult"].max()
    ranking = ranking[ranking["_ult"] >= fmax - pd.Timedelta(weeks=args.activos_semanas)]
    top = ranking[ranking["semanas_con_venta"] >= args.min_semanas].head(args.top)
    cat_por_sku = dict(zip(top["sku"], top["categoria"].fillna("(sin_cat)")))
    skus = top["sku"].tolist()
    print(f"[universo] {len(skus)} SKUs | fecha max {fmax.date()}\n", flush=True)

    # Cachear serie + regresores (inertes y realineados) por SKU
    series = {}
    con_reg = 0
    for sku in skus:
        try:
            pdf = prepare_prophet_df(df, sku, canal=None, zona=None)
            if len(pdf) < MIN_TRAIN + HORIZON:
                continue
            regs = get_category_regressors(cat_por_sku.get(sku, ""))
            if regs:
                con_reg += 1
            series[sku] = (pdf, regs, realinear(regs))
        except Exception:
            continue
    print(f"[universo] {len(series)} evaluables | {con_reg} con regresores de categoria\n", flush=True)

    vol = {s: series[s][0]["y"].sum() for s in series}

    print("[1/2] INERTE (regresores actuales, lunes)...", flush=True)
    inerte = {}
    for i, (s, (pdf, regs, _)) in enumerate(series.items(), 1):
        inerte[s] = _backtest(pdf, regs)
        if i % 25 == 0: print(f"  {i}/{len(series)}", flush=True)
    sano = {s for s, d in inerte.items() if not np.isnan(_wmape(d)) and _wmape(d) <= UMBRAL_SANO}
    print(f"[baseline] sano={len(sano)}\n", flush=True)

    print("[2/2] ACTIVADO (regresores realineados, domingo)...", flush=True)
    activ = {}
    for i, (s, (pdf, _, regs_d)) in enumerate(series.items(), 1):
        activ[s] = _backtest(pdf, regs_d)
        if i % 25 == 0: print(f"  {i}/{len(series)}", flush=True)
    print(flush=True)

    def pond(dfs, conj, fn):
        num = den = 0.0
        for s in conj:
            w = fn(dfs[s])
            if not np.isnan(w):
                num += w * vol[s]; den += vol[s]
        return num / den if den else float("nan")

    # SKUs CON regresores dentro del sano (donde el fix puede tener efecto)
    sano_con_reg = {s for s in sano if series[s][1]}
    print("=" * 60, flush=True)
    print("RESULTADO — grupo SANO, ponderado por volumen", flush=True)
    print("=" * 60, flush=True)
    print(f"{'config':<24}{'WMAPE sem':>12}{'WMAPE mes':>12}", flush=True)
    print(f"{'INERTE (actual)':<24}{pond(inerte,sano,_wmape):>11.2f}%{pond(inerte,sano,_wmape_mes):>11.2f}%", flush=True)
    print(f"{'ACTIVADO (fix)':<24}{pond(activ,sano,_wmape):>11.2f}%{pond(activ,sano,_wmape_mes):>11.2f}%", flush=True)
    d_sem = pond(activ,sano,_wmape) - pond(inerte,sano,_wmape)
    d_mes = pond(activ,sano,_wmape_mes) - pond(inerte,sano,_wmape_mes)
    print(f"\ndelta sem: {d_sem:+.2f} pts   delta mes: {d_mes:+.2f} pts", flush=True)

    mej = sum(1 for s in sano if not np.isnan(_wmape(activ[s])) and _wmape(activ[s]) - _wmape(inerte[s]) < -0.5)
    emp = sum(1 for s in sano if not np.isnan(_wmape(activ[s])) and _wmape(activ[s]) - _wmape(inerte[s]) > 0.5)
    print(f"SKUs mejoran/empeoran (sem): {mej}/{emp}", flush=True)

    # Foco: solo SKUs CON regresores (el fix no puede afectar a los sin regresores)
    print(f"\n--- Solo SKUs con regresores de categoria ({len(sano_con_reg)} en sano) ---", flush=True)
    if sano_con_reg:
        print(f"INERTE  : {pond(inerte,sano_con_reg,_wmape):.2f}% sem", flush=True)
        print(f"ACTIVADO: {pond(activ,sano_con_reg,_wmape):.2f}% sem", flush=True)
        mejc = sum(1 for s in sano_con_reg if _wmape(activ[s]) - _wmape(inerte[s]) < -0.5)
        empc = sum(1 for s in sano_con_reg if _wmape(activ[s]) - _wmape(inerte[s]) > 0.5)
        print(f"mejoran/empeoran: {mejc}/{empc}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("Lectura: si ACTIVADO mejora (sobre todo en SKUs con regresores) -> el", flush=True)
    print("fix de alineacion en seasonality.py vale. Si no cambia -> la estacional.", flush=True)
    print("anual de Prophet ya capturaba esos patrones; los regresores son redundantes.", flush=True)
    print("=== FIN ===", flush=True)

if __name__ == "__main__":
    main()
