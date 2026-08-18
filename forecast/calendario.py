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
    """Lunes de la semana ISO (lun-dom) que contiene `fecha`.

    (18-08-2026) NO USAR PARA INDEXAR EL FORECAST. El comentario anterior decia
    que Prophet entrega ds = lunes: es FALSO, entrega DOMINGOS (semanas dom->sab;
    ver mrp.py::_fecha_a_domingo y el docstring de eventos.py). Sobre un domingo
    esta funcion devuelve el lunes de la semana ANTERIOR (weekday(dom)=6), asi que
    usarla sobre un ds corre la demanda una semana y la reparte entre los habiles
    de otra semana (bug del re-keyeo en optimizer.py, corregido el 18-08).
    Para alinear con el forecast usar `semana_viz_inicio` (domingo).
    Esta funcion sigue siendo correcta para agrupar DIAS del horizonte en semanas
    ISO (campanas de granel/formato, pins del planificador).
    """
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

        # FIX semana parcial (10-07-2026): el tasa-diaria se calcula sobre los días
        # hábiles de la SEMANA ISO COMPLETA, no solo sobre los que caen en el
        # horizonte. Si el horizonte arranca a mitad de semana (p.ej. hoy viernes),
        # los días hábiles ya transcurridos (lun-jue) quedan fuera del rango y su
        # demanda se DESCARTA — no se re-concentra en el día 0.
        #   Antes: horizonte arranca viernes -> habiles={vie} -> por_dia = sem/1
        #          => TODO el semanal caía en el viernes (día 0), pico ~5x que
        #          generaba tensión estructural y disparaba el gap del solver.
        #   Ahora: por_dia = sem / (hábiles de lun-vie) -> el viernes recibe su 1/5.
        # Decisión de negocio (Germán, 10-07): la demanda esperada de días ya
        # transcurridos caducó (no se produce hoy para un martes que ya fue); lo
        # que efectivamente se comprometió entra por las OV (demanda comprometida).
        habiles_semana = [d for d in dias_semana if es_habil(d)]

        if habiles_semana:
            # Tasa diaria = semanal / hábiles de la semana ISO completa.
            por_dia = yhat_sem / len(habiles_semana)
            # Asignar SOLO a los hábiles que caen dentro del horizonte
            # (los transcurridos se descartan; los futuros reciben su porción).
            for d in habiles_semana:
                if fecha_inicio <= d <= fecha_fin:
                    demanda_diaria[d] += por_dia
        else:
            # Caso raro: la semana ISO no tiene NINGÚN día hábil (semana entera de
            # feriados). Distribuir uniforme entre los días disponibles del
            # horizonte para no perder la demanda total.
            por_dia = yhat_sem / len(dias_en_horizonte)
            for d in dias_en_horizonte:
                demanda_diaria[d] += por_dia

    return demanda_diaria


# =============================================================================
# Stock de seguridad diario — fórmula de cobertura (fuente única)
# =============================================================================

def calcular_ss_diario(
    forecast_diario_u: dict[date, float],
    dia: date,
    ss_dias: int,
) -> float:
    """
    Stock de seguridad del día `dia`, en unidades.

    Definición (Germán, 11-07-2026): el SS de un día es la SUMA del forecast
    diario de los próximos `ss_dias` días HÁBILES, siendo `dia` el primero de
    la ventana (inclusive). Representa la demanda que el stock debe aguantar
    durante la ventana de cobertura.

    Reemplaza la fórmula anterior `forecast_diario_del_dia × ss_dias`, que:
      - colapsaba a 0 en días no hábiles (sáb/dom/feriado: forecast_dia=0),
      - sobre-dimensionaba en días de forecast alto (multiplicaba un puntual
        por 15 en vez de sumar 15 días reales).

    Args:
        forecast_diario_u: dict {fecha: forecast_unidades} ya distribuido sobre
                           días hábiles (salida de distribuir_forecast_a_diario).
                           Idealmente cubre hasta ~ss_dias hábiles más allá del
                           horizonte del plan; los días sin entrada aportan 0.
        dia:      día para el cual se calcula el SS.
        ss_dias:  cantidad de días hábiles de cobertura (0 => SS=0, p.ej. MTO).

    Returns:
        SS en unidades (float). 0.0 si ss_dias <= 0.

    Nota sobre el borde del horizonte: si la ventana de `ss_dias` hábiles se
    extiende más allá del rango con forecast disponible, los días faltantes
    aportan 0 y el SS queda subestimado para los últimos días del horizonte.
    Es un efecto conocido y acotado (días finales, menos accionables); para
    evitarlo, el caller debe proveer forecast_diario_u extendido.
    """
    if ss_dias <= 0:
        return 0.0

    total = 0.0
    habiles_contados = 0
    d = dia
    # Límite de seguridad: 15 hábiles ≈ 21 días naturales; cortamos holgado
    # para no iterar infinito si el forecast se agota antes de juntar ss_dias.
    limite_natural = ss_dias * 3 + 15

    while habiles_contados < ss_dias:
        if es_habil(d):
            total += forecast_diario_u.get(d, 0.0)
            habiles_contados += 1
        d += timedelta(days=1)
        if (d - dia).days > limite_natural:
            break

    return total


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

    # Test 7: SS diario (suma de próximos ss_dias hábiles desde d inclusive)
    from calendario import calcular_ss_diario
    # Forecast diario: 100 u cada día hábil de una ventana larga, 0 en findes.
    # Construimos 6 semanas desde lunes 4-may (con feriados reales de mayo).
    fc_dia = {}
    d0 = date(2026, 5, 4)
    for i in range(60):
        dd = d0 + timedelta(days=i)
        fc_dia[dd] = 100.0 if es_habil(dd) else 0.0

    # SS de 5 días hábiles desde lunes 4-may: 4,5,6,7,8 mayo (todos hábiles) = 500
    ss5 = calcular_ss_diario(fc_dia, date(2026, 5, 4), 5)
    assert ss5 == 500.0, f"SS 5 hábiles desde lun 4-may: esperaba 500, obtuve {ss5}"

    # SS calculado en SÁBADO (9-may): la ventana arranca en sábado (no hábil,
    # no cuenta) y toma los próximos 5 hábiles: lun11,mar12,mié13,jue14,vie15 = 500.
    # Clave: NO colapsa a 0 aunque el día base sea no hábil.
    ss_sab = calcular_ss_diario(fc_dia, date(2026, 5, 9), 5)
    assert ss_sab == 500.0, f"SS en sábado: esperaba 500 (no 0), obtuve {ss_sab}"

    # SS que cruza el feriado 21-may (Glorias Navales): la ventana salta el feriado
    # y toma 5 hábiles reales. Desde lun 18-may: 18,19,20,(21 feriado salta),22,25 = 500
    ss_fer = calcular_ss_diario(fc_dia, date(2026, 5, 18), 5)
    assert ss_fer == 500.0, f"SS cruzando feriado: esperaba 500, obtuve {ss_fer}"

    # SS con ss_dias=0 (MTO) => 0
    assert calcular_ss_diario(fc_dia, date(2026, 5, 4), 0) == 0.0, "ss_dias=0 => 0"

    # Borde: forecast se agota -> ventana corta -> subestima (no rompe)
    fc_corto = {date(2026, 5, 4): 100.0, date(2026, 5, 5): 100.0}
    ss_corto = calcular_ss_diario(fc_corto, date(2026, 5, 4), 15)
    assert ss_corto == 200.0, f"forecast corto: esperaba 200 (2 días con dato), obtuve {ss_corto}"
    print(f"✓ SS diario: lun={ss5}, sábado={ss_sab} (no colapsa), feriado={ss_fer}, corto={ss_corto}")

    print()
    print("=" * 60)
    print("Todos los tests pasaron ✓")
    print("=" * 60)
