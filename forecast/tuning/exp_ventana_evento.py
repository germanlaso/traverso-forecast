#!/usr/bin/env python3
"""
exp_ventana_evento.py — Compara VENTANAS CANDIDATAS del evento del competidor
contra el criterio de aceptación. NO PERSISTE NADA.

POR QUÉ
-------
`diag_ventana_evento.py` re-derivó una ventana candidata (6 tramos, 2024-08-18 ->
2025-01-12) que NO es la que se validó a mano el 05-08 (sep->dic sin las ISO
37/46/50). Y apareció un problema de fondo: la serie es GRUMOSA (semanas 36/37/38
= 1.891 / 124 / 429), o sea timing de pedidos, no demanda. Eso abre dos lecturas:

  (i)  cherry-pick de picos  -> las semanas bajas NO son evento
  (ii) evento de período     -> el evento fue continuo; las bajas son semanas
                                sin pedido, y hay que incluirlas

El cierre del 05-08 registró que el rango contiguo sep-nov SOBRE-CORRIGE
(septiembre cayó a 181 cj), lo que juega contra (ii). Pero fue n=1. Esto lo mide.

CRITERIO DE ACEPTACIÓN (del §3.2 del cierre 05-08)
--------------------------------------------------
  oct-nov 2026 ~ 844 cj/sem     y     ago-sep 2026 en 950-1.092 cj/sem

GARANTÍAS
---------
No llama a save_model / run_sku_pipeline. Entrena en memoria y descarta. Ningún
pickle de /app/models se toca. Solo lectura de la BD de ventas.

DOS BASELINES, y la diferencia importa
--------------------------------------
  · `pickle_produccion`: lo que hay HOY en disco (entrenado 05-08). Es lo que
    consume el cron. Es el número de eco2.py: ago-sep 1.360 / oct-nov 2.410.
  · `sin_evento`: reentrenado ahora con ventas al día, sin evento. NO es
    producción: incluye ~6 semanas de historia nueva. La brecha entre ambos es,
    de hecho, lo que haría el D2 (retrain semanal) por sí solo.
  Comparar un candidato contra el baseline EQUIVOCADO atribuye al evento un
  efecto que era del retrain.

USO
---
    python3 /app/tuning/exp_ventana_evento.py
    python3 /app/tuning/exp_ventana_evento.py --sku 260010495
    python3 /app/tuning/exp_ventana_evento.py --solo derivado_1.8,contiguo_ago_dic

Correr EN SERIE: verificar `docker stats` en ~0% antes de lanzar.
"""
import argparse
import sys

import pandas as pd

sys.path.insert(0, "/app")

from db import load_sales
from forecaster import (get_categoria, load_model, make_forecast, make_key,
                        prepare_prophet_df, train_model, _cap_forecast)
from seasonality import get_regressors

# Ventanas de medición — IDÉNTICAS a eco2.py, para que los números sean comparables
VENTANAS_MEDICION = [("ago-sep", "08-15", "09-30"), ("oct-nov", "10-01", "11-30")]
ANIO_FC = 2026

# Criterio de aceptación del §3.2
TARGET = {"ago-sep": (950.0, 1092.0), "oct-nov": (800.0, 890.0)}

PERIODS = 26
NOMBRE_REG = "ev_competidor_2024"

# ── Candidatos ────────────────────────────────────────────────────────────────
# Cada candidato es una lista de tramos (desde, hasta) en fechas de DOMINGO.
# `sin_evento` = [] es el baseline reentrenado.
CANDIDATOS: dict[str, list[tuple[str, str]]] = {
    # baseline: reentrenar hoy, sin evento
    "sin_evento": [],

    # (i) lo que devolvió diag_ventana_evento.py con umbral 1.8 — 16 sem, 6 tramos
    "derivado_1.8": [
        ("2024-08-18", "2024-08-18"),
        ("2024-09-01", "2024-09-08"),
        ("2024-09-29", "2024-11-10"),
        ("2024-11-24", "2024-12-08"),
        ("2024-12-22", "2024-12-29"),
        ("2025-01-12", "2025-01-12"),
    ],

    # (ii) evento de período, arrancando en el escalón real de la serie (sem 33)
    "contiguo_ago_dic": [("2024-08-18", "2024-12-29")],

    # (ii) evento de período, arrancando en la fecha comercial declarada
    "contiguo_sep_dic": [("2024-09-01", "2024-12-29")],

    # aproximación de la ventana validada el 05-08: sep->dic sin ISO 37, 46, 50
    "doc_05_08": [
        ("2024-09-01", "2024-09-08"),
        ("2024-09-22", "2024-11-10"),
        ("2024-11-24", "2024-12-08"),
        ("2024-12-22", "2024-12-29"),
    ],
}


def domingos(tramos: list[tuple[str, str]]) -> list[str]:
    """Expande tramos (desde, hasta) a la lista de domingos ISO que contienen.

    Los tramos ya vienen anclados a domingo, así que esto es un paso de 7 días.
    En `eventos.py` este paso lo hará calendario.semana_viz_inicio() sobre las
    fechas naturales que ingrese el usuario.
    """
    out = []
    for a, b in tramos:
        d, fin = pd.Timestamp(a), pd.Timestamp(b)
        while d <= fin:
            out.append(d.strftime("%Y-%m-%d"))
            d += pd.Timedelta(days=7)
    return sorted(set(out))


def medir(fc: pd.DataFrame) -> dict:
    f = fc.copy()
    f["ds"] = pd.to_datetime(f["ds"])
    res = {}
    for etiqueta, a, b in VENTANAS_MEDICION:
        sel = f[(f["ds"] >= f"{ANIO_FC}-{a}") & (f["ds"] <= f"{ANIO_FC}-{b}")]["yhat"]
        res[etiqueta] = float(sel.mean()) if len(sel) else float("nan")
    return res


def coef_regresor(model, nombre: str):
    """Coeficiente aprendido, si la versión de Prophet lo expone."""
    try:
        from prophet.utilities import regressor_coefficients
        rc = regressor_coefficients(model)
        fila = rc[rc["regressor"] == nombre]
        if len(fila):
            return float(fila.iloc[0]["coef"])
    except Exception:
        pass
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", default="250010495")
    ap.add_argument("--solo", default="", help="lista separada por comas")
    args = ap.parse_args()
    sku = args.sku

    pedidos = [c.strip() for c in args.solo.split(",") if c.strip()] or list(CANDIDATOS)
    desconocidos = [c for c in pedidos if c not in CANDIDATOS]
    if desconocidos:
        print(f"Candidatos desconocidos: {desconocidos}")
        print(f"Disponibles: {list(CANDIDATOS)}")
        return

    print(f"=== VENTANAS CANDIDATAS — SKU {sku} (cajas/semana) ===")
    print("NO se persiste ningún modelo. Ventanas de medición iguales a eco2.py.")
    print()

    df = load_sales()
    categoria = get_categoria(df, sku)
    regressors = get_regressors(categoria)
    prophet_df = prepare_prophet_df(df, sku, canal=None, zona=None)
    print(f"categoria: {categoria} | regresores base: {len(regressors)}")
    print(f"historia:  {prophet_df['ds'].min():%Y-%m-%d} -> "
          f"{prophet_df['ds'].max():%Y-%m-%d}  ({len(prophet_df)} sem)")

    # Baseline 1: el pickle que consume el cron HOY
    print()
    cached = load_model(make_key(sku, None, None))
    if cached:
        m_cache, meta_cache = cached
        try:
            fc_c = _cap_forecast(make_forecast(m_cache, PERIODS, regressors), prophet_df)
            m_c = medir(fc_c)
            ent = (meta_cache or {}).get("trained_at", "?") if isinstance(meta_cache, dict) else "?"
            print(f"[pickle_produccion] entrenado {ent}")
            print(f"    ago-sep {m_c['ago-sep']:>8,.0f}   oct-nov {m_c['oct-nov']:>8,.0f}")
        except Exception as e:
            print(f"[pickle_produccion] ERROR: {type(e).__name__}: {e}")
            print("    (si dice 'Regressor ... missing', el pickle está CONTAMINADO)")
    else:
        print("[pickle_produccion] sin pickle en caché")

    print()
    print(f"{'candidato':<20}{'n_sem':>6}{'activas':>8}{'coef':>8}"
          f"{'ago-sep':>10}{'oct-nov':>10}  veredicto")
    print("-" * 78)

    filas = []
    for nombre in pedidos:
        tramos = CANDIDATOS[nombre]
        fechas = domingos(tramos)
        eventos = ([{"name": NOMBRE_REG, "dates": fechas}] if fechas else None)

        try:
            model = train_model(prophet_df, regressors=regressors, extra_events=eventos)
            fc = _cap_forecast(make_forecast(model, PERIODS, regressors, eventos), prophet_df)
        except Exception as e:
            print(f"{nombre:<20}ERROR {type(e).__name__}: {e}")
            continue

        # GUARDA de regresor inerte: cuántas semanas del entrenamiento quedaron en 1.
        # Si hay fechas declaradas y activas==0, el regresor es una columna de ceros
        # y Prophet lo ignora en silencio (bug documentado en
        # exp_realineacion_regresores.py). Un forecast sin corregir y un regresor
        # inerte se ven IDÉNTICOS: sin este contador no se distinguen.
        activas = 0
        if fechas:
            ds_hist = set(pd.to_datetime(prophet_df["ds"]).dt.strftime("%Y-%m-%d"))
            activas = len(ds_hist & set(fechas))

        med = medir(fc)
        coef = coef_regresor(model, NOMBRE_REG) if fechas else None

        if fechas and activas == 0:
            veredicto = "REGRESOR INERTE"
        else:
            ok_a = TARGET["ago-sep"][0] <= med["ago-sep"] <= TARGET["ago-sep"][1]
            ok_o = TARGET["oct-nov"][0] <= med["oct-nov"] <= TARGET["oct-nov"][1]
            veredicto = {(True, True): "CUMPLE ambos",
                         (True, False): "solo ago-sep",
                         (False, True): "solo oct-nov",
                         (False, False): "no cumple"}[(ok_a, ok_o)]

        f_coef = f"{coef:>8.2f}" if coef is not None else f"{'-':>8}"
        print(f"{nombre:<20}{len(fechas):>6}{activas:>8}{f_coef}"
              f"{med['ago-sep']:>10,.0f}{med['oct-nov']:>10,.0f}  {veredicto}")
        filas.append((nombre, len(fechas), activas, med))

    print()
    print(f"Target §3.2: ago-sep {TARGET['ago-sep'][0]:,.0f}-{TARGET['ago-sep'][1]:,.0f}"
          f"  |  oct-nov ~844 (banda {TARGET['oct-nov'][0]:,.0f}-{TARGET['oct-nov'][1]:,.0f})")
    print()
    print("CÓMO LEER:")
    print("  · 'activas' = semanas del entrenamiento con el regresor en 1. Si es 0")
    print("    con fechas declaradas, el regresor no hizo NADA (bug de alineación).")
    print("  · Comparar cada candidato contra `sin_evento`, NO contra")
    print("    `pickle_produccion`: la brecha entre esos dos es efecto del retrain")
    print("    (historia nueva), no del evento.")
    print("  · coef: multiplicativo (seasonality_mode='multiplicative' se hereda en")
    print("    add_regressor). Un coef alto con pocas semanas activas = sobreajuste")
    print("    a picos de pedido, no al evento.")
    print("  · El target de ago-sep (950-1.092) es un JUICIO del 05-08, no una")
    print("    medición: el real 2025 fue 691. Tratarlo como referencia, no ley.")


if __name__ == "__main__":
    main()
