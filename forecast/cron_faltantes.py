"""
cron_faltantes.py — Orquestador diario del informe de faltantes (para el cron).

Flujo:
  1. Calcula los faltantes (ventana de 14 días) y los persiste. TODOS LOS DÍAS,
     sin excepción: así el dashboard queda al día y los faltantes se guardan
     por fecha (nunca consolidados).
  2. Si HOY NO es día hábil → NO envía correo y termina OK. El calendario lo
     resuelve dias_informe.rango_informe() (fuente única: calendario.es_habil).
  3. Si es día hábil → envía el informe del rango [último día hábil .. ayer].
     Lunes normal: viernes + sábado + domingo en UN correo.
  4. Si el cálculo FALLÓ → alerta de error SOLO al admin (no el informe),
     evitando el "falso 0 faltantes" cuando en realidad el cálculo no corrió.

    0 12 * * * docker exec traverso_forecast python3 /app/cron_faltantes.py \\
                 >> /home/ubuntu/traverso_faltantes.log 2>&1

  El cron corre TODOS los días a propósito (el filtro de días hábiles vive acá,
  no en el crontab, porque el cálculo sí debe correr sábado y domingo).

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
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    desde_calc = ayer - timedelta(days=VENTANA_DIAS - 1)   # ventana de CÁLCULO (14 días)

    # ── 1. Cálculo — SIEMPRE, sea o no día hábil ──────────────────────────────
    try:
        import faltantes
        filas = faltantes.ejecutar(desde_calc, ayer, persistir_bd=True)
        logger.info("Cálculo OK: %d filas persistidas (%s a %s).",
                    len(filas), desde_calc.isoformat(), ayer.isoformat())
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
        # alerta de error al admin (no se envía el informe). Se manda también en
        # día no hábil: si el cálculo se rompe un sábado hay que enterarse.
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ ERROR en cálculo de Faltantes — {ayer.isoformat()} — Traverso",
                cuerpo_texto=(
                    "El cálculo diario de faltantes FALLÓ. No se envió el informe a los "
                    "destinatarios (para evitar reportar datos incompletos).\n\n"
                    f"Fecha objetivo: {ayer.isoformat()}\n"
                    f"Ventana: {desde_calc.isoformat()} a {ayer.isoformat()}\n\n"
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

    # ── 2. ¿Corresponde enviar correo hoy? ────────────────────────────────────
    # (01-08-2026) Este bloque faltaba: dias_informe.py estaba desplegado y
    # enviar() ya aceptaba desde/hasta, pero el wrapper seguía llamando en modo
    # día único -> el informe se enviaba también sábados, domingos y feriados.
    try:
        from dias_informe import rango_informe, etiqueta_rango
        rango = rango_informe(hoy)
    except Exception as e:
        # Si el módulo de calendario falla, NO se bloquea el informe: se cae al
        # comportamiento histórico (día único) y se avisa en el log.
        logger.warning("No se pudo evaluar el calendario (%s). Se envía el día único.", e)
        rango = (ayer, ayer)
        etiqueta_rango = lambda a, b: a.isoformat()      # noqa: E731

    if rango is None:
        logger.info("Hoy (%s) NO es día hábil: cálculo persistido, correo NO enviado. "
                    "El próximo día hábil cubrirá el rango acumulado.", hoy.isoformat())
        return

    desde_inf, hasta_inf = rango
    logger.info("Día hábil: el informe cubre %s (%d día/s).",
                etiqueta_rango(desde_inf, hasta_inf),
                (hasta_inf - desde_inf).days + 1)

    # ── 3. Envío del informe (solo si el cálculo fue OK y hoy es hábil) ───────
    try:
        import enviar_faltantes
        enviar_faltantes.enviar(desde=desde_inf, hasta=hasta_inf)
        logger.info("Informe enviado.")
    except Exception as e:
        # el cálculo sí quedó persistido; falló solo el envío → alerta al admin
        tb = traceback.format_exc()
        logger.error("Envío del informe FALLÓ: %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=(f"⚠ ERROR al enviar informe de Faltantes — "
                        f"{etiqueta_rango(desde_inf, hasta_inf)} — Traverso"),
                cuerpo_texto=(
                    "El cálculo se completó y persistió correctamente, pero FALLÓ el envío "
                    "del correo del informe.\n\n"
                    f"Rango: {desde_inf.isoformat()} a {hasta_inf.isoformat()}\n\n"
                    f"Error:\n{tb}\n"
                    "Reintentar: docker exec traverso_forecast python3 /app/enviar_faltantes.py"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)


if __name__ == "__main__":
    main()
