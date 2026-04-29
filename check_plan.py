import sys, json
sys.path.insert(0, '/app')
import urllib.request

body = json.dumps({'horizonte_semanas': 13}).encode()
req = urllib.request.Request(
    'http://localhost:8000/plan',
    data=body,
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())

ordenes_limon = [o for o in data['ordenes'] if o['sku'] == '121010210']

print('=== JUGO LIMON — respuesta del endpoint /plan ===')
print('Total ordenes plan:', len(data['ordenes']))
print('Ordenes JUGO LIMON:', len(ordenes_limon))
print()

for o in ordenes_limon[:8]:
    print('Sem', o['semana_necesidad'],
          ':', o['cantidad_cajas'], 'cj',
          '| stock_ini=', o['stock_inicial_cajas'],
          'stock_fin=', o['stock_final_cajas'],
          '| aprobada=', o.get('aprobada'),
          '| OF=', o.get('numero_of'))
