# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.3-V5 (en desarrollo) — Actualizado: 07/05/2026

---

## Estado al cierre de sesión 06-07/05/2026

Bloque V5 del plan v1.3 con dos commits hechos en `feature/v1.3-cascada`. Falta Paso 9 (docs) y Paso 10 (push). Resto del backend funcional con BD post-D3 + optimizer post-R12.

---

## Cambios aplicados en bloque V5

### D2 — factor_velocidad para SKUs Sachetera (commit `4077039`, vacío)

`factor_velocidad = 1.0` (antes 0.8) para SKUs `260010105` (Mostaza) y `250010105` (Ketchup) en línea Sachetera.

- BD UPDATE aplicado.
- Excel `Traverso_Parametros_MRP_V4.xlsx` sincronizado a 1.0 antes del commit.
- Filosofía: BD es fuente de verdad, Excel es utilidad. Commit vacío con trazabilidad por mensaje.

### R12 — Primer SKU del día sin setup (commit `4db4c76`, real)

Modificación a `forecast/optimizer.py` reflejando regla operativa del Gerente: la línea se prepara antes de cada jornada (limpieza/montaje extra-jornada), entonces el primer SKU del día NO paga setup.

Cambios técnicos:
1. `W_INICIO_SIMBOLICO = 1` en sección de pesos. Peso simbólico, no penaliza fragmentación.
2. Detección de inicio reformulada: `inicio <= asig` (integridad) + `sum(inicios_dl) >= sum(asigs_dl) - 1` (al menos N-1 SKUs pagan setup).
3. Función objetivo actualizada con `W_INICIO_SIMBOLICO * inicio`.

Validación: 3 tests sobre plan h=13 pasaron. 41 OFTs con paga_setup vs 130 baseline pre-R12 (-68.5%, dentro rango esperado).

### D3 — lead_time = 1 día para 8 SKUs producción propia (commit `d866a77`, vacío)

Confirmación de regla operativa: lead time = tiempo desde fin de producción hasta producto disponible para venta = 1 día para fabricación propia.

- BD UPDATE: 8 SKUs PRODUCCION con `lead_time_sem = 0.15` (round(0.15×7)=1 día efectivo).
- IMPORTACION sin cambios (siguen en 12 sem).
- Reconciliación de Excel canonical: `forecast/data/Traverso_Parametros_MRP.xlsx` estaba en estado V3 con fórmulas VLOOKUP de cache vacío. Sobrescrito con copia de V4 que tiene literales 0.15.

Validación visual (dashboard Stock por SKU):
- Mostaza: cobertura inicial mejoró sustancialmente (stock_fin semana 2: 0 → 1.237). Producción 22.800 → 27.550 cj.
- Ketchup: solo 2 sem bajo SS leves. OK desde semana 3.
- Vinagre Manzana: 10 sem bajo SS leves (5% del SS, no quiebre).
- Vinagre Rosado: bajo nivel de servicio crónico — preexistente, NO regresión de D3. Candidato a revisar con Gerente en sesión futura.

---

## Workaround documentado (deuda V6)

**`lead_time_sem = 0.15` es valor cosmético**. Semánticamente la columna debería llamarse `lead_time_dias` y los valores ser enteros directos.

Refactor pendiente en V6:
- Renombrar columna en BD (`mrp_sku_params`).
- Renombrar en Excel canonical y migrate_params.py.
- Ajustar `mrp.py`, `optimizer.py`, `ordenes.py` para usar días directamente (eliminar el `× 7`).
- Frontend: "Lead time: X sem" → "X día(s)".
- Actualizar `CLAUDE.md` y `v1.3_DISENO_ARQUITECTURA.md`.

---

## Estado de los commits del bloque V5

```
9 commits ahead of origin/feature/v1.3-cascada

4db4c76 feat(optimizer): R12 — primer SKU del día sin setup
d866a77 chore(params): D3 aplicada — lead_time 1 día efectivo para 8 SKUs producción + reconciliación canonical
4077039 chore(params): D2 aplicada — factor_velocidad 1.0 para SKUs Sachetera
[5 commits previos del bloque F1+V4 ya documentados en ESTADO_TECNICO_PROYECTO_02-05-26.md]
```

**No pusheado todavía**. El push (Paso 10) queda para próxima sesión.

---

## Pendientes para próxima sesión

### Paso 9 — Documentación

1. **Actualizar `CLAUDE.md`** con:
   - R12 (regla operativa: primer SKU del día sin setup).
   - Supuesto operativo: limpieza/montaje extra-jornada hace que la línea esté lista al inicio del día.
   - Patrón observado de duplicación en display de Claude Code (O13 actualizado): es 100% display, no afecta runtime, mitigación = Read post-creación si aparece en preview.
   - Path mangling Git Bash con `docker exec`: usar doble slash inicial (`//app/...`, `//tmp/...`) o `bash -c '...'`.
   - Patrón "antes de Y, hacé X" debe tratarse como bloqueante hasta confirmación.
   - Métricas: `alertas BAJO_SS adjuntas a OFTs` NO es monotónica de calidad — puede subir cuando plan produce más reactivo. Dashboard visual sigue siendo último filtro.

2. **Actualizar `docs/v1.3_DISENO_ARQUITECTURA.md`**:
   - §3: agregar R12 a tabla de reglas.
   - §4.1: documentar nuevo modelo de N1 (W_INICIO_SIMBOLICO, restricción `sum(inicios) >= sum(asigs) - 1`).

3. **Crear `docs/ESTADO_TECNICO_PROYECTO_07-05-26.md`**: este documento.

### Paso 10 — Push

```powershell
git push origin feature/v1.3-cascada
```

### Pendientes operativos / decisiones

- **Vinagre Rosado bajo nivel de servicio**: revisar parámetros (forecast, SS_dias, batch_min, prioridades en L1Pet LV) con Gerente. NO bloqueante.
- **Excel `Traverso_Parametros_MRP_V4.xlsx` en raíz** (untracked): decidir si eliminar (canonical ya tiene mismo contenido), archivar a SharePoint, o dejar. Recomendación: eliminar tras archivar.
- **Scripts transitorios en `tests/fixtures/`**: `decompose_objective.py`, `test_r12.py`, `inspect_lead_time_excel.py`. Decidir si versionar o eliminar.
- **2 docs modificados en `docs/cierre_sesion_05-05-26/`**: revisar y commitear o descartar cambios.

---

## Estado git al cierre

```
On branch feature/v1.3-cascada
Your branch is ahead of 'origin/feature/v1.3-cascada' by 9 commits.

Changes not staged for commit:
  modified:   docs/cierre_sesion_05-05-26/<archivo1>
  modified:   docs/cierre_sesion_05-05-26/<archivo2>

Untracked files:
  Traverso_Parametros_MRP_V4.xlsx
  INICIO_SESION_04-05-26.md
  PLAN_CARGA_V4_Y_SETUP_MATRIX.md
  tests/fixtures/decompose_objective.py
  tests/fixtures/test_r12.py
  tests/fixtures/inspect_lead_time_excel.py
  tests/fixtures/v1.3_post_v4_metrics.txt
```

---

## Observaciones operativas acumuladas (para CLAUDE.md)

### O11 — Solver hits timeout 60s con FEASIBLE en h=13

No es regresión. Considerar timeout 120s en futuras corridas. VPN debe estar activa antes de cualquier `/plan` (SQL Server requerido).

### O12 — Sachetera margen cero por diseño

`cap_dia = 9500 = batch_min` para Mostaza/Ketchup. Decisión Gerente, no bug.

### O13 (actualizada en sesión 06/05) — Bug display Claude Code en archivos largos

Patrón: archivos creados con Write tool muestran líneas duplicadas en preview de aprobación, pero el archivo en disco está limpio. **8 apariciones en sesión, 7 falsas alarmas confirmadas con Read, 1 real (heredoc original al inicio).** Distribución cierra: bug es 100% display, no afecta runtime. Mitigación: si aparece duplicación en preview, hacer Read; archivo correcto.

### Aprendizajes operativos para CLAUDE.md

- **Verificar deps ANTES de reinstalar**: no reinstalar preventivamente, solo si imports fallan.
- **Path mangling Git Bash con `docker exec`**: doble slash inicial (`//app/...`, `//tmp/...`).
- **Heredoc en PowerShell falla**: usar archivo + `git commit -F archivo` con cleanup explícito.
- **VPN activa antes de `/plan`**: SQL Server requerido para refresh de stock.
- **"Antes de Y, hacé X" es bloqueante** hasta confirmación: Claude Code tiende a saltar X y hacer Y directamente.
- **Métricas agregadas pueden engañar**: `alertas BAJO_SS adjuntas a OFTs` puede SUBIR cuando el plan produce más reactivo. Validación visual del dashboard es el último filtro.
- **Scripts inline `python -c "..."` >40 líneas: pueden tener bug de display pero ejecución correcta**. Si hay duda, mover a archivo con Write incremental + Read antes de promover.

---

## Tag de retorno seguro

```powershell
git checkout v1.2-piloto
docker compose down
docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast
```

Para volver al cierre del bloque V5: `git checkout feature/v1.3-cascada`.

---

## Tags Git

- `v1.0` — MRP clásico + Forecast + Aprobaciones
- `v1.1-piloto` — OR-Tools semanal + sincronización + multi-líneas
- `v1.2-backend` — CP-SAT diario + factor_velocidad + cajas
- `v1.2-piloto` — Frontend completado + setup_unidades + match por numero_of (estable)
- `feature/v1.3-cascada` (branch, 9 commits ahead al cierre 07/05) — F1 + V4 + V5 (D2+R12+D3) implementados, falta docs y push
- `v1.3-piloto` (futuro) — cuando F1+F2+F3+F6 estén juntos y mergeados a `main`

---

## Contexto del negocio (sin cambios)

- **Empresa**: Traverso S.A. (alimentos chilenos)
- **Segmento piloto**: COMERCIAL — 10 SKUs prioritarios
- **Total SKUs**: 471 SKUs activos
- **Líneas**: L001 Líquidos 1, L002 Líquidos 2, S001 Salsas 1, S002 Salsas 2 (Sachetera = S001+S002 conceptualmente)
- **Stack**: FastAPI + Prophet + OR-Tools CP-SAT + React + PostgreSQL + SQL Server (Docker)

---

*Cerrado al fin de la sesión del 07/05/2026, antes de Paso 9 (docs) y Paso 10 (push). Próxima sesión arranca con docs + push.*
