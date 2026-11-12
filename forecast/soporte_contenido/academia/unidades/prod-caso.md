---
titulo: Leer un análisis de línea
objetivo: Entender el análisis vigente de una línea, sus acciones recomendadas y qué se le pregunta a Producción.
minutos: 10
puntos: 100
version: 1
ayuda: analisislinea
por_que: Cuando una línea no alcanza, el análisis propone qué hacer: ajustar parámetros, extender turnos, usar otra línea o ampliar. Producción conoce la realidad de la planta, y su respuesta es clave para que la decisión sea buena.
desafio: En Análisis de Línea, abre el análisis vigente de una línea "No cumple" y lee sus acciones recomendadas y, si la tiene, la pregunta para Producción.
---
## Paso a paso
![Análisis vigente de una línea](prod__caso.png)

En **Control → Análisis de Línea**, presiona **Análisis #N** en una línea. Se abre su [[g:analisis-vigente]]:
1. **Acciones recomendadas (en orden de esfuerzo)**: cada una con su efecto y su costo o riesgo. Las [[g:palancas]] van de menor a mayor esfuerzo: parámetros, horas extra, línea alternativa y ampliación.
2. **Para Producción**: una pregunta concreta que el análisis le hace a la planta (por ejemplo, si es viable un turno adicional). Tu respuesta ayuda a decidir.
3. **Ver detalle del diagnóstico**: las causas detectadas, las palancas evaluadas y la evidencia.
4. **Tu decisión**: aceptar todo, aceptar solo algunas acciones o descartar, con nombre, PIN y motivo. Lo decide quien tiene el PIN; el detalle está en la ruta Administración.

## Bueno saber
- Solo el análisis vigente se decide. Los anteriores están en **Historial**, en solo lectura.
- **Validar con solver esta noche** comprueba una palanca con el optimizador (corre desde las 21:00).
- Nada se aplica solo: el sistema propone y una persona decide.

```cuestionario
[
 {"id": "p1", "pregunta": "¿En qué orden aparecen las acciones recomendadas?", "opciones": ["Por costo, de mayor a menor", "De menor a mayor esfuerzo: parámetros, horas extra, línea alternativa y ampliación", "Al azar", "Por fecha"], "correcta": 1, "explicacion": "Las palancas se ordenan por esfuerzo: primero lo más simple."},
 {"id": "p2", "pregunta": "El análisis muestra \"Para Producción: ¿es viable un segundo turno las próximas 2 semanas?\". ¿Qué es?", "opciones": ["Una orden ya aprobada", "Una pregunta a la planta cuya respuesta ayuda a decidir", "Un error del sistema", "Un evento de la bitácora"], "correcta": 1, "explicacion": "Es la pregunta concreta que el análisis le hace a Producción."},
 {"id": "p3", "pregunta": "¿Dónde ves las causas detectadas y la evidencia?", "opciones": ["En Ver detalle del diagnóstico", "En la Bitácora", "En Rendimiento", "No se muestran"], "correcta": 0, "explicacion": "El detalle del diagnóstico despliega causas, palancas y evidencia."},
 {"id": "p4", "pregunta": "¿Qué hace \"Validar con solver esta noche\"?", "opciones": ["Aplica la acción de inmediato", "Comprueba una palanca con el optimizador; corre desde las 21:00", "Borra el análisis", "Envía el informe semanal"], "correcta": 1, "explicacion": "La validación prueba la palanca con el solver durante la noche, sin aplicar cambios."}
]
```
