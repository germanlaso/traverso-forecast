# Plan de carga — Parámetros V4 + creación de mrp_setup_matrix

> **Fecha del plan:** 03/05/2026 (domingo) · **Sesión objetivo:** lunes 04/05/2026
> **Branch:** `feature/v1.3-cascada` (ya con F1 cerrada, hash `4df8d8b`)
> **Punto de retorno seguro:** `git checkout v1.2-piloto`
> **Objetivo:** dejar el sistema listo para arrancar F2 con parámetros operativos correctos del Gerente de Producción y arquitectura completa de matriz de setups.

---

## Resumen ejecutivo

Dos cosas suceden en este plan:

1. **Carga de parámetros V4** del Gerente de Producción. Cambian: códigos de línea (de L001/L002/S001/S002 a Sachetera/L1Pet LV/L1Pet A), velocidades (Sachetera baja a un tercio), horas/turno (8 → 9), batch_min y cap_bodega de varios SKUs, y Factor_Velocidad por par SKU+línea.

2. **Creación adelantada de `mrp_setup_matrix`** (originalmente F4 del roadmap v1.3). Se carga matriz simétrica derivada de `t_cambio_hrs` actual. Cuando llegue la matriz real del Gerente, F5 es solo un UPDATE — la arquitectura ya está. Esto desacopla F2 de cualquier refactor futuro de fuente de datos.

Las decisiones del usuario (cerradas en chat 03/05):

- **Códigos de línea**: usar el "Código Línea" del Excel V4 (`Sachetera`, `L1Pet LV`, `L1Pet A`).
- **Líneas alternativas**: el sistema debe estar diseñado para soportarlas. Hoy todos los SKUs tienen 1 sola línea por restricción operativa transitoria.
- **OFs aprobadas existentes**: borrar antes de cargar (eliminamos el problema de FKs con códigos viejos).
- **batch_min no entero**: redondear hacia abajo (ej. 3666.67 → 3666).
- **Auto-transición A→A en setup_matrix**: incluir con `tiempo_horas = 0`.
- **Carga inicial simétrica**: `A→B = B→A = t_cambio_hrs[B, línea]` (predecesor anónimo, igual que hoy).

---

## Reglas de juego para la sesión con Claude Code

Las reglas persistentes ya están en memoria de Claude Code. Recordatorio para la sesión:

1. **Sin heredoc en `git commit -m`**. Una sola línea con `-m "mensaje"`.
2. **Sin `Co-Authored-By` ni firma de Claude**. Autor único `germanlaso`.
3. **Antes de cada cambio funcional**: mostrar diff/preview, esperar aprobación.
4. **Después de cada cambio en backend**: `docker cp` → `rm -rf __pycache__` → `docker compose restart forecast` → healthcheck → curl `/plan` → comparar métricas → commit.
5. **Sin push hasta el final** de este bloque. Cuando los 4 commits estén verdes y validados, recién push.
6. **El paso de validación post-carga es obligatorio**, no opcional. Si las métricas se ven raras, parar y discutir antes de continuar.

---

## Pre-requisitos (verificar antes de arrancar)

```powershell
# 1. Estar en feature/v1.3-cascada
git status
git branch --show-current  # → feature/v1.3-cascada

# 2. Working tree limpio (no hay cambios sin commitear)
git diff --stat  # → vacío

# 3. Contenedores corriendo
docker compose ps  # → traverso_forecast Up, traverso_dashboard Up, traverso_mrp_db Up

# 4. /plan responde
curl.exe http://localhost:8000/health
```

Si alguno falla, parar y resolver antes de seguir.

---

## Bloque de trabajo — 4 commits

### Paso 0 — Backup de la BD (no genera commit, va a archivo gitignored)

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmm"
docker exec traverso_mrp_db pg_dump -U mrp_user mrp > "backup_pre_v4_$ts.sql"
# Verificar que el .sql tiene contenido (>50KB típicamente)
Get-Item "backup_pre_v4_$ts.sql" | Select-Object Name, Length
```

El nombre del archivo va a estar dentro del patrón `backup_*.sql` que conviene agregar a `.gitignore` si no está.

---

### Commit 1 — `chore(db): limpiar OFs aprobadas previo a recodificación de líneas`

**Archivos modificados:** ninguno. Solo es un script SQL aplicado contra PostgreSQL. El commit en sí va a ser un script de migración archivado para trazabilidad.

**Crear archivo `migrate_v1.3_clean_ordenes.sql`:**

```sql
-- Limpieza previa a recarga de parámetros V4 (códigos de línea cambiarán)
BEGIN;

-- Backup conteo previo
SELECT 'mrp_aprobaciones', COUNT(*) FROM mrp_aprobaciones
UNION ALL
SELECT 'mrp_ordenes', COUNT(*) FROM mrp_ordenes;

-- Borrado en orden de dependencia
DELETE FROM mrp_aprobaciones;
DELETE FROM mrp_ordenes;

-- NOTA: NO se resetea mrp_contador_of. Decisión del usuario:
-- mantener correlativo histórico para consistencia con PDFs ya generados.

-- Verificación
SELECT 'mrp_aprobaciones', COUNT(*) FROM mrp_aprobaciones
UNION ALL
SELECT 'mrp_ordenes', COUNT(*) FROM mrp_ordenes;

COMMIT;
```

**Aplicar:**

```powershell
docker cp migrate_v1.3_clean_ordenes.sql traverso_mrp_db:/tmp/clean.sql
docker exec traverso_mrp_db psql -U mrp_user -d mrp -f /tmp/clean.sql
```

**Validación:**
```sql
SELECT COUNT(*) FROM mrp_aprobaciones;  -- Esperado: 0
SELECT COUNT(*) FROM mrp_ordenes;       -- Esperado: 0
SELECT MAX(numero_of_ult) FROM mrp_contador_of;  -- Esperado: lo que sea, > 0
```

**Commit:**
```powershell
git add migrate_v1.3_clean_ordenes.sql
git commit -m "chore(db): limpiar OFs aprobadas previo a recodificación de líneas"
```

---

### Commit 2 — `feat(db): crear tabla mrp_setup_matrix con CRUD en db_mrp.py`

**Archivos:**
- `migrate_v1.3_setup_matrix.sql` — schema
- `forecast/db_mrp.py` — funciones de acceso

**Crear `migrate_v1.3_setup_matrix.sql`:**

```sql
-- Tabla de matriz de setups SKU→SKU por línea (preparación para F2/F5)
BEGIN;

CREATE TABLE IF NOT EXISTS mrp_setup_matrix (
    sku_desde       VARCHAR(30) NOT NULL,
    sku_hasta       VARCHAR(30) NOT NULL,
    linea           VARCHAR(20) NOT NULL,
    tiempo_horas    FLOAT NOT NULL CHECK (tiempo_horas >= 0),
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (sku_desde, sku_hasta, linea)
);

CREATE INDEX IF NOT EXISTS idx_setup_matrix_linea
    ON mrp_setup_matrix(linea);

CREATE INDEX IF NOT EXISTS idx_setup_matrix_destino
    ON mrp_setup_matrix(sku_hasta, linea);

COMMIT;
```

**Aplicar:**
```powershell
docker cp migrate_v1.3_setup_matrix.sql traverso_mrp_db:/tmp/setup.sql
docker exec traverso_mrp_db psql -U mrp_user -d mrp -f /tmp/setup.sql
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "\d mrp_setup_matrix"
```

**Funciones a agregar en `forecast/db_mrp.py`:**

Buscar la sección de funciones relacionadas con `mrp_sku_lineas` y agregar a continuación:

```python
# ============================================================
# mrp_setup_matrix (introducida v1.3 — preparación para F2)
# ============================================================

def get_setup_matrix(linea: str | None = None,
                     sku_desde: str | None = None,
                     sku_hasta: str | None = None) -> list[dict]:
    """Lee filas de la matriz, opcionalmente filtradas."""
    sql = "SELECT sku_desde, sku_hasta, linea, tiempo_horas FROM mrp_setup_matrix WHERE 1=1"
    params = []
    if linea:
        sql += " AND linea = %s"
        params.append(linea)
    if sku_desde:
        sql += " AND sku_desde = %s"
        params.append(sku_desde)
    if sku_hasta:
        sql += " AND sku_hasta = %s"
        params.append(sku_hasta)
    sql += " ORDER BY linea, sku_desde, sku_hasta"

    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_setup_time(sku_desde: str, sku_hasta: str, linea: str) -> float:
    """
    Devuelve el tiempo de setup en horas.
    Convención v1.3: si sku_desde == sku_hasta, devuelve 0 (auto-transición).
    Si la fila no existe, devuelve None — el caller decide qué hacer
    (por ejemplo, en F2: alerta de configuración).
    """
    if sku_desde == sku_hasta:
        return 0.0

    sql = """
        SELECT tiempo_horas
        FROM mrp_setup_matrix
        WHERE sku_desde = %s AND sku_hasta = %s AND linea = %s
    """
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, (sku_desde, sku_hasta, linea))
            row = cur.fetchone()
            return float(row[0]) if row else None


def upsert_setup_entry(sku_desde: str, sku_hasta: str, linea: str,
                       tiempo_horas: float) -> None:
    """Insert o update de una fila."""
    sql = """
        INSERT INTO mrp_setup_matrix (sku_desde, sku_hasta, linea, tiempo_horas, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (sku_desde, sku_hasta, linea)
        DO UPDATE SET tiempo_horas = EXCLUDED.tiempo_horas, updated_at = NOW()
    """
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, (sku_desde, sku_hasta, linea, float(tiempo_horas)))
        c.commit()


def borrar_toda_setup_matrix() -> None:
    """Limpia la tabla. Usado por la migración inicial."""
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM mrp_setup_matrix")
        c.commit()
```

**Validación:**
```powershell
docker cp forecast\db_mrp.py traverso_forecast:/app/db_mrp.py
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast
docker logs traverso_forecast --tail 20  # Sin tracebacks

docker exec traverso_forecast python3 -c "
from db_mrp import get_setup_matrix, get_setup_time
print('matrix vacía:', get_setup_matrix())
print('auto-transicion:', get_setup_time('A', 'A', 'L1Pet LV'))  # → 0.0
print('inexistente:', get_setup_time('A', 'B', 'L1Pet LV'))  # → None
"
```

**Commit:**
```powershell
git add migrate_v1.3_setup_matrix.sql forecast/db_mrp.py
git commit -m "feat(db): crear tabla mrp_setup_matrix con CRUD en db_mrp.py"
```

---

### Commit 3 — `chore(params): cargar parámetros V4 y matriz de setups inicial simétrica`

Este es el commit grande. Tres cambios:

#### 3.1 — Reemplazar Excel en `data/`

```powershell
# Backup del Excel V3 (por las dudas)
Copy-Item data\Traverso_Parametros_MRP.xlsx data\Traverso_Parametros_MRP_V3_backup.xlsx
# Reemplazar con V4
Copy-Item <ruta-de-descarga>\Traverso_Parametros_MRP_V4.xlsx data\Traverso_Parametros_MRP.xlsx
```

> **Nota**: el `migrate_params.py` siempre lee `data/Traverso_Parametros_MRP.xlsx`. Reemplazamos ese archivo, no el nombre.

#### 3.2 — Ajustes al `migrate_params.py`

Hay que revisar y modificar:

**a) Lectura de pestaña LINEAS_PRODUCCION** — la columna "Código Línea" ahora trae los nombres reales (`Sachetera`, `L1Pet LV`, `L1Pet A`). Verificar que el código actual use esa columna como PK y no `Nombre Línea` (que ahora trae la categoría tipológica `SALSAS`/`LÍQUIDOS`).

**b) Lectura de pestaña SKU_LINEA** — la columna "Código Línea" trae mayúsculas (`SACHETERA`, `L1PET LV`, `L1PET A`). Hay que **normalizar a los códigos canónicos** de LINEAS_PRODUCCION. Mapping explícito:

```python
LINEA_CODIGO_NORMALIZER = {
    "SACHETERA": "Sachetera",
    "L1PET LV":  "L1Pet LV",
    "L1PET A":   "L1Pet A",
}
```

**c) Redondeo hacia abajo** de campos `batch_min_u`, `batch_mult_u` y `compra_minima_u` cuando vienen como float:

```python
import math
batch_min_u = math.floor(float(row["Batch\nMínimo (u.)"]))
```

**d) Nueva columna `Factor_Linea` en SKU_LINEA**. Default 1.0 si está vacío.

**e) NUEVO BLOQUE — Generación de matriz de setups inicial.** Después de cargar `mrp_sku_lineas`, agregar:

```python
def cargar_setup_matrix_inicial():
    """
    Genera la matriz inicial simétrica desde mrp_sku_lineas.
    Para cada línea: para cada par (sku_a, sku_b) de los SKUs asignados a esa línea:
      - sku_a → sku_a: 0
      - sku_a → sku_b: t_cambio_hrs[sku_b, linea]  (predecesor anónimo)
      - sku_b → sku_a: t_cambio_hrs[sku_a, linea]
    """
    from db_mrp import borrar_toda_setup_matrix, upsert_setup_entry, get_all_sku_lineas

    print("\n=== Cargando mrp_setup_matrix (simétrica inicial) ===")
    borrar_toda_setup_matrix()

    sku_lineas = get_all_sku_lineas()  # lista de dicts {sku, linea, t_cambio_hrs, ...}

    # Agrupar por línea
    por_linea = {}
    for sl in sku_lineas:
        por_linea.setdefault(sl["linea"], []).append(sl)

    total_filas = 0
    for linea, items in por_linea.items():
        # Mapa sku → t_cambio hacia ese sku en esta línea
        t_cambio_de = {it["sku"]: float(it["t_cambio_hrs"]) for it in items}
        skus = list(t_cambio_de.keys())

        for sku_a in skus:
            for sku_b in skus:
                if sku_a == sku_b:
                    tiempo = 0.0
                else:
                    tiempo = t_cambio_de[sku_b]  # tiempo de llegar a B
                upsert_setup_entry(sku_a, sku_b, linea, tiempo)
                total_filas += 1

        print(f"  {linea}: {len(skus)} SKUs → {len(skus)**2} filas")

    print(f"Total filas insertadas: {total_filas}")


# Llamar al final de migrate_params.main(), después de cargar mrp_sku_lineas:
if __name__ == "__main__":
    main()
    cargar_setup_matrix_inicial()
```

#### 3.3 — Ejecutar carga

```powershell
docker cp forecast\migrate_params.py traverso_forecast:/app/migrate_params.py
docker cp data\Traverso_Parametros_MRP.xlsx traverso_forecast:/app/data/Traverso_Parametros_MRP.xlsx
docker exec traverso_forecast rm -rf /app/__pycache__
docker exec traverso_forecast python3 /app/migrate_params.py
```

**Validación con queries directas:**
```powershell
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c @"
SELECT codigo, nombre, area, velocidad_u_hr, turnos_dia, horas_turno, dias_semana
FROM mrp_lineas
ORDER BY codigo;
"@

docker exec traverso_mrp_db psql -U mrp_user -d mrp -c @"
SELECT sku, descripcion, tipo, lead_time_sem, ss_dias, batch_min_u, cap_bodega_u, linea_preferida
FROM mrp_sku_params
ORDER BY tipo, sku;
"@

docker exec traverso_mrp_db psql -U mrp_user -d mrp -c @"
SELECT sku, linea, t_cambio_hrs, factor_velocidad, preferida
FROM mrp_sku_lineas
ORDER BY linea, sku;
"@

docker exec traverso_mrp_db psql -U mrp_user -d mrp -c @"
SELECT linea, COUNT(*) as filas, SUM(CASE WHEN sku_desde=sku_hasta THEN 1 ELSE 0 END) as auto
FROM mrp_setup_matrix
GROUP BY linea
ORDER BY linea;
"@

# Esperado (con 8 SKUs PRODUCCION):
#   L1Pet LV  → 5 SKUs → 25 filas (5 auto)
#   L1Pet A   → 1 SKU  → 1 fila  (1 auto)
#   Sachetera → 2 SKUs → 4 filas (2 auto)
#   TOTAL: 30 filas, 8 auto
```

**Verificación esperada:**
- 3 líneas en `mrp_lineas`: `Sachetera`, `L1Pet LV`, `L1Pet A`. Velocidades: 1055.55, 12222.22, 9444.44.
- 10 SKUs en `mrp_sku_params`: 8 PRODUCCION + 2 IMPORTACION (sopa, kikkoman).
- 8 filas en `mrp_sku_lineas` (los 8 PRODUCCION) con factor_velocidad correcto.
- 30 filas en `mrp_setup_matrix` distribuidas como arriba.

**Commit:**
```powershell
git add forecast/migrate_params.py data/Traverso_Parametros_MRP.xlsx
# (el backup _V3 que dejaste en data/ NO se commitea — agregar a .gitignore si todavía no)
git commit -m "chore(params): cargar parámetros V4 y matriz de setups inicial simétrica"
```

---

### Validación post-carga (paso obligatorio antes del último commit)

#### V1 — Generar plan con horizonte 13 + métricas

```powershell
[System.IO.File]::WriteAllText("$PWD\body.json", '{"horizonte_semanas": 13, "optimizar": true}')
curl.exe -X POST http://localhost:8000/plan -H "Content-Type: application/json" --data "@body.json" -o tests/fixtures/v1.3_post_v4_metrics.json -s -w "Status: %{http_code} | %{time_total}s`n"

python tests/fixtures/extract_metrics.py tests/fixtures/v1.3_post_v4_metrics.json > tests/fixtures/v1.3_post_v4_metrics.txt
Get-Content tests/fixtures/v1.3_post_v4_metrics.txt
```

#### V2 — Comparar con baseline F1

Abrir lado a lado:
- `tests/fixtures/v1.2_baseline_metrics.txt` (ya en repo, baseline F1)
- `tests/fixtures/v1.3_post_v4_metrics.txt` (recién generado)

**Métricas clave a comparar:**

| Métrica | F1 baseline (esperado) | Post-V4 (a observar) |
|---|---|---|
| `status` | OPTIMAL | OPTIMAL o FEASIBLE — ambos OK |
| `solver_time_sec` | ~6 s | Puede subir a 10-30 s. Si >60 s, investigar. |
| `ofts_produccion` | 268 | Va a cambiar — esperar diferencia significativa |
| `ofts_con_paga_setup` | 113 | Va a cambiar |
| `max SKUs/día/línea` | 4 | Probablemente 1-2 (asignación 1-a-1) |

**Diferencias esperadas (NO son bugs):**

- **Más alertas BAJO_SS y EXCESO_BODEGA simultáneas**, especialmente en Mostaza/Ketchup. Razón: cap_bodega 95.000 + ss_dias 15 + Sachetera 7600 u/día efectivo deja muy poco margen entre SS y cap.
- **Uso de Sachetera cerca del 100%** o saturada, vs ~20% antes.
- **Menos OFTs por día** porque hay menos SKUs por línea.
- **Setups menos relevantes** (asignación 1-a-1 → poca consolidación posible).

**Si aparece alguna de estas señales rojas, parar y discutir:**

- `status = INFEASIBLE` → la matriz de parámetros tiene un conflicto duro. Revisar SS vs cap_bodega.
- `solver_time_sec > 60` → el problema se volvió combinatoriamente más difícil de lo esperado. Investigar.
- Errores HTTP 500 en `/plan` → bug en código (probablemente migrate_params no llenó algo correctamente).

#### V3 — Validación visual en dashboard

```powershell
# Si no se reinició por algún motivo:
docker compose restart dashboard
# Esperar 30 seg
Start-Sleep 30
```

Abrir `http://localhost:3000` y verificar:

- **Plan de Producción**: tabla se renderiza, OFTs visibles. Las columnas de Línea muestran los nuevos códigos (`Sachetera`, `L1Pet LV`, `L1Pet A`) — **NO** los viejos (L001, L002, S001, S002).
- **Detalle Producción**: las 3 columnas de línea son las nuevas. Si aparece una columna fantasma con código viejo, hay hardcoding en frontend que hay que cazar.
- **Stock por SKU**: gráficos renderizan, proyecciones razonables.
- **Forecast**: sin cambios funcionales, debe seguir funcionando.

**Si hay hardcoding de códigos viejos en frontend** (probable que aparezca en alguna parte):

```powershell
# Buscar en frontend
Select-String -Path "dashboard\src\**\*.jsx","dashboard\src\**\*.js" -Pattern "L001|L002|S001|S002|Líquidos 1|Líquidos 2|Salsas 1|Salsas 2"
```

Si aparece, lo arreglamos en Commit 4 abajo.

---

### Commit 4 (CONDICIONAL) — `fix(frontend): actualizar referencias hardcodeadas a códigos de línea`

**Solo aplicar si la búsqueda de arriba devuelve resultados.**

Reemplazar las constantes viejas por las nuevas:
- `L001` → `L1Pet LV` (líquidos vinagrera)
- `L002` → `L1Pet A` (líquidos vespucio)
- `S001` → `Sachetera`
- `S002` → no aparece más, eliminar referencia o reemplazar por nada

```powershell
git add dashboard/src/...
git commit -m "fix(frontend): actualizar referencias hardcodeadas a códigos de línea"
```

---

## Generar snapshot técnico de la sesión

Crear `docs/ESTADO_TECNICO_PROYECTO_03-05-26.md` o `04-05-26.md` (según día) con:

- Resumen de los 3-4 commits del día.
- Métricas comparativas baseline F1 vs post-V4.
- Observaciones para discutir con Gerente de Producción (Sachetera ajustada, factor_velocidad doble interpretación, etc.).
- Próximo paso: F2 (sequencer.py).

---

## Decisión final del bloque: hacer push

```powershell
git log --oneline -5  # Verificar 3-4 commits limpios
git push origin feature/v1.3-cascada
```

A partir de aquí, F2 puede arrancar sobre base sólida.

---

## Si algo se rompe sin solución clara

```powershell
git checkout v1.2-piloto
docker compose down
docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast

# Restaurar BD desde backup
docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < backup_pre_v4_<timestamp>.sql
```

---

## Frase de arranque sugerida para Claude Code

> Hola. Tengo un plan completo de carga de parámetros V4 + creación de matriz de setups, ya consensuado en chat web. Lee `PLAN_CARGA_V4_Y_SETUP_MATRIX.md` que dejé en la raíz del repo. Después confírmame: (1) qué entendiste, (2) si las pre-condiciones se cumplen (rama correcta, working tree limpio, contenedores arriba), (3) en qué orden vamos a hacer los 3 commits funcionales (más el commit condicional 4 si aparece hardcoding en frontend). Antes de tocar nada, hacemos el backup de BD del Paso 0.

---

## Observaciones que vale la pena registrar antes de F2

Estas son cosas que ya sabemos van a aparecer en la validación post-carga. **No bloquean** la carga, pero conviene tenerlas escritas para discutir con el Gerente de Producción en algún momento (probablemente la sesión de mayo de validación operativa que ya está en el Gantt).

### O1 — Sachetera muy ajustada
- Velocidad efectiva Mostaza/Ketchup ≈ 844 u/hr (factor 0.8 × 1056 nominal).
- En 9 hrs/día: ~7600 unidades/día.
- `cap_bodega` 95.000 + `ss_dias` 15 → SS estimado del orden de 90.000 u (al borde de cap_bodega).
- Casi seguro vamos a ver alertas `BAJO_SS` y `EXCESO_BODEGA` simultáneamente para estos dos SKUs.
- Pregunta para el Gerente: ¿el `ss_dias=15` es realista para SKUs con cap_bodega tan ajustada, o es heredado del Excel viejo y conviene bajarlo a 7-10 días?

### O2 — Doble interpretación posible del factor_velocidad
- Las velocidades nuevas en LINEAS_PRODUCCION ya bajaron respecto a la versión anterior (especialmente Sachetera de 3000 a 1055).
- El factor_velocidad 0.8 de Mostaza/Ketchup en Sachetera se aplica multiplicativamente sobre esa velocidad ya reducida.
- ¿Es la intención (los SKUs "factor 0.8" son **además** más lentos que la velocidad promedio de la línea), o las velocidades nuevas ya incorporan la merma y el factor 0.8 está siendo contado dos veces?
- Pregunta para el Gerente.

### O3 — Asignación 1-a-1 limita la validación de F2
- Hoy cada línea tiene 1 SKU (excepto L1Pet LV con 5 vinagres + jugo limón 30x500).
- F2 (sequencing intra-día) va a tener trabajo solo en L1Pet LV. En L1Pet A y Sachetera será trivial.
- Es la línea preferida que maneja muchas decisiones, lo cual es OK pero conviene saber que el "test de F2" será mayoritariamente sobre L1Pet LV.

### O4 — La matriz de setups es uniforme dentro de cada línea
- Todos los `t_cambio_hrs` en SKU_LINEA son 0.5 (excepto IMPORTADOS que son 0).
- Por lo tanto la matriz de setups inicial va a tener todos los pares iguales a 0.5 dentro de cada línea.
- F2 con matriz uniforme no va a "preferir" un orden por razones de setup. Va a ordenar por demanda, capacidad y SS.
- Cuando llegue la matriz real (con valores diferenciados por par), F2 va a empezar a optimizar de verdad.
- **Esto NO es un bug** — es por construcción, mientras no haya datos reales.

---

*Plan generado el domingo 03/05/2026 para sesión de Claude Code el lunes 04/05/2026.*
*Sobre base estable: tag `v1.2-piloto`, branch `feature/v1.3-cascada` con F1 cerrada.*
