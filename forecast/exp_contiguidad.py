#!/usr/bin/env python3
"""
exp_contiguidad.py — Programa nocturno: mide la contiguidad de bloque por SKU.

PREGUNTA
--------
La contiguidad prohibe el goteo diario (producir el mismo SKU todos los dias en
cantidades chicas). Medido en el plan #101, L1Pet LV semana 17-08: 20 batches de
solo 6 SKU. La restriccion deberia reducir eso a ~6 bloques.

El costo esperado es MAS EXCESO SOBRE SS: concentrar la produccion deja el stock
por encima del SS los dias siguientes, que es justo lo que el goteo evitaba. La
pregunta es cuanto, y si aparecen quiebres.

POR QUE HACE FALTA BANDA DE VARIANZA
------------------------------------
El gap de N2 tiene varianza propia (±4 puntos es propiedad de LNS, no de los
inputs). Una corrida contra una corrida no prueba nada: el 31-07 se atribuyo un
salto de Q* 10->36 a las campanas cuando en realidad habian cambiado DOS
variables. Por eso este programa corre N repeticiones de cada brazo, EN SERIE
(nunca en paralelo), y reporta rango y mediana.

BRAZOS
------
  A_base    : config actual (sin contiguidad)          -> baseline + varianza
  B_contig  : + SECUENCIA_CONTIG_SKU=1 en L1Pet LV     -> efecto de la restriccion

Todas las corridas con --no-promote: NO tocan el plan vigente.

METRICAS
--------
  batches, bloques (SKU-semana distintos), ratio batches/bloque
  quiebres (estado=QUIEBRE en detalle_diario, criterio intradia del 03-08)
  dias bajo SS, exceso sobre SS
  gap y status de cada pasada

Uso (dejar corriendo de noche):
    python3 /app/exp_contiguidad.py --reps 3 --horizonte 8 > /app/exp_contig.log 2>&1

Duracion estimada: reps x 2 brazos x ~70 min. Con reps=3 son ~7 h.
Elegir ventana lejos del cron del plan (10:00 UTC) y de faltantes/vigia.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

BRAZOS = {
    # baseline: config actual, para tener la banda de varianza
    "A_base": {},
    # EL IMPORTANTE: embalaje en un solo bloque contiguo por semana. Cada cambio
    # de embalaje exige reconfigurar la encajonadora, muy por encima del costo de
    # reanudar el mismo SKU. Medido en #101 semana 17-08: 4 cambios donde
    # alcanzaria 1.
    "B_emb": {"SECUENCIA_CONTIG_NIVELES": "embalaje",
              "SECUENCIA_CONTIG_LINEAS": "L1Pet LV"},
    # jerarquia completa: embalaje arriba, familia DENTRO de cada embalaje.
    # La clave del nivel 2 es (embalaje, familia), no solo familia: si fuera solo
    # familia se prohibiria que limon apareciera en los dos embalajes, poniendo
    # familia ARRIBA de embalaje e invirtiendo la jerarquia de costos.
    "C_emb_fam": {"SECUENCIA_CONTIG_NIVELES": "embalaje,familia",
                  "SECUENCIA_CONTIG_LINEAS": "L1Pet LV"},
    # secundario (el mas barato): prohibe reanudar el mismo SKU en la semana
    "D_sku": {"SECUENCIA_CONTIG_SKU": "1",
              "SECUENCIA_CONTIG_LINEAS": "L1Pet LV"},
}

# Config N2 de produccion (la misma del crontab) para que sea comparable.
ENV_BASE = {
    "N2_ENABLED": "1", "SS_COBERTURA": "1", "N2_BARRERA_MODO": "quiebre",
    "N2_WORKERS_C": "8", "N2_TL_C": "3600",
    "CAMPANA_GRANEL_ENABLED": "1", "CAMPANA_FORMATO_ENABLED": "1",
}


def metricas(linea_foco: str) -> dict:
    """Lee el ULTIMO plan persistido (aunque no sea vigente) y calcula metricas."""
    sys.path.insert(0, "/app")
    from sqlalchemy import text
    from db_mrp import SessionLocal
    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, snapshot FROM mrp_planes ORDER BY id DESC LIMIT 1")).mappings().first()
    if not row:
        return {}
    snap = row["snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap)

    out = {"plan_id": row["id"]}
    # batches vs bloques en la linea foco
    pares = set()
    nb = 0
    for o in (snap.get("ofts") or []):
        if (o.get("linea") or "").strip() != linea_foco:
            continue
        f = str(o.get("fecha_lanzamiento"))[:10]
        if not f or f == "None":
            continue
        d = dt.date.fromisoformat(f)
        lun = (d - dt.timedelta(days=d.weekday())).isoformat()
        pares.add((lun, o.get("sku")))
        nb += 1
    out["batches"] = nb
    out["bloques"] = len(pares)
    out["ratio"] = round(nb / len(pares), 2) if pares else 0

    # cambios de EMBALAJE en la secuencia cronologica real (la metrica clave)
    with SessionLocal() as s2:
        upc = {r[0]: int(r[1] or 0) for r in s2.execute(text(
            "SELECT sku, u_por_caja FROM mrp_sku_params")).fetchall()}
    porsem = {}
    for o in (snap.get("ofts") or []):
        if (o.get("linea") or "").strip() != linea_foco:
            continue
        f = str(o.get("fecha_lanzamiento"))[:10]
        if not f or f == "None":
            continue
        d = dt.date.fromisoformat(f)
        lun = (d - dt.timedelta(days=d.weekday())).isoformat()
        porsem.setdefault(lun, []).append((f, o.get("sku"), upc.get(o.get("sku"), 0)))
    camb = minimo = 0
    for lun, lst in porsem.items():
        lst.sort(key=lambda x: (x[0], x[1]))
        embs = [e for _f, _s, e in lst]
        camb += sum(1 for a, b in zip(embs, embs[1:]) if a != b)
        minimo += max(0, len(set(embs)) - 1)
    out["camb_emb"] = camb
    out["min_emb"] = minimo

    # cambios de FAMILIA (derivada del prefijo de granel_grupo) en la secuencia real
    with SessionLocal() as s3:
        gg = {r[0]: (r[1] or "").strip().lower() for r in s3.execute(text(
            "SELECT sku, granel_grupo FROM mrp_sku_params")).fetchall()}
    cf = 0
    for lun, lst in porsem.items():
        lst.sort(key=lambda x: (x[0], x[1]))
        fams = [(gg.get(sk, "").split("_")[0] or "?") for _f, sk, _e in lst]
        cf += sum(1 for a, b in zip(fams, fams[1:]) if a != b)
    out["camb_fam"] = cf

    # quiebres y SS (criterio intradia: estado ya viene con el fix del 03-08)
    q = bajo = exc = 0
    dd = snap.get("detalle_diario") or {}
    for _sku, serie in dd.items():
        for _f, c in serie.items():
            e = c.get("estado")
            if e == "QUIEBRE":
                q += 1
            elif e == "BAJO_SS":
                bajo += 1
            ss = c.get("ss_u") or 0
            sf = c.get("stock_fin_u")
            if ss and sf is not None and sf > ss:
                exc += 1
    out["quiebres"] = q
    out["bajo_ss"] = bajo
    out["exceso_ss"] = exc
    res = snap.get("resumen") or {}
    for k in ("gap", "status", "n_ordenes"):
        if k in res:
            out[k] = res[k]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--horizonte", type=int, default=8)
    ap.add_argument("--time-limit", type=int, default=1800)
    ap.add_argument("--linea", default="L1Pet LV")
    ap.add_argument("--brazos", default="A_base,B_emb,C_emb_fam")
    args = ap.parse_args()

    brazos = [b.strip() for b in args.brazos.split(",") if b.strip() in BRAZOS]
    print(f"=== exp_contiguidad · reps={args.reps} · brazos={brazos} ===")
    print(f"    horizonte={args.horizonte} TL={args.time_limit}s foco={args.linea}")
    print(f"    inicio {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"    EN SERIE, --no-promote: no toca el plan vigente")
    print()

    res = defaultdict(list)
    for rep in range(1, args.reps + 1):
        for b in brazos:
            env = dict(os.environ)
            env.update(ENV_BASE)
            env.update(BRAZOS[b])
            env["PYTHONPATH"] = "/app"
            t0 = time.time()
            print(f"[{dt.datetime.now():%H:%M:%S}] rep {rep}/{args.reps} · {b} ...",
                  flush=True)
            cmd = ["python3", "-u", "/app/cron_plan.py",
                   "--horizonte", str(args.horizonte),
                   "--time-limit", str(args.time_limit),
                   "--no-promote", "--skip-refresh"]
            try:
                p = subprocess.run(cmd, env=env, cwd="/app",
                                   capture_output=True, text=True, timeout=9000)
                ok = p.returncode == 0
                if not ok:
                    print(f"    FALLO rc={p.returncode}")
                    print("    " + (p.stderr or "")[-600:])
            except subprocess.TimeoutExpired:
                print("    TIMEOUT")
                ok = False
            dur = (time.time() - t0) / 60
            m = metricas(args.linea) if ok else {}
            m["rep"] = rep
            m["brazo"] = b
            m["min"] = round(dur, 1)
            m["ok"] = ok
            res[b].append(m)
            print(f"    -> {m}", flush=True)
            print()

    # ── resumen ─────────────────────────────────────────────────────────────
    print("=" * 78)
    print("RESUMEN")
    print("=" * 78)
    campos = ["camb_emb", "min_emb", "camb_fam", "batches", "ratio", "quiebres", "bajo_ss", "exceso_ss", "min"]
    print(f"{'brazo':<12}{'n':>3}" + "".join(f"{c:>12}" for c in campos))
    med = {}
    for b in brazos:
        oks = [m for m in res[b] if m.get("ok")]
        if not oks:
            print(f"{b:<12}{0:>3}   (sin corridas exitosas)")
            continue
        fila = f"{b:<12}{len(oks):>3}"
        med[b] = {}
        for c in campos:
            vs = sorted(m.get(c, 0) or 0 for m in oks)
            mid = vs[len(vs) // 2]
            med[b][c] = mid
            rng = f"{mid:g}" if len(set(vs)) == 1 else f"{mid:g}[{vs[0]:g}-{vs[-1]:g}]"
            fila += f"{rng:>12}"
        print(fila)

    otros = [b for b in brazos if b != "A_base" and b in med]
    if "A_base" in med and otros:
      for _ob in otros:
        a, b = med["A_base"], med[_ob]
        print()
        print(f"### {_ob} vs A_base ###")
        for c in ["camb_emb", "camb_fam", "batches", "ratio", "quiebres", "bajo_ss", "exceso_ss"]:
            d = b[c] - a[c]
            print(f"  {c:<12} {a[c]:>8g} -> {b[c]:>8g}   ({d:+g})")
        print()
        print("  Como leerlo:")
        print("   · camb_emb es LA metrica: debe caer hacia min_emb (1 por semana).")
        print("   · exceso_ss va a SUBIR: es el costo esperado de concentrar produccion.")
        print("   · quiebres: si suben, ver la DISTRIBUCION temporal antes de concluir.")
        print("     Concentrados en las primeras 2-3 semanas = transicion (se agotan).")
        print("     Repartidos en todo el horizonte = timing o estructura (atender).")
        print("   · comparar los deltas contra el RANGO del baseline: si el delta cae")
        print("     dentro de la varianza de A_base, no hay efecto demostrado.")
    print()
    print(f"fin {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
