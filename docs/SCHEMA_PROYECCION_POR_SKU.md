# Schema — `proyeccion_por_sku` en response de `/plan`

**Fecha:** 11/05/2026 (nominal: martes 14/05/2026)
**Contexto:** Decisión arquitectónica V6.27 (auditoría completa backend↔frontend). Bloque B1 de los fixes acordados. Backend emite proyección completa por SKU, frontend solo renderiza. **Una sola fuente de verdad.**

---

## 1. Decisiones de diseño

| ID | Decisión |
|---|---|
| **D1** | Emitir **2 campos de stock final**: `stock_fin_cj_visible` (clampeado ≥0, alimenta la curva azul del gráfico) y `stock_fin_cj_real` (puede ser negativo, alimenta KPIs y estado). |
| **D2** | Semana = **domingo a sábado** (alineado con `getSemana()` del frontend actual y con `calendario.semana_viz_inicio()` del backend). NO usar semana ISO (lunes). |
| **D3** | Incluir **TODOS los SKUs activos del catálogo**, no solo los del modelo del optimizer. Cada SKU lleva un campo `cobertura ∈ {proyeccion_completa, solo_stock, sin_proyeccion}` que indica qué nivel de detalle pudo construirse. |

---

## 2. Estructura completa del campo

```json
{
  "proyeccion_por_sku": {
    "121010290": {
      "stock_inicial_cj": 5240,
      "cobertura": "proyeccion_completa",
      "semanas": [
        {
          "semana": "2026-05-10",
          "stock_ini_cj": 5240,
          "entradas_cj": 950,
          "entradas_aprobadas_cj": 0,
          "entradas_sugeridas_cj": 950,
          "ventas_cj": 1148,
          "ss_cj": 380,
          "stock_fin_cj_visible": 5042,
          "stock_fin_cj_real": 5042,
          "estado": "OK",
          "n_ofts_semana": 1,
          "semana_parcial": false
        }
      ]
    }
  }
}
```

### 2.1 Nivel SKU

| Campo | Tipo | Descripción |
|---|---|---|
| `stock_inicial_cj` | número | Stock real en cajas al primer día del horizonte. Fuente: parquet (`stock_unidades` ÷ `u_por_caja`). Mismo valor que `stock_ini_cj` de la primera semana cuando la cobertura es completa. |
| `cobertura` | string enum | `proyeccion_completa` \| `solo_stock` \| `sin_proyeccion`. Ver §3. |
| `semanas` | array | Lista de semanas (domingo a sábado) cubriendo el horizonte. Vacía si `cobertura == "sin_proyeccion"`. |

### 2.2 Nivel semana

| Campo | Tipo | Descripción |
|---|---|---|
| `semana` | string ISO date | Domingo de la semana (`semana_viz_inicio`). |
| `stock_ini_cj` | número | Stock al inicio del domingo. Sem 0 = `stock_inicial_cj`; sem N>0 = `stock_fin_cj_real` de sem N-1. |
| `entradas_cj` | número | Total cajas que ingresan en la semana = `entradas_aprobadas_cj + entradas_sugeridas_cj`. |
| `entradas_aprobadas_cj` | número | Cajas de OFs aprobadas con `fecha_entrada_real` en la semana. |
| `entradas_sugeridas_cj` | número | Cajas de OFTs no aprobadas con `fecha_entrada_real` en la semana, **independientemente de si su lanzamiento ya pasó o no** (corrige el bug V6.26 del banner amarillo). |
| `ventas_cj` | número | Suma de demanda diaria de los 7 días de la semana, convertida a cajas (`u ÷ u_por_caja`). Para días no hábiles `demanda_diaria = 0` por construcción de `calendario.distribuir_forecast_a_diario()`. |
| `ss_cj` | número | SS dinámico semanal = `round((yhat_sem_cj / 7) × ss_dias)`. **`yhat` viene ya en cajas** desde `run_sku_pipeline` (verificado en `mrp.py:316`, `optimizer.py:858`, y test 4 del snapshot HOY). NO dividir por `upc`. Es el umbral en cajas debajo del cual la semana se marca `BAJO_SS`. Si `yhat_sem == 0` → `ss_cj == 0`. |
| `stock_fin_cj_visible` | número ≥0 | `max(0, stock_fin_cj_real)`. Curva azul del gráfico. |
| `stock_fin_cj_real` | número | `stock_ini_cj + entradas_cj - ventas_cj`. Puede ser negativo. Alimenta `estado` y KPIs. |
| `estado` | string enum | `OK` \| `BAJO_SS` \| `QUIEBRE`. Ver §4. |
| `n_ofts_semana` | número | Cantidad de OFTs (aprobadas + sugeridas) cuyo **`fecha_entrada_real` cae en la semana**. **NO se cuenta por `fecha_lanzamiento`** — una OFT con lanzamiento hoy y entrada en 1 semana cuenta en la semana de entrada, no en la actual. Esta convención se alinea con que `entradas_aprobadas_cj` y `entradas_sugeridas_cj` también agregan por `fecha_entrada_real`. |
| `semana_parcial` | bool | `true` si la semana es la primera del horizonte y no arranca un domingo (ej. plan corre miércoles), o la última y no termina un sábado. |

---

## 3. Cobertura — qué SKUs incluir y cómo

### `cobertura == "proyeccion_completa"`

SKUs que pasaron por el optimizador y tienen forecast > 0. Tienen:
- Stock inicial real.
- Demanda semanal (Prophet).
- OFTs propias o como entradas aprobadas.
- Proyección semana a semana con todas las semanas del horizonte.

### `cobertura == "solo_stock"`

SKUs activos del catálogo que **no entran al optimizador** pero **tienen forecast**. Casos:
- **IMPORTACION**: el optimizador no los procesa (`optimizer.py:166-170`), pero tienen forecast Prophet y OFs preservadas en `main.py:761-778`. Construir proyección semanal igual con esos datos.
- **PRODUCCION filtrados por V6.12-mini** (`stock_inicial > cap_bodega`): proyección plana sin entradas (no se sugieren OFTs).
- **PRODUCCION sin línea asignada** (`skus_sin_linea` en `optimizer.py:192-195`): proyección plana sin entradas.
- **PRODUCCION con `demanda_total == 0`** (excluidos en `optimizer.py:173-178`): si llegan al catálogo activo y tienen forecast (aunque sea con yhat=0 en todas las semanas), reportar `solo_stock` con `ventas_cj = 0` por semana.

### `cobertura == "sin_proyeccion"`

SKUs activos sin forecast (try/except de `main.py:401-415` filtra). Solo se emite `stock_inicial_cj`; `semanas: []`. El frontend muestra advertencia "⚠ proyección no disponible para este SKU".

---

## 4. Cálculo de `estado`

Orden de evaluación (primer match gana):

1. `stock_fin_cj_real < 0` ó `(stock_ini_cj + entradas_cj) < ventas_cj` → **`QUIEBRE`**
2. `0 <= stock_fin_cj_real < ss_cj` → **`BAJO_SS`**
3. caso restante → **`OK`**

> Nota: las dos condiciones de QUIEBRE son equivalentes algebraicamente
> (`stock_fin = stock_ini + entradas - ventas`), pero se evalúan ambas explícitamente
> para tolerancia frente a `ventas_cj` que viene de redondeo.

---

## 5. Algoritmo de construcción (pseudocódigo)

```python
def construir_proyeccion_por_sku(
    ordenes_finales,            # PROD + IMPORTACION post-optimizer/MRP
    aprobadas_db,               # OFs aprobadas con fecha_entrada_real, cantidad_real_cj
    sku_params_all,             # TODOS los SKUs activos del catálogo (no filtrados)
    forecasts,                  # {sku: [{ds, yhat}, ...]} en cajas semanales
    stocks_actuales,            # {sku: cajas}
    fecha_inicio,               # date hoy
    horizonte_dias,             # 28 para h=4
) -> dict:
    fecha_fin = fecha_inicio + timedelta(days=horizonte_dias - 1)

    # 1. Construir lista de semanas (domingo a sábado) que cubren el horizonte
    semanas = enumerar_semanas_viz(fecha_inicio, fecha_fin)
    # ej. plan corre miércoles 13/05 con h=28: semanas =
    #   [10/05 (parcial), 17/05, 24/05, 31/05, 07/06 (parcial)]

    proyeccion = {}
    for sku, sp in sku_params_all.items():
        upc = sp.unidades_por_caja
        stock_ini_cj = stocks_actuales.get(sku, 0)

        # 2. Decidir cobertura
        tiene_forecast = sku in forecasts and len(forecasts[sku]) > 0
        if not tiene_forecast:
            proyeccion[sku] = {
                "stock_inicial_cj": stock_ini_cj,
                "cobertura": "sin_proyeccion",
                "semanas": [],
            }
            continue

        # 3. Pre-agregar OFTs y aprobadas por semana_viz_inicio(fecha_entrada_real)
        entradas_apr_por_sem, entradas_sug_por_sem, n_ofts_por_sem = \
            agregar_entradas(ordenes_finales, aprobadas_db, sku)

        # 4. Pre-agregar ventas por semana (sumar demanda diaria de los 7 días)
        demanda_diaria = distribuir_forecast_a_diario(forecasts[sku], fecha_inicio, fecha_fin)
        ventas_por_sem = agregar_ventas(demanda_diaria, semanas)

        # 5. Iteración semana a semana
        semanas_out = []
        stock_acum_real = stock_ini_cj
        for sem in semanas:
            ventas_cj = round(ventas_por_sem[sem] / upc, 1)
            entr_apr  = round(entradas_apr_por_sem.get(sem, 0), 1)
            entr_sug  = round(entradas_sug_por_sem.get(sem, 0), 1)
            entr_tot  = round(entr_apr + entr_sug, 1)

            stock_ini_sem = round(stock_acum_real, 1)
            stock_fin_real = round(stock_acum_real + entr_tot - ventas_cj, 1)
            stock_fin_visible = max(0.0, stock_fin_real)

            ss_cj = calcular_ss_semana(forecasts[sku], sem, sp.ss_dias, upc)

            estado = (
                "QUIEBRE" if stock_fin_real < 0
                else "BAJO_SS" if stock_fin_real < ss_cj
                else "OK"
            )

            semana_parcial = (
                (sem == semanas[0] and fecha_inicio > sem)
                or (sem == semanas[-1] and fecha_fin < sem + timedelta(days=6))
            )

            semanas_out.append({
                "semana": sem.isoformat(),
                "stock_ini_cj": stock_ini_sem,
                "entradas_cj": entr_tot,
                "entradas_aprobadas_cj": entr_apr,
                "entradas_sugeridas_cj": entr_sug,
                "ventas_cj": ventas_cj,
                "ss_cj": ss_cj,
                "stock_fin_cj_visible": stock_fin_visible,
                "stock_fin_cj_real": stock_fin_real,
                "estado": estado,
                "n_ofts_semana": n_ofts_por_sem.get(sem, 0),
                "semana_parcial": semana_parcial,
            })
            stock_acum_real = stock_fin_real

        cobertura = decidir_cobertura(sku, sku_in_optimizer_model, sp)
        proyeccion[sku] = {
            "stock_inicial_cj": stock_ini_cj,
            "cobertura": cobertura,
            "semanas": semanas_out,
        }

    return proyeccion
```

---

## 6. Tratamiento de los 8 casos borde

| # | Caso | Tratamiento |
|---|---|---|
| 1 | **Semana inicial parcial** (plan corre día no-domingo) | Primera semana = domingo previo. `stock_ini_cj` = **stock del parquet de hoy** (lo que dice `stocks_actuales[sku]`), **NO reconstruido restando ventas dom→hoy**. Razón: es lo que el usuario espera ver — coincide con "stock real" del dashboard de "Stock actual". Las ventas de la semana parcial inicial se computan solo sobre los días dentro del horizonte (de hoy al sábado), no sobre los días previos al inicio del plan (`distribuir_forecast_a_diario` ya filtra). Marcar `semana_parcial: true`. **Implicación:** `stock_ini_cj + entradas_cj - ventas_cj = stock_fin_cj_real` sigue siendo coherente, pero la semana refleja "qué va a pasar desde hoy hasta el sábado" y no "qué pasó la semana entera". |
| 2 | **Última semana parcial** (h=4 cierra a media semana) | Marcar `semana_parcial: true`. Entradas/ventas truncadas al `fecha_fin`. |
| 3 | **SS = 0** | `ss_cj = 0`. Estado nunca puede ser BAJO_SS por construcción (QUIEBRE solo si stock<0). |
| 4 | **`batch_min_u` fraccionario** (V6.29) | Cajas se redondean con `round(u / upc, 1)`. Mantiene 1 decimal en respuesta. |
| 5 | **`yhat` negativo de Prophet** | Ya clampeado en `optimizer.py:858` (`max(0.0, yhat)`). En proyección, replicamos el clamp al construir `demanda_diaria`. |
| 6 | **SKU sin `u_por_caja`** | `upc = 1`. Cajas = unidades. |
| 7 | **Entrada aprobada con `fecha_entrada_real` fuera del horizonte** | Ignorar — `entradas_aprobadas_cj = 0` para esa semana. No alterar stock. |
| 8 | **Plan re-generado tras aprobar OFT** | `n_ofts_semana` cambia; documentado. Comportamiento esperado, no bug. |

---

## 7. Posicionamiento en la arquitectura

**Decisión:** módulo nuevo `forecast/proyeccion.py`.

Razones:
- Es lógica de **presentación/agregación**, no de optimización.
- Tiene que correr **en ambos paths**: con optimizer (`req.optimizar=True`) y sin optimizer (MRP clásico).
- Tiene que combinar `ordenes_finales` (que ya incluye PROD optimizadas + IMPORTACION preservadas) con `aprobadas_db` y `stocks_actuales`.

**Llamada desde `main.py`** después de armar `ordenes` y antes del `return`. Una sola llamada, una sola fuente de verdad.

**Firma propuesta:**
```python
def construir_proyeccion_por_sku(
    ordenes_finales: list[dict],
    aprobadas_db: list[dict],
    sku_params: dict[str, SKUParams],      # TODOS los activos
    forecasts: dict[str, list[dict]],
    stocks_actuales: dict[str, float],
    fecha_inicio: date,
    horizonte_dias: int,
    skus_en_modelo: set[str] | None = None, # para distinguir proyeccion_completa vs solo_stock
) -> dict[str, dict]:
```

---

## 8. Tests de paridad (Capa B mínima — Bloque 4 del plan)

Antes de tocar frontend, validar para 5-10 SKUs de cada categoría:

1. **SKU con OFT**: comparar `stock_fin_cj_real` semana 0 vs el `stock_inicial_cajas` del primer OFT del SKU en el plan vigente (post-V6.14). Deben coincidir.
2. **SKU sin OFT con stock real > 0** (caso del bug, ej. 261010555): el nuevo campo debe emitir `stock_inicial_cj > 0` y `cobertura = "solo_stock"`. El frontend hoy lo muestra como 0.
3. **SKU con OFT sugerida con lanzamiento pasado**: la entrada **debe entrar** en `entradas_sugeridas_cj` (bug V6.26 del banner amarillo). El frontend hoy la descarta. **SKU específico se identifica al ejecutar el smoke test** — el script `forecast/tests/smoke_proyeccion.py` busca el primer SKU del plan vigente con OFT no aprobada cuya `fecha_lanzamiento <= hoy` y lo reporta. Si ningún SKU cumple la condición (caso raro en h=4 si hoy es domingo o lunes), el script lo indica y se puede forzar el caso editando `fecha_lanzamiento` de cualquier OFT a una fecha pasada vía UPDATE en `mrp_aprobaciones` o regenerando el plan tras cambiar la fecha de inicio.
4. **SKU IMPORTACION**: emitir `cobertura = "solo_stock"` y proyección con entradas de las OFs IMPORTACION.
5. **SKU filtrado V6.12-mini**: emitir `cobertura = "solo_stock"` con `entradas_cj = 0` toda la proyección.

Tabla de referencia: `/tmp/tabla_maestra_v2.csv` en `traverso_forecast` (74 SKUs con diagnóstico).

---

## 9. Tamaño esperado del payload

- 76 SKUs activos × 5 semanas (h=4 + parcial inicial) × ~12 campos numéricos = ~4.500 valores.
- Sumado a OFTs y resto del response: ~150 KB total estimado. Sin compresión. **Trivial.**

---

## 10. Compatibilidad

- Campo nuevo. Frontend solo lo lee si existe.
- Si por algún motivo backend no lo emite (versión vieja, falla), frontend cae a comportamiento pre-B1 con banner de advertencia.
- Una versión backend "vieja" no incluye `proyeccion_por_sku` — frontend nuevo lo detecta y muestra el banner amarillo legacy.

---

*Documento de referencia para implementación B1. No mutar sin re-discutir en chat web.*
