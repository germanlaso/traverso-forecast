import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='LINEAS_PRODUCCION', header=2)
print('Shape:', df.shape)
for i,c in enumerate(df.columns):
    print(i, repr(str(c)))
print()
print('Fila 0:', df.iloc[0].tolist())
