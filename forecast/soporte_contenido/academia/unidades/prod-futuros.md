---
titulo: Eventos futuros y cómo anular
objetivo: Anotar paradas y bloqueos que vienen para que el plan los considere, y corregir un registro equivocado.
minutos: 8
puntos: 100
version: 1
ayuda: bitacora
por_que: Si producción sabe que la próxima semana se hace una mantención, anotarla en la bitácora hace que el plan no le asigne producción a esas horas. Así se evita prometer lo que la línea no podrá hacer.
desafio: En la Bitácora, revisa la lista de eventos y encuentra uno planificado para los próximos días, si lo hay.
---
## Eventos a futuro
![Lista de eventos de la bitácora](prod__bitacora_lista.png)

1. **Últimos 7 días y planificados (próximos 30)**: la lista de eventos, filtrable por línea.
2. **Anular**: corrige un evento registrado por error.

Para fechas futuras (hasta 90 días) solo se pueden anotar:
- **Parada planificada** y **bloqueo programado**: **restan esas horas al plan** desde la próxima corrida (06:00).
- **Línea sin programa**: deja constancia de que no se programará, pero **no** resta horas.

Los eventos futuros se registran igual que los demás: desde la pestaña Bitácora o desde la grilla de Detalle Producción (en un día futuro, la ventana indica que el evento bloquea horas del plan).

Si una parada planificada cambia de fecha o se cancela, anúlala y registra la nueva.

## Anular un evento
1. Escribe tu nombre en **Registrado por** (es quien anula).
2. Presiona **Anular** en el evento y confirma.
3. El evento no se borra: queda registrado como anulado, con quién lo anuló.

```cuestionario
[
 {"id": "p1", "pregunta": "La línea 3 tendrá mantención el próximo martes de 8:00 a 14:00. ¿Qué registras?", "opciones": ["Nada, el plan lo sabe", "Una parada planificada con ese horario: restará esas horas al plan", "Un comentario en Detalle Producción", "Un evento de forecast"], "correcta": 1, "explicacion": "Las paradas planificadas futuras restan horas al plan desde la próxima corrida."},
 {"id": "p2", "pregunta": "¿Qué evento futuro NO resta horas al plan?", "opciones": ["Parada planificada", "Bloqueo programado", "Línea sin programa", "Todos restan horas"], "correcta": 2, "explicacion": "\"Sin programa\" deja constancia, pero no resta horas."},
 {"id": "p3", "pregunta": "Registraste un evento en la línea equivocada. ¿Qué haces?", "opciones": ["Lo borro", "Lo anulo (con mi nombre en Registrado por) y registro el correcto", "Lo dejo así", "Pido que lo borren en la base de datos"], "correcta": 1, "explicacion": "Los eventos no se borran: se anulan y queda constancia de quién lo hizo."},
 {"id": "p4", "pregunta": "¿Hasta cuántos días hacia adelante se pueden anotar eventos?", "opciones": ["7", "30", "90", "Sin límite"], "correcta": 2, "explicacion": "Se pueden anotar hasta 90 días a futuro."}
]
```
