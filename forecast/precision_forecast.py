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
  - yhat en CAJAS: Prophet entrena sobre dbo.ventas, que viene en cajas. El MRP
    multiplica por u_por_caja para pasar a unidades. (Corregido 06-10-2026.)

PASO 4 (--escribir): persiste en mrp_forecast_vintage (ON CONFLICT DO NOTHING,
el primer modelo del corte gana). TODO O NADA por corte: si un SKU falla, ese
corte no se escribe (evita cortes parciales silenciosos). yhat redondeado a 1
decimal = lo que consumio el plan (_format_forecast).

Uso:
  python3 /app/precision_forecast.py --corte 2026-09-27 --solo 250010495,141010175
  python3 /app/precision_forecast.py --corte 2026-10-04 --verificar
  python3 /app/precision_forecast.py --todos                     # dry-run, resumen por corte
  python3 /app/precision_forecast.py --corte 2026-09-27 --escribir
  python3 /app/precision_forecast.py --todos --escribir --origen backfill

PASO 5 (cron semanal, lunes 04:00 UTC, 1 h despues de cron_retrain):
  python3 /app/precision_forecast.py --ultimos 3 --escribir --origen cron
  --ultimos 3 = corte vigente + 2 anteriores: AUTORREPARABLE. Si una semana el
  job falla, la siguiente rellena el corte pendiente (DO NOTHING respeta lo ya
  escrito). Con --origen cron, cualquier error o excepcion manda alerta al admin.

PASO 6a (venta real): en el mismo run (salvo --verificar) se calcula la venta
real semanal con prepare_prophet_df (misma funcion que entrena Prophet) para
los SKU con vintage, con 0 explicito en semanas sin venta, y se hace UPSERT en
mrp_venta_semanal. Ventana: --todos desde la primera semana objetivo (corte
minimo + 7); --ultimos/--corte las ultimas SEMANAS_VENTA_CRON semanas cerradas.
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
SEMANAS_VENTA_CRON = 8      # el cron reescribe (upsert) las ultimas N semanas cerradas

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
    """sku -> (mtime, path) del PRIMER pkl cuyo domingo de corte == corte,
    tomado solo de COHORTES VALIDAS.

    Cohorte = pkl de un mismo directorio asignados al mismo corte por mtime.
    Valida sii max(ult_hist) == corte - 7: con D2-bis, un reentrenamiento real
    siempre tiene algun SKU que vendio en la ultima semana cerrada. Descarta
    copias que no preservaron el mtime (caso models_bak_20260903: `cp -r`
    manual, 441 pkl de julio con mtime 03-09 17:01). Se valida sobre la cohorte
    COMPLETA (ignorando --solo), para que un subconjunto de intermitentes no la
    invalide por error."""
    esperado = corte - timedelta(days=7)
    dirs = sorted(glob.glob(os.path.join(APP, "models_bak_*"))) + [MODELS_DIR]
    elegidos = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        cohorte = {}
        for path in glob.glob(os.path.join(d, "*.pkl")):
            sku = os.path.basename(path)[:-4]
            if "__" in sku:                      # huerfanos de segmentacion
                continue
            mt = os.path.getmtime(path)
            if _domingo(datetime.fromtimestamp(mt).date(), semana_viz_inicio) == corte:
                cohorte[sku] = (mt, path)
        if not cohorte:
            continue
        ults = []
        for sku, (mt, path) in cohorte.items():
            try:
                ults.append(pd.Timestamp(_cargar_pkl(path).history["ds"].max()).date())
            except Exception as e:
                log.warning("  %s/%s: no se pudo leer historia: %r", os.path.basename(d), sku, e)
        mx = max(ults) if ults else None
        if mx != esperado:
            log.warning("  %s: cohorte de %d pkl del corte %s DESCARTADA: max(ult_hist)=%s != %s "
                        "(el mtime no es fecha de entrenamiento)",
                        os.path.basename(d), len(cohorte), corte, mx, esperado)
            continue
        n_sel = 0
        for sku, (mt, path) in cohorte.items():
            if solo and sku not in solo:
                continue
            n_sel += 1
            if sku not in elegidos or mt < elegidos[sku][0]:
                elegidos[sku] = (mt, path)
        log.info("  %s: %d pkl del corte %s | cohorte VALIDA (max ult_hist=%s) | %d seleccionados",
                 os.path.basename(d), len(cohorte), corte, mx, n_sel)
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

def _construir_filas(corte, cand, eventos, solo, df_ventas, col_fecha, fz, origen):
    """Devuelve (filas, errores). Cada fila trae las columnas de la tabla mas
    ult_hist/fuente (solo display)."""
    skus = sorted(set(cand) | {s for s in eventos if not solo or s in solo})
    filas, errores = [], []
    for sku in skus:
        try:
            if sku in eventos:
                yh, ult = _vintage_evento(sku, corte, df_ventas, col_fecha, eventos[sku], fz)
                fuente, con_ev, mtime = "evento", True, None
            else:
                mt, path = cand[sku]
                yh, ult = _vintage_pickle(sku, path, corte, df_ventas, fz)
                fuente, con_ev = os.path.basename(os.path.dirname(path)), False
                mtime = datetime.fromtimestamp(mt)
            for h in HORIZONTES:
                filas.append(dict(sku=sku, semana_objetivo=corte + timedelta(days=7 * h),
                                  horizonte_sem=h, domingo_corte=corte,
                                  yhat_cj=round(yh[h], 1), con_evento=con_ev,
                                  modelo_mtime=mtime, origen=origen,
                                  ult_hist=ult, fuente=fuente))
        except Exception as e:
            errores.append((sku, repr(e)))
            log.error("corte %s SKU %s: %r", corte, sku, e)
    return filas, errores


def _resumen_corte(corte, filas, errores) -> str:
    if not filas:
        return f"corte {corte}: 0 filas | {len(errores)} error"
    df = pd.DataFrame(filas)
    esperado = corte - timedelta(days=7)
    u = df.drop_duplicates("sku")
    n_atras = int((u["ult_hist"] != esperado).sum())
    fuentes = ",".join(sorted(u["fuente"].unique()))
    return (f"corte {corte}: {u.shape[0]} SKU ({int(u.con_evento.sum())} evento) | "
            f"{len(df)} filas | {len(errores)} error | ult_hist!={esperado}: {n_atras} | "
            f"fuente: {fuentes}")


def _imprimir_tabla(filas):
    out = pd.DataFrame(filas)[["sku", "horizonte_sem", "domingo_corte", "semana_objetivo",
                               "yhat_cj", "con_evento", "ult_hist", "fuente"]]
    out = out.sort_values(["horizonte_sem", "sku"])
    with pd.option_context("display.max_rows", 50, "display.width", 160):
        print(out.head(50).to_string(index=False))


def _procesar(cortes, cand_por_corte, eventos, solo, df_ventas, col_fecha, fz,
              escribir, origen) -> int:
    from db_mrp import insertar_forecast_vintage
    cols_db = ("sku", "semana_objetivo", "horizonte_sem", "domingo_corte", "yhat_cj",
               "con_evento", "modelo_mtime", "origen")
    n_err_total = 0
    for corte in cortes:
        cand = cand_por_corte[corte]
        if not cand:
            log.warning("corte %s: SIN modelos del corte (no hubo reentrenamiento?) -> se omite", corte)
            continue
        filas, errores = _construir_filas(corte, cand, eventos, solo, df_ventas,
                                          col_fecha, fz, origen)
        n_err_total += len(errores)
        log.info(_resumen_corte(corte, filas, errores))
        if len(cortes) == 1 and not escribir:
            _imprimir_tabla(filas)
        if not escribir:
            continue
        if errores:
            log.error("corte %s: %d error(es) -> NO se escribe (todo o nada por corte)",
                      corte, len(errores))
            continue
        r = insertar_forecast_vintage([{k: f[k] for k in cols_db} for f in filas])
        log.info("corte %s ESCRITO: recibidas %d | insertadas %d | existentes %d",
                 corte, r["recibidas"], r["insertadas"], r["existentes"])
    modo = "ESCRITURA" if escribir else "DRY-RUN (NO se escribio en BD)"
    log.info("=== RESUMEN %s: %d corte(s) | %d error(es) ===", modo, len(cortes), n_err_total)
    return 1 if n_err_total else 0


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

def _ventas_semanales(skus, df_ventas, desde, hasta, prepare_prophet_df):
    """Venta real por (sku, semana cerrada) en [desde, hasta], 0 explicito sin venta.
    prepare_prophet_df corta la historia en la ultima venta (falla B): sin el 0,
    los intermitentes desaparecerian de la evaluacion y sesgarian las metricas."""
    semanas, c = [], desde
    while c <= hasta:
        semanas.append(c)
        c += timedelta(days=7)
    filas, errores = [], []
    for sku in skus:
        try:
            pdf = prepare_prophet_df(df_ventas, sku)
            serie = {}
            if pdf is not None and not pdf.empty:
                f = pd.to_datetime(pdf["ds"]).dt.date
                no_dom = [d for d in f if d.weekday() != 6]
                if no_dom:
                    raise RuntimeError(f"ds no domingo: {no_dom[:3]}")
                serie = dict(zip(f, pdf["y"].astype(float)))
            for w in semanas:
                filas.append(dict(sku=sku, semana=w,
                                  venta_cj=round(max(serie.get(w, 0.0), 0.0), 1)))
        except Exception as e:
            errores.append((sku, repr(e)))
            log.error("venta SKU %s: %r", sku, e)
    return filas, errores, semanas


def _procesar_ventas(a, vigente, cand_por_corte, eventos, solo, df_ventas, fz) -> int:
    from db_mrp import skus_forecast_vintage, upsert_venta_semanal
    hasta = vigente - timedelta(days=7)                 # ultima semana cerrada
    primera = CORTE_MIN + timedelta(days=7)             # primera semana objetivo posible
    if a.todos:
        desde = primera
    else:
        desde = max(primera, vigente - timedelta(days=7 * SEMANAS_VENTA_CRON))
    if desde > hasta:
        log.info("venta real: sin semanas cerradas en la ventana")
        return 0
    skus = set(skus_forecast_vintage()) | set(eventos)
    for cand in cand_por_corte.values():
        skus |= set(cand)
    if solo:
        skus &= solo
    filas, errores, semanas = _ventas_semanales(sorted(skus), df_ventas, desde, hasta,
                                                fz["prepare_prophet_df"])
    df = pd.DataFrame(filas)
    if len(df):
        tot = df.groupby("semana")["venta_cj"].sum().round(0)
        log.info("venta real %s..%s | %d SKU x %d sem = %d filas | %d error | total cj por semana: %s",
                 desde, hasta, len(skus), len(semanas), len(df), len(errores),
                 {str(k): int(v) for k, v in tot.items()})
    if not a.escribir:
        log.info("venta real: DRY-RUN (NO se escribio en BD)")
        return 1 if errores else 0
    if errores:
        log.error("venta real: %d error(es) -> NO se escribe (todo o nada)", len(errores))
        return 1
    r = upsert_venta_semanal(filas)
    log.info("venta real ESCRITA: recibidas %d | nuevas %d | cambiadas %d | iguales %d",
             r["recibidas"], r["nuevas"], r["cambiadas"], r["iguales"])
    return 0


def _alerta(asunto: str, cuerpo: str) -> None:
    """Mismo patron que cron_retrain.py: un fallo del mail no tira el proceso."""
    try:
        from enviar_faltantes import enviar_alerta
        enviar_alerta(asunto, cuerpo, None)       # None -> destinatario admin por defecto
        log.info("mail enviado: %s", asunto)
    except Exception:
        log.exception("no se pudo enviar el mail de alerta")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--corte", help="domingo de corte YYYY-MM-DD")
    g.add_argument("--todos", action="store_true",
                   help=f"todos los cortes desde {CORTE_MIN} hasta el vigente")
    g.add_argument("--ultimos", type=int,
                   help="los N cortes mas recientes (incluye el vigente)")
    ap.add_argument("--solo", default="", help="SKU separados por coma")
    ap.add_argument("--verificar", action="store_true",
                    help="test de fidelidad contra el camino de produccion (solo corte vigente)")
    ap.add_argument("--escribir", action="store_true",
                    help="persistir en mrp_forecast_vintage (sin esto: dry-run)")
    ap.add_argument("--origen", default="backfill", choices=("backfill", "cron"))
    a = ap.parse_args()
    if a.verificar and (a.escribir or a.todos or a.ultimos):
        sys.exit("ERROR: --verificar no se combina con --escribir, --todos ni --ultimos")
    if a.ultimos is not None and a.ultimos < 1:
        sys.exit("ERROR: --ultimos debe ser >= 1")
    if a.origen != "cron":
        return _main(a)
    # Modo cron: cualquier error o excepcion avisa al admin (patron cron_faltantes)
    try:
        rc = _main(a)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
        if rc:
            _alerta("[Traverso][PRECISION] vintages: fallo de validacion",
                    f"precision_forecast.py --origen cron abortó: {e.code}\n"
                    f"Revisar /home/ubuntu/traverso_precision.log")
        return rc
    except Exception as e:
        log.exception("excepcion no controlada")
        _alerta("[Traverso][PRECISION] vintages: EXCEPCION",
                f"precision_forecast.py --origen cron falló con excepción: {e!r}\n"
                f"No se escribieron vintages. La próxima corrida (--ultimos) "
                f"rellena los cortes pendientes si los modelos siguen en backup.\n"
                f"Revisar /home/ubuntu/traverso_precision.log")
        return 1
    if rc:
        _alerta("[Traverso][PRECISION] vintages con errores",
                f"precision_forecast.py --origen cron terminó con rc={rc}: algún corte "
                f"tuvo errores y NO se escribió (todo o nada por corte).\n"
                f"Revisar /home/ubuntu/traverso_precision.log")
    return rc


def _main(a) -> int:
    solo = {s.strip() for s in a.solo.split(",") if s.strip()}

    from forecaster import (make_forecast, _cap_forecast, get_categoria,
                            run_sku_pipeline, prepare_prophet_df)
    from seasonality import get_regressors
    from calendario import semana_viz_inicio
    from eventos import cargar_eventos_activos
    from main import get_sales_df
    for n in ("cmdstanpy", "prophet"):
        lg = logging.getLogger(n)
        lg.setLevel(logging.WARNING)
        lg.disabled = True        # setLevel solo no alcanza: algo lo reconfigura al entrenar
    fz = dict(make_forecast=make_forecast, _cap_forecast=_cap_forecast,
              get_categoria=get_categoria, run_sku_pipeline=run_sku_pipeline,
              get_regressors=get_regressors, prepare_prophet_df=prepare_prophet_df)

    vigente = _domingo(date.today(), semana_viz_inicio)
    if a.todos:
        cortes, c = [], CORTE_MIN
        while c <= vigente:
            cortes.append(c)
            c += timedelta(days=7)
    elif a.ultimos:
        cortes = [vigente - timedelta(days=7 * k) for k in range(a.ultimos - 1, -1, -1)]
        cortes = [c for c in cortes if c >= CORTE_MIN]
    else:
        corte = date.fromisoformat(a.corte)
        if corte.weekday() != 6:
            sys.exit(f"ERROR: --corte {corte} no es domingo")
        if corte < CORTE_MIN:
            sys.exit(f"ERROR: --corte {corte} anterior a {CORTE_MIN} (regimen pre-cron)")
        if corte > vigente:
            sys.exit(f"ERROR: --corte {corte} es futuro")
        if a.verificar and corte != vigente:
            sys.exit(f"ERROR: --verificar solo aplica al corte vigente ({vigente}): "
                     f"es el unico donde produccion de hoy = produccion de entonces")
        cortes = [corte]

    modo = "VERIFICAR" if a.verificar else ("ESCRIBIR" if a.escribir else "DRY-RUN")
    log.info("=== %s cortes=%s | h=%s | solo=%s | origen=%s ===", modo,
             [str(c) for c in cortes], HORIZONTES, sorted(solo) or "todos", a.origen)
    cand_por_corte = {c: _candidatos_corte(c, semana_viz_inicio, solo) for c in cortes}
    eventos = cargar_eventos_activos()
    log.info("SKU con evento: %s", sorted(eventos))

    log.info("cargando ventas (get_sales_df)...")
    df_ventas = get_sales_df()
    col_fecha = next((c for c in COLS_FECHA_VENTAS if c in df_ventas.columns), None)
    if not col_fecha:
        sys.exit(f"ERROR: sin columna de fecha en ventas: {list(df_ventas.columns)}")
    log.info("ventas: %d filas | columna fecha = %s", len(df_ventas), col_fecha)

    if a.verificar:
        c = cortes[0]
        return _verificar(c, cand_por_corte[c], eventos, solo, df_ventas, col_fecha, fz)
    rc_v = _procesar(cortes, cand_por_corte, eventos, solo, df_ventas, col_fecha, fz,
                     a.escribir, a.origen)
    rc_s = _procesar_ventas(a, vigente, cand_por_corte, eventos, solo, df_ventas, fz)
    return rc_v or rc_s


if __name__ == "__main__":
    sys.exit(main())
