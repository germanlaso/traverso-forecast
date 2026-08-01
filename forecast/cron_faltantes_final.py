"""
cron_faltantes_final.py — Envío FINAL del informe de faltantes (correo de las 11 AM).

Flujo:
  1. NO recalcula. Usa lo persistido por cron_faltantes.py (8 AM).
  2. Si HOY NO es día hábil → NO envía y NO congela. Termina OK.
     (Congelar un sábado cerraría la ventana de explicaciones sin que nadie
     hubiera podido escribirlas: la ventana es de 8 a 11 de un día laboral.)
  3. Si es día hábil → envía el rango [último día hábil .. ayer] al grupo
     ampliado (FALTANTES_DEST_FINAL), CON las explicaciones incorporadas por las
     áreas entre las 8 y las 11.
  4. Si el envío fue EXITOSO → congela las explicaciones de TODAS las fechas del
     rango (read-only). El lunes son tres: viernes, sábado y domingo.
  5. Si el envío FALLÓ → alerta SOLO al admin (no congela, para permitir reintento).

Cron (11 AM Chile = 15:00 UTC):
    0 15 * * 1-5 docker exec traverso_forecast python3 /app/cron_faltantes_final.py \\
                   >> /home/ubuntu/traverso_faltantes.log 2>&1

  El `1-5` del crontab es redundante con la guarda de días hábiles de este script
  (queda como cinturón). Los feriados los cubre sólo el script, no el cron.

Destinatario de la alerta: env FALTANTES_ALERTA (o el primer FALTANTES_DEST).
"""

import sys
import logging
import traceback
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    # ── 1. ¿Corresponde enviar hoy? ───────────────────────────────────────────
    # (01-08-2026) Este bloque faltaba: dias_informe.py estaba desplegado y
    # enviar_final() ya aceptaba desde/hasta, pero el wrapper seguía llamando en
    # modo día único -> enviaba y congelaba también sábados, domingos y feriados.
    try:
        from dias_informe import rango_informe, etiqueta_rango, fechas_del_rango
        rango = rango_informe(hoy)
    except Exception as e:
        # Si el calendario falla, NO se bloquea el informe: se cae al
        # comportamiento histórico (día único) y se avisa en el log.
        logger.warning("No se pudo evaluar el calendario (%s). Se envía el día único.", e)
        rango = (ayer, ayer)
        etiqueta_rango = lambda a, b: a.isoformat()                      # noqa: E731
        fechas_del_rango = lambda a, b: [a]                              # noqa: E731

    if rango is None:
        logger.info("Hoy (%s) NO es día hábil: informe FINAL no enviado y "
                    "explicaciones NO congeladas (nadie pudo escribirlas). "
                    "El próximo día hábil cubrirá el rango acumulado.", hoy.isoformat())
        return

    desde_inf, hasta_inf = rango
    etiqueta = etiqueta_rango(desde_inf, hasta_inf)
    fechas = fechas_del_rango(desde_inf, hasta_inf)
    logger.info("Día hábil: el informe FINAL cubre %s (%d día/s).", etiqueta, len(fechas))

    # ── 2. Envío del informe FINAL (con explicaciones) ────────────────────────
    try:
        import enviar_faltantes
        enviar_faltantes.enviar_final(desde=desde_inf, hasta=hasta_inf)
        logger.info("Informe FINAL enviado (%s).", etiqueta)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Envío FINAL FALLÓ: %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ ERROR al enviar informe FINAL de Faltantes — {etiqueta} — Traverso",
                cuerpo_texto=(
                    "FALLÓ el envío del correo FINAL de faltantes (11 AM) al grupo ampliado. "
                    "Las explicaciones NO se congelaron (se permite reintento).\n\n"
                    f"Rango: {desde_inf.isoformat()} a {hasta_inf.isoformat()}\n\nError:\n{tb}\n"
                    "Reintentar: docker exec traverso_forecast python3 /app/cron_faltantes_final.py"))
            logger.info("Alerta de error enviada al admin.")
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(1)

    # ── 3. Congelar TODAS las fechas del rango (solo si el envío fue OK) ──────
    # Antes se congelaba sólo `ayer`: el lunes eso habría cerrado el domingo y
    # dejado viernes y sábado editables para siempre.
    try:
        from db_mrp import congelar_explicaciones_faltantes
        total = 0
        for f in fechas:
            n = congelar_explicaciones_faltantes(f.isoformat())
            total += n or 0
            logger.info("Explicaciones congeladas para %s: %d.", f.isoformat(), n)
        if len(fechas) > 1:
            logger.info("Total congeladas en el rango %s: %d.", etiqueta, total)
    except Exception as e:
        # el correo sí se envió; falló solo el congelamiento → alerta al admin (no crítico)
        tb = traceback.format_exc()
        logger.error("Congelamiento FALLÓ (el correo sí se envió): %s", e)
        try:
            import enviar_faltantes
            enviar_faltantes.enviar_alerta(
                asunto=f"⚠ Faltantes: correo FINAL enviado pero NO se congelaron explicaciones — {etiqueta}",
                cuerpo_texto=(
                    "El correo FINAL se envió correctamente, pero FALLÓ el congelamiento "
                    "de las explicaciones (podrían seguir editables).\n\n"
                    f"Rango: {desde_inf.isoformat()} a {hasta_inf.isoformat()}\n\nError:\n{tb}"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)


if __name__ == "__main__":
    main()
