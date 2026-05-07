# Mensaje inicial para Claude Code — próxima sesión

> **Cómo usar este archivo**: cuando arranques `claude` en la raíz del repo en la próxima sesión, copiá y pegá el bloque de abajo como tu primer mensaje a Claude Code.

---

## Mensaje único (post-decisión Gerente confirmada)

```
Lee `CLAUDE.md`, `docs/v1.3_DISENO_ARQUITECTURA.md`, y `docs/ESTADO_TECNICO_PROYECTO_05-05-26.md`. Adicionalmente, lee `docs/cierre_sesion_05-05-26/R12_PRIMER_SETUP_GRATIS.md` que documenta la regla nueva en detalle.

Confírmame qué entendés del estado actual y de las decisiones del Gerente (D1, D2, D3=R12).

Resumen de lo que tenés que implementar — Bloque V5:

D1 (mantenida): batch_min_u = 9500 para Mostaza/Ketchup. Sin cambios en BD. NO TOCAR.
D2 (cambio): factor_velocidad de 0.8 a 1.0 para Mostaza/Ketchup en Sachetera.
D3 (cambio de modelo): R12 — primer SKU del día NO paga setup en TODAS las líneas.

Plan de trabajo con commits separados:

**Paso 1 — Verificación previa**
- `git status` y `git log --oneline -7`. Confirmá que estamos en `feature/v1.3-cascada` con los 5 commits del bloque V4.
- BD en estado original:
  ```sql
  SELECT sku, batch_min_u FROM mrp_sku_params WHERE sku IN ('250010105', '260010105');
  -- Esperado: ambos 9500
  
  SELECT sku, linea, factor_velocidad FROM mrp_sku_lineas WHERE sku IN ('250010105', '260010105') AND linea = 'Sachetera';
  -- Esperado: ambos 0.8
  ```
- Confirmá que el backend responde 200 en `GET /plan/params`.

**Paso 2 — Aplicar D2 (factor_velocidad)**
- Snapshot de la BD (SELECT antes).
- UPDATE: factor_velocidad = 1.0 para Mostaza (260010105) y Ketchup (250010105) en línea Sachetera.
- Verificación con SELECT.
- Actualizar `forecast/data/Traverso_Parametros_MRP.xlsx` (pestaña SKU_LINEA): cambiar Factor_Linea de 0.8 a 1.0 para esas dos filas. Recordatorio: el Excel está gitignored, pero hay que mantenerlo coherente con BD para próximos `migrate_params.py`.
- Commit: `chore(params): factor_velocidad 1.0 para Mostaza/Ketchup en Sachetera (D2 Gerente, resuelve O2 y parte de O10)`

**Paso 3 — Implementar D3 (R12) en `optimizer.py`**
- Sigue el detalle técnico del documento `R12_PRIMER_SETUP_GRATIS.md` paso a paso.
- Resumen del cambio: 
  (a) Reemplazar la detección actual de `inicio[d,k,l]` (que es por SKU con `inicio >= asig - asig_prev`) por una restricción agregada por (día, línea): `Σ_k inicio[d,k,l] >= Σ_k asig[d,k,l] - 1`.
  (b) Mantener `inicio[d,k,l] <= asig[d,k,l]` para cada (d,k,l) por integridad.
  (c) **Importante**: agregar `W_INICIO_SIMBOLICO = 1` al objetivo, sumando todos los `inicio[d,k,l]`. Sin esto, el solver puede dejar "inicios fantasma" en (d,l) con cap holgada y los tests del Paso 5 fallan intermitentemente. Detalle en R12_PRIMER_SETUP_GRATIS.md §"Implementación / Paso 3".
  (d) Eliminar el caso especial de día 0 (queda subsumido por R12).
- ¡IMPORTANTE! Después del cambio: `docker exec traverso_forecast rm -rf /app/__pycache__` y `docker compose restart forecast`.
- Commit: `feat(optimizer): R12 — primer SKU del día sin setup (D3 Gerente)`

**Paso 4 — Validación post-fix**
- Regenerar `/plan` con horizonte 13 (usar el body.json existente).
- Extraer métricas: `python tests/fixtures/extract_metrics.py tests/fixtures/v1.3_post_r12_metrics.json | tee tests/fixtures/v1.3_post_r12_metrics.txt`
- Comparar contra Test B' (tests/fixtures/v1.3_post_v4_test_b.json):
  - Sachetera uso% — esperado 50-80% (margen cero por O12).
  - quiebre — esperado 0.
  - **ofts_con_paga_setup — esperado entre 20 y 60** (vs 130 en Test B'). Esta es la métrica crítica de R12.
    - Si <20 (o 0): posible fragmentación extrema (días con 1 SKU). NO es éxito — inspeccionar Detalle Producción visualmente. Si se ve 1 SKU/línea/día durante todo el horizonte, R12 está liberando demasiado y el solver se aprovecha. Documentar y consultar antes de avanzar.
    - Si >80: R12 mal implementada o `W_INICIO_SIMBOLICO` no aplicado. Re-revisar Paso 3.
  - objective_value — esperado <300 mil M (vs 521 mil M en Test B').
- Si las métricas están en rango: continuar. Si no: diagnóstico antes de avanzar.

**Paso 5 — Tests específicos de R12**
Correr los 3 tests del documento `R12_PRIMER_SETUP_GRATIS.md` sección "Tests específicos para validar R12":
1. Por cada (línea, fecha): N_ofts_con_setup == N_skus_distintos - 1.
2. Total de setups baja sustancialmente vs Test B'.
3. Días con 1 solo SKU NUNCA tienen setup.

Si los 3 pasan: R12 está bien implementada. Sino: diagnóstico antes de seguir. Recordá que el Test 1 puede fallar específicamente si `W_INICIO_SIMBOLICO` no fue agregado al objetivo en el Paso 3 (inicios fantasma).

**Paso 6 — Validación visual**
- Refrescar dashboard en `http://localhost:3000`.
- Pestañas: Forecast, Plan, Stock, Detalle.
- Verificar que Sachetera produce (no está vacía).
- Sin errores 500 en consola del navegador.
- Sin alertas de validación obvia.

**Paso 7 — Commit 4 condicional (deuda técnica V4: hardcoding de líneas en frontend)**
Este paso NO está relacionado con R12 ni con D2. Es un pendiente del bloque V4 (recodificación de líneas con nombres descriptivos: Sachetera, L1Pet LV, L1Pet A) que conviene cerrar acá si aparece regresión visual.

- Si en el Paso 6 viste algo raro en Detalle Producción (líneas no aparecen, badges mal coloreados, etc.) → buscar referencias hardcodeadas:
  - `grep -rn "L001\|L002\|S001\|S002" dashboard/src/`
  - Si aparece: arreglar referencias y commit `fix(frontend): actualizar referencias hardcodeadas a códigos de línea (deuda V4)`.
- Si el dashboard funciona limpio en el Paso 6: **skip**, no buscar problemas que no existen. La deuda queda para cuando se manifieste.

**Paso 8 — Commit 5 condicional (fix_stock.py)**
- `git show 3242bce -- forecast/fix_stock.py | head -50`
- Evaluar si es script de v1.1 obsoleto. Si sí: `git rm forecast/fix_stock.py` + commit `chore(repo): eliminar fix_stock.py — script auxiliar obsoleto de v1.1 (resuelve O5)`.
- Si tiene utilidad actual: skip.

**Paso 9 — Documentación**
- Actualizar `CLAUDE.md` agregando R12 en "Reglas de negocio activas" + nota sobre supuesto operativo (limpieza extra-jornada).
- Actualizar `docs/v1.3_DISENO_ARQUITECTURA.md` §3 con R12, §4.1 con descripción del modelo nuevo.
- Crear `docs/ESTADO_TECNICO_PROYECTO_<fecha>.md` cerrando bloque V4 + V5. Estructura igual a `ESTADO_TECNICO_PROYECTO_05-05-26.md`.
- Commit: `docs: estado técnico cierre bloques V4+V5 + reglas R12`.

**Paso 10 — Push**
- `git log --oneline -10` para ver el linaje completo.
- `git push origin feature/v1.3-cascada`.
- Output esperado: confirmación de push, nueva rama remota.
- Generar URL para PR (si querés): `https://github.com/germanlaso/traverso-forecast/pull/new/feature/v1.3-cascada` — NO crear la PR todavía (esperar a F2+F3+F6 para mergear todo junto a main).

Empezá con el Paso 1. Mostrame outputs y vamos paso a paso. Si algo se rompe inesperadamente, no improvises — paramos y diagnosticamos.
```

---

## Tip operativo previo a la sesión

**Antes de pegar el mensaje a Claude Code**, verificá que el contenedor está sano:

```powershell
docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 --break-system-packages -q
docker exec traverso_forecast pip install ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast

# Verificá que el backend responde:
curl.exe -s http://localhost:8000/plan/params -o NUL -w "%{http_code}"
# Esperás: 200
```

Si responde 200, Claude Code puede arrancar limpio. Si no, primero `docker logs traverso_forecast --tail 30` y diagnosticar.

---

## Si surgen complicaciones imprevistas en el Paso 4 (métricas raras)

Estos son los escenarios menos probables pero conviene tenerlos identificados:

**Escenario A — `ofts_con_paga_setup` baja muy poco (<30% reducción, p.ej. 90-130)**
→ R12 mal implementada. Re-revisar el cambio en `optimizer.py`. La restricción agregada debería estar matando muchas variables `inicio`.

**Escenario A' — `ofts_con_paga_setup` baja TODA (a 0 o cerca)**
→ Fragmentación extrema: el solver eligió poner cada SKU en un día solo para evitar siempre el setup. NO es éxito. Inspeccionar Detalle Producción: si se ve 1 SKU por línea por día, está fragmentado.
→ Mitigación: NO subir `W_INICIO_SIMBOLICO` (eso introduce sesgo de consolidación que es trabajo de F2). Tampoco reintroducir W_SETUP=200. Documentar y consultar — probablemente conviene esperar a F2 con matriz real.

**Escenario B — Sachetera sigue al 0%**
→ Algo más además de O10. Posibles culpables: matriz de setups con valores absurdos, ss_dias muy alto que el solver no logra cubrir aún con cap completa, batch_mult incompatible con cap_día.
→ Hacer un nuevo "Corte 0 sanity check" expandido.

**Escenario C — Quiebres > 0**
→ Posible: alguna semana con cambio frecuente de SKU + batch_min restrictivo + R12 no alcanzando para liberar capacidad.
→ Documentar como observación nueva (no necesariamente bug). Volver al Gerente con el caso concreto.

**Escenario D — Solver INFEASIBLE**
→ Algo está rompiendo la factibilidad del modelo. Probablemente la implementación de R12 introdujo una contradicción.
→ Revertir el cambio de R12 y diagnosticar.
→ Como fallback: aplicar D2 sin R12 primero. Eso ya debería desbloquear Sachetera marginalmente (cap=9500=batch_min sin setup).

**Escenario E — Test 1 falla intermitentemente (algunas (linea, día) con N_setup ≠ N_skus - 1)**
→ Casi seguro: `W_INICIO_SIMBOLICO` no fue agregado al objetivo en el Paso 3. Verificar el bloque `obj_terms.append(W_INICIO_SIMBOLICO * m.inicio[(d, k, l)])`. Si está ausente, agregarlo y reejecutar.

En cualquiera de los escenarios, **NO hacer push hasta resolverlo**. Mantener el patrón de no comprometer estado roto.
