# persistencia.py — persistencia de planes N1 en mrp_planes
# Solo INSERT (vigente=false). No promueve, no evalua gate, no toca cron.
import json
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from db_mrp import SessionLocal

CLAVES_SNAPSHOT = (
    "ofts", "stock_diario", "alertas", "uso_linea",
    "resumen", "sobrecargas_aprobadas",
)

_SQL_INSERT = text("""
    INSERT INTO mrp_planes
        (timestamp_stock, horizonte_sem, time_limit_sec,
         status, objective, gap, aceptable, vigente, snapshot)
    VALUES
        (:timestamp_stock, :horizonte_sem, :time_limit_sec,
         :status, :objective, :gap, :aceptable, false, CAST(:snapshot AS jsonb))
    RETURNING id
""")


def _fila(resultado, horizonte_sem, timestamp_stock, time_limit_sec, entradas_fijas):
    snapshot = {k: resultado.get(k) for k in CLAVES_SNAPSHOT}
    snapshot["entradas_fijas"] = entradas_fijas or []
    # default=str: cinturon por si sobrecargas_aprobadas trae objetos crudos
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    return {
        "timestamp_stock": timestamp_stock,
        "horizonte_sem": horizonte_sem,
        "time_limit_sec": time_limit_sec,
        "status": resultado.get("status"),
        "objective": resultado.get("objective_value"),
        "gap": None,       # TODO: exponer desde optimizer (BestObjectiveBound)
        "aceptable": None,  # TODO: gate N1 (G1+G2)
        "snapshot": snapshot_json,
    }


def persistir_plan(
    resultado: dict[str, Any],
    horizonte_sem: int,
    timestamp_stock: Optional[str] = None,
    time_limit_sec: Optional[int] = None,
    entradas_fijas: Optional[list[dict]] = None,
    session: Optional[Session] = None,
) -> int:
    """Inserta un plan como fila nueva en mrp_planes (vigente=false).
    Devuelve el id. NO promueve ni evalua aceptable (quedan NULL/false).

    Si se pasa `session`, usa esa sesion y NO commitea (el caller controla la
    transaccion: requerido por el cron para insert+promocion atomica, y por el
    dry-run con rollback). Si no se pasa, abre sesion propia y commitea.
    """
    fila = _fila(resultado, horizonte_sem, timestamp_stock,
                 time_limit_sec, entradas_fijas)

    if session is not None:
        return session.execute(_SQL_INSERT, fila).scalar_one()

    with SessionLocal() as s:
        nuevo_id = s.execute(_SQL_INSERT, fila).scalar_one()
        s.commit()
        return nuevo_id
