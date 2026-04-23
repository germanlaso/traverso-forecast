"""
seasonality.py — Regressores de estacionalidad por categoría comercial
Traverso S.A. · Piloto de Forecast

CÓMO FUNCIONA:
  Prophet modela: demanda = tendencia + estacionalidad + Σ(regressores) + error

  Cada regressor es una columna binaria (0/1) en el DataFrame de entrenamiento.
  Prophet aprende durante el entrenamiento cuánto sube o baja la demanda cuando
  esa columna vale 1. Ese coeficiente aprendido se aplica automáticamente al
  forecastear períodos futuros donde el evento volverá a ocurrir.

AGREGAR NUEVOS REGRESSORES:
  1. Define las fechas en get_category_regressors() para la categoría que corresponda
  2. Usa _semanas_del_rango() o _semanas_previas_fecha() para calcular las semanas
  3. El pipeline de entrenamiento los aplica automáticamente según Categ. Comercial

CATEGORÍAS ACTUALES:
  - LIMON:   verano (dic–mar) + semanas previas a Semana Santa
  - VINAGRE: verano (dic–mar)
  - SALSAS:  semanas previas a Fiestas Patrias + temporada calor (oct–mar)
  - SOPAS:   temporada fría (may–ago)
"""

from datetime import date, timedelta

# ── Años cubiertos: historial + horizonte de forecast ─────────────────────────
_YEARS = list(range(2021, 2029))


# ── Utilidades de fechas ──────────────────────────────────────────────────────

def _semanas_del_rango(inicio: date, fin: date) -> list[str]:
    """Todos los lunes dentro de un rango de fechas."""
    semanas = []
    d = inicio - timedelta(days=inicio.weekday())  # retroceder al lunes
    while d <= fin:
        semanas.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return semanas


def _semana_santa(year: int) -> list[str]:
    """
    Calcula las 3 semanas previas a Viernes Santo para un año dado.
    Usa el algoritmo de Gauss para calcular el Domingo de Pascua.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = ((h + l - 7 * m + 114) % 31) + 1
    pascua = date(year, month, day)
    viernes_santo = pascua - timedelta(days=2)
    lunes_ref = viernes_santo - timedelta(days=viernes_santo.weekday())
    return [(lunes_ref - timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(3)]


def _semanas_previas_fecha(year: int, mes: int, dia: int, n: int = 4) -> list[str]:
    """N semanas previas (inclusive) a una fecha específica."""
    fecha    = date(year, mes, dia)
    lunes    = fecha - timedelta(days=fecha.weekday())
    return [(lunes - timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(n)]


def _temporada(meses: list[int]) -> list[str]:
    """
    Todas las semanas que caen en los meses indicados para todos los años en _YEARS.
    Permite meses > 12 para indicar "mes del año siguiente"
    (ej: [12, 13, 14, 15] = dic, ene, feb, mar del año siguiente).
    """
    semanas = []
    for y in _YEARS:
        for m in meses:
            mes_real  = m if m <= 12 else m - 12
            year_real = y if m <= 12 else y + 1
            try:
                inicio = date(year_real, mes_real, 1)
                if mes_real == 12:
                    fin = date(year_real + 1, 1, 1) - timedelta(days=1)
                else:
                    fin = date(year_real, mes_real + 1, 1) - timedelta(days=1)
                semanas += _semanas_del_rango(inicio, fin)
            except ValueError:
                pass
    return sorted(set(semanas))


# ── Definición de regressores por categoría ───────────────────────────────────

def get_category_regressors(categoria: str) -> list[dict]:
    """
    Retorna la lista de regressores para una categoría comercial.

    Cada regressor es un dict con:
        name:   nombre de la columna en el DataFrame Prophet (sin espacios)
        label:  descripción legible para el dashboard
        dates:  lista de fechas ISO (lunes de cada semana afectada)
        value:  siempre 1.0 — Prophet aprende el coeficiente real durante el entrenamiento

    IMPORTANTE sobre 'value':
        No representa el % de aumento — ese lo aprende Prophet del historial.
        Es simplemente el indicador de que el evento está activo esa semana.
        Si quieres explorar el efecto aprendido post-entrenamiento, usa
        model.params['beta'] después de entrenar.
    """
    cat = (categoria or "").strip().upper()

    # ── LIMÓN ─────────────────────────────────────────────────────────────────
    if cat == "LIMON":
        return [
            {
                "name":  "verano_limon",
                "label": "Temporada verano dic–mar (ensaladas, pescados, mariscos)",
                "dates": _temporada([12, 13, 14, 15]),   # dic, ene, feb, mar
                "value": 1.0,
            },
            {
                "name":  "semana_santa",
                "label": "Semanas previas a Semana Santa (peak limón)",
                "dates": sorted(set(
                    s for y in _YEARS for s in _semana_santa(y)
                )),
                "value": 1.0,
            },
        ]

    # ── VINAGRE ───────────────────────────────────────────────────────────────
    if cat == "VINAGRE":
        return [
            {
                "name":  "verano_vinagre",
                "label": "Temporada verano dic–mar (ensaladas, pescados, mariscos)",
                "dates": _temporada([12, 13, 14, 15]),
                "value": 1.0,
            },
        ]

    # ── SALSAS ────────────────────────────────────────────────────────────────
    if cat == "SALSAS":
        return [
            {
                "name":  "fiestas_patrias",
                "label": "4 semanas previas a Fiestas Patrias (asados)",
                "dates": sorted(set(
                    s for y in _YEARS for s in _semanas_previas_fecha(y, 9, 18, n=4)
                )),
                "value": 1.0,
            },
            {
                "name":  "temporada_calor_salsas",
                "label": "Temporada calor oct–mar (asados y parrilla)",
                "dates": _temporada([10, 11, 12, 13, 14, 15]),  # oct–mar
                "value": 1.0,
            },
        ]

    # ── SOPAS ─────────────────────────────────────────────────────────────────
    if cat == "SOPAS":
        return [
            {
                "name":  "temporada_fria",
                "label": "Temporada fría may–ago (mayor consumo de sopas)",
                "dates": _temporada([5, 6, 7, 8]),
                "value": 1.0,
            },
        ]

    # ── Sin regressores específicos para esta categoría ───────────────────────
    return []


def get_all_regressors_summary() -> dict:
    """
    Retorna un resumen de todos los regressores definidos.
    Útil para documentación y para el endpoint /regressors de la API.
    """
    categorias = ["LIMON", "VINAGRE", "SALSAS", "SOPAS"]
    summary = {}
    for cat in categorias:
        regs = get_category_regressors(cat)
        summary[cat] = [
            {
                "name":        r["name"],
                "label":       r["label"],
                "n_semanas":   len(r["dates"]),
                "primera":     r["dates"][0]  if r["dates"] else None,
                "ultima":      r["dates"][-1] if r["dates"] else None,
            }
            for r in regs
        ]
    return summary
