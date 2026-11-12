-- ============================================================================
-- Análisis de Línea: un solo caso VIGENTE por línea (12-11-2026, v2.2.0).
-- Un caso sin decidir pasa a 'reemplazado' cuando se abre uno más nuevo de la misma línea.
-- Lo decidido no se toca. Idempotente.
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_casos_vigentes.sql
-- ============================================================================
BEGIN;
DO $$
DECLARE c TEXT;
BEGIN
  SELECT conname INTO c FROM pg_constraint
  WHERE conrelid = 'mrp_analisis_casos'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) ILIKE '%estado%';
  IF c IS NOT NULL THEN EXECUTE format('ALTER TABLE mrp_analisis_casos DROP CONSTRAINT %I', c); END IF;
END $$;
ALTER TABLE mrp_analisis_casos ADD CONSTRAINT mrp_analisis_casos_estado_check
    CHECK (estado IN ('solicitado','en_cola','ejecutando','listo','error','en_decision',
                      'aplicado','descartado','en_seguimiento','cerrado','reemplazado'));
ALTER TABLE mrp_analisis_casos ADD COLUMN IF NOT EXISTS reemplazado_por BIGINT;

-- casos actuales: los sin decidir que ya tienen uno más nuevo (no error) de la misma línea
WITH ultimo AS (
    SELECT DISTINCT ON (linea) linea, id FROM mrp_analisis_casos
    WHERE estado NOT IN ('error') ORDER BY linea, creado_en DESC, id DESC
)
UPDATE mrp_analisis_casos k SET estado = 'reemplazado', reemplazado_por = u.id
FROM ultimo u
WHERE k.linea = u.linea AND k.id <> u.id AND k.decision IS NULL
  AND k.estado IN ('listo','solicitado','en_cola','ejecutando');

-- validaciones programadas de casos reemplazados: no gastar una noche de solver en ellas
UPDATE mrp_analisis_validaciones v SET estado = 'cancelada', fin = now(), error = 'Caso reemplazado por uno más nuevo'
FROM mrp_analisis_casos k
WHERE v.caso_id = k.id AND k.estado = 'reemplazado' AND v.estado = 'programada';
COMMIT;

SELECT linea, id, estado, decision, reemplazado_por FROM mrp_analisis_casos ORDER BY linea, id;
