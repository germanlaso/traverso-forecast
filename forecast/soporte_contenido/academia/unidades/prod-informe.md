---
titulo: Informe semanal y Base de conocimiento
objetivo: Leer el informe automático de cada lunes y entender lo que el sistema aprende de los datos y las decisiones.
minutos: 10
puntos: 100
version: 1
ayuda: informeia,aprendido
por_que: El informe semanal resume en un documento lo que pasó y sugiere dónde mirar. La Base de conocimiento guarda lo que funcionó y lo que no, para que cada nuevo análisis parta de la experiencia de la planta y no de cero.
desafio: Abre el último Informe semanal y busca qué línea destaca. Luego, en Base de conocimiento, revisa su capacidad real frente al 100% parametrizado.
---
## Informe semanal
![Informe semanal](prod__informe.png)

Está en **Informes → Informe semanal**. Se genera solo cada lunes por la mañana.
1. **Abrir en pestaña nueva**: para leerlo completo.
2. **Imprimir / PDF**: para guardarlo o compartirlo (A4 apaisado).

Incluye los indicadores de la semana, la comparación de programas y una lectura con observaciones generada por IA. La lectura es una ayuda para el análisis, no una decisión.

## Base de conocimiento
![Base de conocimiento: capacidad real](prod__conocimiento.png)

Está en **Informes → Base de conocimiento**.
1. **Capacidad real vs parametrizada**: lo que cada línea produce de verdad (punto verde: promedio de las 3 mejores semanas; punto gris: semana normal) frente al 100% con que planifica el sistema, con una lectura por línea.

![Base de conocimiento: intervenciones y descartes](prod__conocimiento_2.png)

2. **Intervenciones**: qué se cambió, qué se esperaba y qué pasó. Se evalúan solas a los 7 días (preliminar) y a los 14 (veredicto).
3. **Recomendaciones descartadas y por qué**: los motivos también enseñan; la IA los considera en los próximos análisis de la línea. (En la imagen, los motivos aparecen difuminados porque pueden mencionar información de clientes.)

```cuestionario
[
 {"id": "p1", "pregunta": "¿Cuándo se genera el Informe semanal?", "opciones": ["Cuando alguien lo pide", "Solo, cada lunes por la mañana", "Cada día a las 06:00", "Una vez al mes"], "correcta": 1, "explicacion": "El informe automático se genera cada lunes."},
 {"id": "p2", "pregunta": "La lectura de la IA en el informe sugiere revisar una línea. ¿Qué es esa sugerencia?", "opciones": ["Una orden que se aplica sola", "Una ayuda para el análisis: alguien la revisa y decide", "Un cambio de parámetros ya hecho", "Un error"], "correcta": 1, "explicacion": "Las sugerencias se revisan antes de aplicarse."},
 {"id": "p3", "pregunta": "En Base de conocimiento, el punto verde de una línea está en 85%. ¿Qué indica?", "opciones": ["Que en sus mejores semanas produce el 85% de su capacidad parametrizada", "Que tiene 85% de cumplimiento", "Que el forecast tiene 85% de error", "Que está detenida el 15% del tiempo"], "correcta": 0, "explicacion": "El punto verde es el promedio de las 3 mejores semanas frente al 100% con que planifica el sistema."},
 {"id": "p4", "pregunta": "¿Para qué sirve escribir el motivo cuando se descarta una recomendación?", "opciones": ["Es solo un trámite", "La IA lo considera en los próximos análisis de esa línea", "Para el informe de faltantes", "Para el forecast"], "correcta": 1, "explicacion": "Los motivos de descarte también enseñan al sistema."}
]
```
