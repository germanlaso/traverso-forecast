---
titulo: Precisión del forecast
objetivo: Medir si el forecast acierta, distinguiendo sesgo (dirección del error) y WMAPE (tamaño del error).
minutos: 10
puntos: 100
version: 1
ayuda: precision
por_que: Un forecast que siempre se queda corto te lleva a quiebres; uno que siempre se pasa, a sobrestock. Saberlo a tiempo te permite anticiparte y registrar eventos donde hacen falta.
desafio: En Precisión Forecast, con 1 semana de anticipación, encuentra el SKU con mayor desviación de la última semana cerrada.
---
## Paso a paso
![Precisión del forecast](plan__precision.png)

1. **Anticipación**: compara la venta real con lo que se pronosticó **1 semana** o **2 semanas** antes. Cada una se evalúa por separado.
2. **Sesgo neto**: si es positivo, el forecast **sobredimensiona** (riesgo de sobrestock); si es negativo, **subdimensiona** (riesgo de quiebre).
3. **WMAPE**: el tamaño del error. A diferencia del sesgo, los errores de distintos SKU no se compensan.
4. **Forecast vs real vs año anterior**: muestra semana a semana lo pronosticado, lo vendido y lo que se vendió el año anterior. Es la forma más directa de ver si el forecast acierta. Con el botón **Desviación** cambias a la vista del sesgo y el WMAPE de cada semana.

En el gráfico, haz clic en una semana cerrada para ver solo esa semana en la tabla, y en una fila de la tabla para ver la evolución de ese SKU.

## Cómo usarlo en el día a día
- Un sesgo negativo persistente en un SKU es una señal para revisar si hubo un evento no registrado o un cambio de mercado.
- La zona gris del gráfico son semanas sin venta real todavía: no se evalúan.

```cuestionario
[
 {"id": "p1", "pregunta": "El sesgo neto de una categoría es -12%. ¿Qué significa?", "opciones": ["El forecast se pasó: riesgo de sobrestock", "El forecast se quedó corto: riesgo de quiebre", "El error es pequeño", "No hay datos"], "correcta": 1, "explicacion": "Sesgo bajo 0 = el forecast subdimensiona la venta: riesgo de quiebre."},
 {"id": "p2", "pregunta": "¿Por qué el WMAPE puede ser alto aunque el sesgo sea cercano a 0?", "opciones": ["Porque está mal calculado", "Porque los errores de distintos SKU se compensan en el sesgo, pero no en el WMAPE", "Porque solo mide un SKU", "Porque incluye la semana en curso"], "correcta": 1, "explicacion": "El sesgo suma errores con signo y se compensan; el WMAPE mide su tamaño sin compensar."},
 {"id": "p3", "pregunta": "¿Se mezclan en un mismo número la anticipación de 1 y de 2 semanas?", "opciones": ["Sí, se promedian", "No, cada anticipación se evalúa por separado", "Solo en el gráfico", "Solo para SKU MTO"], "correcta": 1, "explicacion": "Se eligen con el selector y nunca se mezclan."},
 {"id": "p4", "pregunta": "¿Cómo ves solo los SKU de una semana específica?", "opciones": ["Haciendo clic en esa semana cerrada del gráfico", "Descargando un Excel", "No se puede", "Cambiando la anticipación"], "correcta": 0, "explicacion": "Al hacer clic en una semana cerrada, la tabla se filtra a esa semana."}
]
```
