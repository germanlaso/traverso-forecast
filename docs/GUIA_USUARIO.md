# Guía de uso — Sistema de Planificación de Producción

Bienvenido. Esta guía te ayuda a probar el nuevo sistema de planificación durante el piloto. Léela una vez antes de empezar — son 5 minutos.

---

## 1. Cómo entrar al sistema

**Desde la oficina:**

Abrí el navegador (Chrome o Edge) y andá a:

```
http://180.1.1.18:3000
```

**Desde fuera de la oficina:**

Conectate primero a la VPN de Traverso. Después accedés a la misma dirección.

**Si la página no carga:** verificá la VPN. Si igual no carga, escribime un mail (ver sección 6).

---

## 2. Qué vas a ver

La pantalla principal tiene cuatro pestañas en la parte superior. Acá te explico cada una en una línea:

- **Forecast de Demanda** — predicciones de venta por SKU para los próximos meses.
- **Plan de Producción** — qué producir, cuándo y en qué línea.
- **Stock por SKU** — cuánto stock vamos a tener en cada momento si seguimos el plan.
- **Detalle Producción** — qué se produce cada día, en qué línea y en qué orden.

---

## 3. Cómo usar el sistema (flujo típico)

Una sesión normal de prueba se ve así:

### Paso 1 — Actualizar stock real

Antes de generar un plan nuevo, asegurate de que el stock está al día. En la pestaña **Plan de Producción** vas a ver un botón para refrescar el stock. Hacelo si han pasado horas o días desde la última vez.

> Esto trae el stock real desde el ERP (puede tardar 30-60 segundos).

### Paso 2 — Generar el plan

Apretá el botón "Generar Plan" en la pestaña **Plan de Producción**. Por defecto el horizonte son 13 semanas, podés cambiarlo si querés.

> El plan tarda **alrededor de 1-2 minutos** en generarse. Es normal. Mientras tanto vas a ver una rueda girando.

### Paso 3 — Revisar el plan generado

Una vez que termine, mirá:

- **¿Cuántas órdenes se generaron?** (lo verás arriba: "X órdenes, Y alertas")
- **¿Hay alertas?** Las alertas indican SKUs que pueden quedarse sin stock. Mirá cuáles son y si te parecen razonables.
- **¿Las cantidades se ven razonables?** Comparalas mentalmente con lo que producirías en Excel.

### Paso 4 — Explorar las otras pestañas

Mirá:

- **Stock por SKU** para ver la proyección de stock semana a semana.
- **Detalle Producción** para ver el calendario diario por línea.

### Paso 5 — Aprobar o no

Si una orden te parece bien, la podés aprobar (esto la "fija" para futuras corridas del plan). Si no te parece, la podés cancelar.

> Las órdenes aprobadas se respetan en futuras corridas del plan. Las tentativas pueden cambiar.

---

## 4. Qué nos sirve mucho que pruebes

Estamos buscando feedback en estos puntos específicos. Si pruebas algo y notás algo en alguno de estos temas, **eso vale oro**:

### A. Realismo del plan vs. tu experiencia con Excel

- ¿Las cantidades sugeridas son parecidas a las que vos pondrías?
- ¿Las fechas de lanzamiento son razonables?
- ¿Asigna los SKUs a las líneas correctas?

### B. Casos raros

- ¿Algún SKU sale con cantidad rara (muy poca o muchísima)?
- ¿Algún día con producción inusual (mucha concentración o muy vacío)?
- ¿Alguna alerta que no entendés por qué aparece?

### C. Usabilidad

- ¿Hay algo que no se entiende en pantalla?
- ¿Falta algún dato que sería útil ver?
- ¿Algún número confuso o mal formateado?

---

## 5. Qué NO esperar todavía

El sistema está en **fase piloto**. Algunas cosas todavía no están:

- **Solo hay 18 SKUs cargados** (no los 263 que producimos). Son los del segmento COMERCIAL piloto.
- **El orden intra-día no está optimizado** todavía. Si en un día se producen 3 SKUs, el sistema asigna las cantidades pero no decide aún el orden óptimo. Eso viene en una versión futura.
- **La matriz de tiempos de cambio entre SKUs** todavía es uniforme (asume 30 minutos para cualquier cambio). Cuando tengamos datos reales del Gerente, va a ser más precisa.
- **Si algo se cae**, no va a haber arreglo inmediato — yo (German) voy a estar de vacaciones por dos semanas. El sistema está estable, pero si pasa algo crítico, esperá a mi vuelta.

---

## 6. Cómo reportar problemas o sugerencias

Mandame un mail a:

```
glaso@traverso.cl
```

**Importante:** poné en el asunto del mail, al inicio:

```
TEST MRP - <tu mensaje>
```

Por ejemplo:
- `TEST MRP - Cantidad rara en Vinagre Blanco`
- `TEST MRP - No me carga la pestaña Stock`
- `TEST MRP - Sugerencia de mejora`

Eso me ayuda a filtrar y revisarlos todos juntos cuando vuelva de vacaciones.

### Plantilla mínima del mail

Para que el reporte sea útil, incluí estos puntos. **No es complicado, pero hace toda la diferencia:**

```
Qué hice:
   (Ej: "Apreté Generar Plan con horizonte 13 semanas")

Qué esperaba que pasara:
   (Ej: "Que apareciera un plan con varias órdenes")

Qué pasó:
   (Ej: "Salió un error 500 / no apareció nada / tardó 5 min")

SKU o línea afectada (si aplica):
   (Ej: "SKU 121010210 Jugo Limón")

Captura de pantalla (si tenés):
   (Adjuntá una imagen — lo más útil es de la pantalla entera)
```

### Ejemplos

**Reporte poco útil:**

> *"No funciona el plan"*

(¿Qué no funciona? ¿En qué pestaña? ¿Qué error apareció?)

**Reporte útil:**

> *"Apreté Generar Plan con horizonte 13. Tardó 2 minutos y al terminar mostró 'Error 500' en rojo arriba. La pestaña Stock por SKU sigue mostrando datos viejos. Adjunto captura."*

---

## 7. Limitaciones conocidas (no son bugs)

Algunas cosas son lentas porque están así por diseño en esta versión piloto. **Si te encontrás con esto, no es un problema, es esperado:**

- **La primera vez que abrís la app**, la lista de SKUs puede tardar **30-60 segundos** en cargar. Es normal en esta versión. Va a mejorar.
- **Generar un plan tarda ~1-2 minutos**. El sistema está calculando muchas cosas (predicciones de demanda + optimización de producción). Es normal.
- **Si el sistema reinicia (raro)**, la primera carga puede tardar 2-3 minutos extra. También es normal.

---

## 8. Resumen rápido (para tener a mano)

- **URL**: `http://180.1.1.18:3000`
- **Mail para reportar**: `glaso@traverso.cl` con asunto `TEST MRP - ...`
- **Horizonte recomendado para plan**: 13 semanas
- **Refrescar stock antes de cada plan importante**
- **Plan tarda 1-2 min** (es normal)
- **Si algo crítico se rompe**, esperá a mi vuelta

---

Gracias por probar el sistema. Tu feedback durante estas semanas vale mucho — va a definir cómo evoluciona la herramienta.

— German
