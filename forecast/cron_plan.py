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
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cron_plan")


def _detectar_recepcion_pendiente(aprobadas, unidades_por_caja, hoy,
                                 umbral=0.80, umbral_parcial=0.20):
    """Alertas de OF lanzadas el ÚLTIMO DÍA HÁBIL que no se reflejan en el stock de HOY.

    Día HÁBIL, no calendario: un lunes hay que mirar las OF del viernes. Con
    `hoy - 1 día` la alerta nunca se disparaba los lunes (nadie lanza OF el domingo),
    que es justo el día en que más importa.

    Las entregas se acumulan sobre TODO el rango [día de lanzamiento .. ayer], porque
    entre el lanzamiento y hoy pudo haber despachos (el sábado hay facturación).

    Ver el bloque 6c de main() para la semántica completa y los sesgos del método.
    Devuelve una lista de dicts listos para `snapshot['alertas']`; nunca modifica
    stock ni entradas: es puramente informativo.
    """
    from sqlalchemy import text as _t
    from db import get_engine
    from stock import _parse_decimal

    try:
        from dias_informe import dia_habil_anterior
        ayer = dia_habil_anterior(hoy) or (hoy - dt.timedelta(days=1))
    except Exception:
        ayer = hoy - dt.timedelta(days=1)

    # OF lanzadas el último día hábil, agregadas por SKU (puede haber más de una)
    ofs, refs = {}, {}
    for ap in aprobadas:
        if ap.get("fecha_lanzamiento_real") != ayer:
            continue
        sku = str(ap.get("sku", "")).strip()
        cj = float(ap.get("cantidad_real_cj") or 0)
        if not sku or cj <= 0:
            continue
        ofs[sku] = ofs.get(sku, 0.0) + cj
        refs.setdefault(sku, []).append(str(ap.get("numero_of", "")))
    if not ofs:
        return []

    lista_sku = ",".join("'" + s + "'" for s in ofs)
    bodegas = "'BSUR01','VESP01','VARA01'"

    def _snap(engine, fecha_ddmmyyyy):
        out = {}
        for bd in ("DBTraversoV2", "DBMontanerV2"):
            try:
                rows = engine.execute(_t(
                    f"SELECT LTRIM(RTRIM([CODIGO])) AS sku, [STOCK] AS st "
                    f"FROM {bd}.dbo.Stock_Lote_Fecha "
                    f"WHERE [FECHA DESCARGA INFO] = :f "
                    f"  AND [BODEGA] IN ({bodegas}) "
                    f"  AND LTRIM(RTRIM([CODIGO])) IN ({lista_sku})"),
                    {"f": fecha_ddmmyyyy}).fetchall()
            except Exception:
                continue          # Montaner puede no tener ese snapshot
            for sku, st in rows:
                out[sku] = out.get(sku, 0.0) + _parse_decimal(st)
        return out

    with get_engine().connect() as c:
        s_ayer = _snap(c, ayer.strftime("%d-%m-%Y"))
        s_hoy = _snap(c, hoy.strftime("%d-%m-%Y"))
        entregas = {}
        try:
            # rango completo: del día de lanzamiento hasta ayer inclusive. Si el
            # lanzamiento fue un viernes, cubre también sábado y domingo.
            for sku, cant in c.execute(_t(
                f"SELECT LTRIM(RTRIM([Codigo Articulo])) AS sku, SUM([Cantidad]) AS q "
                f"FROM dbo.ventas WHERE CAST([Fecha] AS DATE) BETWEEN :d1 AND :d2 "
                f"  AND [Tipo Doc] IN ('Factura','Boleta') AND [Cantidad] > 0 "
                f"  AND LTRIM(RTRIM([Codigo Articulo])) IN ({lista_sku}) "
                f"GROUP BY LTRIM(RTRIM([Codigo Articulo]))"),
                {"d1": ayer, "d2": hoy - dt.timedelta(days=1)}).fetchall():
                entregas[sku] = float(cant or 0)
        except Exception:
            entregas = {}         # sin entregas -> faltante sobrestimado, no subestimado

    alertas = []
    for sku, of_cj in sorted(ofs.items()):
        esperado = s_ayer.get(sku, 0.0) + of_cj - entregas.get(sku, 0.0)
        real = s_hoy.get(sku, 0.0)
        faltante = esperado - real
        frac = (faltante / of_cj) if of_cj else 0.0

        # (11-08-2026) BANDA PARCIAL. Antes el corte era `faltante < umbral` (0,80)
        # y la recepción PARCIAL quedaba muda. No por poco margen: el 11-08,
        # 251010105 tenía un faltante MÁXIMO de 637 cj sobre una OF de 900 y el
        # umbral era 720, así que era ARITMÉTICAMENTE IMPOSIBLE que alertara. Era el
        # único de los 11 SKU de ese día con un día de quiebre en el plan, y caía
        # justo en la banda ciega. Los 7 que sí alertaron eran todos de recepción
        # nula: la alerta funcionaba en los extremos y era ciega en el medio.
        #
        # El faltante parcial NO es ruido: son cajas que alguien tiene que decidir si
        # van a llegar. Sigue siendo informativo — el cálculo del plan no se toca.
        if frac < umbral_parcial:
            continue                      # recibida: nada que informar
        grado = "total" if frac >= umbral else "parcial"
        pct_recibido = max(0.0, min(100.0, 100.0 * (1.0 - frac)))

        upc = int(unidades_por_caja.get(sku, 1) or 1)
        refs_txt = ", ".join(x for x in refs.get(sku, []) if x)
        if grado == "total":
            msg = (f"OF de {of_cj:.0f} cj lanzada el {ayer.isoformat()} (último día "
                   f"hábil) no se refleja en el stock de hoy (esperado "
                   f"{esperado:.0f} cj, real {real:.0f} cj). Probable terminal report "
                   f"pendiente: los quiebres de los primeros días de este SKU "
                   f"podrían no ser reales.")
        else:
            msg = (f"Recepción PARCIAL: de la OF de {of_cj:.0f} cj lanzada el "
                   f"{ayer.isoformat()} llegaron ~{of_cj - faltante:.0f} cj "
                   f"({pct_recibido:.0f}%) y faltan ~{faltante:.0f} cj. El plan NO "
                   f"cuenta las que faltan, así que los quiebres de los primeros "
                   f"días de este SKU pueden no ser reales.")

        alertas.append({
            "sku": sku,
            "tipo": "RECEPCION_PENDIENTE",   # NO cambiar: el Mapa de Quiebres filtra
                                             # por este valor exacto (main.py L1477)
            "grado": grado,                  # "total" | "parcial"  (aditivo)
            "fecha": hoy.isoformat(),
            "numero_of": refs_txt,
            "of_cj": round(of_cj, 1),
            "stock_ayer_cj": round(s_ayer.get(sku, 0.0), 1),
            "entregas_ayer_cj": round(entregas.get(sku, 0.0), 1),
            "esperado_cj": round(esperado, 1),
            "real_cj": round(real, 1),
            "faltante_cj": round(faltante, 1),
            "faltante_u": int(round(faltante * upc)),
            "pct_recibido": round(pct_recibido, 1),
            "mensaje": msg,
        })
    return alertas


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
    # D1 (27-07-2026): el forecast debe cubrir el horizonte + los 35 dias de margen
    # que necesita el SS de cobertura + 7 de colchon. La constante `horizonte + 4`
    # no lo garantizaba: make_future_dataframe ancla en el fin de historia DEL
    # MODELO, no en hoy; con modelos cacheados el 82,6% de los SKU quedaba corto.
    # Ver DECISION_forecast_cobertura_y_reentrenamiento.md
    fecha_cobertura = hoy + dt.timedelta(days=args.horizonte * 7 + 42)
    log.info(f"[4/8] el forecast debe cubrir hasta {fecha_cobertura}")
    # (10-08-2026) EVENTOS COMERCIALES — Fase 1.
    # Detras de flag: mientras EVENTOS_ENABLED != 1 este bloque no hace nada y el
    # comportamiento es identico al de antes (extra_events=None). Se apaga sacando
    # el flag del crontab, sin revertir codigo.
    #
    # Efecto de pasar extra_events: run_sku_pipeline SALTEA el cache y reentrena
    # ese SKU en cada corrida (forecaster.py L371). No persiste el pickle: los
    # eventos vetan el guardado (ver INVARIANTE en run_sku_pipeline), porque un
    # modelo entrenado con eventos solo es cargable por una corrida que pase los
    # MISMOS eventos. Son segundos por SKU y solo afecta a los que tengan evento.
    eventos_por_sku: dict = {}
    if os.getenv("EVENTOS_ENABLED", "0") == "1":
        try:
            from eventos import cargar_eventos_activos
            eventos_por_sku = cargar_eventos_activos()
            n_reg = sum(len(v) for v in eventos_por_sku.values())
            log.info(f"[4/8] eventos ON: {len(eventos_por_sku)} SKU, {n_reg} regresor(es)")
            # Los SKU MTO se saltean antes del pipeline (abajo), asi que un evento
            # cargado sobre un MTO no se aplicaria y hay que decirlo.
            mto_ev = [s for s in eventos_por_sku
                      if getattr(sku_params.get(s), "mto", False)]
            if mto_ev:
                log.warning(f"[4/8] eventos IGNORADOS (SKU es MTO, sin forecast): {mto_ev}")
            fuera = [s for s in eventos_por_sku if s not in sku_params]
            if fuera:
                log.warning(f"[4/8] eventos de SKU que no estan en params: {fuera}")
        except Exception as e:
            # Un problema de eventos NO debe tirar el plan del dia: se degrada a
            # "sin eventos", que es exactamente el comportamiento previo.
            log.error(f"[4/8] eventos: fallo la carga, se CONTINUA SIN EVENTOS: {e}")
            eventos_por_sku = {}
    else:
        log.info("[4/8] eventos OFF (EVENTOS_ENABLED != 1)")

    forecasts = {}
    n_mto = 0
    for sku in sku_params:
        # MTO (a pedido): sin forecast. Se OMITE del dict (mismo estado que
        # "forecast no disponible", ya manejado aguas abajo). La demanda queda
        # solo OV (se netea aparte) y SS=0 viene de params. -> demanda = OV.
        if getattr(sku_params[sku], "mto", False):
            n_mto += 1
            continue
        _ev = eventos_por_sku.get(sku)
        if _ev:
            log.info(f"[4/8] {sku}: {len(_ev)} regresor(es) de evento "
                     f"({', '.join(e['name'] for e in _ev)}) -> reentrena sin persistir")
        try:
            r = run_sku_pipeline(df=df_sales, sku=sku, canal=None,
                                 forecast_periods=args.horizonte + 4,
                                 fecha_cobertura=fecha_cobertura,
                                 extra_events=_ev)
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

    # ── 6c. Alertas de RECEPCIÓN PENDIENTE (29-07-2026) ──────────────────────
    #
    # SEMÁNTICA DE LAS OF APROBADAS (definida con Germán, 29-07-2026):
    #   · `fecha_lanzamiento_real` = día en que se PRODUCE (turno 07:00-18:00).
    #   · `fecha_entrada_real`     = día en que la producción YA ESTÁ EN EL STOCK y
    #     por tanto disponible para despacho. La producción del día D se ingresa al
    #     cierre de ese día ("terminal report") y aparece en el snapshot del ETL de
    #     las 5 AM del día D+1 = `fecha_entrada_real`.
    #
    # POR QUÉ EL FILTRO DE entradas_fijas ES `fer > hoy_str` Y NO `>=`:
    #   NO CAMBIAR a `>=`. (Se evaluó y descartó explícitamente el 29-07-2026, y se
    #   revalidó el 11-08-2026.)
    #
    #   OJO CON LA JUSTIFICACIÓN: la versión original de este comentario decía que
    #   "una OF con fecha_entrada_real == hoy YA está contabilizada en el stock que
    #   leímos hoy". ESO ES FALSO y se midió: el 11-08-2026 había 11 OF con
    #   recepción hoy y en 9 de ellas el stock NO las reflejaba (7 de recepción nula
    #   + 2 parciales). Nadie debe razonar sobre esa premisa.
    #
    #   Las razones por las que el filtro SÍ se sostiene son otras dos:
    #     a) DOBLE CONTEO. Si la recepción ya ocurrió (total o parcialmente), sumar
    #        la OF cuenta dos veces lo que ya está en el stock -> el modelo cree
    #        tener stock fantasma y produce de menos -> quiebre REAL más adelante.
    #        Es el error caro: subcontar cuesta capacidad, sobrecontar cuesta
    #        servicio. Y en una recepción PARCIAL no se sabe cuánto sumar sin el
    #        balance de inventario.
    #     b) NO INVENTAR STOCK QUE NO SE PUEDE CONFIRMAR. Es la misma postura que
    #        aplica la alerta de abajo: el cálculo no se toca, se informa.
    #
    #   Lo que sí cambió el 11-08-2026: la alerta ahora cubre también la recepción
    #   PARCIAL, que antes quedaba muda (ver _detectar_recepcion_pendiente).
    #
    # EL CASO QUE ESTA ALERTA CUBRE:
    #   Si al cerrar el turno el equipo de calidad no está disponible, el terminal
    #   report queda para el día siguiente y esa producción NO aparece en el snapshot
    #   de las 5 AM. El plan entonces ve menos stock del que físicamente hay y reporta
    #   QUIEBRE en los primeros días del horizonte — un quiebre que probablemente NO
    #   es real. El cálculo NO se toca (no inventamos stock que no podemos confirmar);
    #   sólo se emite una alerta informativa para que el usuario lo interprete.
    #
    # ALCANCE: SÓLO EL ÚLTIMO DÍA HÁBIL (decisión de Germán, 29-07-2026):
    #   La alerta mira únicamente las OF lanzadas el último día hábil anterior. Si al
    #   día D+2 la recepción sigue sin detectarse, el sistema ASUME QUE LA OF NO SE
    #   EJECUTÓ: no se alerta más y no entra en ningún cálculo (el filtro
    #   `fer > hoy_str` ya la excluye de entradas_fijas por tener fecha pasada).
    #   Día HÁBIL y no calendario: un lunes hay que mirar el viernes, o la alerta
    #   nunca se dispararía los lunes.
    #
    # DETECCIÓN (balance de inventario entre dos snapshots):
    #   esperado(hoy) = stock(D) + OF_lanzadas(D) - entregas(D .. hoy-1)
    #   faltante      = esperado - stock_real(hoy)
    #   donde D = último día hábil anterior. Las entregas se acumulan sobre todo el
    #   rango porque entre el lanzamiento y hoy pudo haber despachos (el sábado hay
    #   facturación: ~376 líneas en 60 días).
    #   Se alerta sólo si faltante >= UMBRAL_RECEP (80%) de la OF: los faltantes
    #   parciales suelen ser producción incompleta o sesgo del método, no terminal
    #   report pendiente. Validado el 29-07: con umbral 80% dispara 1 de 16 casos.
    #
    # SESGOS CONOCIDOS del método (por eso la alerta lleva los números crudos):
    #   · `dbo.ventas` filtra Segmento='COMERCIAL' y no excluye bodegas -> las
    #     entregas pueden quedar subestimadas y el faltante verse mayor.
    #   · Las notas de crédito (devoluciones) no se cuentan.
    #
    # PENDIENTE (backlog): leer el estado real de recepción desde SAP en vez de
    # inferirlo. Hoy las OF de este sistema no se sincronizan con SAP.
    UMBRAL_RECEP = 0.80
    try:
        _alertas_recep = _detectar_recepcion_pendiente(
            aprobadas=aprobadas_db, unidades_por_caja=unidades_por_caja,
            hoy=hoy, umbral=UMBRAL_RECEP)
        if _alertas_recep:
            rich.setdefault('alertas', []).extend(_alertas_recep)
            log.warning(f"[6/8] RECEPCION PENDIENTE: {len(_alertas_recep)} SKU con OF "
                        f"lanzada ayer que no se refleja en el stock de hoy "
                        f"-> los quiebres de los primeros dias pueden no ser reales.")
            for a in _alertas_recep:
                log.warning(f"    {a['sku']}: OF {a['of_cj']:.0f} cj ({a['numero_of']}), "
                            f"esperado {a['esperado_cj']:.0f} cj, real {a['real_cj']:.0f} cj, "
                            f"faltan {a['faltante_cj']:.0f} cj")
        else:
            log.info("[6/8] recepción de OF de ayer: sin faltantes relevantes.")
    except Exception as e:
        log.warning(f"[6/8] no se pudo evaluar recepción pendiente: {e}")

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
