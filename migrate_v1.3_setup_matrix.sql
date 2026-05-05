-- Tabla de matriz de setups SKU→SKU por línea (preparación para F2/F5)
BEGIN;

CREATE TABLE IF NOT EXISTS mrp_setup_matrix (
    sku_desde       VARCHAR(30) NOT NULL,
    sku_hasta       VARCHAR(30) NOT NULL,
    linea           VARCHAR(20) NOT NULL,
    tiempo_horas    FLOAT NOT NULL CHECK (tiempo_horas >= 0),
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (sku_desde, sku_hasta, linea)
);

CREATE INDEX IF NOT EXISTS idx_setup_matrix_linea
    ON mrp_setup_matrix(linea);

CREATE INDEX IF NOT EXISTS idx_setup_matrix_destino
    ON mrp_setup_matrix(sku_hasta, linea);

COMMIT;
