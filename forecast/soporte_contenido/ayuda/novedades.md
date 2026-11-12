---
titulo: Novedades
seccion: General
resumen: Lo nuevo que puedes hacer con la app, versión por versión. Versión actual 2.1.2 (12-11-2026).
orden: 901
actualizado: 2026-11-12
---
La versión vigente aparece en la barra superior; al hacer clic se abre esta página. El número tiene tres partes: la primera cambia cuando cambia la forma de trabajar, la segunda cuando hay pantallas o funciones nuevas y la tercera con correcciones menores.

## Versión 2.1.2 — 12 de noviembre de 2026
Correcciones y ajustes de forma.

- **Análisis de Línea: carga requerida corregida.** Ahora mide la producción que realmente hace falta: la demanda menos el stock disponible, manteniendo el stock de seguridad. Antes sumaba toda la demanda, y las líneas con mucho stock aparecían más exigidas de lo que estaban. El mismo criterio se aplica al Informe semanal. Ver [[a:analisislinea|Análisis de Línea]].
- **Detalle Producción:** el selector muestra el número de semana junto a las fechas, y cada línea indica la semana que se está viendo.

## Versión 2.1.1 — 12 de noviembre de 2026
La Ayuda y la Academia quedaron al día con los menús nuevos y la jornada de 42 h:
- Cada artículo indica en qué sección del menú está la pantalla y enlaza a las pantallas relacionadas.
- [[a:detalle|Detalle Producción]]: cómo aprobar y crear órdenes, y qué significan la producción real y los minutos de detención.
- [[a:bitacora|Bitácora]]: cómo registrar la hora de inicio y fin de una parada (la duración se calcula sola).
- [[a:parametros|Parámetros]]: cómo configurar turnos con vigencia y excepciones por fecha.
- [[a:faq|Preguntas frecuentes]] renovadas y nuevos términos en el glosario: horas nominales, turno adicional y excepción de capacidad.
- Academia: la unidad "Moverse por la app y pedir ayuda" incluye la nueva sección Informes.

## Versión 2.1.0 — 12 de noviembre de 2026
La capacidad de las líneas se ajusta a la jornada laboral de 42 horas semanales.

### Capacidad con la jornada de 42 horas
- El plan calcula la capacidad de cada línea con la jornada de 42 horas: lunes y martes de 9 horas, y miércoles a viernes de 8 horas. Rige desde el plan del 13 de noviembre.
- Cada línea puede tener su propia jornada: horas por día en cada turno y hasta tres turnos. Un turno adicional puede tener fecha de inicio y de término, por ejemplo para una temporada.
- Las excepciones por fecha (un sábado trabajado, una extensión de turno o un día sin producción) se registran para ese día y el plan las considera.
- Las paradas planificadas y los bloqueos programados de la Bitácora siguen descontándose de la capacidad de ese día.
- Ver [[a:parametros|la ayuda de Parámetros]].

### Indicadores con la jornada nueva
- Rendimiento, Análisis de Línea y el Informe semanal miden la ocupación contra las horas de la jornada de 42 horas y ya no cuentan los feriados como días de trabajo. Por eso la ocupación de algunas semanas anteriores cambia, en especial las que tuvieron feriado. Ver [[a:rendimiento|Rendimiento]].

### Otras mejoras
- Detalle Producción ya no muestra el botón "Generar plan" cuando no hay plan cargado: el plan se genera automáticamente todos los días a las 06:00.

## Versión 2.0.0 — 12 de noviembre de 2026
La primera versión numerada después del piloto. Suma herramientas para controlar la operación de las líneas, análisis con inteligencia artificial y un módulo de soporte para aprender a usar la app.

### Menús reorganizados
Los menús se ordenaron para encontrar más rápido las herramientas existentes y las nuevas:
- **Planificación**: lo que se usa para armar y seguir el programa (Stock Diario, Detalle Producción, Campañas, Programación Diaria y Bitácora).
- **Control**: las alertas del día (Faltantes, Resumen 30d, Mapa de Quiebres y Análisis de Línea).
- **Informes** (nuevo): lectura y evaluación de resultados (Faltantes, Resumen 30d, Precisión Forecast, Rendimiento, Informe semanal y Base de conocimiento).
- **Herramientas**: configuración del sistema (Parámetros y Salud Datalake).
- **Soporte**: Ayuda, Academia, Chat de consultas y Novedades.
- La aprobación y edición de órdenes se hace en **Detalle Producción**; la antigua pantalla Plan de Producción ya no es necesaria.

### Bitácora de las líneas
Un registro de todo lo que afecta el funcionamiento de cada línea:
- Registra paradas no planificadas, mantenciones y otros eventos, con máquina, hora de inicio y término (la duración se calcula sola).
- Programa paradas o ventanas de detención futuras: el plan descuenta esas horas de la capacidad de la línea.
- Más detalle en [[a:bitacora|la ayuda de Bitácora]].

### Más información en Detalle Producción
- Producción real junto a lo programado, para comparar día a día.
- Registro de eventos de bitácora desde la misma grilla, sin cambiar de pantalla.
- Tiempos de detención por día y por máquina.
- Descarga del plan completo en CSV.
- Más detalle en [[a:detalle|la ayuda de Detalle Producción]].

### Análisis de la operación con inteligencia artificial
- **Informe semanal**: se genera automáticamente cada lunes. Evalúa en detalle el rendimiento de cada línea (cumplimiento, ocupación y riesgo de quiebre) y entrega una lectura con IA y recomendaciones concretas para el equipo de producción. Ver [[a:informeia|Informe semanal]].
- **Rendimiento**: indicadores semanales por línea, como cumplimiento del programa en cajas y ocupación. Ver [[a:rendimiento|Rendimiento]].
- **Análisis de Línea**: un semáforo de capacidad muestra qué líneas no alcanzan a cubrir su demanda. Para cada una propone alternativas en orden de esfuerzo (ajustar parámetros, extender turnos, usar otra línea) y recomendaciones de calibración de parámetros. El sistema revisa las líneas a diario, abre casos cuando detecta riesgo y valida durante la noche, con el optimizador, las alternativas propuestas. Ver [[a:analisislinea|Análisis de Línea]].
- **Base de conocimiento**: la IA va acumulando lo aprendido. Registra la capacidad real que demuestra cada línea frente a la teórica, y qué decisiones funcionaron y cuáles no, para mejorar sus próximas recomendaciones. Ver [[a:aprendido|Base de conocimiento]].

### Parámetros en la app
- Edición de batch mínimo, capacidad de bodega, velocidad de línea y factor de velocidad por SKU, protegida con PIN.
- Validaciones que bloquean valores inconsistentes y advierten de casos dudosos.
- Historial de cambios (quién y cuándo), con opción de revertir.
- Recomendaciones de ajuste que surgen del análisis de las líneas.
- Más detalle en [[a:parametros|la ayuda de Parámetros]].

### Un plan más completo
- Los SKU cuyo stock supera su capacidad de bodega ya no quedan fuera del plan, lo que reduce los quiebres proyectados.
- El aviso **"OF modificadas desde el último plan"** indica que hay cambios en órdenes que el plan automático de las 06:00 todavía no incorpora, y se apaga solo cuando los incorpora.

### Nuevo módulo de Soporte
- **Ayuda en línea**: toda la información para usar la app, con glosario, buscador y el botón "?" en cada pantalla, que abre la ayuda de lo que estás viendo. Ver [[a:faq|Preguntas frecuentes]].
- **Academia**: cursos rápidos sobre cada parte de la app, con cuestionarios. Ya está disponible la ruta Fundamentos.
- **Chat de consultas** (Mostacín): responde preguntas sobre cómo usar cualquier función de la app. Está en el menú Soporte y en el botón de abajo a la derecha de todas las pantallas. No ve datos ni modifica nada.

### Otras mejoras
- **Forecast de Demanda**: el pronóstico aparece solo al elegir SKU, canal o semanas. Ver [[a:forecast|Forecast de Demanda]].
- **Barra superior**: muestra la fecha, la semana y la versión de la app.

## Antes de la versión 2.0.0
- **Octubre 2026 — Precisión Forecast**: compara la venta real con el forecast hecho con 1 y 2 semanas de anticipación. Ver [[a:precision|Precisión Forecast]].
