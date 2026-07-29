"""
campanas_api.py — Endpoints de Campanas de linea (V6, 29-07-2026).

Se expone como APIRouter para NO tocar main.py mas que con una linea:

    from campanas_api import router as campanas_router
    app.include_router(campanas_router)

Modelo de datos (db_mrp): mrp_campana_reglas + mrp_campana_calendario.
Semantica de una fila del calendario:
  - fijado=TRUE  -> pin del planificador. El optimizer lo fuerza (granel == 1).
  - fijado=FALSE -> propuesta del solver de la ultima corrida (solo informativa).
  - modo ""      -> semana sin granel de salsa (solo se envasan independientes).

Las OFM/OF manuales NO estan sujetas a la campana: entran como entradas_fijas y
el acoplamiento solo aplica a lo que decide el solver.
"""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db_mrp import (
    get_campana_reglas,
    get_campana_calendario,
    upsert_campana_pin,
    delete_campana_pin,
    get_all_sku_params,
)

router = APIRouter(prefix="/campanas", tags=["campanas"])

RECURSO_GRANEL = "GRANEL_SALSAS"


def _lunes(d: date) -> date:
    """Inicio de semana ISO (lunes). Mismo criterio que calendario.semana_iso_inicio."""
    return d - timedelta(days=d.weekday())


class PinIn(BaseModel):
    semana: date          # cualquier dia de la semana; se normaliza al lunes
    modo: str = ""        # "ketchup" | "mostaza" | "" (= sin granel)
    autor: str = ""


@router.get("/reglas")
def reglas():
    """Reglas activas por recurso (dimension, modos posibles, max por semana)."""
    return {"reglas": get_campana_reglas()}


@router.get("/calendario")
def calendario(recurso: str = RECURSO_GRANEL, semanas: int = 10):
    """Calendario desde la semana actual, `semanas` hacia adelante.

    Devuelve una fila por semana SIEMPRE (aunque no haya registro en BD), para que
    el front pueda dibujar la grilla completa sin inventar huecos.
    """
    inicio = _lunes(date.today())
    fin = inicio + timedelta(weeks=max(1, semanas) - 1)
    filas = {r["semana"]: r for r in get_campana_calendario(
        recurso=recurso, desde=inicio, hasta=fin)}

    out = []
    for i in range(max(1, semanas)):
        w = inicio + timedelta(weeks=i)
        r = filas.get(w)
        out.append({
            "semana": w.isoformat(),
            "modo": (r or {}).get("modo", "") or "",
            "fijado": bool((r or {}).get("fijado", False)),
            "autor": (r or {}).get("autor", "") or "",
        })
    return {"recurso": recurso, "desde": inicio.isoformat(), "calendario": out}


@router.put("/pin")
def fijar_pin(pin: PinIn, recurso: str = RECURSO_GRANEL):
    """Fija el modo de una semana (pin duro). Valida contra los modos de la regla."""
    reglas_ = {r["recurso"]: r for r in get_campana_reglas()}
    if recurso not in reglas_:
        raise HTTPException(404, f"recurso '{recurso}' sin regla activa")
    modos_ok = set(reglas_[recurso].get("modos") or [])
    modo = (pin.modo or "").strip().lower()
    if modo and modo not in modos_ok:
        raise HTTPException(
            400, f"modo '{modo}' invalido para {recurso}. Validos: {sorted(modos_ok)} o vacio")
    w = _lunes(pin.semana)
    upsert_campana_pin(recurso, w, modo, fijado=True, autor=pin.autor)
    return {"ok": True, "recurso": recurso, "semana": w.isoformat(),
            "modo": modo, "fijado": True}


@router.delete("/pin")
def soltar_pin(semana: date, recurso: str = RECURSO_GRANEL):
    """Suelta una semana: el solver vuelve a decidirla en la proxima corrida."""
    w = _lunes(semana)
    n = delete_campana_pin(recurso, w)
    return {"ok": True, "recurso": recurso, "semana": w.isoformat(), "borradas": n}


@router.get("/skus")
def skus_por_grupo():
    """SKU agrupados por granel_grupo. Sirve para que el usuario vea el impacto
    de fijar una semana: que productos quedan habilitados y cuales no."""
    grupos: dict[str, list[dict]] = {}
    for sp in get_all_sku_params():
        g = (sp.get("granel_grupo") or "").strip().lower() or "(independiente)"
        grupos.setdefault(g, []).append({
            "sku": sp.get("sku"),
            "descripcion": sp.get("descripcion", ""),
            "mto": bool(sp.get("mto", False)),
        })
    return {"grupos": {k: sorted(v, key=lambda x: x["sku"]) for k, v in grupos.items()},
            "conteo": {k: len(v) for k, v in grupos.items()}}
