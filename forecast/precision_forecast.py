"""
precision_forecast.py - Vintages del forecast para el dashboard de precision.

PASO 1 (dry-run): reconstruye, para un domingo de corte, el forecast que el
sistema tuvo vigente esa semana y lo imprime para h=1 y h=2. NO escribe en BD.

PASO 2 (--verificar): test de fidelidad sobre el corte VIGENTE. Compara la
reconstruccion contra run_sku_pipeline llamado como cron_plan.py (L332).
Esperado: diferencia 0. Los SKU con evento se reconstruyen dos veces para
verificar determinismo. NO escribe en BD ni en /app/models (persistir=False).

Definiciones acordadas (06-10-2026):
  - Semana = domingo a sabado (semana_viz_inicio).
  - domingo_corte = semana_viz_inicio(mtime del pkl). Primero del corte gana.
  - h=1 -> semana_objetivo = corte + 7 ; h=2 -> corte + 14. Nunca se mezclan.
  - SKU sin evento: pickle -> make_forecast -> _cap_forecast(model.history).
    El tope sale de la historia del modelo (= la que veia produccion esa
    semana), NO de las ventas de hoy (evita fuga de datos futuros).
  - SKU con evento: run_sku_pipeline con ventas truncadas al sabado previo al
    corte + extra_events, persistir=False (replica del camino del plan).
  - Ventana: cortes >= 2026-08-30 (regimen de reentrenamiento semanal).
  - yhat en UNIDADES (el MRP lo consume como unidades; cajas se derivan al
    consultar con unidades_por_caja).

Uso:
  python3 /app/precision_forecast.py --corte 2026-09-27 --solo 250010495,141010175
  python3 /app/precision_forecast.py --corte 2026-10-04 --verificar
"""
import argparse
import glob
import logging
import os
import pickle
import sys
from datetime import date, datetime, timedelta

import pandas as pd

APP = "/app"
MODELS_DIR = os.path.join(APP, "models")
CORTE_MIN = date(2026, 8, 30)
HORIZONTES = (1, 2)
COLS_FECHA_VENTAS = ("fecha", "fecha_semana", "ds", "Fecha")
TOL_EXACTO = 1e-6

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [precision] %(message)s")
log = logging.getLogger(__name__)


# -- Utilidades de fecha -------------------------------------------------------

def _domingo(d: date, semana_viz_inicio) -> date:
    """semana_viz_inicio normalizado a date, verificado contra calculo local."""
    r = semana_viz_inicio(d)
    if isinstance(r, str):
        r = date.fromisoformat(r[:10])
    elif isinstance(r, (pd.Timestamp, datetime)):
        r = r.date()
    local = d - timedelta(days=(d.weekday() + 1) % 7)
    if r != local or r.weekday() != 6:
        raise RuntimeError(f"semana_viz_inicio({d}) = {r}, esperado domingo {local}")
    return r


# -- Seleccion de modelos del corte ---------------------------------------------

def _candidatos_corte(corte: date, semana_viz_inicio, solo: set) -> dict:
    """sku -> (mtime, path) del PRIMER pkl cuyo domingo de corte == corte."""
    dirs = sorted(glob.glob(os.path.join(APP, "models_bak_*"))) + [MODELS_DIR]
    elegidos = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        n_dir = 0
        for path in glob.glob(os.path.join(d, "*.pkl")):
            sku = os.path.basename(path)[:-4]
            if "__" in sku:                      # huerfanos de segmentacion
                continue
            if solo and sku not in solo:
                continue
            mt = os.path.getmtime(path)
            if _domingo(datetime.fromtimestamp(mt).date(), semana_viz_inicio) != corte:
                continue
            n_dir += 1
            if sku not in elegidos or mt < elegidos[sku][0]:
                elegidos[sku] = (mt, path)
        if n_dir:
            log.info("  %s: %d pkl del corte %s", os.path.basename(d), n_dir, corte)
    return elegidos


def _cargar_pkl(path: str):
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
    except Exception:
        import joblib
        obj = joblib.load(path)
    if isinstance(obj, dict) and "model" in obj:
        return obj["model"]
    if hasattr(obj, "predict") and hasattr(obj, "history"):
        return obj
    claves = list(obj)[:8] if isinstance(obj, dict) else ""
    raise RuntimeError(f"formato de pickle no reconocido: {type(obj)} {claves}")


def _cols_forecast(fcl: pd.DataFrame) -> tuple:
    col_f = next((c for c in ("ds", "fecha", "semana") if c in fcl.columns), None)
    col_y = next((c for c in ("yhat", "forecast", "valor") if c in fcl.columns), None)
    if not col_f or not col_y:
        raise RuntimeError(f"columnas de forecast no reconocidas: {list(fcl.columns)}")
    return col_f, col_y


def _extraer(fc: pd.DataFrame, corte: date, col_f: str, col_y: str) -> dict:
    f = pd.to_datetime(fc[col_f]).dt.date
    out = {}
    for h in HORIZONTES:
        obj = corte + timedelta(days=7 * h)
        fila = fc.loc[f == obj, col_y]
        if len(fila) != 1:
            raise RuntimeError(f"semana objetivo {obj} no encontrada (n={len(fila)})")
        out[h] = float(fila.iloc[0])
    return out


# -- Caminos de prediccion -------------------------------------------------------

def _vintage_pickle(sku, path, corte, df_ventas, fz):
    model = _cargar_pkl(path)
    regs = fz["get_regressors"](fz["get_categoria"](df_ventas, sku))
    ult = pd.Timestamp(model.history["ds"].max()).date()
    obj_max = corte + timedelta(days=7 * max(HORIZONTES))
    periods = (obj_max - ult).days // 7 + 1
    if periods < 1:
        raise RuntimeError(f"historia del modelo ({ult}) posterior a la semana objetivo")
    fc = fz["make_forecast"](model, periods, regs)
    fc = fz["_cap_forecast"](fc, model.history[["ds", "y"]])
    return _extraer(fc, corte, "ds", "yhat"), ult


def _vintage_evento(sku, corte, df_ventas, col_fecha, eventos, fz):
    df_trunc = df_ventas[pd.to_datetime(df_ventas[col_fecha]).dt.date < corte]
    res = fz["run_sku_pipeline"](df_trunc, sku, extra_events=eventos,
                                 persistir=False, forecast_periods=26)
    if res.get("from_cache"):
        raise RuntimeError("run_sku_pipeline devolvio cache: el evento no se aplico")
    fcl = pd.DataFrame(res["forecast"])
    col_f, col_y = _cols_forecast(fcl)
    hist = pd.DataFrame(res.get("history", []))
    ult = pd.to_datetime(hist["fecha"]).max().date() if "fecha" in hist else None
    return _extraer(fcl, corte, col_f, col_y), ult


def _vintage_produccion(sku, corte, df_ventas, eventos_sku, fz):
    """Camino de produccion: run_sku_pipeline como lo llama cron_plan.py L332.
    persistir=False solo blinda contra escrituras; no cambia los valores."""
    res = fz["run_sku_pipeline"](df=df_ventas, sku=sku, canal=None,
                                 forecast_periods=26,
                                 extra_events=eventos_sku,
                                 persistir=False)
    fcl = pd.DataFrame(res["forecast"])
    col_f, col_y = _cols_forecast(fcl)
    return _extraer(fcl, corte, col_f, col_y), bool(res.get("from_cache"))


# -- Modos -----------------------------------------------------------------------

def _dry_run(corte, cand, eventos, solo, df_ventas, col_fecha, fz) -> int:
    skus = sorted(set(cand) | {s for s in eventos if not solo or s in solo})
    filas, errores = [], []
    for sku in skus:
        try:
            if sku in eventos:
                yh, ult = _vintage_evento(sku, corte, df_ventas, col_fecha, eventos[sku], fz)
                fuente, con_ev = "evento", True
            else:
                mt, path = cand[sku]
                yh, ult = _vintage_pickle(sku, path, corte, df_ventas, fz)
                fuente = os.path.basename(os.path.dirname(path))
                con_ev = False
            for h in HORIZONTES:
                filas.append(dict(sku=sku, h=h, corte=corte,
                                  semana_obj=corte + timedelta(days=7 * h),
                                  yhat_u=round(yh[h], 2), con_evento=con_ev,
                                  ult_hist=ult, fuente=fuente))
        except Exception as e:
            errores.append((sku, repr(e)))
            log.error("SKU %s: %r", sku, e)

    if filas:
        out = pd.DataFrame(filas).sort_values(["h", "sku"])
        with pd.option_context("display.max_rows", 50, "display.width", 160):
            print(out.head(50).to_string(index=False))
        esperado = corte - timedelta(days=7)
        n_atras = int((out.drop_duplicates("sku")["ult_hist"] != esperado).sum())
        log.info("ult_hist distinto de %s (historia corta / intermitentes): %d SKU", esperado, n_atras)

    log.info("=== RESUMEN: %d SKU ok | %d error | %d filas (NO se escribio en BD) ===",
             len(skus) - len(errores), len(errores), len(filas))
    return 1 if errores else 0


def _verificar(corte, cand, eventos, solo, df_ventas, col_fecha, fz) -> int:
    skus = sorted(set(cand) | {s for s in eventos if not solo or s in solo})
    log.info("=== VERIFICAR corte vigente %s: %d SKU ===", corte, len(skus))
    filas, errores = [], []
    for i, sku in enumerate(skus, 1):
        try:
            con_ev = sku in eventos
            if con_ev:
                rec, _ = _vintage_evento(sku, corte, df_ventas, col_fecha, eventos[sku], fz)
                rec2, _ = _vintage_evento(sku, corte, df_ventas, col_fecha, eventos[sku], fz)
            else:
                rec, _ = _vintage_pickle(sku, cand[sku][1], corte, df_ventas, fz)
                rec2 = rec
            prod, from_cache = _vintage_produccion(sku, corte, df_ventas,
                                                   eventos.get(sku), fz)
            for h in HORIZONTES:
                filas.append(dict(sku=sku, h=h, evento=con_ev, from_cache=from_cache,
                                  rec=rec[h], prod=prod[h],
                                  diff=rec[h] - prod[h], det=rec2[h] - rec[h]))
        except Exception as e:
            errores.append((sku, repr(e)))
            log.error("SKU %s: %r", sku, e)
        if i % 25 == 0:
            log.info("  ... %d/%d", i, len(skus))

    if not filas:
        log.error("sin filas para comparar")
        return 1

    df = pd.DataFrame(filas)
    df["adiff"] = df["diff"].abs()
    print("\n=== FIDELIDAD (rec = reconstruccion, prod = camino cron_plan) ===")
    for grupo, g in df.groupby("evento"):
        etiqueta = "CON evento" if grupo else "SIN evento"
        print(f"{etiqueta:11s} | filas {len(g):4d} | exactas(<1e-6) {int((g.adiff < TOL_EXACTO).sum()):4d}"
              f" | <0.01 {int((g.adiff < 0.01).sum()):4d} | <1 {int((g.adiff < 1).sum()):4d}"
              f" | max|diff| {g.adiff.max():.6f}")
    ev = df[df.evento]
    if len(ev):
        print(f"Determinismo (2 corridas, SKU con evento): max|det| = {ev['det'].abs().max():.6f}")
    sin_cache = df[(~df.evento) & (~df.from_cache)]["sku"].unique()
    print(f"SKU sin evento que produccion NO tomo de cache: {len(sin_cache)} {list(sin_cache)[:10]}")
    top = df.sort_values("adiff", ascending=False).head(10)
    with pd.option_context("display.width", 160):
        print("\nTop 10 por |diff|:")
        print(top[["sku", "h", "evento", "from_cache", "rec", "prod", "diff"]].to_string(index=False))

    log.info("=== RESUMEN VERIFICAR: %d SKU | %d error | NO se escribio nada ===",
             len(skus) - len(errores), len(errores))
    return 1 if errores else 0


# -- Main ------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", required=True, help="domingo de corte YYYY-MM-DD")
    ap.add_argument("--solo", default="", help="SKU separados por coma")
    ap.add_argument("--verificar", action="store_true",
                    help="test de fidelidad contra el camino de produccion (solo corte vigente)")
    a = ap.parse_args()

    corte = date.fromisoformat(a.corte)
    if corte.weekday() != 6:
        sys.exit(f"ERROR: --corte {corte} no es domingo")
    if corte < CORTE_MIN:
        sys.exit(f"ERROR: --corte {corte} anterior a {CORTE_MIN} (regimen pre-cron)")
    solo = {s.strip() for s in a.solo.split(",") if s.strip()}

    from forecaster import make_forecast, _cap_forecast, get_categoria, run_sku_pipeline
    from seasonality import get_regressors
    from calendario import semana_viz_inicio
    from eventos import cargar_eventos_activos
    from main import get_sales_df
    for n in ("cmdstanpy", "prophet"):
        logging.getLogger(n).setLevel(logging.WARNING)
    fz = dict(make_forecast=make_forecast, _cap_forecast=_cap_forecast,
              get_categoria=get_categoria, run_sku_pipeline=run_sku_pipeline,
              get_regressors=get_regressors)

    vigente = _domingo(date.today(), semana_viz_inicio)
    if corte > vigente:
        sys.exit(f"ERROR: --corte {corte} es futuro")
    if a.verificar and corte != vigente:
        sys.exit(f"ERROR: --verificar solo aplica al corte vigente ({vigente}): "
                 f"es el unico donde produccion de hoy = produccion de entonces")

    modo = "VERIFICAR" if a.verificar else "DRY-RUN"
    log.info("=== %s corte=%s | h=%s | solo=%s ===", modo, corte, HORIZONTES, sorted(solo) or "todos")
    cand = _candidatos_corte(corte, semana_viz_inicio, solo)
    eventos = cargar_eventos_activos()
    log.info("candidatos pickle: %d | SKU con evento: %s", len(cand), sorted(eventos))

    log.info("cargando ventas (get_sales_df)...")
    df_ventas = get_sales_df()
    col_fecha = next((c for c in COLS_FECHA_VENTAS if c in df_ventas.columns), None)
    if not col_fecha:
        sys.exit(f"ERROR: sin columna de fecha en ventas: {list(df_ventas.columns)}")
    log.info("ventas: %d filas | columna fecha = %s", len(df_ventas), col_fecha)

    if a.verificar:
        return _verificar(corte, cand, eventos, solo, df_ventas, col_fecha, fz)
    return _dry_run(corte, cand, eventos, solo, df_ventas, col_fecha, fz)


if __name__ == "__main__":
    sys.exit(main())
