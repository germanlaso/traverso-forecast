#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron_plan.py — Ciclo diario de planificacion (6 AM).

Reusa el MISMO pipeline que el endpoint /plan (funciones reales de main/forecaster/
mrp/stock/db_mrp; NO reconstruye nada). Diferencias con /plan:
  - captura el resultado RICO (stock_diario, uso_linea) via monkeypatch, para el gate
  - al final: evaluar_gate_n1 -> persistir_plan -> (si aceptable) promover_plan

Flujo:
  1. refresh stock (fetch_and_save_stock)
  2. leer stock (load_stock_parquet + calcular_stock_disponible)
  3. FAIL-SAFE de frescura: fecha_descarga == hoy y filas > 0
       si no -> NO generar, alertar, conservar el plan vigente, salir con codigo != 0
  4. forecast capeado (run_sku_pipeline -> ya aplica _cap_forecast)
  5. aprobadas -> entradas_fijas (logica copiada LITERAL de /plan, L411-437)
  6. optimizar_plan (wrapper real; cap ya en el pipeline)
  7. evaluar_gate_n1 sobre el rico capturado
  8. persistir_plan (SIEMPRE, auditoria) + (si aceptable) promover_plan, en UNA txn
       si no aceptable -> persiste vigente=false, NO promueve, conserva el vigente previo

Uso (manual / test):
  docker exec traverso_forecast python3 /app/cron_plan.py --horizonte 8 --time-limit 1800
Cron (crontab del host, 6 AM):
  0 6 * * *  docker exec traverso_forecast python3 /app/cron_plan.py --horizonte 8 --time-limit 1800 >> /var/log/traverso_cron.log 2>&1

NOTA: la logica de 'aprobadas -> entradas_fijas' esta DUPLICADA de main.py /plan.
Deuda conocida: extraer a una funcion compartida. Hoy se copia literal para no
tocar main.py (archivo sensible) ni aproximar la parte delicada de las OFs.
"""
import argparse
import datetime as dt
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cron_plan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizonte", type=int, default=8, help="horizonte en semanas")
    ap.add_argument("--time-limit", type=int, default=1800, help="time_limit del solver en seg")
    ap.add_argument("--skip-refresh", action="store_true", help="no refrescar stock (test)")
    ap.add_argument("--no-pedidos", action="store_true", help="no netear OV de HANA (test/A-B)")
    ap.add_argument("--no-promote", action="store_true", help="persistir sin promover (test: no pisa el vigente)")
    args = ap.parse_args()

    hoy = dt.date.today()
    log.info(f"=== CRON PLAN inicio | horizonte={args.horizonte} sem | time_limit={args.time_limit}s | hoy={hoy} ===")

    # ── 1. REFRESH STOCK ─────────────────────────────────────────────────────
    from stock import fetch_and_save_stock, load_stock_parquet, calcular_stock_disponible
    if not args.skip_refresh:
        try:
            res = fetch_and_save_stock()
            log.info(f"[1/8] refresh OK: {res.get('n_skus')} SKUs, {res.get('n_registros')} registros, "
                     f"fecha_descarga_info={res.get('fecha_descarga_info')}")
        except Exception as e:
            log.error(f"[1/8] refresh FALLO: {e} -> abortar, conservar plan vigente")
            sys.exit(2)
    else:
        log.info("[1/8] refresh OMITIDO (--skip-refresh)")

    # ── 2. LEER STOCK ────────────────────────────────────────────────────────
    df_stock = load_stock_parquet()
    n_filas = 0 if df_stock is None or df_stock.empty else len(df_stock)
    log.info(f"[2/8] stock leido: {n_filas} filas")

    # ── 3. FAIL-SAFE DE FRESCURA ─────────────────────────────────────────────
    # El stock en SQL es acumulativo: el vigente es el del MAX(fecha_descarga).
    # Verificamos que ese MAX sea HOY y que haya filas. Si no, NO generamos plan.
    if n_filas == 0:
        log.error("[3/8] FAIL-SAFE: stock vacio (0 filas) -> NO generar, conservar vigente")
        sys.exit(3)

    fecha_col = None
    for c in ("fecha_descarga", "fecha_descarga_info"):
        if c in df_stock.columns:
            fecha_col = c
            break
    if fecha_col is None:
        log.warning("[3/8] FAIL-SAFE: no encuentro columna fecha_descarga -> continuo con ADVERTENCIA")
        max_fecha = None
    else:
        import pandas as pd
        fechas = pd.to_datetime(df_stock[fecha_col], errors="coerce").dropna()
        max_fecha = fechas.max().date() if len(fechas) else None
        log.info(f"[3/8] MAX({fecha_col}) = {max_fecha}")
        # OJO trampa conocida: fecha_descarga puede venir con dia/mes cruzados
        # (bug de parseo en el refresh). Si max_fecha != hoy, no asumimos stale a
        # ciegas: logueamos fuerte y NO promovemos (persistimos para auditoria).
        if max_fecha != hoy:
            log.warning(f"[3/8] FAIL-SAFE: stock NO es de hoy (max={max_fecha}, hoy={hoy}). "
                        f"Puede ser stock viejo O el bug de parseo de fecha_descarga. "
                        f"Se generara el plan pero NO se promovera (auditoria).")
            frescura_ok = False
        else:
            frescura_ok = True

    if fecha_col is None:
        frescura_ok = False  # sin poder verificar frescura, no promovemos

    # ── 4-6. GENERAR PLAN (mismo pipeline que /plan) ─────────────────────────
    import mrp as _mrp
    from forecaster import run_sku_pipeline
    from db_mrp import listar_aprobadas_db
    import optimizer
    from optimizer import optimizar_plan

    # captura del RICO via monkeypatch (patron probado)
    _RICH = []
    _orig = optimizer.optimizar_plan_v12_rich
    optimizer.optimizar_plan_v12_rich = lambda *a, **k: (_RICH.append(_orig(*a, **k)) or _RICH[-1])
    # forzar time_limit del solver
    optimizer._time_limit_para = lambda *a, **k: args.time_limit

    # parametros
    sku_params, lineas, sku_lineas = _mrp.load_params_from_db()
    if not sku_params:
        log.error("[4/8] parametros MRP vacios -> abortar")
        sys.exit(4)

    # stock disponible (misma funcion que /plan)
    unidades_por_caja = {p.sku: p.unidades_por_caja for p in sku_params.values()}
    stocks_actuales, alertas_vcto = calcular_stock_disponible(
        df_raw=df_stock, unidades_por_caja=unidades_por_caja,
    )

    # forecasts (run_sku_pipeline -> capea internamente)
    # get_sales_df vive en main; lo importamos para reusar el cache/carga real
    from main import get_sales_df
    df_sales = get_sales_df()
    forecasts = {}
    n_mto = 0
    for sku in sku_params:
        # MTO (a pedido): sin forecast. Se OMITE del dict (mismo estado que
        # "forecast no disponible", ya manejado aguas abajo). La demanda queda
        # solo OV (se netea aparte) y SS=0 viene de params. -> demanda = OV.
        if getattr(sku_params[sku], "mto", False):
            n_mto += 1
            continue
        try:
            r = run_sku_pipeline(df=df_sales, sku=sku, canal=None,
                                 forecast_periods=args.horizonte + 4)
            forecasts[sku] = r.get("forecast", [])
        except Exception as e:
            log.warning(f"[4/8] forecast no disponible para {sku}: {e}")
    if n_mto:
        log.info(f"[4/8] MTO: {n_mto} SKU sin forecast (demanda solo OV)")
    log.info(f"[4/8] forecasts: {sum(1 for v in forecasts.values() if v)}/{len(sku_params)} (MTO {n_mto} omitidos)")
    if not forecasts:
        log.error("[4/8] sin forecasts -> abortar")
        sys.exit(4)

    # aprobadas -> entradas_fijas  (COPIA LITERAL de /plan L411-437)
    aprobadas_db = listar_aprobadas_db()
    hoy_str = hoy.isoformat()
    entradas_fijas = {}
    for ap in aprobadas_db:
        sku_ap = str(ap.get("sku", ""))
        fer = str(ap.get("fecha_entrada_real") or ap.get("semana_necesidad", ""))[:10]
        fl = str(ap.get("fecha_lanzamiento_real") or "")[:10]
        ln = str(ap.get("linea") or "")
        cj = float(ap.get("cantidad_real_cj") or 0)
        if sku_ap and fer and cj > 0 and fer > hoy_str:
            entradas_fijas.setdefault(sku_ap, []).append({
                "fecha_entrada": fer, "fecha_lanzamiento": fl, "linea": ln,
                "semana_necesidad": str(ap.get("semana_necesidad", ""))[:10],
                "cantidad_cajas": cj, "numero_of": ap.get("numero_of", ""),
                "aprobada": True,
            })
    log.info(f"[5/8] aprobadas -> entradas_fijas: {len(entradas_fijas)} SKU")

    # plan base MRP + optimizador (mismo que /plan)
    ordenes = _mrp.generar_plan_completo(
        sku_params=sku_params, forecasts=forecasts, stocks_actuales=stocks_actuales,
        lineas=lineas, horizonte_semanas=args.horizonte,
        alertas_stock=alertas_vcto, entradas_fijas=entradas_fijas,
    )
    # V-OV: netear pedidos abiertos (OV) de HANA. Reusa el helper de main
    # (fail-safe + kill-switch OV_NETTING_ENABLED en un solo lugar). skus_validos
    # = SKU de PRODUCCIÓN (el conector clasifica importado/maquila y planta-sin-
    # planificar). --no-pedidos lo omite para comparar A/B en la validación.
    pedidos_abiertos = {}
    # (11-07) desglose OV por SKU (en unidades) para el encabezado del dashboard:
    #   fisico   = stock ANTES de rebajar OV vencida
    #   comprom  = OV vencida (lo que se resta)
    #   disp     = fisico - comprom  (puede ser < 0 = quiebre real de arranque)
    ov_encabezado: dict[str, dict] = {}
    if not args.no_pedidos:
        from main import _fetch_ov_split
        skus_prod = {s for s, p in sku_params.items()
                     if str(getattr(p, "tipo", "")).upper() == "PRODUCCION"}
        # V-OV2 (10-07): OV vencida = stock comprometido (rebaja stock), NO demanda.
        pedidos_abiertos, comprometido = _fetch_ov_split(skus_prod)
        if comprometido:
            n_neg = 0
            for s, cj in comprometido.items():
                upc_s = int(unidades_por_caja.get(s, 1) or 1)
                fisico_u = float(stocks_actuales.get(s, 0.0)) * upc_s   # ANTES de rebajar
                comprom_u = float(cj) * upc_s
                ov_encabezado[s] = {
                    "stock_fisico_u": int(round(fisico_u)),
                    "comprometido_u": int(round(comprom_u)),
                }
                stocks_actuales[s] = stocks_actuales.get(s, 0.0) - cj
                if stocks_actuales[s] < 0:
                    n_neg += 1
            log.info(f"[6/8] stock rebajado por OV vencida: {len(comprometido)} SKU "
                     f"({sum(comprometido.values()):.0f} cj); {n_neg} en disponible < 0.")
    log.info(f"[6/8] optimizando (OR-Tools)... | OV futuras(demanda): {len(pedidos_abiertos)} SKU con pedido")
    ordenes_opt, diag = optimizar_plan(
        ordenes_mrp=ordenes, sku_params=sku_params, lineas=lineas,
        forecasts=forecasts, stocks_actuales=stocks_actuales,
        entradas_fijas=entradas_fijas, pedidos_abiertos=pedidos_abiertos,
        horizonte_semanas=args.horizonte,
    )
    log.info(f"[6/8] solver: status={diag.get('status')} gap={diag.get('gap')} "
             f"t={diag.get('tiempo_ms')}ms")

    if not _RICH:
        log.error("[6/8] no se capturo la capa rica -> abortar (no persisto)")
        sys.exit(5)
    rich = _RICH[-1]

    # Inyectar OF aprobadas como filas de orden (PARIDAD con main.py /plan L572+).
    # El optimizer consumio las aprobadas como entradas_fijas internas y NO las
    # re-emite como ordenes. Sin esto, vista_dashboard.ordenes NO contiene las
    # aprobadas -> el frontend las parcha como 'huerfanas' y desaparecen al
    # desaprobar. Las agregamos aca para que el snapshot del cron las incluya
    # igual que el endpoint /plan. (fix 13-07-26)
    from datetime import date as _date_helper, timedelta as _td_helper
    _ya_en_ordenes = {o.get('numero_of') for o in ordenes_opt if o.get('numero_of')}
    for sku_ap, lst in entradas_fijas.items():
        sp_ap = sku_params.get(sku_ap)
        upc_ap = getattr(sp_ap, 'unidades_por_caja', 1) if sp_ap else 1
        lt_ap = getattr(sp_ap, 'lead_time_semanas', 1) if sp_ap else 1
        desc_ap = getattr(sp_ap, 'descripcion', '') if sp_ap else ''
        tipo_ap = getattr(sp_ap, 'tipo', 'PRODUCCION') if sp_ap else 'PRODUCCION'
        linea_pref = getattr(sp_ap, 'linea_preferida', None) if sp_ap else None
        for ent in lst:
            if not ent.get('aprobada'):
                continue
            nof_ap = ent.get('numero_of', '')
            if nof_ap and nof_ap in _ya_en_ordenes:
                continue  # el optimizer ya la emitio; no duplicar
            fer_iso = str(ent.get('fecha_entrada', ''))[:10]
            if not fer_iso:
                continue
            try:
                f_ent = _date_helper.fromisoformat(fer_iso)
            except ValueError:
                continue
            fl_iso = str(ent.get('fecha_lanzamiento', '') or '')[:10]
            if fl_iso:
                f_lan_iso = fl_iso
            else:
                f_lan_iso = (f_ent - _td_helper(days=int(round(lt_ap * 7)))).isoformat()
            linea_ap = ent.get('linea', '') or linea_pref
            cj_ap = int(round(float(ent.get('cantidad_cajas', 0) or 0)))
            ordenes_opt.append({
                'sku': sku_ap, 'descripcion': desc_ap, 'tipo': tipo_ap,
                'semana_necesidad': ent.get('semana_necesidad', '') or fer_iso,
                'semana_emision': f_lan_iso, 'fecha_lanzamiento': f_lan_iso,
                'fecha_entrada_real': fer_iso,
                'cantidad_cajas': cj_ap, 'cantidad_unidades': cj_ap * upc_ap,
                'linea': linea_ap, 'motivo': 'OF aprobada',
                'alerta': None, 'tiene_alerta': False,
                'stock_inicial_cajas': 0, 'stock_final_cajas': 0,
                'forecast_cajas': 0, 'ss_cajas': 0,
                'lead_time_sem': lt_ap, 'u_por_caja': upc_ap,
                'aprobada': True, 'numero_of': nof_ap,
            })

    # Asignar numero_of a cada orden (copia literal de /plan L537-566).
    # Sin esto las ordenes salen con numero_of=null y el frontend no las
    # identifica (columna N Orden vacia, no se pueden aprobar).
    import re as _re
    from db_mrp import get_orden_by_key, numero_of_tentativo
    for o in ordenes_opt:
        sku_p = sku_params.get(o.get('sku', ''))
        if sku_p and 'lead_time_sem' not in o:
            o['lead_time_sem'] = getattr(sku_p, 'lead_time_semanas', 1)
        if o.get('numero_of') and o.get('aprobada'):
            continue
        motivo = o.get('motivo', '')
        m_ap = _re.search(r'OF_APROBADA:([\w-]+)', motivo)
        if m_ap:
            o['numero_of'] = m_ap.group(1); o['aprobada'] = True; continue
        fl = o.get('fecha_lanzamiento') or o.get('semana_emision')
        linea_o = o.get('linea') or ''
        existente = get_orden_by_key(o['sku'], fl, linea_o)
        if existente and existente.get('numero_of'):
            o['numero_of'] = existente['numero_of']
            o['aprobada'] = bool(existente.get('estado') == 'APROBADA')
        else:
            o['numero_of'] = numero_of_tentativo(o['sku'], fl, linea_o)
            o['aprobada'] = False

    # proyeccion_por_sku (copia literal de /plan L573-581): la pestana Stock
    # la lee como fuente unica de verdad (planExterno.proyeccion_por_sku[sku]).
    from proyeccion import construir_proyeccion_por_sku
    import datetime as _dt2
    try:
        proyeccion_por_sku = construir_proyeccion_por_sku(
            ordenes_finales=ordenes_opt, aprobadas_db=aprobadas_db,
            sku_params=sku_params, forecasts=forecasts,
            stocks_actuales=stocks_actuales, fecha_inicio=_dt2.date.today(),
            horizonte_dias=args.horizonte * 7,
        )
    except Exception as e:
        log.warning(f'[6/8] no se pudo construir proyeccion_por_sku: {e}')
        proyeccion_por_sku = {}

        # vista_dashboard: forma LEGACY que el frontend consume (App.js usa
    # plan.ordenes/stock_info/n_alertas/resumen_semanal/n_skus/n_ordenes).
    # Se guarda en el snapshot para que GET /plan/vigente la sirva directo,
    # sin traducir rico->legacy al vuelo.
    try:
        vencidos = [a for a in alertas_vcto if a.get('tipo') == 'VENCIDO']
        proximos = [a for a in alertas_vcto if a.get('tipo') == 'PROXIMO_VENCIMIENTO']
        rich['vista_dashboard'] = {
            'n_skus': len(sku_params),
            'n_ordenes': len(ordenes_opt),
            'n_alertas': sum(1 for o in ordenes_opt if o.get('tiene_alerta')),
            'horizonte_sem': args.horizonte,
            'stock_info': {
                'usa_stock_real': True,
                'advertencia': None,
                'n_lotes_vencidos_excluidos': len(vencidos),
                'n_lotes_proximos_vencer': len(proximos),
            },
            'ordenes': ordenes_opt,
            'resumen_semanal': _mrp.resumen_semanal(ordenes_opt),
            'proyeccion_por_sku': proyeccion_por_sku,
        }
    except Exception as e:
        log.warning(f'[6/8] no se pudo armar vista_dashboard: {e}')
        rich['vista_dashboard'] = None

    # (11-07) completar encabezado_sku con físico/comprometido (viven acá, antes
    # de la rebaja). El optimizer dejó esas claves en None; las poblamos ahora.
    try:
        enc = rich.get('encabezado_sku') or {}
        for s, ov in ov_encabezado.items():
            if s in enc:
                enc[s]['stock_fisico_u'] = ov['stock_fisico_u']
                enc[s]['comprometido_u'] = ov['comprometido_u']
        # SKU sin OV vencida: físico = disponible_inicial, comprometido = 0
        for s, e in enc.items():
            if e.get('stock_fisico_u') is None:
                e['stock_fisico_u'] = e.get('disponible_inicial_u', 0)
                e['comprometido_u'] = 0
        rich['encabezado_sku'] = enc
    except Exception as e:
        log.warning(f'[6/8] no se pudo completar encabezado_sku fis/comp: {e}')

    # ── 7. GATE ──────────────────────────────────────────────────────────────
    from persistencia import evaluar_gate_n1, persistir_plan, promover_plan
    aceptable, det = evaluar_gate_n1(rich)
    log.info(f"[7/8] gate: aceptable={aceptable} | G1={det['g1_sin_quiebres']} "
             f"G2={det['g2_lineas_ok']} | min_stock={det['min_stock']} "
             f"max_uso={det['max_uso_linea_pct']} | negativos={det['n_celdas_negativas']} "
             f"sobrecargas={det['n_lineas_sobrecargadas']}")

    # solo promovemos si el gate pasa Y la frescura del stock es OK
    promover = aceptable and frescura_ok and not args.no_promote
    if args.no_promote:
        log.info("[7/8] --no-promote: se persiste para inspección pero NO se promueve (vigente intacto)")
    if aceptable and not frescura_ok:
        log.warning("[7/8] plan ACEPTABLE pero stock no fresco -> persisto SIN promover")

    # ── 8. PERSISTIR (+ promover) EN UNA TRANSACCION ─────────────────────────
    from db_mrp import SessionLocal
    ts_stock = str(max_fecha) if max_fecha else None
    try:
        with SessionLocal() as s:
            plan_id = persistir_plan(
                resultado=rich, horizonte_sem=args.horizonte,
                timestamp_stock=ts_stock, time_limit_sec=args.time_limit,
                entradas_fijas=[v for lst in entradas_fijas.values() for v in lst],
                aceptable=aceptable,
                session=s,
            )
            if promover:
                promover_plan(plan_id, session=s)
                s.commit()
                log.info(f"[8/8] plan id={plan_id} PERSISTIDO y PROMOVIDO (vigente)")
            else:
                s.commit()
                log.info(f"[8/8] plan id={plan_id} PERSISTIDO sin promover "
                         f"(aceptable={aceptable}, frescura_ok={frescura_ok}) -> vigente previo intacto")
    except Exception as e:
        log.error(f"[8/8] error al persistir/promover: {e}")
        sys.exit(6)

    log.info(f"=== CRON PLAN fin OK | plan_id={plan_id} | promovido={promover} ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
