"""
router_soporte.py — Menú Soporte: Ayuda, glosario y Academia (12-11-2026).

Solo lectura del contenido (soporte_contenido.py) + avance de la Academia en mrp_db
(tablas de migrate_soporte.sql). NO toca plan, solver ni parámetros.
Mostacín (chat) va en un router aparte (etapa 3).

Endpoints:
  GET  /soporte/estado                          conteos de contenido (verificación rápida)
  GET  /soporte/ayuda/indice                    artículos (sin cuerpo)
  GET  /soporte/ayuda/articulo/{id}             artículo completo
  GET  /soporte/ayuda/glosario                  términos
  GET  /soporte/ayuda/buscar?q=&limite=         búsqueda en artículos, unidades y glosario
  GET  /soporte/img/{archivo}                   pantallazo (el frontend lo carga con fetch → blob)
  GET  /soporte/academia/rutas                  rutas → módulos → unidades (con título y puntos)
  GET  /soporte/academia/unidad/{id}            unidad SIN respuestas correctas
  POST /soporte/academia/personas               {nombre} → registra o recupera la persona
  GET  /soporte/academia/avance/{persona_id}    avance, puntos, insignias y certificados
  POST /soporte/academia/unidad/{id}/responder  {persona_id, respuestas} → corrige en el backend
  POST /soporte/academia/unidad/{id}/desafio    {persona_id} → marca el desafío práctico como hecho
  POST /soporte/academia/seguimiento            {pin} → vista de administración (PIN de edición)
"""
import json
import secrets
from typing import Dict, Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

import soporte_contenido as sc
from db_mrp import engine as _engine
from params_edicion import _verificar_pin   # mismo PIN que el panel de Parámetros

router = APIRouter(prefix="/soporte", tags=["Soporte"])


class PersonaIn(BaseModel):
    nombre: str


class RespuestasIn(BaseModel):
    persona_id: int
    respuestas: Dict[str, int]


class PersonaRefIn(BaseModel):
    persona_id: int


class PinIn(BaseModel):
    pin: Optional[str] = None


def _contenido(fn, *args):
    """Traduce errores de contenido a HTTP (404 si no existe, 500 si está mal formado)."""
    try:
        return fn(*args)
    except sc.ContenidoError as e:
        msg = str(e)
        raise HTTPException(404 if msg.startswith(("No existe", "Id de")) else 500, msg)


def _persona(c, persona_id: int) -> dict:
    fila = c.execute(sa.text("SELECT id, nombre FROM academia_personas WHERE id = :i"),
                     {"i": persona_id}).mappings().first()
    if not fila:
        raise HTTPException(404, f"Persona {persona_id} no registrada en la Academia.")
    return dict(fila)


# ── Estado ────────────────────────────────────────────────────────────────────
@router.get("/estado")
def estado():
    try:
        import claude_api
        ia = claude_api.configurado()
    except Exception:
        ia = False
    mapa = _contenido(sc.mapa_unidades)
    return {"articulos": len(_contenido(sc.listar_articulos)), "terminos": len(_contenido(sc.glosario)),
            "rutas": len(_contenido(sc.rutas).get("rutas", [])), "unidades": len(mapa), "api_claude": ia}


# ── Ayuda ─────────────────────────────────────────────────────────────────────
@router.get("/ayuda/indice")
def ayuda_indice():
    return _contenido(sc.listar_articulos)


@router.get("/ayuda/articulo/{art_id}")
def ayuda_articulo(art_id: str):
    return _contenido(sc.leer_articulo, art_id)


@router.get("/ayuda/glosario")
def ayuda_glosario():
    return _contenido(sc.glosario)


@router.get("/ayuda/buscar")
def ayuda_buscar(q: str = Query(..., min_length=2, max_length=200), limite: int = Query(10, ge=1, le=30)):
    res = _contenido(sc.buscar, q, limite)
    for r in res:
        r.pop("texto", None)   # el frontend solo necesita el extracto
    return res


@router.get("/img/{archivo}")
def imagen(archivo: str):
    if not sc.img_valida(archivo):
        raise HTTPException(400, "Nombre de imagen inválido.")
    ruta = sc.DIR_IMG / archivo
    if not ruta.exists():
        raise HTTPException(404, f"No existe la imagen {archivo}.")
    return FileResponse(ruta, headers={"Cache-Control": "max-age=3600"})


# ── Academia: contenido ───────────────────────────────────────────────────────
@router.get("/academia/rutas")
def academia_rutas():
    data = _contenido(sc.rutas)
    salida = []
    for r in sorted(data.get("rutas", []), key=lambda x: x.get("orden", 99)):
        modulos = []
        for m in r.get("modulos", []):
            unidades = []
            for uid in m.get("unidades", []):
                u = _contenido(sc.leer_unidad, uid)
                unidades.append({k: u[k] for k in ("id", "titulo", "objetivo", "minutos", "puntos")}
                                | {"tiene_desafio": bool(u["desafio"]), "n_preguntas": len(u["preguntas"])})
            modulos.append({**{k: m.get(k) for k in ("id", "titulo", "insignia")}, "unidades": unidades})
        salida.append({**{k: r.get(k) for k in ("id", "titulo", "publico", "orden")}, "modulos": modulos})
    return {"version": data.get("version", 1), "rutas": salida}


@router.get("/academia/unidad/{unidad_id}")
def academia_unidad(unidad_id: str):
    return _contenido(sc.leer_unidad, unidad_id)


# ── Academia: personas y avance ───────────────────────────────────────────────
@router.post("/academia/personas")
def academia_persona(p: PersonaIn):
    nombre = " ".join((p.nombre or "").split())
    if len(nombre) < 3:
        raise HTTPException(422, "Indica tu nombre y apellido.")
    if len(nombre) > 80:
        raise HTTPException(422, "Nombre demasiado largo (máx. 80 caracteres).")
    norm = sc.normalizar(nombre)
    with _engine.begin() as c:
        fila = c.execute(sa.text(
            "INSERT INTO academia_personas (nombre, nombre_norm) VALUES (:n, :nn) "
            "ON CONFLICT (nombre_norm) DO UPDATE SET ultimo_acceso = now() "
            "RETURNING id, nombre, (xmax = 0) AS nueva"), {"n": nombre, "nn": norm}).mappings().first()
    return dict(fila)


def _resumen_avance(c, persona_id: int) -> dict:
    filas = c.execute(sa.text(
        "SELECT unidad_id, estado, mejor_puntaje_pct, intentos, desafio_ok, aprobada_en "
        "FROM academia_avance WHERE persona_id = :p"), {"p": persona_id}).mappings().all()
    av = {f["unidad_id"]: dict(f) for f in filas}
    certs = {f["ruta_id"]: dict(f) for f in c.execute(sa.text(
        "SELECT ruta_id, codigo, emitido_en FROM academia_certificados WHERE persona_id = :p"),
        {"p": persona_id}).mappings().all()}
    mapa = sc.mapa_unidades()
    puntos = sum(mapa[u]["puntos"] for u, f in av.items() if f["estado"] == "aprobada" and u in mapa)
    rutas_out = []
    for r in sorted(sc.rutas().get("rutas", []), key=lambda x: x.get("orden", 99)):
        mods, total_u, aprob_u = [], 0, 0
        for m in r.get("modulos", []):
            us = m.get("unidades", [])
            ok = sum(1 for u in us if av.get(u, {}).get("estado") == "aprobada")
            total_u, aprob_u = total_u + len(us), aprob_u + ok
            mods.append({"id": m.get("id"), "titulo": m.get("titulo"), "insignia": m.get("insignia"),
                         "unidades": len(us), "aprobadas": ok, "insignia_ganada": bool(us) and ok == len(us)})
        rutas_out.append({"id": r["id"], "titulo": r.get("titulo"), "unidades": total_u, "aprobadas": aprob_u,
                          "avance_pct": round(100 * aprob_u / total_u) if total_u else 0,
                          "completa": total_u > 0 and aprob_u == total_u,
                          "certificado": certs.get(r["id"]), "modulos": mods})
    return {"puntos": puntos, "unidades": av, "rutas": rutas_out}


def _emitir_certificados(c, persona_id: int, resumen: dict, version_rutas: int):
    for r in resumen["rutas"]:
        if r["completa"] and not r["certificado"]:
            c.execute(sa.text(
                "INSERT INTO academia_certificados (persona_id, ruta_id, version_ruta, codigo) "
                "VALUES (:p, :r, :v, :cod) ON CONFLICT (persona_id, ruta_id, version_ruta) DO NOTHING"),
                {"p": persona_id, "r": r["id"], "v": version_rutas, "cod": secrets.token_hex(4).upper()})


@router.get("/academia/avance/{persona_id}")
def academia_avance(persona_id: int):
    with _engine.connect() as c:
        p = _persona(c, persona_id)
        try:
            return {"persona": p, **_resumen_avance(c, persona_id)}
        except sc.ContenidoError as e:
            raise HTTPException(500, str(e))


@router.post("/academia/unidad/{unidad_id}/responder")
def academia_responder(unidad_id: str, body: RespuestasIn):
    res = _contenido(sc.corregir, unidad_id, body.respuestas)
    with _engine.begin() as c:
        _persona(c, body.persona_id)
        c.execute(sa.text(
            "INSERT INTO academia_intentos (persona_id, unidad_id, version_contenido, respuestas, detalle, "
            "  correctas, total, puntaje_pct, aprobado) "
            "VALUES (:p, :u, :v, CAST(:r AS JSONB), CAST(:d AS JSONB), :ok, :t, :pct, :ap)"),
            {"p": body.persona_id, "u": unidad_id, "v": res["version"], "r": json.dumps(body.respuestas),
             "d": json.dumps(res["detalle"]), "ok": res["correctas"], "t": res["total"],
             "pct": res["puntaje_pct"], "ap": res["aprobado"]})
        c.execute(sa.text(
            "INSERT INTO academia_avance (persona_id, unidad_id, estado, mejor_puntaje_pct, intentos, "
            "  version_contenido, aprobada_en) "
            "VALUES (:p, :u, CASE WHEN :ap THEN 'aprobada' ELSE 'en_curso' END, :pct, 1, :v, "
            "        CASE WHEN :ap THEN now() END) "
            "ON CONFLICT (persona_id, unidad_id) DO UPDATE SET "
            "  intentos = academia_avance.intentos + 1, "
            "  mejor_puntaje_pct = GREATEST(academia_avance.mejor_puntaje_pct, EXCLUDED.mejor_puntaje_pct), "
            "  estado = CASE WHEN academia_avance.estado = 'aprobada' OR :ap THEN 'aprobada' ELSE 'en_curso' END, "
            "  aprobada_en = COALESCE(academia_avance.aprobada_en, EXCLUDED.aprobada_en), "
            "  version_contenido = EXCLUDED.version_contenido, actualizado_en = now()"),
            {"p": body.persona_id, "u": unidad_id, "ap": res["aprobado"], "pct": res["puntaje_pct"],
             "v": res["version"]})
        resumen = _resumen_avance(c, body.persona_id)
        _emitir_certificados(c, body.persona_id, resumen, sc.rutas().get("version", 1))
    res.pop("detalle")
    return res


@router.post("/academia/unidad/{unidad_id}/desafio")
def academia_desafio(unidad_id: str, body: PersonaRefIn):
    u = _contenido(sc.leer_unidad, unidad_id)
    if not u["desafio"]:
        raise HTTPException(422, f"La unidad {unidad_id} no tiene desafío práctico.")
    with _engine.begin() as c:
        _persona(c, body.persona_id)
        c.execute(sa.text(
            "INSERT INTO academia_avance (persona_id, unidad_id, desafio_ok, version_contenido) "
            "VALUES (:p, :u, true, :v) "
            "ON CONFLICT (persona_id, unidad_id) DO UPDATE SET desafio_ok = true, actualizado_en = now()"),
            {"p": body.persona_id, "u": unidad_id, "v": u["version"]})
    return {"ok": True}


# ── Seguimiento (administración, con PIN) ─────────────────────────────────────
@router.post("/academia/seguimiento")
def academia_seguimiento(body: PinIn):
    with _engine.connect() as c:
        _verificar_pin(c, body.pin)
        personas = c.execute(sa.text(
            "SELECT id, nombre, creado_en, ultimo_acceso FROM academia_personas ORDER BY nombre")).mappings().all()
        salida = []
        for p in personas:
            r = _resumen_avance(c, p["id"])
            salida.append({"id": p["id"], "nombre": p["nombre"], "ultimo_acceso": p["ultimo_acceso"],
                           "puntos": r["puntos"],
                           "rutas": [{k: x[k] for k in ("id", "titulo", "avance_pct", "completa", "certificado")}
                                     for x in r["rutas"]]})
        # Unidades con más dificultad (señal para mejorar el contenido)
        unidades = c.execute(sa.text(
            "SELECT unidad_id, count(*) AS intentos, round(100.0 * avg(CASE WHEN aprobado THEN 1 ELSE 0 END)) "
            "  AS tasa_aprobacion_pct, round(avg(puntaje_pct)) AS puntaje_medio_pct "
            "FROM academia_intentos GROUP BY unidad_id ORDER BY tasa_aprobacion_pct, intentos DESC")).mappings().all()
    return {"personas": salida, "unidades": [dict(u) for u in unidades]}
