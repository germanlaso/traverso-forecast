import sys
if 'mrp' in sys.modules:
    del sys.modules['mrp']
import mrp
params, lineas, sku_lineas = mrp.load_params_from_excel('/app/data/Traverso_Parametros_MRP.xlsx')
print('sku_lineas:', len(sku_lineas))
for sl in sku_lineas[:5]:
    print(sl.sku, sl.linea, sl.preferida)
print()
print('lineas preferidas en params:')
for k,v in params.items():
    if v.linea_preferida:
        print(k, v.linea_preferida)
