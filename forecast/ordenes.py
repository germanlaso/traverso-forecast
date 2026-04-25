"""
ordenes.py — Gestión de órdenes aprobadas · Traverso S.A.

Persistencia: /app/data/ordenes_aprobadas.json
Clave única:  sku__semana_necesidad__semana_emision
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ordenes", tags=["Ordenes Aprobadas"])

ORDENES_PATH = Path("/app/data/ordenes_aprobadas.json")


class OrdenAprobar(BaseModel):
    sku:                  str
    descripcion:          str
    tipo:                 str
    semana_emision:       str        # fecha lanzamiento sugerida por MRP
    semana_necesidad:     str        # fecha entrada stock sugerida por MRP
    cantidad_sugerida_cj: float
    cantidad_real_cj:     float
    u_por_caja:           float = 1.0
    responsable:          str
    comentario:           str   = ""
    linea:                str   = ""
    fecha_lanzamiento_real: str = "" # fecha real de lanzamiento (editable)
    fecha_entrada_real:     str = "" # fecha real entrada stock (editable, ej. retraso maritimo)


def _load() -> dict:
    if not ORDENES_PATH.exists():
        return {}
    try:
        return json.loads(ORDENES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Error leyendo ordenes_aprobadas.json: {e}")
        return {}


def _save(data: dict) -> None:
    ORDENES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORDENES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def orden_key(sku, semana_necesidad, semana_emision):
    return f"{sku}__{semana_necesidad}__{semana_emision}"


@router.get("/aprobadas")
def listar_aprobadas():
    return list(_load().values())


@router.post("/aprobar")
def aprobar_orden(req: OrdenAprobar):
    data = _load()
    key  = orden_key(req.sku, req.semana_necesidad, req.semana_emision)
    # Resolver fechas reales (si no se proporcionan, usar las sugeridas por MRP)
    fecha_lanzamiento_real = req.fecha_lanzamiento_real or req.semana_emision
    fecha_entrada_real     = req.fecha_entrada_real     or req.semana_necesidad

    registro = {
        "key":                    key,
        "sku":                    req.sku,
        "descripcion":            req.descripcion,
        "tipo":                   req.tipo,
        "semana_emision":         req.semana_emision,         # sugerida MRP
        "semana_necesidad":       req.semana_necesidad,       # sugerida MRP
        "fecha_lanzamiento_real": fecha_lanzamiento_real,     # real aprobada
        "fecha_entrada_real":     fecha_entrada_real,         # real aprobada
        "cantidad_sugerida_cj":   req.cantidad_sugerida_cj,
        "cantidad_real_cj":       req.cantidad_real_cj,
        "cantidad_real_u":        round(req.cantidad_real_cj * req.u_por_caja),
        "u_por_caja":             req.u_por_caja,
        "responsable":            req.responsable,
        "comentario":             req.comentario,
        "linea":                  req.linea,
        "modificada":             (req.cantidad_real_cj != req.cantidad_sugerida_cj
                                   or bool(req.fecha_lanzamiento_real)
                                   or bool(req.fecha_entrada_real)),
        "timestamp":              datetime.now().isoformat(),
    }
    data[key] = registro
    _save(data)
    logger.info(f"[ORDEN] Aprobada: {req.sku} · {req.semana_necesidad} · {req.cantidad_real_cj:.0f} cj · por {req.responsable}")
    return registro


@router.delete("/cancelar/{key:path}")
def cancelar_orden(key: str):
    data = _load()
    if key not in data:
        return {"ok": False, "mensaje": "Orden no encontrada"}
    del data[key]
    _save(data)
    return {"ok": True, "key": key}


@router.get("/aprobadas/resumen")
def resumen_aprobadas():
    items = list(_load().values())
    return {
        "total":       len(items),
        "modificadas": sum(1 for o in items if o.get("modificada")),
        "por_tipo":    {t: sum(1 for o in items if o["tipo"]==t) for t in ["PRODUCCION","IMPORTACION","MAQUILA"]},
        "ordenes":     items,
    }
