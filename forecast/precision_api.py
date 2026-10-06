"""
precision_api.py - API del dashboard de precision del forecast.

Cruza mrp_forecast_vintage (lo que el forecast predijo con 1 o 2 semanas de
anticipacion) con mrp_venta_semanal (venta real, mismo binning que Prophet).
Ambas tablas las escribe precision_forecast.py (cron lunes 04:00 UTC).

Reglas (acordadas 06-10-2026):
  - Los horizontes NUNCA se mezclan: todo endpoint recibe UN horizonte (1 o 2).
  - Solo semanas cerradas (la venta real solo existe para semanas cerradas).
  - Sesgo%  = (S yhat - S real) / S real  -> signo: + sobredimensionado, - subdimensionado.
  - WMAPE%  = S |yhat - real| / S real    -> magnitud, no se cancela entre SKU.
  - Agregacion en CAJAS (u / u_por_caja): unidad de negocio de stock y produccion.
    El % por SKU individual es identico en u o cj (invariante a escala).
  - Linea = linea_preferida de mrp_sku_params (particion: cada SKU en UNA linea;
    sin linea -> 'SIN_LINEA'). Suma de lineas = total, sin doble conteo.
  - SKU de bajo volumen (venta real promedio < umbral_cj por semana): no se
    informa % (explota con denominadores chicos), solo cajas.

Endpoints:
  GET /precision/filtros  -> opciones de filtros + semanas disponibles por horizonte
  GET /precision          -> serie semanal, KPI de la ventana, ranking por SKU, huecos
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from db_mrp import get_session

router = APIRouter(prefix="/precision", tags=["Precision forecast"])

SIN_LINEA = "SIN_LINEA"
UMBRAL_CJ_SEMANA_DEFAULT = 5.0
TOL_ACIERTO_PCT = 0.5          # |sesgo| < 0,5% se informa como "en linea"


# -- Helpers -------------------------------------------------------------------

def _pct(num: float, den: float) -> Optional[float]:
    if den is None or den <= 0:
        return None
    return round(100.0 * num / den, 1)


def _rango_semana(d: date) -> str:
    fin = d + timedelta(days=6)
    return f"{d:%d-%m} – {fin:%d-%m}"


def _frase(h: int, semana: date, sesgo: Optional[float]) -> str:
    anticip = "1 semana" if h == 1 else f"{h} semanas"
    if sesgo is None:
        return f"Con {anticip} de anticipación, la semana del {semana:%d-%m} no tiene venta para comparar."
    if abs(sesgo) < TOL_ACIERTO_PCT:
        return f"Con {anticip} de anticipación, el forecast de la semana del {semana:%d-%m} estuvo en línea con la venta real."
    sentido = "sobredimensionada" if sesgo > 0 else "subdimensionada"
    pct = f"{abs(sesgo):.1f}".replace(".", ",")      # coma decimal (es-CL)
    return (f"Con {anticip} de anticipación, la venta de la semana del {semana:%d-%m} "
            f"fue {sentido} un {pct}%.")


def _metricas(g: pd.DataFrame) -> dict:
    real, yhat = float(g["real_cj"].sum()), float(g["yhat_cj"].sum())
    err_abs = float((g["yhat_cj"] - g["real_cj"]).abs().sum())
    return dict(real_cj=round(real, 1), yhat_cj=round(yhat, 1),
                real_u=round(float(g["real_u"].sum()), 1),
                yhat_u=round(float(g["yhat_u"].sum()), 1),
                error_abs_cj=round(err_abs, 1),
                sesgo_pct=_pct(yhat - real, real),
                wmape_pct=_pct(err_abs, real),
                n_sku=int(g["sku"].nunique()))


def _cargar_base(h: int, desde: Optional[date], hasta: Optional[date],
                 categoria: Optional[str], linea: Optional[str],
                 q: Optional[str], skus: Optional[str]) -> pd.DataFrame:
    where = ["v.horizonte_sem = :h"]
    params: dict = {"h": h}
    if desde:
        where.append("v.semana_objetivo >= :desde"); params["desde"] = desde
    if hasta:
        where.append("v.semana_objetivo <= :hasta"); params["hasta"] = hasta
    if categoria:
        where.append("p.categoria = :categoria"); params["categoria"] = categoria
    if linea:
        where.append("COALESCE(NULLIF(p.linea_preferida, ''), :sin_linea) = :linea")
        params["linea"] = linea
    if q:
        where.append("(v.sku ILIKE :q OR p.descripcion ILIKE :q)"); params["q"] = f"%{q.strip()}%"
    if skus:
        lista = [s.strip() for s in skus.split(",") if s.strip()]
        if lista:
            where.append("v.sku = ANY(:skus)"); params["skus"] = lista
    params["sin_linea"] = SIN_LINEA
    where_sql = " AND ".join(where)
    sql = f"""
        SELECT v.sku, v.semana_objetivo AS semana, v.domingo_corte, v.con_evento,
               v.yhat_u::float AS yhat_u, s.venta_u::float AS real_u,
               GREATEST(COALESCE(p.u_por_caja, 1), 1) AS upc,
               p.descripcion, p.categoria,
               COALESCE(NULLIF(p.linea_preferida, ''), :sin_linea) AS linea
          FROM mrp_forecast_vintage v
          JOIN mrp_venta_semanal s ON s.sku = v.sku AND s.semana = v.semana_objetivo
          LEFT JOIN mrp_sku_params p ON p.sku = v.sku
         WHERE {where_sql}
    """
    with get_session() as session:
        rows = session.execute(text(sql), params).mappings().all()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df["semana"] = pd.to_datetime(df["semana"]).dt.date
    df["real_cj"] = df["real_u"] / df["upc"]
    df["yhat_cj"] = df["yhat_u"] / df["upc"]
    return df


def _semanas_sin_vintage(h: int, desde: Optional[date], hasta: Optional[date]) -> list[str]:
    """Semanas cerradas (con venta registrada) sin vintage para este horizonte.
    Ej.: sin reentrenamiento el 21-09 -> falta W=27-09 en h=1 y W=04-10 en h=2."""
    params: dict = {"h": h}
    filtro = ""
    if desde:
        filtro += " AND s.semana >= :desde"; params["desde"] = desde
    if hasta:
        filtro += " AND s.semana <= :hasta"; params["hasta"] = hasta
    sql = f"""
        SELECT DISTINCT s.semana
          FROM mrp_venta_semanal s
         WHERE NOT EXISTS (SELECT 1 FROM mrp_forecast_vintage v
                            WHERE v.semana_objetivo = s.semana AND v.horizonte_sem = :h)
           {filtro}
         ORDER BY s.semana
    """
    with get_session() as session:
        rows = session.execute(text(sql), params).fetchall()
    return [str(r[0]) for r in rows]


# -- Endpoints -----------------------------------------------------------------

@router.get("/filtros")
def precision_filtros():
    """Opciones de filtros (solo SKU con vintage) y semanas evaluables por horizonte."""
    with get_session() as session:
        skus = session.execute(text("""
            SELECT f.sku, p.descripcion, p.categoria,
                   COALESCE(NULLIF(p.linea_preferida, ''), :sin) AS linea
              FROM (SELECT DISTINCT sku FROM mrp_forecast_vintage) f
              LEFT JOIN mrp_sku_params p ON p.sku = f.sku
             ORDER BY f.sku
        """), {"sin": SIN_LINEA}).mappings().all()
        lineas = session.execute(text("""
            SELECT DISTINCT COALESCE(NULLIF(p.linea_preferida, ''), :sin) AS codigo, l.nombre
              FROM (SELECT DISTINCT sku FROM mrp_forecast_vintage) f
              LEFT JOIN mrp_sku_params p ON p.sku = f.sku
              LEFT JOIN mrp_lineas l ON l.codigo = p.linea_preferida
             ORDER BY 1
        """), {"sin": SIN_LINEA}).mappings().all()
        semanas = session.execute(text("""
            SELECT v.horizonte_sem AS h, v.semana_objetivo AS semana
              FROM mrp_forecast_vintage v
              JOIN mrp_venta_semanal s ON s.sku = v.sku AND s.semana = v.semana_objetivo
             GROUP BY 1, 2 ORDER BY 1, 2
        """)).mappings().all()
    sem_por_h: dict = {"1": [], "2": []}
    for r in semanas:
        sem_por_h[str(r["h"])].append(str(r["semana"]))
    return {
        "skus": [dict(r) for r in skus],
        "categorias": sorted({r["categoria"] for r in skus if r["categoria"]}),
        "lineas": [{"codigo": r["codigo"],
                    "nombre": "Sin línea (no se produce en planta)" if r["codigo"] == SIN_LINEA
                    else (r["nombre"] or r["codigo"])} for r in lineas],
        "semanas_evaluables": sem_por_h,
    }


@router.get("")
def precision(
    horizonte: int = Query(..., description="Anticipación en semanas: 1 o 2 (nunca se mezclan)"),
    desde: Optional[date] = Query(None, description="Semana objetivo inicial (domingo)"),
    hasta: Optional[date] = Query(None, description="Semana objetivo final (domingo)"),
    categoria: Optional[str] = None,
    linea: Optional[str] = Query(None, description=f"Código de línea preferida o {SIN_LINEA}"),
    q: Optional[str] = Query(None, description="Texto en SKU o descripción"),
    skus: Optional[str] = Query(None, description="Lista de SKU separados por coma"),
    umbral_cj: float = Query(UMBRAL_CJ_SEMANA_DEFAULT, ge=0,
                             description="Venta real promedio (cj/semana) bajo la cual no se informa % por SKU"),
):
    if horizonte not in (1, 2):
        raise HTTPException(400, "horizonte debe ser 1 o 2")
    df = _cargar_base(horizonte, desde, hasta, categoria, linea, q, skus)
    huecos = _semanas_sin_vintage(horizonte, desde, hasta)
    meta = {"horizonte": horizonte, "unidad_agregacion": "cajas", "umbral_cj_semana": umbral_cj,
            "filtros": {"desde": str(desde) if desde else None, "hasta": str(hasta) if hasta else None,
                        "categoria": categoria, "linea": linea, "q": q, "skus": skus}}
    if df.empty:
        return {"meta": meta, "kpi": None, "serie": [], "ranking_sku": [],
                "semanas_sin_vintage": huecos}

    # Serie semanal
    serie = []
    for semana, g in df.groupby("semana", sort=True):
        m = _metricas(g)
        serie.append({"semana": str(semana), "rango": _rango_semana(semana),
                      "corte": str(g["domingo_corte"].iloc[0]), **m,
                      "frase": _frase(horizonte, semana, m["sesgo_pct"])})

    # KPI de la ventana completa
    kpi = _metricas(df)
    kpi["n_semanas"] = int(df["semana"].nunique())

    # Ranking por SKU (ordenado por contribucion al error absoluto)
    ranking = []
    n_sem = df.groupby("sku")["semana"].nunique()
    for sku, g in df.groupby("sku"):
        m = _metricas(g)
        prom_sem = m["real_cj"] / max(int(n_sem[sku]), 1)
        bajo = prom_sem < umbral_cj
        r0 = g.iloc[0]
        ranking.append({"sku": sku, "descripcion": r0["descripcion"], "categoria": r0["categoria"],
                        "linea": r0["linea"], "con_evento": bool(g["con_evento"].any()),
                        "n_semanas": int(n_sem[sku]), "real_prom_cj_sem": round(prom_sem, 1),
                        "bajo_volumen": bool(bajo), **m,
                        "sesgo_pct": None if bajo else m["sesgo_pct"],
                        "wmape_pct": None if bajo else m["wmape_pct"]})
    ranking.sort(key=lambda r: r["error_abs_cj"], reverse=True)

    return {"meta": meta, "kpi": kpi, "serie": serie, "ranking_sku": ranking,
            "semanas_sin_vintage": huecos}
