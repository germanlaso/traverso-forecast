"""
pasada_d.py — PASADA D: eficiencia de línea (13-11-2026)

Se ejecuta DESPUÉS de la Pasada C (optimizer.optimizar_plan, flag N2_PASADA_D=1) y
re-optimiza cada línea-semana del plan de C con un modelo CP-SAT chico:

  · compacta la producción en menos días (los días liberados, hacia el final de la semana),
  · agrupa por jerarquía de cambio (formato > empaque > granel > etiqueta), también entre días,
  · ordena dentro del día (claros -> oscuros, ajíes al final),
  · llena los días abiertos hasta la meta de ocupación agrandando órdenes (tope +50 %),
    prefiriendo SKU de baja cobertura y los que absorben una OFT de la semana siguiente.

GARANTÍAS (barreras sobre Δ = producción acumulada D − C, por SKU y día):
  · Q*: no agrega quiebres ni los profundiza   · S*: no crea días bajo SS ni los profundiza
  · no excede la capacidad con la regla de setup de C (la ocupación visible queda <= 100 %)
  · mantiene campañas (no agrega SKU a una línea-semana) y las OF aprobadas
  · CONTROL FINAL: si D tuviera más quiebres o más días bajo SS que C, se descarta y queda C.
Hoy queda FIJO: D trabaja desde el día siguiente hasta el fin del horizonte (semana en curso
con sus días restantes; semanas siguientes completas).

Supuestos PROVISIONALES (a reemplazar con los datos de Producción): tiempos de cambio por
nivel, ranking de color, granel derivado de la descripción, grupo de etiqueta, contaminante = ají.
Modifica `resultado` EN SU LUGAR (cron_plan persiste ese mismo objeto) y solo al final.
"""
from __future__ import annotations

import copy
import itertools
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import date, timedelta

from ortools.sat.python import cp_model

from calendario import horas_linea_dia

logger = logging.getLogger(__name__)

_e = os.environ.get
# ─── Parámetros (entorno) ────────────────────────────────────────────────────
T_CAMBIO_H = json.loads(_e("N2_D_T_CAMBIO_H", "") or "{}") or {
    "formato": 2.0, "empaque": 1.0, "granel": 0.5, "etiqueta": 0.25}     # manda el mayor
T_LIMPIEZA_OSCURO_CLARO_H = float(_e("N2_D_T_LIMPIEZA_OC_H", "0.5"))
T_LIMPIEZA_AJI_H = float(_e("N2_D_T_LIMPIEZA_AJI_H", "1.0"))
META_OCUP = float(_e("N2_D_META_OCUP", "0.95"))
TOPE_CRECIMIENTO = float(_e("N2_D_TOPE_CRECIMIENTO", "1.5"))
N_MAX_SKU_DIA = int(_e("N2_D_N_MAX_SKU_DIA", "4"))
TL_SEG = float(_e("N2_D_TL_SEG", "20"))
WORKERS = int(_e("N2_D_WORKERS", "8"))
W_DIA = 1000            # abrir un día (más 50 por posición en la semana: cerrar el final cuesta menos)
W_DIA_POS = 50
W_VIOL = 300            # transición contra regla de orden
W_ARR_SKU = int(_e("N2_D_W_ARR_SKU", "30"))
W_ARR_EMPAQUE = int(_e("N2_D_W_ARR_EMPAQUE", "80"))
W_ARR_GRANEL = int(_e("N2_D_W_ARR_GRANEL", "30"))
W_FALTANTE = 10         # por unidad de tiempo (ESC) bajo la meta en un día abierto
K_COBERTURA = float(_e("N2_D_K_COBERTURA", "2.0"))
F_ABSORBE = float(_e("N2_D_F_ABSORBE", "0.3"))
TOPE_W_CRECER = 20
RANK = [  # (patrón en granel/descripción, rango): primero que calce. PROVISIONAL.
    (r"INCOLORO", 1), (r"VINAGRE.*BLANCO|VINAGRE_BLANCO|BALSAMICO BLANCO", 2),
    (r"MANZANA|VINAGRE_MANZANA", 3), (r"ROSADO|VINAGRE_ROSADO", 4),
    (r"LIMON_PICA|PICA", 6), (r"LIMONETA", 6), (r"LIMON", 5),
    (r"JUGO", 7), (r"ACETO", 9), (r"SOYA", 10), (r"VAINILLA", 10),
]
ESC = 1000  # milésimas de minuto (redondeo despreciable frente a la ocupación visible)


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


# ─── Atributos y cambios ─────────────────────────────────────────────────────
def atributos(sp: dict) -> dict:
    A = {}
    for s, x in sp.items():
        desc = (x.get("descripcion") or "").upper()
        gr = (x.get("granel_grupo") or "").upper()
        if not gr:
            gr = " ".join([t for t in desc.split() if not re.match(r"^\d", t)][:2])
        etiq = re.sub(r"\b\d+\s*X\s*(?=\d)", "", desc)
        rank = 8
        for pat, r in RANK:
            if re.search(pat, gr + " " + desc):
                rank = r
                break
        A[s] = dict(formato=str(x.get("formato") or ""), upc=int(x.get("u_por_caja") or 1),
                    granel=gr, etiq=etiq, rank=rank, aji=bool(re.search(r"AJ[IÍ]", desc)))
    return A


def t_cambio(A, i, j):
    """(horas, viola_regla) de pasar de i a j dentro del día."""
    a, b = A[i], A[j]
    h = 0.0
    if a["formato"] != b["formato"]: h = max(h, T_CAMBIO_H["formato"])
    if a["upc"] != b["upc"]: h = max(h, T_CAMBIO_H["empaque"])
    if a["granel"] != b["granel"]: h = max(h, T_CAMBIO_H["granel"])
    if a["etiq"] != b["etiq"]: h = max(h, T_CAMBIO_H["etiqueta"])
    if a["aji"] and not b["aji"]:
        return h + T_LIMPIEZA_AJI_H, 1
    if a["granel"] != b["granel"] and b["rank"] < a["rank"] and not (a["aji"] or b["aji"]):
        return h + T_LIMPIEZA_OSCURO_CLARO_H, 1
    return h, 0


def mejor_orden(A, skus):
    """Orden intradía de menor costo (primero sin violar reglas). <= 6 SKU: exacto."""
    skus = list(skus)
    if len(skus) <= 1:
        return skus, 0.0, 0
    perms = itertools.permutations(skus) if len(skus) <= 6 else [sorted(skus, key=lambda s: A[s]["rank"])]
    best = None
    for p in perms:
        h = v = 0
        for i, j in zip(p, p[1:]):
            hh, vv = t_cambio(A, i, j)
            h += hh
            v += vv
        if best is None or (v, h) < (best[2], best[1]):
            best = (list(p), h, v)
    return best


# ─── Datos ───────────────────────────────────────────────────────────────────
class Datos:
    """Vista común del plan de C: desde el resultado rico (servidor) o desde un cmp (pruebas)."""

    @classmethod
    def desde_resultado(cls, resultado: dict, kw: dict) -> "Datos":
        D = cls()
        D.dd = resultado["detalle_diario"]
        D.sp = kw["sku_params"]
        D.L = kw["lineas_params"]
        D.fac = {(x["sku"], x["linea"]): float(x.get("factor_velocidad") or 1.0) for x in kw["sku_lineas"]}
        D.tcam = {(x["sku"], x["linea"]): float(x.get("t_cambio_hrs") or 0.0) for x in kw["sku_lineas"]}
        D.hoy = _d(kw.get("fecha_inicio") or resultado["resumen"]["fecha_inicio"])
        D.ofts_c = resultado["ofts"]
        D.ap_u, D.ap_n = defaultdict(float), defaultdict(int)
        for s, lst in (kw.get("entradas_aprobadas") or {}).items():
            for e in lst:
                fl, ln, u = e.get("fecha_lanzamiento"), e.get("linea"), float(e.get("cantidad_u") or 0)
                if fl and ln and u > 0:
                    D.ap_u[(ln, _d(fl).isoformat())] += u
                    D.ap_n[(ln, _d(fl).isoformat())] += 1
        D._completar()
        return D

    @classmethod
    def desde_cmp(cls, fn: str, cual: str = "base") -> "Datos":
        import gzip
        d = json.load(gzip.open(fn))
        D = cls()
        D.plan = d[cual]
        D.dd = D.plan["detalle_diario"]
        D.sp = {x["sku"]: x for x in d["sku_params"]}
        D.L = {l["codigo"]: l for l in d["lineas"]}
        D.fac = {(x["sku"], x["linea"]): float(x["factor_velocidad"] or 1) for x in d["sku_lineas"]}
        D.tcam = {(x["sku"], x["linea"]): float(x.get("t_cambio_hrs") or 0) for x in d["sku_lineas"]}
        D.hoy = _d(D.plan["resumen"]["fecha_inicio"])
        D.ofts_c = D.plan["ofts"]
        D.ap_u, D.ap_n = defaultdict(float), defaultdict(int)
        for e in D.plan.get("entradas_fijas", []):          # sin SKU en el snapshot: upc 12
            l, f = e.get("linea"), e.get("fecha_lanzamiento")
            if l in D.L and f:
                D.ap_u[(l, f)] += float(e.get("cantidad_cajas") or 0) * 12
                D.ap_n[(l, f)] += 1
        D._completar()
        return D

    def _completar(self):
        self.A = atributos(self.sp)
        self.fechas = sorted({f for s in self.dd for f in self.dd[s]})
        self.cap_h = {}
        for l, lp in self.L.items():
            for f in self.fechas:
                self.cap_h[(l, f)] = horas_linea_dia(
                    _d(f), lp.get("horas_turno", 8), lp.get("turnos_dia", 1), lp.get("turnos_config"),
                    lp.get("excepciones"), lp.get("bloqueos"))
        self.prodC = defaultdict(float)
        for o in self.ofts_c:
            self.prodC[(o["sku"], o["linea"], o["fecha_lanzamiento"])] += float(o["cantidad_unidades"])
        self.ap_h = defaultdict(float, {k: u / max(1e-9, float(self.L[k[0]].get("velocidad_u_hr") or 1))
                                        for k, u in self.ap_u.items() if k[0] in self.L})

    def vel(self, l):
        return float(self.L[l].get("velocidad_u_hr") or 1)

    def horas_prod(self, s, l, u):
        return u / (self.vel(l) * self.fac.get((s, l), 1.0))


# ─── Stock y evaluación (misma regla para C y D) ─────────────────────────────
def stock(D, prod_sf):
    fin, disp = {}, {}
    for s, serie in D.dd.items():
        fs = sorted(serie)
        st = serie[fs[0]]["stock_ini_disp_u"]
        for f in fs:
            v = serie[f]
            dp = st + v["entrada_aprobada_u"] - v["demanda_corr_u"]
            fn = dp + prod_sf.get((s, f), 0)
            disp[(s, f)], fin[(s, f)] = dp, fn
            st = fn
    return fin, disp


def evaluar(D, P, ventana, lineas):
    """KPI de eficiencia y guardas sobre P: (sku, linea, fecha) -> unidades."""
    lun0, lunf = ventana
    prod_sf = defaultdict(float)
    for (s, l, f), u in P.items():
        prod_sf[(s, f)] += u
    fin, disp = stock(D, prod_sf)
    por_ld = defaultdict(dict)
    for (s, l, f), u in P.items():
        if u > 0.5:
            por_ld[(l, f)][s] = u
    R = defaultdict(float)
    hab = [lun0 + timedelta(i) for i in range((lunf - lun0).days)]
    for l in lineas:
        for k0 in range(0, len(hab), 7):
            dias = [x.isoformat() for x in hab[k0:k0 + 7] if D.cap_h.get((l, x.isoformat()), 0) > 0]
            prev = {"sku": set(), "emb": set(), "gr": set()}
            for f in dias:
                skus = por_ld.get((l, f), {})
                cap = max(1e-9, D.cap_h[(l, f)] - D.ap_h[(l, f)])
                hp = sum(D.horas_prod(s, l, u) for s, u in skus.items())
                _, hc, viol = mejor_orden(D.A, skus)
                if skus:
                    R["abiertos"] += 1
                    R["ocup_sum"] += (hp + hc) / cap
                    R["ge95"] += (hp + hc) / cap >= 0.95 - 1e-6
                    R["lt70"] += (hp + hc) / cap < 0.70
                    R["h_cambio"] += hc
                    R["viol"] += viol
                else:
                    R[f"cerrado_{_d(f).weekday()}"] += 1
                for k, fk in (("sku", lambda s: s), ("emb", lambda s: D.A[s]["upc"]),
                              ("gr", lambda s: (D.A[s]["upc"], D.A[s]["granel"]))):
                    v = {fk(s) for s in skus}
                    R["arr_" + k] += len(v - prev[k])
                    prev[k] = v
        R["unidades"] += sum(u for (s, ll, f), u in P.items() if ll == l and lun0 <= _d(f) < lunf)
    for s in D.dd:
        if D.sp.get(s, {}).get("linea_preferida") not in lineas:
            continue
        for f, v in D.dd[s].items():
            if lun0 <= _d(f) < lunf:
                R["quiebres"] += disp[(s, f)] < 0
                R["bajo_ss"] += fin[(s, f)] < v["ss_u"]
                R["sobre_2ss"] += _d(f).weekday() < 5 and v["ss_u"] > 0 and fin[(s, f)] > 2 * v["ss_u"]
    R["ocup"] = R["ocup_sum"] / R["abiertos"] if R["abiertos"] else 0
    return dict(R)


# ─── Modelo por línea-semana ─────────────────────────────────────────────────
def _limites(D):
    """LB/UB de Δ por (sku, fecha), desde el detalle de C (sin recalcular)."""
    LB, UB = {}, {}
    for s, serie in D.dd.items():
        fs = sorted(serie)
        cb = float(D.sp.get(s, {}).get("cap_bodega_u") or 0)
        for k, f in enumerate(fs):
            v = serie[f]
            lb = min(0.0, v["ss_u"] - v["stock_fin_u"])                                  # S* (cierre)
            if k + 1 < len(fs):
                # Q* y S* sobre el disponible del día siguiente (regla de las alertas de C con
                # QUIEBRE_INTRADIA_SOLVER): no crea quiebres ni alertas BAJO_SS nuevas
                vn = serie[fs[k + 1]]
                lb = max(lb, min(0.0, max(vn.get("ss_u") or 0, 0) - vn["stock_disp_u"]))
            LB[(s, f)] = lb
            UB[(s, f)] = max(0.0, cb - v["stock_fin_u"]) if cb > 0 else 1e12
    return LB, UB


def _resolver(D, P, delta, LB, UB, l, dias_sem, fut, desde, finC, log):
    dias = [f for f in dias_sem if f >= desde and D.cap_h.get((l, f), 0) - D.ap_h[(l, f)] > 0.01]
    S = sorted({s for (s, ll, f) in P if ll == l and f in dias_sem and P[(s, ll, f)] > 0.5})
    if not S or not dias:
        return
    vel = D.vel(l)
    cur = {(s, f): P.get((s, l, f), 0.0) for s in S for f in dias_sem}
    totC = {s: sum(D.prodC.get((s, l, f), 0.0) for f in dias_sem) for s in S}
    totcur = {s: sum(cur[(s, f)] for f in dias_sem) for s in S}
    coef = {s: int(round(D.A[s]["upc"] / (vel * D.fac.get((s, l), 1.0)) * 60 * ESC)) for s in S}
    st_c = {s: int(round(D.tcam.get((s, l), 0.0) * 60 * ESC)) for s in S}     # setup regla C
    m = cp_model.CpModel()
    x, y = {}, {}
    for s in S:
        upc = D.A[s]["upc"]
        maxc = int(TOPE_CRECIMIENTO * max(totC[s], totcur[s]) // upc) + 1
        bmin = -(-int(D.sp[s].get("batch_min_u") or 0) // upc)
        if totcur[s] > 0:
            bmin = min(bmin, int(totcur[s] // upc))
        for f in dias:
            x[(s, f)] = m.NewIntVar(0, maxc, "")
            y[(s, f)] = m.NewBoolVar("")
            m.Add(x[(s, f)] <= maxc * y[(s, f)])
            if bmin > 0:
                m.Add(x[(s, f)] >= bmin).OnlyEnforceIf(y[(s, f)])
            m.AddHint(x[(s, f)], int(round(cur[(s, f)] / upc)))
            m.AddHint(y[(s, f)], cur[(s, f)] > 0.5)
        m.Add(sum(x[(s, f)] for f in dias) * upc <= int(TOPE_CRECIMIENTO * totC[s]) + upc)
    # barreras Q*/S* y bodega, en la semana y hacia adelante
    for s in S:
        upc = D.A[s]["upc"]
        acum_cur, fijo, acum_new = 0.0, 0.0, []
        for f in dias_sem:
            acum_cur += cur[(s, f)]
            if f in dias:
                acum_new.append(x[(s, f)])
            else:
                fijo += cur[(s, f)]
            if (s, f) not in LB:
                continue
            expr = sum(acum_new) * upc if acum_new else 0
            base = delta[s].get(f, 0.0) - acum_cur + fijo
            m.Add(expr >= int(-(-(LB[(s, f)] - base) // 1)))
            if UB[(s, f)] < 1e11:
                m.Add(expr <= int((UB[(s, f)] - base) // 1))
        dfin = sum(x[(s, f)] for f in dias) * upc + int(round(fijo)) - int(round(acum_cur))
        lbf = max([LB[(s, g)] - delta[s].get(g, 0.0) for g in fut if (s, g) in LB] or [-1e12])
        ubf = min([UB[(s, g)] - delta[s].get(g, 0.0) for g in fut if (s, g) in UB] or [1e12])
        if lbf > -1e11:
            m.Add(dfin >= int(-(-lbf // 1)))
        if ubf < 1e11:
            m.Add(dfin <= int(ubf // 1))
    # días: secuencia (circuito), capacidad, apertura, faltante bajo la meta
    open_, costo_cambio, viol, falt = {}, [], [], []
    for f in dias:
        o = m.NewBoolVar("")
        open_[f] = o
        for s in S:
            m.AddImplication(y[(s, f)], o)
        m.Add(sum(y[(s, f)] for s in S) >= 1).OnlyEnforceIf(o)
        m.Add(sum(y[(s, f)] for s in S) <= max(0, N_MAX_SKU_DIA - D.ap_n[(l, f)]))
        arcs, cc, starts = [(0, 0, o.Not())], [], {}
        for i, si in enumerate(S, 1):
            arcs.append((i, i, y[(si, f)].Not()))
            st_ = m.NewBoolVar("")
            starts[si] = st_
            arcs += [(0, i, st_), (i, 0, m.NewBoolVar(""))]
            for j, sj in enumerate(S, 1):
                if i != j:
                    a = m.NewBoolVar("")
                    arcs.append((i, j, a))
                    h, v = t_cambio(D.A, si, sj)
                    cc.append((a, int(round(h * 60 * ESC)), v))
        m.AddCircuit(arcs)
        prod = sum(coef[s] * x[(s, f)] for s in S)
        chg = sum(c * a for a, c, v in cc)
        cap = int((D.cap_h[(l, f)] - D.ap_h[(l, f)]) * 60 * ESC)
        sk_c = [s for s in S if cur[(s, f)] > 0.5]
        if sk_c:   # si C ya excede con la regla provisional, D puede llegar hasta lo de C (no más)
            uso_c = sum(coef[s] * int(round(cur[(s, f)] / D.A[s]["upc"])) for s in sk_c)
            uso_c += int(round(mejor_orden(D.A, sk_c)[1] * 60 * ESC)) + len(sk_c) * ESC
            cap = max(cap, uso_c)
        m.Add(prod + chg <= cap)
        # regla de setup de C (la que muestra la app): el primero del día gratis, salvo aprobadas
        cap_c = int((D.cap_h[(l, f)] * vel - D.ap_u[(l, f)]) / vel * 60 * ESC)
        set_c = sum(st_c[s] * y[(s, f)] for s in S) - (0 if D.ap_n[(l, f)] else sum(st_c[s] * starts[s] for s in S))
        if sk_c:
            uso_cc = sum(coef[s] * int(round(cur[(s, f)] / D.A[s]["upc"])) for s in sk_c) \
                + sum(st_c[s] for s in sk_c) - (0 if D.ap_n[(l, f)] else min(st_c[s] for s in sk_c))
            cap_c = max(cap_c, uso_cc)
        m.Add(prod + set_c <= cap_c)
        costo_cambio.append(sum((c // ESC) * a for a, c, v in cc))
        viol += [a for a, c, v in cc if v]
        sh = m.NewIntVar(0, max(cap, 0), "")
        m.Add(sh >= int(META_OCUP * cap) - prod - chg - cap * (1 - o))
        falt.append(sh)
    arr = []
    for s in S:
        for k, f in enumerate(dias):
            a = m.NewBoolVar("")
            m.Add(a >= y[(s, f)] - (y[(s, dias[k - 1])] if k else 0))
            arr.append(a)
    arr_g = []
    for key, w in ((lambda s: D.A[s]["upc"], W_ARR_EMPAQUE), (lambda s: D.A[s]["granel"], W_ARR_GRANEL)):
        grupos = defaultdict(list)
        for s in S:
            grupos[key(s)].append(s)
        if len(grupos) < 2:
            continue
        for sg in grupos.values():
            prev = None
            for f in dias:
                on = m.NewBoolVar("")
                m.AddMaxEquality(on, [y[(s, f)] for s in sg])
                a = m.NewBoolVar("")
                m.Add(a >= on - (prev if prev is not None else 0))
                arr_g.append((w, a))
                prev = on
    obj1 = (sum((W_DIA + W_DIA_POS * k) * open_[f] for k, f in enumerate(dias)) + sum(costo_cambio)
            + W_VIOL * sum(viol) + W_ARR_SKU * sum(arr) + sum(w * a for w, a in arr_g))
    m.Minimize(obj1)
    sol = cp_model.CpSolver()
    sol.parameters.max_time_in_seconds = TL_SEG
    sol.parameters.num_workers = WORKERS
    sol.parameters.random_seed = 42
    st1 = sol.Solve(m)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log.append((l, dias_sem[0], f"etapa 1 {sol.StatusName(st1)}: se mantiene C"))
        return
    # etapa 2: estructura fija; llenar con criterio de cobertura / absorción
    for f in dias:
        m.Add(open_[f] == int(sol.Value(open_[f])))
    m.Add(obj1 <= int(sol.ObjectiveValue() * 1.03) + 50)
    m.ClearHints()
    for v in list(x.values()) + list(y.values()):
        m.AddHint(v, sol.Value(v))
    sem_sig = [(_d(dias_sem[-1]) + timedelta(i)).isoformat() for i in range(1, 8)]
    crecer = []
    for s in S:
        dem = [D.dd[s][g]["demanda_corr_u"] for g in D.fechas if g > dias_sem[-1] and g in D.dd[s]][:28]
        dprom = sum(dem) / len(dem) if dem else 0
        sem_cob = (finC.get((s, dias_sem[-1]), 0) / dprom / 7) if dprom > 0 else 10
        w = min(TOPE_W_CRECER, 1 + K_COBERTURA * max(0.0, sem_cob))
        if any(P.get((s, l, g), 0) > 0.5 for g in sem_sig):
            w *= F_ABSORBE
        for f in dias:
            c0 = int(round(cur[(s, f)] / D.A[s]["upc"]))
            up, dn = m.NewIntVar(0, 10 ** 7, ""), m.NewIntVar(0, 10 ** 7, "")
            m.Add(x[(s, f)] - c0 == up - dn)
            crecer.append(int(round(w * coef[s])) * up + max(1, coef[s] // 4) * dn)
    m.Minimize(W_FALTANTE * sum(falt) + sum(crecer))
    st2 = sol.Solve(m)
    if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        log.append((l, dias_sem[0], f"etapa 2 {sol.StatusName(st2)}: se mantiene C"))
        return
    for s in S:
        upc = D.A[s]["upc"]
        acum_cur = acum_new = 0.0
        for f in dias_sem:
            acum_cur += cur[(s, f)]
            nu = sol.Value(x[(s, f)]) * upc if f in dias else cur[(s, f)]
            acum_new += nu
            if nu > 0:
                P[(s, l, f)] = nu
            else:
                P.pop((s, l, f), None)
            delta[s][f] = delta[s].get(f, 0.0) + (acum_new - acum_cur)
        for g in fut:
            delta[s][g] = delta[s].get(g, 0.0) + (acum_new - acum_cur)
    log.append((l, dias_sem[0], f"{sol.StatusName(st1)}/{sol.StatusName(st2)}",
                f"abiertos {sum(sol.Value(open_[f]) for f in dias)}/{len(dias)}"))


def optimizar(D):
    """Corre D sobre el horizonte. Devuelve (P_D, log, desde, ventana)."""
    hoy = D.hoy
    desde = min([f for f in D.fechas if f > hoy.isoformat()] or [hoy.isoformat()])
    lun = hoy - timedelta(hoy.weekday())
    fin_h = _d(D.fechas[-1]) + timedelta(1)
    P = {k: v for k, v in D.prodC.items() if v > 0.5}
    LB, UB = _limites(D)
    finC = {(s, f): v["stock_fin_u"] for s, serie in D.dd.items() for f, v in serie.items()}
    delta, log = defaultdict(dict), []
    w = lun
    lineas = sorted({l for (_, l, _) in P})
    while w < fin_h:
        dias_sem = [(w + timedelta(i)).isoformat() for i in range(7)]
        fut = [f for f in D.fechas if f > dias_sem[-1]]
        for l in lineas:
            _resolver(D, P, delta, LB, UB, l, dias_sem, fut, desde, finC, log)
        w += timedelta(7)
    return P, log, desde, (lun, fin_h)


# ─── Integración con el resultado rico de C ──────────────────────────────────
def _contar(D, P):
    prod_sf = defaultdict(float)
    for (s, l, f), u in P.items():
        prod_sf[(s, f)] += u
    fin, disp = stock(D, prod_sf)
    q = sum(1 for k, v in disp.items() if v < 0)
    b = sum(1 for (s, f), v in fin.items() if v < D.dd[s][f]["ss_u"])                       # estado
    a = sum(1 for (s, f), v in disp.items() if 0 <= v < (D.dd[s][f]["ss_u"] or 0))           # alerta
    return q, b, a


def aplicar_pasada_d(resultado: dict, kw: dict) -> dict:
    """Aplica D sobre el resultado de C, EN SU LUGAR. Devuelve un diagnóstico.
    Si D empeora quiebres o días bajo SS (control final), no modifica nada."""
    t0 = time.time()
    D = Datos.desde_resultado(resultado, kw)
    PC = {k: v for k, v in D.prodC.items() if v > 0.5}
    PD, log, desde, vent = optimizar(D)
    qc, bc, ac = _contar(D, PC)
    qd, bd, ad = _contar(D, PD)
    lineas = sorted({l for (_, l, _) in PC})
    eC, eD = evaluar(D, PC, vent, lineas), evaluar(D, PD, vent, lineas)
    n_ok = sum(1 for r in log if "se mantiene" not in r[2])
    diag = {"desde": desde, "seg": round(time.time() - t0, 1), "linea_semanas": len(log),
            "resueltas": n_ok, "quiebres": [qc, qd], "bajo_ss": [bc, bd], "alertas_bajo_ss": [ac, ad],
            "abiertos": [eC.get("abiertos"), eD.get("abiertos")],
            "ocup": [round(eC.get("ocup", 0), 3), round(eD.get("ocup", 0), 3)],
            "arr_sku": [eC.get("arr_sku"), eD.get("arr_sku")], "arr_emb": [eC.get("arr_emb"), eD.get("arr_emb")],
            "h_cambio": [round(eC.get("h_cambio", 0), 1), round(eD.get("h_cambio", 0), 1)],
            "unidades": [eC.get("unidades"), eD.get("unidades")], "aplicada": False}
    for r in log:
        if "se mantiene" in r[2]:
            logger.info(f"[PASADA_D] {r[0]} sem {r[1]}: {r[2]}")
    if qd > qc or bd > bc or ad > ac:
        logger.warning(f"[PASADA_D] DESCARTADA (control final): quiebres {qc}->{qd}, "
                       f"bajo SS {bc}->{bd}, alertas bajo SS {ac}->{ad}. Queda el plan de C.")
        resultado.setdefault("n2_diag", {})["D"] = diag
        return diag
    # se escribe sobre COPIAS y se reemplaza al final: si algo falla a mitad, `resultado` queda intacto
    claves = ("ofts", "detalle_diario", "alertas", "uso_linea", "resumen", "encabezado_sku", "stock_diario")
    tmp = {k: copy.deepcopy(resultado[k]) for k in claves if k in resultado}
    _escribir(tmp, D, PD, desde)
    resultado.update(tmp)
    diag["aplicada"] = True
    resultado.setdefault("n2_diag", {})["D"] = diag
    logger.info(f"[PASADA_D] APLICADA en {diag['seg']}s desde {desde} | {n_ok}/{len(log)} línea-semanas | "
                f"días abiertos {diag['abiertos'][0]:.0f}->{diag['abiertos'][1]:.0f} | ocupación "
                f"{diag['ocup'][0]:.0%}->{diag['ocup'][1]:.0%} | arranques SKU {diag['arr_sku'][0]:.0f}->"
                f"{diag['arr_sku'][1]:.0f} | horas cambio {diag['h_cambio'][0]}->{diag['h_cambio'][1]} | "
                f"quiebres {qc}->{qd} | bajo SS {bc}->{bd} (alertas {ac}->{ad}) | unidades {diag['unidades'][0]:.0f}->{diag['unidades'][1]:.0f}")
    return diag


def _escribir(resultado, D, PD, desde):
    """Reescribe OFT, stock, detalle, alertas, uso y resumen con el plan de D (desde 'desde')."""
    # 1. OFT: se conservan las de C anteriores a 'desde'; las demás se rearman con orden del día
    ofts = [o for o in resultado["ofts"] if o["fecha_lanzamiento"] < desde]
    por_ld = defaultdict(dict)
    for (s, l, f), u in PD.items():
        if f >= desde and u > 0.5:
            por_ld[(l, f)][s] = u
    for (l, f), skus in sorted(por_ld.items(), key=lambda t: (t[0][1], t[0][0])):
        orden = mejor_orden(D.A, skus)[0]
        vel = D.vel(l)
        for pos, s in enumerate(orden):
            sp = D.sp[s]
            upc = D.A[s]["upc"]
            lt = int(round((sp.get("lead_time_sem", 0) or 0) * 7))
            paga = pos > 0 or D.ap_n[(l, f)] > 0
            ofts.append({
                "sku": s, "linea": l, "fecha_lanzamiento": f,
                "fecha_entrada_real": (_d(f) + timedelta(days=lt)).isoformat(),
                "cantidad_cajas": int(round(skus[s] / upc)), "cantidad_unidades": int(round(skus[s])),
                "u_por_caja": upc, "paga_setup": paga,
                "setup_unidades": int(D.tcam.get((s, l), 0.0) * vel) if paga else 0,
                "aprobada": False, "numero_of": None, "motivo": "OFT",
                "orden_dia": pos + 1,
            })
    ofts.sort(key=lambda o: (o["fecha_lanzamiento"], o["linea"], o.get("orden_dia", 0)))
    # 2. stock: Δ exacto sobre el detalle de C
    acum = defaultdict(float)
    for o in resultado["ofts"]:
        acum[(o["sku"], o["fecha_lanzamiento"])] -= float(o["cantidad_unidades"])
    for o in ofts:
        acum[(o["sku"], o["fecha_lanzamiento"])] += float(o["cantidad_unidades"])
    cajas_dia = defaultdict(int)
    for o in ofts:
        cajas_dia[(o["sku"], o["fecha_lanzamiento"])] += int(o["cantidad_cajas"])
    cambiados = {s for (s, f), v in acum.items() if abs(v) > 0.5}
    cap_b = {s: float(D.sp.get(s, {}).get("cap_bodega_u") or 0) for s in D.dd}
    # N2_CAP_EFECTIVA: SKU que ya parten sobre la bodega no generan alerta en C (su capacidad
    # efectiva es su propio stock). Se respeta: capacidad efectiva = máximo stock de C.
    con_alerta = {a["sku"] for a in resultado["alertas"] if a.get("tipo") == "EXCESO_BODEGA"}
    for s, cb in list(cap_b.items()):
        serie = resultado["detalle_diario"].get(s) or {}
        mx = max((v["stock_fin_u"] for v in serie.values()), default=0)
        if cb and mx > cb and s not in con_alerta:
            cap_b[s] = float(mx)
    otras = [a for a in resultado["alertas"] if a.get("sku") not in cambiados
             or a.get("tipo") not in ("QUIEBRE", "BAJO_SS", "EXCESO_BODEGA")]
    nuevas = []
    for s in cambiados:
        serie = resultado["detalle_diario"].get(s)
        if not serie:
            continue
        dl, dl_prev, smin, sfin = 0.0, 0.0, None, 0
        for f in sorted(serie):
            v = serie[f]
            dl += acum.get((s, f), 0.0)
            fin = int(round(v["stock_fin_u"] + dl))
            disp = int(round(v["stock_disp_u"] + dl_prev))
            v["stock_fin_u"], v["stock_disp_u"] = fin, disp
            v["stock_ini_disp_u"] = int(round(v["stock_ini_disp_u"] + dl_prev))
            v["oft_cajas"] = cajas_dia.get((s, f)) or None
            ss = v.get("ss_u") or 0
            v["estado"] = "QUIEBRE" if disp < 0 else ("BAJO_SS" if ss > 0 and fin < ss else "OK")
            if disp < 0:
                nuevas.append({"sku": s, "fecha": f, "tipo": "QUIEBRE",
                               "mensaje": f"Demanda no cubierta: {-disp} unidades", "deficit_u": -disp})
            elif ss > 0 and disp < ss:     # misma regla que C (QUIEBRE_INTRADIA_SOLVER: sobre el disponible)
                nuevas.append({"sku": s, "fecha": f, "tipo": "BAJO_SS",
                               "mensaje": f"Stock {fin} u bajo SS ({ss - disp} u faltantes)", "deficit_u": ss - disp})
            if cap_b.get(s) and fin > cap_b[s]:
                nuevas.append({"sku": s, "fecha": f, "tipo": "EXCESO_BODEGA",
                               "mensaje": f"Stock {fin} u excede cap. bodega ({int(fin - cap_b[s])} u sobre cap)",
                               "deficit_u": int(fin - cap_b[s])})
            if s in (resultado.get("stock_diario") or {}):
                resultado["stock_diario"][s][f] = max(0, fin)
            smin = fin if smin is None else min(smin, fin)
            sfin = fin
            dl_prev = dl
        enc = (resultado.get("encabezado_sku") or {}).get(s)
        if enc is not None:
            enc["stock_final_u"], enc["stock_min_u"] = sfin, smin if smin is not None else 0
    resultado["alertas"] = otras + nuevas
    resultado["ofts"] = ofts
    # 3. uso de línea con la regla de C (producción/factor + setup), desde 'desde'
    occ = defaultdict(float)
    for o in ofts:
        if o["fecha_lanzamiento"] >= desde:
            occ[(o["linea"], o["fecha_lanzamiento"])] += o["cantidad_unidades"] / D.fac.get((o["sku"], o["linea"]), 1.0) \
                + o["setup_unidades"]
    for l, serie in resultado["uso_linea"].items():
        for f in serie:
            if f >= desde:
                cap_u = int(D.vel(l) * D.cap_h.get((l, f), 0)) if l in D.L else 0
                serie[f] = round(100 * occ.get((l, f), 0.0) / cap_u, 1) if cap_u else 0.0
    # 4. resumen
    r = resultado.get("resumen", {})
    r["ofts_generadas"] = len(ofts)
    r["alertas_quiebre"] = sum(1 for a in resultado["alertas"] if a["tipo"] == "QUIEBRE")
    r["alertas_bajo_ss"] = sum(1 for a in resultado["alertas"] if a["tipo"] == "BAJO_SS")
    r["alertas_exceso_bodega"] = sum(1 for a in resultado["alertas"] if a["tipo"] == "EXCESO_BODEGA")
    r["uso_promedio_lineas_pct"] = {l: round(sum(u.values()) / len(u), 1) if u else 0.0
                                    for l, u in resultado["uso_linea"].items()}


# ─── Uso fuera del servidor: comparar C y C+D sobre un cmp_*.json.gz ──────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmp")
    ap.add_argument("--cual", default="base")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    D = Datos.desde_cmp(a.cmp, a.cual)
    PC = {k: v for k, v in D.prodC.items() if v > 0.5}
    t0 = time.time()
    PD, log, desde, vent = optimizar(D)
    print(f"desde {desde} · {len(log)} línea-semanas · {time.time() - t0:.0f}s · control (quiebres, bajo SS, alertas bajo SS): {_contar(D, PC)} -> {_contar(D, PD)}")
    lineas = sorted(D.L)
    eC, eD = evaluar(D, PC, vent, lineas), evaluar(D, PD, vent, lineas)
    for k in ("abiertos", "ocup", "ge95", "lt70", "arr_sku", "arr_emb", "arr_gr", "h_cambio", "viol",
              "unidades", "quiebres", "bajo_ss", "sobre_2ss", "cerrado_0", "cerrado_4"):
        print(f"{k:10} {eC.get(k, 0):12.2f} {eD.get(k, 0):12.2f}")
