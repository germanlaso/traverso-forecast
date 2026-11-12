---
titulo: Forecast de Demanda y Eventos
objetivo: Leer el pronóstico de un SKU y saber cuándo registrar un evento para corregir su historia.
minutos: 12
puntos: 100
version: 1
ayuda: forecast,eventos
por_que: Todo el plan parte del forecast. Si una semana de venta fue anormal y nadie lo registra, el sistema la va a repetir como si fuera normal, y vas a producir de más o de menos.
desafio: Abre el forecast de la mostaza 261010255, revisa su MAPE y luego, en Eventos, mira si tiene algún evento registrado.
---
## Leer el forecast de un SKU
![Forecast de Demanda](plan__forecast.png)

1. **SKU**: escribe el código o el nombre y elígelo de la lista. El forecast se carga solo.
2. **Canal** y **semanas**: cambia el canal o el horizonte; también se recalcula solo.
3. **MAPE**: el error promedio del modelo para ese SKU, en %. Cuanto más bajo, más confiable el pronóstico.
4. **Forecast semanal detallado**: la tabla con lo que el sistema espera vender cada semana.

El modelo se reentrena automáticamente cada domingo con la historia de ventas.

## Registrar un evento
![Eventos](plan__eventos.png)

Un [[g:evento]] es un periodo en que la venta fue anormal por una causa conocida (por ejemplo, un quiebre del competidor que disparó la venta).
1. **Eventos registrados**: los que ya existen, activos o inactivos.
2. **Registrar un evento pasado**: elige el producto, ponle un nombre descriptivo y las fechas.
3. Revisa la vista previa: venta real de esas semanas frente a la venta habitual, y cómo quedaría el forecast con y sin la corrección.
4. Guarda. La corrección se aplica en la **próxima corrida del plan** (mañana a las 06:00).

```cuestionario
[
 {"id": "p1", "pregunta": "Cambias el canal en Forecast de Demanda. ¿Qué tienes que hacer para ver el nuevo pronóstico?", "opciones": ["Presionar Reentrenar", "Nada: se recalcula solo", "Esperar al domingo", "Descargar un Excel"], "correcta": 1, "explicacion": "El forecast se carga solo al cambiar SKU, canal o semanas."},
 {"id": "p2", "pregunta": "¿Qué indica un MAPE alto en un SKU?", "opciones": ["Que vende mucho", "Que el modelo se equivoca bastante en ese SKU", "Que está en quiebre", "Que es MTO"], "correcta": 1, "explicacion": "El MAPE es el error promedio del modelo: alto significa un pronóstico menos confiable."},
 {"id": "p3", "pregunta": "Hace dos meses un competidor quebró y la mostaza vendió el doble durante tres semanas. ¿Qué haces?", "opciones": ["Nada, el modelo lo entiende solo", "Registro un evento con esas fechas para que el forecast no repita ese pico", "Bajo el stock de seguridad", "Edito el forecast a mano"], "correcta": 1, "explicacion": "Un evento le dice al sistema que esas semanas fueron anormales, para que no las proyecte como normales."},
 {"id": "p4", "pregunta": "Registraste un evento hoy a las 15:00. ¿Cuándo se refleja en el plan?", "opciones": ["De inmediato", "En la próxima corrida del plan, mañana a las 06:00", "El próximo domingo", "Nunca, es solo informativo"], "correcta": 1, "explicacion": "Los eventos se aplican en la próxima corrida del plan."}
]
```
