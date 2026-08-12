"""
cron_of_sap.py — Ingesta diaria de OF/TR de SAP a Postgres (mrp_of_sap).
Traverso S.A. · Conciliación OF/TR · Fase 1.

QUÉ HACE
    1. Conecta HANA (hana_of.conectar, con timeouts).
    2. Lee el SP de OF/TR (ventana móvil ~6 meses) y normaliza.
    3. Crea mrp_of_sap si no existe (idempotente).
    4. UPSERT ACUMULATIVO: inserta lo nuevo, actualiza lo cambiado, NO borra lo que
       ya no viene (la ventana móvil descarta lo viejo; nosotros lo conservamos).

NO toca el solver, el plan, ni nada de lo construido. Es pura medición.

DEGRADACIÓN ELEGANTE
    Si HANA no responde (timeout) o el SP falla, loguea el error y sale con código
    != 0 SIN dejar la tabla a medias (el upsert es transaccional). No genera plan
    ni alerta: es un proceso de medición independiente. El monitoreo de que corrió
    se hace por el log (grep), igual que las otras corridas.

USO
    # a mano, dentro del container:
    docker exec -e PYTHONPATH=/app -w /app -e HANA_PWD="$HANA_PWD" \\
        traverso_forecast python3 -u /app/cron_of_sap.py

    # dry-run: lee y resume, NO persiste
    ... python3 -u /app/cron_of_sap.py --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cron_of_sap")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="lee y resume, no persiste")
    args = ap.parse_args()

    t0 = datetime.now()
    logger.info("=== CRON OF/SAP inicio %s ===", t0.isoformat(timespec="seconds"))

    # 1-2. Leer HANA
    try:
        import hana_of
        conn = hana_of.conectar()
        try:
            filas = hana_of.leer_of_tr(conn)
        finally:
            conn.close()
    except Exception as e:
        logger.error("Lectura HANA FALLÓ: %s", e)
        sys.exit(2)

    n = len(filas)
    n_pend = sum(1 for f in filas if f["pendiente"])
    n_of = len({f["orden_produccion"] for f in filas})
    logger.info("Leídas %d filas-recibo | %d OF | %d pendientes.", n, n_of, n_pend)

    # verificación de clave antes de persistir (fail-loud)
    claves = [(f["orden_produccion"], f["terminal_report"], f["batchnum"]) for f in filas]
    if len(claves) != len(set(claves)):
        dups = len(claves) - len(set(claves))
        logger.error("CLAVE NO ÚNICA: %d colisiones (of,tr,batchnum). "
                     "Aborto para no perder filas en el UPSERT.", dups)
        sys.exit(3)

    if args.dry_run:
        logger.info("[DRY-RUN] no se persiste. %d filas listas.", n)
        logger.info("=== CRON OF/SAP fin (dry-run) %.1fs ===",
                    (datetime.now() - t0).total_seconds())
        return

    # 3-4. Crear tabla + UPSERT acumulativo
    try:
        from db_mrp import crear_tablas_of_sap, upsert_of_sap_bulk
        crear_tablas_of_sap()
        res = upsert_of_sap_bulk(filas)
    except Exception as e:
        logger.error("Persistencia FALLÓ: %s", e)
        sys.exit(4)

    logger.info("UPSERT OK: %d filas procesadas.", res["filas"])
    logger.info("=== CRON OF/SAP fin %.1fs ===", (datetime.now() - t0).total_seconds())


if __name__ == "__main__":
    main()
