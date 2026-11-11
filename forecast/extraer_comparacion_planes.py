"""
Extrae lo necesario para evaluar el impacto de los cambios de parámetros (solo lectura).

Compara dos planes de mrp_planes (base = antes de los cambios, nuevo = después) y agrega
el historial de cambios del panel y los parámetros vigentes. El análisis se hace aparte.

Uso (dentro del contenedor):
  python3 /app/extraer_comparacion_planes.py --base 331 --nuevo 332 --out /tmp/comparacion_planes.json.gz
  # --nuevo omitido = el plan más reciente
"""
import argparse
import gzip
import json
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa

from db_mrp import engine

CLAVES_PLAN = ("resumen", "alertas", "uso_linea", "ofts", "encabezado_sku", "entradas_fijas",
               "sobrecargas_aprobadas", "detalle_diario")


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _plan(c, pid):
    meta = c.execute(sa.text("SELECT id, created_at, vigente, gap FROM mrp_planes WHERE id = :i"), {"i": pid}).first()
    if meta is None:
        raise SystemExit(f"No existe el plan {pid}")
    out = {"meta": dict(meta._mapping)}
    for k in CLAVES_PLAN:
        out[k] = c.execute(sa.text("SELECT snapshot->:k FROM mrp_planes WHERE id = :i"), {"k": k, "i": pid}).scalar()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=int, required=True)
    ap.add_argument("--nuevo", type=int, default=None)
    ap.add_argument("--out", default="/tmp/comparacion_planes.json.gz")
    a = ap.parse_args()
    with engine.connect() as c:
        nuevo = a.nuevo or c.execute(sa.text("SELECT MAX(id) FROM mrp_planes")).scalar()
        if nuevo == a.base:
            raise SystemExit("El plan nuevo es el mismo que el base: todavía no terminó la corrida.")
        base_ts = c.execute(sa.text("SELECT created_at FROM mrp_planes WHERE id = :i"), {"i": a.base}).scalar()
        out = {
            "base": _plan(c, a.base),
            "nuevo": _plan(c, nuevo),
            # cambios hechos DESPUÉS de generar el plan base (los que el plan nuevo ya incorpora)
            "historial": [dict(r._mapping) for r in c.execute(sa.text(
                "SELECT * FROM mrp_params_historial WHERE ts > :t ORDER BY ts"), {"t": base_ts})],
            "recomendaciones": [dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_params_recomendaciones"))],
            "sku_params": [dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params"))],
            "sku_lineas": [dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_lineas"))],
            "lineas": [dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_lineas"))],
        }
    with gzip.open(a.out, "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, default=_default)
    print("OK", a.out, "| base", a.base, "| nuevo", nuevo, "| cambios en historial:", len(out["historial"]))
    for k in ("base", "nuevo"):
        m = out[k]["meta"]
        al = out[k]["alertas"] or []
        print(f"  plan {m['id']} ({m['created_at']}, vigente={m['vigente']}, gap={m['gap']}): "
              f"QUIEBRE={sum(1 for x in al if x.get('tipo') == 'QUIEBRE')} "
              f"BAJO_SS={sum(1 for x in al if x.get('tipo') == 'BAJO_SS')} "
              f"OFT={len(out[k]['ofts'] or [])}")


if __name__ == "__main__":
    main()
