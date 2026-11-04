-- ============================================================================
-- Clasificación de SKU fuera del catálogo de planificación — Módulo Evaluación de la Operación
-- Tabla PROPIA del módulo: NO toca mrp_sku_lineas ni mrp_sku_params (los lee el solver).
-- Idempotente: CREATE IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING
-- (re-ejecutar agrega SKU nuevos y respeta lo ya editado a mano).
-- Ejecutar: docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < forecast/migrate_operacion_sku_linea.sql
--
-- Clases:
--   LINEA                 produce en una línea (requiere linea + u_por_caja) -> entra a KPIs de línea
--   IMPORTADO_ETIQUETADO  Kikkoman / Melitta: importado + etiquetado, fuera del MRP (decisión 04-11-26)
--   ARMADO                bi/tri packs: armado manual, no ocupa línea
--   SEMIELABORADO         códigos 8xxxxxxxxx (bolsas 250 gr): no son cajas de PT (POR CONFIRMAR)
--   POR_CLASIFICAR        sin regla: se informa aparte hasta clasificarlo
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS mrp_operacion_sku_linea (
    sku               VARCHAR(30)  PRIMARY KEY,
    descripcion       VARCHAR(160),
    clase             VARCHAR(30)  NOT NULL
        CHECK (clase IN ('LINEA','IMPORTADO_ETIQUETADO','ARMADO','SEMIELABORADO','POR_CLASIFICAR')),
    linea             VARCHAR(20),
    u_por_caja        NUMERIC(10,2),
    factor_velocidad  DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (factor_velocidad > 0),
    origen            VARCHAR(30)  NOT NULL,
    validado          BOOLEAN      NOT NULL DEFAULT FALSE,
    comentario        TEXT,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_linea_completa CHECK (clase <> 'LINEA' OR (linea IS NOT NULL AND u_por_caja > 0))
);

-- Candidatos: SKU con OF en mrp_of_sap (no granel) que no están en el catálogo de planificación.
-- Regla de formato: SKU del catálogo con los mismos últimos 4 dígitos y el mismo largo de código
-- -> se propone la línea y el u_por_caja más frecuentes, solo si concentran >= 60% del grupo.
WITH cand AS (
    SELECT o.sku, MAX(o.descripcion) AS descripcion
    FROM mrp_of_sap o
    WHERE NOT o.es_granel AND o.sku <> ''
      AND NOT EXISTS (SELECT 1 FROM mrp_sku_lineas sl WHERE sl.sku = o.sku)
    GROUP BY o.sku
),
grupos AS (
    SELECT right(sl.sku, 4) AS fmt, length(sl.sku) AS len, sl.linea, sp.u_por_caja, COUNT(*) AS n
    FROM mrp_sku_lineas sl JOIN mrp_sku_params sp ON sp.sku = sl.sku
    WHERE sl.preferida AND sp.u_por_caja > 0
    GROUP BY 1, 2, 3, 4
),
hermano AS (
    SELECT DISTINCT ON (fmt, len) fmt, len, linea, u_por_caja, n,
           n::numeric / SUM(n) OVER (PARTITION BY fmt, len) AS share,
           SUM(n) OVER (PARTITION BY fmt, len) AS n_total
    FROM grupos
    ORDER BY fmt, len, n DESC
),
clasif AS (
    SELECT c.sku, c.descripcion, h.linea AS h_linea, h.u_por_caja AS h_upc, h.n, h.n_total,
           CASE
               WHEN c.descripcion ILIKE '%KIKKOMAN%' OR c.descripcion ILIKE '%MELITTA%'
                    THEN 'IMPORTADO_ETIQUETADO'
               WHEN c.descripcion ~* '(BI|TRI)\s*PACK' THEN 'ARMADO'
               WHEN c.sku LIKE '8%' AND length(c.sku) = 10 THEN 'SEMIELABORADO'
               WHEN h.linea IS NOT NULL AND h.share >= 0.6 THEN 'LINEA'
               ELSE 'POR_CLASIFICAR'
           END AS clase
    FROM cand c
    LEFT JOIN hermano h ON h.fmt = right(c.sku, 4) AND h.len = length(c.sku)
)
INSERT INTO mrp_operacion_sku_linea
    (sku, descripcion, clase, linea, u_por_caja, origen, validado, comentario)
SELECT sku, LEFT(descripcion, 160), clase,
       CASE WHEN clase = 'LINEA' THEN h_linea END,
       CASE WHEN clase = 'LINEA' THEN h_upc END,
       CASE clase
           WHEN 'IMPORTADO_ETIQUETADO' THEN 'regla_marca'
           WHEN 'ARMADO'               THEN 'regla_descripcion'
           WHEN 'SEMIELABORADO'        THEN 'regla_codigo'
           WHEN 'LINEA'                THEN 'regla_formato'
           ELSE 'sin_regla'
       END,
       clase = 'IMPORTADO_ETIQUETADO',          -- decisión explícita de Germán; el resto queda por validar
       CASE WHEN clase = 'LINEA'
            THEN 'formato ' || right(sku, 4) || ': ' || n || '/' || n_total || ' SKU del catálogo en ' || h_linea
       END
FROM clasif
ON CONFLICT (sku) DO NOTHING;

COMMIT;
