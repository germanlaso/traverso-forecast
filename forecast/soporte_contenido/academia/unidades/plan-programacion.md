---
titulo: Programación Diaria
objetivo: Generar el programa de producción para entregar a planta.
minutos: 6
puntos: 100
version: 1
ayuda: programacion
por_que: Es lo que llega a planta. Si una orden no está aprobada, no aparece aquí y nadie la va a producir.
---
## Paso a paso
![Programación Diaria](plan__programacion.png)

1. **Desde / Hasta**: el rango de días del programa.
2. **Líneas**: elige todas o solo algunas.
3. **🖨️ Imprimir / Guardar PDF**: genera el documento para planta.

El programa muestra, por día y por línea, las órdenes **aprobadas** con SKU, cajas, unidades, responsable y comentarios.

## Bueno saber
- Solo aparecen las órdenes aprobadas. Si falta una, apruébala en [[a:detalle|Detalle Producción]].

```cuestionario
[
 {"id": "p1", "pregunta": "Una orden sugerida no aparece en la Programación Diaria. ¿Por qué?", "opciones": ["Por un error del sistema", "Porque solo aparecen las órdenes aprobadas", "Porque es de otra semana siempre", "Porque es MTO"], "correcta": 1, "explicacion": "La Programación Diaria muestra solo órdenes aprobadas."},
 {"id": "p2", "pregunta": "¿Cómo entregas el programa a planta?", "opciones": ["Con 🖨️ Imprimir / Guardar PDF", "Descargando el forecast", "Desde la bitácora", "Por Mostacín"], "correcta": 0, "explicacion": "El botón genera el documento imprimible o el PDF."},
 {"id": "p3", "pregunta": "¿Puedes generar el programa solo para dos líneas?", "opciones": ["No, siempre son todas", "Sí, eligiendo las líneas", "Solo con PIN", "Solo los lunes"], "correcta": 1, "explicacion": "El selector de líneas permite elegir cuáles incluir."}
]
```
