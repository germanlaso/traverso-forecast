---
titulo: Detalle Producción
seccion: Planificación
resumen: Grilla por línea y día con las órdenes, la capacidad y la bitácora.
orden: 32
actualizado: 2026-11-11
---
## Para qué sirve
Muestra la producción semana a semana, por línea y por día: qué órdenes hay, cuánta capacidad usan y qué eventos tiene registrada cada línea. Desde aquí también se aprueban, editan y crean órdenes.

## Qué muestra
- Navegación por semana (**Sem ant.** / **Sem sig.**) y filtro de línea.
- Por cada línea y día: las órdenes con su estado y la capacidad del día.
- Estados de una orden: **Aprobada**, **Pendiente** (sugerida) y **Urgente** ([[g:urgente|urgente]]: su fecha de lanzamiento es hoy o ya pasó y no está aprobada).
- Minutos registrados en la [[g:bitacora]] para cada línea y día.

## Cómo se usa
1. Elige la semana y, si quieres, una línea.
2. Para aprobar una orden pendiente, usa **Aprobar**; para cambiar una aprobada, **Editar**.
3. Para producir algo que el sistema no sugirió, usa **Crear OF** en la línea:
   1. Elige el SKU, la cantidad en cajas y la fecha de lanzamiento.
   2. Si excede la capacidad disponible del día, el sistema avisa, pero permite crearla (turno extra o criterio del planificador).
4. Para registrar o ver eventos de un día, abre la bitácora desde la celda.
5. Para ver cómo queda el stock de un SKU, usa **Ver proyección diaria de inventario**.

## Cómo leer los datos
- La capacidad del día sale del calendario de turnos de la línea y descuenta las [[g:parada-planificada|paradas planificadas y bloqueos]] registrados.
- Las órdenes manuales ([[g:ofm]]) entran como aprobadas.

## Pantallas relacionadas
Plan de Producción · Bitácora · Programación Diaria
