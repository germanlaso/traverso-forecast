---
titulo: Análisis de Línea
seccion: Control
resumen: Semáforo de capacidad por línea, diagnóstico y acciones recomendadas.
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
  - **Barra**: carga requerida por la demanda.
  - **Marca negra**: [[g:uso-programado]] en el plan.
  - **Línea roja**: capacidad nominal (100%).
  - **Línea verde**: capacidad demostrada.
- **Análisis (n · m por decidir)**: casos abiertos de la línea, automáticos (los abre el sistema tras el plan diario) o manuales.

## Cómo se usa
1. Revisa las líneas **No cumple** y **En riesgo**.
2. Usa **Analizar** en una línea: en aproximadamente un minuto entrega causas, [[g:palancas]] en orden de esfuerzo y una recomendación.
3. Revisa las acciones recomendadas: efecto, costo o riesgo.
4. Si quieres comprobar una palanca, usa **Validar con solver esta noche** (se ejecuta desde las 21:00).
5. Registra **tu decisión**: aceptar todo, aceptar solo las acciones marcadas o descartar. Pide tu nombre, el [[g:pin]] y un motivo.

## Cómo leer los datos
- La capacidad nominal (100%) sigue el calendario de turnos de cada línea (por defecto la [[g:jornada-42h]]), sin contar feriados, e incluye turnos adicionales vigentes y excepciones por fecha.
- **No cumple** (rojo): carga requerida sobre 95% en alguna de las próximas 3 semanas, o quiebre por capacidad desde la semana 2.
- **En riesgo** (ámbar): carga sobre 85%, o quiebre inmediato en la semana 1.
- Si la barra supera la marca negra, el plan no alcanzó a programar lo que la demanda pide.
- **Nada se aplica solo**: los cambios de parámetros aceptados pasan como recomendaciones al panel de Parámetros.
- Los motivos de descarte también sirven: el sistema los considera en los próximos análisis.

## Pantallas relacionadas
[[a:aprendido|Base de conocimiento]] · [[a:parametros|Parámetros]] · [[a:quiebres|Mapa de Quiebres]]
