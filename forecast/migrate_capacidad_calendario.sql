-- ============================================================================
-- Calendario de capacidad (11-11-2026): jornada legal de 42 h semanales.
--   mrp_lineas.turnos_config  : turnos con horas por día [L,M,X,J,V,S,D]
--                               default: 1 turno 9-9-8-8-8-0-0 (42 h)
--   mrp_capacidad_excepciones : horas totales de un día puntual (sábado trabajado,
--                               extensión de turno, día sin producción)
--   mrp_params_config.capacidad_calendario = 'off' -> el plan sigue igual que hoy hasta
--   activarlo ('on'). Para probar sin activar: CAPACIDAD_CALENDARIO=1 en cron_plan --no-promote.
-- NO modifica turnos_dia / horas_turno / dias_semana (el legado sigue intacto).
-- Idempotente. Ejecutar:
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_capacidad_calendario.sql
-- ============================================================================
BEGIN;

ALTER TABLE mrp_lineas ADD COLUMN IF NOT EXISTS turnos_config JSONB;
UPDATE mrp_lineas
SET turnos_config = '[{"turno": 1, "horas": [9, 9, 8, 8, 8, 0, 0]}]'::jsonb
WHERE turnos_config IS NULL;

CREATE TABLE IF NOT EXISTS mrp_capacidad_excepciones (
    id          BIGSERIAL     PRIMARY KEY,
    linea       VARCHAR(20)   NOT NULL,
    fecha       DATE          NOT NULL,
    horas       NUMERIC(5,2)  NOT NULL CHECK (horas >= 0 AND horas <= 24),
    tipo        VARCHAR(20)   NOT NULL DEFAULT 'extension'
        CHECK (tipo IN ('extension','sabado','domingo_feriado','sin_produccion','otro')),
    motivo      TEXT          NOT NULL,
    creado_por  VARCHAR(80)   NOT NULL,
    creado_en   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    anulado     BOOLEAN       NOT NULL DEFAULT FALSE,
    anulado_por VARCHAR(80),
    anulado_en  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cap_excepcion_vigente
    ON mrp_capacidad_excepciones (linea, fecha) WHERE NOT anulado;

-- historial: valores de texto (patrones de turnos) además de numéricos
ALTER TABLE mrp_params_historial ADD COLUMN IF NOT EXISTS valor_anterior_txt TEXT;
ALTER TABLE mrp_params_historial ADD COLUMN IF NOT EXISTS valor_nuevo_txt TEXT;

INSERT INTO mrp_params_config (clave, valor) VALUES ('capacidad_calendario', 'off')
ON CONFLICT (clave) DO NOTHING;

COMMIT;

SELECT codigo, turnos_config, turnos_dia, horas_turno, dias_semana FROM mrp_lineas WHERE activa ORDER BY codigo;
SELECT clave, valor FROM mrp_params_config WHERE clave = 'capacidad_calendario';
