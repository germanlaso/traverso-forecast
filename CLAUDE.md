# CLAUDE.md — Onboarding para Claude Code

> **Lee este archivo primero.** Contiene todo lo que necesitas saber para arrancar productivo en este repo.

---

## Qué es este proyecto

**Traverso S.A.** es una empresa chilena de alimentos (vinagres, salsas, jugos limón, sopas). Este repo implementa un **Sistema de Planificación de Producción asistido por IA** que sustituye un proceso manual basado en Excel.

El sistema decide:
- **Qué** producir (qué SKUs requieren reposición).
- **Cuándo** producir (fechas de lanzamiento al día).
- **En qué línea** (asignación entre 4 líneas con velocidades distintas).
- **En qué orden** (a partir de v1.3 — secuenciamiento intra-día).

**Estado actual**: piloto operativo con 10 SKUs comerciales sobre 4 líneas. Próximo escalamiento: 471 SKUs activos.

**Versión activa**: v1.2-piloto (tag estable). En desarrollo: **v1.3** (arquitectura cascada Lot Sizing → Sequencing).

---

## Stack y arquitectura

```
React Dashboard (puerto 3000)
  ├── Forecast de Demanda (Prophet)
  ├── Plan de Producción (MRP + OR-Tools)
  ├── Stock por SKU (proyección)
  └── Detalle Producción (grid diario por línea)
        ↓
FastAPI (puerto 8000)
        ↓
  ┌──────┬──────────┬──────────┬────────┬──────────────┐
  │ MRP  │ OR-Tools │ Prophet  │  SQL   │  PostgreSQL  │
  │      │  CP-SAT  │ forecast │ Server │   mrp_db     │
  └──────┴──────────┴──────────┴────────┴──────────────┘
```

**Todo corre en Docker Compose** con tres contenedores principales:
- `traverso_forecast` (FastAPI + OR-Tools + Prophet)
- `traverso_dashboard` (React)
- `traverso_mrp_db` (PostgreSQL)
- SQL Server externo (datos ERP, solo lectura)

---

## Estructura del repo

```
forecast/                        # Backend FastAPI
  main.py                        # ~735 líneas — endpoints API
  mrp.py                         # ~600 líneas — motor MRP clásico
  optimizer.py                   # ~1.100 líneas — OR-Tools CP-SAT (Nivel 1)
  sequencer.py                   # ★ A CREAR EN F2 — Nivel 2 sequencing
  calendario.py                  # feriados Chile + helpers días hábiles
  db_mrp.py                      # ORM PostgreSQL
  db.py                          # SQL Server (stock, ventas)
  stock.py                       # integración stock FEFO
  ordenes.py                     # gestión OFs (aprobación, PDF)
  forecaster.py                  # wrapper Prophet
  migrate_params.py              # carga inicial Excel → BD
  requirements.txt

dashboard/src/                   # Frontend React
  App.js                         # estado global, llamada única a /plan
  components/
    StockProyeccion.jsx          # ~571 líneas
    DetalleProduccion.jsx        # ~646 líneas — grid diario por línea
    (Plan de Producción está dentro de App.js)

data/
  Traverso_Parametros_MRP.xlsx   # carga inicial (PostgreSQL es fuente de verdad)

docs/
  v1.3_DISENO_ARQUITECTURA.md    # ★ LÉELO — decisiones de diseño v1.3
  ESTADO_TECNICO_PROYECTO_*.md   # snapshots por sesión

migrate_*.sql                    # scripts SQL aplicados
docker-compose.yml
```

---

## Reglas de oro de este entorno

### 1. Después de editar archivos `.py` en `forecast/`

```powershell
# Sincronizar al contenedor
docker cp forecast\optimizer.py traverso_forecast:/app/optimizer.py

# Limpiar bytecode viejo (¡crítico, ya nos ha mordido varias veces!)
docker exec traverso_forecast rm -rf /app/__pycache__

# Reiniciar
docker compose restart forecast
```

**Por qué importa**: Python a veces carga el `.pyc` de `__pycache__` aunque hayas actualizado el `.py`. Esto causó horas de debugging "fantasma" en sesiones anteriores. Siempre limpiar caché tras cambios.

### 2. Después de editar archivos `.jsx` en `dashboard/src/`

```powershell
# Sincronizar al contenedor
docker cp dashboard\src\App.js traverso_dashboard:/app/src/App.js

# El hot-reload de React a veces no compila cambios grandes — forzar:
(Get-Content dashboard\src\App.js) | Set-Content dashboard\src\App.js
docker compose restart dashboard
```

### 3. Después de `docker compose up -d` desde cero

Algunas dependencias se desinstalan al recrear el contenedor (bug conocido). Reinstalar:

```powershell
docker exec traverso_forecast pip install reportlab==4.1.0 --break-system-packages -q
docker exec traverso_forecast pip install ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
```

Pendiente arreglar `requirements.txt` con pins (tarea menor v1.3).

### 4. PowerShell tiene limitaciones que ya nos han mordido

| Problema | Solución |
|---|---|
| No soporta heredocs `<< 'EOF'` | Usar `[System.IO.File]::WriteAllText()` |
| `Out-File` agrega BOM, rompe JSON | Usar `[System.IO.File]::WriteAllText()` para JSON |
| Comillas escapadas en `curl -d "{\"k\":\"v\"}"` fallan | Usar `--data "@body.json"` con archivo |
| No tiene `head` | `Select-Object -First N` o evitar pipe |

Ejemplo de invocación correcta a `/plan`:

```powershell
[System.IO.File]::WriteAllText("$PWD\body.json", '{"horizonte_semanas": 13, "optimizar": true}')
curl.exe -X POST http://localhost:8000/plan -H "Content-Type: application/json" --data "@body.json" -o plan.json -s -w "Status: %{http_code} | %{time_total}s`n"
```

### 5. PostgreSQL: queries directas

```powershell
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT * FROM mrp_sku_lineas;"
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "\d mrp_aprobaciones"
```

### 6. Verificar contenido en contenedor (sin caer en pipe `head`)

```powershell
docker exec traverso_forecast python3 -c @"
with open('/app/optimizer.py') as f:
    for i, l in enumerate(f, 1):
        if 'palabra_clave' in l:
            print(f'L{i}: {l.rstrip()}')
"@
```

---

## Modelo de datos clave

### Numeración de OFs (cambiará en F3 de v1.3)

- **Definitivas (aprobadas)**: `OF-YYYY-NNNNN` — correlativo PostgreSQL en `mrp_contador_of`.
- **Tentativas (sugeridas por optimizador)**: `OFT-YYYY-NNNNN`.
- **Asignación de número**: ocurre **después** del optimizador, en `main.py`.
- **Cambio en F3**: hoy se agrupa por `(sku, semana_emision)`. Va a cambiar a `(sku, fecha_lanzamiento, linea)` para que cada día = una OF distinta. Ver `docs/v1.3_DISENO_ARQUITECTURA.md` §4.3.

### Capacidades de líneas (PostgreSQL `mrp_lineas`)

| Código | Línea | Velocidad | Cap. día | Cap. semana |
|--------|-------|-----------|----------|-------------|
| L001 | Líquidos 1 | 12.000 u/hr | 96.000 u | 480.000 u |
| L002 | Líquidos 2 | 10.000 u/hr | 80.000 u | 400.000 u |
| S001 | Salsas 1 | 3.000 u/hr | 24.000 u | 120.000 u |
| S002 | Salsas 2 | 3.000 u/hr | 24.000 u | 120.000 u |

Asume `turnos_dia=1`, `horas_turno=8`, `dias_semana=5`.

### Tabla nueva en v1.3 (F4)

```sql
CREATE TABLE mrp_setup_matrix (
    sku_desde       VARCHAR(30) NOT NULL,
    sku_hasta       VARCHAR(30) NOT NULL,
    linea           VARCHAR(20) NOT NULL,
    tiempo_horas    FLOAT NOT NULL,
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (sku_desde, sku_hasta, linea)
);
```

---

## SKUs del piloto (10)

### PRODUCCION (8 — entran al optimizador)
- 113010290 Vinagre Manzana 30x500 — L001 pref / L002 alt
- 111010290 Vinagre Blanco 30x500 — L002 pref / L001 alt
- 112010290 Vinagre Rosado 30x500 — L002 pref / L001 alt
- 114010290 Vinagre Incoloro 30x500 — L001 pref
- 121010210 Jugo Limón 20x1000 (1L) — L001 pref, **factor 0.8**
- 121010290 Jugo Limón 30x500 — L001 pref
- 250010105 Ketchup 10x1000 BOLSA — S002 pref / S001 alt, factor 0.8
- 260010105 Mostaza 10x1000 BOLSA — S001 pref / S002 alt, factor 0.8

### IMPORTACION (2 — NO entran al optimizador, solo MRP clásico)
- 410010185 Sopa Inst. Carne 12x65 POTE
- 500170180 Salsa Soya Kikkoman 12x591

---

## Reglas de negocio activas

Listado completo y autoritativo en `docs/v1.3_DISENO_ARQUITECTURA.md` §3. Resumen:

1. **OF nunca en pasado**: `fem = max(necesidad - lead_time, hoy)`.
2. **Auto-rechazo OFs vencidas**: aprobadas con `fecha_entrada ≤ hoy` no se inyectan.
3. **OF ≤ capacidad diaria** (con factor_velocidad y descontando setup).
4. **Lead time**: `fecha_entrada = lanzamiento + round(lead_time × 7) días`.
5. **Setup primer día de corrida** (consecutivos del mismo SKU no pagan en v1.2; v1.3 lo refina con sequencing).
6. **factor_velocidad**: SKU con factor 0.8 consume 1/0.8 = 1.25× más capacidad.
7. **SS dinámico diario**: `SS = demanda_diaria × ss_dias`.
8. **Solo PRODUCCION al optimizador**, IMPORTACION sigue MRP clásico.
9. **OFs no atraviesan medianoche** (v1.3, R1).
10. **N_max = 4 SKUs/día/línea** (v1.3, R2).

---

## Fase activa: v1.3

**Estamos en**: arranque de v1.3 desde tag `v1.2-piloto`.

**Próximo paso (F1)**: ajustar `optimizer.py` (Nivel 1):
- Agregar restricción `Σ_k asig[d,k,l] ≤ 4` (N_max).
- Reducir o eliminar `W_SETUP = 200` (N2 lo hará mejor).
- Día 0 sin setup: `inicio[0] = 0` (R4).
- Mantener W_DEFICIT, W_EXCESO, W_ALT.

**Después**: F2 (crear `sequencer.py`), F3 (numeración por día), F4 (tabla matriz, paralelo), F6 (frontend), F5 (datos reales matriz cuando lleguen).

Detalle completo: `docs/v1.3_DISENO_ARQUITECTURA.md` §8.

---

## Tag de retorno seguro

Si algo se rompe sin solución clara durante v1.3:

```powershell
git checkout v1.2-piloto
docker compose down
docker compose up -d
docker exec traverso_forecast pip install reportlab==4.1.0 ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
docker exec traverso_forecast rm -rf /app/__pycache__
docker compose restart forecast
```

---

## Convenciones de código

- **Python**: stdlib + FastAPI + Pydantic + SQLAlchemy + ortools + Prophet. Funciones puras donde sea posible.
- **JavaScript**: React funcional + hooks. No Redux. Estado global mínimo en `App.js`.
- **Comentarios en español** son OK (el equipo es chileno). Identificadores en inglés o español, lo que sea más natural.
- **No agregar dependencias** sin discutirlo. Cualquier nueva pip/npm va vía conversación.
- **Tests**: hoy mínimos (proyecto piloto). En v1.3 podemos agregar tests específicos para `sequencer.py` (greenfield) — esto es bienvenido.

---

## Cómo trabajamos en este repo

- **Decisiones grandes (arquitectura)**: chat web Claude, registramos en `docs/v1.3_DISENO_ARQUITECTURA.md`.
- **Implementación**: Claude Code (este entorno).
- **Documentación de avance al negocio**: chat web (PDFs ejecutivos).
- **Snapshots técnicos**: al final de cada sesión grande, generar `ESTADO_TECNICO_PROYECTO_<fecha>.md` en `docs/`.

Cuando termines una sesión productiva en Claude Code, recuerda:
1. Verificar que el cambio funciona (correr `/plan`, ver logs).
2. Hacer commit (no es automático).
3. Si fue un hito, sugerir un tag git.
4. Actualizar `docs/v1.3_DISENO_ARQUITECTURA.md` o crear nuevo `ESTADO_TECNICO_<fecha>.md`.

---

## Primera invocación recomendada

Al iniciar `claude` en la raíz del repo, tu primer mensaje:

> Lee `CLAUDE.md` y `docs/v1.3_DISENO_ARQUITECTURA.md`. Confírmame qué entiendes del proyecto, del estado actual y de las decisiones de v1.3. Después arrancamos con F1: ajuste de Nivel 1 en `optimizer.py`.
