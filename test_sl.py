import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_LINEA', header=2)
print('Shape:', df.shape)
for i,c in enumerate(df.columns):
    print(i, repr(str(c)))
print()
print('Primeras 3 filas:')
print(df.iloc[:3].to_string())
