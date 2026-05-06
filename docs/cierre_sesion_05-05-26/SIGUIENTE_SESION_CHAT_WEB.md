# Onboarding para próxima sesión — Chat web Claude

> **Pegáselo al Claude del nuevo chat al inicio de la próxima sesión.** Lleva todo el contexto post-conversación con Gerente.

---

## Estado al cierre del 05/05/2026 (post-decisión Gerente)

**Proyecto**: Traverso S.A. — Sistema de Planificación de Producción con IA.
**Rama activa**: `feature/v1.3-cascada` (5 commits locales, sin push).
**Última versión estable**: `v1.2-piloto` (tag, retorno seguro).
**Próximo objetivo**: `v1.3-piloto` (desbloqueado por decisiones del Gerente, listo para fix técnico).

---

## Linaje de commits del bloque V4 (sesión 05/05)

```
XXXXXXX docs: estado técnico 05-05-26 con diagnóstico de O10 (batch_min Sachetera) + decisiones Gerente
b47ae40 chore(params): cargar parámetros V4 y matriz de setups inicial simétrica
d0f36b9 feat(db): crear tabla mrp_setup_matrix con CRUD en db_mrp.py
a4bd815 chore(repo): ignorar archivos de backup SQL locales
7892b4d chore(db): limpiar OFs aprobadas previo a recodificación de líneas
bcd86d1 fix(stock): envolver fetch_and_save_stock en bloque with engine.connect()
```

---

## Decisiones del Gerente (post-conversación 05/05 tarde)

### Decisión 1 — `batch_min_u = 9500` se mantiene

El Gerente confirma que 9,500 unidades es el batch mínimo operativo real para Mostaza/Ketchup en Sachetera. **No se baja a 3000** como en el test diagnóstico.

**Implicación**: Sachetera quedará al 100% durante varios días seguidos cuando produzca Mostaza/Ketchup. Cero margen para imprevistos. Decisión deliberada del negocio.

→ Registra **O12 (NUEVA)**: "Sachetera con margen cero por diseño operativo. No es bug, es decisión del Gerente."

### Decisión 2 — `factor_velocidad = 1.0` para Mostaza/Ketchup en Sachetera

El Gerente confirma que la velocidad nominal 1055 u/hr **ya incluye** la merma del producto. El 0.8 cargado en V4 era doble-conteo (confirma la sospecha O2 abierta desde el domingo).

**Cambio en BD**:
```sql
UPDATE mrp_sku_lineas
SET factor_velocidad = 1.0
WHERE sku IN ('250010105', '260010105') AND linea = 'Sachetera';
```

→ Cierra **O2** definitivamente.

### Decisión 3 — REGLA R12: el primer SKU del día NO paga setup (NUEVA, en TODAS las líneas)

**Esta es la decisión más importante porque modifica el modelo, no solo parámetros.**

**Lógica del Gerente**: la limpieza/preparación de la línea para el primer SKU del día se hace al cierre del día anterior, después del cierre operativo. Es trabajo extra-jornada (turno de limpieza/mantenimiento) y NO consume horas productivas del día siguiente.

**Regla nueva (R12)**:
> En cualquier línea, en cualquier día, el primer SKU programado **NO paga setup**. Solo el segundo SKU en adelante (cambios intra-día) paga setup.

**Diferencia con el modelo actual (post-F1)**:

| Caso | Modelo actual | Regla R12 (nueva) |
|---|---|---|
| Día 0, SKU único | setup = 0 (R4 vigente) | setup = 0 |
| Día N, SKU continúa de día anterior | setup = 0 | setup = 0 |
| **Día N, SKU nuevo (no era el de ayer), primer del día** | **setup = 1** ⚠ | **setup = 0** ✅ |
| Día N, segundo SKU en adelante en el mismo día | setup = 1 | setup = 1 |

**Implementación técnica**: ver `R12_PRIMER_SETUP_GRATIS.md` (documento aparte, detallado).

→ Registra **R12** como regla de negocio en CLAUDE.md y en `docs/v1.3_DISENO_ARQUITECTURA.md` §3.

---

## Hallazgo crítico de la sesión: O10 (resuelto)

**Síntoma post-V4**: Sachetera 0%, 151 quiebres, objective ×15 vs F1 baseline.

**Causa**: batch_min_u=9500 vs cap_día_efectiva=7600 con factor 0.8 → infactible.

**Resolución (con decisiones del Gerente)**: factor_velocidad pasa de 0.8 a 1.0 → cap_día_efectiva = 9500 = batch_min. Marginalmente factible **si y solo si** se aplica también R12 (primer SKU del día sin setup), porque sino los días con cambio de SKU pierden 422 unidades del setup y vuelven a quedar bajo batch_min.

**Hipótesis**: con D1 + D2 + D3 (R12) aplicadas, Sachetera produce normalmente en planes con corridas largas (3+ días consecutivos del mismo SKU) y queda sub-utilizada en semanas de cambio frecuente. El plan generado deberá mostrar:
- Sachetera entre 50-100% en semanas con un SKU dominante.
- Quiebres mínimos o cero.
- Posible bajo_ss en semanas con cambio (margen cero por diseño O12).

---

## Plan de trabajo para próxima sesión

**Bloque V5 — Aplicar decisiones del Gerente y cerrar bloque V4**

Pasos detallados en `MENSAJE_INICIO_CLAUDE_CODE.md`. Resumen:

1. **Verificar estado**: `git log`, `git status`, BD original (batch_min=9500, factor=0.8).
2. **Aplicar D2 (factor_velocidad=1.0)**: UPDATE en BD + actualizar Excel V4.
3. **Aplicar D3 (R12) en `optimizer.py`**: cambio quirúrgico en restricción de `inicio`. Detalle en `R12_PRIMER_SETUP_GRATIS.md`.
4. **Validar post-fix**: regenerar `/plan`, comparar con baseline F1 + Test B'. Sachetera debería arrancar.
5. **Validar visualmente** dashboard.
6. **Commits separados**: uno para D2 (BD/Excel), otro para D3 (R12 en optimizer).
7. **Frontend hardcoding** (commit 4 condicional).
8. **Decisión sobre fix_stock.py** (commit 5 condicional).
9. **Push** del bloque V4 + V5.
10. **Documento de cierre** `ESTADO_TECNICO_PROYECTO_<fecha>.md`.

---

## Pendientes después del bloque V5

- **F2 — Sequencer (Nivel 2)**: ya desbloqueado. R12 conecta limpiamente con `paga_setup[pos=1]=0` en N2.
- **F3 — Numeración OFs por (sku, fecha_lanzamiento, linea)**: pendiente.
- **F4 — Endpoints CRUD para mrp_setup_matrix**: parcial (la tabla existe, los endpoints faltan).
- **F5 — Cargar matriz real de setups SKU→SKU** cuando llegue del Gerente (~2 semanas desde el 02/05).
- **F6 — Frontend con orden intra-día**.

---

## Observaciones acumuladas (O1-O12)

- **O1**: Sachetera ajustada — velocidad 1055 vs 3000 anterior.
- **O2 — RESUELTA por D2**: Doble interpretación factor_velocidad. El factor 0.8 era doble-conteo.
- **O3**: Asignación 1-a-1 limita F2 — solo L1Pet LV tiene múltiples SKUs (5).
- **O4**: Matriz de setups uniforme inicial. F2 no preferirá orden por setup hasta matriz real.
- **O5**: `forecast/fix_stock.py` ruido de v1.1. Pendiente evaluar si eliminar.
- **O6**: UserWarning en `pd.to_datetime` para fecha_vcto — TODO(v1.4) en stock.py:97-98.
- **O7**: Stock al 05/05 vs F1 baseline — diferencias incluyen stock más reciente.
- **O8**: Bug visual OF triplicada en DetalleProduccion.jsx. Reproducir post-V5 cerrado.
- **O9**: `migrate_params.py` asume estructura específica del Excel por columna posicional.
- **O10 — RESUELTA por D1+D2+R12**: batch_min=9500 con factor=0.8 era infactible. Fix combinado.
- **O11**: Solver_time=60s al timeout con parámetros V4. No es regresión, es problema combinatorio legítimo más duro. Considerar timeout a 120s.
- **O12 (NUEVA)**: Sachetera con margen cero por diseño operativo. Decisión deliberada del Gerente, no bug.

---

## Estado de la BD al cierre

```sql
-- Confirmado al cierre 05/05/2026 (post-conversación Gerente)
-- BD en estado original V4, AÚN NO se aplicó la decisión D2

SELECT sku, batch_min_u FROM mrp_sku_params WHERE sku IN ('250010105', '260010105');
-- 250010105 | 9500
-- 260010105 | 9500

SELECT sku, linea, factor_velocidad FROM mrp_sku_lineas
WHERE sku IN ('250010105', '260010105') AND linea = 'Sachetera';
-- 250010105 | Sachetera | 0.8
-- 260010105 | Sachetera | 0.8
```

El cambio de D2 (factor 0.8 → 1.0) **se aplica al inicio de la próxima sesión**, no ahora.

---

## Material para arrancar próxima sesión

1. **Este documento** (`SIGUIENTE_SESION_CHAT_WEB.md`) → primer mensaje al Claude del nuevo chat web.
2. **Mensaje inicial Claude Code** (`MENSAJE_INICIO_CLAUDE_CODE.md`) → primer mensaje al iniciar Claude Code.
3. **Detalle técnico R12** (`R12_PRIMER_SETUP_GRATIS.md`) → referencia técnica para implementar la regla nueva en `optimizer.py`.
4. **Brief Gerente archivado** (`BRIEF_GERENTE_PRODUCCION_RESUELTO.md`) → para referencia histórica de cómo se llegó a las decisiones.

---

## Tag de retorno seguro (sin cambios)

```powershell
git checkout v1.2-piloto
docker compose down && docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast
```
