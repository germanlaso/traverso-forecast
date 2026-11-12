// version.js — Versión de la app (fuente única). Se muestra en la barra superior y enlaza a
// Ayuda > Novedades (forecast/soporte_contenido/ayuda/novedades.md).
//
// Criterio (vigente desde 12-11-2026):
//   MAYOR  cambia la etapa o la forma de trabajar de los usuarios (p. ej. ingreso con cuenta Microsoft).
//   MENOR  pantalla o funcionalidad nueva, o cambio visible en menús, flujos o en la lógica del plan.
//   PARCHE corrección o ajuste sin cambio en cómo se usa.
//   Cambios internos sin efecto visible (scripts, cron, diagnóstico) no suben versión.
// Al subir versión: (1) actualizar VERSION y FECHA_VERSION, (2) agregar la entrada en novedades.md,
// (3) tras el deploy, tag de git: git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z
// Historia: v1.x = piloto (tags v1.0 … v1.3-piloto-ready). v2.0.0 = primera versión numerada post-piloto.
export const VERSION = '2.2.0';
export const FECHA_VERSION = '12-11-2026';
