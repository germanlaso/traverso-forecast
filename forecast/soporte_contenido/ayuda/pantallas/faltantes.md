---
titulo: Faltantes
seccion: Control
resumen: Informe diario de pedidos no despachados y su causa.
orden: 40
actualizado: 2026-11-11
---
## Para qué sirve
Muestra los [[g:faltante]]s: cantidades de pedidos ([[g:ov]]) que no se despacharon, y si la causa fue falta de stock o vida útil. Es un análisis de lo que ya pasó, con datos hasta ayer.

## Qué muestra
- Filtros: rango de fechas (**Desde** / **Hasta**), SKU y causa.
- Gráfico **Faltante diario (cajas)**: una barra por día.
- Detalle del día seleccionado por SKU, con la causa, la explicación, la solución propuesta y la fecha estimada de reposición.

## Cómo se usa
1. Elige el rango de fechas.
2. Haz clic en una barra para ver el detalle de ese día (por defecto se muestra el último día disponible).
3. Completa la **explicación** y la **solución** de cada faltante cuando corresponda. Se guardan al escribir.
4. Usa **↓ Excel** para descargar el informe del día.

## Cómo leer los datos
- **[[g:sin-stock]]** (rojo): no había stock suficiente; apunta a producción.
- **[[g:vu-insuficiente]]** (ámbar): había stock, pero sin la [[g:vu]] que exige el cliente; apunta a rotación.
- **Mixta**: el faltante del día tiene ambas causas.
- Cuando el informe ya se envió, la explicación queda como "Enviada — no editable".
- Un asterisco en el stock indica que ese día no tenía foto de stock y se usó la anterior más cercana.
- El informe se envía por correo todos los días a las 8:00 y a las 11:00.

## Pantallas relacionadas
Resumen 30d · Stock Diario · Mapa de Quiebres
