# CLAUDE.md — Onboarding para Claude Code

> **Lee este archivo primero.** Contiene todo lo que necesitas saber para arrancar productivo en este repo.

---

## Qué es este proyecto

**Traverso S.A.** es una empresa chilena de alimentos (vinagres, salsas, jugos limón, sopas). Este repo implementa un **Sistema de Planificación de Producción asistido por IA** que sustituye un proceso manual basado en Excel.

El sistema decide:
- **Qué** producir (qué SKUs requieren reposición).
- **Cuándo** producir (fechas de lanzamiento al día).
- **En qué línea** (asignación entre las líneas con velocidades distintas).
- **En qué orden** (a partir de v1.3 — secuenciamiento intra-día, en desarrollo).

**Estado actual**: piloto operativo con 18 SKUs (16 PRODUCCION + 2 IMPORTACION) sobre 3 líneas. Próximo escalamiento: 471 SKUs activos.

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
- SQL Server externo (datos ERP, solo lectura). Requiere VPN activa para `/plan` y `/stock/refresh`.

---

## Líneas de producción (datos verificados contra BD `mrp_lineas`)

> **Importante:** los nombres de líneas en este proyecto son los que aparecen abajo. Versiones viejas de los docs hablaban de `L001/L002/S001/S002` — esa nomenclatura quedó obsoleta. La fuente de verdad es la BD.

| Código | Área | Turnos | Hrs/turno | Días/sem | Velocidad (u/hr) | Cap/día (u) | Cap/sem (u) |
|---|---|---|---|---|---|---|---|
| **L1Pet LV** | LIQUIDOS/VINAGRERA | 1 | 9 | 5 | 12.223 | ~110.000 | ~550.000 |
| **L1Pet A** | LIQUIDOS/VESPUCIO | 1 | 9 | 5 | 9.445 | ~85.000 | ~425.000 |
| **Sachetera** | SALSAS/VESPUCIO | 1 | 9 | 5 | 1.056 | ~9.500 | ~47.500 |

**Tipografía:** capitalizada exactamente así (`L1Pet LV`, `L1Pet A`, `Sachetera`). NO en mayúsculas. La PK de `mrp_lineas.codigo` es case-sensitive y `mrp_sku_lineas.linea` es FK.

**Nota Sachetera:** `cap_dia ≈ batch_min = 9.500` para Mostaza/Ketchup/Salsa Barbecue. Margen cero por diseño operativo (decisión Gerente, no bug).

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
  data/
    Traverso_Parametros_MRP.xlsx # canonical (PostgreSQL es fuente de verdad)
  requirements.txt

dashboard/src/                   # Frontend React
  App.js                         # estado global, llamada única a /plan
  components/
    StockProyeccion.jsx          # ~571 líneas
    DetalleProduccion.jsx        # ~646 líneas — grid diario por línea
    (Plan de Producción está dentro de App.js)

docs/
  v1.3_DISENO_ARQUITECTURA.md    # ★ LÉELO — decisiones de diseño v1.3
  ESTADO_TECNICO_PROYECTO_*.md   # snapshots por sesión

migrate_*.sql                    # scripts SQL aplicados
docker-compose.yml
```

---

## SKUs del piloto (18 — datos verificados contra BD `mrp_sku_params`)

### PRODUCCION (16 — entran al optimizador)

| SKU | Descripción | Línea preferida | Alternativa |
|---|---|---|---|
| 111010290 | Vinagre Blanco 30x500 PET | L1Pet LV | — |
| 112010290 | Vinagre Rosado 30x500 PET | L1Pet LV | — |
| 113010290 | Vinagre Manzana 30x500 PET | L1Pet LV | — |
| 114010290 | Vinagre Incoloro 30x500 PET | L1Pet LV | — |
| 121010290 | Jugo Limón 30x500 PET | L1Pet LV | — |
| 121010210 | Jugo Limón 20x1000 PET (1L) | L1Pet LV | L1Pet A |
| 111010115 | Vinagre Blanco 12x1000 PET | L1Pet LV | L1Pet A |
| 112011115 | Vinagre Rosado Montaner 12x1000 PET | L1Pet LV | L1Pet A |
| 113010210 | Vinagre Manzana 20x1000 PET | L1Pet LV | L1Pet A |
| 114010115 | Vinagre Incoloro 12x1000 PET | L1Pet LV | L1Pet A |
| 141010160 | Salsa Soya 12x320 PET | L1Pet A | — |
| 141010210 | Salsa Soya 20x1000 PET | L1Pet A | — |
| 123010160 | Jugo Limón 60% 12x320 PET | L1Pet A | — |
| 250010105 | Ketchup 10x1000 BOLSA | Sachetera | — |
| 260010105 | Mostaza 10x1000 BOLSA | Sachetera | — |
| 251010105 | Salsa Barbecue 10x1000 BOLSA | Sachetera | — |

**Distribución**: L1Pet LV alcanza 10 SKUs (5 nativos + 5 con alt), L1Pet A alcanza 8 SKUs (3 nativos + 5 como alt), Sachetera 3 SKUs.

**factor_velocidad < 1.0**: SKUs ×12×1000 (más lentos en su línea), Salsa Soya 20x1000, Jugo Limón 20x1000. Detalle en `mrp_sku_lineas`.

### IMPORTACION (2 — NO entran al optimizador, solo MRP clásico)

- 410010185 Sopa Inst. Carne Traverso 12x65 POTE
- 500170180 Salsa Soya Kikkoman 12x591 VIDRIO

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

Algunas dependencias se desinstalan al recrear el contenedor (bug conocido). **Verificar primero, reinstalar solo si imports fallan**:

```powershell
docker exec traverso_forecast python3 -c "import reportlab, ortools, prophet; print('ok')"
# Si falla:
docker exec traverso_forecast pip install reportlab==4.1.0 --break-system-packages -q
docker exec traverso_forecast pip install ortools "numpy<2.0" "pandas<2.0" --break-system-packages -q --force-reinstall
```

Pendiente arreglar `requirements.txt` con pins (deuda V6).

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

### 5. Path mangling Git Bash con `docker exec`

Git Bash convierte rutas Unix a Windows automáticamente, lo que rompe rutas dentro del contenedor. Solución:

```bash
# MAL (Git Bash convierte /app/file → C:/Program Files/Git/app/file):
docker exec traverso_forecast cat /app/optimizer.py

# BIEN (doble slash inicial preserva la ruta):
docker exec traverso_forecast cat //app/optimizer.py

# O envolver en bash -c:
docker exec traverso_forecast bash -c 'cat /app/optimizer.py'
```

### 6. PostgreSQL: queries directas

```powershell
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT * FROM mrp_sku_lineas;"
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "\d mrp_aprobaciones"
```

### 7. Verificar contenido en contenedor (sin caer en pipe `head`)

```powershell
docker exec traverso_forecast python3 -c @"
with open('/app/optimizer.py') as f:
    for i, l in enumerate(f, 1):
        if 'palabra_clave' in l:
            print(f'L{i}: {l.rstrip()}')
"@
```

### 8. "Antes de Y, hacé X" es bloqueante hasta confirmación

Patrón observado: cuando el usuario indica "antes de Y, hacé X", la tendencia natural es saltar X y hacer Y directamente. **No hagas Y hasta tener X confirmado**, aunque parezca obvio. Si X no está claro, pregunta antes de avanzar.

### 9. Display Claude Code en archivos largos

Patrón observado en sesión 06/05: archivos creados con Write tool muestran líneas duplicadas en preview de aprobación, pero el archivo en disco está limpio. **Distribución observada: 8 apariciones, 7 falsas alarmas confirmadas con Read, 1 real (heredoc original).** Mitigación: si aparece duplicación en preview, hacer Read post-creación; el archivo correcto es el que está en disco. Es bug 100% display, no afecta runtime.

---

## Modelo de datos clave

### Numeración de OFs (cambiará en F3 de v1.3)

- **Definitivas (aprobadas)**: `OF-YYYY-NNNNN` — correlativo PostgreSQL en `mrp_contador_of`.
- **Tentativas (sugeridas por optimizador)**: `OFT-YYYY-NNNNN`.
- **Asignación de número**: ocurre **después** del optimizador, en `main.py`.
- **Cambio en F3**: hoy se agrupa por `(sku, semana_emision)`. Va a cambiar a `(sku, fecha_lanzamiento, linea)` para que cada día = una OF distinta. Ver `docs/v1.3_DISENO_ARQUITECTURA.md` §4.3.

### Tablas PostgreSQL principales

```sql
mrp_lineas         -- 3 líneas activas con capacidades
mrp_sku_params     -- 18 SKUs (16 PRODUCCION + 2 IMPORTACION)
mrp_sku_lineas     -- pares SKU↔línea con t_cambio_hrs y factor_velocidad
mrp_setup_matrix   -- ★ matriz dependiente del par (sku_desde, sku_hasta, linea)
mrp_ordenes        -- órdenes activas
mrp_aprobaciones   -- historial de versiones
mrp_contador_of    -- correlativo anual
```

### `mrp_setup_matrix` — estado actual

Tabla **ya existe** con datos dummy (no es F4 todavía completa, pero schema y migración inicial están hechos). Esquema:

```sql
sku_desde       VARCHAR(30) NOT NULL
sku_hasta       VARCHAR(30) NOT NULL
linea           VARCHAR(20) NOT NULL
tiempo_horas    DOUBLE PRECISION NOT NULL CHECK (tiempo_horas >= 0)
updated_at      TIMESTAMP DEFAULT NOW()
PRIMARY KEY (sku_desde, sku_hasta, linea)
```

**Datos al 07/05/2026 (pre-importación de los 8 SKUs nuevos):** 30 pares poblados, todos con `tiempo_horas = 0.5h` excepto los diagonales `(X,X) = 0`. Es la matriz dummy "predecesor anónimo" derivada de `mrp_sku_lineas.t_cambio_hrs`.

**Lo que falta para cerrar F4 completa** (ver doc de arquitectura §6):
- Endpoints CRUD: `GET / PUT / DELETE /params/setup-matrix/...`
- Endpoint de carga masiva: `POST /params/setup-matrix/importar`
- Función `regenerar_matriz_setup_dummy()` que repuebla la matriz desde `mrp_sku_lineas` (necesaria al agregar SKUs nuevos).
- Conexión real con N2 (sequencer) en F2.

---

## Reglas de negocio activas

Listado completo y autoritativo en `docs/v1.3_DISENO_ARQUITECTURA.md` §3. Resumen:

1. **OF nunca en pasado**: `fem = max(necesidad - lead_time, hoy)`.
2. **Auto-rechazo OFs vencidas**: aprobadas con `fecha_entrada ≤ hoy` no se inyectan.
3. **OF ≤ capacidad diaria** (con factor_velocidad y descontando setup).
4. **Lead time**: `fecha_entrada = lanzamiento + round(lead_time × 7) días`. Para PRODUCCION: `lead_time_sem = 0.15` ⇒ 1 día efectivo (regla operativa V5/D3). **Workaround V6 pendiente**: renombrar columna a `lead_time_dias` con valores enteros.
5. **factor_velocidad**: SKU con factor 0.8 consume 1/0.8 = 1.25× más capacidad efectiva.
6. **SS dinámico diario**: `SS = demanda_diaria × ss_dias`.
7. **Solo PRODUCCION al optimizador**, IMPORTACION sigue MRP clásico.
8. **OFs no atraviesan medianoche** (v1.3, R1).
9. **N_max = 4 SKUs/día/línea** (v1.3, R2 — aplicada en F1).
10. **Día 0 sin setup** (v1.3, R4 — aplicada en F1).
11. **Primer SKU del día sin setup** (v1.3, R12 — aplicada en V5):
    - Regla operativa del Gerente: la línea se prepara antes de cada jornada (limpieza/montaje extra-jornada).
    - Implementación: `W_INICIO_SIMBOLICO = 1` y restricción `Σ inicios_dl >= Σ asigs_dl - 1`.
    - Resultado: al menos N-1 SKUs/día pagan setup. El primero entra "limpio".

---

## Métricas: cuidado con interpretarlas

- **`alertas BAJO_SS adjuntas a OFTs`** NO es métrica monotónica de calidad. Puede SUBIR cuando el plan produce más reactivo (más OFTs lanzadas más cerca del vencimiento). El dashboard visual sigue siendo el último filtro.
- **`paga_setup count`** depende fuertemente del horizonte y de la regla R12. No comparar entre versiones sin normalizar contra la cota mínima `n_dias_con_produccion - n_lineas_con_produccion`.
- **`solver_time`** crece con N° SKUs y horizonte. Hoy h=13 con 10 SKUs ≈ 6s. Con 18 SKUs es de esperar 15-30s. Considerar timeout 120s para corridas largas.

---

## Fase activa: v1.3

**Estamos en**: V5 cerrado en backend. Sesión actual amplía piloto a 18 SKUs y alinea Excel a BD.

**Próximos pasos**:
- **Tarea actual** (chat web + Code, esta sesión): importar Excel V6 a BD, regenerar `mrp_setup_matrix` con los pares nuevos.
- **F2** (sequencer.py): Nivel 2 de la cascada. Variables de orden intra-día. Esperando matriz real del Gerente.
- **F3** (numeración por día): refactor para que cada día = una OF distinta.
- **F4** (matriz CRUD + endpoints): schema y datos dummy ya están. Falta endpoints + función `regenerar_matriz_setup_dummy()`.
- **F5** (cargar matriz real): cuando llegue del Gerente.
- **F6** (frontend orden intra-día).

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

Para volver al cierre de V5 (con ampliación a 18 SKUs): `git checkout feature/v1.3-cascada`.

---

## Convenciones de código

- **Python**: stdlib + FastAPI + Pydantic + SQLAlchemy + ortools + Prophet. Funciones puras donde sea posible.
- **JavaScript**: React funcional + hooks. No Redux. Estado global mínimo en `App.js`.
- **Comentarios en español** son OK (el equipo es chileno). Identificadores en inglés o español, lo que sea más natural.
- **No agregar dependencias** sin discutirlo. Cualquier nueva pip/npm va vía conversación.
- **Tests**: hoy mínimos (proyecto piloto). En v1.3 podemos agregar tests específicos para `sequencer.py` (greenfield) — esto es bienvenido.
- **Commits**: autor único `germanlaso`, sin `Co-Authored-By`. Mensajes en español.

---

## Cómo trabajamos en este repo

- **Decisiones grandes (arquitectura)**: chat web Claude, registramos en `docs/v1.3_DISENO_ARQUITECTURA.md`.
- **Implementación**: Claude Code (este entorno).
- **Documentación de avance al negocio**: chat web (PDFs ejecutivos).
- **Snapshots técnicos**: al final de cada sesión grande, generar `ESTADO_TECNICO_PROYECTO_<fecha>[-tarde|-noche].md` en `docs/`. Los snapshots históricos NO se editan — son fotos de un momento.

Cuando termines una sesión productiva en Claude Code, recuerda:
1. Verificar que el cambio funciona (correr `/plan`, ver logs).
2. Hacer commit (no es automático).
3. Si fue un hito, sugerir un tag git.
4. Actualizar `docs/v1.3_DISENO_ARQUITECTURA.md` o crear nuevo `ESTADO_TECNICO_<fecha>.md`.

---

## Primera invocación recomendada

Al iniciar `claude` en la raíz del repo, tu primer mensaje:

> Lee `CLAUDE.md` y `docs/v1.3_DISENO_ARQUITECTURA.md` y el snapshot más reciente en `docs/ESTADO_TECNICO_PROYECTO_*.md`. Confírmame qué entiendes del proyecto, del estado actual y de las decisiones de v1.3. Después arrancamos con la siguiente fase.
