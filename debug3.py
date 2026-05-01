import sys
sys.path.insert(0, "/app")

from datetime import date, timedelta
from db_mrp import get_all_sku_lineas
from mrp import load_params_from_db
from forecaster import run_sku_pipeline
from db import load_sales
from calendario import semana_iso_inicio, distribuir_forecast_a_diario, capacidad_dia_unidades, generar_horizonte_diario
from optimizer import _construir_modelo, _agregar_objetivo
from ortools.sat.python import cp_model

sku_params, lineas, _ = load_params_from_db()
df = load_sales()

# Construir inputs como hace el wrapper
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
    }

sku_lineas_rich = []
for r in get_all_sku_lineas():
    sku_lineas_rich.append({
        "sku": r["sku"], "linea": r["linea"],
        "t_cambio_hrs": float(r.get("t_cambio_hrs", 0) or 0),
        "preferida": bool(r.get("preferida", False)),
        "factor_velocidad": float(r.get("factor_velocidad", 1.0) or 1.0),
    })

# Forecast filtrado a futuro
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
                if lu < lunes_ini or lu > lunes_fin:
                    continue
                d[lu] = d.get(lu, 0.0) + max(0.0, float(f.get("yhat",0))) * upc
            except: pass
        forecast_rich[sku] = d
    except: pass

# SKUs activos (PRODUCCION con demanda en horizonte)
skus_activos = []
for sku, sp in sku_params_rich.items():
    if sp.get("tipo","").upper() != "PRODUCCION":
        continue
    if sum(forecast_rich.get(sku, {}).values()) > 0:
        skus_activos.append(sku)

sku_a_lineas = {}
for entry in sku_lineas_rich:
    s = entry["sku"]
    if s not in skus_activos: continue
    sku_a_lineas.setdefault(s, []).append(entry)

print(f"SKUs activos: {len(skus_activos)}")
print(f"Pares en sku_a_lineas: {sum(len(v) for v in sku_a_lineas.values())}")

skus_modelo = [s for s in skus_activos if s in sku_a_lineas]
print(f"SKUs en modelo: {len(skus_modelo)}")
print()

horizonte = generar_horizonte_diario(hoy, 42)
demanda_diaria = {}
for sku in skus_modelo:
    demanda_diaria[sku] = distribuir_forecast_a_diario(
        forecast_rich.get(sku, {}), fecha_inicio=hoy, fecha_fin=hoy+timedelta(days=41))

cap_dia = {}
for d in horizonte:
    for cod, lp in lineas_params_rich.items():
        cap_dia[(d, cod)] = capacidad_dia_unidades(
            d, lp["velocidad_u_hr"], lp["horas_turno"], lp["turnos_dia"])

# Reportar batch_min en cajas para cada SKU
print("BATCH MIN EN CAJAS:")
for sku in skus_modelo:
    sp = sku_params_rich[sku]
    upc = sp["u_por_caja"]
    bmu = sp["batch_min_u"]
    bmc = -(-bmu // upc) if bmu > 0 else 0
    print(f"  {sku}: batch_min_u={bmu}, upc={upc} -> batch_min_cajas={bmc}")
print()

# Verificar si hay batch_min_cajas más grande que cajas_max para algun par
print("VERIFICANDO BATCH_MIN_CAJAS vs CAJAS_MAX (cota superior):")
problemas = 0
for sku in skus_modelo:
    sp = sku_params_rich[sku]
    upc = sp["u_por_caja"]
    bmu = sp["batch_min_u"]
    bmc = -(-bmu // upc) if bmu > 0 else 0
    for entry in sku_a_lineas[sku]:
        l = entry["linea"]
        f = entry.get("factor_velocidad", 1.0)
        # cap diaria de la linea cuando es hábil
        cap_l_dia_habil = lineas_params_rich[l]["velocidad_u_hr"] * lineas_params_rich[l]["horas_turno"] * lineas_params_rich[l]["turnos_dia"]
        # El cajas_max para día hábil
        cajas_max = int((cap_l_dia_habil * f) // upc) if cap_l_dia_habil > 0 else 0
        # Setup unidades
        t_camb = entry.get("t_cambio_hrs", 0)
        setup_u = int(t_camb * lineas_params_rich[l]["velocidad_u_hr"])
        cap_efectiva = cap_l_dia_habil - setup_u
        cajas_max_con_setup = int((cap_efectiva * f) // upc) if cap_efectiva > 0 else 0
        if bmc > cajas_max:
            print(f"  ✗ {sku} en {l}: batch_min_cajas={bmc} > cajas_max={cajas_max} -- INFACTIBLE en este par")
            problemas += 1
        elif bmc > cajas_max_con_setup:
            print(f"  ⚠ {sku} en {l}: batch_min_cajas={bmc} > cajas_max_con_setup={cajas_max_con_setup} (cap_dia={cap_l_dia_habil}, setup_u={setup_u}, factor={f})")
            problemas += 1
        else:
            print(f"  ✓ {sku} en {l}: batch_min_cajas={bmc} cabe (cajas_max={cajas_max}, con_setup={cajas_max_con_setup})")

if problemas == 0:
    print("  Ninguno problema detectado a nivel par SKU-Linea")
else:
    print(f"  {problemas} pares con problema potencial")

# Construir el modelo y reportar el infeasibility
print()
print("CONSTRUYENDO MODELO Y RESOLVIENDO...")
m = _construir_modelo(
    horizonte=horizonte, skus=skus_modelo,
    sku_params=sku_params_rich, lineas_params=lineas_params_rich,
    sku_a_lineas=sku_a_lineas, demanda_diaria=demanda_diaria,
    cap_dia=cap_dia, stock_inicial={s:0 for s in skus_modelo},
    entradas_aprobadas={},
)
_agregar_objetivo(m, sku_params=sku_params_rich, lineas_params=lineas_params_rich,
                  cap_dia=cap_dia, sku_a_lineas=sku_a_lineas)

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 30
status = solver.Solve(m.model)
print(f"Status: {solver.StatusName(status)}")

# Si es infeasible, buscar restricciones que están en conflicto
if status == cp_model.INFEASIBLE:
    print()
    print("Modelo es INFEASIBLE. Activando análisis de núcleo de infactibilidad...")
    # CP-SAT puede dar pistas pero no MUS directo. Probemos con assumptions:
    # Habría que aislar manualmente. Por ahora reportamos los stats:
    print(f"  Variables totales: {len(m.cajas) + len(m.asig) + len(m.inicio) + len(m.stock_u)}")
    print(f"  Restricciones: ?")