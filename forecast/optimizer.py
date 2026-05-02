"""
optimizer.py — Optimizador CP-SAT diario para planificación de producción.

v1.2 — Modelo diario con variables en CAJAS (reemplaza modelo semanal de v1.1)

Características clave:
  - Variables cajas[d,k,l] por día / SKU / línea (decisión natural en cajas)
  - prod_unidades[d,k,l] = u_por_caja[k] × cajas[d,k,l] (para restricciones de capacidad)
  - Setup pagado solo en primer día de corrida (vía variable inicio[d,k,l])
  - Múltiples SKUs por línea-día permitidos (cap. agregada línea-día)
  - Capacidad respeta calendario real (feriados/findes con cap=0)
  - Solo SKUs tipo PRODUCCION; importación pasa sin tocar (con fecha lunes)
  - Variables solo para pares SKU-Línea válidos (mrp_sku_lineas)
  - Stock como IntVar con cota inferior negativa; déficit penalizado
  - SS dinámico diario: SS = demanda_diaria × ss_dias

Pesos del objetivo (v1.2):
  W_DEFICIT  = 100.000   penalizar stock < SS
  W_EXCESO   =  50.000   penalizar stock > cap_bodega
  W_URGENTE  =  10.000   priorizar SKUs con stock crítico
  W_SETUP    =       0   v1.3: desactivado en N1 — N2 (sequencer.py) optimiza
                          setups con matriz SKU→SKU real (R9). Constante
                          conservada para rollback rápido.
  W_ALT      =      50   preferir línea preferida vs alternativa

Firma pública preservada de v1.1: optimizar_plan(plan_mrp, ...)
"""

from datetime import date, timedelta
from typing import Any
from ortools.sat.python import cp_model

# Calendario (módulo nuevo v1.2)
from calendario import (
    es_habil,
    capacidad_dia_unidades,
    distribuir_forecast_a_diario,
    generar_horizonte_diario,
    semana_iso_inicio,
)


# =============================================================================
# Configuración
# =============================================================================

# Pesos de la función objetivo
# v1.2: W_SLACK reemplazado por W_SETUP — penalizamos cada inicio de corrida
# para incentivar consolidar producción y minimizar cambios de SKU.
# El comportamiento "llenar líneas" emerge naturalmente del SS y la cap. de bodega.
W_DEFICIT = 100_000
W_EXCESO = 50_000
W_URGENTE = 10_000
W_SETUP = 0        # v1.3: ya no se usa en N1 — N2 optimizará setups con matriz real (R9).
                   # Conservada para rollback rápido o experimentos (e.g. W_SETUP=20).
W_ALT = 50         # penaliza usar línea alternativa

# v1.3 — Restricción de Nivel 1 (lot sizing).
# Acota cuántos SKUs distintos puede asignar el optimizador a una misma
# línea-día. Esto contiene el problema combinatorio que enfrenta el Nivel 2
# (sequencer.py): N≤4 por (línea, día) garantiza sub-problemas tratables
# en milisegundos. Decisión cerrada en sesión de diseño v1.3 (R2).
N_MAX_SKUS_DIA_LINEA = 4

# Solver
SOLVER_TIME_LIMIT_SEC = 60   # piloto. Subir a 180-300 para 471 SKUs
SOLVER_NUM_WORKERS = 4

# Escala entera para evitar floats en CP-SAT (factor_velocidad por SKU-Línea).
# costo_unidad_escalado[s,l] = round(FACTOR_ESCALA / factor_sl[s,l]).
# cap_dia_escalada[d,l]      = cap_dia_nominal[d,l] × FACTOR_ESCALA.
# Mientras mayor sea, más precisión pero números más grandes (CP-SAT tolera
# enteros hasta ~2^63). 1000 da 3 decimales de precisión, suficiente para
# factores reales (típicamente 0.5-1.0 con 2 decimales).
FACTOR_ESCALA = 1000

# Cota inferior del stock (debe ser suficientemente negativa para no truncar
# escenarios de quiebre temporales). Empíricamente -10×cap_bodega es seguro.
STOCK_LOWER_BOUND_FACTOR = 10

# Horizonte por defecto
HORIZONTE_DIAS_DEFAULT = 42  # 6 semanas


# =============================================================================
# Estructuras intermedias
# =============================================================================

class _ModeloCPSAT:
    """Contenedor de variables y referencias del modelo CP-SAT en construcción.

    v1.2: la variable principal es `cajas` (no `prod`/unidades). `prod_u` es
    derivada lineal: prod_u[d,k,l] = u_por_caja[k] × cajas[d,k,l]. Esto reduce
    el espacio de búsqueda en factor u_por_caja (10-30×) y garantiza que toda
    OF sea múltiplo de la caja sin restricción adicional.

    v1.2.1: factor_velocidad por par SKU-Línea. La capacidad efectiva de
    producción de un SKU en una línea es `velocidad_linea × factor`. Para
    mantener todo entero en CP-SAT, escalamos por FACTOR_ESCALA=1000:
        costo_caja_escalado[s,l] = round(1000 / factor_sl[s,l]) × u_por_caja[s]
        cap_dia_escalada[d,l] = cap_dia_linea_nominal[d,l] × 1000
    El setup_u[s,l] NO se escala por factor (decisión: el setup es tiempo
    físico de línea, sin importar SKU siguiente).
    """

    def __init__(self):
        self.model: cp_model.CpModel = cp_model.CpModel()
        # Variables de decisión
        self.cajas: dict[tuple[date, str, str], cp_model.IntVar] = {}
        self.asig: dict[tuple[date, str, str], cp_model.IntVar] = {}
        self.inicio: dict[tuple[date, str, str], cp_model.IntVar] = {}
        # Variables de estado
        self.stock_u: dict[tuple[date, str], cp_model.IntVar] = {}      # en unidades
        self.deficit: dict[tuple[date, str], cp_model.IntVar] = {}      # bajo SS, en unidades
        self.exceso: dict[tuple[date, str], cp_model.IntVar] = {}       # sobre cap_bodega, en unidades
        # Referencias para post-proceso
        self.skus: list[str] = []
        self.lineas: list[str] = []
        self.fechas: list[date] = []
        self.pares_sku_linea: dict[str, list[str]] = {}
        self.u_por_caja: dict[str, int] = {}                            # cache
        self.setup_u: dict[tuple[str, str], int] = {}                   # cache (u eqv. línea)
        self.factor: dict[tuple[str, str], float] = {}                  # cache factor_velocidad


# =============================================================================
# Función pública
# =============================================================================

def optimizar_plan_v12_rich(
    plan_mrp: dict[str, Any],
    sku_params: dict[str, dict],
    lineas_params: dict[str, dict],
    sku_lineas: list[dict],
    forecast_semanal: dict[str, dict[date, float]],
    stock_inicial: dict[str, float],
    entradas_aprobadas: dict[str, list[dict]],
    fecha_inicio: date | None = None,
    horizonte_dias: int = HORIZONTE_DIAS_DEFAULT,
) -> dict[str, Any]:
    """
    [API rica v1.2 — uso interno y testing]

    Optimiza el plan de producción a nivel diario y devuelve estructura rica:
        - OFTs con fecha_lanzamiento, fecha_entrada_real, cajas, paga_setup
        - stock_diario por SKU/fecha
        - alertas (QUIEBRE, BAJO_SS, EXCESO_BODEGA)
        - uso_linea por línea/fecha
        - resumen agregado

    Para integración con main.py usar `optimizar_plan(...)` (wrapper legacy).
    """
    if fecha_inicio is None:
        fecha_inicio = date.today()

    horizonte = generar_horizonte_diario(fecha_inicio, horizonte_dias)
    fecha_fin = horizonte[-1]

    # ─── 1. Filtrar SKUs que entran al modelo ────────────────────────────────
    skus_produccion = [
        sku for sku, params in sku_params.items()
        if params.get("tipo", "").upper() == "PRODUCCION"
    ]

    # Excluir SKUs sin demanda en el horizonte (decisión 9)
    skus_activos = []
    for sku in skus_produccion:
        forecast_sku = forecast_semanal.get(sku, {})
        total_demanda = sum(forecast_sku.values())
        if total_demanda > 0:
            skus_activos.append(sku)

    if not skus_activos:
        return _resultado_vacio("Sin SKUs de producción con demanda en horizonte")

    # ─── 2. Construir mapa SKU -> líneas válidas ─────────────────────────────
    sku_a_lineas: dict[str, list[dict]] = {}
    for entry in sku_lineas:
        s = entry["sku"]
        if s not in skus_activos:
            continue
        sku_a_lineas.setdefault(s, []).append(entry)

    # SKUs sin línea asignada se excluyen con warning (no debería pasar si BD está OK)
    skus_sin_linea = [s for s in skus_activos if s not in sku_a_lineas]
    if skus_sin_linea:
        print(f"[optimizer] WARN: SKUs sin línea en mrp_sku_lineas: {skus_sin_linea}")
    skus_modelo = [s for s in skus_activos if s in sku_a_lineas]

    if not skus_modelo:
        return _resultado_vacio("Ningún SKU activo tiene línea asignada en mrp_sku_lineas")

    # ─── 3. Demanda diaria (forecast distribuido) ────────────────────────────
    demanda_diaria: dict[str, dict[date, float]] = {}
    for sku in skus_modelo:
        demanda_diaria[sku] = distribuir_forecast_a_diario(
            forecast_semanal.get(sku, {}),
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )

    # ─── 4. Capacidad por línea-día ──────────────────────────────────────────
    cap_dia: dict[tuple[date, str], int] = {}
    for d in horizonte:
        for cod_linea, lp in lineas_params.items():
            cap_dia[(d, cod_linea)] = capacidad_dia_unidades(
                fecha=d,
                velocidad_u_hr=lp.get("velocidad_u_hr", 0),
                horas_turno=lp.get("horas_turno", 8),
                turnos_dia=lp.get("turnos_dia", 1),
            )

    # ─── 5. Construir modelo CP-SAT ──────────────────────────────────────────
    m = _construir_modelo(
        horizonte=horizonte,
        skus=skus_modelo,
        sku_params=sku_params,
        lineas_params=lineas_params,
        sku_a_lineas=sku_a_lineas,
        demanda_diaria=demanda_diaria,
        cap_dia=cap_dia,
        stock_inicial=stock_inicial,
        entradas_aprobadas=entradas_aprobadas,
    )

    # ─── 6. Función objetivo ─────────────────────────────────────────────────
    _agregar_objetivo(m, sku_params=sku_params, lineas_params=lineas_params,
                      cap_dia=cap_dia, sku_a_lineas=sku_a_lineas)

    # ─── 7. Resolver ─────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SEC
    solver.parameters.num_search_workers = SOLVER_NUM_WORKERS
    status = solver.Solve(m.model)
    status_name = solver.StatusName(status)
    solver_time = solver.WallTime()

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _resultado_vacio(
            f"Solver no encontró solución factible: status={status_name}",
            status=status_name, solver_time_sec=solver_time,
        )

    # ─── 8. Post-procesar a OFTs y stock visible ─────────────────────────────
    return _post_procesar(
        m=m, solver=solver,
        horizonte=horizonte, sku_params=sku_params, lineas_params=lineas_params,
        sku_a_lineas=sku_a_lineas, cap_dia=cap_dia,
        status_name=status_name, solver_time_sec=solver_time,
        objective_value=solver.ObjectiveValue(),
    )


# =============================================================================
# Construcción del modelo
# =============================================================================

def _construir_modelo(
    horizonte: list[date],
    skus: list[str],
    sku_params: dict[str, dict],
    lineas_params: dict[str, dict],
    sku_a_lineas: dict[str, list[dict]],
    demanda_diaria: dict[str, dict[date, float]],
    cap_dia: dict[tuple[date, str], int],
    stock_inicial: dict[str, float],
    entradas_aprobadas: dict[str, list[dict]],
) -> _ModeloCPSAT:
    """Construye variables y restricciones del modelo CP-SAT con variables en cajas."""

    m = _ModeloCPSAT()
    m.skus = skus
    m.fechas = horizonte
    m.lineas = list(lineas_params.keys())
    m.pares_sku_linea = {s: [e["linea"] for e in sku_a_lineas[s]] for s in skus}

    # Cache: u_por_caja por SKU, setup_unidades por par SKU-Línea, factor_velocidad
    for s in skus:
        upc = int(sku_params[s].get("u_por_caja", 1) or 1)
        m.u_por_caja[s] = max(upc, 1)
        for entry in sku_a_lineas[s]:
            l = entry["linea"]
            t_cambio = entry.get("t_cambio_hrs", 0.0) or 0.0
            vel = lineas_params[l].get("velocidad_u_hr", 0) or 0
            # Setup en unidades de línea (decisión: NO escala por factor_velocidad)
            m.setup_u[(s, l)] = int(t_cambio * vel)
            # Factor de velocidad del SKU en esta línea
            f = float(entry.get("factor_velocidad", 1.0) or 1.0)
            m.factor[(s, l)] = f if f > 0 else 1.0

    # ─── Variables ───────────────────────────────────────────────────────────

    for d_idx, d in enumerate(horizonte):
        for s in skus:
            cap_bodega = int(sku_params[s].get("cap_bodega_u", 1_000_000) or 1_000_000)
            stock_low = -STOCK_LOWER_BOUND_FACTOR * cap_bodega
            # FIX v1.2.2: la cota superior de def_/exceso debe ser mucho mayor que cap_bodega
            # porque SS_dinámico = demanda_diaria × ss_dias puede ser muchas veces la cap_bodega
            # cuando ss_dias es alto (10-30) y la demanda diaria es comparable a cap_bodega/30.
            # Usamos un upper bound generoso: 100 × cap_bodega cubre todos los escenarios reales.
            stock_high = 2 * cap_bodega
            big_ub = 100 * cap_bodega
            m.stock_u[(d, s)] = m.model.NewIntVar(stock_low, stock_high, f"stock_{d_idx}_{s}")
            m.deficit[(d, s)] = m.model.NewIntVar(0, big_ub, f"def_{d_idx}_{s}")
            m.exceso[(d, s)] = m.model.NewIntVar(0, big_ub, f"exc_{d_idx}_{s}")

            for l in m.pares_sku_linea[s]:
                cap_l_d = cap_dia[(d, l)]
                upc = m.u_por_caja[s]
                f = m.factor[(s, l)]
                # Cota superior en cajas considerando factor:
                #   max_unidades = cap_l_d × factor   (cuántas u del SKU caben en la línea)
                #   max_cajas    = max_unidades / u_por_caja
                cajas_max = int((cap_l_d * f) // upc) if cap_l_d > 0 else 0
                m.cajas[(d, s, l)] = m.model.NewIntVar(0, cajas_max, f"cajas_{d_idx}_{s}_{l}")
                m.asig[(d, s, l)] = m.model.NewBoolVar(f"asig_{d_idx}_{s}_{l}")
                m.inicio[(d, s, l)] = m.model.NewBoolVar(f"inicio_{d_idx}_{s}_{l}")

    # ─── Restricciones por (d, s, l) ─────────────────────────────────────────

    for d_idx, d in enumerate(horizonte):
        for s in skus:
            sp = sku_params[s]
            upc = m.u_por_caja[s]
            # Batch mínimo en cajas (Opción 1: ceil para no violar el mínimo)
            batch_min_u = int(sp.get("batch_min_u", 0) or 0)
            batch_min_cajas = -(-batch_min_u // upc) if batch_min_u > 0 else 0  # ceil division

            for l in m.pares_sku_linea[s]:
                cajas_v = m.cajas[(d, s, l)]
                asig = m.asig[(d, s, l)]
                inicio = m.inicio[(d, s, l)]
                cap_l_d = cap_dia[(d, l)]

                # Capacidad individual: cajas × upc ≤ cap_dia × asig
                # (laxa, solo apaga producción si asig=0; la cap real está en R1a agregada)
                m.model.Add(upc * cajas_v <= cap_l_d * asig)

                # Batch mínimo en cajas (si hay asignación)
                if batch_min_cajas > 0:
                    m.model.Add(cajas_v >= batch_min_cajas * asig)

                # NOTA: ya no hay restricción de batch_mult_u — al trabajar en cajas
                # la producción es múltiplo de u_por_caja por construcción. Si
                # batch_mult_u > u_por_caja y existe lógica adicional, agregar aquí.

                # Día no hábil → asig=0, inicio=0
                if cap_l_d == 0:
                    m.model.Add(asig == 0)
                    m.model.Add(inicio == 0)

                # Detección de inicio
                if d_idx == 0:
                    # Día 0 paga siempre setup si hay asignación
                    m.model.Add(inicio == asig)
                else:
                    asig_prev = m.asig[(horizonte[d_idx - 1], s, l)]
                    m.model.Add(inicio >= asig - asig_prev)
                    m.model.Add(inicio <= asig)

    # ─── Restricciones agregadas por (d, l) ──────────────────────────────────

    for d_idx, d in enumerate(horizonte):
        for l in m.lineas:
            cap_l_d = cap_dia[(d, l)]
            if cap_l_d == 0:
                continue

            # R1a: Capacidad agregada línea-día con factor_velocidad
            # ----------------------------------------------------------------
            # Razonamiento físico:
            #   "horas consumidas por SKU s en línea l" = u_producidas / (vel × factor)
            #   Σ_k horas_consumidas[k] + Σ_k inicio[k] × t_cambio[k]  ≤  horas_dia[l]
            #
            # Multiplicando ambos lados por (vel × FACTOR_ESCALA):
            #   Σ_k (u[k,l] × FACTOR_ESCALA / factor[k,l])
            # + Σ_k (inicio[k,l] × t_cambio[k,l] × vel × FACTOR_ESCALA)
            #   ≤  cap_dia[d,l] × FACTOR_ESCALA
            #
            # Donde u[k,l] = u_por_caja[k] × cajas[d,k,l].
            # Pre-calculamos costo_caja_escalado[s,l] = round(FACTOR_ESCALA / factor) × upc.
            # ----------------------------------------------------------------
            terms = []
            for s in m.skus:
                if l not in m.pares_sku_linea[s]:
                    continue
                upc = m.u_por_caja[s]
                f = m.factor[(s, l)]
                # Costo en "unidades-escala-línea" por caja del SKU:
                costo_caja = int(round(FACTOR_ESCALA / f)) * upc
                terms.append(costo_caja * m.cajas[(d, s, l)])
                stp = m.setup_u[(s, l)]
                if stp > 0:
                    # Setup en "unidades-escala-línea": t_cambio × vel × FACTOR_ESCALA
                    terms.append(stp * FACTOR_ESCALA * m.inicio[(d, s, l)])
            if terms:
                m.model.Add(sum(terms) <= cap_l_d * FACTOR_ESCALA)

            # R1b (v1.3, R2): cap. de nº de SKUs distintos asignados a esta línea-día.
            # N1 acota Σ_k asig[d,k,l] ≤ 4 para que el sub-problema de N2
            # (sequencer.py) sea siempre pequeño. Solo SKUs que tienen esta
            # línea como par válido contribuyen a la suma.
            asigs_dl = [
                m.asig[(d, s, l)]
                for s in m.skus
                if l in m.pares_sku_linea[s]
            ]
            if asigs_dl:
                m.model.Add(sum(asigs_dl) <= N_MAX_SKUS_DIA_LINEA)

    # ─── Restricciones por (d, s) ────────────────────────────────────────────

    for d_idx, d in enumerate(horizonte):
        for s in skus:
            sp = sku_params[s]
            upc = m.u_por_caja[s]
            cap_bodega = int(sp.get("cap_bodega_u", 1_000_000) or 1_000_000)
            ss_dias = int(sp.get("ss_dias", 0) or 0)

            # Balance de stock (en unidades)
            entrada_d = _entradas_del_dia(s, d, entradas_aprobadas)
            demanda_d = int(round(demanda_diaria[s].get(d, 0.0)))
            prod_u_total_d = sum(
                upc * m.cajas[(d, s, l)] for l in m.pares_sku_linea[s]
            )

            if d_idx == 0:
                stock_prev_val = int(round(stock_inicial.get(s, 0)))
                m.model.Add(
                    m.stock_u[(d, s)] == stock_prev_val + prod_u_total_d + entrada_d - demanda_d
                )
            else:
                stock_prev = m.stock_u[(horizonte[d_idx - 1], s)]
                m.model.Add(
                    m.stock_u[(d, s)] == stock_prev + prod_u_total_d + entrada_d - demanda_d
                )

            # Déficit bajo SS (en unidades, SS dinámico = demanda × ss_dias)
            ss_d = demanda_d * ss_dias
            m.model.Add(m.deficit[(d, s)] >= ss_d - m.stock_u[(d, s)])

            # Exceso sobre cap_bodega (en unidades)
            m.model.Add(m.exceso[(d, s)] >= m.stock_u[(d, s)] - cap_bodega)

            # Una línea por SKU por día
            asigs_s_d = [m.asig[(d, s, l)] for l in m.pares_sku_linea[s]]
            if len(asigs_s_d) > 1:
                m.model.Add(sum(asigs_s_d) <= 1)

    return m


# =============================================================================
# Función objetivo
# =============================================================================

def _agregar_objetivo(
    m: _ModeloCPSAT,
    sku_params: dict[str, dict],
    lineas_params: dict[str, dict],
    cap_dia: dict[tuple[date, str], int],
    sku_a_lineas: dict[str, list[dict]],
) -> None:
    """Añade la función objetivo multi-criterio al modelo.

    v1.2: penalizamos cada inicio de corrida (W_SETUP) en vez del slack mal
    formulado de v1.0. Esto incentiva consolidar producción naturalmente.
    """

    obj_terms = []

    # Penalizar déficit bajo SS
    for (d, s), v in m.deficit.items():
        obj_terms.append(W_DEFICIT * v)

    # Penalizar exceso sobre cap bodega
    for (d, s), v in m.exceso.items():
        obj_terms.append(W_EXCESO * v)

    # Penalizar asignación a línea alternativa (preferir la preferida)
    pref_map: dict[tuple[str, str], bool] = {}
    for s, entries in sku_a_lineas.items():
        for e in entries:
            pref_map[(s, e["linea"])] = bool(e.get("preferida", False))
    for (d, s, l), asig in m.asig.items():
        if not pref_map.get((s, l), True):
            # Es alternativa → penalizamos suavemente
            obj_terms.append(W_ALT * asig)

    m.model.Minimize(sum(obj_terms))


# =============================================================================
# Helpers
# =============================================================================

def _entradas_del_dia(sku: str, fecha: date, entradas_aprobadas: dict[str, list[dict]]) -> int:
    """Suma las entradas aprobadas de un SKU para una fecha específica."""
    total = 0
    for e in entradas_aprobadas.get(sku, []):
        f_ent = e.get("fecha_entrada")
        if isinstance(f_ent, str):
            # Parseo defensivo si viene como string ISO
            try:
                f_ent = date.fromisoformat(f_ent[:10])
            except ValueError:
                continue
        if f_ent == fecha:
            total += int(e.get("cantidad_u", 0) or 0)
    return total


def _resultado_vacio(mensaje: str, status: str = "EMPTY",
                     solver_time_sec: float = 0.0) -> dict[str, Any]:
    return {
        "status": status,
        "objective_value": None,
        "solver_time_sec": solver_time_sec,
        "ofts": [],
        "stock_diario": {},
        "alertas": [{"tipo": "INFO", "mensaje": mensaje}],
        "uso_linea": {},
        "resumen": {"mensaje": mensaje},
    }


# =============================================================================
# Post-procesamiento
# =============================================================================

def _post_procesar(
    m: _ModeloCPSAT,
    solver: cp_model.CpSolver,
    horizonte: list[date],
    sku_params: dict[str, dict],
    lineas_params: dict[str, dict],
    sku_a_lineas: dict[str, list[dict]],
    cap_dia: dict[tuple[date, str], int],
    status_name: str,
    solver_time_sec: float,
    objective_value: float,
) -> dict[str, Any]:
    """Convierte la solución del solver en OFTs, stock visible y alertas."""

    ofts: list[dict] = []
    stock_diario: dict[str, dict[str, int]] = {}
    alertas: list[dict] = []
    uso_linea: dict[str, dict[str, float]] = {l: {} for l in m.lineas}

    # ─── OFTs (una por día con producción) ──────────────────────────────────
    for d in horizonte:
        for s in m.skus:
            sp = sku_params[s]
            upc = m.u_por_caja[s]
            lt_dias = int(round((sp.get("lead_time_sem", 0) or 0) * 7))
            for l in m.pares_sku_linea[s]:
                cajas_v = solver.Value(m.cajas[(d, s, l)])
                if cajas_v <= 0:
                    continue
                cant_u = cajas_v * upc
                paga_setup = bool(solver.Value(m.inicio[(d, s, l)]))
                # setup_u[(s,l)] ya está cacheado como int(t_cambio_hrs * vel)
                # (sin escalar por factor_velocidad — regla 5 v1.2)
                setup_u_val = m.setup_u.get((s, l), 0) if paga_setup else 0
                ofts.append({
                    "sku": s,
                    "linea": l,
                    "fecha_lanzamiento": d.isoformat(),
                    "fecha_entrada_real": (d + timedelta(days=lt_dias)).isoformat(),
                    "cantidad_cajas": cajas_v,
                    "cantidad_unidades": cant_u,
                    "u_por_caja": upc,
                    "paga_setup": paga_setup,
                    "setup_unidades": setup_u_val,
                    "aprobada": False,
                    "numero_of": None,
                    "motivo": "OFT",
                })

    # ─── Stock visible y alertas ─────────────────────────────────────────────
    for s in m.skus:
        stock_diario[s] = {}
        sp = sku_params[s]
        upc = m.u_por_caja[s]
        cap_bodega = int(sp.get("cap_bodega_u", 1_000_000) or 1_000_000)

        for d in horizonte:
            stock_real = solver.Value(m.stock_u[(d, s)])
            stock_visible = max(0, stock_real)
            stock_diario[s][d.isoformat()] = stock_visible

            deficit_v = solver.Value(m.deficit[(d, s)])
            exceso_v = solver.Value(m.exceso[(d, s)])

            # Alerta de quiebre (stock real negativo)
            if stock_real < 0:
                alertas.append({
                    "sku": s,
                    "fecha": d.isoformat(),
                    "tipo": "QUIEBRE",
                    "mensaje": f"Demanda no cubierta: {-stock_real} unidades",
                    "deficit_u": -stock_real,
                })
            elif deficit_v > 0:
                alertas.append({
                    "sku": s,
                    "fecha": d.isoformat(),
                    "tipo": "BAJO_SS",
                    "mensaje": f"Stock {stock_real} u bajo SS ({deficit_v} u faltantes)",
                    "deficit_u": deficit_v,
                })

            if exceso_v > 0:
                alertas.append({
                    "sku": s,
                    "fecha": d.isoformat(),
                    "tipo": "EXCESO_BODEGA",
                    "mensaje": f"Stock {stock_real} u excede cap. bodega ({exceso_v} u sobre cap)",
                    "deficit_u": exceso_v,
                })

    # ─── Uso de líneas ───────────────────────────────────────────────────────
    for d in horizonte:
        for l in m.lineas:
            cap_l_d = cap_dia[(d, l)]
            if cap_l_d == 0:
                uso_linea[l][d.isoformat()] = 0.0
                continue
            # Ocupación en "unidades equivalentes a velocidad nominal de línea":
            #   u_eqv = u_producidas_sku / factor_sl   (producir con factor<1 consume más tiempo)
            ocupado = 0.0
            for s in m.skus:
                if l not in m.pares_sku_linea[s]:
                    continue
                upc = m.u_por_caja[s]
                f = m.factor[(s, l)]
                cajas_v = solver.Value(m.cajas[(d, s, l)])
                ocupado += (upc * cajas_v) / f
                if solver.Value(m.inicio[(d, s, l)]):
                    # Setup ya está en u-eqv-línea (no escala por factor)
                    ocupado += m.setup_u.get((s, l), 0)
            uso_linea[l][d.isoformat()] = round(100 * ocupado / cap_l_d, 1)

    # ─── Resumen ─────────────────────────────────────────────────────────────
    n_quiebres = sum(1 for a in alertas if a["tipo"] == "QUIEBRE")
    n_bajo_ss = sum(1 for a in alertas if a["tipo"] == "BAJO_SS")
    n_exceso = sum(1 for a in alertas if a["tipo"] == "EXCESO_BODEGA")
    uso_promedio_lineas = {
        l: round(sum(usos.values()) / len(usos), 1) if usos else 0.0
        for l, usos in uso_linea.items()
    }

    resumen = {
        "horizonte_dias": len(horizonte),
        "fecha_inicio": horizonte[0].isoformat(),
        "fecha_fin": horizonte[-1].isoformat(),
        "skus_optimizados": len(m.skus),
        "lineas_consideradas": len(m.lineas),
        "ofts_generadas": len(ofts),
        "alertas_quiebre": n_quiebres,
        "alertas_bajo_ss": n_bajo_ss,
        "alertas_exceso_bodega": n_exceso,
        "uso_promedio_lineas_pct": uso_promedio_lineas,
    }

    return {
        "status": status_name,
        "objective_value": objective_value,
        "solver_time_sec": solver_time_sec,
        "ofts": ofts,
        "stock_diario": stock_diario,
        "alertas": alertas,
        "uso_linea": uso_linea,
        "resumen": resumen,
    }


# =============================================================================
# Wrapper LEGACY — firma compatible con v1.1 / main.py
# =============================================================================

def optimizar_plan(
    ordenes_mrp: list,
    sku_params: dict,
    lineas: dict,
    forecasts: dict,
    stocks_actuales: dict,
    entradas_fijas: dict | None = None,
    horizonte_semanas: int = 13,
) -> tuple[list[dict], dict]:
    """
    [API pública / legacy] Optimiza el plan de producción y devuelve órdenes
    en el formato esperado por main.py / frontend.

    Esta función traduce los formatos del MRP clásico (cajas, listas de forecast,
    objetos SKUParams) al formato rico v1.2 (unidades, dicts, fechas), llama al
    optimizador diario, y traduce las OFTs ricas a órdenes legacy.

    Mantiene la firma exacta de v1.1 para drop-in replacement en main.py.

    Args:
        ordenes_mrp: lista de órdenes generadas por MRP clásico (incluye PRODUCCION
            e IMPORTACION). Las de IMPORTACION se preservan; las de PRODUCCION se
            REEMPLAZAN por las del optimizador.
        sku_params: dict {sku: SKUParams} — parámetros del MRP (cajas, lead_time_semanas, ...)
        lineas: dict {codigo: LineaProduccion}
        forecasts: dict {sku: [{ds, yhat}, ...]} — forecast en CAJAS por semana (Prophet)
        stocks_actuales: dict {sku: stock_actual_cajas}
        entradas_fijas: dict {sku: [{fecha_entrada, cantidad_cajas, numero_of, aprobada}, ...]}
        horizonte_semanas: nominal del MRP (se traduce a días con × 7)

    Returns:
        (ordenes_finales, diag_opt)
        - ordenes_finales: lista de dicts con campos:
            sku, descripcion, tipo, semana_necesidad, semana_emision,
            fecha_lanzamiento, fecha_entrada_real,
            cantidad_cajas, cantidad_unidades, linea, motivo, alerta,
            stock_inicial_cajas, stock_final_cajas, forecast_cajas, ss_cajas,
            tiene_alerta, lead_time_sem, paga_setup, aprobada
        - diag_opt: dict {optimizado, status, tiempo_ms, ofts_generadas, alertas, ...}
    """
    import logging
    logger = logging.getLogger("optimizer")

    if entradas_fijas is None:
        entradas_fijas = {}

    # ─── 1. Separar PRODUCCION de IMPORTACION ────────────────────────────────
    # Preservar IMPORTACION tal cual (con fecha_lanzamiento = lunes de su semana)
    ordenes_importacion = []
    for o in ordenes_mrp:
        sku = o.get("sku") if isinstance(o, dict) else getattr(o, "sku", "")
        sp = sku_params.get(sku)
        tipo = (
            sp.tipo if (sp and hasattr(sp, "tipo"))
            else (o.get("tipo", "PRODUCCION") if isinstance(o, dict) else "PRODUCCION")
        )
        if tipo and tipo.upper() != "PRODUCCION":
            o_dict = _orden_a_dict(o)
            # Aseguramos fecha_lanzamiento = lunes ISO de la semana_emision (decisión 2)
            if o_dict.get("semana_emision"):
                o_dict["fecha_lanzamiento"] = _a_lunes_iso(o_dict["semana_emision"])
            if o_dict.get("semana_necesidad"):
                o_dict["fecha_entrada_real"] = _a_lunes_iso(o_dict["semana_necesidad"])
            o_dict["paga_setup"] = False
            o_dict["setup_unidades"] = 0
            ordenes_importacion.append(o_dict)

    # ─── 2. Traducir parámetros legacy → formato rich v1.2 ───────────────────
    sku_params_rich = {}
    for sku, sp in sku_params.items():
        # sp es objeto SKUParams (dataclass). Traducir a dict con llaves rich.
        sku_params_rich[sku] = {
            "tipo": _attr(sp, "tipo", "PRODUCCION"),
            "u_por_caja": int(_attr(sp, "unidades_por_caja", 1) or 1),
            "lead_time_sem": float(_attr(sp, "lead_time_semanas", 1) or 1),
            "ss_dias": int(_attr(sp, "stock_seguridad_dias", 0) or 0),
            "batch_min_u": int(_attr(sp, "batch_minimo", 0) or 0),
            "batch_mult_u": int(_attr(sp, "multiplo_batch", 1) or 1),
            "cap_bodega_u": int(_attr(sp, "cap_bodega", 1_000_000) or 1_000_000),
            "linea_preferida": _attr(sp, "linea_preferida", ""),
            "descripcion": _attr(sp, "descripcion", ""),
        }

    lineas_params_rich = {}
    for cod, ln in lineas.items():
        lineas_params_rich[cod] = {
            "velocidad_u_hr": float(_attr(ln, "velocidad_u_hr", 0) or 0),
            "horas_turno": float(_attr(ln, "horas_turno", 8) or 8),
            "turnos_dia": int(_attr(ln, "turnos_dia", 1) or 1),
            "nombre": _attr(ln, "nombre", ""),
        }

    # ─── 3. sku_lineas — leerlas desde la BD (preferida + alternativas) ──────
    sku_lineas_rich = []
    try:
        from db_mrp import get_all_sku_lineas
        for r in get_all_sku_lineas():
            sku_lineas_rich.append({
                "sku": r["sku"],
                "linea": r["linea"],
                "t_cambio_hrs": float(r.get("t_cambio_hrs", 0) or 0),
                "preferida": bool(r.get("preferida", False)),
                "factor_velocidad": float(r.get("factor_velocidad", 1.0) or 1.0),
            })
    except Exception as e:
        logger.warning(f"[optimizer] No pude leer mrp_sku_lineas: {e}")

    # Si la BD no tiene mrp_sku_lineas pobladas, fallback a línea_preferida
    if not sku_lineas_rich:
        for sku, sp in sku_params.items():
            lp = _attr(sp, "linea_preferida", "")
            if lp and lp in lineas_params_rich:
                sku_lineas_rich.append({
                    "sku": sku, "linea": lp,
                    "t_cambio_hrs": float(_attr(sp, "t_cambio_hrs", 0) or 0),
                    "preferida": True,
                    "factor_velocidad": 1.0,  # default sin información
                })

    # ─── 4. Forecast: cajas → unidades, lista → dict {lunes: yhat_u} ─────────
    # IMPORTANTE: Prophet entrega forecast como histórico + futuro. Aquí
    # filtramos solo el futuro y limitamos al horizonte de planificación.
    horizonte_dias_default = max(horizonte_semanas * 7, 14)
    fecha_inicio_default = date.today()
    fecha_fin_default = fecha_inicio_default + timedelta(days=horizonte_dias_default)
    from calendario import semana_iso_inicio
    lunes_inicio = semana_iso_inicio(fecha_inicio_default)
    lunes_fin = semana_iso_inicio(fecha_fin_default)

    forecast_rich = {}
    for sku, lst in forecasts.items():
        upc = sku_params_rich.get(sku, {}).get("u_por_caja", 1)
        d = {}
        for f in lst:
            fecha_str = str(f.get("ds", ""))[:10]
            try:
                fecha_obj = date.fromisoformat(fecha_str)
            except ValueError:
                continue
            lunes = semana_iso_inicio(fecha_obj)
            # FIX v1.2.1: filtrar solo fechas dentro del horizonte futuro.
            # Antes se sumaba todo el histórico de Prophet (varios años de yhat),
            # produciendo demandas absurdamente altas y modelos INFEASIBLE.
            if lunes < lunes_inicio or lunes > lunes_fin:
                continue
            yhat_cajas = max(0.0, float(f.get("yhat", 0) or 0))
            yhat_u = yhat_cajas * upc
            d[lunes] = d.get(lunes, 0.0) + yhat_u
        forecast_rich[sku] = d

    # ─── 5. Stock inicial: cajas → unidades ──────────────────────────────────
    stock_inicial_rich = {}
    for sku, st_cj in stocks_actuales.items():
        upc = sku_params_rich.get(sku, {}).get("u_por_caja", 1)
        stock_inicial_rich[sku] = float(st_cj or 0) * upc

    # ─── 6. Entradas aprobadas: cajas → unidades, agrupar por SKU ────────────
    entradas_aprobadas_rich: dict[str, list[dict]] = {}
    for sku, ents in entradas_fijas.items():
        upc = sku_params_rich.get(sku, {}).get("u_por_caja", 1)
        for e in ents:
            if not e.get("aprobada"):
                continue
            fer = e.get("fecha_entrada", "")
            cj = float(e.get("cantidad_cajas", 0) or 0)
            if not fer or cj <= 0:
                continue
            try:
                fecha_obj = date.fromisoformat(str(fer)[:10])
            except ValueError:
                continue
            entradas_aprobadas_rich.setdefault(sku, []).append({
                "fecha_entrada": fecha_obj,
                "cantidad_u": int(cj * upc),
                "numero_of": e.get("numero_of", ""),
            })

    # ─── 7. Llamar al optimizador rico ───────────────────────────────────────
    horizonte_dias = max(horizonte_semanas * 7, 14)
    fecha_inicio = date.today()
    fecha_fin = fecha_inicio + timedelta(days=horizonte_dias - 1)

    resultado = optimizar_plan_v12_rich(
        plan_mrp={"ordenes": ordenes_mrp},
        sku_params=sku_params_rich,
        lineas_params=lineas_params_rich,
        sku_lineas=sku_lineas_rich,
        forecast_semanal=forecast_rich,
        stock_inicial=stock_inicial_rich,
        entradas_aprobadas=entradas_aprobadas_rich,
        fecha_inicio=fecha_inicio,
        horizonte_dias=horizonte_dias,
    )

    # ─── 8. Convertir OFTs ricas → órdenes legacy ────────────────────────────
    from calendario import semana_viz_inicio
    ordenes_produccion: list[dict] = []
    for oft in resultado["ofts"]:
        sku = oft["sku"]
        sp_rich = sku_params_rich.get(sku, {})
        sp = sku_params.get(sku)
        upc = oft["u_por_caja"]

        f_lan = date.fromisoformat(oft["fecha_lanzamiento"])
        f_ent = date.fromisoformat(oft["fecha_entrada_real"])
        # semana_emision/semana_necesidad: domingo de la semana viz (compatibilidad)
        sem_emi = semana_viz_inicio(f_lan).isoformat()
        sem_nec = semana_viz_inicio(f_ent).isoformat()

        # Stock contextual del SKU en la fecha de entrada
        stock_ent = resultado["stock_diario"].get(sku, {}).get(f_ent.isoformat(), 0)
        # Forecast aproximado de la semana de necesidad (u → cajas)
        lunes_nec = _a_lunes_iso_date(semana_viz_inicio(f_ent))
        fc_u = forecast_rich.get(sku, {}).get(lunes_nec, 0.0)
        fc_cj = round(fc_u / upc, 1) if upc else 0.0

        ss_dias = sp_rich.get("ss_dias", 0)
        ss_u = (fc_u / 7.0) * ss_dias if ss_dias else 0
        ss_cj = round(ss_u / upc, 1) if upc else 0.0

        alerta = None
        if oft.get("paga_setup"):
            alerta_setup = "Setup"  # informativo, no bloqueante
        else:
            alerta_setup = None

        ordenes_produccion.append({
            "sku": sku,
            "descripcion": sp_rich.get("descripcion", ""),
            "tipo": "PRODUCCION",
            "semana_necesidad": sem_nec,
            "semana_emision": sem_emi,
            "fecha_lanzamiento": oft["fecha_lanzamiento"],
            "fecha_entrada_real": oft["fecha_entrada_real"],
            "cantidad_cajas": int(oft["cantidad_cajas"]),
            "cantidad_unidades": int(oft["cantidad_unidades"]),
            "linea": oft["linea"],
            "motivo": "OFT (optimizada)",
            "alerta": alerta,
            "stock_inicial_cajas": 0,  # se calcula globalmente abajo
            "stock_final_cajas": round(stock_ent / upc, 1) if upc else 0.0,
            "forecast_cajas": fc_cj,
            "ss_cajas": ss_cj,
            "tiene_alerta": False,
            "lead_time_sem": float(_attr(sp, "lead_time_semanas", 1)) if sp else 1.0,
            "paga_setup": oft["paga_setup"],
            "setup_unidades": oft.get("setup_unidades", 0),
            "aprobada": False,
            "numero_of": None,
            "u_por_caja": upc,
        })

    # ─── 9. Inyectar alertas como flags ──────────────────────────────────────
    # Defensivo: las alertas tipo INFO/EMPTY no tienen sku ni fecha; se ignoran aquí.
    alertas_por_sku_fecha: dict[tuple[str, str], list[str]] = {}
    for a in resultado["alertas"]:
        sku_a = a.get("sku")
        fecha_a = a.get("fecha")
        if not sku_a or not fecha_a:
            continue
        key = (sku_a, fecha_a)
        alertas_por_sku_fecha.setdefault(key, []).append(a.get("mensaje", ""))

    for o in ordenes_produccion:
        key = (o["sku"], o["fecha_entrada_real"])
        if key in alertas_por_sku_fecha:
            o["alerta"] = "; ".join(alertas_por_sku_fecha[key])
            o["tiene_alerta"] = True

    # ─── 10. Combinar PRODUCCION (optimizada) + IMPORTACION (preservada) ─────
    ordenes_finales = ordenes_produccion + ordenes_importacion

    # ─── 11. Diagnóstico ─────────────────────────────────────────────────────
    diag = {
        "optimizado": resultado["status"] in ("OPTIMAL", "FEASIBLE"),
        "status": resultado["status"],
        "tiempo_ms": int((resultado.get("solver_time_sec") or 0) * 1000),
        "objective_value": resultado.get("objective_value"),
        "ofts_generadas": len(ordenes_produccion),
        "ordenes_importacion_preservadas": len(ordenes_importacion),
        "alertas": {
            "quiebre": resultado["resumen"].get("alertas_quiebre", 0),
            "bajo_ss": resultado["resumen"].get("alertas_bajo_ss", 0),
            "exceso_bodega": resultado["resumen"].get("alertas_exceso_bodega", 0),
        },
        "uso_promedio_lineas_pct": resultado["resumen"].get("uso_promedio_lineas_pct", {}),
        "horizonte_dias": resultado["resumen"].get("horizonte_dias", horizonte_dias),
    }

    return ordenes_finales, diag


# ── Helpers privados del wrapper legacy ─────────────────────────────────────

def _attr(obj, name, default=None):
    """Lee un atributo de un objeto o una clave de un dict (helper polimórfico)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _orden_a_dict(o) -> dict:
    """Convierte una orden (objeto OrdenSugerida o dict) a dict puro."""
    if isinstance(o, dict):
        return dict(o)
    # dataclass → dict
    from dataclasses import is_dataclass, asdict
    if is_dataclass(o):
        return asdict(o)
    # fallback: copia de __dict__
    return dict(getattr(o, "__dict__", {}))


def _a_lunes_iso(fecha_iso: str) -> str:
    """
    Convierte cualquier fecha ISO al lunes de su semana ISO.
    Robusto: si recibe un domingo, sábado, viernes, etc., siempre devuelve
    el lunes ISO de esa semana (decisión 2: importación lanza el lunes).
    """
    try:
        d = date.fromisoformat(str(fecha_iso)[:10])
    except (ValueError, TypeError):
        return fecha_iso
    from calendario import semana_iso_inicio
    return semana_iso_inicio(d).isoformat()


def _a_lunes_iso_date(d: date) -> date:
    """Devuelve el lunes ISO de la semana de la fecha dada."""
    from calendario import semana_iso_inicio
    return semana_iso_inicio(d)


# =============================================================================
# Smoke test — escenario sintético mínimo
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smoke test: optimizer.py — modelo diario v1.2")
    print("=" * 60)

    fecha_inicio = date(2026, 5, 4)  # lunes (sin feriados los próximos días)

    # 2 SKUs, 2 líneas
    sku_params = {
        "VIN_MANZ": {
            "tipo": "PRODUCCION", "ss_dias": 7, "batch_min_u": 5000,
            "batch_mult_u": 1000, "cap_bodega_u": 200_000,
            "u_por_caja": 30, "lead_time_sem": 1.0,
        },
        "VIN_BLANC": {
            "tipo": "PRODUCCION", "ss_dias": 7, "batch_min_u": 5000,
            "batch_mult_u": 1000, "cap_bodega_u": 200_000,
            "u_por_caja": 30, "lead_time_sem": 1.0,
        },
    }
    lineas_params = {
        "L001": {"velocidad_u_hr": 12000, "horas_turno": 8, "turnos_dia": 1},
        "L002": {"velocidad_u_hr": 10000, "horas_turno": 8, "turnos_dia": 1},
    }
    sku_lineas = [
        {"sku": "VIN_MANZ", "linea": "L001", "t_cambio_hrs": 0.5, "preferida": True},
        {"sku": "VIN_MANZ", "linea": "L002", "t_cambio_hrs": 0.8, "preferida": False},
        {"sku": "VIN_BLANC", "linea": "L002", "t_cambio_hrs": 0.5, "preferida": True},
    ]
    forecast_semanal = {
        "VIN_MANZ":  {date(2026, 5, 4): 30_000, date(2026, 5, 11): 30_000},
        "VIN_BLANC": {date(2026, 5, 4): 20_000, date(2026, 5, 11): 20_000},
    }
    stock_inicial = {"VIN_MANZ": 40_000, "VIN_BLANC": 25_000}
    entradas_aprobadas: dict[str, list[dict]] = {}

    resultado = optimizar_plan_v12_rich(
        plan_mrp={"ordenes": []},
        sku_params=sku_params,
        lineas_params=lineas_params,
        sku_lineas=sku_lineas,
        forecast_semanal=forecast_semanal,
        stock_inicial=stock_inicial,
        entradas_aprobadas=entradas_aprobadas,
        fecha_inicio=fecha_inicio,
        horizonte_dias=14,  # test corto
    )

    print(f"\nStatus:           {resultado['status']}")
    print(f"Objective value:  {resultado['objective_value']}")
    print(f"Tiempo solver:    {resultado['solver_time_sec']:.2f}s")
    print(f"\nResumen:")
    for k, v in resultado["resumen"].items():
        print(f"  {k}: {v}")

    print(f"\nOFTs generadas ({len(resultado['ofts'])}):")
    for o in resultado["ofts"][:10]:
        setup_str = f" [SETUP {o.get('setup_unidades', 0)} u]" if o["paga_setup"] else ""
        print(f"  {o['fecha_lanzamiento']}  {o['sku']:10s} → {o['linea']}: "
              f"{o['cantidad_cajas']:>5d} cj ({o['cantidad_unidades']:>7d} u){setup_str}")

    print(f"\nAlertas ({len(resultado['alertas'])}):")
    for a in resultado["alertas"][:5]:
        print(f"  [{a['tipo']:14s}] {a.get('sku','-'):10s} "
              f"{a.get('fecha','-')}: {a['mensaje']}")

    print(f"\nUso promedio líneas:")
    for l, pct in resultado["resumen"]["uso_promedio_lineas_pct"].items():
        print(f"  {l}: {pct}%")

    # ─── Asserts ──
    assert resultado["status"] in ("OPTIMAL", "FEASIBLE"), \
        f"Esperaba OPTIMAL/FEASIBLE, obtuve {resultado['status']}"
    assert len(resultado["ofts"]) > 0, "Debería generar al menos una OFT"

    # Verificar que ninguna OFT cae en finde o feriado
    for o in resultado["ofts"]:
        f = date.fromisoformat(o["fecha_lanzamiento"])
        assert es_habil(f), f"OFT en día no hábil: {o}"

    # Verificar que cantidad_unidades = cajas × u_por_caja (redondeo a cajas)
    for o in resultado["ofts"]:
        assert o["cantidad_unidades"] == o["cantidad_cajas"] * o["u_por_caja"], \
            f"OFT no respeta cajas: {o}"

    # Verificar que ninguna OFT excede cap_dia
    for o in resultado["ofts"]:
        l = o["linea"]
        cap = lineas_params[l]["velocidad_u_hr"] * lineas_params[l]["horas_turno"]
        assert o["cantidad_unidades"] <= cap, \
            f"OFT excede cap diaria: {o['cantidad_unidades']} > {cap}"

    print()
    print("=" * 60)
    print("Smoke test PASÓ ✓")
    print("=" * 60)
