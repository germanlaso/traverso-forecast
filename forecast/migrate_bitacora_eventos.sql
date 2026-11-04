-- ============================================================================
-- Bitácora de eventos diarios por línea — Módulo Evaluación de la Operación
-- Idempotente: CREATE ... IF NOT EXISTS + INSERT ... ON CONFLICT DO NOTHING.
-- No modifica ni borra nada existente.
-- Ejecutar: docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < forecast/migrate_bitacora_eventos.sql
-- ============================================================================

BEGIN;

-- Catálogo de tipos de evento. 'categoria' es lo que consume el motor de KPIs:
--   PARADA_PLANIFICADA    -> descuenta de capacidad real disponible
--   PARADA_NO_PLANIFICADA -> pérdida de eficiencia / disponibilidad
--   SIN_PROGRAMA          -> capacidad ociosa explicada por falta de programa
--   INFORMATIVO           -> observación sin detención (no descuenta minutos)
CREATE TABLE IF NOT EXISTS mrp_eventos_tipos (
    codigo             VARCHAR(30)  PRIMARY KEY,
    nombre             VARCHAR(80)  NOT NULL,
    categoria          VARCHAR(30)  NOT NULL
        CHECK (categoria IN ('PARADA_PLANIFICADA','PARADA_NO_PLANIFICADA',
                             'SIN_PROGRAMA','INFORMATIVO')),
    requiere_duracion  BOOLEAN      NOT NULL DEFAULT TRUE,
    activo             BOOLEAN      NOT NULL DEFAULT TRUE,
    orden              SMALLINT     NOT NULL DEFAULT 99
);

INSERT INTO mrp_eventos_tipos (codigo, nombre, categoria, requiere_duracion, orden) VALUES
    ('MANT_PLAN',      'Mantención planificada',               'PARADA_PLANIFICADA',    TRUE,  10),
    ('LIMPIEZA',       'Limpieza / sanitización',              'PARADA_PLANIFICADA',    TRUE,  20),
    ('CAMBIO_FORMATO', 'Cambio de formato / setup',            'PARADA_PLANIFICADA',    TRUE,  30),
    ('FALLA_MEC',      'Falla mecánica / eléctrica',           'PARADA_NO_PLANIFICADA', TRUE,  40),
    ('FALTA_MAT',      'Falta de material / insumo',           'PARADA_NO_PLANIFICADA', TRUE,  50),
    ('FALTA_PERS',     'Falta de personal',                    'PARADA_NO_PLANIFICADA', TRUE,  60),
    ('CALIDAD',        'Detención por calidad',                'PARADA_NO_PLANIFICADA', TRUE,  70),
    ('SIN_PROGRAMA',   'Línea disponible sin programa',        'SIN_PROGRAMA',          TRUE,  80),
    ('OTRO',           'Otra detención',                       'PARADA_NO_PLANIFICADA', TRUE,  90),
    ('OBSERVACION',    'Observación (sin detención)',          'INFORMATIVO',           FALSE, 100)
ON CONFLICT (codigo) DO NOTHING;

-- Eventos. Sin DELETE desde la app: se anulan (se conserva el histórico).
-- 'linea' se valida en la API contra mrp_lineas (PK case-sensitive, ej. 'L1Pet LV').
CREATE TABLE IF NOT EXISTS mrp_eventos_linea (
    id              BIGSERIAL    PRIMARY KEY,
    fecha           DATE         NOT NULL,
    linea           VARCHAR(50)  NOT NULL,
    tipo            VARCHAR(30)  NOT NULL REFERENCES mrp_eventos_tipos(codigo),
    duracion_min    INTEGER
        CHECK (duracion_min IS NULL OR duracion_min BETWEEN 1 AND 1440),
    sku             VARCHAR(20),
    comentario      TEXT,
    registrado_por  VARCHAR(80)  NOT NULL,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    anulado         BOOLEAN      NOT NULL DEFAULT FALSE,
    anulado_por     VARCHAR(80),
    anulado_en      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_eventos_linea_fecha_linea
    ON mrp_eventos_linea (fecha, linea);

COMMIT;
