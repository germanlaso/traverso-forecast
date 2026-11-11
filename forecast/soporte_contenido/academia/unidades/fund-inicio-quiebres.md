---
titulo: Inicio y Mapa de Quiebres
objetivo: Leer el resumen del plan y encontrar qué productos quiebran, en qué línea y en qué semana.
minutos: 10
puntos: 100
version: 1
ayuda: home,quiebres
por_que: El objetivo número uno de la planificación es evitar quiebres. Estas dos pantallas te dicen en un minuto dónde está el problema.
desafio: En el Mapa de Quiebres, filtra "Solo quiebre", encuentra la línea con más SKU en quiebre y abre el Stock Diario de uno de sus SKU.
---
## Inicio: el estado del plan de un vistazo
![Panel de inicio](fund__inicio.png)

1. **SKU en quiebre**: productos cuyo stock proyectado queda bajo cero en el horizonte del plan.
2. **SKU en riesgo**: stock muy cerca de cero.
3. **SKU bajo SS**: bajo el stock de seguridad, pero sobre cero.
4. **Ver Mapa de Quiebres**: te lleva al detalle por línea y semana.

## Mapa de Quiebres: dónde y cuándo
![Mapa de Quiebres](fund__quiebres.png)

1. **Filtros**: Todos, Riesgo y quiebre, o Solo quiebre. Empieza por "Solo quiebre".
2. **Resumen de la línea**: cuántos SKU y cuántos días en quiebre tiene.
3. **Recepción pendiente**: hay una OF lanzada que no se ve en el stock. El quiebre puede ser falso o hay producción sin registrar: vale la pena revisarlo.

Colores de cada semana: sin color = OK · amarillo claro = bajo SS · naranja = riesgo · rojo = quiebre.
- Haz clic en una celda para ver los días afectados.
- Haz clic en el código del SKU para abrir su stock día a día.

```cuestionario
[
 {"id": "p1", "pregunta": "En el Mapa de Quiebres, una celda está en rojo. ¿Qué significa?", "opciones": ["El SKU está bajo el SS", "El stock proyectado queda bajo cero esa semana", "El SKU no tiene forecast", "Hay una OF aprobada esa semana"], "correcta": 1, "explicacion": "Rojo es quiebre: stock proyectado bajo cero."},
 {"id": "p2", "pregunta": "Un SKU muestra \"recepción pendiente\". ¿Qué deberías pensar?", "opciones": ["Que el quiebre es seguro", "Que hay una OF lanzada que no se refleja en el stock: el quiebre podría ser falso", "Que el proveedor no entregó", "Que el SKU es MTO"], "correcta": 1, "explicacion": "Hay producción lanzada que no se ve en el stock. Conviene revisar antes de actuar."},
 {"id": "p3", "pregunta": "¿Cómo abres el stock día a día de un SKU desde el Mapa de Quiebres?", "opciones": ["Haciendo clic en el código del SKU", "No se puede desde ahí", "Con el botón \"?\"", "Desde Herramientas"], "correcta": 0, "explicacion": "Al hacer clic en el SKU se abre su proyección de stock."},
 {"id": "p4", "pregunta": "¿Qué filtro conviene usar primero para ver lo más urgente?", "opciones": ["Todos", "Riesgo y quiebre", "Solo quiebre", "Ninguno"], "correcta": 2, "explicacion": "\"Solo quiebre\" muestra únicamente los SKU que quedan bajo cero."}
]
```
