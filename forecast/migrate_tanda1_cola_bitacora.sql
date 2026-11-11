-- ============================================================================
-- Tanda 1 (11-11-2026): cola única del solver + bitácora "Bloqueo programado"
-- Idempotente. Ejecutar:
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_tanda1_cola_bitacora.sql
-- ============================================================================
BEGIN;

-- Cola del solver (traza; la exclusión la da un advisory lock de PostgreSQL)
CREATE TABLE IF NOT EXISTS mrp_solver_cola (
    id              BIGSERIAL    PRIMARY KEY,
    tipo            VARCHAR(30)  NOT NULL,     -- plan_cron | prevuelo | prueba | plan_manual | analisis_programado
    descripcion     TEXT,
    solicitado_por  VARCHAR(80),
    estado          VARCHAR(14)  NOT NULL DEFAULT 'en_cola'
        CHECK (estado IN ('en_cola','ejecutando','terminado','error','cancelado','interrumpido')),
    pid             INTEGER,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    inicio          TIMESTAMPTZ,
    fin             TIMESTAMPTZ,
    espera_s        INTEGER,
    detalle         TEXT
);
CREATE INDEX IF NOT EXISTS ix_solver_cola_estado ON mrp_solver_cola (estado, creado_en DESC);

-- Bitácora: categoría nueva BLOQUEO_PROGRAMADO (bloquea horas del solver, como PARADA_PLANIFICADA)
DO $$
DECLARE c TEXT;
BEGIN
  SELECT conname INTO c FROM pg_constraint
  WHERE conrelid = 'mrp_eventos_tipos'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) ILIKE '%categoria%';
  IF c IS NOT NULL THEN
    EXECUTE format('ALTER TABLE mrp_eventos_tipos DROP CONSTRAINT %I', c);
  END IF;
END $$;
ALTER TABLE mrp_eventos_tipos ADD CONSTRAINT mrp_eventos_tipos_categoria_check
    CHECK (categoria IN ('PARADA_PLANIFICADA','PARADA_NO_PLANIFICADA','SIN_PROGRAMA','INFORMATIVO','BLOQUEO_PROGRAMADO'));

INSERT INTO mrp_eventos_tipos (codigo, nombre, categoria, requiere_duracion, orden) VALUES
    ('BLOQUEO_PROG', 'Bloqueo programado (capacitación, inventario, auditoría, otro)', 'BLOQUEO_PROGRAMADO', TRUE, 35)
ON CONFLICT (codigo) DO NOTHING;

-- Interruptor: los bloqueos a futuro de la bitácora restan horas al solver ('on' por defecto)
INSERT INTO mrp_params_config (clave, valor) VALUES ('bloqueos_bitacora', 'on')
ON CONFLICT (clave) DO NOTHING;

COMMIT;

SELECT codigo, nombre, categoria FROM mrp_eventos_tipos ORDER BY orden;
