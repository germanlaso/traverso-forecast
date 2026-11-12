---
titulo: Detalle Producción: leer la grilla
objetivo: Leer por línea y día las órdenes, la capacidad usada, la producción real y las detenciones.
minutos: 12
puntos: 100
version: 1
ayuda: detalle
por_que: Es tu pantalla de trabajo diario. En un vistazo te dice qué está por lanzarse, qué falta aprobar, qué línea está llena y cuánto se produjo de verdad.
desafio: En Detalle Producción, ubica una orden Urgente y la línea con menos capacidad libre de la semana.
---
## Paso a paso
![Grilla de Detalle Producción](plan__detalle_grilla.png)

1. **Semana**: muévete con **Sem ant.** y **Sem sig.**; **Hoy** vuelve a la semana actual. También puedes filtrar por línea.
2. **Celda de un día**: las órdenes de ese día y la barra de capacidad, con el **% libre**.
3. **Resumen de la línea**: cuántas órdenes están **aprobadas** y cuántas **pendientes**.
4. **Producción real**: bajo cada orden, lo producido según SAP (Terminal Report) y su % de lo aprobado.
5. **Fecha del stock del datalake** y **⬇ Descargar plan (CSV)**.

Al hacer clic en el nombre de una línea se despliega su tabla de órdenes, con el estado de cada una.

## Cómo leer los colores
- Producción real: **verde** desde 90% de lo aprobado, **ámbar** entre 50% y 89%, **rojo** bajo 50%. Con "…", la orden está en curso.
- Los **minutos de detención** de la bitácora aparecen en cada día; en rojo si hubo una parada no planificada.
- La capacidad de cada día sale del calendario de turnos de la línea (por defecto la [[g:jornada-42h]]) y descuenta paradas planificadas y bloqueos.

```cuestionario
[
 {"id": "p1", "pregunta": "Una orden muestra \"real 150 cj · 30%\" en rojo. ¿Qué significa?", "opciones": ["Que se produjo más de lo aprobado", "Que se produjo solo el 30% de lo aprobado", "Que la orden está pendiente", "Que hay un error en SAP"], "correcta": 1, "explicacion": "Rojo indica que lo producido está bajo el 50% de lo aprobado."},
 {"id": "p2", "pregunta": "¿De dónde sale la producción real que muestra la grilla?", "opciones": ["De lo que escribe el planificador", "Del Terminal Report de SAP", "Del forecast", "De la bitácora"], "correcta": 1, "explicacion": "La producción real viene del Terminal Report de SAP."},
 {"id": "p3", "pregunta": "Un día de una línea aparece con minutos en rojo. ¿Qué indica?", "opciones": ["Que la línea está libre", "Que hubo una parada no planificada registrada en la bitácora", "Que hay órdenes urgentes", "Que el stock está bajo"], "correcta": 1, "explicacion": "Los minutos de detención salen de la bitácora; en rojo, si hubo paradas no planificadas."},
 {"id": "p4", "pregunta": "¿Cómo ves la tabla con el estado de cada orden de una línea?", "opciones": ["Haciendo clic en el nombre de la línea", "Descargando el CSV", "Desde Programación Diaria", "No existe"], "correcta": 0, "explicacion": "Al hacer clic en la línea se despliega su tabla de órdenes."}
]
```
