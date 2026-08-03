"""
forecaster.py — Motor de forecast con Prophet
Traverso S.A. · Piloto de Forecast
Granularidad: semanal (W) | Dimensiones: SKU x Canal x Zona
Regressores: automáticos por Categ. Comercial via seasonality.py
"""

import pickle
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from math import ceil

import pandas as pd
import numpy as np
from prophet import Prophet
from sklearn.metrics import mean_absolute_percentage_error

from seasonality import get_category_regressors, get_regressors

logger     = logging.getLogger(__name__)
MODELS_DIR = Path("/app/models")
MODELS_DIR.mkdir(exist_ok=True)

FREQ = "W"  # Semanal

# Tope del forecast: yhat nunca puede superar FORECAST_CAP_FACTOR x el máximo
# histórico real del SKU. Frena la extrapolación explosiva de Prophet en SKUs
# de poca o errática historia (picos de decenas de miles que rompían el optimizador).
FORECAST_CAP_FACTOR = 3.0


# ── Clave de segmento ─────────────────────────────────────────────────────────

def make_key(sku: str, canal: str | None = None, zona: str | None = None) -> str:
    parts = [sku.strip()]
    if canal: parts.append(canal.strip())
    if zona:  parts.append(zona.strip())
    return "__".join(parts)


# ── Preparación de datos ──────────────────────────────────────────────────────

def prepare_prophet_df(df: pd.DataFrame,
                       sku: str,
                       canal: str | None = None,
                       zona: str | None  = None) -> pd.DataFrame:
    mask = df["sku"] == sku
    if canal: mask &= df["canal"] == canal
    if zona:  mask &= df["zona"]  == zona

    seg = df[mask].copy()
    if seg.empty:
        dims = f"SKU={sku}" + (f", canal={canal}" if canal else "") + (f", zona={zona}" if zona else "")
        raise ValueError(f"Sin datos para: {dims}")

    prophet_df = (
        seg.set_index("fecha_semana")["cantidad"]
           .resample(FREQ).sum()
           .reset_index()
           .rename(columns={"fecha_semana": "ds", "cantidad": "y"})
    )
    prophet_df["y"] = prophet_df["y"].clip(lower=0)

    # (D2-bis, 03-08-2026) Descartar el bin de la semana EN CURSO.
    # resample("W") forma un bin con los pocos dias ya transcurridos. Verificado:
    # el retrain del lunes 13-07 dejo la semana 12-07 con y=2 contra ~50 de las
    # previas (111010600) -> un solo dia de venta. Ese outlier a la baja cae al
    # FINAL de la serie, justo donde Prophet estima la tendencia, y la sesga hacia
    # abajo. Ademas es inconsistente: solo afecta a los SKU que vendieron ese dia.
    # ds es el domingo de INICIO de la semana (verificado dow=Sun), asi que la
    # semana cierra en ds+6. Determinista, no depende del horario del ETL.
    # Ver DECISION_forecast_cobertura_y_reentrenamiento.md (D2-bis)
    if len(prophet_df) > 1:
        _ini_ult = prophet_df["ds"].max()
        if _ini_ult + timedelta(days=6) >= pd.Timestamp(date.today()):
            prophet_df = prophet_df.iloc[:-1]

    return prophet_df


def get_categoria(df: pd.DataFrame, sku: str) -> str:
    """Obtiene la Categ. Comercial de un SKU desde el DataFrame de ventas."""
    rows = df[df["sku"] == sku]["categoria"]
    if rows.empty:
        return ""
    val = rows.dropna().mode()
    return str(val.iloc[0]).strip().upper() if not val.empty else ""


# ── Entrenamiento ─────────────────────────────────────────────────────────────

def _apply_regressors(model: Prophet,
                      df_train: pd.DataFrame,
                      regressors: list[dict]) -> pd.DataFrame:
    """
    Agrega columnas de regressores al DataFrame y los registra en el modelo.
    Retorna el DataFrame con las columnas nuevas.
    """
    ev_dates_cache = {}
    for reg in regressors:
        col = reg["name"]
        if col not in ev_dates_cache:
            ev_dates_cache[col] = pd.to_datetime(reg["dates"])
        df_train[col] = df_train["ds"].apply(
            lambda d: 1.0 if d in ev_dates_cache[col].values else 0.0
        )
        model.add_regressor(col, standardize=False)
    return df_train


def train_model(prophet_df: pd.DataFrame,
                regressors: list[dict] | None    = None,
                extra_events: list[dict] | None  = None,
                changepoint_prior_scale: float   = 0.05,
                overrides: dict | None           = None) -> Prophet:
    """
    Entrena un modelo Prophet semanal.

    Args:
        prophet_df:             DataFrame ds/y
        regressors:             Regressores automáticos de estacionalidad (de seasonality.py)
        extra_events:           Eventos comerciales adicionales ingresados manualmente
        changepoint_prior_scale: Flexibilidad de tendencia (0.01=rígida, 0.5=flexible)
        overrides:              (03-08-2026) kwargs de Prophet a sobrescribir, para
                                experimentos controlados. ADITIVO: sin overrides el
                                comportamiento es identico al de produccion.
                                Llave especial no-Prophet:
                                  "_country_holidays": False -> no llama
                                  add_country_holidays (los feriados CL son fechas
                                  exactas y los ds son domingos, ver
                                  DISENO_fix_tendencia_forecast.md H4)
                                Ver DISENO_fix_tendencia_forecast.md §5.2
    """
    _ov = dict(overrides or {})
    _usar_holidays_cl = _ov.pop("_country_holidays", True)

    _kwargs = dict(
        yearly_seasonality="auto", # <2 años de historia -> Prophet desactiva anual (evita onda espuria en SKU nuevos). Estacionalidad de negocio via regresores.
        weekly_seasonality=True,
        daily_seasonality=False,
        changepoint_prior_scale=changepoint_prior_scale,
        seasonality_prior_scale=10.0,
        interval_width=0.90,
        seasonality_mode="multiplicative",
    )
    _kwargs.update(_ov)
    model = Prophet(**_kwargs)
    if _usar_holidays_cl:
        model.add_country_holidays(country_name="CL")

    df_train = prophet_df.copy()

    # Regressores automáticos por categoría
    all_regressors = list(regressors or [])

    # Eventos manuales adicionales del equipo comercial
    for ev in (extra_events or []):
        all_regressors.append({
            "name":  ev["name"],
            "dates": ev["dates"],
            "value": ev.get("value", 1.0),
        })

    if all_regressors:
        df_train = _apply_regressors(model, df_train, all_regressors)

    model.fit(df_train)
    return model


# ── Forecast ──────────────────────────────────────────────────────────────────

def make_forecast(model: Prophet,
                  periods: int = 26,
                  regressors: list[dict] | None   = None,
                  extra_events: list[dict] | None = None) -> pd.DataFrame:
    future = model.make_future_dataframe(periods=periods, freq=FREQ)

    all_regressors = list(regressors or [])
    for ev in (extra_events or []):
        all_regressors.append({"name": ev["name"], "dates": ev["dates"]})

    ev_dates_cache = {}
    for reg in all_regressors:
        col = reg["name"]
        if col not in ev_dates_cache:
            ev_dates_cache[col] = pd.to_datetime(reg["dates"])
        future[col] = future["ds"].apply(
            lambda d: 1.0 if d in ev_dates_cache[col].values else 0.0
        )

    fc = model.predict(future)
    for col in ("yhat", "yhat_lower", "yhat_upper"):
        fc[col] = fc[col].clip(lower=0)
    return fc[["ds", "yhat", "yhat_lower", "yhat_upper", "trend"]]


# ── Evaluación ────────────────────────────────────────────────────────────────

def evaluate_model(prophet_df: pd.DataFrame,
                   regressors: list[dict] | None = None) -> dict:
    n      = len(prophet_df)
    cutoff = max(4, int(n * 0.8))
    train  = prophet_df.iloc[:cutoff]
    test   = prophet_df.iloc[cutoff:]

    if len(train) < 8:
        return {"mape": None, "mae": None, "rmse": None,
                "note": "Historial insuficiente (mín. 8 semanas)"}

    model = train_model(train, regressors=regressors)
    fc    = make_forecast(model, periods=len(test), regressors=regressors)
    pred  = fc.iloc[-len(test):]["yhat"].values
    real  = test["y"].values
    mask  = real > 0

    if mask.sum() == 0:
        return {"mape": None, "mae": None, "rmse": None, "note": "Demanda cero en período de prueba"}

    return {
        "mape":         round(float(mean_absolute_percentage_error(real[mask], pred[mask])) * 100, 2),
        "mae":          round(float(np.mean(np.abs(real - pred))), 1),
        "rmse":         round(float(np.sqrt(np.mean((real - pred) ** 2))), 1),
        "n_train":      int(len(train)),
        "n_test":       int(len(test)),
        "n_regressors": len(regressors) if regressors else 0,
        "evaluated_at": datetime.utcnow().isoformat(),
    }


# ── Persistencia ──────────────────────────────────────────────────────────────

def save_model(model: Prophet, key: str, metadata: dict | None = None):
    path = MODELS_DIR / f"{key}.pkl"
    with open(path, "wb") as f:
        pickle.dump({"model": model, "metadata": metadata or {},
                     "saved_at": datetime.utcnow().isoformat()}, f)
    logger.info(f"Modelo guardado: {path}")


def load_model(key: str) -> tuple[Prophet, dict] | None:
    path = MODELS_DIR / f"{key}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data["model"], data.get("metadata", {})


def list_trained_models() -> list[dict]:
    result = []
    for pkl in MODELS_DIR.glob("*.pkl"):
        try:
            with open(pkl, "rb") as f:
                data = pickle.load(f)
            parts = pkl.stem.split("__")
            result.append({
                "key":      pkl.stem,
                "sku":      parts[0] if parts else pkl.stem,
                "canal":    parts[1] if len(parts) > 1 else None,
                "zona":     parts[2] if len(parts) > 2 else None,
                "saved_at": data.get("saved_at"),
                "metrics":  data.get("metadata", {}).get("metrics", {}),
                "categoria": data.get("metadata", {}).get("categoria", ""),
                "n_regressors": data.get("metadata", {}).get("n_regressors", 0),
            })
        except Exception:
            pass
    return sorted(result, key=lambda x: x["key"])


# ── Pipeline completo ─────────────────────────────────────────────────────────

def _cap_forecast(fc: pd.DataFrame,
                  prophet_df: pd.DataFrame,
                  factor: float = FORECAST_CAP_FACTOR) -> pd.DataFrame:
    """Limita yhat/yhat_lower/yhat_upper a `factor` x máximo histórico real del SKU.

    Si el SKU no tiene venta histórica positiva (max_hist <= 0), NO capa: su caso
    (SKU sin historia / nuevo) se trata por separado, no aplastando su forecast a 0.
    El tope es por segmento SKU, no global.
    """
    if prophet_df is None or prophet_df.empty:
        return fc
    max_hist = float(prophet_df["y"].max())
    if max_hist <= 0:
        return fc
    tope = factor * max_hist
    fc = fc.copy()
    for col in ("yhat", "yhat_lower", "yhat_upper"):
        fc[col] = fc[col].clip(upper=tope)
    return fc


def _periods_para_cobertura(ultima_semana,
                            fecha_cobertura: date | None,
                            minimo: int) -> int:
    """Períodos semanales necesarios para que el forecast llegue a `fecha_cobertura`.

    (D1, 27-07-2026) `make_future_dataframe` extiende desde la ÚLTIMA SEMANA
    ENTRENADA del modelo, no desde hoy. Con modelos cacheados el desfase puede
    ser de semanas: el 27-07 el 82,6% de los SKU tenía forecast que no alcanzaba
    el horizonte del plan (hasta 42 días ciegos). Anclamos los períodos a la
    fecha objetivo en vez de usar la constante `horizonte + 4`.

    Nunca devuelve menos que `minimo`: sólo amplía, jamás recorta.
    Ver DECISION_forecast_cobertura_y_reentrenamiento.md
    """
    if fecha_cobertura is None or ultima_semana is None:
        return minimo
    try:
        u = pd.Timestamp(ultima_semana).date()
    except Exception:
        return minimo
    dias = (fecha_cobertura - u).days
    if dias <= 0:
        return minimo
    return max(minimo, int(ceil(dias / 7)) + 1)   # +1: margen de semana parcial


def run_sku_pipeline(df: pd.DataFrame,
                     sku: str,
                     canal: str | None          = None,
                     zona: str | None           = None,
                     extra_events: list[dict] | None = None,
                     forecast_periods: int      = 26,
                     force_retrain: bool        = False,
                     fecha_cobertura: date | None = None) -> dict:
    """
    Pipeline completo para un segmento SKU x Canal x Zona.

    Flujo:
      1. Detecta la Categ. Comercial del SKU
      2. Carga los regressores de estacionalidad correspondientes (seasonality.py)
      3. Evalúa con hold-out (80/20)
      4. Entrena con historial completo + regressores + eventos manuales
      5. Genera forecast a `forecast_periods` semanas
      6. Guarda el modelo en disco
    """
    key       = make_key(sku, canal, zona)
    categoria = get_categoria(df, sku)

    # Regressores automáticos según categoría
    regressors = get_regressors(categoria)
    logger.info(f"SKU={sku} | categoria='{categoria}' | regressors={[r['name'] for r in regressors]}")

    # Intentar modelo en caché (solo si no hay eventos manuales que cambien el modelo)
    if not force_retrain and not extra_events:
        cached = load_model(key)
        if cached:
            model, meta = cached
            prophet_df = prepare_prophet_df(df, sku, canal, zona)
            # D1: períodos anclados a la fecha objetivo del plan. El ancla es la
            # historia DEL MODELO (puede ser vieja), no la de las ventas.
            _periods = _periods_para_cobertura(
                model.history["ds"].max(), fecha_cobertura, forecast_periods)
            fc = make_forecast(model, _periods, regressors)
            fc = _cap_forecast(fc, prophet_df)
            # Siempre devolver historial aunque venga del caché
            history = (
                prophet_df
                .rename(columns={"ds": "fecha", "y": "real"})
                .assign(fecha=lambda x: x["fecha"].dt.strftime("%Y-%m-%d"))
                .to_dict(orient="records")
            )
            return {
                "key":         key, "sku": sku, "canal": canal, "zona": zona,
                "categoria":   categoria,
                "regressors":  [r["name"] for r in regressors],
                "forecast":    _format_forecast(fc),
                "history":     history,
                "metrics":     meta.get("metrics", {}),
                "from_cache":  True,
            }

    prophet_df = prepare_prophet_df(df, sku, canal, zona)
    if len(prophet_df) < 8:
        raise ValueError(
            f"Segmento '{key}' tiene solo {len(prophet_df)} semanas. Mínimo requerido: 8."
        )

    # Evaluar con regressores
    metrics = evaluate_model(prophet_df, regressors)

    # Entrenar con historial completo
    model = train_model(prophet_df, regressors=regressors, extra_events=extra_events)
    # D1: modelo recién entrenado -> el ancla es el fin de la historia real.
    _periods = _periods_para_cobertura(
        prophet_df["ds"].max(), fecha_cobertura, forecast_periods)
    fc    = make_forecast(model, _periods, regressors, extra_events)
    fc    = _cap_forecast(fc, prophet_df)

    save_model(model, key, metadata={
        "metrics":        metrics,
        "n_history":      len(prophet_df),
        "freq":           FREQ,
        "forecast_periods": _periods,          # efectivos (D1), no el mínimo pedido
        "categoria":      categoria,
        "regressors":     [r["name"] for r in regressors],
        "n_regressors":   len(regressors),
        "trained_at":     datetime.utcnow().isoformat(),
    })

    history = (
        prophet_df
        .rename(columns={"ds": "fecha", "y": "real"})
        .assign(fecha=lambda x: x["fecha"].dt.strftime("%Y-%m-%d"))
        .to_dict(orient="records")
    )

    return {
        "key":        key, "sku": sku, "canal": canal, "zona": zona,
        "categoria":  categoria,
        "regressors": [r["name"] for r in regressors],
        "forecast":   _format_forecast(fc),
        "history":    history,
        "metrics":    metrics,
        "from_cache": False,
    }


def _format_forecast(fc: pd.DataFrame) -> list[dict]:
    return (
        fc.assign(ds=fc["ds"].dt.strftime("%Y-%m-%d"))
          .round({"yhat": 1, "yhat_lower": 1, "yhat_upper": 1, "trend": 1})
          .to_dict(orient="records")
    )
