---
titulo: Parámetros
seccion: Herramientas
resumen: Diagnóstico y edición de los parámetros de líneas y SKU.
orden: 60
actualizado: 2026-11-11
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
4. En la edición de línea puedes ajustar velocidad, turnos y excepciones por fecha (por ejemplo, un sábado trabajado).
5. Si un cambio fue un error, usa **Revertir** en el historial (solo el cambio más reciente de cada campo).

## Cómo leer los datos
- 🔴 **Error**: no se puede guardar (por ejemplo, batch mayor a la capacidad diaria o cap. bodega menor al batch).
- 🟡 **Advertencia**: se puede guardar, pero conviene revisarla (por ejemplo, batch de menos de 3 horas, o cap. bodega menor a batch + SS).
- Los cambios aplican en la **próxima corrida del plan**.
- Consultar es libre; editar requiere PIN.

## Pantallas relacionadas
Análisis de Línea · Lo aprendido · Detalle Producción
