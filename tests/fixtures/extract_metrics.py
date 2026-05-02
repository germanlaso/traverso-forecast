"""
Extrae las 5 métricas clave de un response JSON del endpoint POST /plan.

Uso:
    python3 extract_metrics.py <ruta_plan.json> [--label LABEL]

Métricas extraídas:
    1. status del solver        (optimizacion.status)
    2. tiempo solver (s)        (optimizacion.tiempo_ms / 1000)
    3. objective_value          (optimizacion.objective_value)
    4. OFTs PRODUCCION totales  (count ordenes con tipo=PRODUCCION y aprobada=False)
    5. OFTs con paga_setup=true (subset de la métrica 4 con paga_setup=true)

Imprime en stdout en formato legible. Útil para baseline F1 y comparación
tras cada commit de la fase F1 (cascada v1.3).
"""
import json
import sys
from pathlib import Path


def extract(path: Path, label: str = "") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    opt = plan.get("optimizacion", {}) or {}
    ordenes = plan.get("ordenes", []) or []

    ofts_produccion = [
        o for o in ordenes
        if str(o.get("tipo", "")).upper() == "PRODUCCION"
        and not o.get("aprobada", False)
    ]
    ofts_con_setup = [o for o in ofts_produccion if o.get("paga_setup")]

    return {
        "label": label or path.name,
        "status": opt.get("status", "UNKNOWN"),
        "solver_time_sec": round((opt.get("tiempo_ms", 0) or 0) / 1000.0, 2),
        "objective_value": opt.get("objective_value"),
        "ofts_produccion": len(ofts_produccion),
        "ofts_con_paga_setup": len(ofts_con_setup),
    }


def format_metrics(m: dict) -> str:
    obj = m["objective_value"]
    obj_str = f"{obj:,.0f}" if isinstance(obj, (int, float)) else str(obj)
    return (
        f"=== {m['label']} ===\n"
        f"  status                : {m['status']}\n"
        f"  solver_time_sec       : {m['solver_time_sec']}\n"
        f"  objective_value       : {obj_str}\n"
        f"  ofts_produccion       : {m['ofts_produccion']}\n"
        f"  ofts_con_paga_setup   : {m['ofts_con_paga_setup']}\n"
    )


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 extract_metrics.py <plan.json> [--label LABEL]")
        sys.exit(1)
    path = Path(sys.argv[1])
    label = ""
    if "--label" in sys.argv:
        i = sys.argv.index("--label")
        if i + 1 < len(sys.argv):
            label = sys.argv[i + 1]
    m = extract(path, label)
    print(format_metrics(m))


if __name__ == "__main__":
    main()
