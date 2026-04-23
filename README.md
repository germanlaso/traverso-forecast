# Traverso S.A. — Piloto de Forecast de Demanda
## Guía de instalación y uso — Windows + Docker Desktop

---

## Requisitos previos

- Docker Desktop instalado y corriendo (ícono en la barra de tareas)
- Acceso a la red de Traverso (VPN activa si estás fuera de la oficina)
- Git (opcional, para clonar el repositorio)

---

## Paso 1 — Configurar la conexión a SQL Server

Abre el archivo `.env` en la raíz del proyecto y edita los valores:

```env
SQL_SERVER=192.168.1.50        # IP o nombre del servidor SQL
SQL_DATABASE=Ventas            # Nombre de la base de datos
SQL_USERNAME=usuario_lectura   # Usuario con permisos SELECT
SQL_PASSWORD=tu_password       # Contraseña
```

> **Nota:** Si aún no tienes acceso al SQL, puedes usar el modo CSV
> poniendo tu archivo de ventas en `forecast/data/ventas.csv`.
> El sistema lo detecta automáticamente desde el dashboard.

---

## Paso 2 — Configurar la query de ventas

Abre `forecast/db.py` y edita la variable `SALES_QUERY` con los nombres
reales de tu tabla y columnas:

```python
SALES_QUERY = """
SELECT
    CAST(tu_columna_fecha AS DATE)   AS fecha,
    tu_columna_sku                   AS sku,
    tu_columna_descripcion           AS descripcion,
    SUM(tu_columna_cantidad)         AS cantidad
FROM
    tu_tabla_ventas
WHERE
    tu_columna_fecha >= DATEADD(MONTH, -48, GETDATE())
    AND tu_columna_cantidad > 0
GROUP BY
    CAST(tu_columna_fecha AS DATE), tu_columna_sku, tu_columna_descripcion
ORDER BY sku, fecha
"""
```

---

## Paso 3 — Levantar el sistema

Abre una terminal (PowerShell o CMD) en la carpeta del proyecto:

```powershell
# Construir e iniciar todos los servicios
docker-compose up --build

# La primera vez tarda ~5-8 minutos (descarga dependencias Python y Node)
# Las veces siguientes: ~30 segundos
```

Verás logs de los dos servicios. Cuando aparezca:
```
traverso_forecast | INFO: Application startup complete.
traverso_dashboard | Compiled successfully!
```
...el sistema está listo.

---

## Paso 4 — Acceder al sistema

| Servicio       | URL                          | Descripción                    |
|----------------|------------------------------|--------------------------------|
| Dashboard      | http://localhost:3000        | Interfaz principal de forecast |
| API (docs)     | http://localhost:8000/docs   | Documentación interactiva API  |
| Health check   | http://localhost:8000/health | Estado de conexión SQL         |

---

## Paso 5 — Generar tu primer forecast

1. Abre http://localhost:3000
2. Verifica que aparezca **"● SQL conectado"** en la barra superior
   - Si aparece error, revisa el `.env` y que la VPN esté activa
3. Selecciona un SKU del listado
4. Elige el horizonte de forecast (12 meses recomendado)
5. Haz clic en **"▶ Generar forecast"**
6. El primer entrenamiento tarda 30-90 segundos por SKU
7. Los entrenamientos siguientes son instantáneos (modelo en caché)

---

## Modo CSV (sin conexión SQL)

Si no tienes acceso al SQL aún, exporta un CSV de ventas con estas columnas:

```
fecha,sku,descripcion,cantidad
2022-01-01,SKU-001,Detergente 1L,1250
2022-01-01,SKU-002,Suavizante 2L,890
...
```

1. Copia el archivo a `forecast/data/ventas.csv`
2. En el dashboard, activa **"CSV (modo offline)"**
3. Ingresa la ruta `/app/data/ventas.csv`
4. El sistema cargará los datos del CSV

---

## Ajustes comerciales (regressores)

En el panel "Ajustes comerciales":

1. **Activa** el checkbox del evento
2. **Ingresa las fechas** afectadas separadas por coma: `2025-02-01, 2025-02-28`
3. **Ajusta el valor** de impacto:
   - `1.25` = la demanda aumenta 25% (promo, lanzamiento)
   - `0.85` = la demanda baja 15% (nuevo competidor, crisis)
4. Haz clic en **"↺ Reentrenar"** para incorporar el evento al modelo

---

## Comandos útiles

```powershell
# Detener el sistema
docker-compose down

# Ver logs en tiempo real
docker-compose logs -f

# Reiniciar solo el motor de forecast
docker-compose restart forecast

# Entrar al contenedor para debug
docker exec -it traverso_forecast bash

# Limpiar modelos entrenados (para empezar de cero)
docker volume rm traverso-pilot_forecast_models
```

---

## Migración a cloud (cuando estés listo)

El sistema está containerizado: migrar a cloud es copiar los mismos
archivos a un servidor Linux y correr:

```bash
# En el servidor cloud (DigitalOcean, AWS, etc.)
git clone tu-repo traverso-pilot
cd traverso-pilot
# Editar .env con credenciales de producción + IP del SQL vía VPN Fortinet
docker-compose up -d
```

No hay ningún cambio de código. El mismo `docker-compose.yml` funciona
en local y en producción.

---

## Estructura del proyecto

```
traverso-pilot/
├── docker-compose.yml      # Orquestación de servicios
├── .env                    # Credenciales SQL (NO subir a Git)
├── forecast/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py             # API FastAPI (endpoints)
│   ├── forecaster.py       # Motor Prophet (entrenamiento, forecast)
│   ├── db.py               # Conexión SQL Server + extracción
│   ├── models/             # Modelos entrenados (persistidos en volumen)
│   └── data/               # CSVs de ventas (modo offline)
└── dashboard/
    ├── Dockerfile
    ├── package.json
    ├── public/index.html
    └── src/App.js          # Dashboard React completo
```

---

## Soporte y próximos pasos

Una vez validado el piloto con los primeros SKUs, los siguientes pasos son:

1. **Entrenar todos los SKUs** — usar el endpoint `/train/batch` con la lista completa
2. **Configurar retraining mensual** — job automático que compara real vs. forecast
3. **Migrar a cloud** — DigitalOcean Droplet + VPN Fortinet headless
4. **Conectar módulo MRP** — plan de producción basado en el forecast

---

*Traverso S.A. · Gerencia de Producción · Piloto v1.0 · Abril 2026*
