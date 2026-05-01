import sys
sys.path.insert(0, "/app")
from datetime import date, timedelta
from calendario import distribuir_forecast_a_diario, semana_iso_inicio

# Test simple: 1000 unidades en 1 semana
forecast = {date(2026, 5, 4): 1000}  # lunes 4 de mayo 2026
demanda = distribuir_forecast_a_diario(
    forecast, fecha_inicio=date(2026, 5, 4), fecha_fin=date(2026, 5, 10))
print("Test 1 — 1000 u en una semana, horizonte 4-10 mayo:")
total = 0
for fecha, val in sorted(demanda.items()):
    print(f"  {fecha} ({fecha.strftime('%a')}): {val}")
    total += val
print(f"  Total: {total} (esperado: 1000)")