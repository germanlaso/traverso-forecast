---
titulo: Campañas
objetivo: Leer y fijar las campañas semanales de granel y formato.
minutos: 8
puntos: 100
version: 1
ayuda: campanas
por_que: Cada cambio de granel o de formato cuesta tiempo de línea. Agrupar la producción por semanas ahorra esos cambios, y tú decides cuándo fijar la semana o dejar que el sistema la elija.
desafio: En Campañas, encuentra una semana propuesta por el optimizador (punteada) y una fijada por el planificador (con candado), si existen.
---
## Paso a paso
![Campañas](plan__campanas.png)

Una [[g:campana]] agrupa la producción por semana: por ejemplo, una semana de granel de ketchup y otra de mostaza.
1. **🔒 Fijado por el planificador**: el plan respeta esa semana.
2. **Propuesto por el optimizador**: lo que eligió el sistema en la última corrida.

Para fijar una semana, haz clic en la celda y elige la opción. Para devolverle la decisión al sistema, usa **Soltar (decide el plan)**.

## Bueno saber
- Los cambios se aplican en la **próxima corrida del plan**.
- Las órdenes manuales no están sujetas a la campaña.
- En Stock Diario, las franjas de color del fondo muestran la campaña de cada semana.

```cuestionario
[
 {"id": "p1", "pregunta": "Una celda tiene candado. ¿Qué significa?", "opciones": ["Que la semana está bloqueada para siempre", "Que la fijó el planificador y el plan la respeta", "Que no hay producción", "Que es un error"], "correcta": 1, "explicacion": "El candado indica una decisión del planificador que el plan respeta."},
 {"id": "p2", "pregunta": "¿Qué hace \"Soltar (decide el plan)\"?", "opciones": ["Borra la campaña", "Devuelve la decisión de esa semana al optimizador", "Aprueba las órdenes de la semana", "Cambia el granel"], "correcta": 1, "explicacion": "La semana vuelve a ser decidida por el sistema."},
 {"id": "p3", "pregunta": "Fijaste una campaña hoy. ¿Cuándo la toma el plan?", "opciones": ["De inmediato", "En la próxima corrida del plan", "El lunes", "Nunca"], "correcta": 1, "explicacion": "Como los demás cambios, se aplica en la próxima corrida."}
]
```
