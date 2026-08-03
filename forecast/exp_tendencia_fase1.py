#!/usr/bin/env python3
"""
exp_tendencia_fase1.py — Screening de variantes de tendencia (M1 colapso + M4 nivel).

Fase 1 de DISENO_fix_tendencia_forecast.md §5.3.

QUE MIDE (y que NO)
-------------------
Mide la SALUD del forecast, no su error. Entrena con TODA la historia y proyecta
a la fecha objetivo, igual que produccion. No necesita ground truth, asi que
cuesta 1 fit por SKU/variante (contra 6 del rolling-origin) y funciona incluso en
SKU con historia muy corta que el CV no puede evaluar (251010100, n_obs=11).

  M1 · colapso : el ultimo ds con yhat>0 llega a fecha_cobertura?  -> debe SUBIR
  M4 · nivel   : media de yhat en las ultimas 4 semanas del horizonte
                 / media de las ultimas 12 semanas reales          -> debe -> 1
  trend_fin    : trend en el ultimo periodo. NEGATIVO = modelo roto.
  n_cero       : semanas con yhat=0 dentro del horizonte (clamp silencioso, H7)

NO mide WMAPE: eso es Fase 2, sobre las variantes que sobrevivan aca. Filtrar
primero por "elimina el colapso?" y despues por "a que costo en precision?"
ahorra la mayor parte del computo.

VARIANTES (una variable por corrida, §5.2)
------------------------------------------
  V0 baseline · V1 growth=flat · V2 n_changepoints=n_obs//10 · V3 cps=0.01
  V4 weekly_seasonality=False  · V5 sin add_country_holidays · V6 additive

NO ESCRIBE NADA: no guarda modelos ni toca /app/models. Es solo lectura.

Uso:
    # primera vez (paga la carga del datalake, ~1-11 min segun la hora)
    python3 /app/exp_tendencia_fase1.py --cache-ventas /tmp/ventas_exp.parquet

    # siguientes iteraciones (reusa el parquet, arranca en segundos)
    python3 /app/exp_tendencia_fase1.py --cache-ventas /tmp/ventas_exp.parquet

    # solo los 3 testigos, una variante
    python3 /app/exp_tendencia_fase1.py --skus 230010255,119010520,251010100 --variantes V0,V1
"""

import argparse
import datetime as dt
import logging
import os
import random
import sys
import time

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
for _noisy in ("prophet", "cmdstanpy", "matplotlib"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("exp1")

# Los 3 SKU con venta estable y forecast 0 (medidos el 03-08 sobre #101).
# Si una variante no los arregla, no resuelve el problema.
TESTIGOS = ["230010255", "119010520", "251010100"]


def variantes_para(n_obs: int) -> dict[str, dict]:
    """Overrides por variante. V2 depende de n_obs, por eso es una funcion."""
    return {
        "V0_baseline":   {},
        "V1_flat":       {"growth": "flat"},
        "V2_ncp":        {"n_changepoints": int(min(25, max(0, n_obs // 10)))},
        "V3_cps001":     {"changepoint_prior_scale": 0.01},
        "V4_noweekly":   {"weekly_seasonality": False},
        "V5_noholidays": {"_country_holidays": False},
        "V6_additive":   {"seasonality_mode": "additive"},
    }


def cohorte(n_obs: int, pct_con_venta: float) -> str:
    largo = "corta" if n_obs < 52 else ("media" if n_obs <= 104 else "larga")
    if pct_con_venta >= 0.80:
        reg = "regular"
    elif pct_con_venta >= 0.30:
        reg = "intermitente"
    else:
        reg = "esporadico"
    return f"{largo}/{reg}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizonte", type=int, default=8)
    ap.add_argument("--n-por-cohorte", type=int, default=3)
    ap.add_argument("--skus", type=str, default=None,
                    help="lista explicita; si se pasa, no estratifica")
    ap.add_argument("--variantes", type=str, default=None,
                    help="subconjunto, ej. V0,V1 (por prefijo)")
    ap.add_argument("--cache-ventas", type=str, default=None,
                    help="parquet para cachear el df de ventas entre corridas")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", type=str, default=None, help="volcar el detalle a CSV")
    args = ap.parse_args()

    t0 = time.time()
    hoy = dt.date.today()
    fecha_cobertura = hoy + dt.timedelta(days=args.horizonte * 7 + 42)

    from forecaster import (prepare_prophet_df, train_model, make_forecast,
                            _cap_forecast, get_categoria)
    from seasonality import get_regressors
    import mrp as _mrp

    # ── ventas (con cache opcional: la carga puede tardar minutos) ───────────
    if args.cache_ventas and os.path.exists(args.cache_ventas):
        df_sales = pd.read_parquet(args.cache_ventas)
        log.info(f"ventas desde cache {args.cache_ventas}: {len(df_sales)} filas")
    else:
        from main import get_sales_df
        log.info("cargando ventas del datalake (puede tardar varios minutos)...")
        df_sales = get_sales_df()
        log.info(f"ventas cargadas: {len(df_sales)} filas")
        if args.cache_ventas:
            try:
                df_sales.to_parquet(args.cache_ventas)
                log.info(f"cache guardado en {args.cache_ventas}")
            except Exception as e:
                log.warning(f"no se pudo guardar el cache: {e}")

    sku_params, _l, _sl = _mrp.load_params_from_db()
    if not sku_params:
        log.error("params MRP vacios -> abortar")
        return 4

    # ── perfilar SKU (n_obs + intermitencia) para estratificar ──────────────
    universo = [s for s in sku_params if not getattr(sku_params[s], "mto", False)]
    perfil: dict[str, tuple[int, float, str]] = {}
    for s in universo:
        try:
            pdf = prepare_prophet_df(df_sales, s)
        except Exception:
            continue
        n = len(pdf)
        if n < 8:
            continue
        ult = pdf.tail(52)["y"]
        pct = float((ult > 0).sum()) / max(1, len(ult))
        perfil[s] = (n, pct, cohorte(n, pct))
    log.info(f"universo perfilable: {len(perfil)} SKU de {len(universo)} no-MTO")

    # ── muestra ─────────────────────────────────────────────────────────────
    if args.skus:
        muestra = [s.strip() for s in args.skus.split(",") if s.strip() in perfil]
        faltan = [s.strip() for s in args.skus.split(",") if s.strip() not in perfil]
        if faltan:
            log.warning(f"SKU no perfilables (se omiten): {faltan}")
    else:
        rnd = random.Random(args.seed)
        porco: dict[str, list[str]] = {}
        for s, (_n, _p, co) in perfil.items():
            porco.setdefault(co, []).append(s)
        muestra = [s for s in TESTIGOS if s in perfil]
        for co in sorted(porco):
            cands = sorted(x for x in porco[co] if x not in muestra)
            muestra += rnd.sample(cands, min(args.n_por_cohorte, len(cands)))
        # testigos primero, resto ordenado
        muestra = [s for s in TESTIGOS if s in muestra] + \
                  sorted(x for x in muestra if x not in TESTIGOS)

    log.info(f"muestra: {len(muestra)} SKU | fecha_cobertura={fecha_cobertura}")
    for s in muestra:
        n, pct, co = perfil[s]
        tag = "  <-- TESTIGO" if s in TESTIGOS else ""
        log.info(f"   {s}: n_obs={n:3d} sem_con_venta={pct:5.0%} [{co}]{tag}")

    filtro = [v.strip() for v in args.variantes.split(",")] if args.variantes else None
    filas = []

    # ── correr ──────────────────────────────────────────────────────────────
    for i, sku in enumerate(muestra, 1):
        n_obs, pct, co = perfil[sku]
        pdf = prepare_prophet_df(df_sales, sku)
        regs = get_regressors(get_categoria(df_sales, sku))
        ult_hist = pdf["ds"].max()
        # periodos hasta la fecha objetivo (misma logica que D1)
        per = max(1, int((fecha_cobertura - ult_hist.date()).days / 7) + 1)
        media_hist = float(pdf.tail(12)["y"].mean())

        todas = variantes_para(n_obs)
        for vid, ov in todas.items():
            if filtro and not any(vid.startswith(f) for f in filtro):
                continue
            try:
                m = train_model(pdf, regressors=regs, overrides=ov)
                fc = make_forecast(m, per, regs)
                fc = _cap_forecast(fc, pdf)
            except Exception as e:
                log.warning(f"[{i}/{len(muestra)}] {sku} {vid}: FALLO {e}")
                filas.append(dict(sku=sku, n_obs=n_obs, cohorte=co, variante=vid,
                                  ok=False, cubre=False, ult_pos=None,
                                  trend_fin=None, nivel=None, n_cero=None))
                continue

            fut = fc[fc["ds"] > ult_hist]
            pos = fut[fut["yhat"] > 0]
            ult_pos = str(pos["ds"].max())[:10] if not pos.empty else None
            cubre = bool(ult_pos and ult_pos >= fecha_cobertura.isoformat())
            trend_fin = float(fut["trend"].iloc[-1]) if not fut.empty else None
            nivel = (float(fut.tail(4)["yhat"].mean()) / media_hist) if media_hist > 0 else None
            n_cero = int((fut["yhat"] <= 0).sum())

            filas.append(dict(sku=sku, n_obs=n_obs, cohorte=co, variante=vid,
                              ok=True, cubre=cubre, ult_pos=ult_pos,
                              trend_fin=trend_fin, nivel=nivel, n_cero=n_cero))
        log.info(f"[{i}/{len(muestra)}] {sku} listo ({len(todas)} variantes)")

    res = pd.DataFrame(filas)
    if res.empty:
        log.error("sin resultados")
        return 1

    # ── reporte ─────────────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print(f"FASE 1 · M1 (colapso) y M4 (nivel) | objetivo de cobertura {fecha_cobertura}")
    print("=" * 78)
    print()
    print("--- AGREGADO POR VARIANTE ---")
    print(f"{'variante':<16}{'%cubre':>8}{'%trend<0':>10}{'nivel_med':>11}{'cero_med':>10}")
    for vid, g in res.groupby("variante"):
        gv = g[g["ok"]]
        if gv.empty:
            continue
        pc = 100.0 * gv["cubre"].mean()
        tn = 100.0 * (gv["trend_fin"] < 0).mean()
        nv = gv["nivel"].median(skipna=True)
        cz = gv["n_cero"].median()
        print(f"{vid:<16}{pc:>7.0f}%{tn:>9.0f}%{nv:>11.2f}{cz:>10.0f}")

    print()
    print("--- TESTIGOS (si una variante no los arregla, no sirve) ---")
    tg = res[res["sku"].isin(TESTIGOS)]
    print(f"{'sku':<12}{'variante':<16}{'cubre':>7}{'ult_pos':>13}{'trend_fin':>11}{'nivel':>8}")
    for _, r in tg.sort_values(["sku", "variante"]).iterrows():
        tf = f"{r['trend_fin']:.1f}" if r["trend_fin"] is not None else "-"
        nv = f"{r['nivel']:.2f}" if r["nivel"] is not None else "-"
        print(f"{r['sku']:<12}{r['variante']:<16}{str(r['cubre']):>7}"
              f"{str(r['ult_pos']):>13}{tf:>11}{nv:>8}")

    print()
    print("--- POR COHORTE (%cubre) ---")
    piv = res[res["ok"]].pivot_table(index="cohorte", columns="variante",
                                     values="cubre", aggfunc="mean") * 100
    print(piv.round(0).to_string())

    if args.csv:
        res.to_csv(args.csv, index=False)
        print(f"\ndetalle -> {args.csv}")

    print()
    print(f"listo en {(time.time()-t0)/60:.1f} min")
    print("Criterio: adoptar solo si %cubre sube Y los 3 testigos pasan a cubre=True.")
    print("La calidad (WMAPE por horizonte, guardarrail de no-regresion) es Fase 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
