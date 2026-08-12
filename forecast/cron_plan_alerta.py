#!/usr/bin/env python3
"""
cron_plan_alerta.py — Verifica el plan del día y avisa SOLO si hay algo roto.

POR QUÉ EXISTE
--------------
El 12-08-2026 el cron murió con un KeyError y no se generó plan. Nadie se enteró
hasta que Germán leyó el log a las 07:19. `cron_plan.py` tiene sys.exit(2..6) y
ningún envío de correo: el cron MÁS crítico era el único sin notificación, cuando
`cron_faltantes.py` ya resolvía esto desde julio.

POR QUÉ ES UN CRON APARTE Y NO UN BLOQUE DENTRO DE cron_plan.py
---------------------------------------------------------------
Porque la alerta más importante es "el plan NO existe". Si el chequeo viviera
dentro de cron_plan.py, un proceso que muere no ejecutaría nada y no avisaría
nadie — exactamente el caso del 12-08. Tiene que ser un observador externo.

POLÍTICA (decidida el 12-08-2026)
---------------------------------
El plan SE PROMUEVE IGUAL aunque tenga problemas, y se avisa. No promover
también cuesta: deja a Producción con el plan y el stock de ayer. La decisión la
toma una persona, no el gate.

SOLO CHEQUEOS BINARIOS. Ninguno tiene umbral discutible: si dispara, algo está
roto. Las bandas (producción total fuera de rango, tamaño del universo, etc.)
quedan para cuando haya datos que las calibren — un umbral inventado se vuelve
ruido en una semana, y una alerta que llega todos los días se deja de mirar.

REGLA DE ORO: si no se puede decir qué hacer cuando llega, no es una alerta.

UN SOLO CORREO POR DÍA, con todos los hallazgos juntos, y SILENCIO si está todo
bien. Mismo patrón que cron_faltantes.

USO
---
    python3 /app/cron_plan_alerta.py           # verifica y avisa si hace falta
    python3 /app/cron_plan_alerta.py --dry-run # imprime, no envía
    python3 /app/cron_plan_alerta.py --forzar  # envía aunque esté todo OK (prueba)

CRONTAB (09:00 Chile = 13:00 UTC). El plan arranca 06:00 y en el peor caso -- A y
C agotando los dos TL -- cierra ~07:40, asi que a las 09:00 hay margen sin
arriesgar un falso positivo por corrida larga:

    0 13 * * * docker exec -e PYTHONPATH=/app -w /app traverso_forecast \\
      python3 /app/cron_plan_alerta.py >> /home/ubuntu/traverso_plan_alerta.log 2>&1
"""
import argparse
import datetime as dt
import json
import logging
import sys

sys.path.insert(0, "/app")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("plan_alerta")

# Un plan de hoy que no cerró antes de esta hora ya es sospechoso, pero el margen
# se maneja corriendo el cron a las 09:00; acá no se asume nada de horarios.
STATUS_MALOS = {"INFEASIBLE", "TIMEOUT_SIN_SOLUCION"}


def _hoy_chile() -> dt.date:
    """Fecha local de Chile. El container corre en UTC y en la madrugada UTC ya es
    'mañana' respecto de Chile, así que usar utcnow().date() daría el día equivocado."""
    return (dt.datetime.utcnow() - dt.timedelta(hours=4)).date()


def revisar() -> tuple[list, list, dict]:
    """Devuelve (criticos, avisos, contexto). Cada hallazgo es (codigo, texto)."""
    from sqlalchemy import text
    from db_mrp import SessionLocal

    hoy = _hoy_chile()
    crit, avis, ctx = [], [], {"fecha": hoy.isoformat()}

    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, created_at, timestamp_stock, status, gap, aceptable, vigente, "
            "snapshot FROM mrp_planes ORDER BY id DESC LIMIT 1")).mappings().first()

    # ── A. ¿Existe un plan de hoy? ────────────────────────────────────────────
    # Es LA alerta importante: el caso del 12-08.
    if row is None:
        crit.append(("SIN_PLANES", "No hay ningún plan en mrp_planes."))
        return crit, avis, ctx

    creado = row["created_at"]
    f_creado = creado.date() if hasattr(creado, "date") else None
    ctx.update(plan_id=row["id"], creado=str(creado)[:19], status=row["status"],
               vigente=row["vigente"], aceptable=row["aceptable"])

    if f_creado != hoy:
        crit.append(("SIN_PLAN_HOY",
                     f"El último plan es el #{row['id']} del {str(creado)[:16]}. "
                     f"HOY ({hoy}) no se generó ninguno.\n"
                     f"    -> Revisar /home/ubuntu/traverso_cron.log y correr a mano."))
        # Sin plan de hoy, el resto de los chequeos no aplican al plan de hoy.
        return crit, avis, ctx

    # ── B. ¿Se promovió? ──────────────────────────────────────────────────────
    # Con la política vigente (promover igual y avisar) esto no debería pasar.
    if not row["vigente"]:
        crit.append(("NO_PROMOVIDO",
                     f"El plan #{row['id']} se generó pero NO quedó vigente "
                     f"(aceptable={row['aceptable']}). Producción sigue con el anterior.\n"
                     f"    -> Revisar el gate en el log."))

    # ── C. ¿El stock es de hoy? ───────────────────────────────────────────────
    ts = row["timestamp_stock"]
    f_stock = ts.date() if hasattr(ts, "date") else None
    ctx["stock"] = str(ts)[:10]
    if f_stock != hoy:
        crit.append(("STOCK_VIEJO",
                     f"El plan #{row['id']} se calculó con stock del {f_stock}, no de hoy.\n"
                     f"    -> Falló el refresco de stock (datalake). El plan está "
                     f"sobre inventario desactualizado."))

    # ── D. ¿El solver resolvió? ───────────────────────────────────────────────
    st = str(row["status"] or "")
    if st in STATUS_MALOS:
        crit.append(("SOLVER",
                     f"La pasada C terminó en {st} (no resolvió).\n"
                     f"    -> Es el incidente del 06-08. Revisar N2_BARRERA_SOBRE."))

    snap = row["snapshot"] or {}
    if isinstance(snap, str):
        snap = json.loads(snap)
    dd = snap.get("detalle_diario") or {}

    # ── E. ¿Llegaron las OV de HANA? ──────────────────────────────────────────
    # Si HANA cae, el plan corre SIN demanda de pedidos y no avisa (pendiente R4
    # desde el 20-07). Cero SKU con pedido en TODO el horizonte no es plausible.
    n_ov = sum(1 for serie in dd.values()
               if any(float(c.get("pedidos_crudos_u") or 0) > 0 for c in serie.values()))
    ctx["sku_con_ov"] = n_ov
    if dd and n_ov == 0:
        crit.append(("SIN_OV",
                     "Ningún SKU tiene pedidos (OV) en el horizonte.\n"
                     "    -> Probable caída de HANA: el plan se calculó solo con "
                     "forecast, sin demanda real."))

    # ── F. ¿Algún evento quedó inerte? ────────────────────────────────────────
    # Un regresor cuyas fechas no coinciden EXACTO con el `ds` del modelo genera
    # una columna de ceros: Prophet lo ignora sin error y el forecast queda igual
    # que sin evento. Falla silenciosa pura.
    try:
        from eventos import cargar_eventos_activos
        from forecaster import load_model, make_key
        import pandas as pd
        regs = cargar_eventos_activos()
        ctx["eventos_sku"] = len(regs)
        for sku, lista in sorted(regs.items()):
            cached = load_model(make_key(sku, None, None))
            if not cached:
                avis.append(("EVENTO_SIN_MODELO",
                             f"{sku} tiene eventos cargados pero no hay modelo en caché."))
                continue
            model, _ = cached
            ds = set(pd.to_datetime(model.history["ds"]).dt.strftime("%Y-%m-%d"))
            for r in lista:
                n_ok = len(ds & set(r["dates"]))
                if n_ok == 0:
                    crit.append(("EVENTO_INERTE",
                                 f"{sku}: el regresor '{r['name']}' no coincide con "
                                 f"ninguna semana del historial.\n"
                                 f"    -> No está corrigiendo NADA. Revisar las fechas."))
                elif n_ok < len(r["dates"]):
                    avis.append(("EVENTO_PARCIAL",
                                 f"{sku}: '{r['name']}' coincide en {n_ok} de "
                                 f"{len(r['dates'])} semanas."))
    except Exception as e:
        avis.append(("EVENTO_CHEQUEO", f"No se pudo verificar los eventos: "
                                       f"{type(e).__name__}: {e}"))

    return crit, avis, ctx


def _cuerpo(crit, avis, ctx) -> str:
    L = [f"Verificación del plan del {ctx.get('fecha')}", ""]
    if ctx.get("plan_id"):
        L += [f"  plan #{ctx['plan_id']} · creado {ctx.get('creado')} · "
              f"status {ctx.get('status')}",
              f"  stock {ctx.get('stock')} · vigente {ctx.get('vigente')} · "
              f"{ctx.get('sku_con_ov', '?')} SKU con OV", ""]
    if crit:
        L += ["PROBLEMAS:", ""]
        for i, (cod, txt) in enumerate(crit, 1):
            L += [f"  {i}. [{cod}] {txt}", ""]
    if avis:
        L += ["Avisos menores:", ""]
        L += [f"  - [{cod}] {txt}" for cod, txt in avis] + [""]
    if not crit and not avis:
        L += ["Sin hallazgos: el plan de hoy está OK.", ""]
    L += ["--",
          "Verificador diario del plan · Traverso · mensaje automático",
          "Solo avisa cuando encuentra algo. El silencio significa que está bien."]
    return "\n".join(L)


def prevuelo(imprimir_solo=False) -> int:
    """PRE-VUELO: corre el ciclo completo del plan en dry-run y avisa si se rompe.

    POR QUÉ ES UN PROCESO EXTERNO Y NO UN BLOQUE DENTRO DE cron_plan.py: el caso
    que hay que detectar es justamente que cron_plan CRASHEE. Si el aviso viviera
    adentro, un traceback impediría que se ejecute — exactamente lo del 12-08.

    Corre con los TL del solver en 5 s: no interesa la calidad del plan, solo que
    el ciclo NO SE ROMPA. Tarda ~2 min en vez de ~90.
    """
    import os
    import subprocess

    env = dict(os.environ)
    # TL cortos: el pre-vuelo mide que no crashee, no que el plan sea bueno.
    # OJO: el TL de la Pasada A lo controla N2_TL_A, NO --time-limit.
    env["N2_TL_A"] = "5"
    env["N2_TL_C"] = "5"
    cmd = [sys.executable, "/app/cron_plan.py", "--dry-run", "--skip-refresh",
           "--no-promote", "--horizonte", "8", "--time-limit", "5"]

    logger.info("Pre-vuelo: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=1200, cwd="/app")
        salida = (r.stdout or "") + (r.stderr or "")
        ok = (r.returncode == 0) and ("Traceback" not in salida)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        salida, ok, rc = "El pre-vuelo excedió los 20 minutos.", False, -1
    except Exception as e:
        salida, ok, rc = f"{type(e).__name__}: {e}", False, -2

    if ok:
        logger.info("Pre-vuelo OK: el ciclo completo corre sin errores.")
        if imprimir_solo:
            print("Pre-vuelo OK.")
        return 0

    # Solo las últimas líneas: el traceback y el contexto inmediato.
    cola = "\n".join(salida.strip().splitlines()[-25:])
    cuerpo = (
        f"El PRE-VUELO del plan falló (exit {rc}).\n\n"
        f"El ciclo se rompe con los datos de hoy, así que el cron de las 06:00 "
        f"probablemente NO genere plan.\n"
        f"Hay tiempo de arreglarlo antes.\n\n"
        f"Últimas líneas:\n\n{cola}\n")
    logger.error("Pre-vuelo FALLÓ (exit %s)", rc)
    if imprimir_solo:
        print(cuerpo)
        return 1
    import os as _os
    from enviar_faltantes import enviar_alerta
    enviar_alerta(f"[Traverso] PRE-VUELO del plan FALLÓ — {_hoy_chile()}", cuerpo,
                  destinatarios=_os.environ.get("PLAN_ALERTA"))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="imprime, no envía")
    ap.add_argument("--forzar", action="store_true", help="envía aunque esté todo OK")
    ap.add_argument("--prevuelo", action="store_true",
                    help="corre el ciclo del plan en dry-run y avisa si se rompe")
    args = ap.parse_args()

    if args.prevuelo:
        return prevuelo(imprimir_solo=args.dry_run)

    try:
        crit, avis, ctx = revisar()
    except Exception as e:
        # Un verificador que muere en silencio es PEOR que no tenerlo: daría la
        # falsa sensación de que no hay problemas. Si el chequeo falla, avisa.
        logger.exception("El chequeo falló")
        cuerpo = (f"El verificador del plan falló y no pudo revisar nada.\n\n"
                  f"{type(e).__name__}: {e}\n\n"
                  f"El plan de hoy quedó SIN VERIFICAR.")
        if args.dry_run:
            print(cuerpo)
            return 1
        try:
            from enviar_faltantes import enviar_alerta
            import os
            enviar_alerta("[Traverso] Falló el verificador del plan", cuerpo,
                          destinatarios=os.environ.get("PLAN_ALERTA"))
        except Exception:
            logger.exception("Tampoco se pudo enviar la alerta")
        return 1

    cuerpo = _cuerpo(crit, avis, ctx)
    logger.info("criticos=%d avisos=%d", len(crit), len(avis))

    if args.dry_run:
        print(cuerpo)
        return 0

    if not crit and not avis and not args.forzar:
        logger.info("Sin hallazgos: no se envía correo.")
        return 0

    # El asunto distingue "no hay plan" de "el plan es raro": no pesan igual.
    sin_plan = any(c in ("SIN_PLAN_HOY", "SIN_PLANES") for c, _ in crit)
    if sin_plan:
        asunto = f"[Traverso] SIN PLAN DE PRODUCCION — {ctx.get('fecha')}"
    elif crit:
        asunto = f"[Traverso] Plan con problemas — {ctx.get('fecha')}"
    else:
        asunto = f"[Traverso] Plan: avisos menores — {ctx.get('fecha')}"

    import os
    from enviar_faltantes import enviar_alerta
    enviar_alerta(asunto, cuerpo, destinatarios=os.environ.get("PLAN_ALERTA"))
    logger.info("Alerta enviada: %s", asunto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
