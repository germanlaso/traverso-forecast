"""
optimizer.py — Optimizador OR-Tools CP-SAT para Traverso S.A. v1.1
Usa mrp_sku_lineas para múltiples líneas por SKU y t_cambio_hrs por SKU×Línea.
"""
import math, logging
from datetime import date, timedelta
logger = logging.getLogger(__name__)

W_DEFICIT=100_000; W_EXCESO=50_000; W_URGENTE=10_000; W_SLACK=100; W_ALT=50
MAX_TIME=30; N_WORKERS=4


def optimizar_plan(ordenes_mrp, sku_params, lineas, forecasts,
                   stocks_actuales, entradas_fijas, horizonte_semanas=13):
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        logger.error("OR-Tools no instalado")
        return ordenes_mrp, {"status":"ERROR","optimizado":False}

    hoy  = date.today()
    sems = _semanas_horizonte(hoy, horizonte_semanas)
    lins = {c:l for c,l in lineas.items() if _cap_dia_u(l) > 0}
    skus = [k for k,p in sku_params.items() if getattr(p,'activo',True) and k in forecasts]

    if not skus or not lins:
        return ordenes_mrp, {"status":"SIN_DATOS","optimizado":False}

    # Solo optimizar SKUs de tipo PRODUCCION — importación/maquila no usan líneas
    skus_prod = [k for k in skus
                 if getattr(sku_params[k], 'tipo', 'PRODUCCION').upper() == 'PRODUCCION']
    skus_imp  = [k for k in skus if k not in skus_prod]
    logger.info(f"[Optimizer] SKUs produccion: {len(skus_prod)} | importacion/maquila: {len(skus_imp)}")

    fc   = _forecast_map(forecasts, skus_prod, sems, sku_params)
    ap   = _aprobadas_map(entradas_fijas, skus_prod, sku_params)
    lok  = _lineas_por_sku(sku_params, lins, skus_prod)
    urg  = _urgencia(ordenes_mrp, hoy)
    skus = skus_prod  # el resto del modelo solo ve SKUs de produccion

    model = cp_model.CpModel()
    BIG   = 100_000_000

    prod = {}; asig = {}; stk = {}; def_ = {}; exc_ = {}

    for k in skus:
        p    = sku_params[k]
        capb = getattr(p,'cap_bodega',999_999)
        lk   = [r['linea'] for r in lok.get(k,[])]

        for s in sems:
            for r in lok.get(k,[]):
                l    = r['linea']
                lin  = lins[l]
                capd = int(_cap_dia_u(lin) * getattr(p,'pct_dia_max',1.0))
                # Descontar t_cambio por cambio de SKU (en unidades equivalentes)
                t_cambio_u = int(r['t_cambio_hrs'] * lin.velocidad_u_hr)
                capd_eff   = max(0, capd - t_cambio_u)
                v = model.NewIntVar(0, capd_eff, f"p_{s}_{k}_{l}")
                b = model.NewBoolVar(f"a_{s}_{k}_{l}")
                prod[(s,k,l)] = v
                asig[(s,k,l)] = b
                model.Add(v <= capd_eff * b)
                bmin = getattr(p,'batch_minimo',0)
                if bmin > 0:
                    model.Add(v >= bmin * b)

            if lk:
                model.Add(sum(asig[(s,k,l)] for l in lk if (s,k,l) in asig) <= 1)

            bm = getattr(p,'multiplo_batch',1) or 1
            if bm > 1 and lk:
                pvars = [prod[(s,k,l)] for l in lk if (s,k,l) in prod]
                if pvars:
                    nb = model.NewIntVar(0, BIG//bm, f"nb_{s}_{k}")
                    model.Add(sum(pvars) == bm * nb)

            stk[(s,k)]  = model.NewIntVar(-BIG, capb*2, f"stk_{s}_{k}")
            def_[(s,k)] = model.NewIntVar(0, BIG, f"def_{s}_{k}")
            exc_[(s,k)] = model.NewIntVar(0, BIG, f"exc_{s}_{k}")

    # Balance de stock
    for i,s in enumerate(sems):
        for k in skus:
            p    = sku_params[k]
            upj  = getattr(p,'unidades_por_caja',1) or 1
            lk   = [r['linea'] for r in lok.get(k,[])]
            dem  = int(fc.get(k,{}).get(s,0))
            apu  = int(ap.get(k,{}).get(s,0))
            ss_u = int((dem/7)*getattr(p,'stock_seguridad_dias',0)) if dem>0 else 0
            capb = getattr(p,'cap_bodega',999_999)
            pvars= [prod[(s,k,l)] for l in lk if (s,k,l) in prod]
            ptot = sum(pvars) if pvars else model.NewConstant(0)
            sant = int(stocks_actuales.get(k,0)*upj) if i==0 else stk[(sems[i-1],k)]
            model.Add(stk[(s,k)] == sant + ptot + apu - dem)
            model.AddMaxEquality(def_[(s,k)], [
                model.NewConstant(0), model.NewConstant(ss_u) - stk[(s,k)]])
            model.AddMaxEquality(exc_[(s,k)], [
                model.NewConstant(0), stk[(s,k)] - model.NewConstant(capb)])

    # Capacidad semanal por línea
    slack_ = {}
    for l,lin in lins.items():
        caps = int(_cap_semana_u(lin))
        for s in sems:
            slk_k = [k for k in skus if (s,k,l) in prod]
            if not slk_k: continue
            pl = [prod[(s,k,l)] for k in slk_k]
            model.Add(sum(pl) <= caps)
            sl = model.NewIntVar(0, caps, f"sl_{l}_{s}")
            model.Add(sl == caps - sum(pl))
            slack_[(l,s)] = sl

    # Función objetivo
    obj = []
    for s in sems:
        for k in skus:
            obj.append(W_DEFICIT * def_[(s,k)])
            obj.append(W_EXCESO  * exc_[(s,k)])
            nivel = urg.get((k,s),0)
            if nivel > 0:
                lk = [r['linea'] for r in lok.get(k,[])]
                pv = [prod[(s,k,l)] for l in lk if (s,k,l) in prod]
                if pv:
                    np_ = model.NewBoolVar(f"nop_{s}_{k}")
                    model.Add(sum(pv)==0).OnlyEnforceIf(np_)
                    model.Add(sum(pv)>=1).OnlyEnforceIf(np_.Not())
                    obj.append(W_URGENTE * nivel * np_)
            # Penalizar línea alternativa
            for r in lok.get(k,[]):
                if not r['preferida'] and (s,k,r['linea']) in asig:
                    obj.append(W_ALT * asig[(s,k,r['linea'])])

    for (l,s),sl in slack_.items():
        caps = int(_cap_semana_u(lins[l]))
        umb  = int(caps*0.10)
        slk_k = [k for k in skus if (s,k,l) in prod]
        if not slk_k: continue
        hp   = model.NewBoolVar(f"hp_{l}_{s}")
        pl_t = sum(prod[(s,k,l)] for k in slk_k)
        model.Add(pl_t>=1).OnlyEnforceIf(hp)
        model.Add(pl_t==0).OnlyEnforceIf(hp.Not())
        slx  = model.NewIntVar(0, caps, f"slx_{l}_{s}")
        model.AddMaxEquality(slx,[model.NewConstant(0), sl - model.NewConstant(umb)])
        slp  = model.NewIntVar(0, caps, f"slp_{l}_{s}")
        model.Add(slp==slx).OnlyEnforceIf(hp)
        model.Add(slp==0).OnlyEnforceIf(hp.Not())
        obj.append(W_SLACK * slp)

    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_TIME
    solver.parameters.num_workers         = N_WORKERS
    solver.parameters.log_search_progress = False
    sc = solver.Solve(model)
    sn = solver.StatusName(sc)
    logger.info(f"[Optimizer] {sn} | {solver.WallTime():.1f}s | obj={solver.ObjectiveValue():.0f}")

    if sc not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning(f"[Optimizer] {sn} — fallback MRP")
        return ordenes_mrp, {"status":sn,"optimizado":False,
                             "tiempo_ms":int(solver.WallTime()*1000)}

    ordenes_opt = _extraer(solver, ordenes_mrp, prod, asig, stk,
                           sku_params, lins, skus, sems, fc, ap, lok, hoy)
    uso  = _uso_lineas(solver, prod, lins, skus, sems)
    ss_a = _bajo_ss(ordenes_mrp, sku_params, fc)
    ss_d = _bajo_ss(ordenes_opt, sku_params, fc)

    return ordenes_opt, {
        "status":sn,"optimizado":True,
        "tiempo_ms":int(solver.WallTime()*1000),
        "objetivo":solver.ObjectiveValue(),
        "semanas_bajo_ss_antes":ss_a,
        "semanas_bajo_ss_despues":ss_d,
        "uso_promedio_lineas_pct":uso,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _semanas_horizonte(hoy, n):
    dow   = hoy.weekday()
    inicio = hoy - timedelta(days=(dow+1)%7)
    if inicio < hoy: inicio += timedelta(weeks=1)
    return [(inicio + timedelta(weeks=i)).isoformat() for i in range(n)]

def _cap_dia_u(lin):
    return (getattr(lin,'turnos_dia',1) *
            getattr(lin,'horas_turno',8) *
            getattr(lin,'velocidad_u_hr',0))

def _cap_semana_u(lin):
    return _cap_dia_u(lin) * getattr(lin,'dias_semana',5)

def _forecast_map(forecasts, skus, sems, sku_params):
    res = {}
    for k in skus:
        upj = getattr(sku_params[k],'unidades_por_caja',1) or 1
        res[k] = {}
        for f in forecasts.get(k,[]):
            ds = str(f.get('ds',''))[:10]
            if ds in sems:
                res[k][ds] = max(0.0, float(f.get('yhat',0))) * upj
    return res

def _aprobadas_map(entradas_fijas, skus, sku_params):
    try:
        from mrp import _fecha_a_domingo as _fad
    except Exception:
        def _fad(f):
            d = date.fromisoformat(str(f)[:10])
            return (d - timedelta(days=(d.weekday()+1)%7)).isoformat()
    res = {k:{} for k in skus}
    for k in skus:
        upj = getattr(sku_params[k],'unidades_por_caja',1) or 1
        for ef in entradas_fijas.get(k,[]):
            if not ef.get('aprobada'): continue
            sem = _fad(ef['fecha_entrada'])
            u   = float(ef.get('cantidad_cajas',0)) * upj
            res[k][sem] = res[k].get(sem,0.0) + u
    return res

def _lineas_por_sku(sku_params, lins, skus):
    """
    Retorna {sku → [{linea, t_cambio_hrs, preferida}]}.
    Lee mrp_sku_lineas de PostgreSQL. Si no hay datos, usa linea_preferida del SKU.
    """
    db_map = {}
    try:
        from db_mrp import get_all_sku_lineas
        for row in get_all_sku_lineas():
            if row['linea'] in lins:
                db_map.setdefault(row['sku'], []).append(row)
    except Exception as e:
        logger.warning(f"[Optimizer] No se pudo leer mrp_sku_lineas: {e}")

    res = {}
    for k in skus:
        p    = sku_params[k]
        pref = getattr(p,'linea_preferida','')
        rows = db_map.get(k)
        if rows:
            res[k] = rows
        elif pref and pref in lins:
            res[k] = [{'linea':pref,'t_cambio_hrs':getattr(p,'t_cambio_hrs',0),'preferida':True}]
        elif lins:
            first = next(iter(lins))
            res[k] = [{'linea':first,'t_cambio_hrs':0,'preferida':True}]
        else:
            res[k] = []
    return res

def _urgencia(ordenes_mrp, hoy):
    res = {}
    for o in ordenes_mrp:
        k,s,fem = o.get('sku',''),o.get('semana_necesidad',''),o.get('semana_emision','')
        if not k or not s or not fem: continue
        try:
            fd = date.fromisoformat(fem[:10])
            nivel = 3 if fd<=hoy else (2 if fd<=hoy+timedelta(days=7) else 1)
        except Exception:
            nivel = 0
        res[(k,s)] = nivel
    return res

def _extraer(solver, ordenes_mrp, prod, asig, stk,
             sku_params, lins, skus, sems, fc, ap, lok, hoy):
    resultado = [
        {**o,'optimizado':False,'motivo_optimizacion':'OF aprobada — fija'}
        for o in ordenes_mrp if o.get('aprobada')
    ]
    # Incluir órdenes de importación/maquila del MRP sin cambios
    skus_no_prod = [k for k in sku_params
                    if getattr(sku_params[k],'tipo','PRODUCCION').upper() != 'PRODUCCION']
    for o in ordenes_mrp:
        if not o.get('aprobada') and o.get('sku') in skus_no_prod:
            resultado.append({**o,'optimizado':False,
                              'motivo_optimizacion':'Importacion/Maquila — sin optimizar'})
    for s in sems:
        for k in skus:
            p    = sku_params[k]
            upj  = getattr(p,'unidades_por_caja',1) or 1
            lk   = [r['linea'] for r in lok.get(k,[])]
            ptot = sum(solver.Value(prod[(s,k,l)]) for l in lk if (s,k,l) in prod)
            if ptot <= 0: continue
            lasig = next((l for l in lk if (s,k,l) in asig
                          and solver.Value(asig[(s,k,l)])==1), lk[0] if lk else None)
            pcj   = math.ceil(ptot/upj)
            sfin  = solver.Value(stk[(s,k)]) if (s,k) in stk else 0
            sfcj  = round(sfin/upj,1)
            yhat  = fc.get(k,{}).get(s,0)
            yhcj  = round(yhat/upj,1)
            sscj  = round((yhcj/7)*getattr(p,'stock_seguridad_dias',0),1)
            apu   = ap.get(k,{}).get(s,0)
            sinicj= round((sfin - ptot - int(apu) + int(yhat))/upj,1)
            lt    = round(getattr(p,'lead_time_semanas',1)*7)
            fem   = date.fromisoformat(s) - timedelta(days=lt)
            alerta= (f"URGENTE: debio emitirse hace {(hoy-fem).days} dias"
                     if fem <= hoy else None)
            # Línea preferida?
            pref_rows = [r for r in lok.get(k,[]) if r['preferida']]
            pref_l    = pref_rows[0]['linea'] if pref_rows else None
            es_pref   = (lasig == pref_l)
            # Uso de la línea
            caps   = int(_cap_semana_u(lins[lasig])) if lasig and lasig in lins else 1
            pl_tot = sum(solver.Value(prod[(s,kk,lasig)])
                         for kk in skus if (s,kk,lasig) in prod) if lasig else 0
            uso    = round(pl_tot/caps*100,1) if caps>0 else 0
            # t_cambio de esta asignación
            t_row  = next((r for r in lok.get(k,[]) if r['linea']==lasig), {})
            t_camb = t_row.get('t_cambio_hrs',0)

            resultado.append({
                'sku':k,'descripcion':getattr(p,'descripcion',''),
                'tipo':getattr(p,'tipo','PRODUCCION'),
                'semana_necesidad':s,'semana_emision':fem.isoformat(),
                'cantidad_cajas':int(pcj),'cantidad_unidades':int(ptot),
                'linea':lasig,'es_linea_preferida':es_pref,
                'uso_linea_pct':uso,'t_cambio_hrs':t_camb,
                'motivo':f"FC:{yhcj:.0f} SS:{sscj:.0f} Stock:{max(0,sinicj):.0f}",
                'motivo_optimizacion':(f"OR-Tools: {pcj} cj en {lasig} "
                                       f"({'pref' if es_pref else 'alt'}) "
                                       f"uso {uso}% t_cambio {t_camb}h"),
                'alerta':alerta,'tiene_alerta':bool(alerta),
                'stock_inicial_cajas':float(max(0,sinicj)),
                'stock_final_cajas':float(max(0,sfcj)),
                'forecast_cajas':float(yhcj),'ss_cajas':float(sscj),
                'aprobada':False,'optimizado':True,'numero_of':None,
            })
    resultado.sort(key=lambda x:(x.get('semana_emision',''),x.get('sku','')))
    return resultado

def _bajo_ss(ordenes, sku_params, fc):
    count = 0
    for o in ordenes:
        if o.get('aprobada'): continue
        k,s = o.get('sku',''),o.get('semana_necesidad','')
        p   = sku_params.get(k)
        if not p: continue
        upj = getattr(p,'unidades_por_caja',1) or 1
        sf  = o.get('stock_final_cajas',0)
        yh  = fc.get(k,{}).get(s,0)/upj
        ss  = (yh/7)*getattr(p,'stock_seguridad_dias',0)
        if sf < ss: count += 1
    return count

def _uso_lineas(solver, prod, lins, skus, sems):
    usos = []
    for l,lin in lins.items():
        cap = _cap_semana_u(lin)
        if cap <= 0: continue
        for s in sems:
            tot = sum(solver.Value(prod[(s,k,l)]) for k in skus if (s,k,l) in prod)
            if tot > 0: usos.append(tot/cap*100)
    return round(sum(usos)/len(usos),1) if usos else 0.0
