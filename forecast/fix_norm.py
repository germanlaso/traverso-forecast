content = open('/app/mrp.py').read()
old = "    s = str(s).lower().strip()"
new = "    s = str(s).lower().strip().replace(chr(10), '').replace(chr(13), '')"
if old in content:
    open('/app/mrp.py','w').write(content.replace(old, new, 1))
    print('FIXED')
else:
    print('NOT FOUND')
    for i,l in enumerate(content.split('\n')[55:70], 55):
        print(i, repr(l))
