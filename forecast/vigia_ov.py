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

DOS VISTAS (se reportan ambas)
  · "plan"     = con OFT propuestas + OF aprobadas. Es lo que muestra el dashboard.
                 Con esta vista se DISPARA la alerta (consistencia con la pantalla).
  · "aprobado" = sólo con OF/OFM ya aprobadas. Dice si la cobertura depende de
                 aprobar una OFT que todavía nadie aprobó.

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
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.info("HANA: %d SKU con pedido abierto.", len(ov))

    entradas_vivas = _entradas_aprobadas_vivas(upc_de)

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

        # Proyección: dos vistas en paralelo.
        stock_plan = None
        stock_aprob = None
        eventos = []
        for f in fechas:
            c = por_fecha[f]
            fc = float(c.get("forecast_u") or 0)
            oft_u = float(c.get("oft_cajas") or 0) * upc
            ent = float((entradas_vivas.get(sku) or {}).get(f, 0.0))
            dem = max(fc, ped_u.get(f, 0.0))          # regla del optimizer

            ini = float(c.get("stock_ini_disp_u") or 0) if stock_plan is None else stock_plan
            stock_plan = ini + oft_u + ent - dem
            base_ap = ini if stock_aprob is None else stock_aprob
            stock_aprob = base_ap + ent - dem          # sin OFT

            if f < v_ini.isoformat() or f > v_fin.isoformat():
                continue                               # fuera de la ventana de alerta
            if stock_plan < 0:
                eventos.append({
                    "fecha": f,
                    "deficit_u": int(round(-stock_plan)),
                    "deficit_cj": round(-stock_plan / upc, 1),
                    "deficit_solo_aprobado_u": int(round(max(0.0, -stock_aprob))),
                    "deficit_solo_aprobado_cj": round(max(0.0, -stock_aprob) / upc, 1),
                    "demanda_u": int(round(dem)),
                    "pedido_u": int(round(ped_u.get(f, 0.0))),
                    "forecast_u": int(round(fc)),
                })

        if eventos:
            # ¿el quiebre lo trae el plan o es nuevo por las OV de hoy?
            ya_en_plan = {
                f for f in por_fecha
                if float(por_fecha[f].get("stock_fin_u") or 0) < 0
                and v_ini.isoformat() <= f <= v_fin.isoformat()
            }
            resultados.append({
                "sku": sku,
                "descripcion": params.get(sku, {}).get("descripcion", ""),
                "linea": params.get(sku, {}).get("linea_preferida", ""),
                "upc": upc,
                "arrastre_ov_vencida_u": int(round(arrastre_u)),
                "eventos": eventos,
                "nuevos": [e for e in eventos if e["fecha"] not in ya_en_plan],
            })

    nuevos = [r for r in resultados if r["nuevos"]]
    return {
        "ok": True,
        "hoy": hoy.isoformat(),
        "ventana": [v_ini.isoformat(), v_fin.isoformat()],
        "plan_id": plan_id,
        "plan_generado": str(plan_ts),
        "n_sku_con_ov": len(ov),
        "total_con_quiebre": len(resultados),
        "total_nuevos": len(nuevos),
        "sku_nuevos": nuevos,
        "sku_todos": resultados,
    }


def _imprimir(rep: dict, todos: bool = False):
    print(f"\n{'='*78}")
    print(f"VIGÍA DE OV — {rep['hoy']} · ventana {rep['ventana'][0]} a {rep['ventana'][1]}")
    print(f"Plan vigente #{rep['plan_id']} (generado {rep['plan_generado']})")
    print(f"HANA: {rep['n_sku_con_ov']} SKU con pedido abierto")
    print(f"{'='*78}")
    print(f"SKU con quiebre en la ventana : {rep['total_con_quiebre']}")
    print(f"  de los cuales NUEVOS (no estaban en el plan): {rep['total_nuevos']}")

    lista = rep["sku_todos"] if todos else rep["sku_nuevos"]
    if not lista:
        print("\nSin quiebres nuevos. Nada que alertar.")
        return
    for r in sorted(lista, key=lambda x: -sum(e["deficit_u"] for e in x["eventos"])):
        marca = "  ⚠ARRASTRE OV VENCIDA" if r["arrastre_ov_vencida_u"] > 0 else ""
        print(f"\n{r['sku']}  {r['descripcion'][:44]}  [{r['linea']}]{marca}")
        for e in (r["nuevos"] if not todos else r["eventos"]):
            extra = ""
            if e["deficit_solo_aprobado_cj"] > e["deficit_cj"]:
                extra = f"   (sólo con lo aprobado: −{e['deficit_solo_aprobado_cj']:,.0f} cj)"
            print(f"    {e['fecha']}  déficit −{e['deficit_cj']:>8,.1f} cj"
                  f"   demanda {e['demanda_u']:>7,} u"
                  f" (pedido {e['pedido_u']:,} / fcst {e['forecast_u']:,}){extra}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=DIAS_HABILES_DEFAULT,
                    help="días hábiles hacia adelante (default 5)")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    ap.add_argument("--todos", action="store_true",
                    help="incluye los quiebres que ya venían en el plan")
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
        _imprimir(rep, todos=args.todos)


if __name__ == "__main__":
    main()
