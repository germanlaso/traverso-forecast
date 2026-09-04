#!/usr/bin/env python3
"""
cron_retrain.py -- Wrapper de reentrenamiento semanal de modelos Prophet (F3).

Envuelve retrain_modelos.py agregando lo que el script pelado NO hace:

  1. BACKUP de /app/models ANTES de reentrenar. retrain_modelos.py no respalda
     solo (la linea 25 de ese script es solo el comando manual documentado).
     Sin esto, un reentreno con datos malos sobrescribe todos los modelos buenos
     sin rollback.
  2. GUARDA DE CONTEO (patron cron_faltantes.py / D4): si el reentreno retorna
     != 0, o deja menos de UMBRAL_MIN_MODELOS pkl reescritos, NO falla en
     silencio -> alerta al admin. Un reentreno parcial silencioso reactiva el
     acantilado de SS y el plan vuelve a dar TIMEOUT semanas despues.
  3. HEARTBEAT opcional en exito (HEARTBEAT_OK): un mail breve confirma que
     corrio, para distinguir "corrio OK" de "el cron no se disparo" (server
     caido un domingo).

Se invoca desde cron el domingo noche Chile.
Ver DECISION_forecast_cobertura_y_reentrenamiento.md (D2).

Autor: German Laso <glaso@traverso.cl>
"""
import os
import sys
import glob
import shutil
import logging
import subprocess
from datetime import datetime

# --- Parametros (ajustables) ---
MODELS_DIR = "/app/models"
RETRAIN = "/app/retrain_modelos.py"
HORIZONTE = 8

# El 04-09 el reentreno dejo 199 pkl frescos (244 universo - 43 MTO - 2 sin-datos).
# Umbral conservador: alerta si se reescriben <185 (perdida de >~14 SKU respecto
# del normal). Ajustar si el universo forecasteable cambia de tamano.
UMBRAL_MIN_MODELOS = 185

HEARTBEAT_OK = True   # mail breve tambien en exito (detecta "el cron no corrio")
ADMIN = None          # None -> enviar_alerta usa su destinatario por defecto (admin)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [retrain] %(message)s",
)
log = logging.getLogger(__name__)


def _backup_models() -> str:
    """Copia /app/models a /app/models_bak_YYYYMMDD (sufijo _HHMM si ya existe)."""
    if not os.path.isdir(MODELS_DIR):
        raise RuntimeError(f"No existe {MODELS_DIR}")
    dst = f"/app/models_bak_{datetime.now():%Y%m%d}"
    if os.path.exists(dst):
        dst = f"{dst}_{datetime.now():%H%M}"
    shutil.copytree(MODELS_DIR, dst)  # copy2: preserva mtime del origen; no lo toca
    n = len(glob.glob(os.path.join(dst, "*.pkl")))
    log.info("[1/3] backup OK -> %s (%d pkl)", dst, n)
    return dst


def _contar_reescritos(desde_ts: float) -> int:
    """
    Cuenta pkl en /app/models con mtime >= desde_ts (inicio del wrapper).
    Son exactamente los que el reentreno acaba de reescribir. Robusto a TZ y a
    medianoche (no depende de comparar contra date.today()). El backup vive en
    otro directorio, asi que no contamina el conteo.
    """
    return sum(
        1
        for f in glob.glob(os.path.join(MODELS_DIR, "*.pkl"))
        if os.path.getmtime(f) >= desde_ts
    )


def _alerta(asunto: str, cuerpo: str) -> None:
    try:
        from enviar_faltantes import enviar_alerta
        enviar_alerta(asunto, cuerpo, ADMIN)
        log.info("mail enviado: %s", asunto)
    except Exception:
        log.exception("no se pudo enviar el mail")


def main() -> int:
    t0 = datetime.now()
    log.info("=== CRON RETRAIN inicio ===")

    # --- 1/3: backup (obligatorio antes de sobrescribir) ---
    try:
        _backup_models()
    except Exception as e:
        log.exception("backup FALLO")
        _alerta(
            "[Traverso][RETRAIN] FALLO backup de modelos",
            f"El backup previo al reentrenamiento fallo: {e}\n"
            f"NO se reentreno (los modelos vigentes quedan intactos).",
        )
        return 1

    # --- 2/3: reentrenamiento (subproceso aislado, captura rc) ---
    log.info("[2/3] reentrenando (retrain_modelos.py --horizonte %d) ...", HORIZONTE)
    try:
        rc = subprocess.run(
            [sys.executable, RETRAIN, "--horizonte", str(HORIZONTE)]
        ).returncode
    except Exception as e:
        log.exception("no se pudo lanzar retrain_modelos.py")
        _alerta(
            "[Traverso][RETRAIN] FALLO al lanzar el reentrenamiento",
            f"No se pudo ejecutar {RETRAIN}: {e}\n"
            f"Los modelos viejos estan respaldados en /app/models_bak_*.",
        )
        return 1

    dt_min = (datetime.now() - t0).total_seconds() / 60.0
    log.info("[2/3] retrain rc=%d t=%.1f min", rc, dt_min)

    # --- 3/3: guarda de conteo ---
    frescos = _contar_reescritos(t0.timestamp())
    log.info(
        "[3/3] modelos reescritos: %d (umbral %d)", frescos, UMBRAL_MIN_MODELOS
    )

    if rc != 0 or frescos < UMBRAL_MIN_MODELOS:
        _alerta(
            "[Traverso][RETRAIN] Reentrenamiento con problemas",
            (
                "El reentrenamiento semanal termino con problemas.\n\n"
                f"  return code : {rc} (esperado 0)\n"
                f"  reescritos  : {frescos} (umbral {UMBRAL_MIN_MODELOS})\n"
                f"  duracion    : {dt_min:.1f} min\n\n"
                "Los modelos previos estan respaldados en /app/models_bak_*.\n"
                "Revisar traverso_retrain.log. Si no se corrige, el plan puede "
                "volver a dar TIMEOUT por forecast desactualizado."
            ),
        )
        log.warning(
            "=== CRON RETRAIN fin CON PROBLEMAS | rc=%d frescos=%d ===", rc, frescos
        )
        return 1

    log.info("=== CRON RETRAIN fin OK | frescos=%d t=%.1f min ===", frescos, dt_min)
    if HEARTBEAT_OK:
        _alerta(
            "[Traverso][RETRAIN] OK - modelos reentrenados",
            f"Reentrenamiento semanal OK: {frescos} modelos frescos en {dt_min:.1f} min.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
