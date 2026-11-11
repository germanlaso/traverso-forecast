---
titulo: El ciclo diario del sistema
objetivo: Entender qué hace el sistema cada día y qué decide el planificador.
minutos: 8
puntos: 100
version: 1
ayuda: plan,home
por_que: El sistema propone, pero las decisiones son tuyas. Si sabes en qué momento del día pasa cada cosa, sabrás cuándo mirar y qué esperar de cada pantalla.
---
## Explicación
El sistema reemplaza la planificación manual en Excel por un ciclo automático que se repite todos los días. Tiene cinco etapas:

1. **Forecast**: cada domingo el modelo se reentrena con la historia de ventas y proyecta la venta semanal de cada SKU ([[g:forecast]]).
2. **Plan**: todos los días a las **06:00** el sistema genera el [[g:plan-vigente]]. Combina el forecast, los pedidos ([[g:ov]]), el stock y la capacidad de las líneas, y propone órdenes de fabricación ([[g:oft|OF sugeridas]]).
3. **Aprobación**: el planificador revisa las sugerencias y aprueba las que corresponden. Una [[g:of-aprobada]] queda fija: el sistema la respeta en las siguientes corridas.
4. **Producción**: las órdenes aprobadas forman el programa que se entrega a planta (Programación Diaria).
5. **Control**: el sistema mide lo que pasó. Informe de [[g:faltante|faltantes]] a las 8:00 y 11:00, bitácora de las líneas, rendimiento y análisis de capacidad.

## Lo que el sistema NO hace
- No aprueba órdenes solo.
- No cambia parámetros solo: cuando detecta un problema, **recomienda** y una persona decide.
- Los cambios de parámetros, campañas y eventos se aplican en la **próxima corrida del plan** (al día siguiente a las 06:00).

```cuestionario
[
 {"id": "p1", "pregunta": "¿A qué hora se genera el plan de producción cada día?", "opciones": ["A las 06:00, de forma automática", "Cuando el planificador presiona Generar plan", "A las 11:00, junto con el informe de faltantes", "Una vez por semana, el domingo"], "correcta": 0, "explicacion": "El plan se genera solo todos los días a las 06:00. El botón Generar plan está deshabilitado a propósito."},
 {"id": "p2", "pregunta": "¿Qué pasa con una OF sugerida que el planificador no aprueba?", "opciones": ["Se envía igual a planta", "Sigue siendo una propuesta y el sistema puede cambiarla en la próxima corrida", "Se borra del sistema para siempre", "Se aprueba sola al día siguiente"], "correcta": 1, "explicacion": "La OF sugerida es una propuesta. Solo al aprobarla queda fija en el plan."},
 {"id": "p3", "pregunta": "Cambiaste un parámetro hoy a las 15:00. ¿Cuándo se refleja en el plan?", "opciones": ["De inmediato", "En una hora", "En la próxima corrida del plan, mañana a las 06:00", "El próximo domingo"], "correcta": 2, "explicacion": "Los cambios de parámetros, campañas y eventos se aplican en la próxima corrida del plan."},
 {"id": "p4", "pregunta": "¿Cada cuánto se reentrena el modelo de forecast?", "opciones": ["Todos los días", "Cada domingo", "Una vez al mes", "Solo cuando alguien lo pide"], "correcta": 1, "explicacion": "El forecast se reentrena automáticamente cada domingo."}
]
```
