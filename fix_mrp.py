content = open('/app/mrp.py').read()
lines = content.split('\n')
new_lines = []
for line in lines:
    if "batch_minimo=int(row.get('batch_minimo', 0))," in line:
        line = line.replace("int(row.get('batch_minimo', 0))", "int(row.get('batch_minimo', 0) or 0)")
    if "multiplo_batch=int(row.get('multiplo_batch', 1))," in line:
        line = line.replace("int(row.get('multiplo_batch', 1))", "int(row.get('multiplo_batch', 1) or 1)")
    if "cap_bodega=int(row.get('cap_bodega', 999999))," in line:
        line = line.replace("int(row.get('cap_bodega', 999999))", "int(row.get('cap_bodega', 999999) or 999999)")
    if "unidades_por_caja=int(row.get('unidades_por_caja', 1))," in line:
        line = line.replace("int(row.get('unidades_por_caja', 1))", "int(row.get('unidades_por_caja', 1) or 1)")
    new_lines.append(line)
open('/app/mrp.py', 'w').write('\n'.join(new_lines))
print('DONE')
