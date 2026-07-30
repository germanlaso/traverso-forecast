"""
vigia_ov.py — Detección de quiebres nuevos por OV que llegaron después del plan.

PROBLEMA QUE RESUELVE
Las OV se cargan en SAP durante todo el día, pero el plan se genera una vez (6 AM).
Un pedido grande que entra a media mañana no se ve en ninguna pantalla hasta la
corrida siguiente. Caso real (30-07-2026): 334 cj de JUGO PIÑA con entrega el 03-ago
entraron después de las 09:06 y el dashboard mostraba el SKU en verde.

QUÉ HACE
Lee HANA en vivo, reconstruye la proyección de stock con esa demanda actualizada y
detecta qué SKU pasan a QUIEBRE en los próximos N días hábiles. No escribe nada ni
toca el plan vigente: sólo detecta.

CÓMO PROYECTA (mismas reglas que el optimizer y el dashboard)
  · demanda[d] = max(forecast[d], pedidos_u[d])   -- el pedido CONSUME el forecast,
    no se suma (regla confirmada 09-07, optimizer.py:616).
  · Pedidos en CAJAS desde HANA -> se pasan a unidades con u_por_caja.
  · OV sin fecha o vencida -> se arrastra al día 0 (igual que el conector).
  · stock[d] = stock[d-1] + oft[d] + entrada_aprobada[d] - demanda[d]
  · Se parte del stock inicial del plan vigente (viene del parquet, que sólo se
    refresca al correr el plan). LIMITACIÓN CONOCIDA: el vigía detecta cambios en la
    DEMANDA, no en el stock. Un despacho posterior al plan no se ve.
    -> Backlog: lectura de stock en vivo desde SAP (requiere TI).

CRITERIO DE DISPARO (definido 30-07)
El vigía existe para detectar UNA cosa: quiebres que aparecen por OV cargadas DESPUÉS
de que corrió el plan. Los quiebres propios del plan ya se ven en el dashboard y en sus
alertas; re-alertarlos sería ruido. Entonces se exige:

  1. FILTRO — el quiebre NO existía con la demanda original del plan. Si con esa
     demanda ya quebraba, no es cosa del vigía.
  2. DISPARO — las órdenes APROBADAS (OF/OFM) no alcanzan a cubrir. Un OFT es una
     propuesta: nadie se comprometió a producirlo y tiene lead time, así que no
     cuenta como cobertura.
  3. INFORMACIÓN — si el plan ya propuso una OFT que cubriría el hueco, se indica:
       · "APROBAR_OFT" -> alcanza con aprobar la OFT que ya está propuesta.
       · "CRITICO"     -> quiebra incluso contando la OFT: hay que decidir algo
                          (OFM express, mover carga, avisar al cliente).

DÍA 0
No se alerta sobre el día de hoy: a esa altura ya no hay nada que hacer. Pero el
efecto del arrastre SÍ se conserva (deprime el stock inicial y se propaga), así que
los SKU con arrastre de OV vencida se MARCAN en el reporte: una alerta en D+1..D+5
puede venir de una OV que en realidad debía anularse.

USO
    python3 vigia_ov.py                 # 5 días hábiles, salida por consola
    python3 vigia_ov.py --dias 3        # otra ventana
    python3 vigia_ov.py --json          # salida JSON (para el wrapper del cron)
    python3 vigia_ov.py --todos         # lista también los SKU sin quiebre nuevo
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vigia_ov")

DIAS_HABILES_DEFAULT = 5
# Cuántas OV se listan por día antes de resumir. Un día puede tener 20+ OV chicas y
# el correo se vuelve ilegible.
MAX_OV_LISTADAS = 6


def _dias_habiles(desde: date, n: int) -> list[date]:
    """Los n días hábiles siguientes a `desde` (excluye el propio `desde`).

    Lun-Vie. Sábado se excluye del horizonte de alerta aunque haya facturación:
    lo que importa es si hay que reaccionar produciendo, y la planta no produce
    el fin de semana.
    """
    out, d = [], desde
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def _detalle_por_ov(conn, hoy: date, skus: set[str], corte=None) -> dict:
    """{sku: {fecha_iso: [{doc, bd, cajas}]}} con el detalle por nota de venta.

    Las funciones públicas de hana_pedidos AGREGAN por fecha y descartan el documento.
    Para decir en la alerta CUÁL OV y de QUÉ cliente se usa `_leer_fuente` con
    incluir_cliente=True (opt-in; el módulo sigue sin PII para todo lo demás).
    Es privada: si cambia su forma, esto degrada a alerta sin detalle de OV (no falla).

    Mismo tratamiento de fechas que el conector: fecha nula o vencida -> día 0.

    `corte` = timestamp en que corrió el plan. Cada OV se marca `nueva=True` si se
    creó DESPUÉS (Fecha NV + DocTime, que es HHMM). Eso permite señalar exactamente
    qué pedidos el plan no vio, en vez de listar todos los del día.

    LIMITACIÓN: si una OV vieja se MODIFICÓ hoy (cambio de cantidad), su fecha de
    creación no cambia y se clasifica como preexistente. El SP no expone UpdateDate.
    """
    import hana_pedidos as hp
    out: dict[str, dict[str, list]] = {}
    for schema, etiqueta in hp.FUENTES:
        for r in hp._leer_fuente(conn, schema, etiqueta,
                                 incluir_cliente=True, incluir_creacion=True):
            sku = str(r.get("sku") or "")
            if not sku or (skus and sku not in skus):
                continue
            cj = float(r.get("cantidad") or 0)
            if cj <= 0:
                continue
            f = r.get("fecha")
            vencida = f is None or f < hoy
            fe = hoy if vencida else f
            k = fe.isoformat() if hasattr(fe, "isoformat") else str(fe)[:10]
            out.setdefault(sku, {}).setdefault(k, []).append({
                "doc": str(r.get("doc") or ""),
                "bd": etiqueta,
                "cajas": round(cj, 1),
                "vencida": bool(vencida),
                "cliente": str(r.get("nom_cliente") or "").strip(),
                "cod_cliente": str(r.get("cod_cliente") or "").strip(),
                "creado": r.get("creado"),
                "nueva": bool(corte and r.get("creado") and r["creado"] > corte),
            })
    return out


def _plan_vigente():
    from db_mrp import get_session
    from sqlalchemy import text
    with get_session() as s:
        row = s.execute(text(
            "SELECT id, created_at, snapshot FROM mrp_planes WHERE vigente LIMIT 1"
        )).fetchone()
    if row is None:
        raise RuntimeError("No hay plan vigente.")
    return row[0], row[1], (row[2] or {})


def _entradas_aprobadas_vivas(upc_de: dict) -> dict:
    """{sku: {fecha_iso: unidades}} de las OF/OFM aprobadas vigentes AHORA.

    Se leen en vivo (no del snapshot) porque entre el plan y este momento se pueden
    haber aprobado OFM — justo el caso de la producción express.
    """
    from db_mrp import listar_aprobadas_db
    out: dict[str, dict[str, float]] = {}
    for ap in listar_aprobadas_db():
        sku = str(ap.get("sku", ""))
        fer = str(ap.get("fecha_entrada_real") or "")[:10]
        if not sku or not fer:
            continue
        u = ap.get("cantidad_real_u")
        if u is None:
            u = float(ap.get("cantidad_real_cj") or 0) * (upc_de.get(sku, 1) or 1)
        out.setdefault(sku, {})[fer] = out.setdefault(sku, {}).get(fer, 0.0) + float(u or 0)
    return out


def evaluar(n_dias: int = DIAS_HABILES_DEFAULT, hoy: date | None = None) -> dict:
    """Devuelve el reporte de quiebres detectados. No escribe nada."""
    import hana_pedidos as hp
    from db_mrp import get_all_sku_params

    hoy = hoy or date.today()
    ventana = _dias_habiles(hoy, n_dias)
    v_ini, v_fin = ventana[0], ventana[-1]

    plan_id, plan_ts, snap = _plan_vigente()
    detalle = snap.get("detalle_diario") or {}
    if not detalle:
        raise RuntimeError(f"El plan {plan_id} no tiene detalle_diario.")

    params = {str(p["sku"]): p for p in get_all_sku_params()}
    upc_de = {s: int(p.get("u_por_caja", 1) or 1) or 1 for s, p in params.items()}

    # ── OV en vivo ────────────────────────────────────────────────────────────
    conn = hp.conectar(os.environ.get("HANA_PWD"))
    try:
        ov = hp.obtener_pedidos_abiertos(conn, hoy=hoy, skus_validos=set(params))
        try:
            # Corte = momento en que corrió el plan, en hora LOCAL (DocTime de HANA es
            # hora local). created_at viene tz-aware en UTC -> astimezone() usa el TZ
            # del container, que está en hora Chile.
            corte = plan_ts
            try:
                corte = plan_ts.astimezone().replace(tzinfo=None)
            except Exception:
                pass
            ov_det = _detalle_por_ov(conn, hoy, set(params), corte=corte)
        except Exception as e:
            logger.warning("Sin detalle por OV (%s): la alerta va sin número de NV.", e)
            ov_det = {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.info("HANA: %d SKU con pedido abierto.", len(ov))

    entradas_vivas = _entradas_aprobadas_vivas(upc_de)

    # Calendario de granel: si un SKU acoplado quiebra en una semana de OTRO granel,
    # el plan NO puede proponer producción — y eso cambia la acción (la OFM manual
    # está exenta de la campaña). Sin esto la alerta dice "crítico" sin explicar por qué.
    cal_granel = {}
    try:
        from db_mrp import get_campana_calendario
        for row in get_campana_calendario(recurso="GRANEL_SALSAS"):
            sem = row["semana"]
            cal_granel[sem.isoformat() if hasattr(sem, "isoformat") else str(sem)] = (
                (row.get("modo") or "").strip().lower())
    except Exception as e:
        logger.warning("Sin calendario de granel (%s): la alerta va sin ese contexto.", e)

    resultados = []
    for sku, por_fecha in detalle.items():
        fechas = sorted(por_fecha.keys())
        if not fechas:
            continue
        upc = upc_de.get(sku, 1)

        # Pedidos en vivo -> unidades por día, con arrastre al día 0.
        ped_u: dict[str, float] = {}
        arrastre_u = 0.0
        for f, cajas in (ov.get(sku) or {}).items():
            fe = hoy if (f is None or f < hoy) else f
            if f is not None and f < hoy:
                arrastre_u += float(cajas) * upc
            k = fe.isoformat() if hasattr(fe, "isoformat") else str(fe)[:10]
            if k > fechas[-1]:
                continue                      # fuera del horizonte del plan
            ped_u[k] = ped_u.get(k, 0.0) + float(cajas) * upc

        # Tres proyecciones en paralelo:
        #   aprob_live -> sólo aprobadas + OV en vivo   (DISPARA la alerta)
        #   plan_live  -> con OFT + OV en vivo          (clasifica: CRITICO o no)
        #   aprob_plan -> sólo aprobadas + demanda ORIGINAL del plan
        #                 (si acá ya quebraba, el quiebre no lo trajeron las OV de hoy)
        s_aprob_live = s_plan_live = s_aprob_plan = None
        oft_acum = 0.0
        dias = []          # una entrada por día del horizonte del plan
        incrementos = []   # días donde la demanda SUBIÓ respecto al plan
        for f in fechas:
            c = por_fecha[f]
            fc = float(c.get("forecast_u") or 0)
            oft_u = float(c.get("oft_cajas") or 0) * upc
            ent = float((entradas_vivas.get(sku) or {}).get(f, 0.0))
            dem_live = max(fc, ped_u.get(f, 0.0))          # regla del optimizer
            dem_plan = float(c.get("demanda_corr_u") or 0)  # ya es max(fcst, ped) del plan

            ini_u = float(c.get("stock_ini_disp_u") or 0)
            b_al = ini_u if s_aprob_live is None else s_aprob_live
            b_pl = ini_u if s_plan_live is None else s_plan_live
            b_ap = ini_u if s_aprob_plan is None else s_aprob_plan
            s_aprob_live = b_al + ent - dem_live
            s_plan_live = b_pl + oft_u + ent - dem_live
            s_aprob_plan = b_ap + ent - dem_plan
            oft_acum += oft_u

            if dem_live > dem_plan + 0.5:
                incrementos.append({
                    "fecha": f,
                    "extra_cj": round((dem_live - dem_plan) / upc, 1),
                    "ovs": sorted((ov_det.get(sku) or {}).get(f, []),
                                  key=lambda x: (not x.get("nueva"), -x["cajas"])),
                })

            dias.append({
                "fecha": f,
                "quiebra": s_aprob_live < 0,
                "deficit_cj": round(max(0.0, -s_aprob_live) / upc, 1),
                "con_oft_cj": round(s_plan_live / upc, 1),
                "oft_acum_cj": round(oft_acum / upc, 1),
                "critico": s_plan_live < 0,
                "por_ov_nueva": s_aprob_plan >= 0,
                "en_ventana": v_ini.isoformat() <= f <= v_fin.isoformat(),
            })

        # TRAMOS: días consecutivos en quiebre se colapsan en un solo evento. Un hueco
        # que dura 4 días es UN problema, no cuatro alertas.
        tramos, actual = [], None
        for d in dias:
            elegible = d["quiebra"] and d["en_ventana"] and d["por_ov_nueva"]
            if elegible:
                if actual is None:
                    actual = {"desde": d["fecha"], "hasta": d["fecha"], "dias": 1,
                              "deficit_max_cj": d["deficit_cj"],
                              "con_oft_cj": d["con_oft_cj"],
                              "oft_acum_cj": d["oft_acum_cj"],
                              "clase": "CRITICO" if d["critico"] else "APROBAR_OFT"}
                else:
                    actual["hasta"] = d["fecha"]
                    actual["dias"] += 1
                    actual["deficit_max_cj"] = max(actual["deficit_max_cj"], d["deficit_cj"])
                    actual["con_oft_cj"] = min(actual["con_oft_cj"], d["con_oft_cj"])
                    actual["oft_acum_cj"] = d["oft_acum_cj"]
                    if d["critico"]:
                        actual["clase"] = "CRITICO"
            elif actual is not None:
                tramos.append(actual); actual = None
        if actual is not None:
            tramos.append(actual)

        # ¿el tramo cae en una semana cuyo granel NO es el de este SKU?
        grupo = (params.get(sku, {}).get("granel_grupo") or "").strip().lower()
        for t in tramos:
            t["bloqueo_campana"] = ""
            if not grupo or not cal_granel:
                continue
            d0 = date.fromisoformat(t["desde"])
            lun = (d0 - timedelta(days=d0.weekday())).isoformat()
            modo = cal_granel.get(lun, "")
            if modo and modo != grupo:
                t["bloqueo_campana"] = (
                    f"la semana del {lun} es de granel {modo} y este SKU es {grupo}: "
                    f"el plan no puede proponer producción. Una OFM manual sí "
                    f"(está exenta de la campaña).")

        if tramos:
            resultados.append({
                "sku": sku,
                "descripcion": params.get(sku, {}).get("descripcion", ""),
                "linea": params.get(sku, {}).get("linea_preferida", ""),
                "upc": upc,
                "arrastre_ov_vencida_u": int(round(arrastre_u)),
                "tramos": tramos,
                # OV que causan el aumento de demanda respecto al plan: son las que
                # gatillan la alerta, aunque entreguen ANTES del día del quiebre.
                "incrementos": incrementos,
                "criticos": [t for t in tramos if t["clase"] == "CRITICO"],
            })

    criticos = [r for r in resultados if r["criticos"]]
    return {
        "ok": True,
        "hoy": hoy.isoformat(),
        "ventana": [v_ini.isoformat(), v_fin.isoformat()],
        "plan_id": plan_id,
        "plan_generado": str(plan_ts),
        "criterio": ("quiebres causados por OV posteriores al plan, evaluados sólo "
                     "con órdenes APROBADAS (los OFT no cuentan como cobertura)"),
        "n_sku_con_ov": len(ov),
        "total_alertas": len(resultados),
        "total_criticos": len(criticos),
        "sku_alerta": resultados,
        "sku_criticos": criticos,
    }


def _imprimir(rep: dict, todos: bool = False):
    print(f"\n{'='*88}")
    print(f"VIGÍA DE OV — {rep['hoy']} · ventana {rep['ventana'][0]} a {rep['ventana'][1]}")
    print(f"Plan vigente #{rep['plan_id']} (generado {rep['plan_generado']})")
    print(f"HANA: {rep['n_sku_con_ov']} SKU con pedido abierto")
    print(f"{'='*88}")
    print(f"ALERTAS (quiebre nuevo por OV posterior al plan) : {rep['total_alertas']}")
    print(f"  · de los cuales CRÍTICOS (la OFT no alcanza)   : {rep['total_criticos']}")

    if not rep["sku_alerta"]:
        print("\nSin alertas: ninguna OV nueva genera quiebre en la ventana.")
        return

    for r in sorted(rep["sku_alerta"],
                    key=lambda x: -max(t["deficit_max_cj"] for t in x["tramos"])):
        marca = "   ⚠ARRASTRE OV VENCIDA" if r["arrastre_ov_vencida_u"] > 0 else ""
        print(f"\n{r['sku']}  {r['descripcion'][:42]}  [{r['linea']}]{marca}")

        for t in r["tramos"]:
            rango = (t["desde"] if t["dias"] == 1
                     else f"{t['desde']} a {t['hasta']} ({t['dias']} días)")
            if t["clase"] == "CRITICO":
                etq = "🔴 CRÍTICO"
                det = (f"ni con las OFT propuestas alcanza "
                       f"({t['oft_acum_cj']:,.0f} cj): quedaría {t['con_oft_cj']:,.0f} cj")
            else:
                etq = "🟡 APROBAR OFT"
                det = (f"aprobando las OFT del plan ({t['oft_acum_cj']:,.0f} cj acum.) "
                       f"quedaría {t['con_oft_cj']:,.0f} cj")
            print(f"    {rango}  {etq}  déficit máx −{t['deficit_max_cj']:,.0f} cj")
            print(f"       {det}")
            if t.get("bloqueo_campana"):
                print(f"       ⚑ CAMPAÑA: {t['bloqueo_campana']}")

        # Aumento de demanda respecto al plan. IMPORTANTE: el snapshot del plan guarda
        # el agregado diario, NO el detalle por OV, así que no se puede saber cuál OV
        # específica es nueva. Se muestra el AUMENTO (que sí es exacto) y las OV con
        # entrega ese día como referencia para buscarlas en SAP.
        if r["incrementos"]:
            for inc in r["incrementos"]:
                print(f"       Aumento de demanda el {inc['fecha']}: "
                      f"+{inc['extra_cj']:,.0f} cj sobre lo que veía el plan")
                nuevas = [o for o in inc["ovs"] if o.get("nueva")]
                if nuevas:
                    tot = sum(o["cajas"] for o in nuevas)
                    print(f"         OV cargadas DESPUÉS del plan ({tot:,.0f} cj):")
                    for o in nuevas[:MAX_OV_LISTADAS]:
                        cli = f" — {o['cliente'][:38]}" if o.get("cliente") else ""
                        v = " (VENCIDA→hoy)" if o["vencida"] else ""
                        h = o["creado"].strftime(" %H:%M") if o.get("creado") else ""
                        print(f"           · OV {o['doc']}{h} [{o['bd']}] "
                              f"{o['cajas']:,.0f} cj{cli}{v}")
                    if len(nuevas) > MAX_OV_LISTADAS:
                        r2 = sum(o["cajas"] for o in nuevas[MAX_OV_LISTADAS:])
                        print(f"           · … y {len(nuevas)-MAX_OV_LISTADAS} más "
                              f"({r2:,.0f} cj)")
                else:
                    print(f"         (ninguna OV de ese día se creó después del plan: "
                          f"puede ser una OV modificada)")
        else:
            print(f"       (sin aumento de demanda en la ventana: viene del arrastre)")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=DIAS_HABILES_DEFAULT,
                    help="días hábiles hacia adelante (default 5)")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    args = ap.parse_args()
    try:
        rep = evaluar(n_dias=args.dias)
    except Exception as e:
        logger.error("Evaluación FALLÓ: %s", e)
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, default=str))
    else:
        _imprimir(rep)


if __name__ == "__main__":
    main()
