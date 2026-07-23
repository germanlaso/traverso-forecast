"""
cron_faltantes_final.py — Envío FINAL del informe de faltantes (correo de las 11 AM).

Flujo:
  1. NO recalcula. Usa lo persistido por cron_faltantes.py (8 AM).
  2. Envía el informe del día anterior, CON las explicaciones incorporadas por las
     áreas entre las 8 y las 11, al grupo ampliado (FALTANTES_DEST_FINAL).
  3. Si el envío fue EXITOSO → congela las explicaciones de esa fecha (read-only).
  4. Si el envío FALLÓ → alerta SOLO al admin (no congela, para permitir reintento).

Cron sugerido (11 AM Chile = 15:00 UTC):
    0 15 * * * docker exec traverso_forecast python3 /app/cron_faltantes_final.py \\
                 >> /home/ubuntu/traverso_faltantes.log 2>&1

Destinatario de la alerta: env FALTANTES_ALERTA (o el primer FALTANTES_DEST).
"""

import sys
import logging
import traceback
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    ayer = date.today() - timedelta(days=1)

    # ── 1. Envío del informe FINAL (con explicaciones) ────────────────────────
    try:
        import enviar_faltantes
        enviar_faltantes.enviar_final(ayer.isoformat())
        logger.info("Informe FINAL enviado (%s).", ayer.isoformat())
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Envío FINAL FALLÓ: %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ ERROR al enviar informe FINAL de Faltantes — {ayer.isoformat()} — Traverso",
                cuerpo_texto=(
                    "FALLÓ el envío del correo FINAL de faltantes (11 AM) al grupo ampliado. "
                    "Las explicaciones NO se congelaron (se permite reintento).\n\n"
                    f"Fecha: {ayer.isoformat()}\n\nError:\n{tb}\n"
                    "Reintentar: docker exec traverso_forecast python3 /app/cron_faltantes_final.py"))
            logger.info("Alerta de error enviada al admin.")
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(1)

    # ── 2. Congelar explicaciones de la fecha reportada (solo si el envío fue OK) ──
    try:
        from db_mrp import congelar_explicaciones_faltantes
        n = congelar_explicaciones_faltantes(ayer.isoformat())
        logger.info("Explicaciones congeladas para %s: %d.", ayer.isoformat(), n)
    except Exception as e:
        # el correo sí se envió; falló solo el congelamiento → alerta al admin (no crítico)
        tb = traceback.format_exc()
        logger.error("Congelamiento FALLÓ (el correo sí se envió): %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ Faltantes: correo FINAL enviado pero NO se congelaron explicaciones — {ayer.isoformat()}",
                cuerpo_texto=(
                    "El correo FINAL se envió correctamente, pero FALLÓ el congelamiento "
                    "de las explicaciones (podrían seguir editables).\n\n"
                    f"Fecha: {ayer.isoformat()}\n\nError:\n{tb}"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)


if __name__ == "__main__":
    main()
