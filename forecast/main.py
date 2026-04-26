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
from mrp import (load_params_from_excel, generar_plan_completo,
                 resumen_semanal, resumen_por_linea)
from stock import (fetch_and_save_stock, load_stock_parquet,
                   calcular_stock_disponible, stock_summary)
from ordenes import router as ordenes_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MRP_EXCEL_PATH = "/app/data/Traverso_Parametros_MRP.xlsx"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Traverso Forecast API iniciando...")
    # Pre-cargar ventas desde SQL al iniciar — evita múltiples cargas simultáneas
    try:
        logger.info("Pre-cargando ventas desde SQL Server...")
        _sales_cache["sql"] = load_sales()
        logger.info(f"Ventas pre-cargadas: {len(_sales_cache['sql'])} registros")
    except Exception as e:
        logger.warning(f"No se pudo pre-cargar ventas: {e}")
    yield


app = FastAPI(
    title="Traverso S.A. — API de Forecast",
    description="Motor Prophet · SKU x Canal x Zona · Granularidad semanal · v1.1",
    version="1.1.0",
    lifespan=lifespan,
)

app.include_router(ordenes_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class EventoComercial(BaseModel):
    name: str
    dates: list[str]
    value: float = 1.0
    label: Optional[str] = None


class ForecastRequest(BaseModel):
    sku: str
    canal: Optional[str] = None
    zona: Optional[str] = None
    periods: int = 26
    events: list[EventoComercial] = []
    force_retrain: bool = False
    use_csv: Optional[str] = None


class TrainBatchRequest(BaseModel):
    skus: list[str]
    canal: Optional[str] = None
    zona: Optional[str] = None
    periods: int = 26
    events: list[EventoComercial] = []


class AprobacionRequest(BaseModel):
    sku: str
    descripcion: str
    tipo: str
    semana_emision: str
    semana_necesidad: str
    cantidad_sugerida_cj: int
    cantidad_real_cj: int
    u_por_caja: int = 1
    responsable: str
    comentario: str = ""


class PlanRequest(BaseModel):
    skus: Optional[list[str]] = None
    canal: Optional[str] = None
    horizonte_semanas: int = 13


# ── Cache en memoria ──────────────────────────────────────────────────────────

_sales_cache: dict = {}
_sales_lock = __import__('threading').Lock()


def get_sales_df(use_csv: str | None = None):
    key = use_csv or "sql"
    if key in _sales_cache:
        return _sales_cache[key]
    with _sales_lock:
        # Double-check dentro del lock
        if key not in _sales_cache:
            if use_csv:
                logger.info(f"Cargando desde CSV: {use_csv}")
                _sales_cache[key] = load_sales_from_csv(use_csv)
            else:
                logger.info("Cargando desde SQL Server (dbo.ventas)...")
                _sales_cache[key] = load_sales()
            logger.info(f"Cargados {len(_sales_cache[key])} registros")
    return _sales_cache[key]


# ── Endpoints: Sistema ────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"])
def health():
    """Estado del servicio y conexión SQL."""
    return {
        "status": "ok",
        "db": test_connection(),
        "models_count": len(list_trained_models()),
    }


@app.delete("/cache", tags=["Sistema"])
def clear_cache():
    """Limpia el cache en memoria para forzar recarga desde SQL."""
    _sales_cache.clear()
    return {"ok": True, "message": "Cache limpiado — próxima petición recargará desde SQL"}


# ── Endpoints: Datos ──────────────────────────────────────────────────────────

@app.get("/dimensions", tags=["Datos"])
def dimensions():
    """Valores únicos de Canal y Zona disponibles en dbo.ventas."""
    try:
        return get_dimension_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/skus", tags=["Datos"])
def list_skus(use_csv: Optional[str] = Query(None)):
    """Lista todos los SKUs con volumen, cobertura de historial y dimensiones."""
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
            result["ultima_venta"] = result["ultima_venta"].dt.strftime("%Y-%m-%d")
            return result.to_dict(orient="records")
        else:
            return get_sku_list().to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Stock ──────────────────────────────────────────────────────────

# Estado del refresh en memoria
_refresh_state = {"status": "idle", "mensaje": "", "timestamp": None}

def _run_refresh():
    """Ejecuta el refresh en background y actualiza el estado."""
    global _refresh_state
    _refresh_state = {"status": "running", "mensaje": "Descargando stock desde SQL Server...", "timestamp": None}
    try:
        result = fetch_and_save_stock()
        _refresh_state = {"status": "ok", "mensaje": f"Stock actualizado: {result['n_skus']} SKUs, {result['n_registros']} registros", "timestamp": result["timestamp_refresh"], **result}
        logger.info(f"[STOCK] Refresh completado: {result}")
    except Exception as e:
        _refresh_state = {"status": "error", "mensaje": str(e), "timestamp": None}
        logger.exception("Error en refresh de stock")


@app.post("/stock/refresh", tags=["Stock"])
def stock_refresh(background_tasks: BackgroundTasks):
    """
    Inicia la descarga de stock en background y retorna inmediatamente.
    Consultar GET /stock/refresh/status para saber cuando terminó.
    """
    if _refresh_state.get("status") == "running":
        return {"status": "running", "mensaje": "Ya hay un refresh en curso"}
    background_tasks.add_task(_run_refresh)
    return {"status": "started", "mensaje": "Descarga iniciada en background"}


@app.get("/stock/refresh/status", tags=["Stock"])
def stock_refresh_status():
    """Retorna el estado del último refresh de stock."""
    return _refresh_state


@app.get("/stock/summary", tags=["Stock"])
def get_stock_summary():
    """
    Resumen del stock actual cargado en parquet.

    Muestra:
    - Totales y cobertura de SKUs/bodegas
    - Unidades vencidas excluidas del MRP
    - Unidades próximas a vencer (alerta)
    - Fecha de la última descarga
    """
    return stock_summary()


# ── Endpoints: Forecast ───────────────────────────────────────────────────────

@app.post("/forecast", tags=["Forecast"])
def forecast_sku(req: ForecastRequest):
    """
    Genera el forecast para un segmento SKU x Canal x Zona.
    - canal=None y zona=None → forecast consolidado del SKU completo
    - Incluye historial real + predicción + intervalos de confianza + métricas
    - Reutiliza modelo en caché si existe (force_retrain=true para reentrenar)
    """
    try:
        df = get_sales_df(req.use_csv)
        events = [e.model_dump() for e in req.events] if req.events else None
        return run_sku_pipeline(
            df=df,
            sku=req.sku,
            canal=req.canal,
            zona=req.zona,
            extra_events=events,
            forecast_periods=req.periods,
            force_retrain=req.force_retrain,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error forecast {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Entrenamiento ──────────────────────────────────────────────────

@app.post("/train/batch", tags=["Entrenamiento"])
async def train_batch(req: TrainBatchRequest, background_tasks: BackgroundTasks):
    """
    Entrena modelos para múltiples SKUs en segundo plano.
    Si skus=[] o skus=null, entrena TODOS los SKUs disponibles.
    """
    import time

    df = get_sales_df()
    events = [e.model_dump() for e in req.events] if req.events else None
    skus_to_train = req.skus if req.skus else sorted(df["sku"].unique().tolist())

    if not req.skus:
        logger.info(f"Entrenamiento masivo: {len(skus_to_train)} SKUs detectados")

    job_id = f"batch_{len(skus_to_train)}skus_{int(time.time())}"

    def _train():
        ok, errors = 0, 0
        for sku in skus_to_train:
            try:
                run_sku_pipeline(
                    df, sku, req.canal, req.zona,
                    extra_events=events,
                    forecast_periods=req.periods,
                    force_retrain=True,
                )
                ok += 1
                if ok % 50 == 0:
                    logger.info(f"[{job_id}] Progreso: {ok}/{len(skus_to_train)} SKUs")
            except Exception as e:
                errors += 1
                logger.warning(f"[{job_id}] {sku} error: {e}")
        logger.info(f"[{job_id}] COMPLETADO: {ok} OK, {errors} errores")

    background_tasks.add_task(_train)
    return {
        "job_id": job_id,
        "n_skus": len(skus_to_train),
        "canal": req.canal,
        "status": "en_proceso",
        "nota": "Sigue el progreso en los logs de Docker cada 50 SKUs",
    }


@app.get("/models", tags=["Modelos"])
def get_models():
    """Lista todos los modelos entrenados con sus métricas."""
    return list_trained_models()


@app.get("/metrics/{sku}", tags=["Evaluación"])
def get_metrics(
    sku: str,
    canal: Optional[str] = Query(None),
    zona: Optional[str] = Query(None),
    use_csv: Optional[str] = Query(None),
):
    """Evalúa la precisión del modelo para un segmento con hold-out."""
    try:
        df = get_sales_df(use_csv)
        prophet_df = prepare_prophet_df(df, sku, canal, zona)
        metrics = evaluate_model(prophet_df)
        return {"key": make_key(sku, canal, zona), "sku": sku,
                "canal": canal, "zona": zona, **metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Plan de Producción ─────────────────────────────────────────────

@app.post("/plan", tags=["Plan de Produccion"])
def generar_plan(req: PlanRequest = None):
    """
    Genera el plan de producción y abastecimiento.

    - Stock real desde SQL Server (parquet local — ejecutar /stock/refresh primero)
    - Aplica FEFO: lotes vencidos excluidos, próximos a vencer alertados
    - Cruza forecast Prophet con parámetros MRP del Excel
    - Genera órdenes con fecha de emisión, línea, alertas de urgencia

    Requiere que /stock/refresh se haya ejecutado al menos una vez.
    """
    try:
        if req is None:
            req = PlanRequest()

        import importlib
        import mrp as _mrp
        importlib.reload(_mrp)

        # Parámetros MRP
        sku_params, lineas, sku_lineas = _mrp.load_params_from_excel(MRP_EXCEL_PATH)

        if req.skus:
            sku_params = {k: v for k, v in sku_params.items() if k in req.skus}

        if not sku_params:
            raise HTTPException(
                status_code=404,
                detail="No se encontraron SKUs con parámetros MRP definidos",
            )

        # Stock real desde parquet
        df_stock_raw = load_stock_parquet()
        unidades_por_caja = {
            p.sku: p.unidades_por_caja for p in sku_params.values()
        }
        stocks_actuales, alertas_vcto = calcular_stock_disponible(
            df_raw=df_stock_raw,
            unidades_por_caja=unidades_por_caja,
        )

        usa_stock_real = not df_stock_raw.empty
        skus_sin_stock = [
            sku for sku in sku_params if sku not in stocks_actuales
        ]

        # Forecasts
        df = get_sales_df()
        forecasts = {}
        for sku in sku_params:
            try:
                result = run_sku_pipeline(
                    df=df,
                    sku=sku,
                    canal=req.canal,
                    forecast_periods=req.horizonte_semanas + 4,
                )
                forecasts[sku] = result.get("forecast", [])
            except Exception as e:
                logger.warning(f"Forecast no disponible para {sku}: {e}")

        if not forecasts:
            raise HTTPException(
                status_code=404,
                detail="No hay forecasts disponibles para los SKUs solicitados",
            )

        # Plan
        ordenes = _mrp.generar_plan_completo(
            sku_params=sku_params,
            forecasts=forecasts,
            stocks_actuales=stocks_actuales,
            lineas=lineas,
            horizonte_semanas=req.horizonte_semanas,
            alertas_stock=alertas_vcto,
        )

        # Alertas de vencimiento agrupadas por tipo
        vencidos = [a for a in alertas_vcto if a["tipo"] == "VENCIDO"]
        proximos = [a for a in alertas_vcto if a["tipo"] == "PROXIMO_VENCIMIENTO"]

        return {
            "n_skus": len(sku_params),
            "n_ordenes": len(ordenes),
            "n_alertas": sum(1 for o in ordenes if o["tiene_alerta"]),
            "horizonte_sem": req.horizonte_semanas,
            # ── Stock info ──────────────────────────────────────────────────
            "stock_info": {
                "usa_stock_real": usa_stock_real,
                "advertencia": (
                    None if usa_stock_real
                    else "⚠️  Sin stock real — ejecuta POST /stock/refresh. "
                         "El plan asume stock=0 para todos los SKUs."
                ),
                "skus_sin_stock_en_parquet": skus_sin_stock,
                "n_lotes_vencidos_excluidos": len(vencidos),
                "n_lotes_proximos_vencer": len(proximos),
            },
            # ── Alertas FEFO ────────────────────────────────────────────────
            "alertas_vencimiento": {
                "vencidos": vencidos,      # excluidos del MRP
                "proximos": proximos,      # incluidos pero alertados
            },
            # ── Plan ────────────────────────────────────────────────────────
            "ordenes": ordenes,
            "resumen_semanal": _mrp.resumen_semanal(ordenes),
            "carga_lineas": _mrp.resumen_por_linea(ordenes, lineas, sku_params),
        }

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Archivo MRP no encontrado en {MRP_EXCEL_PATH}. "
                   "Copia el Excel a forecast/data/",
        )
    except Exception as e:
        logger.exception("Error generando plan MRP")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/plan/params", tags=["Plan de Produccion"])
def get_mrp_params():
    """Lista los SKUs con parámetros MRP cargados desde el Excel."""
    try:
        sku_params, lineas, sku_lineas = load_params_from_excel(MRP_EXCEL_PATH)
        return {
            "n_skus": len(sku_params),
            "n_lineas": len(lineas),
            "skus": [
                {
                    "sku": p.sku,
                    "descripcion": p.descripcion,
                    "tipo": p.tipo,
                    "lead_time_sem": p.lead_time_semanas,
                    "ss_dias": p.stock_seguridad_dias,
                    "batch_min_u": p.batch_minimo,
                    "u_por_caja": p.unidades_por_caja,
                    "linea_preferida": p.linea_preferida,
                }
                for p in sku_params.values()
            ],
            "lineas": [
                {
                    "codigo": l.codigo,
                    "nombre": l.nombre,
                    "cap_u_semana": l.capacidad_u_semana,
                    "horas_disp_sem": l.horas_disponibles_semana,
                }
                for l in lineas.values()
            ],
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Excel no encontrado en {MRP_EXCEL_PATH}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ── Endpoints: Órdenes aprobadas ──────────────────────────────────────────────

@app.post("/ordenes/aprobar", tags=["Ordenes"])
def aprobar(req: AprobacionRequest):
    """
    Aprueba una orden sugerida por el MRP.
    El jefe de producción puede modificar la cantidad (cantidad_real_cj).
    Si la orden ya existe (mismo SKU + semanas), la actualiza.
    """
    try:
        return aprobar_orden(
            sku=req.sku,
            descripcion=req.descripcion,
            tipo=req.tipo,
            semana_emision=req.semana_emision,
            semana_necesidad=req.semana_necesidad,
            cantidad_sugerida_cj=req.cantidad_sugerida_cj,
            cantidad_real_cj=req.cantidad_real_cj,
            u_por_caja=req.u_por_caja,
            responsable=req.responsable,
            comentario=req.comentario,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ordenes/{orden_id}/cancelar", tags=["Ordenes"])
def cancelar(orden_id: str):
    """Cancela una orden aprobada. Puede reaprobarse después."""
    try:
        return cancelar_orden(orden_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ordenes", tags=["Ordenes"])
def listar(
    sku:    Optional[str] = None,
    estado: Optional[str] = None,
):
    """
    Lista órdenes aprobadas/canceladas.
    Filtros opcionales: sku, estado (APROBADA | CANCELADA)
    """
    return listar_ordenes(sku=sku, estado=estado)


@app.get("/ordenes/resumen", tags=["Ordenes"])
def resumen_ordenes():
    """Resumen de aprobaciones: totales, aprobadas, canceladas."""
    return resumen_aprobaciones()


@app.get("/ordenes/por-semana", tags=["Ordenes"])
def ordenes_semana():
    """
    Órdenes aprobadas indexadas por semana_necesidad.
    Usado por el dashboard de proyección de stock.
    """
    return ordenes_aprobadas_por_semana()


@app.get("/regressors", tags=["Estacionalidad"])
def get_regressors():
    """Retorna todos los regressores de estacionalidad definidos por categoría."""
    from seasonality import get_all_regressors_summary
    return get_all_regressors_summary()
