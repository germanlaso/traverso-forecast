-- ============================================================================
-- Categoría de línea para el dashboard de rendimiento (tabla propia del módulo).
-- mrp_lineas.area mezcla planta y línea ('VESPUCIO/C3Porrones', 'SALSAS/VESPUCIO'):
-- no sirve como categoría. NO se modifica mrp_lineas (la lee el solver).
-- Carga inicial por regla: token SALSAS / LIQUIDOS / ENCURTIDOS en area y, si no, en nombre.
-- Idempotente (ON CONFLICT DO NOTHING: respeta correcciones manuales).
-- Ejecutar: docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < forecast/migrate_operacion_lineas_categoria.sql
-- ============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS mrp_operacion_lineas (
    codigo      VARCHAR(20)  PRIMARY KEY,
    categoria   VARCHAR(40)  NOT NULL,
    origen      VARCHAR(20)  NOT NULL DEFAULT 'regla',
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

WITH t AS (
    SELECT codigo,
           upper(translate(COALESCE(area, ''),   'ÁÉÍÓÚáéíóú', 'AEIOUaeiou')) AS a,
           upper(translate(COALESCE(nombre, ''), 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou')) AS n
    FROM mrp_lineas
),
c AS (
    SELECT codigo,
           COALESCE(
               CASE WHEN a LIKE '%SALSA%' THEN 'SALSAS' WHEN a LIKE '%LIQUIDO%' THEN 'LÍQUIDOS'
                    WHEN a LIKE '%ENCURTIDO%' THEN 'ENCURTIDOS' END,
               CASE WHEN n LIKE '%SALSA%' THEN 'SALSAS' WHEN n LIKE '%LIQUIDO%' THEN 'LÍQUIDOS'
                    WHEN n LIKE '%ENCURTIDO%' THEN 'ENCURTIDOS' END,
               'SIN CATEGORÍA') AS categoria
    FROM t
)
INSERT INTO mrp_operacion_lineas (codigo, categoria)
SELECT codigo, categoria FROM c
ON CONFLICT (codigo) DO NOTHING;

COMMIT;
