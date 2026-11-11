---
titulo: Plan de Producción
seccion: Planificación
resumen: Órdenes sugeridas por el sistema, su aprobación y descarga del plan.
orden: 31
actualizado: 2026-11-11
---
## Para qué sirve
Es donde se revisan y aprueban las órdenes que propone el sistema. El plan se genera solo cada día a las 06:00; el planificador decide qué se aprueba.

## Qué muestra
- **Stock actual**: SKU, bodegas, total de cajas y fecha de la descarga.
- Indicadores: SKU planificados, órdenes sugeridas, órdenes aprobadas, SKU con alertas y [[g:horizonte]].
- Tabla de **órdenes de producción / abastecimiento sugeridas**, filtrable por línea.
- **Resumen semanal de emisión**.

## Cómo se usa
1. Filtra por línea si quieres revisar una a la vez.
2. Revisa cada [[g:oft]]: SKU, cantidad, fechas de lanzamiento y de entrada a stock.
3. Para aprobar, usa **Aprobar orden**. En la ventana:
   1. Ajusta la cantidad real a producir (cajas) y las fechas reales, si cambian.
   2. Indica el responsable (jefe de producción) y un comentario si corresponde.
   3. Confirma: la orden pasa a [[g:of-aprobada]] y recibe su número definitivo.
4. Para corregir una aprobación, usa **Editar aprobación**.
5. **Descargar plan (CSV)** baja todo el plan (sugerido y aprobado) para Excel.

## Cómo leer los datos
- El botón **Generar plan** está deshabilitado: el plan lo genera el proceso diario de las 06:00.
- El número de una OF sugerida es tentativo; el definitivo se asigna al aprobar.
- Una OF aprobada queda fija: el sistema la respeta en las siguientes corridas.

## Pantallas relacionadas
Detalle Producción · Programación Diaria · Stock Diario
