# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Cierre del día — 12/05/2026 (noche)

> **Nota sobre fechas**: este snapshot continúa la convención de fechas reales inaugurada por `11-05-26-cierre-B1.md`. Cubre la segunda mitad del 12/05 (tarde-noche), siguiente al snapshot `12-05-26-tarde.md` cuyo cierre dejó V6.37 identificado pero pendiente.

---

## Resumen ejecutivo de la sesión

Sesión densa (~7h) dedicada a resolver V6.37 (bug crítico del optimizador descubierto al cierre del 12/05 tarde) y a un overhaul completo de UX del flujo de edición de OFs en Detalle Producción. **Nueve deudas técnicas cerradas en una sola sesión**, todas validadas end-to-end con una prueba operacional realista que el usuario diseñó: modificar/desaprobar OFs hasta llevar todas las líneas a cap=100% sin sobrecargas.

El sistema queda **listo para piloto del 15/05** con un flujo de edición robusto: el operador puede aprobar/editar/desaprobar OFs en cadena sin esperar regeneraciones, ver feedback visual instantáneo, y un badge global indica cuándo el plan está stale.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Commits del día | 7 (V6.37 + logger fix + V6.42 + V6.38 + V6.40 + V6.44/V6.45/V6.46 + V6.48 + V6.49 + V6.39) |
| Archivos tocados | 4 (forecast/main.py, forecast/optimizer.py, forecast/ordenes.py, dashboard/src/App.js, dashboard/src/components/DetalleProduccion.jsx) |
| Líneas netas backend | +94 (optimizer.py) + ~30 (main.py) + ~30 (ordenes.py) |
| Líneas netas frontend | +35 (App.js) - 14 (DetalleProduccion.jsx, neta tras eliminar ModalDesplazar) |
| Tags creados | `v1.3-v6.37`, `v1.3-v6.37-v6.42`, `v1.3-v6.46`, `v1.3-piloto-ready` |
| Smoke tests | ✓ 30+ tests browser + 5+ verificaciones BD + prueba operacional end-to-end |
| Deudas cerradas | 9 (V6.37, V6.38, V6.39, V6.40, V6.42, V6.44, V6.45, V6.46, V6.48, V6.49) |
| Deudas nuevas registradas | 4 (V6.41, V6.43, V6.45.2, V6.47) |
| Status optimizer | FEASIBLE @60s, 154-178 OFTs según contexto |

---

## 1. Bloque A — V6.37: optimizer respeta cap y N_max por OFs aprobadas

### Origen del bug

Reportado al cierre del 12/05 tarde como bug crítico descubierto en el dashboard: indicadores mostraban Doypack 12/05 al **400%** y L1Pet LV 12/05 al **102%** con **8 SKUs/día** (violando N_MAX=4). Pre-V6.37 latente: F3 destapó el problema al permitir aprobaciones múltiples del mismo SKU/día/línea.

### Diagnóstico

Auditoría leyendo `forecast/main.py` (~720 líneas), `forecast/optimizer.py` (~1185 líneas), `forecast/ordenes.py` (~445 líneas), `forecast/db_mrp.py` (~563 líneas):

**Causa raíz única** (no eran tres hipótesis sino una sola con dos síntomas): el optimizer modelaba las OFs aprobadas **únicamente como movimiento de inventario**, no como ocupación de recurso productivo.

| Restricción | ¿Consideraba aprobadas? |
|---|---|
| Balance de stock | **Sí** — vía `_entradas_del_dia` por `fecha_entrada` |
| R1a — Cap diaria agregada | **No** — `terms` solo sumaba `cajas[d,s,l]` e `inicio[d,s,l]` (variables del modelo) |
| R1b — N_MAX=4 SKUs | **No** — `asigs_dl` solo sumaba `asig[d,s,l]` (variables del modelo) |

El optimizer creía que tenía 100% de capacidad y 4 slots libres cada día/línea aunque hubiera aprobadas ya consumiéndolos.

**Falta de información estructural en `entradas_fijas`**: el contrato llevaba `{sku → [{fecha_entrada, cantidad_cajas, numero_of, aprobada}]}`. Para restar cap y slot N_MAX faltaban `fecha_lanzamiento` (día de producción) y `linea`.

### Verificación BD

Confirmado que `mrp_ordenes.fecha_lanzamiento` y `mrp_ordenes.linea` estaban poblados para las 13 aprobaciones existentes post-F3 (ningún null crítico).

### Fix implementado

**5 patches coordinados** (commit `fd1d6f8`):

1. **`main.py:418-433`** — propaga `fecha_lanzamiento_real` + `linea` desde BD al dict `entradas_fijas`.
2. **`optimizer.py:875-893`** — propaga ambos campos a `entradas_aprobadas_rich`.
3. **`optimizer.py:370-460`** — pre-cómputo `aprobadas_u_dl` + `aprobadas_skus_dl`. Descuento en R1a (`cap_libre = max(0, cap_l_d - u_aprobadas_dl)`) y R1b (`n_max_libre = max(0, N_MAX - n_aprobadas)`). Prohíbe asig=1 para SKUs ya aprobados ese (d, l) (decisión usuario: operador edita la OF existente). R12 ajustada: si hay aprobadas, todas las OFTs nuevas pagan setup.
4. **`optimizer.py:_post_procesar`** — expone `m.sobrecargas_aprobadas` en el resultado.
5. **`optimizer.py:optimizar_plan`** — propaga al `diag` que vuelve a `main.py`.

### Hotfix V6.37 — `logger` no definido (commit `9aa1975`)

Primer deploy de V6.37 cayó al `except` de `main.py` con `name 'logger' is not defined`. Causa: `logger.warning` en línea 421 del pre-cómputo, pero `logger` se definía solo dentro de `optimizar_plan()` (línea 838). Fix: `import logging` + `logger = logging.getLogger("optimizer")` a nivel módulo.

### Validación V6.37

- Caso testigo Doypack 12/05 (16.200u aprobadas vs cap 5.400u): warning `[V6.37] 1 (linea,dia) saturados solo por OFs aprobadas` se dispara correctamente, optimizer no agrega OFTs ese (d, l).
- `optimizado=True, FEASIBLE @60s, 166 OFTs, 1 sobrecarga detectada`.
- Validación visual en dashboard: 3 líneas (Doypack, L1Pet LV, Sachetera) muestran restricciones respetadas.

---

## 2. Bloque B — V6.42: visualización preserva linea/fecha reales

### Bug descubierto al validar V6.37 visualmente

L1Pet LV 12/05 en la captura mostraba **5 OFs** (3 aprobadas + 2 OFTs), violando N_max=4. Pero curl directo al backend confirmaba que el optimizer SÍ respetaba las restricciones.

### Diagnóstico

Al cruzar BD vs response del plan:

| Origen | OFs aprobadas L1Pet LV 12/05 |
|---|---|
| BD (`listar_aprobadas_db`) | Solo OF-2026-00002 (sku 111010175) |
| `plan.ordenes` | OF-00013, OF-00011, OF-00002 |

OF-00013 y OF-00011 estaban en BD como **L1Pet A**, pero en plan response aparecían como **L1Pet LV**.

**Bug pre-existente latente desde siempre, expuesto por F3+V6.37**: `main.py:471-517` al inyectar las aprobadas en `plan.ordenes` para el frontend, reescribía dos campos:

```python
f_lan = f_ent - _td_helper(days=int(round(lt_ap * 7)))  # ignora fecha_lanzamiento_real
"linea": getattr(sp_ap, "linea_preferida", None)  # ignora la linea aprobada
```

El sistema retornaba `linea_preferida` del SKU en lugar de la línea aprobada por el operador, y recalculaba `fecha_lanzamiento` desde lead_time en lugar de usar `fecha_lanzamiento_real`. **Pre-F3 esto era invisible** porque el operador no podía editar esos campos, así que linea siempre coincidía con linea_preferida.

### Fix (commit `389a6e3`)

`main.py:471-517` ahora usa `ent["linea"]` y `ent["fecha_lanzamiento"]` con fallback al comportamiento viejo si los campos vinieran vacíos (datos legacy pre-F3).

### Validación V6.42

Cuenta post-fix de Doypack/L1Pet/Sachetera 12/05: distribuciones exactamente como BD esperaba.

- **L1Pet A 12/05**: 3 APR + 1 OFT = 4 SKUs (N_max al límite) ✅
- **L1Pet LV 12/05**: 1 APR + 2 OFT = 3 SKUs ✅
- **Doypack 12/05**: 3 APR + 0 OFT = 3 SKUs ✅
- **Sachetera 12/05**: 1 APR (SKU 250010105) + 0 OFT del mismo SKU ✅

---

## 3. Bloque C — V6.38: plan no auto-regenera tras editar OF

### Necesidad operacional

Reportada por usuario en reunión: "Al modificar o desaprobar una OF, se gatilla automáticamente una regeneración del plan. Hay que desactivarlo... puede ser una pesadilla si el operador tiene que modificar varias órdenes" (5 edits × 90s = inutilizable).

### Diagnóstico

`App.js` tenía 3 puntos de invocación a `runPlan()`:

| Línea | Trigger | Decisión |
|---|---|---|
| 962 | `onSolicitarPlan` (StockProyeccion) | Mantener — click manual |
| 968 | `onPlanChanged` (DetalleProduccion) | **Quitar** — auto-trigger silencioso |
| 970 | `onSolicitarPlan` (DetalleProduccion) | Mantener — botón "Regenerar Plan" |

### Fix (commit `8b055f5` + `c2bdafd`)

**Patches App.js**:
1. Nuevo state `planStale` (boolean) con persistencia en localStorage.
2. Helper `marcarPlanStale()` que setea flag + localStorage.
3. `runPlan` limpia el flag tras éxito.
4. `onPlanChanged` ahora invoca `marcarPlanStale()` en vez de `runPlan()`.
5. **Badge global en topbar** "⚠ Plan desactualizado — Regenerar" visible en TODAS las pestañas, clickeable para navegar a Plan.

Diseño UX confirmado con usuario antes de implementar: opción (a) — solo badge ámbar, grilla queda igual, operador decide cuándo recalcular.

**Bug intermedio resuelto**: primer deploy puso el badge solo en `{activeTab === 'plan'}`, así que cuando el operador editaba en pestaña "Detalle Producción" el flag se seteaba pero el badge era invisible. Fix: mover a topbar global.

### Validación V6.38

Los 7 smoke tests pasaron: marca/limpia stale correctamente, persiste tras F5, click navega a Plan, no auto-regenera tras edición.

---

## 4. Bloque D — V6.39: badges del grid abren modales canónicos

### Estado pre-V6.39

Click en badge de OF dentro del grid de días abría `ModalDesplazar` (legacy, solo permitía cambiar fecha). UX inconsistente con el botón "Editar" de la tabla, que abría `ModalEditar` (más completo).

### Fix (commit `82d2c4c`)

`DetalleProduccion.jsx`:
- Función `ModalDesplazar` eliminada (~90 líneas).
- State `modalDesplazar` y su render eliminados.
- `onClick` del badge decide según `estaAprobada`: aprobada → `ModalEditar`; pendiente → `onAprobar(o)` (mismo modal que botón "Aprobar" de la tabla).
- Tooltip refleja la acción: "Click para editar / retirar aprobación" vs "Click para aprobar".

Diseño confirmado con usuario: ambos estados abren modal (decisión A vs C). Razón: simetría con tabla, menos confusión.

### Validación V6.39

Los 3 smoke tests pasaron (badge aprobada → ModalEditar, badge pendiente → modal aprobación, tooltips correctos).

---

## 5. Bloque E — V6.40: grid ordenado cronológicamente

### Problema

La tabla por línea mostraba las filas en orden arbitrario (probablemente orden de generación del optimizer). Difícil leer cronológicamente.

### Fix (commit `9c1aa18`)

`DetalleProduccion.jsx:454-485`: `ordenesTabla` se ordena por `fecha_lanzamiento_real` (si está aprobada) o `fecha_lanzamiento` del optimizer. Desempate por `sku` y luego por `numero_of` para determinismo entre renders.

Esfuerzo real: ~15 minutos. Esperado: 30 min.

---

## 6. Bloque F — V6.44, V6.45, V6.46: UX overhaul de edición

### V6.44 — Reflejo local instantáneo

**Problema reportado por usuario**: tras editar OF aprobada, el cambio se persistía en BD pero la UI seguía mostrando el plan viejo hasta refrescar. Efecto colateral lógico de V6.38 (sin auto-regenerar plan, sin refresh visual).

**Fix**: `ModalEditar.handleGuardar` captura la respuesta del backend (`aprobData`) y la propaga al padre vía callback `onAprobacionEditada(aprobUpdated)`. App.js actualiza `ordenesAprobadas` con `.map`. Para desaprobación, `onAprobacionRetirada(numero_of)` quita de `ordenesAprobadas` y marca `aprobada=false` en `plan.ordenes`. El grid rearma porque `aprobMap` cambia.

### V6.45 — Edición estable sin crear OFs duplicadas

**Bug detectado en testing post-V6.44**: al editar `fecha_lanzamiento` de una OF aprobada, el backend creaba una OF nueva (00014, 00015...) en lugar de actualizar la existente.

**Diagnóstico**: `ordenes.py:117-120` hacía lookup por PK F3 `(sku, fecha_lanzamiento, linea)` — falla justamente cuando el operador edita la `fecha_lanzamiento` porque busca por la fecha NUEVA que aún no existe en BD. Cae al `else next_numero_of()` y crea OF duplicada.

**Fix**: `OrdenAprobar` acepta `numero_of` opcional. Si viene, se usa directo (saltea lookup F3). ModalEditar y ModalDesplazar envían `numero_of` explícito.

Verificado con `upsert_orden` (db_mrp.py:152-169) — actualiza por `numero_of` si ya existe, sin crear duplicado.

### V6.46 — Auto-recalculo fecha_entrada

**Bug detectado por usuario en reunión inicial del bloque**: "al editar fecha de lanzamiento, la fecha de entrada no cambia. Es un tema importante porque afecta la disponibilidad de inventario".

**Fix**: `ModalEditar` agrega `useEffect` que escucha cambios de `fechaLanz` y recalcula `fechaEnt = fechaLanz + lead_time_sem * 7 días`. Lead_time se obtiene de `orden.lead_time_sem` (campo del plan). Si el operador toca manualmente fechaEnt, se setea flag `fechaEntEditada=true` que respeta su override.

### Limpieza de BD durante testing

- OF-2026-00014 (huérfana creada por bug V6.45 antes del fix): eliminada manualmente. 4 filas en `mrp_aprobaciones` + 1 en `mrp_ordenes`. Versioning del backend funcionó correctamente — las 3 primeras MODIFICADA + 1 APROBADA = historial inmutable.

### Validación V6.45 + V6.46

- OF-00010 editada 3 veces seguidas (fecha + cantidad): mantuvo número de OF (versiones 1→2→3 en BD).
- Auto-recálculo fecha_entrada: 14/05 → 16/05 manual → cambio fecha_lanzamiento a 15/05 → fechaEnt NO cambió (respetó override).
- Cero OFs duplicadas tras 4 ediciones distintas.

---

## 7. Bloque G — V6.48 y V6.49: sincronización backend ↔ frontend

### Bug observacional crítico

Durante prueba operacional end-to-end del usuario: tras desaprobar OF-2026-00010 y regenerar plan, la OF seguía apareciendo en el dashboard como "Pendiente" con cap saturada 102% (5.520u).

### V6.48 — Refetch `ordenesAprobadas` tras runPlan

**Diagnóstico**: cruce BD vs `/ordenes/aprobadas` vs state local. BD decía APROBADA, endpoint backend la devolvía, pero `ordenesAprobadas` en App.js no la tenía. Causa: V6.44 actualiza state local (`setOrdenesAprobadas(prev => prev.filter(...))`) pero `runPlan` no re-sincroniza al regenerar. Modificaciones locales divergentes de BD quedaban congeladas.

**Impacto operacional grave**: el operador veía "Aprobar" en una OF aprobada; al clickear re-aprobaba sin querer (pensando que estaba desaprobando), quedando OFs aprobadas que el operador creyó retirar.

**Fix (commit `8b055f5` extendido)**: tras `setPlan(data)` exitoso en `runPlan`, se hace `await axios.get('/ordenes/aprobadas')` + `setOrdenesAprobadas(...)`. Reconcilia state local con BD cada vez que el plan se regenera. +5 líneas.

### V6.49 — Desaprobación efectivamente llega al backend

**Diagnóstico post-V6.48**: usuario intentó desaprobar OF-00010 (esta vez con dashboard mostrando estado consistente). Click "Retirar aprobación", DELETE HTTP 200, frontend reflejó cambio... pero BD mostraba versión 3 sigue APROBADA (sin nueva versión 4 CANCELADA).

**Análisis Network + código**: el endpoint `cancelar_orden` (ordenes.py:186-198) recibía el path `260030255__2026-05-10__2026-05-13` y hacía `get_orden_by_key(sku, sn, se)`. Pero la firma real de la función es `get_orden_by_key(sku, fecha_lanzamiento, linea)` — comparaba `semana_necesidad` contra `fecha_lanzamiento` y `semana_emision` contra `linea`. Nunca encontraba la orden, devolvía `{ok: false}` con HTTP 200. El frontend no validaba `data.ok` y procedía a actualizar state local como si hubiera cancelado.

**Bug latente desde F3** (sept 2025): pre-F3 el match funcionaba por coincidencia porque `semana_emision = fecha_lanzamiento` y `linea` era constante. V6.42 explícitamente alineó `semana_emision = fecha_lanzamiento` en el plan response para visualización correcta — eso rompió definitivamente el match silenciosamente.

**Fix (commit pendiente al cierre)**:
- `ordenes.py`: endpoint cancelar acepta dos formatos en path:
  * `numero_of` directo (`OF-2026-XXXXX`, preferido) — bypassea el lookup roto.
  * Key legacy `sku__sn__se` — compatibilidad.
- `DetalleProduccion.jsx`: `handleCancelar` envía `numero_of` directo y valida `data.ok` del response.

### Validación V6.48 + V6.49

- OF-00010 desaprobada: BD muestra `id=29 estado=CANCELADA` (versión 3 cambió de APROBADA → CANCELADA, comportamiento esperado de `cancelar_orden_db` que hace UPDATE).
- Plan regenerado tras desaprobar: badge "Plan desactualizado" desaparece, OF-00010 no aparece en grid Doypack 13/05, sin sobrecargas reportadas.

---

## 8. Prueba operacional end-to-end

### Diseño de la prueba (idea del usuario)

> "obtengamos un detalle de todas las OF y OFT de la semana 10/05 al 16/05. Luego yo voy a modificar todo para que no quede ninguna línea con exceso de capacidad. Revisamos si quedó todo correcto en la BD. Luego vuelvo a regenerar el plan y revisamos si no se produce ninguna violación de cap o nro de SKU"

### Snapshot inicial

Plan generado en horizonte 4 semanas:
- 178 OFs total en plan.
- Sobrecargas reportadas: 2 (Doypack 13/05 con 19.320u > 5.400u, Doypack 14/05 con 6.600u > 5.400u).
- N_max=4 respetado en todas las líneas.

### Modificaciones del usuario

- OF-2026-00010 (260030255 MOSTAZA TOTTUS): desaprobada.
- OF-2026-00016 (210030255 AJI CREMA TOTTUS): cantidad 300→225 cj.
- OF-2026-00015 (210010175 AJI CREMA TRAVERSO): cantidad 550→450 cj.
- OF-2026-00012 (210010175 AJI CREMA TRAVERSO): cantidad 550→450 cj.

### Resultado final post-regeneración

**Cero sobrecargas reportadas. Cero violaciones N_max. Plan limpio.**

Doypack semana 10-16/05:
- 12/05: OF-00004 → 5.400u / 100% / 0% libre
- 13/05: OF-00016 → 5.400u / 100% / 0% libre
- 14/05: OF-00015 → 5.400u / 100% / 0% libre
- 15/05: OF-00012 → 5.400u / 100% / 0% libre

4 OFs aprobadas, una por día, todas exactamente al 100%. Configuración óptima.

```
$ docker compose logs forecast --tail=10 --no-color | grep V6.37
(vacío)
```

---

## 9. Decisiones de diseño relevantes

### V6.37 — Política sobre sobrecargas por aprobadas solas
- **Decisión**: si la línea ya está excedida (por cap o N_max), se asume capacidad libre = 0 con advertencia. El operador deberá decidir qué hacer con eso.
- Implementación: `cap_libre = max(0, cap_l_d - u_aprobadas)`. Reporte en `diag_opt.sobrecargas_aprobadas` + log.

### V6.37 — Prohibición de OFT-duplicada cuando SKU ya aprobado
- **Decisión A**: si un SKU tiene OF aprobada en (d, l), el optimizer NO puede agregar OFT del mismo SKU ese (d, l). El operador edita la OF existente si necesita más cajas.
- Razón: más limpio operacionalmente. Si en post-piloto aparece caso de "extender corrida ya aprobada", se revisita.

### V6.37 — R12 con aprobadas presentes
- **Decisión B**: si hay aprobada en (d, l), la "primera del día gratis" es la aprobada (la línea físicamente arrancó con ella). Todas las OFTs nuevas pagan setup.

### V6.38 — UX badge stale
- **Decisión (a)**: solo badge ámbar visible en topbar, grilla queda igual. El operador decide cuándo recalcular.
- Razón: más simple, el operador ve claramente que el plan está stale sin perder contexto.

### V6.39 — Click badge OFT pendiente
- **Decisión (A)**: ambos casos abren modal (aprobada → editar, pendiente → aprobar).
- Razón: simetría con la tabla. UX consistente.

### V6.45 — Identificación estable de OF
- **Decisión**: agregar `numero_of` opcional al request de aprobar. Si viene, se usa directo (saltea lookup PK F3).
- Razón: la PK F3 `(sku, fl, linea)` se rompe cuando el operador edita justamente uno de esos campos.

### V6.49 — Endpoint cancelar
- **Decisión**: aceptar dos formatos en path (`numero_of` directo o key legacy). Mantener key legacy por compatibilidad aunque esté roto desde F3 — solo afecta clientes externos hipotéticos.

---

## 10. Deudas pendientes (post-vacaciones)

| ID | Descripción | Prioridad | Esfuerzo |
|---|---|---|---|
| V6.41 | "Doypack 4" aparece como línea separada de "Doypack" en grid. Verificar primero si es bug visual (dashboard agrupando mal) o si BD tiene la línea como real. | Baja | 30 min - 1h |
| V6.43 | Evaluar si aprobar una OFT individual debería marcar plan como stale. Hoy no marca (las aprobaciones puntuales no afectan grid global). Si el operador no quiere regenerar tras 1 aprobación pero sí tras varias, dejar como está. | Baja | 0 (decisión) |
| V6.45.2 | Tras desaprobar, la OF mantiene prefijo `OF-XXXXX` en `mrp_ordenes` en lugar de volver a `OFT-XXXXX`. No afecta operación (listar_aprobadas_db hace INNER JOIN y filtra correctamente), pero queda ruido visual mientras el plan esté stale. | Baja | 30 min |
| V6.47 | Crear OF completamente nueva desde Detalle Producción (botón explícito, no derivada de OFT del optimizer). UX a definir: ¿botón global por línea? ¿picker SKU + cantidad + fecha + línea? | Media (feature) | 2-3h |

---

## 11. Estado del proyecto al cierre

**Tags Git:**
- `v1.3-piloto-ready` ← punto de retorno seguro post-V6.49.

**Branch**: `feature/v1.3-cascada` con 7 commits del día.

**Containers operativos:**
- `traverso_forecast` (uvicorn FastAPI, optimizer + endpoints)
- `traverso_dashboard` (react-scripts dev server con hot-reload)
- `traverso_mrp_db` (PostgreSQL 16-alpine)

**Plan productivo actual** (post-prueba operacional):
- 13 OFs aprobadas en BD (numerización OF-2026-00001 a OF-2026-00016 con huecos 00014 eliminada manualmente, OF-00010 cancelada).
- Cero sobrecargas en Doypack 12-15/05 (configuración óptima por modificación del operador).
- Optimizer en horizonte 4 semanas: FEASIBLE @60s, ~150 OFTs.

---

## 12. Pendientes pre-vacaciones (martes 13/05 + miércoles 14/05)

1. **Manual del usuario** (estimado 3-4h). Mañana 13/05.
2. **PDF v8 para gerencia** (estimado 2-3h). Incluir screenshots actualizados con los fixes V6.37 a V6.49. Probablemente 14/05.
3. **Comunicación al equipo** (estimado 30 min). 14/05.
4. **Vacaciones**: del 15/05 (post-comunicación) en adelante.

**Prueba del 15/05 con equipo**: el sistema está listo. El flujo principal del operador (aprobar/editar/desaprobar OFs, regenerar plan) está robusto y validado end-to-end con un caso operacional realista que el propio usuario diseñó.

---

## 13. Observaciones finales

- **V6.49 reveló bug latente desde F3** (sept 2025). El testing end-to-end del 12/05 fue el primer momento donde un usuario realmente desaprobaba OFs en producción. Pre-F3 el flujo no era "desaprobar fácil" porque las pantallas no lo soportaban claramente.
- **Patrón emergente del día**: cada fix de UX (V6.38 → V6.44 → V6.45 → V6.46 → V6.48 → V6.49) reveló el siguiente bug que estaba enmascarado por el comportamiento anterior. V6.38 (no auto-regenerar) destapó V6.44 (sin reflejo local quedaba inconsistente). V6.45 (numero_of estable) destapó V6.46 (fecha_entrada no se recalculaba). V6.48 (refetch state) destapó V6.49 (cancelar no funcionaba). Cada uno descubierto por testing del usuario, no por auditoría preventiva.
- **Cantidad de fixes en una sesión inusual** (9 cerrados). El día empezó con un solo bug crítico (V6.37) que al resolverse expuso una cascada. Llevamos disciplina de no perder ninguno: cada bug nuevo se diagnosticó hasta causa raíz antes de patchear.
- **Patrón de feedback recursivo del usuario**: el usuario probó cada fix activamente, reportó bugs nuevos con captura + descripción, y diseñó la prueba final end-to-end. Sin esto la sesión hubiera cerrado con solo V6.37 y los otros 8 bugs habrían explotado en producción el 15/05.
