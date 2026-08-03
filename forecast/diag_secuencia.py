#!/usr/bin/env python3
"""
diag_secuencia.py — Etapa 1: cuantas transiciones de nivel se pagan HOY.

Antes de implementar cualquier post-orden o restriccion de secuencia, medir si
hay algo que ganar. Si el solver ya agrupa por mineros de lote y demanda
correlacionada, el ordenamiento sale INERTE — como salio la campana de formato
de L1Pet LV, cuyo costo medido fue cero.

QUE MIDE
--------
Los bloques de produccion son CONTINUOS e INDEPENDIENTES DEL DIA: un embalaje
puede ocupar 3 dias y fraccion y otro 1 dia y fraccion (confirmado con
Produccion el 03-08). Por eso el dia NO es frontera de secuencia y las
transiciones minimas de una semana dependen solo de cuantos GRUPOS ANIDADOS
tiene el conjunto asignado a esa semana:

    (n_embalajes - 1)
  + SUMA sobre embalajes (n_familias - 1)
  + SUMA sobre (embalaje,familia) (n_graneles - 1)

Ese es el minimo alcanzable con orden optimo, y es exactamente lo que un
`cap <= K grupos por semana` controlaria.

Se reporta tambien el conteo si la semana se ejecutara en un orden arbitrario
(por SKU, como se lee la tabla hoy): la diferencia es lo que se gana ordenando.

IMPORTANTE — implicancia de diseno
----------------------------------
Si un bloque cruza dias, el ORDEN determina que dia se produce cada SKU, y por
lo tanto su fecha_entrada y el balance de stock. El post-orden NO es cosmetico:
o el modelo acota la fragmentacion (cap <= K) y la asignacion por dia queda
compatible, o las fechas del plan pasan a ser indicativas dentro de la semana.

IMPORTANTE — lo que este diagnostico NO dice
--------------------------------------------
- No valoriza en horas: falta el tiempo de cambio POR NIVEL (pendiente de
  Produccion). Cuenta transiciones, no minutos.
- El orden real en planta lo decide Produccion, que probablemente ya agrupa por
  criterio propio. El "CRONOLOGICO" es el peor caso de seguir la tabla literal,
  no necesariamente lo que ocurre.
- Reordenar DENTRO de un dia no mueve capacidad; reordenar ENTRE dias si puede
  cambiar que dia produce que, y eso ya es decision del solver, no post-orden.

Solo lectura: no escribe nada.

Uso:
    python3 /app/diag_secuencia.py
    python3 /app/diag_secuencia.py --linea "L1Pet LV" --detalle
"""

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict

from sqlalchemy import text

# Niveles de secuencia por linea. Provisional hasta que exista la tabla de
# configuracion; en L1Pet LV el orden de costo es formato > embalaje > familia >
# sub-granel (confirmado con Produccion el 03-08).
NIVELES = {
    "L1Pet LV": ["embalaje", "familia", "granel"],
}
NIVELES_DEFAULT = ["familia", "granel"]


def transiciones(seq, niveles):
    """Cuenta cambios por nivel recorriendo la secuencia."""
    out = {n: 0 for n in niveles}
    for a, b in zip(seq, seq[1:]):
        for n in niveles:
            if a.get(n) != b.get(n):
                out[n] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--linea", type=str, default=None)
    ap.add_argument("--detalle", action="store_true",
                    help="imprime la secuencia completa por semana")
    args = ap.parse_args()

    sys.path.insert(0, "/app")
    from db_mrp import SessionLocal

    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, snapshot FROM mrp_planes WHERE vigente LIMIT 1")).mappings().first()
        prm = {r[0]: dict(desc=r[1] or "", fmt=(r[2] or "").strip(),
                          upc=int(r[3] or 0), gr=(r[4] or "").strip())
               for r in s.execute(text(
                   "SELECT sku, descripcion, formato, u_por_caja, granel_grupo "
                   "FROM mrp_sku_params")).fetchall()}
        cat = {r[0]: dict(fam=r[1], of=int(r[2] or 0), og=int(r[3] or 0))
               for r in s.execute(text(
                   "SELECT granel_grupo, familia, orden_familia, orden_granel "
                   "FROM mrp_graneles")).fetchall()}

    snap = row["snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap)
    print(f"=== diag_secuencia · plan #{row['id']} · catalogo: {len(cat)} graneles ===")
    print()

    # ── armar OFTs con sus atributos de nivel ────────────────────────────────
    por_sem = defaultdict(list)
    sin_granel = set()
    for o in (snap.get("ofts") or []):
        sku = o.get("sku")
        ln = (o.get("linea") or "(sin)").strip()
        f = str(o.get("fecha_lanzamiento"))[:10]
        if not f or f == "None":
            continue
        if args.linea and ln != args.linea:
            continue
        p = prm.get(sku, {})
        gr = p.get("gr", "")
        c = cat.get(gr, {})
        if not gr:
            sin_granel.add(sku)
        d = dt.date.fromisoformat(f)
        lun = (d - dt.timedelta(days=d.weekday())).isoformat()
        por_sem[(ln, lun)].append(dict(
            sku=sku, fecha=f, cajas=o.get("cantidad_cajas"),
            formato=p.get("fmt", ""), embalaje=p.get("upc", 0),
            granel=gr or "(vacio)", familia=c.get("fam", "(sin cat)"),
            of=c.get("of", 99), og=c.get("og", 99),
            desc=(p.get("desc") or "")[:34],
        ))

    if not por_sem:
        print("sin OFTs para el filtro dado")
        return 0

    tot_cron = defaultdict(int)
    tot_opt = defaultdict(int)
    filas = []

    grupos_sem = {}
    for (ln, lun), ofts in sorted(por_sem.items()):
        niveles = NIVELES.get(ln, NIVELES_DEFAULT)
        # orden arbitrario = como se lee la tabla (por SKU), SIN agrupar
        cron = sorted(ofts, key=lambda x: x["sku"])
        # orden optimo = jerarquia de niveles, ignorando el dia
        if "embalaje" in niveles:
            opt = sorted(ofts, key=lambda x: (x["embalaje"], x["of"], x["og"], x["sku"]))
        else:
            opt = sorted(ofts, key=lambda x: (x["of"], x["og"], x["sku"]))
        tc = transiciones(cron, niveles)
        to = transiciones(opt, niveles)
        for n in niveles:
            tot_cron[n] += tc[n]
            tot_opt[n] += to[n]
        # grupos anidados (lo que un cap <= K controlaria)
        embs = defaultdict(list)
        for o in ofts:
            embs[o["embalaje"]].append(o)
        g_emb = len(embs)
        g_fam = {e: len({o["familia"] for o in lst}) for e, lst in embs.items()}
        g_gr = {}
        for e, lst in embs.items():
            per = defaultdict(set)
            for o in lst:
                per[o["familia"]].add(o["granel"])
            g_gr[e] = {f: len(v) for f, v in per.items()}
        grupos_sem[(ln, lun)] = (g_emb, g_fam, g_gr)
        filas.append((ln, lun, len(ofts), len({o["fecha"] for o in ofts}),
                      niveles, tc, to, cron, opt))

    print("--- POR (LINEA, SEMANA) ---")
    print(f"{'linea':<14}{'semana':<12}{'OFT':>4}{'dias':>5}  "
          f"{'transiciones CRONOLOGICO':<28}{'transiciones OPTIMO':<26}")
    for ln, lun, n, nd, niveles, tc, to, _c, _o in filas:
        sc = " ".join(f"{k[:3]}={tc[k]}" for k in niveles)
        so = " ".join(f"{k[:3]}={to[k]}" for k in niveles)
        flag = "" if sum(tc.values()) == sum(to.values()) else "  <-- hay ahorro"
        print(f"{ln:<14}{lun:<12}{n:>4}{nd:>5}  {sc:<28}{so:<26}{flag}")

    print()
    print("--- GRUPOS ANIDADOS POR SEMANA (lo que un cap <= K controlaria) ---")
    print(f"{'linea':<14}{'semana':<12}{'emb':>4}{'fam/emb':>9}{'gran/emb-fam':>14}"
          f"{'trans_min':>10}")
    tot_min = 0
    for (ln, lun), (g_emb, g_fam, g_gr) in sorted(grupos_sem.items()):
        tmin = (g_emb - 1) + sum(v - 1 for v in g_fam.values())
        for e, per in g_gr.items():
            tmin += sum(v - 1 for v in per.values())
        tot_min += tmin
        sf = ",".join(str(g_fam[e]) for e in sorted(g_fam))
        sg = "|".join(",".join(str(g_gr[e][f]) for f in sorted(g_gr[e]))
                      for e in sorted(g_gr))
        print(f"{ln:<14}{lun:<12}{g_emb:>4}{sf:>9}{sg:>14}{tmin:>10}")
    print(f"{'':<26}{'':>4}{'':>9}{'TOTAL minimo':>14}{tot_min:>10}")

    print()
    print("--- TOTAL (todas las semanas del horizonte) ---")
    nivset = []
    for _l, _s, _n, _d, niveles, _tc, _to, _c, _o in filas:
        for x in niveles:
            if x not in nivset:
                nivset.append(x)
    print(f"{'nivel':<14}{'CRONOLOGICO':>13}{'OPTIMO':>9}{'ahorro':>9}")
    for n in nivset:
        a, b = tot_cron[n], tot_opt[n]
        print(f"{n:<14}{a:>13}{b:>9}{a-b:>9}")
    print()
    ta, tb = sum(tot_cron.values()), sum(tot_opt.values())
    print(f"{'TOTAL':<14}{ta:>13}{tb:>9}{ta-tb:>9}")
    print()
    if ta - tb <= 0:
        print("VEREDICTO: el plan ya sale agrupado -> el post-orden es INERTE.")
    else:
        pct = 100.0 * (ta - tb) / ta if ta else 0
        print(f"VEREDICTO: el post-orden ahorraria {ta-tb} transiciones ({pct:.0f}%).")
        print("Para valorizarlo en horas falta el tiempo de cambio POR NIVEL (Produccion).")

    if sin_granel:
        print()
        print(f"--- {len(sin_granel)} SKU sin granel_grupo (quedan agrupados como '(vacio)') ---")
        for sku in sorted(sin_granel)[:20]:
            print(f"    {sku}  {(prm.get(sku,{}).get('desc') or '')[:44]}")

    if args.detalle:
        print()
        print("=== DETALLE POR SEMANA ===")
        for ln, lun, n, nd, niveles, tc, to, cron, opt in filas:
            print()
            print(f"--- {ln} · semana {lun} · {n} OFT en {nd} dias ---")
            print("  CRONOLOGICO (como lo propone el plan):")
            for o in cron:
                print(f"    {o['fecha']} emb={o['embalaje']:<3} {o['familia']:<8} "
                      f"{o['granel']:<18} {o['sku']} {o['desc']}")
            print("  OPTIMO (agrupado por niveles):")
            for o in opt:
                print(f"    {o['fecha']} emb={o['embalaje']:<3} {o['familia']:<8} "
                      f"{o['granel']:<18} {o['sku']} {o['desc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
