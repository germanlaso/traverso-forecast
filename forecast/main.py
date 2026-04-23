"""
main.py — API FastAPI del sistema de forecast Traverso S.A.
Endpoints: /health, /skus, /forecast, /train, /models
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import test_connection, load_sales, load_sales_from_csv, get_sku_list
from forecaster import (
    run_sku_pipeline, list_trained_models,
    prepare_prophet_df, evaluate_model
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Traverso Forecast API iniciando...")
    yield
    logger.info("Traverso Forecast API detenida.")

app = FastAPI(
    title="Traverso S.A. — API de Forecast",
    description="Motor de predicción de demanda con Prophet. Piloto v1.0",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class EventoComercial(BaseModel):
    name:   str
    dates:  list[str]          # ["2025-02-01", "2025-02-28"]
    value:  float = 1.0        # 1.25 = +25%, 0.85 = -15%
    label:  Optional[str] = None

class ForecastRequest(BaseModel):
    sku:              str
    periods:          int              = 12
    freq:             str              = "MS"   # MS=mensual, W=semanal, D=diario
    events:           list[EventoComercial] = []
    force_retrain:    bool             = False
    use_csv:          Optional[str]    = None   # Ruta a CSV si no hay SQL

class TrainBatchRequest(BaseModel):
    skus:    list[str]
    periods: int   = 12
    freq:    str   = "MS"
    events:  list[EventoComercial] = []

# ── Cache en memoria (para piloto) ───────────────────────────────────────────
_sales_cache: dict = {}

def get_sales_df(use_csv: str | None = None):
    """Carga ventas desde SQL o CSV, con cache en memoria."""
    cache_key = use_csv or "sql"
    if cache_key not in _sales_cache:
        if use_csv:
            logger.info(f"Cargando ventas desde CSV: {use_csv}")
            _sales_cache[cache_key] = load_sales_from_csv(use_csv)
        else:
            logger.info("Cargando ventas desde SQL Server...")
            _sales_cache[cache_key] = load_sales()
        logger.info(f"Ventas cargadas: {len(_sales_cache[cache_key])} registros")
    return _sales_cache[cache_key]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"])
def health():
    """Estado del servicio y conexión a la base de datos."""
    db_status = test_connection()
    return {
        "status":    "ok",
        "db":        db_status,
        "models_ok": len(list_trained_models()),
    }


@app.get("/skus", tags=["Datos"])
def list_skus(use_csv: Optional[str] = Query(None)):
    """
    Lista todos los SKUs disponibles en el historial con volumen y cobertura.
    Usa ?use_csv=/app/data/ventas.csv para modo offline.
    """
    try:
        if use_csv:
            df   = get_sales_df(use_csv)
            skus = (
                df.groupby(["sku", "descripcion"])
                  .agg(volumen_total=("cantidad", "sum"),
                       primera_venta=("fecha", "min"),
                       ultima_venta=("fecha", "max"),
                       meses_con_venta=("fecha", lambda x: x.dt.to_period("M").nunique()))
                  .reset_index()
                  .sort_values("volumen_total", ascending=False)
            )
            skus["primera_venta"] = skus["primera_venta"].dt.strftime("%Y-%m-%d")
            skus["ultima_venta"]  = skus["ultima_venta"].dt.strftime("%Y-%m-%d")
            return skus.to_dict(orient="records")
        else:
            return get_sku_list().to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/forecast", tags=["Forecast"])
def forecast_sku(req: ForecastRequest):
    """
    Genera el forecast para un SKU específico.
    
    - Si el modelo ya existe en disco, lo reutiliza (rápido).
    - Si force_retrain=true, reentrena con datos frescos.
    - Incluye historial real + predicción + intervalos de confianza + métricas.
    """
    try:
        df     = get_sales_df(req.use_csv)
        events = [e.model_dump() for e in req.events] if req.events else None

        result = run_sku_pipeline(
            df=df,
            sku=req.sku,
            events=events,
            forecast_periods=req.periods,
            freq=req.freq,
            force_retrain=req.force_retrain,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error en forecast de SKU {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train/batch", tags=["Entrenamiento"])
async def train_batch(req: TrainBatchRequest, background_tasks: BackgroundTasks):
    """
    Entrena modelos para múltiples SKUs en segundo plano.
    Retorna inmediatamente con un job_id para consultar el estado.
    """
    job_id = f"batch_{len(req.skus)}skus_{int(__import__('time').time())}"

    def _train():
        df     = get_sales_df()
        events = [e.model_dump() for e in req.events] if req.events else None
        for sku in req.skus:
            try:
                run_sku_pipeline(df, sku, events, req.periods, req.freq, force_retrain=True)
                logger.info(f"[{job_id}] SKU {sku} entrenado OK")
            except Exception as e:
                logger.warning(f"[{job_id}] SKU {sku} error: {e}")

    background_tasks.add_task(_train)
    return {"job_id": job_id, "skus": req.skus, "status": "en_proceso"}


@app.get("/models", tags=["Modelos"])
def get_models():
    """Lista todos los modelos entrenados y guardados en disco."""
    return list_trained_models()


@app.delete("/cache", tags=["Sistema"])
def clear_cache():
    """Limpia el cache de ventas en memoria para forzar recarga desde SQL."""
    _sales_cache.clear()
    return {"ok": True, "message": "Cache limpiado"}


@app.get("/metrics/{sku}", tags=["Evaluación"])
def get_metrics(sku: str, use_csv: Optional[str] = Query(None)):
    """
    Evalúa la precisión del modelo para un SKU usando validación cruzada.
    Devuelve MAPE, MAE y RMSE.
    """
    try:
        df         = get_sales_df(use_csv)
        prophet_df = prepare_prophet_df(df, sku)
        metrics    = evaluate_model(prophet_df)
        return {"sku": sku, **metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
