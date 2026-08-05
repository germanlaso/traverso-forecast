"""techo.py — Techo de adelanto de produccion por SKU (linea L1Pet LV).

Contexto (05-08-2026): la regla de negocio es "mas vale la linea al 90% cuatro
dias que al 70% cinco dias". Pero L1Pet LV tiene 550.000 u/semana de capacidad
contra una demanda de ~56.000-155.000 u, asi que llegar al 90% durante 4 dias
exige producir ~396.000 u de una vez = varias semanas de demanda por lote.

Este script mide CUANTAS SEMANAS DE DEMANDA se pueden adelantar antes de chocar
con los tres techos que no son tecnicos:
  1. cap_bodega por SKU (fisico, ya es restriccion del modelo)
  2. vida util (el 83% de faltantes en TOTTUS es vu_insuficiente: adelantar
     produccion empeora justamente eso)
  3. marca privada (el sobrante no tiene canal; en marca propia si)

Solo lectura.
"""
import json
from sqlalchemy import text
from db_mrp import SessionLocal

LINEA = "L1Pet LV"
CAP_SEMANAL_U = 550_000          # del encabezado de la linea en el dashboard
MARCAS_PRIVADAS = ("TOTTUS", "CUISINE", "NUESTRA COCINA", "HIGUERAS", "FRESCOLIM")

with SessionLocal() as s:
    r = s.execute(text(
        "SELECT id, snapshot FROM mrp_planes WHERE vigente LIMIT 1")).mappings().first()
    prm = {x[0]: dict(upc=int(x[1] or 0), cap=int(x[2] or 0), ss=int(x[3] or 0),
                      desc=x[4] or "", bmin=int(x[5] or 0))
           for x in s.execute(text(
               "SELECT sku, u_por_caja, cap_bodega_u, ss_dias, descripcion, batch_min_u "
               "FROM mrp_sku_params WHERE linea_preferida = :l AND activo"),
               {"l": LINEA}).fetchall()}

snap = r["snapshot"]
if isinstance(snap, str):
    snap = json.loads(snap)
dd = snap.get("detalle_diario") or {}

print(f"plan vigente #{r['id']} · {LINEA} · techo de adelanto por SKU")
print()
print(f"{'sku':<11}{'descripcion':<31}{'dem/sem_u':>10}{'cap_bod_u':>10}"
      f"{'sem_bod':>8}{'batch_sem':>10}{'marca':>9}")
print("-" * 89)

tot_dem = 0.0
filas = []
for sku, p in sorted(prm.items()):
    ser = dd.get(sku) or {}
    if not ser:
        continue
    dem_u = sum((c.get("demanda_corr_u") or 0) for c in ser.values())
    n_sem = max(1.0, len(ser) / 7.0)
    dsem = dem_u / n_sem
    if dsem <= 0:
        continue
    tot_dem += dsem
    sem_bod = p["cap"] / dsem if dsem else 0
    # cuantas semanas de demanda cubre UN batch minimo: si es alto, el batch
    # ya fuerza a adelantar aunque nadie lo decida
    batch_sem = p["bmin"] / dsem if dsem else 0
    mk = "PRIVADA" if any(k in p["desc"].upper() for k in MARCAS_PRIVADAS) else "propia"
    filas.append((sem_bod, sku, p["desc"][:30], dsem, p["cap"], batch_sem, mk))

for sem_bod, sku, desc, dsem, cap, batch_sem, mk in sorted(filas):
    print(f"{sku:<11}{desc:<31}{dsem:>10.0f}{cap:>10}{sem_bod:>8.1f}"
          f"{batch_sem:>10.1f}{mk:>9}")

print()
print(f"demanda total de la linea : {tot_dem:>10.0f} u/semana")
print(f"capacidad semanal         : {CAP_SEMANAL_U:>10} u   -> uso {100*tot_dem/CAP_SEMANAL_U:.0f}%")
print(f"para 4 dias al 90%        : {0.9*4*CAP_SEMANAL_U/5:>10.0f} u = "
      f"{(0.9*4*CAP_SEMANAL_U/5)/max(1,tot_dem):.1f} semanas de demanda")
print()
priv = [f for f in filas if f[6] == "PRIVADA"]
print(f"SKU de marca privada: {len(priv)} de {len(filas)} "
      f"({100*len(priv)/max(1,len(filas)):.0f}%) — ahi el sobrante NO tiene canal")
if filas:
    sb = sorted(f[0] for f in filas)
    print(f"sem_bod: min {sb[0]:.1f} · mediana {sb[len(sb)//2]:.1f} · max {sb[-1]:.1f}")
print()
print("COMO LEERLO")
print("  sem_bod   = semanas de demanda que caben en cap_bodega. Es el techo FISICO")
print("              de adelanto: si es 2, no se puede producir para 5 semanas por")
print("              mas capacidad de linea que haya.")
print("  batch_sem = semanas de demanda que cubre UN batch minimo. Si es alto, el")
print("              parametro YA fuerza a adelantar sin que nadie lo decida.")
print("  La mediana de sem_bod acota la regla alcanzable: con techo 2 semanas la")
print("  meta realista se parece mas a '3 dias al 40%' que a '4 dias al 90%'.")
