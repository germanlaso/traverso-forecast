-- =============================================================================
-- Migración v1.2: Agregar columna factor_velocidad a mrp_sku_lineas
-- =============================================================================
-- Esta columna permite ajustar la velocidad efectiva de una línea para un
-- SKU específico. Por ejemplo, factor=0.8 significa que la línea produce el
-- 80% de su velocidad nominal cuando procesa ese SKU.
--
-- Default: 1.0 (sin ajuste).
--
-- Ejecutar UNA SOLA VEZ:
--   docker exec traverso_mrp_db psql -U mrp_user -d mrp -f /tmp/migrate_v1.2.sql
-- O bien copiando este archivo al contenedor de PostgreSQL.
-- =============================================================================

ALTER TABLE mrp_sku_lineas
    ADD COLUMN IF NOT EXISTS factor_velocidad FLOAT NOT NULL DEFAULT 1.0;

-- Verificar:
-- SELECT sku, linea, t_cambio_hrs, preferida, factor_velocidad
--   FROM mrp_sku_lineas
--   ORDER BY sku, linea;
