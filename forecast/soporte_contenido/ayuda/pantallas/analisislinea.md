---
titulo: Análisis de Línea
seccion: Control
resumen: Semáforo de capacidad por línea, análisis vigente con diagnóstico, acciones recomendadas y decisión.
orden: 48
actualizado: 2026-11-12
---
Está en **Control → Análisis de Línea**.

## Para qué sirve
Responde: **¿puede cada línea cumplir lo que viene?** Muestra el [[g:semaforo|semáforo]] de cada línea y, cuando una no está pudiendo cumplir, permite analizarla y decidir qué hacer.

## Qué muestra
- Una fila por línea, de la más comprometida a la menos, con su **estado** (**No cumple**, **En riesgo** u **OK**) y el **por qué**.
- **Carga próx. 3 sem** ([[g:carga-requerida]]) y **Demostrada** ([[g:capacidad-demostrada]]).
- Un gráfico por semana:
  - **Barra**: carga requerida, es decir, la producción neta que hace falta (demanda menos stock disponible, manteniendo el stock de seguridad).
  - **Marca negra**: [[g:uso-programado]] en el plan.
  - **Línea roja**: capacidad nominal (100%).
  - **Línea verde**: capacidad demostrada.
- **Análisis #N**: el [[g:analisis-vigente]] de la línea, con "· por decidir" si todavía no tiene decisión.
- **Historial (n)**: los análisis anteriores de la línea, solo para consulta.

## Cómo se usa
1. Revisa las líneas **No cumple** y **En riesgo**.
2. Usa **Analizar** en una línea: en aproximadamente un minuto entrega causas, [[g:palancas]] en orden de esfuerzo y una recomendación. Ese análisis pasa a ser el vigente.
3. Abre **Análisis #N** y revisa las acciones recomendadas: efecto, costo o riesgo.
4. Si quieres comprobar una palanca, usa **Validar con solver esta noche** (se ejecuta desde las 21:00).
5. Registra **tu decisión**: aceptar todo, aceptar solo las acciones marcadas o descartar. Pide tu nombre, el [[g:pin]] y un motivo.

## Un solo análisis vigente por línea
- Cada línea tiene **un análisis vigente**: el más reciente. Es el único que se decide y se valida con solver.
- Cuando se abre un análisis nuevo (manual o automático tras el plan diario), los anteriores **sin decidir** quedan **"reemplazado por #N"**: pasan al Historial en solo lectura, ya no se deciden y sus validaciones programadas se cancelan, porque sus cifras quedaron desactualizadas.
- Lo **ya decidido no cambia**. Si un análisis anterior tiene acciones aceptadas que aún no se ejecutan, aparecen en el vigente bajo **"Acciones pendientes de análisis anteriores de esta línea"**, para marcarlas como hechas o descartarlas (con tu nombre y PIN de la sección "Tu decisión"). Las que son cambios de parámetros se cierran al aplicarlas en Herramientas → Parámetros.
- Un análisis **reemplazado no es un descarte**: no cuenta como decisión para el aprendizaje del sistema.

## Cómo leer los datos
- La carga requerida es **neta de stock**: una línea con mucho stock de sus productos aparece menos exigida que si se mirara solo la demanda.
- La capacidad nominal (100%) sigue el calendario de turnos de cada línea (por defecto la [[g:jornada-42h]]), sin contar feriados, e incluye turnos adicionales vigentes y excepciones por fecha.
- **No cumple** (rojo): carga requerida sobre 95% en alguna de las próximas 3 semanas, o quiebre por capacidad desde la semana 2.
- **En riesgo** (ámbar): carga sobre 85%, o quiebre inmediato en la semana 1.
- Si la barra supera la marca negra, el plan no alcanzó a programar lo que hace falta producir.
- **Nada se aplica solo**: los cambios de parámetros aceptados pasan como recomendaciones al panel de Parámetros.
- Los motivos de descarte también sirven: el sistema los considera en los próximos análisis.

## Pantallas relacionadas
[[a:aprendido|Base de conocimiento]] · [[a:parametros|Parámetros]] · [[a:quiebres|Mapa de Quiebres]]
