# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.3-V5 + V6.14 + V6.18 + V6.12-mini — Actualizado: 11/05/2026

> **Nota sobre fechas**: snapshot generado el domingo 11/05/2026 real (calendario nominal corre adelantado, mantengo la convención de snapshots anteriores).

---

## Resumen ejecutivo de la sesión

Sesión dedicada exclusivamente a investigar la preocupación del usuario del 13/05 ("muchos quiebres visibles en el dashboard"). Diagnóstico exhaustivo de ~5h en chat web que reformuló el problema dos veces, descartó hipótesis iniciales erróneas y aterrizó en una conclusión inesperada: **el optimizador hace su trabajo correctamente; el "rojo masivo" es 100% del dashboard**.

Cierre del día: **diagnóstico cerrado pero fixes pendientes**. Se decide dividir el trabajo: el resto se ataca con Claude Code (auditoría exhaustiva backend↔frontend + fixes coherentes), no en chat web.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Plan h=4 vigente | FEASIBLE @86s, 132 OFTs, 7 alertas |
| SKUs con OFT (PRODUCE) | 51 de 74 PRODUCCION activos |
| SKUs sin OFT (problemático aparente) | 22 |
| OK_PRODUCE_BIEN (gap ≤10% necesidad) | **47** |
| OK_STOCK_SUFICIENTE (no requieren producción) | **21** |
| OK_DEMANDA_NULA | 4 |
| BUG_NO_PRODUCE (bug real del optimizador) | **1** (Vinagre Tinto Tottus 30x500) |
| CAPACIDAD_LIMITE (gap chico) | 1 |
| **GAP TOTAL real** | **162 cajas** (corregido) |

---

## 1. El recorrido del diagnóstico (importante para Code)

Esta sección documenta cómo llegamos al diagnóstico, porque varios callejones sin salida son trampas conocidas que Code podría volver a caer.

### 1.1 Hipótesis inicial errónea: "el optimizador subproduce"

Primer diagnóstico (mi script de tabla maestra v1):
- 28 SKUs INSUFICIENTE (con OFT pero gap > 0).
- 8 BUG_NO_PRODUCE en L1Pet LV.
- GAP TOTAL 24.964 cajas.

**Conclusión apresurada**: el optimizador no produce lo suficiente.

### 1.2 Pausa pedida por el usuario y revisión metódica

El usuario pidió: "Quiero entenderlo y validarlo bien... no quiero un fix incompleto. Cualquier confusión entre cajas y unidades es un bug ENORME, absolutamente inaceptable."

Esa pausa salvó el proyecto de un fix erróneo.

### 1.3 Bug detectado en mi propio script de diagnóstico

Comparando `stock_inicial_cajas = 5240` que reportaba el plan para Mostaza Traverso BOLSA vs `stock_cj = 524` que calculaba mi script (factor 10×, discrepancia gigante), descubrimos:

**El campo `stock_unidades` del parquet de stock contiene CAJAS, no unidades**, aunque el nombre del campo sugiere lo contrario. Confirmado:
- `umed = CJ` para 905 de 906 filas (1 fila en KG ignorada).
- `stock_unidades` total para Mostaza Traverso BOLSA = 5.240, con upc=30. Si fueran unidades serían 174 cajas; si son cajas son 5.240 cajas. El plan dice 5.240 cajas. **Son cajas.**

Mi script dividía `stock_unidades / u_por_caja` pensando que recibía unidades, subestimando el stock real por factores 12-30×. **Toda mi clasificación de "INSUFICIENTE" era ficción de ese bug**.

### 1.4 Diagnóstico correcto (con stock corregido)

Tabla maestra v2 con stock leído correctamente:

| Categoría | SKUs | Lectura |
|---|---|---|
| OK_PRODUCE_BIEN | 47 | Optimizador atiende bien |
| OK_STOCK_SUFICIENTE | 21 | Stock cubre necesidad, no produce correctamente |
| OK_DEMANDA_NULA | 4 | Sin demanda, no produce correctamente |
| BUG_NO_PRODUCE | 1 | Vinagre Tinto Tottus 30x500, único bug real |
| CAPACIDAD_LIMITE | 1 | Mostaza Vintage Doypack, gap chico (14 cj) |

**72 de 74 SKUs atendidos correctamente.** Gap total 162 cj, distribuido en 2 SKUs.

### 1.5 La causa real del "rojo masivo" del dashboard

Triple combo en el frontend que el usuario percibe como "muchos quiebres":

1. **V6.14 incompleto**: el dashboard muestra `Stock Actual = 0 cj` para SKUs sin OFT, aunque tengan stock real significativo (verificamos 261010555 = 496 cj reales, mostrados como 0).
2. **Banner amarillo "OFTs sugeridas no se muestran en la proyección"**: para SKUs con OFT pendiente de aprobación, la curva azul de stock proyectado se traza como si no hubiera producción → cae a 0 y aparece rojo.
3. **Posibles divergencias adicionales** entre cálculos paralelos del backend y frontend que **NO TERMINAMOS DE AUDITAR**.

---

## 2. Validación de unidades — 5 tests pasados

Confianza alta en estos puntos (cada uno validado independientemente):

| Test | Resultado |
|---|---|
| Parquet `stock_unidades` = cajas (umed='CJ' en 99.9%) | ✓ |
| Plan: `cantidad_unidades = cantidad_cajas × u_por_caja` en 50/50 OFTs revisadas | ✓ |
| Plan: `stock_inicial_cajas` del plan = stock parquet en 6/6 SKUs verificados (260010105, 121010290, 121010175, 260010175, 113010290, 141010210) | ✓ |
| Forecast endpoint `/forecast` devuelve cajas en yhat (no unidades). Confirmado comparando con history.real | ✓ |
| Dashboard muestra `Stock Actual = 0 cj` para SKUs sin OFT cuando real es 496-1127 cj. Confirmado en 4 SKUs (111030290, 112010115, 261010555 con 0; vs 111010115, 141010210 con OFT mostrando bien) | ✓ |

**Hallazgo lateral del Test 2**: `batch_min_u` en BD tiene valores fraccionarios sospechosos:
- 111010115: `batch_min_u = 7083`, `upc = 12` → 590.25 cj (no entero)
- 111030290: `batch_min_u = 700`, `upc = 30` → 23.33 cj (no entero)
- 111013290: `batch_min_u = 3667`, `upc = 30` → 122.23 cj (no entero)

Esto sugiere que el `batch_min_u` no fue cargado bien en el Excel original, o que la convención es "cajas redondeadas a unidades permitiendo decimales" (absurda). Es deuda V6.X para revisar con Gerente, no afecta el diagnóstico de hoy.

---

## 3. AUDITORÍA PENDIENTE — Lo que Claude Code tiene que hacer

El usuario observó algo crítico al cierre:

> "me incomoda muchísimo que los cálculos del backend no estén estructuralmente alineados con los del frontend, eso nos va a seguir dando dolores de cabeza"

Tiene razón. **El frontend hace cálculos paralelos al backend** y eso es el origen de V6.14 incompleto y posiblemente otros bugs no descubiertos. Hay que auditarlo en profundidad antes de fixear.

### 3.1 Plan de 3 capas

**Capa A — Auditoría de fórmulas del frontend (LECTURA, no edit)**:
- Listar todos los archivos JSX que muestran datos del backend.
- Para cada uno, identificar **dónde recalcula** vs **dónde lee directamente del payload**.
- Documentar cada cálculo paralelo: qué calcula, con qué fórmula, contra qué fuente.
- Output esperado: un inventario en markdown con líneas de código específicas.

Archivos a revisar (según CLAUDE.md):
- `dashboard/src/components/StockProyeccion.jsx` (~571 líneas) — **el más crítico**
- `dashboard/src/components/DetalleProduccion.jsx` (~646 líneas)
- `dashboard/src/App.js` — incluye "Plan de Producción"
- Componentes de "Forecast de Demanda"

Sospechas a investigar específicamente:
- Cálculo de "Stock Actual (cj)": ¿de dónde lo saca? V6.14 v1 lo intentó arreglar pero falla para SKUs sin OFT.
- Cálculo de "Venta Estimada (cj)": ¿se basa en /forecast? ¿lo agrega correctamente?
- Cálculo de "Stock Mínimo Proy. (cj)": ¿calcula ss_dias × demanda en frontend o lo trae del backend?
- Cálculo de la **curva azul** del gráfico de stock proyectado: ¿iteración propia? ¿incluye OFTs sugeridas o no? El banner amarillo dice que no las incluye.
- Cálculo de "Cobertura Actual (días)": ¿stock / demanda diaria?
- Tabla "Proyección semanal detallada": ¿usa los mismos números que el gráfico?

### 3.2 Capa B — Test de paridad backend↔frontend

Para cada cálculo paralelo identificado, construir un test que compare:
- Lo que el backend dice (o lo que dice la fuente cruda como parquet).
- Lo que el frontend calcula.

Reportar discrepancias por SKU, no en agregado.

### 3.3 Capa C — Fixes coherentes

**Regla de oro arquitectónica**: cada cálculo tiene **una sola fuente de verdad**. Idealmente, todo se calcula en el backend y el frontend solo presenta.

Fixes anticipados:

**Fix A (V6.14 v2)** — Stock por SKU disponible para TODOS los SKUs:
- Backend (`main.py` o donde se arme la respuesta del plan): agregar campo `stock_por_sku: {sku: cajas}` con todos los SKUs del catálogo activo.
- Frontend (`StockProyeccion.jsx` líneas 281-294): leer `stock_por_sku[sku]` directamente, eliminar la dependencia de `ordenesSku[0]`.

**Fix B (banner amarillo)** — Curva proyectada considerando OFTs sugeridas:
- Decisión de diseño primero: ¿la curva azul debe incluir OFTs sugeridas?
- Opción razonable: por defecto incluir (muestra cómo será al aprobar), con toggle "solo aprobado" para validación.

**Fix C (otros)** — Lo que aparezca de la Capa B.

### 3.4 Tiempo estimado

| Capa | Tiempo |
|---|---|
| A — Auditoría | 1h |
| B — Tests de paridad | 1h |
| C — Fixes | 1-2h |
| **Total** | **3-4h** |

Cabe perfectamente en la jornada del lunes 12/05 (calendario nominal) que el usuario tenía planificada para Fix A + V6.11 + V6.12-mini + manual del usuario. Re-priorizar: el manual y V6.11 quedan para martes.

---

## 4. Estado git al cierre

Sin cambios de código hoy. Sigue en `feature/v1.3-cascada`, commit más reciente `82cef34` (V6.12-mini del 13/05 nominal). Backups BD del día disponibles en `/home/ubuntu/backups/`.

---

## 5. Deudas técnicas actualizadas

| ID | Descripción | Prioridad |
|---|---|---|
| V6.11 | Observabilidad SKUs sin forecast (banner amarillo en UI) | Post-vacaciones |
| V6.12-mini | ✅ HECHO 13/05 |
| V6.12-completa | Degradación elegante o fallback MRP clásico para SKUs filtrados | Post-vacaciones |
| V6.14 v1 | ✅ HECHO 12/05 (parcial) |
| **V6.14 v2** | **Dashboard muestra Stock 0 para SKUs sin OFT — fix con `stock_por_sku` en payload** | **Pre-vacaciones (CRÍTICO)** |
| V6.17 | SS sobredimensionado en L1Pet LV (15 días uniforme) | Post-vacaciones, conversación con Gerente |
| V6.18 | ✅ HECHO 12/05 |
| V6.19 | Modo blando para buscar SS factibles | Post-vacaciones |
| V6.20 | W_USO_LINEA | Post-vacaciones |
| V6.21 | batch_min restricción blanda | Post-vacaciones |
| V6.23 | Detalle Producción muestra OFTs partidas como cuadritos | Post-vacaciones |
| V6.24 | Fragmentación temporal del optimizador (requiere F2 sequencer) | Post-vacaciones |
| V6.25 | Timeout endpoint /params/importar-excel muy corto | Post-vacaciones |
| **V6.26 NUEVA** | **Banner amarillo: curva azul ignora OFTs sugeridas → reformular cálculo** | **Pre-vacaciones (CRÍTICO)** |
| **V6.27 NUEVA** | **Auditoría completa cálculos paralelos backend↔frontend** | **Pre-vacaciones (CRÍTICO, paraguas de V6.14 v2 + V6.26)** |
| **V6.28 NUEVA** | **Vinagre Tinto Tottus 30x500 (112030290): único SKU sin OFT por bug del optimizador (gap 148 cj)** | Post-vacaciones, baja |
| **V6.29 NUEVA** | **`batch_min_u` con valores fraccionarios sospechosos en BD: revisar con Gerente** | Post-vacaciones |

---

## 6. Archivos generados hoy en el server

Disponibles en el contenedor `traverso_forecast`:
- `/tmp/plan_h4_diag.json` — plan h=4 vigente, ~80 KB
- `/tmp/tabla_maestra_v2.csv` — 74 SKUs con diagnóstico completo (también copiado a `/tmp/` del host)

Útiles para Claude Code en la próxima sesión:
- `/tmp/tabla_maestra.py` — script v1 con bug de unidades (no usar)
- `/tmp/tabla_maestra_v2.py` — script corregido, fuente de la tabla actual
- `/tmp/validar_unidades.py` — los 5 tests de validación
- `/tmp/diag_insuf.py` — análisis de N_max=4 mordiendo en L1Pet LV

---

## 7. Cosas que NO son problema (descartadas hoy con datos)

- ❌ "El optimizador subproduce los SKUs core" — falso, el problema era mi script de diagnóstico.
- ❌ "Hay confusión sistémica de unidades en el backend" — falso, los 5 tests confirman coherencia en parquet+plan+forecast.
- ❌ "El SS sobredimensionado está causando los rojos del dashboard" — parcialmente: V6.17 es real pero no explica los Stock=0 falsos.
- ❌ "Doypack saturada está afectando muchos SKUs" — sí pero solo CAPACIDAD_LIMITE para 1 SKU con gap chico (14 cj). Los otros Doypack o tienen OFT (atendidos) o tienen stock suficiente.
- ❌ "N_max=4 mordiendo en L1Pet LV genera quiebres" — sí, 7/8 días al N=4 en sem 1, pero la asignación que el optimizador hizo es la correcta dada esa restricción. Los SKUs que quedan fuera tienen stock suficiente para h=4.

---

## 8. Decisiones tomadas hoy

| ID | Decisión |
|---|---|
| D1 | Pausa investigación a fondo antes de cualquier fix |
| D2 | Stock parquet se lee SIEMPRE como cajas (`umed='CJ'`), no dividir por upc |
| D3 | Optimizador NO requiere fix prioritario (excepto Vinagre Tinto Tottus, baja) |
| D4 | Fix prioritario es V6.14 v2 + V6.26 (banner amarillo) — el dashboard |
| D5 | Auditoría exhaustiva backend↔frontend (V6.27) ANTES de tocar nada |
| D6 | Dividir trabajo: chat web para estrategia + Code para auditoría e implementación |

---

## 9. Primera invocación recomendada en Claude Code

> Lee `CLAUDE.md`, `docs/ESTADO_TECNICO_PROYECTO_09-05-26.md`, `docs/ESTADO_TECNICO_PROYECTO_12-05-26.md`, `docs/ESTADO_TECNICO_PROYECTO_13-05-26.md` y `docs/ESTADO_TECNICO_PROYECTO_HOY.md` (este snapshot).
>
> Confirmame qué entendiste del estado actual. Arranquemos por la **Capa A** de la auditoría descripta en §3.1 del snapshot de hoy: leer `dashboard/src/components/StockProyeccion.jsx`, `dashboard/src/components/DetalleProduccion.jsx` y `dashboard/src/App.js`, identificar todos los cálculos paralelos al backend, y reportarme un inventario detallado con números de línea. NO toques código todavía — solo análisis.
>
> El plan vigente está en `/tmp/plan_h4_diag.json` del contenedor `traverso_forecast` y la tabla diagnóstica en `/tmp/tabla_maestra_v2.csv`. Usalos como referencia.

---

## 10. Tag de retorno seguro

Para volver al tag estable v1.2-piloto:
```bash
git checkout v1.2-piloto
docker compose down && docker compose up -d --build
```

Para volver al estado al cierre del 13/05 nominal (real domingo): `git checkout 82cef34`.

Backups BD disponibles en `/home/ubuntu/backups/`.

---

*Cerrado al fin de la sesión chat web del 11/05/2026 real (nominal: martes 14/05). Próxima sesión: Claude Code ejecuta auditoría + fixes según §3.*
