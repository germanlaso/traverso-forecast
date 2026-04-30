"""
migrate_params.py
Migra los parámetros MRP del Excel a PostgreSQL.
Ejecutar una sola vez (o cuando se quiera reimportar desde el Excel).

Uso:
    python migrate_params.py [ruta_excel]
    python migrate_params.py /app/data/Traverso_Parametros_MRP.xlsx
"""
import sys
import math
import openpyxl
from db_mrp import (
    crear_tablas_params,
    upsert_linea,
    upsert_sku_params,
    upsert_sku_linea,
    borrar_todas_sku_lineas,
)

EXCEL_PATH = sys.argv[1] if len(sys.argv) > 1 else "/app/data/Traverso_Parametros_MRP.xlsx"

def _float(v, default=0.0):
    try: return float(v) if v is not None else default
    except: return default

def _int(v, default=0):
    try: return int(float(v)) if v is not None else default
    except: return default

def _str(v, default=""):
    return str(v).strip() if v is not None else default

# Mapa nombre línea → código (para SKU_PARAMS que usa nombre)
LINEA_NOMBRE_A_CODIGO = {}

def migrar():
    print(f"Leyendo Excel: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    print(f"Pestañas: {wb.sheetnames}")

    # ── Crear tablas ──────────────────────────────────────────────────────────
    crear_tablas_params()
    print("Tablas creadas/verificadas en PostgreSQL")

    # ── Migrar LINEAS_PRODUCCION ──────────────────────────────────────────────
    ws_lin = wb['LINEAS_PRODUCCION']
    rows_lin = list(ws_lin.iter_rows(min_row=4, values_only=True))
    
    n_lineas = 0
    for row in rows_lin:
        codigo = _str(row[0])
        if not codigo or codigo.startswith("Nota"):
            continue
        activa = _str(row[10], "S").upper() == "S"
        if not activa:
            continue

        turnos    = _int(row[3], 1)
        horas     = _float(row[4], 8)
        dias      = _int(row[5], 5)
        velocidad = _float(row[7], 0)

        linea = {
            "codigo":         codigo,
            "nombre":         _str(row[1]),
            "area":           _str(row[2]),
            "turnos_dia":     turnos,
            "horas_turno":    horas,
            "dias_semana":    dias,
            "velocidad_u_hr": velocidad,
            "activa":         True,
        }
        upsert_linea(linea)
        LINEA_NOMBRE_A_CODIGO[_str(row[1]).lower()] = codigo
        cap = turnos * horas * dias * velocidad
        print(f"  Línea {codigo}: {_str(row[1])} | vel={velocidad} u/hr | cap={cap:,.0f} u/sem")
        n_lineas += 1

    print(f"→ {n_lineas} líneas migradas")

    # ── Migrar SKU_PARAMS ─────────────────────────────────────────────────────
    ws_sku = wb['SKU_PARAMS']
    rows_sku = list(ws_sku.iter_rows(min_row=4, values_only=True))

    n_skus = 0
    for row in rows_sku:
        sku = _str(row[0])
        if not sku or not sku[0].isdigit():
            continue

        activo_val = _str(row[14], "S").upper()
        activo = activo_val == "S"

        # Mapear nombre de línea a código
        linea_nombre = _str(row[10]).lower()
        linea_cod = ""
        if linea_nombre:  # solo si el Excel especifica algo
            for nombre_key, cod_val in LINEA_NOMBRE_A_CODIGO.items():
                if linea_nombre in nombre_key or nombre_key in linea_nombre:
                    linea_cod = cod_val
                    break
            # Fallback por palabras clave SOLO si hay nombre de línea pero no match exacto
            if not linea_cod:
                if "liquid" in linea_nombre or "limon" in linea_nombre or "vinagre" in linea_nombre:
                    linea_cod = "L001"
                elif "salsa" in linea_nombre:
                    linea_cod = "S001"
        # NOTA: si linea_nombre está vacío (típico en IMPORTACION), linea_cod queda en ""
        # — antes este caso caía en el fallback "liquid/vinagre/limon" y asignaba L001 mal.

        params = {
            "sku":             sku,
            "descripcion":     _str(row[1]),
            "categoria":       _str(row[3]),
            "tipo":            _str(row[4], "PRODUCCION"),
            "u_por_caja":      _int(row[2], 1),
            "lead_time_sem":   _float(row[5], 1),
            "ss_dias":         _int(row[6], 15),
            "batch_min_u":     _int(row[7], 0),
            "batch_mult_u":    _int(row[8], 1) or 1,
            "cap_bodega_u":    _int(row[9], 999999) or 999999,
            "t_cambio_hrs":    _float(row[11], 0),
            "linea_preferida": linea_cod,
            "activo":          activo,
        }
        upsert_sku_params(params)
        print(f"  SKU {sku}: {params['descripcion'][:35]} | linea={linea_cod} | cap_bod={params['cap_bodega_u']:,}")
        n_skus += 1

    print(f"→ {n_skus} SKUs migrados")

    # ── Migrar SKU_LINEA (pares SKU ↔ Línea con t_cambio y factor_velocidad) ──
    # Estrategia: borrar todos los pares y re-insertar desde el Excel (fuente
    # de verdad). Así, si en el Excel se eliminó un par, también se elimina en BD.
    if 'SKU_LINEA' in wb.sheetnames:
        ws_sl = wb['SKU_LINEA']
        rows_sl = list(ws_sl.iter_rows(min_row=4, values_only=True))

        # Limpieza previa: borrar todos los registros antes de re-insertar
        borrar_todas_sku_lineas()

        n_sku_lineas = 0
        for row in rows_sl:
            sku    = _str(row[0])      # col A: SKU
            linea  = _str(row[2])      # col C: Código Línea
            t_camb = _float(row[4], 0) # col E: T. Cambio Batch (hrs)
            pref_s = _str(row[5], "N").upper()  # col F: Línea Preferida (S/N)
            factor = _float(row[6], 1.0)        # col G: Factor_Velocidad

            # Filtrar filas vacías o de notas
            if not sku or not sku[0].isdigit():
                continue
            if not linea:
                print(f"  ⚠ SKU_LINEA fila ignorada (linea vacía): sku={sku}")
                continue
            if factor <= 0:
                print(f"  ⚠ factor_velocidad inválido para {sku}/{linea}, usando 1.0")
                factor = 1.0

            preferida = (pref_s == "S")

            rec = {
                "sku":              sku,
                "linea":            linea,
                "t_cambio_hrs":     t_camb,
                "preferida":        preferida,
                "factor_velocidad": factor,
            }
            upsert_sku_linea(rec)
            flag = " ★" if preferida else "  "
            warn = "  ⚠" if factor != 1.0 else ""
            print(f"  {flag} {sku} → {linea} | t_camb={t_camb}h | factor={factor}{warn}")
            n_sku_lineas += 1

        print(f"→ {n_sku_lineas} pares SKU-Línea migrados")
    else:
        print("⚠ Pestaña SKU_LINEA no encontrada en el Excel — paso saltado")

    print("\n✅ Migración completada exitosamente")

if __name__ == "__main__":
    migrar()
