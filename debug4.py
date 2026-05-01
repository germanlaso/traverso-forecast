import sys
sys.path.insert(0, "/app")

from datetime import date, timedelta
from db_mrp import get_all_sku_lineas
from mrp import load_params_from_db
from forecaster import run_sku_pipeline
from db import load_sales
from calendario import semana_iso_inicio, distribuir_forecast_a_diario, capacidad_dia_unidades, generar_horizonte_diario
from optimizer import _construir_modelo, _agregar_objetivo, STOCK_LOWER_BOUND_FACTOR
from ortools.sat.python import cp_model

sku_params, lineas, _ = load_params_from_db()
df = load_sales()

# (idéntico setup que debug3) ...
sku_params_rich = {sku: {
    "tipo": sp.tipo, "u_por_caja": int(sp.unidades_por_caja or 1),
    "lead_time_sem": float(sp.lead_time_semanas or 1),
    "ss_dias": int(sp.stock_seguridad_dias or 0),
    "batch_min_u": int(sp.batch_minimo or 0),
    "batch_mult_u": int(sp.multiplo_batch or 1),
    "cap_bodega_u": int(sp.cap_bodega or 1_000_000),
    "linea_preferida": sp.linea_preferida or "",
    "descripcion": sp.descripcion or "",
} for sku, sp in sku_params.items()}

lineas_params_rich = {cod: {
    "velocidad_u_hr": float(ln.velocidad_u_hr or 0),
    "horas_turno": float(ln.horas_turno or 8),
    "turnos_dia": int(ln.turnos_dia or 1),
} for cod, ln in lineas.items()}

sku_lineas_rich = [{"sku": r["sku"], "linea": r["linea"],
    "t_cambio_hrs": float(r.get("t_cambio_hrs", 0) or 0),
    "preferida": bool(r.get("preferida", False)),
    "factor_velocidad": float(r.get("factor_velocidad", 1.0) or 1.0),
} for r in get_all_sku_lineas()]

hoy = date.today()
fin = hoy + timedelta(days=42)
lunes_ini = semana_iso_inicio(hoy)
lunes_fin = semana_iso_inicio(fin)

forecast_rich = {}
for sku in sku_params:
    try:
        r = run_sku_pipeline(df=df, sku=sku, canal=None, forecast_periods=10)
        upc = sku_params_rich[sku]["u_por_caja"]
        d = {}
        for f in r.get("forecast", []):
            try:
                fo = date.fromisoformat(str(f["ds"])[:10])
                lu = semana_iso_inicio(fo)
                if lu < lunes_ini or lu > lunes_fin: continue
                d[lu] = d.get(lu, 0.0) + max(0.0, float(f.get("yhat",0))) * upc
            except: pass
        forecast_rich[sku] = d
    except: pass

skus_activos = [s for s in sku_params_rich if sku_params_rich[s]["tipo"]=="PRODUCCION" and sum(forecast_rich.get(s,{}).values()) > 0]
sku_a_lineas = {}
for entry in sku_lineas_rich:
    if entry["sku"] in skus_activos:
        sku_a_lineas.setdefault(entry["sku"], []).append(entry)
skus_modelo = [s for s in skus_activos if s in sku_a_lineas]

horizonte = generar_horizonte_diario(hoy, 42)
demanda_diaria = {sku: distribuir_forecast_a_diario(forecast_rich.get(sku,{}), hoy, hoy+timedelta(days=41)) for sku in skus_modelo}
cap_dia = {(d, cod): capacidad_dia_unidades(d, lp["velocidad_u_hr"], lp["horas_turno"], lp["turnos_dia"]) for d in horizonte for cod, lp in lineas_params_rich.items()}

print("="*70)
print("ANALIZANDO POR SKU EL BALANCE INICIAL")
print("="*70)
for sku in skus_modelo:
    sp = sku_params_rich[sku]
    cap_bod = sp["cap_bodega_u"]
    ss_dias = sp["ss_dias"]
    
    # Total demanda en horizonte
    demanda_total = sum(demanda_diaria[sku].values())
    
    # Capacidad de produccion total disponible (asumiendo todas las lineas habiles)
    cap_prod_total = 0
    for entry in sku_a_lineas[sku]:
        l = entry["linea"]
        f = entry.get("factor_velocidad", 1.0)
        # ~30 dias hábiles en 42 días horizonte
        for d in horizonte:
            cap_d = cap_dia.get((d, l), 0)
            if cap_d > 0:
                cap_prod_total += cap_d * f
    
    # Demanda dia 0 y SS dia 0
    dem_0 = demanda_diaria[sku].get(horizonte[0], 0)
    ss_0 = dem_0 * ss_dias
    
    # Stock al final del horizonte mínimo (si pudieramos producir todo el cap)
    stock_min = -10 * cap_bod
    stock_max = 2 * cap_bod
    
    print(f"\n  {sku}:")
    print(f"    cap_bodega={cap_bod}, ss_dias={ss_dias}")
    print(f"    demanda_dia_0={dem_0:.0f}, SS_dia_0={ss_0:.0f}")
    print(f"    stock IntVar bounds: [{stock_min}, {stock_max}]")
    print(f"    deficit IntVar bounds: [0, {stock_max}]")
    if ss_0 > stock_max:
        print(f"    *** PROBLEMA: SS_dia_0 ({ss_0:.0f}) > deficit_upper_bound ({stock_max}) ***")
        print(f"    *** def[0] >= SS - stock = {ss_0:.0f} - stock_real")
        print(f"    *** Si stock_real es muy negativo, def necesita ser muy grande, pero su UB es {stock_max}")
    
    print(f"    demanda_total_horizonte={demanda_total:.0f}")
    print(f"    cap_prod_total_horizonte={cap_prod_total:.0f}")
    if demanda_total > cap_prod_total:
        print(f"    *** PROBLEMA: demanda > capacidad de producción total ***")