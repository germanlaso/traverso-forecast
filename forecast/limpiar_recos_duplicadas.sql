-- ============================================================================
-- Limpieza única (11-11-2026): recomendaciones ABIERTAS repetidas para el mismo SKU/línea y
-- campo (creadas por casos distintos de Análisis de Línea). Se conserva la MÁS RECIENTE de cada
-- grupo y las demás quedan 'descartada' por el Sistema, con la nota. No borra nada.
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/limpiar_recos_duplicadas.sql
-- ============================================================================
BEGIN;
SELECT entidad, clave, linea, campo, count(*) AS abiertas
FROM mrp_params_recomendaciones WHERE estado = 'abierta'
GROUP BY 1, 2, 3, 4 HAVING count(*) > 1 ORDER BY 2, 4;

WITH ranking AS (
    SELECT id, first_value(id) OVER (PARTITION BY entidad, clave, linea, campo ORDER BY created_at DESC, id DESC) AS conservar
    FROM mrp_params_recomendaciones WHERE estado = 'abierta'
)
UPDATE mrp_params_recomendaciones r
SET estado = 'descartada', estado_por = 'Sistema (duplicada)', estado_en = now(),
    motivo = r.motivo || ' | Duplicada: se conserva la recomendación #' || k.conservar || '.'
FROM ranking k
WHERE r.id = k.id AND k.id <> k.conservar;

-- las acciones de casos que apuntaban a las descartadas siguen pendientes: se cierran cuando
-- se aplique o descarte la recomendación conservada (misma combinación SKU + campo).
COMMIT;

SELECT estado, count(*) FROM mrp_params_recomendaciones GROUP BY 1 ORDER BY 1;
