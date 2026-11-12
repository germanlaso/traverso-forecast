#!/bin/sh
# comparar_42h.sh — 3 corridas SIN PROMOVER, en secuencia (nunca en paralelo), mismos datos:
#   A: legado (horas_turno x turnos)            CAPACIDAD_CALENDARIO=0
#   B: jornada 42 h (9-9-8-8-8)                 CAPACIDAD_CALENDARIO=1
#   C: jornada 42 h + llenar turno              CAPACIDAD_CALENDARIO=1 N2_LLENAR_TURNO=1
# Mismas banderas que el cron de producción (crontab 09:00 UTC) + --no-promote --skip-refresh.
# Uso (en el server):
#   docker exec -d traverso_forecast sh /app/comparar_42h.sh 2330      # espera a las 23:30 UTC
# (12-11-2026) Variables opcionales: CORRIDAS="B C" (subconjunto) y SEMILLA=7 (N2_SEED_A).
#   docker exec -d -e CORRIDAS="B C" traverso_forecast sh /app/comparar_42h.sh 0000
set -u
CORRIDAS="${CORRIDAS:-A B C}"
SEMILLA="${SEMILLA:-42}"
HORA="${1:-0000}"
echo "esperando ${HORA} UTC..." > /app/comp42.log
while [ "$(date -u +%H%M)" -lt "$HORA" ]; do sleep 30; done
cd /app
export PYTHONPATH=/app N2_ENABLED=1 SS_COBERTURA=1 N2_BARRERA_MODO=quiebre N2_WORKERS_C=8 N2_TL_C=3600 \
  CAMPANA_GRANEL_ENABLED=1 CAMPANA_FORMATO_ENABLED=1 QUIEBRE_INTRADIA_SOLVER=1 N2_BARRERA_SOBRE=fin \
  EVENTOS_ENABLED=1 N2_QBR_MAG_MODO=off N2_ESCALA_A=1 N2_A_GAP_EVENTOS=6 N2_SEED_A=$SEMILLA \
  N2_DIAG_LOG_SOLVER=1 N2_CAP_EFECTIVA=1
echo "corridas: $CORRIDAS | semilla: $SEMILLA" >> /app/comp42.log
for corrida in $CORRIDAS; do
  case $corrida in
    A) CAL=0; LLENAR=0 ;;
    B) CAL=1; LLENAR=0 ;;
    C) CAL=1; LLENAR=1 ;;
  esac
  # el cron de producción parte a las 09:00 UTC: no iniciar una corrida (~95 min) después de las 07:20 UTC
  AHORA=$(date -u +%H%M)
  if [ "$AHORA" -ge 0720 ] && [ "$AHORA" -lt 1200 ]; then
    echo "$(date -u +%FT%TZ) corrida $corrida OMITIDA: no alcanza a terminar antes del cron de las 09:00 UTC" >> /app/comp42.log
    continue
  fi
  echo "$(date -u +%FT%TZ) inicio corrida $corrida (CAPACIDAD_CALENDARIO=$CAL N2_LLENAR_TURNO=$LLENAR)" >> /app/comp42.log
  COLA_DESCRIPCION="comparacion 42h corrida $corrida" CAPACIDAD_CALENDARIO=$CAL N2_LLENAR_TURNO=$LLENAR python3 -u /app/cron_plan.py --horizonte 8 --time-limit 1800 \
      --no-promote --skip-refresh > /app/comp42_$corrida.log 2>&1
  echo "$(date -u +%FT%TZ) fin corrida $corrida: $(grep -o 'plan_id=[0-9]*' /app/comp42_$corrida.log | tail -1) | $(grep -o '\[CAPACIDAD\].*' /app/comp42_$corrida.log | tail -1)" >> /app/comp42.log
done
echo "$(date -u +%FT%TZ) FIN" >> /app/comp42.log
