"""
proyeccion.py — Construcción de la proyección semanal por SKU para el frontend.

Bloque B1 de V6.27 (auditoría completa backend↔frontend, 11/05/2026).
Schema completo en docs/SCHEMA_PROYECCION_POR_SKU.md.

Filosofía:
  - Backend es fuente única de verdad: emite proyección completa.
  - Frontend solo renderiza, no recalcula.
  - Cubre TODOS los SKUs activos del catálogo (no solo los del optimizer).
  - Cobertura ∈ {proyeccion_completa, solo_stock, sin_proyeccion}.

Decisiones de diseño cerradas con usuario (chat web, 11/05/2026):
  D1 - Emitir stock_fin_cj_visible (clampeado ≥0, curva azul) Y
       stock_fin_cj_real (negativo posible, KPIs + estado).
  D2 - Semana = domingo a sábado (calendario.semana_viz_inicio).
  D3 - Incluir todos los SKUs activos, con flag cobertura.

Convenciones:
  - yhat de Prophet viene en CAJAS (run_sku_pipeline).
  - stocks_actuales en CAJAS (calcular_stock_disponible).
  - Cantidad_real_cj / cantidad_cajas en CAJAS.
  - Toda la respuesta en CAJAS, redondeado a 1 decimal.
"""

from datetime import date, timedelta
from typing import Any

from calendario import (
    semana_viz_inicio,
    semana_iso_inicio,
    distribuir_forecast_a_diario,
)


# =============================================================================
# Enumeración de semanas viz
# =============================================================================

def enumerar_semanas_viz(fecha_inicio: date, fecha_fin: date) -> list[date]:
    """Lista de domingos (semana_viz_inicio) que cubren [fecha_inicio, fecha_fin].

    La primera semana arranca en el domingo previo (o igual a) fecha_inicio.
    Cada elemento cubre 7 días dom-sáb.
    """
    semanas: list[date] = []
    sem = semana_viz_inicio(fecha_inicio)
    while sem <= fecha_fin:
        semanas.append(sem)
        sem = sem + timedelta(days=7)
    return semanas


# =============================================================================
# Helpers
# =============================================================================

def _parse_fecha(s: Any) -> date | None:
    """Convierte string ISO / date a date. None si no parsea."""
    if s is None:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Lee atributo de objeto o clave de dict (polimórfico)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# Mapeo nombre_canonico → aliases (defensivo: tolera SKUParams (dataclass) y dicts crudos de BD)
_SKU_ATTR_ALIASES = {
    "unidades_por_caja":     ("unidades_por_caja", "u_por_caja", "upj"),
    "stock_seguridad_dias":  ("stock_seguridad_dias", "ss_dias"),
    "cap_bodega":            ("cap_bodega", "cap_bodega_u"),
    "tipo":                  ("tipo",),
    "lead_time_semanas":     ("lead_time_semanas", "lead_time_sem"),
}


def _get_sku_attr(sp: Any, canonico: str, default: Any = None) -> Any:
    """
    Lee un atributo del SKUParams probando múltiples alias.

    El dataclass `SKUParams` (mrp.py) usa nombres largos
    (`unidades_por_caja`, `stock_seguridad_dias`, `cap_bodega`), pero los
    rows crudos de BD usan nombres cortos (`u_por_caja`, `ss_dias`,
    `cap_bodega_u`). Esta función prueba ambos para ser robusta.

    Devuelve el primer valor no-None, sino default.
    """
    aliases = _SKU_ATTR_ALIASES.get(canonico, (canonico,))
    for name in aliases:
        v = _attr(sp, name, None)
        if v is not None:
            return v
    return default


# =============================================================================
# Agregación de entradas
# =============================================================================

def _agregar_entradas_por_semana(
    ordenes_finales: list[dict],
    aprobadas_db: list[dict],
    fecha_inicio: date,
    fecha_fin: date,
) -> dict[str, dict[date, dict]]:
    """
    Agrupa entradas por (sku, semana_viz) según fecha_entrada_real.

    Devuelve {sku: {sem_dom: {aprobadas_cj, sugeridas_cj, n_ofts}}}.

    Reglas (ver schema §2.2):
    - Aprobadas: cantidad_real_cj y fecha_entrada_real de aprobadas_db
      (fuente de verdad). Si fecha_entrada_real no viene, usar semana_necesidad.
    - Sugeridas: OFTs en ordenes_finales con aprobada=False y numero_of
      no presente en aprobadas_db (evita doble conteo).
    - Entradas con fecha_entrada_real fuera del horizonte se ignoran.
    - n_ofts cuenta por fecha_entrada_real, NO por fecha_lanzamiento.
    """
    # Set de numero_of que están aprobados (para evitar doble conteo en sugeridas)
    apr_numof = {a.get("numero_of") for a in aprobadas_db if a.get("numero_of")}

    result: dict[str, dict[date, dict]] = {}

    def _bucket(sku: str, sem: date) -> dict:
        if sku not in result:
            result[sku] = {}
        if sem not in result[sku]:
            result[sku][sem] = {"aprobadas_cj": 0.0, "sugeridas_cj": 0.0, "n_ofts": 0}
        return result[sku][sem]

    # 1) Aprobadas — fuente: tabla mrp_aprobaciones
    for a in aprobadas_db:
        sku = a.get("sku")
        fer = _parse_fecha(a.get("fecha_entrada_real") or a.get("semana_necesidad"))
        if not sku or not fer:
            continue
        if fer < fecha_inicio or fer > fecha_fin:
            continue
        cj = float(a.get("cantidad_real_cj", 0) or 0)
        if cj <= 0:
            continue
        b = _bucket(sku, semana_viz_inicio(fer))
        b["aprobadas_cj"] += cj
        b["n_ofts"] += 1

    # 2) Sugeridas — OFTs no aprobadas en ordenes_finales
    for o in ordenes_finales:
        if o.get("aprobada"):
            continue  # ya contada arriba como aprobada
        nof = o.get("numero_of")
        if nof and nof in apr_numof:
            continue  # numero_of pertenece a una aprobación → ya contada
        sku = o.get("sku")
        fer = _parse_fecha(o.get("fecha_entrada_real") or o.get("semana_necesidad"))
        if not sku or not fer:
            continue
        if fer < fecha_inicio or fer > fecha_fin:
            continue
        cj = float(o.get("cantidad_cajas", 0) or 0)
        if cj <= 0:
            continue
        b = _bucket(sku, semana_viz_inicio(fer))
        b["sugeridas_cj"] += cj
        b["n_ofts"] += 1

    return result


# =============================================================================
# Forecast → dict semanal
# =============================================================================

def _forecast_a_dict_semanal(
    forecast_lista: list[dict],
    fecha_inicio: date,
    fecha_fin: date,
) -> dict[date, float]:
    """
    Convierte forecast list [{ds, yhat}, ...] (yhat en CAJAS) en dict
    {lunes_iso: yhat_cajas} filtrado al horizonte extendido.

    El horizonte extendido incluye la semana ISO del fecha_inicio y la del
    fecha_fin para que distribuir_forecast_a_diario cubra ambos bordes.
    """
    lunes_inicio = semana_iso_inicio(fecha_inicio)
    lunes_fin = semana_iso_inicio(fecha_fin)

    out: dict[date, float] = {}
    for f in forecast_lista or []:
        ds = _parse_fecha(_attr(f, "ds"))
        if ds is None:
            continue
        lunes = semana_iso_inicio(ds)
        if lunes < lunes_inicio or lunes > lunes_fin:
            continue
        yhat = max(0.0, float(_attr(f, "yhat", 0) or 0))
        out[lunes] = out.get(lunes, 0.0) + yhat
    return out


# =============================================================================
# Cobertura
# =============================================================================

def _decidir_cobertura(
    sp: Any,
    forecast_sem: dict[date, float],
    stock_cj: float,
) -> str:
    """
    Decide cobertura según schema §3:
    - sin_proyeccion: no hay forecast.
    - solo_stock: IMPORTACION, filtrado V6.12-mini, o demanda_total=0.
    - proyeccion_completa: PROD con forecast > 0 y no filtrado.
    """
    if not forecast_sem:
        return "sin_proyeccion"
    tipo = str(_get_sku_attr(sp, "tipo", "PRODUCCION") or "PRODUCCION").upper()
    if tipo == "IMPORTACION":
        return "solo_stock"
    upc = int(_get_sku_attr(sp, "unidades_por_caja", 1) or 1)
    cap_u = int(_get_sku_attr(sp, "cap_bodega", 0) or 0)
    stock_u = stock_cj * upc
    if cap_u > 0 and stock_u > cap_u:
        return "solo_stock"  # V6.12-mini filtrado
    total_demanda = sum(forecast_sem.values())
    if total_demanda <= 0:
        return "solo_stock"  # demanda nula → fuera del modelo
    return "proyeccion_completa"


# =============================================================================
# Función pública
# =============================================================================

def construir_proyeccion_por_sku(
    ordenes_finales: list[dict],
    aprobadas_db: list[dict],
    sku_params: dict[str, Any],
    forecasts: dict[str, list[dict]],
    stocks_actuales: dict[str, float],
    fecha_inicio: date,
    horizonte_dias: int,
) -> dict[str, dict]:
    """
    Construye el campo proyeccion_por_sku para el response de /plan.

    Args:
        ordenes_finales: lista de órdenes (PROD + IMPORTACION) emitidas por
            el optimizador o el MRP clásico. Cada una con sku, fecha_lanzamiento,
            fecha_entrada_real, cantidad_cajas, aprobada, numero_of, tipo.
        aprobadas_db: filas de mrp_aprobaciones (listar_aprobadas_db). Cada una
            con sku, fecha_entrada_real, cantidad_real_cj, numero_of,
            semana_necesidad.
        sku_params: dict {sku: SKUParams} con TODOS los SKUs activos del
            catálogo (no filtrar previamente).
        forecasts: dict {sku: [{ds, yhat}, ...]} con yhat en CAJAS (semanal).
        stocks_actuales: dict {sku: stock_cj} desde calcular_stock_disponible.
        fecha_inicio: primer día del horizonte (típicamente date.today()).
        horizonte_dias: cantidad de días del horizonte (horizonte_semanas * 7).

    Returns:
        dict {sku: {stock_inicial_cj, cobertura, semanas: [...]}}.

    El frontend lee este campo directamente para renderizar la proyección de
    stock por SKU sin recalcular nada (V6.14 v2 + V6.26 + Bloque B1).
    """
    fecha_fin = fecha_inicio + timedelta(days=horizonte_dias - 1)
    semanas_viz = enumerar_semanas_viz(fecha_inicio, fecha_fin)

    entradas_por_sku = _agregar_entradas_por_semana(
        ordenes_finales, aprobadas_db, fecha_inicio, fecha_fin,
    )

    proyeccion: dict[str, dict] = {}

    for sku, sp in sku_params.items():
        upc = int(_get_sku_attr(sp, "unidades_por_caja", 1) or 1)
        ss_dias = float(_get_sku_attr(sp, "stock_seguridad_dias", 0) or 0)
        stock_ini_cj = float(stocks_actuales.get(sku, 0) or 0)

        forecast_sem = _forecast_a_dict_semanal(
            forecasts.get(sku, []), fecha_inicio, fecha_fin,
        )

        cobertura = _decidir_cobertura(sp, forecast_sem, stock_ini_cj)

        if cobertura == "sin_proyeccion":
            proyeccion[sku] = {
                "stock_inicial_cj": round(stock_ini_cj, 1),
                "cobertura": cobertura,
                "semanas": [],
            }
            continue

        # Distribución forecast → demanda diaria (en cajas, sin convertir a u)
        demanda_diaria_cj = distribuir_forecast_a_diario(
            forecast_sem, fecha_inicio, fecha_fin,
        )

        entradas_sku = entradas_por_sku.get(sku, {})
        semanas_out: list[dict] = []
        stock_acum_real = stock_ini_cj

        # ─── Convención de semana parcial inicial ────────────────────────────
        # Si fecha_inicio NO es domingo (ej. plan corre miércoles), la primera
        # semana viz arranca el domingo previo a fecha_inicio. Decisión cerrada
        # con usuario (D2 + observación 2 del schema doc):
        #   - stock_ini_cj de semana 0 = stock_actual del parquet (HOY), NO
        #     reconstruido restando ventas dom→hoy. Coincide con "stock real"
        #     del dashboard. Marcamos semana_parcial=true.
        #   - ventas_cj de semana 0 cubre solo los días dentro del horizonte
        #     (de hoy al sábado), no los días previos. distribuir_forecast_a_diario
        #     ya respeta este filtro por construcción.
        #   - stock_fin_real = stock_ini (hoy) + entradas_horizonte - ventas_horizonte.
        # Implicación: semana 0 representa "qué va a pasar de hoy al sábado",
        # no "qué pasó la semana entera". Coherente con la expectativa del usuario.
        # ─────────────────────────────────────────────────────────────────────

        for sem in semanas_viz:
            sem_fin = sem + timedelta(days=6)

            # Ventas: suma demanda diaria en cajas de los 7 días, intersectado
            # con horizonte. Días fuera del horizonte cuentan 0 (no afectan).
            ventas_sem_cj = 0.0
            dia = sem
            while dia <= sem_fin:
                if fecha_inicio <= dia <= fecha_fin:
                    ventas_sem_cj += demanda_diaria_cj.get(dia, 0.0)
                dia += timedelta(days=1)

            ent = entradas_sku.get(sem, {})
            entr_apr = float(ent.get("aprobadas_cj", 0.0))
            entr_sug = float(ent.get("sugeridas_cj", 0.0))
            entr_tot = entr_apr + entr_sug
            n_ofts = int(ent.get("n_ofts", 0))

            stock_ini_sem = stock_acum_real
            stock_fin_real = stock_acum_real + entr_tot - ventas_sem_cj
            stock_fin_visible = max(0.0, stock_fin_real)

            # SS semanal: forecast viene en semanas ISO (lun-dom); semana viz
            # va dom-sáb. Tomamos el yhat de la semana ISO cuyo lunes sigue al
            # domingo de la semana viz — esa es la semana ISO que comparte 6
            # de los 7 días con la semana viz.
            lunes_iso = semana_iso_inicio(sem + timedelta(days=1))
            yhat_sem_cj = forecast_sem.get(lunes_iso, 0.0)
            ss_cj = (yhat_sem_cj / 7.0) * ss_dias if ss_dias > 0 else 0.0

            # Estado (schema §4)
            if stock_fin_real < 0:
                estado = "QUIEBRE"
            elif stock_fin_real < ss_cj:
                estado = "BAJO_SS"
            else:
                estado = "OK"

            semana_parcial = (
                (sem == semanas_viz[0] and fecha_inicio > sem)
                or (sem == semanas_viz[-1] and fecha_fin < sem_fin)
            )

            semanas_out.append({
                "semana": sem.isoformat(),
                "stock_ini_cj": round(stock_ini_sem, 1),
                "entradas_cj": round(entr_tot, 1),
                "entradas_aprobadas_cj": round(entr_apr, 1),
                "entradas_sugeridas_cj": round(entr_sug, 1),
                "ventas_cj": round(ventas_sem_cj, 1),
                "ss_cj": round(ss_cj, 1),
                "stock_fin_cj_visible": round(stock_fin_visible, 1),
                "stock_fin_cj_real": round(stock_fin_real, 1),
                "estado": estado,
                "n_ofts_semana": n_ofts,
                "semana_parcial": semana_parcial,
            })

            stock_acum_real = stock_fin_real

        proyeccion[sku] = {
            "stock_inicial_cj": round(stock_ini_cj, 1),
            "cobertura": cobertura,
            "semanas": semanas_out,
        }

    return proyeccion


# =============================================================================
# Smoke test — ejecutable con `python proyeccion.py`
# =============================================================================

if __name__ == "__main__":
    from datetime import date

    print("=" * 60)
    print("Smoke test: proyeccion.py — Bloque B1 / V6.27")
    print("=" * 60)

    # SKU mock con todos los atributos relevantes
    class _SP:
        def __init__(self, tipo="PRODUCCION", upc=30, ss=10, cap=200_000):
            self.tipo = tipo
            self.unidades_por_caja = upc
            self.stock_seguridad_dias = ss
            self.cap_bodega = cap

    fecha_inicio = date(2026, 5, 11)  # lunes (semana viz dom 10/05)
    horizonte_dias = 28

    sku_params = {
        "A_PROD": _SP(tipo="PRODUCCION"),
        "B_IMP":  _SP(tipo="IMPORTACION"),
        "C_SIN_FC": _SP(tipo="PRODUCCION"),  # no estará en forecasts
        "D_DEMANDA0": _SP(tipo="PRODUCCION"),
        "E_FILTRADO_CAP": _SP(tipo="PRODUCCION", cap=10_000),
        "F_V6_26": _SP(tipo="PRODUCCION"),  # OFT con lanzamiento <= hoy (bug V6.26)
    }

    forecasts = {
        "A_PROD": [
            {"ds": "2026-05-11", "yhat": 100.0},
            {"ds": "2026-05-18", "yhat": 120.0},
            {"ds": "2026-05-25", "yhat": 100.0},
            {"ds": "2026-06-01", "yhat": 100.0},
        ],
        "B_IMP": [
            {"ds": "2026-05-11", "yhat": 20.0},
            {"ds": "2026-05-18", "yhat": 20.0},
            {"ds": "2026-05-25", "yhat": 20.0},
            {"ds": "2026-06-01", "yhat": 20.0},
        ],
        "D_DEMANDA0": [
            {"ds": "2026-05-11", "yhat": 0.0},
            {"ds": "2026-05-18", "yhat": 0.0},
        ],
        "E_FILTRADO_CAP": [
            {"ds": "2026-05-11", "yhat": 50.0},
            {"ds": "2026-05-18", "yhat": 50.0},
        ],
        "F_V6_26": [
            {"ds": "2026-05-11", "yhat": 80.0},
            {"ds": "2026-05-18", "yhat": 80.0},
        ],
    }

    stocks_actuales = {
        "A_PROD": 500.0,
        "B_IMP": 200.0,
        "C_SIN_FC": 300.0,
        "D_DEMANDA0": 400.0,
        # E_FILTRADO_CAP: stock_u = 600 * 30 = 18.000 > cap_bodega 10.000 → solo_stock
        "E_FILTRADO_CAP": 600.0,
        "F_V6_26": 250.0,
    }

    ordenes_finales = [
        {
            "sku": "A_PROD",
            "fecha_lanzamiento": "2026-05-13",
            "fecha_entrada_real": "2026-05-14",
            "cantidad_cajas": 150,
            "aprobada": False,
            "numero_of": "OFT-A-001",
            "tipo": "PRODUCCION",
        },
        {
            "sku": "A_PROD",
            "fecha_lanzamiento": "2026-05-25",
            "fecha_entrada_real": "2026-05-26",
            "cantidad_cajas": 200,
            "aprobada": False,
            "numero_of": "OFT-A-002",
            "tipo": "PRODUCCION",
        },
        {
            "sku": "B_IMP",
            "fecha_lanzamiento": "2026-05-11",
            "fecha_entrada_real": "2026-05-18",
            "cantidad_cajas": 80,
            "aprobada": True,  # ya aprobada
            "numero_of": "OF-2026-00050",
            "tipo": "IMPORTACION",
        },
        # Caso V6.26: OFT sugerida con fecha_lanzamiento ANTERIOR a fecha_inicio
        # (lanzamiento ya pasado) y fecha_entrada_real DENTRO del horizonte.
        # El frontend hoy descarta esta entrada → curva azul cae a 0 → rojo.
        # El backend (esta función) DEBE contarla en entradas_sugeridas_cj.
        {
            "sku": "F_V6_26",
            "fecha_lanzamiento": "2026-05-09",   # sábado previo a fecha_inicio=11/05
            "fecha_entrada_real": "2026-05-12",  # martes 12 (1 día después del inicio)
            "cantidad_cajas": 175,
            "aprobada": False,
            "numero_of": "OFT-F-V626",
            "tipo": "PRODUCCION",
        },
    ]

    aprobadas_db = [
        {
            "sku": "B_IMP",
            "fecha_entrada_real": "2026-05-18",
            "semana_necesidad": "2026-05-17",
            "cantidad_real_cj": 80,
            "numero_of": "OF-2026-00050",
        },
    ]

    proy = construir_proyeccion_por_sku(
        ordenes_finales=ordenes_finales,
        aprobadas_db=aprobadas_db,
        sku_params=sku_params,
        forecasts=forecasts,
        stocks_actuales=stocks_actuales,
        fecha_inicio=fecha_inicio,
        horizonte_dias=horizonte_dias,
    )

    # ── Asserts ──
    assert "A_PROD" in proy, "A_PROD debería estar"
    assert proy["A_PROD"]["cobertura"] == "proyeccion_completa", \
        f"A_PROD esperado proyeccion_completa, obtuve {proy['A_PROD']['cobertura']}"
    assert proy["A_PROD"]["stock_inicial_cj"] == 500.0

    assert proy["B_IMP"]["cobertura"] == "solo_stock", \
        f"B_IMP (IMPORTACION) esperado solo_stock"

    assert proy["C_SIN_FC"]["cobertura"] == "sin_proyeccion", \
        f"C_SIN_FC sin forecast esperado sin_proyeccion"
    assert proy["C_SIN_FC"]["semanas"] == []

    assert proy["D_DEMANDA0"]["cobertura"] == "solo_stock", \
        f"D_DEMANDA0 con yhat=0 esperado solo_stock"

    assert proy["E_FILTRADO_CAP"]["cobertura"] == "solo_stock", \
        f"E_FILTRADO_CAP con stock>cap esperado solo_stock"

    # Estructura de semanas para A_PROD
    assert len(proy["A_PROD"]["semanas"]) >= 4, \
        f"A_PROD debería tener al menos 4 semanas, tiene {len(proy['A_PROD']['semanas'])}"

    # Primera semana
    s0 = proy["A_PROD"]["semanas"][0]
    print(f"\nA_PROD primera semana: {s0}")
    assert s0["semana"] == "2026-05-10", f"primera semana debería ser dom 10/05, es {s0['semana']}"
    assert s0["stock_ini_cj"] == 500.0
    # OFT-A-001 entra 14/05 (jueves) → semana viz dom 10/05
    assert s0["entradas_sugeridas_cj"] == 150.0
    assert s0["entradas_aprobadas_cj"] == 0.0
    assert s0["n_ofts_semana"] == 1
    # Stock fin real = 500 + 150 - ventas_sem
    assert s0["stock_fin_cj_visible"] >= 0
    assert s0["stock_fin_cj_real"] == s0["stock_fin_cj_visible"] or s0["stock_fin_cj_real"] < 0

    # B_IMP: aprobada entra 18/05 → semana viz dom 17/05
    s1_imp_idx = next(
        (i for i, s in enumerate(proy["B_IMP"]["semanas"]) if s["semana"] == "2026-05-17"),
        None,
    )
    assert s1_imp_idx is not None, "B_IMP debería tener semana 17/05"
    s_imp = proy["B_IMP"]["semanas"][s1_imp_idx]
    assert s_imp["entradas_aprobadas_cj"] == 80.0
    assert s_imp["entradas_sugeridas_cj"] == 0.0, \
        "B_IMP no debería contar la OFT del plan (ya aprobada) doblemente"

    # ── Test V6.26 (bug del banner amarillo) ──────────────────────────────
    # OFT sugerida con fecha_lanzamiento=09/05 (sábado anterior a fecha_inicio
    # 11/05) y fecha_entrada_real=12/05 (martes, dentro del horizonte).
    # El frontend hoy DESCARTA esta OFT por tener semLanz <= semanaActual.
    # El backend DEBE contarla — el bug se cierra al usar este campo.
    assert "F_V6_26" in proy
    assert proy["F_V6_26"]["cobertura"] == "proyeccion_completa"
    s_v626_0 = proy["F_V6_26"]["semanas"][0]
    assert s_v626_0["semana"] == "2026-05-10", \
        f"F_V6_26 primera semana debería ser dom 10/05, es {s_v626_0['semana']}"
    assert s_v626_0["entradas_sugeridas_cj"] == 175.0, (
        f"BUG V6.26: la OFT con lanzamiento ya pasado (09/05) y entrada en "
        f"horizonte (12/05) DEBE contar como entrada_sugerida_cj. "
        f"Obtuve {s_v626_0['entradas_sugeridas_cj']} (esperado 175.0)."
    )
    assert s_v626_0["n_ofts_semana"] == 1
    assert s_v626_0["entradas_aprobadas_cj"] == 0.0
    print(f"\nF_V6_26 semana 0 (test V6.26): {s_v626_0}")

    print("\nResumen de cobertura:")
    for sku, p in proy.items():
        print(f"  {sku:18s} cobertura={p['cobertura']:22s} "
              f"stock_ini={p['stock_inicial_cj']:>6.1f} "
              f"semanas={len(p['semanas'])}")

    print("\n" + "=" * 60)
    print("Smoke test interno PASÓ ✓")
    print("=" * 60)
