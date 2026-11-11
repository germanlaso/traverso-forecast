-- ============================================================================
-- Análisis de Línea: acciones por caso (aceptar todo / en parte / descartar) y vínculo
-- con el aprendizaje (intervenciones) y con el panel de parámetros (recomendaciones).
-- Idempotente. Ejecutar:
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_acciones_caso.sql
-- ============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS mrp_analisis_acciones (
    id                 BIGSERIAL    PRIMARY KEY,
    caso_id            BIGINT       NOT NULL REFERENCES mrp_analisis_casos(id),
    orden              INTEGER      NOT NULL,
    palanca            VARCHAR(30),
    accion             TEXT         NOT NULL,
    efecto_esperado    TEXT,
    costo_o_riesgo     TEXT,
    cambios_parametros JSONB,
    -- aceptada = pendiente de ejecutar (si no es de parámetros) · rechazada · hecha · descartada
    estado             VARCHAR(12)  NOT NULL CHECK (estado IN ('aceptada','rechazada','hecha','descartada')),
    intervencion_id    BIGINT       REFERENCES mrp_intervenciones(id),
    recomendaciones    INTEGER      NOT NULL DEFAULT 0,   -- cambios enviados al panel
    resuelto_por       VARCHAR(80),
    resuelto_en        TIMESTAMPTZ,
    comentario         TEXT,
    creado_en          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_accion_caso UNIQUE (caso_id, orden)
);
CREATE INDEX IF NOT EXISTS ix_analisis_acciones_estado ON mrp_analisis_acciones (estado);

-- recomendación del panel -> intervención (al aplicarla en el panel, el cambio queda enlazado)
ALTER TABLE mrp_params_recomendaciones ADD COLUMN IF NOT EXISTS intervencion_id BIGINT;
ALTER TABLE mrp_params_recomendaciones ADD COLUMN IF NOT EXISTS caso_id BIGINT;

COMMIT;

SELECT 'mrp_analisis_acciones' AS tabla, count(*) FROM mrp_analisis_acciones;
