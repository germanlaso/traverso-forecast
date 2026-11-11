"""
solver_cola.py — Cola ÚNICA del solver con bloqueo (R17, 11-11-2026).

Nunca corren dos solvers a la vez: cron del plan, pre-vuelo, corridas de prueba
(--no-promote), comparaciones, análisis programados y la corrida manual desde la app
pasan por aquí.

Mecanismo: advisory lock de PostgreSQL de SESIÓN, en una conexión dedicada (sin pool).
Si el proceso muere, la conexión se cierra y el lock se libera solo. La tabla
mrp_solver_cola deja la traza visible (quién espera, quién corre, cuánto tardó).

Uso:
    from solver_cola import turno_solver, SolverOcupado
    with turno_solver("plan_cron", "cron 06:00"):
        ... optimizar ...
    # corrida manual: no esperar más de 10 s
    with turno_solver("plan_manual", "app", espera_max_s=10): ...
"""
import logging
import os
import time
from contextlib import contextmanager
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter
from sqlalchemy.pool import NullPool

from db_mrp import engine as _engine

log = logging.getLogger("solver_cola")
router = APIRouter(prefix="/solver", tags=["Solver"])

LOCK_KEY = 7_330_042
INTERVALO_S = 15
AVISO_CADA_S = 300


class SolverOcupado(RuntimeError):
    pass


def _engine_dedicado():
    return sa.create_engine(_engine.url, poolclass=NullPool)


def _registrar(c, tipo, descripcion, solicitado_por):
    return c.execute(sa.text("""INSERT INTO mrp_solver_cola (tipo, descripcion, solicitado_por, estado, pid)
                                VALUES (:t, :d, :s, 'en_cola', :p) RETURNING id"""),
                     {"t": tipo, "d": descripcion[:300], "s": solicitado_por, "p": os.getpid()}).scalar()


@contextmanager
def turno_solver(tipo: str, descripcion: str = "", solicitado_por: str = "sistema",
                 espera_max_s: Optional[float] = None):
    eng = _engine_dedicado()
    conn = eng.connect()
    jid = None
    try:
        try:
            jid = _registrar(conn, tipo, descripcion, solicitado_por)
            conn.commit()
        except Exception as e:      # sin tabla (migración pendiente): igual se usa el lock
            conn.rollback()
            log.warning(f"[COLA] sin registro en mrp_solver_cola: {e}")
        t0, ultimo_aviso = time.time(), 0.0
        while True:
            ok = conn.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
            conn.commit()
            if ok:
                break
            esperado = time.time() - t0
            if espera_max_s is not None and esperado >= espera_max_s:
                if jid:
                    conn.execute(sa.text("UPDATE mrp_solver_cola SET estado = 'cancelado', fin = now(), "
                                         "detalle = 'Solver ocupado' WHERE id = :i"), {"i": jid})
                    conn.commit()
                quien = _ocupante(conn)
                raise SolverOcupado(f"El solver está ocupado{(' por ' + quien) if quien else ''}. Intenta más tarde.")
            if esperado - ultimo_aviso >= AVISO_CADA_S:
                log.info(f"[COLA] {tipo}: esperando turno del solver ({esperado / 60:.0f} min) | ocupado por: {_ocupante(conn)}")
                ultimo_aviso = esperado
            time.sleep(INTERVALO_S)
        espera = time.time() - t0
        if jid:
            # con el lock en mano, nadie más corre: lo que figure 'ejecutando' quedó huérfano
            conn.execute(sa.text("UPDATE mrp_solver_cola SET estado = 'interrumpido', fin = now() "
                                 "WHERE estado = 'ejecutando' AND id <> :i"), {"i": jid})
            conn.execute(sa.text("UPDATE mrp_solver_cola SET estado = 'ejecutando', inicio = now(), "
                                 "espera_s = :e WHERE id = :i"), {"e": round(espera), "i": jid})
            conn.commit()
        log.info(f"[COLA] {tipo}: turno del solver obtenido (esperó {espera:.0f} s)")
        try:
            yield jid
        except BaseException as e:
            if jid:
                estado = "terminado" if isinstance(e, SystemExit) and e.code in (0, None) else "error"
                conn.execute(sa.text("UPDATE mrp_solver_cola SET estado = :s, fin = now(), detalle = :d WHERE id = :i"),
                             {"s": estado, "d": f"{type(e).__name__}: {e}"[:500], "i": jid})
                conn.commit()
            raise
        else:
            if jid:
                conn.execute(sa.text("UPDATE mrp_solver_cola SET estado = 'terminado', fin = now() WHERE id = :i"), {"i": jid})
                conn.commit()
        finally:
            try:
                conn.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()
            except Exception:
                pass
    finally:
        conn.close()
        eng.dispose()


def _ocupante(conn) -> str:
    try:
        r = conn.execute(sa.text("""SELECT tipo, descripcion, inicio FROM mrp_solver_cola WHERE estado = 'ejecutando'
                                    ORDER BY inicio DESC LIMIT 1""")).first()
        conn.commit()
        return f"{r.tipo} ({r.descripcion}) desde {r.inicio:%H:%M}" if r else ""
    except Exception:
        conn.rollback()
        return ""


@router.get("/cola")
def ver_cola(limit: int = 30):
    with _engine.connect() as c:
        filas = [dict(r._mapping) for r in c.execute(sa.text(
            "SELECT * FROM mrp_solver_cola ORDER BY id DESC LIMIT :l"), {"l": max(1, min(limit, 200))})]
        libre = c.execute(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        if libre:
            c.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    ejec = next((f for f in filas if f["estado"] == "ejecutando"), None)
    return {"ocupado": not libre, "ejecutando": ejec,
            "en_cola": [f for f in filas if f["estado"] == "en_cola"], "historial": filas}
