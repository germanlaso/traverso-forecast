"""
seasonality.py — Regressores de estacionalidad por categoria comercial
Traverso S.A. · Piloto de Forecast

COMO FUNCIONA:
  Prophet modela: demanda = tendencia + estacionalidad + regressores + error

  Cada regressor es una columna binaria (0/1) en el DataFrame de entrenamiento.
  Prophet aprende durante el entrenamiento cuanto sube o baja la demanda cuando
  esa columna vale 1. Ese coeficiente se aplica automaticamente al forecastear
  periodos futuros donde el evento volvera a ocurrir.

AGREGAR NUEVOS REGRESSORES:
  1. Define las fechas en get_category_regressors() para la categoria
  2. Usa _temporada() o _semanas_previas_fecha() para calcular semanas
  3. El pipeline los aplica automaticamente segun Categ. Comercial del SKU

CATEGORIAS Y VALORES EXACTOS EN dbo.ventas (Segmento=COMERCIAL):
  SALSAS            375.007 registros  — peak Fiestas Patrias + temporada calor
  VINAGRES          232.702 registros  — peak verano (ensaladas/pescados)
  JUGO DE LIMON     130.316 registros  — peak verano + Semana Santa
  JUGOS CONCENTRADOS 121.551 registros — peak verano
  ENCURTIDOS         95.178 registros  — peak Fiestas Patrias
  SOPAS              92.455 registros  — peak temporada fria
  SOYA               54.895 registros  — sin estacionalidad definida aun
  MAYONESA           30.334 registros  — peak verano + Fiestas Patrias
  ESENCIAS           27.192 registros  — sin estacionalidad definida aun
  KIKKOMAN           16.306 registros  — sin estacionalidad definida aun
  MELITTA             5.316 registros  — sin estacionalidad definida aun
  ACEITES             2.370 registros  — sin estacionalidad definida aun
"""

from datetime import date, timedelta

_YEARS = list(range(2021, 2029))


# ── Utilidades ────────────────────────────────────────────────────────────────

def _semanas_del_rango(inicio: date, fin: date) -> list[str]:
    semanas = []
    d = inicio - timedelta(days=inicio.weekday())
    while d <= fin:
        semanas.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return semanas


def _semana_santa(year: int) -> list[str]:
    """3 semanas previas a Viernes Santo. Algoritmo de Gauss."""
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
    viernes = pascua - timedelta(days=2)
    lunes   = viernes - timedelta(days=viernes.weekday())
    return [(lunes - timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(3)]


def _semanas_previas_fecha(year: int, mes: int, dia: int, n: int = 4) -> list[str]:
    """N semanas previas (inclusive) a una fecha."""
    fecha = date(year, mes, dia)
    lunes = fecha - timedelta(days=fecha.weekday())
    return [(lunes - timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(n)]


def _temporada(meses: list[int]) -> list[str]:
    """
    Semanas en los meses indicados para todos los anos en _YEARS.
    Meses > 12 indican el ano siguiente (ej: 13=enero, 14=febrero del año sig.)
    """
    semanas = []
    for y in _YEARS:
        for m in meses:
            mes_real  = m if m <= 12 else m - 12
            year_real = y if m <= 12 else y + 1
            try:
                inicio = date(year_real, mes_real, 1)
                fin    = date(year_real, mes_real + 1, 1) - timedelta(days=1) \
                         if mes_real < 12 else date(year_real + 1, 1, 1) - timedelta(days=1)
                semanas += _semanas_del_rango(inicio, fin)
            except ValueError:
                pass
    return sorted(set(semanas))


def _verano() -> list[str]:
    """Temporada verano Chile: diciembre - marzo."""
    return _temporada([12, 13, 14, 15])


def _fiestas_patrias(n_semanas: int = 4) -> list[str]:
    """N semanas previas al 18 de septiembre."""
    return sorted(set(
        s for y in _YEARS for s in _semanas_previas_fecha(y, 9, 18, n=n_semanas)
    ))


def _semana_santa_all() -> list[str]:
    """3 semanas previas a Semana Santa para todos los anos."""
    return sorted(set(s for y in _YEARS for s in _semana_santa(y)))


# ── Regressores por categoria ─────────────────────────────────────────────────

def get_category_regressors(categoria: str) -> list[dict]:
    """
    Retorna la lista de regressores para una categoria comercial.

    Cada regressor:
        name:   nombre de columna en el DataFrame Prophet (sin espacios)
        label:  descripcion legible para el dashboard
        dates:  lista de fechas ISO (lunes de cada semana afectada)
        value:  1.0 — Prophet aprende el coeficiente real del historial

    COMO AGREGAR UNA NUEVA CATEGORIA:
        1. Agrega un bloque 'if cat in ("NOMBRE_EN_BD"):' al final
        2. Define los regressores con _temporada(), _fiestas_patrias(), etc.
        3. Haz commit y rebuild — se aplica automaticamente al reentrenar
    """
    cat = (categoria or "").strip().upper()

    # ── JUGO DE LIMON ─────────────────────────────────────────────────────────
    if cat in ("JUGO DE LIMON", "LIMON", "LIMON ", "LIMÓN", "JUGO LIMON"):
        return [
            {
                "name":  "verano_limon",
                "label": "Temporada verano dic-mar (ensaladas, pescados, mariscos)",
                "dates": _verano(),
                "value": 1.0,
            },
            {
                "name":  "semana_santa",
                "label": "3 semanas previas a Semana Santa (peak limon)",
                "dates": _semana_santa_all(),
                "value": 1.0,
            },
        ]

    # ── VINAGRES ──────────────────────────────────────────────────────────────
    if cat in ("VINAGRES", "VINAGRE"):
        return [
            {
                "name":  "verano_vinagre",
                "label": "Temporada verano dic-mar (ensaladas, pescados, mariscos)",
                "dates": _verano(),
                "value": 1.0,
            },
            {
                "name":  "semana_santa",
                "label": "3 semanas previas a Semana Santa",
                "dates": _semana_santa_all(),
                "value": 1.0,
            },
        ]

    # ── SALSAS ────────────────────────────────────────────────────────────────
    if cat in ("SALSAS", "SALSA"):
        return [
            {
                "name":  "fiestas_patrias",
                "label": "4 semanas previas a Fiestas Patrias (asados)",
                "dates": _fiestas_patrias(4),
                "value": 1.0,
            },
            {
                "name":  "temporada_calor",
                "label": "Temporada calor oct-mar (asados y parrilla)",
                "dates": _temporada([10, 11, 12, 13, 14, 15]),
                "value": 1.0,
            },
        ]

    # ── SOPAS ─────────────────────────────────────────────────────────────────
    if cat in ("SOPAS", "SOPA"):
        return [
            {
                "name":  "temporada_fria",
                "label": "Temporada fria may-ago (mayor consumo sopas)",
                "dates": _temporada([5, 6, 7, 8]),
                "value": 1.0,
            },
        ]

    # ── JUGOS CONCENTRADOS ────────────────────────────────────────────────────
    if cat in ("JUGOS CONCENTRADOS", "JUGO CONCENTRADO"):
        return [
            {
                "name":  "verano_jugos",
                "label": "Temporada verano dic-mar (mayor consumo jugos)",
                "dates": _verano(),
                "value": 1.0,
            },
        ]

    # ── ENCURTIDOS ────────────────────────────────────────────────────────────
    if cat in ("ENCURTIDOS", "ENCURTIDO"):
        return [
            {
                "name":  "fiestas_patrias",
                "label": "4 semanas previas a Fiestas Patrias (acompanamiento asados)",
                "dates": _fiestas_patrias(4),
                "value": 1.0,
            },
            {
                "name":  "temporada_calor",
                "label": "Temporada calor oct-mar (mayor consumo con asados)",
                "dates": _temporada([10, 11, 12, 13, 14, 15]),
                "value": 1.0,
            },
        ]

    # ── MAYONESA ──────────────────────────────────────────────────────────────
    if cat in ("MAYONESA", "MAYONESAS"):
        return [
            {
                "name":  "verano_mayonesa",
                "label": "Temporada verano dic-mar (ensaladas y asados)",
                "dates": _verano(),
                "value": 1.0,
            },
            {
                "name":  "fiestas_patrias",
                "label": "4 semanas previas a Fiestas Patrias",
                "dates": _fiestas_patrias(4),
                "value": 1.0,
            },
        ]

    # ── Sin regressores especificos para esta categoria ───────────────────────
    # Categorias sin estacionalidad definida aun:
    # SOYA, ESENCIAS, KIKKOMAN, MELITTA, ACEITES, CUIDADO DEL HOGAR,
    # CUIDADO PERSONAL, GRANELES, ABARROTES, OTROS
    return []


def get_all_regressors_summary() -> dict:
    """Resumen de todos los regressores definidos. Usado por /regressors API."""
    categorias = [
        "JUGO DE LIMON", "VINAGRES", "SALSAS", "SOPAS",
        "JUGOS CONCENTRADOS", "ENCURTIDOS", "MAYONESA",
    ]
    summary = {}
    for cat in categorias:
        regs = get_category_regressors(cat)
        summary[cat] = [
            {
                "name":      r["name"],
                "label":     r["label"],
                "n_semanas": len(r["dates"]),
                "primera":   r["dates"][0]  if r["dates"] else None,
                "ultima":    r["dates"][-1] if r["dates"] else None,
            }
            for r in regs
        ]
    return summary
