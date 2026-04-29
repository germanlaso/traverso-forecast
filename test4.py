import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
print('Columnas raw:', len(df.columns))
print('Shape:', df.shape)
df.columns = [str(c).replace('\n',' ').strip() for c in df.columns]
print('Columnas normalizadas:')
for i,c in enumerate(df.columns):
    print(i, repr(c))
