---
titulo: Eventos
seccion: Forecast
resumen: Registro de periodos con venta anormal para que el forecast no los repita.
orden: 21
actualizado: 2026-11-11
---
## Para qué sirve
Permite registrar un [[g:evento]]: un periodo en que la venta de un producto fue anormal por una causa conocida (por ejemplo, un quiebre del competidor). Así el [[g:forecast]] no proyecta ese pico o caída como si fuera normal.

## Qué muestra
- **Eventos registrados**, con su estado (activo o inactivo).
- Formulario **Registrar un evento pasado**: producto, nombre, desde y hasta.
- Vista previa del efecto: venta real de esas semanas, venta habitual (misma semana de otros años) y cómo quedaría el forecast sin corregir y con la corrección.

## Cómo se usa
1. Busca el producto por código o nombre.
2. Ponle un nombre descriptivo (por ejemplo, "quiebre del competidor 2024") e indica las fechas.
3. Revisa la vista previa: compara la venta real con la habitual.
4. Guarda. Si no se pudo comprobar el efecto, el sistema avisa y permite **Guardar de todos modos**.
5. Para dejar de aplicar un evento, usa **Desactivar**.

## Cómo leer los datos
- La corrección se aplica en la **próxima corrida del plan** (al día siguiente a las 06:00), no de inmediato.
- Si cambias las fechas después de ver la vista previa, se vuelve a calcular: el sistema no guarda sin haber mostrado el efecto real.

## Pantallas relacionadas
Forecast de Demanda · Precisión Forecast
