"""
check.py — Script de validacion rapida del entorno
Traverso S.A. · Uso: python3 check.py

Verifica en segundos:
  - Que los archivos criticos son la version correcta
  - Que el Excel de parametros MRP existe y se puede leer
  - Que la conexion SQL funciona
  - Que los modelos entrenados existen
"""
import sys
import os
import hashlib
from pathlib import Path

OK    = "✓"
FAIL  = "✗"
WARN  = "⚠"

def check(label, condition, detail=""):
    icon = OK if condition else FAIL
    print(f"  {icon} {label}" + (f" — {detail}" if detail else ""))
    return condition

results = []
print("\n=== Traverso Forecast — Validacion de entorno ===\n")

# 1. Archivos Python criticos
print("[ Archivos Python ]")
for fname in ["main.py", "mrp.py", "forecaster.py", "db.py", "seasonality.py"]:
    path = Path(f"/app/{fname}")
    exists = path.exists()
    results.append(check(fname, exists, "OK" if exists else "NO ENCONTRADO"))

# 2. Contenido critico de mrp.py
print("\n[ Version mrp.py ]")
mrp_content = Path("/app/mrp.py").read_text(encoding="utf-8")
results.append(check("Sin bloque Fallback", "Fallback" not in mrp_content,
                     "OK" if "Fallback" not in mrp_content else "VERSION VIEJA"))
results.append(check("Mapeo 'Tipo Abastecimiento'", "'Tipo Abastecimiento'" in mrp_content,
                     "OK" if "'Tipo Abastecimiento'" in mrp_content else "MAPEO INCORRECTO"))
results.append(check("Mapeo 'Unidades por Caja'", "'Unidades por Caja'" in mrp_content,
                     "OK" if "'Unidades por Caja'" in mrp_content else "MAPEO INCORRECTO"))

# 3. Excel MRP
print("\n[ Excel MRP ]")
excel_path = Path("/app/data/Traverso_Parametros_MRP.xlsx")
excel_exists = excel_path.exists()
results.append(check("Excel existe", excel_exists,
                     f"{excel_path.stat().st_size/1024:.1f} KB" if excel_exists else "NO ENCONTRADO"))

if excel_exists:
    try:
        import pandas as pd
        xl = pd.ExcelFile(str(excel_path))
        df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
        df.columns = [str(c).replace('\n', ' ').strip() for c in df.columns]
        df2 = df.rename(columns={'SKU (Código SAP)': 'sku', 'Lead Time (semanas)': 'lead_time_semanas'})
        df2['sku'] = df2['sku'].astype(str).str.strip()
        df2 = df2[df2['sku'].str.match(r'^\d+$')]
        df2 = df2.dropna(subset=['lead_time_semanas'])
        results.append(check("SKUs con parametros completos", len(df2) > 0, f"{len(df2)} SKUs"))
        
        df_lin = pd.read_excel(xl, sheet_name='LINEAS_PRODUCCION', header=2)
        df_lin.columns = [str(c).replace('\n', ' ').strip() for c in df_lin.columns]
        df_lin = df_lin.dropna(subset=[c for c in df_lin.columns if 'elocidad' in c or 'Velocidad' in c][:1])
        results.append(check("Lineas de produccion", len(df_lin) > 0, f"{len(df_lin)} lineas"))
    except Exception as e:
        results.append(check("Lectura Excel", False, str(e)))

# 4. Modelos entrenados
print("\n[ Modelos Prophet ]")
models_dir = Path("/app/models")
if models_dir.exists():
    pkls = list(models_dir.glob("*.pkl"))
    results.append(check("Modelos entrenados", len(pkls) > 0, f"{len(pkls)} modelos"))
else:
    results.append(check("Carpeta models", False, "NO EXISTE"))

# 5. Conexion SQL
print("\n[ Conexion SQL ]")
try:
    from db import test_connection
    result = test_connection()
    results.append(check("SQL Server", result["ok"],
                         result.get("version", result.get("error", ""))[:60]))
except Exception as e:
    results.append(check("SQL Server", False, str(e)[:60]))

# Resumen
total = len(results)
ok    = sum(results)
print(f"\n{'='*50}")
print(f"Resultado: {ok}/{total} checks OK")
if ok == total:
    print("Sistema listo para operar.")
else:
    print(f"{total-ok} problema(s) detectado(s) — revisar items marcados con {FAIL}")
print()
