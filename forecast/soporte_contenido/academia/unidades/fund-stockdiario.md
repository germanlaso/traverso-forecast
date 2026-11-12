---
titulo: Stock Diario de un SKU
objetivo: Leer la proyección diaria de stock de un producto y detectar cuándo quedaría bajo SS o en quiebre.
minutos: 12
puntos: 100
version: 2
ayuda: stockdiario,stock
por_que: El Mapa de Quiebres te dice que hay un problema; el Stock Diario te dice cuándo empieza, por qué y si ya hay una orden que lo resuelve.
desafio: Busca un SKU que aparezca en quiebre en el Mapa de Quiebres y encuentra en su Stock Diario el primer día en que el estado deja de ser OK.
---
## Paso a paso
![Stock Diario de un SKU](fund__stockdiario.png)

1. **Buscador**: escribe el código o el nombre del SKU y elígelo de la lista.
2. **Stock de seguridad**: el SS en días hábiles (los SKU a pedido muestran "MTO (0)").
3. **Leyenda del gráfico**: barras de forecast y pedidos (OV), órdenes sugeridas y aprobadas, y las líneas de stock disponible y stock de seguridad.
4. **Tabla diaria**: stock disponible, pedidos, forecast, demanda corregida, órdenes y el **estado** de cada día.

## Cómo leerlo
- Si la línea de **stock disponible** cruza bajo la de **stock de seguridad**, ese día queda bajo SS. Si baja de cero, es quiebre.
- Pasa el mouse sobre un día para ver el desglose: forecast, pedidos, demanda corregida, stock y SS.
- Si hay una **OF sugerida** antes del quiebre, revísala y apruébala en [[a:detalle|Detalle Producción]].
- Las franjas de color del fondo son las campañas de la semana (granel o formato).

```cuestionario
[
 {"id": "p1", "pregunta": "En el gráfico, la línea de stock disponible baja de la línea de stock de seguridad pero sigue sobre cero. ¿Qué estado tiene ese día?", "opciones": ["Quiebre", "Bajo SS", "OK", "Riesgo de faltante"], "correcta": 1, "explicacion": "Bajo el SS pero sobre cero es bajo SS."},
 {"id": "p2", "pregunta": "¿Qué muestra el indicador \"SS (días hábiles)\" de un SKU a pedido?", "opciones": ["15 d", "MTO (0)", "Nada, queda vacío", "El SS en cajas"], "correcta": 1, "explicacion": "Los SKU a pedido no tienen stock de seguridad y se muestran como MTO (0)."},
 {"id": "p3", "pregunta": "Ves un quiebre el día 20 y una OF sugerida con entrada el día 18. ¿Qué haces?", "opciones": ["Nada: el sistema la aprueba solo", "La reviso y, si corresponde, la apruebo en Detalle Producción", "Borro la OF", "Cambio el forecast"], "correcta": 1, "explicacion": "La OF sugerida resolvería el quiebre, pero solo cuenta como compromiso cuando el planificador la aprueba."},
 {"id": "p4", "pregunta": "¿Cómo ves el detalle de un día (forecast, pedidos, demanda y SS)?", "opciones": ["Pasando el mouse sobre ese día en el gráfico", "Descargando un Excel", "Preguntando a producción", "No se puede"], "correcta": 0, "explicacion": "El tooltip del gráfico desglosa cada día."}
]
```
