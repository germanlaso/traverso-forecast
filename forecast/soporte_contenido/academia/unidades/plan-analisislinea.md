---
titulo: Análisis de Línea: leer el semáforo
objetivo: Identificar qué líneas no alcanzan a cubrir lo que viene y cómo pedir un análisis.
minutos: 10
puntos: 100
version: 2
ayuda: analisislinea
por_que: Un quiebre por capacidad se ve venir semanas antes. El semáforo te avisa qué línea no va a alcanzar, a tiempo para extender un turno, mover producción o ajustar parámetros.
desafio: En Análisis de Línea, encuentra una línea "No cumple" y lee en su fila qué semana supera la capacidad y por qué.
---
## Paso a paso
![Análisis de Línea](plan__analisislinea.png)

Cada fila es una línea, ordenadas de la más comprometida a la menos:
1. **Estado**: **No cumple** (rojo), **En riesgo** (ámbar) u **OK** (verde), con el **por qué** al lado.
2. **Carga próx. 3 sem** y **Demostrada**: la [[g:carga-requerida]] de las próximas 3 semanas (la producción neta que hace falta: demanda menos stock disponible, manteniendo el stock de seguridad) y la [[g:capacidad-demostrada]] de la línea.
3. **Analizar**: en aproximadamente un minuto entrega las causas, las [[g:palancas]] en orden de esfuerzo y una recomendación.
4. **Análisis #N**: el análisis vigente de la línea, con "· por decidir" si espera una decisión. Los anteriores están en **Historial (n)**, solo para consulta.

En el gráfico de semanas de cada fila: la **barra** es la carga requerida, la **marca negra** lo programado en el plan, la **línea roja** la capacidad nominal (100%) y la **línea verde** la capacidad demostrada. El asterisco (S46*) marca la semana en curso.

## El semáforo
- **No cumple**: carga requerida sobre 95% en alguna de las próximas 3 semanas, o quiebre por capacidad desde la semana 2.
- **En riesgo**: carga sobre 85%, o quiebre inmediato en la semana 1 (pedidos o recepciones).
- **OK**: el resto.

Si la barra supera la marca negra, el plan no alcanzó a programar todo lo que la demanda pide. La capacidad nominal sigue el calendario de turnos de cada línea y no cuenta feriados.

## Un análisis vigente por línea
Cada línea tiene un solo análisis vigente: el más reciente. Cuando se abre uno nuevo, los anteriores que no se habían decidido quedan **"reemplazado por #N"** y ya no se deciden, porque sus cifras quedaron desactualizadas. Lo ya decidido se mantiene, y las acciones aceptadas que aún no se ejecutan aparecen en el vigente para cerrarlas.

**Nada se aplica solo**: el análisis recomienda y una persona decide. Decidir un caso (con PIN) se ve en la ruta Administración.

```cuestionario
[
 {"id": "p1", "pregunta": "Una línea aparece como \"No cumple\". ¿Qué puede significar?", "opciones": ["Que su carga requerida supera el 95% en alguna de las próximas 3 semanas", "Que tiene paradas no planificadas hoy", "Que no tiene forecast", "Que su producción real fue baja ayer"], "correcta": 0, "explicacion": "Rojo: carga sobre 95% en las próximas 3 semanas, o quiebre por capacidad desde la semana 2."},
 {"id": "p2", "pregunta": "En el gráfico de una línea, la barra supera la marca negra. ¿Qué indica?", "opciones": ["Que el plan programó más de lo necesario", "Que el plan no alcanzó a programar todo lo que pide la demanda", "Que la línea está detenida", "Nada importante"], "correcta": 1, "explicacion": "La barra es lo requerido y la marca negra lo programado."},
 {"id": "p3", "pregunta": "¿Qué representa la línea verde?", "opciones": ["La capacidad nominal", "La capacidad demostrada: lo que la línea ha producido realmente", "El forecast", "El stock de seguridad"], "correcta": 1, "explicacion": "La línea verde es la capacidad demostrada en las últimas semanas."},
 {"id": "p5", "pregunta": "Una línea tenía el análisis #12 sin decidir y hoy se abrió el #15. ¿Qué pasa con el #12?", "opciones": ["Se decide igual, junto con el #15", "Queda \"reemplazado por #15\": pasa al Historial y ya no se decide", "Se borra", "Cuenta como descartado"], "correcta": 1, "explicacion": "Solo el análisis vigente se decide. Los anteriores sin decidir quedan reemplazados, y eso no cuenta como descarte."},
 {"id": "p4", "pregunta": "¿El análisis aplica cambios automáticamente en los parámetros?", "opciones": ["Sí, siempre", "No: recomienda y una persona decide", "Solo en líneas rojas", "Solo de noche"], "correcta": 1, "explicacion": "El sistema propone; las decisiones las toma una persona."}
]
```
