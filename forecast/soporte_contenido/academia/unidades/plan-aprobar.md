---
titulo: Aprobar y editar una orden
objetivo: Aprobar una OF sugerida con sus datos reales y corregirla después si hace falta.
minutos: 10
puntos: 100
version: 1
ayuda: detalle
por_que: Aprobar es la decisión más importante del planificador: convierte una propuesta del sistema en un compromiso que producción va a ejecutar y que el plan va a respetar.
desafio: En Detalle Producción, abre la ventana de aprobación de una orden pendiente, revisa sus datos y ciérrala con Cancelar, sin aprobar.
---
## Aprobar una orden
![Ventana de aprobación](plan__aprobar.png)

En la tabla de la línea, presiona **Aprobar** en una orden **Pendiente** o **Urgente**. Se abre la ventana de aprobación:
1. **Cantidad real a producir (cajas)**: parte con lo sugerido por el sistema; ajústala si producirás otra cantidad.
2. **Fecha de lanzamiento real** y **fecha de entrada a stock real**: cuándo se produce y cuándo estará disponible.
3. **Responsable** (jefe de producción) y un **comentario** opcional.
4. **✓ Confirmar aprobación**: la orden pasa a [[g:of-aprobada]] y recibe su número definitivo.

Si te arrepientes, **Cancelar** cierra la ventana sin cambiar nada.

## Editar o retirar una aprobación
- En una orden aprobada, **✏️ Editar** permite cambiar la cantidad, las fechas y el comentario, y **Guardar**.
- **↩ Retirar aprobación** la devuelve a sugerida.
- Después de aprobar o editar, la barra superior muestra **"OF modificadas desde el último plan"** hasta que el plan de las 06:00 incorpore el cambio.

```cuestionario
[
 {"id": "p1", "pregunta": "El sistema sugiere 850 cajas, pero producción solo puede hacer 600 esta semana. ¿Qué haces al aprobar?", "opciones": ["Apruebo 850 y aviso por correo", "Ajusto la cantidad real a 600 antes de confirmar", "No apruebo nada", "Creo una OF manual por 250"], "correcta": 1, "explicacion": "La cantidad real se ajusta en la ventana de aprobación antes de confirmar."},
 {"id": "p2", "pregunta": "Abriste la ventana de aprobación por error. ¿Cómo sales sin aprobar?", "opciones": ["Con ✓ Confirmar aprobación", "Con Cancelar", "Cerrando el navegador es la única forma", "Con Retirar aprobación"], "correcta": 1, "explicacion": "Cancelar cierra la ventana sin guardar."},
 {"id": "p3", "pregunta": "Aprobaste una orden con la fecha equivocada. ¿Qué haces?", "opciones": ["Creo otra orden", "Uso ✏️ Editar, corrijo la fecha y guardo", "Espero al plan de mañana", "No se puede corregir"], "correcta": 1, "explicacion": "Las órdenes aprobadas se editan con ✏️ Editar."},
 {"id": "p4", "pregunta": "Después de aprobar, aparece \"OF modificadas desde el último plan\". ¿Qué significa?", "opciones": ["Que hubo un error", "Que el cambio se incorporará en la próxima corrida del plan (06:00)", "Que hay que regenerar el plan a mano", "Que la orden se anuló"], "correcta": 1, "explicacion": "El aviso se apaga solo cuando el plan de la mañana incorpora los cambios."},
 {"id": "p5", "pregunta": "¿Qué hace ↩ Retirar aprobación?", "opciones": ["Borra la orden del sistema", "Devuelve la orden a sugerida", "La envía a planta", "Cambia el responsable"], "correcta": 1, "explicacion": "La orden vuelve a ser una propuesta del sistema."}
]
```
