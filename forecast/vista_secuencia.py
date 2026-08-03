#!/usr/bin/env python3
"""
vista_secuencia.py — Vista read-only del ordenamiento de secuencia por linea.

Genera un HTML autocontenido (sin dependencias, sin JS externo) que muestra:

  1. La jerarquia de niveles configurada para la linea, ordenada por costo.
  2. Por cada semana del plan: la secuencia ACTUAL contra la PROPUESTA, con
     bloques de ancho proporcional a la DURACION de cada corrida y los cambios
     marcados. Asi se ve de un vistazo que hay corridas de 20 min separadas por
     cambios de embalaje.
  3. El catalogo de graneles con su orden preferente.
  4. Las preguntas abiertas para Produccion.

NO modifica nada: lee el plan vigente, mrp_sku_params, mrp_graneles y mrp_lineas.

Se genera como HTML y no como pestana del dashboard a proposito: cero riesgo
para el frontend en produccion, y se puede proyectar o imprimir en la reunion.
Integrarlo como tab es el paso siguiente, si prueba util.

Uso:
    python3 /app/vista_secuencia.py --linea "L1Pet LV" --out /app/secuencia_L1PetLV.html
"""

import argparse
import datetime as dt
import html
import json
import sys
from collections import defaultdict

from sqlalchemy import text

# Niveles por linea, ordenados de MAS a MENOS caro (confirmado con Produccion
# 03-08: formato > embalaje > familia > sub-granel). Provisional hasta que exista
# la columna `nivel` en mrp_campana_reglas.
NIVELES = {
    "L1Pet LV": [
        ("formato",  "Formato",    "campana semanal (gate exclusivo)", "#0f766e"),
        ("embalaje", "Embalaje",   "u/caja - nivel 1",                 "#4f46e5"),
        ("familia",  "Familia",    "nivel 2",                          "#b45309"),
        ("granel",   "Sub-granel", "nivel 3 - el mas barato",          "#64748b"),
    ],
}

COLOR_EMB = {12: "#4f46e5", 20: "#0891b2", 30: "#7c3aed", 0: "#94a3b8"}
COLOR_FAM = {"vinagre": "#475569", "limon": "#ca8a04",
             "ketchup": "#b91c1c", "mostaza": "#a16207"}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     background:#f8fafc;color:#0f172a;padding:28px 32px 60px}
h1{font-size:22px;font-weight:650;letter-spacing:-.01em}
h2{font-size:15px;font-weight:650;margin:30px 0 12px;padding-bottom:7px;
   border-bottom:1px solid #e2e8f0;color:#1e293b}
.sub{color:#64748b;font-size:13px;margin-top:3px}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:9px;padding:12px 15px;
      min-width:132px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.card .k{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#64748b}
.card .v{font-size:21px;font-weight:650;margin-top:3px}
.card .n{font-size:11px;color:#94a3b8;margin-top:1px}
.niv{display:flex;gap:0;align-items:stretch;margin:14px 0 6px;flex-wrap:wrap}
.niv .lvl{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;
          margin-right:8px;position:relative;min-width:150px}
.niv .lvl .bar{height:3px;border-radius:2px;margin-bottom:8px}
.niv .lvl .t{font-weight:650;font-size:13px}
.niv .lvl .d{font-size:11px;color:#64748b;margin-top:2px}
.niv .arrow{align-self:center;color:#cbd5e1;font-size:18px;margin-right:8px}
.wk{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:15px 17px;
    margin-bottom:13px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.wkh{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:11px}
.wkh .ttl{font-weight:650;font-size:14px}
.wkh .meta{font-size:12px;color:#64748b}
.row{margin:9px 0}
.row .lab{font-size:11px;text-transform:uppercase;letter-spacing:.04em;
          color:#64748b;margin-bottom:4px;display:flex;justify-content:space-between}
.row .lab b{color:#0f172a;font-weight:600;text-transform:none;letter-spacing:0;font-size:12px}
.seq{display:flex;height:38px;border-radius:6px;overflow:hidden;
     border:1px solid #e2e8f0;background:#f1f5f9}
.blk{position:relative;display:flex;align-items:center;justify-content:center;
     min-width:3px;overflow:hidden}
.blk .fam{position:absolute;left:0;right:0;bottom:0;height:4px}
.blk span{font-size:9.5px;color:#fff;font-weight:600;white-space:nowrap;
          text-shadow:0 1px 1px rgba(0,0,0,.25);padding:0 2px}
.cut{width:3px;background:#dc2626;flex:none}
.day{width:1px;background:#fff;flex:none;opacity:.85}
.dayhdr{display:flex;font-size:9.5px;color:#94a3b8;margin-bottom:2px}
.dayhdr div{text-align:center;border-left:1px solid #e2e8f0;padding-left:2px}
.mx{border-collapse:collapse;font-size:11.5px;margin-top:9px;width:100%}
.mx th{background:transparent;color:#64748b;font-size:10px;padding:3px 4px;
       text-transform:none;letter-spacing:0;font-weight:600;text-align:center}
.mx th.sk{text-align:left;font-family:ui-monospace,monospace;font-size:11px}
.mx td{border:none;padding:2px 3px;text-align:center}
.mx td.sk{text-align:left;font-family:ui-monospace,monospace;color:#334155;
          white-space:nowrap;padding-right:9px}
.mx .cell{display:block;height:17px;border-radius:3px;background:#f1f5f9;
          line-height:17px;font-size:9.5px;color:#fff;font-weight:600}
.mx tr.multi td.sk{color:#b91c1c;font-weight:650}
.mx .n{color:#b91c1c;font-weight:650;font-size:11px}
.cut.f{background:#f59e0b}
.cut.g{background:#cbd5e1}
.lg{display:flex;gap:15px;flex-wrap:wrap;margin:10px 0 0;font-size:11.5px;color:#475569}
.lg i{display:inline-block;width:11px;height:11px;border-radius:3px;
      margin-right:5px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e2e8f0;
      border-radius:9px;overflow:hidden;font-size:13px}
th{background:#f1f5f9;text-align:left;padding:8px 11px;font-size:11px;
   text-transform:uppercase;letter-spacing:.04em;color:#475569;font-weight:600}
td{padding:7px 11px;border-top:1px solid #f1f5f9}
.ask{background:#fff;border:1px solid #e2e8f0;border-left:3px solid #0f766e;
     border-radius:8px;padding:13px 16px;margin-top:10px}
.ask ol{margin-left:17px}
.ask li{margin:5px 0}
.ask .blank{display:inline-block;min-width:120px;border-bottom:1px dashed #94a3b8;
            margin-left:6px}
.warn{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;
      padding:11px 15px;font-size:13px;color:#78350f;margin-top:11px}
.ok{color:#047857;font-weight:600}
.bad{color:#b91c1c;font-weight:600}
footer{margin-top:34px;font-size:11.5px;color:#94a3b8;border-top:1px solid #e2e8f0;
       padding-top:12px}
"""


def esc(x):
    return html.escape(str(x))


def bloques_html(seq, total_min, niveles_activos):
    """Barra de bloques con ancho proporcional a la duracion + cortes marcados."""
    out = []
    prev = None
    for o in seq:
        if prev is not None:
            if prev["embalaje"] != o["embalaje"]:
                out.append('<div class="cut" title="cambio de EMBALAJE"></div>')
            elif prev["familia"] != o["familia"]:
                out.append('<div class="cut f" title="cambio de FAMILIA"></div>')
            elif prev["granel"] != o["granel"]:
                out.append('<div class="cut g" title="cambio de sub-granel"></div>')
        pct = (o["min"] / total_min * 100) if total_min else 0
        col = COLOR_EMB.get(o["embalaje"], "#94a3b8")
        fam = COLOR_FAM.get(o["familia"], "#94a3b8")
        lbl = f'{o["min"]:.0f}\u2032' if pct > 3.2 else ""
        tip = (f'{o["sku"]} · {o["desc"]} · emb {o["embalaje"]} · {o["familia"]}'
               f' · {o["granel"]} · {o["cajas"]:.0f} cj · {o["min"]:.0f} min'
               f' · {o["fecha"]}')
        out.append(
            f'<div class="blk" style="width:{pct:.3f}%;background:{col}" title="{esc(tip)}">'
            f'<span>{lbl}</span><div class="fam" style="background:{fam}"></div></div>')
        prev = o
    return "".join(out)


def barra_dias(seq, total_min):
    """Barra cronologica: bloques en el orden REAL del plan, con separador de dia."""
    out = []
    prev = None
    for o in seq:
        if prev is not None:
            if prev["fecha"] != o["fecha"]:
                out.append('<div class="day" title="cambio de dia"></div>')
            if prev["embalaje"] != o["embalaje"]:
                out.append('<div class="cut" title="cambio de EMBALAJE"></div>')
            elif prev["familia"] != o["familia"]:
                out.append('<div class="cut f" title="cambio de FAMILIA"></div>')
            elif prev["granel"] != o["granel"]:
                out.append('<div class="cut g" title="cambio de sub-granel"></div>')
        pct = (o["min"] / total_min * 100) if total_min else 0
        col = COLOR_EMB.get(o["embalaje"], "#94a3b8")
        fam = COLOR_FAM.get(o["familia"], "#94a3b8")
        lbl = f'{o["min"]:.0f}\u2032' if pct > 3.2 else ""
        tip = (f'{o["sku"]} · {o["desc"]} · emb {o["embalaje"]} · {o["familia"]}'
               f' · {o["granel"]} · {o["cajas"]:.0f} cj · {o["min"]:.0f} min'
               f' · {o["fecha"]}')
        out.append(
            f'<div class="blk" style="width:{pct:.3f}%;background:{col}" title="{esc(tip)}">'
            f'<span>{lbl}</span><div class="fam" style="background:{fam}"></div></div>')
        prev = o
    return "".join(out)


def matriz_goteo(ofts):
    """Matriz SKU x dia: hace visible el goteo (mismo SKU partido en varios dias)."""
    dias = sorted({o["fecha"] for o in ofts})
    por = defaultdict(dict)
    for o in ofts:
        c = por[o["sku"]].get(o["fecha"])
        por[o["sku"]][o["fecha"]] = (c or 0) + o["min"]
    ordenado = sorted(por.items(), key=lambda x: (-len(x[1]), x[0]))
    H = ["<table class='mx'><tr><th class='sk'>SKU</th>"]
    for d in dias:
        H.append(f"<th>{esc(d[-2:])}</th>")
    H.append("<th>días</th></tr>")
    for sku, celdas in ordenado:
        multi = len(celdas) > 1
        H.append(f"<tr class='{'multi' if multi else ''}'>"
                 f"<td class='sk'>{esc(sku)}</td>")
        for d in dias:
            if d in celdas:
                mi = celdas[d]
                H.append(f"<td><span class='cell' style='background:#4f46e5' "
                         f"title='{esc(sku)} · {d} · {mi:.0f} min'>{mi:.0f}</span></td>")
            else:
                H.append("<td><span class='cell'></span></td>")
        H.append(f"<td class='{'n' if multi else ''}'>{len(celdas)}</td></tr>")
    H.append("</table>")
    nm = sum(1 for _s, c in por.items() if len(c) > 1)
    ex = sum(len(c) - 1 for c in por.values())
    if ex:
        H.append(f"<div class='sub'><b>{nm}</b> SKU se producen en más de un día "
                 f"(<b>{ex}</b> arranques de más). Cada fila roja es un SKU "
                 f"partido: mismo producto, misma semana, varias puestas en marcha.</div>")
    return "".join(H)


def transiciones(seq):
    t = {"embalaje": 0, "familia": 0, "granel": 0}
    for a, b in zip(seq, seq[1:]):
        if a["embalaje"] != b["embalaje"]:
            t["embalaje"] += 1
        elif a["familia"] != b["familia"]:
            t["familia"] += 1
        elif a["granel"] != b["granel"]:
            t["granel"] += 1
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--linea", default="L1Pet LV")
    ap.add_argument("--out", default="/app/secuencia.html")
    args = ap.parse_args()

    sys.path.insert(0, "/app")
    from db_mrp import SessionLocal

    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT id, snapshot FROM mrp_planes WHERE vigente LIMIT 1")).mappings().first()
        prm = {r[0]: dict(desc=r[1] or "", fmt=(r[2] or "").strip(),
                          upc=int(r[3] or 0), gr=(r[4] or "").strip(),
                          bmin=int(r[5] or 0))
               for r in s.execute(text(
                   "SELECT sku, descripcion, formato, u_por_caja, granel_grupo, "
                   "batch_min_u FROM mrp_sku_params")).fetchall()}
        cat = {r[0]: dict(fam=r[1], of=int(r[2] or 0), og=int(r[3] or 0), nt=r[4] or "")
               for r in s.execute(text(
                   "SELECT granel_grupo, familia, orden_familia, orden_granel, notas "
                   "FROM mrp_graneles")).fetchall()}
        ln = s.execute(text(
            "SELECT velocidad_u_hr, turnos_dia, horas_turno, dias_semana FROM mrp_lineas "
            "WHERE codigo = :c"), {"c": args.linea}).first()
        reglas = s.execute(text(
            "SELECT recurso, dimension, modos, max_modos_semana, linea FROM "
            "mrp_campana_reglas WHERE activo")).mappings().all()

    if not row:
        print("sin plan vigente")
        return 1
    vel = float(ln[0]) if ln else 1.0
    cap_dia_h = (float(ln[1]) * float(ln[2])) if ln else 0.0
    snap = row["snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap)

    # ── armar OFTs de la linea ───────────────────────────────────────────────
    sem = defaultdict(list)
    for o in (snap.get("ofts") or []):
        if (o.get("linea") or "").strip() != args.linea:
            continue
        f = str(o.get("fecha_lanzamiento"))[:10]
        if not f or f == "None":
            continue
        sku = o.get("sku")
        p = prm.get(sku, {})
        c = cat.get(p.get("gr", ""), {})
        cj = float(o.get("cantidad_cajas") or 0)
        u = cj * p.get("upc", 0)
        d = dt.date.fromisoformat(f)
        lun = (d - dt.timedelta(days=d.weekday())).isoformat()
        sem[lun].append(dict(
            sku=sku, fecha=f, cajas=cj, u=u, min=(u / vel * 60) if vel else 0,
            formato=p.get("fmt", ""), embalaje=p.get("upc", 0),
            granel=p.get("gr") or "(sin granel)",
            familia=c.get("fam", "(sin cat)"),
            of=c.get("of", 99), og=c.get("og", 99),
            desc=(p.get("desc") or "")[:44], bmin=p.get("bmin", 0),
        ))

    if not sem:
        print(f"sin OFTs para {args.linea} en el plan #{row['id']}")
        return 1

    niveles = NIVELES.get(args.linea, [])
    nivel_keys = [k for k, _t, _d, _c in niveles if k != "formato"]

    # ── metricas globales ────────────────────────────────────────────────────
    todos = [o for v in sem.values() for o in v]
    tot_min = sum(o["min"] for o in todos)
    cortas = sum(1 for o in todos if o["min"] < 30)
    ta = {"embalaje": 0, "familia": 0, "granel": 0}
    tb = {"embalaje": 0, "familia": 0, "granel": 0}
    dup = 0
    bloques = []
    for lun in sorted(sem):
        ofts = sem[lun]
        act = sorted(ofts, key=lambda x: (x["fecha"], x["sku"]))
        prop = sorted(ofts, key=lambda x: (x["embalaje"], x["of"], x["og"], x["sku"]))
        a, b = transiciones(act), transiciones(prop)
        for k in ta:
            ta[k] += a[k]
            tb[k] += b[k]
        cnt = defaultdict(int)
        for o in ofts:
            cnt[o["sku"]] += 1
        dup += sum(v - 1 for v in cnt.values() if v > 1)
        bloques.append((lun, ofts, act, prop, a, b))

    # ── HTML ─────────────────────────────────────────────────────────────────
    H = []
    H.append(f"<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
             f"<title>Secuencia · {esc(args.linea)}</title><style>{CSS}</style></head><body>")
    H.append(f"<h1>Secuenciación · {esc(args.linea)}</h1>"
             f"<div class='sub'>Plan #{row['id']} · velocidad {vel:,.0f} u/hr · "
             f"{cap_dia_h:.0f} h/día · generado {dt.date.today().isoformat()}</div>")

    # jerarquia
    H.append("<h2>Jerarquía de niveles — de más a menos caro</h2>")
    H.append("<div class='niv'>")
    for i, (k, t, d, c) in enumerate(niveles):
        H.append(f"<div class='lvl'><div class='bar' style='background:{c}'></div>"
                 f"<div class='t'>{esc(t)}</div><div class='d'>{esc(d)}</div></div>")
        if i < len(niveles) - 1:
            H.append("<div class='arrow'>&rsaquo;</div>")
    H.append("</div>")
    H.append("<div class='sub'>El nivel más caro va arriba: así cambia menos veces. "
             "El formato ya está resuelto por la campaña semanal (un solo formato por semana).</div>")

    # metricas
    ev = ta["embalaje"] - tb["embalaje"]
    H.append("<h2>Situación del plan vigente</h2><div class='cards'>")
    for k, v, n in [
        ("Corridas", f"{len(todos)}", f"{tot_min/60:.0f} h de máquina"),
        ("Corrida media", f"{tot_min/len(todos):.0f}\u2032", f"{cortas} bajo 30 min"),
        ("Uso de línea", f"{tot_min/60/(cap_dia_h*5*len(sem))*100:.0f}%",
         f"{cap_dia_h*5*len(sem):.0f} h disponibles"),
        ("Cambios de embalaje", f"{ta['embalaje']}", f"mínimo posible: {tb['embalaje']}"),
        ("Mín. teórico embalaje", f"{tb['embalaje']}", f"hoy {ta['embalaje']} · requiere reasignar días"),
        ("Batches repetidos", f"{dup}", "mismo SKU 2+ veces por semana"),
    ]:
        H.append(f"<div class='card'><div class='k'>{esc(k)}</div>"
                 f"<div class='v'>{esc(v)}</div><div class='n'>{esc(n)}</div></div>")
    H.append("</div>")

    # secuencia real por semana
    H.append("<h2>Secuencia real del plan, semana por semana</h2>")
    H.append("<div class='sub'>Orden cronológico tal como el plan lo propone. "
             "Los bloques NO se reordenan: agrupar exige mover producción entre "
             "días, y eso lo decide el optimizador, no una vista.</div>")
    H.append("<div class='lg'>"
             + "".join(f"<span><i style='background:{c}'></i>embalaje {k}</span>"
                       for k, c in COLOR_EMB.items() if k)
             + "".join(f"<span><i style='background:{c};height:5px;border-radius:2px'></i>"
                       f"{esc(f)}</span>" for f, c in COLOR_FAM.items() if f in
                       {o['familia'] for o in todos})
             + "<span><i style='background:#dc2626;width:4px'></i>cambio de embalaje</span>"
               "<span><i style='background:#f59e0b;width:4px'></i>cambio de familia</span>"
               "<span><i style='background:#cbd5e1;width:4px'></i>cambio de sub-granel</span>"
               "<span><i style='background:#fff;width:3px;border:1px solid #cbd5e1'></i>fin de día</span>"
             + "</div>")

    for lun, ofts, act, prop, a, b in bloques:
        tmin = sum(o["min"] for o in ofts)
        fmts = sorted({o["formato"] for o in ofts if o["formato"]})
        d0 = dt.date.fromisoformat(lun)
        H.append("<div class='wk'>")
        H.append(f"<div class='wkh'><div class='ttl'>Semana del "
                 f"{d0.strftime('%d-%m')}</div>"
                 f"<div class='meta'>{len(ofts)} corridas · {tmin/60:.1f} h · "
                 f"formato {esc('/'.join(fmts) or '-')}</div></div>")
        n_emb = len({o["embalaje"] for o in ofts})
        H.append(f"<div class='row'><div class='lab'>"
                 f"<span>Secuencia cronológica · las marcas blancas separan días</span>"
                 f"<b class='bad'>{a['embalaje']} cambios de embalaje</b></div>"
                 f"<div class='seq'>{barra_dias(act, tmin)}</div></div>")
        H.append(f"<div class='sub'>Mínimo teórico si los embalajes se produjeran "
                 f"en bloques contiguos: <b>{max(0, n_emb-1)}</b> cambio(s). "
                 f"Alcanzarlo requiere que el optimizador reasigne días, "
                 f"no basta reordenar.</div>")
        H.append(matriz_goteo(ofts))
        H.append("</div>")

    H.append("<div class='warn'><b>Cómo leer los bloques:</b> el ancho es "
             "proporcional a la duración de la corrida y las líneas verticales "
             "marcan los cambios. Muchos bloques angostos separados por líneas rojas "
             "significan corridas cortas con cambios costosos en medio. Pasar el mouse "
             "sobre un bloque muestra el SKU, el granel y los minutos. La matriz "
             "de abajo muestra qué SKU se parten en varios días.</div>")

    # catalogo
    H.append("<h2>Orden preferente de graneles</h2><table>"
             "<tr><th>Familia</th><th>Orden</th><th>Granel</th><th>SKU en la línea</th>"
             "<th>Nota</th></tr>")
    usados = defaultdict(int)
    for o in todos:
        usados[o["granel"]] += 1
    for g, c in sorted(cat.items(), key=lambda x: (x[1]["of"], x[1]["og"])):
        if c["fam"] in ("ketchup", "mostaza"):
            continue
        col = COLOR_FAM.get(c["fam"], "#94a3b8")
        H.append(f"<tr><td><i style='display:inline-block;width:10px;height:10px;"
                 f"border-radius:2px;background:{col};margin-right:6px'></i>"
                 f"{esc(c['fam'])}</td><td>{c['of']}.{c['og']}</td>"
                 f"<td><b>{esc(g)}</b></td><td>{usados.get(g,0)}</td>"
                 f"<td class='sub'>{esc(c['nt'])}</td></tr>")
    H.append("</table>")

    # preguntas
    H.append("<h2>Para confirmar con Producción</h2><div class='ask'><ol>")
    for q in [
        "Cambio de <b>embalaje</b> (12↔30 u/caja, mismo formato): minutos, operarios, merma",
        "Cambio de <b>sub-granel</b> dentro de la familia (blanco→manzana): ídem",
        "Cambio entre <b>familias</b> (vinagre→limón): ídem",
        "¿El orden incoloro → manzana → blanco → rosado es el correcto?",
        "¿Hay 5 recetas de limón distintas según marca, o basta limón / limón pica?",
        "¿Orden preferido dentro de limón? ¿Y entre familias (limón antes que vinagre)?",
    ]:
        H.append(f"<li>{q}<span class='blank'></span></li>")
    H.append("</ol></div>")

    # reglas vigentes
    H.append("<h2>Campañas configuradas hoy (solo lectura)</h2><table>"
             "<tr><th>Recurso</th><th>Dimensión</th><th>Modos</th>"
             "<th>Máx/semana</th><th>Línea</th></tr>")
    for r in reglas:
        H.append(f"<tr><td><b>{esc(r['recurso'])}</b></td><td>{esc(r['dimension'])}</td>"
                 f"<td>{esc(', '.join(r['modos'] or []))}</td>"
                 f"<td>{esc(r['max_modos_semana'])}</td>"
                 f"<td>{esc(r['linea'] or '(toda la planta)')}</td></tr>")
    H.append("</table>")

    H.append("<footer>Vista de solo lectura generada desde el plan vigente. "
             "No modifica parámetros ni el plan. La propuesta es un reordenamiento "
             "Muestra el plan tal como es, sin reordenar: agrupar exige mover "
             "producción entre días y eso lo resuelve el optimizador."
             "</footer></body></html>")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("".join(H))
    print(f"generado: {args.out}")
    print(f"  {len(todos)} corridas · {tot_min/60:.1f} h · "
          f"cambios de embalaje {ta['embalaje']} -> {tb['embalaje']} (evitables {ev})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
