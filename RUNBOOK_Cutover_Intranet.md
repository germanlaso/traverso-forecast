# RUNBOOK — Cutover a Intranet (Planificación de Producción)

**Objetivo:** publicar el dashboard bajo `intranet.traverso.cl/planificacion` a través del
reverse proxy de TI (Apache en `180.2.1.53:4433`), cambiando el contenedor `dashboard` de
modo dev a **build de producción**.

**Radio de impacto:** solo el contenedor `dashboard`. El backend (`forecast`), la BD
(`mrp_db`) y los crones **no se tocan** en el cutover. Un fallo del cutover NO afecta al
forecast ni a los correos automáticos.

**Duración estimada:** 10–15 min (build ~2–3 min + verificación).

---

## Arquitectura del proxy (confirmada por TI)

| Petición pública (proxy :4433) | Se reenvía a | Strip |
|---|---|---|
| `/planificacion/api/...` | `180.1.1.18:8000/...` | quita `/planificacion/api` |
| `/planificacion/static/...` | `180.1.1.18:3000/static/...` | quita `/planificacion` |
| `/planificacion/...` | `180.1.1.18:3000/...` | quita `/planificacion` |

La regla de `/api` se evalúa **antes** que la general. La app compila con
`PUBLIC_URL=/planificacion` (assets) y `REACT_APP_API_BASE=/planificacion/api` (llamadas).

---

## 0. Precondiciones — verificar ANTES de agendar la ventana

- [ ] **TI confirmó** que la regla de assets es por **prefijo** (`/planificacion/static/`),
      no por el archivo literal `bundle.js`. El build genera nombres con hash
      (`main.<hash>.js`), chunks y `.css`.
- [ ] **TI confirmó** que el proxy está activo en `:4433` con las 3 reglas de arriba.
- [ ] Repo al día en el server (`git pull` sin pendientes):
      - `dashboard/Dockerfile.prod`
      - `dashboard/src/App.js` (hardening + ErrorBoundary + BACKEND_URL env-aware)
      - `dashboard/src/components/*` (los 11 con `const API` env-aware)
      - `docker-compose.yml` (dashboard → Dockerfile.prod + build args)
- [ ] Verificación de que no quedó ningún `const API` sin migrar (debe salir **vacío**):
      ```bash
      cd ~/traverso-forecast
      grep -rn "const API" dashboard/src/ | grep -v "REACT_APP_API_BASE"
      ```
- [ ] `docker-compose.dev-backup.yml` presente en la raíz del repo (para rollback).

---

## 1. Backups (primeros pasos de la ventana, antes de tocar nada)

```bash
cd ~/traverso-forecast

# Tag git del estado pre-cutover (por si hay que volver el código)
git tag cutover-intranet-$(date +%Y%m%d)
git push --tags

# Imagen dev del dashboard respaldada (para rollback RÁPIDO sin rebuild)
docker tag traverso-forecast-dashboard traverso-forecast-dashboard:dev-backup
docker images | grep dashboard
```

Confirmar que aparece `traverso-forecast-dashboard:dev-backup` antes de seguir.

---

## 2. Cutover — ejecutar en la ventana coordinada con TI

```bash
cd ~/traverso-forecast
git pull

# Build del dashboard de producción (assets /planificacion, API /planificacion/api)
docker compose build dashboard

# Swap: SOLO el dashboard
docker compose up -d dashboard
```

> ⚠️ **CRÍTICO:** usar `docker compose up -d dashboard` (con el nombre del servicio).
> **NUNCA** `docker compose up -d` a secas: recrearía el `forecast` y puede disparar el
> incidente conocido del `HANA_PWD` (toma un password stale de 19 chars → falla silenciosa
> de datos OV → correo falso de "0 faltantes").

Verificar arranque del contenedor:
```bash
docker compose ps dashboard
docker compose logs --tail 20 dashboard
```
Debe verse `serve` sirviendo en el puerto 3000 (no `react-scripts start`).

---

## 3. Verificación post-cutover (smoke test A TRAVÉS DEL PROXY)

Abrir `https://intranet.traverso.cl/planificacion` (o `http://180.2.1.53:4433/planificacion`)
y con DevTools (F12) abierto:

- [ ] **La UI carga completa** (topbar, tabs, formulario). NO pantalla en blanco.
- [ ] **Network → tildar Disable cache → recargar (Ctrl+Shift+R):**
  - [ ] Los assets `/planificacion/static/js/main.<hash>.js` y `.css` cargan en **200**
        (no 404). Si dan 404 → la regla de assets de TI no es por prefijo.
  - [ ] Las llamadas `/planificacion/api/...` (skus, health, dimensions, summary,
        aprobadas, vigente) cargan en **200** con JSON real (no `index.html`).
- [ ] **Pestañas con datos reales:**
  - [ ] Forecast: selecciona un SKU y genera forecast.
  - [ ] Faltantes: carga el listado.
  - [ ] Stock Diario: carga la proyección de un SKU.
  - [ ] Campañas: carga los calendarios.
  - [ ] Mapa de Quiebres: carga.
- [ ] **Descarga de PDF** de una OF aprobada (valida el fix de `BACKEND_URL`): el `<a href>`
      debe apuntar a `/planificacion/api/ordenes/<n>/pdf` y descargar el PDF.
- [ ] **Consola sin errores** de CORS ni `is not a function`.

Si algo falla de forma parcial (assets sí, datos no, o viceversa) → suele ser una de las
dos reglas del proxy. El banner rojo "No se pudieron cargar los datos" (ErrorBoundary)
indica que la app arrancó pero un endpoint respondió mal → mirar Network.

---

## 4. Rollback (si el cutover falla y hay que volver atrás YA)

Vuelve el dashboard a modo dev. Los usuarios acceden por LAN (`180.1.1.18:3000`) como antes.

```bash
cd ~/traverso-forecast
docker compose -f docker-compose.dev-backup.yml up -d dashboard
docker compose -f docker-compose.dev-backup.yml logs --tail 20 dashboard
```

- Levanta la imagen `:dev-backup` respaldada en el paso 1 (segundos, sin rebuild).
- **No afecta** forecast, mrp_db ni los crones (siguen corriendo intactos).
- Del lado de TI: pueden quitar el ítem del menú / la regla del proxy; no dependemos de
  que ellos deshagan nada para seguir operando por LAN.

Para volver a intentar el cutover más tarde: repetir desde el paso 2 con el compose normal
(`docker compose up -d dashboard`).

---

## 5. Post-cutover

- [ ] Avisar a TI que quedó OK.
- [ ] Monitorear las primeras horas (accesos, correos automáticos del cron siguen llegando).
- [ ] Confirmar que el cron de faltantes (8 AM Chile) corrió normal al día siguiente.

### Follow-ups anotados (no bloqueantes)
- Refactor de `const API` a un módulo compartido `dashboard/src/config.js` (elimina el
  anti-patrón de la constante repetida en 12 archivos).
- `docker-compose.override.yml` de dev si se quiere hot-reload en el server para iterar.
- Revisar si algún otro `<a href>` al backend usa rutas absolutas (hoy solo el PDF de OF).

---

## Referencia rápida de archivos tocados

| Archivo | Cambio |
|---|---|
| `dashboard/Dockerfile.prod` | Multi-stage: build + `serve -s build` en :3000 |
| `dashboard/src/App.js` | `API` env-aware, `BACKEND_URL` env-aware, ErrorBoundary, guards de arrays |
| `dashboard/src/components/*` (11) | `const API = process.env.REACT_APP_API_BASE \|\| ''` |
| `docker-compose.yml` | `dashboard` → `Dockerfile.prod` + build args, sin volúmenes |
| `docker-compose.dev-backup.yml` | Compose de rollback a dev |
