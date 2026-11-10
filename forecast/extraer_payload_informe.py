"""
Extrae el payload del Informe de Operación (solo lectura) a un JSON comprimido.

Contenido:
  - KPIs del período y evolutivo semanal por línea (kpi_operacion.dashboard)
  - Conciliación app / SAP / real por SKU y semana (para desvíos recurrentes)
  - Parámetros: mrp_sku_params, mrp_sku_lineas, mrp_lineas, mrp_graneles, campañas, clasificación
  - Plan vigente (mrp_planes): todas las claves del snapshot salvo las que superen el tope de tamaño
  - Faltantes del último corte (mrp_faltantes) y bitácora por línea/semana/tipo/máquina
  - Última vintage de forecast por SKU (mrp_forecast_vintage), si existe

Uso (dentro del contenedor):
  python3 /app/extraer_payload_informe.py --desde 2026-09-07 --hasta 2026-11-08 --out /tmp/payload_informe.json.gz
No escribe en la base.
"""
import argparse
import gzip
import json
from datetime import date, timedelta
from decimal import Decimal

import sqlalchemy as sa

import kpi_operacion as k
from db_mrp import engine

TOPE_CLAVE_MB = 12   # claves del snapshot más grandes que esto se omiten (y se informa)


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date,)):
        return o.isoformat()
    return str(o)


def _filas(c, sql, params=None):
    try:
        return [dict(r._mapping) for r in c.execute(sa.text(sql), params or {})]
    except Exception as e:   # tabla opcional: se informa, no se cae
        c.rollback()
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=date.fromisoformat, default=date(2026, 9, 7))
    ap.add_argument("--hasta", type=date.fromisoformat, default=date(2026, 11, 8))
    ap.add_argument("--out", default="/tmp/payload_informe.json.gz")
    a = ap.parse_args()

    out = {"generado": date.today().isoformat(), "periodo": {"desde": a.desde.isoformat(), "hasta": a.hasta.isoformat()}}
    tamanos = {}

    # 1. KPIs y evolutivo (mismo cálculo que el dashboard)
    out["dashboard"] = k.dashboard(desde=a.desde, hasta=a.hasta, linea=None, categoria=None)

    # 2. Conciliación por semana (para desvíos recurrentes por SKU)
    semanas = []
    lunes = a.desde - timedelta(days=a.desde.weekday())
    while lunes <= a.hasta:
        r = k.calcular_semana(lunes)
        semanas.append({
            "semana": lunes.isoformat(),
            "semana_iso": lunes.isocalendar()[1],
            "conciliacion_sku": r["conciliacion_sku"],
            "lineas": [{"linea": x["linea"], "kpi": x["kpi"], "horas": x["horas"], "cajas": x["cajas"],
                        "cobertura_bitacora": x["cobertura_bitacora"], "n_eventos": x["n_eventos"]}
                       for x in r["lineas"]],
            "fuera_de_lineas": r["resumen"]["fuera_de_lineas"],
        })
        lunes += timedelta(days=7)
    out["semanas"] = semanas

    with engine.connect() as c:
        # 3. Parámetros y maestros
        out["sku_params"] = _filas(c, "SELECT * FROM mrp_sku_params")
        out["sku_lineas"] = _filas(c, "SELECT * FROM mrp_sku_lineas")
        out["lineas"] = _filas(c, "SELECT * FROM mrp_lineas")
        out["lineas_categoria"] = _filas(c, "SELECT * FROM mrp_operacion_lineas")
        out["graneles"] = _filas(c, "SELECT * FROM mrp_graneles")
        out["campana_reglas"] = _filas(c, "SELECT * FROM mrp_campana_reglas")
        out["campana_calendario"] = _filas(c, "SELECT * FROM mrp_campana_calendario")
        out["clasificacion_fuera_catalogo"] = _filas(c, "SELECT * FROM mrp_operacion_sku_linea")

        # 4. Plan vigente: snapshot completo salvo claves demasiado grandes
        meta = _filas(c, "SELECT id, created_at, round(gap::numeric,2) AS gap FROM mrp_planes WHERE vigente")
        out["plan_meta"] = meta
        claves = [r["k"] for r in _filas(c, "SELECT jsonb_object_keys(snapshot) AS k FROM mrp_planes WHERE vigente")]
        out["plan"] = {}
        for clave in claves:
            mb = c.execute(sa.text("SELECT octet_length((snapshot->:k)::text)/1048576.0 FROM mrp_planes WHERE vigente"),
                           {"k": clave}).scalar()
            tamanos[f"plan.{clave}"] = round(float(mb or 0), 2)
            if mb and mb > TOPE_CLAVE_MB:
                out["plan"][clave] = {"omitido": f"{mb:.1f} MB supera el tope de {TOPE_CLAVE_MB} MB"}
                continue
            out["plan"][clave] = c.execute(sa.text("SELECT snapshot->:k FROM mrp_planes WHERE vigente"),
                                           {"k": clave}).scalar()

        # 5. Faltantes del último corte, agregados por SKU (sin datos de clientes)
        out["faltantes_ultimo_corte"] = _filas(c, """
            SELECT fecha, sku, MAX(descripcion) AS descripcion, MAX(cat_comercial) AS cat_comercial,
                   MAX(grupo) AS grupo, MAX(causa) AS causa, SUM(faltante_cj) AS faltante_cj,
                   SUM(programado_cj) AS programado_cj, MAX(stock_ini_cj) AS stock_ini_cj, COUNT(*) AS n_clientes
            FROM mrp_faltantes WHERE fecha = (SELECT MAX(fecha) FROM mrp_faltantes)
            GROUP BY fecha, sku ORDER BY faltante_cj DESC""")
        out["faltantes_historico_semanal"] = _filas(c, """
            SELECT date_trunc('week', fecha)::date AS semana, sku, SUM(faltante_cj) AS faltante_cj
            FROM mrp_faltantes WHERE fecha >= :d GROUP BY 1, 2 HAVING SUM(faltante_cj) > 0""", {"d": a.desde})

        # 6. Bitácora agregada
        out["bitacora_semana_tipo"] = _filas(c, """
            SELECT e.linea, date_trunc('week', e.fecha)::date AS semana, e.tipo, t.categoria,
                   COUNT(*) AS n, SUM(COALESCE(e.duracion_min,0)) AS minutos, COUNT(DISTINCT e.fecha) AS dias
            FROM mrp_eventos_linea e JOIN mrp_eventos_tipos t ON t.codigo = e.tipo
            WHERE NOT e.anulado GROUP BY 1, 2, 3, 4 ORDER BY 1, 2""")
        out["bitacora_maquina"] = _filas(c, """
            SELECT linea, COALESCE(maquina, '(sin máquina)') AS maquina, tipo, COUNT(*) AS n,
                   SUM(COALESCE(duracion_min,0)) AS minutos
            FROM mrp_eventos_linea WHERE NOT anulado GROUP BY 1, 2, 3 ORDER BY 5 DESC""")

        # 7. Forecast: última vintage por SKU (si la tabla tiene esa forma)
        cols = [r["column_name"] for r in _filas(c, """SELECT column_name FROM information_schema.columns
                                                     WHERE table_name = 'mrp_forecast_vintage'""")]
        out["forecast_vintage_columnas"] = cols
        out["forecast_vintage_muestra"] = _filas(c, "SELECT * FROM mrp_forecast_vintage ORDER BY 1 DESC LIMIT 400")

    out["tamanos_mb"] = tamanos
    with gzip.open(a.out, "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=_json_default)
    print("OK", a.out)
    print("claves:", list(out.keys()))
    print("plan:", out.get("plan_meta"), "tamaños MB:", tamanos)
    print("semanas:", len(semanas), "sku_params:", len(out["sku_params"]) if isinstance(out["sku_params"], list) else out["sku_params"])


if __name__ == "__main__":
    main()
