"""
senales_forecast.py — Evaluación PRELIMINAR del forecast por SKU (Análisis de Línea, MVP 1).

Objetivo (decisión 11-11-26): entender cuándo el origen de un quiebre puede estar en el
forecast, antes de mover capacidad. No ajusta el forecast; solo levanta señales con evidencia
para que la IA (y el planificador) las consideren.

Fuentes (las mismas de la pestaña Precisión del forecast, todo en CAJAS):
  mrp_venta_semanal      (sku, semana, venta_cj)              venta real por semana (domingo)
  mrp_forecast_vintage   (sku, semana_objetivo, horizonte_sem, yhat_cj, con_evento)
  detalle del plan       forecast_u de los próximos días       (lo que el plan va a producir)

Señales:
  HISTORIA_CORTA     menos de 52 semanas con venta: el modelo no vio una temporada completa
  ERROR_ALTO         WMAPE h=1 de las últimas 8 semanas cerradas > 35%
  SESGO              sesgo h=1 de las últimas 8 semanas fuera de ±15% (sobre o subdimensionado)
  SALTO_FORECAST     forecast de las próximas 4 semanas > 1,4x la venta promedio de las últimas 8
  PICO_LANZAMIENTO   el forecast sube y la misma semana del año anterior cae en las primeras
                     10 semanas de vida del SKU: el "pico" puede ser llenado de canal, no temporada
  EVENTO             hay eventos activos en las semanas proyectadas (regresores)
SKU con venta promedio < 5 cj/semana: no se calculan % (denominadores chicos).
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import sqlalchemy as sa

UMBRAL_HISTORIA_SEM = 52
UMBRAL_WMAPE = 0.35
UMBRAL_SESGO = 0.15
UMBRAL_SALTO = 1.4
SEMANAS_LANZAMIENTO = 10
UMBRAL_CJ_SEMANA = 5.0
VENTANA_ERROR = 8


def _n(x):   # 1234.5 -> "1.235"
    return f"{x:,.0f}".replace(",", ".")


def _d(x):   # 2.25 -> "2,3"
    return f"{x:.1f}".replace(".", ",")


def _domingo(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def evaluar_sku(sku: str, ventas: dict, vintage_h1: dict, fc_futuro_cj_sem: Optional[float],
                semanas_futuras: list, eventos_futuros: bool, hoy: date) -> dict:
    """Núcleo puro. ventas: {semana(date): cj}; vintage_h1: {semana: yhat_cj};
    fc_futuro_cj_sem: forecast promedio por semana de las próximas 4 (cajas);
    semanas_futuras: domingos de las próximas semanas proyectadas."""
    vigente = _domingo(hoy)
    cerradas = sorted(w for w in ventas if w < vigente)
    con_venta = [w for w in cerradas if (ventas.get(w) or 0) > 0]
    primera = con_venta[0] if con_venta else None
    # semanas desde la primera venta (la tabla puede no tener filas en semanas sin venta)
    historia = ((vigente - primera).days // 7) if primera else 0
    ult = cerradas[-VENTANA_ERROR:]
    venta_rec = (sum(ventas[w] for w in ult) / len(ult)) if ult else 0.0

    senales = []
    if primera is None:
        senales.append({"codigo": "SIN_HISTORIA", "nivel": "alta", "texto": "Sin ventas registradas: el forecast no tiene base."})
    elif historia < UMBRAL_HISTORIA_SEM:
        senales.append({"codigo": "HISTORIA_CORTA", "nivel": "media",
                        "texto": f"Solo {historia} semanas de historia (primera venta {primera:%d-%m-%Y}): "
                                 f"el modelo no vio una temporada completa."})

    wmape = sesgo = None
    pares = [(vintage_h1[w], ventas[w]) for w in ult if w in vintage_h1 and w in ventas]
    if pares and venta_rec >= UMBRAL_CJ_SEMANA:
        real = sum(r for _, r in pares)
        if real > 0:
            wmape = sum(abs(f - r) for f, r in pares) / real
            sesgo = (sum(f for f, _ in pares) - real) / real
            if wmape > UMBRAL_WMAPE:
                senales.append({"codigo": "ERROR_ALTO", "nivel": "media",
                                "texto": f"Error del forecast a 1 semana de {wmape:.0%} (WMAPE, últimas {len(pares)} semanas)."})
            if abs(sesgo) > UMBRAL_SESGO:
                dir_ = "sobredimensionado" if sesgo > 0 else "subdimensionado"
                senales.append({"codigo": "SESGO", "nivel": "media",
                                "texto": f"Forecast {dir_} {abs(sesgo):.0%} en las últimas {len(pares)} semanas."})

    ratio = None
    if fc_futuro_cj_sem is not None and venta_rec >= UMBRAL_CJ_SEMANA:
        ratio = fc_futuro_cj_sem / venta_rec if venta_rec else None
        if ratio and ratio > UMBRAL_SALTO:
            senales.append({"codigo": "SALTO_FORECAST", "nivel": "alta" if ratio > 2 else "media",
                            "texto": f"El forecast de las próximas semanas ({_n(fc_futuro_cj_sem)} cj/sem) es "
                                     f"{_d(ratio)} veces la venta reciente ({_n(venta_rec)} cj/sem)."})
            if primera:
                ly = [w - timedelta(days=364) for w in semanas_futuras]
                en_lanz = [w for w in ly if primera <= w < primera + timedelta(weeks=SEMANAS_LANZAMIENTO)]
                if en_lanz:
                    senales.append({"codigo": "PICO_LANZAMIENTO", "nivel": "alta",
                                    "texto": f"La misma semana del año anterior ({en_lanz[0]:%d-%m-%Y}) cae en las primeras "
                                             f"{SEMANAS_LANZAMIENTO} semanas de vida del SKU: el pico puede ser llenado de "
                                             f"canal del lanzamiento, no temporada."})
    if eventos_futuros:
        senales.append({"codigo": "EVENTO", "nivel": "baja",
                        "texto": "Hay eventos activos (regresores) en las semanas proyectadas."})

    alta = any(s["nivel"] == "alta" for s in senales)
    medias = sum(1 for s in senales if s["nivel"] == "media")
    return {"sku": sku, "historia_semanas": historia, "primera_venta": primera.isoformat() if primera else None,
            "venta_reciente_cj_sem": round(venta_rec, 1),
            "forecast_prox_cj_sem": round(fc_futuro_cj_sem, 1) if fc_futuro_cj_sem is not None else None,
            "ratio_forecast_vs_venta": round(ratio, 2) if ratio else None,
            "wmape_8s": round(wmape, 3) if wmape is not None else None,
            "sesgo_8s": round(sesgo, 3) if sesgo is not None else None,
            "senales": senales, "forecast_sospechoso": alta or medias >= 2}


def senales_forecast(c, skus: list, detalle: dict, sku_params: dict, hoy: Optional[date] = None,
                     semanas_fc: int = 4) -> dict:
    """Carga los datos de la BD (conexión c) y evalúa cada SKU. detalle = detalle_diario del plan."""
    skus = [s for s in dict.fromkeys(skus) if s]
    if not skus:
        return {}
    fechas = sorted({f for dd in detalle.values() for f in dd})
    hoy = hoy or (date.fromisoformat(fechas[0]) if fechas else date.today())
    desde = _domingo(hoy) - timedelta(weeks=60)
    ventas = defaultdict(dict)
    for r in c.execute(sa.text("""SELECT sku, semana, venta_cj::float AS cj FROM mrp_venta_semanal
                                  WHERE sku = ANY(:s) AND semana >= :d"""), {"s": skus, "d": desde - timedelta(weeks=60)}):
        ventas[r.sku][r.semana] = r.cj
    vint, eventos = defaultdict(dict), defaultdict(bool)
    for r in c.execute(sa.text("""SELECT sku, semana_objetivo AS w, horizonte_sem AS h, yhat_cj::float AS y, con_evento
                                  FROM mrp_forecast_vintage WHERE sku = ANY(:s) AND semana_objetivo >= :d"""),
                       {"s": skus, "d": desde}):
        if int(r.h) == 1:
            vint[r.sku][r.w] = r.y
        if r.w >= _domingo(hoy) and r.con_evento:
            eventos[r.sku] = True
    fin = hoy + timedelta(weeks=semanas_fc)
    semanas_fut = sorted({_domingo(hoy + timedelta(weeks=i)) for i in range(semanas_fc)})
    out = {}
    for s in skus:
        upc = float((sku_params.get(s) or {}).get("u_por_caja") or 1) or 1.0
        dd = detalle.get(s, {})
        fc_u = sum(float(v.get("forecast_u") or 0) for f, v in dd.items() if hoy.isoformat() <= f < fin.isoformat())
        fc_cj_sem = (fc_u / upc / semanas_fc) if dd else None
        out[s] = evaluar_sku(s, ventas.get(s, {}), vint.get(s, {}), fc_cj_sem, semanas_fut, eventos.get(s, False), hoy)
    return out
