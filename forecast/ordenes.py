"""
ordenes.py — Gestión de órdenes MRP · Traverso S.A.
Persistencia: PostgreSQL (traverso_mrp_db)
"""
import logging
import math
from typing import Optional
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas as rl_canvas
from db_mrp import (
    init_db, next_numero_of, next_numero_of_manual, numero_of_tentativo,
    upsert_orden, get_orden_by_key,
    aprobar_orden_db, cancelar_orden_db,
    listar_aprobadas_db, historial_aprobaciones_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ordenes", tags=["Ordenes"])
PDF_DIR = Path("/app/data/ordenes_pdf")
PDF_DIR.mkdir(parents=True, exist_ok=True)

try:
    init_db()
except Exception as e:
    logger.warning(f"[ORDENES] No se pudo inicializar DB MRP: {e}")

# ── V6.46 · u_por_caja: fuente unica = parametros MRP ────────────────────────
# El request NO es confiable. El frontend enviaba `modalOrden.u_por_caja || 1`;
# al EDITAR una OF ya aprobada el objeto del modal no traia el campo, llegaba
# u_por_caja=1 y cantidad_real_u quedaba guardado en CAJAS en vez de unidades.
# Auditoria 31-07-2026: 22 de 24 OF editadas (version>=2) afectadas; 0 de 164
# sin editar. Los lectores (main.py, vigia_ov.py) ya derivan de cantidad_real_cj,
# esto corta el origen. Hermano del bug `0 or 15` (falsy-coalescing).
_UPC_CACHE: dict[str, float] = {}
_UPC_CARGADO = False


def _cargar_upc() -> None:
    """Carga unidades_por_caja de todos los SKU desde parametros MRP (BD, con
    fallback a Excel). Se cachea a nivel modulo: el upc no cambia en runtime."""
    global _UPC_CARGADO
    _UPC_CARGADO = True   # marcar antes: un fallo no debe reintentar en loop
    try:
        import mrp as _mrp
        try:
            sku_params, _, _ = _mrp.load_params_from_db()
            if not sku_params:
                raise ValueError("parametros de BD vacios")
        except Exception:
            sku_params, _, _ = _mrp.load_params_from_excel(
                "/app/data/Traverso_Parametros_MRP.xlsx")
        _UPC_CACHE.clear()
        for _k, _v in sku_params.items():
            _u = getattr(_v, "unidades_por_caja", None)
            if _u:
                _UPC_CACHE[str(_k)] = float(_u)
        logger.info(f"[ORDENES] u_por_caja cargado desde parametros MRP: "
                    f"{len(_UPC_CACHE)} SKU")
    except Exception as e:
        logger.warning(f"[ORDENES] no se pudo cargar u_por_caja desde MRP: {e}")


def _upc_real(sku: str, upc_request: Optional[float] = None) -> float:
    """u_por_caja real del SKU. Prioriza SIEMPRE los parametros MRP; el valor
    del request es solo fallback y se loguea si difiere."""
    sku = str(sku)
    if not _UPC_CARGADO:
        _cargar_upc()
    upc = _UPC_CACHE.get(sku)
    if upc:
        if upc_request and abs(float(upc_request) - upc) > 0.01:
            logger.warning(f"[ORDENES] {sku}: u_por_caja del request="
                           f"{upc_request} != MRP={upc}. Se usa el de MRP.")
        return upc
    fb = float(upc_request or 1.0)
    logger.warning(f"[ORDENES] {sku}: sin u_por_caja en parametros MRP; "
                   f"se usa el del request ({fb}). Revisar carga de parametros.")
    return fb


class OrdenAprobar(BaseModel):
    sku:                    str
    descripcion:            str
    tipo:                   str
    semana_emision:         str
    semana_necesidad:       str
    cantidad_sugerida_cj:   float
    cantidad_real_cj:       float
    u_por_caja:             Optional[float] = None   # V6.46: NO confiable; se resuelve desde params MRP
    responsable:            str
    comentario:             str   = ""
    linea:                  str   = ""
    fecha_lanzamiento:      str   = ""   # F3: fecha sugerida por el optimizer (parte de la clave logica)
    fecha_lanzamiento_real: str   = ""   # F3: fecha real (si el usuario la modifico en el modal)
    fecha_entrada_real:     str   = ""
    numero_of:              str   = ""   # V6.45: identificador para edicion (saltea lookup F3 cuando viene)


def orden_key(sku, semana_necesidad, semana_emision):
    return f"{sku}__{semana_necesidad}__{semana_emision}"


def _parse_date(s):
    if not s: return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


@router.get("/aprobadas")
def listar_aprobadas():
    try:
        rows = listar_aprobadas_db()
        for r in rows:
            r["key"] = orden_key(
                r["sku"],
                str(r["semana_necesidad"])[:10] if r["semana_necesidad"] else "",
                str(r["semana_emision"])[:10] if r["semana_emision"] else "",
            )
            for campo in ["semana_emision", "semana_necesidad",
                          "fecha_lanzamiento_real", "fecha_entrada_real"]:
                if r.get(campo) and not isinstance(r[campo], str):
                    r[campo] = str(r[campo])[:10]
            if r.get("aprobado_en") and not isinstance(r["aprobado_en"], str):
                r["aprobado_en"] = str(r["aprobado_en"])
        return rows
    except Exception as e:
        logger.exception("Error listando aprobadas")
        raise HTTPException(status_code=500, detail=str(e))


def _calcular_fecha_entrada(fecha_manual, fecha_lanz, cantidad_cj, sku, fallback):
    """
    Calcula fecha_entrada_real.
    Regla: fecha_lanzamiento_real + round(lead_time_semanas × 7) días.
    Sin desborde — una OF no supera la capacidad diaria de la línea.
    Si el usuario editó manualmente la fecha (fecha_manual), se respeta.
    """
    if fecha_manual:
        return fecha_manual
    try:
        from mrp import load_params_from_db
        from datetime import date, timedelta
        sku_params, _, _ = load_params_from_db()
        p = sku_params.get(sku)
        if not p:
            return fallback
        lt_dias = round(p.lead_time_semanas * 7)
        fecha_ini = date.fromisoformat(str(fecha_lanz)[:10])
        return (fecha_ini + timedelta(days=lt_dias)).isoformat()
    except Exception as e:
        logger.warning(f"fecha_entrada_real fallback: {e}")
        return fallback


@router.post("/aprobar")
def aprobar_orden(req: OrdenAprobar):
    try:
        _upc = _upc_real(req.sku, req.u_por_caja)   # V6.46
        sn = req.semana_necesidad[:10]
        se = req.semana_emision[:10]
        # F3 (12/05/2026): clave logica es (sku, fecha_lanzamiento, linea).
        # Cascada de fallbacks: fecha_lanzamiento_real (si el usuario la edito) >
        # fecha_lanzamiento (sugerida por el optimizer) > semana_emision.
        fl_str = (req.fecha_lanzamiento_real or req.fecha_lanzamiento or se)[:10]
        linea_req = req.linea or ""
        # V6.45: si el request trae numero_of (edicion de OF aprobada), usamos
        # ESE numero como identificador estable. Sin esto, al editar la fecha
        # de lanzamiento el lookup F3 fallaba (busca por la NUEVA fecha que
        # aun no existe en BD), creando una OF duplicada con numero distinto.
        if req.numero_of:
            numero_of = req.numero_of
        else:
            existente = get_orden_by_key(req.sku, fl_str, linea_req)
            numero_of = existente["numero_of"] if existente and existente.get("numero_of") else next_numero_of()

        upsert_orden({
            "numero_of":            numero_of,
            "sku":                  req.sku,
            "descripcion":          req.descripcion,
            "tipo":                 req.tipo,
            "semana_emision":       _parse_date(se),
            "semana_necesidad":     _parse_date(sn),
            "fecha_lanzamiento":    _parse_date(fl_str),
            "cantidad_sugerida_cj": req.cantidad_sugerida_cj,
            "cantidad_sugerida_u":  req.cantidad_sugerida_cj * _upc,
            "u_por_caja":           _upc,
            "linea":                req.linea,
        })

        aprobacion = aprobar_orden_db(numero_of, {
            "sku":                    req.sku,
            "cantidad_real_cj":       req.cantidad_real_cj,
            "cantidad_real_u":        round(req.cantidad_real_cj * _upc),
            "fecha_lanzamiento_real": _parse_date(req.fecha_lanzamiento_real or se),
            "fecha_entrada_real":     _parse_date(_calcular_fecha_entrada(
                req.fecha_entrada_real or None, req.fecha_lanzamiento_real or se,
                req.cantidad_real_cj, req.sku, sn
            )),
            "responsable":            req.responsable,
            "comentario":             req.comentario,
            "semana_emision":         se,
            "semana_necesidad":       sn,
        })

        logger.info(f"[ORDEN] {numero_of} aprobada: {req.sku} · {sn} · {req.cantidad_real_cj:.0f} cj · {req.responsable}")

        return {
            "key":                    orden_key(req.sku, sn, se),
            "numero_of":              numero_of,
            "sku":                    req.sku,
            "descripcion":            req.descripcion,
            "tipo":                   req.tipo,
            "semana_emision":         se,
            "semana_necesidad":       sn,
            "cantidad_sugerida_cj":   req.cantidad_sugerida_cj,
            "cantidad_real_cj":       req.cantidad_real_cj,
            "cantidad_real_u":        round(req.cantidad_real_cj * _upc),
            "fecha_lanzamiento_real": req.fecha_lanzamiento_real or se,
            "fecha_entrada_real":     req.fecha_entrada_real or sn,
            "responsable":            req.responsable,
            "comentario":             req.comentario,
            "linea":                  req.linea,
            "modificada":             req.cantidad_real_cj != req.cantidad_sugerida_cj or bool(req.fecha_entrada_real),
            "version":                aprobacion["version"],
            "timestamp":              aprobacion["created_at"],
        }
    except Exception as e:
        logger.exception("Error aprobando orden")
        raise HTTPException(status_code=500, detail=str(e))


class OrdenManual(BaseModel):
    sku:               str
    descripcion:       str   = ""
    linea:             str
    cantidad_cj:       float
    u_por_caja:        Optional[float] = None   # V6.46: NO confiable; se resuelve desde params MRP
    fecha_lanzamiento: str            # día en la línea (grid Detalle Producción)
    fecha_entrada:     str   = ""     # opcional; si vacío se calcula por lead time
    responsable:       str   = ""
    comentario:        str   = ""


@router.post("/crear-manual")
def crear_orden_manual(req: OrdenManual):
    """
    OF manual del planificador. Cae al MISMO circuito que /aprobar:
    upsert en mrp_ordenes + inserción APROBADA en mrp_aprobaciones, de modo
    que el optimizer la trata como entrada_fija y el Stock Diario live la
    superpone. Se distingue por el prefijo OFM- en numero_of.
    """
    try:
        _upc = _upc_real(req.sku, req.u_por_caja)   # V6.46
        fl = req.fecha_lanzamiento[:10]
        fe = _calcular_fecha_entrada(
            req.fecha_entrada or None, fl, req.cantidad_cj, req.sku, fl
        )
        # Clave natural del modelo: (sku, fecha_lanzamiento, linea) es UNICA.
        # Si ya existe una orden en ese slot (p.ej. una OFM cancelada, cuya fila
        # en mrp_ordenes persiste), reutilizamos su numero_of y re-aprobamos
        # (misma logica que /aprobar). Evita la violacion de uq_orden_sku_fecha_linea
        # y no prolifera numeros. Slot libre -> nueva OFM-NNNNNN.
        existente = get_orden_by_key(req.sku, fl, req.linea)
        reutilizada = bool(existente and existente.get("numero_of"))
        numero_of = existente["numero_of"] if reutilizada else next_numero_of_manual()

        upsert_orden({
            "numero_of":            numero_of,
            "sku":                  req.sku,
            "descripcion":          req.descripcion,
            "tipo":                 "PRODUCCION",
            "semana_emision":       _parse_date(fl),   # informativo
            "semana_necesidad":     _parse_date(fe),   # informativo
            "fecha_lanzamiento":    _parse_date(fl),   # clave lógica + capacidad
            "cantidad_sugerida_cj": req.cantidad_cj,   # manual: sugerido = real
            "cantidad_sugerida_u":  round(req.cantidad_cj * _upc),
            "u_por_caja":           _upc,
            "linea":                req.linea,
            "motivo":               "MANUAL",
        })

        aprobacion = aprobar_orden_db(numero_of, {
            "sku":                    req.sku,
            "cantidad_real_cj":       req.cantidad_cj,
            "cantidad_real_u":        round(req.cantidad_cj * _upc),
            "fecha_lanzamiento_real": _parse_date(fl),
            "fecha_entrada_real":     _parse_date(fe),
            "responsable":            req.responsable or "Manual",
            "comentario":             req.comentario,
        })

        logger.info(f"[OFM] {numero_of} creada: {req.sku} · {req.linea} · {fl} · {req.cantidad_cj:.0f} cj")

        return {
            "ok":                     True,
            "numero_of":              numero_of,
            "manual":                 True,
            "reutilizada":            reutilizada,
            "sku":                    req.sku,
            "descripcion":            req.descripcion,
            "tipo":                   "PRODUCCION",
            "linea":                  req.linea,
            "cantidad_real_cj":       req.cantidad_cj,
            "cantidad_real_u":        round(req.cantidad_cj * _upc),
            "fecha_lanzamiento_real": fl,
            "fecha_entrada_real":     fe,
            "responsable":            req.responsable or "Manual",
            "comentario":             req.comentario,
            "version":                aprobacion["version"],
            "timestamp":              aprobacion["created_at"],
        }
    except Exception as e:
        logger.exception("Error creando OF manual")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cancelar/{key:path}")
def cancelar_orden(key: str):
    """
    Cancela una OF aprobada (marca todas sus aprobaciones APROBADA como CANCELADA).

    V6.49: acepta dos formatos en el path:
      - numero_of directo: "OF-2026-00010" o "OFT-2026-XXXXX" (preferido,
        introducido en V6.49 — robusto contra cambios de PK).
      - Key legacy: "sku__sn__se" (compatibilidad).

    El formato legacy era roto desde F3: el endpoint pasaba (sku, sn, se) a
    get_orden_by_key cuya firma es (sku, fecha_lanzamiento, linea). Como
    semana_emision != fecha_lanzamiento en F3+, el lookup nunca encontraba
    la orden y devolvia {ok: false} con status 200, dejando el frontend
    creyendo que cancelo cuando en realidad no cancelo nada.
    """
    try:
        # V6.49: si el path es un numero_of (formato OF-YYYY-NNNNN), usar directo
        if key.startswith("OF-") or key.startswith("OFT-") or key.startswith("OFM-"):
            n_cancelados = cancelar_orden_db(key)
            if not n_cancelados:
                return {"ok": False, "mensaje": f"No habia aprobacion activa para {key}"}
            return {"ok": True, "numero_of": key}

        # Legacy: key formato sku__sn__se. NOTA: este lookup esta roto desde F3
        # (pasa (sn,se) donde get_orden_by_key espera (fecha_lanzamiento, linea)).
        # Solo se mantiene por compatibilidad con clientes viejos.
        partes = key.split("__")
        if len(partes) != 3:
            raise HTTPException(status_code=400, detail="Key inválido")
        sku, sn, se = partes
        existente = get_orden_by_key(sku, sn, se)
        if not existente:
            return {"ok": False, "mensaje": "Orden no encontrada (legacy key — usar numero_of)"}
        cancelar_orden_db(existente["numero_of"])
        return {"ok": True, "key": key, "numero_of": existente["numero_of"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aprobadas/resumen")
def resumen_aprobadas():
    try:
        items = listar_aprobadas_db()
        return {
            "total":       len(items),
            "modificadas": sum(1 for o in items if o.get("cantidad_real_cj") != o.get("cantidad_sugerida_cj")),
            "por_tipo":    {t: sum(1 for o in items if o["tipo"] == t)
                           for t in ["PRODUCCION", "IMPORTACION", "MAQUILA"]},
            "ordenes":     items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{numero_of}/historial")
def get_historial(numero_of: str):
    try:
        return historial_aprobaciones_db(numero_of)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{numero_of}/pdf")
def get_pdf_orden(numero_of: str):
    """Retorna el PDF de una orden aprobada. Siempre regenera para tener datos frescos."""
    pdf_path = PDF_DIR / f"{numero_of}.pdf"
    # Buscar la orden en la BD
    from db_mrp import listar_aprobadas_db
    aprobadas = listar_aprobadas_db()
    orden = next((o for o in aprobadas if o.get("numero_of") == numero_of), None)
    if not orden:
        raise HTTPException(status_code=404, detail=f"Orden {numero_of} no encontrada o no aprobada")
    # Enriquecer con u_por_caja real desde parámetros MRP
    try:
        import sys
        sys.path.insert(0, "/app")
        import mrp as _mrp
        MRP_EXCEL = "/app/data/Traverso_Parametros_MRP.xlsx"
        sku_params, _, _ = _mrp.load_params_from_excel(MRP_EXCEL)
        sku = str(orden.get("sku", ""))
        if sku in sku_params:
            orden = dict(orden)
            orden["u_por_caja"] = sku_params[sku].unidades_por_caja
    except Exception as e:
        logger.warning(f"No se pudo obtener u_por_caja desde MRP: {e}")
    _generar_pdf_orden(orden, pdf_path)
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{numero_of}.pdf"
    )


def _generar_pdf_orden(orden: dict, pdf_path: Path):
    """Genera el PDF de una orden de fabricación con diseño profesional."""
    TEAL     = HexColor("#1D9E75")
    TEAL_MID = HexColor("#0F6E56")
    TEAL_LT  = HexColor("#E1F5EE")
    GRAY_LT  = HexColor("#F1EFE8")
    GRAY_MID = HexColor("#D3D1C7")
    GRAY_DK  = HexColor("#5F5E5A")
    TEXT     = HexColor("#2C2C2A")
    AMBER    = HexColor("#EF9F27")
    AMBER_LT = HexColor("#FAEEDA")
    DANGER   = HexColor("#E24B4A")

    W, H = A4
    LM, RM, TM, BM = 1.8*cm, 1.8*cm, 1.5*cm, 1.8*cm
    TW = W - LM - RM

    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)

    # ── Header ────────────────────────────────────────────────────────────────
    c.setFillColor(TEAL)
    c.rect(0, H - 28, W, 28, fill=1, stroke=0)
    c.setFillColor(TEAL_MID)
    c.rect(W - 200, H - 28, 200, 28, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LM, H - 18, "TRAVERSO S.A.  ·  Orden de Fabricación")
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - RM, H - 12, orden.get("numero_of", ""))
    c.setFont("Helvetica", 8)
    c.setFillColor(TEAL_LT)
    c.drawRightString(W - RM, H - 23, "Sistema de Planificación de Producción")

    # ── Número OF grande ──────────────────────────────────────────────────────
    y = H - 28 - 20
    c.setFillColor(TEAL_LT)
    c.roundRect(LM, y - 50, TW, 50, 5, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.roundRect(LM, y - 50, TW, 50, 5, fill=0, stroke=1)
    c.setFillColor(TEAL_MID)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(W/2, y - 33, orden.get("numero_of", ""))
    c.setFillColor(GRAY_DK)
    c.setFont("Helvetica", 9)
    tipo = orden.get("tipo", "")
    tipo_label = "ORDEN DE PRODUCCIÓN" if tipo == "PRODUCCION" else "ORDEN DE IMPORTACIÓN" if tipo == "IMPORTACION" else "ORDEN DE MAQUILA"
    c.drawCentredString(W/2, y - 45, tipo_label)
    y -= 60

    # ── Sección SKU ───────────────────────────────────────────────────────────
    def section(title, ypos):
        c.setFillColor(TEAL_MID)
        c.rect(LM, ypos - 2, TW, 16, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(LM + 6, ypos + 3, title.upper())
        return ypos - 20

    def row(label, value, ypos, col=TEXT, bold=False):
        c.setFillColor(GRAY_LT)
        c.rect(LM, ypos - 2, TW * 0.35, 14, fill=1, stroke=0)
        c.setFillColor(GRAY_DK)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(LM + 5, ypos + 2, label)
        c.setFillColor(col)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.drawString(LM + TW * 0.35 + 8, ypos + 2, str(value) if value else "—")
        # Borde
        c.setStrokeColor(GRAY_MID)
        c.setLineWidth(0.3)
        c.rect(LM, ypos - 2, TW, 14, fill=0, stroke=1)
        return ypos - 16

    y = section("Producto", y)
    y = row("SKU (Código SAP)", orden.get("sku", ""), y, bold=True)
    y = row("Descripción", orden.get("descripcion", ""), y)
    y = row("Tipo abastecimiento", orden.get("tipo", ""), y)
    y = row("Línea de producción", orden.get("linea", "") or "—", y)
    y -= 8

    # ── Cantidades ────────────────────────────────────────────────────────────
    y = section("Cantidades", y)

    # Dos columnas: sugerida vs real
    col_w = (TW - 4) / 2
    u_caja  = float(orden.get("u_por_caja") or 1)
    sug_cj  = orden.get("cantidad_sugerida_cj")
    real_cj = orden.get("cantidad_real_cj")
    sug_u   = round(float(sug_cj)  * u_caja) if sug_cj  else "—"
    real_u  = round(float(real_cj) * u_caja) if real_cj else "—"
    for i, (label, val_sug, val_real) in enumerate([
        ("Cajas",    sug_cj,  real_cj),
        ("Unidades", sug_u,   real_u),
    ]):
        # Header primera vez
        if i == 0:
            c.setFillColor(GRAY_DK)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(LM + TW * 0.3 + 5, y + 2, "Sugerido MRP")
            c.drawString(LM + TW * 0.3 + col_w/2 + 5, y + 2, "Real aprobado")
            c.setStrokeColor(GRAY_MID)
            c.setLineWidth(0.3)
            c.rect(LM, y - 2, TW, 14, fill=0, stroke=1)
            y -= 16

        c.setFillColor(GRAY_LT)
        c.rect(LM, y - 2, TW * 0.3, 14, fill=1, stroke=0)
        c.setFillColor(GRAY_DK)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(LM + 5, y + 2, label)

        # Valor sugerido
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 9)
        sug_str = f"{float(val_sug):,.0f}" if val_sug and val_sug != "—" else "—"
        c.drawString(LM + TW * 0.3 + 8, y + 2, sug_str)

        # Valor real (destacado si difiere)
        real_str = f"{float(val_real):,.0f}" if val_real and val_real != "—" else "—"
        difiere = str(val_sug) != str(val_real)
        c.setFillColor(AMBER if difiere else TEAL_MID)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(LM + TW * 0.3 + col_w/2 + 8, y + 2, real_str)
        if difiere:
            c.setFillColor(AMBER_LT)
            c.roundRect(LM + TW * 0.3 + col_w/2 + 4, y - 1, col_w/2 - 4, 12, 2, fill=1, stroke=0)
            c.setFillColor(AMBER)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(LM + TW * 0.3 + col_w/2 + 8, y + 2, real_str + "  ⚡")

        c.setStrokeColor(GRAY_MID)
        c.setLineWidth(0.3)
        c.rect(LM, y - 2, TW, 14, fill=0, stroke=1)
        y -= 16

    y -= 8

    # ── Fechas ────────────────────────────────────────────────────────────────
    y = section("Fechas", y)

    fechas = [
        ("Semana emisión (MRP)",    str(orden.get("semana_emision",  ""))[:10]),
        ("Semana entrada stock (MRP)", str(orden.get("semana_necesidad",""))[:10]),
        ("Fecha lanzamiento real",  str(orden.get("fecha_lanzamiento_real",""))[:10]),
        ("Fecha entrada stock real", str(orden.get("fecha_entrada_real",""))[:10]),
    ]
    for label, val in fechas:
        es_real = "real" in label.lower()
        color = TEAL_MID if es_real else TEXT
        y = row(label, val, y, col=color, bold=es_real)

    y -= 8

    # ── Aprobación ────────────────────────────────────────────────────────────
    y = section("Aprobación", y)
    y = row("Aprobado por", orden.get("responsable", ""), y, bold=True)
    y = row("Fecha aprobación", str(orden.get("aprobado_en", ""))[:16], y)
    y = row("Comentario", orden.get("comentario", "") or "—", y)
    y -= 8

    # ── Motivo MRP ────────────────────────────────────────────────────────────
    if orden.get("motivo"):
        y = section("Detalle cálculo MRP", y)
        # Parsear motivo FC:X SS:X Stock:X Neta:X
        import re
        motivo = orden.get("motivo", "")
        campos = {"FC": "Forecast semana (cj)", "SS": "Stock seguridad (cj)",
                  "Stock": "Stock inicial (cj)", "Neta": "Necesidad neta (cj)"}
        for key_m, label_m in campos.items():
            match = re.search(rf"{key_m}:([\d.]+)", motivo)
            val_m = f"{float(match.group(1)):,.0f}" if match else "—"
            y = row(label_m, val_m, y)
        y -= 8

    # ── Footer ────────────────────────────────────────────────────────────────
    c.setFillColor(GRAY_MID)
    c.rect(0, 0, W, 18, fill=1, stroke=0)
    c.setFillColor(GRAY_DK)
    c.setFont("Helvetica", 7)
    c.drawString(LM, 6, f"Traverso S.A.  ·  {orden.get('numero_of', '')}  ·  Generado: {datetime.now().strftime('%d-%m-%Y %H:%M')}  ·  Confidencial")
    c.drawRightString(W - RM, 6, "Sistema de Planificación de Producción v1.1")

    c.save()
    logger.info(f"[PDF] Generado: {pdf_path}")


@router.get("/numero-tentativo")
def get_numero_tentativo(sku: str, semana_necesidad: str, semana_emision: str):
    try:
        existente = get_orden_by_key(sku, semana_necesidad[:10], semana_emision[:10])
        if existente and existente.get("numero_of"):
            return {"numero_of": existente["numero_of"], "tipo": "definitivo"}
        return {"numero_of": numero_of_tentativo(sku, semana_necesidad, semana_emision), "tipo": "tentativo"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
