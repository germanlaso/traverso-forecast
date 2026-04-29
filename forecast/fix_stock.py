# Aplicar fix SQLAlchemy a stock.py en el contenedor
with open('/app/stock.py', 'r') as f:
    src = f.read()

import re

# Fix: reemplazar pd.read_sql con conn.execute + pd.DataFrame
src_new = re.sub(
    r'df\s*=\s*pd\.read_sql(?:_query)?\(([^,]+),\s*(?:get_engine\(\)|conn)\)',
    lambda m: (
        f'result = conn.execute(_text({m.group(1)}))\n'
        f'    df = pd.DataFrame(result.fetchall(), columns=result.keys())'
    ),
    src
)

# Asegurar que text está importado
if 'from sqlalchemy import' in src_new:
    if '_text' not in src_new:
        src_new = src_new.replace(
            'from sqlalchemy import',
            'from sqlalchemy import text as _text\nfrom sqlalchemy import'
        )
elif 'from sqlalchemy' not in src_new:
    src_new = 'from sqlalchemy import text as _text\n' + src_new

# Asegurar que los with get_engine().connect() as conn: existen
if 'get_engine' in src_new and 'with get_engine().connect()' not in src_new:
    src_new = re.sub(
        r'(def \w+\([^)]*\):[^{]*?)(df\s*=\s*(?:result\s*=|pd))',
        lambda m: m.group(1) + '    with get_engine().connect() as conn:\n    ' + m.group(2),
        src_new
    )

if src_new != src:
    with open('/app/stock.py', 'w') as f:
        f.write(src_new)
    print('Fix aplicado a stock.py')
    for i, l in enumerate(src_new.splitlines(), 1):
        if 'read_sql' in l or '_text' in l or 'get_engine' in l:
            print(f'  L{i}: {l.strip()}')
else:
    print('Sin cambios necesarios')
