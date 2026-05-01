"""
calendario.py — Módulo de calendario para optimización diaria.

Centraliza:
  - Feriados Chile (2026 hardcodeado, extensible a años posteriores)
  - Helpers de días hábiles
  - Distribución de forecast semanal → demanda diaria
  - Generación del horizonte de planificación

Convenciones:
  - Día hábil  = lunes a viernes Y NO feriado nacional
  - Semana ISO = lunes a domingo (alineado con Prophet `ds`)
  - Semana viz = domingo a sábado (alineado con DetalleProduccion.jsx)
"""

from datetime import date, timedelta
from typing import Iterable


# =============================================================================
# Feriados Chile — fuente de verdad única
# =============================================================================
# Movido desde DetalleProduccion.jsx. Cuando se agregue un año nuevo, agregar
# acá y exportar al frontend vía endpoint /calendario/feriados.

FERIADOS_CHILE: dict[int, frozenset[date]] = {
    2026: frozenset({
        date(2026, 1, 1),    # Año Nuevo
        date(2026, 3, 29),   # Domingo de Resurrección
        date(2026, 3, 30),   # Lunes de Resurrección (movible)
        date(2026, 4, 6),    # Día Nacional Pueblos Indígenas
        date(2026, 5, 1),    # Día del Trabajador
        date(2026, 5, 21),   # Día de las Glorias Navales
        date(2026, 6, 29),   # San Pedro y San Pablo
        date(2026, 7, 16),   # Virgen del Carmen
        date(2026, 8, 15),   # Asunción de la Virgen
        date(2026, 9, 18),   # Independencia Nacional
        date(2026, 9, 19),   # Glorias del Ejército
        date(2026, 10, 12),  # Encuentro de Dos Mundos
        date(2026, 10, 31),  # Día de las Iglesias Evangélicas
        date(2026, 11, 1),   # Todos los Santos
        date(2026, 11, 2),   # Día de los Difuntos (irregular)
        date(2026, 12, 8),   # Inmaculada Concepción
        date(2026, 12, 25),  # Navidad
    }),
}


def es_feriado(fecha: date) -> bool:
    """True si la fecha es feriado nacional. Devuelve False si el año
    no está catalogado (con warning implícito: el caller debería verificar)."""
    feriados_anio = FERIADOS_CHILE.get(fecha.year)
    if feriados_anio is None:
        return False
    return fecha in feriados_anio


def es_finde(fecha: date) -> bool:
    """True si la fecha es sábado o domingo."""
    # weekday(): lunes=0, ..., sábado=5, domingo=6
    return fecha.weekday() >= 5


def es_habil(fecha: date) -> bool:
    """True si la fecha es día hábil (lun-vie y no feriado)."""
    return not es_finde(fecha) and not es_feriado(fecha)


# =============================================================================
# Generación de horizontes
# =============================================================================

def generar_horizonte_diario(
    fecha_inicio: date,
    n_dias: int
) -> list[date]:
    """Lista de fechas consecutivas desde fecha_inicio (incluida)."""
    return [fecha_inicio + timedelta(days=i) for i in range(n_dias)]


def dias_habiles_entre(fecha_inicio: date, fecha_fin: date) -> list[date]:
    """Lista de días hábiles en [fecha_inicio, fecha_fin] (ambos incluidos)."""
    if fecha_fin < fecha_inicio:
        return []
    dias = []
    d = fecha_inicio
    while d <= fecha_fin:
        if es_habil(d):
            dias.append(d)
        d += timedelta(days=1)
    return dias


def contar_dias_habiles(fecha_inicio: date, fecha_fin: date) -> int:
    """Cantidad de días hábiles en [fecha_inicio, fecha_fin]."""
    return len(dias_habiles_entre(fecha_inicio, fecha_fin))


# =============================================================================
# Semanas — convenciones distintas según consumidor
# =============================================================================

def semana_iso_inicio(fecha: date) -> date:
    """Lunes de la semana ISO que contiene `fecha`. Usado para alinear
    con forecast de Prophet (que entrega ds = lunes de cada semana)."""
    return fecha - timedelta(days=fecha.weekday())


def semana_iso_fin(fecha: date) -> date:
    """Domingo de la semana ISO que contiene `fecha`."""
    return semana_iso_inicio(fecha) + timedelta(days=6)


def semana_viz_inicio(fecha: date) -> date:
    """Domingo de la semana de visualización (DetalleProduccion.jsx).
    Esta convención es domingo-sábado."""
    # weekday(): domingo=6 → restamos (weekday+1) % 7 días para llegar al domingo
    dias_desde_domingo = (fecha.weekday() + 1) % 7
    return fecha - timedelta(days=dias_desde_domingo)


def semana_viz_fin(fecha: date) -> date:
    """Sábado de la semana de visualización."""
    return semana_viz_inicio(fecha) + timedelta(days=6)


def dias_de_semana_iso(lunes: date) -> list[date]:
    """Los 7 días de la semana ISO que arranca en `lunes`."""
    return [lunes + timedelta(days=i) for i in range(7)]


# =============================================================================
# Distribución forecast semanal → demanda diaria
# =============================================================================

def distribuir_forecast_a_diario(
    forecast_semanal: dict[date, float],
    fecha_inicio: date,
    fecha_fin: date,
) -> dict[date, float]:
    """
    Convierte un forecast semanal (clave = lunes ISO de cada semana) en un
    diccionario de demanda diaria.

    Regla:
      - Días hábiles de la semana → demanda = forecast_semana / nº_dias_habiles
      - Días no hábiles (finde/feriado) → demanda = 0
      - Si una semana no tiene días hábiles (raro), distribuye uniforme
        entre los 7 días para no perder la demanda total

    Args:
        forecast_semanal: dict {lunes: yhat_semanal_unidades}
        fecha_inicio:    primer día del horizonte (incluido)
        fecha_fin:       último día del horizonte (incluido)

    Returns:
        dict {fecha: demanda_unidades_dia} con todas las fechas del rango,
        incluso aquellas donde la demanda es 0.
    """
    demanda_diaria: dict[date, float] = {}

    # Inicializar todas las fechas del rango en 0
    d = fecha_inicio
    while d <= fecha_fin:
        demanda_diaria[d] = 0.0
        d += timedelta(days=1)

    # Para cada semana del forecast, distribuir entre sus días hábiles
    for lunes, yhat_sem in forecast_semanal.items():
        if yhat_sem <= 0:
            continue

        dias_semana = dias_de_semana_iso(lunes)
        # Filtrar a los días que están dentro del horizonte solicitado
        dias_en_horizonte = [d for d in dias_semana if fecha_inicio <= d <= fecha_fin]
        if not dias_en_horizonte:
            continue

        habiles = [d for d in dias_en_horizonte if es_habil(d)]

        if habiles:
            # Caso normal: repartir entre días hábiles dentro del horizonte
            por_dia = yhat_sem / len(habiles)
            for d in habiles:
                demanda_diaria[d] += por_dia
        else:
            # Caso raro: ningún día hábil de esa semana cae dentro del horizonte
            # (por ej. semana entera de feriados, o semana parcialmente fuera del rango)
            # → distribuir uniforme entre los días disponibles para no perder demanda
            por_dia = yhat_sem / len(dias_en_horizonte)
            for d in dias_en_horizonte:
                demanda_diaria[d] += por_dia

    return demanda_diaria


# =============================================================================
# Capacidad por línea-día — interfaz para el optimizer
# =============================================================================

def capacidad_dia_unidades(
    fecha: date,
    velocidad_u_hr: float,
    horas_turno: float,
    turnos_dia: int,
) -> int:
    """
    Capacidad en unidades de una línea para un día específico.

    Devuelve 0 si el día no es hábil (feriado o finde).
    Esta función es la interfaz primaria del optimizer para conocer
    cap_dia[d, l] — modela la regla "no se produce los días no hábiles"
    sin necesidad de restricciones adicionales.
    """
    if not es_habil(fecha):
        return 0
    return int(velocidad_u_hr * horas_turno * turnos_dia)


# =============================================================================
# Smoke test — ejecutable directamente con `python calendario.py`
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smoke test: calendario.py")
    print("=" * 60)

    # Test 1: feriados conocidos
    assert es_feriado(date(2026, 5, 1)), "1 mayo debería ser feriado"
    assert es_feriado(date(2026, 9, 18)), "18 sep debería ser feriado"
    assert not es_feriado(date(2026, 5, 2)), "2 mayo no es feriado"
    print("✓ Feriados detectados correctamente")

    # Test 2: días hábiles
    assert es_habil(date(2026, 4, 30)), "jueves 30 abr es hábil"
    assert not es_habil(date(2026, 5, 1)), "viernes 1 mayo NO es hábil (feriado)"
    assert not es_habil(date(2026, 5, 2)), "sábado NO es hábil"
    assert not es_habil(date(2026, 5, 3)), "domingo NO es hábil"
    assert es_habil(date(2026, 5, 4)), "lunes 4 mayo es hábil"
    print("✓ Días hábiles detectados correctamente")

    # Test 3: contar días hábiles
    n = contar_dias_habiles(date(2026, 4, 30), date(2026, 5, 8))
    # 30/4 jue ✓, 1/5 vie feriado ✗, 2-3 finde ✗, 4-5-6-7-8 lun-vie ✓
    # = 1 + 5 = 6
    assert n == 6, f"Esperaba 6, obtuve {n}"
    print(f"✓ Días hábiles 30/4-8/5: {n} (correcto)")

    # Test 4: semanas
    fecha = date(2026, 5, 6)  # miércoles
    assert semana_iso_inicio(fecha) == date(2026, 5, 4), "lunes ISO"
    assert semana_iso_fin(fecha) == date(2026, 5, 10), "domingo ISO"
    assert semana_viz_inicio(fecha) == date(2026, 5, 3), "domingo viz"
    assert semana_viz_fin(fecha) == date(2026, 5, 9), "sábado viz"
    print("✓ Semanas ISO y viz calculadas correctamente")

    # Test 5: distribución forecast
    # Semana 4-10 mayo: feriado el 1 (fuera) → 5 días hábiles (lun-vie)
    forecast = {date(2026, 5, 4): 1000.0}
    demanda = distribuir_forecast_a_diario(
        forecast,
        fecha_inicio=date(2026, 5, 4),
        fecha_fin=date(2026, 5, 10),
    )
    # 5 días hábiles → 200/día
    assert demanda[date(2026, 5, 4)] == 200.0, "lunes 200"
    assert demanda[date(2026, 5, 5)] == 200.0
    assert demanda[date(2026, 5, 8)] == 200.0, "viernes 200"
    assert demanda[date(2026, 5, 9)] == 0.0, "sábado 0"
    assert demanda[date(2026, 5, 10)] == 0.0, "domingo 0"
    total = sum(demanda.values())
    assert abs(total - 1000.0) < 0.01, f"Total preservado: {total}"
    print(f"✓ Forecast distribuido: total preservado = {total}")

    # Test 6: capacidad línea-día
    # Línea L001: 12000 u/hr × 8 hrs × 1 turno = 96000 u/día
    cap_lab = capacidad_dia_unidades(date(2026, 4, 30), 12000, 8, 1)
    cap_fer = capacidad_dia_unidades(date(2026, 5, 1), 12000, 8, 1)
    cap_dom = capacidad_dia_unidades(date(2026, 5, 3), 12000, 8, 1)
    assert cap_lab == 96000, f"Esperaba 96000, obtuve {cap_lab}"
    assert cap_fer == 0, f"Feriado debe ser 0, obtuve {cap_fer}"
    assert cap_dom == 0, f"Domingo debe ser 0, obtuve {cap_dom}"
    print(f"✓ Capacidad: hábil={cap_lab}, feriado={cap_fer}, domingo={cap_dom}")

    print()
    print("=" * 60)
    print("Todos los tests pasaron ✓")
    print("=" * 60)
