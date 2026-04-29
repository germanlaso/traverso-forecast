import pandas as pd
xl = pd.ExcelFile('/app/data/Traverso_Parametros_MRP.xlsx')
df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)

def normalize(s):
    s = str(s).lower().strip()
    for a,b in [(' ',''),('(',''),(')',''),('.',''),
                ('a','a'),('e','e'),('i','i'),('o','o'),('u','u'),
                (chr(225),'a'),(chr(233),'e'),(chr(237),'i'),(chr(243),'o'),(chr(250),'u'),(chr(241),'n')]:
        s = s.replace(a,b)
    return s

for col in df.columns:
    c = normalize(col)
    if 'tipo' in c:
        print(repr(col), '->', repr(c), '-> tipo col:', df[col].iloc[0])
