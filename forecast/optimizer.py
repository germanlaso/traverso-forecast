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
import logging
from ortools.sat.python import cp_model

# Calendario (módulo nuevo v1.2)
from calendario import (
    es_habil,
    capacidad_dia_unidades,
    distribuir_forecast_a_diario,
    calcular_ss_diario,
    generar_horizonte_diario,
    semana_iso_inicio,
)

# Logger a nivel modulo (V6.37: necesario para que _construir_modelo loguee
# sobrecargas de aprobadas. Antes de V6.37 solo optimizar_plan() definia logger
# localmente; las otras funciones no tenian acceso).
logger = logging.getLogger("optimizer")


# =============================================================================
# Configuración
# =============================================================================

# Pesos de la función objetivo
# v1.2: W_SLACK reemplazado por W_SETUP — penalizamos cada inicio de corrida
# para incentivar consolidar producción y minimizar cambios de SKU.
# El comportamiento "llenar líneas" emerge naturalmente del SS y la cap. de bodega.
W_DEFICIT = 100_000
W_QUIEBRE = 1_000_000  # V6.18: penalización adicional por stock < 0 (10× peor que bajo SS)
W_EXCESO = 10_000
W_URGENTE = 10_000
W_SETUP = 0        # v1.3: ya no se usa en N1 — N2 optimizará setups con matriz real (R9).
                   # Conservada para rollback rápido o experimentos (e.g. W_SETUP=20).
W_ALT = 50         # penaliza usar línea alternativa (pasada A / N1)
# (05-08-2026) W_ALT es el UNICO termino del objetivo que no se multiplica por
# ESCALA_OBJ, asi que en N2 compite en una escala 1000x menor que los demas:
#   coef_def_leve = 20 * 100 * 1000 / ss_d  -> dejar 1% del SS bajo objetivo un
#   dia cuesta ~20.000, mientras MIGRAR un SKU un dia entero cuesta 50.
# Migrar es ~400 veces mas barato que el deficit mas leve, asi que C migra
# siempre que el gate de formato lo empuje. Medido en el plan #117: las 30 OFTs
# en linea alternativa son TODAS formato 1000 en semanas donde la campana fijo
# 500 -> la campana expulsa produccion a L1Pet, que es 4x mas lenta.
#
# El balance correcto es asimetrico por pasada:
#   · A (N1-min): migrar debe ser BARATO. Su trabajo es determinar que quiebres
#     son inevitables; si la linea alternativa evita uno, hay que usarla. Ademas
#     A corre con W_DEF=W_EXC=0 (indiferente al volumen), asi que W_ALT no tiene
#     contra que competir salvo el quiebre. No se toca.
#   · C (SS-target): migrar debe ser CARO. La barrera Q* ya garantiza que C no
#     puede crear quiebres nuevos (q_eff = min(Q*,0)), asi que migrar no compra
#     nada en servicio: solo mueve produccion a una linea mas lenta. Subirlo aqui
#     solo puede aumentar bajo_ss, que es blando.
#
# W_ALT_C_K se expresa en unidades de ESCALA_OBJ para que sea comparable:
#   K=100 -> migrar un dia cuesta 100.000 = un dia con ~5% del SS de deficit leve.
#   Sandwich buscado: por encima del deficit leve, muy por debajo del quiebre
#   (coef_qbr_mag ~ 200.000 por 1% del SS).
# K=0 (default) -> comportamiento IDENTICO al actual.
# (La lectura de la env var vive mas abajo, junto a las otras: aqui `_os` todavia
# no esta importado.)
W_INICIO_SIMBOLICO = 1   # v1.3 (R12): desempate para evitar inicios fantasma
                         # cuando la cota Σ inicio >= Σ asig - 1 deja al solver
                         # indiferente. NO subir por encima de 1 (recrearía
                         # W_SETUP=200 eliminado en F1, presión de consolidación
                         # va en F2 con matriz real).

# =============================================================================
# N2 (03-07-2026) — Objetivo por DESVIACIÓN % del SS (elimina sesgo de unidades)
# =============================================================================
# Motivación (diagnóstico N2): con la penalización uniforme POR UNIDAD y
# capacidad de línea ajustada, el solver salvaba preferentemente los SKU rápidos
# (factor_velocidad alto) y dejaba quebrar a los lentos (factor 0.6, SKU de 1 kg
# en Miele LV) — porque "salvar" una unidad rinde lo mismo pero cuesta menos
# capacidad en un SKU rápido. Fix: medir déficit/exceso/quiebre como % del SS de
# cada SKU (adimensional), con curva CONVEXA (pendiente creciente hacia abajo) y
# un término de EVENTO de quiebre UNIFORME entre SKU.
#
# desv% = (stock - SS) / SS       (SS = demanda_diaria × ss_dias, dinámico)
#   SS = 0  -> déficit/quiebre APAGADOS (sin demanda no hay servicio que cuidar);
#             exceso se mide vs cap_bodega (no llenar bodega de SKU sin rotación).
#
# Coeficientes "por punto porcentual" de desviación (calibración de arranque
# 03-07; se afinan con la corrida de validación h=4):
W_EXC_ALTO   = 0    # N1-min 07-07: era 8  (exceso>+100% SS -> N2)
W_EXC_LEVE   = 0    # N1-min 07-07: era 3  (exceso 0..+100% SS -> N2)
W_DEF_LEVE   = 0    # N1-min 07-07: era 20 (deficit 0..-50% SS -> N2)
W_DEF_GRAVE  = 0    # N1-min 07-07: era 60 (deficit -50..-100% SS -> N2)
W_QBR_MAG    = 200  # quiebre  < -100% (magnitud, creciente)  -> castigo doble (1/2)
# V-OV (09-07): quiebre ABSOLUTO por unidad para SKU sin SS (ss_dias=0, MTO).
# El objetivo %-del-SS gatea el quiebre en ss_d>0 (coef = W·100·ESCALA/ss_d,
# indefinido en 0); sin esto un pedido de un MTO entra al balance pero N1 no lo
# produce (quiebre gratis). Peso por unidad, no %-relativo. Calibrable (A/B 5b).
W_QBR_ABS    = 200
# Evento de quiebre: término binario por (SKU, semana), UNIFORME entre SKU.
# Es lo que rompe el sesgo: evitar el quiebre de cualquier SKU pesa igual, sin
# importar factor ni volumen. Castigo doble (2/2). En "puntos de penalización".
W_QBR_EVENTO = 5_000
# Exceso sobre cap_bodega cuando SS=0 (por unidad; único freno sin demanda).
W_EXC_BODEGA_SS0 = 3

# Escala entera del objetivo: los coeficientes "por punto %" se convierten a
# "por unidad" dividiendo por (SS/100). Para mantener enteros con precisión sin
# truncar a 0 en SKU de SS grande, multiplicamos por ESCALA_OBJ.
#   coef_unidad_tramo = round(W_tramo * 100 * ESCALA_OBJ / SS)
#   evento_escalado   = W_QBR_EVENTO * ESCALA_OBJ
ESCALA_OBJ = 1_000
# Breakpoints de la curva, como fracción del SS (déficit hacia abajo):
#   0 -> 0.5·SS  (tramo leve) ; 0.5·SS -> 1.0·SS (grave) ; >1.0·SS (quiebre mag.)
# y exceso: 0 -> 1.0·SS (leve) ; >1.0·SS (alto).
FRAC_DEF_LEVE  = 0.5   # hasta -50% del SS
FRAC_DEF_GRAVE = 1.0   # hasta -100% del SS (stock = 0)
FRAC_EXC_LEVE  = 1.0   # hasta +100% del SS

# ─── Flag SS_COBERTURA (11-07) ───────────────────────────────────────────────
# OFF (default): comportamiento idéntico a hoy. El evento_qbr se crea SOLO en la
#   rama ss_d>0 -> en findes/feriados (ss_d=0 con fórmula vieja) el quiebre NO
#   dispara el evento semanal -> quiebre de finde GRATIS (agujero detectado 11-07).
# ON: (1) ss_d se calcula con calcular_ss_diario (cobertura de próximos ss_dias
#   hábiles) -> NO colapsa en findes; (2) el evento_qbr uniforme por (SKU,semana)
#   se crea y liga SIEMPRE (todos los días, findes incluidos), fuera de la
#   bifurcación de SS. Sigue siendo UN binario por SKU-semana (guard `not in`),
#   así que NO infla el conteo de binarios ni el gap. Castigo por EVENTO uniforme
#   (no magnitud) -> sin sesgo por velocidad/factor de línea.
import os as _os
SS_COBERTURA = _os.environ.get("SS_COBERTURA", "0") == "1"

# v1.3 — Restricción de Nivel 1 (lot sizing).
# Acota cuántos SKUs distintos puede asignar el optimizador a una misma
# línea-día. Esto contiene el problema combinatorio que enfrenta el Nivel 2
# (sequencer.py): N≤4 por (línea, día) garantiza sub-problemas tratables
# en milisegundos. Decisión cerrada en sesión de diseño v1.3 (R2).
N_MAX_SKUS_DIA_LINEA = 4

# Solver
# Timeout del solver por horizonte (en SEMANAS, tal como llega del picklist
# de la UI: App.js y StockProyeccion.jsx ofrecen [4, 8, 13, 17, 26]).
# Una entrada por cada opcion del selector. El modelo crece con el horizonte
# (248 SKUs x 7 dias/sem), por lo que el limite escala con el.
#   h=4  -> 60s   (piloto, validado)
#   h=13 -> 300s  (confirmado FEASIBLE empiricamente el 11/06/2026)
#   h=8/17/26 tentativos (a calibrar con mediciones reales).
SOLVER_TIME_LIMIT_POR_HORIZONTE = {
    4:  60,
    8:  120,
    8:  300,  # N1-min 07-07: era 120 (viejo, 77 SKU); 250 SKU necesita mas
    17: 420,
    26: 600,
}
# Fallback si llega un horizonte fuera del picklist (p.ej. llamada directa a
# la API con un valor no listado). Evita KeyError: un horizonte desconocido
# no debe romper el plan, solo usar un limite prudente.
SOLVER_TIME_LIMIT_DEFAULT = 300
SOLVER_NUM_WORKERS = 8   # subido de 4: mas workers ayuda en modelos grandes (h>=13)
SOLVER_RANDOM_SEED = None  # (N2) si != None se fija en el solver (reproducibilidad pasada C)

# ─── N2 (13-07): flag y parametros de la orquestacion de dos pasadas ─────────
# OFF (default): single-pass N1-min, identico al cron actual. ON: optimizar_plan
# corre A (N1-min, define Q*) -> C (SS-target, barrera Q*). Ver DEFINICION_N2_v2.
N2_ENABLED = _os.environ.get("N2_ENABLED", "0") == "1"
# (27-07-2026) Pesos y workers de la pasada C, configurables por entorno para poder
# calibrar sin tocar código. Los defaults son los valores históricos: sin variables
# definidas, el comportamiento es idéntico al anterior.
#   N2_W_DEF_LEVE / N2_W_DEF_GRAVE : castigo por déficit vs SS (tramos)
#   N2_W_EXC_LEVE / N2_W_EXC_ALTO  : castigo por exceso sobre SS (tramos)
#   N2_WORKERS_C                   : workers de la pasada C
N2_PESOS_C = {
    "W_DEF_LEVE":  int(_os.environ.get("N2_W_DEF_LEVE",  "20")),
    "W_DEF_GRAVE": int(_os.environ.get("N2_W_DEF_GRAVE", "60")),
    "W_EXC_LEVE":  int(_os.environ.get("N2_W_EXC_LEVE",  "3")),
    "W_EXC_ALTO":  int(_os.environ.get("N2_W_EXC_ALTO",  "8")),
}
N2_WORKERS_A = 8
N2_WORKERS_C = int(_os.environ.get("N2_WORKERS_C", "2"))
# H=8: C@1w no converge (TIMEOUT_SIN_SOLUCION); 2w a costa de determinismo
N2_SEED_C = 42
# (27-07-2026) Modo de la barrera Q* de N2. Ver bloque 6b en optimizar_plan_v12_rich.
#   "universal": stock_u >= Q* en toda celda (histórico; congela la sobreproducción de A).
#   "quiebre"  : stock_u >= min(Q*, 0) — preserva el nivel de servicio de A sin
#                congelar su inventario, dejando a C reducir producción hacia el SS.
N2_BARRERA_MODO = _os.environ.get("N2_BARRERA_MODO", "universal").strip().lower()

N2_TL_A = int(_os.environ.get("N2_TL_A", "1800"))
N2_TL_C = int(_os.environ.get("N2_TL_C", "1800"))  # calibrable: probar 600-900

# ─── Campaña de granel (V6 · 29-07) ──────────────────────────────────────────
# Estado de planta semanal: a lo mas un granel de salsa (ketchup/mostaza) por
# semana habilita el envasado de los SKU de ese grupo (granel_grupo en
# mrp_sku_params). Flag OFF por default -> modelo identico al actual.
CAMPANA_GRANEL_ENABLED = _os.environ.get("CAMPANA_GRANEL_ENABLED", "0") == "1"
GRANEL_MODOS = ("ketchup", "mostaza")

# ── Secuenciacion (03-08-2026) ────────────────────────────────────────────────
# Contiguidad de bloque por SKU: prohibe el goteo diario (producir, parar,
# reanudar el mismo SKU dentro de la semana). Estructural, no ponderada: la
# agrupacion se resuelve ANTES que la desviacion de SS, no compite con ella.
# Ver DISENO_SECUENCIACION.md
SECUENCIA_CONTIG_SKU = _os.environ.get("SECUENCIA_CONTIG_SKU", "0") == "1"
SECUENCIA_CONTIG_LINEAS = _os.environ.get("SECUENCIA_CONTIG_LINEAS", "")   # vacio = todas
SECUENCIA_MAX_BLOQUES = int(_os.environ.get("SECUENCIA_MAX_BLOQUES", "1") or 1)
# Contiguidad por NIVEL de agrupacion (el caso importante): el grupo se produce
# en UN bloque contiguo por semana. "embalaje" usa u_por_caja; "granel" usa
# granel_grupo. Un cambio de embalaje (reconfigurar encajonadora) es mucho mas
# caro que reanudar el mismo SKU, por eso este nivel pesa mas que la contiguidad
# por SKU. Lista separada por comas, vacio = apagado.
SECUENCIA_CONTIG_NIVELES = _os.environ.get("SECUENCIA_CONTIG_NIVELES", "")
# (05-08) ORDEN de bloques: "uno primero y el otro despues", con la transicion
# ocurriendo DENTRO de un dia. La contiguidad sola no lo logra: dos grupos pueden
# ser contiguos Y coexistir todos los dias, que es lo del plan #113 (semana del
# 10-08: vinagre y limon presentes los 5 dias, ambos contiguos, cero huecos).
# Tampoco sirve prohibir el solapamiento diario: el dia de transicion tiene por
# fuerza los dos grupos (el embalaje 30 termina el miercoles a media manana y el
# 12 sigue esa tarde), y prohibirlo desperdiciaria capacidad.
#
# La regla correcta es UNA SOLA TRANSICION POR PAR: con n grupos activos en la
# semana se permiten n-1 dias con mas de un grupo. Con 2 embalajes -> 1 dia
# compartido -> 1 cambio de embalaje por semana, que es el minimo posible.
# Peso de linea alternativa en la pasada C, en unidades de ESCALA_OBJ.
# Ver el bloque de comentarios de W_ALT. K=0 -> comportamiento identico al actual.
W_ALT_C_K = int(_os.environ.get("W_ALT_C_K", "0") or 0)

# ── Costo de CAMBIO DE GRUPO, jerarquico (05-08-2026) ────────────────────────
# Penaliza cada ARRANQUE de grupo en la pasada C, con peso distinto por nivel:
# minimizar cambios de embalaje pesa mas que minimizar cambios de familia.
#
# Por que peso y no restriccion dura (que es lo que se probo primero):
#   · Jerarquico por construccion: dos pesos expresan "embalaje primero, familia
#     despues" sin restricciones de precedencia cuadraticas, que son las que
#     llevaron el gap de la pasada A de 0.0 a 6.4.
#   · No choca con la barrera Q*: la barrera exige un stock y la contiguidad dura
#     puede hacerlo inalcanzable; un precio nunca es infactible.
#   · El solver puede CEDER: si evitar un cambio costaria un quiebre, cambia. Con
#     restriccion dura agrupaba igual, aunque costara servicio.
#
# Calibracion (unidades de ESCALA_OBJ, comparables con el resto del objetivo):
# en L1Pet LV un cambio de 0,5 h son ~6.100 u de capacidad; con ss_d~50.000 el
# coeficiente de exceso leve es ~6/u, o sea ~37.000 de objetivo. K_EMB=50 pone el
# cambio de embalaje en 50.000: por encima de ese costo de capacidad (refleja
# deterioro y horas-hombre, no solo tiempo) y muy por debajo de un quiebre
# (coef_qbr_mag ~400/u con ese SS: 1.000 u quebradas = 400.000).
# Ratio 5:1 entre embalaje y familia = la jerarquia declarada por Produccion.
W_CAMBIO_GRUPO_K = {
    "formato":   int(_os.environ.get("W_CAMBIO_FORMATO_K", "0") or 0),
    "embalaje":  int(_os.environ.get("W_CAMBIO_EMB_K", "0") or 0),
    "familia":   int(_os.environ.get("W_CAMBIO_FAM_K", "0") or 0),
    "granel":    int(_os.environ.get("W_CAMBIO_GRANEL_K", "0") or 0),
}

SECUENCIA_ORDEN_NIVELES = _os.environ.get("SECUENCIA_ORDEN_NIVELES", "")
# Orden preferente DENTRO de un nivel, separado por comas. En familias el orden
# es fijo (vinagre antes que limon); en embalajes es indiferente, asi que se deja
# vacio y el solver elige.
SECUENCIA_ORDEN_FAMILIA = _os.environ.get("SECUENCIA_ORDEN_FAMILIA", "vinagre,limon")

# ── Quiebre INTRADIA en el SOLVER (04-08-2026 · Etapa 2) ─────────────────────
# La Etapa 1 (03-08) corrigio solo el REPORTE: `estado` y las alertas pasaron a
# evaluarse sobre el stock al INICIO del dia. El solver siguio con el criterio
# viejo (stock de CIERRE), asi que cree que producir el dia D cubre la demanda de
# D -> su optimo es llegar a D con stock 0 y producir ese dia. Operacionalmente
# eso es un dia TARDE: la produccion de D entra al cierre y se ve en D+1.
# Medido en el plan #109: el patron se repite en decenas de SKU.
#
# Con el flag, el QUIEBRE y el DEFICIT vs SS se evaluan sobre `stock_disp` (stock
# al inicio del dia menos la demanda del dia, ANTES de la produccion del dia).
# El EXCESO sigue sobre el cierre `stock_u`, que es donde esta el pico real de
# inventario. Regla: lo que mide "¿tengo suficiente?" va sobre el disponible; lo
# que mide "¿tengo demasiado?" va sobre el cierre.
QUIEBRE_INTRADIA_SOLVER = _os.environ.get("QUIEBRE_INTRADIA_SOLVER", "0") == "1"

# Campana de FORMATO por linea (Caso 2). Independiente del granel para poder
# medir su efecto por separado. v1 = SOLO PINS: las semanas sin pin las decide
# el solver sin penalizacion de cambio (no forzamos campana en todo el horizonte,
# que en una linea sin holgura sale caro).
CAMPANA_FORMATO_ENABLED = _os.environ.get("CAMPANA_FORMATO_ENABLED", "0") == "1"


def _time_limit_para(horizonte_semanas: int) -> int:
    """Devuelve el time-limit del solver (segundos) para un horizonte dado.

    Usa la tabla por horizonte; si el valor no esta listado, cae al default
    (nunca lanza KeyError).
    """
    return SOLVER_TIME_LIMIT_POR_HORIZONTE.get(
        int(horizonte_semanas), SOLVER_TIME_LIMIT_DEFAULT
    )

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
        self.quiebre: dict[tuple[date, str], cp_model.IntVar] = {}      # stock < 0 (V6.18)
        # N2 (03-07): tramos de la curva convexa en % del SS (por día, SKU)
        self.def_leve: dict[tuple[date, str], cp_model.IntVar] = {}     # déficit 0..-50% (unidades)
        self.def_grave: dict[tuple[date, str], cp_model.IntVar] = {}    # déficit -50..-100% (unidades)
        self.qbr_mag: dict[tuple[date, str], cp_model.IntVar] = {}      # quiebre <-100% (unidades)
        self.exc_leve: dict[tuple[date, str], cp_model.IntVar] = {}     # exceso 0..+100% (unidades)
        self.exc_alto: dict[tuple[date, str], cp_model.IntVar] = {}     # exceso >+100% (unidades)
        self.exc_bodega: dict[tuple[date, str], cp_model.IntVar] = {}   # exceso vs cap_bodega si SS=0
        self.coef_def_leve: dict[tuple[date, str], int] = {}            # coef/unidad escalado por SS
        self.coef_def_grave: dict[tuple[date, str], int] = {}
        self.coef_qbr_mag: dict[tuple[date, str], int] = {}
        self.coef_exc_leve: dict[tuple[date, str], int] = {}
        self.coef_exc_alto: dict[tuple[date, str], int] = {}
        self.evento_qbr: dict[tuple[str, str], cp_model.IntVar] = {}    # binaria (sku, semana_iso)
        self.granel: dict[tuple[str, str], cp_model.IntVar] = {}       # V6 campaña: (semana_iso, modo)
        self.granel_pins: dict[str, str] = {}                           # V6: {semana_iso: modo} fijados
        self.formato: dict[tuple[str, str, str], cp_model.IntVar] = {}  # V6: (linea, semana, formato)
        self.formato_pins: dict[str, dict[str, str]] = {}               # V6: {linea: {semana: formato}}
        self.formato_recurso: dict[str, str] = {}                       # V6: {linea: recurso de la regla}
        # Referencias para post-proceso
        self.skus: list[str] = []
        self.lineas: list[str] = []
        self.fechas: list[date] = []
        self.pares_sku_linea: dict[str, list[str]] = {}
        self.u_por_caja: dict[str, int] = {}                            # cache
        self.setup_u: dict[tuple[str, str], int] = {}                   # cache (u eqv. línea)
        # (04-08) stock al INICIO del dia menos la demanda del dia, ANTES de la
        # produccion de ese dia. Es el piso real del dia y la base correcta del
        # criterio de quiebre. Ver QUIEBRE_INTRADIA_SOLVER.
        self.stock_disp: dict[tuple[date, str], cp_model.IntVar] = {}
        # (05-08) arranques de grupo por nivel, para penalizarlos en el objetivo:
        # {(nivel, fecha, grupo, linea): BoolVar}
        self.arranques_grupo: dict[tuple[str, date, str, str], cp_model.IntVar] = {}
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
    pedidos_abiertos: dict[str, dict[date, float]] | None = None,
    fecha_inicio: date | None = None,
    horizonte_dias: int = HORIZONTE_DIAS_DEFAULT,
    time_limit_sec: int | None = None,
    cotas_qstar: dict[tuple[str, str], int] | None = None,
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

    # Time-limit: si el caller no lo especifica, derivarlo del horizonte en
    # semanas (aprox dias/7). El wrapper legacy lo pasa explicito desde el
    # picklist; en uso directo/testing se infiere.
    if time_limit_sec is None:
        time_limit_sec = _time_limit_para(round(horizonte_dias / 7))

    horizonte = generar_horizonte_diario(fecha_inicio, horizonte_dias)
    fecha_fin = horizonte[-1]

    # ─── 1. Filtrar SKUs que entran al modelo ────────────────────────────────
    skus_produccion = [
        sku for sku, params in sku_params.items()
        if params.get("tipo", "").upper() == "PRODUCCION"
    ]

    # Excluir SKUs sin demanda en el horizonte (decisión 9)
    # V-OV: un SKU con pedido abierto (OV) entra aunque su forecast sea 0
    # (MTO / esporádicos). Si no, su demanda comprometida se caería del modelo.
    skus_con_pedido = set(pedidos_abiertos or {})
    skus_activos = []
    for sku in skus_produccion:
        forecast_sku = forecast_semanal.get(sku, {})
        total_demanda = sum(forecast_sku.values())
        if total_demanda > 0 or sku in skus_con_pedido:
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

    # ─── 3. Demanda diaria: base-SS (forecast) y consumo (forecast ⊕ pedidos) ─
    # V-OV (Manual §3, snapshot 09-07): se desdobla la demanda en dos vectores.
    #   demanda_ss_base -> forecast solo    -> target SS (N2): ss_d = base×ss_dias
    #   demanda_consumo -> max(fc, pedidos) -> balance/quiebre (piso N1)
    # Netear en un solo vector inflaría el SS de un pedidón. Aguas arriba del
    # split N1/N2 -> ambas capas heredan el desdoblamiento.
    demanda_ss_base: dict[str, dict[date, float]] = {}
    for sku in skus_modelo:
        demanda_ss_base[sku] = distribuir_forecast_a_diario(
            forecast_semanal.get(sku, {}),
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
    demanda_consumo = netear_pedidos_a_diario(
        demanda_ss_base, pedidos_abiertos, sku_params, fecha_inicio, fecha_fin,
    )

    # (11-07) Forecast diario EXTENDIDO para el SS de cobertura. El SS del día d
    # suma los próximos ss_dias hábiles; para los últimos días del horizonte esa
    # ventana se sale de fecha_fin. Extendemos ~5 semanas (cubre 15 hábiles + margen
    # de feriados) usando el MISMO forecast_semanal (que trae +4 períodos del
    # pipeline). Sólo para calcular SS en el post-proceso; NO entra al modelo.
    _fecha_fin_ext = fecha_fin + timedelta(days=35)
    ss_forecast_ext: dict[str, dict[date, float]] = {}
    for sku in skus_modelo:
        ss_forecast_ext[sku] = distribuir_forecast_a_diario(
            forecast_semanal.get(sku, {}),
            fecha_inicio=fecha_inicio,
            fecha_fin=_fecha_fin_ext,
        )

    # ─── D4: Guarda de cobertura del forecast (27-07-2026) ───────────────────
    # Detecta el caso "extensión de rango sin datos": distribuir_forecast_a_diario
    # rellena con ceros, así que el dict diario SIEMPRE llega a fecha_fin aunque el
    # forecast semanal se haya agotado antes. Por eso verificamos el forecast SEMANAL.
    #
    # Origen: hallazgo 27-07-2026 (plan id=56). El forecast terminaba el 11-09 con
    # horizonte hasta el 20-09 => 9 días sin demanda y SS truncado desde el 24-08.
    # La falla fue SILENCIOSA. Ver DECISION_forecast_cobertura_y_reentrenamiento.md
    #
    # Esta guarda SÓLO OBSERVA Y LOGUEA; no altera el plan.
    def _ultima_semana_cubierta(fc_sem: dict) -> date | None:
        """Último día cubierto por el forecast semanal (clave + 6 días)."""
        claves = [k for k, v in fc_sem.items() if v and v > 0]
        if not claves:
            return None
        ult = max(claves)
        if isinstance(ult, str):
            ult = date.fromisoformat(ult[:10])
        elif not isinstance(ult, date) and hasattr(ult, "date"):
            ult = ult.date()          # pandas.Timestamp / datetime
        elif isinstance(ult, date) and hasattr(ult, "hour"):
            ult = ult.date()          # datetime.datetime (subclase de date)
        return ult + timedelta(days=6)

    _criticos: list[tuple[str, date, int]] = []   # no cubre el horizonte -> días ciegos
    _avisos:   list[tuple[str, date, int]] = []   # no cubre el margen SS -> SS truncado
    _sin_fc:   list[str] = []
    for sku in skus_modelo:
        _cob = _ultima_semana_cubierta(forecast_semanal.get(sku, {}))
        if _cob is None:
            _sin_fc.append(sku)
        elif _cob < fecha_fin:
            _criticos.append((sku, _cob, (fecha_fin - _cob).days))
        elif _cob < _fecha_fin_ext:
            _avisos.append((sku, _cob, (_fecha_fin_ext - _cob).days))

    _n = len(skus_modelo) or 1
    _pct = 100.0 * len(_criticos) / _n
    print(f"[cobertura] horizonte hasta {fecha_fin} | SS necesita hasta {_fecha_fin_ext}")
    print(f"[cobertura] SKUs={len(skus_modelo)} | CRITICOS={len(_criticos)} ({_pct:.1f}%) "
          f"| avisos_SS={len(_avisos)} | sin_forecast={len(_sin_fc)}")
    for _s, _c, _d in sorted(_criticos, key=lambda t: -t[2])[:15]:
        print(f"[cobertura] CRITICO {_s}: forecast hasta {_c} -> {_d} dias CIEGOS en el plan")
    for _s, _c, _d in sorted(_avisos, key=lambda t: -t[2])[:10]:
        print(f"[cobertura] aviso   {_s}: forecast hasta {_c} -> SS truncado {_d} dias")
    if _pct > 5.0:
        print(f"[cobertura] *** ALERTA: {_pct:.1f}% de los SKU no cubren el horizonte. "
              f"El plan tiene dias sin demanda. Revisar reentrenamiento de modelos. ***")
    # ─── fin D4 ──────────────────────────────────────────────────────────────

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
        es_pasada_c=bool(cotas_qstar),
        horizonte=horizonte,
        skus=skus_modelo,
        sku_params=sku_params,
        lineas_params=lineas_params,
        sku_a_lineas=sku_a_lineas,
        demanda_consumo=demanda_consumo,
        demanda_ss_base=demanda_ss_base,
        cap_dia=cap_dia,
        stock_inicial=stock_inicial,
        entradas_aprobadas=entradas_aprobadas,
        ss_forecast_ext=ss_forecast_ext,
    )

    # ─── 6. Función objetivo ─────────────────────────────────────────────────
    # (05-08) Peso de linea alternativa ASIMETRICO por pasada: cotas_qstar
    # distingue A (None) de C (con contenido). Ver el comentario de W_ALT_C_K.
    _w_alt = (W_ALT_C_K * ESCALA_OBJ) if (cotas_qstar and W_ALT_C_K > 0) else W_ALT
    if cotas_qstar and W_ALT_C_K > 0:
        logger.info(f"[N2] W_ALT en pasada C = {_w_alt:,} "
                    f"(K={W_ALT_C_K} x ESCALA_OBJ) | en A queda {W_ALT}")
    _agregar_objetivo(m, sku_params=sku_params, lineas_params=lineas_params,
                      cap_dia=cap_dia, sku_a_lineas=sku_a_lineas, w_alt=_w_alt)

    # ─── 6b. (N2) Barrera dura Q*: stock_u[(d,s)] >= Q*[(s, d_iso)] ───────────
    # Cota inferior por celda tomada del stock SIN clamp de la pasada N1
    # (DEFINICION_N2_v2 §1.2): N2 no puede empeorar ningun quiebre que N1 evito.
    #
    # (27-07-2026) MODO configurable via env N2_BARRERA_MODO:
    #
    #   "universal" (histórico): stock_u >= Q* en TODA celda. Problema: la pasada A
    #       corre con W_DEF=W_EXC=W_SETUP=0, o sea es INDIFERENTE a cuánto produce
    #       — cualquier nivel de stock le da el mismo objetivo. Si el LNS deja a un
    #       SKU con inventario inflado, ese valor se vuelve PISO OBLIGATORIO para C.
    #       C sí penaliza el exceso sobre SS (W_EXC_ALTO), pero no puede bajarlo:
    #       la cota es dura. Resultado: sobreproducción que C no puede corregir.
    #
    #   "quiebre" (recomendado): stock_u >= min(Q*, 0). Preserva EXACTAMENTE el
    #       propósito declarado —no empeorar el nivel de servicio de A— sin
    #       congelar su nivel de inventario:
    #         · Q* >= 0 (A no quebró)  -> cota 0: C no puede introducir un quiebre
    #                                     nuevo, pero SÍ puede reducir producción.
    #         · Q* <  0 (inevitable)   -> cota Q*: C no puede empeorarlo.
    #       C queda libre para acercar el inventario al SS, que es su misión.
    _modo_barrera = N2_BARRERA_MODO
    if cotas_qstar:
        _n_barrera = 0
        _n_relajadas = 0
        # (04-08) La cota va sobre la MISMA variable que juzga el quiebre. Si el
        # criterio es intradia, acotar el cierre no impide que C hunda el piso.
        _vars_barrera = m.stock_disp if QUIEBRE_INTRADIA_SOLVER else m.stock_u
        for (d, s), var in _vars_barrera.items():
            q = cotas_qstar.get((s, d.isoformat()))
            if q is None:
                continue
            if _modo_barrera == "quiebre":
                q_eff = min(int(q), 0)
                if q_eff != int(q):
                    _n_relajadas += 1
            else:
                q_eff = int(q)
            m.model.Add(var >= q_eff)
            _n_barrera += 1
        logger.info(f"[N2] barrera Q* modo={_modo_barrera} sobre="
                    f"{'stock_disp' if QUIEBRE_INTRADIA_SOLVER else 'stock_fin'}"
                    f": {_n_barrera} cotas agregadas"
                    + (f" ({_n_relajadas} relajadas a 0 -> C puede reducir producción)"
                       if _modo_barrera == "quiebre" else ""))

    # ─── 7. Resolver ─────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec
    solver.parameters.num_search_workers = SOLVER_NUM_WORKERS
    if SOLVER_RANDOM_SEED is not None:
        solver.parameters.random_seed = SOLVER_RANDOM_SEED
    status = solver.Solve(m.model)
    status_name = solver.StatusName(status)
    solver_time = solver.WallTime()

    # ── Clasificacion de status (fix 11/06: timeout != infeasible) ──────────
    # CP-SAT (ortools 9.x) devuelve:
    #   OPTIMAL    -> solucion probadamente optima
    #   FEASIBLE   -> hay solucion factible (NO probada optima). CP-SAT ya
    #                 reporta FEASIBLE -no UNKNOWN- cuando agota el tiempo
    #                 pero encontro al menos una solucion. Es decir: el caso
    #                 'timeout con solucion parcial' YA llega aca como FEASIBLE.
    #   INFEASIBLE -> probado que NO existe solucion
    #   UNKNOWN    -> se acabo el tiempo SIN ninguna solucion (ni pruebas)
    #   MODEL_INVALID -> error de construccion del modelo
    #
    # El bug anterior trataba UNKNOWN igual que INFEASIBLE. Ahora cada caso
    # se distingue. Para marcar el subcaso 'FEASIBLE por timeout' (sin probar
    # optimalidad) miramos si el solver consumio casi todo el limite: si
    # FEASIBLE y WallTime >= 95% del limite, fue corte por tiempo.
    # Nota: no se usa solver.SolutionCount() — ese metodo no existe en
    # CpSolver (pertenece al callback); el status ya indica si hay solucion.
    if status == cp_model.OPTIMAL:
        pass  # status_name = 'OPTIMAL'
    elif status == cp_model.FEASIBLE:
        # Hay solucion. Distinguir si fue corte por tiempo (suboptima) o si
        # el solver simplemente devolvio factible. En ambos casos es operable.
        if solver_time >= 0.95 * time_limit_sec:
            status_name = "FEASIBLE_TIMEOUT"
        # else: queda 'FEASIBLE' normal
    elif status == cp_model.INFEASIBLE:
        # Infactibilidad REAL probada por el solver.
        return _resultado_vacio(
            "El solver probó que no existe plan factible con las restricciones actuales (INFEASIBLE real). Revisar parámetros (cap_bodega, SS, capacidad).",
            status="INFEASIBLE", solver_time_sec=solver_time,
        )
    elif status == cp_model.MODEL_INVALID:
        return _resultado_vacio(
            "Modelo invalido (MODEL_INVALID): error de construccion del modelo CP-SAT.",
            status="MODEL_INVALID", solver_time_sec=solver_time,
        )
    else:
        # UNKNOWN: se acabo el tiempo sin encontrar ninguna solucion.
        # NO es lo mismo que INFEASIBLE -> status propio para no confundir.
        return _resultado_vacio(
            f"El solver no encontró solución dentro del límite de tiempo "
            f"({time_limit_sec}s) y no pudo probar infactibilidad. "
            f"Probar un horizonte menor o subir el time-limit.",
            status="TIMEOUT_SIN_SOLUCION", solver_time_sec=solver_time,
        )

    # ─── 8. Post-procesar a OFTs y stock visible ─────────────────────────────
    resultado = _post_procesar(
        m=m, solver=solver,
        horizonte=horizonte, sku_params=sku_params, lineas_params=lineas_params,
        sku_a_lineas=sku_a_lineas, cap_dia=cap_dia,
        status_name=status_name, solver_time_sec=solver_time,
        objective_value=solver.ObjectiveValue(),
        demanda_ss_base=demanda_ss_base,
        demanda_consumo=demanda_consumo,
        stock_inicial=stock_inicial,
        ss_forecast_ext=ss_forecast_ext,
        entradas_aprobadas=entradas_aprobadas,
        pedidos_abiertos=pedidos_abiertos,
    )

    # Si la solucion es suboptima por timeout, dejar constancia para el usuario
    # con una alerta INFO (alimenta el backlog #2: estados del solver en la UI).
    if status_name == "FEASIBLE_TIMEOUT":
        resultado.setdefault("alertas", []).insert(0, {
            "tipo": "INFO",
            "mensaje": (
                f"Plan FACTIBLE pero subóptimo: el solver alcanzó el límite de "
                f"tiempo ({time_limit_sec}s) antes de probar optimalidad. "
                f"La solución es válida y operable."
            ),
        })

    return resultado


# =============================================================================
# Construcción del modelo
# =============================================================================

def netear_pedidos_a_diario(
    demanda_fc: dict[str, dict[date, float]],
    pedidos_abiertos: dict[str, dict[date, float]] | None,
    sku_params: dict[str, dict],
    fecha_inicio: date,
    fecha_fin: date,
) -> dict[str, dict[date, float]]:
    """Consumo de forecast: consumo[d] = max(forecast[d], pedidos_u[d]) por día.

    Regla confirmada (09-07): el pedido consume el forecast del día (max, no suma):
    donde el pedido supera al forecast, manda el pedido; donde el forecast supera,
    se conserva (no se pierde lo no pedido, no hay doble conteo).

    - Pedidos entran en CAJAS -> se convierten a unidades (× u_por_caja) acá.
    - fecha None o < fecha_inicio -> se arrastra a fecha_inicio (día 0). Idempotente
      con el arrastre del conector; defensivo si se invoca sin él.
    - fecha > fecha_fin -> fuera del horizonte de planificación, se descarta (log).

    demanda_fc NO se muta: se devuelve una copia (el vector de SS queda intacto).
    """
    consumo: dict[str, dict[date, float]] = {s: dict(f) for s, f in demanda_fc.items()}
    if not pedidos_abiertos:
        return consumo

    n_fuera = 0
    for sku, por_fecha in pedidos_abiertos.items():
        upc = int((sku_params.get(sku) or {}).get("u_por_caja", 1) or 1)
        dia_ped: dict[date, float] = {}
        for f, cajas in por_fecha.items():
            fe = fecha_inicio if (f is None or f < fecha_inicio) else f
            if fe > fecha_fin:
                n_fuera += 1
                continue
            dia_ped[fe] = dia_ped.get(fe, 0.0) + float(cajas) * upc
        if not dia_ped:
            continue
        d_sku = consumo.setdefault(sku, {})
        for fe, ped_u in dia_ped.items():
            d_sku[fe] = max(d_sku.get(fe, 0.0), ped_u)
    if n_fuera:
        logger.info("[neteo OV] %d pedido(s) fuera del horizonte (> %s) descartado(s).",
                    n_fuera, fecha_fin.isoformat())
    return consumo


def _construir_modelo(
    horizonte: list[date],
    skus: list[str],
    sku_params: dict[str, dict],
    lineas_params: dict[str, dict],
    sku_a_lineas: dict[str, list[dict]],
    demanda_consumo: dict[str, dict[date, float]],
    demanda_ss_base: dict[str, dict[date, float]],
    cap_dia: dict[tuple[date, str], int],
    stock_inicial: dict[str, float],
    entradas_aprobadas: dict[str, list[dict]],
    ss_forecast_ext: dict[str, dict[date, float]] | None = None,
    es_pasada_c: bool = False,
) -> _ModeloCPSAT:
    """Construye variables y restricciones del modelo CP-SAT con variables en cajas.

    es_pasada_c: True cuando se construye la pasada C (SS-target). Se usa para las
    restricciones que NO deben aplicarse en A, como el ORDEN de bloques: en A
    degradan la convergencia (gap 0.0 -> 6.94 medido el 05-08) y conceptualmente
    no corresponden, porque A solo determina que quiebres son inevitables.
    """

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
            m.stock_disp[(d, s)] = m.model.NewIntVar(stock_low, stock_high,
                                                    f"stockdisp_{d_idx}_{s}")
            m.deficit[(d, s)] = m.model.NewIntVar(0, big_ub, f"def_{d_idx}_{s}")
            m.exceso[(d, s)] = m.model.NewIntVar(0, big_ub, f"exc_{d_idx}_{s}")
            m.quiebre[(d, s)] = m.model.NewIntVar(0, big_ub, f"qbr_{d_idx}_{s}")

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

                # R12 (v1.3, decisión Gerente 05/05/2026): primer SKU del día
                # NO paga setup. La cota inferior agregada
                #   Σ_k inicio[d,k,l] >= Σ_k asig[d,k,l] - 1
                # se aplica más abajo en la sección "Restricciones agregadas
                # por (d, l)". Acá solo mantenemos integridad por SKU
                # (inicio nunca 1 si asig=0). R4 (día 0 sin setup) queda
                # subsumida por R12: si día 0 tiene N=1 SKU, Σ inicio = 0.
                m.model.Add(inicio <= asig)

    # ─── Acoplamiento de campaña de granel (V6 · flag CAMPANA_GRANEL_ENABLED) ─
    # granel[(w, modo)] binaria, <=1 granel de salsa por semana. Un SKU con
    # granel_grupo ketchup/mostaza solo puede producirse (asig=1) en semanas
    # donde ESE granel esta activo. Acople DURO: forzar un modo NUNCA vuelve N1
    # infactible — el faltante cae en quiebre penalizado (blando por diseño, ver
    # STOCK_LOWER_BOUND_FACTOR). Independientes (grupo vacio) sin acople.
    if CAMPANA_GRANEL_ENABLED:
        _semanas_g = sorted({semana_iso_inicio(d).isoformat() for d in horizonte})
        for _w in _semanas_g:
            for _modo in GRANEL_MODOS:
                m.granel[(_w, _modo)] = m.model.NewBoolVar(f"granel_{_w}_{_modo}")
            m.model.Add(sum(m.granel[(_w, _modo)] for _modo in GRANEL_MODOS) <= 1)
        # Pins del planificador (mrp_campana_calendario, fijado=TRUE). Import lazy:
        # si la BD no responde, degrada a "el solver decide" en vez de romper el plan.
        _pins = {}
        try:
            from db_mrp import get_campana_pins_dict
            _pins = get_campana_pins_dict("GRANEL_SALSAS") or {}
        except Exception as _e:
            logger.warning(f"[CAMPANA] no se pudieron leer pins ({_e}) -> solver decide")
        m.granel_pins = dict(_pins)   # visible en el post-solve (otra funcion)
        _n_pin = 0
        for _w, _modo_pin in _pins.items():
            if _w not in _semanas_g:
                continue  # pin fuera del horizonte actual: se ignora
            if _modo_pin in GRANEL_MODOS:
                m.model.Add(m.granel[(_w, _modo_pin)] == 1)
            else:
                # "" / "ninguno" -> semana sin granel de salsa
                for _modo in GRANEL_MODOS:
                    m.model.Add(m.granel[(_w, _modo)] == 0)
            _n_pin += 1
        if _n_pin:
            logger.info(f"[CAMPANA] {_n_pin} semanas FIJADAS por pin: "
                        + ", ".join(f"{w}={_pins[w] or 'ninguno'}"
                                    for w in sorted(_pins) if w in _semanas_g))

        _n_acople = 0
        for d in horizonte:
            _w = semana_iso_inicio(d).isoformat()
            for s in skus:
                _grupo = (sku_params[s].get("granel_grupo") or "").strip().lower()
                if _grupo not in GRANEL_MODOS:
                    continue
                for l in m.pares_sku_linea[s]:
                    m.model.Add(m.asig[(d, s, l)] <= m.granel[(_w, _grupo)])
                    _n_acople += 1
        logger.info(f"[CAMPANA] granel ON: {len(_semanas_g)} semanas x "
                    f"{len(GRANEL_MODOS)} modos, {_n_acople} acoples asig<=granel")

    # ─── Campana de FORMATO por linea (V6 · flag CAMPANA_FORMATO_ENABLED) ─────
    # formato[(linea, semana, fmt)] binaria, <= max_modos por semana. Un SKU con
    # ese formato solo puede producirse EN ESA LINEA si su formato esta activo.
    # El acople va sobre asig[(d, s, linea)]: si el SKU corre en otra linea, el
    # estado de formato de esta no lo limita.
    if CAMPANA_FORMATO_ENABLED:
        _reglas_f = []
        try:
            from db_mrp import get_campana_reglas, get_campana_pins_dict
            for _r in get_campana_reglas():
                if (_r.get("dimension") or "") == "formato" and _r.get("linea"):
                    _reglas_f.append(_r)
        except Exception as _e:
            logger.warning(f"[CAMPANA] no se pudieron leer reglas de formato ({_e})")

        _semanas_f = sorted({semana_iso_inicio(d).isoformat() for d in horizonte})
        for _r in _reglas_f:
            _lin = _r["linea"]
            _modos = [str(x) for x in (_r.get("modos") or [])]
            _maxm = int(_r.get("max_modos_semana") or 1)
            if not _modos:
                continue
            for _w in _semanas_f:
                for _fmt in _modos:
                    m.formato[(_lin, _w, _fmt)] = m.model.NewBoolVar(
                        f"fmt_{_lin}_{_w}_{_fmt}".replace(" ", "_"))
                m.model.Add(
                    sum(m.formato[(_lin, _w, _f)] for _f in _modos) <= _maxm)

            # Pins: solo estas semanas quedan forzadas.
            _pf = {}
            try:
                _pf = get_campana_pins_dict(_r["recurso"]) or {}
            except Exception as _e:
                logger.warning(f"[CAMPANA] sin pins de {_r['recurso']} ({_e})")
            m.formato_pins[_lin] = dict(_pf)
            m.formato_recurso[_lin] = _r["recurso"]
            _npf = 0
            for _w, _fmt in _pf.items():
                if _w not in _semanas_f:
                    continue
                if _fmt in _modos:
                    m.model.Add(m.formato[(_lin, _w, _fmt)] == 1)
                else:
                    for _f in _modos:
                        m.model.Add(m.formato[(_lin, _w, _f)] == 0)
                _npf += 1

            # Acople: produccion en esa linea solo si su formato esta activo.
            _naf = 0
            for d in horizonte:
                _w = semana_iso_inicio(d).isoformat()
                for s in skus:
                    _fmt = str(sku_params[s].get("formato") or "").strip()
                    if _fmt not in _modos:
                        continue          # formato ajeno a la regla: sin acople
                    if _lin not in m.pares_sku_linea.get(s, []):
                        continue          # el SKU no corre en esa linea
                    m.model.Add(m.asig[(d, s, _lin)] <= m.formato[(_lin, _w, _fmt)])
                    _naf += 1
            logger.info(f"[CAMPANA] formato ON {_lin}: modos={_modos} "
                        f"{len(_semanas_f)} semanas, {_npf} pins, {_naf} acoples")

    # ─── Contiguidad de bloque por SKU (03-08 · SECUENCIA_CONTIG_SKU) ────────
    # PROBLEMA MEDIDO (plan #101, L1Pet LV semana 17-08): 20 batches de solo 6
    # SKU distintos. El mismo SKU se produce todos los dias en cantidades chicas
    # (111010290: 21+28+27+27+34 min en 5 dias). No es indiferencia del solver:
    # es el optimo del objetivo tal como esta escrito. N2 minimiza la desviacion
    # % del SS DIA POR DIA (W_EXC_LEVE=3, W_EXC_ALTO=8); concentrar la produccion
    # deja el stock por encima del SS los dias siguientes -> exceso penalizado.
    # Gotear lo mantiene pegado al SS. Y no hay contrapeso: W_SETUP=0 y
    # t_cambio_hrs=0 en los 249 SKU.
    #
    # POR QUE ESTRUCTURAL Y NO PESO: un W_SETUP moderado NEGOCIA gradualmente
    # con el exceso de SS (y ya se elimino en F1). La agrupacion debe resolverse
    # ANTES que la desviacion de SS, no competir con ella: se impone como
    # estructura y el SS se optimiza DENTRO del espacio restringido. Aplica a
    # ambas pasadas: A encuentra los quiebres inevitables DADA la agrupacion y C
    # optimiza SS dentro de ella.
    #
    # POR QUE DURA SIN RIESGO: mismo argumento que el acople de granel (ya en
    # produccion). Si un SKU no puede producirse en bloque contiguo, produce
    # menos y el faltante cae en QUIEBRE, que es blando por STOCK_LOWER_BOUND_
    # FACTOR. No genera infactibilidad y no agrega ningun peso nuevo.
    #
    # `inicio` NO sirve para esto: es un contador agregado por (dia,linea)
    # (Σ inicio >= Σ asig - 1, R12) y su unica ligadura por SKU es inicio<=asig.
    # No esta atado a la transicion asig[d-1]->asig[d], asi que Σ inicio <= 1 no
    # expresa contiguidad. Se usa variable propia `arranca`.
    if SECUENCIA_CONTIG_SKU and not es_pasada_c:
        logger.info("[SECUENCIA] contiguidad SKU OMITIDA en pasada A "
                    "- toda la secuenciacion va en C")
    if SECUENCIA_CONTIG_SKU and es_pasada_c:
        _lineas_c = {x.strip() for x in SECUENCIA_CONTIG_LINEAS.split(",") if x.strip()}
        _arranca: dict = {}
        _prod_sku: dict = {}
        _n_ct = 0
        for d_idx, d in enumerate(horizonte):
            for s in skus:
                for l in m.pares_sku_linea[s]:
                    if _lineas_c and l not in _lineas_c:
                        continue
                    a = m.model.NewBoolVar(f"arranca_{d_idx}_{s}_{l}")
                    _arranca[(d, s, l)] = a
                    # (04-08 · FIX) mismo escape que en la contiguidad por nivel:
                    # `asig` es permiso, no produccion. Se usa un indicador propio
                    # ligado a las CAJAS.
                    prod = m.model.NewBoolVar(f"prod_{d_idx}_{s}_{l}")
                    _cap_s = (int(cap_dia.get((d, l), 0) or 0) + 1) * 2
                    m.model.Add(m.cajas[(d, s, l)] <= _cap_s * prod)
                    m.model.Add(prod <= m.cajas[(d, s, l)])
                    _prod_sku[(d, s, l)] = prod
                    prev = _prod_sku.get((horizonte[d_idx - 1], s, l)) if d_idx > 0 else None
                    if prev is None:
                        m.model.Add(a >= prod)
                    else:
                        m.model.Add(a >= prod - prev)
                    m.model.Add(a <= prod)
        # Un solo arranque por (SKU, linea, semana) -> un solo bloque contiguo,
        # que puede ocupar varios dias pero no reanudarse.
        _por_sem: dict = {}
        for (d, s, l), a in _arranca.items():
            _por_sem.setdefault((semana_iso_inicio(d).isoformat(), s, l), []).append(a)
        for _k, _vs in _por_sem.items():
            if len(_vs) > 1:
                m.model.Add(sum(_vs) <= SECUENCIA_MAX_BLOQUES)
                _n_ct += 1
        logger.info(f"[SECUENCIA] contiguidad SKU ON | lineas="
                    f"{sorted(_lineas_c) or 'TODAS'} | max_bloques/semana="
                    f"{SECUENCIA_MAX_BLOQUES} | {len(_arranca)} vars, "
                    f"{_n_ct} restricciones")

    # ─── Contiguidad por NIVEL (03-08 · SECUENCIA_CONTIG_NIVELES) ────────────
    # El caso que importa. Medido en #101 L1Pet LV semana 17-08: el embalaje 12 se
    # produce el 18 y el 20, y el 30 el 17, 19, 20 y 21 -> 4 cambios de embalaje
    # donde alcanzaria 1. Cada cambio exige reconfigurar la encajonadora, muy por
    # encima del costo de reanudar el mismo SKU (misma config, mismo granel,
    # misma etiqueta). Orden de costo confirmado con Produccion el 03-08:
    # formato > embalaje > familia > sub-granel.
    #
    # `usa[d,g,l]` = el grupo g ocupa la linea el dia d. Necesita AMBAS cotas:
    # sin la superior el solver pondria usa=1 todos los dias y satisfaria la
    # restriccion con un solo arranque, volviendola inerte.
    #
    # Estructural, sin peso: la agrupacion se resuelve ANTES que la desviacion de
    # SS. Dura sin riesgo de infactibilidad (mismo argumento que el acople de
    # granel: el faltante cae en quiebre, blando por STOCK_LOWER_BOUND_FACTOR).
    # (05-08) TODA la secuenciacion vive en C, no en A. Medido en dos corridas:
    # con la contiguidad activa en A, la pasada A pasa de OPTIMAL gap=0.0 a
    # FEASIBLE_TIMEOUT gap~6.4 -> el Q* deja de ser confiable y la barrera que
    # hereda C se construye sobre una cota mala.
    # El costo aparecio al CERRAR el escape de `asig` (03-08): al ligar `usa` a
    # `cajas` con big-M la restriccion paso de inerte a real, y la relajacion
    # lineal quedo muy floja. Antes de ese fix A daba OPTIMAL porque la
    # restriccion practicamente no restringia.
    # Principio: A solo determina que quiebres son INEVITABLES; agrupacion,
    # orden y eleccion de linea son preferencias de eficiencia y pertenecen a C.
    _niv = [x.strip() for x in SECUENCIA_CONTIG_NIVELES.split(",") if x.strip()]
    _ord = {x.strip() for x in SECUENCIA_ORDEN_NIVELES.split(",") if x.strip()}
    _ord_fam = [x.strip().lower() for x in SECUENCIA_ORDEN_FAMILIA.split(",") if x.strip()]
    if _niv and not es_pasada_c:
        logger.info(f"[SECUENCIA] contiguidad OMITIDA en pasada A "
                    f"(niveles={_niv}) - toda la secuenciacion va en C")
    if _niv and es_pasada_c:
        _lineas_n = {x.strip() for x in SECUENCIA_CONTIG_LINEAS.split(",") if x.strip()}

        def _val_nivel(_s, _nivel):
            sp = sku_params[_s]
            if _nivel == "embalaje":
                return str(sp.get("u_por_caja") or "")
            if _nivel == "granel":
                return str(sp.get("granel_grupo") or "").strip().lower()
            if _nivel == "formato":
                return str(sp.get("formato") or "").strip()
            if _nivel == "familia":
                # PROVISIONAL: la familia se deriva del prefijo de granel_grupo
                # (vinagre_blanco -> vinagre, limon_pica -> limon). La fuente
                # correcta es mrp_graneles.familia, que todavia no viaja hasta el
                # modelo (trampa de las 4 capas: BD -> dataclass -> dict rich ->
                # modelo). Valido para L1Pet LV con el naming cargado el 03-08.
                _g = str(sp.get("granel_grupo") or "").strip().lower()
                return _g.split("_")[0] if _g else ""
            return ""

        def _clave_de(_s, _hasta):
            """Clave ACUMULADA de los niveles 0.._hasta.

            La jerarquia es ANIDADA: el grupo del nivel N incluye los valores de
            todos los niveles superiores. Asi "agrupar por familia DENTRO de cada
            embalaje" se expresa como contiguidad de la clave (embalaje, familia):
            (12,limon) y (30,limon) son grupos DISTINTOS, cada uno contiguo.
            Si en cambio se agrupara solo por familia a nivel semana, se prohibiria
            que limon apareciera en los dos embalajes -> pondria familia ARRIBA de
            embalaje, invirtiendo la jerarquia de costos.
            """
            partes = []
            for nv in _niv[:_hasta + 1]:
                v = _val_nivel(_s, nv)
                if not v:
                    return None
                partes.append(v)
            return "|".join(partes)

        for _i_niv, _nivel in enumerate(_niv):
            _usa: dict = {}
            _arr: dict = {}
            _nr = 0
            # (linea -> grupo -> [skus])
            _por_l: dict = {}
            for s in skus:
                g = _clave_de(s, _i_niv)
                if not g:
                    continue
                for l in m.pares_sku_linea[s]:
                    if _lineas_n and l not in _lineas_n:
                        continue
                    _por_l.setdefault(l, {}).setdefault(g, []).append(s)
            for l, grupos in _por_l.items():
                if len(grupos) < 2:
                    continue          # un solo grupo: nada que agrupar
                for g, skus_g in grupos.items():
                    for d_idx, d in enumerate(horizonte):
                        u = m.model.NewBoolVar(f"usa_{_nivel}_{d_idx}_{g}_{l}")
                        _usa[(d, g, l)] = u
                        # (04-08 · FIX) `usa` se liga a las CAJAS, no a `asig`.
                        # asig es solo un PERMISO: la unica ligadura con la
                        # produccion es `upc*cajas <= cap*asig` (linea ~777), asi
                        # que asig=1 con cajas=0 es factible y GRATIS. Con la
                        # version anterior el solver satisfacia la contiguidad
                        # poniendo asig=1 en el dia del hueco sin producir nada:
                        # cadena contigua en el modelo, hueco real en las OFTs.
                        # Medido en el plan #113: (emb30, limon) produjo lun/mar/jue
                        # de la semana del 31-08 saltando el miercoles habil.
                        # Es el mismo patron que los "inicios fantasma" que motivaron
                        # W_INICIO_SIMBOLICO. Ligando a cajas, `usa` refleja
                        # produccion EFECTIVA y el escape desaparece.
                        cajas_g = [m.cajas[(d, x, l)] for x in skus_g]
                        # BIG: cota superior valida para la suma de cajas del grupo
                        # ese dia. cap_dia esta en unidades y u_por_caja >= 1, asi
                        # que cap_dia + 1 acota la suma en cajas con holgura. Se
                        # evita leer el dominio de la variable (API interna de
                        # OR-Tools, fragil entre versiones).
                        # Cota CONSERVADORA: cada SKU aporta a lo sumo ~cap_dia
                        # cajas (upc>=1), y la capacidad agregada admite sobrecarga
                        # penalizada, asi que se multiplica por el nº de SKU del
                        # grupo. Un BIG holgado relaja algo la propagacion, pero un
                        # BIG invalido permitiria usa=0 CON produccion, que es
                        # exactamente el escape que se esta cerrando.
                        _big_g = (int(cap_dia.get((d, l), 0) or 0) + 1) * max(1, len(skus_g))
                        m.model.Add(sum(cajas_g) <= _big_g * u)   # produce -> usa=1
                        m.model.Add(u <= sum(cajas_g))            # no produce -> usa=0
                        a = m.model.NewBoolVar(f"arrg_{_nivel}_{d_idx}_{g}_{l}")
                        _arr[(d, g, l)] = a
                        m.arranques_grupo[(_nivel, d, g, l)] = a
                        prev = _usa.get((horizonte[d_idx - 1], g, l)) if d_idx > 0 else None
                        if prev is None:
                            m.model.Add(a >= u)
                        else:
                            m.model.Add(a >= u - prev)
                        m.model.Add(a <= u)
            _por_sem: dict = {}
            for (d, g, l), a in _arr.items():
                _por_sem.setdefault((semana_iso_inicio(d).isoformat(), g, l), []).append(a)
            # SECUENCIA_MAX_BLOQUES=0 -> no se agrega la cota dura: las variables
            # `arranca` se crean igual y el agrupamiento se logra por PRECIO
            # (W_CAMBIO_*_K). Es el modo recomendado: nunca infactible y el solver
            # puede ceder si agrupar costaria servicio.
            if SECUENCIA_MAX_BLOQUES > 0:
                for _k, _vs in _por_sem.items():
                    if len(_vs) > 1:
                        m.model.Add(sum(_vs) <= SECUENCIA_MAX_BLOQUES)
                        _nr += 1

            # ── ORDEN: una sola transicion por par de grupos ─────────────────
            # Con n grupos activos en la semana se permiten n-1 dias con mas de un
            # grupo. Ese dia extra es la TRANSICION (el cambio ocurre dentro del
            # dia), asi que los bloques quedan "uno primero y el otro despues" sin
            # prohibir el dia compartido ni desperdiciar capacidad.
            # No genera infactibilidad: si un grupo no cabe en los dias que le
            # quedan, el faltante cae en QUIEBRE (blando), igual que el acople de
            # granel.
            # (05-08) El ORDEN se aplica SOLO EN C. Medido en la corrida de las
            # 09:09: con las 474 restricciones de precedencia activas en A, la
            # pasada A paso de OPTIMAL gap=0.0 a FEASIBLE_TIMEOUT gap=6.94 -> el
            # Q* deja de ser confiable y la barrera que hereda C se construye
            # sobre una cota mala.
            # Y conceptualmente no corresponde: A es indiferente al volumen
            # (W_DEF=W_EXC=0), su unica mision es determinar que quiebres son
            # INEVITABLES. El orden es una preferencia de eficiencia operativa, no
            # de servicio: pertenece a C. Mismo principio asimetrico que W_ALT.
            if _nivel in _ord and es_pasada_c:
                _no = _nf = 0
                # (semana, linea) -> {grupo: [usa por dia]}
                _sem_g: dict = {}
                for (d, g, l2), u_ in _usa.items():
                    w = semana_iso_inicio(d).isoformat()
                    _sem_g.setdefault((w, l2), {}).setdefault(g, []).append((d, u_))
                for (w, l2), gs in _sem_g.items():
                    if len(gs) < 2:
                        continue
                    # `usado[g]` = el grupo aparece en la semana
                    usado = {}
                    for g, pares in gs.items():
                        ug = m.model.NewBoolVar(f"usado_{_nivel}_{w}_{g}_{l2}")
                        for _d, u_ in pares:
                            m.model.Add(ug >= u_)
                        m.model.Add(ug <= sum(u_ for _d, u_ in pares))
                        usado[g] = ug
                    # dias con MAS de un grupo: a lo sumo (n_usados - 1)
                    dias_w = sorted({d for pares in gs.values() for d, _u in pares})
                    extras = []
                    for d in dias_w:
                        us_d = [u_ for g, pares in gs.items() for dd, u_ in pares if dd == d]
                        if len(us_d) < 2:
                            continue
                        e = m.model.NewIntVar(0, len(us_d), f"extra_{_nivel}_{d}_{l2}")
                        m.model.Add(e >= sum(us_d) - 1)
                        extras.append(e)
                    if extras:
                        m.model.Add(sum(extras) <= sum(usado.values()) - 1)
                        _no += 1
                    # ORDEN FIJO dentro del nivel (p.ej. vinagre antes que limon).
                    # La clave del nivel es acumulada ("emb|fam"), asi que la
                    # precedencia se aplica entre grupos que comparten prefijo:
                    # dentro de CADA embalaje, las familias van en orden.
                    if _ord_fam and "|" in next(iter(gs), ""):
                        def _pos(_g):
                            suf = _g.split("|")[-1]
                            return _ord_fam.index(suf) if suf in _ord_fam else 99
                        for g1 in gs:
                            for g2 in gs:
                                if g1 == g2:
                                    continue
                                if g1.split("|")[:-1] != g2.split("|")[:-1]:
                                    continue      # distinto embalaje: no aplica
                                if _pos(g1) >= _pos(g2):
                                    continue      # solo pares (anterior, posterior)
                                # g1 va antes que g2: prohibido g2 en d y g1 en d'>d
                                m1 = dict(gs[g1]); m2 = dict(gs[g2])
                                for d in dias_w:
                                    for dp in dias_w:
                                        if dp <= d:
                                            continue
                                        if d in m2 and dp in m1:
                                            m.model.Add(m2[d] + m1[dp] <= 1)
                                            _nf += 1
                logger.info(f"[SECUENCIA] ORDEN en {_nivel}: {_no} semanas con "
                            f"cota de transiciones, {_nf} restricciones de "
                            f"precedencia (orden={_ord_fam or 'libre'})")

            logger.info(f"[SECUENCIA] contiguidad N{_i_niv+1}={_nivel} "
                        f"(clave={'+'.join(_niv[:_i_niv+1])}) ON | lineas="
                        f"{sorted(_lineas_n) or 'TODAS'} | grupos="
                        f"{sum(len(v) for v in _por_l.values())} | "
                        f"{len(_usa)} usa, {len(_arr)} arranques, {_nr} restricciones")

    # ─── Restricciones agregadas por (d, l) ──────────────────────────────────

    # V6.37: Pre-cómputo de ocupación por OFs aprobadas
    # ----------------------------------------------------------------
    # Para cada (fecha_lanzamiento, linea) suma de unidades aprobadas y
    # conjunto de SKUs aprobados. Se usa para:
    #   (a) descontar cap_dia en R1a (capacidad fisica ocupada),
    #   (b) descontar slot N_MAX en R1b (numero de SKUs distintos),
    #   (c) prohibir OFTs nuevas del mismo SKU ya aprobado ese (d, l),
    #   (d) ajustar R12 (la "primera del dia gratis" es la aprobada si existe).
    # Las aprobadas se siguen modelando como entrada de stock en el balance
    # via _entradas_del_dia(); este pre-computo es el lado "ocupacion de recurso".
    # ----------------------------------------------------------------
    aprobadas_u_dl: dict[tuple[date, str], int] = {}
    aprobadas_skus_dl: dict[tuple[date, str], set] = {}
    sobrecargas_aprobadas: list[dict] = []

    for sku_ap, lst in entradas_aprobadas.items():
        for e in lst:
            fl = e.get("fecha_lanzamiento")
            ln = e.get("linea", "")
            u_ap = int(e.get("cantidad_u", 0) or 0)
            if not isinstance(fl, date) or not ln or u_ap <= 0:
                continue
            key = (fl, ln)
            aprobadas_u_dl[key] = aprobadas_u_dl.get(key, 0) + u_ap
            aprobadas_skus_dl.setdefault(key, set()).add(sku_ap)

    # Detectar (linea, dia) ya saturados solo por aprobadas (politica decidida:
    # se asume capacidad libre 0 con advertencia, el operador decide que hacer).
    for (d_ap, l_ap), u_ap in aprobadas_u_dl.items():
        cap = cap_dia.get((d_ap, l_ap), 0)
        n_ap = len(aprobadas_skus_dl[(d_ap, l_ap)])
        cap_excedida = u_ap > cap
        nmax_excedido = n_ap > N_MAX_SKUS_DIA_LINEA
        if cap_excedida or nmax_excedido:
            motivos = []
            if cap_excedida:
                motivos.append(f"cap excedida ({u_ap}u > {cap}u)")
            if nmax_excedido:
                motivos.append(f"N_max excedido ({n_ap} SKUs > {N_MAX_SKUS_DIA_LINEA})")
            sobrecargas_aprobadas.append({
                "linea": l_ap,
                "fecha": d_ap.isoformat(),
                "u_aprobadas": u_ap,
                "cap_dia": cap,
                "n_skus_aprobados": n_ap,
                "n_max": N_MAX_SKUS_DIA_LINEA,
                "motivo": " + ".join(motivos),
            })

    if sobrecargas_aprobadas:
        logger.warning(
            f"[V6.37] {len(sobrecargas_aprobadas)} (linea,dia) saturados solo "
            f"por OFs aprobadas - se asume capacidad libre 0 ese par. "
            f"Detalle: {sobrecargas_aprobadas}"
        )

    # Exponer en el modelo para que se propague en _post_procesar -> diag
    m.sobrecargas_aprobadas = sobrecargas_aprobadas

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
            #
            # V6.37: el lado derecho es cap_libre = max(0, cap_l_d - u_aprobadas[d,l]).
            # Si cap_libre = 0, sum(terms) <= 0 fuerza cajas=0 ese (d,l) (variables >= 0).
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
                # V6.37: restar unidades de OFs aprobadas ya ocupando este (d, l)
                u_ap_dl = aprobadas_u_dl.get((d, l), 0)
                cap_libre_u = max(0, cap_l_d - u_ap_dl)
                m.model.Add(sum(terms) <= cap_libre_u * FACTOR_ESCALA)

            # R1b (v1.3, R2): cap. de nº de SKUs distintos asignados a esta línea-día.
            # N1 acota Σ_k asig[d,k,l] ≤ 4 para que el sub-problema de N2
            # (sequencer.py) sea siempre pequeño.
            # V6.37: SKUs ya aprobados ese (d,l) ocupan slot (decuento de N_MAX) y
            # se prohibe OFT nueva del mismo SKU (decision A: operador edita la OF
            # existente en lugar de tener una OFT paralela).
            skus_ap_dl = aprobadas_skus_dl.get((d, l), set())
            n_ap_dl = len(skus_ap_dl)
            n_max_libre = max(0, N_MAX_SKUS_DIA_LINEA - n_ap_dl)

            # Prohibir OFT nueva (asig=1) para SKUs ya aprobados ese (d, l)
            for s in skus_ap_dl:
                if l in m.pares_sku_linea[s]:
                    m.model.Add(m.asig[(d, s, l)] == 0)

            # SKUs candidatos a OFT nueva ese (d, l)
            asigs_dl = [
                m.asig[(d, s, l)]
                for s in m.skus
                if l in m.pares_sku_linea[s] and s not in skus_ap_dl
            ]
            if asigs_dl:
                m.model.Add(sum(asigs_dl) <= n_max_libre)
                # R12 (v1.3, decisión Gerente 05/05/2026): el primer SKU del día
                # en esta línea NO paga setup.
                # V6.37 (decision B): si hay aprobadas ese (d,l), la "primera del
                # dia gratis" YA es una aprobada (la linea fisicamente arranco con
                # ella). Todas las OFTs nuevas pagan setup -> inicios >= asigs (no -1).
                inicios_dl = [
                    m.inicio[(d, s, l)]
                    for s in m.skus
                    if l in m.pares_sku_linea[s] and s not in skus_ap_dl
                ]
                if n_ap_dl == 0:
                    # Sin aprobadas: R12 estándar (la primera nueva es gratis)
                    m.model.Add(sum(inicios_dl) >= sum(asigs_dl) - 1)
                else:
                    # Con aprobadas: todas las OFTs nuevas pagan setup
                    m.model.Add(sum(inicios_dl) >= sum(asigs_dl))

    # ─── Restricciones por (d, s) ────────────────────────────────────────────

    for d_idx, d in enumerate(horizonte):
        for s in skus:
            sp = sku_params[s]
            upc = m.u_por_caja[s]
            cap_bodega = int(sp.get("cap_bodega_u", 1_000_000) or 1_000_000)
            ss_dias = int(sp.get("ss_dias", 0) or 0)

            # Balance de stock (en unidades)
            entrada_d = _entradas_del_dia(s, d, entradas_aprobadas)
            demanda_consumo_d = int(round(demanda_consumo[s].get(d, 0.0)))   # piso N1 (balance/quiebre)
            demanda_ss_base_d = int(round(demanda_ss_base[s].get(d, 0.0)))   # target SS (N2)
            prod_u_total_d = sum(
                upc * m.cajas[(d, s, l)] for l in m.pares_sku_linea[s]
            )

            # (04-08) Balance en DOS pasos. Algebraicamente identico al anterior
            # (stock_u = prev + entrada - demanda + prod), pero expone el piso del
            # dia: stock_disp = lo disponible tras servir la demanda y ANTES de la
            # produccion de ese dia. La produccion entra al CIERRE.
            if d_idx == 0:
                stock_prev_val = int(round(stock_inicial.get(s, 0)))
                m.model.Add(
                    m.stock_disp[(d, s)] == stock_prev_val + entrada_d - demanda_consumo_d
                )
            else:
                stock_prev = m.stock_u[(horizonte[d_idx - 1], s)]
                m.model.Add(
                    m.stock_disp[(d, s)] == stock_prev + entrada_d - demanda_consumo_d
                )
            m.model.Add(m.stock_u[(d, s)] == m.stock_disp[(d, s)] + prod_u_total_d)

            # Variable sobre la que se juzga FALTA (quiebre / deficit vs SS).
            # El EXCESO se sigue juzgando sobre el cierre (m.stock_u).
            _v_falta = m.stock_disp[(d, s)] if QUIEBRE_INTRADIA_SOLVER else m.stock_u[(d, s)]

            # Déficit bajo SS (SS dinámico, en unidades)
            # V-OV: base = forecast SOLO (los pedidos NO inflan el SS; van al balance).
            if SS_COBERTURA:
                # Fórmula de cobertura: suma del forecast de los próximos ss_dias
                # días hábiles desde d (inclusive). NO colapsa en findes/feriados.
                _fc_ext_s = (ss_forecast_ext or {}).get(s) or demanda_ss_base.get(s) or {}
                ss_d = int(round(calcular_ss_diario(_fc_ext_s, d, ss_dias)))
            else:
                # Fórmula legacy: forecast del día × ss_dias (colapsa a 0 en findes).
                ss_d = demanda_ss_base_d * ss_dias

            # Compatibilidad: mantenemos deficit/exceso/quiebre ligados (post-proceso
            # y otras lecturas). El OBJETIVO usa los tramos en % del SS (abajo).
            m.model.Add(m.deficit[(d, s)] >= ss_d - _v_falta)
            m.model.Add(m.exceso[(d, s)] >= m.stock_u[(d, s)] - cap_bodega)
            m.model.Add(m.quiebre[(d, s)] >= -_v_falta)  # V6.18: >0 solo si stock<0

            big_ub_s = 100 * cap_bodega

            # ── Evento de quiebre por (SKU, semana ISO): binaria UNIFORME entre SKU ──
            # (11-07, SS_COBERTURA) Se crea/liga SIEMPRE, fuera de la bifurcación de
            # SS, para que un quiebre de CUALQUIER día (findes/feriados incluidos)
            # dispare el evento de su semana. Sigue siendo UN binario por (SKU,semana)
            # gracias al guard `not in` -> NO infla el conteo de binarios ni el gap.
            # Castigo por EVENTO uniforme (no magnitud) -> sin sesgo por velocidad.
            # Con el flag OFF, esto NO corre (el evento se crea solo en rama ss_d>0,
            # como el comportamiento legacy).
            if SS_COBERTURA:
                w = semana_iso_inicio(d).isoformat()
                if (s, w) not in m.evento_qbr:
                    m.evento_qbr[(s, w)] = m.model.NewBoolVar(f"evq_{s}_{w}")
                m.model.Add(m.evento_qbr[(s, w)] * big_ub_s >= m.quiebre[(d, s)])

            if ss_d > 0:
                # ── Curva convexa en % del SS ─────────────────────────────────
                # Déficit descompuesto en tramos (unidades). La suma cubre el
                # déficit total; el solver llena primero el tramo más barato
                # (coeficientes crecientes) -> convexidad sin binarios.
                lim_leve = int(FRAC_DEF_LEVE * ss_d)               # 0..-50% del SS
                lim_grave = int((FRAC_DEF_GRAVE - FRAC_DEF_LEVE) * ss_d)  # -50..-100%
                m.def_leve[(d, s)] = m.model.NewIntVar(0, max(1, lim_leve), f"dfl_{d_idx}_{s}")
                m.def_grave[(d, s)] = m.model.NewIntVar(0, max(1, lim_grave), f"dfg_{d_idx}_{s}")
                m.qbr_mag[(d, s)] = m.model.NewIntVar(0, big_ub_s, f"qmg_{d_idx}_{s}")
                # suma de tramos >= déficit total (ss_d - stock); >=0 implícito
                m.model.Add(
                    m.def_leve[(d, s)] + m.def_grave[(d, s)] + m.qbr_mag[(d, s)]
                    >= ss_d - _v_falta
                )

                # Exceso SOBRE SS descompuesto (leve 0..+100%, alto >+100%)
                lim_exc_leve = int(FRAC_EXC_LEVE * ss_d)
                m.exc_leve[(d, s)] = m.model.NewIntVar(0, max(1, lim_exc_leve), f"exl_{d_idx}_{s}")
                m.exc_alto[(d, s)] = m.model.NewIntVar(0, big_ub_s, f"exa_{d_idx}_{s}")
                m.model.Add(
                    m.exc_leve[(d, s)] + m.exc_alto[(d, s)] >= m.stock_u[(d, s)] - ss_d
                )

                # Coeficientes por unidad, escalados: W_tramo · 100 · ESCALA / SS
                m.coef_def_leve[(d, s)] = int(round(W_DEF_LEVE * 100 * ESCALA_OBJ / ss_d))
                m.coef_def_grave[(d, s)] = int(round(W_DEF_GRAVE * 100 * ESCALA_OBJ / ss_d))
                m.coef_qbr_mag[(d, s)] = int(round(W_QBR_MAG * 100 * ESCALA_OBJ / ss_d))
                m.coef_exc_leve[(d, s)] = int(round(W_EXC_LEVE * 100 * ESCALA_OBJ / ss_d))
                m.coef_exc_alto[(d, s)] = int(round(W_EXC_ALTO * 100 * ESCALA_OBJ / ss_d))

                if not SS_COBERTURA:
                    # LEGACY: evento_qbr solo en rama ss_d>0 (agujero de finde).
                    w = semana_iso_inicio(d).isoformat()
                    if (s, w) not in m.evento_qbr:
                        m.evento_qbr[(s, w)] = m.model.NewBoolVar(f"evq_{s}_{w}")
                    m.model.Add(m.evento_qbr[(s, w)] * big_ub_s >= m.quiebre[(d, s)])
            else:
                # SS = 0: no hay banda %-del-SS que medir. Freno a llenar bodega
                # (siempre) y, SOLO si hay demanda ese día (MTO/pedido), quiebre
                # ABSOLUTO por unidad para que N1 no lo deje quebrar.
                # V-OV-fix (10-07): SIN evento_qbr (bool) y gateado por demanda. El
                # binario se creaba en CADA celda ss_d==0 (findes/feriados de TODOS
                # los SKU) -> cientos de booleanos inútiles que inflaban el espacio
                # de búsqueda y degradaban el gap (37% a 1800s el 10-07). El castigo
                # por unidad (IntVar) alcanza para forzar producción del MTO.
                # (11-07 SS_COBERTURA ON: el evento_qbr ya se creó arriba, uniforme,
                # así que un MTO en quiebre también dispara su evento semanal.)
                m.exc_bodega[(d, s)] = m.model.NewIntVar(0, big_ub_s, f"exb_{d_idx}_{s}")
                m.model.Add(m.exc_bodega[(d, s)] >= m.stock_u[(d, s)] - cap_bodega)
                if demanda_consumo_d > 0:
                    m.qbr_mag[(d, s)] = m.model.NewIntVar(0, big_ub_s, f"qmg0_{d_idx}_{s}")
                    m.model.Add(m.qbr_mag[(d, s)] >= -_v_falta)
                    m.coef_qbr_mag[(d, s)] = int(W_QBR_ABS * ESCALA_OBJ)

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
    w_alt: int = W_ALT,
) -> None:
    """Añade la función objetivo multi-criterio al modelo.

    v1.2: penalizamos cada inicio de corrida (W_SETUP) en vez del slack mal
    formulado de v1.0. Esto incentiva consolidar producción naturalmente.
    """

    obj_terms = []

    # N2 (03-07): penalización por DESVIACIÓN % del SS (curva convexa) + evento
    # uniforme de quiebre. Reemplaza la penalización por-unidad (W_DEFICIT/
    # W_EXCESO/W_QUIEBRE) que sesgaba contra SKU lentos bajo capacidad ajustada.

    # Déficit progresivo (0..-50%, -50..-100%) y quiebre-magnitud (<-100%)
    for (d, s), v in m.def_leve.items():
        obj_terms.append(m.coef_def_leve[(d, s)] * v)
    for (d, s), v in m.def_grave.items():
        obj_terms.append(m.coef_def_grave[(d, s)] * v)
    for (d, s), v in m.qbr_mag.items():
        obj_terms.append(m.coef_qbr_mag[(d, s)] * v)   # castigo doble (1/2): magnitud

    # Exceso sobre SS progresivo (leve < alto), menor que el déficit
    for (d, s), v in m.exc_leve.items():
        obj_terms.append(m.coef_exc_leve[(d, s)] * v)
    for (d, s), v in m.exc_alto.items():
        obj_terms.append(m.coef_exc_alto[(d, s)] * v)

    # Exceso vs cap_bodega cuando SS=0 (único freno sin demanda)
    for (d, s), v in m.exc_bodega.items():
        obj_terms.append(W_EXC_BODEGA_SS0 * ESCALA_OBJ * v)

    # Evento de quiebre UNIFORME por (SKU, semana): rompe el sesgo de factor.
    # Castigo doble (2/2): evitar QUE un SKU quiebre pesa igual para todos.
    for (s, w), b in m.evento_qbr.items():
        obj_terms.append(W_QBR_EVENTO * ESCALA_OBJ * b)

    # Penalizar asignación a línea alternativa (preferir la preferida)
    pref_map: dict[tuple[str, str], bool] = {}
    for s, entries in sku_a_lineas.items():
        for e in entries:
            pref_map[(s, e["linea"])] = bool(e.get("preferida", False))
    for (d, s, l), asig in m.asig.items():
        if not pref_map.get((s, l), True):
            # Es alternativa → penalizamos suavemente
            obj_terms.append(w_alt * asig)

    # (05-08) Costo de cambio de grupo, jerarquico. m.arranques_grupo solo se
    # llena en la pasada C (la secuenciacion no corre en A), asi que este termino
    # es automaticamente asimetrico. El primer arranque de la semana no se
    # descuenta: es constante para todos los planes y no afecta la comparacion.
    _n_pen = 0
    for (_niv_g, _d, _g, _l), _a in m.arranques_grupo.items():
        _k = W_CAMBIO_GRUPO_K.get(_niv_g, 0)
        if _k > 0:
            obj_terms.append(_k * ESCALA_OBJ * _a)
            _n_pen += 1
    if _n_pen:
        logger.info(f"[SECUENCIA] costo de cambio de grupo en objetivo: "
                    f"{_n_pen} terminos | pesos="
                    + str({k: v for k, v in W_CAMBIO_GRUPO_K.items() if v}))

    # R12: peso simbólico para evitar inicios fantasma (ver Paso 3 del doc R12).
    # Sin este peso, la cota Σ inicio >= Σ asig - 1 deja al solver indiferente
    # entre Σ inicio = N-1 y Σ inicio = N cuando hay holgura de capacidad. El
    # término ε=1 desempata hacia el menor valor factible. NO usarlo para
    # consolidar corridas — esa optimización es trabajo de N2/F2.
    for (d, s, l), inicio in m.inicio.items():
        obj_terms.append(W_INICIO_SIMBOLICO * inicio)

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
        "sobrecargas_aprobadas": [],  # V6.37
    }


# =============================================================================
# Post-procesamiento
# =============================================================================

def _calcular_gap(solver, objective_value, status_name):
    """Gap de optimalidad CP-SAT en %, consistente con _n2_gap_1800.py:
        gap% = (objective - best_bound) / |objective| * 100
    Devuelve None si no aplica (INFEASIBLE / sin objetivo / |obj| ~ 0).
    """
    if status_name in ("INFEASIBLE", "MODEL_INVALID", "TIMEOUT_SIN_SOLUCION"):
        return None
    try:
        bound = solver.BestObjectiveBound()
    except Exception:
        return None
    if abs(objective_value) <= 1e-9:
        return None
    return (objective_value - bound) / abs(objective_value) * 100.0


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
    demanda_ss_base: dict[str, dict[date, float]] | None = None,
    demanda_consumo: dict[str, dict[date, float]] | None = None,
    stock_inicial: dict[str, float] | None = None,
    ss_forecast_ext: dict[str, dict[date, float]] | None = None,
    entradas_aprobadas: dict[str, list[dict]] | None = None,
    pedidos_abiertos: dict[str, dict[date, float]] | None = None,
) -> dict[str, Any]:
    """Convierte la solución del solver en OFTs, stock visible y alertas.

    Params nuevos (11-07, dashboard diario plan-consistente):
      demanda_ss_base : forecast diario por SKU (para SS y display de forecast)
      demanda_consumo : max(forecast, pedidos) por SKU (demanda corregida)
      stock_inicial   : stock disponible inicial por SKU (ya rebajado por OV, sin clamp)
      ss_forecast_ext : forecast diario EXTENDIDO ~ss_dias hábiles más allá del
                        horizonte, para que el SS de los últimos días no se
                        subestime (ventana de cobertura completa).
    """

    gap = _calcular_gap(solver, objective_value, status_name)

    ofts: list[dict] = []
    stock_diario: dict[str, dict[str, int]] = {}
    alertas: list[dict] = []
    uso_linea: dict[str, dict[str, float]] = {l: {} for l in m.lineas}

    # ─── OFTs (una por día con producción) ──────────────────────────────────
    # oft_por_dia: índice (sku, fecha_iso) -> lista de cantidades, para poblar
    # el detalle_diario del dashboard sin re-recorrer. numero_of se asigna
    # después (en cron/main), acá guardamos la cantidad como referencia.
    oft_por_dia: dict[tuple[str, str], list[int]] = {}
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
                oft_por_dia.setdefault((s, d.isoformat()), []).append(cajas_v)

    # ─── (V6) Calendario de granel elegido ───────────────────────────────────
    # Volcado al log para comparar reproducibilidad entre corridas (Paso 1). Sin
    # esto el modo semanal es invisible: el solver lo decide y no queda rastro.
    if CAMPANA_GRANEL_ENABLED and m.granel:
        _cal = {}
        for (_w, _modo), _v in m.granel.items():
            if solver.Value(_v) == 1:
                _cal[_w] = _modo
        _txt = " | ".join(f"{_w}:{_cal.get(_w, 'ninguno')}"
                          for _w in sorted({k[0] for k in m.granel}))
        logger.info(f"[CAMPANA] calendario granel -> {_txt}")
    if CAMPANA_FORMATO_ENABLED and m.formato:
        _lins = sorted({k[0] for k in m.formato})
        for _lin in _lins:
            _sem = sorted({k[1] for k in m.formato if k[0] == _lin})
            _act = {}
            for (_l, _w, _f), _v in m.formato.items():
                if _l == _lin and solver.Value(_v) == 1:
                    _act[_w] = _f
            logger.info(f"[CAMPANA] calendario formato {_lin} -> "
                        + " | ".join(f"{w}:{_act.get(w, 'libre')}" for w in _sem))
            # Persistir la propuesta (fijado=FALSE) para el dashboard, sin tocar
            # las semanas con pin: su fila ya tiene fijado=TRUE.
            _rec = m.formato_recurso.get(_lin)
            if _rec:
                try:
                    from db_mrp import upsert_campana_pin as _upin
                    from datetime import date as _d2
                    _fij = set(m.formato_pins.get(_lin, {}) or {})
                    for _w in _sem:
                        if _w in _fij:
                            continue
                        _upin(_rec, _d2.fromisoformat(_w), _act.get(_w, ""),
                              fijado=False, autor="solver")
                except Exception as _e:
                    logger.warning(f"[CAMPANA] no se pudo persistir formato {_lin} ({_e})")
        # Persistir la propuesta (fijado=FALSE) para que el dashboard la muestre.
        # Las semanas con pin NO se tocan: su fila ya tiene fijado=TRUE y
        # sobrescribirla borraria la decision del planificador.
        try:
            from db_mrp import upsert_campana_pin
            from datetime import date as _date
            _ya_fijadas = set(getattr(m, "granel_pins", {}) or {})
            for _w in sorted({k[0] for k in m.granel}):
                if _w in _ya_fijadas:
                    continue
                upsert_campana_pin("GRANEL_SALSAS", _date.fromisoformat(_w),
                                   _cal.get(_w, ""), fijado=False, autor="solver")
        except Exception as _e:
            logger.warning(f"[CAMPANA] no se pudo persistir el calendario ({_e})")

    # ─── Stock visible y alertas ─────────────────────────────────────────────
    for s in m.skus:
        stock_diario[s] = {}
        sp = sku_params[s]
        upc = m.u_por_caja[s]
        cap_bodega = int(sp.get("cap_bodega_u", 1_000_000) or 1_000_000)

        # (03-08) quiebre intradia: se evalua sobre el stock al INICIO del dia
        stock_prev_disp = float((stock_inicial or {}).get(s, 0.0))
        consumo_s = (demanda_consumo or {}).get(s) or {}
        for d in horizonte:
            stock_real = solver.Value(m.stock_u[(d, s)])
            stock_visible = max(0, stock_real)
            stock_diario[s][d.isoformat()] = stock_visible

            consumo_d = int(round(consumo_s.get(d, 0.0)))
            stock_disp = stock_prev_disp - consumo_d   # (03-08) piso del dia (pre-produccion)
            deficit_v = solver.Value(m.deficit[(d, s)])
            exceso_v = solver.Value(m.exceso[(d, s)])

            # (03-08) Alerta de quiebre INTRADIA: demanda no servible con el stock
            # al inicio del dia (la produccion del mismo dia entra al cierre).
            if stock_disp < 0:
                alertas.append({
                    "sku": s,
                    "fecha": d.isoformat(),
                    "tipo": "QUIEBRE",
                    "mensaje": f"Demanda no cubierta: {-int(round(stock_disp))} unidades",
                    "deficit_u": -int(round(stock_disp)),
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

            stock_prev_disp = stock_real   # (03-08) cierre de hoy = inicio de manana

    # ─── Detalle diario y encabezado por SKU (dashboard plan-consistente) ─────
    # (11-07) Fuente ÚNICA para la pestaña Stock Diario. Todo en UNIDADES, sin
    # clamp (el stock_diario de arriba SÍ clampea a 0 para gráficos legacy; acá
    # guardamos el real para ver quiebres y disponibles negativos). El SS usa la
    # fórmula de cobertura (calcular_ss_diario) sobre forecast extendido.
    detalle_diario: dict[str, dict[str, dict]] = {}
    encabezado_sku: dict[str, dict] = {}
    _dss = demanda_ss_base or {}
    _dco = demanda_consumo or {}
    _sti = stock_inicial or {}
    _ssext = ss_forecast_ext or {}
    _ea = entradas_aprobadas or {}
    _pcrudo = pedidos_abiertos or {}   # (22-07) OV cruda por SKU/fecha (cajas), pre-netting

    for s in m.skus:
        sp = sku_params[s]
        upc = m.u_por_caja[s]
        ss_dias = int(sp.get("ss_dias", 0) or 0)
        fc_ext_s = _ssext.get(s) or _dss.get(s) or {}   # extendido si está, si no el del horizonte
        fc_base_s = _dss.get(s) or {}
        consumo_s = _dco.get(s) or {}
        pcrudo_s = _pcrudo.get(s) or {}   # (22-07) OV cruda del SKU: {fecha: cajas}

        serie = {}
        stock_prev_disp = float(_sti.get(s, 0.0))   # disponible inicial (sin clamp)
        stock_min = None
        stock_final = 0

        for d in horizonte:
            d_iso = d.isoformat()
            stock_real = solver.Value(m.stock_u[(d, s)])       # cierre del día (sin clamp)
            fc_d = fc_base_s.get(d, 0.0)                        # forecast del día
            consumo_d = consumo_s.get(d, 0.0)                  # max(fc, pedidos)
            pedidos_d = max(0.0, consumo_d - fc_d)             # OV del día = consumo - forecast (si >0)
            # (22-07) OV cruda real del día (cajas -> unidades), ANTES del netting max(fc,ov).
            # Distinto de pedidos_d (que es solo el exceso sobre forecast). Es informativo;
            # NO entra en ningún cálculo de balance/optimización, solo para el dashboard.
            pedidos_crudos_d = float(pcrudo_s.get(d, 0.0)) * upc
            ss_d = calcular_ss_diario(fc_ext_s, d, ss_dias)    # SS cobertura (fórmula nueva)

            # (03-08) Quiebre INTRADIA: la demanda del dia se sirve con el stock
            # al INICIO del dia (stock_prev_disp), NO con el cierre (stock_real,
            # que ya incluye la produccion del mismo dia -> entra al cierre, se ve
            # en D+1). stock_disp = piso del dia; es lo que grafica la curva
            # "Stock disponible" y define el estado QUIEBRE.
            stock_disp = stock_prev_disp - consumo_d
            if stock_disp < 0:
                estado = "QUIEBRE"
            elif ss_d > 0 and stock_real < ss_d:
                estado = "BAJO_SS"
            else:
                estado = "OK"

            oft_cajas = oft_por_dia.get((s, d_iso))
            entrada_apr_d = _entradas_del_dia(s, d, _ea)  # (13-07) para recalculo live
            serie[d_iso] = {
                "stock_ini_disp_u": int(round(stock_prev_disp)),
                "stock_disp_u": int(round(stock_disp)),
                "entrada_aprobada_u": int(round(entrada_apr_d)),
                "pedidos_u": int(round(pedidos_d)),
                "pedidos_crudos_u": int(round(pedidos_crudos_d)),
                "demanda_corr_u": int(round(consumo_d)),
                "forecast_u": int(round(fc_d)),
                "stock_fin_u": int(stock_real),
                "ss_u": int(round(ss_d)),
                "oft_cajas": int(sum(oft_cajas)) if oft_cajas else None,
                "estado": estado,
            }

            stock_min = stock_real if stock_min is None else min(stock_min, stock_real)
            stock_final = stock_real
            stock_prev_disp = stock_real   # el cierre de hoy es el inicio de mañana

        detalle_diario[s] = serie
        encabezado_sku[s] = {
            "disponible_inicial_u": int(round(float(_sti.get(s, 0.0)))),
            "stock_final_u": int(stock_final),
            "stock_min_u": int(stock_min) if stock_min is not None else 0,
            "ss_dias": ss_dias,
            "u_por_caja": upc,
            # stock_fisico_u y comprometido_u se inyectan en cron/main (viven allí,
            # antes de la rebaja). Placeholder para que la clave exista siempre.
            "stock_fisico_u": None,
            "comprometido_u": None,
        }

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
        "detalle_diario": detalle_diario,     # (11-07) dashboard plan-consistente
        "encabezado_sku": encabezado_sku,     # (11-07) fis/comp se inyectan en cron/main
        "alertas": alertas,
        "uso_linea": uso_linea,
        "resumen": resumen,
        "gap": gap,
        "sobrecargas_aprobadas": getattr(m, "sobrecargas_aprobadas", []),  # V6.37
    }


# =============================================================================
# Wrapper LEGACY — firma compatible con v1.1 / main.py
# =============================================================================

# =============================================================================
# N2 — Orquestacion de dos pasadas con barrera Q* (13-07). Ver DEFINICION_N2_v2.
# =============================================================================
# A: N1-minimo (W_DEF=W_EXC=0) @ 8 workers -> define Q* (stock SIN clamp).
# C: SS-target (20/60/3/8) @ 1 worker + seed=42, sujeto a stock_u >= Q*.
# NO toca el termino de quiebre viejo (fidelidad con la validacion en scratchpad:
# A=C=280 dias-SKU, -641 colchon). Salva/restaura los globals del modulo.

def _build_qstar(resultado: dict) -> tuple[dict, int]:
    """Q*[(sku, dia_iso)] = piso del dia, crudo y sin clamp.

    (04-08) La variable DEBE ser la misma sobre la que el modelo juzga el quiebre,
    o A y la barrera hablan de cosas distintas: A minimizaria quiebres intradia y
    la barrera protegeria el cierre, dejando a C libre para hundir el piso sin
    violar ninguna cota. Medido en el plan #111: A dio Q*=58 inevitables y el plan
    final salio con 94 quiebres, 36 de ellos evitables segun A.

    Con QUIEBRE_INTRADIA_SOLVER=1 se usa stock_disp_u (inicio del dia menos la
    demanda del dia); si no, stock_fin_u como antes. Fallback a stock_fin_u para
    snapshots viejos que no traen el campo.
    """
    det = (resultado or {}).get("detalle_diario") or {}
    campo = "stock_disp_u" if QUIEBRE_INTRADIA_SOLVER else "stock_fin_u"
    q, n_neg = {}, 0
    for s, celdas in det.items():
        for d_iso, c in celdas.items():
            v = c.get(campo)
            if v is None:
                v = c.get("stock_fin_u")
            if v is not None:
                q[(s, d_iso)] = int(v)
                if v < 0:
                    n_neg += 1
    return q, n_neg


def _desglose_n2(resultado: dict) -> dict:
    """Bucket dias-SKU en quiebre/bajo_ss/exc_ss/ok, global y por linea. Replica
    el desglose del scratchpad _n2_ac_workers_asim.py (comparabilidad 280/-641)."""
    from collections import defaultdict
    det = (resultado or {}).get("detalle_diario") or {}
    ofts = (resultado or {}).get("ofts") or []
    cajas = defaultdict(lambda: defaultdict(float))
    for o in ofts:
        cj = float(o.get("cantidad_cajas", 0) or 0)
        if cj > 0:
            cajas[o.get("sku")][o.get("linea")] += cj
    mapa = {s: max(porl, key=porl.get) for s, porl in cajas.items()}
    g = dict(quiebre=0, bajo_ss=0, exc_ss=0, ok=0)
    por_linea = defaultdict(lambda: dict(quiebre=0, bajo_ss=0, exc_ss=0, ok=0))
    for s, celdas in det.items():
        ln = mapa.get(s) or "(sin linea)"
        for _d, c in celdas.items():
            sf = c.get("stock_fin_u")
            ss = c.get("ss_u") or 0
            if sf is None:
                continue
            k = ("quiebre" if sf < 0 else "bajo_ss" if (ss > 0 and sf < ss)
                 else "exc_ss" if (ss > 0 and sf > ss) else "ok")
            g[k] += 1
            por_linea[ln][k] += 1
    uso = ((resultado or {}).get("resumen") or {}).get("uso_promedio_lineas_pct") or {}
    return {"global": g, "por_linea": dict(por_linea), "uso": uso}


def _correr_dos_pasadas(**rich_kwargs) -> dict:
    """A (N1-min) -> captura Q* -> C (SS-target, barrera Q*) sobre inputs ricos ya
    preparados. Devuelve el resultado rico de C con resultado['n2_diag'] adjunto.
    Salva/restaura globals del modulo."""
    global W_DEF_LEVE, W_DEF_GRAVE, W_EXC_LEVE, W_EXC_ALTO
    global SOLVER_NUM_WORKERS, SOLVER_RANDOM_SEED, SS_COBERTURA

    _save = (W_DEF_LEVE, W_DEF_GRAVE, W_EXC_LEVE, W_EXC_ALTO,
             SOLVER_NUM_WORKERS, SOLVER_RANDOM_SEED, SS_COBERTURA)
    kwargs_A = dict(rich_kwargs, cotas_qstar=None, time_limit_sec=N2_TL_A)
    kwargs_C = dict(rich_kwargs, time_limit_sec=N2_TL_C)
    try:
        SS_COBERTURA = True  # N2 requiere cobertura ON (no colapsa en finde)

        # ── Pasada A: N1-minimo @ 8 workers -> define Q* ──
        W_DEF_LEVE = W_DEF_GRAVE = W_EXC_LEVE = W_EXC_ALTO = 0
        SOLVER_NUM_WORKERS = N2_WORKERS_A
        SOLVER_RANDOM_SEED = None
        logger.info(f"[N2] Pasada A (N1-min) @ {N2_WORKERS_A}w TL={N2_TL_A}s")
        resA = optimizar_plan_v12_rich(**kwargs_A)
        qstar, n_neg = _build_qstar(resA)
        logger.info(f"[N2] Q*: {len(qstar)} celdas, {n_neg} quiebre inevitables | "
                    f"A status={resA.get('status')} gap={resA.get('gap')}")

        # ── Pasada C: SS-target @ 1 worker + seed, barrera Q* ──
        W_DEF_LEVE = N2_PESOS_C["W_DEF_LEVE"]
        W_DEF_GRAVE = N2_PESOS_C["W_DEF_GRAVE"]
        W_EXC_LEVE = N2_PESOS_C["W_EXC_LEVE"]
        W_EXC_ALTO = N2_PESOS_C["W_EXC_ALTO"]
        SOLVER_NUM_WORKERS = N2_WORKERS_C
        SOLVER_RANDOM_SEED = N2_SEED_C
        kwargs_C["cotas_qstar"] = qstar
        logger.info(f"[N2] Pasada C (SS-target) @ {N2_WORKERS_C}w seed={N2_SEED_C} "
                    f"TL={N2_TL_C}s pesos={N2_PESOS_C} barrera={N2_BARRERA_MODO}")
        resC = optimizar_plan_v12_rich(**kwargs_C)
        logger.info(f"[N2] C status={resC.get('status')} gap={resC.get('gap')}")
    finally:
        (W_DEF_LEVE, W_DEF_GRAVE, W_EXC_LEVE, W_EXC_ALTO,
         SOLVER_NUM_WORKERS, SOLVER_RANDOM_SEED, SS_COBERTURA) = _save

    dA = _desglose_n2(resA)
    dC = _desglose_n2(resC)
    resC["n2_diag"] = {
        "A": {**dA, "gap": resA.get("gap"), "status": resA.get("status")},
        "C": {**dC, "gap": resC.get("gap"), "status": resC.get("status")},
        "qstar_celdas": len(qstar), "qstar_neg": n_neg,
    }
    return resC


def optimizar_plan(
    ordenes_mrp: list,
    sku_params: dict,
    lineas: dict,
    forecasts: dict,
    stocks_actuales: dict,
    entradas_fijas: dict | None = None,
    pedidos_abiertos: dict | None = None,
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
            # F3 (12/05/2026): para IMPORTACION usamos semana_emision directamente
            # como fecha_lanzamiento (no lunes ISO) porque MRP clasico genera
            # multiples OFTs del mismo SKU IMPORTACION en distintas semanas con
            # fechas de emision distintas; colapsarlas al lunes pierde el
            # discriminador y causa colisiones de numero_of (clave F3 es
            # (sku, fecha_lanzamiento, linea)).
            if o_dict.get("semana_emision"):
                o_dict["fecha_lanzamiento"] = o_dict["semana_emision"]
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
            # V6: granel_grupo y formato deben viajar hasta _construir_modelo o
            # el acoplamiento de campana queda en 0 acoples (fallo silencioso).
            # Este dict es una lista CERRADA de claves: lo que no se copia aca,
            # el modelo lo lee como None y la restriccion no se agrega.
            "granel_grupo": str(_attr(sp, "granel_grupo", "") or "").strip().lower(),
            "formato": str(_attr(sp, "formato", "") or "").strip(),
            "mto": bool(_attr(sp, "mto", False)),
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
    #
    # (D1, 27-07-2026) La cota SUPERIOR llegaba sólo al fin del horizonte y
    # descartaba las semanas que el SS de cobertura necesita (`_fecha_fin_ext`
    # = fecha_fin + 35 d). Resultado: aunque el forecast se generara largo, acá
    # se recortaba y el SS caía a cero en la cola del plan.
    # Se amplía +42 d (35 del margen SS + 7 de colchón). La cota INFERIOR no se
    # toca: es la que evita sumar el histórico de Prophet (ver FIX v1.2.1 abajo).
    # Ver DECISION_forecast_cobertura_y_reentrenamiento.md
    horizonte_dias_default = max(horizonte_semanas * 7, 14)
    fecha_inicio_default = date.today()
    fecha_fin_default = fecha_inicio_default + timedelta(days=horizonte_dias_default + 42)
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
            # V6.37: fecha_lanzamiento (= dia de produccion) y linea, para
            # descontar cap diaria (R1a) y slot N_MAX (R1b).
            fl_raw = e.get("fecha_lanzamiento", "")
            try:
                fl_obj = date.fromisoformat(str(fl_raw)[:10]) if fl_raw else None
            except ValueError:
                fl_obj = None
            entradas_aprobadas_rich.setdefault(sku, []).append({
                "fecha_entrada": fecha_obj,
                "fecha_lanzamiento": fl_obj,           # V6.37
                "linea": e.get("linea", "") or "",     # V6.37
                "cantidad_u": int(cj * upc),
                "numero_of": e.get("numero_of", ""),
            })

    # ─── 6b. V6.12-mini: filtrar SKUs con stock_inicial > cap_bodega ─────────
    # Defensivo: estos SKUs generan infactibilidad estructural en CP-SAT porque
    # la restricción stock_u[d,s] <= cap_bodega se viola desde el día 0.
    # Se filtran del modelo y se reporta al usuario para que ajuste cap_bodega
    # en SKU_PARAMS o revise el dato de stock.
    skus_filtrados_cap_bodega = []
    for sku in list(sku_params_rich.keys()):
        cap_u = sku_params_rich[sku].get("cap_bodega_u", 0) or 0
        stock_u = stock_inicial_rich.get(sku, 0) or 0
        if cap_u and stock_u > cap_u:
            upc = sku_params_rich[sku].get("u_por_caja", 1) or 1
            skus_filtrados_cap_bodega.append({
                "sku": sku,
                "descripcion": sku_params_rich[sku].get("descripcion", ""),
                "stock_actual_u": int(stock_u),
                "stock_actual_cj": round(stock_u / upc, 1),
                "cap_bodega_u": int(cap_u),
                "cap_bodega_cj": round(cap_u / upc, 1),
                "razon": "stock_inicial > cap_bodega (genera infactibilidad estructural)",
            })
            sku_params_rich.pop(sku, None)
            forecast_rich.pop(sku, None)
            stock_inicial_rich.pop(sku, None)
            entradas_aprobadas_rich.pop(sku, None)

    if skus_filtrados_cap_bodega:
        logger.warning(
            f"[V6.12-mini] {len(skus_filtrados_cap_bodega)} SKUs filtrados del optimizador "
            f"por stock>cap_bodega: {[s['sku'] for s in skus_filtrados_cap_bodega]}"
        )

    # ─── 7. Llamar al optimizador rico ───────────────────────────────────────
    horizonte_dias = max(horizonte_semanas * 7, 14)
    fecha_inicio = date.today()
    fecha_fin = fecha_inicio + timedelta(days=horizonte_dias - 1)

    # Time-limit segun el horizonte del picklist (4/8/13/17/26 sem).
    time_limit_sec = _time_limit_para(horizonte_semanas)
    logger.info(f"[optimizer] horizonte={horizonte_semanas} sem -> time_limit={time_limit_sec}s, workers={SOLVER_NUM_WORKERS}")

    _rich_kwargs = dict(
        plan_mrp={"ordenes": ordenes_mrp},
        sku_params=sku_params_rich,
        lineas_params=lineas_params_rich,
        sku_lineas=sku_lineas_rich,
        forecast_semanal=forecast_rich,
        stock_inicial=stock_inicial_rich,
        entradas_aprobadas=entradas_aprobadas_rich,
        pedidos_abiertos=pedidos_abiertos,
        fecha_inicio=fecha_inicio,
        horizonte_dias=horizonte_dias,
        time_limit_sec=time_limit_sec,
    )
    if N2_ENABLED:
        logger.info("[N2] N2_ENABLED=1 -> dos pasadas (A -> Q* -> C)")
        resultado = _correr_dos_pasadas(**_rich_kwargs)
    else:
        resultado = optimizar_plan_v12_rich(**_rich_kwargs)

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
            "stock_inicial_cajas": round(stock_inicial_rich.get(sku, 0) / upc, 1) if upc else 0.0,
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
        # FEASIBLE_TIMEOUT cuenta como optimizado: hay un plan operable, solo
        # que no se probo optimalidad. INFEASIBLE/TIMEOUT_SIN_SOLUCION no.
        "optimizado": resultado["status"] in ("OPTIMAL", "FEASIBLE", "FEASIBLE_TIMEOUT"),
        "status": resultado["status"],
        "tiempo_ms": int((resultado.get("solver_time_sec") or 0) * 1000),
        "objective_value": resultado.get("objective_value"),
        "gap": resultado.get("gap"),
        "ofts_generadas": len(ordenes_produccion),
        "ordenes_importacion_preservadas": len(ordenes_importacion),
        "alertas": {
            "quiebre": resultado["resumen"].get("alertas_quiebre", 0),
            "bajo_ss": resultado["resumen"].get("alertas_bajo_ss", 0),
            "exceso_bodega": resultado["resumen"].get("alertas_exceso_bodega", 0),
        },
        "uso_promedio_lineas_pct": resultado["resumen"].get("uso_promedio_lineas_pct", {}),
        "horizonte_dias": resultado["resumen"].get("horizonte_dias", horizonte_dias),
        "sobrecargas_aprobadas": resultado.get("sobrecargas_aprobadas", []),  # V6.37
        "n2": resultado.get("n2_diag"),  # (N2) desglose A/C si corrio dos pasadas
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
