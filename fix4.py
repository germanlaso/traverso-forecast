c = open("/app/mrp.py").read()

# 1. Revertir el daño del fix3
c = c.replace(
    "elif 'preferida' in c and 'linea' in c:",
    "elif 'preferida' in c:"
)

# 2. Fix correcto: mapear 'codigolinea' para columnas con \n
# 'Código\nLínea' -> normalizado queda 'codigolinea' (con \n->espacio->eliminado)
# Verificar que el strip de \n ya funciona
# Agregar mapeo explícito para nombre de linea en SKU_LINEA
c = c.replace(
    "elif 'codigolinea' in c:\n            col_map3[col] = 'linea'",
    "elif 'codigolinea' in c or ('codigo' in c and 'linea' in c):\n            col_map3[col] = 'linea'"
)

open("/app/mrp.py", "w").write(c)
print("revertido ok:", "elif 'preferida' in c:" in c)
print("codigolinea ok:", "('codigo' in c and 'linea' in c)" in c)