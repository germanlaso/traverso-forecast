"""
params_edicion.py — Fase 2 del Diagnóstico de Parámetros: EDICIÓN con validación.

Reglas (decisiones 10-11-2026):
  · La BD manda. El Excel queda solo para cargas masivas controladas.
  · Editar requiere PIN de edición + nombre de quien edita + motivo. Consultar es libre.
  · La validación es la MISMA del diagnóstico (params_diagnostico.diagnosticar_sku):
      🔴 error  -> bloquea el guardado (batch > capacidad diaria, cap. bodega < batch, velocidad 0)
      🟡 warn   -> se informa y se permite guardar (batch < 3 h, cap. bodega < batch + SS, ...)
  · Cada cambio queda en mrp_params_historial (valor anterior -> nuevo) y se puede revertir.
  · Los cambios aplican en la PRÓXIMA corrida del plan (cron nocturno o corrida manual).

Campos editables:
  SKU (global, todas sus líneas):  batch_min_u, cap_bodega_u
  SKU × línea:                     factor_velocidad
  Línea (afecta todos sus SKU):    velocidad_u_hr, turnos_dia, horas_turno, dias_semana

PIN: se define una vez dentro del contenedor:
  docker exec -it traverso_forecast python3 /app/params_edicion.py --set-pin
"""
import argparse
import getpass
import json
import hashlib
import hmac
import secrets
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import params_diagnostico as _pd
from db_mrp import engine as _engine

router = APIRouter(prefix="/params", tags=["Parametros"])

AVISO_APLICACION = "Los cambios aplican en la próxima corrida del plan (cron nocturno o corrida manual)."

CAMPOS_SKU = {"batch_min_u": int, "cap_bodega_u": int}
CAMPOS_SKU_LINEA = {"factor_velocidad": float}
CAMPOS_LINEA = {"velocidad_u_hr": float, "turnos_dia": int, "horas_turno": float, "dias_semana": int}
LIMITES = {
    "batch_min_u": (1, 10_000_000),
    "cap_bodega_u": (1, _pd.CAP_BODEGA_INFINITA),     # 999999 = sin límite
    "factor_velocidad": (0.05, 3.0),
    "velocidad_u_hr": (1, 1_000_000),
    "turnos_dia": (1, 3),
    "horas_turno": (1, 12),
    "dias_semana": (1, 7),
}
ETIQUETAS = {
    "batch_min_u": "Batch mínimo", "cap_bodega_u": "Cap. bodega", "factor_velocidad": "Factor de velocidad",
    "velocidad_u_hr": "Velocidad de línea", "turnos_dia": "Turnos por día", "horas_turno": "Horas por turno",
    "dias_semana": "Días por semana",
}


# ── PIN ───────────────────────────────────────────────────────────────────────
def _hash_pin(pin: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), sal.encode(), 200_000).hex()


def _pin_configurado(c) -> bool:
    return c.execute(sa.text("SELECT 1 FROM mrp_params_config WHERE clave = 'pin_edicion'")).first() is not None


def _verificar_pin(c, pin: Optional[str]):
    fila = c.execute(sa.text("SELECT valor FROM mrp_params_config WHERE clave = 'pin_edicion'")).scalar()
    if not fila:
        raise HTTPException(503, "No hay PIN de edición configurado. Definirlo con: "
                                 "docker exec -it traverso_forecast python3 /app/params_edicion.py --set-pin")
    sal, h = fila.split("$", 1)
    if not pin or not hmac.compare_digest(_hash_pin(str(pin), sal), h):
        raise HTTPException(403, "PIN de edición incorrecto.")


def _verificar_identidad(editor: Optional[str], motivo: Optional[str]):
    if not editor or len(editor.strip()) < 3:
        raise HTTPException(422, "Indica tu nombre (quien edita).")
    if not motivo or len(motivo.strip()) < 5:
        raise HTTPException(422, "Indica el motivo del cambio.")


# ── Lectura de datos ──────────────────────────────────────────────────────────
def _forecast():
    """Forecast semanal (cj) por SKU desde el plan vigente; {} si no está disponible."""
    try:
        import main as _main
        return _main._forecast_semanal_cj_desde_plan() or {}
    except Exception:
        return {}


def _cargar(c):
    lineas = {r.codigo: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_lineas"))}
    prods = {r.sku: dict(r._mapping) for r in c.execute(sa.text("SELECT * FROM mrp_sku_params"))}
    pares = [dict(r._mapping) for r in c.execute(sa.text(
        "SELECT sku, linea, t_cambio_hrs, preferida, factor_velocidad FROM mrp_sku_lineas"))]
    return lineas, prods, pares


DIAS = ["L", "M", "X", "J", "V", "S", "D"]


def _validar_turnos(v) -> list:
    """(11-11-2026) Valida turnos_config: 1 a 3 turnos, 7 horas cada uno (0-12 h por turno),
    a lo sumo 24 h por día sumando turnos. Devuelve la lista normalizada."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            raise HTTPException(422, "Turnos: formato inválido.")
    if not isinstance(v, list) or not 1 <= len(v) <= 3:
        raise HTTPException(422, "Debe haber entre 1 y 3 turnos.")
    out = []
    for i, t in enumerate(v):
        h = (t or {}).get("horas") if isinstance(t, dict) else None
        if not isinstance(h, list) or len(h) != 7:
            raise HTTPException(422, f"Turno {i + 1}: se esperan 7 valores (L a D).")
        try:
            h = [round(float(x or 0), 2) for x in h]
        except (TypeError, ValueError):
            raise HTTPException(422, f"Turno {i + 1}: horas inválidas.")
        if any(x < 0 or x > 12 for x in h):
            raise HTTPException(422, f"Turno {i + 1}: cada día debe tener entre 0 y 12 h.")
        item = {"turno": i + 1, "horas": h}
        # (11-11-2026) vigencia opcional (temporadas, eventos): desde / hasta, vacío = sin límite
        from datetime import date as _date
        des, has = (t.get("desde") or None), (t.get("hasta") or None)
        if (des or has) and i == 0:
            raise HTTPException(422, "El turno 1 es la jornada base: no lleva fechas de vigencia.")
        try:
            d1 = _date.fromisoformat(str(des)[:10]) if des else None
            d2 = _date.fromisoformat(str(has)[:10]) if has else None
        except ValueError:
            raise HTTPException(422, f"Turno {i + 1}: fechas de vigencia inválidas (YYYY-MM-DD).")
        if d1 and d2 and d2 < d1:
            raise HTTPException(422, f"Turno {i + 1}: la fecha 'hasta' es anterior a 'desde'.")
        if d1:
            item["desde"] = d1.isoformat()
        if d2:
            item["hasta"] = d2.isoformat()
        out.append(item)
    for d in range(7):
        if sum(t["horas"][d] for t in out) > 24:
            raise HTTPException(422, f"{DIAS[d]}: la suma de turnos supera 24 h.")
    if sum(sum(t["horas"]) for t in out) <= 0:
        raise HTTPException(422, "La línea quedaría sin horas en la semana.")
    return out


def _separar_linea(cambios: Optional[dict]) -> dict:
    """Cambios de línea: numéricos validados con _limpiar + turnos_config validado aparte."""
    cambios = dict(cambios or {})
    tc = cambios.pop("turnos_config", None)
    out = _limpiar(cambios, CAMPOS_LINEA)
    if tc is not None:
        out["turnos_config"] = _validar_turnos(tc)
    return out


def _json_tc(v):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return v
    return json.dumps(v, sort_keys=True)


def _limpiar(cambios: Optional[dict], permitidos: dict) -> dict:
    out = {}
    for k, v in (cambios or {}).items():
        if k not in permitidos:
            raise HTTPException(422, f"Campo no editable: {k}")
        try:
            val = permitidos[k](v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{ETIQUETAS.get(k, k)}: valor inválido ({v}).")
        lo, hi = LIMITES[k]
        if not (lo <= val <= hi):
            raise HTTPException(422, f"{ETIQUETAS.get(k, k)} debe estar entre {lo:g} y {hi:g}.")
        out[k] = val
    return out


# ── Validación (mismo motor que el diagnóstico) ───────────────────────────────
def _validar_sku(c, sku: str, cambios_prod: dict, factores: dict) -> dict:
    lineas, prods, pares = _cargar(c)
    prod = prods.get(sku)
    if prod is None:
        raise HTTPException(404, f"SKU no encontrado: {sku}")
    pares_sku = [p for p in pares if p["sku"] == sku]
    for lin in factores:
        if not any(p["linea"] == lin for p in pares_sku):
            raise HTTPException(422, f"El SKU {sku} no está asignado a la línea {lin}.")
    fc = _forecast().get(sku)
    prop = {**prod, **cambios_prod}
    por_linea, errores, advertencias = [], [], []
    for par in sorted(pares_sku, key=lambda p: (not p["preferida"], p["linea"])):
        lin = lineas.get(par["linea"])
        if lin is None:
            continue
        par_prop = {**par, **({"factor_velocidad": factores[par["linea"]]} if par["linea"] in factores else {})}
        dl = _pd.derivados_linea(lin)
        act = _pd.diagnosticar_sku(prod, dl, par, fc)
        pro = _pd.diagnosticar_sku(prop, dl, par_prop, fc)
        por_linea.append({"linea": par["linea"], "preferida": bool(par["preferida"]), "actual": act, "propuesto": pro})
        for a in pro["alertas"]:
            item = {"linea": par["linea"], **a}
            if a["nivel"] == _pd.NIVEL_ERROR:
                errores.append(item)
            elif a["nivel"] == _pd.NIVEL_WARN:
                advertencias.append(item)
    return {"sku": sku, "descripcion": prod.get("descripcion"), "por_linea": por_linea,
            "errores": errores, "advertencias": advertencias, "puede_guardar": not errores}


def _impacto_linea(c, codigo: str, cambios: dict) -> dict:
    lineas, prods, pares = _cargar(c)
    lin = lineas.get(codigo)
    if lin is None:
        raise HTTPException(404, f"Línea no encontrada: {codigo}")
    horas = float(cambios.get("horas_turno", lin.get("horas_turno") or 0))
    turnos = int(cambios.get("turnos_dia", lin.get("turnos_dia") or 0))
    if "turnos_config" not in cambios and not lin.get("turnos_config") and horas * turnos > 24:
        raise HTTPException(422, "Turnos × horas por turno no puede superar 24 h por día.")
    fc = _forecast()
    lin_prop = {**lin, **cambios}
    dl_act, dl_pro = _pd.derivados_linea(lin), _pd.derivados_linea(lin_prop)
    skus, nuevos_err, nuevas_adv, resueltas = [], 0, 0, 0
    for par in sorted((p for p in pares if p["linea"] == codigo), key=lambda p: p["sku"]):
        prod = prods.get(par["sku"])
        if prod is None or not prod.get("activo", True):
            continue
        act = _pd.diagnosticar_sku(prod, dl_act, par, fc.get(par["sku"]))
        pro = _pd.diagnosticar_sku(prod, dl_pro, par, fc.get(par["sku"]))
        ca = {(a["nivel"], a["codigo"]) for a in act["alertas"]}
        cp = {(a["nivel"], a["codigo"]) for a in pro["alertas"]}
        nuevas = [a for a in pro["alertas"] if (a["nivel"], a["codigo"]) not in ca and a["nivel"] != _pd.NIVEL_INFO]
        quitadas = [a for a in act["alertas"] if (a["nivel"], a["codigo"]) not in cp and a["nivel"] != _pd.NIVEL_INFO]
        nuevos_err += sum(1 for a in nuevas if a["nivel"] == _pd.NIVEL_ERROR)
        nuevas_adv += sum(1 for a in nuevas if a["nivel"] == _pd.NIVEL_WARN)
        resueltas += len(quitadas)
        if nuevas or quitadas:
            skus.append({"sku": par["sku"], "descripcion": prod.get("descripcion"),
                         "horas_batch_actual": act["derivados"].get("horas_por_batch"),
                         "horas_batch_propuesto": pro["derivados"].get("horas_por_batch"),
                         "nuevas": nuevas, "resueltas": quitadas})
    return {"linea": codigo, "derivados_actual": dl_act, "derivados_propuesto": dl_pro,
            "skus_afectados": skus, "n_nuevos_errores": nuevos_err, "n_nuevas_advertencias": nuevas_adv,
            "n_resueltas": resueltas, "puede_guardar": nuevos_err == 0}


# ── Escritura con historial ───────────────────────────────────────────────────
def _registrar(c, entidad, sku, linea, campo, anterior, nuevo, motivo, editor,
               origen="panel", recomendacion_id=None, revierte_id=None, anterior_txt=None, nuevo_txt=None) -> int:
    return c.execute(sa.text("""
        INSERT INTO mrp_params_historial (entidad, sku, linea, campo, valor_anterior, valor_nuevo,
                                          motivo, editor, origen, recomendacion_id, revierte_id,
                                          valor_anterior_txt, valor_nuevo_txt)
        VALUES (:e, :s, :l, :c, :a, :n, :m, :ed, :o, :r, :rv, :at, :nt) RETURNING id"""),
        {"e": entidad, "s": sku, "l": linea, "c": campo, "a": anterior, "n": nuevo, "m": motivo.strip(),
         "ed": editor.strip(), "o": origen, "r": recomendacion_id, "rv": revierte_id,
         "at": anterior_txt, "nt": nuevo_txt}).scalar()


def _aplicar_sku(c, sku, cambios_prod, factores, motivo, editor, origen="panel", reco_ids=(), revierte_id=None):
    hechos = []
    if cambios_prod:
        actual = dict(c.execute(sa.text("SELECT * FROM mrp_sku_params WHERE sku = :s FOR UPDATE"), {"s": sku}).first()._mapping)
        for campo, val in cambios_prod.items():
            if actual.get(campo) is not None and float(actual[campo]) == float(val):
                continue
            c.execute(sa.text(f"UPDATE mrp_sku_params SET {campo} = :v, updated_at = now() WHERE sku = :s"),
                      {"v": val, "s": sku})
            _rid = _reco_para(c, "sku", sku, None, campo, reco_ids)
            hid = _registrar(c, "sku", sku, None, campo, actual.get(campo), val, motivo, editor, origen, _rid, revierte_id)
            _vincular_intervencion(c, _rid, hid)
            hechos.append({"historial_id": hid, "campo": campo, "anterior": actual.get(campo), "nuevo": val})
    for lin, val in (factores or {}).items():
        ant = c.execute(sa.text("SELECT factor_velocidad FROM mrp_sku_lineas WHERE sku = :s AND linea = :l FOR UPDATE"),
                        {"s": sku, "l": lin}).scalar()
        if ant is not None and abs(float(ant) - float(val)) < 1e-9:
            continue
        c.execute(sa.text("UPDATE mrp_sku_lineas SET factor_velocidad = :v WHERE sku = :s AND linea = :l"),
                  {"v": val, "s": sku, "l": lin})
        _rid = _reco_para(c, "sku_linea", sku, lin, "factor_velocidad", reco_ids)
        hid = _registrar(c, "sku_linea", sku, lin, "factor_velocidad", ant, val, motivo, editor, origen, _rid, revierte_id)
        _vincular_intervencion(c, _rid, hid)
        hechos.append({"historial_id": hid, "campo": "factor_velocidad", "linea": lin, "anterior": ant, "nuevo": val})
    _marcar_recos(c, reco_ids, editor)
    return hechos


def _aplicar_linea(c, codigo, cambios, motivo, editor, origen="panel", reco_ids=(), revierte_id=None):
    actual = dict(c.execute(sa.text("SELECT * FROM mrp_lineas WHERE codigo = :c FOR UPDATE"), {"c": codigo}).first()._mapping)
    hechos = []
    for campo, val in cambios.items():
        if campo == "turnos_config":
            ant, nue = _json_tc(actual.get("turnos_config")), _json_tc(val)
            if ant == nue:
                continue
            c.execute(sa.text("UPDATE mrp_lineas SET turnos_config = CAST(:v AS JSONB), updated_at = now() WHERE codigo = :c"),
                      {"v": json.dumps(val), "c": codigo})
            sem_a = sum(sum(t["horas"]) for t in json.loads(ant)) if ant else None
            sem_n = sum(sum(t["horas"]) for t in val)
            hid = _registrar(c, "linea", None, codigo, "turnos_config", sem_a, sem_n, motivo, editor, origen,
                             _reco_para(c, "linea", codigo, codigo, campo, reco_ids), revierte_id,
                             anterior_txt=ant, nuevo_txt=nue)
            hechos.append({"historial_id": hid, "campo": campo, "anterior": ant, "nuevo": nue})
            continue
        if actual.get(campo) is not None and float(actual[campo]) == float(val):
            continue
        c.execute(sa.text(f"UPDATE mrp_lineas SET {campo} = :v, updated_at = now() WHERE codigo = :c"),
                  {"v": val, "c": codigo})
        hid = _registrar(c, "linea", None, codigo, campo, actual.get(campo), val, motivo, editor, origen,
                         _reco_para(c, "linea", codigo, codigo, campo, reco_ids), revierte_id)
        hechos.append({"historial_id": hid, "campo": campo, "anterior": actual.get(campo), "nuevo": val})
    _marcar_recos(c, reco_ids, editor)
    return hechos


def _reco_para(c, entidad, clave, linea, campo, reco_ids):
    """Id de la recomendación (entre las indicadas) que corresponde a este cambio, o None."""
    if not reco_ids:
        return None
    for r in c.execute(sa.text("SELECT id, entidad, clave, linea, campo FROM mrp_params_recomendaciones "
                               "WHERE id = ANY(:ids)"), {"ids": [int(i) for i in reco_ids]}):
        if r.entidad == entidad and r.clave == clave and r.campo == campo and (not r.linea or not linea or r.linea == linea):
            return r.id
    return None


def _marcar_recos(c, reco_ids, editor):
    if reco_ids:
        c.execute(sa.text("""UPDATE mrp_params_recomendaciones SET estado = 'aplicada', estado_por = :ed,
                             estado_en = now() WHERE id = ANY(:ids) AND estado = 'abierta'"""),
                  {"ids": list(reco_ids), "ed": editor.strip()})
        _cerrar_acciones_de_caso(c, reco_ids, editor)


def _vincular_intervencion(c, reco_id, hid):
    """(11-11-2026) Si la recomendación vino de un caso de Análisis de Línea, el cambio aplicado
    queda en la intervención (historial_ids + aplicado_en): es lo que se evaluará a 7/14 días."""
    if not reco_id or not hid:
        return
    try:
      with c.begin_nested():   # savepoint: un error aquí no aborta la edición
        iv = c.execute(sa.text("SELECT intervencion_id FROM mrp_params_recomendaciones WHERE id = :r"), {"r": reco_id}).scalar()
        if iv:
            c.execute(sa.text("""UPDATE mrp_intervenciones
                                 SET historial_ids = array_append(COALESCE(historial_ids, '{}'::bigint[]), CAST(:h AS BIGINT)),
                                     aplicado_en = COALESCE(aplicado_en, now()) WHERE id = :i"""), {"h": hid, "i": iv})
    except Exception:
        pass


def _cerrar_acciones_de_caso(c, reco_ids, editor):
    _sincronizar_acciones(c, editor)


def _sincronizar_acciones(c, editor, motivo: str = ""):
    """(11-11-2026) Acciones de casos con cambios de parámetros: cuando ya no queda ninguna
    recomendación ABIERTA para sus (SKU, campo) -> 'hecha' si alguna se aplicó después de
    aceptarla, o 'descartada' si no. Funciona aunque varias acciones compartan la misma
    recomendación (sin duplicados). Cierra los casos sin pendientes."""
    try:
        with c.begin_nested():   # savepoint: un error aquí no aborta la edición
            filas = c.execute(sa.text("""
                SELECT a.id, a.intervencion_id,
                       EXISTS (SELECT 1 FROM jsonb_array_elements(a.cambios_parametros) cp
                               JOIN mrp_params_recomendaciones r ON r.entidad = 'sku' AND r.clave = cp->>'sku'
                                AND r.campo = cp->>'campo' AND r.estado = 'aplicada' AND r.estado_en >= a.creado_en) AS aplicada
                FROM mrp_analisis_acciones a
                WHERE a.estado = 'aceptada' AND a.recomendaciones > 0
                  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(a.cambios_parametros) cp
                                  JOIN mrp_params_recomendaciones r ON r.entidad = 'sku' AND r.clave = cp->>'sku'
                                   AND r.campo = cp->>'campo' AND r.estado = 'abierta')""")).fetchall()
            for f in filas:
                if f.aplicada:
                    c.execute(sa.text("""UPDATE mrp_analisis_acciones SET estado = 'hecha', resuelto_por = :ed, resuelto_en = now(),
                                         comentario = 'Cambios aplicados en el panel de parámetros' WHERE id = :i"""),
                              {"ed": editor.strip(), "i": f.id})
                    if f.intervencion_id:
                        c.execute(sa.text("UPDATE mrp_intervenciones SET aplicado_en = COALESCE(aplicado_en, now()) WHERE id = :i"),
                                  {"i": f.intervencion_id})
                else:
                    c.execute(sa.text("""UPDATE mrp_analisis_acciones SET estado = 'descartada', resuelto_por = :ed,
                                         resuelto_en = now(), comentario = :m WHERE id = :i"""),
                              {"ed": editor.strip(), "m": f"Recomendación descartada en el panel{': ' + motivo if motivo else ''}",
                               "i": f.id})
                    if f.intervencion_id:
                        c.execute(sa.text("""UPDATE mrp_intervenciones SET veredicto = 'no_concluyente', evaluado_en = now(),
                                             evaluado_por = :ed, aprendizaje = :m WHERE id = :i AND veredicto = 'pendiente'"""),
                                  {"ed": editor.strip(), "m": f"No se aplicó (descartada en el panel){': ' + motivo if motivo else ''}",
                                   "i": f.intervencion_id})
            c.execute(sa.text("""
                UPDATE mrp_analisis_casos k SET estado = 'cerrado'
                WHERE k.estado = 'en_seguimiento'
                  AND NOT EXISTS (SELECT 1 FROM mrp_analisis_acciones a WHERE a.caso_id = k.id AND a.estado = 'aceptada')"""))
    except Exception:
        pass


# ── Modelos ───────────────────────────────────────────────────────────────────
class ValidarSku(BaseModel):
    cambios_producto: dict | None = None       # {batch_min_u, cap_bodega_u}
    factores: dict | None = None               # {linea: factor_velocidad}


class EditarSku(ValidarSku):
    editor: str
    pin: str
    motivo: str
    recomendacion_ids: list[int] | None = None


class ValidarLinea(BaseModel):
    cambios: dict                              # {velocidad_u_hr, turnos_dia, horas_turno, dias_semana}


class EditarLinea(ValidarLinea):
    editor: str
    pin: str
    motivo: str
    recomendacion_ids: list[int] | None = None


class Autorizacion(BaseModel):
    editor: str
    pin: str
    motivo: str | None = None


class EstadoReco(Autorizacion):
    estado: str                                # descartada | abierta


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("/config")
def config():
    with _engine.connect() as c:
        cal = c.execute(sa.text("SELECT valor FROM mrp_params_config WHERE clave = 'capacidad_calendario'")).scalar()
        return {"pin_configurado": _pin_configurado(c), "aviso": AVISO_APLICACION, "limites": LIMITES,
                "calendario_activo": (cal or "").lower() == "on",
                "umbrales": {"horas_batch_min": _pd.UMBRAL_HORAS_BATCH_MIN,
                             "factor_rango": list(_pd.FACTOR_RANGO_NORMAL)}}


@router.post("/sku/{sku}/validar")
def validar_sku(sku: str, body: ValidarSku):
    cp = _limpiar(body.cambios_producto, CAMPOS_SKU)
    fa = {k: _limpiar({"factor_velocidad": v}, CAMPOS_SKU_LINEA)["factor_velocidad"] for k, v in (body.factores or {}).items()}
    with _engine.connect() as c:
        return _validar_sku(c, sku, cp, fa)


@router.put("/sku/{sku}")
def editar_sku(sku: str, body: EditarSku):
    _verificar_identidad(body.editor, body.motivo)
    cp = _limpiar(body.cambios_producto, CAMPOS_SKU)
    fa = {k: _limpiar({"factor_velocidad": v}, CAMPOS_SKU_LINEA)["factor_velocidad"] for k, v in (body.factores or {}).items()}
    if not cp and not fa:
        raise HTTPException(422, "No hay cambios para guardar.")
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        v = _validar_sku(c, sku, cp, fa)
        if not v["puede_guardar"]:
            raise HTTPException(422, {"mensaje": "Hay errores que impiden guardar.", "errores": v["errores"]})
        hechos = _aplicar_sku(c, sku, cp, fa, body.motivo, body.editor, reco_ids=body.recomendacion_ids or ())
    return {"guardado": True, "cambios": hechos, "advertencias": v["advertencias"], "aviso": AVISO_APLICACION}


@router.post("/linea/{codigo}/validar")
def validar_linea(codigo: str, body: ValidarLinea):
    cambios = _separar_linea(body.cambios)
    with _engine.connect() as c:
        return _impacto_linea(c, codigo, cambios)


@router.put("/linea/{codigo}")
def editar_linea(codigo: str, body: EditarLinea):
    _verificar_identidad(body.editor, body.motivo)
    cambios = _separar_linea(body.cambios)
    if not cambios:
        raise HTTPException(422, "No hay cambios para guardar.")
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        imp = _impacto_linea(c, codigo, cambios)
        if not imp["puede_guardar"]:
            raise HTTPException(422, {"mensaje": f"El cambio genera {imp['n_nuevos_errores']} error(es) nuevo(s) "
                                                 f"en SKU de la línea.", "impacto": imp})
        hechos = _aplicar_linea(c, codigo, cambios, body.motivo, body.editor, reco_ids=body.recomendacion_ids or ())
    return {"guardado": True, "cambios": hechos, "impacto": imp, "aviso": AVISO_APLICACION}


@router.get("/historial")
def historial(sku: Optional[str] = None, linea: Optional[str] = None, limit: int = 50):
    sql = "SELECT * FROM mrp_params_historial WHERE 1=1"
    p = {"lim": max(1, min(limit, 500))}
    if sku:
        sql += " AND sku = :sku"; p["sku"] = sku
    if linea:
        sql += " AND linea = :linea"; p["linea"] = linea
    sql += " ORDER BY ts DESC, id DESC LIMIT :lim"
    with _engine.connect() as c:
        return {"historial": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.post("/historial/{hid}/revertir")
def revertir(hid: int, body: Autorizacion):
    _verificar_identidad(body.editor, body.motivo or "Reversión")
    motivo = body.motivo or f"Reversión del cambio #{hid}"
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        h = c.execute(sa.text("SELECT * FROM mrp_params_historial WHERE id = :i FOR UPDATE"), {"i": hid}).first()
        if h is None:
            raise HTTPException(404, "Cambio no encontrado.")
        if h.revertido_por:
            raise HTTPException(409, f"Este cambio ya fue revertido (#{h.revertido_por}).")
        if h.campo == "turnos_config":
            if not h.valor_anterior_txt:
                raise HTTPException(409, "El cambio no tiene patrón anterior registrado: no se puede revertir.")
            actual_tc = c.execute(sa.text("SELECT turnos_config FROM mrp_lineas WHERE codigo = :c"), {"c": h.linea}).scalar()
            if _json_tc(actual_tc) != _json_tc(h.valor_nuevo_txt):
                raise HTTPException(409, "Los turnos cambiaron después de este registro: revertir desde el cambio más reciente.")
            val_tc = _validar_turnos(h.valor_anterior_txt)
            imp = _impacto_linea(c, h.linea, {"turnos_config": val_tc})
            if not imp["puede_guardar"]:
                raise HTTPException(422, {"mensaje": "Revertir genera errores nuevos en SKU de la línea.", "impacto": imp})
            hechos = _aplicar_linea(c, h.linea, {"turnos_config": val_tc}, motivo, body.editor, "revertir", revierte_id=hid)
            if hechos:
                c.execute(sa.text("UPDATE mrp_params_historial SET revertido_por = :n WHERE id = :i"),
                          {"n": hechos[0]["historial_id"], "i": hid})
            return {"revertido": True, "cambios": hechos, "aviso": AVISO_APLICACION}
        if h.campo.startswith("excepcion"):
            raise HTTPException(409, "Las excepciones se anulan desde la lista de excepciones.")
        if h.valor_anterior is None:
            raise HTTPException(409, "El cambio no tiene valor anterior registrado: no se puede revertir.")
        tipo = {**CAMPOS_SKU, **CAMPOS_SKU_LINEA, **CAMPOS_LINEA}[h.campo]
        val = tipo(h.valor_anterior)
        if h.entidad == "linea":
            actual = c.execute(sa.text(f"SELECT {h.campo} FROM mrp_lineas WHERE codigo = :c"), {"c": h.linea}).scalar()
        elif h.entidad == "sku_linea":
            actual = c.execute(sa.text("SELECT factor_velocidad FROM mrp_sku_lineas WHERE sku = :s AND linea = :l"),
                               {"s": h.sku, "l": h.linea}).scalar()
        else:
            actual = c.execute(sa.text(f"SELECT {h.campo} FROM mrp_sku_params WHERE sku = :s"), {"s": h.sku}).scalar()
        if actual is None or abs(float(actual) - float(h.valor_nuevo)) > 1e-9:
            raise HTTPException(409, "El valor cambió después de este registro: revertir desde el cambio más reciente.")
        if h.entidad == "linea":
            imp = _impacto_linea(c, h.linea, {h.campo: val})
            if not imp["puede_guardar"]:
                raise HTTPException(422, {"mensaje": "Revertir genera errores nuevos en SKU de la línea.", "impacto": imp})
            hechos = _aplicar_linea(c, h.linea, {h.campo: val}, motivo, body.editor, "revertir", revierte_id=hid)
        else:
            cp = {h.campo: val} if h.entidad == "sku" else {}
            fa = {h.linea: val} if h.entidad == "sku_linea" else {}
            v = _validar_sku(c, h.sku, cp, fa)
            if not v["puede_guardar"]:
                raise HTTPException(422, {"mensaje": "Revertir deja errores en el SKU.", "errores": v["errores"]})
            hechos = _aplicar_sku(c, h.sku, cp, fa, motivo, body.editor, "revertir", revierte_id=hid)
        if hechos:
            c.execute(sa.text("UPDATE mrp_params_historial SET revertido_por = :n WHERE id = :i"),
                      {"n": hechos[0]["historial_id"], "i": hid})
    return {"revertido": True, "cambios": hechos, "aviso": AVISO_APLICACION}


@router.get("/recomendaciones")
def recomendaciones(estado: Optional[str] = "abierta", sku: Optional[str] = None, linea: Optional[str] = None):
    sql = """
        SELECT r.*,
               CASE r.entidad
                 WHEN 'sku'       THEN (SELECT CASE r.campo WHEN 'batch_min_u' THEN p.batch_min_u
                                                             WHEN 'cap_bodega_u' THEN p.cap_bodega_u END
                                        FROM mrp_sku_params p WHERE p.sku = r.clave)
                 WHEN 'sku_linea' THEN (SELECT sl.factor_velocidad FROM mrp_sku_lineas sl
                                        WHERE sl.sku = r.clave AND sl.linea = r.linea)
                 WHEN 'linea'     THEN (SELECT CASE r.campo WHEN 'velocidad_u_hr' THEN l.velocidad_u_hr
                                                             WHEN 'turnos_dia' THEN l.turnos_dia
                                                             WHEN 'horas_turno' THEN l.horas_turno
                                                             WHEN 'dias_semana' THEN l.dias_semana END
                                        FROM mrp_lineas l WHERE l.codigo = r.clave)
               END AS valor_vigente
        FROM mrp_params_recomendaciones r WHERE 1=1"""
    p = {}
    if estado:
        sql += " AND r.estado = :estado"; p["estado"] = estado
    if sku:
        sql += " AND r.entidad IN ('sku','sku_linea') AND r.clave = :sku"; p["sku"] = sku
    if linea:
        sql += " AND (r.linea = :linea OR (r.entidad = 'linea' AND r.clave = :linea))"; p["linea"] = linea
    sql += """ ORDER BY CASE r.prioridad WHEN 'alta' THEN 0 WHEN 'media-alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END,
               r.entidad, r.clave"""
    with _engine.connect() as c:
        return {"recomendaciones": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.post("/recomendaciones/{rid}/estado")
def estado_reco(rid: int, body: EstadoReco):
    if body.estado not in ("descartada", "abierta"):
        raise HTTPException(422, "Estado inválido: usar 'descartada' o 'abierta'.")
    _verificar_identidad(body.editor, body.motivo or "")
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        r = c.execute(sa.text("SELECT * FROM mrp_params_recomendaciones WHERE id = :i FOR UPDATE"), {"i": rid}).first()
        if r is None:
            raise HTTPException(404, "Recomendación no encontrada.")
        if r.estado == "aplicada":
            raise HTTPException(409, "La recomendación ya fue aplicada: para deshacer, revierte el cambio en el historial.")
        c.execute(sa.text("""UPDATE mrp_params_recomendaciones SET estado = :e, estado_por = :ed, estado_en = now(),
                             motivo = CASE WHEN :e = 'descartada' THEN motivo || ' | Descartada: ' || :m ELSE motivo END
                             WHERE id = :i"""),
                  {"e": body.estado, "ed": body.editor.strip(), "m": (body.motivo or "").strip(), "i": rid})
        if body.estado == "descartada":
            _sincronizar_acciones(c, body.editor, (body.motivo or "").strip())
    return {"id": rid, "estado": body.estado}


# ── Calendario de capacidad: excepciones por fecha y activación (11-11-2026) ──
TIPOS_EXC = ("extension", "sabado", "domingo_feriado", "sin_produccion", "otro")


class Excepcion(Autorizacion):
    linea: str
    fecha: str               # YYYY-MM-DD
    horas: float             # horas TOTALES del día (todos los turnos)
    tipo: str = "extension"


class Activacion(Autorizacion):
    activo: bool


@router.get("/excepciones")
def listar_excepciones(linea: Optional[str] = None, desde: Optional[str] = None, incluir_anuladas: bool = False):
    sql = "SELECT * FROM mrp_capacidad_excepciones WHERE fecha >= COALESCE(CAST(:d AS DATE), current_date - 7)"
    p = {"d": desde}
    if linea:
        sql += " AND linea = :l"; p["l"] = linea
    if not incluir_anuladas:
        sql += " AND NOT anulado"
    sql += " ORDER BY fecha, linea"
    with _engine.connect() as c:
        return {"excepciones": [dict(r._mapping) for r in c.execute(sa.text(sql), p)]}


@router.post("/excepciones")
def crear_excepcion(body: Excepcion):
    from datetime import date as _date
    _verificar_identidad(body.editor, body.motivo)
    if body.tipo not in TIPOS_EXC:
        raise HTTPException(422, f"Tipo inválido: {body.tipo}")
    try:
        f = _date.fromisoformat(body.fecha)
    except ValueError:
        raise HTTPException(422, "Fecha inválida (YYYY-MM-DD).")
    if not 0 <= float(body.horas) <= 24:
        raise HTTPException(422, "Las horas del día deben estar entre 0 y 24.")
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        if c.execute(sa.text("SELECT 1 FROM mrp_lineas WHERE codigo = :l"), {"l": body.linea}).first() is None:
            raise HTTPException(404, f"Línea no encontrada: {body.linea}")
        prev = c.execute(sa.text("""SELECT id, horas FROM mrp_capacidad_excepciones
                                    WHERE linea = :l AND fecha = :f AND NOT anulado FOR UPDATE"""),
                         {"l": body.linea, "f": f}).first()
        if prev is not None:
            c.execute(sa.text("""UPDATE mrp_capacidad_excepciones SET anulado = TRUE, anulado_por = :e, anulado_en = now()
                                 WHERE id = :i"""), {"e": body.editor.strip(), "i": prev.id})
        eid = c.execute(sa.text("""INSERT INTO mrp_capacidad_excepciones (linea, fecha, horas, tipo, motivo, creado_por)
                                   VALUES (:l, :f, :h, :t, :m, :e) RETURNING id"""),
                        {"l": body.linea, "f": f, "h": float(body.horas), "t": body.tipo,
                         "m": body.motivo.strip(), "e": body.editor.strip()}).scalar()
        _registrar(c, "linea", None, body.linea, f"excepcion {f.isoformat()}",
                   float(prev.horas) if prev is not None else None, float(body.horas), body.motivo, body.editor)
    return {"id": eid, "reemplazo": prev.id if prev is not None else None, "aviso": AVISO_APLICACION}


@router.post("/excepciones/{eid}/anular")
def anular_excepcion(eid: int, body: Autorizacion):
    _verificar_identidad(body.editor, body.motivo or "Anulación")
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        r = c.execute(sa.text("SELECT * FROM mrp_capacidad_excepciones WHERE id = :i FOR UPDATE"), {"i": eid}).first()
        if r is None or r.anulado:
            raise HTTPException(404, "Excepción no encontrada o ya anulada.")
        c.execute(sa.text("""UPDATE mrp_capacidad_excepciones SET anulado = TRUE, anulado_por = :e, anulado_en = now()
                             WHERE id = :i"""), {"e": body.editor.strip(), "i": eid})
        _registrar(c, "linea", None, r.linea, f"excepcion {r.fecha.isoformat()}", float(r.horas), None,
                   body.motivo or "Anulación de excepción", body.editor)
    return {"anulada": eid, "aviso": AVISO_APLICACION}


@router.put("/calendario")
def activar_calendario(body: Activacion):
    """Interruptor general del calendario de capacidad (plan, KPIs y análisis)."""
    _verificar_identidad(body.editor, body.motivo)
    with _engine.begin() as c:
        _verificar_pin(c, body.pin)
        ant = c.execute(sa.text("SELECT valor FROM mrp_params_config WHERE clave = 'capacidad_calendario'")).scalar()
        nue = "on" if body.activo else "off"
        c.execute(sa.text("""INSERT INTO mrp_params_config (clave, valor, updated_at) VALUES ('capacidad_calendario', :v, now())
                             ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, updated_at = now()"""), {"v": nue})
        _registrar(c, "linea", None, None, "capacidad_calendario", None, None, body.motivo, body.editor,
                   anterior_txt=ant, nuevo_txt=nue)
    return {"capacidad_calendario": nue, "aviso": AVISO_APLICACION}


# ── CLI: definir el PIN ───────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Configuración del panel de edición de parámetros")
    ap.add_argument("--set-pin", action="store_true", help="define o cambia el PIN de edición")
    a = ap.parse_args()
    if a.set_pin:
        p1 = getpass.getpass("Nuevo PIN de edición (mín. 4 caracteres): ")
        p2 = getpass.getpass("Repetir PIN: ")
        if p1 != p2 or len(p1) < 4:
            raise SystemExit("Los PIN no coinciden o tienen menos de 4 caracteres. No se guardó nada.")
        sal = secrets.token_hex(8)
        with _engine.begin() as c:
            c.execute(sa.text("""INSERT INTO mrp_params_config (clave, valor, updated_at)
                                 VALUES ('pin_edicion', :v, now())
                                 ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, updated_at = now()"""),
                      {"v": f"{sal}${_hash_pin(p1, sal)}"})
        print("PIN de edición guardado.")
    else:
        ap.print_help()
