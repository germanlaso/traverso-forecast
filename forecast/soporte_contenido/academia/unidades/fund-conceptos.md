---
titulo: Los conceptos clave
objetivo: Distinguir stock de seguridad, quiebre, bajo SS y los tipos de orden de fabricación.
minutos: 10
puntos: 100
version: 2
ayuda: stockdiario,detalle
por_que: Estas palabras aparecen en todas las pantallas. Si las tienes claras, cada número que ves tiene sentido y sabes cuándo preocuparte.
---
## Stock de seguridad (SS)
El [[g:ss]] es el stock mínimo que el plan busca mantener para absorber variaciones de la demanda. **Se define en días hábiles de cobertura**, pero en la mayoría de las pantallas y estadísticas se muestra convertido a **cajas**.

## Quiebre, bajo SS y riesgo
- **Quiebre**: el stock proyectado queda **bajo cero**. No alcanza para cubrir la demanda ([[g:quiebre]]).
- **Bajo SS**: el stock queda bajo el stock de seguridad, pero **sobre cero**. Es una alerta temprana ([[g:bajo-ss]]).
- **Riesgo**: en el Mapa de Quiebres, el stock queda muy cerca de cero (10% del SS o menos), sin llegar a quebrar.

## Tipos de órdenes
![Órdenes en Detalle Producción](fund__detalle_ordenes.png)

1. **OF sugerida (OFT)**, que en Detalle Producción aparece como **Pendiente**: la propone el sistema al generar el plan. Es una propuesta.
2. **OF aprobada** (✓ Aprobada): el planificador la revisó y aprobó en Detalle Producción. Queda fija en el plan.
3. **Urgente** (⚡): una OF sugerida cuya fecha de lanzamiento es hoy o ya pasó y todavía no está aprobada.

Además existe la **OFM**: una orden creada a mano por el planificador, que entra al plan como aprobada.

## Productos a pedido (MTO)
Un SKU [[g:mto]] se produce contra pedidos y no contra forecast. No tiene forecast propio y su SS es 0.

```cuestionario
[
 {"id": "p1", "pregunta": "El stock proyectado de un SKU queda en -50 cajas. ¿Cómo se llama esa situación?", "opciones": ["Bajo SS", "Riesgo", "Quiebre", "Normal"], "correcta": 2, "explicacion": "Quiebre es stock proyectado bajo cero."},
 {"id": "p2", "pregunta": "El SS de un SKU son 2.000 cajas y su stock proyectado es 1.500 cajas. ¿Cómo se llama?", "opciones": ["Quiebre", "Bajo SS", "Sin problema", "MTO"], "correcta": 1, "explicacion": "Está bajo el stock de seguridad pero sobre cero: bajo SS."},
 {"id": "p3", "pregunta": "¿En qué unidad se DEFINE el stock de seguridad?", "opciones": ["En cajas", "En unidades", "En días hábiles de cobertura", "En kilos"], "correcta": 2, "explicacion": "Se define en días hábiles de cobertura y el sistema lo convierte a cajas para mostrarlo."},
 {"id": "p4", "pregunta": "¿Qué diferencia a una OF sugerida de una OF aprobada?", "opciones": ["La sugerida la creó un planificador a mano", "La aprobada es una propuesta que el sistema puede cambiar", "La sugerida es una propuesta del sistema; la aprobada quedó fija en el plan", "No hay diferencia"], "correcta": 2, "explicacion": "La OF sugerida es una propuesta. La aprobada la revisó el planificador y el sistema la respeta."},
 {"id": "p5", "pregunta": "¿Por qué un SKU MTO tiene SS igual a 0?", "opciones": ["Porque está discontinuado", "Porque se produce contra pedidos, no contra forecast", "Porque es un error del sistema", "Porque es importado"], "correcta": 1, "explicacion": "Los SKU a pedido se fabrican cuando hay pedido, por eso no mantienen stock de seguridad."}
]
```
