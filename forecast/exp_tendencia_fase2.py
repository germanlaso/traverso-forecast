#!/usr/bin/env python3
"""
exp_tendencia_fase2.py — Calidad: WMAPE por horizonte (M2) y no-regresion (M3).

Fase 2 de DISENO_fix_tendencia_forecast.md §5.3, sobre las variantes que
sobrevivieron el screening de Fase 1.

QUE RESPONDE
------------
Fase 1 mostro que V1_flat elimina el colapso (96% cubre, 8% trend<0 contra 72%
y 32% del baseline). Lo que NO puede responder es a que costo: growth="flat"
renuncia a capturar tendencias reales. Si un SKU crece o decrece de verdad,
flat lo ignora.

  M2 · WMAPE por horizonte h=1..H, sin promediar. Donde gana y donde pierde.
       Fase 1 no lo veia porque eval_forecast_error usa h=4 por default y el
       colapso ocurre en h=8..22.
  M3 · GUARDARRAIL: WMAPE de los SKU que HOY estan sanos. Es facil "arreglar"
       3 SKU degradando 200. Si M3 empeora mas del umbral, la variante se
       descarta por buena que sea en M1.

Micro (portafolio, sum|err|/sum|real|) y macro (promedio de WMAPE por SKU) se
reportan por separado: micro lo dominan los SKU grandes, macro trata a todos
igual. Un fix puede mejorar uno y empeorar el otro.

COMPARABILIDAD
--------------
Solo se comparan SKU con resultado en TODAS las variantes y sobre los MISMOS
cutoffs. Un SKU que falla en una variante se excluye de todas: si no, la
comparacion mide poblaciones distintas.

Con H=12, los SKU con n_obs < 8+12=20 quedan fuera del CV (251010100, n_obs=11).
Su validacion es solo por M1/M4 de Fase 1 — no hay ground truth suficiente.

NO ESCRIBE NADA: no toca /app/models.

Uso:
    python3 /app/exp_tendencia_fase2.py --cache-ventas /tmp/ventas_exp.pkl \\
        --fase1-csv /tmp/exp_fase1.csv --csv /tmp/exp_fase2.csv
"""

import argparse
import datetime as dt
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
for _noisy in ("prophet", "cmdstanpy", "matplotlib"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("exp2")

MIN_TRAIN = 8   # mismo minimo que eval_forecast_error._cv_un_sku


def cv_por_horizonte(prophet_df, regressors, overrides, n_cutoffs, H):
    """Rolling-origin guardando el PASO de horizonte de cada punto.

    Diferencia con eval_forecast_error._cv_un_sku: ahi las filas son
    (ds, real, pred) y se pierde el h, asi que no se puede ver donde se degrada.
    Aca cada fila lleva h = 1..H.

    Devuelve DataFrame(h, real, pred) o None si el SKU no es evaluable.
    """
    from forecaster import train_model, make_forecast, _cap_forecast

    n = len(prophet_df)
    if n < MIN_TRAIN + H:
        return None
    ultimo = n - H
    primero = max(MIN_TRAIN, ultimo - n_cutoffs + 1)
    origenes = list(range(primero, ultimo + 1))
    if not origenes:
        return None

    filas = []
    for c in origenes:
        train = prophet_df.iloc[:c]
        test = prophet_df.iloc[c:c + H]
        if len(train) < MIN_TRAIN or test.empty:
            continue
        try:
            m = train_model(train, regressors=regressors, overrides=overrides)
            fc = make_forecast(m, H, regressors)
            fc = _cap_forecast(fc, train)          # cap como en produccion
            pred = fc.iloc[-H:][["ds", "yhat"]].reset_index(drop=True)
        except Exception:
            continue
        for j in range(len(test)):
            if j >= len(pred):
                break
            filas.append((j + 1,
                          float(test.iloc[j]["y"]),
                          float(pred.iloc[j]["yhat"])))
    if not filas:
        return None
    return pd.DataFrame(filas, columns=["h", "real", "pred"]).dropna()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizonte", type=int, default=8, help="horizonte del PLAN (semanas)")
    ap.add_argument("--H", type=int, default=12, help="horizonte de EVALUACION (semanas)")
    ap.add_argument("--n-cutoffs", type=int, default=6)
    ap.add_argument("--variantes", type=str, default="V0_baseline,V1_flat,V3_cps001",
                    help="las que sobrevivieron Fase 1")
    ap.add_argument("--n-por-cohorte", type=int, default=4)
    ap.add_argument("--skus", type=str, default=None)
    ap.add_argument("--cache-ventas", type=str, default=None)
    ap.add_argument("--fase1-csv", type=str, default=None,
                    help="CSV de Fase 1: clasifica sano/roto para M3 sin recomputar")
    ap.add_argument("--umbral-m3", type=float, default=2.0,
                    help="%% relativo de degradacion aceptable en los sanos")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", type=str, default=None)
    args = ap.parse_args()

    t0 = time.time()
    from eval_forecast_error import _wmape          # misma metrica que produccion
    from forecaster import prepare_prophet_df, get_categoria
    from seasonality import get_regressors
    from exp_tendencia_fase1 import cohorte, variantes_para, TESTIGOS
    import mrp as _mrp

    # ── ventas ───────────────────────────────────────────────────────────────
    if args.cache_ventas and os.path.exists(args.cache_ventas):
        df_sales = pd.read_pickle(args.cache_ventas)
        log.info(f"ventas desde cache: {len(df_sales)} filas")
    else:
        from main import get_sales_df
        log.info("cargando ventas del datalake...")
        df_sales = get_sales_df()
        if args.cache_ventas:
            try:
                df_sales.to_pickle(args.cache_ventas)
            except Exception as e:
                log.warning(f"cache no guardado: {e}")
    log.info(f"ventas: {len(df_sales)} filas")

    sku_params, _l, _sl = _mrp.load_params_from_db()

    # ── perfilar y muestrear IGUAL que Fase 1 (mismo seed -> misma muestra) ──
    universo = [s for s in sku_params if not getattr(sku_params[s], "mto", False)]
    perfil = {}
    for s in universo:
        try:
            pdf = prepare_prophet_df(df_sales, s)
        except Exception:
            continue
        if len(pdf) < 8:
            continue
        ult = pdf.tail(52)["y"]
        pct = float((ult > 0).sum()) / max(1, len(ult))
        perfil[s] = (len(pdf), pct, cohorte(len(pdf), pct))

    if args.skus:
        muestra = [s.strip() for s in args.skus.split(",") if s.strip() in perfil]
    else:
        import random
        rnd = random.Random(args.seed)
        porco = {}
        for s, (_n, _p, co) in perfil.items():
            porco.setdefault(co, []).append(s)
        muestra = [s for s in TESTIGOS if s in perfil]
        for co in sorted(porco):
            cands = sorted(x for x in porco[co] if x not in muestra)
            muestra += rnd.sample(cands, min(args.n_por_cohorte, len(cands)))
        muestra = [s for s in TESTIGOS if s in muestra] + \
                  sorted(x for x in muestra if x not in TESTIGOS)

    # ── clasificacion sano/roto para M3 ─────────────────────────────────────
    sanos = set()
    if args.fase1_csv and os.path.exists(args.fase1_csv):
        f1 = pd.read_csv(args.fase1_csv)
        base = f1[f1["variante"].str.startswith("V0")]
        sanos = set(base[base["cubre"] == True]["sku"].astype(str))
        log.info(f"clasificacion desde Fase 1: {len(sanos)} sanos en baseline")
    else:
        log.warning("sin --fase1-csv: M3 se calcula sobre 'todos menos testigos'")
        sanos = {s for s in muestra if s not in TESTIGOS}

    vids = [v.strip() for v in args.variantes.split(",")]
    log.info(f"muestra {len(muestra)} SKU | variantes {vids} | H={args.H} "
             f"| cutoffs={args.n_cutoffs}")
    log.info(f"fits estimados: ~{len(muestra)*len(vids)*args.n_cutoffs}")

    # ── correr ──────────────────────────────────────────────────────────────
    detalle = []   # (sku, variante, h, real, pred)
    excluidos = []
    for i, sku in enumerate(muestra, 1):
        n_obs, pct, co = perfil[sku]
        pdf = prepare_prophet_df(df_sales, sku)
        regs = get_regressors(get_categoria(df_sales, sku))
        todas = variantes_para(n_obs)

        por_var = {}
        for vid in vids:
            ov = todas.get(vid)
            if ov is None:
                log.warning(f"variante desconocida: {vid}")
                continue
            r = cv_por_horizonte(pdf, regs, ov, args.n_cutoffs, args.H)
            if r is None or r.empty:
                por_var = {}
                break
            por_var[vid] = r

        if not por_var or len(por_var) != len(vids):
            excluidos.append((sku, n_obs))
            log.info(f"[{i}/{len(muestra)}] {sku} (n={n_obs}) EXCLUIDO "
                     f"(no evaluable en todas las variantes con H={args.H})")
            continue

        for vid, r in por_var.items():
            for _, row in r.iterrows():
                detalle.append((sku, co, vid, int(row["h"]),
                                row["real"], row["pred"]))
        log.info(f"[{i}/{len(muestra)}] {sku} (n={n_obs}) ok")

    if not detalle:
        log.error("sin resultados")
        return 1

    df = pd.DataFrame(detalle, columns=["sku", "cohorte", "variante", "h", "real", "pred"])
    df["abs_err"] = (df["real"] - df["pred"]).abs()
    skus_ok = sorted(df["sku"].unique())

    def wmape_micro(d):
        sr = d["real"].abs().sum()
        return float(d["abs_err"].sum() / sr) if sr > 0 else np.nan

    def wmape_macro(d):
        vals = []
        for _s, g in d.groupby("sku"):
            vals.append(_wmape(g["real"].values, g["pred"].values))
        v = [x for x in vals if not np.isnan(x)]
        return float(np.mean(v)) if v else np.nan

    base_vid = vids[0]

    print()
    print("=" * 78)
    print(f"FASE 2 · M2 (WMAPE por horizonte) y M3 (no-regresion) | H={args.H}")
    print(f"SKU comparables: {len(skus_ok)} | excluidos: {len(excluidos)}")
    print("=" * 78)

    # M2 --------------------------------------------------------------------
    print()
    print("--- M2 · WMAPE MICRO por horizonte (delta vs baseline) ---")
    hdr = f"{'h':>3}" + "".join(f"{v:>16}" for v in vids)
    print(hdr)
    for h in range(1, args.H + 1):
        dh = df[df["h"] == h]
        if dh.empty:
            continue
        base = wmape_micro(dh[dh["variante"] == base_vid])
        fila_h = f"{h:>3}"
        for v in vids:
            w = wmape_micro(dh[dh["variante"] == v])
            if v == base_vid:
                fila_h += f"{w:>16.3f}"
            else:
                d = w - base
                fila_h += f"{w:>10.3f}{d:>+6.3f}"
        print(fila_h)

    # M3 --------------------------------------------------------------------
    print()
    print("--- M3 · GUARDARRAIL de no-regresion ---")
    grupos = {
        "todos":       [s for s in skus_ok],
        "sanos (V0)":  [s for s in skus_ok if s in sanos],
        "rotos (V0)":  [s for s in skus_ok if s not in sanos],
    }
    print(f"{'grupo':<14}{'n':>4}" + "".join(f"{v+' micro':>18}" for v in vids))
    for g, lst in grupos.items():
        if not lst:
            continue
        d = df[df["sku"].isin(lst)]
        base = wmape_micro(d[d["variante"] == base_vid])
        fila = f"{g:<14}{len(lst):>4}"
        for v in vids:
            w = wmape_micro(d[d["variante"] == v])
            if v == base_vid:
                fila += f"{w:>18.3f}"
            else:
                rel = 100.0 * (w - base) / base if base else np.nan
                fila += f"{w:>11.3f}{rel:>+6.1f}%"
        print(fila)

    print()
    print(f"{'grupo':<14}{'n':>4}" + "".join(f"{v+' macro':>18}" for v in vids))
    for g, lst in grupos.items():
        if not lst:
            continue
        d = df[df["sku"].isin(lst)]
        base = wmape_macro(d[d["variante"] == base_vid])
        fila = f"{g:<14}{len(lst):>4}"
        for v in vids:
            w = wmape_macro(d[d["variante"] == v])
            if v == base_vid:
                fila += f"{w:>18.3f}"
            else:
                rel = 100.0 * (w - base) / base if base else np.nan
                fila += f"{w:>11.3f}{rel:>+6.1f}%"
        print(fila)

    # veredicto -------------------------------------------------------------
    print()
    print("--- VEREDICTO ---")
    lst_s = grupos["sanos (V0)"]
    if not lst_s:
        print("  sin SKU sanos comparables: M3 no evaluable")
    else:
        d = df[df["sku"].isin(lst_s)]
        base = wmape_micro(d[d["variante"] == base_vid])
        for v in vids:
            if v == base_vid:
                continue
            w = wmape_micro(d[d["variante"] == v])
            rel = 100.0 * (w - base) / base if base else np.nan
            ok = rel <= args.umbral_m3
            print(f"  {v}: WMAPE sanos {rel:+.1f}% vs baseline "
                  f"(umbral +{args.umbral_m3:.1f}%) -> "
                  f"{'PASA M3' if ok else 'FALLA M3'}")
    print("  Recordar: M1 (colapso) ya fue medido en Fase 1. Adoptar requiere AMBOS.")

    if excluidos:
        print()
        print("--- EXCLUIDOS (historia insuficiente para H) ---")
        for s, n in excluidos:
            tag = "  <-- TESTIGO: validar solo por M1/M4" if s in TESTIGOS else ""
            print(f"  {s}: n_obs={n}{tag}")

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\ndetalle -> {args.csv}")
    print(f"\nlisto en {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
