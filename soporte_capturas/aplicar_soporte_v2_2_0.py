"""aplicar_soporte_v2_2_0.py — Ajusta en su lugar (sin pisar cambios de otros chats) el glosario y el guion
de capturas para la v2.2.0 de Análisis de Línea. Correr desde la raíz del repo, después de git pull:
    python soporte_capturas\\aplicar_soporte_v2_2_0.py
Es idempotente: si ya se aplicó, no cambia nada."""
import json
from pathlib import Path

G = Path("forecast/soporte_contenido/ayuda/glosario.json")
S = Path("soporte_capturas/guion_planificador.json")
cambios = []

g = json.loads(G.read_text(encoding="utf-8"))
ids = {t["id"] for t in g}
for t in g:
    if t["id"] == "carga-requerida":
        nueva = ("Producción neta que hace falta en una línea: la demanda menos el stock disponible, manteniendo el stock "
                 "de seguridad. Se expresa como % de la capacidad nominal. Una línea con mucho stock aparece menos exigida "
                 "que si se mirara solo la demanda.")
        if t["definicion"] != nueva:
            t["definicion"] = nueva; t["sinonimos"] = ["requerido", "necesidad neta"]; cambios.append("carga-requerida")
nuevos = [
    {"id": "analisis-vigente", "termino": "Análisis vigente", "nombre": "Análisis vigente de una línea",
     "definicion": "El análisis más reciente de una línea en Análisis de Línea (botón \"Análisis #N\"). Es el único que se decide y se valida con solver; los anteriores quedan en el Historial, solo para consulta.",
     "sinonimos": ["análisis actual", "caso vigente"], "pantallas": ["analisislinea"]},
    {"id": "reemplazado", "termino": "Reemplazado", "nombre": "Análisis reemplazado",
     "definicion": "Estado de un análisis anterior que no se había decidido cuando se abrió uno nuevo de la misma línea. Queda en el Historial en solo lectura, no se decide y sus validaciones programadas se cancelan. No es un descarte: no cuenta como decisión para el aprendizaje.",
     "sinonimos": ["reemplazado por"], "pantallas": ["analisislinea"]},
]
for n in nuevos:
    if n["id"] not in ids:
        g.append(n); cambios.append(n["id"])
G.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")

s = json.loads(S.read_text(encoding="utf-8"))
for c in s["capturas"]:
    if c["archivo"] == "plan__analisislinea.png":
        nuevas = [a for a in c["anotaciones"] if a["n"] != 4] + [{"n": 4, "texto": "Análisis #", "pos": "abajo", "opcional": True}]
        if nuevas != c["anotaciones"]:
            c["anotaciones"] = nuevas; cambios.append("guion plan__analisislinea")
S.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
print("Cambios:", ", ".join(cambios) if cambios else "ninguno (ya estaba aplicado)")
