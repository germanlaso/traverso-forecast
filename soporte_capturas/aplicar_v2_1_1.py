"""aplicar_v2_1_1.py — Sube la versión a 2.1.1 y agrega su entrada en Novedades (una sola vez).
Se corre desde la raíz del repo DESPUÉS de git pull:  python soporte_capturas\\aplicar_v2_1_1.py
No pisa lo que otros chats escribieron: edita version.js y novedades.md del repo en su lugar."""
import re, sys
from pathlib import Path

V = Path("dashboard/src/version.js"); N = Path("forecast/soporte_contenido/ayuda/novedades.md")
v = V.read_text(encoding="utf-8"); n = N.read_text(encoding="utf-8")
if "## Versión 2.1.1" in n:
    sys.exit("Novedades ya tiene la entrada 2.1.1: nada que hacer.")
if "export const VERSION = '2.1.0';" not in v or "## Versión 2.1.0" not in n:
    sys.exit("La versión vigente no es 2.1.0: revisa con git pull antes de aplicar. No se cambió nada.")
ENTRADA = """## Versión 2.1.1 — 12 de noviembre de 2026
La Ayuda y la Academia quedaron al día con los menús nuevos y la jornada de 42 h:
- Cada artículo indica en qué sección del menú está la pantalla y enlaza a las pantallas relacionadas.
- [[a:detalle|Detalle Producción]]: cómo aprobar y crear órdenes, y qué significan la producción real y los minutos de detención.
- [[a:bitacora|Bitácora]]: cómo registrar la hora de inicio y fin de una parada (la duración se calcula sola).
- [[a:parametros|Parámetros]]: cómo configurar turnos con vigencia y excepciones por fecha.
- [[a:faq|Preguntas frecuentes]] renovadas y nuevos términos en el glosario: horas nominales, turno adicional y excepción de capacidad.
- Academia: la unidad "Moverse por la app y pedir ayuda" incluye la nueva sección Informes.

"""
n = n.replace("## Versión 2.1.0", ENTRADA + "## Versión 2.1.0", 1)
n = re.sub(r"(resumen:.*?)2\.1\.0", r"\g<1>2.1.1", n, count=1)
v = v.replace("export const VERSION = '2.1.0';", "export const VERSION = '2.1.1';")
V.write_text(v, encoding="utf-8"); N.write_text(n, encoding="utf-8")
print("OK: version.js -> 2.1.1 y entrada 2.1.1 agregada en novedades.md")
