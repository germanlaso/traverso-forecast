import sys
sys.path.insert(0, '/app')

from mrp import load_params_from_db, generar_plan_sku
from db_mrp import listar_aprobadas_db
from stock import load_stock_parquet, calcular_stock_disponible
from forecaster import run_sku_pipeline
from db import load_sales
from datetime import date

SKU = '121010210'

# Params
sku_params, lineas, _ = load_params_from_db()
params = sku_params[SKU]
print(f'Params: lead={params.lead_time_semanas}, ss={params.stock_seguridad_dias}, upj={params.unidades_por_caja}')

# Entradas fijas
aprobadas = listar_aprobadas_db()
hoy_str = date.today().isoformat()
print(f'Hoy: {hoy_str}')
entradas_fijas = []
for ap in aprobadas:
    if str(ap.get('sku', '')) != SKU:
        continue
    fer = str(ap.get('fecha_entrada_real') or ap.get('semana_necesidad', ''))[:10]
    cj = float(ap.get('cantidad_real_cj') or 0)
    nof = ap.get('numero_of', '')
    print(f'  OF en BD: {nof} | fer={fer} | cj={cj} | fer>hoy={fer > hoy_str}')
    if fer and cj > 0 and fer > hoy_str:
        entradas_fijas.append({
            'fecha_entrada': fer,
            'cantidad_cajas': cj,
            'aprobada': True,
            'numero_of': nof,
        })

print(f'Entradas fijas inyectadas al MRP: {len(entradas_fijas)}')
for ef in entradas_fijas:
    print(f'  -> {ef}')

# Stock actual
df_stock = load_stock_parquet()
stocks, _ = calcular_stock_disponible(df_stock, {SKU: params.unidades_por_caja})
stock_actual = stocks.get(SKU, 0)
print(f'Stock actual: {stock_actual} cj')

# Forecast
df_ventas = load_sales()
result = run_sku_pipeline(df=df_ventas, sku=SKU, forecast_periods=17)
forecast = result.get('forecast', [])
futuro = [f for f in forecast if f['ds'] >= hoy_str][:6]
print('Forecast futuro (primeras 6 semanas):')
for f in futuro:
    print(f'  {f["ds"]}: yhat={f["yhat"]:.0f} cj')

# Correr MRP
print()
print('=== PLAN MRP ===')
ordenes = generar_plan_sku(
    params=params,
    forecast=forecast,
    stock_actual_cajas=stock_actual,
    lineas=lineas,
    horizonte_semanas=8,
    entradas_fijas=entradas_fijas,
)
if not ordenes:
    print('Sin ordenes generadas')
for o in ordenes:
    print(f'  Sem {o.semana_necesidad}: {o.cantidad_cajas} cj | stock_ini={o.stock_inicial_cajas} stock_fin={o.stock_final_cajas} ss={o.ss_cajas:.0f}')
