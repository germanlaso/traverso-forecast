-- F3: Cambiar clave de identificación de OFTs/OFs de
--     (sku, semana_emision, semana_necesidad) a (sku, fecha_lanzamiento, linea).
-- 
-- 1) Agregar columna fecha_lanzamiento (aditiva, sin pérdida)
-- 2) Backfill desde fecha_lanzamiento_real (si aprobada) o semana_emision (fallback)
-- 3) Verificar consistencia
-- 4) Agregar UNIQUE constraint sobre (sku, fecha_lanzamiento, linea)

BEGIN;

-- 1) Columna nueva
ALTER TABLE mrp_ordenes 
ADD COLUMN IF NOT EXISTS fecha_lanzamiento DATE;

-- 2) Backfill: usar fecha_lanzamiento_real de la última aprobación, sino semana_emision
UPDATE mrp_ordenes o
SET fecha_lanzamiento = COALESCE(
    (SELECT a.fecha_lanzamiento_real
     FROM mrp_aprobaciones a 
     WHERE a.numero_of = o.numero_of 
       AND a.estado = 'APROBADA'
       AND a.fecha_lanzamiento_real IS NOT NULL
     ORDER BY a.version DESC 
     LIMIT 1),
    o.semana_emision
)
WHERE o.fecha_lanzamiento IS NULL;

-- 3) Verificar que el backfill no dejó NULLs
DO $$
DECLARE
    n_null INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_null FROM mrp_ordenes WHERE fecha_lanzamiento IS NULL;
    IF n_null > 0 THEN
        RAISE EXCEPTION 'Backfill incompleto: % filas con fecha_lanzamiento NULL', n_null;
    END IF;
END $$;

-- 4) Verificar que no hay duplicados en (sku, fecha_lanzamiento, linea)
DO $$
DECLARE
    n_dup INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_dup FROM (
        SELECT sku, fecha_lanzamiento, linea, COUNT(*) AS c
        FROM mrp_ordenes
        GROUP BY sku, fecha_lanzamiento, linea
        HAVING COUNT(*) > 1
    ) dup;
    IF n_dup > 0 THEN
        RAISE EXCEPTION 'Hay % grupos duplicados en (sku, fecha_lanzamiento, linea) — revisar antes de UNIQUE', n_dup;
    END IF;
END $$;

-- 5) UNIQUE constraint (crea índice automático)
ALTER TABLE mrp_ordenes 
ADD CONSTRAINT uq_orden_sku_fecha_linea UNIQUE (sku, fecha_lanzamiento, linea);

COMMIT;
