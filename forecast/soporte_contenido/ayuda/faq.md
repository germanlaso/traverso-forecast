---
titulo: Preguntas frecuentes
seccion: General
resumen: Respuestas a las dudas más comunes.
orden: 900
actualizado: 2026-11-12
---
## ¿Cómo se genera el plan? ¿Puedo regenerarlo?
El plan se genera solo todos los días a las **06:00** y no se regenera a mano: no hay botón "Generar plan" en ninguna pantalla. Si un día no hay plan vigente, avisa a Planificación. Si apruebas, editas o creas órdenes durante el día, esas órdenes **son válidas de inmediato**. La barra superior muestra **"⚠ OF modificadas desde el último plan"** solo para avisar que hay cambios posteriores al último plan; el plan de la mañana siguiente los incorpora a sus proyecciones y el aviso se apaga.

## Cambié un parámetro y el plan no cambió. ¿Por qué?
Los cambios de parámetros, campañas y eventos se aplican en la **próxima corrida del plan** (al día siguiente a las 06:00).

## ¿Dónde apruebo las órdenes de fabricación?
En [[a:detalle|Detalle Producción]]: cada orden pendiente tiene su botón **Aprobar**.

## ¿Qué diferencia hay entre una OF sugerida y una aprobada?
La [[g:oft]] es una propuesta del sistema. La [[g:of-aprobada]] la revisó el planificador y queda fija en el plan.

## ¿Qué diferencia hay entre "quiebre" y "bajo SS"?
[[g:quiebre]] es stock proyectado bajo cero. [[g:bajo-ss]] es bajo el stock de seguridad, pero sobre cero.

## El SS aparece en días en un lugar y en cajas en otro. ¿Cuál vale?
Ambos. El [[g:ss]] se define en días hábiles de cobertura y el sistema lo convierte a cajas para los gráficos y estadísticas.

## ¿Por qué no hay un botón para actualizar el stock?
El stock viene del datalake, que se actualiza una vez al día. La fecha de esa actualización se ve en [[a:detalle|Detalle Producción]].

## ¿Mostacín puede aprobar órdenes o cambiar parámetros?
No. Mostacín (el Chat de consultas) solo responde y te lleva a la pantalla donde se hace el cambio.

## ¿Por qué me pide el PIN?
Editar parámetros o decidir casos de análisis requiere el [[g:pin]], tu nombre y un motivo. Así cada cambio queda registrado y se puede revertir.

## ¿Qué hay de nuevo en la app?
La versión vigente aparece en la barra superior. Al hacer clic se abren las [[a:novedades|Novedades]].
