import sys
sys.path.insert(0, "/app")

from datetime import date, timedelta
from db_mrp import get_all_sku_lineas
from mrp import load_params_from_db
from forecaster import run_sku_pipeline
from db import load_sales
from calendario import semana_iso_inicio, distribuir_forecast_a_diario, capacidad_dia_unidades

sku_params, lineas, _ = load_params_from_db()
df = load_sales()

print("="*70)
print("FORECAST CRUDO DE PROPHET (todas las fechas, primeras y últimas)")
print("="*70)
for sku in ["111010290", "121010290"]:
    result = run_sku_pipeline(df=df, sku=sku, canal=None, forecast_periods=10)
    fc_list = result.get("forecast", [])
    print(f"\n  {sku}: total entries en forecast = {len(fc_list)}")
    if fc_list:
        print(f"    PRIMERA: {fc_list[0]['ds'][:10]} yhat={fc_list[0]['yhat']:.0f} cj")
        print(f"    ULTIMA:  {fc_list[-1]['ds'][:10]} yhat={fc_list[-1]['yhat']:.0f} cj")
        # Solo las del futuro
        hoy = date.today()
        futuras = [f for f in fc_list if date.fromisoformat(f["ds"][:10]) >= hoy]
        print(f"    FUTURAS (>= hoy): {len(futuras)}")
        for f in futuras[:8]:
            print(f"      {f['ds'][:10]}  yhat={f['yhat']:.0f} cj")

print()
print("="*70)
print("VERIFICANDO QUE EL FIX ESTA EN optimizer.py DEL CONTENEDOR")
print("="*70)
import inspect
from optimizer import optimizar_plan
src = inspect.getsource(optimizar_plan)
if "FIX v1.2.1: filtrar solo fechas" in src:
    print("  ✓ Fix presente")
else:
    print("  ✗ FIX NO ENCONTRADO — el archivo no tiene el cambio nuevo")

# Recortar y mostrar la parte de filtrado
for i, line in enumerate(src.split("\n")):
    if "filtrar" in line.lower() or "fecha_inicio_default" in line or "lunes_inicio" in line:
        print(f"    L{i}: {line.strip()}")

print()
print("="*70)
print("LLAMADA REAL AL WRAPPER")
print("="*70)
forecasts = {}
for sku in sku_params:
    try:
        r = run_sku_pipeline(df=df, sku=sku, canal=None, forecast_periods=10)
        forecasts[sku] = r.get("forecast", [])
    except: pass

stocks_actuales = {sku: 1000 for sku in sku_params}
ordenes, diag = optimizar_plan(
    ordenes_mrp=[],
    sku_params=sku_params,
    lineas=lineas,
    forecasts=forecasts,
    stocks_actuales=stocks_actuales,
    entradas_fijas={},
    horizonte_semanas=6,
)
print(f"  Status: {diag.get('status')}")
print(f"  Tiempo: {diag.get('tiempo_ms')}ms")
print(f"  OFTs:   {diag.get('ofts_generadas')}")