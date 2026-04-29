content = open('/app/mrp.py').read()
old = """    col_names = ['sku', 'descripcion', 'unidades_por_caja', 'categoria', 'tipo',
                 'lead_time_semanas', 'stock_seguridad_dias', 'batch_minimo',
                 'multiplo_batch', 'cap_bodega', 'linea_produccion', 't_cambio',
                 'compra_minima', 'pais_origen', 'activo', 'notas']
    # Asignar nombres por posicion hasta donde alcancen las columnas
    n = min(len(col_names), len(df_sku.columns))
    df_sku.columns = col_names[:n] + list(df_sku.columns[n:])"""
new = """    col_map = {}
    for col in df_sku.columns:
        c = col.lower().replace(' ','').replace('(','').replace(')','').replace('.','')
        if 'skucodigo' in c or 'codigosap' in c: col_map[col] = 'sku'
        elif 'descripcion' in c: col_map[col] = 'descripcion'
        elif 'unidadesporcaja' in c or 'unidades' in c: col_map[col] = 'unidades_por_caja'
        elif 'categoria' in c: col_map[col] = 'categoria'
        elif 'tipoabastecimiento' in c or 'tipo' in c: col_map[col] = 'tipo'
        elif 'leadtime' in c or 'lead' in c: col_map[col] = 'lead_time_semanas'
        elif 'stockseguridad' in c or 'seguridad' in c: col_map[col] = 'stock_seguridad_dias'
        elif 'batchminimo' in c or 'batchmin' in c: col_map[col] = 'batch_minimo'
        elif 'multiplobatch' in c or 'multiplo' in c: col_map[col] = 'multiplo_batch'
        elif 'capbodega' in c or 'bodega' in c: col_map[col] = 'cap_bodega'
        elif 'lineaproduccion' in c or 'linea' in c: col_map[col] = 'linea_produccion'
        elif 'tcambio' in c or 'cambio' in c: col_map[col] = 't_cambio'
        elif 'compra' in c: col_map[col] = 'compra_minima'
        elif 'pais' in c: col_map[col] = 'pais_origen'
        elif 'activo' in c: col_map[col] = 'activo'
    df_sku = df_sku.rename(columns=col_map)"""
open('/app/mrp.py','w').write(content.replace(old,new))
print('DONE' if 'leadtime' in open('/app/mrp.py').read() else 'ERROR')
