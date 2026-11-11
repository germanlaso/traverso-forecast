---
titulo: Stock Diario
seccion: Planificación
resumen: Proyección diaria del stock de un SKU, separando forecast y pedidos.
orden: 30
actualizado: 2026-11-11
---
## Para qué sirve
Muestra, día a día, cómo evoluciona el stock de un SKU según el [[g:plan-vigente]]: qué demanda viene (forecast y pedidos), qué producción entra y cuándo quedaría [[g:bajo-ss]] o en [[g:quiebre]].

## Qué muestra
- Buscador de SKU por código o nombre.
- Indicadores: stock físico, comprometido (OV vencidas), disponible inicial, stock final, stock mínimo y [[g:ss]] en días hábiles (los SKU [[g:mto]] muestran "MTO (0)").
- Gráfico diario con: forecast, pedidos ([[g:ov]]), [[g:oft|OF sugerida]] propuesta, [[g:of-aprobada]] u [[g:ofm]], stock disponible y línea de stock de seguridad.
- Marcas de **Quiebre** y **Bajo SS**.

## Cómo se usa
1. Busca el SKU.
2. Pasa el mouse sobre un día para ver el desglose: forecast, pedidos, demanda corregida, stock y SS.
3. Si ves un quiebre, revisa si hay una OF sugerida antes de esa fecha y apruébala desde **Plan de Producción** o **Detalle Producción**.

## Cómo leer los datos
- **Quiebre** = stock proyectado bajo cero. **Bajo SS** = bajo el stock de seguridad pero sobre cero.
- El SS se define en días hábiles, pero en el gráfico se muestra en cajas.
- Los números vienen del sistema y ya incluyen las OF aprobadas vigentes; la pantalla no recalcula nada.
- Si aparece el aviso de que el plan es anterior al detalle diario, hay que esperar la próxima corrida del plan.

## Pantallas relacionadas
Mapa de Quiebres · Detalle Producción · Plan de Producción
