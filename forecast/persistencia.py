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

# ── Gate de aceptacion N1 ───────────────────────────────────────────────────
#
# (12-08-2026) G1 DEJO DE SER BLOQUEANTE Y PASO A SER UNA MEDICION.
#
# El comentario original de este bloque decia que G1 contaba "quiebres reales"
# sobre stock_diario, y explicitaba que NO usaba stock_final_cajas porque estaba
# clampeado. La intencion era correcta; la premisa, FALSA: `stock_diario` TAMBIEN
# esta clampeado a 0. Medido el 12-08 sobre el plan 141 (206 SKU, 11.536 celdas):
#
#     stock_diario   -> 0 celdas < 0, minimo 0.0 EXACTO   <- imposible, es el clamp
#     detalle_diario -> 49 dias con estado=QUIEBRE
#                       49 con stock_disp_u < 0 (intradia)
#                       27 con stock_fin_u  < 0 (cierre)
#
# O sea que G1 reportaba `negativos=0` TODOS los dias por construccion: no podia
# fallar, y por lo tanto no controlaba nada. Cada "aceptable=True" del cron daba
# una garantia que no existia.
#
# POR QUE NO SE ARREGLA SOLO CAMBIANDO LA FUENTE: la pasada A demuestra que hay
# quiebres INEVITABLES (Q* = 43 el 12-08). Con la fuente correcta y el criterio de
# cero, el gate rechazaria TODOS los planes y el cron nunca volveria a promover.
# El problema no era solo la medicion: el CRITERIO nunca tuvo sentido.
#
# POLITICA VIGENTE (decidida el 12-08): el plan se promueve igual y se avisa por
# separado (cron_plan_alerta.py). Siendo asi, contar quiebres no puede ser una
# condicion de bloqueo. G1 MIDE E INFORMA; lo que bloquea es:
#   - status no operable (INFEASIBLE / vacio)
#   - G2: linea sobrecargada -> uso_linea > 100%, que es una imposibilidad FISICA
#
# Se reportan las DOS mediciones de quiebre, etiquetadas. Publicar una sola
# repetiria el error del 11-08: dos numeros correctos que parecen contradecirse
# porque nadie dijo que miden.
#   intradia (stock_disp_u < 0) = criterio del MRP y de lo que muestra el dashboard
#   cierre   (stock_fin_u  < 0) = comparable con la barrera de N2 (anclada en `fin`)
#
# G3 (cerrar OPTIMAL) NO entra al gate: es deuda que no bloquea el cron.
_G2_TOL = 1e-6  # tolerancia de floats: 100.0 exacto es aceptable, no sobrecarga


def medir_quiebres(resultado: dict) -> dict:
    """Cuenta quiebres del plan sobre `detalle_diario`, que NO esta clampeado.

    No decide nada: solo mide. Devuelve las dos definiciones por separado mas los
    minimos reales, en unidades.
    """
    dd = resultado.get("detalle_diario") or {}
    n_estado = n_disp = n_fin = 0
    min_disp = min_fin = None
    skus = set()
    muestra = []
    for sku, serie in dd.items():
        for f, c in serie.items():
            sdp = c.get("stock_disp_u")
            sfn = c.get("stock_fin_u")
            if c.get("estado") == "QUIEBRE":
                n_estado += 1
                skus.add(sku)
                if len(muestra) < 10:
                    muestra.append({"sku": sku, "fecha": f,
                                    "stock_disp_u": sdp, "stock_fin_u": sfn})
            if sdp is not None:
                if sdp < 0:
                    n_disp += 1
                min_disp = sdp if min_disp is None else min(min_disp, sdp)
            if sfn is not None:
                if sfn < 0:
                    n_fin += 1
                min_fin = sfn if min_fin is None else min(min_fin, sfn)
    return {
        "n_dias_quiebre": n_estado,        # estado == QUIEBRE (criterio del MRP)
        "n_sku_quiebre": len(skus),
        "n_celdas_disp_neg": n_disp,       # intradia
        "n_celdas_fin_neg": n_fin,         # cierre
        "min_stock_disp_u": min_disp,
        "min_stock_fin_u": min_fin,
        "muestra_quiebres": muestra,
    }


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
    g1 = (len(negativos) == 0)   # se conserva por trazabilidad; NO decide (ver arriba)

    # Medicion REAL de quiebres, sobre datos sin clampear.
    q = medir_quiebres(resultado)

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

    # (12-08-2026) G1 fuera de la condicion: mide, no bloquea. Ver el bloque de
    # comentarios de arriba. En la practica no cambia el comportamiento -- G1 dio
    # verde todos los dias por construccion -- pero deja de dar una garantia falsa.
    aceptable = bool(operable and g2)

    detalle = {
        "aceptable": aceptable,
        "status": status,
        "operable": operable,
        "g1_sin_quiebres": g1,        # informativo: NO entra en `aceptable`
        "g1_es_bloqueante": False,    # explicito, para que nadie lo asuma
        "g2_lineas_ok": g2,
        # `min_stock` y `n_celdas_negativas` salen de stock_diario, que esta
        # CLAMPEADO: se conservan por compatibilidad del log y del snapshot, pero
        # NO son la medicion de quiebres. La real es `quiebres`.
        "min_stock": min_stock,
        "n_celdas_negativas": len(negativos),
        "celdas_negativas": negativos[:10],   # muestra acotada
        "quiebres": q,
        "max_uso_linea_pct": max_uso,
        "n_lineas_sobrecargadas": len(sobrecargas),
        "lineas_sobrecargadas": sobrecargas[:10],
    }
    return aceptable, detalle
