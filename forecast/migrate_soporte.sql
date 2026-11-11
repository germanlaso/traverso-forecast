-- ============================================================================
-- Menú Soporte (12-11-2026): Academia (avance por persona) y registro anónimo de
-- preguntas a Mostacín. Idempotente. No toca tablas existentes.
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_soporte.sql
-- ============================================================================
BEGIN;

-- Personas de la Academia. Identificación por nombre (como la bitácora) hasta tener Entra ID.
-- nombre_norm = minúsculas, sin tildes, espacios simples: evita "Juan Pérez" / "juan perez" duplicados.
CREATE TABLE IF NOT EXISTS academia_personas (
    id              BIGSERIAL    PRIMARY KEY,
    nombre          VARCHAR(80)  NOT NULL,
    nombre_norm     VARCHAR(80)  NOT NULL UNIQUE,
    entra_oid       VARCHAR(64)  UNIQUE,                 -- se completa al activar Entra ID
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    ultimo_acceso   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Avance por persona y unidad (una fila por par). Puntos e insignias se calculan, no se guardan.
CREATE TABLE IF NOT EXISTS academia_avance (
    persona_id        BIGINT       NOT NULL REFERENCES academia_personas(id),
    unidad_id         VARCHAR(60)  NOT NULL,
    estado            VARCHAR(12)  NOT NULL DEFAULT 'en_curso'
        CHECK (estado IN ('en_curso','aprobada')),
    mejor_puntaje_pct INTEGER      NOT NULL DEFAULT 0 CHECK (mejor_puntaje_pct BETWEEN 0 AND 100),
    intentos          INTEGER      NOT NULL DEFAULT 0,
    desafio_ok        BOOLEAN      NOT NULL DEFAULT false,   -- desafío práctico (autodeclarado)
    version_contenido INTEGER      NOT NULL DEFAULT 1,
    iniciada_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    aprobada_en       TIMESTAMPTZ,
    actualizado_en    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (persona_id, unidad_id)
);

-- Historial de intentos de cuestionario: sirve para ver qué preguntas fallan más
-- (señal de que la explicación de la unidad o de la Ayuda debe mejorar).
CREATE TABLE IF NOT EXISTS academia_intentos (
    id                BIGSERIAL    PRIMARY KEY,
    persona_id        BIGINT       NOT NULL REFERENCES academia_personas(id),
    unidad_id         VARCHAR(60)  NOT NULL,
    version_contenido INTEGER      NOT NULL DEFAULT 1,
    respuestas        JSONB        NOT NULL,             -- {pregunta_id: opcion_elegida}
    detalle           JSONB        NOT NULL,             -- {pregunta_id: true/false}
    correctas         INTEGER      NOT NULL,
    total             INTEGER      NOT NULL,
    puntaje_pct       INTEGER      NOT NULL,
    aprobado          BOOLEAN      NOT NULL,
    creado_en         TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_academia_intentos_unidad ON academia_intentos (unidad_id, creado_en);

-- Certificados emitidos (registro estable aunque cambie el contenido de la ruta).
CREATE TABLE IF NOT EXISTS academia_certificados (
    id              BIGSERIAL    PRIMARY KEY,
    persona_id      BIGINT       NOT NULL REFERENCES academia_personas(id),
    ruta_id         VARCHAR(30)  NOT NULL,
    version_ruta    INTEGER      NOT NULL DEFAULT 1,
    codigo          VARCHAR(16)  NOT NULL UNIQUE,         -- código verificable impreso en el certificado
    emitido_en      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (persona_id, ruta_id, version_ruta)
);

-- Preguntas a Mostacín: ANÓNIMAS (decisión 12-11-2026). Sin nombre ni IP.
CREATE TABLE IF NOT EXISTS soporte_preguntas (
    id              BIGSERIAL    PRIMARY KEY,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    pantalla        VARCHAR(40),                          -- activeTab desde donde se preguntó
    pregunta        TEXT         NOT NULL,
    respuesta       TEXT,
    fuentes         JSONB,                                -- ids de artículos/unidades/términos usados
    no_sabe         BOOLEAN      NOT NULL DEFAULT false,  -- Mostacín no encontró respuesta en el contenido
    error           TEXT,
    modelo          VARCHAR(40),
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    costo_usd       NUMERIC(8,4),
    segundos        NUMERIC(6,1),
    util            SMALLINT     CHECK (util IN (-1, 1)), -- 👎 / 👍 del usuario
    util_comentario TEXT
);
CREATE INDEX IF NOT EXISTS ix_soporte_preguntas_fecha ON soporte_preguntas (creado_en);

COMMIT;

SELECT 'academia_personas' AS tabla, count(*) FROM academia_personas
UNION ALL SELECT 'academia_avance', count(*) FROM academia_avance
UNION ALL SELECT 'academia_intentos', count(*) FROM academia_intentos
UNION ALL SELECT 'academia_certificados', count(*) FROM academia_certificados
UNION ALL SELECT 'soporte_preguntas', count(*) FROM soporte_preguntas;
