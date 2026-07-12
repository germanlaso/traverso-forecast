# persistencia.py — persistencia de planes N1 en mrp_planes
# INSERT (vigente=false) + promocion atomica (vigente unico). No evalua gate.
import json
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from db_mrp import SessionLocal

CLAVES_SNAPSHOT = (
    "ofts", "stock_diario", "alertas", "uso_linea",
    "resumen", "sobrecargas_aprobadas", "vista_dashboard",
    "detalle_diario", "encabezado_sku",
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


def _fila(resultado, horizonte_sem, timestamp_stock, time_limit_sec, entradas_fijas, aceptable):
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
        "gap": resultado.get("gap"),   # expuesto por optimizer (_calcular_gap)
        "aceptable": aceptable,        # veredicto del gate N1 (lo pasa el caller)
        "snapshot": snapshot_json,
    }


def persistir_plan(
    resultado: dict[str, Any],
    horizonte_sem: int,
    timestamp_stock: Optional[str] = None,
    time_limit_sec: Optional[int] = None,
    entradas_fijas: Optional[list[dict]] = None,
    aceptable: Optional[bool] = None,
    session: Optional[Session] = None,
) -> int:
    """Inserta un plan como fila nueva en mrp_planes (vigente=false).
    Devuelve el id. NO promueve (vigente=false). aceptable/gap se guardan si
    el caller los pasa (aceptable lo evalua con evaluar_gate_n1; gap viene del
    optimizer). vigente siempre false: la promocion es una operacion aparte.

    Si se pasa `session`, usa esa sesion y NO commitea (el caller controla la
    transaccion: requerido por el cron para insert+promocion atomica, y por el
    dry-run con rollback). Si no se pasa, abre sesion propia y commitea.
    """
    fila = _fila(resultado, horizonte_sem, timestamp_stock,
                 time_limit_sec, entradas_fijas, aceptable)

    if session is not None:
        return session.execute(_SQL_INSERT, fila).scalar_one()

    with SessionLocal() as s:
        nuevo_id = s.execute(_SQL_INSERT, fila).scalar_one()
        s.commit()
        return nuevo_id

_SQL_BAJAR = text("UPDATE mrp_planes SET vigente = false WHERE vigente")
_SQL_SUBIR = text("UPDATE mrp_planes SET vigente = true WHERE id = :plan_id")
_SQL_EXISTE = text("SELECT 1 FROM mrp_planes WHERE id = :plan_id")


def promover_plan(plan_id: int, session: Optional[Session] = None) -> None:
    """Marca plan_id como el plan vigente, de forma atomica.

    Baja el vigente actual (0 o 1 filas) y sube plan_id, en ese orden (el orden
    importa: el indice unico parcial permite 0 vigentes como estado intermedio,
    no 2). El caller es responsable de validar el gate ANTES de promover: esta
    funcion NO evalua aceptable, solo ejecuta la promocion.

    Si se pasa `session`, usa esa sesion y NO commitea (el caller controla la
    transaccion: permite insert+promocion atomicos en el cron). Si no, abre
    sesion propia y commitea.

    Lanza ValueError si plan_id no existe.
    """
    def _promover(s):
        if s.execute(_SQL_EXISTE, {"plan_id": plan_id}).first() is None:
            raise ValueError(f"promover_plan: no existe plan id={plan_id}")
        s.execute(_SQL_BAJAR)
        s.execute(_SQL_SUBIR, {"plan_id": plan_id})

    if session is not None:
        _promover(session)
        return

    with SessionLocal() as s:
        _promover(s)
        s.commit()

# ── Gate de aceptacion N1 (G1 + G2) ─────────────────────────────────────────
# G1: 0 quiebres reales -> ningun stock_diario[sku][fecha] < 0.
#     (NO se cuenta sobre alertas "QUIEBRE" -umbral- ni stock_final_cajas -clampeado-)
# G2: ninguna linea sobrecargada -> uso_linea[linea][fecha] <= 100 (en %, 100 = llena OK).
# G3 (cerrar OPTIMAL) NO entra al gate: es deuda que no bloquea el cron.
_G2_TOL = 1e-6  # tolerancia de floats: 100.0 exacto es aceptable, no sobrecarga


def evaluar_gate_n1(resultado: dict) -> tuple[bool, dict]:
    """Evalua si un plan N1 es ACEPTABLE (G1 y G2). Opera sobre el dict RICO
    (necesita stock_diario y uso_linea celda por celda, no el resumen agregado).

    Devuelve (aceptable, detalle) donde detalle trae las metricas para el log
    del cron y el snapshot: min stock, celdas negativas, max uso, lineas
    sobrecargadas. NO promueve ni persiste: solo evalua.

    Si el status no es operable (INFEASIBLE / vacio), aceptable = False.
    """
    status = resultado.get("status")
    operable = status in ("OPTIMAL", "FEASIBLE", "FEASIBLE_TIMEOUT")

    sd = resultado.get("stock_diario") or {}
    ul = resultado.get("uso_linea") or {}

    # ── G1: ningun stock proyectado < 0 ──
    negativos = [
        {"sku": sku, "fecha": f, "stock": v}
        for sku, serie in sd.items()
        for f, v in serie.items()
        if v < 0
    ]
    min_stock = min(
        (v for serie in sd.values() for v in serie.values()),
        default=None,
    )
    g1 = (len(negativos) == 0)

    # ── G2: ninguna linea > 100% ──
    sobrecargas = [
        {"linea": l, "fecha": f, "uso_pct": u}
        for l, serie in ul.items()
        for f, u in serie.items()
        if u > 100 + _G2_TOL
    ]
    max_uso = max(
        (u for serie in ul.values() for u in serie.values()),
        default=None,
    )
    g2 = (len(sobrecargas) == 0)

    aceptable = bool(operable and g1 and g2)

    detalle = {
        "aceptable": aceptable,
        "status": status,
        "operable": operable,
        "g1_sin_quiebres": g1,
        "g2_lineas_ok": g2,
        "min_stock": min_stock,
        "n_celdas_negativas": len(negativos),
        "celdas_negativas": negativos[:10],   # muestra acotada
        "max_uso_linea_pct": max_uso,
        "n_lineas_sobrecargadas": len(sobrecargas),
        "lineas_sobrecargadas": sobrecargas[:10],
    }
    return aceptable, detalle
