# CLAUDE.md — Onboarding para Claude Code

> **Lee este archivo primero.** Contiene todo lo que necesitas saber para arrancar productivo en este repo.

---

## Qué es este proyecto

**Traverso S.A.** es una empresa chilena de alimentos (vinagres, salsas, jugos limón, sopas). Este repo implementa un **Sistema de Planificación de Producción asistido por IA** que sustituye un proceso manual basado en Excel.

El sistema decide:
- **Qué** producir (qué SKUs requieren reposición).
- **Cuándo** producir (fechas de lanzamiento al día).
- **En qué línea** (asignación entre 5 líneas con velocidades distintas).
- **En qué orden** (a partir de v1.3 — secuenciamiento intra-día, parcialmente implementado).

**Estado actual** (al 09/05/2026): piloto operativo con **76 SKUs activos** sobre **5 líneas**. Sistema desplegado en servidor interno (Ubuntu 26.04 LTS) accesible al equipo en `http://180.1.1.18:3000`. Pruebas con equipo de producción inician **15/05/2026**.

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

**Todo corre en Docker Compose** con tres contenedores:
- `traverso_forecast` (FastAPI + OR-Tools + Prophet + CmdStan)
- `traverso_dashboard` (React)
- `traverso_mrp_db` (PostgreSQL 16)
- SQL Server externo `180.2.1.16:1433` BD `DBTraversoV2` (datos ERP, solo lectura)

**Despliegue**: servidor Ubuntu 26.04 (180.1.1.18) con backup nightly automático en `/home/ubuntu/backups/` (rotación 7 días, cron 02:00 AM).

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
  Dockerfile                     # incluye build-essential, install_cmdstan, sin --reload

dashboard/src/                   # Frontend React
  App.js                         # estado global, llamada única a /plan
  components/
    StockProyeccion.jsx          # ~571 líneas
    DetalleProduccion.jsx        # ~646 líneas — grid diario por línea
    (Plan de Producción está dentro de App.js)

forecast/data/                   # ★ EXCLUIDO de git (.gitignore)
  Traverso_Parametros_MRP.xlsx   # carga inicial (PostgreSQL es fuente de verdad)
  stock_actual.csv               # snapshot stock desde SQL Server (refresh manual)

docs/
  v1.3_DISENO_ARQUITECTURA.md    # ★ LÉELO — decisiones de diseño v1.3
  GUIA_USUARIO.md                # guía para equipo durante el piloto
  ESTADO_TECNICO_PROYECTO_*.md   # snapshots por sesión (★ último: 09-05-26)

migrate_*.sql                    # scripts SQL aplicados
docker-compose.yml               # con `command:` override sin --reload
```

---

## Reglas de oro de este entorno

### 1. Después de editar archivos `.py` en `forecast/`

```bash
# Sincronizar al contenedor
docker cp forecast/optimizer.py traverso_forecast:/app/optimizer.py

# Limpiar bytecode viejo (¡crítico, ya nos ha mordido varias veces!)
docker exec traverso_forecast rm -rf /app/__pycache__

# Reiniciar
docker compose restart forecast
```

**Por qué importa**: Python a veces carga el `.pyc` de `__pycache__` aunque hayas actualizado el `.py`. Esto causó horas de debugging "fantasma" en sesiones anteriores. Siempre limpiar caché tras cambios.

### 2. Después de editar archivos `.jsx` en `dashboard/src/`

```bash
docker cp dashboard/src/App.js traverso_dashboard:/app/src/App.js
docker compose restart dashboard
```

### 3. Después de `docker compose up -d --build` desde cero

Con el `Dockerfile` actualizado del 08/05, **todas las dependencias se instalan al build** (incluyendo CmdStan, OR-Tools, cmdstanpy<1.3.0). Tarda 15-25 min pero queda funcional sin intervención manual extra.

Tras un build limpio, además del compose-up:
1. Crear tabla `mrp_setup_matrix` (deuda V6.9): `docker exec -i traverso_mrp_db psql -U mrp_user -d mrp < migrate_v1.3_setup_matrix.sql`
2. Importar Excel: `curl -X POST http://localhost:8000/params/importar-excel`
3. Refresh stock: `curl -X POST http://localhost:8000/stock/refresh`

### 4. PowerShell tiene limitaciones

| Problema | Solución |
|---|---|
| No soporta heredocs `<< 'EOF'` | Usar `[System.IO.File]::WriteAllText()` o trabajar en SSH |
| `Out-File` agrega BOM, rompe JSON | Usar `[System.IO.File]::WriteAllText()` |
| Comillas escapadas en `curl -d "{\"k\":\"v\"}"` fallan | Usar `--data "@body.json"` con archivo |
| Path con espacios en scp/ssh | Comillar con doble: `"C:\Users\Pavilion Aero\..."` |

### 5. PostgreSQL: queries directas

```bash
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "SELECT * FROM mrp_sku_lineas;"
docker exec traverso_mrp_db psql -U mrp_user -d mrp -c "\d mrp_sku_params"
```

### 6. Verificar contenido en contenedor (sin caer en pipe `head` en PowerShell)

```bash
docker exec traverso_forecast python3 -c "
with open('/app/optimizer.py') as f:
    for i, l in enumerate(f, 1):
        if 'palabra_clave' in l:
            print(f'L{i}: {l.rstrip()}')
"
```

### 7. ★ Excel canónico vive FUERA del repo

`forecast/data/` está en `.gitignore`. El Excel `Traverso_Parametros_MRP.xlsx` se mantiene en OneDrive del usuario:

```
C:\Users\Pavilion Aero\OneDrive - Traverso S.A\Proyectos\Planificación de producción\traverso-pilot\traverso-pilot-git\forecast\data\Traverso_Parametros_MRP.xlsx
```

Para reimportar, primero `scp` al servidor, después `POST /params/importar-excel`.

---

## Modelo de datos clave

### Líneas de producción (al 09/05/2026)

| Código (PK) | Velocidad u/h | Cap día (1×9h) | Cap sem (5d) | SKUs activos |
|---|---|---|---|---|
| **L1Pet LV** | 12.222 | 110.000 | 550.000 | 32 |
| **L1Pet A** | 9.445 | 85.000 | 425.000 | 13 |
| **Sachetera** | 1.056 | 9.500 | 47.500 | 3 |
| **Doypack** | (definir) | (definir) | (definir) | 21 |
| **Doypack 4** | (definir) | (definir) | (definir) | 6 |

⚠️ **PK case-sensitive**: usar `L1Pet LV` (capitalización exacta), no `L1PET LV`.

### Numeración de OFs (cambiará en F3 de v1.3)

- **Definitivas (aprobadas)**: `OF-YYYY-NNNNN` — correlativo PostgreSQL en `mrp_contador_of`.
- **Tentativas (sugeridas por optimizador)**: `OFT-YYYY-NNNNN`.
- **Asignación de número**: ocurre **después** del optimizador, en `main.py`.
- **Cambio en F3** (post-piloto): hoy se agrupa por `(sku, semana_emision)`. Va a cambiar a `(sku, fecha_lanzamiento, linea)`.

### Tablas BD (PostgreSQL `mrp_db`)

```
mrp_lineas            5 filas
mrp_sku_params        77 filas (76 activos + 1 inactivo)
mrp_sku_lineas        80 (asignaciones SKU↔línea con preferida + alt)
mrp_setup_matrix      1.834 pares
mrp_ordenes           dinámica (OFTs y OFs)
mrp_aprobaciones      historial de cambios de estado
mrp_contador_of       correlativo
```

⚠️ **`mrp_setup_matrix` se crea con script manual** (`migrate_v1.3_setup_matrix.sql`), NO con `crear_tablas_params()`. Es la deuda V6.9.

---

## SKUs del piloto (76 activos al 09/05/2026)

77 cargados — 1 inactivo (`251010175 SALSA BARBECUE TRAVERSO 12X500 DOYPACK`, sin ventas en SQL Server).

**Distribución por línea preferida**:
- L1Pet LV: 32 SKUs (vinagres + jugos 30x500 PET, mayormente)
- Doypack: 21 SKUs (salsas formato bolsa)
- L1Pet A: 13 SKUs (formatos 1L principalmente)
- Doypack 4: 6 SKUs (salsas Doypack 12x1000)
- Sachetera: 3 SKUs (salsas en sachets)
- Sin línea (IMPORTACION): 2 SKUs (`410010185 Sopas`, `500170180 Kikkoman`)

**Hallazgo del 09/05**: 8 SKUs marca privada 30x500 PET (Tottus, Cuisine&Co, Frescolim) tenían `cap_bodega_u = 14.000` insuficiente; subido temporalmente a **140.000 u** (pendiente validar con Gerente al volver).

---

## Reglas de negocio activas

Listado completo y autoritativo en `docs/v1.3_DISENO_ARQUITECTURA.md` §3. Resumen:

1. **OF nunca en pasado**: `fem = max(necesidad - lead_time, hoy)`.
2. **Auto-rechazo OFs vencidas**: aprobadas con `fecha_entrada ≤ hoy` no se inyectan.
3. **OF ≤ capacidad diaria** (con factor_velocidad y descontando setup).
4. **Lead time**: `fecha_entrada = lanzamiento + round(lead_time × 7) días`.
5. **Setup primer día de corrida** (consecutivos del mismo SKU no pagan en v1.2).
6. **factor_velocidad**: SKU con factor 0.8 consume 1/0.8 = 1.25× más capacidad.
7. **SS dinámico diario**: `SS = demanda_diaria × ss_dias`.
8. **Solo PRODUCCION al optimizador**, IMPORTACION sigue MRP clásico.
9. **OFs no atraviesan medianoche** (v1.3, R1).
10. **N_max = 4 SKUs/día/línea** (v1.3, R12).
11. **Stock_proyectado <= cap_bodega_u** (restricción dura — si stock_inicial ya viola, INFEASIBLE).
12. **Primer SKU del día sin penalización de setup** (R12 implementada en commit `4db4c76`).

---

## Comportamientos del optimizador a tener presentes

⚠️ **Hoy el optimizador NO tolera estos casos** (los devuelve como `INFEASIBLE`):

1. **SKU activo sin forecast** (sin ventas en SQL Server). Solución hoy: marcar `activo=false` en BD.
2. **SKU con `stock_inicial > cap_bodega_u`**. Solución hoy: aumentar `cap_bodega_u` en Excel.
3. **SKU activo sin `linea_preferida`** en `mrp_sku_params` (aunque tenga la línea en `mrp_sku_lineas`). Solución hoy: UPDATE manual o llenar columna en Excel.

Las **deudas V6.11 y V6.12-mini** (planificadas para semana del 12-14/05) son fixes defensivos para que estos casos no rompan el plan completo.

---

## Fase activa: post-ampliación a 76 SKUs (semana 12-14/05)

**Estamos en**: estabilización pre-vacaciones del usuario (15/05–29/05). Sistema en servidor con 76 SKUs operativo. Lista de tareas pre-vacaciones:

### Lunes 12/05
1. **V6.14 — Bug dashboard `Stock 0`** (prioridad #1, 2-3h).
2. **Persistir UPDATEs en Excel** + commit/push (30 min).
3. **V6.11 — filtrar SKUs sin forecast** (1h).
4. **V6.12-mini — filtrar stock > cap_bodega** (1h).
5. Smoke test final (30 min).

### Martes 13/05
1. Manual gráfico con screenshots (lenguaje neutro chileno) — 3-4h.

### Miércoles 14/05
1. PDF de avance v8 — 1h.
2. Comunicación al equipo arranque del 15/05 — 30 min.

### Jueves 15/05
Buffer. Ideal: nada planificado (vacaciones inician).

---

## Tag de retorno seguro

Si algo se rompe sin solución clara:

```bash
# Restaurar BD desde backup
docker exec -i traverso_mrp_db psql -U mrp_user -d mrp \
  < /home/ubuntu/backups/mrp_db_20260509_160359.sql

# O retornar al tag estable de código
git checkout v1.2-piloto
docker compose down
docker compose up -d --build  # ~25 min
```

---

## Convenciones de código

- **Python**: stdlib + FastAPI + Pydantic + SQLAlchemy + ortools + Prophet. Funciones puras donde sea posible.
- **JavaScript**: React funcional + hooks. No Redux. Estado global mínimo en `App.js`.
- **Comentarios en español** son OK (el equipo es chileno). Identificadores en inglés o español, lo que sea más natural.
- **No agregar dependencias** sin discutirlo. Cualquier nueva pip/npm va vía conversación.
- **Documentación al equipo en español neutro** (no argentino, no chilenismos fuertes — debe leer bien para cualquier hispanohablante).

---

## Cómo trabajamos en este repo

- **Decisiones grandes (arquitectura)**: chat web Claude, registramos en `docs/v1.3_DISENO_ARQUITECTURA.md`.
- **Implementación**: Claude Code (terminal en servidor o PC).
- **Documentación de avance al negocio**: chat web (PDFs ejecutivos).
- **Snapshots técnicos**: al final de cada sesión grande, generar `ESTADO_TECNICO_PROYECTO_<fecha>.md` en `docs/`.

Cuando termines una sesión productiva:
1. Verificar que el cambio funciona (correr `/plan`, ver logs).
2. Hacer commit (no es automático).
3. Si fue un hito, sugerir un tag git.
4. Actualizar `docs/v1.3_DISENO_ARQUITECTURA.md` o crear nuevo `ESTADO_TECNICO_<fecha>.md`.

---

## Primera invocación recomendada en próxima sesión

> Lee `CLAUDE.md` y `docs/ESTADO_TECNICO_PROYECTO_09-05-26.md`. Confírmame qué entiendes del estado actual y arranquemos por la deuda V6.14 (bug del dashboard mostrando stock=0).

---

**Tag estable de retorno**: `v1.2-piloto`. **Commit más reciente** (al 09/05/2026): `4fbe0ed` (08/05).
