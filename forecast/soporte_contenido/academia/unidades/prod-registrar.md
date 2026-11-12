---
titulo: Registrar un evento en la bitácora
objetivo: Anotar lo que pasa en una línea, con su tipo, máquina y horario de inicio y fin.
minutos: 10
puntos: 100
version: 2
ayuda: bitacora,detalle
por_que: La bitácora es la voz de la planta en el sistema. Sin ella, una caída de producción parece un mal plan; con ella, se sabe que fue una falla de la tapadora de 45 minutos, y los indicadores y el análisis de capacidad lo toman en cuenta.
desafio: Abre la bitácora de un día desde la grilla de Detalle Producción, completa la hora de inicio y fin de un evento de prueba y revisa cuántos minutos calcula. Ciérrala sin registrar.
---
Hay **dos formas** de registrar un evento. Usa la que te quede más cómoda: el resultado es el mismo.

## Forma 1: desde la pestaña Bitácora
![Formulario de la pestaña Bitácora](prod__bitacora_form.png)

Está en **Planificación → Bitácora**.
1. **Registrado por**: tu nombre y apellido. Queda recordado en este equipo.
2. **Tipo de evento**: por ejemplo, una parada no planificada, una parada planificada o un día sin programa. Antes elige la **fecha** y la **línea**.
3. **Hora inicio**: cuándo empezó el evento.
4. **Hora fin**: cuándo terminó. Los minutos se calculan solos y aparecen junto a la etiqueta, incluso si el evento pasó la medianoche.
5. **Máquina** (por ejemplo, llenadora o tapadora): opcional, igual que el **SKU** y el **comentario**, pero ayudan mucho a entender qué pasó.

Si no conoces el horario, escribe directamente la **duración (min)**. Termina con **Registrar evento**.

Esta forma sirve cuando registras varios eventos seguidos o de distintas líneas y fechas.

## Forma 2: desde la grilla de Detalle Producción
![Bitácora desde la grilla](prod__bitacora_grilla.png)

En **Planificación → Detalle Producción**, cada día de cada línea tiene un acceso a la bitácora (el ícono junto al día; si ya hay eventos, muestra los minutos registrados). Al hacer clic se abre una ventana con **los eventos de esa línea y ese día** y el mismo formulario, con la línea y la fecha ya puestas:
1. **Hora inicio** y 2. **Hora fin**: la duración se calcula sola.
3. **Máquina** (opcional) y los demás datos.

Esta forma sirve cuando estás revisando la semana de una línea y quieres anotar o ver lo que pasó ese día sin salir de la grilla. En días futuros, la ventana indica qué eventos **restan horas al plan**.

## Para qué se usa lo que registras
- Los minutos de detención aparecen en la grilla de Detalle Producción (en rojo si hubo paradas no planificadas).
- La **eficiencia** de una línea solo se calcula en los días con bitácora.
- El análisis de capacidad y el informe semanal usan estos eventos para explicar por qué una línea no cumplió.

```cuestionario
[
 {"id": "p1", "pregunta": "Una llenadora estuvo detenida de 23:30 a 00:15. ¿Cómo lo registras?", "opciones": ["No se puede, cruza la medianoche", "Hora inicio 23:30 y hora fin 00:15: el sistema calcula 45 minutos", "Dos eventos separados, uno por día", "Solo con comentario"], "correcta": 1, "explicacion": "La duración se calcula sola, incluso si el evento pasa la medianoche."},
 {"id": "p2", "pregunta": "No sabes a qué hora empezó y terminó una parada, pero sabes que duró unos 30 minutos. ¿Qué haces?", "opciones": ["No la registro", "Escribo 30 en duración (min)", "Invento un horario", "Le pido a Mostacín que la registre"], "correcta": 1, "explicacion": "Si no conoces el horario, se registra directamente la duración en minutos."},
 {"id": "p3", "pregunta": "¿Por qué conviene indicar la máquina?", "opciones": ["Es obligatorio", "Porque permite saber qué equipo causa las detenciones y analizarlas por máquina", "Para calcular el forecast", "No sirve de nada"], "correcta": 1, "explicacion": "La máquina es opcional, pero permite ver qué equipos concentran las detenciones."},
 {"id": "p5", "pregunta": "Estás revisando la semana de una línea en Detalle Producción y recuerdas una parada del martes. ¿Cómo la registras sin salir de la grilla?", "opciones": ["No se puede: hay que ir a la pestaña Bitácora", "Con el acceso a la bitácora del martes de esa línea, que abre el formulario con la línea y la fecha ya puestas", "Creando una OF manual", "Con un comentario en la orden"], "correcta": 1, "explicacion": "Cada día de la grilla tiene acceso a la bitácora, con la línea y la fecha ya completadas."},
 {"id": "p4", "pregunta": "¿Qué indicador solo se calcula en los días que tienen bitácora?", "opciones": ["El forecast", "La eficiencia de la línea", "El stock de seguridad", "Los faltantes"], "correcta": 1, "explicacion": "La eficiencia necesita las horas de funcionamiento, que salen de la bitácora."}
]
```
