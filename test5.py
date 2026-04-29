import sys
if 'mrp' in sys.modules:
    del sys.modules['mrp']
import mrp
params, lineas, _ = mrp.load_params_from_excel('/app/data/Traverso_Parametros_MRP.xlsx')
print('SKUs:', len(params))
for k,v in params.items():
    print(k, v.tipo, v.lead_time_semanas)
