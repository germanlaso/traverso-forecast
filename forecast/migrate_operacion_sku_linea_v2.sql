-- ============================================================================
-- Parche v2: clase MAQUILA para mayonesas (decisión 04-11-26: solo la 300x8 está en el MRP).
-- Idempotente. Sirve tanto si la tabla se creó con la versión 1 como con la actual.
-- Correr SIEMPRE después de migrate_operacion_sku_linea.sql.
-- ============================================================================
BEGIN;

ALTER TABLE mrp_operacion_sku_linea DROP CONSTRAINT IF EXISTS mrp_operacion_sku_linea_clase_check;
ALTER TABLE mrp_operacion_sku_linea DROP CONSTRAINT IF EXISTS ck_clase;
ALTER TABLE mrp_operacion_sku_linea ADD CONSTRAINT ck_clase
    CHECK (clase IN ('LINEA','IMPORTADO_ETIQUETADO','MAQUILA','ARMADO','SEMIELABORADO','POR_CLASIFICAR'));

UPDATE mrp_operacion_sku_linea
SET clase = 'MAQUILA', linea = NULL, u_por_caja = NULL, origen = 'decision_usuario', validado = TRUE,
    comentario = 'Mayonesa de maquila (decisión 04-11-26); solo la 300x8 está en el MRP',
    updated_at = now()
WHERE descripcion ILIKE '%MAYONESA%' AND clase <> 'MAQUILA';

COMMIT;
