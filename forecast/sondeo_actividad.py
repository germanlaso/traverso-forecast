"""Sondeo de actividad reciente: hasta qué fecha llegan los datos y cuántos
SKUs caen según distintos umbrales de 'venta reciente'. Solo LEE."""
import sys
sys.path.insert(0, "/app")
import pandas as pd
from db import get_sku_list

r = get_sku_list()
r["ultima_venta"] = pd.to_datetime(r["ultima_venta"])
fecha_max = r["ultima_venta"].max()
print(f"Fecha máx de venta en datos: {fecha_max.date()}")
print(f"SKUs totales (>=1 venta en 48m): {len(r)}")
print()
print(f"{'Umbral':>22} {'SKUs activos':>13} {'con>=20sem':>11}")
for sem in (2,4,6,8,12):
    corte = fecha_max - pd.Timedelta(weeks=sem)
    act = r[r["ultima_venta"] >= corte]
    act20 = act[act["semanas_con_venta"] >= 20]
    print(f"  últimas {sem:>2} semanas      {len(act):>10}   {len(act20):>10}")
