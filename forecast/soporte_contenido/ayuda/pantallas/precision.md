---
titulo: Precisión Forecast
seccion: Forecast
resumen: Venta real vs lo que el forecast predijo con 1 y 2 semanas de anticipación.
orden: 22
actualizado: 2026-11-12
---
Está en **Forecast → Precisión Forecast** y también en **Informes → Precisión Forecast**.

## Para qué sirve
Mide qué tan bien acierta el [[g:forecast]]. Compara la venta real con lo que se pronosticó con **1 semana** y con **2 semanas** de anticipación. Cada anticipación se evalúa por separado y nunca se mezclan.

## Qué muestra
- Selector de anticipación (1 o 2 semanas) y filtros por SKU, categoría, línea y rango de semanas.
- Indicadores: [[g:sesgo]] neto, [[g:wmape]], venta real y forecast en cajas, semanas evaluadas.
- Dos vistas del gráfico: **Forecast vs real vs año anterior** (lo pronosticado, lo vendido y el año anterior, semana a semana) y **Desviación** (sesgo y WMAPE de cada semana).
- Tabla por SKU con su desviación.

## Cómo se usa
1. Elige la anticipación.
2. Filtra por categoría o línea si quieres acotar.
3. Haz clic en una semana cerrada del gráfico para ver solo esa semana en la tabla.
4. Haz clic en una fila de la tabla para ver la evolución de ese SKU en el gráfico.

## Cómo leer los datos
- **Sesgo sobre 0**: el forecast sobredimensiona → riesgo de sobrestock (ámbar).
- **Sesgo bajo 0**: subdimensiona → riesgo de quiebre (rojo).
- **WMAPE** mide la magnitud del error; a diferencia del sesgo, los errores de distintos SKU no se compensan.
- La zona gris del gráfico es la semana en curso y las próximas: aún no hay venta real.
- Si una semana no tiene forecast para esa anticipación, aparece como hueco (no se interpola).
- "Bajo vol.": SKU con venta promedio bajo el umbral; no se informa su %.

## Pantallas relacionadas
[[a:forecast|Forecast de Demanda]] · [[a:eventos|Eventos]]
