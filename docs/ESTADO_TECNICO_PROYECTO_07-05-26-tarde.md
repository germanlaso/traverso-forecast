# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.3-V5 + ampliación piloto (en curso) — Actualizado: 07/05/2026 (tarde)

---

## Contexto de esta sesión (chat web)

Sesión de continuación del cierre V5 (mañana 07/05). Esta sesión aborda dos cosas en paralelo:

1. **Ampliación del piloto** de 10 a 18 SKUs para tener un universo más realista antes de F2 y para que la cota `N_max=4` empiece a morder de verdad.
2. **Alineación de docs y Excel con la realidad de la BD**: los snapshots viejos hablaban de `L001/L002/S001/S002` con velocidades aproximadas, pero la BD lleva tiempo con `L1Pet LV / L1Pet A / Sachetera` y velocidades reales. Esta sesión documenta la verdad actual.

**No hay cambios de código en backend en esta sesión.** El backend sigue en `feature/v1.3-cascada` con los 9 commits del bloque V5. Los cambios son en datos (Excel/BD) y documentación.

---

## Hallazgos al cruzar BD vs Excel vs docs viejos

### 1. Nomenclatura de líneas (corregida en docs)

Los snapshots desde v1.0 a v1.2 hablaban de 4 líneas (`L001 / L002 / S001 / S002`). La realidad de la BD es **3 líneas**:

| Código (BD) | Área | Velocidad real | Cap/día | Cap/sem |
|---|---|---|---|---|
| `L1Pet LV` | LIQUIDOS/VINAGRERA | 12.223 u/h | ~110.000 | ~550.000 |
| `L1Pet A` | LIQUIDOS/VESPUCIO | 9.445 u/h | ~85.000 | ~425.000 |
| `Sachetera` | SALSAS/VESPUCIO | 1.056 u/h | ~9.500 | ~47.500 |

**Tipografía exacta** (case-sensitive, PK en `mrp_lineas`): `L1Pet LV`, `L1Pet A`, `Sachetera`. NO en mayúsculas, NO con espacios distintos.

**Capacidades** asumen `turnos_dia=1`, `horas_turno=9` (no 8 como decían los docs viejos), `dias_semana=5`.

**Sachetera**: `cap_dia ≈ batch_min = 9.500` (margen cero por diseño, decisión Gerente, no bug).

### 2. `mrp_setup_matrix` ya existe parcialmente

Schema verificado en BD (poblado el 05/05/2026, 30 pares):

```sql
sku_desde       VARCHAR(30) NOT NULL
sku_hasta       VARCHAR(30) NOT NULL
linea           VARCHAR(20) NOT NULL
tiempo_horas    DOUBLE PRECISION NOT NULL CHECK (tiempo_horas >= 0)
updated_at      TIMESTAMP DEFAULT NOW()
PRIMARY KEY (sku_desde, sku_hasta, linea)
INDEXES: idx_setup_matrix_linea, idx_setup_matrix_destino
```

El doc de arquitectura listaba F4 como pendiente, pero el schema y la migración inicial ya estaban hechos. **F4 quedará formalmente cerrada cuando estén los endpoints CRUD + función `regenerar_matriz_setup_dummy()`**.

Datos actuales (pre-importación): convención dummy `tiempo_horas = 0.5` para pares ≠, `0` para diagonales `(X, X)`.

### 3. La columna `linea_preferida` existe en `mrp_sku_params`

Output de BD lo confirma. Significa que `migrate_params.py` sí lee `Línea Producción` de la pestaña SKU_PARAMS y la escribe en BD. **Decisión:** mantener la columna en SKU_PARAMS (igual que V4) para no romper migrate_params.py. **Deuda V6.2 registrada**: derivar `linea_preferida` de `mrp_sku_lineas.preferida=true` en lugar de leerla de SKU_PARAMS.

---

## Ampliación del piloto: 10 → 18 SKUs

### Excel canonical actualizado y normalizado

Archivo: `forecast/data/Traverso_Parametros_MRP.xlsx`. 

8 SKUs nuevos (todos PRODUCCION):

| SKU | Descripción | Línea preferida | Alternativa | Factor pref/alt |
|---|---|---|---|---|
| 141010160 | Salsa Soya 12x320 PET | L1Pet A | — | 1.0 |
| 141010210 | Salsa Soya 20x1000 PET | L1Pet A | — | 0.8 |
| 123010160 | Jugo Limón 60% 12x320 PET | L1Pet A | — | 1.0 |
| 111010115 | Vinagre Blanco 12x1000 PET | L1Pet LV | L1Pet A | 0.8 / 0.8 |
| 112011115 | Vinagre Rosado Montaner 12x1000 PET | L1Pet LV | L1Pet A | 0.8 / 0.8 |
| 113010210 | Vinagre Manzana 20x1000 PET | L1Pet LV | L1Pet A | 0.8 / 0.8 |
| 114010115 | Vinagre Incoloro 12x1000 PET | L1Pet LV | L1Pet A | 0.8 / 0.8 |
| 251010105 | Salsa Barbecue 10x1000 BOLSA | Sachetera | — | 1.0 |

### Distribución resultante (18 SKUs total = 16 PROD + 2 IMP)

| Línea | SKUs alcanzables | Detalle |
|---|---|---|
| L1Pet LV | 10 | 5 vinagres ×30×500 + Jugo Limón 30x500 + 4 con alternativa (Blanco/Rosado/Incoloro ×12×1000, Manzana 20×1000, Limón 20×1000 con LV preferida) |
| L1Pet A | 8 | 3 nativos (Soya ×2, Limón 60%) + 5 como alternativa de los anteriores |
| Sachetera | 3 | Mostaza, Ketchup, Salsa Barbecue |

**Por qué importa para v1.3**:
- L1Pet LV con 10 SKUs alcanzables y `N_max=4` obliga al optimizador a decidir qué 4 entran cada día. La cota empieza a morder.
- L1Pet A con varios SKUs como alternativa va a estresar el W_ALT y la decisión preferida vs. alt.
- Sachetera con 3 SKUs simétricos da casos de prueba para el sequencer.

### Iteraciones Excel ↔ chat (V1 → V6)

Quedaron registradas en outputs locales del chat:
- V1 inicial: subido por usuario tras agregar 8 SKUs.
- V2: corrección de cap_bodega Salsa Barbecue (1.267 → 95.000) y factor Vinagre Manzana 20x1000 alt (1.0 → 0.8).
- V3: corrección de inconsistencia preferida SKU 121010210 entre SKU_PARAMS y SKU_LINEA.
- V4: normalización tipográfica a MAYÚSCULAS.
- V5: corrección preferida SKUs 112011115 y 114010115 (L1PET LV en ambas hojas).
- V6 (canonical actual): renormalización tipográfica a CAPITALIZADO (`L1Pet LV / L1Pet A / Sachetera`) **alineado con BD**, no con MAYÚSCULAS. 61 celdas modificadas (16 en SKU_PARAMS, 45 en SKU_LINEA).

**Decisión final de tipografía**: capitalizado, igual a BD. La PK en `mrp_lineas` es case-sensitive, importar con MAYÚSCULAS hubiera creado duplicados o roto el upsert.

---

## Plan para próxima sesión de Claude Code

Esta sesión cierra solo en el chat. La implementación va a Code. **No tocar código backend en esta sesión.**

### Tarea para Code: importar Excel + repoblar matriz

**Pre-condiciones**:
- Branch `feature/v1.3-cascada` checked out (9 commits ahead de origin tras V5).
- Excel canonical en `forecast/data/Traverso_Parametros_MRP.xlsx` (versión V6 normalizada, alineada con BD).
- Docker containers up (`traverso_forecast`, `traverso_dashboard`, `traverso_mrp_db`).
- VPN activa (para `/stock/refresh` y `/plan`).

**Pasos secuenciales**:

1. **Backup BD pre-cambio**:
   ```powershell
   docker exec traverso_mrp_db pg_dump -U mrp_user mrp > backup_pre_ampliacion_$(Get-Date -Format yyyyMMdd_HHmmss).sql
   ```

2. **Verificar consistencia Excel V6** (sanity check antes de importar):
   ```python
   # Esperado:
   # SKU_PARAMS: 18 filas (16 PROD + 2 IMP)
   # SKU_LINEA: 22 filas (16 SKUs activos en al menos 1 línea, 5 con alt)
   # Líneas únicas: {Sachetera, L1Pet LV, L1Pet A}
   # 0 inconsistencias entre SKU_PARAMS.linea_produccion y SKU_LINEA.preferida=S
   ```

3. **Importar a BD**:
   ```powershell
   curl.exe -X POST http://localhost:8000/params/importar-excel -s | ConvertFrom-Json
   ```

4. **Verificar post-import**:
   ```powershell
   # mrp_sku_params debe tener 18 filas
   docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT COUNT(*) FROM mrp_sku_params;"
   docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT sku, linea_preferida FROM mrp_sku_params WHERE tipo='PRODUCCION' ORDER BY sku;"

   # mrp_sku_lineas debe tener 21 filas (16 SKUs PROD + 5 alternativas)
   docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT COUNT(*) FROM mrp_sku_lineas;"

   # Validar consistencia: linea_preferida en sku_params == linea con preferida=true en sku_lineas
   docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "
   SELECT p.sku, p.linea_preferida, l.linea AS linea_pref_skulinea
   FROM mrp_sku_params p
   LEFT JOIN mrp_sku_lineas l ON p.sku = l.sku AND l.preferida = true
   WHERE p.tipo = 'PRODUCCION'
   ORDER BY p.sku;
   "
   ```

5. **Implementar `regenerar_matriz_setup_dummy()`** en `forecast/db_mrp.py`:

   ```python
   def regenerar_matriz_setup_dummy(conn) -> dict:
       """
       Repuebla mrp_setup_matrix con la matriz dummy 'predecesor anónimo'.
       Para cada par (sku_desde, sku_hasta, linea) donde ambos SKUs tienen
       esa línea en mrp_sku_lineas:
         - matriz[A, B, linea] = mrp_sku_lineas.t_cambio_hrs[B, linea]  si A != B
         - matriz[A, A, linea] = 0
       
       NO borra entradas existentes con tiempos != dummy (preserva calibración manual).
       Modo seguro: solo INSERT ON CONFLICT DO UPDATE para los pares calculados.
       
       Returns: {"insertados": N, "actualizados": M, "total_pares": T}
       """
       # 1. Leer todos los pares SKU-línea con t_cambio_hrs
       # 2. Agrupar por línea
       # 3. Para cada línea, generar producto cartesiano
       # 4. UPSERT en mrp_setup_matrix
       ...
   ```

   Y exponerla via endpoint `POST /params/setup-matrix/regenerar-dummy` en `main.py`.

6. **Ejecutar la regeneración**:
   ```powershell
   curl.exe -X POST http://localhost:8000/params/setup-matrix/regenerar-dummy -s
   ```

7. **Verificar matriz post-regeneración**:
   ```powershell
   # Esperado: 173 pares total
   #   L1Pet LV: 100 (10×10)
   #   L1Pet A: 64 (8×8)
   #   Sachetera: 9 (3×3)
   docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "
   SELECT linea, COUNT(*) FROM mrp_setup_matrix GROUP BY linea ORDER BY linea;
   "
   ```

8. **Smoke test del optimizador con horizonte 13**:
   ```powershell
   [System.IO.File]::WriteAllText("$PWD\body.json", '{"horizonte_semanas": 13, "optimizar": true}')
   curl.exe -X POST http://localhost:8000/plan -H "Content-Type: application/json" --data "@body.json" -o plan.json -s -w "Status: %{http_code} | %{time_total}s`n"
   ```

   **Métricas esperadas**:
   - Status: FEASIBLE u OPTIMAL.
   - solver_time: 15-30s estimado (vs 6s con 10 SKUs).
   - OFTs PRODUCCION: ~400-500 (vs 268 con 10 SKUs).
   - `N_max=4` debería morder en al menos un bucket de L1Pet LV (10 SKUs alcanzables).
   - 0 errores de KeyError o referencias a `mrp_setup_matrix` faltantes.

9. **Validación visual frontend**:
   - Plan de Producción muestra OFTs con líneas correctas.
   - Stock por SKU genera proyección para los 8 SKUs nuevos.
   - Detalle Producción muestra distribución diaria coherente en las 3 líneas.
   - 0 regresiones visuales detectadas.

10. **Commits sugeridos** (autor `germanlaso`, sin Co-Authored-By, en español):

    ```
    chore(params): ampliar piloto a 18 SKUs — import Excel V6 + repoblar matriz dummy

    - Excel canonical alineado con BD (capitalizado: L1Pet LV / L1Pet A / Sachetera)
    - 8 SKUs PRODUCCION nuevos (Soya ×2, Limón 60%, Vinagres ×12×1000 ×4, Salsa Barbecue)
    - mrp_setup_matrix: 30 → 173 pares (matriz dummy uniforme = 0.5h)
    
    feat(db_mrp): agregar regenerar_matriz_setup_dummy()

    - Función reutilizable para repoblar matriz al sumar SKUs nuevos
    - Endpoint POST /params/setup-matrix/regenerar-dummy
    - Modo upsert seguro: no borra calibraciones manuales existentes
    
    docs: actualizar CLAUDE.md, v1.3_DISENO_ARQUITECTURA.md, snapshot 07-05-tarde
    ```

### Pendientes operativos / decisiones para sesión futura

- **Vinagre Rosado bajo nivel de servicio**: comportamiento preexistente, NO introducido por D3 ni por la ampliación. Revisar parámetros (forecast, SS_dias, batch_min, prioridades en L1Pet LV) con Gerente. NO bloqueante para v1.3.
- **`Traverso_Parametros_MRP_V4.xlsx` en raíz** (untracked): decidir si eliminar (canonical ya tiene mismo contenido), archivar a SharePoint, o dejar. Recomendación: eliminar tras archivar.
- **Scripts transitorios en `tests/fixtures/`**: `decompose_objective.py`, `test_r12.py`, `inspect_lead_time_excel.py`. Decidir si versionar o eliminar.
- **2 docs modificados en `docs/cierre_sesion_05-05-26/`**: revisar y commitear o descartar cambios.
- **Push pendiente**: 9 commits del V5 + nuevos commits de esta ampliación. Pushear todos juntos al final.

---

## Estado git esperado al cierre de la próxima sesión Code

```
On branch feature/v1.3-cascada
Your branch is ahead of 'origin/feature/v1.3-cascada' by ~12 commits.

Commits del bloque V5 (ya estaban):
  4077039  chore(params): D2 — factor_velocidad 1.0 para Sachetera
  d866a77  chore(params): D3 — lead_time 1 día efectivo para 8 SKUs producción
  4db4c76  feat(optimizer): R12 — primer SKU del día sin setup
  [+5 commits previos del bloque F1+V4]

Commits nuevos de la ampliación piloto:
  XXXXXXX  chore(params): ampliar piloto a 18 SKUs — import Excel V6 + matriz dummy
  XXXXXXX  feat(db_mrp): agregar regenerar_matriz_setup_dummy()
  XXXXXXX  docs: CLAUDE.md, v1.3_DISENO_ARQUITECTURA.md, snapshot 07-05-tarde
```

Pushear cuando esté validado:
```powershell
git push origin feature/v1.3-cascada
```

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

Esto deja el sistema en estado validado al 01/05/2026 (pre-V5, pre-ampliación).

Para volver al cierre del bloque V5 sin la ampliación: `git checkout 4db4c76`.

Para volver al estado post-ampliación (esta sesión): cuando los commits estén pusheados, será `git checkout feature/v1.3-cascada`.

---

## Tags Git

- `v1.0` — MRP clásico + Forecast + Aprobaciones
- `v1.1-piloto` — OR-Tools semanal + sincronización + multi-líneas
- `v1.2-backend` — CP-SAT diario + factor_velocidad + cajas
- `v1.2-piloto` — Frontend completado + setup_unidades + match por numero_of (estable)
- `feature/v1.3-cascada` (branch, 9 commits ahead pre-ampliación) — F1 + V4 + V5 (D2+R12+D3)
- **Esta sesión** — agrega ampliación piloto (18 SKUs) + regenerar_matriz_setup_dummy
- `v1.3-piloto` (futuro) — cuando F1 + ampliación + F2 + F3 + F6 estén juntos y mergeados a `main`

---

## Contexto del negocio (sin cambios)

- **Empresa**: Traverso S.A. (alimentos chilenos)
- **Segmento piloto ampliado**: COMERCIAL — 18 SKUs (16 PRODUCCION + 2 IMPORTACION)
- **Total SKUs activos**: 471 (escalamiento futuro)
- **Líneas**: L1Pet LV, L1Pet A, Sachetera
- **Stack**: FastAPI + Prophet + OR-Tools CP-SAT + React + PostgreSQL + SQL Server (Docker)

---

*Cerrado al fin de la sesión chat web del 07/05/2026 (tarde). Próxima sesión: Claude Code ejecuta el plan documentado en este archivo.*
