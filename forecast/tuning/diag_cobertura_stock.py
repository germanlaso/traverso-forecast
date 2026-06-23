#!/usr/bin/env python3
"""
diag_cobertura_stock.py — PASO 1 (v2). SOLO LECTURA, no modela.

Redefine 'quiebre' con la definicion de German: STOCK CRITICO = el stock cubre
menos de X dias de venta tipica, sostenido al menos 7 dias consecutivos.

Por que v2: la v1 (presencia/stock=0) era demasiado binaria — un lote nunca
aparece con stock 0 (el quiebre se ve como ausencia de fila), y la presencia era
~98% en sano y cola por igual. Pero stock BAJO relativo a la demanda frena
ventas mucho antes de llegar a 0. Esta version mide eso.

DECISIONES (consensuadas):
  - Venta diaria de referencia = venta TIPICA del SKU (mediana de venta semanal
    de las ultimas ~8 semanas con venta) / 7. NO la venta contemporanea, para
    evitar circularidad: si la venta cayo POR el quiebre, usar la venta de esa
    semana escondería el quiebre (poco stock / poca venta = parece que alcanza).
  - Cobertura_dias = stock_disponible_dia / venta_diaria_referencia.
  - Critico = cobertura < UMBRAL (3 y 5 dias) sostenido >= 7 dias CONSECUTIVOS
    (consecutivos medidos sobre dias de calendario; huecos de snapshot rompen
    la racha de forma conservadora).

PRUEBA DE CENSURA (la clave): en las semanas marcadas criticas, ¿la venta cae
respecto al baseline del SKU? Si cae -> censura real -> regresor vale. Si no
cae -> stock ajustado sin censura -> regresor no ayuda.

USO:
  docker cp diag_cobertura_stock.py traverso_forecast:/tmp/diag_cobertura_stock.py
  docker exec traverso_forecast python3 /tmp/diag_cobertura_stock.py 2>&1 | grep -v -i warning
"""
import sys, os
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from sqlalchemy import text
from db import get_engine, load_sales

BODEGAS = ("BSUR01", "VESP01", "VARA01")
UMBRALES_DIAS = [3, 5]      # cobertura critica
RACHA_MIN = 7               # dias consecutivos
BASELINE_SEMANAS = 8        # ventana para venta tipica

STOCK_QUERY = """
SELECT [CODIGO] AS sku, [STOCK] AS stock_raw,
       [FECHA VCTO] AS fecha_vcto, [FECHA DESCARGA INFO] AS fecha_snap
FROM dbo.Stock_Lote_Fecha
WHERE [BODEGA] IN ('BSUR01','VESP01','VARA01')
  AND [CODIGO] IS NOT NULL AND [CODIGO] <> ''
  AND [STOCK]  IS NOT NULL AND [STOCK]  <> ''
"""

def cargar_stock_diario():
    with get_engine().connect() as c:
        r = c.execute(text(STOCK_QUERY))
        df = pd.DataFrame(r.fetchall(), columns=r.keys())
    df["sku"] = df["sku"].astype(str).str.strip()
    df["stock"] = (df["stock_raw"].astype(str).str.strip()
                   .str.replace(r"\.(?=\d{3})", "", regex=True)
                   .str.replace(",", ".", regex=False))
    df["stock"] = pd.to_numeric(df["stock"], errors="coerce").fillna(0)
    df["fecha_snap"] = pd.to_datetime(df["fecha_snap"], dayfirst=True, errors="coerce")
    df["fecha_vcto"] = pd.to_datetime(df["fecha_vcto"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["fecha_snap"])
    df = df[~(df["fecha_vcto"].notna() & (df["fecha_vcto"] < df["fecha_snap"]))]  # vencidos
    # stock disponible por SKU-dia (suma lotes/bodegas)
    return df.groupby(["sku", "fecha_snap"])["stock"].sum().reset_index()

def venta_diaria_referencia(ventas):
    """Mediana de venta semanal de las ultimas BASELINE_SEMANAS con venta, /7."""
    v = (ventas.groupby(["sku", "fecha_semana"])["cantidad"].sum()
         .reset_index().sort_values(["sku", "fecha_semana"]))
    out = {}
    for sku, g in v.groupby("sku"):
        ult = g.tail(BASELINE_SEMANAS)["cantidad"]
        m = ult.median()
        if m and m > 0:
            out[sku] = m / 7.0
    return out

def rachas_criticas(fechas, criticos, racha_min):
    """fechas: serie de Timestamps ordenada; criticos: bool alineado.
    Cuenta dias que pertenecen a una racha de >= racha_min dias consecutivos
    de calendario en estado critico. Devuelve set de fechas en racha."""
    en_racha = set()
    run = []
    fechas = list(fechas)
    for i, (f, crit) in enumerate(zip(fechas, criticos)):
        if crit and (not run or (f - run[-1]).days == 1):
            run.append(f)
        elif crit:  # critico pero hubo salto de fechas -> nueva racha
            if len(run) >= racha_min:
                en_racha.update(run)
            run = [f]
        else:
            if len(run) >= racha_min:
                en_racha.update(run)
            run = []
    if len(run) >= racha_min:
        en_racha.update(run)
    return en_racha

def main():
    print("=== DIAGNOSTICO COBERTURA / CENSURA DE STOCK ===\n", flush=True)
    print("[1] stock diario por SKU...", flush=True)
    sd = cargar_stock_diario()
    print(f"    {len(sd):,} SKU-dia | {sd['sku'].nunique()} SKUs | "
          f"{sd['fecha_snap'].min().date()} -> {sd['fecha_snap'].max().date()}", flush=True)

    print("[2] venta tipica de referencia...", flush=True)
    ventas = load_sales()
    vref = venta_diaria_referencia(ventas)
    sd["v_dia"] = sd["sku"].map(vref)
    sd = sd.dropna(subset=["v_dia"])
    sd["cobertura_dias"] = sd["stock"] / sd["v_dia"]
    print(f"    {sd['sku'].nunique()} SKUs con venta de referencia\n", flush=True)

    # WMAPE baseline para clasificar sano/cola
    ev = None
    for p in ("/app/eval_check_noreg.csv", "/app/eval_error_topdown_top100_act4s.csv"):
        if os.path.exists(p):
            ev = pd.read_csv(p, dtype={"sku": str}); ev["sku"] = ev["sku"].str.strip(); break

    for umbral in UMBRALES_DIAS:
        print("=" * 64, flush=True)
        print(f"UMBRAL: cobertura < {umbral} dias, sostenida >= {RACHA_MIN} dias consecutivos", flush=True)
        print("=" * 64, flush=True)
        sd["crit"] = sd["cobertura_dias"] < umbral
        # rachas por SKU
        dias_en_racha = {}
        for sku, g in sd.sort_values("fecha_snap").groupby("sku"):
            en = rachas_criticas(g["fecha_snap"], g["crit"].tolist(), RACHA_MIN)
            if en:
                dias_en_racha[sku] = en
        n_skus_afectados = len(dias_en_racha)
        total_dias_critico = sum(len(v) for v in dias_en_racha.values())
        print(f"  SKUs con al menos una racha critica: {n_skus_afectados} de {sd['sku'].nunique()}", flush=True)
        print(f"  Total SKU-dia en racha critica: {total_dias_critico:,}", flush=True)

        if ev is not None:
            # fraccion de dias en racha critica por SKU (sobre sus dias observados)
            obs = sd.groupby("sku")["fecha_snap"].nunique()
            frac = {s: len(d) / obs[s] for s, d in dias_en_racha.items()}
            ev["_frac_crit"] = ev["sku"].map(frac).fillna(0.0)
            sano = ev[ev["wmape_sem_%"] <= 50]; cola = ev[ev["wmape_sem_%"] > 50]
            print(f"  Frac dias criticos — SANO: {100*sano['_frac_crit'].mean():.1f}%  | "
                  f"COLA: {100*cola['_frac_crit'].mean():.1f}%", flush=True)
            corr = ev["_frac_crit"].corr(ev["wmape_sem_%"])
            print(f"  Correlacion frac_critico vs WMAPE: {corr:+.3f}", flush=True)

        # PRUEBA DE CENSURA: en semanas criticas, ¿cae la venta vs baseline del SKU?
        # Alinear dias criticos a semana-domingo y comparar venta de esa semana
        # contra la venta tipica semanal del SKU.
        if dias_en_racha:
            crit_dias = pd.DataFrame(
                [(s, f) for s, ds in dias_en_racha.items() for f in ds],
                columns=["sku", "fecha"])
            wd = crit_dias["fecha"].dt.weekday
            crit_dias["semana"] = crit_dias["fecha"] - pd.to_timedelta((wd + 1) % 7, unit="D")
            sem_crit = crit_dias.drop_duplicates(["sku", "semana"])[["sku", "semana"]]
            vsem = ventas.groupby(["sku", "fecha_semana"])["cantidad"].sum().reset_index()
            vsem.columns = ["sku", "semana", "venta"]
            vtip = {s: v * 7 for s, v in vref.items()}  # venta semanal tipica
            m = sem_crit.merge(vsem, on=["sku", "semana"], how="left")
            m["venta"] = m["venta"].fillna(0)
            m["v_tipica"] = m["sku"].map(vtip)
            m = m.dropna(subset=["v_tipica"])
            m = m[m["v_tipica"] > 0]
            m["ratio"] = m["venta"] / m["v_tipica"]
            print(f"  PRUEBA DE CENSURA ({len(m)} semanas-SKU criticas):", flush=True)
            print(f"    venta media en semana critica vs tipica: {100*m['ratio'].mean():.0f}% "
                  f"(< 100% sugiere censura)", flush=True)
            print(f"    mediana: {100*m['ratio'].median():.0f}%", flush=True)
        print(flush=True)

    print("=" * 64, flush=True)
    print("Lectura: el regresor de quiebre vale si (a) la COLA tiene mas dias", flush=True)
    print("criticos que el SANO, (b) correlacion positiva, y sobre todo (c) la", flush=True)
    print("venta CAE en semanas criticas (ratio < 100%). Si la venta NO cae, el", flush=True)
    print("stock bajo no censura -> no es la palanca.", flush=True)
    print("=== FIN ===", flush=True)

if __name__ == "__main__":
    main()
