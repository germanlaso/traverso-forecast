content = open('/app/mrp.py').read()
old = "        c = col.lower().replace(' ','').replace('(','').replace(')','').replace('.','')
        if 'skucodigo' in c or 'codigosap' in c: col_map[col] = 'sku'"
new = "        c = col.lower().replace(' ','').replace('(','').replace(')','').replace('.','').replace('o','o').replace('a','a').replace('e','e').replace('i','i').replace('u','u').replace('o','o').replace('a','a').replace('e','e').replace('i','i').replace('u','u').replace('n','n')
        c = c.replace(chr(243),'o').replace(chr(225),'a').replace(chr(233),'e').replace(chr(237),'i').replace(chr(250),'u').replace(chr(241),'n')
        if 'sku' in c: col_map[col] = 'sku'"
open('/app/mrp.py','w').write(content.replace(old,new))
print('DONE' if "chr(243)" in open('/app/mrp.py').read() else 'ERROR')
