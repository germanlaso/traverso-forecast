---
titulo: Parámetros
seccion: Herramientas
resumen: Diagnóstico y edición de los parámetros de líneas y SKU.
orden: 60
actualizado: 2026-11-12
---
## Para qué sirve
Muestra la capacidad de cada línea y revisa que los parámetros de cada SKU sean coherentes. Con [[g:pin]], permite editarlos. Los parámetros que se guardan aquí son los que usa el plan.

## Qué muestra
- Indicadores: líneas, SKU activos, errores, advertencias y SKU sin línea.
- Por línea: horas por día, capacidad por turno, día y semana, y la carga que exige la demanda.
- Por SKU: [[g:batch-minimo]], múltiplo de batch, [[g:cap-bodega]], unidades por caja, [[g:ss]], [[g:lead-time]], [[g:factor-velocidad]], velocidad efectiva, horas por batch, [[g:cobertura]] del batch y forecast.
- Panel de **recomendaciones** abiertas (por ejemplo, del Análisis de Línea).

## Cómo se usa
1. Busca un SKU o revisa una línea. Filtra por errores o advertencias con los chips.
2. Para editar un SKU o una línea, usa **Editar**:
   1. Cambia el valor y revisa la validación.
   2. Escribe tu nombre, el PIN y el motivo del cambio.
   3. Guarda.
3. Para aplicar una recomendación, ábrela y usa **Usar sugerencia**; o descártala con un motivo.
4. En la edición de línea puedes ajustar la velocidad, los turnos y las excepciones por fecha (ver más abajo).
5. Si un cambio fue un error, usa **Revertir** en el historial (solo el cambio más reciente de cada campo).

## Turnos y jornada de una línea
La capacidad de cada línea sale de su calendario de turnos. Por defecto es la [[g:jornada-42h]]: lunes y martes 9 h, miércoles a viernes 8 h.
1. En la línea, usa **Editar** y abre la pestaña **Editar**.
2. En **Horas por día y turno**, cada fila es un turno (hasta 3) y cada columna un día. Un día en 0 significa que ese turno no trabaja ese día.
3. El **turno 1** es la jornada base y no lleva fechas.
4. Los turnos adicionales pueden tener **vigencia**: fecha **desde** y **hasta** (por ejemplo, un turno de temporada). Con la casilla **sin término**, el turno rige indefinidamente.
5. Revisa el **impacto en los SKU de la línea** antes de guardar, y guarda con tu nombre, el PIN y el motivo.

Los totales de la grilla suman **todos** los turnos; la vista previa de impacto considera solo los turnos **vigentes hoy**.

## Excepciones por fecha
Para un día puntual distinto del calendario normal, usa la pestaña **Excepciones por fecha** de la línea:
1. Elige el tipo: **extensión de turno**, **sábado trabajado**, **domingo o feriado trabajado**, **día sin producción** u **otro**.
2. Indica la fecha y las **horas totales de ese día** (0 = sin producción).
3. Guarda con PIN. Para corregir, usa **Anular**.

Las paradas planificadas y bloqueos registrados en la [[a:bitacora|Bitácora]] también restan horas a la capacidad.

## Cómo leer los datos
- 🔴 **Error**: no se puede guardar (por ejemplo, batch mayor a la capacidad diaria o cap. bodega menor al batch).
- 🟡 **Advertencia**: se puede guardar, pero conviene revisarla (por ejemplo, batch de menos de 3 horas, o cap. bodega menor a batch + SS).
- Los cambios de parámetros, turnos y excepciones aplican en la **próxima corrida del plan**.
- Consultar es libre; editar requiere PIN.

## Pantallas relacionadas
[[a:analisislinea|Análisis de Línea]] · [[a:aprendido|Base de conocimiento]] · [[a:detalle|Detalle Producción]]
