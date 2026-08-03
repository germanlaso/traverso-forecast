#!/usr/bin/env python3
"""
retrain_modelos.py — Reentrenamiento de los modelos Prophet.

Paso 4 de DECISION_forecast_cobertura_y_reentrenamiento.md.

Reentrena (force_retrain=True) los SKU activos NO-MTO de mrp_sku_params usando
el MISMO camino que cron_plan.py (get_sales_df + run_sku_pipeline), para que el
resultado sea identico al que consumira el plan.

Motivo (03-08-2026): los modelos activos son del 02-07 con historia hasta el
21-06. D1 pide bien los periodos (22-23 semanas, cobertura hasta el 22-11), pero
Prophet extrapola ~12 semanas mas alla de lo aprendido: la tendencia decae, yhat
cruza cero y queda clampeado. Medido en el plan #101: 141010175 con forecast
26 -> 15 -> 7 -> 0 (muere el 21-08) y 322010325 con forecast 0 en los 56 dias.
No es falta de cobertura de fechas, es falta de senal: historia fresca re-estima
nivel y tendencia y acorta la extrapolacion.

PRERREQUISITO: D2-bis activa en forecaster.prepare_prophet_df (descarta el bin
de la semana en curso). Sin ella el bin parcial -verificado el 13-07: la semana
del 12-07 quedo con y=2 contra ~50 de las previas- sesga la tendencia a la baja,
justo el problema que se quiere corregir. El script lo verifica y aborta si falta.

DESTRUCTIVO: sobreescribe los pickles de /app/models. Hacer backup antes:
    docker exec traverso_forecast cp -r /app/models /app/models_bak_AAAAMMDD

Uso:
    python3 /app/retrain_modelos.py --dry-run              # diagnostico, no reentrena
    python3 /app/retrain_modelos.py --solo 141010175,113011290
    python3 /app/retrain_modelos.py                        # completo
"""

import argparse
import datetime as dt
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
# Prophet/cmdstanpy son extremadamente verbosos por SKU: bajarlos a WARNING para
# que el log quede legible (el del 13-07 tenia ~15 lineas de DEBUG por modelo).
for _noisy in ("prophet", "cmdstanpy", "matplotlib"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("retrain")


def _verificar_d2bis() -> bool:
    """D2-bis debe estar activa: prepare_prophet_df tiene que descartar el bin
    de la semana en curso. Se prueba con un df sintetico, sin tocar datos reales."""
    import pandas as pd
    from forecaster import prepare_prophet_df

    hoy = dt.date.today()
    dom_actual = hoy - dt.timedelta(days=(hoy.weekday() + 1) % 7)
    fechas = [dom_actual - dt.timedelta(weeks=k) for k in range(9, -1, -1)]
    df = pd.DataFrame({
        "sku": ["__TEST__"] * len(fechas),
        "fecha_semana": pd.to_datetime(fechas),
        "cantidad": [100] * (len(fechas) - 1) + [3],
        "canal": [None] * len(fechas),
        "zona": [None] * len(fechas),
        "categoria": ["X"] * len(fechas),
    })
    out = prepare_prophet_df(df, "__TEST__")
    ult = str(out["ds"].max())[:10]
    return ult != str(dom_actual)


def _cobertura(forecast: list[dict]) -> tuple[str | None, str | None, float]:
    """(ultimo ds con yhat>0, ultimo ds del forecast, total yhat)."""
    ult_pos, ult, tot = None, None, 0.0
    for row in forecast or []:
        ds = row.get("ds")
        y = float(row.get("yhat") or 0.0)
        ult = ds
        tot += max(0.0, y)
        if y > 0:
            ult_pos = ds
    return ult_pos, ult, tot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizonte", type=int, default=8,
                    help="horizonte en semanas, para calcular fecha_cobertura igual que el cron")
    ap.add_argument("--solo", type=str, default=None,
                    help="lista de SKU separados por coma (para probar con pocos)")
    ap.add_argument("--dry-run", action="store_true",
                    help="no reentrena: reporta la cobertura actual (desde cache)")
    args = ap.parse_args()

    t0 = time.time()
    hoy = dt.date.today()

    # ── D2-bis: prerrequisito ────────────────────────────────────────────────
    try:
        ok = _verificar_d2bis()
    except Exception as e:
        log.error(f"no se pudo verificar D2-bis: {e}")
        return 2
    if not ok:
        log.error("D2-bis NO esta activa (prepare_prophet_df no descarta la semana "
                  "en curso). Abortando: reentrenar asi sesga la tendencia a la baja.")
        return 2
    log.info("D2-bis verificada: la semana en curso se descarta")

    # ── datos, por el mismo camino que cron_plan ─────────────────────────────
    import mrp as _mrp
    from forecaster import run_sku_pipeline
    from main import get_sales_df

    sku_params, _lineas, _sku_lineas = _mrp.load_params_from_db()
    if not sku_params:
        log.error("parametros MRP vacios -> abortar")
        return 4

    df_sales = get_sales_df()
    log.info(f"ventas cargadas: {len(df_sales)} filas")

    # misma formula que cron_plan.py (D1)
    fecha_cobertura = hoy + dt.timedelta(days=args.horizonte * 7 + 42)
    log.info(f"fecha_cobertura objetivo: {fecha_cobertura} (horizonte {args.horizonte} sem)")

    if args.solo:
        objetivo = [s.strip() for s in args.solo.split(",") if s.strip()]
        faltan = [s for s in objetivo if s not in sku_params]
        if faltan:
            log.warning(f"SKU no presentes en params (se ignoran): {faltan}")
        objetivo = [s for s in objetivo if s in sku_params]
    else:
        objetivo = [s for s in sku_params
                    if not getattr(sku_params[s], "mto", False)]

    modo = "DRY-RUN (sin reentrenar)" if args.dry_run else "REENTRENANDO"
    log.info(f"{modo} | {len(objetivo)} SKU")

    ok_n, fail_n, cortos = 0, 0, []
    fallidos: list[tuple[str, str]] = []

    for i, sku in enumerate(sorted(objetivo), 1):
        try:
            r = run_sku_pipeline(
                df=df_sales, sku=sku, canal=None,
                forecast_periods=args.horizonte + 4,
                fecha_cobertura=fecha_cobertura,
                force_retrain=not args.dry_run,
            )
            ult_pos, ult, tot = _cobertura(r.get("forecast", []))
            corto = (ult_pos is None) or (ult_pos < fecha_cobertura.isoformat())
            if corto:
                cortos.append((sku, ult_pos, ult))
            ok_n += 1
            flag = "  <-- CORTO" if corto else ""
            log.info(f"[{i:3d}/{len(objetivo)}] {sku}: yhat>0 hasta {ult_pos} "
                     f"| fin fc {ult} | total {tot:.0f}{flag}")
        except Exception as e:
            fail_n += 1
            fallidos.append((sku, str(e)[:120]))
            log.warning(f"[{i:3d}/{len(objetivo)}] {sku}: FALLO -> {e}")

    # ── resumen ──────────────────────────────────────────────────────────────
    dur = time.time() - t0
    log.info("=" * 70)
    log.info(f"{modo} | OK={ok_n} FALLIDOS={fail_n} | {dur/60:.1f} min")
    log.info(f"objetivo de cobertura: {fecha_cobertura}")
    log.info(f"SKU que NO llegan a la fecha objetivo con yhat>0: {len(cortos)}")
    for sku, ult_pos, ult in cortos:
        log.info(f"   CORTO {sku}: yhat>0 hasta {ult_pos} (fin del fc: {ult})")
    if fallidos:
        log.info(f"fallidos ({len(fallidos)}):")
        for sku, err in fallidos:
            log.info(f"   {sku}: {err}")
    log.info("=" * 70)
    if not args.dry_run:
        log.info("Modelos reescritos en /app/models. El proximo cron del plan los usara.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
