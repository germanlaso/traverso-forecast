"""
params_diagnostico.py — Motor de diagnóstico de parámetros MRP (línea / SKU).

FUNCIÓN PURA: no toca BD, ni red, ni archivos. Recibe los parámetros ya leídos y
devuelve indicadores derivados + alertas. Se usa en DOS contextos con el mismo
código, de modo que la validación nunca pueda divergir del diagnóstico:

  · Fase 1 (diagnóstico): alimentada con lo que hay hoy en BD  -> GET /params/diagnostico
  · Fase 2 (edición):     alimentada con lo que el usuario propone, ANTES de guardar
                          -> POST /params/diagnostico/simular

Unidades: la capacidad de LÍNEA se expresa solo en unidades (mezcla SKUs con
distinto u_por_caja, las cajas no serían comparables). A nivel SKU se expone todo
en unidades Y cajas.

NOTA: este módulo NO calcula stock de seguridad. La fórmula canónica de SS vive en
calendario.py::calcular_ss_diario (fuente única de verdad); acá solo se muestra el
parámetro ss_dias tal cual está cargado.
"""

from __future__ import annotations

# ── Umbrales de las alertas (ajustables en un solo lugar) ────────────────────
UMBRAL_MARGEN_DIA      = 0.90   # batch que consume >90% de la capacidad diaria -> frágil
UMBRAL_DIAS_COBERTURA  = 30     # batch que cubre >30 días de forecast -> sobrestock
RATIO_CAP_BODEGA_MIN   = 2.0    # cap_bodega debería ser >= 2x batch_min
CAP_BODEGA_INFINITA    = 999999 # centinela usado por los loaders para "sin límite"
DIAS_HABILES_SEMANA    = 5      # para pasar demanda semanal -> diaria

NIVEL_ERROR = "error"
NIVEL_WARN  = "warn"
NIVEL_INFO  = "info"


# ── Helpers ──────────────────────────────────────────────────────────────────
def _f(v, d=0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def _i(v, d=0) -> int:
    try:
        return int(float(v)) if v is not None else d
    except (TypeError, ValueError):
        return d


def _div(a, b):
    """División segura: None si el divisor es 0/None."""
    b = _f(b)
    return (_f(a) / b) if b else None


def _r(v, n=1):
    return None if v is None else round(v, n)


def _alerta(nivel, codigo, mensaje):
    return {"nivel": nivel, "codigo": codigo, "mensaje": mensaje}


# ── Derivados de LÍNEA ───────────────────────────────────────────────────────
def derivados_linea(linea: dict) -> dict:
    """Capacidades nominales de la línea (sin factor de SKU), en unidades."""
    vel    = _f(linea.get("velocidad_u_hr"))
    turnos = _i(linea.get("turnos_dia"), 1)
    horas  = _f(linea.get("horas_turno"), 8)
    dias   = _i(linea.get("dias_semana"), 5)

    cap_turno = vel * horas
    cap_dia   = cap_turno * turnos
    cap_sem   = cap_dia * dias
    return {
        "velocidad_u_hr": vel,
        "horas_dia":      horas * turnos,
        "cap_turno_u":    _r(cap_turno, 0),
        "cap_dia_u":      _r(cap_dia, 0),
        "cap_sem_u":      _r(cap_sem, 0),
        "dias_semana":    dias,
        "turnos_dia":     turnos,
    }


# ── Diagnóstico de un par SKU × LÍNEA ────────────────────────────────────────
def diagnosticar_sku(params_producto: dict,
                     der_linea: dict,
                     params_en_linea: dict,
                     forecast_semanal_cj: float | None = None) -> dict:
    """Indicadores derivados + alertas para un SKU en una línea concreta.

    params_producto : batch_min_u, batch_mult_u, cap_bodega_u, ss_dias,
                      lead_time_sem, u_por_caja, mto
    der_linea       : salida de derivados_linea()
    params_en_linea : factor_velocidad, t_cambio_hrs, preferida
    forecast_semanal_cj : demanda semanal estimada en cajas (None si no hay plan).
                          El diario se deriva dividiendo por DIAS_HABILES_SEMANA.
    """
    upc        = _i(params_producto.get("u_por_caja"), 1) or 1
    batch_min  = _i(params_producto.get("batch_min_u"))
    batch_mult = _i(params_producto.get("batch_mult_u"), 1) or 1
    cap_bod    = _i(params_producto.get("cap_bodega_u"), CAP_BODEGA_INFINITA)
    ss_dias    = _i(params_producto.get("ss_dias"))
    mto        = bool(params_producto.get("mto"))

    factor  = _f(params_en_linea.get("factor_velocidad"), 1.0)
    t_camb  = _f(params_en_linea.get("t_cambio_hrs"))

    vel_efec   = _f(der_linea.get("velocidad_u_hr")) * factor
    cap_turno  = _f(der_linea.get("cap_turno_u")) * factor
    cap_dia    = _f(der_linea.get("cap_dia_u")) * factor
    cap_sem    = _f(der_linea.get("cap_sem_u")) * factor

    horas_batch  = _div(batch_min, vel_efec)
    pct_dia      = _div(batch_min, cap_dia)          # fracción de un día que consume 1 batch
    cabe_turno   = (batch_min <= cap_turno) if cap_turno else False
    cabe_dia     = (batch_min <= cap_dia) if cap_dia else False

    fc_sem_cj = None if forecast_semanal_cj is None else _f(forecast_semanal_cj)
    fc_sem_u  = None if fc_sem_cj is None else fc_sem_cj * upc
    fc_cj = None if fc_sem_cj is None else fc_sem_cj / DIAS_HABILES_SEMANA
    fc_u  = None if fc_cj is None else fc_cj * upc
    dias_cobertura = _div(batch_min, fc_u) if fc_u else None

    cap_bod_finita = cap_bod < CAP_BODEGA_INFINITA
    ratio_bodega   = _div(cap_bod, batch_min) if cap_bod_finita else None

    derivados = {
        "u_por_caja":        upc,
        "factor_velocidad":  factor,
        "vel_efectiva_u_hr": _r(vel_efec, 0),
        "cap_turno_u":  _r(cap_turno, 0), "cap_turno_cj": _r(cap_turno / upc, 1),
        "cap_dia_u":    _r(cap_dia, 0),   "cap_dia_cj":   _r(cap_dia / upc, 1),
        "cap_sem_u":    _r(cap_sem, 0),   "cap_sem_cj":   _r(cap_sem / upc, 1),
        "batch_min_u":  batch_min,        "batch_min_cj": _r(batch_min / upc, 1),
        "batch_mult_u": batch_mult,       "batch_mult_cj": _r(batch_mult / upc, 2),
        "horas_por_batch":   _r(horas_batch, 2),
        "pct_dia_por_batch": _r((pct_dia * 100) if pct_dia is not None else None, 1),
        "batch_cabe_turno":  cabe_turno,
        "batch_cabe_dia":    cabe_dia,
        "t_cambio_hrs":      t_camb,
        "forecast_sem_cj":    _r(fc_sem_cj, 1),
        "forecast_sem_u":     _r(fc_sem_u, 0),
        "forecast_diario_cj": _r(fc_cj, 1),
        "forecast_diario_u":  _r(fc_u, 0),
        # Días de máquina que consume la demanda semanal de este SKU en ESTA línea.
        # Es el insumo de la carga de línea: la suma de todos sus SKU vs días hábiles.
        "dias_prod_sem":  _r(_div(fc_sem_u, cap_dia), 2) if fc_sem_u else None,
        "lotes_sem":      _r(_div(fc_sem_u, batch_min), 2) if (fc_sem_u and batch_min) else None,
        "dias_cobertura_batch": _r(dias_cobertura, 1),
        "semanas_cobertura_batch": _r(_div(dias_cobertura, DIAS_HABILES_SEMANA), 2)
                                    if dias_cobertura is not None else None,
        "cap_bodega_u":  None if not cap_bod_finita else cap_bod,
        "cap_bodega_cj": None if not cap_bod_finita else _r(cap_bod / upc, 1),
        "ratio_cap_bodega": _r(ratio_bodega, 2),
        "lead_time_sem": _f(params_producto.get("lead_time_sem"), 1),
        "ss_dias": ss_dias,
        "mto": mto,
    }

    # ── Alertas ──────────────────────────────────────────────────────────────
    alertas = []

    if not vel_efec:
        alertas.append(_alerta(
            NIVEL_ERROR, "VELOCIDAD_CERO",
            "La velocidad efectiva es 0: el SKU no puede producirse en esta línea."))

    elif batch_min > 0 and not cabe_dia:
        # Caso real 23-07 (SKU 210010115 / 250010115 con factor 0.8 en Doypack 4):
        # el batch no entra en un día de capacidad efectiva y el solver no emite la OFT.
        alertas.append(_alerta(
            NIVEL_ERROR, "BATCH_NO_CABE_DIA",
            f"El batch mínimo ({batch_min:,.0f} u) NO cabe en un día de capacidad "
            f"efectiva ({cap_dia:,.0f} u). El solver puede no emitir la OFT y el stock "
            f"caer a negativo. Bajar el batch, subir el factor o cambiar de línea."))

    elif batch_min > 0 and not cabe_turno:
        alertas.append(_alerta(
            NIVEL_WARN, "BATCH_NO_CABE_TURNO",
            f"El batch mínimo ({batch_min:,.0f} u) no cabe en un turno "
            f"({cap_turno:,.0f} u): requiere más de un turno del día."))

    if batch_min > 0 and cabe_dia and pct_dia is not None and pct_dia > UMBRAL_MARGEN_DIA:
        alertas.append(_alerta(
            NIVEL_WARN, "MARGEN_DIA_AJUSTADO",
            f"Un solo batch consume el {pct_dia*100:,.1f}% de la capacidad diaria: "
            f"margen muy ajustado, cualquier cambio menor lo vuelve infactible."))

    if cap_bod_finita and batch_min > 0 and ratio_bodega is not None \
            and ratio_bodega < RATIO_CAP_BODEGA_MIN:
        alertas.append(_alerta(
            NIVEL_ERROR, "CAP_BODEGA_INSUFICIENTE",
            f"La capacidad de bodega ({cap_bod:,.0f} u) es menor a "
            f"{RATIO_CAP_BODEGA_MIN:g}x el batch mínimo ({batch_min:,.0f} u): "
            f"puede volver infactible la producción."))

    if batch_min > 0 and batch_mult > 1 and (batch_min % batch_mult) != 0:
        alertas.append(_alerta(
            NIVEL_WARN, "BATCH_NO_MULTIPLO",
            f"El batch mínimo ({batch_min:,.0f} u) no es múltiplo del múltiplo de "
            f"batch ({batch_mult:,.0f} u): el lote real se redondeará hacia arriba."))

    if dias_cobertura is not None and dias_cobertura > UMBRAL_DIAS_COBERTURA:
        alertas.append(_alerta(
            NIVEL_WARN, "SOBRESTOCK",
            f"Un batch cubre {dias_cobertura:,.0f} días de demanda "
            f"(> {UMBRAL_DIAS_COBERTURA}): riesgo de sobrestock y de vida útil."))

    if mto and ss_dias > 0:
        alertas.append(_alerta(
            NIVEL_WARN, "MTO_CON_SS",
            f"SKU marcado MTO (contra pedido) pero con stock de seguridad "
            f"de {ss_dias} días: revisar coherencia."))

    if factor and factor < 1.0:
        alertas.append(_alerta(
            NIVEL_INFO, "FACTOR_REDUCIDO",
            f"Factor de velocidad {factor:g}: la línea rinde "
            f"{(1-factor)*100:,.0f}% menos para este SKU."))

    if fc_u is None:
        alertas.append(_alerta(
            NIVEL_INFO, "SIN_FORECAST",
            "Sin forecast en el plan vigente (típico en MTO): no se puede estimar "
            "cuántos días cubre el batch."))

    return {"derivados": derivados, "alertas": alertas}


# ── Árbol completo línea -> SKU ──────────────────────────────────────────────
def construir_diagnostico(lineas: list[dict],
                          sku_params: list[dict],
                          sku_lineas: list[dict],
                          forecast_semanal_cj: dict | None = None,
                          skus_inactivos: set | None = None) -> dict:
    """Arma el árbol de diagnóstico.

    lineas     : get_all_lineas()      -> [{codigo, nombre, area, turnos_dia, ...}]
    sku_params : get_all_sku_params()  -> [{sku, descripcion, batch_min_u, ...}]  (solo activos)
    sku_lineas : get_all_sku_lineas()  -> [{sku, linea, factor_velocidad, preferida, ...}]
    forecast_semanal_cj : {sku: cajas/semana} (promedio del plan vigente); puede ser None/{}.
    skus_inactivos : set de SKU que existen pero están activo=FALSE. Sirve para no
                     reportarlos como error de integridad cuando conservan su
                     asignación de línea (caso normal, no un problema de datos).
    """
    forecast_semanal_cj = forecast_semanal_cj or {}
    skus_inactivos = skus_inactivos or set()
    p_by_sku = {str(p["sku"]).strip(): p for p in sku_params}

    # pares por línea, y líneas por SKU (para el badge "también en ...")
    pares_por_linea: dict[str, list[dict]] = {}
    lineas_por_sku: dict[str, list[str]] = {}
    for par in sku_lineas:
        sku = str(par.get("sku") or "").strip()
        lin = str(par.get("linea") or "").strip()
        if not sku or not lin:
            continue
        pares_por_linea.setdefault(lin, []).append(par)
        lineas_por_sku.setdefault(sku, []).append(lin)

    out_lineas = []
    skus_con_linea: set[str] = set()
    tot_err = tot_warn = 0

    for lin in sorted(lineas, key=lambda x: str(x.get("codigo") or "")):
        cod = str(lin.get("codigo") or "").strip()
        der_l = derivados_linea(lin)
        items = []

        for par in sorted(pares_por_linea.get(cod, []), key=lambda x: str(x.get("sku"))):
            sku = str(par.get("sku") or "").strip()
            prod = p_by_sku.get(sku)
            if prod is None:
                # El SKU no está entre los activos. Dos casos muy distintos:
                #  · inactivo  -> normal, conserva su asignación de línea (info)
                #  · inexistente -> problema real de integridad de datos (error)
                inactivo = sku in skus_inactivos
                items.append({
                    "sku": sku,
                    "descripcion": "(SKU inactivo)" if inactivo else "(sin parámetros de SKU)",
                    "params_producto": {}, "params_en_linea": dict(par),
                    "derivados": {}, "preferida": bool(par.get("preferida")),
                    "otras_lineas": [l for l in lineas_por_sku.get(sku, []) if l != cod],
                    "inactivo": inactivo,
                    "alertas": [_alerta(
                        NIVEL_INFO, "SKU_INACTIVO",
                        "SKU marcado como inactivo; conserva la asignación de línea pero "
                        "no entra en la planificación.")
                        if inactivo else _alerta(
                        NIVEL_ERROR, "SKU_SIN_PARAMS",
                        "El par SKU-línea existe pero el SKU no está en mrp_sku_params.")],
                })
                if not inactivo:
                    tot_err += 1
                continue

            skus_con_linea.add(sku)
            params_producto = {
                "batch_min_u":   _i(prod.get("batch_min_u")),
                "batch_mult_u":  _i(prod.get("batch_mult_u"), 1),
                "cap_bodega_u":  _i(prod.get("cap_bodega_u"), CAP_BODEGA_INFINITA),
                "ss_dias":       _i(prod.get("ss_dias")),
                "lead_time_sem": _f(prod.get("lead_time_sem"), 1),
                "u_por_caja":    _i(prod.get("u_por_caja"), 1) or 1,
                "mto":           bool(prod.get("mto")),
            }
            params_en_linea = {
                "factor_velocidad": _f(par.get("factor_velocidad"), 1.0),
                "t_cambio_hrs":     _f(par.get("t_cambio_hrs")),
                "preferida":        bool(par.get("preferida")),
            }
            diag = diagnosticar_sku(params_producto, der_l, params_en_linea,
                                    forecast_semanal_cj.get(sku))
            tot_err  += sum(1 for a in diag["alertas"] if a["nivel"] == NIVEL_ERROR)
            tot_warn += sum(1 for a in diag["alertas"] if a["nivel"] == NIVEL_WARN)

            items.append({
                "sku": sku,
                "descripcion": prod.get("descripcion") or "",
                "categoria": prod.get("categoria") or "",
                "params_producto": params_producto,   # global del SKU (todas sus líneas)
                "params_en_linea": params_en_linea,   # solo en ESTA línea
                "derivados": diag["derivados"],
                "alertas": diag["alertas"],
                "preferida": params_en_linea["preferida"],
                "otras_lineas": [l for l in lineas_por_sku.get(sku, []) if l != cod],
            })

        n_err  = sum(1 for it in items for a in it["alertas"] if a["nivel"] == NIVEL_ERROR)
        n_warn = sum(1 for it in items for a in it["alertas"] if a["nivel"] == NIVEL_WARN)

        # Carga de la línea, medida en DÍAS DE MÁQUINA por semana.
        # Se separa en:
        #   · cautiva  -> SKU que solo pueden producirse en esta línea (piso irreducible)
        #   · flexible -> SKU con línea alternativa (podrían moverse)
        # OJO: la carga total puede estar sobrestimada cuando hay SKU multi-línea, porque
        # a cada línea se le imputa la demanda COMPLETA del SKU. El rango
        # [cautiva, total] acota la carga real.
        dias_cautivos = dias_flexibles = 0.0
        dem_sem_u = 0.0
        for it in items:
            dp = _f(it["derivados"].get("dias_prod_sem"))
            dem_sem_u += _f(it["derivados"].get("forecast_sem_u"))
            if it.get("otras_lineas"):
                dias_flexibles += dp
            else:
                dias_cautivos += dp
        dias_totales = dias_cautivos + dias_flexibles
        dsem = der_l["dias_semana"] or 5
        carga_pct     = (dias_totales / dsem * 100) if dsem else None
        cautiva_pct   = (dias_cautivos / dsem * 100) if dsem else None
        flexible_pct  = (dias_flexibles / dsem * 100) if dsem else None

        out_lineas.append({
            "codigo": cod,
            "nombre": lin.get("nombre") or "",
            "area":   lin.get("area") or "",
            "activa": bool(lin.get("activa", True)),
            "params": {   # futuros campos editables de la línea
                "turnos_dia":     der_l["turnos_dia"],
                "horas_turno":    _f(lin.get("horas_turno"), 8),
                "dias_semana":    der_l["dias_semana"],
                "velocidad_u_hr": der_l["velocidad_u_hr"],
            },
            "derivados": {
                **der_l,
                "demanda_sem_estimada_u": _r(dem_sem_u, 0),
                "dias_prod_necesarios":   _r(dias_totales, 2),
                "dias_prod_cautivos":     _r(dias_cautivos, 2),
                "dias_prod_flexibles":    _r(dias_flexibles, 2),
                "dias_disponibles":       dsem,
                "carga_pct":          _r(carga_pct, 1),
                "carga_cautiva_pct":  _r(cautiva_pct, 1),
                "carga_flexible_pct": _r(flexible_pct, 1),
                "holgura_dias": _r(dsem - dias_totales, 2),
                "holgura_u": _r(_f(der_l["cap_sem_u"]) - dem_sem_u, 0),
            },
            "n_skus": len(items),
            "n_flexibles": sum(1 for it in items if it.get("otras_lineas")),
            "n_errores": n_err,
            "n_warnings": n_warn,
            "skus": items,
        })

    # ── Anotación cruzada de alternativas ────────────────────────────────────
    # Para cada SKU que puede correr en más de una línea, se anota qué costaría
    # producirlo en cada alternativa (días de máquina allí, que dependen de la
    # velocidad y el factor de ESA línea) y cómo está cargada esa línea hoy.
    # Es lo que permite responder "¿hay dónde absorber el exceso?".
    dias_por_par = {}     # (sku, linea) -> dias_prod_sem
    linea_por_cod = {}    # codigo -> dict de la línea de salida
    for l in out_lineas:
        linea_por_cod[l["codigo"]] = l
        for it in l["skus"]:
            dias_por_par[(it["sku"], l["codigo"])] = it["derivados"].get("dias_prod_sem")

    for l in out_lineas:
        for it in l["skus"]:
            alts = []
            for otra in it.get("otras_lineas", []):
                lo = linea_por_cod.get(otra)
                if lo is None:
                    continue
                d_alli = dias_por_par.get((it["sku"], otra))
                alts.append({
                    "linea": otra,
                    "dias_prod_sem": d_alli,
                    "carga_pct": lo["derivados"].get("carga_pct"),
                    "holgura_dias": lo["derivados"].get("holgura_dias"),
                    # ¿la holgura de esa línea alcanza para absorber este SKU?
                    "absorbe": (d_alli is not None
                                and lo["derivados"].get("holgura_dias") is not None
                                and _f(lo["derivados"]["holgura_dias"]) >= _f(d_alli)),
                })
            it["alternativas"] = alts

    # ── SKU sin línea asignada ───────────────────────────────────────────────
    sin_linea = []
    for sku, prod in sorted(p_by_sku.items()):
        if sku in skus_con_linea or sku in lineas_por_sku:
            continue
        sin_linea.append({
            "sku": sku,
            "descripcion": prod.get("descripcion") or "",
            "categoria": prod.get("categoria") or "",
            "tipo": prod.get("tipo") or "",
            "activo": bool(prod.get("activo", True)),
            "params_producto": {
                "batch_min_u":   _i(prod.get("batch_min_u")),
                "batch_mult_u":  _i(prod.get("batch_mult_u"), 1),
                "cap_bodega_u":  _i(prod.get("cap_bodega_u"), CAP_BODEGA_INFINITA),
                "ss_dias":       _i(prod.get("ss_dias")),
                "lead_time_sem": _f(prod.get("lead_time_sem"), 1),
                "u_por_caja":    _i(prod.get("u_por_caja"), 1) or 1,
                "mto":           bool(prod.get("mto")),
            },
            "alertas": [_alerta(
                NIVEL_INFO, "SIN_LINEA",
                "SKU sin línea de producción asignada (importado/comprado, o falta "
                "asignarlo).")],
        })

    return {
        "lineas": out_lineas,
        "sin_linea": sin_linea,
        "resumen": {
            "n_lineas": len(out_lineas),
            "n_skus": len(p_by_sku),
            "n_pares": sum(len(v) for v in pares_por_linea.values()),
            "n_sin_linea": len(sin_linea),
            "n_errores": tot_err,
            "n_warnings": tot_warn,
            "umbrales": {
                "margen_dia": UMBRAL_MARGEN_DIA,
                "dias_cobertura": UMBRAL_DIAS_COBERTURA,
                "ratio_cap_bodega": RATIO_CAP_BODEGA_MIN,
            },
        },
    }
