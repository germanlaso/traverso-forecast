import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
df.columns = [str(c).replace('\n',' ').strip() for c in df.columns]
col_names = ['sku','descripcion','unidades_por_caja','categoria','tipo','lead_time_semanas']
n = min(len(col_names), len(df.columns))
df.columns = col_names[:n] + list(df.columns[n:])
df['sku'] = df['sku'].astype(str).str.strip()
df = df[df['sku'].str.match(r'^\d+\$')]
df = df.dropna(subset=['lead_time_semanas'])
print('SKUs:', len(df))
print(df[['sku','lead_time_semanas']].to_string())
