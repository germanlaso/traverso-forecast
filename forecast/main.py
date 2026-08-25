"""
main.py — API FastAPI · Traverso S.A. Sistema de Forecast
Dimensiones: SKU x Canal x Zona | Granularidad: semanal
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import (test_connection, load_sales, load_sales_from_csv,
                get_sku_list, get_dimension_summary)
from forecaster import (run_sku_pipeline, list_trained_models,
                        prepare_prophet_df, evaluate_model, make_key)
from mrp import (load_params_from_excel, load_params_from_db, generar_plan_completo,
                 resumen_semanal, resumen_por_linea)
from stock import (fetch_and_save_stock, load_stock_parquet,
                   calcular_stock_disponible, stock_summary)
from ordenes import router as ordenes_router
from campanas_api import router as campanas_router
from db_mrp import (numero_of_tentativo, get_orden_by_key,
                    crear_tablas_params, get_all_lineas, get_all_sku_params,
                    update_sku_param, update_linea)
from proyeccion import construir_proyeccion_por_sku

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MRP_EXCEL_PATH = "/app/data/Traverso_Parametros_MRP.xlsx"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Traverso Forecast API iniciando...")
    # Crear tablas de parámetros MRP en PostgreSQL
    try:
        crear_tablas_params()
        logger.info("Tablas de parámetros MRP verificadas/creadas")
    except Exception as _e_tbls:
        logger.warning(f"No se pudieron crear tablas de parámetros: {_e_tbls}")
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
app.include_router(campanas_router)   # V6: campanas de granel

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


class PlanRequest(BaseModel):
    skus: Optional[list[str]] = None
    canal: Optional[str] = None
    horizonte_semanas: int = 13
    optimizar: bool = False
    incluir_pedidos: bool = True    # V-OV: netear OV abiertas de HANA al plan


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
            # (10-08-2026) Esta pantalla es de ANALISIS: nunca debe escribir el
            # cache de produccion. Con eventos el veto ya era automatico, pero
            # `force_retrain=True` SIN eventos (el boton "Reentrenar") todavia
            # pisaba el pickle. Es el incidente del 05-08 (§3.3): una pantalla de
            # exploracion no puede romper el plan. Para entrenar de verdad estan
            # /train/batch y retrain_modelos.py.
            persistir=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error forecast {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Eventos comerciales ────────────────────────────────────────────
# Los modelos Pydantic van ACA y no en la seccion de modelos de arriba, a
# proposito: main.py es un archivo sensible y asi toda la feature vive en un
# tramo contiguo que se revierte borrandolo. Los imports de eventos* son LOCALES
# a cada endpoint por la misma razon: si algo falla en esos modulos, se cae este
# grupo de endpoints y no el arranque de la API entera.
#
# FLUJO PENSADO PARA EL OPERADOR: declara UN periodo en fechas naturales y el
# backend hace el resto. No se le pide identificar semanas ni fases, porque no
# puede saberlo: el corte entre fases sale de un quiebre estructural de la serie.
#   1. POST /eventos/analizar  -> el sistema propone 1 o 2 fases
#   2. POST /eventos/preview   -> que habria pasado el anio pasado, en cajas
#   3. POST /eventos           -> guarda

class EventoFase(BaseModel):
    etiqueta: str = "base"
    fecha_desde: str
    fecha_hasta: str
    nivel: Optional[float] = None


class EventoAnalizarRequest(BaseModel):
    sku: str
    fecha_desde: str
    fecha_hasta: str
    canal: Optional[str] = None
    zona: Optional[str] = None


class EventoPreviewRequest(BaseModel):
    sku: str
    fases: list[EventoFase]
    canal: Optional[str] = None
    zona: Optional[str] = None


class EventoGuardarRequest(BaseModel):
    nombre: str
    sku: str
    fases: list[EventoFase]
    tipo: str = "pasado"
    nota: Optional[str] = None
    reemplazar: bool = True     # borra las filas previas de ese (nombre, sku)


@app.get("/eventos", tags=["Eventos"])
def eventos_listar(sku: Optional[str] = None, solo_activos: bool = False):
    """Eventos cargados, y los regresores efectivos que produciran."""
    try:
        from db_mrp import get_eventos
        from eventos import cargar_eventos_activos, expandir_a_domingos
        filas = get_eventos(sku=sku, solo_activos=solo_activos)
        for f in filas:
            f["n_semanas"] = len(expandir_a_domingos(f["fecha_desde"], f["fecha_hasta"]))
        return {"eventos": filas, "regresores": cargar_eventos_activos(sku=sku)}
    except Exception as e:
        logger.exception("Error listando eventos")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/eventos/analizar", tags=["Eventos"])
def eventos_analizar(req: EventoAnalizarRequest):
    """Propone las fases del periodo declarado y devuelve la serie para graficar.

    Solo lectura y sin entrenar: es rapido.
    """
    try:
        from eventos_deteccion import detectar_fases
        df = get_sales_df()
        return detectar_fases(df, req.sku, req.fecha_desde, req.fecha_hasta,
                              canal=req.canal, zona=req.zona)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error analizando evento {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/eventos/preview", tags=["Eventos"])
def eventos_preview(req: EventoPreviewRequest):
    """Que habria pasado el anio pasado, con y sin la correccion.

    LENTO (~5 s): entrena DOS modelos Prophet en memoria. Ninguno se persiste.
    El frontend necesita spinner.
    """
    try:
        from eventos_deteccion import preview_evento
        df = get_sales_df()
        fases = [f.model_dump() for f in req.fases]
        return preview_evento(df, req.sku, fases, canal=req.canal, zona=req.zona)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error en preview de evento {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/eventos", tags=["Eventos"])
def eventos_guardar(req: EventoGuardarRequest):
    """Guarda un evento: una fila por fase. Idempotente si reemplazar=True."""
    try:
        from db_mrp import borrar_eventos, upsert_evento
        from eventos import cargar_eventos_activos
        if not req.fases:
            raise HTTPException(status_code=400, detail="Sin fases que guardar.")
        if req.tipo == "futuro":
            # Un evento futuro NO puede ser un regresor (columna cero en todo el
            # entrenamiento -> coeficiente no identificable). Necesita ajuste
            # post-hoc del forecast, que es Fase 2 y no esta implementado. Y
            # antes hay que resolver el doble conteo contra las OV de HANA.
            raise HTTPException(
                status_code=400,
                detail=("Los eventos futuros todavia no se aplican: requieren "
                        "ajuste post-hoc del forecast (Fase 2)."))
        n_borradas = borrar_eventos(req.nombre, req.sku) if req.reemplazar else 0
        ids = [upsert_evento(nombre=req.nombre, sku=req.sku,
                             etiqueta=f.etiqueta, fecha_desde=f.fecha_desde,
                             fecha_hasta=f.fecha_hasta, tipo=req.tipo,
                             nota=req.nota) for f in req.fases]
        return {"ok": True, "ids": ids, "filas_reemplazadas": n_borradas,
                "regresores": cargar_eventos_activos(sku=req.sku)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error guardando evento {req.sku}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/eventos", tags=["Eventos"])
def eventos_borrar(nombre: str, sku: str, solo_desactivar: bool = True):
    """Desactiva (default) o borra un evento completo.

    Desactivar es la operacion segura: deja la fila para auditoria y el cron
    deja de usarla. `solo_desactivar=false` borra de verdad.
    """
    try:
        if solo_desactivar:
            from db_mrp import set_evento_activo
            n = set_evento_activo(nombre, sku, False)
            return {"ok": True, "desactivadas": n}
        from db_mrp import borrar_eventos
        return {"ok": True, "borradas": borrar_eventos(nombre, sku)}
    except Exception as e:
        logger.exception(f"Error borrando evento {sku}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Entrenamiento ──────────────────────────────────────────────────

@app.post("/train/batch", tags=["Entrenamiento"])
async def train_batch(req: TrainBatchRequest, background_tasks: BackgroundTasks):
    """
    Entrena modelos para múltiples SKUs en segundo plano.
    Si skus=[] o skus=null, entrena TODOS los SKUs disponibles.
    """
    import time

    # (10-08-2026) Entrenar en lote CON eventos no guardaria nada: los eventos
    # vetan la persistencia del pickle (ver INVARIANTE en run_sku_pipeline). El
    # lote correria los 250 modelos y descartaria todo, en silencio. Mejor fallar
    # rapido que dejar creer que se reentreno.
    if req.events:
        raise HTTPException(
            status_code=400,
            detail=("El entrenamiento en lote no admite eventos: un modelo "
                    "entrenado con eventos no se persiste, asi que el lote no "
                    "guardaria nada. Para probar eventos use /forecast o "
                    "/eventos/preview."))

    df = get_sales_df()
    events = None
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

def _fetch_pedidos_abiertos(skus_validos: set) -> dict:
    """V-OV: lee pedidos abiertos (OV) desde SAP HANA para netearlos al plan.

    FAIL-SAFE: ante cualquier error (HANA caído, credencial, driver ausente)
    devuelve {} y loguea — un problema de HANA NUNCA debe romper el plan diario.
    Kill-switch de ops: env OV_NETTING_ENABLED=0 lo desactiva sin redeploy.
    Devuelve {sku: {fecha: cajas}} filtrado a skus_validos (SKU de producción).
    """
    import os
    if os.environ.get("OV_NETTING_ENABLED", "1") not in ("1", "true", "True", "yes"):
        logger.info("[Plan] Neteo de OV desactivado por OV_NETTING_ENABLED.")
        return {}
    try:
        from datetime import date
        import hana_pedidos
        conn = hana_pedidos.conectar()
        try:
            pedidos = hana_pedidos.obtener_pedidos_abiertos(
                conn, hoy=date.today(), skus_validos=skus_validos,
            )
        finally:
            conn.close()
        n_cj = sum(c for fechas in pedidos.values() for c in fechas.values())
        logger.info(f"[Plan] OV neteadas: {len(pedidos)} SKU, {n_cj:.0f} cajas comprometidas.")
        return pedidos
    except Exception as e:
        logger.warning(f"[Plan] No pude leer OV de HANA; se planifica SIN pedidos: {e}")
        return {}


def _fetch_ov_split(skus_validos: set) -> tuple[dict, dict]:
    """V-OV2 (10-07): OV separada en (futuras, comprometido).

        futuras      {sku: {fecha: cajas}}  fecha >= hoy -> DEMANDA en su fecha.
        comprometido {sku: cajas}           fecha < hoy  -> se RESTA del stock_inicial
                     (stock ya apartado por notas de venta vencidas, no despachadas;
                     no es demanda a producir).

    Mismo FAIL-SAFE y kill-switch que _fetch_pedidos_abiertos: ante cualquier error
    devuelve ({}, {}) y el plan sigue sin OV.
    """
    import os
    if os.environ.get("OV_NETTING_ENABLED", "1") not in ("1", "true", "True", "yes"):
        logger.info("[Plan] Neteo de OV desactivado por OV_NETTING_ENABLED.")
        return {}, {}
    try:
        from datetime import date
        import hana_pedidos
        conn = hana_pedidos.conectar()
        try:
            futuras, comprometido = hana_pedidos.obtener_ov_split(
                conn, hoy=date.today(), skus_validos=skus_validos,
            )
        finally:
            conn.close()
        cj_fut = sum(c for fechas in futuras.values() for c in fechas.values())
        cj_comp = sum(comprometido.values())
        logger.info(
            f"[Plan] OV split: futuras(demanda) {len(futuras)} SKU / {cj_fut:.0f} cj | "
            f"comprometido(rebaja stock) {len(comprometido)} SKU / {cj_comp:.0f} cj."
        )
        return futuras, comprometido
    except Exception as e:
        logger.warning(f"[Plan] No pude leer OV de HANA; se planifica SIN pedidos: {e}")
        return {}, {}


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

        # v1.2: Quitado importlib.reload(_mrp). Causaba que se cargara el .pyc viejo
        # incluso después de cambios en mrp.py. Documentado en ESTADO_TECNICO_PROYECTO.md.
        import mrp as _mrp

        # Parámetros MRP
        # Cargar parámetros desde PostgreSQL (fallback a Excel si BD vacía)
        try:
            sku_params, lineas, sku_lineas = _mrp.load_params_from_db()
            if not sku_params:
                raise ValueError("BD de parámetros vacía")
        except Exception as _e_params:
            logger.warning(f"Fallback a Excel para parámetros: {_e_params}")
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

        # Cargar órdenes aprobadas para recálculo con realidad
        from db_mrp import listar_aprobadas_db
        aprobadas_db = listar_aprobadas_db()
        # Convertir a dict {sku → [{fecha_entrada_real, cantidad_real_cj}]}
        from datetime import date as _hoy_date
        hoy_str = _hoy_date.today().isoformat()
        entradas_fijas = {}
        for ap in aprobadas_db:
            sku_ap = str(ap.get("sku",""))
            fer = str(ap.get("fecha_entrada_real") or ap.get("semana_necesidad",""))[:10]
            fl  = str(ap.get("fecha_lanzamiento_real") or "")[:10]   # V6.37
            ln  = str(ap.get("linea") or "")                          # V6.37
            cj  = float(ap.get("cantidad_real_cj") or 0)
            # Solo inyectar entradas futuras — las pasadas ya están en el stock real de SQL
            # Auto-rechazo: si fer <= hoy, asumimos que la OF se perdió o ya llegó al stock real
            if sku_ap and fer and cj > 0 and fer > hoy_str:
                if sku_ap not in entradas_fijas:
                    entradas_fijas[sku_ap] = []
                entradas_fijas[sku_ap].append({
                    "fecha_entrada": fer,
                    "fecha_lanzamiento": fl,         # V6.37: descuento cap/N_max
                    "linea": ln,                     # V6.37: descuento cap/N_max
                    "semana_necesidad": str(ap.get("semana_necesidad",""))[:10],
                    "cantidad_cajas": cj,
                    "numero_of": ap.get("numero_of",""),
                    "aprobada": True,
                })

        # Plan — con entradas fijas de órdenes aprobadas
        ordenes = _mrp.generar_plan_completo(
            sku_params=sku_params,
            forecasts=forecasts,
            stocks_actuales=stocks_actuales,
            lineas=lineas,
            horizonte_semanas=req.horizonte_semanas,
            alertas_stock=alertas_vcto,
            entradas_fijas=entradas_fijas,
        )

        # Alertas de vencimiento agrupadas por tipo
        vencidos = [a for a in alertas_vcto if a["tipo"] == "VENCIDO"]
        proximos = [a for a in alertas_vcto if a["tipo"] == "PROXIMO_VENCIMIENTO"]

        # ── OR-Tools: optimizar si se solicitó ──────────────────────────────
        diag_opt = {"optimizado": False}
        if req.optimizar:
            try:
                from optimizer import optimizar_plan
                logger.info("[Plan] Iniciando optimizador OR-Tools...")
                # V-OV2 (10-07): OV separada. Futuras = demanda en su fecha. Vencidas
                # (comprometido) = stock ya apartado -> se RESTA del stock_inicial (no
                # se produce demanda inexistente). skus_validos = SKU de PRODUCCIÓN.
                pedidos_abiertos = {}
                comprometido = {}
                if getattr(req, "incluir_pedidos", True):
                    skus_prod = {s for s, p in sku_params.items()
                                 if str(getattr(p, "tipo", "")).upper() == "PRODUCCION"}
                    pedidos_abiertos, comprometido = _fetch_ov_split(skus_prod)
                    # Rebaja del stock por OV vencida (permite negativo = quiebre real
                    # ya ocurrido -> el modelo produce para cubrir lo comprometido).
                    if comprometido:
                        n_neg = 0
                        for s, cj in comprometido.items():
                            nuevo = stocks_actuales.get(s, 0.0) - cj
                            stocks_actuales[s] = nuevo
                            if nuevo < 0:
                                n_neg += 1
                        logger.info(
                            f"[Plan] Stock rebajado por OV vencida: {len(comprometido)} SKU "
                            f"({sum(comprometido.values()):.0f} cj); {n_neg} quedan en disponible < 0."
                        )
                ordenes, diag_opt = optimizar_plan(
                    ordenes_mrp=ordenes,
                    sku_params=sku_params,
                    lineas=lineas,
                    forecasts=forecasts,
                    stocks_actuales=stocks_actuales,
                    entradas_fijas=entradas_fijas,
                    pedidos_abiertos=pedidos_abiertos,
                    horizonte_semanas=req.horizonte_semanas,
                )
                logger.info(f"[Plan] OR-Tools: {diag_opt.get('status')} "
                            f"t={diag_opt.get('tiempo_ms')}ms")

                # v1.2: el optimizer consumió las OFs aprobadas como entradas internas
                # del modelo, pero el frontend igual necesita verlas en la lista.
                # Las inyectamos como filas adicionales con aprobada=True.
                # V6.42: usar linea y fecha_lanzamiento REALES de la aprobada (campos
                # que V6.37 propaga desde BD). Antes se reescribian con linea_preferida
                # del SKU y fecha_lanzamiento = fecha_entrada - lead_time, lo que rompia
                # la visualizacion cuando el operador editaba esos campos en el modal.
                # Fallback: si los campos no estan (datos legacy pre-F3), usar el
                # calculo viejo para no romper.
                from datetime import date as _date_helper, timedelta as _td_helper
                for sku_ap, lst in entradas_fijas.items():
                    sp_ap = sku_params.get(sku_ap)
                    upc_ap = getattr(sp_ap, "unidades_por_caja", 1) if sp_ap else 1
                    lt_ap = getattr(sp_ap, "lead_time_semanas", 1) if sp_ap else 1
                    desc_ap = getattr(sp_ap, "descripcion", "") if sp_ap else ""
                    tipo_ap = getattr(sp_ap, "tipo", "PRODUCCION") if sp_ap else "PRODUCCION"
                    linea_pref = getattr(sp_ap, "linea_preferida", None) if sp_ap else None
                    for ent in lst:
                        if not ent.get("aprobada"):
                            continue
                        fer_iso = str(ent.get("fecha_entrada", ""))[:10]
                        if not fer_iso:
                            continue
                        try:
                            f_ent = _date_helper.fromisoformat(fer_iso)
                        except ValueError:
                            continue
                        # V6.42: fecha_lanzamiento desde el campo propagado por V6.37,
                        # con fallback al calculo viejo (entrada - lead_time)
                        fl_iso = str(ent.get("fecha_lanzamiento", "") or "")[:10]
                        if fl_iso:
                            f_lan_iso = fl_iso
                        else:
                            f_lan_iso = (f_ent - _td_helper(days=int(round(lt_ap * 7)))).isoformat()
                        # V6.42: linea desde el campo propagado por V6.37, con fallback
                        # a linea_preferida del SKU
                        linea_ap = ent.get("linea", "") or linea_pref
                        cj_ap = int(round(float(ent.get("cantidad_cajas", 0) or 0)))
                        ordenes.append({
                            "sku": sku_ap,
                            "descripcion": desc_ap,
                            "tipo": tipo_ap,
                            "semana_necesidad": ent.get("semana_necesidad", "") or fer_iso,
                            "semana_emision": f_lan_iso,
                            "fecha_lanzamiento": f_lan_iso,
                            "fecha_entrada_real": fer_iso,
                            "cantidad_cajas": cj_ap,
                            "cantidad_unidades": cj_ap * upc_ap,
                            "linea": linea_ap,
                            "motivo": "OF aprobada",
                            "alerta": None,
                            "tiene_alerta": False,
                            "stock_inicial_cajas": 0,
                            "stock_final_cajas": 0,
                            "forecast_cajas": 0,
                            "ss_cajas": 0,
                            "lead_time_sem": lt_ap,
                            "u_por_caja": upc_ap,
                            "aprobada": True,
                            "numero_of": ent.get("numero_of", ""),
                        })
            except Exception as e_opt:
                logger.error(f"[Plan] Error OR-Tools: {e_opt} — devuelto plan MRP")
                diag_opt = {"optimizado": False, "error": str(e_opt)}

        # Asignar número OF y lead_time_sem a cada orden (después del optimizador)
        import re as _re
        for o in ordenes:
            # lead_time_sem para que el frontend calcule fecha_entrada exacta
            sku_p = sku_params.get(o.get("sku", ""))
            if sku_p and "lead_time_sem" not in o:
                o["lead_time_sem"] = getattr(sku_p, "lead_time_semanas", 1)

            # Si ya tiene numero_of asignado (aprobada fija), saltar
            if o.get("numero_of") and o.get("aprobada"):
                continue

            motivo = o.get("motivo", "")
            # Caso 1: fila de entrada aprobada del MRP (prefijo OF_APROBADA:)
            m_ap = _re.search(r"OF_APROBADA:([\w-]+)", motivo)
            if m_ap:
                o["numero_of"] = m_ap.group(1)
                o["aprobada"] = True
                continue
            # Caso 2: buscar en BD
            # F3 (12/05/2026): clave (sku, fecha_lanzamiento, linea). Antes (sku, sn, se).
            fl = o.get("fecha_lanzamiento") or o.get("semana_emision")
            linea_o = o.get("linea") or ""
            existente = get_orden_by_key(o["sku"], fl, linea_o)
            if existente and existente.get("numero_of"):
                o["numero_of"] = existente["numero_of"]
                o["aprobada"] = bool(existente.get("estado") == "APROBADA")
            else:
                o["numero_of"] = numero_of_tentativo(o["sku"], fl, linea_o)
                o["aprobada"] = False

        # ── Proyección por SKU (Bloque B1 / V6.27) ──────────────────────────
        # Backend emite proyección completa; frontend solo renderiza.
        # Cierra V6.14 v2 + V6.26 (ver docs/SCHEMA_PROYECCION_POR_SKU.md).
        # Nota: si req.skus filtra sku_params arriba (L378-379),
        # proyeccion_por_sku solo cubre ese subset (semántica consistente con el plan).
        proyeccion_por_sku = construir_proyeccion_por_sku(
            ordenes_finales=ordenes,
            aprobadas_db=aprobadas_db,
            sku_params=sku_params,
            forecasts=forecasts,
            stocks_actuales=stocks_actuales,
            fecha_inicio=_hoy_date.today(),
            horizonte_dias=req.horizonte_semanas * 7,
        )

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
            "optimizacion": diag_opt,
            "proyeccion_por_sku": proyeccion_por_sku,
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


@app.get("/plan/vigente", tags=["Plan de Produccion"])
def get_plan_vigente():
    """Devuelve el plan VIGENTE persistido en mrp_planes (el que promovio el cron).

    El dashboard consume este endpoint en vez de regenerar el plan al vuelo.
    Retorna la vista_dashboard (forma legacy: ordenes/stock_info/n_alertas/
    resumen_semanal/n_skus/n_ordenes) + metadata de frescura para avisar si el
    stock es viejo. Si no hay plan vigente, retorna disponible=False.
    """
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal
    from datetime import date as _date
    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT id, horizonte_sem, status, gap, aceptable, "
            "timestamp_stock, created_at, snapshot "
            "FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {"disponible": False,
                "mensaje": "No hay plan vigente. El cron aun no genero uno, o ninguno paso el gate."}
    snap = row["snapshot"] or {}
    vista = snap.get("vista_dashboard") or {}
    ts_stock = row["timestamp_stock"]
    # frescura: el stock del plan vigente es de hoy?
    stock_es_hoy = bool(ts_stock and ts_stock.date() == _date.today())
    return {
        "disponible": True,
        "plan_id": row["id"],
        "horizonte_sem": row["horizonte_sem"],
        "status": row["status"],
        "gap": row["gap"],
        "aceptable": row["aceptable"],
        "timestamp_stock": str(ts_stock) if ts_stock else None,
        "created_at": str(row["created_at"]),
        "stock_es_hoy": stock_es_hoy,
        "advertencia_frescura": (
            None if stock_es_hoy
            else f"El stock del plan vigente es del {ts_stock}, no de hoy. "
                 f"Puede estar desactualizado."
        ),
        # los 6 campos que el frontend espera (misma forma que POST /plan):
        "n_skus": vista.get("n_skus"),
        "n_ordenes": vista.get("n_ordenes"),
        "n_alertas": vista.get("n_alertas"),
        "stock_info": vista.get("stock_info"),
        "ordenes": vista.get("ordenes", []),
        "resumen_semanal": vista.get("resumen_semanal"),
        "proyeccion_por_sku": vista.get("proyeccion_por_sku", {}),
    }


@app.get("/plan/proyeccion_diaria/{sku}", tags=["Plan de Produccion"])
def get_proyeccion_diaria(sku: str):
    """Serie DIARIA para la pestaña Stock Diario. LECTOR DELGADO.

    (11-07) Lee TODO del snapshot del plan vigente (detalle_diario + encabezado_sku),
    calculado por el optimizer con fuente única (calcular_ss_diario, split OV,
    stock real sin clamp). NO recalcula forecast/SS/pedidos — así el dashboard
    muestra EXACTAMENTE lo que el modelo optimizó (fin del 'vemos datos distintos').

    Fallback: para planes viejos (sin detalle_diario en el snapshot) devuelve
    disponible=False con motivo, para que el frontend muestre 'regenerar plan'.
    """
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal
    import mrp as _mrp

    # 1) plan vigente
    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT id, horizonte_sem, created_at, snapshot "
            "FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {"disponible": False,
                "mensaje": "No hay plan vigente. El cron aún no generó uno."}
    snap = row["snapshot"] or {}

    detalle = (snap.get("detalle_diario") or {}).get(sku)
    encab = (snap.get("encabezado_sku") or {}).get(sku)

    # Fallback: plan viejo sin los campos nuevos (generado antes del 11-07)
    if detalle is None or encab is None:
        return {
            "disponible": False,
            "plan_viejo": True,
            "mensaje": ("El plan vigente (id={}) es anterior al detalle diario. "
                        "Regenerá el plan para ver la vista corregida."
                        ).format(row["id"]),
            "plan_id": row["id"],
        }

    # 2) descripción del SKU (cosmético; no recalcula nada del plan)
    try:
        sku_params, _l, _sl = _mrp.load_params_from_db()
        sp = sku_params.get(sku)
        descripcion = getattr(sp, "descripcion", "") if sp else ""
    except Exception:
        descripcion = ""

    upc = int(encab.get("u_por_caja", 1) or 1)

    def _cj(u):
        return round(u / upc, 1) if (u is not None and upc) else (None if u is None else 0.0)

    # 3) serie diaria: leer del snapshot, exponer en unidades Y cajas
    dias = []
    for fecha_iso in sorted(detalle.keys()):
        c = detalle[fecha_iso]
        dias.append({
            "fecha": fecha_iso,
            "oft_cajas": c.get("oft_cajas"),
            "stock_ini_disp_u": c.get("stock_ini_disp_u"),
            "stock_ini_disp_cj": _cj(c.get("stock_ini_disp_u")),
            "pedidos_u": c.get("pedidos_u"),
            "pedidos_cj": _cj(c.get("pedidos_u")),
            "pedidos_crudos_u": c.get("pedidos_crudos_u"),
            "pedidos_crudos_cj": _cj(c.get("pedidos_crudos_u")),
            "demanda_corr_u": c.get("demanda_corr_u"),
            "demanda_corr_cj": _cj(c.get("demanda_corr_u")),
            "forecast_u": c.get("forecast_u"),
            "forecast_cj": _cj(c.get("forecast_u")),
            "stock_fin_u": c.get("stock_fin_u"),
            "stock_fin_cj": _cj(c.get("stock_fin_u")),
            "ss_u": c.get("ss_u"),
            "ss_cj": _cj(c.get("ss_u")),
            "estado": c.get("estado"),
        })

    # 4) encabezado (todo en unidades + cajas)
    encabezado = {
        "stock_fisico_u": encab.get("stock_fisico_u"),
        "stock_fisico_cj": _cj(encab.get("stock_fisico_u")),
        "comprometido_u": encab.get("comprometido_u"),
        "comprometido_cj": _cj(encab.get("comprometido_u")),
        "disponible_inicial_u": encab.get("disponible_inicial_u"),
        "disponible_inicial_cj": _cj(encab.get("disponible_inicial_u")),
        "stock_final_u": encab.get("stock_final_u"),
        "stock_final_cj": _cj(encab.get("stock_final_u")),
        "stock_min_u": encab.get("stock_min_u"),
        "stock_min_cj": _cj(encab.get("stock_min_u")),
        "ss_dias": encab.get("ss_dias"),
    }

    return {
        "disponible": True,
        "sku": sku,
        "descripcion": descripcion,
        "upc": upc,
        "ss_dias": encab.get("ss_dias"),
        "plan_id": row["id"],
        "fecha_inicio": row["created_at"].date().isoformat() if row["created_at"] else None,
        "horizonte_dias": int(row["horizonte_sem"] or 4) * 7,
        "encabezado": encabezado,
        "dias": dias,
    }


def _proyeccion_sin_demanda(sku, snap, row, _dd):
    """Proyeccion para un SKU que NO entro al MRP (sin forecast ni OV).

    No hay demanda que proyectar, asi que la curva es el stock actual mas las OF
    aprobadas que tenga cargadas. Sirve para ver cobertura y entradas en vez de un
    cartel de error. Se marca `sin_demanda=True` para que el front lo aclare.
    """
    from db_mrp import get_all_sku_params, listar_aprobadas_db

    prm = next((p for p in get_all_sku_params() if str(p.get("sku")) == str(sku)), None)
    if prm is None:
        return {"disponible": False,
                "mensaje": f"El SKU {sku} no esta en los parametros MRP.",
                "plan_id": row["id"]}
    upc = int(prm.get("u_por_caja", 1) or 1) or 1

    # Fechas: las mismas del plan, para que el grafico use el mismo horizonte.
    fechas = sorted(next(iter(_dd.values())).keys())

    # Stock disponible actual (consolidado Traverso+Montaner, 3 bodegas).
    # Firma real (misma que usa /plan): devuelve (stocks_actuales, alertas_vcto).
    #
    # (14-08-2026) FIX unidad: `calcular_stock_disponible` devuelve CAJAS
    # ("stock ya viene en cajas, sin conversión" — su docstring; el parametro
    # unidades_por_caja esta marcado como IGNORADO). El valor se guardaba tal
    # cual en `stock_ini_u`, que el resto de la funcion trata como UNIDADES, y
    # despues `_cj()` lo dividia por upc para "pasarlo a cajas": el dashboard
    # mostraba stock_real / upc. Medido en 121010290: 4.664 cj reales -> 156 cj
    # en pantalla (4664/30). Solo afecta a los SKU que NO entraron al MRP (los
    # que pasan por esta funcion); los del plan salen del snapshot, ya correctos
    # — por eso 121010210 se veia bien y 121010290 no.
    stock_ini_u = 0
    try:
        _df = load_stock_parquet()
        _stocks, _ = calcular_stock_disponible(
            df_raw=_df, unidades_por_caja={str(sku): upc})
        _v = _stocks.get(str(sku)) if isinstance(_stocks, dict) else None
        if isinstance(_v, dict):
            # Rama defensiva: si alguna vez devuelve dict, esas claves YA son unidades.
            stock_ini_u = int(round(float(
                _v.get("disponible_u", _v.get("stock_u", 0)) or 0)))
        elif _v is not None:
            stock_ini_u = int(round(float(_v) * upc))   # CAJAS -> unidades
    except Exception as _e:
        logger.warning(f"[proyeccion sin demanda] stock de {sku} no disponible: {_e}")

    entradas = {}
    try:
        for ap in listar_aprobadas_db():
            if str(ap.get("sku", "")) != str(sku):
                continue
            fer = str(ap.get("fecha_entrada_real") or "")[:10]
            if not fer:
                continue
            # V6.46: cantidad_real_u puede venir SUCIO (cajas en lugar de unidades)
            # cuando la OF se aprobo/edito sin u_por_caja en el request. El dato que
            # ingresa el operario y que usa el optimizer es cantidad_real_cj:
            # derivar SIEMPRE de ahi. Auditado 31-07-2026: 22 de 24 OF editadas mal.
            u = float(ap.get("cantidad_real_cj") or 0) * upc
            entradas[fer] = entradas.get(fer, 0.0) + float(u or 0)
    except Exception:
        entradas = {}

    def _cj(u):
        return round(u / upc, 1) if (u is not None and upc) else None

    dias, stock = [], stock_ini_u
    for f in fechas:
        ent = int(round(entradas.get(f, 0.0)))
        ini = stock
        stock = ini + ent
        dias.append({
            "fecha": f, "oft_cajas": None,
            "stock_ini_disp_u": ini, "stock_ini_disp_cj": _cj(ini),
            "pedidos_u": 0, "pedidos_cj": 0.0,
            "pedidos_crudos_u": 0, "pedidos_crudos_cj": 0.0,
            "demanda_corr_u": 0, "demanda_corr_cj": 0.0,
            "forecast_u": 0, "forecast_cj": 0.0,
            "stock_fin_u": stock, "stock_fin_cj": _cj(stock),
            "ss_u": 0, "ss_cj": 0.0,
            "entrada_aprobada_u": ent,
            "estado": "OK",
            "oft_lineas": [], "aprob_lineas": [],
        })

    sf = [d["stock_fin_u"] for d in dias] or [0]
    return {
        "disponible": True, "sin_demanda": True, "plan_id": row["id"], "sku": sku,
        "upc": upc, "descripcion": prm.get("descripcion", ""),
        "mensaje": ("Este SKU no entro al plan: no tiene forecast ni pedidos, asi que "
                    "no hay demanda que proyectar. La curva muestra el stock actual y "
                    "las OF aprobadas."),
        "dias": dias,
        "encabezado": {
            "stock_fisico_u": stock_ini_u, "stock_fisico_cj": _cj(stock_ini_u),
            "comprometido_u": 0, "comprometido_cj": 0.0,
            "disponible_inicial_u": stock_ini_u, "disponible_inicial_cj": _cj(stock_ini_u),
            "stock_final_u": sf[-1], "stock_final_cj": _cj(sf[-1]),
            "stock_min_u": min(sf), "stock_min_cj": _cj(min(sf)),
            "ss_dias": prm.get("ss_dias"), "u_por_caja": upc,
        },
    }


@app.get("/plan/proyeccion_diaria_live/{sku}", tags=["Plan de Produccion"])
def get_proyeccion_diaria_live(sku: str):
    """
    (13-07) Como /plan/proyeccion_diaria, pero RECALCULA el balance de stock
    superponiendo las OF aprobadas VIVAS (cantidad/fecha actuales de
    mrp_aprobaciones), SIN correr el optimizer. La curva refleja el cambio al
    instante cuando el planificador modifica una OF.

    Alcance (definido con German 13-07): solo mueve las entradas aprobadas y
    recalcula el balance hacia adelante; NO re-optimiza produccion (eso es warm
    start, tema aparte). Las OFT del optimizer quedan fijas.
    """
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal, listar_aprobadas_db

    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT id, horizonte_sem, created_at, timestamp_stock, snapshot "
            "FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {"disponible": False,
                "mensaje": "No hay plan vigente. El cron aun no genero uno."}
    snap = row["snapshot"] or {}
    detalle = (snap.get("detalle_diario") or {}).get(sku)
    encab = (snap.get("encabezado_sku") or {}).get(sku)
    if detalle is None or encab is None:
        # (30-07) Distinguir DOS casos que antes se reportaban igual ("plan viejo"):
        #  a) el snapshot no tiene detalle_diario -> si, plan viejo.
        #  b) el snapshot lo tiene pero ESTE SKU no entro al MRP: sin forecast y sin
        #     OV no hay demanda, asi que el optimizer no lo planifica (los 33 MTO sin
        #     pedido y los pocos de PRODUCCION sin forecast). El plan es correcto; el
        #     SKU simplemente no tiene filas. Para esos se arma una proyeccion plana
        #     desde el stock actual + las OF aprobadas, que es informacion util.
        _dd = snap.get("detalle_diario") or {}
        if not _dd:
            return {"disponible": False, "plan_viejo": True,
                    "mensaje": "El plan vigente es anterior al detalle diario. Regenera el plan.",
                    "plan_id": row["id"]}
        return _proyeccion_sin_demanda(sku, snap, row, _dd)

    upc = int(encab.get("u_por_caja", 1) or 1)
    def _cj(u):
        return round(u / upc, 1) if (u is not None and upc) else (None if u is None else 0.0)

    # (11-08-2026) UNA SOLA REGLA CON EL PLAN.
    # Antes esta curva sumaba TODAS las aprobadas vivas, mientras el plan excluye las
    # de `fer <= hoy` (cron_plan.py L281). Resultado: el 11-08 el modal de 251010105
    # mostraba 0 dias de quiebre y el Mapa de Quiebres 1, con 900 cj de diferencia y
    # nada en pantalla que lo explicara.
    #
    # Y la curva estaba MAS equivocada que el plan, no menos: de esas 900 cj solo
    # habian llegado ~263, y esas ya estaban dentro del stock inicial del propio
    # grafico -> las contaba DOS VECES. Es el mismo doble conteo contra el que
    # advierte el comentario del filtro en cron_plan.
    #
    # Ahora la curva usa la regla del plan y lo pendiente se informa APARTE: un solo
    # numero de quiebres, y al lado el aviso de la recepcion sin confirmar.
    _hoy_plan = str(row["timestamp_stock"] or row["created_at"] or "")[:10]

    entradas_plan = {}          # fer > hoy_plan  -> las que el plan cuenta
    entradas_pend = {}          # fer <= hoy_plan -> recepcion de hoy o pasada
    _of_pend = []
    try:
        for ap in listar_aprobadas_db():
            if str(ap.get("sku", "")) != sku:
                continue
            fer = str(ap.get("fecha_entrada_real") or "")[:10]
            if not fer:
                continue
            # V6.46: cantidad_real_u puede venir SUCIO (cajas en lugar de unidades)
            # cuando la OF se aprobo/edito sin u_por_caja en el request. El dato que
            # ingresa el operario y que usa el optimizer es cantidad_real_cj:
            # derivar SIEMPRE de ahi. Auditado 31-07-2026: 22 de 24 OF editadas mal.
            u = float(ap.get("cantidad_real_cj") or 0) * upc
            if _hoy_plan and fer <= _hoy_plan:
                entradas_pend[fer] = entradas_pend.get(fer, 0.0) + float(u or 0)
                _of_pend.append({"numero_of": ap.get("numero_of"),
                                 "fecha_entrada": fer,
                                 "cantidad_cj": float(ap.get("cantidad_real_cj") or 0)})
            else:
                entradas_plan[fer] = entradas_plan.get(fer, 0.0) + float(u or 0)
    except Exception:
        entradas_plan, entradas_pend, _of_pend = {}, {}, []
    entradas_vivas = entradas_plan          # la curva usa la regla del plan

    # Faltante confirmado por BALANCE DE INVENTARIO. Lo calcula cron_plan al generar
    # el plan y queda en snapshot['alertas']; NO se recalcula aca porque exige
    # consultas a SQL Server que tardan minutos (medido el 11-08). Los planes
    # anteriores al 11-08-2026 no traen `faltante_u`: el front debe tolerar su
    # ausencia y simplemente no dibujar la curva punteada.
    _rp = next((a for a in (snap.get("alertas") or [])
                if a.get("tipo") == "RECEPCION_PENDIENTE"
                and str(a.get("sku")) == str(sku)), None)
    # Solo lo NO recibido: sumar la OF completa repetiria el doble conteo, porque la
    # parte ya recibida esta dentro del stock inicial.
    _falt_u = max(0, int(round(float((_rp or {}).get("faltante_u") or 0))))

    # (11-08-2026) Solo se INFORMAN las recepciones RECIENTES.
    # La EXCLUSION de la curva sigue aplicando a TODAS las de `fer <= hoy` (es la
    # regla del plan; si no, la curva volveria a diverger del Mapa). Pero una OF con
    # recepcion de hace tres meses no es una "recepcion pendiente": es un dato viejo
    # en mrp_aprobaciones. Es extremadamente improbable que una recepcion siga
    # pendiente al dia subsiguiente.
    # El 11-08 el aviso listaba una OF del 26-05 junto a la de hoy y parecia que
    # faltaban 1.850 cj cuando lo accionable eran 900.
    # Ventana de 4 dias corridos, no 1: cubre el lunes mirando al viernes.
    _DIAS_RECIENTE = 4
    try:
        from datetime import date as _d, timedelta as _tdd
        _corte = (_d.fromisoformat(_hoy_plan) - _tdd(days=_DIAS_RECIENTE)).isoformat()
    except Exception:
        _corte = ""
    _of_reciente = [o for o in _of_pend if o["fecha_entrada"] >= _corte]
    _pend_reciente_u = sum(
        v for k, v in entradas_pend.items() if k >= _corte)

    # Recalculo del balance hacia adelante.
    # demanda_base[d] se despeja de la base congelada para NO recalcular forecast/OV:
    #   demanda_base = stock_ini_base + oft_base + entrada_base - stock_fin_base
    # El unico cambio es entrada_base -> entrada_viva; todo lo demas identico al optimizer.
    fechas = sorted(detalle.keys())
    plan_viejo_sin_campo = any("entrada_aprobada_u" not in detalle[f] for f in fechas)

    # (30-07) LINEA por dia, para el tooltip de los graficos. Permite ver el
    # traspaso de carga entre lineas: que linea produce y si es preferida o
    # alternativa.
    #   · OFT propuesta   -> se indexa por fecha_lanzamiento (verificado: las claves
    #     de detalle_diario coinciden con fecha_lanzamiento, no con la de entrada).
    #   · OF/OFM aprobada -> por fecha_entrada_real, que es como se grafica la barra
    #     verde (entrada_aprobada_u).
    _pref = {}
    try:
        from db_mrp import get_all_sku_lineas
        for _sl in get_all_sku_lineas():
            _d = _sl if isinstance(_sl, dict) else dict(_sl)
            if str(_d.get("sku")) == sku:
                _pref[str(_d.get("linea"))] = bool(_d.get("preferida"))
    except Exception:
        _pref = {}

    _oft_lin, _apr_lin = {}, {}
    for _o in (snap.get("ofts") or []):
        if str(_o.get("sku", "")) != sku:
            continue
        _lin = str(_o.get("linea") or "")
        _cjs = float(_o.get("cantidad_cajas") or 0)
        if not _lin or _cjs <= 0:
            continue
        _item = {"linea": _lin, "cajas": _cjs,
                 "preferida": _pref.get(_lin),
                 "alternativa": (_pref.get(_lin) is False)}
        if _o.get("aprobada"):
            _k = str(_o.get("fecha_entrada_real") or "")[:10]
            _item["numero_of"] = _o.get("numero_of")
            _item["motivo"] = _o.get("motivo")
            if _k:
                _apr_lin.setdefault(_k, []).append(_item)
        else:
            _k = str(_o.get("fecha_lanzamiento") or "")[:10]
            if _k:
                _oft_lin.setdefault(_k, []).append(_item)

    dias = []
    stock_prev = None
    for fecha_iso in fechas:
        c = detalle[fecha_iso]
        oc = c.get("oft_cajas")
        oft_u = int(oc) * upc if oc else 0
        entrada_base = int(c.get("entrada_aprobada_u", 0) or 0)
        stock_ini_base = int(c.get("stock_ini_disp_u", 0) or 0)
        stock_fin_base = int(c.get("stock_fin_u", 0) or 0)
        demanda_base = stock_ini_base + oft_u + entrada_base - stock_fin_base
        entrada_viva = int(round(entradas_vivas.get(fecha_iso, 0.0)))
        stock_ini = stock_ini_base if stock_prev is None else stock_prev
        stock_fin = stock_ini + oft_u + entrada_viva - demanda_base
        # (03-08) quiebre intradia: la demanda del dia se sirve con el stock al
        # inicio (stock_ini); la produccion/entrada del dia entra al cierre.
        stock_disp = stock_ini - demanda_base
        ss_u = int(c.get("ss_u", 0) or 0)
        if stock_disp < 0:
            estado = "QUIEBRE"
        elif ss_u > 0 and stock_fin < ss_u:
            estado = "BAJO_SS"
        else:
            estado = "OK"
        dias.append({
            "fecha": fecha_iso,
            "oft_cajas": c.get("oft_cajas"),
            "stock_ini_disp_u": int(round(stock_ini)),
            "stock_ini_disp_cj": _cj(int(round(stock_ini))),
            "stock_disp_u": int(round(stock_disp)),
            "stock_disp_cj": _cj(int(round(stock_disp))),
            "pedidos_u": c.get("pedidos_u"),
            "pedidos_cj": _cj(c.get("pedidos_u")),
            "pedidos_crudos_u": c.get("pedidos_crudos_u"),
            "pedidos_crudos_cj": _cj(c.get("pedidos_crudos_u")),
            "demanda_corr_u": c.get("demanda_corr_u"),
            "demanda_corr_cj": _cj(c.get("demanda_corr_u")),
            "forecast_u": c.get("forecast_u"),
            "forecast_cj": _cj(c.get("forecast_u")),
            "stock_fin_u": int(stock_fin),
            "stock_fin_cj": _cj(int(stock_fin)),
            "ss_u": c.get("ss_u"),
            "ss_cj": _cj(c.get("ss_u")),
            "entrada_aprobada_u": entrada_viva,
            # (11-08-2026) Entrada que el plan NO cuenta (recepcion de hoy o pasada).
            # El monto a DIBUJAR como pendiente es el FALTANTE de
            # `recepcion_pendiente`, no esto: parte de esta cantidad ya puede estar
            # dentro del stock inicial.
            "entrada_pendiente_u": int(round(entradas_pend.get(fecha_iso, 0.0))),
            "estado": estado,
            # lineas de produccion del dia (para el tooltip de los graficos)
            "oft_lineas": _oft_lin.get(fecha_iso, []),
            "aprob_lineas": _apr_lin.get(fecha_iso, []),
        })
        stock_prev = stock_fin

    # encabezado: valores del snapshot (fisico/comprometido/disponible no cambian);
    # stock_final y stock_min recalculados desde la serie live para consistencia con la curva.
    _sf_live = [d["stock_fin_u"] for d in dias] if dias else [0]
    encabezado = {
        "stock_fisico_u": encab.get("stock_fisico_u"),
        "stock_fisico_cj": _cj(encab.get("stock_fisico_u")),
        "comprometido_u": encab.get("comprometido_u"),
        "comprometido_cj": _cj(encab.get("comprometido_u")),
        "disponible_inicial_u": encab.get("disponible_inicial_u"),
        "disponible_inicial_cj": _cj(encab.get("disponible_inicial_u")),
        "stock_final_u": int(_sf_live[-1]),
        "stock_final_cj": _cj(int(_sf_live[-1])),
        "stock_min_u": int(min(_sf_live)),
        "stock_min_cj": _cj(int(min(_sf_live))),
        "ss_dias": encab.get("ss_dias"),
    }

    # (28-07) Apertura del stock inicial por empresa (Traverso / Montaner).
    # El desglose sale del parquet de stock (columna `empresa`, agregada el 27-07 al
    # consolidar ambas BD); el snapshot del plan sólo guarda el total. En condiciones
    # normales coinciden, porque el plan se genera del mismo parquet en el paso 1/8.
    # Si alguien refresca el stock después de generar el plan pueden diverger: por eso
    # se devuelve también `total_parquet_u` y el flag `cuadra`, para que la vista pueda
    # advertirlo en vez de mostrar una apertura que no suma.
    empresa_u = {}
    total_parquet_u = None
    try:
        import stock as _stk
        _df = _stk.load_stock_parquet()
        if not _df.empty and "empresa" in _df.columns:
            _s = _df[_df["sku"].astype(str).str.strip() == str(sku).strip()]
            if not _s.empty:
                _g = _s.groupby("empresa")["stock_unidades"].sum()
                # el parquet está en CAJAS (UMED=CJ); el encabezado en unidades
                empresa_u = {str(k): int(round(float(v) * upc)) for k, v in _g.items()}
                total_parquet_u = int(round(float(_s["stock_unidades"].sum()) * upc))
    except Exception as _e_emp:
        logger.warning(f"apertura por empresa no disponible para {sku}: {_e_emp}")

    _fis = encab.get("stock_fisico_u")
    encabezado["por_empresa"] = {
        "T": empresa_u.get("T", 0),
        "M": empresa_u.get("M", 0),
        "T_cj": _cj(empresa_u.get("T", 0)),
        "M_cj": _cj(empresa_u.get("M", 0)),
        "total_parquet_u": total_parquet_u,
        "total_parquet_cj": _cj(total_parquet_u),
        # tolerancia de 1 caja por redondeos de la conversión u <-> cj
        "cuadra": (total_parquet_u is not None and _fis is not None
                   and abs(total_parquet_u - int(_fis)) <= upc),
    }

    return {
        "disponible": True,
        "live": True,
        "plan_viejo_sin_entrada": plan_viejo_sin_campo,
        "sku": sku,
        "upc": upc,
        "ss_dias": encab.get("ss_dias"),
        "plan_id": row["id"],
        "fecha_inicio": row["created_at"].date().isoformat() if row["created_at"] else None,
        "horizonte_dias": int(row["horizonte_sem"] or 4) * 7,
        "encabezado": encabezado,
        "dias": dias,
        # (11-08-2026) Lo que el plan NO cuenta, informado aparte en vez de mezclado
        # en la curva. `faltante_u` es el unico monto seguro de sumar: sale del
        # balance de inventario, no de la cantidad de la OF.
        "recepcion_pendiente": {
            # `hay` y `ofs` = solo las recientes: son las accionables y las unicas que
            # el aviso debe mostrar. Las viejas se cuentan aparte.
            "hay": bool(_of_reciente),
            "entradas_excluidas_u": int(round(_pend_reciente_u)),
            "entradas_excluidas_cj": _cj(int(round(_pend_reciente_u))),
            "ofs": _of_reciente,
            "n_ofs_antiguas": len(_of_pend) - len(_of_reciente),
            "stock_plan_cj": encabezado.get("stock_fisico_cj"),
            "fecha_plan": _hoy_plan,
            "faltante_u": _falt_u,
            "faltante_cj": _cj(_falt_u) if _falt_u else 0.0,
            "confirmado": bool(_rp),   # False = plan viejo, sin balance de inventario
            "grado": (_rp or {}).get("grado"),
            "pct_recibido": (_rp or {}).get("pct_recibido"),
            "mensaje": (_rp or {}).get("mensaje"),
        },
    }


@app.get("/plan/params", tags=["Plan de Produccion"])
def get_mrp_params():
    """Lista los SKUs con parámetros MRP cargados desde PostgreSQL (fallback Excel)."""
    import importlib, mrp as _mrp_params
    try:
        try:
            sku_params, lineas, _sku_lineas = _mrp_params.load_params_from_db()
            if not sku_params:
                raise ValueError("BD vacía")
        except Exception as _e2:
            logger.warning(f"Fallback Excel /plan/params: {_e2}")
            sku_params, lineas, _sku_lineas = _mrp_params.load_params_from_excel(MRP_EXCEL_PATH)
        # factor_velocidad vive en sku_lineas (par SKU-linea). Para /plan/params
        # exponemos el factor de la LINEA PREFERIDA de cada SKU (el que aplica en
        # el grid de Detalle, que agrupa por linea preferida). Default 1.0.
        _factor_pref = {}
        for _sl in (_sku_lineas or []):
            # nos quedamos con el de la linea preferida; si no hay preferida marcada,
            # el primero que aparezca sirve de fallback.
            if getattr(_sl, "preferida", False) or _sl.sku not in _factor_pref:
                _factor_pref[_sl.sku] = float(getattr(_sl, "factor_velocidad", 1.0) or 1.0)
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
                    "batch_mult_u": p.multiplo_batch,
                    "cap_bodega_u": p.cap_bodega,
                    "t_cambio_hrs": getattr(p, 't_cambio_hrs', 0),
                    "pct_dia_max": getattr(p, 'pct_dia_max', 1.0),
                    "u_por_caja": p.unidades_por_caja,
                    "linea_preferida": p.linea_preferida,
                    "factor_velocidad": _factor_pref.get(p.sku, 1.0),
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




# ─────────────────────────────────────────────────────────────────────────────
# Endpoint: GET /plan/quiebres_grid  —  Mapa de Quiebres y Riesgo (SKU x semana)
#
# PARA REVISION. Pegar dentro de main.py, junto al resto de endpoints
# "@app.get('/plan/...')". Es un LECTOR PURO: no recalcula stock, toma
# stock_fin_u / ss_u / estado ya persistidos en detalle_diario del snapshot
# vigente. Agrupa por linea_preferida (campo de params, igual que el grid de
# Detalle). Marca los SKU con RECEPCION_PENDIENTE (quiebre de primeros dias
# puede ser falso).
#
# Severidad por dia:
#   estado OK                                   -> 0  (no entra al mapa)
#   estado BAJO_SS y stock_fin_u  > 10% de SS   -> 1  (bajo SS)
#   estado BAJO_SS y stock_fin_u <= 10% de SS   -> 2  (riesgo)
#   estado QUIEBRE (stock_fin_u < 0)            -> 3  (quiebre; nº = cajas faltantes)
#
# OJO bucket de semana: se usa semana_viz_inicio (DOMINGO-sabado), la MISMA
# convencion de visualizacion que DetalleProduccion y el resto del dashboard.
# NO semana_iso_inicio (ese arranca LUNES, alineado a Prophet/evento_qbr): si se
# usara, las columnas del heatmap no cuadrarian con lo que el usuario ya ve.
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/plan/quiebres_grid", tags=["Plan de Produccion"])
def get_quiebres_grid():
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal
    from datetime import date as _date, timedelta as _td
    import math
    import mrp as _mrp_params

    # 1) snapshot vigente
    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT id, horizonte_sem, created_at, snapshot "
            "FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {"disponible": False,
                "mensaje": "No hay plan vigente. El cron aun no genero uno, o ninguno paso el gate."}

    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        import json as _json
        snap = _json.loads(snap)

    dd = snap.get("detalle_diario") or {}
    encab_all = snap.get("encabezado_sku") or {}
    alertas = snap.get("alertas") or []

    # SKU con recepcion pendiente (marca "posible falso" en los primeros dias).
    # (11-08-2026) Se guarda tambien la alerta COMPLETA: "recepcion pendiente" a secas
    # no dice si faltan 20 cajas o 900, y esa magnitud es lo que permite decidir si
    # aprobar el OFT que el plan genero para cubrir el quiebre. Los planes anteriores
    # a esta fecha no traen faltante_cj y el front degrada al texto de siempre.
    rp_info = {str(a.get("sku")): a for a in alertas
               if a.get("tipo") == "RECEPCION_PENDIENTE" and a.get("sku")}
    rp_skus = set(rp_info)

    # 2) params: linea_preferida (agrupacion) + descripcion / upc de respaldo
    try:
        sku_params, lineas, _ = _mrp_params.load_params_from_db()
        if not sku_params:
            raise ValueError("BD vacia")
    except Exception as _e:
        logger.warning(f"quiebres_grid: fallback Excel params: {_e}")
        sku_params, lineas, _ = _mrp_params.load_params_from_excel(MRP_EXCEL_PATH)
    linea_nombre = {l.codigo: l.nombre for l in lineas.values()}

    # 3) helper de semana de VISUALIZACION (domingo-sabado) = semana_viz_inicio,
    #    la misma que usa DetalleProduccion. El fallback replica su formula exacta.
    try:
        from calendario import semana_viz_inicio as _sem_ini
    except Exception:
        def _sem_ini(d):
            return d - _td(days=(d.weekday() + 1) % 7)          # domingo (= semana_viz)

    NIVELES = ("OK", "BAJO_SS", "RIESGO", "QUIEBRE")

    def _sev(estado, stock_fin_u, ss_u):
        if estado == "QUIEBRE":
            return 3
        if estado == "BAJO_SS":
            if ss_u and ss_u > 0 and stock_fin_u is not None and stock_fin_u <= 0.10 * ss_u:
                return 2
            return 1
        return 0

    # 4) recorrer SKU con >= 1 dia en problema
    semanas_set = {}
    lineas_map = {}

    for sku, serie in dd.items():
        peor = 0
        dias = {}
        for fecha_iso, c in serie.items():
            sev = _sev(c.get("estado"), c.get("stock_fin_u"), c.get("ss_u"))
            dias[fecha_iso] = {"sev": sev,
                               "stock_fin_u": c.get("stock_fin_u"),
                               "stock_disp_u": c.get("stock_disp_u"),
                               "ss_u": c.get("ss_u")}
            if sev > peor:
                peor = sev
        if peor == 0:
            continue  # sin problema -> fuera del mapa

        p = sku_params.get(sku)
        upc = int((getattr(p, "unidades_por_caja", None) or
                   (encab_all.get(sku) or {}).get("u_por_caja") or 1))
        desc = (getattr(p, "descripcion", None) or
                (encab_all.get(sku) or {}).get("descripcion") or "")
        cod_linea = getattr(p, "linea_preferida", None) or "SIN_LINEA"

        # cajas faltantes por dia en quiebre (magnitud = nadir intradia stock_disp_u;
        # fallback a stock_fin_u para snapshots viejos sin el campo)
        for _f, dc in dias.items():
            _base = dc.get("stock_disp_u")
            if _base is None:
                _base = dc.get("stock_fin_u")
            if dc["sev"] == 3 and _base is not None and upc:
                dc["def_cj"] = int(math.ceil(abs(_base) / upc))
            else:
                dc["def_cj"] = 0

        # agregacion por semana viz: peor severidad + nº dias en ese estado + max def
        semanas_sku = {}
        for fecha_iso, dc in dias.items():
            wk = _sem_ini(_date.fromisoformat(fecha_iso)).isoformat()
            semanas_set[wk] = True
            w = semanas_sku.setdefault(wk, {"sev": 0, "dias": 0, "def_cj": 0})
            if dc["sev"] > w["sev"]:
                w["sev"] = dc["sev"]
                w["dias"] = 0
            if dc["sev"] == w["sev"] and dc["sev"] > 0:
                w["dias"] += 1
            if dc["def_cj"] > w["def_cj"]:
                w["def_cj"] = dc["def_cj"]

        item = {
            "sku": sku,
            "descripcion": desc,
            "upc": upc,
            "linea_preferida": cod_linea,
            "recepcion_pendiente": sku in rp_skus,
            "recepcion_info": ({
                "faltante_cj": (rp_info[str(sku)] or {}).get("faltante_cj"),
                "of_cj": (rp_info[str(sku)] or {}).get("of_cj"),
                "grado": (rp_info[str(sku)] or {}).get("grado"),
                "pct_recibido": (rp_info[str(sku)] or {}).get("pct_recibido"),
                "numero_of": (rp_info[str(sku)] or {}).get("numero_of"),
                "mensaje": (rp_info[str(sku)] or {}).get("mensaje"),
            } if str(sku) in rp_info else None),
            "peor_sev": peor,
            "peor_nivel": NIVELES[peor],
            "semanas": semanas_sku,   # keyed por semana iso
            "dias": dias,             # keyed por fecha iso (drill-down)
        }
        grp = lineas_map.setdefault(cod_linea, {
            "codigo": cod_linea,
            "nombre": linea_nombre.get(cod_linea, cod_linea),
            "skus": [],
        })
        grp["skus"].append(item)

    # 5) semanas ordenadas + label "dd mmm"
    _MESES = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]
    semanas = []
    for wk in sorted(semanas_set.keys()):
        d = _date.fromisoformat(wk)
        semanas.append({"iso": wk, "label": f"{d.day:02d} {_MESES[d.month - 1]}"})

    # 6) resumen por linea + orden (mas quiebres primero; dentro, peor_sev desc)
    lineas_out = []
    for _cod, grp in lineas_map.items():
        grp["skus"].sort(key=lambda x: (-x["peor_sev"], x["sku"]))
        res = {"n_skus": len(grp["skus"]), "n_quiebre": 0, "n_riesgo": 0, "n_bajo_ss": 0}
        for it in grp["skus"]:
            if it["peor_sev"] == 3:
                res["n_quiebre"] += 1
            elif it["peor_sev"] == 2:
                res["n_riesgo"] += 1
            elif it["peor_sev"] == 1:
                res["n_bajo_ss"] += 1
        grp["resumen"] = res
        lineas_out.append(grp)
    lineas_out.sort(key=lambda g: (-g["resumen"]["n_quiebre"],
                                   -g["resumen"]["n_riesgo"], g["codigo"]))

    return {
        "disponible": True,
        "plan_id": row["id"],
        "fecha_inicio": row["created_at"].date().isoformat() if row["created_at"] else None,
        "horizonte_dias": int(row["horizonte_sem"] or 8) * 7,
        "semanas": semanas,
        "lineas": lineas_out,
    }

@app.get("/plan/stock_sku", tags=["Plan de Produccion"])
def get_stock_sku():
    """Stock inicial y SS por SKU del plan vigente, en CAJAS. Payload liviano.

    Para la tabla de Detalle Produccion: las OF aprobadas entran al plan como
    entradas_fijas y el optimizer NO las re-emite como OFT, por lo que el objeto
    que el frontend inyecta no trae stock_inicial_cajas ni ss_cajas y la tabla
    mostraba "Stock ini. 0" y "Cobertura —" en todas las aprobadas (31-07-2026).

    Semantica verificada 31-07-2026: stock_inicial_cajas de las OFT coincide
    exactamente con disponible_inicial_u/u_por_caja del encabezado (8/8 SKU).
    ss_cajas se toma del PRIMER dia de detalle_diario (ss_u varia por dia).
    """
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal
    import json as _json

    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT id, snapshot FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {"disponible": False, "skus": {}}

    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        snap = _json.loads(snap)
    enc = snap.get("encabezado_sku") or {}
    dd = snap.get("detalle_diario") or {}

    out = {}
    for sku, e in enc.items():
        try:
            upc = float(e.get("u_por_caja") or 1) or 1.0
            di = e.get("disponible_inicial_u")
            stock_cj = round(float(di) / upc, 1) if di is not None else None
            ss_cj = None
            serie = dd.get(sku)
            if serie:
                f0 = min(serie.keys())
                ssu = (serie.get(f0) or {}).get("ss_u")
                if ssu is not None:
                    ss_cj = round(float(ssu) / upc, 1)
            out[str(sku)] = {
                "stock_inicial_cajas": stock_cj,
                "ss_cajas": ss_cj,
                "ss_dias": e.get("ss_dias"),
            }
        except Exception:
            continue

    return {"disponible": True, "plan_id": row["id"], "skus": out}


# ── Endpoints: Parámetros MRP (CRUD desde BD) ────────────────────────────────

@app.get("/params/lineas")
def get_lineas():
    """Lista todas las líneas de producción desde PostgreSQL."""
    try:
        return get_all_lineas()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/params/lineas/{codigo}")
def put_linea(codigo: str, campos: dict):
    """Actualiza parámetros de una línea de producción."""
    try:
        return update_linea(codigo, campos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/params/skus")
def get_sku_params_endpoint():
    """Lista todos los parámetros de SKU desde PostgreSQL."""
    try:
        return get_all_sku_params()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/params/skus/{sku}")
def put_sku_params(sku: str, campos: dict):
    """Actualiza parámetros de un SKU específico."""
    try:
        return update_sku_param(sku, campos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/params/importar-excel")
def importar_excel_a_bd():
    """Re-importa parámetros desde el Excel a PostgreSQL (sobrescribe la BD)."""
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "/app/migrate_params.py", MRP_EXCEL_PATH],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr)
        return {"ok": True, "output": result.stdout[-500:]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes", tags=["Faltantes"])
def get_faltantes(fecha: str):
    """Detalle de faltantes por quiebre de un día (YYYY-MM-DD): filas por SKU y
    cliente. Solo lectura de mrp_faltantes (materializado por el cron)."""
    try:
        from db_mrp import get_faltantes_por_fecha
        return {"fecha": fecha, "filas": get_faltantes_por_fecha(fecha)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes/rango", tags=["Faltantes"])
def get_faltantes_rango_endpoint():
    """Rango de fechas disponibles (min/max) para inicializar el selector."""
    try:
        from db_mrp import get_faltantes_rango
        return get_faltantes_rango()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes/evolutivo", tags=["Faltantes"])
def get_faltantes_evolutivo_endpoint(desde: str | None = None, hasta: str | None = None,
                                     sku: str | None = None, cliente: str | None = None):
    """Serie diaria de faltante total (cajas) en [desde, hasta], filtrable por SKU
    y/o cliente. Para el gráfico evolutivo del dashboard."""
    try:
        from db_mrp import get_faltantes_evolutivo
        serie = get_faltantes_evolutivo(sku=sku, cod_cliente=cliente, desde=desde, hasta=hasta)
        # normalizar fecha a str y faltante a float
        out = [{"fecha": (r["fecha"].isoformat() if hasattr(r["fecha"], "isoformat") else str(r["fecha"])),
                "faltante_cj": float(r["faltante_cj"] or 0)} for r in serie]
        return {"desde": desde, "hasta": hasta, "sku": sku, "cliente": cliente, "serie": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes/excel", tags=["Faltantes"])
def get_faltantes_excel(fecha: str):
    """Genera y descarga el Informe de Quiebres de Stock (xlsx) de un día
    (YYYY-MM-DD): pestaña resumen por SKU + pestaña detalle por cliente."""
    try:
        from db_mrp import get_faltantes_por_fecha, get_explicaciones_faltantes
        import faltantes_excel
        filas = get_faltantes_por_fecha(fecha)
        explic = get_explicaciones_faltantes(fecha)
        contenido = faltantes_excel.generar_bytes(fecha, filas, explic, con_explicaciones=True)
        nombre = f"Informe_Quiebres_{fecha}.xlsx"
        return Response(
            content=contenido,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes/explicaciones", tags=["Faltantes"])
def get_explicaciones_endpoint(fecha: str):
    """Explicaciones cargadas para los faltantes de un día (YYYY-MM-DD).
    Devuelve {sku: {explicacion, autor, congelada, updated_at}}."""
    try:
        from db_mrp import get_explicaciones_faltantes
        return {"fecha": fecha, "explicaciones": get_explicaciones_faltantes(fecha)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExplicacionFaltante(BaseModel):
    sku: str
    fecha: str
    explicacion: str
    autor: str | None = ""


@app.post("/faltantes/explicaciones", tags=["Faltantes"])
def post_explicacion_endpoint(payload: ExplicacionFaltante):
    """Guarda/actualiza la explicacion de un (sku, fecha). Rechaza (409) si la
    explicacion ya fue congelada por el envio del correo final."""
    try:
        from db_mrp import upsert_explicacion_faltante
        res = upsert_explicacion_faltante(
            payload.sku, payload.fecha, payload.explicacion, payload.autor or "")
        if not res.get("ok"):
            raise HTTPException(
                status_code=409,
                detail="La explicacion ya fue enviada y no puede editarse.")
        return {"ok": True, "sku": payload.sku, "fecha": payload.fecha}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Faltantes V2 — Solución propuesta + Fecha de reposición (desactivable)
# Flag: FALTANTES_V2_ENABLED (default 0). Con el flag OFF, los GET devuelven
# {"enabled": False} y los POST responden 403; el endpoint /faltantes histórico
# NO se toca (Opción 1: endpoints separados, el frontend cruza por SKU).
# ─────────────────────────────────────────────────────────────────────────────

def _faltantes_v2_on() -> bool:
    """True si el feature Faltantes V2 está activado por entorno."""
    import os
    return os.environ.get("FALTANTES_V2_ENABLED", "0") in ("1", "true", "True", "yes")


@app.get("/faltantes/v2/estado", tags=["Faltantes"])
def get_faltantes_v2_estado():
    """Indica si el feature Faltantes V2 está activo (para que el frontend decida
    si mostrar las columnas nuevas)."""
    return {"enabled": _faltantes_v2_on()}


@app.get("/faltantes/soluciones", tags=["Faltantes"])
def get_soluciones_endpoint(fecha: str):
    """Soluciones propuestas cargadas para los faltantes de un día (YYYY-MM-DD).
    Devuelve {sku: {solucion, solucion_autor, congelada}}. Gemelo del GET de
    explicaciones. Si el feature está OFF, devuelve enabled=False y dict vacío."""
    if not _faltantes_v2_on():
        return {"enabled": False, "fecha": fecha, "soluciones": {}}
    try:
        from db_mrp import get_soluciones_faltantes
        return {"enabled": True, "fecha": fecha,
                "soluciones": get_soluciones_faltantes(fecha)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SolucionFaltante(BaseModel):
    sku: str
    fecha: str
    solucion: str
    autor: str | None = ""


@app.post("/faltantes/solucion", tags=["Faltantes"])
def post_solucion_endpoint(payload: SolucionFaltante):
    """Guarda/actualiza la SOLUCIÓN propuesta de un (sku, fecha). Rechaza (409) si
    la fila ya fue congelada por el envío del correo final (mismo flag que la
    explicación). Requiere FALTANTES_V2_ENABLED."""
    if not _faltantes_v2_on():
        raise HTTPException(status_code=403, detail="Feature Faltantes V2 desactivado.")
    try:
        from db_mrp import upsert_solucion_faltante
        res = upsert_solucion_faltante(
            payload.sku, payload.fecha, payload.solucion, payload.autor or "")
        if not res.get("ok"):
            raise HTTPException(
                status_code=409,
                detail="La solución ya fue enviada y no puede editarse.")
        return {"ok": True, "sku": payload.sku, "fecha": payload.fecha}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faltantes/reposicion", tags=["Faltantes"])
def get_reposicion_endpoint(fecha: str):
    """Mapa de fecha de reposición EN VIVO para el día del informe (YYYY-MM-DD).
    `fecha` es el umbral de 'futuro' (inclusive): una OF que entra ese mismo día
    repone. Devuelve {sku: {tipo, valor}} con tipo ∈ auto|inactivo|sin_of|manual.

    El frontend cruza por SKU. Para un SKU no productivo sin fecha manual cargada,
    el SKU NO viene en el map -> el frontend asume {tipo:'manual', valor:None}
    (Opción 1, validada con dato el 25-08). Si el feature está OFF, map vacío."""
    if not _faltantes_v2_on():
        return {"enabled": False, "fecha": fecha, "reposicion": {}}
    try:
        from db_mrp import get_fecha_reposicion_map
        return {"enabled": True, "fecha": fecha,
                "reposicion": get_fecha_reposicion_map(fecha)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RepoManualFaltante(BaseModel):
    sku: str
    fecha: str
    fecha_reposicion: str | None = None   # 'YYYY-MM-DD' o None para borrar
    autor: str | None = ""


@app.post("/faltantes/repo_manual", tags=["Faltantes"])
def post_repo_manual_endpoint(payload: RepoManualFaltante):
    """Guarda la fecha de reposición MANUAL de un SKU no productivo
    (importado/maquila). Editable siempre (NO se congela). Requiere
    FALTANTES_V2_ENABLED."""
    if not _faltantes_v2_on():
        raise HTTPException(status_code=403, detail="Feature Faltantes V2 desactivado.")
    try:
        from db_mrp import upsert_repo_manual
        res = upsert_repo_manual(
            payload.sku, payload.fecha, payload.fecha_reposicion, payload.autor or "")
        return {"ok": bool(res.get("ok")), "sku": payload.sku, "fecha": payload.fecha}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Conciliación OF/TR (Fase 2) — lectura de mrp_of_sap. NO toca el solver.
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/of/cumplimiento", tags=["Conciliacion OF"])
def get_of_cumplimiento(solo_pt: bool = False):
    """Cumplimiento a nivel OF: producido vs planificado, estado (completa/corta/
    sobre/pendiente), ratio y ventana de recibos. solo_pt=True excluye granel (9x).
    Lectura pura de mrp_of_sap (materializado por cron_of_sap.py)."""
    try:
        from db_mrp import get_of_sap_cumplimiento
        filas = get_of_sap_cumplimiento(solo_pt=solo_pt)
        # resumen para los KPIs (evita reccontar en el frontend)
        resumen = {"completa": 0, "corta": 0, "sobre": 0, "pendiente": 0}
        for r in filas:
            resumen[r["estado"]] = resumen.get(r["estado"], 0) + 1
        return {"solo_pt": solo_pt, "total": len(filas),
                "resumen": resumen, "filas": filas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/recepcion/{orden}", tags=["Conciliacion OF"])
def get_of_recepcion(orden: str):
    """Serie de recepción diaria de una OF (drill-down de parciales en el tiempo)."""
    try:
        from db_mrp import get_of_sap_recepcion_diaria
        return {"orden": orden, "serie": get_of_sap_recepcion_diaria(orden)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/tendencia", tags=["Conciliacion OF"])
def get_of_tendencia(solo_pt: bool = False):
    """Fill-rate mensual (por mes de fecha inicio planificada) para el gráfico de
    tendencia. Devuelve conteos por estado y el % de completas sobre OF cerradas."""
    try:
        from db_mrp import get_of_sap_tendencia_mensual
        return {"solo_pt": solo_pt, "serie": get_of_sap_tendencia_mensual(solo_pt=solo_pt)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/adopcion", tags=["Conciliacion OF"])
def get_of_adopcion(desde: str | None = None, hasta: str | None = None,
                    linea: str | None = None, categoria: str | None = None,
                    sku: str | None = None):
    """KPI de ADOPCIÓN: cobertura semanal de SKU planificados por el sistema sobre
    los SKU de PT que la planta produjo (SAP). Match por SKU en la misma semana
    (no por fecha, ver DISENO §10.1). Devuelve serie semanal (la curva del
    nacimiento), agregado por línea inferida, y el contexto de OF fuera del sistema.
    Filtros opcionales: intervalo de fechas, línea, categoría, SKU."""
    try:
        from db_mrp import get_of_sap_adopcion
        return get_of_sap_adopcion(desde=desde, hasta=hasta, linea=linea,
                                   categoria=categoria, sku=sku)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/filtros", tags=["Conciliacion OF"])
def get_of_filtros():
    """Opciones para los selectores del tablero: categorías, líneas y rango de fechas
    disponible en mrp_of_sap. Read-only."""
    try:
        from db_mrp import SessionLocal
        from sqlalchemy import text as _t
        with SessionLocal() as s:
            cats = [r[0] for r in s.execute(_t(
                "SELECT DISTINCT categoria FROM mrp_sku_params "
                "WHERE categoria IS NOT NULL AND categoria <> '' ORDER BY 1")).all()]
            lins = [r[0] for r in s.execute(_t(
                "SELECT DISTINCT linea_preferida FROM mrp_sku_params "
                "WHERE linea_preferida IS NOT NULL AND linea_preferida <> '' ORDER BY 1")).all()]
            rango = s.execute(_t(
                "SELECT MIN(fecha_ini_planif), MAX(fecha_ini_planif) FROM mrp_of_sap "
                "WHERE fecha_ini_planif IS NOT NULL")).first()
        return {
            "categorias": cats,
            "lineas": lins,
            "min_fecha": rango[0].isoformat() if rango and rango[0] else None,
            "max_fecha": rango[1].isoformat() if rango and rango[1] else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/cumplimiento_sku", tags=["Conciliacion OF"])
def get_of_cumplimiento_sku_ep(periodo: str = "semana",
                               desde: str | None = None, hasta: str | None = None,
                               linea: str | None = None, categoria: str | None = None,
                               sku: str | None = None):
    """Cumplimiento por SKU (Solicitado vs Producido, sin topear), estilo reporte de
    Producción. periodo='dia' (fecha única o TR) o 'semana' (centro del tramo)."""
    try:
        from db_mrp import get_of_cumplimiento_sku
        return get_of_cumplimiento_sku(periodo=periodo, desde=desde, hasta=hasta,
                                       linea=linea, categoria=categoria, sku=sku)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/of/cumplimiento_evolutivo", tags=["Conciliacion OF"])
def get_of_cumplimiento_evolutivo_ep(linea: str | None = None, categoria: str | None = None):
    """Cumplimiento global por semana (centro del tramo) para el gráfico evolutivo."""
    try:
        from db_mrp import get_of_cumplimiento_evolutivo
        return {"serie": get_of_cumplimiento_evolutivo(linea=linea, categoria=categoria)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Diagnóstico de parámetros MRP (línea / SKU) — read-only (Fase 1)
# ─────────────────────────────────────────────────────────────────────────────

def _forecast_semanal_cj_desde_plan(n_semanas: int = 4) -> dict:
    """Demanda SEMANAL estimada por SKU (cajas/semana), leída del plan vigente.
    Promedia las próximas n semanas COMPLETAS (descarta semana_parcial).
    El valor diario se deriva aguas abajo dividiendo por los días hábiles.
    Si no hay plan vigente devuelve {}."""
    from sqlalchemy import text as _sql
    from db_mrp import SessionLocal
    with SessionLocal() as s:
        row = s.execute(_sql(
            "SELECT snapshot FROM mrp_planes WHERE vigente LIMIT 1"
        )).mappings().first()
    if row is None:
        return {}
    snap = row["snapshot"] or {}
    proy = ((snap.get("vista_dashboard") or {}).get("proyeccion_por_sku")) or {}
    out = {}
    for sku, d in proy.items():
        sem = [w for w in (d.get("semanas") or []) if not w.get("semana_parcial")]
        sem = sem[:n_semanas]
        if not sem:
            continue
        try:
            prom_cj = sum(float(w.get("ventas_cj") or 0) for w in sem) / len(sem)
        except (TypeError, ValueError):
            continue
        out[str(sku).strip()] = prom_cj          # cj/semana
    return out


@app.get("/params/diagnostico", tags=["Parametros"])
def get_params_diagnostico():
    """Árbol línea -> SKU con capacidades, indicadores derivados y semáforos.
    Solo lectura: no modifica ningún parámetro."""
    try:
        from db_mrp import get_all_lineas, get_all_sku_params, get_all_sku_lineas
        import params_diagnostico as _pdiag
        # el forecast es opcional: si no hay plan vigente o falla la lectura, el
        # diagnóstico igual sirve (pierde solo los indicadores de cobertura).
        try:
            fc = _forecast_semanal_cj_desde_plan()
        except Exception:
            fc = {}
        # SKU que existen pero están inactivos: conservan asignación de línea y no
        # deben reportarse como error de integridad.
        try:
            from sqlalchemy import text as _sql2
            from db_mrp import SessionLocal
            with SessionLocal() as s:
                inactivos = {str(r[0]).strip() for r in s.execute(_sql2(
                    "SELECT sku FROM mrp_sku_params WHERE activo = FALSE")).fetchall()}
        except Exception:
            inactivos = set()
        return _pdiag.construir_diagnostico(
            lineas=get_all_lineas(),
            sku_params=get_all_sku_params(),
            sku_lineas=get_all_sku_lineas(),
            forecast_semanal_cj=fc,
            skus_inactivos=inactivos,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


class SimulacionParams(BaseModel):
    sku: str
    linea: str
    params_producto: dict | None = None   # overrides: batch_min_u, batch_mult_u, ...
    params_en_linea: dict | None = None   # overrides: factor_velocidad, t_cambio_hrs
    params_linea: dict | None = None      # overrides: turnos_dia, horas_turno, ...
    actor: str | None = ""                # reservado para cuando exista SSO


@app.post("/params/diagnostico/simular", tags=["Parametros"])
def post_params_simular(payload: SimulacionParams):
    """Recalcula los indicadores de un (SKU, línea) con parámetros PROPUESTOS.
    NO escribe nada en la base: es un 'qué pasaría si'."""
    try:
        from db_mrp import get_all_lineas, get_all_sku_params, get_all_sku_lineas
        import params_diagnostico as _pdiag

        lin = next((l for l in get_all_lineas()
                    if str(l.get("codigo")).strip() == payload.linea.strip()), None)
        if lin is None:
            raise HTTPException(status_code=404, detail=f"Línea no encontrada: {payload.linea}")
        prod = next((p for p in get_all_sku_params()
                     if str(p.get("sku")).strip() == payload.sku.strip()), None)
        if prod is None:
            raise HTTPException(status_code=404, detail=f"SKU no encontrado: {payload.sku}")
        par = next((x for x in get_all_sku_lineas()
                    if str(x.get("sku")).strip() == payload.sku.strip()
                    and str(x.get("linea")).strip() == payload.linea.strip()), {})

        lin_prop  = {**lin,  **(payload.params_linea or {})}
        prod_prop = {**prod, **(payload.params_producto or {})}
        par_prop  = {**par,  **(payload.params_en_linea or {})}

        der_l = _pdiag.derivados_linea(lin_prop)
        fc = _forecast_semanal_cj_desde_plan().get(payload.sku.strip())

        actual = _pdiag.diagnosticar_sku(prod, _pdiag.derivados_linea(lin), par, fc)
        propuesto = _pdiag.diagnosticar_sku(prod_prop, der_l, par_prop, fc)
        return {
            "sku": payload.sku, "linea": payload.linea,
            "derivados_linea": der_l,
            "actual": actual,
            "propuesto": propuesto,
            "guardado": False,   # Fase 1: simulación pura, nunca escribe
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/regressors", tags=["Estacionalidad"])
def get_regressors():
    """Retorna todos los regressores de estacionalidad definidos por categoría."""
    from seasonality import get_all_regressors_summary
    return get_all_regressors_summary()
