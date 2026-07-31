"""
cron_informe_ventas.py — Orquestador diario del informe de ventas + stock (9 AM Chile).

Flujo:
  1. Genera el informe (informe_ventas.ejecutar): consulta dbo.ventas, lee el stock y
     los maestros, y escribe el Excel.
  2. Si salió bien → lo envía con el Excel adjunto.
  3. Si FALLÓ → alerta SOLO al admin, sin enviar el informe. Nunca silencio: un correo
     ausente no debe confundirse con "no hubo ventas" (mismo criterio que faltantes y
     el vigía).

Cron (9 AM Chile = 13:00 UTC):
    0 13 * * *  docker exec -e PYTHONPATH=/app -w /app traverso_forecast \\
                  python3 /app/cron_informe_ventas.py \\
                  >> /home/ubuntu/traverso_informe_ventas.log 2>&1

  · 13:00 UTC deja el stock ya refrescado por el cron del plan (10:00 UTC, ~75 min).
  · La consulta a dbo.ventas tarda unos minutos (tabla sin índices, ver H7).

Uso manual:
    python3 cron_informe_ventas.py             # genera y envía
    python3 cron_informe_ventas.py --dry-run   # genera, NO envía (deja el Excel)
"""

# ── Ruta de los módulos compartidos ──────────────────────────────────────────
# Este paquete vive en una subcarpeta, pero usa módulos que están en la raíz de la
# app (db.py, stock.py). Se agrega esa raíz al path para poder importarlos.
# TRAVERSO_APP_DIR permite override si el montaje cambia.
import os as _os
import sys as _sys
_APP_DIR = _os.environ.get("TRAVERSO_APP_DIR", "/app")
if _APP_DIR not in _sys.path:
    _sys.path.insert(0, _APP_DIR)


import argparse
import logging
import os
import sys
import traceback
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cron_informe_ventas")

RETENCION_DIAS = 15      # cuántos Excel se guardan en /app/data antes de limpiar


def _limpiar_viejos(dias: int = RETENCION_DIAS) -> int:
    """Borra los Excel del informe con más de `dias` de antigüedad."""
    import glob
    import time
    n, limite = 0, time.time() - dias * 86400
    import informe_ventas as _iv
    patron = _os.path.join(_iv.SALIDA_DIR, "Informe_Ventas_Stock_*.xlsx")
    for f in glob.glob(patron):
        try:
            if os.path.getmtime(f) < limite:
                os.remove(f)
                n += 1
        except Exception:
            pass
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="genera el Excel pero NO envía el correo")
    ap.add_argument("--fecha", default=None, help="YYYY-MM-DD (default: hoy)")
    args = ap.parse_args()

    hoy = date.fromisoformat(args.fecha) if args.fecha else date.today()

    # ── 1. Generación ─────────────────────────────────────────────────────────
    try:
        import informe_ventas
        ruta, rep = informe_ventas.ejecutar(hoy=hoy)
        logger.info("Informe generado OK: %d SKU, %d excluidos, %s cj de venta.",
                    len(rep["df"]), len(rep["excluidos"]), f"{rep['total_ventas']:,}")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Generación FALLÓ: %s", e)
        try:
            import enviar_informe_ventas as env
            env.enviar_alerta(
                asunto=f"⚠ ERROR en el Informe de Ventas — {hoy.isoformat()} — Traverso",
                cuerpo_texto=(
                    "La generación del informe diario de ventas FALLÓ. NO se envió a los "
                    "destinatarios, así que la ausencia de correo hoy NO significa que no "
                    "haya ventas.\n\n"
                    f"Fecha: {hoy.isoformat()}\n\nError:\n{tb}\n"
                    "Revisar: conexión a SQL Server (dbo.ventas), stock_actual.csv y el "
                    "Excel de maestros /app/data/Parametros_Informe_Ventas.xlsx.\n"
                    "Re-ejecutar:\n"
                    "  docker exec -e PYTHONPATH=/app -w /app traverso_forecast "
                    "python3 /app/cron_informe_ventas.py"))
            logger.info("Alerta de error enviada al admin.")
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(1)

    if args.dry_run:
        print(f"\nDRY-RUN: Excel generado en {ruta} (no se envió correo).")
        print(f"  SKU: {len(rep['df'])} | excluidos: {len(rep['excluidos'])}")
        print(f"  Ventas del período: {rep['total_ventas']:,} cj")
        print(f"  Stock ({rep['fecha_stock']}): {rep['total_stock']:,} cj")
        if rep["excluidos"]:
            print("  Excluidos con venta > 0:")
            for e in rep["excluidos"][:10]:
                if int(e["total"]) > 0:
                    print(f"    {e['sku']} {str(e['nombre'])[:40]} "
                          f"({int(e['total']):,} cj)")
        return

    # ── 2. Envío ──────────────────────────────────────────────────────────────
    try:
        import enviar_informe_ventas as env
        env.enviar(rep, ruta)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Envío FALLÓ: %s", e)
        try:
            import enviar_informe_ventas as env
            env.enviar_alerta(
                asunto=f"⚠ ERROR al enviar el Informe de Ventas — {hoy.isoformat()} — Traverso",
                cuerpo_texto=("El informe se generó correctamente pero FALLÓ el envío del "
                              f"correo.\n\nArchivo: {ruta}\n\nError:\n{tb}\n"
                              "Reintentar: docker exec -e PYTHONPATH=/app -w /app "
                              "traverso_forecast python3 /app/cron_informe_ventas.py"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)

    # ── 3. Higiene ────────────────────────────────────────────────────────────
    try:
        n = _limpiar_viejos()
        if n:
            logger.info("Excel viejos eliminados: %d", n)
    except Exception:
        pass


if __name__ == "__main__":
    main()
