-- ============================================================================
-- Capa de APRENDIZAJE (eje del Análisis de Línea) — MVP 1
--   mrp_analisis_casos        : cada análisis de línea, completo (síntomas, diagnóstico,
--                               escenarios, recomendación, decisión humana y su motivo)
--   mrp_intervenciones        : cada cambio aplicado = palanca + contexto + hipótesis +
--                               efecto esperado vs observado + veredicto (qué funciona y cuándo)
--   mrp_conocimiento_empirico : parámetro teórico vs dato empírico, con rango, n y confianza
-- Idempotente. Ejecutar:
--   docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_aprendizaje.sql
-- ============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS mrp_analisis_casos (
    id               BIGSERIAL    PRIMARY KEY,
    linea            VARCHAR(20)  NOT NULL,
    creado_en        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    origen           VARCHAR(12)  NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual','automatico','programado')),
    solicitado_por   VARCHAR(80),
    plan_id          INTEGER,
    estado           VARCHAR(14)  NOT NULL DEFAULT 'solicitado'
        CHECK (estado IN ('solicitado','en_cola','ejecutando','listo','error','en_decision',
                          'aplicado','descartado','en_seguimiento','cerrado')),
    sintomas         JSONB,       -- semáforo, carga requerida, quiebres que lo dispararon
    diagnostico      JSONB,       -- causas clasificadas + evidencia (incluye señales de forecast)
    escenarios       JSONB,       -- palancas probadas en orden de esfuerzo, con efecto y costo
    recomendacion    JSONB,       -- texto IA + acciones propuestas + supuestos y riesgos
    decision         VARCHAR(12)  CHECK (decision IN ('aceptada','parcial','descartada')),
    decision_por     VARCHAR(80),
    decision_motivo  TEXT,        -- los motivos de rechazo también enseñan
    decision_en      TIMESTAMPTZ,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS ix_analisis_casos_linea ON mrp_analisis_casos (linea, creado_en DESC);

CREATE TABLE IF NOT EXISTS mrp_intervenciones (
    id                BIGSERIAL    PRIMARY KEY,
    caso_id           BIGINT       REFERENCES mrp_analisis_casos(id),
    creado_en         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    aplicado_en       TIMESTAMPTZ,
    palanca           VARCHAR(30)  NOT NULL CHECK (palanca IN (
                        'param_batch','param_cap_bodega','param_factor','param_ss','param_velocidad',
                        'turnos','linea_alternativa','ampliacion','forecast','otro')),
    linea             VARCHAR(20),
    skus              TEXT[],
    historial_ids     BIGINT[],    -- vínculo con mrp_params_historial (qué se cambió exactamente)
    contexto          JSONB,       -- estado de la línea al intervenir: uso, carga, causa, n SKU...
    hipotesis         TEXT,
    efecto_esperado   JSONB,
    efecto_observado  JSONB,
    veredicto         VARCHAR(32)  NOT NULL DEFAULT 'pendiente' CHECK (veredicto IN (
                        'pendiente','funciono','funciono_con_efecto_secundario','no_funciono','no_concluyente')),
    aprendizaje       TEXT,        -- la regla o lección en una frase
    evidencia         JSONB,       -- planes comparados, método (control, semillas), cifras
    evaluado_en       TIMESTAMPTZ,
    evaluado_por      VARCHAR(80),
    CONSTRAINT uq_intervencion_semilla UNIQUE (palanca, linea, hipotesis)
);
CREATE INDEX IF NOT EXISTS ix_intervenciones_palanca ON mrp_intervenciones (palanca, veredicto);

CREATE TABLE IF NOT EXISTS mrp_conocimiento_empirico (
    id              BIGSERIAL    PRIMARY KEY,
    entidad         VARCHAR(12)  NOT NULL CHECK (entidad IN ('linea','sku','sku_linea','formato')),
    clave           VARCHAR(40)  NOT NULL,
    metrica         VARCHAR(40)  NOT NULL,   -- capacidad_semanal_pct, velocidad_u_hr, setup_min, batch_real_u, error_forecast...
    valor_teorico   DOUBLE PRECISION,
    valor_empirico  DOUBLE PRECISION,        -- típico (mediana o promedio de mejores semanas, según métrica)
    p10             DOUBLE PRECISION,
    p50             DOUBLE PRECISION,
    p90             DOUBLE PRECISION,
    n_obs           INTEGER      NOT NULL DEFAULT 0,
    ventana_desde   DATE,
    ventana_hasta   DATE,
    confianza       VARCHAR(10)  CHECK (confianza IN ('baja','media','alta')),
    nota            TEXT,
    actualizado_en  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_conocimiento UNIQUE (entidad, clave, metrica)
);

-- ── Primeras intervenciones: evaluación 331 (antes) vs 333/334 (después), 11-11-2026 ──────────
INSERT INTO mrp_intervenciones
    (palanca, linea, skus, historial_ids, aplicado_en, contexto, hipotesis, efecto_esperado,
     efecto_observado, veredicto, aprendizaje, evidencia, evaluado_en, evaluado_por)
VALUES
('param_batch', 'L6Vidrio',
 ARRAY['113110175','115014150','115014175','141033175','141033230','151010175'],
 (SELECT array_agg(id ORDER BY id) FROM mrp_params_historial WHERE campo = 'batch_min_u' AND origen = 'panel'),
 '2026-11-10',
 '{"uso_proyectado_pct": 96, "cambios_sku_4sem": 35, "horas_por_of": 2.8, "causa": "batch parametrizado (0,75 h) muy inferior a las OF reales (3,6-7,6 h)", "linea_saturada": true}',
 'Alinear el batch mínimo con lo que la planta ya produce reduce cambios de SKU y libera capacidad en una línea saturada.',
 '{"cambios_sku": "baja", "uso": "baja", "quiebres": "sin cambio"}',
 '{"cambios_sku_4sem": [35, 26, 23], "of_tentativas": [53, 43, 40], "horas_por_of": [2.8, 3.2, 3.5], "uso_pct": [96, 88, 89], "quiebres_dias_skus_editados": [2, 10, 14], "nota": "SKU con batch nuevo con quiebres en la primera semana; mezclado con 4 OF aprobadas el 10-11 en L6Vidrio"}',
 'funciono_con_efecto_secundario',
 'En línea saturada, subir el batch reduce cambios (-26 a -34%) y libera ~8 pts de uso, pero puede postergar SKU urgentes en la primera semana; evitar batches que cubran más de ~10 días de demanda (caso Soya Cuisine 24x187,5 = 20 días).',
 '{"planes": [331, 333, 334], "metodo": "antes/después + grupo de control (SKU no editados); 1 corrida por plan", "limitaciones": "OF aprobadas el mismo día en L6Vidrio; ruido del solver entre corridas"}',
 '2026-11-11', 'Germán Laso'),

('param_cap_bodega', 'varias',
 (SELECT array_agg(DISTINCT sku) FROM mrp_params_historial WHERE campo = 'cap_bodega_u' AND origen = 'panel'),
 (SELECT array_agg(id ORDER BY id) FROM mrp_params_historial WHERE campo = 'cap_bodega_u' AND origen = 'panel'),
 '2026-11-10',
 '{"causa": "cap. bodega menor a batch mínimo + SS en 6 SKU (Informe IA) + 10 ajustes adicionales", "skus": 16}',
 'Subir la cap. bodega a batch + SS elimina la restricción infactible y reduce alertas de exceso de bodega.',
 '{"exceso_bodega": "baja", "quiebres": "baja en SKU con conflicto"}',
 '{"alertas_exceso_bodega_total": [193, 117, 110], "exceso_bodega_skus_editados": [81, 60, 60], "quiebres_dias_skus_editados": [6, 13, 13]}',
 'funciono',
 'Alinear cap. bodega con batch + SS reduce ~40% las alertas de exceso de bodega. El efecto en quiebres no es concluyente con una corrida (ruido del solver).',
 '{"planes": [331, 333, 334], "metodo": "antes/después + grupo de control; 1 corrida por plan"}',
 '2026-11-11', 'Germán Laso'),

('param_factor', 'L1Pet LV',
 (SELECT array_agg(DISTINCT sku) FROM mrp_params_historial WHERE campo = 'factor_velocidad' AND origen = 'panel'),
 (SELECT array_agg(id ORDER BY id) FROM mrp_params_historial WHERE campo = 'factor_velocidad' AND origen = 'panel'),
 '2026-11-10',
 '{"uso_proyectado_pct": 52, "linea_saturada": false, "causa": "velocidad única por cc; vigentes por formato de caja (Control de Procesos)"}',
 'Factor de velocidad por formato acerca el plan a la realidad sin afectar quiebres en una línea con holgura.',
 '{"uso": "similar", "quiebres": "sin cambio", "realismo": "mejora"}',
 '{"uso_pct": [52, 53, 51], "quiebres_dias": [0, 0, 0], "of_tentativas": [73, 74, 69], "exceso_bodega": [8, 33, 27]}',
 'funciono',
 'En líneas con holgura, corregir velocidades es neutro para quiebres: mejora la precisión del plan. Vigilar el alza de alertas de exceso de bodega (8 -> 27-33).',
 '{"planes": [331, 333, 334], "metodo": "antes/después; 1 corrida por plan"}',
 '2026-11-11', 'Germán Laso')
ON CONFLICT ON CONSTRAINT uq_intervencion_semilla DO NOTHING;

COMMIT;

SELECT id, palanca, linea, veredicto, cardinality(skus) AS n_skus, cardinality(historial_ids) AS n_cambios FROM mrp_intervenciones ORDER BY id;
