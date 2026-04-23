"""
db.py — Conexión a SQL Server y extracción de historial de ventas
Traverso S.A. · Piloto de Forecast
"""

import os
import pandas as pd
import pyodbc
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus


# ── Configuración de conexión ─────────────────────────────────────────────────

def get_connection_string() -> str:
    server   = os.environ["SQL_SERVER"]
    database = os.environ["SQL_DATABASE"]
    username = os.environ["SQL_USERNAME"]
    password = os.environ["SQL_PASSWORD"]
    driver   = os.environ.get("SQL_DRIVER", "ODBC Driver 18 for SQL Server")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
        "Encrypt=yes;"
    )


def get_engine():
    conn_str = get_connection_string()
    quoted   = quote_plus(conn_str)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quoted}", fast_executemany=True)


def test_connection() -> dict:
    """Verifica que la conexión al SQL Server funcione."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT @@VERSION AS version"))
            version = result.fetchone()[0]
        return {"ok": True, "version": version[:80]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Extracción de ventas ──────────────────────────────────────────────────────

SALES_QUERY = """
-- ╔══════════════════════════════════════════════════════════════════╗
-- ║  CONFIGURA ESTA QUERY CON TUS NOMBRES DE TABLA Y COLUMNAS       ║
-- ║  Reemplaza:                                                      ║
-- ║    tu_tabla_ventas  → nombre real de tu tabla                    ║
-- ║    col_fecha        → columna de fecha de venta                  ║
-- ║    col_sku          → columna de código de producto/SKU          ║
-- ║    col_cantidad     → columna de cantidad vendida                ║
-- ║    col_descripcion  → columna de descripción del producto        ║
-- ╚══════════════════════════════════════════════════════════════════╝
SELECT
    CAST(col_fecha AS DATE)        AS fecha,
    col_sku                        AS sku,
    col_descripcion                AS descripcion,
    SUM(col_cantidad)              AS cantidad
FROM
    tu_tabla_ventas
WHERE
    col_fecha >= DATEADD(MONTH, -48, GETDATE())   -- últimos 48 meses
    AND col_cantidad > 0
    AND col_sku IS NOT NULL
GROUP BY
    CAST(col_fecha AS DATE),
    col_sku,
    col_descripcion
ORDER BY
    sku, fecha
"""


def load_sales(skus: list[str] | None = None,
               months: int = 48,
               query_override: str | None = None) -> pd.DataFrame:
    """
    Carga el historial de ventas desde SQL Server.

    Args:
        skus:            Lista de SKUs a filtrar. None = todos.
        months:          Meses de historial a cargar.
        query_override:  Query SQL personalizada (reemplaza la default).

    Returns:
        DataFrame con columnas: fecha, sku, descripcion, cantidad
    """
    engine = get_engine()
    query  = query_override or SALES_QUERY

    df = pd.read_sql(query, engine)

    # Normalización básica
    df["fecha"]    = pd.to_datetime(df["fecha"])
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["sku"]      = df["sku"].astype(str).str.strip()

    if skus:
        df = df[df["sku"].isin(skus)]

    return df


def get_sku_list() -> pd.DataFrame:
    """Retorna la lista de SKUs disponibles con su volumen total."""
    engine = get_engine()

    # Ajusta con tu query real
    query = """
    SELECT
        col_sku         AS sku,
        col_descripcion AS descripcion,
        SUM(col_cantidad) AS volumen_total,
        MIN(col_fecha)    AS primera_venta,
        MAX(col_fecha)    AS ultima_venta,
        COUNT(DISTINCT CAST(col_fecha AS DATE)) AS dias_con_venta
    FROM tu_tabla_ventas
    WHERE col_cantidad > 0 AND col_sku IS NOT NULL
    GROUP BY col_sku, col_descripcion
    ORDER BY volumen_total DESC
    """

    return pd.read_sql(query, engine)


# ── Carga desde CSV (modo offline / piloto sin SQL) ───────────────────────────

def load_sales_from_csv(path: str) -> pd.DataFrame:
    """
    Alternativa offline: carga ventas desde un CSV exportado.
    
    El CSV debe tener columnas: fecha, sku, descripcion, cantidad
    Formato fecha aceptado: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    """
    df = pd.read_csv(path)

    # Detectar y normalizar columnas comunes
    col_map = {}
    for col in df.columns:
        c = col.lower().strip()
        if c in ("fecha", "date", "fecha_venta", "sale_date"):
            col_map[col] = "fecha"
        elif c in ("sku", "codigo", "código", "producto", "product_code", "item"):
            col_map[col] = "sku"
        elif c in ("descripcion", "descripción", "description", "nombre", "product_name"):
            col_map[col] = "descripcion"
        elif c in ("cantidad", "qty", "quantity", "units", "unidades", "ventas"):
            col_map[col] = "cantidad"

    df = df.rename(columns=col_map)

    required = {"fecha", "sku", "cantidad"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"Columnas faltantes en CSV: {missing}. "
                         f"Columnas disponibles: {list(df.columns)}")

    df["fecha"]    = pd.to_datetime(df["fecha"], dayfirst=True, errors="coerce")
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["sku"]      = df["sku"].astype(str).str.strip()

    if "descripcion" not in df.columns:
        df["descripcion"] = df["sku"]

    return df.dropna(subset=["fecha"])
