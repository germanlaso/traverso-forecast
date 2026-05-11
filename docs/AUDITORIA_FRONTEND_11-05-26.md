# Auditoría Frontend ↔ Backend — Cálculos paralelos

**Fecha:** 11/05/2026 (nominal: martes 14/05/2026)
**Contexto:** Capa A de la auditoría descripta en `docs/ESTADO_TECNICO_PROYECTO_HOY.md` §3.1. Identificar todos los puntos donde el frontend recalcula información que el backend ya tiene (o debería tener), para fijar el alcance de los fixes V6.14 v2 / V6.26 / V6.27.
**Alcance:** `dashboard/src/components/StockProyeccion.jsx`, `dashboard/src/components/DetalleProduccion.jsx`, `dashboard/src/App.js`.
**Regla de oro arquitectónica acordada:** una sola fuente de verdad por cálculo; backend emite, frontend renderiza.

---

## Resumen ejecutivo

| Severidad | Cálculos | Categoría |
|---|---:|---|
| 🔴 Crítico | 11 | Alimentan directamente el "rojo masivo" del dashboard o están en regex sobre `motivo` |
| 🟠 Alto | 6 | Calendario y capacidades reimplementados (duplicación estructural) |
| 🟡 Medio | 10 | Duplicaciones tolerables hoy pero candidatas a estructurar |
| 🟢 Bajo | 9 | Cosmético / fallbacks de respuestas viejas |
| **Total** | **36** | |

**Pieza de mayor impacto:** `calcularProyeccion()` en `StockProyeccion.jsx:60-153`. Concentra P4, P5, P6, P8, P9, P10, P14. Es el corazón del bug del banner amarillo y del rojo de la curva azul.

**Bug paralelo no atrapado por V6.14 v1:** `DetalleProduccion.jsx:556` (P21) sigue parseando `Stock:N` por regex — el fix solo tocó `StockProyeccion.jsx`. Debe incluirse en el Fix A.

**Asunción peligrosa más sutil:** `cap_dia = cap_u_semana / 5` en `DetalleProduccion.jsx:278` (P18). No causa el rojo de hoy pero rompe en cuanto haya una semana con feriado.

---

## 🔴 CRÍTICOS (11) — alimentan el "rojo masivo"

### P1 · Stock inicial del SKU (`stockReal`)
**Archivo:** `StockProyeccion.jsx:286-295`
```js
const primeraOrden = ordenesSku[0];
if (primeraOrden && typeof primeraOrden.stock_inicial_cajas === 'number' && primeraOrden.stock_inicial_cajas > 0) {
  setStockReal(primeraOrden.stock_inicial_cajas);
} else {
  const motivo = primeraOrden?.motivo ?? "";
  const m = motivo.match(/Stock:([\d.]+)/);
  setStockReal(m ? parseFloat(m[1]) : 0);
}
```
**Bug confirmado (V6.14 v2):** depende de `ordenesSku[0]`. Si el SKU no tiene OFT → `primeraOrden = undefined` → `stockReal = 0`. Caso real: SKU 261010555 con 496 cj reales se muestra como 0.
**Fuente backend correcta:** parquet de stock (`stock_unidades` en cajas) o `stock_inicial_rich[sku]` ya disponible en `optimizer.py:945`.
**Fix Opción A:** payload `/plan` emite `stock_por_sku: {sku: cajas}` con todos los SKUs activos.

### P4 · Iteración propia del stock proyectado (CURVA AZUL)
**Archivo:** `StockProyeccion.jsx:60-153` — función `calcularProyeccion`
- L82-116: decide qué OFTs incluir como entradas semanales:
  - Aprobada → entra con `cantidad_real_cj`.
  - No aprobada y `semLanz > semanaActual` → entra con `cantidad_cajas`.
  - **No aprobada y `semLanz <= semanaActual` → NO entra** (L109: "si semLanz <= semanaActual y no aprobada → cantidad = 0").
- L138-140: itera `stock = Math.max(0, stock + entradas - f.yhat)`.

**Bug confirmado (V6.26 banner amarillo):** las OFTs sugeridas con lanzamiento ya pasado o esta semana se ignoran → curva azul cae a 0 → estado "Rotura". El backend sí las incluye en su proyección interna; el frontend las descarta unilateralmente.
**Clamp adicional:** `Math.max(0, ...)` impide ver quiebres reales (el backend ya distingue entre negativo y BAJO_SS).
**Fix Opción A:** payload `/plan` emite `proyeccion_por_sku[sku] = [{ds, stock_ini, entradas, ventas, ss, stock_fin, estado}]` ya calculado por backend.

### P5 · SS dinámico semanal recalculado
**Archivo:** `StockProyeccion.jsx:137`
```js
const ss = Math.round((f.yhat / 7) * ssDias);
```
Recalcula el SS dinámico en frontend. Backend hace lo mismo a nivel diario (regla 7 de CLAUDE.md: `SS = demanda_diaria × ss_dias`). Si los redondeos/agregación difieren, el umbral "BAJO_SS" del frontend no coincide con el del backend.
**Fix Opción A:** SS por semana viene en `proyeccion_por_sku`.

### P6 · `minStock` y `semBajoSS` (KPI rojo/ámbar)
**Archivo:** `StockProyeccion.jsx:343-345`
```js
const minStock = proyeccion.length ? Math.min(...proyeccion.map((r) => r.stockFin)) : 0;
const semBajoSS = proyeccion.filter((r) => r.stockFin < r.ss).length;
const stockColor = minStock < 0 ? C.red : semBajoSS > 0 ? C.amber : C.teal;
```
Color del KPI deriva 100% de P4 → hereda el bug de OFTs ignoradas.
**Fix Opción A:** derivado de `proyeccion_por_sku`. Backend puede incluso emitir `kpi_stock_minimo` y `kpi_sem_bajo_ss` directos.

### P8 · Cobertura por fila (tabla semanal)
**Archivo:** `StockProyeccion.jsx:541, 604-605`
```js
const cobDias = r.ventas > 0 ? Math.round((r.stockFin/r.ventas)*7) : 999;
```
Derivada de P4. Si curva cae a 0 → cobertura = 0d → ámbar/rojo.
**Fix Opción A:** cobertura por semana viene en `proyeccion_por_sku`.

### P9 · Estado "Rotura / Bajo SS / OK" por semana
**Archivo:** `StockProyeccion.jsx:539-540, 608-613`
```js
const bajo = r.stockFin < r.ss;
const negativo = r.stockFin < 0;
```
Pintado rojo final del dashboard. Backend ya emite alertas `BAJO_SS` y `QUIEBRE` por OFT (post-V6.18), pero el frontend no las consume — clasifica solo con su propio cálculo.
**Fix Opción A:** campo `estado` ∈ {OK, BAJO_SS, QUIEBRE} por semana en `proyeccion_por_sku`.

### P10 · `nOrdenesProyeccion` (KPI "N órdenes")
**Archivo:** `StockProyeccion.jsx:330-338` — mismo filtro que P4 (aprobadas ∪ `ds > semActual`). Si el banner "OFTs sugeridas no se muestran" dispara, este número también miente.
**Fix Opción A:** payload emite `n_ordenes_en_proyeccion` por SKU.

### P14 · `chartData` (entradas + ventas + stock + ss en el gráfico)
**Archivo:** `StockProyeccion.jsx:348-357` — vuelca `proyeccion` al gráfico. Hereda P4 íntegramente.
**Fix Opción A:** se reduce a un map() trivial desde `proyeccion_por_sku`.

### P21 · Stock inicial parseado por regex (Detalle Producción)
**Archivo:** `DetalleProduccion.jsx:556`
```js
const stockIni = parseFloat(o.motivo?.match(/Stock:([\d.]+)/)?.[1] ?? 0);
```
**V6.14 v1 NO fixeó este lugar.** Para OFTs del optimizer cuyo `motivo = "OFT (optimizada)"` (sin `Stock:N`), `stockIni = 0`. Bug paralelo al P1 pero en otra pestaña.
**Fix Opción A:** leer `o.stock_inicial_cajas` (campo numérico, post-V6.14) — el optimizer ya lo emite por OFT. Solución de 1 línea, sin requerir cambio backend.

### P22 · Cobertura por orden en Detalle
**Archivo:** `DetalleProduccion.jsx:557`
```js
const cobDias = o.forecast_cajas>0 ? Math.round((stockIni/o.forecast_cajas)*7) : "—";
```
Deriva de P21 → con `stockIni = 0`, cobertura siempre 0d → ámbar.
**Fix Opción A:** después de fixear P21, esta queda correcta.

### P28 · Cálculo fallback de `fecha_entrada` por lead time
**Archivo:** `App.js:713-723`
```js
if(o.fecha_entrada_real) return o.fecha_entrada_real;
const ltD = Math.round((o.lead_time_sem ?? 1) * 7);
const d = new Date((o.semana_emision || o.semana_necesidad)+'T12:00:00');
d.setDate(d.getDate()+ltD);
return d.toISOString().slice(0,10);
```
Implementa la regla 4 de CLAUDE.md en frontend pero anclando a `semana_emision` (domingo) en lugar de `fecha_lanzamiento` (día). Solo se ejecuta en respuestas viejas (compat) — riesgo bajo pero deuda.
**Fix:** eliminar el fallback. Backend ya emite `fecha_entrada_real` día-exacta desde v1.2.

---

## 🟠 ALTOS (6) — duplicación estructural

### P15-P17 · Calendario chileno reimplementado en frontend
**Archivo:** `DetalleProduccion.jsx:12-34`
- L12-17: `FERIADOS_CL` hardcoded para 2026 (17 fechas).
- L19: `esFeriado`, L20: `esDiaHabil` (filtra dom/sáb/feriado).
- L21: `addDias`, L22: `getDomingoActual`, L23: `addSemanas`, L24-34: `diasDesde`.

**Backend tiene `forecast/calendario.py`** con feriados Chile + helpers. Reescritos en JS. Si el Gerente edita feriados 2027, hay que tocar dos lugares.
**Fix Bloque B2:** endpoint `/calendario/feriados?anio=2026` o incluir `feriados` en `/plan/params`. Eliminar `FERIADOS_CL` del frontend.

### P18 · Capacidad diaria = `cap_u_semana / 5`
**Archivo:** `DetalleProduccion.jsx:278, 503`
```js
const capDia = linea.cap_u_semana / 5;
```
**Asunción peligrosa:** "5 días hábiles uniformes". Backend calcula `cap_dia_u` con `velocidad × horas_turno × turnos_dia × factor_velocidad`, ajustada por semana corta o feriado. La división por 5 ignora todo eso.
**Fix Bloque B2:** `/plan/params` ya devuelve `lineas[]` — agregar `cap_u_dia` por línea (o por línea×fecha si hay variabilidad).

### P19 · Uso de capacidad por día (`usoPctReal`)
**Archivo:** `DetalleProduccion.jsx:300-301, 311`
```js
const uProd = Math.round(cajasReales * upj);
const usoPctReal = uProd / capDia;
```
Doble recálculo: (a) `cantidad_unidades` desde cajas × upj cuando el backend ya lo emite, (b) % de uso contra el `capDia` aproximado de P18.
**Fix Bloque B2:** leer `o.cantidad_unidades` directamente; usar `cap_u_dia` de P18.

### P20 · Setup semanal y diario por línea
**Archivo:** `DetalleProduccion.jsx:478-484, 504-505`
```js
const setupSem = dias.reduce((s,d)=>s+(ordenesXDia[d.fecha]??[]).reduce((acc,o)=>acc+(o.setup_unidades||0),0), 0);
const setupPctSem = linea.cap_u_semana > 0 ? setupSem / linea.cap_u_semana : 0;
const setupPctDia = capDia > 0 ? setupUDia / capDia : 0;
```
La agregación es legítima (suma `setup_unidades` por OFT). El % usa la misma división aproximada de P18.
**Fix:** misma corrección de capacidad de P18.

---

## 🟡 MEDIOS (10) — duplicación tolerable

### P2 · `getSemana()` — colapso al domingo
**Archivo:** `StockProyeccion.jsx:46-51` — necesario para casar `fecha_lanzamiento` (día) con `f.ds` (domingo) del forecast. Síntoma de que el forecast viene semanal pero las OFTs vienen diarias — la "junta" se hace en frontend. Si el backend pre-agrega al domingo en `proyeccion_por_sku`, esta función desaparece.

### P3 · `getSemanaActual()`
**Archivo:** `StockProyeccion.jsx:53-58` — calcula el lunes (¡no domingo, contrario al comentario!) de la semana del navegador. Depende de TZ del cliente.

### P7 · KPI "Cobertura actual"
**Archivo:** `StockProyeccion.jsx:468-470`
```js
totalVentas > 0 ? `${((stockReal/(totalVentas/horizonte))*7).toFixed(0)} días` : "—"
```
Razonable, pero podría venir como `cobertura_actual_dias` por SKU del backend.

### P11 · `tienePendiente`
**Archivo:** `StockProyeccion.jsx:312-323` — detecta OFT no aprobada con semana de lanzamiento <= actual. Iteración con la regla 1 de CLAUDE.md ("OF nunca en pasado").

### P12 · Forecast refetcheado por SKU
**Archivo:** `StockProyeccion.jsx:259-269` — POST `/forecast` con `periods = horizonte+4`. **No reutiliza el forecast del payload de `/plan`**. Si el plan usó forecast del momento N y ahora son las N+1, los dos pueden diferir → curva azul calculada contra un forecast distinto al que alimentó el optimizador.
**Fix:** `proyeccion_por_sku` debe usar el mismo forecast que el optimizador.

### P13 · `PARAMS_FALLBACK` hardcoded
**Archivo:** `StockProyeccion.jsx:9-21` — 10 SKUs con ss_dias, lt, upj, desc, tipo hardcoded. Si `/plan/params` falla, los valores son ficticios y obsoletos respecto a la BD post-V4 (76 SKUs).
**Fix:** eliminar; mostrar error explícito si `/plan/params` falla.

### P23 · "Urgente / Pasada"
**Archivo:** `DetalleProduccion.jsx:555, 571`
```js
const pasada = fechaLanzReal <= hoy && !aprobada;
```
Regla 1 de CLAUDE.md vuelta a aplicar en frontend.

### P24 · "Pref." vs "Alt." (línea)
**Archivo:** `DetalleProduccion.jsx:515, 549`
```js
const esPreferida = params[o.sku]?.linea === linea.codigo;
```
Backend podría emitir un flag `es_preferida` en la OFT.

### P25 · "esOFT" (aprobado vs sugerido) doble fuente
**Archivo:** `DetalleProduccion.jsx:50`
```js
const esOFT = estaAprobada !== undefined ? !estaAprobada : !orden.aprobada;
```
Hack documentado para evitar parpadeo ámbar→verde post-aprobación.

### P26 · Filtrado ventana de semana visible
**Archivo:** `DetalleProduccion.jsx:453-468` — calendario en frontend para decidir qué OFTs caen en la semana.

---

## 🟢 BAJOS (9) — cosméticos

### P27 · `ordenKey = numero_of`
**Archivo:** `App.js:404` — match estable. OK.

### P29 · Fecha lanzamiento desplegada
**Archivo:** `App.js:729` — `o.fecha_lanzamiento || o.semana_emision`. Cascada de fallbacks.

### P30 · `cantMostrar`
**Archivo:** `App.js:681` — `aprobada ? aprobada.cantidad_real_cj : o.cantidad_cajas`.

### P31 · `modificada`
**Archivo:** `App.js:682` — `aprobada && aprobada.cantidad_real_cj !== o.cantidad_cajas`.

### P32 · Stock total — fallback de nombres
**Archivo:** `App.js:595`
```js
Math.round((stockInfo.total_cajas || stockInfo.total_unidades || 0))
```
Cubre dos nombres del endpoint `/stock/summary`. Relacionado con la confusión cajas/unidades del 11/05.

### P33 · Modal aprobación prefill (cascada de fechas)
**Archivo:** `App.js:334-342` — fallbacks aprobada → orden.fecha_X → orden.semana_X.

### P34 · `chartData` forecast (merge history + forecast)
**Archivo:** `App.js:383-394` — función pura.

### P35 · MAPE thresholds hardcoded
**Archivo:** `App.js:398`
```js
mapeType = !mapeOk ? 'warn' : metrics.mape < 10 ? 'ok' : metrics.mape < 20 ? 'warn' : 'error';
```
Umbrales 10%/20% no vienen del backend.

### P36 · "Próxima semana" — búsqueda en forecast
**Archivo:** `App.js:477` — `result.forecast?.find(f=>f.ds>=todayStr)?.yhat`.

---

## Plan de fixes (acordado con chat web)

| Bloque | Cubre | Estimado |
|---|---|---|
| **B1 — Proyección unificada** (backend emite `proyeccion_por_sku`, frontend renderiza) | P1, P4, P5, P6, P8, P9, P10, P14, P21, P22 | 2h |
| **B2 — Calendario y capacidades en backend** | P15-P20 | 1h |
| **B3 — Decisión UX banner amarillo** (desaparece, la curva ya muestra realidad) | — | 0 (se elimina) |
| **B4 — Cosmético** | P27, P29-P36 | post-vacaciones |

**Regla:** backend es fuente única de verdad. Frontend solo presenta.

---

## Foco recomendado para Capa B (tests de paridad)

Dado un SKU + plan vigente:
1. `stockReal` frontend vs `stock_inicial_rich[sku]` backend (P1).
2. Lista de entradas semanales en `calcularProyeccion()` vs OFTs del plan (P4).
3. Curva azul punto a punto vs proyección backend (P4, P5).
4. `cap_dia` frontend (`cap_u_semana/5`) vs `cap_dia_u` backend para una línea con factor_velocidad ≠ 1 (P18).

Reportar discrepancias por SKU, no en agregado.
