"""
db.py — Conexión a SQL Server y extracción de historial de ventas
Traverso S.A. · Piloto de Forecast
Tabla: dbo.ventas
Segmento: COMERCIAL
Granularidad: semanal
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus


# ── Conexión ──────────────────────────────────────────────────────────────────

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
    quoted = quote_plus(get_connection_string())
    return create_engine(
        f"mssql+pyodbc:///?odbc_connect={quoted}",
        fast_executemany=True
    )


def test_connection() -> dict:
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT @@VERSION")).fetchone()[0]
        return {"ok": True, "version": version[:80]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Query principal ───────────────────────────────────────────────────────────
# Filtros aplicados:
#   - Segmento = 'COMERCIAL'
#   - Todas las empresas (TR, CS, MON) consolidadas como Traverso
#   - Solo Facturas y Boletas (excluye NC y ND)
#   - Cantidad > 0 (excluye devoluciones)
#   - Dimensiones: SKU x Canal de comercializacion x Zona
#   - Agrupación: lunes de cada semana

SALES_QUERY = """
SELECT
    CAST(DATEADD(DAY, 1 - DATEPART(WEEKDAY, [Fecha]), CAST([Fecha] AS DATE)) AS DATE)
                                        AS fecha_semana,
    [Codigo Articulo]                   AS sku,
    [Nombre Articulo]                   AS descripcion,
    [Canal de comercializacion]         AS canal,
    [Zona]                              AS zona,
    SUM([Cantidad])                     AS cantidad,
    SUM([Total Linea])                  AS venta_total_clp,
    AVG([Precio])                       AS precio_promedio,
    [Marca]                             AS marca,
    [Categ. Comercial]                  AS categoria,
    [Sub Familia]                       AS sub_familia
FROM
    dbo.ventas
WHERE
    [Segmento] = 'COMERCIAL'
    AND [Fecha] >= DATEADD(MONTH, -48, GETDATE())
    AND [Tipo Doc] IN ('Factura', 'Boleta')
    AND [Cantidad] > 0
    AND [Codigo Articulo] IS NOT NULL AND [Codigo Articulo] <> ''
    AND [Zona] IS NOT NULL AND [Zona] <> ''
    AND [Canal de comercializacion] IS NOT NULL AND [Canal de comercializacion] <> ''
GROUP BY
    CAST(DATEADD(DAY, 1 - DATEPART(WEEKDAY, [Fecha]), CAST([Fecha] AS DATE)) AS DATE),
    [Codigo Articulo], [Nombre Articulo],
    [Canal de comercializacion], [Zona],
    [Marca], [Categ. Comercial], [Sub Familia]
ORDER BY
    sku, fecha_semana
"""


# ── Carga de datos ────────────────────────────────────────────────────────────

def load_sales(skus: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_sql(SALES_QUERY, get_engine())
    df["fecha_semana"]    = pd.to_datetime(df["fecha_semana"])
    df["cantidad"]        = pd.to_numeric(df["cantidad"],        errors="coerce").fillna(0)
    df["venta_total_clp"] = pd.to_numeric(df["venta_total_clp"], errors="coerce").fillna(0)
    df["precio_promedio"] = pd.to_numeric(df["precio_promedio"], errors="coerce").fillna(0)
    df["sku"]             = df["sku"].astype(str).str.strip()
    df["canal"]           = df["canal"].astype(str).str.strip()
    df["zona"]            = df["zona"].astype(str).str.strip()
    if skus:
        df = df[df["sku"].isin(skus)]
    return df


def get_sku_list() -> pd.DataFrame:
    """Lista de SKUs del segmento COMERCIAL con volumen y cobertura."""
    query = """
    SELECT
        [Codigo Articulo]               AS sku,
        [Nombre Articulo]               AS descripcion,
        [Marca]                         AS marca,
        [Categ. Comercial]              AS categoria,
        [Sub Familia]                   AS sub_familia,
        SUM([Cantidad])                 AS volumen_total,
        SUM([Total Linea])              AS venta_total_clp,
        MIN([Fecha])                    AS primera_venta,
        MAX([Fecha])                    AS ultima_venta,
        COUNT(DISTINCT
            CAST(DATEADD(DAY, 1 - DATEPART(WEEKDAY,[Fecha]),
                CAST([Fecha] AS DATE)) AS DATE))  AS semanas_con_venta,
        COUNT(DISTINCT [Canal de comercializacion]) AS n_canales,
        COUNT(DISTINCT [Zona])                      AS n_zonas
    FROM dbo.ventas
    WHERE
        [Segmento] = 'COMERCIAL'
        AND [Tipo Doc] IN ('Factura', 'Boleta')
        AND [Cantidad] > 0
        AND [Codigo Articulo] IS NOT NULL AND [Codigo Articulo] <> ''
        AND [Fecha] >= DATEADD(MONTH, -48, GETDATE())
    GROUP BY [Codigo Articulo], [Nombre Articulo], [Marca], [Categ. Comercial], [Sub Familia]
    ORDER BY volumen_total DESC
    """
    df = pd.read_sql(query, get_engine())
    df["primera_venta"] = pd.to_datetime(df["primera_venta"]).dt.strftime("%Y-%m-%d")
    df["ultima_venta"]  = pd.to_datetime(df["ultima_venta"]).dt.strftime("%Y-%m-%d")
    return df


def get_dimension_summary() -> dict:
    """Valores únicos de Canal y Zona del segmento COMERCIAL."""
    query = """
    SELECT DISTINCT
        [Canal de comercializacion] AS canal,
        [Zona]                      AS zona
    FROM dbo.ventas
    WHERE
        [Segmento] = 'COMERCIAL'
        AND [Tipo Doc] IN ('Factura', 'Boleta')
        AND [Cantidad] > 0
        AND [Canal de comercializacion] IS NOT NULL AND [Canal de comercializacion] <> ''
        AND [Zona] IS NOT NULL AND [Zona] <> ''
    ORDER BY canal, zona
    """
    df = pd.read_sql(query, get_engine())
    return {
        "canales": sorted(df["canal"].unique().tolist()),
        "zonas":   sorted(df["zona"].unique().tolist()),
    }


# ── Modo CSV offline ──────────────────────────────────────────────────────────

def load_sales_from_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    col_map = {}
    for col in df.columns:
        c = col.lower().strip().replace(" ", "_")
        if c in ("fecha_semana", "fecha", "date", "week"):           col_map[col] = "fecha_semana"
        elif c in ("sku", "codigo_articulo", "codigo"):              col_map[col] = "sku"
        elif c in ("descripcion", "nombre_articulo", "nombre"):      col_map[col] = "descripcion"
        elif c in ("cantidad", "qty", "quantity", "ventas"):         col_map[col] = "cantidad"
        elif c in ("canal", "canal_de_comercializacion", "channel"): col_map[col] = "canal"
        elif c in ("zona", "zone", "region"):                        col_map[col] = "zona"
    df = df.rename(columns=col_map)
    missing = {"fecha_semana", "sku", "cantidad"} - set(df.columns)
    if missing:
        raise ValueError(f"Columnas faltantes: {missing}. Disponibles: {list(df.columns)}")
    df["fecha_semana"] = pd.to_datetime(df["fecha_semana"], dayfirst=True, errors="coerce")
    df["cantidad"]     = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["sku"]          = df["sku"].astype(str).str.strip()
    for col in ("canal", "zona", "descripcion", "marca", "categoria", "sub_familia"):
        if col not in df.columns:
            df[col] = "Sin definir"
    return df.dropna(subset=["fecha_semana"])
