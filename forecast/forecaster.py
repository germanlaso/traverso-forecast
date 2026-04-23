"""
forecaster.py — Motor de forecast con Prophet
Traverso S.A. · Piloto de Forecast
"""

import os
import json
import pickle
import logging
from pathlib import Path
from datetime import datetime, date

import pandas as pd
import numpy as np
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics
from sklearn.metrics import mean_absolute_percentage_error

logger = logging.getLogger(__name__)

MODELS_DIR = Path("/app/models")
MODELS_DIR.mkdir(exist_ok=True)


# ── Preparación de datos para Prophet ────────────────────────────────────────

def prepare_prophet_df(df: pd.DataFrame,
                       sku: str,
                       freq: str = "MS") -> pd.DataFrame:
    """
    Convierte el historial de ventas de un SKU al formato Prophet (ds, y).

    Args:
        df:   DataFrame con columnas fecha, sku, cantidad
        sku:  SKU a preparar
        freq: Frecuencia de agregación — 'D' diaria, 'W' semanal, 'MS' mensual

    Returns:
        DataFrame con columnas ds (fecha) y y (cantidad agregada)
    """
    sku_df = df[df["sku"] == sku].copy()

    if sku_df.empty:
        raise ValueError(f"SKU '{sku}' no encontrado en el historial.")

    # Agregar a la frecuencia deseada
    sku_df = (
        sku_df
        .set_index("fecha")["cantidad"]
        .resample(freq)
        .sum()
        .reset_index()
        .rename(columns={"fecha": "ds", "cantidad": "y"})
    )

    # Prophet requiere y >= 0
    sku_df["y"] = sku_df["y"].clip(lower=0)

    return sku_df


# ── Entrenamiento ─────────────────────────────────────────────────────────────

def train_model(prophet_df: pd.DataFrame,
                events: list[dict] | None = None,
                yearly_seasonality: bool = True,
                weekly_seasonality: bool = False,
                changepoint_prior_scale: float = 0.05) -> Prophet:
    """
    Entrena un modelo Prophet para un SKU.

    Args:
        prophet_df:               DataFrame con ds, y (y opcionalmente columnas de regressores)
        events:                   Lista de eventos comerciales como regressores
                                  [{"name": "promo_verano", "dates": ["2023-02-01", ...], "value": 1.25}]
        yearly_seasonality:       Capturar estacionalidad anual
        weekly_seasonality:       Capturar estacionalidad semanal (útil si datos son diarios)
        changepoint_prior_scale:  Flexibilidad de la tendencia (0.01=rígida, 0.5=flexible)

    Returns:
        Modelo Prophet entrenado
    """
    model = Prophet(
        yearly_seasonality=yearly_seasonality,
        weekly_seasonality=weekly_seasonality,
        daily_seasonality=False,
        changepoint_prior_scale=changepoint_prior_scale,
        seasonality_prior_scale=10.0,
        interval_width=0.90,          # Intervalo de confianza 90%
        seasonality_mode="multiplicative",
    )

    # Feriados chilenos
    model.add_country_holidays(country_name="CL")

    # Regressores de eventos comerciales
    df_train = prophet_df.copy()
    if events:
        for event in events:
            col_name = event["name"]
            event_dates = pd.to_datetime(event["dates"])
            df_train[col_name] = df_train["ds"].apply(
                lambda d: event.get("value", 1.0) if d in event_dates.values else 0.0
            )
            model.add_regressor(col_name, standardize=False)

    model.fit(df_train)
    return model


# ── Forecast ──────────────────────────────────────────────────────────────────

def make_forecast(model: Prophet,
                  periods: int = 12,
                  freq: str = "MS",
                  events: list[dict] | None = None) -> pd.DataFrame:
    """
    Genera el forecast para los próximos `periods` períodos.

    Returns:
        DataFrame con: ds, yhat, yhat_lower, yhat_upper, trend
    """
    future = model.make_future_dataframe(periods=periods, freq=freq)

    # Agregar regressores de eventos futuros al dataframe futuro
    if events:
        for event in events:
            col_name    = event["name"]
            event_dates = pd.to_datetime(event["dates"])
            future[col_name] = future["ds"].apply(
                lambda d: event.get("value", 1.0) if d in event_dates.values else 0.0
            )

    forecast = model.predict(future)

    # Clip negativos (no tiene sentido demanda negativa)
    for col in ["yhat", "yhat_lower", "yhat_upper"]:
        forecast[col] = forecast[col].clip(lower=0)

    return forecast[["ds", "yhat", "yhat_lower", "yhat_upper", "trend"]]


# ── Evaluación ────────────────────────────────────────────────────────────────

def evaluate_model(prophet_df: pd.DataFrame,
                   freq: str = "MS") -> dict:
    """
    Evalúa la precisión del modelo con validación cruzada.
    Usa el 20% final del historial como set de prueba.

    Returns:
        Dict con métricas: mape, mae, rmse
    """
    n       = len(prophet_df)
    cutoff  = max(3, int(n * 0.8))
    train   = prophet_df.iloc[:cutoff]
    test    = prophet_df.iloc[cutoff:]

    if len(train) < 6:
        return {"mape": None, "mae": None, "rmse": None,
                "note": "Historial insuficiente para evaluación"}

    model    = train_model(train)
    forecast = make_forecast(model, periods=len(test), freq=freq)

    pred = forecast.iloc[-len(test):]["yhat"].values
    real = test["y"].values

    # Evitar división por cero en MAPE
    mask = real > 0
    if mask.sum() == 0:
        return {"mape": None, "mae": None, "rmse": None,
                "note": "Todos los valores reales son 0"}

    mape = float(mean_absolute_percentage_error(real[mask], pred[mask]))
    mae  = float(np.mean(np.abs(real - pred)))
    rmse = float(np.sqrt(np.mean((real - pred) ** 2)))

    return {
        "mape":         round(mape * 100, 2),
        "mae":          round(mae, 1),
        "rmse":         round(rmse, 1),
        "n_train":      len(train),
        "n_test":       len(test),
        "evaluated_at": datetime.utcnow().isoformat(),
    }


# ── Persistencia de modelos ───────────────────────────────────────────────────

def save_model(model: Prophet, sku: str, metadata: dict | None = None):
    """Guarda el modelo entrenado en disco."""
    path = MODELS_DIR / f"{sku}.pkl"
    with open(path, "wb") as f:
        pickle.dump({"model": model, "metadata": metadata or {}, 
                     "saved_at": datetime.utcnow().isoformat()}, f)
    logger.info(f"Modelo guardado: {path}")


def load_model(sku: str) -> tuple[Prophet, dict] | None:
    """Carga un modelo previamente entrenado."""
    path = MODELS_DIR / f"{sku}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data["model"], data.get("metadata", {})


def list_trained_models() -> list[dict]:
    """Lista todos los modelos entrenados con su metadata."""
    models = []
    for pkl in MODELS_DIR.glob("*.pkl"):
        try:
            with open(pkl, "rb") as f:
                data = pickle.load(f)
            models.append({
                "sku":      pkl.stem,
                "saved_at": data.get("saved_at"),
                "metadata": data.get("metadata", {}),
            })
        except Exception:
            pass
    return sorted(models, key=lambda x: x["sku"])


# ── Pipeline completo para un SKU ─────────────────────────────────────────────

def run_sku_pipeline(df: pd.DataFrame,
                     sku: str,
                     events: list[dict] | None = None,
                     forecast_periods: int = 12,
                     freq: str = "MS",
                     force_retrain: bool = False) -> dict:
    """
    Pipeline completo: prepara datos → entrena → evalúa → genera forecast → guarda.

    Args:
        df:               DataFrame completo de ventas
        sku:              SKU a procesar
        events:           Eventos comerciales como regressores
        forecast_periods: Períodos a forecastear
        freq:             Frecuencia ('MS' mensual, 'W' semanal, 'D' diaria)
        force_retrain:    Si True, reentrena aunque ya exista modelo guardado

    Returns:
        Dict con forecast, métricas e historial
    """
    # Intentar cargar modelo existente
    if not force_retrain:
        cached = load_model(sku)
        if cached:
            model, meta = cached
            forecast = make_forecast(model, forecast_periods, freq, events)
            return {
                "sku":       sku,
                "forecast":  forecast.to_dict(orient="records"),
                "metrics":   meta.get("metrics", {}),
                "from_cache": True,
            }

    # Preparar datos
    prophet_df = prepare_prophet_df(df, sku, freq)

    if len(prophet_df) < 6:
        raise ValueError(f"SKU '{sku}' tiene menos de 6 períodos de historial. "
                         f"Mínimo recomendado: 24 meses.")

    # Evaluar antes de entrenar con todos los datos
    metrics = evaluate_model(prophet_df, freq)

    # Entrenar con historial completo
    model    = train_model(prophet_df, events)
    forecast = make_forecast(model, forecast_periods, freq, events)

    # Guardar
    save_model(model, sku, metadata={
        "metrics":        metrics,
        "n_history":      len(prophet_df),
        "freq":           freq,
        "forecast_periods": forecast_periods,
        "trained_at":     datetime.utcnow().isoformat(),
    })

    # Historial formateado para respuesta
    history = prophet_df.rename(columns={"ds": "fecha", "y": "real"})
    history["fecha"] = history["fecha"].dt.strftime("%Y-%m-%d")

    return {
        "sku":       sku,
        "forecast":  forecast.assign(ds=forecast["ds"].dt.strftime("%Y-%m-%d"))
                             .to_dict(orient="records"),
        "history":   history.to_dict(orient="records"),
        "metrics":   metrics,
        "from_cache": False,
    }
