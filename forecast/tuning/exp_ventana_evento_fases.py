#!/usr/bin/env python3
"""
exp_ventana_evento_fases.py — ¿Alcanza UN coeficiente para el evento del
competidor, o hacen falta VARIOS? NO PERSISTE NADA.

QUÉ MOTIVA ESTO
---------------
`exp_ventana_evento.py` probó 4 ventanas con UN solo regresor binario. Las cuatro
bajaron oct-nov ~60% (2.507 -> 975-1.065), pero todas dejaron la misma asimetría:

    ago-sep  ~1,1x del real 2025      oct-nov  ~1,55x del real 2025

Mismo SKU, mismo año, mismo modelo. El eco residual quedó concentrado en oct-nov.

La causa probable es que el evento de 2024 NO fue homogéneo. Contra el nivel
pre-evento (267 cj/sem):

    ago-sep 2024:   914  ->  3,4x
    oct-nov 2024: 1.983  ->  7,4x     (2,2 veces más anómalo)

Un regresor binario aprende UN coeficiente y lo aplica uniforme a todo el
período: se pasa corrigiendo la fase suave y se queda corto en la fuerte. Esto
mide si separar en fases (un regresor por fase, cada uno con su coeficiente)
elimina la asimetría.

CORTE ENTRE FASES
-----------------
Semana ISO 39/40 (2024-09-29 / 2024-10-06). Dos razones: en la serie, desde la
semana 40 los valores pasan a ser consistentemente altos (1.370-3.116 salvo las
semanas sin pedido), y coincide con el borde de las ventanas de medición
(ago-sep termina 09-30), así que el resultado es interpretable sin solapamiento.

CRITERIO (reemplaza el del §3.2, que no reproduce: su baseline de 2.776 no se
obtiene ni con el pickle -2.410- ni reentrenando -2.507-)
---------------------------------------------------------------------------
  1. SIMETRÍA: ago-sep y oct-nov deben quedar en un ratio PARECIDO contra el
     real 2025. La asimetría es la señal del eco residual.
  2. Nivel razonable: ratios cerca de 1 + crecimiento genuino, no 1,5x.
  Ambos son internos al experimento y reproducibles.

GARANTÍAS
---------
No llama a save_model / run_sku_pipeline. Entrena en memoria y descarta.

USO
---
    python3 /app/tuning/exp_ventana_evento_fases.py
    python3 /app/tuning/exp_ventana_evento_fases.py --solo sin_evento,dos_fases_contiguo

Correr EN SERIE: `docker stats` en ~0% antes de lanzar.
"""
import argparse
import sys

import pandas as pd

sys.path.insert(0, "/app")

from db import load_sales
from forecaster import (get_categoria, make_forecast, prepare_prophet_df,
                        train_model, _cap_forecast)
from seasonality import get_regressors

VENTANAS_MEDICION = [("ago-sep", "08-15", "09-30"), ("oct-nov", "10-01", "11-30")]
ANIO_FC = 2026
PERIODS = 26

# Reales del SKU 250010495 (de eco2.py), cajas/semana. Yardstick reproducible.
REAL_2025 = {"ago-sep": 691.0, "oct-nov": 639.0}

# ── Candidatos: nombre -> lista de regresores, cada uno con sus tramos ────────
# Un regresor = un coeficiente que Prophet aprende por separado.
F1_CONTIG = ("2024-08-18", "2024-09-29")   # fase suave  (3,4x sobre pre-evento)
F2_CONTIG = ("2024-10-06", "2024-12-29")   # fase fuerte (7,4x sobre pre-evento)

# semanas derivadas por diag_ventana_evento.py (umbral 1.8), partidas en 39/40
F1_DERIV = [("2024-08-18", "2024-08-18"), ("2024-09-01", "2024-09-08"),
            ("2024-09-29", "2024-09-29")]
F2_DERIV = [("2024-10-06", "2024-11-10"), ("2024-11-24", "2024-12-08"),
            ("2024-12-22", "2024-12-29")]
TAIL_2025 = [("2025-01-12", "2025-01-12")]

CANDIDATOS: dict[str, list[dict]] = {
    # baseline
    "sin_evento": [],

    # referencia: el mejor de la corrida anterior, UN regresor
    "una_fase_derivado": [
        {"name": "ev_comp", "tramos": F1_DERIV + F2_DERIV + TAIL_2025},
    ],

    # dos fases, período completo y contiguo
    "dos_fases_contiguo": [
        {"name": "ev_comp_f1", "tramos": [F1_CONTIG]},
        {"name": "ev_comp_f2", "tramos": [F2_CONTIG]},
    ],

    # dos fases, solo las semanas que superan el umbral
    "dos_fases_derivado": [
        {"name": "ev_comp_f1", "tramos": F1_DERIV},
        {"name": "ev_comp_f2", "tramos": F2_DERIV + TAIL_2025},
    ],

    # tres fases: agrega la cola de enero 2025 como fase propia
    "tres_fases": [
        {"name": "ev_comp_f1", "tramos": [F1_CONTIG]},
        {"name": "ev_comp_f2", "tramos": [F2_CONTIG]},
        {"name": "ev_comp_f3", "tramos": [("2025-01-05", "2025-01-26")]},
    ],
}


def domingos(tramos) -> list[str]:
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


def coefs(model) -> dict:
    try:
        from prophet.utilities import regressor_coefficients
        rc = regressor_coefficients(model)
        return {r["regressor"]: float(r["coef"]) for _, r in rc.iterrows()}
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", default="250010495")
    ap.add_argument("--solo", default="")
    args = ap.parse_args()

    pedidos = [c.strip() for c in args.solo.split(",") if c.strip()] or list(CANDIDATOS)
    malos = [c for c in pedidos if c not in CANDIDATOS]
    if malos:
        print(f"Desconocidos: {malos}\nDisponibles: {list(CANDIDATOS)}")
        return

    print(f"=== EVENTO EN FASES — SKU {args.sku} (cajas/semana) ===")
    print("NO se persiste ningún modelo.")
    print(f"real 2025: ago-sep {REAL_2025['ago-sep']:,.0f} | "
          f"oct-nov {REAL_2025['oct-nov']:,.0f}")
    print()

    df = load_sales()
    categoria = get_categoria(df, args.sku)
    regressors = get_regressors(categoria)
    prophet_df = prepare_prophet_df(df, args.sku, canal=None, zona=None)
    ds_hist = set(pd.to_datetime(prophet_df["ds"]).dt.strftime("%Y-%m-%d"))
    print(f"categoria: {categoria} | historia: {len(prophet_df)} sem "
          f"(hasta {prophet_df['ds'].max():%Y-%m-%d})")
    print()

    print(f"{'candidato':<22}{'regs':>5}{'sem':>5}{'act':>5}"
          f"{'ago-sep':>9}{'r25':>6}{'oct-nov':>9}{'r25':>6}{'asim':>7}")
    print("-" * 74)

    for nombre in pedidos:
        especs = CANDIDATOS[nombre]
        eventos, n_sem, n_act = [], 0, 0
        for e in especs:
            fechas = domingos(e["tramos"])
            eventos.append({"name": e["name"], "dates": fechas})
            n_sem += len(fechas)
            n_act += len(ds_hist & set(fechas))

        ev_arg = eventos or None
        try:
            model = train_model(prophet_df, regressors=regressors, extra_events=ev_arg)
            fc = _cap_forecast(
                make_forecast(model, PERIODS, regressors, ev_arg), prophet_df)
        except Exception as e:
            print(f"{nombre:<22}ERROR {type(e).__name__}: {e}")
            continue

        # Guarda de regresor inerte (ver exp_realineacion_regresores.py)
        if n_sem and n_act == 0:
            print(f"{nombre:<22}{len(eventos):>5}{n_sem:>5}{n_act:>5}"
                  f"   REGRESOR INERTE — el resto no significa nada")
            continue

        m = medir(fc)
        r_a = m["ago-sep"] / REAL_2025["ago-sep"]
        r_o = m["oct-nov"] / REAL_2025["oct-nov"]
        asim = r_o - r_a          # ~0 => el eco residual está repartido, no concentrado

        print(f"{nombre:<22}{len(eventos):>5}{n_sem:>5}{n_act:>5}"
              f"{m['ago-sep']:>9,.0f}{r_a:>6.2f}{m['oct-nov']:>9,.0f}{r_o:>6.2f}"
              f"{asim:>+7.2f}")

        cc = {k: v for k, v in coefs(model).items() if k.startswith("ev_")}
        if cc:
            detalle = "  ".join(f"{k}={v:+.2f}" for k, v in sorted(cc.items()))
            print(f"{'':<22}coef: {detalle}")

    print()
    print("CÓMO LEER:")
    print("  · r25  = forecast 2026 / real 2025. No se espera 1,00 exacto (hay")
    print("           crecimiento genuino por clientes retenidos + tendencia).")
    print("  · asim = r25(oct-nov) - r25(ago-sep). ES LA MÉTRICA CLAVE: mide si el")
    print("           eco quedó CONCENTRADO en oct-nov. Con un regresor único dio")
    print("           +0,44 a +0,84. Cerca de 0 => las fases capturaron cada")
    print("           intensidad por separado.")
    print("  · coef = multiplicativo. Se espera f2 > f1 (7,4x vs 3,4x en 2024).")
    print("           Si salen parecidos, la hipótesis de las dos fases es falsa.")
    print("  · act  = semanas del entrenamiento con el regresor en 1. Si es 0 con")
    print("           semanas declaradas, el regresor no hizo nada.")


if __name__ == "__main__":
    main()
