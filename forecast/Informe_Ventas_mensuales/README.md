# Informe de Ventas y Stock por SKU

Informe diario automático que se envía por correo a las **9:00 (hora Chile)** con un
Excel adjunto: una fila por SKU con sus datos maestros, el stock del día y las ventas de
cada uno de los últimos meses.

Nació como un pedido puntual (una tabla de ventas 12 meses) que se repitió lo suficiente
como para automatizarlo.

---

## Qué contiene el informe

Una fila por SKU con:

| Columna | Origen |
|---|---|
| Cod SAP SKU, Nombre, Categoría | `dbo.ventas` (datalake) |
| **U por caja, Formato, Color** | `Parametros_Informe_Ventas.xlsx` (este directorio) |
| Stock del día (cajas) | `stock_actual.csv` — consolidado Traverso + Montaner |
| Una columna por mes | `dbo.ventas`, agregado mensual |
| Total del período | fórmula `SUM()` en el Excel |

Más una segunda hoja, **Excluidos** (ver más abajo).

### Ventana de meses: móvil
**12 meses enteros + el mes en curso.** Se recalcula cada día, así que el informe siempre
cubre el mismo período relativo sin mantenimiento.

Ejemplo: el 31-07-2026 el informe va de **2025-07 a 2026-07** (13 columnas). El
01-08-2026 pasa automáticamente a 2025-08 … 2026-08.

### Criterios de la venta
- **BRUTO**: sólo `Tipo Doc = 'Factura'`. **No** incluye notas de crédito ni de débito.
  Es facturación bruta, no venta neta de devoluciones.
- `Segmento = 'COMERCIAL'`, `Cantidad > 0`.
- Consolida las tres empresas (`dbo.ventas` ya trae TR/CS/MON juntas).
- **En cajas.**

### Criterios del stock
Snapshot de `stock_actual.csv`, el mismo que usa el plan de producción: Traverso +
Montaner consolidados, sólo las 3 bodegas despachables (`BSUR01`, `VESP01`, `VARA01`).
Ya viene en cajas (`UMED=CJ`).

**El stock se refresca cuando corre el plan** (cron 10:00 UTC). Como el informe sale a
las 13:00 UTC, siempre usa el stock de esa mañana. La fecha del snapshot va en el
encabezado de la columna, así que si el plan no corrió se nota.

---

## Las dos exclusiones

**1. Categoría `OTROS`** — reciclaje, recuperación de gastos y similares. No son productos.

**2. SKU sin `U por caja`** en el Excel de maestros. Se quitan de la hoja principal
**pero se listan en la hoja `Excluidos`** y en el cuerpo del correo, con su venta del
período.

> Esto último es deliberado y **no hay que sacarlo**. Un SKU nuevo que aparezca en
> ventas y que nadie cargue en el Excel de maestros desaparecería del informe sin dejar
> rastro, y con él sus ventas. Ejemplo real del primer día: `641071258 CAFÉ MELITTA` con
> 4.600 cajas de venta quedaba fuera. La hoja Excluidos es lo que hace visible ese hueco.

---

## El Excel de maestros

`Parametros_Informe_Ventas.xlsx` — la fuente de **U por caja, Formato y Color**.

**¿Por qué un archivo aparte y no `mrp_sku_params`?** Porque 81 de los 322 SKU del
informe **no están en el MRP** (importados, maquila, bundles, discontinuados). Los
parámetros del MRP sólo cubren lo que se planifica; el informe de ventas es más amplio.

- Se edita **en Excel** y se sube por `scp` (está gitignoreado, como el Excel de
  parámetros del MRP).
- Columnas: `SKU`, `Nombre`, `U por caja`, `Formato`, `Color`. Encabezados en la fila 3.
- **Color puede estar vacío** (hoy lo está en 230 de 322). No pasa nada: la celda queda
  en blanco.

### Cuidado con Excel y los porcentajes
Al escribir `60%` o `100%` en la columna Color, Excel los convierte a `0.6` y `1`. El
archivo actual ya está corregido a texto, pero si volvés a editar esos valores conviene
revisarlos. Afecta a: `123010160`, `123010260` (60%) y `124010150`, `124010151` (100%).

### Cuando aparece un SKU nuevo
1. Sale en la hoja **Excluidos** del informe y en el correo.
2. Agregarlo a `Parametros_Informe_Ventas.xlsx` con su U por caja (Formato y Color
   opcionales).
3. Subirlo por `scp` (comando abajo). Al día siguiente aparece en la hoja principal.

---

## Archivos

```
informe_ventas.py                  motor: consulta, arma la tabla y genera el Excel
enviar_informe_ventas.py           correo HTML + adjunto
cron_informe_ventas.py             wrapper del cron: genera, envía y limpia
Parametros_Informe_Ventas.xlsx     maestros (gitignoreado, se sube por scp)
salida/                            Excel generados (se limpian a los 15 días)
```

Los módulos usan `db.py` y `stock.py`, que viven en la raíz de la app. El shim de
`sys.path` al inicio de cada archivo se encarga de eso; `TRAVERSO_APP_DIR` permite
override si cambia el montaje.

---

## Configuración

En el `.env` (raíz del repo):

```
INFORME_VENTAS_DEST=renato@traverso.cl,fdiaz@traverso.cl,rvaldebenito@traverso.cl,glaso@traverso.cl
INFORME_VENTAS_ALERTA=          # opcional; si falta usa FALTANTES_ALERTA
```

Y **declararlas en el `environment:` del `docker-compose.yml`** (que está en la raíz):

```yaml
      - INFORME_VENTAS_DEST=${INFORME_VENTAS_DEST}
      - INFORME_VENTAS_ALERTA=${INFORME_VENTAS_ALERTA}
```

> El compose enumera las variables una por una: **lo que no se declara ahí llega vacío**
> aunque esté en el `.env`. Es una trampa que ya nos costó una vuelta con `VIGIA_DEST`.

`INFORME_VENTAS_DEST` es **obligatoria y no tiene fallback** a las listas de faltantes
ni del vigía: son públicos distintos y caer en otra lista mandaría el informe a quien no
corresponde, en silencio. Si falta, el proceso falla y el wrapper avisa al admin.

Otras variables opcionales: `INFORME_VENTAS_PARAMS` (ruta del Excel de maestros),
`INFORME_VENTAS_SALIDA` (directorio de salida).

---

## Cron

```
0 13 * * *   → 9:00 Chile, todos los días
```

```bash
0 13 * * * docker exec -e PYTHONPATH=/app -w /app/Informe_Ventas_mensuales \
  traverso_forecast python3 cron_informe_ventas.py \
  >> /home/ubuntu/traverso_informe_ventas.log 2>&1
```

Las 13:00 UTC dejan el stock ya refrescado por el cron del plan (10:00 UTC, ~75 min).

**La consulta a `dbo.ventas` tarda unos minutos** — la tabla no tiene índices (hallazgo
H7, pendiente con TI).

---

## Uso manual

```bash
# genera el Excel sin enviar correo
docker exec -e PYTHONPATH=/app -w /app/Informe_Ventas_mensuales traverso_forecast \
  python3 -u cron_informe_ventas.py --dry-run

# envío de prueba a una sola dirección
docker exec -e PYTHONPATH=/app -w /app/Informe_Ventas_mensuales \
  -e INFORME_VENTAS_DEST=glaso@traverso.cl traverso_forecast \
  python3 -u cron_informe_ventas.py

# una fecha distinta (recalcula la ventana de meses a esa fecha)
docker exec -e PYTHONPATH=/app -w /app/Informe_Ventas_mensuales traverso_forecast \
  python3 -u cron_informe_ventas.py --fecha 2026-06-30 --dry-run
```

Actualizar el Excel de maestros:

```powershell
scp ".\Parametros_Informe_Ventas.xlsx" "ubuntu@180.1.1.18:~/traverso-forecast/forecast/Informe_Ventas_mensuales/Parametros_Informe_Ventas.xlsx"
```

---

## Fail-safe

Si la generación falla (SQL Server caído, falta el Excel de maestros, stock vacío), **no
se envía el informe** y se manda una alerta **sólo al admin** diciendo explícitamente que
la ausencia de correo no significa que no haya ventas.

Es el mismo criterio del informe de faltantes y del vigía de OV: un cero silencioso es
peor que un error visible.

---

## Limitaciones conocidas

- **Ventas brutas, sin NC/ND.** Para la venta neta de devoluciones habría que incluir
  `Nota Credito` (que ya viene con cantidad negativa) y `ND`. Se decidió bruto a
  propósito; cambiarlo es una línea en el `WHERE`.
- **El stock es el del plan de la mañana**, no en vivo. Los despachos del día no se
  reflejan. Backlog: lectura de stock en vivo desde SAP (requiere TI).
- **El mes en curso está incompleto** por definición: la última columna no es comparable
  con las anteriores hasta que cierre el mes.
- **Color incompleto**: 230 de 322 SKU sin dato. Se completa editando el Excel de maestros.
