"""
escenarios.py — Escenarios "qué pasaría si" para corridas de VALIDACIÓN del solver (11-11-2026).

Una corrida de validación (análisis programado) corre el plan completo SIN PROMOVER con un
escenario aplicado EN MEMORIA: nunca escribe parámetros en la BD. El escenario llega por la
variable de entorno ESCENARIO_JSON:

  {"batch_min_u":  {"251010255": 3000},                         # palanca 1: batch mínimo
   "horas_extra":  {"Doypack": {"desde": "2026-11-12", "hasta": "2026-12-03", "horas": 1.6}},
                                                                # palanca 2: horas extra por día hábil
   "sku_lineas_extra": [{"sku": "251010255", "linea": "Doypack 4"}]}   # palanca 3: línea alternativa

Lo aplican mrp.load_params_from_db (batch y horas extra) y optimizer (pares SKU-línea, que el
solver lee directo de la BD). Todo queda en el log con el prefijo [ESCENARIO].
"""
import json
import logging
import os
from datetime import date, timedelta

log = logging.getLogger("escenarios")


def leer_escenario() -> dict:
    raw = os.environ.get("ESCENARIO_JSON")
    if not raw:
        return {}
    try:
        esc = json.loads(raw)
        return esc if isinstance(esc, dict) else {}
    except Exception as e:
        log.error(f"[ESCENARIO] ESCENARIO_JSON inválido: {e}")
        return {}


def aplicar_mrp(sku_params: dict, lineas: dict) -> list:
    """Batch mínimo y horas extra (como excepciones del día = horas base + extra). Devuelve
    la lista de cambios aplicados (para el log)."""
    esc = leer_escenario()
    if not esc:
        return []
    import calendario as _cal
    hechos = []
    for sku, u in (esc.get("batch_min_u") or {}).items():
        sp = sku_params.get(sku)
        if sp is not None:
            ant = getattr(sp, "batch_minimo", None)
            sp.batch_minimo = int(u)
            hechos.append(f"batch {sku}: {ant} -> {int(u)}")
    for cod, he in (esc.get("horas_extra") or {}).items():
        L = lineas.get(cod)
        if L is None:
            continue
        d = date.fromisoformat(he["desde"])
        h = date.fromisoformat(he["hasta"])
        extra = float(he.get("horas") or 0)
        exc = dict(L.excepciones or {})
        n = 0
        while d <= h:
            base = _cal.horas_linea_dia(d, L.horas_turno, L.turnos_dia, L.turnos_config, L.excepciones)
            if base > 0:
                exc[d] = min(24.0, base + extra)
                n += 1
            d += timedelta(days=1)
        L.excepciones = exc
        hechos.append(f"horas extra {cod}: +{extra:g} h en {n} días hábiles ({he['desde']} a {he['hasta']})")
    for h_ in hechos:
        log.info(f"[ESCENARIO] {h_}")
    return hechos


def aplicar_sku_lineas(sku_lineas_rich: list, lineas_validas) -> list:
    """Agrega pares SKU-línea alternativos (factor 1, no preferida, setup igual al de su
    línea preferida)."""
    esc = leer_escenario()
    extra = esc.get("sku_lineas_extra") or []
    hechos = []
    existentes = {(x["sku"], x["linea"]) for x in sku_lineas_rich}
    for p in extra:
        sku, lin = p.get("sku"), p.get("linea")
        if not sku or lin not in lineas_validas or (sku, lin) in existentes:
            continue
        pref = next((x for x in sku_lineas_rich if x["sku"] == sku and x.get("preferida")), None)
        sku_lineas_rich.append({"sku": sku, "linea": lin, "t_cambio_hrs": float((pref or {}).get("t_cambio_hrs", 0.5)),
                                "preferida": False, "factor_velocidad": float(p.get("factor_velocidad", 1.0))})
        hechos.append(f"línea alternativa {sku} -> {lin}")
    for h_ in hechos:
        log.info(f"[ESCENARIO] {h_}")
    return hechos
