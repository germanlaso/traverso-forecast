---
titulo: Crear una orden manual
objetivo: Crear una OF que el sistema no sugirió, respetando la capacidad disponible de la línea.
minutos: 8
puntos: 100
version: 1
ayuda: detalle
por_que: A veces sabes algo que el sistema no sabe: un pedido especial, una prueba o un cambio de último minuto. La orden manual te deja actuar sin esperar al plan, pero con la capacidad a la vista.
desafio: En Detalle Producción, abre "＋ Crear OF" en una línea, elige un SKU y mira cuánta capacidad libre queda ese día. Cierra con Cancelar, sin crear la orden.
---
## Paso a paso
![Crear OF manual](plan__crear_of.png)

En la línea, presiona **＋ Crear OF**. En la ventana:
1. **SKU**: aparecen los SKU de esa línea; con "ver todos los SKU" puedes elegir otro.
2. **Cantidad (cajas)**.
3. **Fecha de lanzamiento** (el día en que se produce en la línea).
4. **Libre** y **Consume esta OF**: cuánta capacidad tiene el día y cuánta usaría la orden.

Si la orden excede la capacidad del día, el sistema avisa, pero permite crearla (turno extra o criterio del planificador). **Crear OF** la guarda; **Cancelar** cierra sin crear.

## Bueno saber
- La orden manual ([[g:ofm]]) entra al plan como **aprobada**.
- No está sujeta a las campañas: sirve, por ejemplo, para un cambio de formato de emergencia.

```cuestionario
[
 {"id": "p1", "pregunta": "¿Con qué estado entra al plan una OF manual (OFM)?", "opciones": ["Sugerida", "Aprobada", "Urgente", "Pendiente de revisión"], "correcta": 1, "explicacion": "Las OFM entran como aprobadas."},
 {"id": "p2", "pregunta": "La orden que quieres crear excede la capacidad del día. ¿Qué pasa?", "opciones": ["El sistema la bloquea", "El sistema avisa, pero permite crearla", "Se crea en otra línea", "Se divide sola en dos días"], "correcta": 1, "explicacion": "Avisa del exceso; la decisión (turno extra, criterio) es del planificador."},
 {"id": "p3", "pregunta": "Necesitas producir un SKU que no aparece en la lista de la línea. ¿Qué haces?", "opciones": ["No se puede", "Uso \"ver todos los SKU\"", "Lo pido a sistemas", "Creo un evento"], "correcta": 1, "explicacion": "La opción ver todos los SKU amplía la lista."},
 {"id": "p4", "pregunta": "¿Una OF manual respeta las campañas de granel o formato?", "opciones": ["Sí, siempre", "No: las OF manuales no están sujetas a las campañas", "Solo los lunes", "Solo si es urgente"], "correcta": 1, "explicacion": "Por eso sirven para cambios de emergencia."}
]
```
