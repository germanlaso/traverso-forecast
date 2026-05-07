# R12 — Primer SKU del día sin setup (regla nueva)

> **Documento técnico de implementación**. Pegáselo al Claude del nuevo chat o a Claude Code cuando vayan a implementar el cambio en `optimizer.py`.

---

## Decisión de negocio (validada con Gerente 05/05/2026)

**Regla R12**: En cualquier línea, en cualquier día, **el primer SKU programado NO paga setup**. Solo el segundo SKU en adelante (cambios intra-día) paga setup.

**Lógica operativa**: la limpieza/preparación para el primer SKU del día se hace al cierre del día anterior, después del cierre operativo. Es trabajo extra-jornada (turno limpieza/mantenimiento) y NO consume horas productivas del día siguiente.

---

## Comparación con el modelo actual

### Modelo actual (post-F1, archivo `optimizer.py`)

La detección actual de `inicio[d,k,l]` es:

```python
# Detección del primer día de corrida (paga setup)
if d_idx == 0:
    m.model.Add(inicio == 0)        # R4: día 0 sin setup
else:
    asig_prev = m.asig[(d-1, k, l)]
    m.model.Add(inicio >= asig - asig_prev)  # inicio=1 si SKU empieza ese día
    m.model.Add(inicio <= asig)              # inicio=0 si no se asigna
```

**Comportamiento**: `inicio=1` siempre que un SKU empieza una corrida. Si la corrida es de 1 día, paga 1 setup. Si es de 5 días, paga 1 setup (solo el primer día). Esto reflejaba la lógica "setup al primer día de la corrida del SKU".

### Modelo nuevo (post-R12)

**Cambio conceptual**: el setup ya no se atribuye al "primer día de la corrida del SKU". Se atribuye al "segundo SKU en adelante en el mismo día".

**Reformulación matemática**:

Para cada (d, l), si N = número de SKUs asignados ese día (`Σ_k asig[d, k, l]`), entonces el número total de setups en (d, l) debe ser:

```
Σ_k inicio[d, k, l] = max(0, N - 1)
```

- N = 0 SKUs asignados → 0 setups.
- N = 1 SKU asignado → 0 setups (el único es el "primero del día", no paga).
- N = 2 SKUs → 1 setup (el segundo paga).
- N = 3 SKUs → 2 setups.
- N = 4 SKUs (límite N_max actual) → 3 setups.

**El optimizador puede elegir cuál SKU es el "afortunado sin setup"** dentro del día. Lo natural es que elija el SKU que tenga el setup más caro (con la matriz futura) o el más probable de continuar al día siguiente. En N1 con matriz dummy uniforme, da igual cuál — todos los setups cuestan lo mismo.

---

## Implementación en `optimizer.py`

### Paso 1 — Eliminar la detección actual de `inicio` por SKU

Localizar el bloque (aproximadamente las líneas que tienen `inicio >= asig - asig_prev`):

```python
# ELIMINAR ESTE BLOQUE
if d_idx == 0:
    m.model.Add(inicio == 0)
else:
    asig_prev = m.asig[(d-1, k, l)]
    m.model.Add(inicio >= asig - asig_prev)
    m.model.Add(inicio <= asig)
```

### Paso 2 — Agregar la nueva restricción agregada por (d, l)

Después del bloque eliminado (o donde corresponda en el flujo actual), agregar:

```python
# R12 — Primer SKU del día NO paga setup (decisión Gerente 05/05/2026)
# Para cada (día, línea): Σ_k inicio[d,k,l] = max(0, Σ_k asig[d,k,l] - 1)
# Reformulado como cota inferior + cota superior por SKU:
#   Σ inicio >= Σ asig - 1
#   inicio[d,k,l] <= asig[d,k,l]   (integridad por SKU)
# La cota inferior fuerza que haya AL MENOS N-1 setups, pero NO determina un valor
# exacto: si la cap. del día es holgada, el solver es indiferente entre Σ inicio=N-1
# y Σ inicio=N, lo que puede dejar "inicios fantasma" sin costo aparente.
# Por eso el Paso 3 agrega un peso simbólico a la función objetivo.

for d_idx, d in enumerate(m.dias):
    for l in m.lineas:
        # Lista de variables asig e inicio en este (día, línea)
        asigs_dl = [m.asig[(d, k, l)] for k in m.skus if l in m.pares_sku_linea[k]]
        inicios_dl = [m.inicio[(d, k, l)] for k in m.skus if l in m.pares_sku_linea[k]]
        if not asigs_dl:
            continue

        # R12: Σ inicio >= Σ asig - 1
        m.model.Add(sum(inicios_dl) >= sum(asigs_dl) - 1)

        # Acotar superior para mantener integridad (inicio nunca 1 si asig=0)
        for k in m.skus:
            if l in m.pares_sku_linea[k]:
                m.model.Add(m.inicio[(d, k, l)] <= m.asig[(d, k, l)])
```

### Paso 3 — Agregar peso simbólico a `Σ inicio` en la función objetivo

**Crítico para que R12 sea determinista.** Sin este peso, el solver puede dejar `inicio=1` en SKUs continuadores (que vienen del día anterior) cuando la capacidad del día es holgada — la cota `Σ inicio >= N-1` no fuerza un valor exacto, solo un piso. El peso simbólico empuja al solver a preferir `inicio=0` siempre que sea factible.

Hoy el efecto indirecto vía R1a (cada `inicio=1` descuenta capacidad y eventualmente sube `def_`) ya empuja a minimizar inicios — pero **solo cuando hay presión de capacidad**. En `(d,l)` con holgura, el solver es indiferente y el Test 1 puede fallar sin que el plan sea peor.

```python
# Peso simbólico para evitar "inicios fantasma"
# No es para consolidar corridas (ese trabajo va en F2 con la matriz real).
# Es solo para desempatar: cuando el solver es indiferente entre Σ inicio=N-1
# y Σ inicio=N, este peso lo inclina al menor valor factible.
W_INICIO_SIMBOLICO = 1

for d in m.dias:
    for k in m.skus:
        for l in m.pares_sku_linea[k]:
            obj_terms.append(W_INICIO_SIMBOLICO * m.inicio[(d, k, l)])
```

**No subir este peso por encima de 1.** Si subís, recreás el W_SETUP=200 que se eliminó en F1 y volvés a presionar consolidación de corridas en N1, lo que es trabajo de F2 con matriz real. El valor `1` es estrictamente para integridad combinatoria.

### Paso 4 — Verificar que R1a sigue siendo coherente

La restricción R1a (capacidad agregada con setup) ya descuenta `inicio × setup_costo`:

```python
# R1a actual — sin cambios necesarios
m.model.Add(
    sum(prod_u_escalada + setup_costo × inicio for k in skus_l) <= cap_dia × FACTOR_ESCALA
)
```

Esto sigue funcionando: si N1 decide que un día tiene 3 SKUs (`Σ asig = 3`), entonces `Σ inicio = 2`, entonces se descuentan 2 setups de la capacidad. **Es exactamente lo que queremos**.

### Paso 5 — Eliminar el comentario de R4 sobre día 0

R4 ("día 0 nunca paga setup") queda **subsumida por R12**: si día 0 tiene N=1 SKU, entonces inicios=0 (correcto). Si tiene N=2 SKUs, entonces inicios=1 (correcto, uno paga). Es coherente con la decisión del Gerente y elimina la asimetría día-0/resto.

→ Eliminar el comentario "R4: día 0 sin setup" y reemplazarlo por "R12: primer SKU del día sin setup (incluye día 0 como caso particular)".

---

## Conexión con N2 (sequencer.py, F2 futura)

N2 va a tener su propia variable `paga_setup[k]` con `k` indexado por posición (`pos=1, 2, ..., N`). La regla nativa allí es:

```python
# En sequencer.py (F2 futura)
for k in skus_dia_linea:
    if pos[k] == 1:
        m.Add(paga_setup[k] == 0)  # Primer SKU = sin setup
    else:
        m.Add(paga_setup[k] == 1)  # Segundo en adelante = setup
```

**N1 y N2 son consistentes**: ambos asignan `setup=0` exactamente al primer SKU del día. La diferencia es que N1 trabaja en agregado (cuenta cuántos setups hay) y N2 trabaja en orden específico (decide cuál SKU es el primero).

---

## Validación post-implementación

Después de aplicar R12 + D2 (factor=1.0), regenerar `/plan` con horizonte 13 y comparar contra Test B':

| Métrica | Test B' (batch_min=3000) | Esperado post-R12+D2 |
|---|---|---|
| status | FEASIBLE | FEASIBLE o FEASIBLE/OPTIMAL |
| Sachetera uso% | 68% | 50-80% (margen cero por O12) |
| OFTs Mostaza | 55 | 40-70 (depende de cómo el solver agrupa corridas) |
| OFTs Ketchup | 54 | 40-70 |
| quiebre | 0 | 0 |
| ofts_con_paga_setup | 130 | **20-60** (R12 elimina los "primer SKU del día") |
| objective_value | 521 mil M | <300 mil M |

El cambio crítico es **`ofts_con_paga_setup`**: con R12 debería bajar drásticamente.

**Rango esperado: 20-60.** Interpretación de los bordes:

- **>80**: R12 mal implementada o inicios fantasma (verificar `W_INICIO_SIMBOLICO` activo).
- **20-60**: rango saludable, R12 funcionando como se diseñó.
- **<20** o **0**: posible fragmentación extrema — el solver eligió poner cada SKU en un día distinto para evitar todo setup. Esto NO es éxito, es señal de problema. Inspeccionar visualmente: si Detalle Producción muestra 1 SKU por día por línea durante todo el horizonte, hay que volver a calibrar (probablemente subir un peso suave de "fragmentación entre días" o esperar a F2).

---

## Tests específicos para validar R12

Después del cambio, hacer al menos estos 3 chequeos en el JSON generado:

```python
import json
with open('tests/fixtures/v1.3_post_r12_metrics.json', encoding='utf-8') as f:
    d = json.load(f)

ofts = [o for o in d['ordenes'] if o['tipo'] == 'PRODUCCION']

# Test 1: para cada (linea, fecha_lanzamiento), contar OFTs y OFTs con paga_setup
from collections import defaultdict
por_dia_linea = defaultdict(lambda: {'total': 0, 'con_setup': 0, 'skus': set()})
for o in ofts:
    key = (o['linea'], o['fecha_lanzamiento'])
    por_dia_linea[key]['total'] += 1
    por_dia_linea[key]['skus'].add(o['sku'])
    if o.get('paga_setup'):
        por_dia_linea[key]['con_setup'] += 1

# Test 1: en cada (linea, dia), N_ofts_con_setup == N_skus_distintos - 1
print("Verificación R12 — N setup == N skus - 1 por (linea, día):")
violaciones = 0
for (linea, fecha), v in por_dia_linea.items():
    n_skus = len(v['skus'])
    n_setup = v['con_setup']
    esperado = max(0, n_skus - 1)
    if n_setup != esperado:
        violaciones += 1
        print(f"  VIOLACIÓN ({linea}, {fecha}): {n_skus} SKUs, {n_setup} setups, esperado {esperado}")
if violaciones == 0:
    print("  OK: todas las (linea, día) cumplen N_setup == N_skus - 1")

# Test 2: total de setups debería ser bastante menor que en Test B'
total_setups = sum(v['con_setup'] for v in por_dia_linea.values())
print(f"\nTotal OFTs con paga_setup: {total_setups} (Test B' tenía 130)")

# Test 3: días con 1 solo SKU NUNCA deben tener setup
dias_un_sku = [k for k, v in por_dia_linea.items() if len(v['skus']) == 1]
con_setup_indebido = [k for k in dias_un_sku if por_dia_linea[k]['con_setup'] > 0]
print(f"\nDías con 1 SKU y setup (no debería haber): {len(con_setup_indebido)}")
```

Si los 3 tests pasan, R12 está correctamente implementada.

---

## Riesgos y consideraciones

### Riesgo 1 — Comportamiento del solver con R12 (fragmentación)

El solver puede preferir tener **muchos días con 1 SKU** en lugar de **pocos días con 2-3 SKUs** porque cada día con 1 SKU evita pagar el setup. Esto puede llevar a planes **fragmentados**, donde la línea cambia de SKU todos los días.

**Detección**: si `ofts_con_paga_setup` cae a <20 (o 0) y al inspeccionar Detalle Producción se ve 1 SKU por línea por día durante todo el horizonte, hay fragmentación.

**Mitigación si pasa**:
- Considerar reintroducir un peso pequeño en función objetivo que penalice la fragmentación entre días distintos (no setups intra-día). Algo como `W_FRAG = 50` aplicado a un indicador `cambio_de_sku_entre_dias[d,l]`.
- O esperar a F2 (sequencer) que va a optimizar dentro del día con la matriz real, y eventualmente a un módulo post-N2 que reordene corridas entre días.
- **No subir `W_INICIO_SIMBOLICO`** para combatir esto — ese parámetro es para integridad combinatoria, no para consolidación. Mezclar las dos cosas confunde el modelo.

### Riesgo 2 — Inicios fantasma si W_INICIO_SIMBOLICO = 0

Sin el peso simbólico del Paso 3, la restricción `Σ inicio >= N-1` admite inicios fantasma (`inicio=1` para SKUs continuadores con cap holgada). Esto haría:
- El Test 1 falla intermitentemente sin razón aparente.
- `ofts_con_paga_setup` queda inflado por sobre el rango esperado.
- El plan en sí no es "peor" (la cap se respeta igual) pero la generación de OFTs reporta más setups que los que realmente operan.

**Garantía**: si el Paso 3 está aplicado con `W_INICIO_SIMBOLICO = 1`, este riesgo no se materializa. Valor `0` lo recrea.

### Riesgo 3 — Coherencia con OFs aprobadas

Si hay OFs aprobadas con `paga_setup=true` que después de R12 deberían ser `paga_setup=false`, el modelo debería respetar la decisión del solver actual y el campo `paga_setup` se actualiza automáticamente en la generación.

→ **Verificar en el código**: el campo `paga_setup` se calcula en la generación de OFTs después del solve, no es un atributo persistido en BD. Por lo tanto, regenerar el plan recalcula los `paga_setup` con la lógica nueva. **No hay migración de datos necesaria**.

### Riesgo 4 — La "decisión del Gerente" implica cambio de proceso operativo

R12 asume que la limpieza/preparación SE HACE efectivamente al cierre del día anterior. Si en planta esto no se está haciendo así (por falta de personal, fines de semana, feriados), el modelo va a generar planes que la planta no puede cumplir.

→ **Documentar como supuesto operativo en CLAUDE.md**: "Regla R12 asume que la limpieza/preparación de líneas para el primer SKU del día se realiza al cierre del día anterior. Si esto cambia, R12 debe revisarse."

→ **Caso especial**: día después de feriado o fin de semana, ¿quién hace la limpieza? Si nadie, ese día sí debería pagar setup. Por ahora R12 asume que sí — si el Gerente lo aclara, se modela como excepción.

---

## Resumen de archivos a modificar

| Archivo | Cambio |
|---|---|
| `forecast/optimizer.py` | (a) Reemplazar bloque de detección de `inicio` por restricción agregada R12. (b) Agregar `W_INICIO_SIMBOLICO = 1` al objetivo. |
| `CLAUDE.md` | Agregar R12 a "Reglas de negocio activas" y documentar supuesto operativo. |
| `docs/v1.3_DISENO_ARQUITECTURA.md` | §3 — actualizar tabla de reglas con R12. §4.1 — actualizar descripción del modelo. |
| `docs/ESTADO_TECNICO_PROYECTO_<fecha>.md` | Documentar como D3 cerrada. |

**No se modifica `db_mrp.py`, `migrate_params.py` ni la BD para R12.** Es puramente un cambio de modelo en el optimizer.
