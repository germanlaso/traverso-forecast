import sys
sys.path.insert(0, "/app")

import traceback
from datetime import date
from db_mrp import get_all_lineas, get_all_sku_params, get_all_sku_lineas
from mrp import load_params_from_db
from forecaster import run_sku_pipeline
from db import load_sales

# Cargar datos
sku_params, lineas, sku_lineas = load_params_from_db()
df = load_sales()

print("="*70)
print("PARAMETROS POR SKU (desde BD)")
print("="*70)
for sku, sp in sku_params.items():
    print(f"  {sku}: tipo={sp.tipo}, lt_sem={sp.lead_time_semanas}, "
          f"ss_dias={sp.stock_seguridad_dias}, "
          f"cap_bod={sp.cap_bodega}, batch_min={sp.batch_minimo}, "
          f"upc={sp.unidades_por_caja}")

print()
print("="*70)
print("LINEAS")
print("="*70)
for cod, ln in lineas.items():
    print(f"  {cod}: vel={ln.velocidad_u_hr} u/hr, "
          f"hrs={ln.horas_turno}, turnos={ln.turnos_dia}, "
          f"cap_dia={ln.velocidad_u_hr * ln.horas_turno * ln.turnos_dia}")

print()
print("="*70)
print("FORECASTS (primeras 4 semanas por SKU)")
print("="*70)
for sku in list(sku_params.keys())[:5]:
    try:
        result = run_sku_pipeline(df=df, sku=sku, canal=None, forecast_periods=10)
        fc = result.get("forecast", [])[:4]
        upc = sku_params[sku].unidades_por_caja
        print(f"  {sku} (upc={upc}):")
        for f in fc:
            print(f"     {f['ds'][:10]}  yhat={f['yhat']:.0f} cj  ({f['yhat']*upc:.0f} u)")
    except Exception as e:
        print(f"  {sku}: forecast fallo - {e}")

print()
print("="*70)
print("INVOCACION DEL OPTIMIZER RICO (con verbose)")
print("="*70)

from optimizer import optimizar_plan_v12_rich
from calendario import distribuir_forecast_a_diario, semana_iso_inicio

# Construir inputs en formato rico (como hace el wrapper)
sku_params_rich = {}
for sku, sp in sku_params.items():
    sku_params_rich[sku] = {
        "tipo": sp.tipo,
        "u_por_caja": int(sp.unidades_por_caja or 1),
        "lead_time_sem": float(sp.lead_time_semanas or 1),
        "ss_dias": int(sp.stock_seguridad_dias or 0),
        "batch_min_u": int(sp.batch_minimo or 0),
        "batch_mult_u": int(sp.multiplo_batch or 1),
        "cap_bodega_u": int(sp.cap_bodega or 1_000_000),
        "linea_preferida": sp.linea_preferida or "",
        "descripcion": sp.descripcion or "",
    }

lineas_params_rich = {}
for cod, ln in lineas.items():
    lineas_params_rich[cod] = {
        "velocidad_u_hr": float(ln.velocidad_u_hr or 0),
        "horas_turno": float(ln.horas_turno or 8),
        "turnos_dia": int(ln.turnos_dia or 1),
        "nombre": ln.nombre or "",
    }

sku_lineas_rich = []
for r in get_all_sku_lineas():
    sku_lineas_rich.append({
        "sku": r["sku"], "linea": r["linea"],
        "t_cambio_hrs": float(r.get("t_cambio_hrs", 0) or 0),
        "preferida": bool(r.get("preferida", False)),
        "factor_velocidad": float(r.get("factor_velocidad", 1.0) or 1.0),
    })

# Forecast rico
forecast_rich = {}
for sku in sku_params:
    try:
        result = run_sku_pipeline(df=df, sku=sku, canal=None, forecast_periods=10)
        upc = sku_params_rich[sku]["u_por_caja"]
        d = {}
        for f in result.get("forecast", []):
            try:
                fecha_obj = date.fromisoformat(str(f["ds"])[:10])
                lunes = semana_iso_inicio(fecha_obj)
                yhat_u = max(0.0, float(f.get("yhat", 0) or 0)) * upc
                d[lunes] = d.get(lunes, 0.0) + yhat_u
            except: pass
        forecast_rich[sku] = d
    except: pass

# Imprimir suma demanda por SKU vs cap bodega
print()
print("DEMANDA TOTAL HORIZONTE vs CAP BODEGA:")
for sku in sku_params:
    if sku_params_rich[sku]["tipo"] != "PRODUCCION":
        continue
    fc = forecast_rich.get(sku, {})
    total = sum(fc.values())
    cap = sku_params_rich[sku]["cap_bodega_u"]
    ratio = total / cap if cap else 0
    print(f"  {sku}: demanda_total={total:.0f} u, cap_bodega={cap} u, ratio={ratio:.1f}x")

# Stock inicial cero (worst case)
stock_inicial_rich = {sku: 0.0 for sku in sku_params}

print()
print("LLAMANDO AL OPTIMIZER...")
try:
    res = optimizar_plan_v12_rich(
        plan_mrp={},
        sku_params=sku_params_rich,
        lineas_params=lineas_params_rich,
        sku_lineas=sku_lineas_rich,
        forecast_semanal=forecast_rich,
        stock_inicial=stock_inicial_rich,
        entradas_aprobadas={},
        fecha_inicio=date.today(),
        horizonte_dias=42,
    )
    print(f"Status: {res['status']}")
    print(f"Tiempo: {res['solver_time_sec']:.2f}s")
    print(f"OFTs: {len(res.get('ofts', []))}")
    print(f"Resumen: {res.get('resumen', {})}")
except Exception as e:
    traceback.print_exc()