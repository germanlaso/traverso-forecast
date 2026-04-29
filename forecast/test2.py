import pandas as pd
from mrp import SKUParams

xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
df.columns = [str(c).replace('\n',' ').strip() for c in df.columns]
col_names = ['sku','descripcion','unidades_por_caja','categoria','tipo','lead_time_semanas','stock_seguridad_dias','batch_minimo','multiplo_batch','cap_bodega','linea_produccion','t_cambio','compra_minima','pais_origen','activo','notas']
n = min(len(col_names), len(df.columns))
df.columns = col_names[:n] + list(df.columns[n:])
df['sku'] = df['sku'].astype(str).str.strip()
df = df[df['sku'].str.match(r'^\d+$')]
df = df.dropna(subset=['lead_time_semanas'])
ok = 0
for _, row in df.iterrows():
    try:
        SKUParams(
            sku=row['sku'],
            descripcion=str(row.get('descripcion','')),
            categoria=str(row.get('categoria','')),
            tipo=str(row.get('tipo','PRODUCCION')).upper().strip(),
            unidades_por_caja=int(row.get('unidades_por_caja
@"
import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
df.columns = [str(c).replace('\n',' ').strip() for c in df.columns]
col_names = ['sku','descripcion','unidades_por_caja','categoria','tipo','lead_time_semanas','stock_seguridad_dias','batch_minimo','multiplo_batch','cap_bodega','linea_produccion','t_cambio','compra_minima','pais_origen','activo','notas']
n = min(len(col_names), len(df.columns))
df.columns = col_names[:n] + list(df.columns[n:])
df['sku'] = df['sku'].astype(str).str.strip()
df_num = df[df['sku'].str.match(r'^\d+$')]
print('SKUs numericos:', len(df_num))
df_ok = df_num.dropna(subset=['lead_time_semanas'])
print('SKUs con lead_time:', len(df_ok))
print(df_ok[['sku','lead_time_semanas']].to_string())
