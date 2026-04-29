"""
Script de prueba del optimizador OR-Tools.
Ejecutar en el contenedor:
  docker cp check_optimizer.py traverso_forecast:/app/check_optimizer.py
  docker exec traverso_forecast python3 /app/check_optimizer.py
"""
import sys, json, urllib.request
sys.path.insert(0, '/app')

print("=" * 60)
print("TEST 1: Importar optimizer.py")
print("=" * 60)
try:
    from optimizer import optimizar_plan
    print("✅ optimizer.py importado OK")
except Exception as e:
    print(f"❌ Error importando optimizer: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("TEST 2: Plan sin optimizador (baseline MRP)")
print("=" * 60)
body = json.dumps({'horizonte_semanas': 13, 'skus': ['121010210']}).encode()
req = urllib.request.Request(
    'http://localhost:8000/plan',
    data=body, headers={'Content-Type': 'application/json'}, method='POST'
)
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())

ordenes_mrp = [o for o in data['ordenes'] if o['sku'] == '121010210']
print(f"Plan MRP clásico: {len(ordenes_mrp)} órdenes para JUGO LIMON")
for o in ordenes_mrp[:4]:
    print(f"  Sem {o['semana_necesidad']}: {o['cantidad_cajas']} cj "
          f"| stock_fin={o['stock_final_cajas']} | aprobada={o.get('aprobada')}")

print()
print("=" * 60)
print("TEST 3: Plan CON optimizador (OR-Tools)")
print("=" * 60)
body2 = json.dumps({'horizonte_semanas': 13, 'skus': ['121010210'], 'optimizar': True}).encode()
req2 = urllib.request.Request(
    'http://localhost:8000/plan',
    data=body2, headers={'Content-Type': 'application/json'}, method='POST'
)
try:
    with urllib.request.urlopen(req2, timeout=60) as r:
        data2 = json.loads(r.read())

    opt_info = data2.get('optimizacion', {})
    print(f"Status OR-Tools: {opt_info.get('status', '?')}")
    print(f"Optimizado: {opt_info.get('optimizado', False)}")
    print(f"Tiempo: {opt_info.get('tiempo_ms', '?')} ms")
    print(f"Uso promedio líneas: {opt_info.get('uso_promedio_lineas_pct', '?')}%")
    print(f"Semanas bajo SS antes: {opt_info.get('semanas_bajo_ss_antes', '?')}")
    print(f"Semanas bajo SS después: {opt_info.get('semanas_bajo_ss_despues', '?')}")

    ordenes_opt = [o for o in data2['ordenes'] if o['sku'] == '121010210']
    print(f"\nPlan optimizado: {len(ordenes_opt)} órdenes para JUGO LIMON")
    for o in ordenes_opt[:4]:
        print(f"  Sem {o['semana_necesidad']}: {o['cantidad_cajas']} cj "
              f"| stock_fin={o['stock_final_cajas']} "
              f"| linea={o.get('linea')} "
              f"| uso={o.get('uso_linea_pct')}%"
              f"| opt={o.get('optimizado')}")

    if opt_info.get('error'):
        print(f"\n⚠️ Error en optimizador: {opt_info['error']}")

except Exception as e:
    print(f"❌ Error llamando al plan con optimizador: {e}")
