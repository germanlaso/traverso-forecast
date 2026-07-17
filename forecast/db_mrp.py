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
    semana_emision  = Column(Date)                          # fecha lanzamiento sugerida MRP (informativo)
    semana_necesidad= Column(Date)                          # fecha entrada stock sugerida MRP (informativo)
    fecha_lanzamiento = Column(Date)                        # F3: fecha de lanzamiento real, parte de PK logica (sku, fecha_lanzamiento, linea)
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


def numero_of_tentativo(sku: str, fecha_lanzamiento: str, linea: str, year: int = None) -> str:
    """
    Numero tentativo determinista para ordenes NO aprobadas.
    F3 (12/05/2026): clave (sku, fecha_lanzamiento, linea) — antes era (sku, sn, se).
    Cambio motivado porque el optimizer parte producciones del mismo SKU en
    distintos dias dentro de la misma semana; la clave anterior colisionaba
    para todas esas OFTs (~43% de OFTs en h=4) generando bugs de aprobacion
    y render del frontend. Ver ESTADO_TECNICO_PROYECTO_12-05-26-tarde.md.

    Prefijo 'OFT' para distinguirlo de las definitivas (OF).
    """
    import hashlib
    y = year or datetime.now().year
    key = f"{sku}__{fecha_lanzamiento}__{linea}"
    h = int(hashlib.md5(key.encode()).hexdigest(), 16) % 99999 + 1
    return f"OFT-{y}-{h:05d}"


def next_numero_of_manual() -> str:
    """
    Correlativo para OF manuales: OFM-NNNNNN (6 dígitos, sin año).
    Prefijo OFM- separado: no colisiona con OF-YYYY-NNNNN ni OFT-.
    Calcula MAX+1 sobre mrp_ordenes. Suficiente para mono-usuario
    (marcha blanca); para multi-usuario, migrar a contador con lock.
    """
    with get_session() as session:
        row = session.execute(text("""
            SELECT COALESCE(MAX(CAST(SUBSTRING(numero_of FROM 5) AS INTEGER)), 0)
            FROM mrp_ordenes
            WHERE numero_of LIKE 'OFM-%'
        """)).fetchone()
        n = (row[0] or 0) + 1
    return f"OFM-{n:06d}"


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


def get_orden_by_key(sku: str, fecha_lanzamiento: str, linea: str) -> dict | None:
    """
    Busca una orden por su clave natural F3: (sku, fecha_lanzamiento, linea).
    Si existe, devuelve datos de la orden + datos de la ultima aprobacion (si la tiene).
    Acepta fecha_lanzamiento como str ISO 'YYYY-MM-DD' o como date.
    """
    with get_session() as session:
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
              AND o.fecha_lanzamiento = :fl
              AND COALESCE(o.linea, '') = COALESCE(:linea, '')
        """), {
            "sku": sku,
            "fl": fecha_lanzamiento,
            "linea": linea or "",
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


# ── Parámetros MRP en PostgreSQL ──────────────────────────────────────────────

def crear_tablas_params():
    """Crea las tablas de parámetros MRP si no existen."""
    with get_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS mrp_lineas (
                codigo          VARCHAR(20) PRIMARY KEY,
                nombre          VARCHAR(100),
                area            VARCHAR(100),
                turnos_dia      INTEGER     DEFAULT 1,
                horas_turno     FLOAT       DEFAULT 8,
                dias_semana     INTEGER     DEFAULT 5,
                velocidad_u_hr  FLOAT       DEFAULT 0,
                activa          BOOLEAN     DEFAULT TRUE,
                updated_at      TIMESTAMP   DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS mrp_sku_params (
                sku             VARCHAR(30) PRIMARY KEY,
                descripcion     VARCHAR(200),
                categoria       VARCHAR(100),
                tipo            VARCHAR(30),
                u_por_caja      INTEGER     DEFAULT 1,
                lead_time_sem   FLOAT       DEFAULT 1,
                ss_dias         INTEGER     DEFAULT 15,
                batch_min_u     INTEGER     DEFAULT 0,
                batch_mult_u    INTEGER     DEFAULT 1,
                cap_bodega_u    INTEGER     DEFAULT 999999,
                t_cambio_hrs    FLOAT       DEFAULT 0,
                linea_preferida VARCHAR(20) DEFAULT '',
                activo          BOOLEAN     DEFAULT TRUE,
                mto             BOOLEAN     DEFAULT FALSE,
                formato         VARCHAR(30) DEFAULT '',
                updated_at      TIMESTAMP   DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS mrp_sku_lineas (
                id               SERIAL PRIMARY KEY,
                sku              VARCHAR(30),
                linea            VARCHAR(20),
                preferida        BOOLEAN     DEFAULT FALSE,
                t_cambio_hrs     FLOAT       NOT NULL DEFAULT 0.0,
                factor_velocidad FLOAT       NOT NULL DEFAULT 1.0,
                UNIQUE(sku, linea)
            );
            -- Columnas agregadas post-creación (idempotente para BD existentes)
            ALTER TABLE mrp_sku_params ADD COLUMN IF NOT EXISTS mto     BOOLEAN     DEFAULT FALSE;
            ALTER TABLE mrp_sku_params ADD COLUMN IF NOT EXISTS formato VARCHAR(30) DEFAULT '';

            -- Informe de faltantes por quiebre (por fecha, SKU y cliente).
            CREATE TABLE IF NOT EXISTS mrp_faltantes (
                fecha            DATE        NOT NULL,
                sku              VARCHAR(30) NOT NULL,
                descripcion      VARCHAR(120) DEFAULT '',
                cod_cliente      VARCHAR(30) NOT NULL DEFAULT '',
                nom_cliente      VARCHAR(120) DEFAULT '',
                stock_ini_cj     NUMERIC(14,2) DEFAULT 0,
                programado_cj    NUMERIC(14,2) DEFAULT 0,
                no_entregado_cj  NUMERIC(14,2) DEFAULT 0,
                faltante_cj      NUMERIC(14,2) DEFAULT 0,
                stock_estimado   BOOLEAN     DEFAULT FALSE,
                causa            VARCHAR(20) DEFAULT '',
                updated_at       TIMESTAMP   DEFAULT NOW(),
                PRIMARY KEY (fecha, sku, cod_cliente)
            );
            ALTER TABLE mrp_faltantes ADD COLUMN IF NOT EXISTS causa VARCHAR(20) DEFAULT '';
            CREATE INDEX IF NOT EXISTS ix_faltantes_fecha ON mrp_faltantes (fecha);
            CREATE INDEX IF NOT EXISTS ix_faltantes_sku   ON mrp_faltantes (sku);
        """))
        session.commit()


def upsert_linea(linea: dict):
    """Inserta o actualiza una línea de producción."""
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_lineas
                (codigo, nombre, area, turnos_dia, horas_turno, dias_semana, velocidad_u_hr, activa, updated_at)
            VALUES
                (:codigo, :nombre, :area, :turnos_dia, :horas_turno, :dias_semana, :velocidad_u_hr, :activa, NOW())
            ON CONFLICT (codigo) DO UPDATE SET
                nombre         = EXCLUDED.nombre,
                area           = EXCLUDED.area,
                turnos_dia     = EXCLUDED.turnos_dia,
                horas_turno    = EXCLUDED.horas_turno,
                dias_semana    = EXCLUDED.dias_semana,
                velocidad_u_hr = EXCLUDED.velocidad_u_hr,
                activa         = EXCLUDED.activa,
                updated_at     = NOW()
        """), linea)
        session.commit()


def upsert_sku_linea(rec: dict):
    """Inserta o actualiza un registro de mrp_sku_lineas (par SKU-Línea).

    Espera dict con: sku, linea, t_cambio_hrs, preferida, factor_velocidad
    """
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_sku_lineas
                (sku, linea, t_cambio_hrs, preferida, factor_velocidad)
            VALUES
                (:sku, :linea, :t_cambio_hrs, :preferida, :factor_velocidad)
            ON CONFLICT (sku, linea) DO UPDATE SET
                t_cambio_hrs     = EXCLUDED.t_cambio_hrs,
                preferida        = EXCLUDED.preferida,
                factor_velocidad = EXCLUDED.factor_velocidad
        """), rec)
        session.commit()


def borrar_todas_sku_lineas():
    """Borra todos los registros de mrp_sku_lineas. Usado por migrate_params.py
    antes de re-importar para limpiar pares que ya no existan en el Excel."""
    with get_session() as session:
        session.execute(text("DELETE FROM mrp_sku_lineas"))
        session.commit()


def borrar_todas_lineas():
    """Borra todos los registros de mrp_lineas. Usado por migrate_params.py
    cuando se re-importa desde el Excel para evitar líneas zombies cuando
    cambian los códigos (ej. v1.2 L001/L002/S001/S002 → v1.3 Sachetera/L1Pet LV/L1Pet A)."""
    with get_session() as session:
        session.execute(text("DELETE FROM mrp_lineas"))
        session.commit()


# ── Faltantes por quiebre ─────────────────────────────────────────────────────

def upsert_faltantes(filas: list[dict]):
    """Inserta/actualiza filas de mrp_faltantes en batch. Idempotente por PK
    (fecha, sku, cod_cliente): re-correr un día pisa sus filas sin duplicar.
    Cada fila: fecha(str YYYY-MM-DD o date), sku, descripcion, cod_cliente,
    nom_cliente, stock_ini_cj, programado_cj, no_entregado_cj, faltante_cj,
    stock_estimado."""
    if not filas:
        return 0
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_faltantes
                (fecha, sku, descripcion, cod_cliente, nom_cliente, stock_ini_cj,
                 programado_cj, no_entregado_cj, faltante_cj, stock_estimado, causa, updated_at)
            VALUES
                (:fecha, :sku, :descripcion, :cod_cliente, :nom_cliente, :stock_ini_cj,
                 :programado_cj, :no_entregado_cj, :faltante_cj, :stock_estimado, :causa, NOW())
            ON CONFLICT (fecha, sku, cod_cliente) DO UPDATE SET
                descripcion     = EXCLUDED.descripcion,
                nom_cliente     = EXCLUDED.nom_cliente,
                stock_ini_cj    = EXCLUDED.stock_ini_cj,
                programado_cj   = EXCLUDED.programado_cj,
                no_entregado_cj = EXCLUDED.no_entregado_cj,
                faltante_cj     = EXCLUDED.faltante_cj,
                stock_estimado  = EXCLUDED.stock_estimado,
                causa           = EXCLUDED.causa,
                updated_at      = NOW()
        """), filas)
        session.commit()
    return len(filas)


def borrar_faltantes_rango(desde: str, hasta: str):
    """Borra faltantes en [desde, hasta] (fechas YYYY-MM-DD). Útil si se quiere
    recalcular un rango desde cero en vez de upsert (p.ej. si cambió la lógica)."""
    with get_session() as session:
        session.execute(text("DELETE FROM mrp_faltantes WHERE fecha BETWEEN :d1 AND :d2"),
                        {"d1": desde, "d2": hasta})
        session.commit()


def get_faltantes_por_fecha(fecha: str) -> list[dict]:
    """Faltantes de un día (YYYY-MM-DD), ordenados por faltante desc."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT fecha, sku, descripcion, cod_cliente, nom_cliente, stock_ini_cj,
                   programado_cj, no_entregado_cj, faltante_cj, stock_estimado, causa
            FROM mrp_faltantes WHERE fecha = :f
            ORDER BY faltante_cj DESC, sku
        """), {"f": fecha}).mappings().all()
    return [dict(r) for r in rows]


def get_faltantes_evolutivo(sku: str | None = None,
                            cod_cliente: str | None = None,
                            desde: str | None = None,
                            hasta: str | None = None) -> list[dict]:
    """Serie diaria de faltante total (cajas), filtrable por SKU, cliente y rango
    de fechas [desde, hasta] (YYYY-MM-DD). Agrega por fecha."""
    cond = []
    params: dict = {}
    if sku:
        cond.append("sku = :sku"); params["sku"] = sku
    if cod_cliente:
        cond.append("cod_cliente = :cc"); params["cc"] = cod_cliente
    if desde:
        cond.append("fecha >= :d1"); params["d1"] = desde
    if hasta:
        cond.append("fecha <= :d2"); params["d2"] = hasta
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    with get_session() as session:
        rows = session.execute(text(f"""
            SELECT fecha, SUM(faltante_cj) AS faltante_cj
            FROM mrp_faltantes {where}
            GROUP BY fecha ORDER BY fecha
        """), params).mappings().all()
    return [dict(r) for r in rows]


def get_faltantes_rango() -> dict:
    """Rango de fechas disponibles en mrp_faltantes (para el selector del dashboard)."""
    with get_session() as session:
        r = session.execute(text(
            "SELECT MIN(fecha) AS min_fecha, MAX(fecha) AS max_fecha, "
            "COUNT(DISTINCT fecha) AS dias FROM mrp_faltantes"
        )).mappings().first()
    return {
        "min_fecha": r["min_fecha"].isoformat() if r and r["min_fecha"] else None,
        "max_fecha": r["max_fecha"].isoformat() if r and r["max_fecha"] else None,
        "dias":      (r["dias"] if r else 0),
    }


def upsert_sku_params(p: dict):
    """Inserta o actualiza parámetros de un SKU."""
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_sku_params
                (sku, descripcion, categoria, tipo, u_por_caja, lead_time_sem, ss_dias,
                 batch_min_u, batch_mult_u, cap_bodega_u, t_cambio_hrs, linea_preferida, activo, mto, formato, updated_at)
            VALUES
                (:sku, :descripcion, :categoria, :tipo, :u_por_caja, :lead_time_sem, :ss_dias,
                 :batch_min_u, :batch_mult_u, :cap_bodega_u, :t_cambio_hrs, :linea_preferida, :activo, :mto, :formato, NOW())
            ON CONFLICT (sku) DO UPDATE SET
                descripcion     = EXCLUDED.descripcion,
                categoria       = EXCLUDED.categoria,
                tipo            = EXCLUDED.tipo,
                u_por_caja      = EXCLUDED.u_por_caja,
                lead_time_sem   = EXCLUDED.lead_time_sem,
                ss_dias         = EXCLUDED.ss_dias,
                batch_min_u     = EXCLUDED.batch_min_u,
                batch_mult_u    = EXCLUDED.batch_mult_u,
                cap_bodega_u    = EXCLUDED.cap_bodega_u,
                t_cambio_hrs    = EXCLUDED.t_cambio_hrs,
                linea_preferida = EXCLUDED.linea_preferida,
                activo          = EXCLUDED.activo,
                mto             = EXCLUDED.mto,
                formato         = EXCLUDED.formato,
                updated_at      = NOW()
        """), p)
        session.commit()


def get_all_lineas() -> list[dict]:
    """Retorna todas las líneas activas desde PostgreSQL."""
    with get_session() as session:
        rows = session.execute(text(
            "SELECT * FROM mrp_lineas WHERE activa = TRUE ORDER BY codigo"
        )).fetchall()
        return [dict(r._mapping) for r in rows]


def get_all_sku_params() -> list[dict]:
    """Retorna todos los parámetros de SKU activos desde PostgreSQL."""
    with get_session() as session:
        rows = session.execute(text(
            "SELECT * FROM mrp_sku_params WHERE activo = TRUE ORDER BY sku"
        )).fetchall()
        return [dict(r._mapping) for r in rows]


def update_sku_param(sku: str, campos: dict) -> dict:
    """Actualiza campos específicos de un SKU."""
    allowed = {"lead_time_sem","ss_dias","batch_min_u","batch_mult_u",
               "cap_bodega_u","t_cambio_hrs","linea_preferida","activo"}
    updates = {k: v for k, v in campos.items() if k in allowed}
    if not updates:
        return {}
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["sku"] = sku
    updates["updated_at"] = "NOW()"
    with get_session() as session:
        session.execute(text(
            f"UPDATE mrp_sku_params SET {set_clause}, updated_at = NOW() WHERE sku = :sku"
        ), updates)
        session.commit()
    return updates


def update_linea(codigo: str, campos: dict) -> dict:
    """Actualiza campos específicos de una línea."""
    allowed = {"nombre","turnos_dia","horas_turno","dias_semana","velocidad_u_hr","activa"}
    updates = {k: v for k, v in campos.items() if k in allowed}
    if not updates:
        return {}
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["codigo"] = codigo
    with get_session() as session:
        session.execute(text(
            f"UPDATE mrp_lineas SET {set_clause}, updated_at = NOW() WHERE codigo = :codigo"
        ), updates)
        session.commit()
    return updates


def get_all_sku_lineas() -> list:
    """Retorna todos los registros de mrp_sku_lineas (SKU → Linea con t_cambio_hrs
    y factor_velocidad)."""
    from sqlalchemy import text as _text
    with get_session() as session:
        result = session.execute(_text(
            "SELECT sku, linea, t_cambio_hrs, preferida, factor_velocidad "
            "FROM mrp_sku_lineas ORDER BY sku, linea"
        ))
        rows = result.fetchall()
        return [
            {"sku": str(r[0]), "linea": str(r[1]),
             "t_cambio_hrs": float(r[2] or 0), "preferida": bool(r[3]),
             "factor_velocidad": float(r[4] or 1.0)}
            for r in rows
        ]


# ============================================================
# mrp_setup_matrix (introducida v1.3 — preparación para F2)
# ============================================================

def get_setup_matrix(linea: str | None = None,
                     sku_desde: str | None = None,
                     sku_hasta: str | None = None) -> list[dict]:
    """Lee filas de la matriz, opcionalmente filtradas."""
    sql = ("SELECT sku_desde, sku_hasta, linea, tiempo_horas "
           "FROM mrp_setup_matrix WHERE 1=1")
    params: dict = {}
    if linea:
        sql += " AND linea = :linea"
        params["linea"] = linea
    if sku_desde:
        sql += " AND sku_desde = :sku_desde"
        params["sku_desde"] = sku_desde
    if sku_hasta:
        sql += " AND sku_hasta = :sku_hasta"
        params["sku_hasta"] = sku_hasta
    sql += " ORDER BY linea, sku_desde, sku_hasta"

    with get_session() as session:
        result = session.execute(text(sql), params)
        rows = result.fetchall()
        return [
            {"sku_desde": str(r[0]), "sku_hasta": str(r[1]),
             "linea": str(r[2]), "tiempo_horas": float(r[3])}
            for r in rows
        ]


def get_setup_time(sku_desde: str, sku_hasta: str, linea: str) -> float | None:
    """
    Devuelve el tiempo de setup en horas.
    Convención v1.3: si sku_desde == sku_hasta, devuelve 0 (auto-transición).
    Si la fila no existe, devuelve None — el caller decide qué hacer
    (por ejemplo, en F2: alerta de configuración).
    """
    if sku_desde == sku_hasta:
        return 0.0

    with get_session() as session:
        result = session.execute(text(
            "SELECT tiempo_horas FROM mrp_setup_matrix "
            "WHERE sku_desde = :sku_desde AND sku_hasta = :sku_hasta AND linea = :linea"
        ), {"sku_desde": sku_desde, "sku_hasta": sku_hasta, "linea": linea})
        row = result.fetchone()
        return float(row[0]) if row else None


def upsert_setup_entry(sku_desde: str, sku_hasta: str, linea: str,
                       tiempo_horas: float) -> None:
    """Insert o update de una fila."""
    with get_session() as session:
        session.execute(text(
            "INSERT INTO mrp_setup_matrix (sku_desde, sku_hasta, linea, tiempo_horas, updated_at) "
            "VALUES (:sku_desde, :sku_hasta, :linea, :tiempo_horas, NOW()) "
            "ON CONFLICT (sku_desde, sku_hasta, linea) "
            "DO UPDATE SET tiempo_horas = EXCLUDED.tiempo_horas, updated_at = NOW()"
        ), {"sku_desde": sku_desde, "sku_hasta": sku_hasta,
            "linea": linea, "tiempo_horas": float(tiempo_horas)})
        session.commit()


def borrar_toda_setup_matrix() -> None:
    """Limpia la tabla. Usado por la migración inicial."""
    with get_session() as session:
        session.execute(text("DELETE FROM mrp_setup_matrix"))
        session.commit()
