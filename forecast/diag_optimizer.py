"""Diagnóstico directo del optimizador con todos los SKUs."""
import sys
sys.path.insert(0, '/app')

from mrp import load_params_from_db
from db_mrp import listar_aprobadas_db
from stock import load_stock_parquet, calcular_stock_disponible
from db import load_sales
from forecaster import run_sku_pipeline
from datetime import date

print("Cargando parámetros...")
sku_params, lineas, _ = load_params_from_db()
skus_activos = [k for k,p in sku_params.items() if p.activo]
print(f"SKUs activos: {len(skus_activos)}")
print(f"Líneas: {list(lineas.keys())}")

print("\nCargando stock...")
df_stock = load_stock_parquet()
stocks_cj, _ = calcular_stock_disponible(
    df_stock, {k: sku_params[k].unidades_por_caja for k in skus_activos}
)

print("\nCargando forecasts (puede tardar)...")
df_ventas = load_sales()
forecasts = {}
for k in skus_activos:
    try:
        r = run_sku_pipeline(df=df_ventas, sku=k, forecast_periods=17)
        forecasts[k] = r.get('forecast', [])
    except Exception as e:
        print(f"  {k}: ERROR forecast — {e}")
        forecasts[k] = []

print(f"Forecasts cargados: {len([k for k,f in forecasts.items() if f])} SKUs con datos")

# Construir entradas_fijas
aprobadas = listar_aprobadas_db()
hoy_str = date.today().isoformat()
entradas_fijas = {}
for ap in aprobadas:
    k = str(ap.get('sku',''))
    if k not in skus_activos:
        continue
    fer = str(ap.get('fecha_entrada_real') or ap.get('semana_necesidad',''))[:10]
    cj  = float(ap.get('cantidad_real_cj') or 0)
    if fer and cj > 0 and fer > hoy_str:
        entradas_fijas.setdefault(k, []).append({
            'fecha_entrada': fer, 'cantidad_cajas': cj, 'aprobada': True
        })

print(f"Entradas fijas: {sum(len(v) for v in entradas_fijas.values())} OFs aprobadas")

# Diagnóstico del modelo sin solver
print("\n=== DIAGNÓSTICO DEL MODELO ===")
from optimizer import _semanas_horizonte, _forecast_map, _aprobadas_map, _lineas_por_sku, _cap_dia_u, _cap_semana_u

hoy = date.today()
semanas = _semanas_horizonte(hoy, 13)
print(f"Semanas: {semanas[0]} → {semanas[-1]}")

fc_map  = _forecast_map(forecasts, skus_activos, semanas, sku_params)
ap_map  = _aprobadas_map(entradas_fijas, skus_activos, sku_params)
lins_ok = _lineas_por_sku(sku_params, lineas, skus_activos)

print("\nSKU → líneas permitidas:")
for k in skus_activos:
    p = sku_params[k]
    print(f"  {k}: {lins_ok.get(k, [])} (pref={p.linea_preferida})")

print("\nCapacidades de líneas:")
for cod, lin in lineas.items():
    cap_dia = _cap_dia_u(lin)
    cap_sem = _cap_semana_u(lin)
    print(f"  {cod}: cap_dia={cap_dia:.0f} u | cap_sem={cap_sem:.0f} u")

print("\nVerificando restricción R3 (stock <= cap_bodega):")
problemas = []
for i, s in enumerate(semanas[:4]):
    for k in skus_activos:
        p = sku_params[k]
        upj = p.unidades_por_caja or 1
        cap_b = p.cap_bodega
        stk_ant_u = int(stocks_cj.get(k, 0) * upj) if i == 0 else None
        dem_u = int(fc_map.get(k, {}).get(s, 0))
        ap_u  = int(ap_map.get(k, {}).get(s, 0))
        lins_k = lins_ok.get(k, [])
        max_prod_u = max(int(_cap_dia_u(lineas[l]) * p.pct_dia_max) for l in lins_k) if lins_k else 0
        
        if i == 0 and stk_ant_u is not None:
            max_stock = stk_ant_u + max_prod_u + ap_u
            if max_prod_u > cap_b:
                problemas.append(f"  ⚠️  {k} sem {s}: max_prod_u={max_prod_u} > cap_bodega={cap_b}")
            if ap_u > cap_b:
                problemas.append(f"  ⚠️  {k} sem {s}: aprobada_u={ap_u} > cap_bodega={cap_b}")

if problemas:
    print("PROBLEMAS ENCONTRADOS:")
    for p in problemas:
        print(p)
else:
    print("  Sin conflictos obvios en R3")

print("\nVerificando AddMaxEquality (posible bug en CP-SAT):")
print("  Si SS_u o cap_bodega son muy grandes, AddMaxEquality puede fallar")
for k in skus_activos[:3]:
    p = sku_params[k]
    upj = p.unidades_por_caja or 1
    dem_sample = int(fc_map.get(k, {}).get(semanas[0], 0))
    ss_u = int((dem_sample / 7) * p.stock_seguridad_dias)
    print(f"  {k}: cap_bodega={p.cap_bodega} u | ss_u_sample={ss_u} | BIG=50_000_000")

