"""
soporte_contenido.py — Contenido del menú Soporte (Ayuda, glosario, Academia). Módulo PURO: no usa BD.

Fuente única en el repo: forecast/soporte_contenido/ (montado en /app/soporte_contenido).
Se publica con `git pull`, sin reiniciar: los archivos se releen cuando cambia su fecha de modificación.

    soporte_contenido/
      ayuda/pantallas/<id>.md     un artículo por pantalla (id = clave del tab en App.js)
      ayuda/faq.md · novedades.md · contacto.md   (artículos generales, mismo formato)
      ayuda/glosario.json         [{id, termino, nombre, definicion, sinonimos[], pantallas[]}]
      academia/rutas.json         {version, rutas:[{id, titulo, publico, orden, modulos:[{id, titulo, insignia, unidades[]}]}]}
      academia/unidades/<id>.md   unidad con cabecera + cuerpo + bloque ```cuestionario (JSON)
      img/                        pantallazos (<pantalla>__<paso>.png)

Formato de un .md:
    ---
    titulo: Plan de Producción
    seccion: Planificación
    resumen: Qué se va a producir, cuándo y en qué línea.
    orden: 20
    ---
    Cuerpo en Markdown. Términos del glosario: [[g:ss]]. Imágenes: ![texto](plan__1.png)

Cuestionario de una unidad (dentro del .md):
    ```cuestionario
    [{"id": "p1", "pregunta": "...", "opciones": ["A", "B", "C"], "correcta": 1, "explicacion": "..."}]
    ```
Archivos que empiezan con "_" no se listan (borradores / ejemplos), pero se pueden leer por id.

Sin PyYAML (no está en el contenedor): cabecera simple `clave: valor`, datos estructurados en JSON.

Validación de todo el contenido (correr antes de cada commit de contenido):
    docker exec -w /app traverso_forecast python3 soporte_contenido.py --validar
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent / "soporte_contenido"
DIR_PANTALLAS = BASE / "ayuda" / "pantallas"
DIR_AYUDA = BASE / "ayuda"
DIR_UNIDADES = BASE / "academia" / "unidades"
DIR_IMG = BASE / "img"
ARCH_GLOSARIO = DIR_AYUDA / "glosario.json"
ARCH_RUTAS = BASE / "academia" / "rutas.json"

ARTICULOS_GENERALES = ("faq", "novedades", "contacto")
RE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")              # ids seguros (sin rutas)
RE_IMG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}\.(png|jpg|jpeg|webp)$")
RE_BLOQUE_CUEST = re.compile(r"```cuestionario\s*\n(.*?)\n```", re.S)
RE_REF_GLOSARIO = re.compile(r"\[\[g:([a-z0-9_-]+)\]\]")
RE_IMG_MD = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
APROBACION_DEFECTO = 0.8
PUNTOS_DEFECTO = 100

_cache = {}   # ruta -> (mtime, valor)


class ContenidoError(ValueError):
    """Contenido inexistente o mal formado (el router lo traduce a 404/500)."""


# ── utilidades ────────────────────────────────────────────────────────────────
def normalizar(s: str) -> str:
    """minúsculas, sin tildes, espacios simples (búsqueda y nombres de persona)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def id_valido(x: str) -> bool:
    return bool(x) and bool(RE_ID.match(x))


def img_valida(nombre: str) -> bool:
    return bool(nombre) and bool(RE_IMG.match(nombre))


def _leer_cacheado(ruta: Path, parser):
    if not ruta.exists():
        raise ContenidoError(f"No existe: {ruta.relative_to(BASE)}")
    mt = ruta.stat().st_mtime
    hit = _cache.get(ruta)
    if hit and hit[0] == mt:
        return hit[1]
    valor = parser(ruta.read_text(encoding="utf-8"), ruta)
    _cache[ruta] = (mt, valor)
    return valor


def _parse_md(texto: str, ruta: Path) -> dict:
    """Separa cabecera `clave: valor` (entre líneas ---) del cuerpo."""
    texto = texto.replace("\r\n", "\n")
    meta, cuerpo = {}, texto
    if texto.startswith("---\n"):
        fin = texto.find("\n---", 4)
        if fin == -1:
            raise ContenidoError(f"{ruta.name}: cabecera sin cierre '---'")
        for n, linea in enumerate(texto[4:fin].split("\n"), start=2):
            if not linea.strip() or linea.lstrip().startswith("#"):
                continue
            if ":" not in linea:
                raise ContenidoError(f"{ruta.name}: línea {n} de la cabecera sin ':' -> {linea!r}")
            k, v = linea.split(":", 1)
            meta[k.strip()] = v.strip()
        cuerpo = texto[fin + 4:].lstrip("\n")
    return {"meta": meta, "cuerpo": cuerpo}


def _parse_json(texto: str, ruta: Path):
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise ContenidoError(f"{ruta.name}: JSON inválido ({e})")


def _entero(v, defecto):
    try:
        return int(v)
    except (TypeError, ValueError):
        return defecto


# ── Ayuda ─────────────────────────────────────────────────────────────────────
def _ruta_articulo(art_id: str) -> Path:
    if not id_valido(art_id) and not (art_id.startswith("_") and id_valido(art_id[1:])):
        raise ContenidoError(f"Id de artículo inválido: {art_id!r}")
    if art_id in ARTICULOS_GENERALES:
        return DIR_AYUDA / f"{art_id}.md"
    return DIR_PANTALLAS / f"{art_id}.md"


def leer_articulo(art_id: str) -> dict:
    d = _leer_cacheado(_ruta_articulo(art_id), _parse_md)
    m = d["meta"]
    return {"id": art_id, "titulo": m.get("titulo", art_id), "seccion": m.get("seccion", ""),
            "resumen": m.get("resumen", ""), "orden": _entero(m.get("orden"), 999),
            "actualizado": m.get("actualizado", ""), "cuerpo": d["cuerpo"]}


def listar_articulos() -> list:
    """Índice de Ayuda: artículos por pantalla + generales (sin cuerpo)."""
    salida = []
    rutas = sorted(DIR_PANTALLAS.glob("*.md")) if DIR_PANTALLAS.exists() else []
    rutas += [DIR_AYUDA / f"{g}.md" for g in ARTICULOS_GENERALES if (DIR_AYUDA / f"{g}.md").exists()]
    for r in rutas:
        if r.stem.startswith("_"):
            continue
        a = leer_articulo(r.stem)
        a.pop("cuerpo")
        a["tipo"] = "general" if r.stem in ARTICULOS_GENERALES else "pantalla"
        salida.append(a)
    return sorted(salida, key=lambda a: (a["tipo"] != "pantalla", a["orden"], a["titulo"]))


def glosario() -> list:
    if not ARCH_GLOSARIO.exists():
        return []
    g = _leer_cacheado(ARCH_GLOSARIO, _parse_json)
    return sorted(g, key=lambda t: normalizar(t.get("termino", "")))


# ── Academia ──────────────────────────────────────────────────────────────────
def rutas() -> dict:
    if not ARCH_RUTAS.exists():
        return {"version": 1, "rutas": []}
    return _leer_cacheado(ARCH_RUTAS, _parse_json)


def _leer_unidad_completa(unidad_id: str) -> dict:
    if not id_valido(unidad_id) and not (unidad_id.startswith("_") and id_valido(unidad_id[1:])):
        raise ContenidoError(f"Id de unidad inválido: {unidad_id!r}")
    d = _leer_cacheado(DIR_UNIDADES / f"{unidad_id}.md", _parse_md)
    m, cuerpo = d["meta"], d["cuerpo"]
    preguntas = []
    bloque = RE_BLOQUE_CUEST.search(cuerpo)
    if bloque:
        try:
            preguntas = json.loads(bloque.group(1))
        except json.JSONDecodeError as e:
            raise ContenidoError(f"{unidad_id}.md: cuestionario con JSON inválido ({e})")
        cuerpo = (cuerpo[:bloque.start()] + cuerpo[bloque.end():]).strip() + "\n"
    try:
        aprobacion = float(m.get("aprobacion", APROBACION_DEFECTO))
    except ValueError:
        aprobacion = APROBACION_DEFECTO
    return {"id": unidad_id, "titulo": m.get("titulo", unidad_id), "objetivo": m.get("objetivo", ""),
            "minutos": _entero(m.get("minutos"), None), "puntos": _entero(m.get("puntos"), PUNTOS_DEFECTO),
            "version": _entero(m.get("version"), 1), "aprobacion": aprobacion,
            "desafio": m.get("desafio", ""), "cuerpo": cuerpo, "preguntas": preguntas}


def leer_unidad(unidad_id: str) -> dict:
    """Unidad para el frontend: el cuestionario va SIN respuestas correctas ni explicaciones."""
    u = dict(_leer_unidad_completa(unidad_id))
    u["preguntas"] = [{"id": p["id"], "pregunta": p["pregunta"], "opciones": p["opciones"]}
                      for p in u["preguntas"]]
    return u


def corregir(unidad_id: str, respuestas: dict) -> dict:
    """Corrige en el backend. respuestas = {pregunta_id: índice de opción}."""
    u = _leer_unidad_completa(unidad_id)
    if not u["preguntas"]:
        raise ContenidoError(f"La unidad {unidad_id} no tiene cuestionario.")
    detalle, resultado = {}, []
    for p in u["preguntas"]:
        elegida = respuestas.get(p["id"])
        ok = elegida is not None and _entero(elegida, -1) == p["correcta"]
        detalle[p["id"]] = ok
        resultado.append({"id": p["id"], "correcta": ok, "opcion_correcta": p["correcta"],
                          "explicacion": p.get("explicacion", "")})
    correctas, total = sum(detalle.values()), len(u["preguntas"])
    pct = round(100 * correctas / total)
    return {"unidad_id": unidad_id, "version": u["version"], "correctas": correctas, "total": total,
            "puntaje_pct": pct, "aprobado": pct >= round(100 * u["aprobacion"]),
            "puntos": u["puntos"], "detalle": detalle, "preguntas": resultado}


def mapa_unidades() -> dict:
    """unidad_id -> {ruta, modulo, puntos}, según rutas.json."""
    m = {}
    for r in rutas().get("rutas", []):
        for mod in r.get("modulos", []):
            for uid in mod.get("unidades", []):
                try:
                    puntos = _leer_unidad_completa(uid)["puntos"]
                except ContenidoError:
                    puntos = PUNTOS_DEFECTO
                m[uid] = {"ruta": r["id"], "modulo": mod["id"], "puntos": puntos}
    return m


# ── Búsqueda (Ayuda y contexto de Mostacín) ──────────────────────────────────
def _fragmentos():
    """Divide artículos y unidades en fragmentos por título '## ' (unidad de búsqueda)."""
    frs = []
    fuentes = [("articulo", r.stem) for r in (sorted(DIR_PANTALLAS.glob("*.md")) if DIR_PANTALLAS.exists() else [])
               if not r.stem.startswith("_")]
    fuentes += [("articulo", g) for g in ARTICULOS_GENERALES if (DIR_AYUDA / f"{g}.md").exists()]
    fuentes += [("unidad", r.stem) for r in (sorted(DIR_UNIDADES.glob("*.md")) if DIR_UNIDADES.exists() else [])
                if not r.stem.startswith("_")]
    for tipo, fid in fuentes:
        d = leer_articulo(fid) if tipo == "articulo" else _leer_unidad_completa(fid)
        partes = re.split(r"\n(?=## )", "\n" + d["cuerpo"])
        for parte in partes:
            parte = parte.strip()
            if not parte:
                continue
            sub = parte.split("\n", 1)[0].lstrip("# ").strip() if parte.startswith("## ") else ""
            frs.append({"tipo": tipo, "id": fid, "titulo": d["titulo"], "subtitulo": sub, "texto": parte})
    for t in glosario():
        frs.append({"tipo": "glosario", "id": t.get("id", ""), "titulo": t.get("termino", ""),
                    "subtitulo": t.get("nombre", ""),
                    "texto": f"{t.get('termino','')} ({t.get('nombre','')}): {t.get('definicion','')}"
                             + (f" Sinónimos: {', '.join(t.get('sinonimos', []))}." if t.get("sinonimos") else "")})
    return frs


def buscar(q: str, limite: int = 10) -> list:
    """Búsqueda simple por palabras (sin tildes). Título y glosario pesan más que el cuerpo."""
    palabras = [p for p in normalizar(q).split() if len(p) >= 2]
    if not palabras:
        return []
    puntaje = []
    for f in _fragmentos():
        tit = normalizar(f"{f['titulo']} {f['subtitulo']}")
        txt = normalizar(f["texto"])
        s = 0
        for p in palabras:
            if p in tit:
                s += 3
            n = txt.count(p)
            if n:
                s += 1 + min(n, 5) * 0.2
        if f["tipo"] == "glosario" and s:
            s += 1
        if s:
            puntaje.append((s, f))
    puntaje.sort(key=lambda x: -x[0])
    salida = []
    for s, f in puntaje[:limite]:
        extracto = re.sub(r"\s+", " ", f["texto"])[:280]
        salida.append({**{k: f[k] for k in ("tipo", "id", "titulo", "subtitulo")},
                       "puntaje": round(s, 2), "extracto": extracto, "texto": f["texto"]})
    return salida


# ── Validación ────────────────────────────────────────────────────────────────
def validar() -> list:
    """Revisa todo el contenido. Devuelve lista de problemas (vacía = OK)."""
    prob = []
    ids_glosario = set()
    try:
        g = glosario()
        for t in g:
            for k in ("id", "termino", "definicion"):
                if not t.get(k):
                    prob.append(f"glosario: término sin '{k}': {t}")
            if t.get("id") in ids_glosario:
                prob.append(f"glosario: id repetido {t.get('id')}")
            ids_glosario.add(t.get("id"))
    except ContenidoError as e:
        prob.append(str(e))

    def revisar_cuerpo(origen, cuerpo):
        for ref in RE_REF_GLOSARIO.findall(cuerpo):
            if ref not in ids_glosario:
                prob.append(f"{origen}: [[g:{ref}]] no existe en el glosario")
        for img in RE_IMG_MD.findall(cuerpo):
            if img.startswith("http"):
                prob.append(f"{origen}: imagen externa no permitida: {img}")
            elif not img_valida(img):
                prob.append(f"{origen}: nombre de imagen inválido: {img}")
            elif not (DIR_IMG / img).exists():
                prob.append(f"{origen}: falta la imagen img/{img}")

    try:
        for a in listar_articulos():
            if not a["titulo"] or a["titulo"] == a["id"]:
                prob.append(f"artículo {a['id']}: falta 'titulo' en la cabecera")
            revisar_cuerpo(f"artículo {a['id']}", leer_articulo(a["id"])["cuerpo"])
    except ContenidoError as e:
        prob.append(str(e))

    unidades_en_rutas = set()
    try:
        for r in rutas().get("rutas", []):
            for k in ("id", "titulo"):
                if not r.get(k):
                    prob.append(f"rutas.json: ruta sin '{k}'")
            for mod in r.get("modulos", []):
                for uid in mod.get("unidades", []):
                    if uid in unidades_en_rutas:
                        prob.append(f"rutas.json: unidad {uid} aparece en más de un módulo")
                    unidades_en_rutas.add(uid)
                    if not (DIR_UNIDADES / f"{uid}.md").exists():
                        prob.append(f"rutas.json: módulo {mod.get('id')} referencia unidad inexistente {uid}")
    except ContenidoError as e:
        prob.append(str(e))

    for r in (sorted(DIR_UNIDADES.glob("*.md")) if DIR_UNIDADES.exists() else []):
        uid = r.stem
        try:
            u = _leer_unidad_completa(uid)
        except ContenidoError as e:
            prob.append(str(e))
            continue
        if not uid.startswith("_") and uid not in unidades_en_rutas:
            prob.append(f"unidad {uid}: no está en ninguna ruta de rutas.json")
        if not u["objetivo"]:
            prob.append(f"unidad {uid}: falta 'objetivo'")
        n = len(u["preguntas"])
        if n and not 3 <= n <= 5:
            prob.append(f"unidad {uid}: el cuestionario tiene {n} preguntas (se esperan 3 a 5)")
        vistos = set()
        for p in u["preguntas"]:
            pid = p.get("id")
            if not pid or pid in vistos:
                prob.append(f"unidad {uid}: pregunta sin id o id repetido ({pid})")
            vistos.add(pid)
            ops = p.get("opciones") or []
            if len(ops) < 2:
                prob.append(f"unidad {uid}/{pid}: menos de 2 opciones")
            if not isinstance(p.get("correcta"), int) or not 0 <= p["correcta"] < len(ops):
                prob.append(f"unidad {uid}/{pid}: 'correcta' fuera de rango")
            if not p.get("explicacion"):
                prob.append(f"unidad {uid}/{pid}: falta 'explicacion'")
        revisar_cuerpo(f"unidad {uid}", u["cuerpo"])
    return prob


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--validar", action="store_true", help="revisa todo el contenido")
    ap.add_argument("--buscar", help="prueba de búsqueda")
    a = ap.parse_args()
    if a.validar:
        p = validar()
        print(f"Artículos: {len(listar_articulos())} · Términos: {len(glosario())} · "
              f"Rutas: {len(rutas().get('rutas', []))} · Unidades en rutas: {len(mapa_unidades())}")
        print("Contenido OK" if not p else "PROBLEMAS:\n  - " + "\n  - ".join(p))
        raise SystemExit(1 if p else 0)
    elif a.buscar:
        for r in buscar(a.buscar):
            print(f"{r['puntaje']:5} {r['tipo']:9} {r['id']:18} {r['titulo']} › {r['subtitulo']}")
    else:
        ap.print_help()
