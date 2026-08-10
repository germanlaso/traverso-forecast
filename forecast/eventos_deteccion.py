"""
eventos_deteccion.py — Detección automática de fases y preview del efecto.
SOLO LECTURA: no entrena para persistir, no escribe en la BD.

PARA QUÉ
--------
El operador NO puede saber en qué semana el evento cambió de intensidad. Eso
salió de un quiebre estructural en la serie, validado con un holdout
out-of-sample. Pedírselo en un formulario garantiza datos malos.

Entonces el operador declara UN período en fechas naturales y el sistema:
  1. `detectar_fases()`  -> propone 1 o 2 fases y devuelve la serie para graficar
  2. `preview_evento()`  -> dice, en cajas, qué habría pasado el año pasado

MÉTODO DEL DETECTOR
-------------------
Para cada semana del período se calcula ratio = venta_real / base, donde base es
la MISMA semana ISO promediada sobre los otros años disponibles. Después se
busca el punto de corte que mejor separa dos niveles.

Dos decisiones que salieron de los datos, no del gusto:

· MEDIANA, no media. La serie es grumosa porque los pedidos llegan a saltos
  (en 250010495 la semana 36 fue 1.891 cj y la 37 fue 124). Con media, un pico
  aislado de 17,9x arrastra el corte a un lugar absurdo; con mediana, no.

· UMBRAL de separación 1,6. Debajo de eso se reporta UNA fase. Verificado: si el
  operador declara solo el Q4 de 2024 (que es enteramente la fase fuerte), la
  separación cae a 1,34 y el detector correctamente NO parte.

Robustez medida sobre 250010495: cinco formas distintas de declarar el mismo
período ("mediados de agosto a fin de diciembre", "septiembre a diciembre",
"agosto a enero", "sep a nov", y el período exacto) devuelven EL MISMO corte.
Es lo que hace viable que el operador sea impreciso.

EL DETECTOR PROPONE, NO DECIDE
------------------------------
El perfil de separación es PLANO alrededor del óptimo (en 250010495 los cortes
vecinos dan 3,57 / 4,13 / 3,58). Así que la propuesta no debe presentarse como
la respuesta: hay que mostrarle al operador el efecto en cajas y dejarlo ajustar.
Eso es `preview_evento()`, y es la pieza que hace juzgable la decisión.
"""
import logging
from datetime import date, timedelta
from statistics import median

import pandas as pd

from calendario import semana_viz_inicio
from eventos import expandir_a_domingos
from forecaster import (get_categoria, make_forecast, prepare_prophet_df,
                        train_model, _cap_forecast)
from seasonality import get_regressors

logger = logging.getLogger(__name__)

MIN_SEMANAS_POR_FASE = 3      # una fase mas corta aprende ruido
UMBRAL_SEPARACION = 1.6       # debajo de esto, una sola fase
DIAS_UN_ANIO = 364            # 52 semanas exactas: preserva el dia de la semana


# ── Detección de fases ────────────────────────────────────────────────────────

def _serie_con_base(df, sku: str, canal=None, zona=None) -> pd.DataFrame:
    """Serie semanal del SKU con la base = misma semana ISO en los otros años."""
    pdf = prepare_prophet_df(df, sku, canal, zona)
    s = pdf[["ds", "y"]].copy()
    s["ds"] = pd.to_datetime(s["ds"])
    s["iso"] = s["ds"].apply(lambda d: d.isocalendar()[1])
    s["anio"] = s["ds"].dt.year

    bases, n_comp = [], []
    for _, row in s.iterrows():
        otros = s[(s["iso"] == row["iso"]) & (s["anio"] != row["anio"])]["y"]
        bases.append(float(otros.mean()) if len(otros) else float("nan"))
        n_comp.append(len(otros))
    s["base"] = bases
    s["n_comp"] = n_comp
    return s


def _buscar_corte(ratios: list[float]) -> tuple | None:
    """Corte que mejor separa dos niveles por mediana. Devuelve (k, sep, n1, n2)."""
    if len(ratios) < 2 * MIN_SEMANAS_POR_FASE:
        return None
    mejor = None
    for k in range(MIN_SEMANAS_POR_FASE, len(ratios) - MIN_SEMANAS_POR_FASE + 1):
        n1, n2 = median(ratios[:k]), median(ratios[k:])
        if n1 <= 0 or n2 <= 0:
            continue
        sep = max(n1, n2) / min(n1, n2)
        if mejor is None or sep > mejor[1]:
            mejor = (k, sep, n1, n2)
    return mejor


def detectar_fases(df, sku: str, fecha_desde, fecha_hasta,
                   canal=None, zona=None) -> dict:
    """Propone 1 o 2 fases para el período declarado y devuelve la serie."""
    domingos = expandir_a_domingos(fecha_desde, fecha_hasta)
    if not domingos:
        return {"ok": False, "mensaje": "El período no contiene ninguna semana."}

    s = _serie_con_base(df, sku, canal, zona)
    idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(s["ds"])}

    semanas, ratios, fechas = [], [], []
    faltantes = []
    for dom in domingos:
        i = idx.get(dom)
        if i is None:
            faltantes.append(dom)
            continue
        row = s.iloc[i]
        base = float(row["base"])
        ratio = (float(row["y"]) / base) if base and base > 0 else None
        semanas.append({"ds": dom, "real": float(row["y"]),
                        "base": None if base != base else base,
                        "ratio": ratio, "n_comp": int(row["n_comp"])})
        if ratio is not None:
            ratios.append(ratio)
            fechas.append(dom)

    if faltantes:
        logger.warning("[deteccion] %s: %d semana(s) del periodo no estan en el "
                       "historial de ventas: %s", sku, len(faltantes), faltantes[:5])

    if len(ratios) < 2:
        return {"ok": False, "sku": sku, "semanas": semanas,
                "mensaje": "No hay suficiente historial comparable en ese período."}

    corte = _buscar_corte(ratios)

    # Una sola fase: período corto, o sin escalón de intensidad
    if corte is None or corte[1] < UMBRAL_SEPARACION:
        sep = corte[1] if corte else None
        nivel = median(ratios)
        motivo = ("el período es corto" if corte is None
                  else "la intensidad se mantiene parecida en todo el período")
        return {
            "ok": True, "sku": sku, "semanas": semanas,
            "separacion": sep,
            "fases": [{"etiqueta": "base", "fecha_desde": fechas[0],
                       "fecha_hasta": fechas[-1], "n_semanas": len(fechas),
                       "nivel": round(nivel, 2)}],
            "mensaje": (f"Una sola fase, del {fechas[0]} al {fechas[-1]} "
                        f"({len(fechas)} semanas): {motivo}. En esas semanas se "
                        f"vendió {nivel:.1f} veces lo habitual."),
        }

    k, sep, n1, n2 = corte
    # La etiqueta sale del NIVEL, no de la posición: un evento puede empezar
    # fuerte y aflojar, y en ese caso la primera fase es la fuerte.
    et1, et2 = ("suave", "fuerte") if n1 <= n2 else ("fuerte", "suave")
    fases = [
        {"etiqueta": et1, "fecha_desde": fechas[0], "fecha_hasta": fechas[k - 1],
         "n_semanas": k, "nivel": round(n1, 2)},
        {"etiqueta": et2, "fecha_desde": fechas[k], "fecha_hasta": fechas[-1],
         "n_semanas": len(fechas) - k, "nivel": round(n2, 2)},
    ]
    return {
        "ok": True, "sku": sku, "semanas": semanas, "separacion": round(sep, 2),
        "fases": fases,
        "mensaje": (
            f"Dos fases. Del {fases[0]['fecha_desde']} al {fases[0]['fecha_hasta']} "
            f"({fases[0]['n_semanas']} semanas) se vendió {n1:.1f} veces lo habitual; "
            f"del {fases[1]['fecha_desde']} al {fases[1]['fecha_hasta']} "
            f"({fases[1]['n_semanas']} semanas), {n2:.1f} veces. "
            f"Separar las dos importa: un solo ajuste para todo el período se "
            f"queda corto en la parte fuerte y se pasa en la suave."),
    }


# ── Preview del efecto ────────────────────────────────────────────────────────

def _mas_un_anio(d: str) -> date:
    return semana_viz_inicio(date.fromisoformat(d) + timedelta(days=DIAS_UN_ANIO))


def preview_evento(df, sku: str, fases: list[dict],
                   canal=None, zona=None) -> dict:
    """Qué habría pasado el año pasado, con y sin la corrección.

    Toma la fase más intensa, la corre un año hacia adelante y usa ESE período
    como prueba: entrena con datos hasta la semana previa y compara la
    predicción contra la venta que realmente ocurrió. Es el mismo criterio de
    tuning/exp_evento_holdout.py, que es out-of-sample.

    Entrena 2 modelos (~5 s). NO persiste ninguno.
    """
    if not fases:
        return {"ok": False, "mensaje": "Sin fases que evaluar."}

    pdf = prepare_prophet_df(df, sku, canal, zona)
    pdf = pdf.copy()
    pdf["ds"] = pd.to_datetime(pdf["ds"])
    fin_hist = pdf["ds"].max().date()

    # ventana de prueba: la fase más intensa, un año después
    principal = max(fases, key=lambda f: f.get("nivel") or 0)
    t_desde = _mas_un_anio(str(principal["fecha_desde"])[:10])
    t_hasta = _mas_un_anio(str(principal["fecha_hasta"])[:10])
    if t_hasta > fin_hist:
        return {"ok": False,
                "mensaje": (f"Todavía no se puede comprobar: haría falta la venta "
                            f"real hasta {t_hasta}, y el historial llega a "
                            f"{fin_hist}. El evento es demasiado reciente.")}

    fin_train = t_desde - timedelta(days=7)
    train = pdf[pdf["ds"] <= pd.Timestamp(fin_train)].reset_index(drop=True)
    test = pdf[(pdf["ds"] >= pd.Timestamp(t_desde))
               & (pdf["ds"] <= pd.Timestamp(t_hasta))].reset_index(drop=True)
    if len(train) < 20 or test.empty:
        return {"ok": False, "mensaje": "Historial insuficiente para comprobarlo."}

    categoria = get_categoria(df, sku)
    regressors = get_regressors(categoria)

    eventos = []
    ds_train = set(train["ds"].dt.strftime("%Y-%m-%d"))
    for f in fases:
        fechas = expandir_a_domingos(f["fecha_desde"], f["fecha_hasta"])
        eventos.append({
            "name": f"prev_{f.get('etiqueta') or 'base'}",
            "dates": fechas,
            "_activas": len(ds_train & set(fechas)),
        })
    inertes = [e["name"] for e in eventos if e["_activas"] == 0]
    ev_arg = [{"name": e["name"], "dates": e["dates"]} for e in eventos]

    n_per = int((pd.Timestamp(t_hasta) - train["ds"].max()).days / 7) + 2

    def _predecir(usar_eventos: bool) -> float:
        m = train_model(train, regressors=regressors,
                        extra_events=ev_arg if usar_eventos else None)
        fc = make_forecast(m, n_per, regressors, ev_arg if usar_eventos else None)
        fc = _cap_forecast(fc, train)          # cap sobre TRAIN, no sobre todo
        fc["ds"] = pd.to_datetime(fc["ds"])
        j = test.merge(fc[["ds", "yhat"]], on="ds", how="inner")
        return float(j["yhat"].mean()) if len(j) else float("nan")

    real = float(test["y"].mean())
    sin_ev = _predecir(False)
    con_ev = _predecir(True)

    def _sesgo(p):
        return (100.0 * (p / real - 1.0)) if real else float("nan")

    mejora = abs(_sesgo(sin_ev)) - abs(_sesgo(con_ev))
    if mejora > 0:
        veredicto = (f"La corrección mejora la proyección: el error pasa de "
                     f"{abs(_sesgo(sin_ev)):.0f}% a {abs(_sesgo(con_ev)):.0f}%.")
    else:
        veredicto = ("ATENCIÓN: la corrección NO mejora la proyección de esa "
                     "ventana. Conviene revisar las fechas antes de guardar.")

    return {
        "ok": True,
        "sku": sku,
        "ventana": {"desde": t_desde.isoformat(), "hasta": t_hasta.isoformat(),
                    "n_semanas": len(test)},
        "entrena_hasta": fin_train.isoformat(),
        "real": round(real, 1),
        "sin_evento": round(sin_ev, 1),
        "con_evento": round(con_ev, 1),
        "sesgo_sin": round(_sesgo(sin_ev), 1),
        "sesgo_con": round(_sesgo(con_ev), 1),
        "semanas_activas": {e["name"]: e["_activas"] for e in eventos},
        "inertes": inertes,
        "mensaje": (
            f"Prueba sobre {t_desde} a {t_hasta}, entrenando solo con datos "
            f"hasta {fin_train} (o sea, sin haber visto esas semanas). "
            f"Sin la corrección se habría proyectado {sin_ev:,.0f} cajas/semana; "
            f"con la corrección, {con_ev:,.0f}. Lo que realmente se vendió fue "
            f"{real:,.0f}. {veredicto}"),
    }
