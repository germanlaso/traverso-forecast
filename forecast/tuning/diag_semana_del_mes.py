#!/usr/bin/env python3
"""
diag_semana_del_mes.py — Mide si existe el efecto "posicion de la semana dentro
del mes" en las ventas (hipotesis: semanas tempranas mas flojas que tardias,
especialmente en canal tradicional). SOLO LEE DATOS, no toca el forecast.

Idea: en consumo masivo el canal tradicional compra mas tras quincena/fin de mes
(ciclo de liquidez del almacenero). Prophet hoy NO modela esto: tiene
yearly_seasonality (anual) y weekly_seasonality (dia de semana, inutil en datos
semanales), pero NINGUNA estacionalidad de "semana del mes". Punto ciego.

Metodo:
  - A cada fecha_semana le asigna su posicion en el mes de dos formas:
      semana_ordinal: 1..5 (que semana del mes es, por dia 1-7=1, 8-14=2, ...)
      frac_mes: fraccion del mes transcurrida (0..1), mas robusta a meses 4/5 sem
  - Normaliza la venta de cada SKU (dividiendo por su media) para que SKUs de
    distinto volumen sean comparables, y promedia el indice por posicion.
  - Desglosa global y POR CANAL.

Indice > 1.0 = esa posicion vende mas que el promedio del SKU; < 1.0 = menos.
Si semana 1-2 < 1.0 y semana 3-4 > 1.0, la hipotesis se confirma.

USO:
  docker cp diag_semana_del_mes.py traverso_forecast:/tmp/diag_semana_del_mes.py
  docker exec traverso_forecast python3 /tmp/diag_semana_del_mes.py
"""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from db import load_sales

df = load_sales().copy()
df["fecha_semana"] = pd.to_datetime(df["fecha_semana"])
df = df[df["cantidad"] > 0]

# Posicion de la semana en el mes
dia = df["fecha_semana"].dt.day
df["semana_ordinal"] = ((dia - 1) // 7 + 1).clip(upper=5)  # 1..5
dim = df["fecha_semana"].dt.daysinmonth
df["frac_mes"] = (dia - 1) / dim  # 0..1

# Normalizar cantidad por SKU (indice relativo a la media del SKU)
media_sku = df.groupby("sku")["cantidad"].transform("mean")
df["indice"] = df["cantidad"] / media_sku.replace(0, np.nan)
df = df.dropna(subset=["indice"])

def tabla(grupo_col=None):
    """Indice medio por semana_ordinal, global o por la columna dada."""
    keys = (["__all__"] if grupo_col is None else df[grupo_col].fillna("(s/d)").unique())
    print(f"\n{'='*64}")
    print(f"Indice de venta por SEMANA DEL MES  {'(GLOBAL)' if grupo_col is None else '(por '+grupo_col+')'}")
    print(f"{'='*64}")
    print(f"{'grupo':<22}{'sem1':>8}{'sem2':>8}{'sem3':>8}{'sem4':>8}{'sem5':>8}{'  n_obs':>9}")
    rows = ([("__all__", df)] if grupo_col is None
            else [(g, df[df[grupo_col].fillna("(s/d)") == g]) for g in keys])
    for nombre, sub in rows:
        if len(sub) < 50:
            continue
        piv = sub.groupby("semana_ordinal")["indice"].mean()
        vals = [piv.get(i, np.nan) for i in range(1, 6)]
        cels = "".join(f"{v:>8.3f}" if not np.isnan(v) else f"{'-':>8}" for v in vals)
        print(f"{str(nombre)[:22]:<22}{cels}{len(sub):>9,}")

tabla(None)        # global
tabla("canal")     # por canal

# Test direccional: promedio sem1-2 vs sem3-4 por canal
print(f"\n{'='*64}")
print("RESUMEN: tempranas (sem1-2) vs tardias (sem3-4), por canal")
print(f"{'='*64}")
print(f"{'canal':<22}{'temprana':>10}{'tardia':>10}{'gap %':>10}")
for canal in df["canal"].fillna("(s/d)").unique():
    sub = df[df["canal"].fillna("(s/d)") == canal]
    if len(sub) < 50:
        continue
    temp = sub[sub["semana_ordinal"] <= 2]["indice"].mean()
    tard = sub[sub["semana_ordinal"].isin([3, 4])]["indice"].mean()
    gap = 100 * (tard - temp) / temp if temp else float("nan")
    print(f"{str(canal)[:22]:<22}{temp:>10.3f}{tard:>10.3f}{gap:>9.1f}%")

print(f"\n{'='*64}")
print("Lectura: gap% > 0 => las semanas tardias venden mas que las tempranas")
print("(hipotesis confirmada). Cuanto mayor el gap, mas fuerte el efecto.")
print("Si TRADICIONAL tiene gap claramente mayor que los demas canales, el")
print("efecto es canal-dependiente y un regresor 'semana del mes' deberia ayudar")
print("sobre todo en bottom-up por canal.")
