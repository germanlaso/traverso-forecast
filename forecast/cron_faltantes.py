"""
cron_faltantes.py — Orquestador diario del informe de faltantes (para el cron).

Flujo:
  1. Calcula los faltantes (ventana de 14 días) y los persiste.
  2. Si el cálculo fue EXITOSO → envía el informe del día anterior a los destinatarios.
  3. Si el cálculo FALLÓ → envía una alerta de error SOLO al admin (no el informe),
     evitando el "falso 0 faltantes" cuando en realidad el cálculo no corrió.

Reemplaza las dos líneas separadas del cron (cálculo + envío) por una sola:
    0 12 * * * docker exec traverso_forecast python3 /app/cron_faltantes.py \\
                 >> /home/ubuntu/traverso_faltantes.log 2>&1

Destinatario de la alerta: env FALTANTES_ALERTA, o el primer FALTANTES_DEST si no está.
"""

import sys
import logging
import traceback
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VENTANA_DIAS = 14


def main():
    ayer = date.today() - timedelta(days=1)
    desde = ayer - timedelta(days=VENTANA_DIAS - 1)

    # ── 1. Cálculo ────────────────────────────────────────────────────────────
    try:
        import faltantes
        filas = faltantes.ejecutar(desde, ayer, persistir_bd=True)
        logger.info("Cálculo OK: %d filas persistidas (%s a %s).",
                    len(filas), desde.isoformat(), ayer.isoformat())
        # limpiar explicaciones huérfanas (no congeladas) cuyo faltante ya no existe
        try:
            from db_mrp import limpiar_explicaciones_huerfanas
            n_huerf = limpiar_explicaciones_huerfanas()
            if n_huerf:
                logger.info("Explicaciones huérfanas eliminadas: %d.", n_huerf)
        except Exception as e_limp:
            logger.warning("No se pudo limpiar explicaciones huérfanas: %s", e_limp)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Cálculo FALLÓ: %s", e)
        # alerta de error al admin (no se envía el informe)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ ERROR en cálculo de Faltantes — {ayer.isoformat()} — Traverso",
                cuerpo_texto=(
                    "El cálculo diario de faltantes FALLÓ. No se envió el informe a los "
                    "destinatarios (para evitar reportar datos incompletos).\n\n"
                    f"Fecha objetivo: {ayer.isoformat()}\n"
                    f"Ventana: {desde.isoformat()} a {ayer.isoformat()}\n\n"
                    f"Error:\n{tb}\n"
                    "Revisar el servidor (conexión HANA/SQL Server, credenciales) y "
                    "re-ejecutar manualmente:\n"
                    "  docker exec traverso_forecast python3 /app/faltantes.py "
                    "--ventana 14 --persistir\n"
                    "  docker exec traverso_forecast python3 /app/enviar_faltantes.py"))
            logger.info("Alerta de error enviada al admin.")
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(1)

    # ── 2. Envío del informe (solo si el cálculo fue OK) ──────────────────────
    try:
        import enviar_faltantes
        enviar_faltantes.enviar(ayer.isoformat())
        logger.info("Informe enviado.")
    except Exception as e:
        # el cálculo sí quedó persistido; falló solo el envío → alerta al admin
        tb = traceback.format_exc()
        logger.error("Envío del informe FALLÓ: %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ ERROR al enviar informe de Faltantes — {ayer.isoformat()} — Traverso",
                cuerpo_texto=(
                    "El cálculo se completó y persistió correctamente, pero FALLÓ el envío "
                    "del correo del informe.\n\n"
                    f"Fecha: {ayer.isoformat()}\n\nError:\n{tb}\n"
                    "Reintentar: docker exec traverso_forecast python3 /app/enviar_faltantes.py"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)


if __name__ == "__main__":
    main()
