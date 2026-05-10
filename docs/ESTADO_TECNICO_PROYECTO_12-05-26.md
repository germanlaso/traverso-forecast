# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.3-V5 + V6.14 + V6.18 + horizonte 4 — Actualizado: 12/05/2026

---

## Resumen ejecutivo de la sesión

Día dedicado a cerrar la deuda V6.14 (bug del dashboard mostrando "Stock 0" para SKUs con stock real). En el camino se descubrieron y caracterizaron problemas estructurales del optimizador en horizonte largo. La sesión cerró con cambios desplegados que dejan el sistema robusto para las pruebas del 15/05, y 7 deudas técnicas nuevas bien documentadas para abordar post-vacaciones.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Commit pusheado | `0825ff1` (feature/v1.3-cascada) |
| Plan h=4 con cambios | FEASIBLE @60s, ~127 OFTs, ~8 quiebres internos, **0 órdenes con stock_final<0** |
| SKUs canónicos validados | 121010290, 111010290, 112010210 (los 3 sin quiebres rojos) |
| Horizonte default | 4 semanas (era 13) |
| Deudas técnicas nuevas | V6.17 a V6.24 (7 nuevas) |

---

## 1. Cambios desplegados

### V6.14 — Stock inicial visible (bug raíz cerrado)

**Backend (`forecast/optimizer.py` línea 945)**

Antes:
```python
"stock_inicial_cajas": 0,  # se calcula globalmente abajo
```

Después:
```python
"stock_inicial_cajas": round(stock_inicial_rich.get(sku, 0) / upc, 1) if upc else 0.0,
```

**Diagnóstico**: el campo `stock_inicial_cajas` quedaba hardcoded a 0 en cada OFT generada por el optimizador. El comentario "se calcula globalmente abajo" prometía un cálculo posterior que nunca existió. La variable `stock_inicial_rich[sku]` (en unidades) está disponible en el scope del armado de la orden.

**Frontend (`dashboard/src/components/StockProyeccion.jsx` líneas 286-298)**

Antes (se basaba en parsear el campo string `motivo` con regex):
```javascript
const motivo = ordenesSku[0]?.motivo ?? "";
const m = motivo.match(/Stock:([\d.]+)/);
setStockReal(m ? parseFloat(m[1]) : 0);
```

Después (prioriza el campo numérico, fallback al regex para MRP clásico):
```javascript
const primeraOrden = ordenesSku[0];
if (primeraOrden && typeof primeraOrden.stock_inicial_cajas === 'number' && primeraOrden.stock_inicial_cajas > 0) {
  setStockReal(primeraOrden.stock_inicial_cajas);
} else {
  const motivo = primeraOrden?.motivo ?? "";
  const m = motivo.match(/Stock:([\d.]+)/);
  setStockReal(m ? parseFloat(m[1]) : 0);
}
```

**Diagnóstico secundario**: el frontend dependía de un patrón string `"Stock:N"` que solo aparecía en órdenes del MRP clásico (formato `"FC:1974 SS:16919 Stock:119 Neta:18774"`). Las órdenes del optimizador llegaban con motivo `"OFT (optimizada)"`, sin el dato numérico. Ahora prioriza el campo estructurado.

**Validación**: 5 SKUs verificados (121010290, 112010210, 111010115, 111010175, 111010290). Todos muestran stock real correcto en dashboard. Match con CSV exacto.

### V6.18 — Penalización fuerte de quiebres reales

**Constantes (líneas 51-58)**:
- Nueva: `W_QUIEBRE = 1_000_000` (10× peor que W_DEFICIT).
- Cambiada: `W_EXCESO = 50_000 → 10_000` (refleja jerarquía operativa).

**Modelo CP-SAT**:
- Nueva variable `m.quiebre[(d, s)]` (línea 312).
- Nuevo atributo de clase `self.quiebre: dict[...] = {}` (línea 122).
- Nueva restricción `m.quiebre >= -m.stock_u` (línea 463). Esto hace que `quiebre = max(0, -stock)` cuando stock es negativo.
- Nuevo término en función objetivo: `obj_terms.append(W_QUIEBRE * v) for v in m.quiebre.items()` (líneas 499-500).

**Justificación**: el modelo anterior contaba "stock 100u bajo SS" y "stock 100u en negativo" como equivalentes en penalización (deficit = ss - stock_u). Eso no reflejaba la jerarquía operativa real: quebrar es mucho peor que estar bajo SS. Ahora un evento de quiebre paga deficit (W_DEFICIT × ss-stock) Y quiebre (W_QUIEBRE × |stock|) simultáneamente.

**Validación en h=4**: quiebres bajaron de 19 (baseline) a 8 (V6.18). Otras métricas estables.

**No mejora h=13**: en el horizonte largo, V6.18 redistribuye alertas pero no las reduce significativamente. Eso es lo que llevó a la decisión de cambiar el horizonte default.

### Horizonte default 4 semanas (decisión operativa)

**Frontend (`dashboard/src/App.js:189` y `StockProyeccion.jsx:200`)**:
- `useState(13)` → `useState(4)`.

**Razonamiento**:
- El equipo opera con visibilidad real de 2-4 semanas. h=13 es para análisis estratégico, no para planificación operativa.
- En h=4, el plan tiene ~8 quiebres internos pero **0 OFTs con stock_final<0** que el dashboard rendería en rojo. El equipo no ve quiebres falsos.
- En h=13, el plan tiene 1.000+ alertas (en su mayoría "bajo SS") que reflejan **SS sobredimensionado**, no problemas operativos reales.

**Las opciones de horizonte (1, 4, 13...) siguen disponibles en el dropdown.** Solo cambia el default.

---

## 2. Hallazgos de la sesión

### Hallazgo crítico — SS sobredimensionado en L1Pet LV

Los 32 SKUs activos de L1Pet LV tienen **`ss_dias = 15` uniforme**, sin variación por SKU/categoría/marca/rotación. Combinado con `lead_time_sem = 0.15` (1 día), el ratio SS/lead_time es **15:1**. Eso es desproporcionado.

**Validación con datos del 12/05:**
- Stock real total L1Pet LV: **29.714 cj**.
- SS requerido total con configuración actual: **16.799 cj**.
- **Ratio: 177%** (el operativo real es ~1,77× el SS configurado).
- Solo **4 de 32 SKUs** están bajo SS hoy mismo (112010290, 112030290, 113010290, 114010290).

**Lectura**: la planta opera bien con stocks que están por debajo del SS configurado para varios SKUs. El SS no refleja la realidad operativa. Es input para la conversación con Gerente al regreso.

### Hallazgo lateral — fragmentación temporal del optimizador

El optimizador genera OFTs muy chicas (ej: SKU 123010260 con 6 órdenes, mínima de 34 cajas = 18 minutos de línea) que no tienen sentido operativo. Probado calibrar W_INICIO_SIMBOLICO en 200 y 10000 — ningún valor mejora significativamente. El problema es **estructural**: el modelo N1 sin N2 (sequencer) tiene indeterminación matemática que solo F2 del v1.3 design doc resuelve.

### Hallazgo lateral — capacidades por línea

| Línea | Uso plan h=13 | Diagnóstico |
|---|---|---|
| Sachetera | 90,8% | Saturada por diseño (cap=batch_min, decisión Gerente). |
| Doypack | 95,4% | **Casi al techo. Validar con Gerente.** |
| L1Pet LV | 46,2% (efectivo ~63% con setup) | Holgada en agregado, picos por (línea, semana) llegan a 63%. |
| L1Pet A | 14,8% | Muy holgada. |
| Doypack 4 | 29,2% | Holgada. |

**Setup time consume ~17% de capacidad efectiva en L1Pet LV**, lo cual reduce la holgura aparente.

---

## 3. Decisiones tomadas hoy

| ID | Decisión |
|---|---|
| D1 | **V6.14 patches desplegados** (backend + frontend). Bug "Stock 0" cerrado. |
| D2 | **V6.18 desplegado** (W_QUIEBRE + ajuste W_EXCESO). Mejora h=4. |
| D3 | **Horizonte default cambiado a 4 sem.** Decisión operativa para que el equipo vea datos realistas en las pruebas del 15/05. h=13 disponible pero no por default. |
| D4 | **W_INICIO_SIMBOLICO mantenido en 1** (calibración 200/10000 sin mejora). |
| D5 | **Calibración compleja de pesos pospuesta.** No vale el tiempo de iterar parámetros sobre un modelo cuya función objetivo no captura adecuadamente timing y continuidad de corridas. Esa fue la prueba empírica de hoy. |

---

## 4. Deudas técnicas registradas (post-vacaciones)

| ID | Descripción | Prioridad |
|---|---|---|
| V6.11 | Filtrar SKUs sin forecast antes del optimizador. | Pre-vacaciones (martes 13/05). |
| V6.12-mini | Filtrar SKUs con `stock > cap_bodega` antes del optimizador. | Pre-vacaciones (martes 13/05). |
| V6.14 | ✅ HECHO. |
| V6.17 | Optimizador en h=13 deja ~1000 alertas estructurales (SS sobredimensionado). | Post-vacaciones, alta. |
| V6.18 | ✅ HECHO (parcial — mejora h=4, no h=13). |
| V6.19 | Permitir al optimizador buscar SS factibles (modo blando: bajar W_DEFICIT, subir W_QUIEBRE — el modelo te dice cuál es el SS posible). | Post-vacaciones. |
| V6.20 | W_USO_LINEA — incentivar uso ≥90% diario (visión inicial del usuario). | Post-vacaciones. |
| V6.21 | Convertir batch_min a restricción blanda (con análisis de sensibilidad). | Post-vacaciones. |
| V6.22 | (descartada — `batch_mult_u` ya está relajado en optimizer.py:351). |
| V6.23 | Detalle Producción muestra OFTs partidas como cuadritos. | Post-vacaciones, cosmético. |
| V6.24 | Fragmentación temporal del optimizador. **Requiere F2 sequencer** del v1.3 design doc. | Post-vacaciones, alta. |

---

## 5. Pendientes pre-vacaciones (martes 13/05 y miércoles 14/05)

### Martes 13/05

1. **Persistir UPDATEs en Excel** (cambios del 09/05 aplicados directo a BD):
   - SKU 251010175 inactivo (columna Activo: S → N).
   - Línea Producción para los 59 SKUs nuevos (completar columna desde valores actuales de SKU_LINEA donde preferida=true).
2. **V6.11**: filtrar SKUs sin forecast antes del optimizador. Estimación: 1h.
3. **V6.12-mini**: filtrar SKUs con stock > cap_bodega. Estimación: 1h.
4. **Manual del usuario** con screenshots (lenguaje neutro chileno). Estimación: 3-4h.

### Miércoles 14/05

1. **PDF v8 de avance** para Gerencia. Mensajes principales:
   - V6.14 cerrado: stock visible correctamente.
   - Hallazgo SS sobredimensionado en L1Pet LV (data del 177%).
   - Hallazgo Doypack al 95% de capacidad.
   - Decisión horizonte default 4 sem.
   - Roadmap V6.17-V6.24 post-vacaciones.
2. Comunicación al equipo: instrucciones de arranque del 15/05.

---

## 6. Estado git al cierreBackups del día (fuera del repo): `/home/ubuntu/traverso_backups_2026-05-12/`.

---

## 7. Tag de retorno seguro

```bash
git checkout v1.2-piloto
docker compose down && docker compose up -d --build
```

Para volver al estado al cierre del 12/05: `git checkout 0825ff1`.

---

## 8. Próximo chat — primera invocación recomendada

> Lee `CLAUDE.md`, `docs/ESTADO_TECNICO_PROYECTO_09-05-26.md` y `docs/ESTADO_TECNICO_PROYECTO_12-05-26.md`. Resúmeme el estado actual y los pendientes pre-vacaciones, y arranquemos por persistir los UPDATEs en Excel + V6.11 + V6.12-mini.

---

*Cerrado al fin de la sesión del lunes 12/05/2026.*
