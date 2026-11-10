-- ============================================================================
-- Panel de edición de parámetros (Fase 2) — tablas de soporte + recomendaciones del Informe IA
-- Idempotente. No modifica parámetros existentes.
-- Ejecutar: docker exec -i traverso_mrp_db psql -U mrp_user -d mrp -v ON_ERROR_STOP=1 < forecast/migrate_params_edicion.sql
-- ============================================================================
BEGIN;

-- Historial de cambios: quién, cuándo, qué, valor anterior -> nuevo, motivo.
CREATE TABLE IF NOT EXISTS mrp_params_historial (
    id              BIGSERIAL    PRIMARY KEY,
    ts              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    entidad         VARCHAR(12)  NOT NULL CHECK (entidad IN ('sku','sku_linea','linea')),
    sku             VARCHAR(30),
    linea           VARCHAR(20),
    campo           VARCHAR(30)  NOT NULL,
    valor_anterior  DOUBLE PRECISION,
    valor_nuevo     DOUBLE PRECISION,
    motivo          TEXT         NOT NULL,
    editor          VARCHAR(80)  NOT NULL,
    origen          VARCHAR(20)  NOT NULL DEFAULT 'panel',      -- panel | revertir | carga_masiva
    recomendacion_id BIGINT,
    revierte_id     BIGINT,
    revertido_por   BIGINT
);
CREATE INDEX IF NOT EXISTS ix_params_hist_sku   ON mrp_params_historial (sku, ts DESC);
CREATE INDEX IF NOT EXISTS ix_params_hist_linea ON mrp_params_historial (linea, ts DESC);

-- Configuración (PIN de edición, guardado como hash con sal; se define con el CLI de params_edicion.py)
CREATE TABLE IF NOT EXISTS mrp_params_config (
    clave       VARCHAR(40)  PRIMARY KEY,
    valor       TEXT         NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Recomendaciones (del Informe IA u otras fuentes). Solo sugieren: aplicar = editar y guardar.
CREATE TABLE IF NOT EXISTS mrp_params_recomendaciones (
    id              BIGSERIAL    PRIMARY KEY,
    entidad         VARCHAR(12)  NOT NULL CHECK (entidad IN ('sku','sku_linea','linea')),
    clave           VARCHAR(30)  NOT NULL,          -- sku o código de línea
    linea           VARCHAR(20)  NOT NULL DEFAULT '',   -- '' = aplica a todas las líneas del SKU
    campo           VARCHAR(30)  NOT NULL,
    valor_actual    DOUBLE PRECISION,               -- al momento de generar la recomendación
    valor_sugerido  DOUBLE PRECISION,               -- NULL = recomendación cualitativa
    rango           TEXT,
    motivo          TEXT         NOT NULL,
    prioridad       VARCHAR(12)  NOT NULL DEFAULT 'media',
    fuente          VARCHAR(80)  NOT NULL,
    estado          VARCHAR(12)  NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta','aplicada','descartada')),
    estado_por      VARCHAR(80),
    estado_en       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_params_reco UNIQUE (fuente, entidad, clave, linea, campo)
);

INSERT INTO mrp_params_recomendaciones
    (entidad, clave, linea, campo, valor_actual, valor_sugerido, rango, motivo, prioridad, fuente)
VALUES
('sku','360010255','','cap_bodega_u','16008','21100','≥ 18.276 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (18.276 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','330010235','','cap_bodega_u','16008','22000','≥ 19.045 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (19.045 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','115014340','','cap_bodega_u','7200','8800','≥ 7.575 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (7.575 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','141010176','','cap_bodega_u','12000','14400','≥ 12.477 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (12.477 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','250010110','','cap_bodega_u','12400','15700','≥ 13.598 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (13.598 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','261010110','','cap_bodega_u','18000','22100','≥ 19.190 u','Cap. bodega menor a batch mínimo + SS (stock de seguridad) estimado (19.190 u). Sugerido con 15% de margen.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','141033175','L6Vidrio','batch_min_u','750','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','113110175','L6Vidrio','batch_min_u','750','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','151010175','L6Vidrio','batch_min_u','750','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','115014175','L6Vidrio','batch_min_u','750','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','115014150','L6Vidrio','batch_min_u','750','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku','141033230','L6Vidrio','batch_min_u','450','4000','3.000–4.000 u (≈3–4 h)','Las OF reales de este SKU fueron de 3,6 a 7,6 h; el parámetro (≈0,75 h) permite al plan proponer OF más cortas que las que hace la planta.','media-alta','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121033290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121012175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121012290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121013290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121011115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121011175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121011290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121038290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122033290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122011175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122038290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122010175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122010210','L1Pet LV','factor_velocidad','0.8','0.82','formato 20x1000','Velocidad vigente del formato 20x1000: 10.000 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','122010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121030290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121010115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121010175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121010210','L1Pet LV','factor_velocidad','0.8','0.82','formato 20x1000','Velocidad vigente del formato 20x1000: 10.000 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','121010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111033290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111013290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111011115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111011175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111011290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111038290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111030290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111010115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111010175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111010210','L1Pet LV','factor_velocidad','0.8','0.82','formato 20x1000','Velocidad vigente del formato 20x1000: 10.000 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','111010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','114010115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','114010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113033290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113013290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113011175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113011290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113038290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113030290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113010115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113010175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113010210','L1Pet LV','factor_velocidad','0.8','0.82','formato 20x1000','Velocidad vigente del formato 20x1000: 10.000 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','113010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112033290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112013290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112011115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112011175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112011290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112038290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112010115','L1Pet LV','factor_velocidad','0.8','0.77','formato 12x1000','Velocidad vigente del formato 12x1000: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112010175','L1Pet LV','factor_velocidad','1.0','0.77','formato 12x500','Velocidad vigente del formato 12x500: 9.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112010210','L1Pet LV','factor_velocidad','0.8','0.82','formato 20x1000','Velocidad vigente del formato 20x1000: 10.000 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112010290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('sku_linea','112030290','L1Pet LV','factor_velocidad','1.0','1.1','formato 30x500','Velocidad vigente del formato 30x500: 13.400 bot/h según Control de Procesos (informe EV-RG-SGI-54). vs 12.222 u/h de la línea.','media','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Sachetera 4P','Sachetera 4P','turnos_dia','1',NULL,'confirmar régimen real','Produjo 182% y 143% de su capacidad nominal en las Sem 44 y 45, con 4 días de fin de semana trabajados (incl. festivo 01-11). Si las extensiones o fines de semana son habituales, reflejarlos en turnos_dia / dias_semana; si son puntuales, registrarlos en la bitácora.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Sachetera','Sachetera','turnos_dia','1',NULL,'confirmar régimen real','Llegó a 193% de su capacidad nominal (Sem 41); 6 días de fin de semana y 13 días sobre el turno en Sem 37–45. Si las extensiones o fines de semana son habituales, reflejarlos en turnos_dia / dias_semana; si son puntuales, registrarlos en la bitácora.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Doypack','Doypack','turnos_dia','1',NULL,'confirmar régimen real','Llegó a 180% de su capacidad nominal (Sem 39); 15 días sobre el turno en Sem 37–45. Si las extensiones o fines de semana son habituales, reflejarlos en turnos_dia / dias_semana; si son puntuales, registrarlos en la bitácora.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Sachetera 1P','Sachetera 1P','turnos_dia','1',NULL,'confirmar régimen real','Llegó a 158% de su capacidad nominal (Sem 38); 7 días sobre el turno. Si las extensiones o fines de semana son habituales, reflejarlos en turnos_dia / dias_semana; si son puntuales, registrarlos en la bitácora.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Doypack','Doypack','batch_min_u',NULL,NULL,'mínimo técnico (a definir con Producción)','El batch mínimo de los SKU de esta línea equivale a un día completo de línea; en 39 de 80 semanas-SKU (Doypack 1–4 y Sachetera) lo producido por OF fue menor a ese mínimo.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Doypack 2','Doypack 2','batch_min_u',NULL,NULL,'mínimo técnico (a definir con Producción)','El batch mínimo de los SKU de esta línea equivale a un día completo de línea; en 39 de 80 semanas-SKU (Doypack 1–4 y Sachetera) lo producido por OF fue menor a ese mínimo.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Doypack 3','Doypack 3','batch_min_u',NULL,NULL,'mínimo técnico (a definir con Producción)','El batch mínimo de los SKU de esta línea equivale a un día completo de línea; en 39 de 80 semanas-SKU (Doypack 1–4 y Sachetera) lo producido por OF fue menor a ese mínimo.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Doypack 4','Doypack 4','batch_min_u',NULL,NULL,'mínimo técnico (a definir con Producción)','El batch mínimo de los SKU de esta línea equivale a un día completo de línea; en 39 de 80 semanas-SKU (Doypack 1–4 y Sachetera) lo producido por OF fue menor a ese mínimo.','alta','Informe IA Sem 37-45 (10-11-2026)'),
('linea','Sachetera','Sachetera','batch_min_u',NULL,NULL,'mínimo técnico (a definir con Producción)','El batch mínimo de los SKU de esta línea equivale a un día completo de línea; en 39 de 80 semanas-SKU (Doypack 1–4 y Sachetera) lo producido por OF fue menor a ese mínimo.','alta','Informe IA Sem 37-45 (10-11-2026)')
ON CONFLICT ON CONSTRAINT uq_params_reco DO NOTHING;

COMMIT;

SELECT entidad, campo, prioridad, COUNT(*) FROM mrp_params_recomendaciones GROUP BY 1,2,3 ORDER BY 1,2;
