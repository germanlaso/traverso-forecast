---
titulo: Faltantes y Resumen 30d
objetivo: Revisar los pedidos no despachados, su causa, y qué productos fallan con más frecuencia.
minutos: 10
puntos: 100
version: 1
ayuda: faltantes,resumen30
por_que: Un faltante es un cliente que no recibió lo que pidió. Entender si fue por falta de stock o por vida útil te dice si el problema está en la producción o en la rotación.
desafio: En Resumen 30d, encuentra el producto con más días con faltante y luego revisa en Faltantes la causa de su último faltante.
---
## Faltantes del día
![Faltantes](plan__faltantes.png)

1. **Rango de fechas** y filtros por SKU y causa.
2. **Indicadores**: faltante del rango y del día, separado por causa.
3. **Faltante diario**: haz clic en una barra para ver el detalle de ese día.
4. **Detalle por SKU**, con la causa, la explicación y la solución propuesta, y **↓ Excel** para descargarlo.

Causas:
- **[[g:sin-stock]]**: no había stock suficiente; apunta a producción.
- **[[g:vu-insuficiente]]**: había stock, pero sin la vida útil que exige el cliente; apunta a rotación.

El informe llega por correo todos los días a las 8:00 y a las 11:00, con datos hasta ayer.

## Resumen de 30 días
En [[a:resumen30|Resumen 30d]], cada fila es un producto con faltante y cada celda un día: amarillo de 1 a 20 cajas, naranja de 21 a 60 y rojo sobre 60.

```cuestionario
[
 {"id": "p1", "pregunta": "Un faltante tiene causa \"VU insuficiente\". ¿Dónde está el problema?", "opciones": ["En producción: no se fabricó", "En la rotación: había stock pero sin la vida útil que exige el cliente", "En el forecast", "En el transporte"], "correcta": 1, "explicacion": "VU insuficiente significa que había stock, pero no lo suficientemente fresco para ese cliente."},
 {"id": "p2", "pregunta": "¿Con datos de qué día trabaja el informe de faltantes?", "opciones": ["En tiempo real", "Hasta ayer", "De la semana pasada", "Del mes anterior"], "correcta": 1, "explicacion": "Es un análisis de lo que ya pasó, con datos hasta el día anterior."},
 {"id": "p3", "pregunta": "En Resumen 30d, una celda está en rojo. ¿Qué significa?", "opciones": ["Más de 60 cajas faltantes ese día", "Que el producto está en quiebre proyectado", "Que no hubo venta", "Que la causa fue VU"], "correcta": 0, "explicacion": "Rojo = más de 60 cajas de faltante ese día."},
 {"id": "p4", "pregunta": "¿Cómo ves el detalle de un día específico en Faltantes?", "opciones": ["Haciendo clic en su barra del gráfico", "Descargando el Excel", "En la bitácora", "No se puede"], "correcta": 0, "explicacion": "Cada barra del gráfico abre el detalle de ese día."}
]
```
