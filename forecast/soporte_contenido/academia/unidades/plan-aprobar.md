---
titulo: Aprobar y editar una orden
objetivo: Aprobar una OF sugerida con sus datos reales y corregirla después si hace falta.
minutos: 10
puntos: 100
version: 2
ayuda: detalle
por_que: Aprobar es la decisión más importante del planificador: convierte una propuesta del sistema en un compromiso que producción va a ejecutar y que el plan va a respetar.
desafio: En Detalle Producción, abre la ventana de aprobación de una orden pendiente, revisa sus datos y ciérrala con Cancelar, sin aprobar.
---
## Aprobar una orden
![Ventana de aprobación](plan__aprobar.png)

Una orden sugerida (**Pendiente** o **Urgente**) se aprueba de dos formas, que abren la misma ventana:
- con el botón **Aprobar** en la tabla de la línea, o
- **haciendo clic en la tarjeta de la orden** (ámbar) en la grilla del día.

En la ventana de aprobación:
1. **Cantidad real a producir (cajas)**: parte con lo sugerido por el sistema; ajústala si producirás otra cantidad.
2. **Fecha de lanzamiento real** y **fecha de entrada a stock real**: cuándo se produce y cuándo estará disponible.
3. **Responsable** (jefe de producción) y un **comentario** opcional.
4. **✓ Confirmar aprobación**: la orden pasa a [[g:of-aprobada]] y recibe su número definitivo.

Si te arrepientes, **Cancelar** cierra la ventana sin cambiar nada.

## Editar o retirar una aprobación
- En una orden aprobada, **✏️ Editar** en la tabla (o un clic en su tarjeta verde de la grilla) permite cambiar la cantidad, las fechas y el comentario, y **Guardar**.
- **↩ Retirar aprobación** la devuelve a sugerida.
- El aviso **"⚠ OF modificadas desde el último plan"** de la barra superior indica que hay órdenes aprobadas, editadas o creadas **después** del último plan. Esas órdenes **ya son válidas**: aparecen en Programación Diaria y se producen. El aviso solo advierte que las proyecciones que calcula el plan (por ejemplo, Stock Diario o el Mapa de Quiebres) todavía no las consideran; el plan de las 06:00 del día siguiente las incorpora y el aviso se apaga.

```cuestionario
[
 {"id": "p1", "pregunta": "El sistema sugiere 850 cajas, pero producción solo puede hacer 600 esta semana. ¿Qué haces al aprobar?", "opciones": ["Apruebo 850 y aviso por correo", "Ajusto la cantidad real a 600 antes de confirmar", "No apruebo nada", "Creo una OF manual por 250"], "correcta": 1, "explicacion": "La cantidad real se ajusta en la ventana de aprobación antes de confirmar."},
 {"id": "p3", "pregunta": "Aprobaste una orden con la fecha equivocada. ¿Qué haces?", "opciones": ["Creo otra orden", "Uso ✏️ Editar, corrijo la fecha y guardo", "Espero al plan de mañana", "No se puede corregir"], "correcta": 1, "explicacion": "Las órdenes aprobadas se editan con ✏️ Editar."},
 {"id": "p4", "pregunta": "Después de aprobar, aparece \"OF modificadas desde el último plan\". ¿Qué significa?", "opciones": ["Que hubo un error", "Que hay órdenes aprobadas, editadas o creadas después del último plan", "Que hay que regenerar el plan a mano", "Que la orden aún no es válida"], "correcta": 1, "explicacion": "La orden aprobada es válida de inmediato. El aviso solo indica que el último plan es anterior a esos cambios; el plan de la mañana siguiente los incorpora a sus proyecciones."},
 {"id": "p6", "pregunta": "¿De qué formas puedes abrir la aprobación de una orden sugerida?", "opciones": ["Solo desde la tabla de la línea", "Con Aprobar en la tabla o haciendo clic en su tarjeta en la grilla", "Solo desde Programación Diaria", "Solo desde Stock Diario"], "correcta": 1, "explicacion": "Ambas abren la misma ventana de aprobación."},
 {"id": "p5", "pregunta": "¿Qué hace ↩ Retirar aprobación?", "opciones": ["Borra la orden del sistema", "Devuelve la orden a sugerida", "La envía a planta", "Cambia el responsable"], "correcta": 1, "explicacion": "La orden vuelve a ser una propuesta del sistema."}
]
```
