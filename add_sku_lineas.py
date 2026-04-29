with open("/app/db_mrp.py", "r") as f:
    src = f.read()

nueva_fn = '''

def get_all_sku_lineas() -> list:
    """Retorna todos los registros de mrp_sku_lineas (SKU → Linea con t_cambio_hrs)."""
    from sqlalchemy import text as _text
    with get_session() as session:
        result = session.execute(_text(
            "SELECT sku, linea, t_cambio_hrs, preferida FROM mrp_sku_lineas ORDER BY sku, linea"
        ))
        rows = result.fetchall()
        return [
            {"sku": str(r[0]), "linea": str(r[1]),
             "t_cambio_hrs": float(r[2] or 0), "preferida": bool(r[3])}
            for r in rows
        ]
'''

if "def get_all_sku_lineas" not in src:
    src = src + nueva_fn
    with open("/app/db_mrp.py", "w") as f:
        f.write(src)
    print("OK: get_all_sku_lineas agregada")
else:
    print("ya existia get_all_sku_lineas")
