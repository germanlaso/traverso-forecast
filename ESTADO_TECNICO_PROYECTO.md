# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.1 — Actualizado: 29/04/2026

---

## Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    TRAVERSO PILOT v1.1                       │
│                                                             │
│  React Dashboard (puerto 3000)                              │
│  ├── Forecast de Demanda (Prophet)                          │
│  ├── Plan de Producción (MRP + aprobaciones)                │
│  ├── Stock por SKU (proyección semanal)                     │
│  └── Detalle Producción (grid diario por línea)             │
│                        │                                    │
│                   FastAPI (puerto 8000)                     │
│                        │                                    │
│         ┌──────────────┼──────────────┐                     │
│         │              │              │                      │
│    SQL Server      PostgreSQL      Prophet                   │
│    (ventas)        (MRP, params)   (modelos)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Base de datos PostgreSQL (mrp_db)

### Tablas de órdenes
```sql
mrp_ordenes        -- órdenes activas (estado APROBADA/CANCELADA)
mrp_aprobaciones   -- historial de versiones de cada orden
mrp_contador_of    -- correlativo anual (OF-YYYY-NNNNN)
```

### Tablas de parámetros MRP
```sql
mrp_lineas         -- líneas de producción con capacidades
mrp_sku_params     -- parámetros por SKU (SS, lead time, batch, bodega)
mrp_sku_lineas     -- asignación SKU → línea (preferida/alternativa)
```

### Schema mrp_lineas
```sql
codigo          VARCHAR(20) PRIMARY KEY
nombre          VARCHAR(100)
area            VARCHAR(100)
turnos_dia      INTEGER     -- turnos por día
horas_turno     FLOAT       -- horas por turno
dias_semana     INTEGER     -- días hábiles por semana
velocidad_u_hr  FLOAT       -- unidades producidas por hora
activa          BOOLEAN
updated_at      TIMESTAMP
-- capacidad_u_semana = turnos_dia × horas_turno × dias_semana × velocidad_u_hr
```

### Schema mrp_sku_params
```sql
sku             VARCHAR(30) PRIMARY KEY
descripcion     VARCHAR(200)
categoria       VARCHAR(100)
tipo            VARCHAR(30)     -- PRODUCCION / IMPORTACION / MAQUILA
u_por_caja      INTEGER
lead_time_sem   FLOAT           -- semanas de lead time
ss_dias         INTEGER         -- días de stock de seguridad
batch_min_u     INTEGER         -- producción mínima en unidades
batch_mult_u    INTEGER         -- múltiplo de producción
cap_bodega_u    INTEGER         -- capacidad máxima bodega en unidades
t_cambio_hrs    FLOAT           -- horas de cambio entre SKUs en la línea
pct_dia_max     FLOAT           -- fracción máxima del día (default 1.0)
linea_preferida VARCHAR(20)     -- código de línea preferida
activo          BOOLEAN
updated_at      TIMESTAMP
```

### Numeración de órdenes
- **Definitivas**: `OF-YYYY-NNNNN` (aprobadas, correlativo en PostgreSQL)
- **Tentativas**: `OFT-YYYY-NNNNN` (sugeridas por MRP, sin aprobar)

---

## Endpoints API principales

### Plan de producción
```
POST /plan                    # Generar plan MRP completo
GET  /plan/params             # Parámetros MRP (SKUs + líneas)
```

### Órdenes
```
POST /ordenes/aprobar         # Aprobar/re-aprobar una orden
DELETE /ordenes/cancelar/{key} # Cancelar aprobación
GET  /ordenes/aprobadas       # Listar todas las aprobadas
GET  /ordenes/{numero_of}/pdf # Generar PDF de la orden
GET  /ordenes/numero-tentativo # Obtener próximo N° OFT
```

### Parámetros MRP (en BD)
```
GET  /params/lineas           # Listar líneas desde PostgreSQL
PUT  /params/lineas/{codigo}  # Actualizar parámetros de una línea
GET  /params/skus             # Listar parámetros SKU desde PostgreSQL
PUT  /params/skus/{sku}       # Actualizar parámetros de un SKU
POST /params/importar-excel   # Re-importar desde Excel a PostgreSQL
```

### Stock y forecast
```
GET  /stock/refresh           # Refrescar stock desde SQL Server
POST /forecast                # Generar forecast para un SKU
POST /train/batch             # Entrenar modelos Prophet en lote
```

---

## Lógica de negocio clave

### Regla de negocio v1.1: OF ≤ capacidad diaria de línea
Una OF no puede superar la capacidad diaria de la línea asignada. Esto elimina
el desborde inter-día y simplifica el cálculo de fecha de entrada real.

### Lead time y fecha de entrada (v1.1 — simplificado)
```
fecha_entrada_real = fecha_lanzamiento_real + round(lead_time_sem × 7) días
```
- Cálculo simple, sin simulación de desborde
- El backend siempre recalcula al aprobar o desplazar una OF
- El usuario puede sobrescribir manualmente en ModalEditar

### Entradas fijas de OFs aprobadas en el MRP (v1.1)
- Las OFs aprobadas se inyectan como entradas ciertas en su fecha_entrada_real
- El MRP emite fila visible para semanas con entrada aprobada AUNQUE el stock
  cubra la necesidad (nec_neta ≤ 0), para que el frontend muestre la OF correctamente
- El número OF aprobado se transmite via campo motivo con prefijo "OF_APROBADA:"

### Stock de seguridad
```
SS_cajas = (yhat_cajas / 7) × ss_dias
```
- Se calcula dinámicamente según el forecast de la semana

### Feriados Chile 2026 (hardcodeados en DetalleProduccion.jsx)
```
01/01, 29/03, 30/03, 06/04, 01/05, 21/05, 29/06, 16/07,
15/08, 18/09, 19/09, 12/10, 31/10, 01/11, 02/11, 08/12, 25/12
```

### t_cambio_hrs
- Tiempo de cambio entre SKUs en la misma línea
- NO afecta el tamaño de la OF (regla de negocio: OF ≤ cap_dia)
- Reservado para uso futuro en optimización de secuencia de producción

---

## Decisiones técnicas importantes (v1.1)

| Decisión | Descripción |
|----------|-------------|
| PostgreSQL separado | Tablas MRP en BD propia, no en SQL Server |
| Correlativo atómico | FOR UPDATE en PostgreSQL evita duplicados |
| PDF on-demand | reportlab genera PDF al solicitar, no al aprobar |
| Parámetros en BD | Excel solo para carga inicial, PostgreSQL es fuente de verdad |
| Lead time simplificado | fecha_entrada = lanzamiento + round(lt×7). Sin desborde. |
| Stock semana actual | El stock real de SQL Server se usa tal cual, no se ajusta |
| Semana dom→sáb | DetalleProduccion usa semanas domingo a sábado |
| MRP como fuente de verdad | StockProyeccion usa stock_ini/fin del MRP directamente |
| Sin importlib.reload | Eliminado de main.py — causaba cargar .pyc viejo en runtime |
| OF_APROBADA en motivo | Mecanismo para pasar numero_of de entrada aprobada al frontend |

---

## Bugs resueltos en v1.1 (sesión 29/04/2026)

### Bug 1 — cj_en_transito (CRÍTICO)
**Síntoma**: OFTs demasiado pequeñas, stock crónico bajo SS en todas las semanas.
**Causa**: El código descontaba producción futura aprobada de la nec_neta actual,
generando OFTs insuficientes y suprimiendo incorrectamente órdenes urgentes.
**Fix**: Eliminado completamente el bloque cj_en_transito de generar_plan_sku.

### Bug 2 — importlib.reload cargaba .pyc viejo
**Síntoma**: Cambios en mrp.py no tomaban efecto aunque el archivo fuera correcto.
**Causa**: importlib.reload() en main.py recargaba el bytecode compilado (.pyc)
ignorando el .py actualizado.
**Fix**: Eliminado importlib.reload() de main.py.

### Bug 3 — fecha_entrada_real desactualizada al desplazar OF
**Síntoma**: Al mover una OF en DetalleProduccion, la fecha de entrada en
StockProyeccion no se actualizaba — seguía mostrando la fecha original.
**Causa**: ModalDesplazar enviaba la fecha_entrada_real antigua (no la recalculaba).
**Fix**: ModalDesplazar envía fecha_entrada_real vacía; el backend la recalcula
siempre como fecha_lanzamiento + lead_time usando PostgreSQL.

### Bug 4 — StockProyeccion recalculaba stock independientemente del MRP
**Síntoma**: La proyección de stock divergía del MRP; stock_ini incorrecto.
**Causa**: calcularProyeccion() tenía su propio motor que no coincidía con el MRP.
**Fix**: calcularProyeccion() ahora usa directamente stock_inicial_cajas y
stock_final_cajas que devuelve el MRP. El backend es única fuente de verdad.

### Bug 5 — OF aprobada no visible en tabla cuando nec_neta ≤ 0
**Síntoma**: La OF aprobada desaparecía de la tabla de proyección semanal cuando
el stock cubría la necesidad sin necesidad de OFT adicional.
**Causa**: generar_plan_sku no emitía fila cuando nec_neta ≤ 0, aunque hubiera
entrada aprobada que mostrar.
**Fix**: El MRP ahora siempre emite fila cuando hay entrada aprobada en la semana,
con stock_ini real, entradas y stock_fin correctos.

### Bug 6 — _calcular_fecha_entrada usaba Excel y simulación de desborde
**Síntoma**: La fecha_entrada_real calculada al aprobar no coincidía con la regla
simplificada acordada con el jefe de producción.
**Causa**: ordenes.py leía parámetros desde Excel (fuente incorrecta) y simulaba
desborde de capacidad (ya no aplica).
**Fix**: _calcular_fecha_entrada usa load_params_from_db() y fórmula simple.

---

## Roadmap

### v1.0 ✅ COMPLETADO Y TAGGEADO (29/04/2026)
- [x] Forecast de Demanda — Prophet, 483 modelos, regressores por categoría
- [x] Plan de Producción — MRP clásico, OFTs, aprobaciones, PDF
- [x] Stock por SKU — proyección semanal, gráfico, tabla detallada
- [x] Detalle Producción — grid diario por línea, modal desplazar, modal editar
- [x] PostgreSQL — tablas MRP, parámetros, historial aprobaciones
- [x] fecha_entrada_real — calculada automáticamente, sincronizada entre módulos
- [x] Bugs críticos MRP resueltos (ver sección anterior)

### v1.1 — EN DESARROLLO (desde 29/04/2026)

#### Semana 6
- [ ] Optimizador OR-Tools para sizing de OFs
  - Variables: cantidad producida por SKU por semana (entera)
  - Restricciones: stock ≥ SS, stock ≤ cap_bodega, batch_min, batch_mult, OFs aprobadas fijas
  - Objetivo: minimizar semanas bajo SS + maximizar uso líneas (90–100%)
- [ ] Capacidad dinámica en MRP (descontar OFs aprobadas de cap. disponible)
- [ ] Alertas automáticas por quiebre post-postergación de OF
- [ ] BOM insumos (Bill of Materials básico)

#### Semana 7
- [ ] Dashboard ejecutivo KPIs
  - Cobertura promedio por categoría
  - % líneas sobre 90% de uso
  - OFs urgentes pendientes
- [ ] Integración pedidos (demanda comprometida vs forecast)
- [ ] 471 SKUs completos (actualmente piloto con 10 SKUs comerciales)

#### Semana 8
- [ ] Pruebas usuarios + capacitación jefe de producción
- [ ] Go-live piloto

### Más adelante (post go-live)
- [ ] Deploy producción (DigitalOcean + VPN headless)
- [ ] Integración SAP B1 via Service Layer API
- [ ] Módulo maquila
- [ ] Retraining automático semanal (compara real vs forecast)
- [ ] Feriados dinámicos (actualmente hardcodeados 2026)
- [ ] Volver repo a privado tras go-live

---

## Archivos del proyecto

```
forecast/
  main.py           # FastAPI principal (~700 líneas) — sin importlib.reload
  mrp.py            # Motor MRP (~560 líneas) — bugs corregidos v1.1
  db_mrp.py         # ORM PostgreSQL (~428 líneas)
  ordenes.py        # Gestión órdenes (~441 líneas) — _calcular_fecha_entrada corregida
  stock.py          # Integración SQL Server (~259 líneas)
  forecaster.py     # Motor Prophet
  requirements.txt  # psycopg2-binary, reportlab incluidos
  migrate_params.py # Migración Excel → PostgreSQL

dashboard/src/
  App.js                              (~826 líneas)
  components/StockProyeccion.jsx      (~571 líneas) — usa stock MRP directamente
  components/DetalleProduccion.jsx    (~583 líneas) — recalcula fecha_entrada_real

data/
  Traverso_Parametros_MRP.xlsx        # Fuente para carga inicial (PostgreSQL es fuente de verdad)
```

---

## Problemas conocidos y workarounds

| Problema | Workaround |
|----------|------------|
| Hot-reload React no compila cambios | `(Get-Content file) \| Set-Content file` + `docker compose restart dashboard` |
| openpyxl no evalúa fórmulas Excel | Usar PostgreSQL como fuente de verdad |
| reportlab se pierde al reiniciar | `docker exec traverso_forecast pip install reportlab==4.1.0 --break-system-packages -q` |
| __pycache__ puede cargar .pyc viejo | `docker exec traverso_forecast rm -rf /app/__pycache__` antes de restart |
| PowerShell no tiene `head` | Usar `Select-Object -First N` o evitar el pipe |
| Links en chat corrompen código Python | Verificar con `docker exec ... grep -n "p.lt"` antes de usar |

---

## Contexto del negocio

- **Empresa**: Traverso S.A. (alimentos chilenos: vinagres, salsas, jugos limón, sopas)
- **Segmento piloto**: COMERCIAL — 10 SKUs prioritarios de producción
- **Total SKUs**: 471 SKUs activos
- **Canales**: TRADICIONAL, CADENAS REGIONALES, SUPERMERCADOS NACIONALES, FOOD SERVICE
- **Líneas de producción**: L001 Líquidos 1, L002 Líquidos 2, S001 Salsas 1, S002 Salsas 2
- **Regla de negocio clave**: Una OF no puede superar la capacidad diaria de la línea

## Capacidades de línea (en PostgreSQL mrp_lineas)
| Código | Nombre | Velocidad | Cap/semana |
|--------|--------|-----------|------------|
| L001 | Líquidos 1 | 12.000 u/hr | 480.000 u/sem |
| L002 | Líquidos 2 | 10.000 u/hr | 400.000 u/sem |
| S001 | Salsas 1 | 3.000 u/hr | 120.000 u/sem |
| S002 | Salsas 2 | 3.000 u/hr | 120.000 u/sem |
