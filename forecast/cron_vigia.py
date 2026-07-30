"""
cron_vigia.py — Orquestador horario del Vigía de OV.

Flujo:
  1. Evalúa (vigia_ov.evaluar): lee HANA en vivo y detecta quiebres nuevos.
  2. ANTI-SPAM: descarta los tramos ya notificados (tabla mrp_vigia_alertas), salvo
     que hayan empeorado materialmente o escalado a CRÍTICO.
  3. Si queda algo por notificar → envía el correo y registra el estado.
  4. Si la evaluación FALLA → alerta SOLO al admin. Nunca silencio: sin esto, un
     fallo de HANA se leería como "no hay riesgo" (el falso cero de faltantes).

Cron sugerido (horario hábil, cada hora, hora Chile = UTC-4):
    0 12-23 * * 1-5  docker exec -e PYTHONPATH=/app -w /app traverso_forecast \\
                       python3 /app/cron_vigia.py >> /home/ubuntu/traverso_vigia.log 2>&1

  · 12-23 UTC = 8-19 Chile. De madrugada no entran OV.
  · 1-5 = lunes a viernes.
  · No se solapa con el cron del plan (10:00 UTC) ni con faltantes (12:00 UTC): el
    vigía tarda segundos, así que aunque coincida a las 12 no compite.

Uso manual:
    python3 cron_vigia.py            # evalúa, aplica anti-spam y envía si corresponde
    python3 cron_vigia.py --dry-run  # evalúa y muestra qué enviaría, sin enviar ni marcar
"""

import argparse
import logging
import sys
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cron_vigia")

# Un tramo ya notificado se vuelve a avisar si el déficit crece al menos esto.
# Dos condiciones a la vez para no avisar por diferencias de redondeo.
UMBRAL_PEOR_PCT = 0.20      # +20%
UMBRAL_PEOR_CJ = 10.0       # y al menos +10 cajas


def _filtrar_anti_spam(rep: dict) -> tuple[list, list]:
    """Devuelve (a_notificar, motivos). Cada SKU conserva sólo los tramos nuevos."""
    from db_mrp import get_vigia_alertas
    previas = get_vigia_alertas()
    a_notificar, motivos = [], []

    for r in rep.get("sku_alerta", []):
        tramos_nuevos = []
        for t in r["tramos"]:
            k = (str(r["sku"]), str(t["desde"]))
            ant = previas.get(k)
            if ant is None:
                tramos_nuevos.append(t)
                motivos.append(f"{r['sku']} {t['desde']}: NUEVO")
                continue
            escalo = (str(ant.get("clase")) != "CRITICO" and t["clase"] == "CRITICO")
            d_ant = float(ant.get("deficit_max_cj") or 0)
            peor = (t["deficit_max_cj"] >= d_ant * (1 + UMBRAL_PEOR_PCT)
                    and t["deficit_max_cj"] - d_ant >= UMBRAL_PEOR_CJ)
            if escalo or peor:
                tramos_nuevos.append(t)
                motivos.append(
                    f"{r['sku']} {t['desde']}: "
                    + ("ESCALÓ a CRÍTICO" if escalo
                       else f"EMPEORÓ {d_ant:,.0f} -> {t['deficit_max_cj']:,.0f} cj"))
        if tramos_nuevos:
            rr = dict(r)
            rr["tramos"] = tramos_nuevos
            rr["criticos"] = [t for t in tramos_nuevos if t["clase"] == "CRITICO"]
            a_notificar.append(rr)
    return a_notificar, motivos


def _marcar(rep: dict, notificados: list) -> None:
    from db_mrp import upsert_vigia_alerta
    for r in notificados:
        for t in r["tramos"]:
            upsert_vigia_alerta(
                sku=str(r["sku"]), desde=t["desde"], hasta=t["hasta"],
                clase=t["clase"], deficit_max_cj=t["deficit_max_cj"],
                plan_id=rep.get("plan_id"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=5, help="días hábiles de la ventana")
    ap.add_argument("--dry-run", action="store_true",
                    help="muestra qué enviaría, sin enviar ni marcar")
    args = ap.parse_args()

    # ── 1. Evaluación ─────────────────────────────────────────────────────────
    try:
        import vigia_ov
        rep = vigia_ov.evaluar(n_dias=args.dias)
        logger.info("Evaluación OK: %d SKU en alerta (%d críticos).",
                    rep["total_alertas"], rep["total_criticos"])
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Evaluación FALLÓ: %s", e)
        try:
            import enviar_vigia
            enviar_vigia.enviar_alerta(
                asunto="⚠ ERROR en el Vigía de OV — Traverso",
                cuerpo_texto=(
                    "La evaluación horaria del vigía de OV FALLÓ. NO se envió aviso a los "
                    "destinatarios, así que la ausencia de correo en esta corrida NO "
                    "significa que no haya riesgo.\n\n"
                    f"Error:\n{tb}\n"
                    "Revisar conexión HANA / plan vigente y re-ejecutar:\n"
                    "  docker exec -e PYTHONPATH=/app -w /app traverso_forecast "
                    "python3 /app/vigia_ov.py"))
            logger.info("Alerta de error enviada al admin.")
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(1)

    # ── 2. Anti-spam ──────────────────────────────────────────────────────────
    try:
        notificar, motivos = _filtrar_anti_spam(rep)
    except Exception as e:
        logger.error("Anti-spam FALLÓ (%s) -> se notifica todo para no perder la alerta.", e)
        notificar, motivos = rep.get("sku_alerta", []), ["(anti-spam no disponible)"]

    if not notificar:
        logger.info("Nada nuevo que notificar (%d SKU en alerta ya avisados).",
                    rep["total_alertas"])
        return

    for m in motivos:
        logger.info("  a notificar -> %s", m)

    if args.dry_run:
        import vigia_ov as _v
        print("\n*** DRY-RUN: esto se enviaría ***")
        _v._imprimir({**rep, "sku_alerta": notificar,
                      "total_alertas": len(notificar),
                      "total_criticos": len([r for r in notificar if r["criticos"]])})
        return

    # ── 3. Envío + marcado ────────────────────────────────────────────────────
    try:
        import enviar_vigia
        enviar_vigia.enviar(rep, notificar=notificar)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Envío FALLÓ: %s", e)
        try:
            import enviar_vigia
            enviar_vigia.enviar_alerta(
                asunto="⚠ ERROR al enviar el aviso del Vigía de OV — Traverso",
                cuerpo_texto=("La detección funcionó pero FALLÓ el envío del correo. "
                              "Los tramos NO se marcaron, así que se reintenta en la "
                              f"corrida siguiente.\n\nError:\n{tb}"))
        except Exception as e2:
            logger.error("Además falló el envío de la alerta: %s", e2)
        sys.exit(2)

    # Se marca DESPUÉS del envío exitoso: si el correo falla, la próxima corrida
    # reintenta en vez de dar el aviso por entregado.
    try:
        _marcar(rep, notificar)
    except Exception as e:
        logger.error("El aviso se envió pero NO se pudo marcar (%s): puede repetirse.", e)

    # higiene: soltar tramos viejos
    try:
        from db_mrp import limpiar_vigia_alertas
        n = limpiar_vigia_alertas(dias=30)
        if n:
            logger.info("Alertas viejas eliminadas: %d", n)
    except Exception:
        pass


if __name__ == "__main__":
    main()
