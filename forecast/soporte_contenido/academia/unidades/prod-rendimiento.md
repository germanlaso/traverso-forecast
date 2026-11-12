---
titulo: Rendimiento: cumplimiento, ocupación y eficiencia
objetivo: Leer cómo rindió cada línea en la semana y qué explica las diferencias.
minutos: 12
puntos: 100
version: 1
ayuda: rendimiento
por_que: Estos tres números cuentan la historia de la semana. El cumplimiento dice si se produjo lo que se programó, la ocupación cuánto se usó la línea y la eficiencia qué tan bien se aprovechó el tiempo en que funcionó.
desafio: En Rendimiento, elige la última semana cerrada y encuentra la línea con menor cumplimiento. Luego revisa si tuvo eventos en la bitácora.
---
## Paso a paso
![Rendimiento](prod__rendimiento.png)

Está en **Informes → Rendimiento**.
1. **Período**, categoría y línea: los filtros de arriba.
2. **Programado en SAP vs producido real**: cajas por semana y [[g:cumplimiento]] (real ÷ programado en SAP).
3. **Ocupación por línea**: cuánto se usó cada línea respecto de sus horas nominales.
4. **Detalle por línea**: los indicadores de cada línea, incluida la [[g:eficiencia]] cuando hay bitácora.

Más abajo están los **eventos de la bitácora** del período, el **evolutivo por línea** (clic para ampliar), los **mayores desvíos por SKU**, la producción **fuera de líneas MRP** y la **calidad de datos**.

## Cómo leer los indicadores
- **Cumplimiento** = cajas producidas ÷ cajas programadas en SAP.
- **Ocupación** = horas equivalentes de producción ÷ [[g:horas-nominales]]. Las horas nominales siguen el calendario de turnos de la línea (por defecto la [[g:jornada-42h]]) y no cuentan los feriados.
- **Eficiencia** = producción real ÷ producción teórica en las horas de funcionamiento. Solo con bitácora.
- Las semanas van de lunes a domingo; el asterisco (*) marca una semana parcial o en curso.

```cuestionario
[
 {"id": "p1", "pregunta": "Una línea tuvo 70% de cumplimiento. ¿Qué significa?", "opciones": ["Que estuvo ocupada el 70% del tiempo", "Que produjo el 70% de las cajas programadas en SAP", "Que su eficiencia fue 70%", "Que el forecast acertó en 70%"], "correcta": 1, "explicacion": "Cumplimiento = producido ÷ programado en SAP."},
 {"id": "p2", "pregunta": "¿Por qué la eficiencia de una línea aparece vacía algunos días?", "opciones": ["Por un error del sistema", "Porque esos días no tienen bitácora", "Porque fue feriado", "Porque no hubo forecast"], "correcta": 1, "explicacion": "La eficiencia se calcula solo con bitácora, que indica las horas de funcionamiento."},
 {"id": "p3", "pregunta": "¿Las horas nominales cuentan los feriados?", "opciones": ["Sí", "No: siguen el calendario de turnos y no cuentan feriados", "Solo los domingos", "Depende del usuario"], "correcta": 1, "explicacion": "Por eso la ocupación de una semana con feriado se mide sobre menos horas."},
 {"id": "p4", "pregunta": "¿Qué indica el asterisco (*) junto a una semana?", "opciones": ["Que tuvo feriado", "Que es una semana parcial o en curso", "Que tuvo paradas", "Que fue la mejor semana"], "correcta": 1, "explicacion": "Las semanas en curso o parciales se marcan con asterisco: sus cifras aún no están cerradas."}
]
```
