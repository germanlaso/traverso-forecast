"""
db_mrp.py — Base de datos PostgreSQL para el sistema MRP · Traverso S.A.

Tablas:
  mrp_ordenes       — todas las órdenes generadas (sugeridas + aprobadas)
  mrp_aprobaciones  — historial de aprobaciones con usuario y fechas reales
  mrp_contador_of   — correlativo anual de números OF
"""

import logging
import os
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import (
    create_engine, text,
    Column, Integer, String, Numeric, Date, DateTime, Text, Boolean,
    UniqueConstraint, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger(__name__)

# ── Conexión ───────────────────────────────────────────────────────────────────
MRP_DB_URL = os.environ.get(
    "MRP_DB_URL",
    "postgresql://mrp_user:mrp_traverso_2026@localhost:5433/mrp"
)

engine = create_engine(MRP_DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ── Modelos ORM ────────────────────────────────────────────────────────────────

class MrpOrden(Base):
    __tablename__ = "mrp_ordenes"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    numero_of       = Column(String(20), unique=True, nullable=False, index=True)
    sku             = Column(String(20), nullable=False, index=True)
    descripcion     = Column(Text)
    tipo            = Column(String(20))                    # PRODUCCION/MAQUILA/IMPORTACION
    semana_emision  = Column(Date)                          # fecha lanzamiento sugerida MRP
    semana_necesidad= Column(Date)                          # fecha entrada stock sugerida MRP
    cantidad_sugerida_cj = Column(Numeric(12, 2))
    cantidad_sugerida_u  = Column(Numeric(12, 2))
    u_por_caja      = Column(Numeric(8, 2), default=1)
    linea           = Column(String(20))
    alerta          = Column(Text)
    motivo          = Column(Text)                          # FC:x SS:x Stock:x Neta:x
    horizonte_sem   = Column(Integer)
    created_at      = Column(DateTime, default=datetime.now)
    updated_at      = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class MrpAprobacion(Base):
    __tablename__ = "mrp_aprobaciones"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    numero_of              = Column(String(20), ForeignKey("mrp_ordenes.numero_of"), nullable=False, index=True)
    sku                    = Column(String(20), nullable=False)
    cantidad_real_cj       = Column(Numeric(12, 2))
    cantidad_real_u        = Column(Numeric(12, 2))
    fecha_lanzamiento_real = Column(Date)
    fecha_entrada_real     = Column(Date)
    responsable            = Column(String(100))
    comentario             = Column(Text)
    estado                 = Column(String(20), default="APROBADA")  # APROBADA / CANCELADA / MODIFICADA
    version                = Column(Integer, default=1)              # historial de modificaciones
    created_at             = Column(DateTime, default=datetime.now)


class MrpContadorOf(Base):
    __tablename__ = "mrp_contador_of"

    año     = Column(Integer, primary_key=True)
    ultimo  = Column(Integer, default=0)


# ── Inicialización ─────────────────────────────────────────────────────────────

def init_db():
    """Crea las tablas si no existen. Idempotente."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("[MRP_DB] Tablas inicializadas correctamente")
    except Exception as e:
        logger.error(f"[MRP_DB] Error inicializando tablas: {e}")
        raise


@contextmanager
def get_session() -> Session:
    """Context manager para sesiones de base de datos."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Correlativo OF ─────────────────────────────────────────────────────────────

def next_numero_of(year: int = None) -> str:
    """
    Genera el próximo número correlativo OF-YYYY-NNNNN.
    Thread-safe mediante FOR UPDATE en PostgreSQL.
    """
    y = year or datetime.now().year
    with get_session() as session:
        # Upsert atómico con lock
        session.execute(text("""
            INSERT INTO mrp_contador_of (año, ultimo)
            VALUES (:y, 1)
            ON CONFLICT (año) DO UPDATE
            SET ultimo = mrp_contador_of.ultimo + 1
        """), {"y": y})
        result = session.execute(
            text("SELECT ultimo FROM mrp_contador_of WHERE año = :y"), {"y": y}
        ).fetchone()
        n = result[0]
    return f"OF-{y}-{n:05d}"


def numero_of_tentativo(sku: str, semana_necesidad: str, semana_emision: str, year: int = None) -> str:
    """
    Número tentativo determinista para órdenes NO aprobadas.
    Basado en hash del key — siempre el mismo para la misma orden.
    Prefijo 'OFT' para distinguirlo de las definitivas (OF).
    """
    import hashlib
    y = year or datetime.now().year
    key = f"{sku}__{semana_necesidad}__{semana_emision}"
    h = int(hashlib.md5(key.encode()).hexdigest(), 16) % 99999 + 1
    return f"OFT-{y}-{h:05d}"


# ── CRUD Órdenes ───────────────────────────────────────────────────────────────

def upsert_orden(data: dict) -> MrpOrden:
    """
    Crea o actualiza una orden en mrp_ordenes.
    Si ya existe el numero_of, actualiza los campos.
    """
    with get_session() as session:
        orden = session.query(MrpOrden).filter_by(numero_of=data["numero_of"]).first()
        if orden:
            for k, v in data.items():
                if hasattr(orden, k):
                    setattr(orden, k, v)
            orden.updated_at = datetime.now()
        else:
            orden = MrpOrden(**{k: v for k, v in data.items() if hasattr(MrpOrden, k)})
            session.add(orden)
        session.flush()
        session.refresh(orden)
        return orden


def get_orden_by_key(sku: str, semana_necesidad: str, semana_emision: str) -> dict | None:
    """Busca una orden por su clave natural (sku + fechas)."""
    with get_session() as session:
        # Buscar la aprobación más reciente para este par sku+fechas
        result = session.execute(text("""
            SELECT o.*, a.cantidad_real_cj, a.cantidad_real_u,
                   a.fecha_lanzamiento_real, a.fecha_entrada_real,
                   a.responsable, a.comentario, a.estado, a.version,
                   a.created_at as aprobado_en
            FROM mrp_ordenes o
            LEFT JOIN mrp_aprobaciones a ON o.numero_of = a.numero_of
                AND a.id = (
                    SELECT MAX(id) FROM mrp_aprobaciones
                    WHERE numero_of = o.numero_of
                )
            WHERE o.sku = :sku
              AND o.semana_necesidad = :sn
              AND o.semana_emision = :se
        """), {
            "sku": sku,
            "sn": semana_necesidad,
            "se": semana_emision
        }).fetchone()
        return dict(result._mapping) if result else None


# ── CRUD Aprobaciones ──────────────────────────────────────────────────────────

def aprobar_orden_db(numero_of: str, data: dict) -> dict:
    """
    Registra una aprobación. Si ya existe, crea una nueva versión (historial).
    """
    with get_session() as session:
        # Ver versión actual
        ultima = session.execute(text("""
            SELECT MAX(version) as v FROM mrp_aprobaciones WHERE numero_of = :nof
        """), {"nof": numero_of}).fetchone()
        version = (ultima.v or 0) + 1

        # Si había aprobaciones anteriores, marcarlas como historial
        if version > 1:
            session.execute(text("""
                UPDATE mrp_aprobaciones SET estado = 'MODIFICADA'
                WHERE numero_of = :nof AND estado = 'APROBADA'
            """), {"nof": numero_of})

        aprobacion = MrpAprobacion(
            numero_of              = numero_of,
            sku                    = data["sku"],
            cantidad_real_cj       = data.get("cantidad_real_cj"),
            cantidad_real_u        = data.get("cantidad_real_u"),
            fecha_lanzamiento_real = data.get("fecha_lanzamiento_real") or data.get("semana_emision"),
            fecha_entrada_real     = data.get("fecha_entrada_real") or data.get("semana_necesidad"),
            responsable            = data.get("responsable"),
            comentario             = data.get("comentario", ""),
            estado                 = "APROBADA",
            version                = version,
        )
        session.add(aprobacion)
        session.flush()
        session.refresh(aprobacion)

        return {
            "numero_of":   numero_of,
            "version":     version,
            "estado":      "APROBADA",
            "created_at":  aprobacion.created_at.isoformat(),
        }


def cancelar_orden_db(numero_of: str) -> bool:
    """Marca todas las aprobaciones de una orden como CANCELADA."""
    with get_session() as session:
        n = session.execute(text("""
            UPDATE mrp_aprobaciones SET estado = 'CANCELADA'
            WHERE numero_of = :nof AND estado = 'APROBADA'
        """), {"nof": numero_of}).rowcount
    return n > 0


def listar_aprobadas_db() -> list[dict]:
    """Retorna todas las órdenes con su última aprobación activa."""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                o.numero_of, o.sku, o.descripcion, o.tipo,
                o.semana_emision, o.semana_necesidad,
                o.cantidad_sugerida_cj, o.linea, o.alerta, o.motivo,
                a.cantidad_real_cj, a.cantidad_real_u,
                a.fecha_lanzamiento_real, a.fecha_entrada_real,
                a.responsable, a.comentario, a.version,
                a.created_at as aprobado_en
            FROM mrp_ordenes o
            INNER JOIN mrp_aprobaciones a ON o.numero_of = a.numero_of
            WHERE a.estado = 'APROBADA'
              AND a.id = (
                  SELECT MAX(id) FROM mrp_aprobaciones
                  WHERE numero_of = o.numero_of AND estado = 'APROBADA'
              )
            ORDER BY a.created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in result]


def historial_aprobaciones_db(numero_of: str) -> list[dict]:
    """Retorna el historial completo de aprobaciones de una orden."""
    with get_session() as session:
        result = session.execute(text("""
            SELECT * FROM mrp_aprobaciones
            WHERE numero_of = :nof
            ORDER BY version DESC
        """), {"nof": numero_of}).fetchall()
        return [dict(r._mapping) for r in result]
