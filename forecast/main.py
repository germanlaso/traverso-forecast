"""
main.py — API FastAPI · Traverso S.A. Sistema de Forecast
Dimensiones: SKU x Canal x Zona | Granularidad: semanal
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import (test_connection, load_sales, load_sales_from_csv,
                get_sku_list, get_dimension_summary)
from forecaster import (run_sku_pipeline, list_trained_models,
                        prepare_prophet_df, evaluate_model, make_key)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Traverso Forecast API iniciando...")
    yield

app = FastAPI(
    title="Traverso S.A. — API de Forecast",
    description="Motor Prophet · SKU x Canal x Zona · Granularidad semanal · v1.0",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class EventoComercial(BaseModel):
    name:   str
    dates:  list[str]
    value:  float        = 1.0    # 1.25 = +25%, 0.85 = -15%
    label:  Optional[str] = None

class ForecastRequest(BaseModel):
    sku:            str
    canal:          Optional[str] = None   # None = consolidado todos los canales
    zona:           Optional[str] = None   # None = consolidado todas las zonas
    periods:        int           = 26     # semanas (26 = ~6 meses)
    events:         list[EventoComercial] = []
    force_retrain:  bool          = False
    use_csv:        Optional[str] = None

class TrainBatchRequest(BaseModel):
    skus:           list[str]
    canal:          Optional[str] = None
    zona:           Optional[str] = None
    periods:        int           = 26
    events:         list[EventoComercial] = []


# ── Cache en memoria ──────────────────────────────────────────────────────────
_sales_cache: dict = {}

def get_sales_df(use_csv: str | None = None):
    key = use_csv or "sql"
    if key not in _sales_cache:
        if use_csv:
            logger.info(f"Cargando desde CSV: {use_csv}")
            _sales_cache[key] = load_sales_from_csv(use_csv)
        else:
            logger.info("Cargando desde SQL Server (dbo.ventas)...")
            _sales_cache[key] = load_sales()
        logger.info(f"Cargados {len(_sales_cache[key])} registros")
    return _sales_cache[key]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"])
def health():
    """Estado del servicio y conexión SQL."""
    return {
        "status":       "ok",
        "db":           test_connection(),
        "models_count": len(list_trained_models()),
    }


@app.get("/dimensions", tags=["Datos"])
def dimensions():
    """Valores únicos de Canal y Zona disponibles en dbo.ventas."""
    try:
        return get_dimension_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/skus", tags=["Datos"])
def list_skus(use_csv: Optional[str] = Query(None)):
    """
    Lista todos los SKUs con volumen, cobertura de historial,
    número de canales y zonas en que se venden.
    """
    try:
        if use_csv:
            df = get_sales_df(use_csv)
            result = (
                df.groupby(["sku", "descripcion"])
                  .agg(
                      volumen_total=("cantidad", "sum"),
                      primera_venta=("fecha_semana", "min"),
                      ultima_venta=("fecha_semana", "max"),
                      semanas_con_venta=("fecha_semana", "nunique"),
                      n_canales=("canal", "nunique"),
                      n_zonas=("zona", "nunique"),
                  )
                  .reset_index()
                  .sort_values("volumen_total", ascending=False)
            )
            result["primera_venta"] = result["primera_venta"].dt.strftime("%Y-%m-%d")
            result["ultima_venta"]  = result["ultima_venta"].dt.strftime("%Y-%m-%d")
            return result.to_dict(orient="records")
        else:
            return get_sku_list().to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/forecast", tags=["Forecast"])
def forecast_sku(req: ForecastRequest):
    """
    Genera el forecast para un segmento SKU x Canal x Zona.

    - canal=None y zona=None → forecast consolidado del SKU completo
    - Incluye historial real + predicción + intervalos de confianza + métricas
    - Reutiliza modelo en caché si existe (force_retrain=true para reentrenar)
    """
    try:
        df     = get_sales_df(req.use_csv)
        events = [e.model_dump() for e in req.events] if req.events else None
        return run_sku_pipeline(
            df=df, sku=req.sku, canal=req.canal, zona=req.zona,
            events=events, forecast_periods=req.periods,
            force_retrain=req.force_retrain,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error forecast {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train/batch", tags=["Entrenamiento"])
async def train_batch(req: TrainBatchRequest, background_tasks: BackgroundTasks):
    """Entrena modelos para múltiples SKUs en segundo plano."""
    import time
    job_id = f"batch_{len(req.skus)}skus_{int(time.time())}"

    def _train():
        df     = get_sales_df()
        events = [e.model_dump() for e in req.events] if req.events else None
        for sku in req.skus:
            try:
                run_sku_pipeline(df, sku, req.canal, req.zona,
                                 events, req.periods, force_retrain=True)
                logger.info(f"[{job_id}] {make_key(sku, req.canal, req.zona)} OK")
            except Exception as e:
                logger.warning(f"[{job_id}] {sku} error: {e}")

    background_tasks.add_task(_train)
    return {"job_id": job_id, "skus": req.skus, "status": "en_proceso"}


@app.get("/models", tags=["Modelos"])
def get_models():
    """Lista todos los modelos entrenados con sus métricas."""
    return list_trained_models()


@app.get("/metrics/{sku}", tags=["Evaluación"])
def get_metrics(sku: str,
                canal: Optional[str] = Query(None),
                zona: Optional[str]  = Query(None),
                use_csv: Optional[str] = Query(None)):
    """Evalúa la precisión del modelo para un segmento con hold-out."""
    try:
        df         = get_sales_df(use_csv)
        prophet_df = prepare_prophet_df(df, sku, canal, zona)
        metrics    = evaluate_model(prophet_df)
        return {"key": make_key(sku, canal, zona), "sku": sku,
                "canal": canal, "zona": zona, **metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache", tags=["Sistema"])
def clear_cache():
    """Limpia el cache en memoria para forzar recarga desde SQL."""
    _sales_cache.clear()
    return {"ok": True, "message": "Cache limpiado — próxima petición recargará desde SQL"}


@app.get("/regressors", tags=["Estacionalidad"])
def get_regressors():
    """
    Retorna todos los regressores de estacionalidad definidos por categoría.
    Útil para entender qué ajustes automáticos aplica el modelo a cada SKU.
    """
    from seasonality import get_all_regressors_summary
    return get_all_regressors_summary()
