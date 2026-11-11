---
titulo: Salud Datalake
seccion: Control
resumen: Estado de la conexión con las bases de datos de origen (SQL Server y SAP HANA).
orden: 44
actualizado: 2026-11-11
---
## Para qué sirve
Muestra si el sistema se está conectando bien a sus fuentes de datos. Si una fuente falla, el plan o los informes pueden quedar desactualizados.

## Qué muestra
- Indicadores: latencia media y máxima de SQL Server, latencia media de HANA y estado de la conexión actual.
- Gráfico de latencia de conexión (ms), con las caídas en rojo y una banda con el estado de HANA.
- **Log de eventos**: cambios de estado y conexiones lentas (más de 1.000 ms).

## Cómo se usa
1. Revisa el estado de la conexión actual.
2. Para acercar un periodo, arrastra sobre el gráfico; el log se filtra a ese periodo.
3. Doble clic o **Restablecer zoom** vuelve a la vista completa.

## Cómo leer los datos
- Caídas o latencias altas sostenidas pueden explicar datos desfasados en otras pantallas. En ese caso, avisa al administrador.

## Pantallas relacionadas
Inicio
