# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Cierre del día — 12/05/2026 (tarde)

> **Nota sobre fechas**: este snapshot usa fechas reales (no calendario nominal). Sesiones previas (`12-05-26.md`, `13-05-26.md`, `HOY.md`) usaban fechas nominales que corrían adelantadas respecto al real. El snapshot del 11/05/2026 real (`11-05-26-cierre-B1.md`) inauguró la convención de fechas reales que continúa este documento.

---

## Resumen ejecutivo de la sesión

Sesión larga (~5h) dedicada a tres bloques estructurales: (1) auditoría y fix completo del flujo de aprobación de órdenes con migración estructural F3 del v1.3 design doc; (2) eliminación del auto-trigger del plan en cada refresh con persistencia via localStorage (V6.36); (3) nueva pestaña "Programación Diaria" con vista imprimible de OFs aprobadas por fecha.

Cierre del día con sistema operativo, robusto para pruebas del 15/05, y un patrón nuevo de generación de PDFs (`window.print()` con CSS de impresión) que sirve de base para futuras vistas imprimibles.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Commits del día | 2 (`5332405` F3 + aprobaciones, `8698262` Prog. Diaria + V6.36) |
| Archivos tocados | 10 (7 backend, 2 frontend, 1 migración SQL) |
| Líneas netas backend | -7 |
| Líneas netas frontend | +345 (la mayoría por componente nuevo) |
| Migración SQL aplicada | ✓ (con backup pre-cambio) |
| Smoke tests browser | ✓ (4 tests aprobación + impresión Programación Diaria) |
| Deudas cerradas | 5 (V6.32, V6.36 parcial, P21/P22 sobre Detalle, vinculadas de B1) |
| Deudas nuevas | 2 (V6.34, V6.35) |
| Status optimizer | FEASIBLE @60s, 172 OFTs únicos (vs 77 colisiones pre-F3) |

---

## 1. Bloque A — F3 + fix aprobaciones (commit `5332405`)

### Bugs originalmente reportados

El usuario reportó 3 bugs en aprobaciones que se descubrieron como síntomas de un mismo bug estructural:

1. PDF no se generaba al aprobar.
2. Orden aprobada no aparecía como aprobada hasta regenerar plan.
3. Aprobar desde "Detalle Producción" saltaba inesperadamente a "Plan de Producción".
4. (Descubierto en diagnóstico) Link al PDF en la tabla llevaba a la pestaña Forecast en lugar de descargar.
5. (Descubierto en diagnóstico) OFs aprobadas quedaban al final de la lista, no intercaladas por fecha.

### Causa raíz estructural

Auditoría leyendo `main.py` (792 líneas), `ordenes.py` (437 líneas), `App.js` (900 líneas):

- **Bug 3 trivial**: `App.js:892` tenía un `setActiveTab('plan')` residual en el `onAprobar` de DetalleProduccion.
- **Bug 1+2 mismo bug**: el frontend matcheaba ordenes plan ↔ aprobadas por `o.numero_of`. Pre-aprobación `o.numero_of = "OFT-..."` (tentativo determinístico por hash); post-aprobación backend devolvía `aprobData.numero_of = "OF-..."` (correlativo definitivo). Sin match → badge ni link PDF aparecían hasta el siguiente `runPlan` (que rebatizaba el OFT por OF).
- **Código muerto**: `main.py:723-785` tenía 5 endpoints `/ordenes/*` duplicados (ya servidos por router de `ordenes.py`). Inalcanzables o con NameError. Eliminados.

Tras un primer intento de fix con match por tupla `(sku, semana_emision, semana_necesidad)`, smoke test reveló que ese match no era único: aprobar el SKU 250010105 actualizaba **3 filas simultáneamente** en el frontend.

Análisis profundo del JSON del plan:
- 186 OFTs totales, 134 tuplas `(sku, sem_emi, sem_nec)` únicas.
- **77 de 180 OFTs (~43%) en tuplas con duplicados**.
- SKU 250010105 con 5+ OFTs todas mismo `(sku, 2026-05-24, 2026-05-24)`.

Causa: `numero_of_tentativo(sku, semana_necesidad, semana_emision)` en `db_mrp.py:131` hasheaba 3 campos no únicos. PK de `mrp_ordenes` era la misma triple → aprobar una OFT del batch "aprobaba" implícitamente las otras del mismo SKU/semana.

### Decisión: F3 ahora, no post-piloto

El doc de arquitectura v1.3 ya documentaba esto como **F3** ("post-piloto"): cambiar PK de `(sku, semana_emision)` a `(sku, fecha_lanzamiento, linea)`. Decisión conjunta: hacer F3 ahora, no post-vacaciones — bloqueante para pruebas del 15/05.

### Implementación F3

1. **Backup BD**: `/home/ubuntu/backups/mrp_db_pre_F3_20260512_122026.sql` (154 KB).
2. **Migración SQL** versionada en repo (`migrate_v1.3_F3.sql`): ADD COLUMN `fecha_lanzamiento DATE`, backfill desde `fecha_lanzamiento_real` de la aprobación más reciente con fallback a `semana_emision`, 2 `DO` blocks safeguards, UNIQUE constraint `uq_orden_sku_fecha_linea`. Idempotente, transaccional. 5 órdenes existentes backfilled correctamente.
3. **`forecast/db_mrp.py`**: agregada columna `fecha_lanzamiento` al modelo `MrpOrden`. `numero_of_tentativo(sku, fecha_lanzamiento, linea)` nueva firma. `get_orden_by_key(sku, fecha_lanzamiento, linea)` nueva firma con `COALESCE(o.linea, '')` para manejar NULLs.
4. **`forecast/main.py`**: passing `fl = o.get("fecha_lanzamiento") or o.get("semana_emision")` y `linea_o = o.get("linea") or ""` al armar el `key` post-optimizer. Eliminados 5 endpoints duplicados + class AprobacionRequest.
5. **`forecast/ordenes.py`**: `OrdenAprobar` agregó campo `fecha_lanzamiento`. `aprobar_orden` con cascada de fallbacks `fl_str = (req.fecha_lanzamiento_real or req.fecha_lanzamiento or se)[:10]`. Upsert incluye `fecha_lanzamiento`.
6. **`forecast/mrp.py`**: para IMPORTACION → `linea="IMPORTACION"` (era None porque IMPORTACION no tiene línea preferida; None rompía la unicidad).
7. **`forecast/optimizer.py`**: para IMPORTACION, `fecha_lanzamiento = semana_emision` directamente (no `_a_lunes_iso(semana_emision)` que colapsaba OFTs distintas del mismo SKU al mismo lunes).

### Fix aprobaciones frontend (consecuencia de F3)

8. **`dashboard/src/App.js`**:
   - `submitAprobacion` captura `oftAnterior = modalOrden.numero_of` antes del POST, y `setPlan` matchea por `o.numero_of === oftAnterior` (no por tupla). Match único garantizado por F3.
   - Constante `BACKEND_URL` derivada de `window.location` reemplaza `:3000` por `:8000`. `<a href={\`\${BACKEND_URL}/...\`}>`. Necesario porque el proxy de webpack dev-server actúa sobre XHR/fetch pero NO sobre navegaciones del browser (`<a target="_blank">`).
   - `plan.ordenes` se ordena por `fecha_lanzamiento` antes del `.map()`. `key={o.numero_of}` en lugar de `key={i}` para estabilidad post-sort.
   - POST de aprobar incluye `fecha_lanzamiento` en el body.
   - `<DetalleProduccion>` recibe `ordenesAprobadas` por prop. Antes tenía state local con su propio fetch que quedaba stale tras aprobar.

9. **`dashboard/src/components/DetalleProduccion.jsx`**: acepta `ordenesAprobadas` por prop, eliminados `useState/setAprobadas` + 2 fetchs a `/ordenes/aprobadas`. App.js es ahora single source of truth.

### Validación

Plan h=4 post-F3: 172 OFTs, 172 `numero_of` únicos, **0 colisiones** (antes 77). SKU 250010105 con 10 OFs únicas distribuidas en semanas distintas (antes 1 OF compartida).

Smoke test browser (4 tests, todos OK):
1. Orden cronológico de OFs (aprobadas intercaladas, no al final).
2. Badge "✓ Aprobada" + "✏️ Editar" inmediato en Detalle al aprobar.
3. Aprobación desde Plan → badge + link PDF inmediato. Click → descarga PDF.
4. Sin regresiones: editar OF aprobada preserva numero_of, regenerar plan mantiene aprobaciones.

---

## 2. Bloque B — V6.36 cache localStorage del plan (commit `8698262`)

### Problema

`useState(plan)` arrancaba en `null`. Un `useEffect` detectaba esa condición + tab activo y disparaba `runPlan()` automáticamente (~90s espera). En cada refresh del browser el usuario veía un spinner durante 90s antes de poder operar. Para las pruebas del 15/05 (cuando el equipo de planta va a refrescar repetidamente para ver actualizaciones) esto sería una fuente constante de fricción.

### Solución

- `useState(plan)` inicializa leyendo `localStorage.getItem('traverso:lastPlan')`.
- `runPlan()` después de `setPlan(data)` cachea via `localStorage.setItem` + timestamp ISO.
- `useEffect` del auto-trigger eliminado completamente (≈12 líneas).
- Helper `formatTimestampRelativo("hace X min/h/dias")`.
- `<span>` al lado del botón "Generar plan" mostrando "Plan generado hace X min" en cursiva. Color condicional:
  - Gris (default).
  - Ámbar si > 24h.
  - Rojo si > 7 días.

El usuario decide explícitamente cuándo regenerar. Plan persiste entre refreshes vía localStorage (~50-500KB por plan, muy debajo del límite ~5-10MB del browser).

### Validación

- F5 muestra plan inmediato sin esperar.
- DevTools → Application → Local Storage muestra `traverso:lastPlan` (JSON) y `traverso:lastPlanTimestamp` (ISO).
- Timestamp visible al lado del botón funciona y se actualiza tras regeneración.

---

## 3. Bloque C — Programación Diaria (commit `8698262`)

### Motivación

El equipo de planta necesita una "guía del día" imprimible: lista de OFs aprobadas para una fecha específica, agrupadas por línea de producción, con cajas/unidades/responsable/comentarios. Hasta hoy debían imprimir PDF de cada OF individualmente o consultar la pestaña Detalle Producción en pantalla.

### Decisiones de diseño

| Decisión | Razón |
|---|---|
| **Lectura A** (solo OFs aprobadas, no tentativas) | El propósito es guiar planta, lo tentativo se ve en Plan/Detalle. |
| **`window.print()` en lugar de backend reportlab** | Cero dependencias nuevas, cero migración. Aprovecha el "Guardar como PDF" del browser. Patrón reusable. |
| **Filtra por `fecha_lanzamiento_real`** | Fecha del momento de aprobación (la que el usuario eligió, con su edición si la cambió). |
| **Filtro multi-select de líneas** | Imprimir solo Sachetera, o solo L1Pet LV, según necesidad de planta. |
| **`tableLayout: fixed` + `colgroup` con `%`** | Anchos fijos por columna. Comentarios largos no rompen layout. Numéricas con `whiteSpace: nowrap`. |
| **`wordBreak: break-word` en Comentarios** | Texto largo sin espacios (URLs, códigos) se corta legible en lugar de overflow horizontal. |
| **CSS impresión con `className="no-print"`** | En lugar de selectores frágiles tipo `#root > div > div:first-child`, marca explícita en topbar + nav. |
| **Nombre dinámico del PDF** | `document.title = "Plan de Produccion YYYY-MM-DD"` antes de `window.print()`, restaurado con `afterprint` listener. Sin tilde por compatibilidad Windows. |

### Componentes y archivos

- `dashboard/src/components/ProgramacionDiaria.jsx` (~250 líneas, nuevo).
- `dashboard/src/App.js`:
  - Import del componente.
  - Tab `['programacion', '📅 Programación Diaria']` agregado al array de la navbar.
  - Render condicional con prop `ordenesAprobadas`.
  - `className="no-print"` en topbar (línea ~411) y div de tabs (línea ~422).

### Validación

PDF generado con 6 OFs distribuidas en 4 líneas, layout limpio, totales por línea correctos, sin navbar/topbar/controles en versión impresa. Validado con comentarios largos: wrap multi-línea en columna Comentarios sin afectar alineación numérica.

---

## 4. Hallazgo lateral confirmado por F3

En el PDF de Programación Diaria del 12/05 (test final del día) se observa:

```
Linea: Doypack
  OF-2026-00004  210030255  AJI CREMA TOTTUS 24x250 DOYPACK    225 cj
  OF-2026-00010  260030255  MOSTAZA TOTTUS 24x250 DOYPACK      225 cj
```

Dos OFs distintas, mismo día, misma línea, distintos SKUs. **Pre-F3 esto era imposible**: la clave `(sku, semana_emision, semana_necesidad)` colisionaba para SKUs del mismo grupo formato/marca/semana. Ahora son OFs independientes con números, comentarios, y cantidades propias.

Validación operativa de F3 en producción.

---

## 5. Decisiones tomadas hoy

| ID | Decisión |
|---|---|
| D1 | F3 anticipado (era post-piloto). Bloqueante para pruebas del 15/05. |
| D2 | Match frontend por `numero_of`, no por tupla. F3 lo hace único. |
| D3 | `linea="IMPORTACION"` (string explícito) en lugar de None para satisfacer UNIQUE constraint. |
| D4 | `fecha_lanzamiento = semana_emision` para IMPORTACION (no lunes ISO que colapsaba). |
| D5 | `DetalleProduccion` recibe `ordenesAprobadas` por prop. App.js single source of truth. |
| D6 | Constante `BACKEND_URL` derivada de `window.location` para `<a href>` (proxy no funciona en navegaciones). |
| D7 | Cache localStorage del plan. Auto-trigger eliminado. Usuario controla cuándo regenerar. |
| D8 | Timestamp visible con color condicional (gris/ámbar/rojo) según antigüedad. |
| D9 | Programación Diaria solo con OFs aprobadas (no tentativas). |
| D10 | `window.print()` para PDF, no backend reportlab. Patrón reusable. |
| D11 | Filtrar Programación Diaria por `fecha_lanzamiento_real`. |
| D12 | Anchos fijos en tabla impresa con `tableLayout: fixed` + `colgroup`. |
| D13 | Commits separados (no monolítico): F3+aprobaciones en uno, Programación Diaria+V6.36 en otro. Atomicidad lógica. |

---

## 6. Deudas técnicas — estado consolidado

### Cerradas hoy

| ID | Descripción |
|---|---|
| V6.32 | PK de `mrp_ordenes` era `(sku, semana_emision, semana_necesidad)`; cerrado por F3 a `(sku, fecha_lanzamiento, linea)`. |
| V6.36 | Auto-trigger del plan en refresh; cerrado con localStorage + timestamp visible. |
| P21 | DetalleProduccion regex Stock:N (cerrado con la prop fix del 12/05 mañana). |
| P22 | cobDias derivado de Stock:N (cae con P21). |

### Nuevas registradas hoy

| ID | Descripción | Prioridad |
|---|---|---|
| V6.34 | Declarar `UniqueConstraint` en `MrpOrden` ORM (hoy solo en BD via migración SQL). Bloqueante solo si se rebuildea BD desde cero con `Base.metadata.create_all`. | Post-vacaciones, baja. |
| V6.35 | Editar `fecha_lanzamiento_real` post-aprobación genera nuevo OF en lugar de actualizar versión. No bloqueante para piloto. | Post-vacaciones, baja. |

### Pre-existentes (sin cambios)

V6.11 (observabilidad SKUs sin forecast), V6.12-completa, V6.14 v1+v2 (cerradas), V6.17 (SS sobredimensionado), V6.19, V6.20, V6.21, V6.23, V6.24 (fragmentación optimizador, requiere F2), V6.25, V6.28, V6.29, V6.30, V6.X bandas Prophet — todas post-vacaciones.

---

## 7. Estado git al cierre

```
8698262 (HEAD -> feature/v1.3-cascada, origin/feature/v1.3-cascada)
        feat(dashboard): Programacion Diaria + cache localStorage del plan (V6.36)
5332405 fix(aprobaciones)+F3: clave (sku, fecha_lanzamiento, linea) para OFTs/OFs
6f4c561 docs: snapshot tecnico cierre Bloque B1 - 11/05/2026 (real)
345d3cd feat(B1): proyeccion_por_sku — backend única fuente de verdad
```

Working tree clean post-snapshot.

---

## 8. Pendientes pre-vacaciones (martes 13/05 y miércoles 14/05)

### Martes 13/05 — Manual del usuario

Manual con screenshots para el equipo de planta. Lenguaje neutro chileno. Las pestañas a documentar:
1. Forecast de Demanda (visión rápida).
2. Plan de Producción (incluyendo aprobación de OFs, edición, link PDF).
3. Stock por SKU (proyección).
4. Detalle Producción (vista grid).
5. **Programación Diaria** (nueva — guía del día imprimible). ⭐

Estimación: 3-4h.

### Miércoles 14/05 — PDF v8 + comunicación

1. **PDF v8 para Gerencia** (~1h):
   - Cierre F3 + fix aprobaciones (bug estructural detectado y resuelto).
   - Programación Diaria como entregable para planta.
   - Cache localStorage como mejora UX.
   - Roadmap post-vacaciones: F2 sequencer (V6.24), SS calibration con Gerente (V6.17), etc.

2. **Comunicación al equipo** (~30 min):
   - Instrucciones de arranque del 15/05.
   - URL del sistema: `http://180.1.1.18:3000`.
   - Tag estable: `git checkout v1.2-piloto` si algo se rompe.
   - Cómo reportar bugs/sugerencias (deuda pendiente: botón flotante de feedback).

### Jueves 15/05

Día de partida. Buffer. Ideal: nada planificado.

---

## 9. Tag de retorno seguro

Para volver al tag estable `v1.2-piloto`:
```bash
git checkout v1.2-piloto
docker compose down && docker compose up -d --build
```

Para volver al cierre del 12/05 tarde:
```bash
git checkout 8698262
```

Backup BD pre-F3: `/home/ubuntu/backups/mrp_db_pre_F3_20260512_122026.sql` (154 KB).

---

## 10. Próximo chat — primera invocación recomendada

> Lee `CLAUDE.md`, `docs/ESTADO_TECNICO_PROYECTO_11-05-26-cierre-B1.md` y `docs/ESTADO_TECNICO_PROYECTO_12-05-26-tarde.md`. Resúmeme el estado actual y arranquemos por el manual del usuario para las pruebas del 15/05. La pestaña nueva "Programación Diaria" es entregable principal a documentar.

---

## 11. Hallazgo crítico al cierre — V6.37 (PRIORIDAD ALTA mañana)

**Detectado al revisar el dashboard tras commit + push del cierre.**

### Síntoma

El optimizador genera OFTs nuevas que **ignoran la capacidad ocupada por OFs ya aprobadas en esa línea/día**. Dos restricciones violadas simultáneamente:

1. **Capacidad diaria**: el indicador del Detalle Producción muestra valores >100% de uso ("400%", "144%", "102%") en días donde hay OFs aprobadas + OFTs sugeridas. El sistema **sabe que está saturado** (lo dice en el indicador) pero el optimizador no lo evita al generar el plan.

2. **N_max=4 SKUs/día/línea**: violada cuando se cuentan los SKUs aprobados + tentativos del mismo día/línea. Caso visto: L1Pet LV martes 12/05 con 3 OFs aprobadas + 5 OFTs sugeridas = 8 SKUs en un día (debería ser ≤4).

### Evidencia visual (capturas del 12/05 al cierre)

**Doypack — martes 12/05** (cap diaria 5.400 u):
- 3 OFs aprobadas (`OF-2026-00004`, `00010`, `00012`) = 16.200 u (ya satura ~300%).
- 1 OFT sugerida adicional (`OFT-2026-94645`) = 5.400 u, marcada "Urgente" con fecha_lanzamiento = 2026-05-12.
- Indicador: **"400% / 0% libre"** + "17% setup".
- Total real del día: 21.600 u, 400% de la cap.

**L1Pet LV — martes 12/05** (cap diaria 110.000 u):
- 3 OFs aprobadas (`OF-2026-00013`, `00011`, `00002`) = 22.390 u.
- 5 OFTs sugeridas (`85883`, `77778`, `52475`, `73212`, otra) = ~82.000 u, todas "Urgente" con fecha_lanzamiento = 2026-05-12.
- Indicador: **"102% / 0% libre"** + "17% setup".
- 8 SKUs distintos en un solo día/línea (viola N_max=4).

### Hipótesis del bug (orden de probabilidad)

1. **Hipótesis 1 (más probable)**: en `forecast/optimizer.py`, el modelo CP-SAT recibe `cap_dia[linea]` directo de BD. **No descuenta** la cap ocupada por OFs ya aprobadas en esa línea/día.

2. **Hipótesis 2**: la restricción `Σ_k asig[d,k,l] ≤ N_max` solo cuenta variables `asig[d,k,l]` del modelo (OFTs tentativas en decisión). No cuenta SKUs ya aprobados como "fijos" en ese día.

3. **Hipótesis 3 (peor caso)**: las OFs aprobadas se inyectan en el plan **después** del optimizador (post-procesamiento en `main.py`), no se pasan como input. Si esto es así, el fix es arquitectónico más grande.

Las 3 hipótesis describen la misma falla con distinto alcance del fix. Hay que leer:
- `forecast/optimizer.py` — sección "entradas aprobadas" y cómo se construye el modelo.
- `forecast/main.py` — cómo se merge el plan tentativo con OFs aprobadas antes de devolver.
- `docs/v1.3_DISENO_ARQUITECTURA.md` §3 R3 ("OFs aprobadas en N2 respetan SKU + cantidad. El N2 sí puede mover su posición intra-día si reduce setups"). El doc dice qué debería pasar; hay que verificar si el código lo implementa.

### Severidad

**Alta para validar antes del 15/05**, pero **no completamente bloqueante**:
- El equipo va a ver indicadores en rojo (400%) — pérdida de confianza en el sistema.
- El planificador es el filtro humano: rechazaría manualmente lo imposible. Pero esa carga es exactamente lo que el optimizador debería evitar.
- Si las pruebas arrancan con este bug, hay riesgo de que el equipo dude del optimizador entero.

### Plan para mañana primera hora

1. **Diagnóstico (1h)**:
   - Leer `optimizer.py` secciones de capacidad y `asig`.
   - Leer `main.py` post-optimizer (merge con aprobadas).
   - Determinar cuál de las 3 hipótesis aplica.
2. **Decisión arquitectónica**: dónde descontar — en el modelo CP-SAT (cap_dia ajustada) o en pre-procesamiento (filtrar SKUs sin espacio).
3. **Implementación (1-2h)**: el descuento en N1 es el primer paso. Validar también N_max con SKUs aprobados sumados.
4. **Validación (1h)**: smoke tests con OFs aprobadas en varios días/líneas, h=4 y h=13.
5. **Commit + push**.

**Estimación total**: 3-4h. **Decisión operativa**: V6.37 ANTES del manual del usuario mañana. Sin el fix, el manual sería confuso (¿cómo se explica al equipo que el sistema sugiere lo imposible?).

### Re-plan pre-vacaciones

- **Martes 13/05**: V6.37 (3-4h) → Manual del usuario (3-4h). Día completo, 6-8h.
- **Miércoles 14/05**: PDF v8 (1h) + comunicación al equipo (30 min). Más holgado.
- **Jueves 15/05**: Partida vacaciones.

### Comando recomendado para arrancar mañana

```bash
cd /home/ubuntu/traverso-forecast
git status
git log --oneline -5
docker compose ps
```

Y arrancar chat web con:
> Lee `CLAUDE.md`, `docs/ESTADO_TECNICO_PROYECTO_11-05-26-cierre-B1.md` y `docs/ESTADO_TECNICO_PROYECTO_12-05-26-tarde.md` con énfasis en §11 (V6.37 descubierto al cierre). Arranquemos por diagnosticar el bug del optimizador antes del manual.

---

*Cerrado al fin de la sesión chat web del 12/05/2026 tarde. F3 + Programación Diaria + V6.36 en producción. **V6.37 descubierto al cierre, prioridad #1 mañana antes del manual.** Próxima sesión: diagnóstico + fix V6.37, después manual del usuario.*
