# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Bloque B1 cerrado — 11/05/2026 (real)

> **Nota sobre fechas**: este snapshot inaugura la convención de **fechas reales** (no calendario nominal del proyecto). Snapshots previos (`12-05-26.md`, `13-05-26.md`, `HOY.md`) usaban fechas del calendario nominal que corre adelantado respecto al real. Para reconstruir la cronología real:
> - `12-05-26.md` ≈ 10/05/2026 real.
> - `13-05-26.md` = 10/05/2026 real.
> - `HOY.md` = 11/05/2026 real (snapshot intermedio del medio día).
> - `11-05-26-cierre-B1.md` (este archivo) = 11/05/2026 real (cierre del día).
>
> Snapshots futuros usan fechas reales con sufijo descriptivo si hay más de uno por día.

---

## Resumen ejecutivo del día

Día dedicado íntegramente al **Bloque B1 del refactor V6.27**: backend como única fuente de verdad para la proyección de stock semanal. Cierre exitoso de 5 deudas técnicas (V6.14 v2, V6.26, V6.27, P21, P22). Validación visual del usuario confirma que el "rojo masivo" del dashboard (síntoma original del 13/05 nominal) está resuelto.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Commit pusheado | `345d3cd` (Bloque B1 backend+frontend) |
| Commits totales del día | 2 (`ebb8537` proyeccion.py + `345d3cd` integración) |
| Archivos tocados | 3 (`forecast/main.py`, `StockProyeccion.jsx`, `DetalleProduccion.jsx`) |
| Líneas netas | -115 (95 ins / 210 del) |
| Smoke tests backend | T1 ✓, T3 ✓, T4 ✓; T2 y T5 documentados |
| Validación visual usuario | ✓ h=4 sin quiebres falsos, h=13 con pocos reales |
| Deudas cerradas | 5 (V6.14 v2, V6.26, V6.27, P21, P22) |
| Deudas nuevas registradas | 1 (V6.30 — Cobertura "—" en primeras OFTs) |

---

## 1. Lo que se hizo

### 1.1 Decisión arquitectónica

Diagnóstico del 11/05 mañana confirmó que el "rojo masivo" del dashboard reportado el 13/05 NO era bug del optimizador (72/74 SKUs atendidos correctamente, gap real 162 cj). La causa fueron **cálculos paralelos en el frontend** que arrastraban V6.14 v1 incompleto + V6.26.

**Decisión D1+D2+D3**: el backend emite un campo nuevo `proyeccion_por_sku` con la proyección semanal completa (stock/entradas/ventas/SS/estado por semana viz dom-sáb). El frontend solo renderiza, sin recalculos.

### 1.2 Implementación backend

- `forecast/proyeccion.py`: módulo con `construir_proyeccion_por_sku()`, helper polimórfico `_get_sku_attr()`, smoke test interno con 6 SKUs mock.
- `forecast/main.py`: import top-level + llamada al final del `/plan` + campo `proyeccion_por_sku` en response.
- Smoke tests post-integración: HTTP 200 / 88s / 76 SKUs / 130 OFTs / FEASIBLE.

### 1.3 Implementación frontend

- `StockProyeccion.jsx` refactor: -135 líneas netas (631→496). Eliminados: `calcularProyeccion()`, 5 useState huérfanos, helper `getSemanaActual`, banner amarillo V6.26, banner de error, useMemo `aprobSku`, 2 fetches a `/ordenes/aprobadas`.
- `DetalleProduccion.jsx` fix P21: regex Stock:N → `o.stock_inicial_cajas`.
- Dropdown horizonte deshabilitado + leyenda "(del plan)".

### 1.4 Validación visual del usuario

Confirmada en `http://180.1.1.18:3000`:
- ✓ h=4 sin quiebres falsos.
- ✓ h=13 con pocos quiebres reales.
- ✓ DetalleProduccion con stock inicial correcto para OFTs del optimizer.
- ✓ Banner amarillo desaparecido.
- ✓ Sin errores en consola del navegador.

**Observación lateral**: stock proyectado por encima del SS. Hipótesis: V6.17 (SS=15d uniforme L1Pet LV sobredimensionado). Tema para Gerente al regreso.

### 1.5 Migración del entorno de Code (PC → Server)

- Instalación de nvm + Node 22.22.2 + Claude Code 2.1.138 en `/home/ubuntu/.nvm/...`.
- Autenticación OAuth (vía incógnito por redirect inicial).
- Acceso nativo a Docker, parquet, BD desde Code.
- Memoria interna en `~/.claude/projects/-home-ubuntu-traverso-forecast/memory/`.

---

## 2. Decisiones tomadas

| ID | Decisión |
|---|---|
| D1 | Schema `proyeccion_por_sku` con `stock_fin_cj_visible` (≥0, curva azul) y `stock_fin_cj_real` (puede ser <0, KPIs+estado). |
| D2 | Semana = domingo a sábado (semana viz). |
| D3 | Incluir TODOS los SKUs activos con flag `cobertura` ∈ {proyeccion_completa, solo_stock, sin_proyeccion}. |
| D4 | Backend única fuente de verdad. Frontend solo renderiza. |
| D5 | Bandas Prophet aproximadas (±20%) hasta que backend exponga las reales. |
| D6 | Import top-level de `proyeccion` en `main.py`. |
| D7 | `req.skus` filtra `proyeccion_por_sku`. |
| D8 | Dropdown horizonte deshabilitado + leyenda "(del plan)". |
| D9 | `ordenesAprobadas` huérfano eliminado (verificado con grep). |
| D10 | Commit B1 backend+frontend juntos (unidad lógica). |
| D11 | Claude Code instalado en servidor (flujo definitivo). |
| D12 | Convención de fechas: snapshots futuros usan fechas reales con sufijo descriptivo. |

---

## 3. Deudas técnicas — estado consolidado

### Cerradas hoy

| ID | Descripción |
|---|---|
| V6.14 v2 | Dashboard mostraba Stock=0 para SKUs sin OFT |
| V6.26 | Curva azul ignoraba OFTs sugeridas con lanzamiento ≤ hoy |
| V6.27 | Auditoría completa cálculos paralelos backend↔frontend |
| P21 | DetalleProduccion regex Stock:N |
| P22 | cobDias derivado de Stock:N (cae con P21) |

### Nueva registrada hoy

| ID | Descripción | Prioridad |
|---|---|---|
| V6.30 | Cobertura "—" para primeras OFTs (forecast_cajas=0 en esas OFTs) | Post-vacaciones, baja |

### Pre-existentes (sin cambios)

V6.11, V6.12-completa, V6.17, V6.19, V6.20, V6.21, V6.23, V6.24, V6.25, V6.28, V6.29, V6.X bandas Prophet — todas post-vacaciones.

---

## 4. Pendientes pre-vacaciones

| Día (nominal) | Tarea | Estimación |
|---|---|---|
| Martes 12/05 | Manual del usuario con screenshots | 3-4 h |
| Miércoles 13/05 | PDF v8 para Gerencia | 1 h |
| Miércoles 13/05 | Comunicación al equipo arranque 15/05 | 30 min |

Mensajes principales del PDF v8: Bloque B1 cerrado, hallazgo SS=15d L1Pet LV (V6.17), hallazgo Doypack ~95% capacidad, roadmap post-vacaciones (F2 sequencer V6.24).

---

## 5. Estado git al cierre

```
345d3cd feat(B1): proyeccion_por_sku — backend única fuente de verdad
ebb8537 feat(proyeccion): B1 paso 1 - modulo proyeccion.py + docs schema y auditoria
b1f05ab docs: anotar urgencia pendiente para mañana — investigar quiebres dashboard
390b09c docs: snapshot técnico cierre 13/05/2026 (nominal)
82cef34 feat(optimizer): V6.12-mini — filtrar SKUs con stock>cap_bodega
```

---

## 6. Tag de retorno seguro

Para volver al tag estable `v1.2-piloto`:
```bash
git checkout v1.2-piloto
docker compose down && docker compose up -d --build
```

Para volver al estado al cierre del 11/05 real (cierre Bloque B1):
```bash
git checkout 345d3cd
```

---

## 7. Próximo chat — primera invocación recomendada

> Lee `CLAUDE.md`, `docs/ESTADO_TECNICO_PROYECTO_11-05-26-cierre-B1.md` y los snapshots previos relevantes. Resúmeme el estado actual y arranquemos por el manual del usuario.

---

*Cerrado al fin de la sesión del 11/05/2026 real. Bloque B1 cerrado. Próxima sesión: manual del usuario.*
