"""
dias_informe.py — Regla de días hábiles para el ENVÍO del informe de faltantes.

(27-07-2026) El informe se envía sólo en días hábiles y cubre todo lo ocurrido
desde el último día hábil anterior:

    en un día hábil T  ->  rango [último día hábil < T]  ..  [T - 1]

    Martes 28-07      -> lunes 27      .. lunes 27          (1 día)
    Lunes  27-07      -> viernes 24    .. domingo 26        (3 días)
    Lunes  21-09      -> jueves 17     .. domingo 20        (4 días)
                         (18 viernes y 19 sábado son feriados patrios)

    Sábado / domingo / feriado -> NO se envía nada.

Importante: esto afecta SÓLO al correo. El CÁLCULO sigue corriendo todos los días
(cron_faltantes.py persiste la ventana de 14 días sin excepción), de modo que el
dashboard queda al día y los faltantes se guardan POR FECHA — nunca consolidados —
para que el gráfico siga mostrando los días separados.

La condición de "hábil" (fines de semana + feriados chilenos) sale de
calendario.py::es_habil, que es la fuente única de verdad del proyecto.
"""

from __future__ import annotations

from datetime import date, timedelta

from calendario import es_habil

# Tope de seguridad al retroceder buscando el día hábil anterior. El feriado más
# largo posible en Chile no llega a 5 días corridos; 15 es holgado y evita un
# bucle infinito si es_habil devolviera False para todo.
_MAX_RETROCESO = 15


def dia_habil_anterior(d: date) -> date | None:
    """Último día hábil ESTRICTAMENTE anterior a `d`. None si no lo encuentra."""
    x = d - timedelta(days=1)
    for _ in range(_MAX_RETROCESO):
        if es_habil(x):
            return x
        x -= timedelta(days=1)
    return None


def rango_informe(hoy: date | None = None) -> tuple[date, date] | None:
    """Rango [desde, hasta] que debe cubrir el informe enviado HOY.

    Devuelve None si hoy NO es día hábil (no corresponde enviar correo).

    `hasta` es siempre ayer; `desde` es el último día hábil anterior a hoy. En un
    día hábil normal ambos coinciden y el informe cubre un solo día, igual que antes.
    """
    hoy = hoy or date.today()
    if not es_habil(hoy):
        return None
    ayer = hoy - timedelta(days=1)
    desde = dia_habil_anterior(hoy)
    if desde is None:
        return (ayer, ayer)
    # desde nunca puede pasarse de ayer (ocurriría sólo si hoy y ayer fueran hábiles
    # consecutivos, en cuyo caso desde == ayer y el rango es de un día).
    if desde > ayer:
        desde = ayer
    return (desde, ayer)


def fechas_del_rango(desde: date, hasta: date) -> list[date]:
    """Todas las fechas del rango, inclusive. Se usa para pedir los faltantes día a
    día y para congelar explicaciones de cada fecha reportada."""
    out, d = [], desde
    while d <= hasta:
        out.append(d)
        d += timedelta(days=1)
    return out


def etiqueta_rango(desde: date, hasta: date) -> str:
    """Texto para asunto de correo y rótulo del Excel.

    OJO: faltantes_excel._fecha_txt invierte cualquier string de 3 partes separadas
    por guión ('a-b-c' -> 'c-b-a'). Por eso el rango se devuelve con 6 partes
    ('24-07-2026 al 26-07-2026'), que esa función deja intacto, y el día único se
    deja en ISO para conservar exactamente el formato actual del informe.
    """
    if desde == hasta:
        return desde.isoformat()                      # 'YYYY-MM-DD' -> lo invierte a dd-mm-yyyy
    return f"{desde.strftime('%d-%m-%Y')} al {hasta.strftime('%d-%m-%Y')}"
