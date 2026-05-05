-- Limpieza previa a recarga de parámetros V4 (códigos de línea cambiarán)
BEGIN;

-- Backup conteo previo
SELECT 'mrp_aprobaciones', COUNT(*) FROM mrp_aprobaciones
UNION ALL
SELECT 'mrp_ordenes', COUNT(*) FROM mrp_ordenes;

-- Borrado en orden de dependencia
DELETE FROM mrp_aprobaciones;
DELETE FROM mrp_ordenes;

-- NOTA: NO se resetea mrp_contador_of. Decisión del usuario:
-- mantener correlativo histórico para consistencia con PDFs ya generados.

-- Verificación
SELECT 'mrp_aprobaciones', COUNT(*) FROM mrp_aprobaciones
UNION ALL
SELECT 'mrp_ordenes', COUNT(*) FROM mrp_ordenes;

COMMIT;
