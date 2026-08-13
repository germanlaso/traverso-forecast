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
                granel_grupo    VARCHAR(20) NOT NULL DEFAULT '',
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
            ALTER TABLE mrp_sku_params ADD COLUMN IF NOT EXISTS granel_grupo VARCHAR(20) NOT NULL DEFAULT '';

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

            CREATE TABLE IF NOT EXISTS mrp_vu_cliente_sku (
                cod_cliente   VARCHAR(30)  NOT NULL,
                sku           VARCHAR(30)  NOT NULL,
                descripcion   VARCHAR(120) DEFAULT '',
                min_dias      INTEGER      NOT NULL,
                min_meses     INTEGER,
                pct_derivado  NUMERIC(6,4),
                updated_at    TIMESTAMP    DEFAULT NOW(),
                PRIMARY KEY (cod_cliente, sku)
            );

            -- Explicaciones de faltantes (por SKU agregado y fecha).
            -- Independiente de mrp_faltantes para sobrevivir a los recálculos de ventana.
            CREATE TABLE IF NOT EXISTS mrp_faltantes_explicaciones (
                sku          VARCHAR(30)  NOT NULL,
                fecha        DATE         NOT NULL,
                explicacion  TEXT         NOT NULL DEFAULT '',
                autor        VARCHAR(120) DEFAULT '',
                congelada    BOOLEAN      NOT NULL DEFAULT FALSE,
                created_at   TIMESTAMP    DEFAULT NOW(),
                updated_at   TIMESTAMP    DEFAULT NOW(),
                PRIMARY KEY (sku, fecha)
            );
            CREATE INDEX IF NOT EXISTS ix_faltantes_expl_fecha
                ON mrp_faltantes_explicaciones (fecha);

            -- ── V6 (29-07) Campanas de linea ─────────────────────────────────
            -- Reglas por recurso (que dimension y modos maneja) y calendario
            -- semanal con pins del planificador. `recurso` generaliza: hoy
            -- GRANEL_SALSAS (estado de planta), a futuro una linea por formato.
            CREATE TABLE IF NOT EXISTS mrp_campana_reglas (
                recurso            VARCHAR(40)  PRIMARY KEY,
                dimension          VARCHAR(30)  NOT NULL,
                modos              JSONB        NOT NULL DEFAULT '[]'::jsonb,
                max_modos_semana   INTEGER      NOT NULL DEFAULT 1,
                peso_cambio        INTEGER      NOT NULL DEFAULT 0,
                activo             BOOLEAN      NOT NULL DEFAULT TRUE,
                updated_at         TIMESTAMP    DEFAULT NOW()
            );

            -- semana = inicio ISO de la semana (mismo criterio que
            -- calendario.semana_iso_inicio). modo vacio o "ninguno" = semana sin
            -- granel. Solo las filas con fijado=TRUE son pins duros; el resto es
            -- registro de lo que propuso el solver.
            CREATE TABLE IF NOT EXISTS mrp_campana_calendario (
                recurso     VARCHAR(40)  NOT NULL,
                semana      DATE         NOT NULL,
                modo        VARCHAR(30)  NOT NULL DEFAULT '',
                fijado      BOOLEAN      NOT NULL DEFAULT FALSE,
                autor       VARCHAR(120) DEFAULT '',
                updated_at  TIMESTAMP    DEFAULT NOW(),
                PRIMARY KEY (recurso, semana)
            );
            CREATE INDEX IF NOT EXISTS ix_campana_cal_semana
                ON mrp_campana_calendario (semana);

            -- ── V6 (30-07) Vigía de OV: estado de las alertas ya notificadas ──
            -- Anti-spam: una fila por tramo de quiebre (sku, desde). Si el tramo ya
            -- fue notificado no se repite, salvo que empeore materialmente o escale
            -- a CRITICO. Sin esto un quiebre que dura 4 días generaría 40 correos.
            CREATE TABLE IF NOT EXISTS mrp_vigia_alertas (
                sku             VARCHAR(30) NOT NULL,
                desde           DATE        NOT NULL,
                hasta           DATE,
                clase           VARCHAR(20) NOT NULL DEFAULT '',
                deficit_max_cj  NUMERIC     NOT NULL DEFAULT 0,
                plan_id         BIGINT,
                n_avisos        INTEGER     NOT NULL DEFAULT 1,
                alertado_at     TIMESTAMP   DEFAULT NOW(),
                PRIMARY KEY (sku, desde)
            );

            -- Eventos comerciales que distorsionan el forecast.
            --
            -- UNA FILA = UN PERIODO en fechas naturales. El usuario NO piensa en
            -- domingos ni en semanas ISO: eventos.py snapea con
            -- calendario.semana_viz_inicio().
            --
            -- `etiqueta` agrupa filas en un MISMO regresor: filas con igual
            -- (nombre, sku, etiqueta) se unen en una sola columna binaria;
            -- etiquetas distintas generan regresores SEPARADOS, cada uno con su
            -- propio coeficiente. Medido el 10-08-2026 sobre 250010495: un solo
            -- regresor sobre todo el evento sobrepredice oct-nov 2025 en +86%
            -- (holdout out-of-sample); separado en dos fases de intensidad
            -- ('suave' ago-sep, 'fuerte' oct-dic) baja a +17%. Sin evento: +402%.
            --
            -- `tipo`: 'pasado'  -> regresor binario, Prophet estima el coeficiente.
            --         'futuro'  -> NO es un regresor. Un regresor cuya columna es
            --                      cero en todo el entrenamiento no es
            --                      identificable y Prophet lo encoge a ~0, asi
            --                      que un evento futuro no tendria ningun efecto.
            --                      Requiere ajuste post-hoc sobre la serie de
            --                      forecast (Fase 2). Hoy eventos.py los IGNORA.
            --
            -- `unidad` es OBLIGATORIA cuando hay magnitud: la confusion
            -- cajas/unidades ya costo un diagnostico entero el 05-08.
            CREATE TABLE IF NOT EXISTS mrp_eventos (
                id              BIGSERIAL    PRIMARY KEY,
                nombre          VARCHAR(100) NOT NULL,
                sku             VARCHAR(30)  NOT NULL,
                etiqueta        VARCHAR(40)  NOT NULL DEFAULT 'base',
                fecha_desde     DATE         NOT NULL,
                fecha_hasta     DATE         NOT NULL,
                tipo            VARCHAR(20)  NOT NULL DEFAULT 'pasado',
                magnitud        NUMERIC,
                unidad          VARCHAR(4),
                tipo_magnitud   VARCHAR(4)   NOT NULL DEFAULT 'abs',
                activo          BOOLEAN      NOT NULL DEFAULT TRUE,
                nota            TEXT,
                created_at      TIMESTAMP    DEFAULT NOW(),
                CONSTRAINT mrp_eventos_rango
                    CHECK (fecha_hasta >= fecha_desde),
                CONSTRAINT mrp_eventos_tipo
                    CHECK (tipo IN ('pasado', 'futuro')),
                CONSTRAINT mrp_eventos_unidad
                    CHECK (unidad IS NULL OR unidad IN ('cj', 'u')),
                CONSTRAINT mrp_eventos_tipo_magnitud
                    CHECK (tipo_magnitud IN ('abs', 'pct')),
                -- un evento futuro sin magnitud+unidad no se puede aplicar
                CONSTRAINT mrp_eventos_futuro_exige_magnitud
                    CHECK (tipo <> 'futuro'
                           OR (magnitud IS NOT NULL AND unidad IS NOT NULL)),
                -- una magnitud sin unidad es la trampa cajas/unidades
                CONSTRAINT mrp_eventos_magnitud_exige_unidad
                    CHECK (magnitud IS NULL OR unidad IS NOT NULL)
            );

            CREATE INDEX IF NOT EXISTS ix_mrp_eventos_sku
                ON mrp_eventos (sku, activo);

            -- `linea` NULL = estado de planta (granel). Con valor = campana
            -- de esa linea (formato), y el acople aplica a la produccion EN
            -- esa linea, no al linea_preferida del SKU.
            ALTER TABLE mrp_campana_reglas
                ADD COLUMN IF NOT EXISTS linea VARCHAR(40);

            INSERT INTO mrp_campana_reglas
                (recurso, dimension, modos, max_modos_semana, peso_cambio, activo, linea)
            VALUES
                ('GRANEL_SALSAS', 'granel_grupo',
                 '["ketchup","mostaza"]'::jsonb, 1, 0, TRUE, NULL),
                ('L1PET_LV', 'formato',
                 '["1000","500"]'::jsonb, 1, 0, TRUE, 'L1Pet LV')
            ON CONFLICT (recurso) DO NOTHING;
        """))
        session.commit()

    # Conciliación OF/TR (Fase 1): tabla independiente, se crea aquí también.
    crear_tablas_of_sap()


# ─── V6 Campanas de linea ────────────────────────────────────────────────────

# ─── V6 Vigía de OV ──────────────────────────────────────────────────────────

def get_vigia_alertas() -> dict:
    """{(sku, desde_iso): fila} de las alertas ya notificadas."""
    with get_session() as session:
        rows = session.execute(text("SELECT * FROM mrp_vigia_alertas")).fetchall()
    out = {}
    for r in rows:
        d = dict(r._mapping)
        k = (str(d["sku"]), d["desde"].isoformat() if hasattr(d["desde"], "isoformat")
             else str(d["desde"]))
        out[k] = d
    return out


def upsert_vigia_alerta(sku: str, desde, hasta, clase: str,
                        deficit_max_cj: float, plan_id=None) -> None:
    """Registra (o actualiza) el estado de un tramo notificado."""
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_vigia_alertas
                (sku, desde, hasta, clase, deficit_max_cj, plan_id, n_avisos, alertado_at)
            VALUES (:sku, :desde, :hasta, :clase, :def_cj, :plan_id, 1, NOW())
            ON CONFLICT (sku, desde) DO UPDATE SET
                hasta          = EXCLUDED.hasta,
                clase          = EXCLUDED.clase,
                deficit_max_cj = EXCLUDED.deficit_max_cj,
                plan_id        = EXCLUDED.plan_id,
                n_avisos       = mrp_vigia_alertas.n_avisos + 1,
                alertado_at    = NOW()
        """), {"sku": sku, "desde": desde, "hasta": hasta, "clase": clase,
               "def_cj": float(deficit_max_cj or 0), "plan_id": plan_id})
        session.commit()


def limpiar_vigia_alertas(dias: int = 30) -> int:
    """Borra tramos cuyo `hasta` ya pasó hace más de `dias`. Devuelve filas borradas."""
    with get_session() as session:
        r = session.execute(text(
            "DELETE FROM mrp_vigia_alertas "
            "WHERE COALESCE(hasta, desde) < CURRENT_DATE - :d"), {"d": dias})
        session.commit()
        return r.rowcount or 0


# ─── Eventos comerciales (forecast) ──────────────────────────────────────────

def get_eventos(sku: str | None = None, solo_activos: bool = True,
                tipo: str | None = None) -> list[dict]:
    """Filas crudas de mrp_eventos, sin expandir a domingos.

    La expansion a domingos y el armado de regresores es de eventos.py; esto es
    solo acceso a datos. Orden estable por (sku, nombre, etiqueta, fecha_desde)
    para que el nombre del regresor sea deterministico.
    """
    q = "SELECT * FROM mrp_eventos WHERE 1=1"
    p: dict = {}
    if sku:
        q += " AND sku = :sku"
        p["sku"] = str(sku)
    if solo_activos:
        q += " AND activo = TRUE"
    if tipo:
        q += " AND tipo = :tipo"
        p["tipo"] = tipo
    q += " ORDER BY sku, nombre, etiqueta, fecha_desde"
    with get_session() as session:
        rows = session.execute(text(q), p).fetchall()
        return [dict(r._mapping) for r in rows]


def upsert_evento(nombre: str, sku: str, fecha_desde, fecha_hasta,
                  etiqueta: str = "base", tipo: str = "pasado",
                  magnitud=None, unidad: str | None = None,
                  tipo_magnitud: str = "abs", activo: bool = True,
                  nota: str | None = None) -> int:
    """Inserta una fila de evento. Devuelve el id."""
    with get_session() as session:
        r = session.execute(text("""
            INSERT INTO mrp_eventos
                (nombre, sku, etiqueta, fecha_desde, fecha_hasta, tipo,
                 magnitud, unidad, tipo_magnitud, activo, nota)
            VALUES
                (:nombre, :sku, :etiqueta, :desde, :hasta, :tipo,
                 :magnitud, :unidad, :tmag, :activo, :nota)
            RETURNING id
        """), {"nombre": nombre, "sku": str(sku), "etiqueta": etiqueta,
               "desde": fecha_desde, "hasta": fecha_hasta, "tipo": tipo,
               "magnitud": magnitud, "unidad": unidad,
               "tmag": tipo_magnitud, "activo": activo, "nota": nota})
        new_id = r.scalar()
        session.commit()
        return int(new_id)


def set_evento_activo(nombre: str, sku: str, activo: bool) -> int:
    """Activa o desactiva todas las filas de un (nombre, sku). Devuelve filas tocadas.

    Desactivar es la operacion SEGURA para sacar un evento de produccion: la fila
    queda para auditoria y cargar_eventos_activos() deja de devolverla, asi que el
    cron vuelve al comportamiento previo sin borrar historia.
    """
    with get_session() as session:
        r = session.execute(text(
            "UPDATE mrp_eventos SET activo = :act "
            "WHERE nombre = :nombre AND sku = :sku"),
            {"act": bool(activo), "nombre": nombre, "sku": str(sku)})
        session.commit()
        return r.rowcount or 0


def borrar_eventos(nombre: str, sku: str) -> int:
    """Borra todas las filas de un (nombre, sku). Para recarga idempotente."""
    with get_session() as session:
        r = session.execute(text(
            "DELETE FROM mrp_eventos WHERE nombre = :nombre AND sku = :sku"),
            {"nombre": nombre, "sku": str(sku)})
        session.commit()
        return r.rowcount or 0


def get_campana_reglas() -> list[dict]:
    """Reglas de campana activas (una por recurso)."""
    with get_session() as session:
        rows = session.execute(text(
            "SELECT * FROM mrp_campana_reglas WHERE activo = TRUE ORDER BY recurso"
        )).fetchall()
        return [dict(r._mapping) for r in rows]


def get_campana_calendario(recurso: str | None = None,
                           desde=None, hasta=None) -> list[dict]:
    """Calendario de campana. Filtra por recurso y rango de semanas si se indica."""
    q = "SELECT * FROM mrp_campana_calendario WHERE 1=1"
    p: dict = {}
    if recurso:
        q += " AND recurso = :recurso"; p["recurso"] = recurso
    if desde:
        q += " AND semana >= :desde";   p["desde"] = desde
    if hasta:
        q += " AND semana <= :hasta";   p["hasta"] = hasta
    q += " ORDER BY recurso, semana"
    with get_session() as session:
        rows = session.execute(text(q), p).fetchall()
        return [dict(r._mapping) for r in rows]


def upsert_campana_pin(recurso: str, semana, modo: str,
                       fijado: bool = True, autor: str = "") -> dict:
    """Fija (o registra) el modo de una semana. modo vacio = sin granel."""
    rec = {"recurso": recurso, "semana": semana,
           "modo": (modo or "").strip().lower(),
           "fijado": bool(fijado), "autor": autor or ""}
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_campana_calendario
                (recurso, semana, modo, fijado, autor, updated_at)
            VALUES (:recurso, :semana, :modo, :fijado, :autor, NOW())
            ON CONFLICT (recurso, semana) DO UPDATE SET
                modo       = EXCLUDED.modo,
                fijado     = EXCLUDED.fijado,
                autor      = EXCLUDED.autor,
                updated_at = NOW()
        """), rec)
        session.commit()
    return rec


def delete_campana_pin(recurso: str, semana) -> int:
    """Suelta una semana (borra el pin). Devuelve filas borradas."""
    with get_session() as session:
        r = session.execute(text(
            "DELETE FROM mrp_campana_calendario "
            "WHERE recurso = :recurso AND semana = :semana"
        ), {"recurso": recurso, "semana": semana})
        session.commit()
        return r.rowcount or 0


def get_campana_pins_dict(recurso: str = "GRANEL_SALSAS") -> dict:
    """{semana_iso: modo} SOLO de los pins duros. Consumido por el optimizer."""
    out = {}
    for row in get_campana_calendario(recurso=recurso):
        if row.get("fijado"):
            sem = row["semana"]
            key = sem.isoformat() if hasattr(sem, "isoformat") else str(sem)
            out[key] = (row.get("modo") or "").strip().lower()
    return out


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
                 batch_min_u, batch_mult_u, cap_bodega_u, t_cambio_hrs, linea_preferida, activo, mto, formato, granel_grupo, updated_at)
            VALUES
                (:sku, :descripcion, :categoria, :tipo, :u_por_caja, :lead_time_sem, :ss_dias,
                 :batch_min_u, :batch_mult_u, :cap_bodega_u, :t_cambio_hrs, :linea_preferida, :activo, :mto, :formato, :granel_grupo, NOW())
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
                granel_grupo    = EXCLUDED.granel_grupo,
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

# -- VU minima por cliente x SKU (tabla de logistica) -------------------------

def upsert_vu_cliente_sku(filas):
    """Reemplaza (idempotente) filas de mrp_vu_cliente_sku."""
    if not filas:
        return 0
    with get_session() as session:
        for f in filas:
            session.execute(text("""
                INSERT INTO mrp_vu_cliente_sku
                    (cod_cliente, sku, descripcion, min_dias, min_meses, pct_derivado, updated_at)
                VALUES
                    (:cod_cliente, :sku, :descripcion, :min_dias, :min_meses, :pct_derivado, NOW())
                ON CONFLICT (cod_cliente, sku) DO UPDATE SET
                    descripcion  = EXCLUDED.descripcion,
                    min_dias     = EXCLUDED.min_dias,
                    min_meses    = EXCLUDED.min_meses,
                    pct_derivado = EXCLUDED.pct_derivado,
                    updated_at   = NOW()
            """), f)
        session.commit()
    return len(filas)

def get_vu_cliente_sku():
    """Devuelve {(cod_cliente, sku): min_dias} para el motor de faltantes."""
    with get_session() as session:
        rows = session.execute(text(
            "SELECT cod_cliente, sku, min_dias FROM mrp_vu_cliente_sku")).fetchall()
    return {(str(r[0]).strip(), str(r[1]).strip()): int(r[2]) for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# Explicaciones de faltantes (feature 2026-07-23)
# ─────────────────────────────────────────────────────────────────────────────

def get_explicaciones_faltantes(fecha) -> dict:
    """Devuelve {sku: {explicacion, autor, congelada, updated_at}} para una fecha.
    fecha: date o str 'YYYY-MM-DD'."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT sku, explicacion, autor, congelada, updated_at
            FROM mrp_faltantes_explicaciones
            WHERE fecha = :f
        """), {"f": str(fecha)}).fetchall()
    return {
        str(r[0]).strip(): {
            "explicacion": r[1] or "",
            "autor": r[2] or "",
            "congelada": bool(r[3]),
            "updated_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    }


def upsert_explicacion_faltante(sku: str, fecha, explicacion: str, autor: str = "") -> dict:
    """Inserta o actualiza la explicacion de un (sku, fecha).
    Rechaza si la fila ya esta congelada (retorna {ok: False, motivo: 'congelada'})."""
    sku = str(sku).strip()
    with get_session() as session:
        # ¿ya existe y esta congelada?
        row = session.execute(text("""
            SELECT congelada FROM mrp_faltantes_explicaciones
            WHERE sku = :s AND fecha = :f
        """), {"s": sku, "f": str(fecha)}).fetchone()
        if row is not None and bool(row[0]):
            return {"ok": False, "motivo": "congelada"}

        session.execute(text("""
            INSERT INTO mrp_faltantes_explicaciones
                (sku, fecha, explicacion, autor, congelada, created_at, updated_at)
            VALUES (:s, :f, :e, :a, FALSE, NOW(), NOW())
            ON CONFLICT (sku, fecha) DO UPDATE SET
                explicacion = EXCLUDED.explicacion,
                autor       = EXCLUDED.autor,
                updated_at  = NOW()
        """), {"s": sku, "f": str(fecha), "e": explicacion or "", "a": autor or ""})
        session.commit()
    return {"ok": True}


def congelar_explicaciones_faltantes(fecha) -> int:
    """Marca congelada=TRUE todas las explicaciones de una fecha (lo llama el
    cron de las 11 tras enviar el correo final). Retorna filas afectadas."""
    with get_session() as session:
        n = session.execute(text("""
            UPDATE mrp_faltantes_explicaciones
            SET congelada = TRUE, updated_at = NOW()
            WHERE fecha = :f AND congelada = FALSE
        """), {"f": str(fecha)}).rowcount
        session.commit()
    return n


def limpiar_explicaciones_huerfanas() -> int:
    """Borra explicaciones NO congeladas cuyo faltante (sku, fecha) ya no existe
    en mrp_faltantes. Las congeladas se conservan como registro historico.
    Lo llama cron_faltantes.py tras recalcular. Retorna filas borradas."""
    with get_session() as session:
        n = session.execute(text("""
            DELETE FROM mrp_faltantes_explicaciones e
            WHERE e.congelada = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM mrp_faltantes f
                  WHERE f.sku = e.sku AND f.fecha = e.fecha
              )
        """)).rowcount
        session.commit()
    return n

# ─── Conciliación OF/TR (Fase 1) ─────────────────────────────────────────────
# Mide OF ingresadas a SAP y su recepción (Terminal Report), SIN tocar el solver.
# Grano: UNA FILA POR RECIBO. PK verificada con dato el 12-08:
# (orden_produccion, terminal_report, batchnum) única sobre todo el dataset.
# Tabla INDEPENDIENTE de la fuente: el SP es ventana móvil de ~6 meses y descarta
# lo viejo; esta tabla acumula y sobrevive a eso. Ver DISENO_conciliacion_of.md.

def crear_tablas_of_sap():
    """Crea mrp_of_sap si no existe. Idempotente. La llama crear_tablas_params()."""
    with get_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS mrp_of_sap (
                orden_produccion   VARCHAR(20)   NOT NULL,
                terminal_report    VARCHAR(20)   NOT NULL DEFAULT '',  -- '' = pendiente
                batchnum           VARCHAR(40)   NOT NULL DEFAULT '',
                sku                VARCHAR(30)   NOT NULL DEFAULT '',
                descripcion        VARCHAR(160)  DEFAULT '',
                cant_planificada   NUMERIC(14,2) DEFAULT 0,   -- total OF (se repite por fila; NO sumar)
                cant_producida     NUMERIC(14,2) DEFAULT 0,   -- por recibo (SÍ se suma)
                cant_lote          NUMERIC(14,2) DEFAULT 0,
                fecha_ini_planif   DATE,                      -- ancla de consistencia (100% cobertura)
                fecha_fin_planif   DATE,
                fecha_tr           DATE,                      -- NULL si pendiente
                fecha_vcto_lote    DATE,
                linea              VARCHAR(40)   DEFAULT '',   -- '' = "Sin Asignar" (98,9% hoy)
                lote               VARCHAR(40)   DEFAULT '',
                codigo_almacen     VARCHAR(20)   DEFAULT '',   -- bodega, NO línea
                es_granel          BOOLEAN       DEFAULT FALSE,
                pendiente          BOOLEAN       DEFAULT FALSE, -- cant_producida == 0
                ingested_at        TIMESTAMP     DEFAULT NOW(),
                updated_at         TIMESTAMP     DEFAULT NOW(),
                PRIMARY KEY (orden_produccion, terminal_report, batchnum)
            );
            CREATE INDEX IF NOT EXISTS ix_of_sap_sku       ON mrp_of_sap (sku);
            CREATE INDEX IF NOT EXISTS ix_of_sap_fecha_tr  ON mrp_of_sap (fecha_tr);
            CREATE INDEX IF NOT EXISTS ix_of_sap_fecha_ini ON mrp_of_sap (fecha_ini_planif);
            CREATE INDEX IF NOT EXISTS ix_of_sap_pend      ON mrp_of_sap (pendiente);
        """))
        session.commit()
    logger.info("[MRP_DB] mrp_of_sap inicializada.")


def upsert_of_sap_bulk(filas: list[dict]) -> dict:
    """UPSERT acumulativo de filas-recibo (salida de hana_of.leer_of_tr()).

    ACUMULA, no reemplaza: nunca borra filas que ya no vengan del SP (la ventana
    móvil las descartó, pero para nosotros son histórico). Actualiza las que cambian
    (típico: una pendiente que pasa a recibida -> se llenan tr/fecha/producida).
    """
    if not filas:
        logger.info("[MRP_DB] upsert_of_sap_bulk: 0 filas, nada que hacer.")
        return {"filas": 0, "ejecutadas": 0}

    sql = text("""
        INSERT INTO mrp_of_sap (
            orden_produccion, terminal_report, batchnum, sku, descripcion,
            cant_planificada, cant_producida, cant_lote,
            fecha_ini_planif, fecha_fin_planif, fecha_tr, fecha_vcto_lote,
            linea, lote, codigo_almacen, es_granel, pendiente, updated_at
        ) VALUES (
            :orden_produccion, :terminal_report, :batchnum, :sku, :descripcion,
            :cant_planificada, :cant_producida, :cant_lote,
            :fecha_ini_planif, :fecha_fin_planif, :fecha_tr, :fecha_vcto_lote,
            :linea, :lote, :codigo_almacen, :es_granel, :pendiente, NOW()
        )
        ON CONFLICT (orden_produccion, terminal_report, batchnum) DO UPDATE SET
            sku              = EXCLUDED.sku,
            descripcion      = EXCLUDED.descripcion,
            cant_planificada = EXCLUDED.cant_planificada,
            cant_producida   = EXCLUDED.cant_producida,
            cant_lote        = EXCLUDED.cant_lote,
            fecha_ini_planif = EXCLUDED.fecha_ini_planif,
            fecha_fin_planif = EXCLUDED.fecha_fin_planif,
            fecha_tr         = EXCLUDED.fecha_tr,
            fecha_vcto_lote  = EXCLUDED.fecha_vcto_lote,
            linea            = EXCLUDED.linea,
            lote             = EXCLUDED.lote,
            codigo_almacen   = EXCLUDED.codigo_almacen,
            es_granel        = EXCLUDED.es_granel,
            pendiente        = EXCLUDED.pendiente,
            updated_at       = NOW()
    """)

    def _p(f):
        return {
            "orden_produccion": f["orden_produccion"],
            "terminal_report":  f["terminal_report"],
            "batchnum":         f["batchnum"],
            "sku":              f["sku"],
            "descripcion":      f["descripcion"][:160],
            "cant_planificada": float(f["cant_planificada"]),
            "cant_producida":   float(f["cant_producida"]),
            "cant_lote":        float(f["cant_lote"]),
            "fecha_ini_planif": f["fecha_ini_planif"],
            "fecha_fin_planif": f["fecha_fin_planif"],
            "fecha_tr":         f["fecha_tr"],
            "fecha_vcto_lote":  f["fecha_vcto_lote"],
            "linea":            f["linea"][:40],
            "lote":             f["lote"][:40],
            "codigo_almacen":   f["codigo_almacen"][:20],
            "es_granel":        bool(f["es_granel"]),
            "pendiente":        bool(f["pendiente"]),
        }

    with get_session() as session:
        session.execute(sql, [_p(f) for f in filas])
        session.commit()
    logger.info("[MRP_DB] upsert_of_sap_bulk: %d filas procesadas (UPSERT).", len(filas))
    return {"filas": len(filas), "ejecutadas": len(filas)}


def get_of_sap_cumplimiento(solo_pt: bool = False) -> list[dict]:
    """Vista de CUMPLIMIENTO a nivel OF (agrega los recibos).

    planificada: MAX (se repite idéntica por fila; nunca sumar).
    producida:   SUM (cada recibo aporta). ratio, estado, nº recibos, ventana TR.
    """
    filtro = "WHERE es_granel = FALSE" if solo_pt else ""
    with get_session() as session:
        rows = session.execute(text(f"""
            SELECT
                orden_produccion,
                MAX(sku)              AS sku,
                MAX(descripcion)      AS descripcion,
                BOOL_OR(es_granel)    AS es_granel,
                MAX(cant_planificada) AS planificada,
                SUM(cant_producida)   AS producida,
                MIN(fecha_ini_planif) AS fecha_ini_planif,
                MIN(fecha_tr)         AS primer_tr,
                MAX(fecha_tr)         AS ultimo_tr,
                COUNT(*) FILTER (WHERE NOT pendiente) AS n_recibos,
                BOOL_AND(pendiente)   AS todo_pendiente
            FROM mrp_of_sap
            {filtro}
            GROUP BY orden_produccion
            ORDER BY MIN(fecha_ini_planif) DESC NULLS LAST
        """)).mappings().all()

    out = []
    for r in rows:
        plan = float(r["planificada"] or 0)
        prod = float(r["producida"] or 0)
        ratio = (prod / plan) if plan > 0 else 0.0
        if r["todo_pendiente"]:
            estado = "pendiente"
        elif abs(ratio - 1) < 1e-4:
            estado = "completa"
        elif ratio < 1:
            estado = "corta"
        else:
            estado = "sobre"
        out.append({
            "orden_produccion": r["orden_produccion"],
            "sku": r["sku"], "descripcion": r["descripcion"],
            "es_granel": bool(r["es_granel"]),
            "planificada": plan, "producida": prod,
            "ratio": round(ratio, 4), "estado": estado,
            "fecha_ini_planif": (r["fecha_ini_planif"].isoformat() if r["fecha_ini_planif"] else None),
            "primer_tr": (r["primer_tr"].isoformat() if r["primer_tr"] else None),
            "ultimo_tr": (r["ultimo_tr"].isoformat() if r["ultimo_tr"] else None),
            "n_recibos": int(r["n_recibos"] or 0),
        })
    return out


def get_of_sap_recepcion_diaria(orden: str) -> list[dict]:
    """Serie de recepción por día de una OF (para los parciales en el tiempo)."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT fecha_tr, SUM(cant_producida) AS producido, COUNT(*) AS n_recibos
            FROM mrp_of_sap
            WHERE orden_produccion = :o AND NOT pendiente AND fecha_tr IS NOT NULL
            GROUP BY fecha_tr ORDER BY fecha_tr
        """), {"o": orden}).mappings().all()
    return [{"fecha": r["fecha_tr"].isoformat(),
             "producido": float(r["producido"] or 0),
             "n_recibos": int(r["n_recibos"])} for r in rows]


def get_of_sap_tendencia_mensual(solo_pt: bool = False) -> list[dict]:
    """Fill-rate mensual: por mes de fecha_ini_planif, cuántas OF completa/corta/
    sobre/pendiente y el % de completas. Para el gráfico de tendencia (Fase 2).

    Agrega a nivel OF primero (planificada MAX, producida SUM) y después por mes,
    para no contar una OF varias veces por sus recibos.
    """
    filtro = "WHERE es_granel = FALSE" if solo_pt else ""
    with get_session() as session:
        rows = session.execute(text(f"""
            WITH por_of AS (
                SELECT
                    orden_produccion,
                    MIN(fecha_ini_planif)                 AS ini,
                    MAX(cant_planificada)                 AS plan,
                    SUM(cant_producida)                   AS prod,
                    BOOL_AND(pendiente)                   AS todo_pend
                FROM mrp_of_sap
                {filtro}
                GROUP BY orden_produccion
            )
            SELECT
                TO_CHAR(DATE_TRUNC('month', ini), 'YYYY-MM') AS mes,
                COUNT(*)                                     AS n_of,
                COUNT(*) FILTER (WHERE todo_pend)            AS pendiente,
                COUNT(*) FILTER (WHERE NOT todo_pend AND plan > 0
                                 AND ABS(prod/plan - 1) < 1e-4)             AS completa,
                COUNT(*) FILTER (WHERE NOT todo_pend AND plan > 0
                                 AND prod/plan < 0.9999)                    AS corta,
                COUNT(*) FILTER (WHERE NOT todo_pend AND plan > 0
                                 AND prod/plan > 1.0001)                    AS sobre
            FROM por_of
            WHERE ini IS NOT NULL
            GROUP BY DATE_TRUNC('month', ini)
            ORDER BY DATE_TRUNC('month', ini)
        """)).mappings().all()

    out = []
    for r in rows:
        n = int(r["n_of"] or 0)
        comp = int(r["completa"] or 0)
        # fill-rate = completas sobre las OF con producción decidida (excluye pendientes)
        cerradas = n - int(r["pendiente"] or 0)
        out.append({
            "mes": r["mes"], "n_of": n,
            "completa": comp, "corta": int(r["corta"] or 0),
            "sobre": int(r["sobre"] or 0), "pendiente": int(r["pendiente"] or 0),
            "fill_rate": round(100 * comp / cerradas, 1) if cerradas else None,
        })
    return out


def get_of_sap_adopcion(desde: str | None = None, hasta: str | None = None,
                        linea: str | None = None, categoria: str | None = None,
                        sku: str | None = None) -> dict:
    """KPI de ADOPCIÓN por UNIDADES (cajas): de las cajas que el sistema planificó,
    cuántas se materializaron como OF en SAP.

    Definición (validada con dato, DISENO §11):
      · Unidad de medida: CAJAS. SAP cant_planificada y sistema cantidad_real_cj están
        ambas en cajas (verificado: coinciden exacto, NO usar cantidad_real_u que está
        en unidades y daría el cociente dividido por u_por_caja).
      · Match: una OF de SAP corresponde a una aprobación del sistema si el
        fecha_lanzamiento_real del sistema cae DENTRO del tramo [ini, fin] de la OF.
        Sin tolerancia. El tramo ancho del dato viejo absorbe el desfase creación/
        producción; el dato nuevo (ini=fin=lanzamiento) exige coincidencia exacta.
      · Topeado por SKU: min(cajas_SAP, cajas_sistema) / cajas_sistema  (∈ [0,1]).
        Si SAP produjo ≥ lo planificado, ese SKU cuenta 100% adoptado.
      · Semana = semana ISO (lunes) del fecha_lanzamiento_real del sistema.
      · Agregación semanal ponderada por volumen: Σ min(sap,plan) / Σ plan.
      · Denominador = cajas planificadas por el SISTEMA (activos, PT). Las semanas sin
        plan no aparecen (no se mide adopción de un plan inexistente).

    Universo: SKU activos, PT (no granel), conocidos. MTO incluidos (§10.3).
    Línea inferida por linea_preferida (§10.4).

    Devuelve:
      serie:     [{semana, plan_cj, sap_cj, pct}]        — curva del nacimiento
      por_linea: [{linea, plan_cj, sap_cj, pct}]         — agregado del período
      por_sku:   [{sku, descripcion, linea, plan_cj, sap_cj, pct}]  — detalle auditable
      fuera_sistema: {of, sku}                            — contexto (SKU desconocidos)
    """
    import pandas as _pd

    params = {p["sku"]: p for p in get_all_sku_params()}
    activos = {k for k, v in params.items() if v.get("activo")}

    # filtros de universo (linea/categoria) sobre params
    def _pasa_filtro(sk):
        if sk not in activos:
            return False
        pr = params.get(sk, {})
        if linea and (pr.get("linea_preferida") or "") != linea:
            return False
        if categoria and (pr.get("categoria") or "") != categoria:
            return False
        if sku and sku not in str(sk):
            return False
        return True

    with get_session() as session:
        # aprobaciones del sistema (plan): sku, fecha lanzamiento, cajas
        ap_rows = session.execute(text("""
            SELECT o.sku AS sku, a.fecha_lanzamiento_real AS fla,
                   a.cantidad_real_cj AS cj
            FROM mrp_aprobaciones a
            JOIN mrp_ordenes o ON o.numero_of = a.numero_of
            WHERE a.estado = 'APROBADA' AND a.fecha_lanzamiento_real IS NOT NULL
        """)).mappings().all()

        # OF de SAP: sku, tramo [ini,fin], cajas planificadas (por OF)
        of_rows = session.execute(text("""
            SELECT sku, orden_produccion,
                   MIN(fecha_ini_planif) AS ini, MAX(fecha_fin_planif) AS fin,
                   MAX(cant_planificada) AS cj_sap
            FROM mrp_of_sap
            WHERE es_granel = FALSE AND fecha_ini_planif IS NOT NULL
            GROUP BY sku, orden_produccion
        """)).mappings().all()

        # contexto: OF con SKU desconocido
        fuera = session.execute(text("""
            SELECT COUNT(DISTINCT m.orden_produccion) AS of, COUNT(DISTINCT m.sku) AS sku
            FROM mrp_of_sap m
            LEFT JOIN mrp_sku_params sp ON sp.sku = m.sku
            WHERE m.es_granel = FALSE AND sp.sku IS NULL
        """)).mappings().first()

    ap = _pd.DataFrame(ap_rows)
    of = _pd.DataFrame(of_rows)
    if ap.empty or of.empty:
        return {"serie": [], "por_linea": [], "por_sku": [],
                "fuera_sistema": {"of": int((fuera or {}).get("of") or 0),
                                  "sku": int((fuera or {}).get("sku") or 0)}}

    ap["sku"] = ap["sku"].astype(str).str.strip()
    ap["fla"] = _pd.to_datetime(ap["fla"])
    ap["cj"] = _pd.to_numeric(ap["cj"], errors="coerce").fillna(0)
    of["sku"] = of["sku"].astype(str).str.strip()
    of["ini"] = _pd.to_datetime(of["ini"])
    of["fin"] = _pd.to_datetime(of["fin"])
    of["cj_sap"] = _pd.to_numeric(of["cj_sap"], errors="coerce").fillna(0)

    # filtros de fecha sobre la semana de lanzamiento del sistema
    if desde:
        ap = ap[ap["fla"] >= _pd.Timestamp(desde)]
    if hasta:
        ap = ap[ap["fla"] <= _pd.Timestamp(hasta)]

    # index de OF por sku para el match por tramo
    of_por_sku = {}
    for _, o in of.iterrows():
        of_por_sku.setdefault(o["sku"], []).append(o)

    filas = []  # (semana, sku, plan_cj, mat_cj)
    for _, a in ap.iterrows():
        if not _pasa_filtro(a["sku"]):
            continue
        # cajas de SAP cuyo tramo [ini,fin] contiene el lanzamiento del sistema
        sap_cj = 0.0
        for o in of_por_sku.get(a["sku"], []):
            fin = o["fin"] if _pd.notna(o["fin"]) else o["ini"]
            if _pd.notna(o["ini"]) and o["ini"] <= a["fla"] <= fin:
                sap_cj += float(o["cj_sap"])
        plan_cj = float(a["cj"])
        mat_cj = min(sap_cj, plan_cj)  # topeado
        sem = a["fla"].to_period("W").start_time.date().isoformat()
        filas.append((sem, a["sku"], plan_cj, mat_cj))

    df = _pd.DataFrame(filas, columns=["sem", "sku", "plan", "mat"])

    # Cajas SAP producidas por semana (centro del tramo), universo activos PT.
    # Sirve para las semanas SIN plan del sistema: se muestran como 0% con el SAP de contexto.
    def _centro_sem(o):
        ini = o["ini"]; fin = o["fin"] if _pd.notna(o["fin"]) else o["ini"]
        if _pd.isna(ini):
            return None
        centro = ini + (fin - ini) / 2
        return centro.to_period("W").start_time.date().isoformat()
    sap_por_sem = {}
    for _, o in of.iterrows():
        if not _pasa_filtro(o["sku"]):
            continue
        w = _centro_sem(o)
        if w:
            sap_por_sem[w] = sap_por_sem.get(w, 0.0) + float(o["cj_sap"])

    def _pct(mat, plan):
        return round(100 * mat / plan, 1) if plan > 0 else None

    # serie semanal (ponderada por volumen)
    # - semana CON plan: pct = mat/plan, pesa con plan_cj real
    # - semana SIN plan pero con producción SAP: plan_cj=0, sap_cj=cajas SAP, pct=0
    #   (aparece en el gráfico en 0%, pesa 0 en cualquier promedio ponderado)
    serie_out = []
    semanas_con_plan = set()
    if not df.empty:
        for sem, g in df.groupby("sem"):
            plan = g["plan"].sum(); mat = g["mat"].sum()
            semanas_con_plan.add(sem)
            serie_out.append({"semana": sem, "plan_cj": round(plan, 0),
                              "sap_cj": round(mat, 0),
                              "pct": _pct(mat, plan) if plan > 0 else 0.0})
    # semanas con producción SAP y SIN plan del sistema -> 0%
    for w, sap_cj in sap_por_sem.items():
        if w not in semanas_con_plan and sap_cj > 0:
            serie_out.append({"semana": w, "plan_cj": 0.0,
                              "sap_cj": round(sap_cj, 0), "pct": 0.0})
    serie_out.sort(key=lambda r: r["semana"])

    # por linea (agregado del periodo)
    linea_out = []
    if not df.empty:
        df["linea"] = df["sku"].map(lambda s: (params.get(s, {}).get("linea_preferida") or "(sin línea)"))
        for ln, g in df.groupby("linea"):
            plan = g["plan"].sum(); mat = g["mat"].sum()
            linea_out.append({"linea": ln, "plan_cj": round(plan, 0),
                              "sap_cj": round(mat, 0), "pct": _pct(mat, plan)})
        linea_out.sort(key=lambda r: -r["plan_cj"])

    # por sku (detalle auditable del periodo)
    sku_out = []
    if not df.empty:
        for sk, g in df.groupby("sku"):
            plan = g["plan"].sum(); mat = g["mat"].sum()
            pr = params.get(sk, {})
            sku_out.append({"sku": sk, "descripcion": pr.get("descripcion", ""),
                            "linea": pr.get("linea_preferida") or "(sin línea)",
                            "plan_cj": round(plan, 0), "sap_cj": round(mat, 0),
                            "pct": _pct(mat, plan)})
        sku_out.sort(key=lambda r: -r["plan_cj"])

    # por sku-semana (detalle desglosado): el frontend lo reagrega al tramo que se
    # seleccione con el brush del gráfico. Una fila por (semana, sku) con plan y mat
    # ya topeado. El browser suma sobre el tramo -> tabla y KPI del período reactivos
    # sin ir al backend en cada arrastre.
    sku_sem_out = []
    if not df.empty:
        for (sem, sk), g in df.groupby(["sem", "sku"]):
            pr = params.get(sk, {})
            sku_sem_out.append({
                "semana": sem, "sku": sk,
                "descripcion": pr.get("descripcion", ""),
                "linea": pr.get("linea_preferida") or "(sin línea)",
                "plan_cj": round(g["plan"].sum(), 0),
                "sap_cj": round(g["mat"].sum(), 0),
            })

    return {
        "serie": serie_out,
        "por_linea": linea_out,
        "por_sku": sku_out,
        "por_sku_semana": sku_sem_out,
        "fuera_sistema": {"of": int((fuera or {}).get("of") or 0),
                          "sku": int((fuera or {}).get("sku") or 0)},
    }


def get_of_cumplimiento_sku(periodo: str = "semana",
                            desde: str | None = None, hasta: str | None = None,
                            linea: str | None = None, categoria: str | None = None,
                            sku: str | None = None) -> dict:
    """Cumplimiento de OF por SKU, estilo reporte de Producción (Solicitado vs
    Producido, %). SIN topear (puede pasar 100% = sobreproducción, ver DISENO §12).

    periodo='semana': bucket por semana del CENTRO del tramo [ini,fin].
    periodo='dia'   : bucket por fecha ÚNICA (si fecha_ini=fecha_fin, dato nuevo de
                      Producción) o por fecha_tr (si es tramo, dato viejo). Las OF con
                      tramo y sin TR (pendientes) no entran al diario.

    Solicitado = cajas planificadas (cant_planificada, MAX por OF — no se repite).
    Producido  = cajas recibidas (cant_producida, SUM de los recibos de la OF).
    Cumplimiento = Producido / Solicitado (crudo).

    Devuelve {periodo, buckets:[{bucket, filas:[{sku,descripcion,solicitado,
    producido,pct}], total:{solicitado,producido,pct}}]}.
    """
    cond = ["es_granel = FALSE"]
    p: dict = {}
    if sku:
        cond.append("sku LIKE :sku"); p["sku"] = f"%{sku}%"
    cond_sql = " AND ".join(cond)

    # expresión de bucket según periodo
    if periodo == "dia":
        # fecha única si ini=fin, si no la fecha del TR (producción efectiva)
        bucket_expr = """
            CASE WHEN fecha_ini_planif = fecha_fin_planif THEN fecha_ini_planif
                 ELSE fecha_tr END
        """
    else:
        # centro del tramo [ini,fin] -> semana ISO (lunes)
        bucket_expr = """
            DATE_TRUNC('week',
                (fecha_ini_planif
                 + ((COALESCE(fecha_fin_planif, fecha_ini_planif) - fecha_ini_planif) / 2))
            )::date
        """

    with get_session() as session:
        # primero agregamos a nivel OF (planificada MAX, producida SUM), con su bucket,
        # después sumamos por (bucket, sku)
        rows = session.execute(text(f"""
            WITH por_of AS (
                SELECT orden_produccion, sku,
                       {bucket_expr} AS bucket,
                       MAX(cant_planificada) AS solicitado,
                       SUM(cant_producida)   AS producido
                FROM mrp_of_sap
                WHERE {cond_sql}
                GROUP BY orden_produccion, sku, fecha_ini_planif, fecha_fin_planif, fecha_tr
            )
            SELECT bucket, sku,
                   SUM(solicitado) AS solicitado,
                   SUM(producido)  AS producido
            FROM por_of
            WHERE bucket IS NOT NULL
            GROUP BY bucket, sku
            ORDER BY bucket, SUM(solicitado) DESC
        """), p).mappings().all()

        # descripción y línea/categoría por SKU (para etiquetas y filtros)
        meta = {r["sku"]: r for r in session.execute(text("""
            SELECT sku, descripcion, linea_preferida, categoria FROM mrp_sku_params
        """)).mappings().all()}

    # filtros de linea/categoria (sobre params) + fecha (sobre bucket) en python
    def _pasa(sk, bucket):
        m = meta.get(sk, {})
        if linea and (m.get("linea_preferida") or "") != linea:
            return False
        if categoria and (m.get("categoria") or "") != categoria:
            return False
        if desde and str(bucket) < desde:
            return False
        if hasta and str(bucket) > hasta:
            return False
        return True

    # armar buckets
    buckets = {}
    for r in rows:
        b = r["bucket"].isoformat()
        sk = r["sku"]
        if not _pasa(sk, r["bucket"]):
            continue
        sol = float(r["solicitado"] or 0)
        pro = float(r["producido"] or 0)
        m = meta.get(sk, {})
        buckets.setdefault(b, []).append({
            "sku": sk, "descripcion": m.get("descripcion", ""),
            "linea": m.get("linea_preferida") or "(sin línea)",
            "solicitado": round(sol, 0), "producido": round(pro, 0),
            "pct": round(100 * pro / sol, 1) if sol > 0 else None,
        })

    out = []
    for b in sorted(buckets.keys()):
        filas = buckets[b]
        tsol = sum(f["solicitado"] for f in filas)
        tpro = sum(f["producido"] for f in filas)
        out.append({
            "bucket": b, "filas": filas,
            "total": {"solicitado": round(tsol, 0), "producido": round(tpro, 0),
                      "pct": round(100 * tpro / tsol, 1) if tsol > 0 else None},
        })
    return {"periodo": periodo, "buckets": out}


def get_of_cumplimiento_evolutivo(linea: str | None = None,
                                  categoria: str | None = None) -> list[dict]:
    """Cumplimiento global por semana (centro del tramo) para el gráfico evolutivo.
    Producido/Solicitado agregado de todos los SKU de PT. Sin topear."""
    cond = ["es_granel = FALSE"]
    with get_session() as session:
        rows = session.execute(text(f"""
            WITH por_of AS (
                SELECT orden_produccion, sku,
                       DATE_TRUNC('week',
                         (fecha_ini_planif
                          + ((COALESCE(fecha_fin_planif, fecha_ini_planif) - fecha_ini_planif) / 2))
                       )::date AS sem,
                       MAX(cant_planificada) AS solicitado,
                       SUM(cant_producida)   AS producido
                FROM mrp_of_sap
                WHERE {" AND ".join(cond)}
                GROUP BY orden_produccion, sku, fecha_ini_planif, fecha_fin_planif
            )
            SELECT po.sem, SUM(po.solicitado) AS solicitado, SUM(po.producido) AS producido
            FROM por_of po
            JOIN mrp_sku_params sp ON sp.sku = po.sku
            WHERE po.sem IS NOT NULL
              AND (:linea IS NULL OR sp.linea_preferida = :linea)
              AND (:categoria IS NULL OR sp.categoria = :categoria)
            GROUP BY po.sem ORDER BY po.sem
        """), {"linea": linea, "categoria": categoria}).mappings().all()
    out = []
    for r in rows:
        sol = float(r["solicitado"] or 0); pro = float(r["producido"] or 0)
        out.append({"semana": r["sem"].isoformat(),
                    "solicitado": round(sol, 0), "producido": round(pro, 0),
                    "pct": round(100 * pro / sol, 1) if sol > 0 else None})
    return out
