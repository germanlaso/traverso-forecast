"""
stock.py — Módulo de stock real Traverso S.A.

Fuente:  SQL Server · tabla Stock_Lote_Fecha
Lógica:  FEFO (First Expired First Out)
         - Stock vencido excluido del disponible → alerta con cajas dejadas fuera
         - Pregunta al Jefe de Producción qué bodegas usar → configurable via env
Persist: forecast/data/stock_actual.csv  (refresh explícito vía /stock/refresh)
"""

from __future__ import annotations
from sqlalchemy import text as _text

import os
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from db import get_engine

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
STOCK_PARQUET_PATH = Path("/app/data/stock_actual.csv")

# Días de anticipación para considerar stock "próximo a vencer"
# (se alerta pero SÍ se incluye en el disponible; lo vencido se excluye)
DIAS_ALERTA_VENCIMIENTO = int(os.environ.get("DIAS_ALERTA_VENCIMIENTO", "30"))

# Bodegas a incluir. Vacío = TODAS. Separadas por coma en la variable de entorno.
# Ejemplo: BODEGAS_MRP=BSUR01,HIGUERAS
# Bodegas por defecto — hardcodeadas en el query SQL (más eficiente que filtrar en pandas)
# Se pueden sobreescribir via env BODEGAS_MRP para el filtro de pandas (doble seguridad)
_bodegas_env = os.environ.get("BODEGAS_MRP", "BSUR01,VESP01,VARA01").strip()
BODEGAS_INCLUIDAS: list[str] = [b.strip() for b in _bodegas_env.split(",") if b.strip()]

# ── Query SQL ─────────────────────────────────────────────────────────────────
# Bodegas incluidas en el MRP (configurable también vía env BODEGAS_MRP)
_BODEGAS_DEFAULT = ("'BSUR01'", "'VESP01'", "'VARA01'")

_STOCK_QUERY = """
SELECT
    [CODIGO]              AS sku,
    [BODEGA]              AS bodega,
    [LOTE]                AS lote,
    [FECHA VCTO]          AS fecha_vcto,
    [STOCK]               AS stock_unidades,
    [UMED]                AS umed,
    [DESCRIPCION]         AS descripcion,
    [FECHA DESCARGA INFO] AS fecha_descarga
FROM dbo.Stock_Lote_Fecha
WHERE
    [BODEGA] IN ('BSUR01', 'VESP01', 'VARA01')
    AND [CODIGO] IS NOT NULL
    AND [CODIGO] <> ''
    AND [STOCK] IS NOT NULL
    AND [STOCK] <> ''
    AND TRY_CONVERT(date, [FECHA DESCARGA INFO], 105) = (
        SELECT MAX(TRY_CONVERT(date, [FECHA DESCARGA INFO], 105))
        FROM dbo.Stock_Lote_Fecha
        WHERE [BODEGA] IN ('BSUR01', 'VESP01', 'VARA01')
    )
"""

# ── Funciones públicas ────────────────────────────────────────────────────────

def fetch_and_save_stock() -> dict:
    """
    Descarga Stock_Lote_Fecha desde SQL Server, aplica filtros,
    guarda en parquet y retorna resumen del refresh.
    """
    logger.info("[STOCK] Iniciando descarga desde SQL Server...")

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(_text(_STOCK_QUERY))
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

    # Normalizar tipos
    df["sku"] = df["sku"].astype(str).str.strip()
    df["bodega"] = df["bodega"].astype(str).str.strip()
    df["lote"] = df["lote"].astype(str).str.strip()
    df["umed"] = df["umed"].astype(str).str.strip()
    df["descripcion"] = df["descripcion"].astype(str).str.strip()
    # STOCK viene como nvarchar con formato europeo: "1,000000" = 1.0
    # Paso 1: si es string, reemplazar separador de miles (.) y coma decimal (,→.)
    df["stock_unidades"] = (
        df["stock_unidades"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.(?=\d{3})", "", regex=True)   # quitar sep. miles
        .str.replace(",", ".", regex=False)               # coma → punto decimal
    )
    df["stock_unidades"] = pd.to_numeric(df["stock_unidades"], errors="coerce").fillna(0)
    # TODO(v1.4): fijar dayfirst=True o format="%d/%m/%Y" según convención
    # de SQL Server. Hoy genera UserWarning pero no rompe el parsing.
    df["fecha_vcto"] = pd.to_datetime(df["fecha_vcto"], errors="coerce")
    df["fecha_descarga"] = pd.to_datetime(df["fecha_descarga"], errors="coerce")

    # Filtro de bodegas (si está configurado)
    if BODEGAS_INCLUIDAS:
        antes = len(df)
        df = df[df["bodega"].isin(BODEGAS_INCLUIDAS)]
        logger.info(
            f"[STOCK] Filtro bodegas {BODEGAS_INCLUIDAS}: "
            f"{antes} → {len(df)} registros"
        )

    # Guardar parquet
    STOCK_PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(STOCK_PARQUET_PATH, index=False)

    n_skus = df["sku"].nunique()
    n_registros = len(df)
    fecha_descarga = df["fecha_descarga"].max()
    logger.info(
        f"[STOCK] Guardado: {n_registros} registros, {n_skus} SKUs → {STOCK_PARQUET_PATH}"
    )

    return {
        "ok": True,
        "n_registros": n_registros,
        "n_skus": n_skus,
        "bodegas_filtradas": BODEGAS_INCLUIDAS or "todas",
        "fecha_descarga_info": str(fecha_descarga.date()) if pd.notna(fecha_descarga) else None,
        "guardado_en": str(STOCK_PARQUET_PATH),
        "timestamp_refresh": datetime.now().isoformat(),
    }


def load_stock_parquet() -> pd.DataFrame:
    """Carga el parquet de stock. Retorna DataFrame vacío si no existe."""
    if not STOCK_PARQUET_PATH.exists():
        logger.warning("[STOCK] Parquet no encontrado — stock_actual vacío. Ejecuta POST /stock/refresh")
        return pd.DataFrame(columns=["sku", "bodega", "lote", "fecha_vcto",
                                      "stock_unidades", "umed", "descripcion"])
    return pd.read_csv(STOCK_PARQUET_PATH, dtype={"sku": str}, parse_dates=["fecha_vcto", "fecha_descarga"])


def calcular_stock_disponible(
    df_raw: pd.DataFrame | None = None,
    unidades_por_caja: dict[str, int] | None = None,  # ignorado — stock ya viene en cajas
) -> tuple[dict[str, float], list[dict]]:
    """
    Aplica lógica FEFO y reglas de vencimiento.

    IMPORTANTE: Stock_Lote_Fecha reporta en CAJAS (UMED=CJ).
    No se divide por unidades_por_caja.

    Reglas:
      - Lotes ya vencidos (fecha_vcto < hoy) → excluidos del disponible
      - Lotes sin fecha_vcto → incluidos sin alerta
      - Lotes próximos a vencer (< DIAS_ALERTA_VENCIMIENTO días) → incluidos + alerta

    Returns:
        stock_cajas  : dict {sku → stock_disponible_en_cajas}  (para MRP)
        alertas_vcto : list de dicts con detalle de lotes excluidos / próximos
    """
    if df_raw is None:
        df_raw = load_stock_parquet()

    if df_raw.empty:
        return {}, []

    hoy = date.today()
    limite_alerta = hoy + timedelta(days=DIAS_ALERTA_VENCIMIENTO)

    alertas: list[dict] = []
    stock_disponible: dict[str, float] = {}

    for sku, grupo in df_raw.groupby("sku"):
        excluido_cj = 0.0
        disponible_cj = 0.0

        for _, row in grupo.iterrows():
            vcto = row["fecha_vcto"]
            cajas = float(row["stock_unidades"])  # ya viene en cajas
            bodega = row["bodega"]
            lote = row["lote"]

            if pd.isna(vcto):
                # Sin fecha de vencimiento → incluir normalmente
                disponible_cj += cajas
                continue

            vcto_date = vcto.date() if hasattr(vcto, "date") else vcto

            if vcto_date < hoy:
                # VENCIDO → excluir
                excluido_cj += cajas
                alertas.append({
                    "sku": sku,
                    "tipo": "VENCIDO",
                    "lote": lote,
                    "bodega": bodega,
                    "fecha_vcto": str(vcto_date),
                    "stock_cajas": round(cajas, 2),
                    "mensaje": (
                        f"Lote {lote} ({bodega}) vencido el {vcto_date} — "
                        f"{cajas:.1f} cj excluidas del MRP"
                    ),
                })
            elif vcto_date <= limite_alerta:
                # PRÓXIMO A VENCER → incluir + alerta
                disponible_cj += cajas
                dias_restantes = (vcto_date - hoy).days
                alertas.append({
                    "sku": sku,
                    "tipo": "PROXIMO_VENCIMIENTO",
                    "lote": lote,
                    "bodega": bodega,
                    "fecha_vcto": str(vcto_date),
                    "dias_restantes": dias_restantes,
                    "stock_cajas": round(cajas, 2),
                    "mensaje": (
                        f"Lote {lote} ({bodega}) vence en {dias_restantes} días "
                        f"({vcto_date}) — {cajas:.1f} cj incluidas"
                    ),
                })
            else:
                # Normal
                disponible_cj += cajas

        stock_disponible[sku] = disponible_cj  # ya en cajas, sin conversión

    return stock_disponible, alertas


def stock_summary() -> dict:
    """Resumen del parquet actual para el endpoint GET /stock/summary."""
    df = load_stock_parquet()
    if df.empty:
        return {
            "disponible": False,
            "mensaje": "Sin datos — ejecuta POST /stock/refresh",
        }

    hoy = date.today()
    total_u = df["stock_unidades"].sum()
    n_skus = df["sku"].nunique()
    n_bodegas = df["bodega"].nunique()
    fecha_descarga = df["fecha_descarga"].max()

    # Convertir unidades a cajas usando UMED como referencia
    # UMED=CJ significa que el stock ya está en cajas
    total_cajas = float(total_u)  # Stock_Lote_Fecha reporta en cajas (UMED=CJ)

    return {
        "disponible": True,
        "n_skus": int(n_skus),
        "n_bodegas": int(n_bodegas),
        "total_cajas": total_cajas,
        "total_unidades": float(total_u),
        "bodegas_filtradas": BODEGAS_INCLUIDAS or "todas",
        "fecha_descarga_info": (
            str(fecha_descarga.date()) if pd.notna(fecha_descarga) else None
        ),
        "parquet_path": str(STOCK_PARQUET_PATH),
        "parquet_modificado": (
            datetime.fromtimestamp(STOCK_PARQUET_PATH.stat().st_mtime).isoformat()
            if STOCK_PARQUET_PATH.exists() else None
        ),
    }
