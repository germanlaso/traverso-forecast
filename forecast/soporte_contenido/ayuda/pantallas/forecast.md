---
titulo: Forecast de Demanda
seccion: Forecast
resumen: Pronóstico semanal de venta por SKU y su error histórico.
orden: 20
actualizado: 2026-11-11
---
## Para qué sirve
Muestra el [[g:forecast]] de un SKU: la venta histórica, la proyección semanal y qué tan preciso ha sido el modelo.

## Qué muestra
- Selección de **SKU**, cantidad de **semanas** y **canal**.
- Datos del producto: marca, categoría, semanas con venta, canales y zonas.
- Indicadores del modelo: **MAPE** (error promedio en %), **MAE** (error absoluto medio en unidades), semanas usadas para entrenar y forecast de la próxima semana.
- **Forecast semanal detallado** en tabla.
- **Ajustes comerciales**: permiten simular el efecto de un evento (por ejemplo, una promoción) activándolo con sus fechas.

## Cómo se usa
1. Elige el SKU y la cantidad de semanas.
2. Revisa el gráfico y la tabla semanal.
3. Si necesitas ver el efecto de un evento, actívalo en **Ajustes comerciales** e ingresa las fechas separadas por coma (AAAA-MM-DD).

## Cómo leer los datos
- El modelo se reentrena automáticamente cada domingo. **Reentrenar** fuerza un nuevo cálculo para el SKU seleccionado.
- Los ajustes comerciales de esta pantalla son una simulación. Para corregir la historia de forma permanente se usa la pantalla **Eventos**.
- Para evaluar la precisión real (venta vs lo pronosticado con anticipación) usa **Precisión Forecast**.

## Pantallas relacionadas
Eventos · Precisión Forecast
