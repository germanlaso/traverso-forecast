---
titulo: Rendimiento
seccion: Informes
resumen: Indicadores semanales de la operación por línea: cumplimiento, ocupación y eficiencia.
orden: 46
actualizado: 2026-11-12
---
Está en **Informes → Rendimiento**.

## Para qué sirve
Muestra cómo rindió la operación: cuánto se programó, cuánto se produjo y cómo se usaron las líneas.

## Qué muestra
- Filtros: periodo, categoría y línea.
- **Programado en la app vs programado en SAP**: cajas por semana y % del programa SAP que tiene OF en la app.
- **Programado en SAP vs producido real**: cajas por semana y [[g:cumplimiento]].
- **[[g:ocupacion]] por línea** y detalle por línea, incluida la [[g:eficiencia]] cuando hay bitácora.
- Eventos de la bitácora del periodo.
- **Evolutivo por línea** (clic para ampliar).
- **Mayores desvíos por SKU**.
- **Producción fuera de líneas MRP** (no entra a los indicadores de línea).
- **Calidad de datos**: lo que el cálculo no pudo medir o requiere validación.

## Cómo leer los datos
- Las semanas van de lunes a domingo; un asterisco (*) marca una semana parcial o en curso.
- Las **horas nominales** de cada línea siguen su calendario de turnos (por defecto la [[g:jornada-42h]]) y **no cuentan los feriados**. Por eso la ocupación de semanas con feriado puede diferir de cálculos anteriores.
- Cumplimiento = cajas producidas ÷ cajas programadas en SAP.
- Ocupación = horas equivalentes de producción ÷ horas nominales.
- Eficiencia = producción real ÷ producción teórica; solo con bitácora.

## Pantallas relacionadas
[[a:bitacora|Bitácora]] · [[a:informeia|Informe semanal]]
