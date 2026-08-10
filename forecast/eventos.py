"""
eventos.py — Eventos comerciales para el forecast · Traverso S.A.

QUÉ HACE
--------
Lee `mrp_eventos` y devuelve, por SKU, los regresores listos para pasarle a
`forecaster.train_model(extra_events=...)`.

CONTRATO DE SALIDA
------------------
    {sku: [{"name": "ev_<nombre>_<etiqueta>", "dates": ["YYYY-MM-DD", ...]}, ...]}

`dates` son DOMINGOS en ISO. Es obligatorio: `_apply_regressors` (forecaster.py)
matchea por IGUALDAD EXACTA contra `ds`, que el pipeline genera en domingo. Una
fecha que no sea domingo exacto produce una columna de CEROS y Prophet la ignora
EN SILENCIO — sin error ni warning. Ese bug tuvo inertes todos los regresores de
categoría durante meses (ver tuning/exp_realineacion_regresores.py).

Por eso el snapping usa `calendario.semana_viz_inicio`, que es idempotente sobre
domingos, y NO las helpers de seasonality.py: `_semanas_del_rango` usa
`weekday() + 1` sin módulo, así que una fecha que YA es domingo retrocede una
semana entera.

UNA FILA = UN PERÍODO
---------------------
El usuario declara períodos en fechas naturales; nunca semanas ni domingos.
Filas con igual (nombre, sku, etiqueta) se UNEN en un solo regresor; etiquetas
distintas generan regresores SEPARADOS, cada uno con su coeficiente.

Por qué importa separar (medido el 10-08-2026 en 250010495, holdout
out-of-sample contra ventas reales de oct-nov 2025, real 639 cj/sem):

    sin evento                          3.210 cj/sem   +402%
    un solo regresor, todo el evento    1.186 cj/sem    +86%
    dos fases ('suave' / 'fuerte')        748 cj/sem    +17%
    tres fases                          1.549 cj/sem   +142%

El evento de 2024 no fue homogéneo: ago-sep estuvo 3,4x sobre el nivel
pre-evento y oct-dic 7,4x. Un regresor binario aprende UN coeficiente y lo
aplica uniforme, así que se pasa corrigiendo la fase suave y se queda corto en
la fuerte. Dos fases lo resuelven; tres sobreajusta.

EVENTOS FUTUROS: NO SE IMPLEMENTAN ACÁ
--------------------------------------
Un evento futuro NO puede ser un regresor. Su columna es idénticamente cero en
todo el entrenamiento, así que el coeficiente no es identificable y el prior de
Prophet lo encoge a ~0: el evento no tendría ningún efecto. Necesita un ajuste
POST-HOC sobre la serie de forecast (reparto proporcional al `yhat` del período,
reescalado para que el total sea exactamente la magnitud declarada). Es Fase 2.
Acá se filtran con un aviso.
"""
import logging
import re
from datetime import date, datetime

from calendario import semana_viz_inicio
from db_mrp import get_eventos

logger = logging.getLogger(__name__)

# Un regresor con muy pocas semanas activas aprende ruido en vez de señal: la
# fase de 4 semanas de `tres_fases` dio coef -0,14 y degradó el holdout a +142%.
# Es AVISO, no bloqueo — la evidencia es de un solo caso.
MIN_SEMANAS_AVISO = 5


def _slug(s: str) -> str:
    """Nombre de columna válido para Prophet: minúsculas, sin espacios ni tildes."""
    s = (s or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("ü", "u")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "sin_nombre"


def _a_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def expandir_a_domingos(fecha_desde, fecha_hasta) -> list[str]:
    """Domingos ISO del período, con los dos extremos snapeados a SU domingo.

    El usuario puede escribir cualquier fecha: si declara martes 2024-08-20 a
    jueves 2024-09-26, el período cubre las semanas que contienen esas fechas,
    o sea los domingos 2024-08-18 .. 2024-09-22.
    """
    d = semana_viz_inicio(_a_date(fecha_desde))
    fin = semana_viz_inicio(_a_date(fecha_hasta))
    out = []
    while d <= fin:
        out.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 7)
    return out


def cargar_eventos_activos(sku: str | None = None) -> dict[str, list[dict]]:
    """Regresores de evento por SKU, listos para `train_model(extra_events=...)`.

    Solo eventos activos de tipo 'pasado'. Los 'futuro' se avisan y se omiten.
    """
    filas = get_eventos(sku=sku, solo_activos=True)
    if not filas:
        return {}

    # (sku, nombre, etiqueta) -> set de domingos
    grupos: dict[tuple, set] = {}
    n_futuros = 0
    for f in filas:
        if str(f.get("tipo") or "pasado") == "futuro":
            n_futuros += 1
            continue
        clave = (str(f["sku"]), str(f["nombre"]), str(f.get("etiqueta") or "base"))
        grupos.setdefault(clave, set()).update(
            expandir_a_domingos(f["fecha_desde"], f["fecha_hasta"]))

    if n_futuros:
        logger.warning(
            "[eventos] %d evento(s) de tipo 'futuro' OMITIDOS: requieren ajuste "
            "post-hoc del forecast (Fase 2), no un regresor", n_futuros)

    out: dict[str, list[dict]] = {}
    for (sku_k, nombre, etiqueta), fechas in sorted(grupos.items()):
        if not fechas:
            continue
        name = f"ev_{_slug(nombre)}_{_slug(etiqueta)}"
        dates = sorted(fechas)
        if len(dates) < MIN_SEMANAS_AVISO:
            logger.warning(
                "[eventos] %s: regresor '%s' tiene solo %d semanas — puede "
                "aprender ruido en vez del evento", sku_k, name, len(dates))
        out.setdefault(sku_k, []).append({"name": name, "dates": dates})

    for sku_k, regs in sorted(out.items()):
        detalle = ", ".join(f"{r['name']}({len(r['dates'])} sem)" for r in regs)
        logger.info("[eventos] %s: %d regresor(es) -> %s", sku_k, len(regs), detalle)

    return out
