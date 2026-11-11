-- ============================================================================
-- Análisis programado con solver (tanda 3, 11-11-2026): validaciones nocturnas de la palanca
-- recomendada en un caso de Análisis de Línea. Idempotente.
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_validaciones.sql
-- ============================================================================
BEGIN;
CREATE TABLE IF NOT EXISTS mrp_analisis_validaciones (
    id              BIGSERIAL    PRIMARY KEY,
    caso_id         BIGINT       NOT NULL REFERENCES mrp_analisis_casos(id),
    linea           VARCHAR(20)  NOT NULL,
    nivel           INTEGER      NOT NULL,             -- palancas 1..nivel acumuladas
    escenario       JSONB        NOT NULL,             -- lo que se aplica en memoria (ESCENARIO_JSON)
    descripcion     TEXT,
    semillas        INTEGER[]    NOT NULL DEFAULT '{42,7}',
    estado          VARCHAR(12)  NOT NULL DEFAULT 'programada'
        CHECK (estado IN ('programada','ejecutando','lista','error','cancelada')),
    planes          JSONB,                             -- {"base": {seed: plan_id}, "escenario": {seed: plan_id}}
    resultado       JSONB,
    solicitado_por  VARCHAR(80)  NOT NULL,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inicio          TIMESTAMPTZ,
    fin             TIMESTAMPTZ,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS ix_validaciones_estado ON mrp_analisis_validaciones (estado, creado_en);
COMMIT;
SELECT 'mrp_analisis_validaciones' AS tabla, count(*) FROM mrp_analisis_validaciones;
