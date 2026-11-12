"""aplicar_soporte_revision_1.py — Corrige en su lugar el término "Plan vigente" del glosario (aviso
"OF modificadas": las órdenes ya son válidas). Correr desde la raíz del repo después de git pull. Idempotente."""
import json
from pathlib import Path
G = Path("forecast/soporte_contenido/ayuda/glosario.json")
g = json.loads(G.read_text(encoding="utf-8"))
nueva = ("Último plan generado y promovido por el proceso diario (06:00). Es la base de las proyecciones de las pantallas "
         "de planificación y control. Las órdenes que se aprueban, editan o crean después son válidas de inmediato; la barra "
         "superior avisa \"OF modificadas desde el último plan\" hasta que el plan de la mañana siguiente las incorpora a sus proyecciones.")
cambio = False
for t in g:
    if t["id"] == "plan-vigente" and t["definicion"] != nueva:
        t["definicion"] = nueva; cambio = True
G.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
print("Plan vigente actualizado" if cambio else "Sin cambios (ya estaba aplicado)")
