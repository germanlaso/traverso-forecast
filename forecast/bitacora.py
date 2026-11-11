"""
Bitácora de eventos diarios por línea — Módulo Evaluación de la Operación.

Endpoints:
  GET  /bitacora/catalogos                 -> tipos de evento activos + líneas activas
  GET  /bitacora/eventos?desde&hasta&linea -> eventos del rango (default: últimos 7 días)
  POST /bitacora/eventos                   -> registra un evento
  POST /bitacora/eventos/{id}/anular       -> anula (no borra) un evento

Validaciones fail-loud (422) en vez de defaults silenciosos: línea y tipo deben
existir y estar activos; duración obligatoria si el tipo la requiere.
Fechas futuras: solo categorías PARADA_PLANIFICADA y SIN_PROGRAMA, hasta 90 días
(se anotan de antemano desde la grilla; cuentan en KPIs recién cuando se evalúa su semana).
"""
from datetime import date, time, timedelta
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db_mrp import engine as _engine   # engine de módulo de mrp_db (pool compartido)

# mrp_lineas: PK = codigo (case-sensitive, ej. 'L1Pet LV'); se guarda el codigo.
SQL_LINEAS = "SELECT codigo, nombre FROM mrp_lineas WHERE activa ORDER BY codigo"
SQL_CODIGOS_LINEA = "SELECT codigo FROM mrp_lineas WHERE activa"
SQL_TIPOS = (
    "SELECT codigo, nombre, categoria, requiere_duracion "
    "FROM mrp_eventos_tipos WHERE activo ORDER BY orden, nombre"
)

router = APIRouter(prefix="/bitacora", tags=["bitacora"])

# (11-11-2026) Se pueden anotar a futuro: paradas planificadas, BLOQUEO PROGRAMADO y línea
# disponible sin programa. Las dos primeras RESTAN horas al solver (mrp.cargar_bloqueos_bitacora);
# "sin programa" no bloquea.
CATEGORIAS_FUTURAS = ("PARADA_PLANIFICADA", "BLOQUEO_PROGRAMADO", "SIN_PROGRAMA")
MAX_DIAS_FUTURO = 90


class EventoIn(BaseModel):
    fecha: date
    linea: str
    tipo: str
    registrado_por: str
    duracion_min: Optional[int] = None
    sku: Optional[str] = None
    comentario: Optional[str] = None
    # (11-11-2026) máquina y horario (opcionales). Con inicio y fin, la duración se calcula sola.
    maquina: Optional[str] = None
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None


class AnularIn(BaseModel):
    anulado_por: str


def _limpiar(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    return s or None


@router.get("/catalogos")
def catalogos():
    with _engine.connect() as c:
        tipos = [dict(r._mapping) for r in c.execute(sa.text(SQL_TIPOS))]
        lineas = [dict(r._mapping) for r in c.execute(sa.text(SQL_LINEAS))]
    return {"tipos": tipos, "lineas": lineas}


@router.get("/eventos")
def listar_eventos(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    linea: Optional[str] = Query(None),
    incluir_anulados: bool = Query(False),
):
    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=6))
    if desde > hasta:
        raise HTTPException(422, "El rango es inválido: 'desde' es posterior a 'hasta'.")

    sql = (
        "SELECT e.id, e.fecha, e.linea, e.tipo, t.nombre AS tipo_nombre, t.categoria, "
        "       e.duracion_min, e.sku, e.comentario, e.registrado_por, e.creado_en, "
        "       e.maquina, e.hora_inicio, e.hora_fin, e.origen_detencion, "
        "       e.anulado, e.anulado_por, e.anulado_en "
        "FROM mrp_eventos_linea e JOIN mrp_eventos_tipos t ON t.codigo = e.tipo "
        "WHERE e.fecha BETWEEN :desde AND :hasta "
    )
    params = {"desde": desde, "hasta": hasta}
    if linea:
        sql += "AND e.linea = :linea "
        params["linea"] = linea
    if not incluir_anulados:
        sql += "AND NOT e.anulado "
    sql += "ORDER BY e.fecha DESC, e.linea, e.creado_en DESC"

    with _engine.connect() as c:
        filas = [dict(r._mapping) for r in c.execute(sa.text(sql), params)]
    return {"desde": desde, "hasta": hasta, "eventos": filas}


@router.post("/eventos")
def crear_evento(ev: EventoIn):
    registrado_por = _limpiar(ev.registrado_por)
    if not registrado_por:
        raise HTTPException(422, "Indica quién registra el evento.")

    with _engine.begin() as c:
        lineas = set(c.execute(sa.text(SQL_CODIGOS_LINEA)).scalars().all())
        if ev.linea not in lineas:
            raise HTTPException(422, f"Línea '{ev.linea}' no existe o no está activa.")

        tipo = c.execute(
            sa.text("SELECT requiere_duracion, categoria FROM mrp_eventos_tipos WHERE codigo = :c AND activo"),
            {"c": ev.tipo},
        ).first()
        if tipo is None:
            raise HTTPException(422, f"Tipo de evento '{ev.tipo}' no existe o no está activo.")

        if ev.fecha > date.today():
            if tipo.categoria not in CATEGORIAS_FUTURAS:
                raise HTTPException(422, "En fechas futuras solo se pueden registrar paradas planificadas, "
                                         "bloqueos programados y línea disponible sin programa.")
            if ev.fecha > date.today() + timedelta(days=MAX_DIAS_FUTURO):
                raise HTTPException(422, f"Solo se pueden anotar eventos hasta {MAX_DIAS_FUTURO} días adelante.")

        duracion = ev.duracion_min
        if ev.hora_inicio and ev.hora_fin:
            mins = (ev.hora_fin.hour * 60 + ev.hora_fin.minute) - (ev.hora_inicio.hour * 60 + ev.hora_inicio.minute)
            if mins <= 0:
                mins += 1440          # cruza medianoche
            if duracion is None:
                duracion = mins
            elif abs(duracion - mins) > 1:
                raise HTTPException(422, f"La duración ({duracion} min) no calza con el horario "
                                         f"{ev.hora_inicio:%H:%M}-{ev.hora_fin:%H:%M} ({mins} min).")
        if tipo.requiere_duracion and not duracion:
            raise HTTPException(422, "Este tipo de evento requiere duración en minutos.")
        if duracion is not None and not (1 <= duracion <= 1440):
            raise HTTPException(422, "La duración debe estar entre 1 y 1440 minutos.")

        nuevo_id = c.execute(
            sa.text(
                "INSERT INTO mrp_eventos_linea "
                "(fecha, linea, tipo, duracion_min, sku, comentario, registrado_por, maquina, hora_inicio, hora_fin) "
                "VALUES (:fecha, :linea, :tipo, :dur, :sku, :com, :por, :maq, :hi, :hf) RETURNING id"
            ),
            {
                "fecha": ev.fecha,
                "linea": ev.linea,
                "tipo": ev.tipo,
                "dur": duracion,
                "sku": _limpiar(ev.sku),
                "com": _limpiar(ev.comentario),
                "por": registrado_por,
                "maq": _limpiar(ev.maquina),
                "hi": ev.hora_inicio,
                "hf": ev.hora_fin,
            },
        ).scalar()
    return {"id": nuevo_id}


@router.post("/eventos/{evento_id}/anular")
def anular_evento(evento_id: int, body: AnularIn):
    por = _limpiar(body.anulado_por)
    if not por:
        raise HTTPException(422, "Indica quién anula el evento.")
    with _engine.begin() as c:
        n = c.execute(
            sa.text(
                "UPDATE mrp_eventos_linea "
                "SET anulado = TRUE, anulado_por = :por, anulado_en = now() "
                "WHERE id = :id AND NOT anulado"
            ),
            {"id": evento_id, "por": por},
        ).rowcount
    if n == 0:
        raise HTTPException(404, f"Evento {evento_id} no existe o ya estaba anulado.")
    return {"id": evento_id, "anulado": True}
