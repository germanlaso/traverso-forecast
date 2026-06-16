"""
eval_forecast_error.py — Medición de error de forecast (línea base)
Traverso S.A. · Diagnóstico de Prophet

Mide el error del forecast de producción sobre los TOP-N SKUs por volumen,
usando cross-validation rolling-origin (reentrenamiento por ventana) — la
única medición honesta del error fuera de muestra.

Reporta:
  - WMAPE semanal (horizonte 1-4 sem) — la métrica que estresa la línea.
  - WMAPE mensual (mes calendario)    — la métrica que estresa el inventario.
  - MAPE / MAE secundarias, sobre el MISMO set de puntos.
  - Agregado de portafolio (WMAPE global ponderado por volumen).

NO modifica nada operacional: solo LEE dbo.ventas y reusa el pipeline real
(db.py, forecaster.py, seasonality.py). Salida: CSV + consola.

Diseñado para correr DENTRO del container traverso_forecast (tiene el entorno
y las env vars del datalake):
    docker cp eval_forecast_error.py traverso_forecast:/app/
    docker exec traverso_forecast python3 /app/eval_forecast_error.py --top 30

Flags:
    --top N            Cuántos SKUs medir (default 30).
    --min-semanas N    Mínimo de semanas con venta para evaluar (default 20).
    --cutoffs N        Nº de orígenes de CV rolling (default 6).
    --canal NOMBRE     Canal específico (default: consolidado, todos los canales).
    --timeout-seg N    Timeout de la lectura del datalake en seg (default 120).
    --out RUTA         CSV de salida (default /app/eval_forecast_error.csv).
"""

import argparse
import sys
import warnings
from datetime import timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Pipeline real del sistema
import db
from db import get_sku_list, load_sales
from forecaster import (
    prepare_prophet_df, train_model, make_forecast, _cap_forecast,
    get_categoria, make_key, FREQ, FORECAST_CAP_FACTOR,
)
from seasonality import get_category_regressors


# ── Robustez datalake: timeout en la conexión (patrón backlog #4) ──────────────

def _patch_engine_timeout(timeout_seg: int):
    """Envuelve db.get_engine para inyectar timeout de query/login en la conexión.

    Si el datalake se degrada (como el 15/06), la lectura falla limpio con error
    en vez de colgar el proceso indefinidamente. NO altera db.py en disco; solo
    parchea la referencia en memoria para ESTA corrida.
    """
    from sqlalchemy import create_engine
    from urllib.parse import quote_plus
    orig_conn_str = db.get_connection_string

    def get_engine_con_timeout():
        # 'timeout' = login timeout; el query timeout va por connect_args del driver.
        quoted = quote_plus(orig_conn_str())
        return create_engine(
            f"mssql+pyodbc:///?odbc_connect={quoted}",
            fast_executemany=True,
            connect_args={"timeout": timeout_seg},
        )

    db.get_engine = get_engine_con_timeout


# ── Métricas ───────────────────────────────────────────────────────────────────

def _wmape(real: np.ndarray, pred: np.ndarray) -> float:
    """WMAPE = sum(|real-pred|) / sum(real). Ponderado por volumen, robusto a ceros.
    Devuelve % o None si no hay volumen real."""
    denom = np.sum(np.abs(real))
    if denom <= 0:
        return None
    return round(float(np.sum(np.abs(real - pred)) / denom) * 100, 2)


def _mape(real: np.ndarray, pred: np.ndarray) -> float:
    """MAPE clásico, solo sobre puntos con real>0 (evita div/0)."""
    mask = real > 0
    if mask.sum() == 0:
        return None
    return round(float(np.mean(np.abs((real[mask] - pred[mask]) / real[mask]))) * 100, 2)


def _mae(real: np.ndarray, pred: np.ndarray) -> float:
    if len(real) == 0:
        return None
    return round(float(np.mean(np.abs(real - pred))), 1)


# ── Cross-validation rolling-origin manual ─────────────────────────────────────
# No uso prophet.diagnostics.cross_validation directamente porque necesito:
#   (a) reusar train_model/make_forecast con los regresores de categoría,
#   (b) aplicar el cap igual que producción,
#   (c) controlar los cutoffs y separar error semanal vs mensual.

def _cv_consolidado_bottomup(df_sku: pd.DataFrame,
                             sku: str,
                             regressors: list,
                             n_cutoffs: int,
                             min_sem_canal: int,
                             horizon_semanas: int = 4) -> dict | None:
    """Bottom-up: entrena un modelo por canal con historia suficiente, suma los
    yhat por semana, y mide el error del TOTAL consolidado del SKU.

    Canales con < min_sem_canal semanas se agrupan en un bucket 'otros' y se
    modelan juntos (un solo Prophet), en vez de entrenar modelos malos por canal
    flaco que contaminarían la suma. Si ni el bucket llega al mínimo, se suma
    crudo al consolidado sin modelar aparte (se absorbe en el total).
    """
    canales = df_sku["canal"].dropna().unique().tolist()
    # Clasificar canales por historia disponible (semanas con venta).
    fuertes, flacos = [], []
    for c in canales:
        n_sem = df_sku[df_sku["canal"] == c]["fecha_semana"].nunique()
        (fuertes if n_sem >= min_sem_canal else flacos).append(c)

    # Construir las subseries a modelar: cada canal fuerte + bucket 'otros'.
    subseries = []  # lista de (etiqueta, prophet_df)
    for c in fuertes:
        try:
            pdf_c = prepare_prophet_df(df_sku, sku, canal=c, zona=None)
            subseries.append((c, pdf_c))
        except ValueError:
            continue
    if flacos:
        df_otros = df_sku[df_sku["canal"].isin(flacos)]
        # Reusar prepare_prophet_df agregando el bucket: lo armo a mano porque
        # prepare_prophet_df filtra por un único canal.
        seg = (df_otros.set_index("fecha_semana")["cantidad"]
                       .resample(FREQ).sum().reset_index()
                       .rename(columns={"fecha_semana": "ds", "cantidad": "y"}))
        seg["y"] = seg["y"].clip(lower=0)
        if len(seg) >= 8:
            subseries.append(("__otros__", seg))

    if not subseries:
        return None

    # Para cada cutoff, predecir cada subserie y SUMAR los yhat → consolidado.
    # Alineamos por las fechas de test del consolidado real.
    pdf_total = prepare_prophet_df(df_sku, sku, canal=None, zona=None)
    n = len(pdf_total)
    min_train = 8
    if n < min_train + horizon_semanas:
        return None
    ultimo_origen = n - horizon_semanas
    primer_origen = max(min_train, ultimo_origen - n_cutoffs + 1)
    origenes = list(range(primer_origen, ultimo_origen + 1))

    filas = []  # (ds, real_total, pred_total)
    fechas_total = pdf_total["ds"].values
    for c_idx in origenes:
        fecha_corte = fechas_total[c_idx - 1]  # última fecha de train
        test_fechas = pdf_total.iloc[c_idx:c_idx + horizon_semanas]["ds"]
        # Real consolidado en esas fechas
        real_map = dict(zip(pdf_total["ds"], pdf_total["y"]))
        # Predicción consolidada = suma de predicciones por subserie
        pred_acumulado = {f: 0.0 for f in test_fechas}
        for etiqueta, pdf_sub in subseries:
            train_sub = pdf_sub[pdf_sub["ds"] <= fecha_corte]
            if len(train_sub) < min_train:
                continue
            try:
                model = train_model(train_sub, regressors=regressors)
                fc = make_forecast(model, periods=horizon_semanas, regressors=regressors)
                fc = _cap_forecast(fc, train_sub)
                fc_map = dict(zip(fc["ds"], fc["yhat"]))
                for f in test_fechas:
                    pred_acumulado[f] += float(fc_map.get(f, 0.0))
            except Exception:
                continue
        for f in test_fechas:
            filas.append((f, float(real_map.get(f, 0.0)), pred_acumulado[f]))

    if not filas:
        return None
    res = pd.DataFrame(filas, columns=["ds", "real", "pred"]).dropna()
    if res.empty:
        return None

    real_w, pred_w = res["real"].values, res["pred"].values
    res_m = (res.assign(mes=res["ds"].dt.to_period("M"))
                .groupby("mes")[["real", "pred"]].sum())
    real_m, pred_m = res_m["real"].values, res_m["pred"].values

    return {
        "n_puntos_sem":   len(res),
        "n_meses":        len(res_m),
        "n_canales_mod":  len(subseries),
        "n_canales_flacos": len(flacos),
        "wmape_sem":      _wmape(real_w, pred_w),
        "wmape_mes":      _wmape(real_m, pred_m),
        "mape_sem":       _mape(real_w, pred_w),
        "mae_sem":        _mae(real_w, pred_w),
        "_sum_abs_err_sem": float(np.sum(np.abs(real_w - pred_w))),
        "_sum_real_sem":    float(np.sum(np.abs(real_w))),
        "_sum_abs_err_mes": float(np.sum(np.abs(real_m - pred_m))),
        "_sum_real_mes":    float(np.sum(np.abs(real_m))),
    }


def _cv_un_sku(prophet_df: pd.DataFrame,
               regressors: list,
               n_cutoffs: int,
               horizon_semanas: int = 4) -> dict | None:
    """Rolling-origin: para cada cutoff, entrena con lo anterior y predice
    `horizon_semanas` hacia adelante. Acumula pares (real, pred) semanales.
    Devuelve arrays semanales + un DataFrame fecha/real/pred para agregación mensual.
    """
    n = len(prophet_df)
    # Necesitamos al menos 8 sem de train inicial + horizonte.
    min_train = 8
    if n < min_train + horizon_semanas:
        return None

    # Cutoffs espaciados: los últimos n_cutoffs orígenes posibles.
    ultimo_origen = n - horizon_semanas
    primer_origen = max(min_train, ultimo_origen - n_cutoffs + 1)
    origenes = list(range(primer_origen, ultimo_origen + 1))
    if not origenes:
        return None

    filas = []  # (ds, real, pred)
    for c in origenes:
        train = prophet_df.iloc[:c]
        test  = prophet_df.iloc[c:c + horizon_semanas]
        if len(train) < min_train or test.empty:
            continue
        try:
            model = train_model(train, regressors=regressors)
            fc = make_forecast(model, periods=horizon_semanas, regressors=regressors)
            fc = _cap_forecast(fc, train)  # cap como en producción
            pred = fc.iloc[-horizon_semanas:][["ds", "yhat"]].reset_index(drop=True)
        except Exception:
            continue
        for j in range(len(test)):
            filas.append((
                test.iloc[j]["ds"],
                float(test.iloc[j]["y"]),
                float(pred.iloc[j]["yhat"]) if j < len(pred) else np.nan,
            ))

    if not filas:
        return None

    res = pd.DataFrame(filas, columns=["ds", "real", "pred"]).dropna()
    if res.empty:
        return None

    # --- Error semanal ---
    real_w = res["real"].values
    pred_w = res["pred"].values

    # --- Error mensual (mes calendario) ---
    res_m = (res.assign(mes=res["ds"].dt.to_period("M"))
                .groupby("mes")[["real", "pred"]].sum())
    real_m = res_m["real"].values
    pred_m = res_m["pred"].values

    return {
        "n_puntos_sem":   len(res),
        "n_meses":        len(res_m),
        "wmape_sem":      _wmape(real_w, pred_w),
        "wmape_mes":      _wmape(real_m, pred_m),
        "mape_sem":       _mape(real_w, pred_w),
        "mae_sem":        _mae(real_w, pred_w),
        # Para el agregado de portafolio: guardo sumas crudas.
        "_sum_abs_err_sem": float(np.sum(np.abs(real_w - pred_w))),
        "_sum_real_sem":    float(np.sum(np.abs(real_w))),
        "_sum_abs_err_mes": float(np.sum(np.abs(real_m - pred_m))),
        "_sum_real_mes":    float(np.sum(np.abs(real_m))),
    }


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--activos-semanas", type=int, default=None,
                    help="Si se indica, filtra a SKUs con venta en las últimas N semanas "
                         "(contadas desde la fecha máxima de datos) antes de tomar el top por volumen.")
    ap.add_argument("--min-semanas", type=int, default=20)
    ap.add_argument("--cutoffs", type=int, default=6)
    ap.add_argument("--canal", type=str, default=None)
    ap.add_argument("--por-canal", action="store_true",
                    help="Modo bottom-up: modela por canal y consolida (vs top-down).")
    ap.add_argument("--min-semanas-canal", type=int, default=20,
                    help="Mín. semanas por canal para modelarlo solo; bajo eso van a bucket 'otros'.")
    ap.add_argument("--timeout-seg", type=int, default=120)
    ap.add_argument("--out", type=str, default=None,
                    help="CSV de salida (default: nombre según modo).")
    args = ap.parse_args()
    if args.out is None:
        suf = f"top{args.top}"
        if args.activos_semanas is not None:
            suf += f"_act{args.activos_semanas}s"
        modo_tag = "bottomup" if args.por_canal else "topdown"
        args.out = f"/app/eval_error_{modo_tag}_{suf}.csv"

    print(f"[1/4] Configurando timeout de datalake = {args.timeout_seg}s")
    _patch_engine_timeout(args.timeout_seg)

    print(f"[2/4] Ranking de volumen (get_sku_list)...")
    ranking = get_sku_list()

    # Filtro de actividad reciente (opcional): SKUs con venta en las últimas N
    # semanas, contadas desde la fecha MÁXIMA de datos (robusto a fallos de carga).
    if args.activos_semanas is not None:
        ranking = ranking.copy()
        ranking["_ult"] = pd.to_datetime(ranking["ultima_venta"])
        fecha_max = ranking["_ult"].max()
        corte = fecha_max - pd.Timedelta(weeks=args.activos_semanas)
        antes = len(ranking)
        ranking = ranking[ranking["_ult"] >= corte]
        print(f"      actividad: fecha máx datos = {fecha_max.date()} | "
              f"corte = {corte.date()} | {len(ranking)}/{antes} SKUs activos "
              f"(últimas {args.activos_semanas} sem)")

    # Filtrar por historia suficiente y tomar top-N por volumen.
    elegibles = ranking[ranking["semanas_con_venta"] >= args.min_semanas].copy()
    no_evaluables = ranking[ranking["semanas_con_venta"] < args.min_semanas]
    top = elegibles.head(args.top)
    skus = top["sku"].tolist()
    print(f"      {len(ranking)} SKUs totales | {len(elegibles)} con >= {args.min_semanas} sem"
          f" | evaluando top {len(skus)}")
    if len(top) < args.top:
        print(f"      (solo {len(top)} cumplen el mínimo de historia)")

    print(f"[3/4] Cargando ventas de {len(skus)} SKUs desde datalake...")
    df = load_sales(skus=skus)
    if args.canal:
        df = df[df["canal"] == args.canal]
        print(f"      filtrado a canal='{args.canal}': {len(df)} filas")

    modo = "bottom-up (por canal, consolidado)" if args.por_canal else "top-down (consolidado)"
    print(f"[4/4] Cross-validation rolling-origin · modo: {modo} · {args.cutoffs} cutoffs, reentrenando...")
    filas_out = []
    acc = {"se_sem": 0.0, "r_sem": 0.0, "se_mes": 0.0, "r_mes": 0.0}
    for idx, sku in enumerate(skus, 1):
        meta = top[top["sku"] == sku].iloc[0]
        categoria = get_categoria(df, sku)
        regressors = get_category_regressors(categoria)
        df_sku = df[df["sku"] == sku]
        if df_sku.empty:
            print(f"  [{idx}/{len(skus)}] {sku}: sin datos tras filtro — skip")
            continue

        if args.por_canal:
            r = _cv_consolidado_bottomup(
                df_sku, sku, regressors,
                n_cutoffs=args.cutoffs,
                min_sem_canal=args.min_semanas_canal,
            )
        else:
            try:
                pdf = prepare_prophet_df(df, sku, canal=args.canal, zona=None)
            except ValueError:
                print(f"  [{idx}/{len(skus)}] {sku}: sin datos — skip")
                continue
            r = _cv_un_sku(pdf, regressors, n_cutoffs=args.cutoffs)

        if r is None:
            print(f"  [{idx}/{len(skus)}] {sku}: historia insuficiente para CV — skip")
            continue
        fila = {
            "sku":          sku,
            "descripcion":  str(meta["descripcion"])[:45],
            "categoria":    categoria,
            "volumen_total": int(meta["volumen_total"]),
            "semanas":      int(meta["semanas_con_venta"]),
            "wmape_sem_%":  r["wmape_sem"],
            "wmape_mes_%":  r["wmape_mes"],
            "mape_sem_%":   r["mape_sem"],
            "mae_sem":      r["mae_sem"],
            "n_pts_sem":    r["n_puntos_sem"],
            "n_meses":      r["n_meses"],
        }
        if args.por_canal:
            fila["n_canales_mod"]   = r.get("n_canales_mod")
            fila["n_canales_flacos"] = r.get("n_canales_flacos")
        filas_out.append(fila)
        acc["se_sem"] += r["_sum_abs_err_sem"]; acc["r_sem"] += r["_sum_real_sem"]
        acc["se_mes"] += r["_sum_abs_err_mes"]; acc["r_mes"] += r["_sum_real_mes"]
        print(f"  [{idx}/{len(skus)}] {sku}: WMAPE sem={r['wmape_sem']}%  mes={r['wmape_mes']}%")

    if not filas_out:
        print("\nNo se pudo evaluar ningún SKU. Revisar historia / filtros.")
        sys.exit(1)

    out = pd.DataFrame(filas_out).sort_values("volumen_total", ascending=False)
    out.to_csv(args.out, index=False)

    # Agregado de portafolio (WMAPE global ponderado por volumen).
    port_sem = round(acc["se_sem"] / acc["r_sem"] * 100, 2) if acc["r_sem"] > 0 else None
    port_mes = round(acc["se_mes"] / acc["r_mes"] * 100, 2) if acc["r_mes"] > 0 else None

    print("\n" + "=" * 64)
    print("RESUMEN DE PORTAFOLIO (top SKUs por volumen)")
    print("=" * 64)
    print(f"  SKUs evaluados:        {len(out)}")
    print(f"  WMAPE semanal global:  {port_sem}%")
    print(f"  WMAPE mensual global:  {port_mes}%")
    print(f"  (mensual < semanal es lo esperado: los errores semanales se compensan al agregar)")
    print(f"\n  Mediana WMAPE sem:     {out['wmape_sem_%'].median()}%")
    print(f"  Peores 5 (WMAPE sem):")
    for _, row in out.nlargest(5, "wmape_sem_%").iterrows():
        print(f"    {row['sku']:>12}  {row['wmape_sem_%']:>6}%  {row['descripcion']}")
    print(f"\n  CSV: {args.out}")
    if len(no_evaluables) > 0:
        print(f"  Nota: {len(no_evaluables)} SKUs del catálogo no evaluables (< {args.min_semanas} sem de historia).")


if __name__ == "__main__":
    main()
