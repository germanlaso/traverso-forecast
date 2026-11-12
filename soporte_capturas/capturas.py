"""
capturas.py — Pantallazos automáticos de la app para Ayuda y Academia (Playwright).

Corre en el PC (Windows) con acceso a la app (http://180.1.1.18:3000). Usa el Microsoft Edge ya instalado,
así que no hace falta descargar navegadores. Cada captura se define en un GUION (JSON): pantalla a abrir,
pasos (clics, escribir), qué difuminar (clientes, proveedores) y anotaciones numeradas. Volver a correr el
guion regenera las imágenes con el mismo nombre: así se mantienen al día cuando cambia la app.

Instalación (una vez):
    pip install playwright
Uso:
    python capturas.py guion_prueba.json                       # todas las capturas del guion
    python capturas.py guion_prueba.json --solo home,plan      # solo archivos que empiezan con esos prefijos
    python capturas.py guion_prueba.json --ver                 # muestra el navegador mientras trabaja
    python capturas.py guion_prueba.json --salida ..\\forecast\\soporte_contenido\\img

Formato del guion:
{
  "base_url": "http://180.1.1.18:3000",
  "viewport": [1440, 900],
  "variables": {"SKU_EJEMPLO": "..."},              # se reemplazan como {SKU_EJEMPLO} en los pasos
  "difuminar_palabras": ["MARCA CLIENTE", ...],     # se difumina, en TODAS las capturas, todo texto que las contenga
  "capturas": [
    {"archivo": "plan__ordenes.png", "titulo": "...",
     "seccion": "🏭 Planificación", "pestana": "Plan de Producción",   # botones del menú (texto exacto)
     "esperar_texto": "Órdenes de producción",                         # texto que confirma que cargó
     "pasos": [{"accion": "click", "texto": "..."} | {"accion": "click", "selector": "..."} |
               {"accion": "escribir", "selector": "...", "valor": "{SKU_EJEMPLO}"} |
               {"accion": "tecla", "tecla": "Enter"} | {"accion": "esperar", "ms": 1500} |
               {"accion": "seleccionar", "selector": "select >> nth=0", "indice": 1 | "valor": "texto"} |
               {"accion": "esperar_texto", "texto": "..."} | {"accion": "scroll", "texto": "..."}],
     "difuminar": [{"selector": "..."} | {"texto": "..."}],
     "anotaciones": [{"n": 1, "texto": "..."} | {"n": 2, "selector": "...", "subir": 1}],   # subir = marcar el contenedor
                    # opcionales: "exacto": true, "indice": 1 (2.ª coincidencia), "opcional": true (si no está, se omite),
                    #             "pos": "izq" (defecto, número a la izquierda) | "der" | "arriba" | "abajo"
     "esperar_sin_texto": ["Cargando"],                                # defecto: no queda ningún "Cargando"
     "recorte": {"selector": "..."} | null,                            # solo esa zona de la pantalla
     "despues": [pasos],                                               # tras la foto (p. ej. click en Cancelar)
     "pagina_completa": false}
  ]
}
Al terminar escribe manifiestos/<guion>.json (fecha, archivo, OK/error) junto a este script.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Falta Playwright. Instálalo con:  pip install playwright")

COLOR = "#F2B705"          # amarillo Mostacín para las anotaciones
TIMEOUT_MS = 30000

JS_ANOTAR = """([cajas, color]) => {
  const capa = document.createElement('div');
  capa.id = '__anotaciones_soporte';
  capa.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none';
  for (const c of cajas) {
    const r = document.createElement('div');
    r.style.cssText = `position:absolute;left:${c.x - 4}px;top:${c.y - 4}px;width:${c.w + 8}px;height:${c.h + 8}px;` +
      `border:3px solid ${color};border-radius:6px;box-shadow:0 0 0 2px rgba(255,255,255,.8)`;
    const b = document.createElement('div');
    b.textContent = c.n;
    // número afuera del recuadro, a la izquierda y centrado; arriba si el elemento está pegado al borde
    const der = c.pos === 'der', abajo = c.pos === 'abajo';
    const arriba = c.pos === 'arriba' || (c.x <= 44 && !abajo && !der);
    const bx = der ? c.x + c.w + 12 : (arriba || abajo) ? c.x - 2 : c.x - 38;
    const by = arriba ? c.y - 36 : abajo ? c.y + c.h + 8 : c.y + c.h / 2 - 13;
    b.style.cssText = `position:absolute;left:${bx}px;top:${by}px;width:26px;height:26px;border-radius:50%;` +
      `background:${color};color:#2C2C2A;font:700 14px Arial;display:flex;align-items:center;justify-content:center;` +
      `border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3)`;
    capa.appendChild(r); capa.appendChild(b);
  }
  document.body.appendChild(capa);
}"""


def sustituir(v, variables):
    if isinstance(v, str):
        for k, x in variables.items():
            v = v.replace("{" + k + "}", str(x))
    return v


def localizar(page, d):
    if d.get("selector"):
        loc = page.locator(d["selector"])
    else:
        loc = page.get_by_text(d["texto"], exact=d.get("exacto", False))
    loc = loc.nth(int(d["indice"])) if "indice" in d else loc.first   # indice: 0 = primera coincidencia
    for _ in range(int(d.get("subir", 0))):          # marcar el contenedor (p. ej. la tarjeta completa)
        loc = loc.locator("xpath=..")
    return loc


JS_PALABRAS = """(palabras) => {
  const ps = palabras.map(p => p.toUpperCase());
  const todos = document.body.querySelectorAll('*');
  for (const e of todos) {
    if (e.children.length && [...e.children].some(h => ps.some(p => (h.textContent || '').toUpperCase().includes(p)))) continue;
    const t = (e.textContent || '').toUpperCase() + ' ' + ((e.value || '') + '').toUpperCase();
    if (ps.some(p => t.includes(p))) e.style.filter = 'blur(6px)';
  }
}"""


JS_HAY_TEXTO = """(t) => [...document.querySelectorAll('body *')].some(e =>
  !e.children.length && (e.textContent || '').includes(t) && e.offsetParent !== null)"""


def esperar_datos(page, cap):
    """Red tranquila y sin textos de carga (el dashboard tarda varios segundos en traer datos)."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass                                          # el websocket de desarrollo puede impedirlo: sigue
    for txt in cap.get("esperar_sin_texto", ["Cargando"]):
        limite = time.time() + TIMEOUT_MS / 1000
        while page.evaluate(JS_HAY_TEXTO, txt):
            if time.time() > limite:
                raise RuntimeError(f"Sigue apareciendo '{txt}' después de {TIMEOUT_MS // 1000} s")
            page.wait_for_timeout(500)


def navegar(page, cap):
    if cap.get("seccion"):
        page.get_by_role("button", name=cap["seccion"], exact=True).first.click()
        page.wait_for_timeout(400)
    if cap.get("pestana"):
        page.get_by_role("button", name=cap["pestana"], exact=True).first.click()
        page.wait_for_timeout(400)


def ejecutar_pasos(page, pasos, variables):
    for p in pasos:
        a = p["accion"]
        if a == "click":
            localizar(page, {k: sustituir(v, variables) for k, v in p.items()}).click()
        elif a == "escribir":
            loc = page.locator(p["selector"]).first
            loc.click()
            loc.fill(sustituir(p["valor"], variables))
        elif a == "seleccionar":                       # <select>: por índice de opción o por texto visible
            loc = page.locator(p["selector"]).first
            if "indice" in p:
                loc.select_option(index=int(p["indice"]))
            else:
                loc.select_option(label=sustituir(p["valor"], variables))
        elif a == "tecla":
            page.keyboard.press(p["tecla"])
        elif a == "esperar":
            page.wait_for_timeout(int(p["ms"]))
        elif a == "esperar_texto":
            page.get_by_text(sustituir(p["texto"], variables)).first.wait_for(timeout=TIMEOUT_MS)
        elif a == "scroll":
            localizar(page, p).scroll_into_view_if_needed()
        else:
            raise ValueError(f"Acción desconocida: {a}")
        page.wait_for_timeout(250)


def difuminar(page, lista):
    for d in lista or []:
        if d.get("selector"):
            page.locator(d["selector"]).evaluate_all("els => els.forEach(e => e.style.filter = 'blur(6px)')")
        elif d.get("subir"):                       # difumina el contenedor del texto indicado
            localizar(page, d).evaluate("e => e.style.filter = 'blur(6px)'")
        else:
            page.get_by_text(d["texto"]).evaluate_all("els => els.forEach(e => e.style.filter = 'blur(6px)')")


def anotar(page, lista):
    cajas = []
    for a in lista or []:
        loc = localizar(page, a)
        try:
            loc.wait_for(timeout=5000 if a.get("opcional") else TIMEOUT_MS)
            box = loc.bounding_box()
        except PWTimeout:
            box = None
        if not box:
            if a.get("opcional"):        # el elemento depende de los datos del día: se omite
                print(f"      (anotación {a['n']} omitida: no aparece hoy)")
                continue
            raise RuntimeError(f"No se encontró en pantalla la anotación {a}")
        sx, sy = page.evaluate("[window.scrollX, window.scrollY]")
        cajas.append({"n": a["n"], "x": box["x"] + sx, "y": box["y"] + sy, "w": box["width"], "h": box["height"],
                      "pos": a.get("pos", "izq")})
    if cajas:
        page.evaluate(JS_ANOTAR, [cajas, COLOR])


def capturar(page, guion, cap, salida, variables):
    page.goto(guion["base_url"], wait_until="domcontentloaded")
    page.get_by_role("button", name=guion.get("boton_inicio", "🏠 Inicio"), exact=True).first.wait_for(timeout=TIMEOUT_MS)
    navegar(page, cap)
    if cap.get("esperar_texto"):
        page.get_by_text(sustituir(cap["esperar_texto"], variables)).first.wait_for(timeout=TIMEOUT_MS)
    esperar_datos(page, cap)
    ejecutar_pasos(page, cap.get("pasos", []), variables)
    esperar_datos(page, cap)
    page.wait_for_timeout(int(cap.get("espera_ms", 1500)))      # gráficos y animaciones
    # Mostacín y el "?" no deben tapar contenido salvo que la captura sea sobre ellos
    if not cap.get("mostrar_flotantes"):
        page.add_style_tag(content="button[aria-label='Pregúntale a Mostacín']{display:none!important}")
    difuminar(page, cap.get("difuminar"))
    if guion.get("difuminar_palabras"):
        page.evaluate(JS_PALABRAS, guion["difuminar_palabras"])
    anotar(page, cap.get("anotaciones"))
    destino = salida / cap["archivo"]
    if cap.get("recorte"):
        localizar(page, cap["recorte"]).screenshot(path=str(destino))
    else:
        page.screenshot(path=str(destino), full_page=bool(cap.get("pagina_completa")))
    # "despues": pasos de cierre (p. ej. Cancelar una ventana abierta solo para la foto, sin guardar nada)
    if cap.get("despues"):
        page.evaluate("() => { const c = document.getElementById('__anotaciones_soporte'); if (c) c.remove(); }")
        ejecutar_pasos(page, cap["despues"], variables)
    return destino


def main():
    ap = argparse.ArgumentParser(description="Pantallazos automáticos de la app (Ayuda y Academia).")
    ap.add_argument("guion")
    ap.add_argument("--salida", default="capturas_salida")
    ap.add_argument("--solo", help="prefijos de archivo separados por coma")
    ap.add_argument("--ver", action="store_true", help="mostrar el navegador")
    ap.add_argument("--navegador", default="msedge", help="msedge (defecto), chrome o chromium")
    a = ap.parse_args()

    guion = json.loads(Path(a.guion).read_text(encoding="utf-8"))
    variables = guion.get("variables", {})
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    capturas = guion["capturas"]
    if a.solo:
        pref = tuple(x.strip() for x in a.solo.split(",") if x.strip())
        capturas = [c for c in capturas if c["archivo"].startswith(pref)]

    manifiesto, errores = [], 0
    with sync_playwright() as pw:
        canal = None if a.navegador == "chromium" else a.navegador
        nav = pw.chromium.launch(channel=canal, headless=not a.ver)
        ctx = nav.new_context(viewport={"width": guion["viewport"][0], "height": guion["viewport"][1]},
                              device_scale_factor=guion.get("escala", 1), locale="es-CL")
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        for cap in capturas:
            t0 = time.time()
            try:
                capturar(page, guion, cap, salida, variables)
                estado = "OK"
            except (PWTimeout, Exception) as e:          # una captura fallida no detiene las demás
                errores += 1
                estado = f"ERROR: {str(e).splitlines()[0][:200]}"
            print(f"{estado[:5]:5} {cap['archivo']:40} {time.time() - t0:5.1f}s  {'' if estado == 'OK' else estado}")
            manifiesto.append({"archivo": cap["archivo"], "titulo": cap.get("titulo", ""), "estado": estado,
                               "fecha": datetime.now().isoformat(timespec="seconds")})
        nav.close()

    # el manifiesto queda junto al script (no en la carpeta de imágenes, que es contenido publicado)
    dir_man = Path(__file__).resolve().parent / "manifiestos"
    dir_man.mkdir(exist_ok=True)
    arch_man = dir_man / f"{Path(a.guion).stem}.json"
    previo = {}
    if arch_man.exists():                         # con --solo se actualizan solo las capturas corridas
        try:
            previo = {m["archivo"]: m for m in json.loads(arch_man.read_text(encoding="utf-8"))}
        except (ValueError, KeyError):
            previo = {}
    previo.update({m["archivo"]: m for m in manifiesto})
    orden = [c["archivo"] for c in guion["capturas"]]
    final = sorted(previo.values(), key=lambda m: orden.index(m["archivo"]) if m["archivo"] in orden else 999)
    arch_man.write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(capturas) - errores} de {len(capturas)} capturas OK · salida: {salida.resolve()}")
    sys.exit(1 if errores else 0)


if __name__ == "__main__":
    main()
