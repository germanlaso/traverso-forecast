content = open('/app/mrp.py').read()
old = "        if c.startswith('sku') or 'codigosap' in c:   col_map3[col] = 'sku'\n        elif 'codigolinea' in c:                       col_map3[col] = 'linea'"
new = "        if 'codigosap' in c or (c.startswith('sku') and 'linea' not in c):   col_map3[col] = 'sku'\n        elif 'codigolinea' in c or ('codigo' in c and 'linea' in c):              col_map3[col] = 'linea'"
if old in content:
    open('/app/mrp.py','w').write(content.replace(old,new))
    print('FIXED')
else:
    print('Buscando alternativa...')
    for i,l in enumerate(content.split('\n')):
        if 'col_map3' in l and ('sku' in l or 'linea' in l):
            print(i, repr(l))
