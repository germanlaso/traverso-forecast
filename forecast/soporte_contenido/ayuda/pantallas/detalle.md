---
titulo: Detalle Producción
seccion: Planificación
resumen: Grilla por línea y día con las órdenes, la capacidad, la producción real y la bitácora. Aquí se aprueban y crean las órdenes.
orden: 32
actualizado: 2026-11-12
---
## Para qué sirve
Es la pantalla de trabajo del planificador. Muestra, semana a semana, por línea y por día: qué órdenes hay, cuánta capacidad usan, cuánto se produjo realmente y qué eventos tiene registrados cada línea. **Aquí se aprueban, editan y crean las órdenes de fabricación.**

## Qué muestra
- Navegación por semana (**Sem ant.** / **Sem sig.**) y filtro de línea.
- Arriba a la derecha: la **fecha del stock del datalake** y **⬇ Descargar plan (CSV)**.
- Por cada línea y día: las órdenes con su estado y la capacidad que consumen.
- Estados de una orden: **✓ Aprobada**, **Pendiente** ([[g:oft|OF sugerida]]) y **⚡ Urgente** (su fecha de lanzamiento es hoy o ya pasó y no está aprobada).
- **Producción real** de cada orden (Terminal Report de SAP): verde desde 90% de lo aprobado, ámbar entre 50% y 89%, rojo bajo 50%; "…" si la orden está en curso.
- **Minutos de detención** registrados en la [[g:bitacora]] para cada línea y día (en rojo si hubo paradas no planificadas).

## Cómo se usa
### Aprobar una orden
1. Ubica la orden **Pendiente** o **Urgente** en su línea y día.
2. Presiona **Aprobar** en la tabla de la línea, o haz clic en la **tarjeta de la orden** en la grilla (abren la misma ventana).
3. En la ventana, ajusta si corresponde la **cantidad real** (cajas), la **fecha de lanzamiento real**, la **fecha de entrada a stock** y un **comentario**.
4. Confirma: la orden pasa a [[g:of-aprobada]], recibe su número definitivo y el sistema la respeta en las próximas corridas.
5. Para corregirla después, usa **✏️ Editar**.

### Crear una orden manual
1. Usa **＋ Crear OF** en la línea.
2. Elige el SKU, la cantidad en cajas y la fecha de lanzamiento.
3. Si excede la capacidad disponible del día, el sistema avisa, pero permite crearla (turno extra o criterio del planificador). Las órdenes manuales ([[g:ofm]]) entran como aprobadas.

### Registrar o ver eventos de la bitácora
1. Abre la bitácora desde la celda de la línea y el día.
2. Elige el tipo de evento y, opcionalmente, la **máquina**.
3. Indica la **hora de inicio** y la **hora de fin**: la duración se calcula sola (si el evento pasa la medianoche, también). También puedes escribir directamente la duración en minutos.
4. Guarda. El detalle completo está en [[a:bitacora|Bitácora]].

## Cómo leer los datos
- La capacidad del día sale del calendario de turnos de la línea y descuenta las [[g:parada-planificada|paradas planificadas y bloqueos]] registrados.
- El aviso **"⚠ OF modificadas desde el último plan"** de la barra superior indica que hay órdenes aprobadas, editadas o creadas **después** del último plan. Esas órdenes **ya son válidas**: aparecen en Programación Diaria y se producen. El aviso solo advierte que las proyecciones que calcula el plan (por ejemplo, Stock Diario o el Mapa de Quiebres) todavía no las consideran; el plan de las 06:00 del día siguiente las incorpora y el aviso se apaga.
- Si no hay plan vigente cargado, la pantalla lo indica: el plan se genera automáticamente todos los días a las 06:00; si falta, avisa a Planificación.
- El CSV descarga el plan completo (órdenes sugeridas y aprobadas) para trabajarlo en Excel.

## Pantallas relacionadas
[[a:stockdiario|Stock Diario]] · [[a:bitacora|Bitácora]] · [[a:programacion|Programación Diaria]] · [[a:campanas|Campañas]]
