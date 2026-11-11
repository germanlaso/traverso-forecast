-- Informes semanales automáticos (tanda 4, 11-11-2026). Idempotente.
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_informes.sql
BEGIN;
CREATE TABLE IF NOT EXISTS mrp_informes (
    id          BIGSERIAL    PRIMARY KEY,
    semana_iso  INTEGER      NOT NULL,
    anio        INTEGER      NOT NULL,
    desde       DATE         NOT NULL,
    hasta       DATE         NOT NULL,
    titulo      TEXT         NOT NULL,
    html        TEXT         NOT NULL,
    datos       JSONB,
    ia          JSONB,
    costo_usd   NUMERIC(8,4),
    creado_por  VARCHAR(80),
    creado_en   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_informes_creado ON mrp_informes (creado_en DESC);
COMMIT;
SELECT 'mrp_informes' AS tabla, count(*) FROM mrp_informes;
