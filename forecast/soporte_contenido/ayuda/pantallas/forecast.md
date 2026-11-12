---
titulo: Forecast de Demanda
seccion: Forecast
resumen: Pronóstico semanal de venta por SKU y su error histórico.
orden: 20
actualizado: 2026-11-12
---
## Para qué sirve
Muestra el [[g:forecast]] de un SKU: la venta histórica, la proyección semanal y qué tan preciso ha sido el modelo.

## Qué muestra
- Selección de **SKU**, **canal** y cantidad de **semanas**. El forecast se carga solo al cambiar cualquiera de ellos: no hay que presionar ningún botón.
- Datos del producto: marca, categoría, semanas con venta, canales y zonas.
- Indicadores del modelo: **MAPE** (error promedio en %), **MAE** (error absoluto medio en unidades), semanas usadas para entrenar y forecast de la próxima semana.
- **Forecast semanal detallado** en tabla.

## Cómo se usa
1. Elige el SKU, el canal y la cantidad de semanas.
2. Revisa el gráfico y la tabla semanal.

## Cómo leer los datos
- El modelo se reentrena automáticamente cada domingo; no se reentrena desde esta pantalla.
- Para corregir semanas con venta anormal (por ejemplo, un quiebre del competidor) se usa [[a:eventos|Eventos]]: la corrección se aplica en la próxima corrida del plan.
- Para evaluar la precisión real (venta vs lo pronosticado con anticipación) usa [[a:precision|Precisión Forecast]].

## Pantallas relacionadas
[[a:eventos|Eventos]] · [[a:precision|Precisión Forecast]]
