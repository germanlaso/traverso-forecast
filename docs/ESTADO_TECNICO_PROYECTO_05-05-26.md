# Estado técnico del proyecto — 05/05/2026

> **Versión**: `v1.3-F1+V4-pendiente-validacion-gerente`
> **Branch**: `feature/v1.3-cascada` (4 commits del bloque V4 locales, sin push).
> **Tag de retorno seguro**: `v1.2-piloto` (intacto).
> **Snapshot generado al cierre de la sesión del lunes 05/05/2026**, antes de que el Gerente de Producción decida sobre la observación O10.

---

## 1. Cambios en sesión 05/05/2026

### 1.1 Antecedente — fix del domingo 03/05 (ya commiteado)

| Hash | Descripción |
|---|---|
| `bcd86d1` | `fix(stock): envolver fetch_and_save_stock en bloque with engine.connect()` |

`POST /stock/refresh` devolvía `NameError: name 'conn' is not defined` (línea 76 de `stock.py`). Se envolvió el `execute+fetchall` en `with engine.connect() as conn:`. Validado end-to-end: 945 registros / 297 SKUs cargados sin error. TODO(v1.4) registrado en `forecast/stock.py:97-98` para fijar `dayfirst=True` o `format="%d/%m/%Y"` en el parsing de `fecha_vcto` (UserWarning de pandas, no rompe).

### 1.2 Bloque V4 (4 commits + 1 housekeeping)

| # | Hash | Mensaje |
|---|---|---|
| 1 | `7892b4d` | `chore(db): limpiar OFs aprobadas previo a recodificación de líneas` |
| 1.5 | `a4bd815` | `chore(repo): ignorar archivos de backup SQL locales` |
| 2 | `d0f36b9` | `feat(db): crear tabla mrp_setup_matrix con CRUD en db_mrp.py` |
| 3 | `b47ae40` | `chore(params): cargar parámetros V4 y matriz de setups inicial simétrica` |

Backup BD pre-V4 generado fuera de Git: `backup_pre_v4_20260505_0713.sql` (13836 bytes, ASCII puro, válido). Patrón `backup_*.sql` agregado a `.gitignore`.

### 1.3 Bugs detectados durante la carga V4 (todos resueltos en commit 3)

1. **Zombies en `mrp_lineas`**: `upsert_linea` actualizaba por código pero nunca borraba códigos viejos. Tras la primera corrida quedaban 7 filas (3 nuevas + 4 zombies de v1.2: L001/L002/S001/S002).
   - **Fix**: nueva función `borrar_todas_lineas()` en `db_mrp.py` + llamada explícita al inicio de la carga, antes del loop de LINEAS_PRODUCCION. Orden defensivo: primero `borrar_todas_sku_lineas()` (hijas) → después `borrar_todas_lineas()` (padre), aunque no hay FK declarada.

2. **Offset `Factor_Linea` row[6] → row[7]**: en V3 la columna `Factor_Linea` estaba en col 6. En V4 el Excel insertó una columna `Notas` (texto libre) y movió `Factor_Linea` a col 7. El código leía `row[6]` (`None` para todos) → `factor=1.0` por default para los 8 SKUs.
   - **Fix**: cambiar `row[6]` → `row[7]` en SKU_LINEA, con comentario explicativo: `# NOTA V4: col[6] es 'Notas' (texto libre), Factor_Linea está en col[7]. En V3 estaba en col[6]. Si vuelve a moverse, ajustar acá.`

3. **Mapeo nombre→código en SKU_PARAMS (bug crítico latente)**: en V3, la columna `Línea\nProducción` traía nombre de línea ("Líquidos 1") y el código mapeaba nombre→código vía `LINEA_NOMBRE_A_CODIGO` con fallback por palabras clave (`liquid`/`salsa`). En V4 esa columna ya trae el código directo (`Sachetera`, `L1Pet LV`, `L1Pet A`). El fallback no matcheaba con los nuevos nombres → **`linea_preferida = ""` para los 8 SKUs PRODUCCION** si no se hubiera detectado.
   - **Fix**: leer el código directo (`linea_cod = _str(row[10])`). Variable global `LINEA_NOMBRE_A_CODIGO` eliminada por código muerto.

4. **Doble llamada a `borrar_todas_sku_lineas()`**: el fix del bug 1 introdujo una limpieza al inicio del programa, pero la sección SKU_LINEA mantenía la llamada original (línea 152). Idempotente pero confunde lecturas futuras.
   - **Fix**: eliminada la llamada redundante. Filosofía declarativa: una sola limpieza al inicio.

### 1.4 Otros cambios técnicos del bloque V4

- **LINEAS_PRODUCCION dedup**: V4 trae 6 filas (1 por par línea+SKU). `set()` de códigos vistos para skipear duplicados al cargar `mrp_lineas`.
- **`LINEA_CODIGO_NORMALIZER`** (`SACHETERA → Sachetera`, etc.): aplicado solo a SKU_LINEA (donde V4 trae mayúsculas). LINEAS_PRODUCCION y SKU_PARAMS ya traen formato canónico.
- **`_print_resumen()`**: nueva función al final de `migrar()` que imprime conteos post-carga (`mrp_lineas`, `mrp_sku_params`, `mrp_sku_lineas`). Sanity check visual.
- **`cargar_setup_matrix_inicial()`**: nueva función separada llamada en `__main__` después de `migrar()`. Genera matriz simétrica desde `mrp_sku_lineas`. Usa el patrón de orquestación: delega 100% en CRUD de `db_mrp.py` (`borrar_toda_setup_matrix`, `upsert_setup_entry`, `get_all_sku_lineas`).

---

## 2. Validación post-carga (V1+V2+V3)

### 2.1 Comparación contra baseline F1

| Métrica | F1 baseline (h=13) | post-V4 (h=13) | Δ |
|---|---|---|---|
| `status` | OPTIMAL | **FEASIBLE** | regresión |
| `solver_time_sec` | 6.02 | 60.02 | al tope timeout |
| `objective_value` | 155,727,700,050 | 2,391,128,800,000 | ×15.4 |
| `ofts_produccion` | 268 | 175 | -35% |
| `ofts_con_paga_setup` | 113 | 108 | -5 |

### 2.2 Hallazgo crítico — Sachetera 0%

`optimizacion.uso_promedio_lineas_pct` post-V4:
- **L1Pet A**: 5.4%
- **L1Pet LV**: 29.0%
- **Sachetera: 0.0%**

Cero OFTs para Mostaza (260010105) y Ketchup (250010105). El optimizador está aceptando **151 quiebres + 99 alertas BAJO_SS + 111 alertas EXCESO_BODEGA** como solución FEASIBLE preferida, en vez de operar Sachetera.

Ejemplos de alertas en los SKUs problemáticos: "Stock 110025 u bajo SS (**603630 u faltantes**)", "Stock 83572 u bajo SS (**543998 u faltantes**)" — indican demanda no satisfecha por meses.

---

## 3. Diagnóstico — Corte 0 sanity check de parámetros

### 3.1 Capacidad de Sachetera en V4

| Parámetro | Valor |
|---|---|
| `velocidad_u_hr` | 1055.55 |
| `horas_turno` × `turnos_dia` | 9 × 1 = 9 hrs |
| `dias_semana` | 5 |
| **`cap_dia_u` nominal** | 9 × 1055.55 = **9500 u/día** |
| **`factor_velocidad` Mostaza/Ketchup** | **0.8** |
| **`cap_dia_u` efectiva (con factor)** | 9500 × 0.8 = **7600 u/día** |
| Setup primer día (matriz) | 0.5 hrs → -422 u |
| **`cap_dia_u` neta primer día (factor + setup)** | 8.5 × 1055.55 × 0.8 = **7178 u** |

### 3.2 batch_min vs cap_dia — los ratios

`batch_min_u` Mostaza = `batch_min_u` Ketchup = **9500** (idénticos).

| Caso | batch_min | capacidad | ratio | ¿Producible en 1 día? |
|---|---|---|---|---|
| Sin factor, sin setup | 9500 | 9500 | **1.00** | apenas (sin margen) |
| Con factor 0.8, sin setup | 9500 | 7600 | **1.25** | **NO** |
| Con factor 0.8, con setup primer día | 9500 | 7178 | **1.32** | **NO** |

### 3.3 Coincidencia exacta — calibración teórica, no operativa

`batch_min_u = 9500 ≡ velocidad × horas = 1055.55 × 9`. La igualdad numérica exacta sugiere que el batch_min se calculó como "lo que cabe en un día perfecto, sin merma ni setup". Cualquier reducción real (factor de SKU, setup, feriado, paro) lo vuelve infactible.

Restricción operativa que choca: regla 3 de CLAUDE.md, **"OF ≤ capacidad diaria con factor_velocidad y descontando setup"**. Si `batch_min > cap_dia_efectiva`, el solver no puede colocar ni un solo batch viable → opta por NO producir y aceptar déficit total.

---

## 4. Test diagnóstico B' — UPDATE temporal de `batch_min`

### 4.1 Procedimiento

```sql
-- Snapshot
SELECT batch_min_u FROM mrp_sku_params WHERE sku IN ('250010105', '260010105');
-- → 9500 / 9500

-- Test
UPDATE mrp_sku_params SET batch_min_u = 3000 WHERE sku IN ('250010105', '260010105');

-- Regenerar plan vía POST /plan, capturar JSON.

-- REVERT
UPDATE mrp_sku_params SET batch_min_u = 9500 WHERE sku IN ('250010105', '260010105');
-- → 9500 / 9500 confirmado al cierre.
```

### 4.2 Tabla comparativa

| Métrica | post-V4 original | Test B' (batch_min=3000) | Δ |
|---|---|---|---|
| `status` | FEASIBLE | FEASIBLE | igual (timeout 60s) |
| `solver_time_sec` | 60.02 | 60.03 | igual |
| `objective_value` | 2,391,128,800,000 | **521,930,300,000** | **−78%** |
| `Sachetera uso%` | **0.0** | **68.1** | **+68 pts** |
| `L1Pet LV uso%` | 29.0 | 28.8 | igual |
| `L1Pet A uso%` | 5.4 | 5.5 | igual |
| `OFTs Sachetera` | 0 | 109 | **+109** |
| `OFTs Mostaza` | 0 | 55 | +55 |
| `OFTs Ketchup` | 0 | 54 | +54 |
| `ofts_produccion` | 175 | 278 | +59% |
| `ofts_con_paga_setup` | 108 | 130 | +20% |
| `alertas.quiebre` | **151** | **0** | **−151** |
| `alertas.bajo_ss` | 99 | 160 | +61 |
| `alertas.exceso_bodega` | 111 | 94 | −17 |

### 4.3 Conclusión del diagnóstico

- **Bloqueante absoluto identificado**: `batch_min_u = 9500` de Mostaza/Ketchup excede la capacidad diaria efectiva de Sachetera (7600/7178 con factor + setup).
- Bajándolo a 3000 (test reversible), Sachetera arranca y los **151 quiebres se reducen a 0**.
- `bajo_ss` sube (99 → 160) porque ahora el solver opera Sachetera al límite y deja stocks ajustados — problema de margen, mucho menos grave que el quiebre total.
- El bloque V4 técnico no tiene bug. Los 4 commits son válidos. La causa raíz es **calibración del Excel**, no código.

---

## 5. Observaciones actualizadas

### O1-O8 (sesiones anteriores)

Documentadas en `INICIO_SESION_04-05-26.md` y discusiones previas. Resumen:

- **O1**: Sachetera muy ajustada (Mostaza/Ketchup ≈ 844 u/hr efectivo, cap_bodega 95k vs SS ~90k).
- **O2**: Doble interpretación posible de `factor_velocidad` (la velocidad nominal V4 ya bajó respecto a V3; aplicar factor 0.8 encima podría ser doble-conteo).
- **O3**: Asignación 1-a-1 limita validación de F2 — solo L1Pet LV con varios SKUs (5).
- **O4**: Matriz de setups uniforme inicial (todos los `t_cambio_hrs = 0.5`).
- **O5**: `forecast/fix_stock.py` ruido viejo de v1.1 (commit `3242bce`). Pendiente decidir si eliminar.
- **O6**: UserWarning en `pd.to_datetime` para `fecha_vcto` (TODO v1.4 en `stock.py:97`).
- **O7**: Stock real al 04/05 distinto del que tenía F1 — métricas post-V4 difieren también por esto.
- **O8**: Bug visual triplicación de OF aprobada en `DetalleProduccion.jsx`. Pendiente fix post-V4.

### O9 — Bug latente del mapeo nombre→código en SKU_PARAMS (resuelto en commit 3)

El código v1.2 mapeaba nombre de línea V3 → código mediante `LINEA_NOMBRE_A_CODIGO` y fallback por palabras clave. V4 cambió la columna a código directo y el fallback no matcheaba — los 8 SKUs PRODUCCION habrían quedado con `linea_preferida = ""` si no se hubiera detectado en validación. Ya resuelto, pero anotado por el riesgo: **los Excels del Gerente cambian estructura entre versiones; los lectores en `migrate_params.py` necesitan tests de regresión por columna**.

### O10 — CRÍTICA: `batch_min = 9500` para Mostaza/Ketchup vs cap_dia Sachetera

**Esto bloquea el go-live con parámetros V4.** Tres opciones de resolución:

| Opción | Cambio | Resuelve | Riesgo |
|---|---|---|---|
| **A** | Quitar `Factor_Linea = 0.8` de Mostaza/Ketchup en Sachetera (asumir velocidad nominal ya reducida) | Marginalmente — cap_dia 9500 = batch_min 9500, sin holgura para setup | Si el factor era legítimo, sobrestimamos capacidad |
| **B** | Bajar `batch_min_u` Mostaza/Ketchup de 9500 a un valor entre 3000 y 7000 | Sí, con margen real | Necesita validación del Gerente sobre lote mínimo operativo |
| **C** | Subir `velocidad_u_hr` Sachetera (1055 → ~1320) o agregar turno/horas (9 → 11) | Sí | Si la velocidad/horas reales son las del V4, asume capacidad inexistente |

**Pregunta concreta para el Gerente:**
1. ¿El `batch_min = 9500` para Mostaza/Ketchup es operativamente intocable, o es heredado del Excel viejo?
2. ¿El `factor_velocidad = 0.8` se aplica sobre la velocidad nominal genérica de la línea (legítimo, factor adicional), o sobre una velocidad ya específica del SKU (doble-conteo)?
3. Si la velocidad nominal es 1055 u/hr × 9 hrs, y el batch mínimo es 9500, ¿la línea está pensada para correr exactamente un batch por día, sin tolerancia a paros/feriados/setups?

### O11 — Solver_time = 60s al timeout incluso sin batch_min como bloqueante

Tras el fix simulado del test B', el solver sigue al timeout de 60s (status FEASIBLE, no llega a OPTIMAL). En F1 baseline el solver llegaba a OPTIMAL en 6s. Diferencia atribuible a:

- Más OFTs por horizonte (278 vs 268 — comparable, pero con más combinatoria por las restricciones más ajustadas).
- Espacio de soluciones más restringido (cap_bodega 95k/110k vs 999999, factor_velocidad < 1, capacidades de línea más bajas).
- Mayor volumen de SS/déficit/exceso → mayor objective_value → árbol de búsqueda más amplio antes de podar.

**No es regresión sobre F1**: con parámetros V4 calibrados, el problema es genuinamente más duro combinatorialmente. Considerar para F2:

- Subir `solver_time_limit` a 120s o 180s.
- Investigar ajustes de heurística CP-SAT (search strategy hints).
- Evaluar si las restricciones N_max=4 y similar están sobre-restringiendo el problema con el dataset actual.

No bloquea el go-live de V4 una vez resuelta O10.

---

## 6. Estado de la rama `feature/v1.3-cascada`

```
b47ae40 chore(params): cargar parámetros V4 y matriz de setups inicial simétrica
d0f36b9 feat(db): crear tabla mrp_setup_matrix con CRUD en db_mrp.py
a4bd815 chore(repo): ignorar archivos de backup SQL locales
7892b4d chore(db): limpiar OFs aprobadas previo a recodificación de líneas
bcd86d1 fix(stock): envolver fetch_and_save_stock en bloque with engine.connect()  ← 03/05 (push hecho)
4df8d8b docs(v1.3): notas de cierre F1 (validación horizonte 13 + resumen)
b35ea5f feat(optimizer): día 0 no paga setup, inicio[0,k,l]=0 (R4)
```

- **4 commits del bloque V4 sin push** (`a4bd815`, `7892b4d`, `d0f36b9`, `b47ae40`). El push está pausado hasta que se resuelva O10.
- **BD en estado original**: `batch_min_u = 9500` confirmado tras revert del test B'. `mrp_lineas` (3 filas), `mrp_sku_params` (10), `mrp_sku_lineas` (8), `mrp_setup_matrix` (30).
- **`mrp_ordenes` y `mrp_aprobaciones`**: vacías (limpiadas en commit 1, no se aprobó nada después).
- **Tag de retorno seguro**: `v1.2-piloto` intacto.

---

## 7. Pendientes próxima sesión

### CRÍTICO — antes de cualquier otra cosa

- **Conversación con Gerente de Producción sobre O10** (las 3 opciones A/B/C arriba). Sin esa decisión, el bloque V4 no puede pushearse a producción porque generaría planes con 151 quiebres reales.

### Tras decisión del Gerente

- **Si opción B (bajar `batch_min`)**: UPDATE en BD (no requiere recompilar Excel) o nueva carga del Excel actualizado.
- **Si opción A (quitar factor 0.8)**: UPDATE en `mrp_sku_lineas` o nueva carga del Excel.
- **Si opción C (subir velocidad / horas)**: nueva carga del Excel con `LINEAS_PRODUCCION` modificado.
- **En todos los casos**: regenerar plan + verificar `quiebre = 0` y `Sachetera uso > 50%`.

### Después del fix de O10

- **Push del bloque V4** a `origin/feature/v1.3-cascada`.
- **Commit 4 condicional** (frontend hardcoding): grep `L001|L002|S001|S002|Líquidos 1|Líquidos 2|Salsas 1|Salsas 2` en `dashboard/src/`. Si aparece, fix obligatorio antes del go-live.
- **Investigar O8** (triplicación visual de OF aprobada) reproduciéndola con datos V4 cargados.
- **Evaluar O5** (`fix_stock.py` ruido v1.1): `git rm` + limpiar contenedor con `docker exec ... rm //app/fix_stock.py` (doble slash anti path-mangling).

### F2 — sequencer.py

- Trabajo planeado, **NO bloqueante por O10**. Una vez resuelta O10 y pusheado V4, se puede arrancar F2 en paralelo a las demás observaciones menores.

---

## 8. Tag de retorno seguro

```powershell
git checkout v1.2-piloto
docker compose down
docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast

# Restaurar BD desde backup
docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < backup_pre_v4_20260505_0713.sql
```

---

## 9. Comandos PowerShell útiles

```powershell
# Sincronizar archivo .py al contenedor (anti path-mangling Windows)
docker cp forecast\<archivo>.py traverso_forecast:/app/<archivo>.py
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast

# Ejecutar SQL en contenedor desde script (doble slash en path destino)
docker cp <archivo>.sql traverso_mrp_db:/tmp/migrate.sql
docker exec traverso_mrp_db psql -U mrp_user -d mrp -f //tmp/migrate.sql

# Backup BD pre-migración (evita corrupción UTF-16 de PowerShell `>`)
$ts = Get-Date -Format "yyyyMMdd_HHmm"
docker exec traverso_mrp_db pg_dump -U mrp_user -f /tmp/backup.sql mrp
docker cp traverso_mrp_db:/tmp/backup.sql "backup_pre_v4_$ts.sql"
docker exec traverso_mrp_db rm //tmp/backup.sql

# POST /plan (body sin BOM, status separado para evitar EPERM con -w)
Set-Content -Path body.json -Value '{"horizonte_semanas": 13, "optimizar": true}' -Encoding ASCII -NoNewline
curl.exe -X POST http://localhost:8000/plan -H "Content-Type: application/json" --data "@body.json" -o tests/fixtures/plan.json -s

# Extracción rápida de métricas
python tests/fixtures/extract_metrics.py tests/fixtures/plan.json
```

---

## 10. Contexto del negocio

Traverso S.A. (alimentos chilenos) está implementando un sistema de planificación de producción asistido por IA en sustitución de un proceso manual basado en Excel. El piloto actual cubre 10 SKUs comerciales sobre 4 líneas (en V4 reducidas a 3 activas: Sachetera, L1Pet LV, L1Pet A) — escalamiento futuro a 471 SKUs activos.

El bloque V4 corresponde a la carga de parámetros operativos provistos por el Gerente de Producción en abril 2026, con varios cambios estructurales:
- Códigos de línea (L001/L002/S001/S002 → Sachetera/L1Pet LV/L1Pet A).
- Velocidades reducidas (Sachetera 3000 → 1055 u/hr; L1Pet LV 12222; L1Pet A 9444).
- `horas_turno` 8 → 9.
- `batch_min`, `cap_bodega`, `factor_velocidad` recalibrados.
- Nueva tabla `mrp_setup_matrix` (originalmente F4, adelantada a V4 para no bloquear F2).

El bloque V4 técnico está completo; lo que falta es la validación operativa con el Gerente sobre las inconsistencias que la carga reveló (O10 principal).

---

*Documento generado al cierre de la sesión del lunes 05/05/2026, antes de la consulta con el Gerente de Producción sobre la observación O10.*
