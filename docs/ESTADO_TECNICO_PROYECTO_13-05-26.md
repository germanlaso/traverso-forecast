# Traverso S.A. — Estado Técnico del Proyecto
## Sistema de Planificación de Producción con IA
### Versión: v1.3-V5 + V6.14 + V6.18 + V6.12-mini — Actualizado: 13/05/2026

> **Nota sobre fechas**: el calendario nominal del proyecto está corrido respecto al calendario real. Este snapshot fue generado el domingo 10/05/2026 real (continuación de la convención iniciada en snapshots anteriores).

---

## Resumen ejecutivo de la sesión

Sesión dedicada a tres bloques: (1) corrección y re-importación del Excel canónico de parámetros con la persistencia de los UPDATEs manuales del 09/05; (2) implementación y validación de V6.12-mini (filtrado defensivo de SKUs con stock>cap_bodega); (3) decisión sobre V6.11 (postergada como observabilidad post-vacaciones). Cierra con sistema robusto para las pruebas del 15/05 y un commit pusheado.

**Indicadores cierre del día:**

| Métrica | Valor |
|---|---|
| Commit pusheado | 82cef34 (V6.12-mini) |
| Plan h=4 con V6.12-mini | FEASIBLE @60s, 128-135 OFTs, 0 órdenes con stock_final<0 |
| BD post-import | 76 activos, 1 inactivo, 74 linea_preferida poblado, 2 vacío (IMPORTACION) |
| sku_lineas | 88 (75 preferidas + 13 alternativas) |
| setup_matrix | 2.191 pares |
| Test forzado V6.12-mini | OK (SKU 260010115 filtrado correctamente al bajar cap_bodega) |

---

## 1. Excel canónico re-importado (Bloque 1)

### Problema detectado en BD pre-import

Tras el re-import inicial del Excel (que el usuario editó anoche con las líneas alternativas), la BD quedó con un problema crítico:

- linea_preferida POBLADO: solo 16 de 76 SKUs activos.
- linea_preferida VACIO: 60 SKUs.

La columna "Línea Producción" en la hoja SKU_PARAMS del Excel estaba sin completar para los 60 SKUs nuevos del 09/05 — la información SÍ estaba en la hoja SKU_LINEA (en las filas con Preferida=S), pero ambas hojas no estaban sincronizadas.

### Hallazgo lateral: confusión Salsa Barbecue

Al validar el flag de Activo para 251010175, se descubrió que el usuario había confundido dos SKUs con descripción muy similar:

| SKU | Descripción | Activo correcto |
|---|---|---|
| 251010105 | SALSA BARBECUE TRAVERSO 10x1000 BOLSA | S (sí se vende) |
| 251010175 | SALSA BARBECUE TRAVERSO 12X500 DOYPACK | N (sin ventas históricas) |

Validado contra BD: el inactivo es 251010175 (DOYPACK). Excel local corregido.

### Solución: script Python

Se generó actualizar_linea_preferida.py (entregado al usuario en outputs locales) que:

1. Lee la hoja SKU_LINEA y construye un mapa SKU → línea preferida.
2. Recorre SKU_PARAMS y completa la columna "Línea Producción" (col K) solo donde está vacía.
3. Salta SKUs inactivos (Activo=N) y IMPORTACION.
4. Es idempotente: si se corre dos veces, la segunda no hace nada.

Resultado:
- 16 SKUs ya tenían línea (no se tocaron).
- 58 SKUs actualizados.
- 1 inactivo omitido (251010175).
- 2 IMPORTACION omitidos (Sopas Carne + Kikkoman).

### Re-import final

Tras correr el script en PC del usuario, subir el Excel al server, sincronizar al contenedor y reimportar:

- 74 SKUs activos con linea_preferida POBLADO ✓
- 2 vacíos (los 2 IMPORTACION) ✓
- 1 inactivo correcto (251010175) ✓
- sku_lineas: 88 (75 preferidas + 13 alternativas) ✓
- setup_matrix: 2.191 pares (de 1.834 anterior) ✓

Smoke test plan h=4 post-import: FEASIBLE, 135 OFTs, 0 órdenes con stock_final<0.

### Deuda registrada

V6.25 (nueva): el endpoint POST /params/importar-excel tiene timeout 30s que es insuficiente cuando hay muchos cambios (regenerar mrp_setup_matrix con 2.191 pares no es gratis). Devuelve HTTP 500 pero el proceso completa correctamente en background. Cosmético, no bloqueante.

---

## 2. V6.12-mini implementada y validada (Bloque 2)

### Problema atacado

Si un SKU activo tiene stock_inicial_u > cap_bodega_u, el modelo CP-SAT arranca con una infactibilidad estructural (la restricción stock_u[d,s] <= cap_bodega se viola desde el día 0) y aborta TODO el plan en milisegundos con INFEASIBLE. Le pasó al usuario el 09/05 cuando 8 SKUs marca privada 30x500 tenían cap_bodega=14.000 y stocks reales hasta 47.700u.

### Solución implementada

Bloque defensivo insertado en forecast/optimizer.py entre la sección 6 (entradas aprobadas) y la sección 7 (llamada al optimizador). Lógica:

- Para cada SKU en sku_params_rich, comparar stock_inicial_rich vs cap_bodega_u.
- Si stock > cap, agregar al listado skus_filtrados_cap_bodega con metadata (sku, descripción, stock_actual_u/cj, cap_bodega_u/cj, razón).
- Remover el SKU de sku_params_rich, forecast_rich, stock_inicial_rich y entradas_aprobadas_rich.
- Si la lista no está vacía, emitir logger.warning con la lista de SKUs filtrados.

### Validación con test forzado

Setup: SKU 260010115 (Mostaza Traverso 12x1000 DOYPACK) con stock real de 36.768u. Cap_bodega bajada artificialmente a 30.000 vía UPDATE en BD.

Resultado:

| Validación | Esperado | Real |
|---|---|---|
| Warning emitido con SKU específico | sí | WARNING:optimizer:[V6.12-mini] 1 SKUs filtrados: ['260010115'] ✓ |
| Plan FEASIBLE (no aborta) | FEASIBLE | FEASIBLE ✓ |
| OFTs del SKU filtrado | 0 | 0 ✓ |
| Otros SKUs siguen optimizando | sí | 128 OFTs vs 129 baseline ✓ |
| 0 órdenes con stock_final<0 | sí | 0 ✓ |

Cap_bodega restaurada a 216.000. Corrida post-restauración: sin warnings, sistema limpio.

### Deuda relacionada

V6.12-completa (post-vacaciones): hoy V6.12-mini filtra al SKU del optimizador. Una versión más sofisticada haría degradación elegante (intentar relajar restricciones progresivamente) o caer al MRP clásico como fallback para que el SKU siga teniendo alguna sugerencia de OFT. Pendiente.

---

## 3. V6.11 — Postergada como observabilidad post-vacaciones

### Análisis hecho

Se inspeccionó el bloque de construcción de forecasts en main.py:401-417. El código actual ya tiene un try/except que filtra implícitamente los SKUs cuando Prophet falla: los SKUs que fallan NO entran al diccionario forecasts, por lo tanto no llegan al optimizador.

### Conclusión

V6.11 reorientada como observabilidad (no como filtro defensivo, ya que el filtro existe de hecho): pendiente para post-vacaciones, requiere también cambios en frontend para mostrar banner amarillo si hay SKUs sin forecast.

---

## 4. Decisiones tomadas hoy

| ID | Decisión |
|---|---|
| D1 | Excel re-importado con script Python automatizado para completar linea_preferida. Idempotente, evita errores manuales. |
| D2 | 251010175 confirmado inactivo (era DOYPACK, no BOLSA). Persistido en Excel. |
| D3 | V6.12-mini implementada y validada con test forzado. Commit 82cef34 pusheado. |
| D4 | V6.11 postergada como observabilidad post-vacaciones. El try/except de main.py ya filtra implícitamente. |
| D5 | V6.25 nueva registrada: endpoint /params/importar-excel con timeout muy corto. No bloqueante. |
| D6 | Próxima sesión: ampliación piloto +50-100 SKUs sobre los 76 actuales. Universo objetivo 126-176 SKUs. |

---

## 5. Deudas técnicas — estado consolidado

| ID | Descripción | Estado |
|---|---|---|
| V6.11 | Filtrar SKUs sin forecast antes del optimizador | Postergada como observabilidad post-vacaciones. Try/except ya filtra implícitamente. |
| V6.12-mini | Filtrar SKUs con stock > cap_bodega | ✅ HECHO hoy. Commit 82cef34. |
| V6.12-completa | Degradación elegante (relajar restricciones / fallback MRP clásico) | Post-vacaciones, baja. |
| V6.14 | Stock inicial visible en dashboard | ✅ HECHO ayer. |
| V6.17 | Optimizador en h=13 deja ~1000 alertas estructurales (SS sobredimensionado) | Post-vacaciones, alta. |
| V6.18 | Penalización fuerte de quiebres (W_QUIEBRE) | ✅ HECHO ayer. |
| V6.19 | Modo blando para buscar SS factibles | Post-vacaciones. |
| V6.20 | W_USO_LINEA para incentivar uso >=90% diario | Post-vacaciones. |
| V6.21 | Convertir batch_min a restricción blanda | Post-vacaciones. |
| V6.23 | Detalle Producción muestra OFTs partidas como cuadritos | Post-vacaciones, cosmético. |
| V6.24 | Fragmentación temporal del optimizador (requiere F2 sequencer) | Post-vacaciones, alta. |
| V6.25 | NUEVA: timeout endpoint /params/importar-excel muy corto | Post-vacaciones, cosmético. |

---

## 6. Próxima sesión — Plan

Decisión tomada al cierre: ampliar piloto en +50-100 SKUs sobre los 76 actuales → universo objetivo 126-176 SKUs. Permite estresar la cota N_MAX=4 sin saltar al test extremo de 471.

### Bloques para la próxima sesión

1. Identificar SKUs a agregar: criterios posibles — los 100 SKUs activos con mayor venta histórica en SQL Server, o todos los SKUs de una categoría completa (ej. SALSAS completo), o mix curado por el usuario.
2. Preparar Excel ampliado: agregar filas a SKU_PARAMS y SKU_LINEA. Parámetros necesarios por SKU: u_por_caja, categoría, tipo, lead_time, ss_dias, batch_min/mult, cap_bodega, línea preferida (+ alternativas si aplica), t_cambio_hrs.
3. Backup BD pre-ampliación.
4. Importar y validar consistencia (mismas validaciones que hoy: 1 línea preferida por SKU, linea_preferida poblado en SKU_PARAMS para todos los activos PRODUCCION, etc.).
5. Regenerar matriz dummy (mrp_setup_matrix) con los nuevos pares SKU↔SKU por línea. Endpoint pendiente o vía script directo.
6. Smoke test extendido: plan h=4 con el nuevo universo. Validar tiempos del solver y comportamiento de V6.12-mini con los SKUs nuevos.
7. Posible ajuste: si performance se degrada significativamente, evaluar subir timeout del solver de 60s a 120s.

### Tareas restantes pre-vacaciones (después de la ampliación)

- Manual del usuario con screenshots (~3-4h).
- PDF v8 de avance para Gerencia (~1h).
- Comunicación al equipo para arranque del 15/05 (~30 min).

---

## 7. Estado git al cierre

Último commit: 82cef34 feat(optimizer): V6.12-mini — filtrar SKUs con stock>cap_bodega.

Historial reciente:
- 82cef34 V6.12-mini (hoy)
- 352da1e snapshot técnico cierre 12/05/2026 (ayer)
- 0825ff1 V6.14 + V6.18 + horizonte default 4 sem
- 4fbe0ed eliminar atributo version obsoleto de docker-compose.yml
- c867747 guía de usuario inicial

Backups BD del día: /home/ubuntu/backups/mrp_db_pre_import3_*.sql.

---

## 8. Tag de retorno seguro

Para volver al tag estable v1.2-piloto: git checkout v1.2-piloto + docker compose down && up -d --build.
Para volver al estado al cierre del 13/05 (nominal): git checkout 82cef34.

---

## 9. Próximo chat — primera invocación recomendada

> Lee CLAUDE.md, docs/ESTADO_TECNICO_PROYECTO_09-05-26.md, docs/ESTADO_TECNICO_PROYECTO_12-05-26.md y docs/ESTADO_TECNICO_PROYECTO_13-05-26.md. Resúmeme el estado actual y arranquemos por identificar los 50-100 SKUs a agregar al piloto antes de los manuales.

---

*Cerrado al fin de la sesión nominal del 13/05/2026 (real: domingo 10/05/2026).*

---

## ⚠ Pendiente urgente para mañana primera hora

Usuario reporta al cierre que ve **muchos quiebres en el dashboard** — más de lo esperado tras la re-importación del Excel y V6.12-mini.

**Investigación pendiente** (orden sugerido):
1. Capturar lista exacta de SKUs en rojo en el dashboard (h=4 vs h=13).
2. Distinguir entre "stock_final<0 real" vs "BAJO_SS visualizado en rojo".
3. Comparar lista con datos del 12/05 (¿son los mismos SKUs?).
4. Si son los mismos: probablemente es V6.17 (SS sobredimensionado, conversación con Gerente).
5. Si hay nuevos: investigar qué cambió tras la re-importación del Excel.

**Hipótesis preferida** (a confirmar): el horizonte 4 default oculta el problema (0 órdenes stock<0) pero el dashboard de "Stock por SKU" puede estar mostrando SS_dinámico calculado sobre los próximos N días que excede lo que el plan puede producir. Es deuda V6.17 (SS sobredimensionado) llegando al ojo del usuario.
