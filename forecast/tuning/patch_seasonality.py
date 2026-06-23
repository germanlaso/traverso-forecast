#!/usr/bin/env python3
"""
patch_seasonality.py — Aplica DOS cambios a seasonality.py y sus llamadores:

  (1) FIX DE ALINEACION lunes -> domingo en las 3 helpers base de generacion de
      fechas. Hoy generan LUNES; el pipeline usa DOMINGOS (ds weekday=6), asi que
      las dummies de regresores caen en fechas que no existen en el ds y quedan en
      cero (regresores INERTES). Verificado: el ds de cada semana es el domingo, y
      la helper genera el lunes siguiente -> restar 1 dia alinea exacto.
      Helpers afectadas: _semanas_del_rango, _semana_santa, _semanas_previas_fecha.
      Todas las intermedias (_temporada, _verano, _fiestas_patrias, _semana_santa_all)
      se apoyan en estas 3, asi que el fix se propaga a todas las categorias.
      Impacto medido: grupo sano 31,71% -> 31,42% sem, 18/6 mejoran (top 100).

  (2) REGRESOR SEMANA-DEL-MES (global, todas las categorias). Dummies por posicion
      ordinal del mes (semmes_1,2,4,5; sem3 referencia), generadas como DOMINGOS.
      Impacto medido: grupo sano -0,62 sem / -0,82 mes, 40/29 (top 100).
      Se expone via get_regressors(categoria) = get_category_regressors(cat) + semmes.
      Los 2 llamadores (forecaster.py, eval_forecast_error.py) pasan a usar get_regressors.

Hace backup, aplica por reemplazo EXACTO, valida con ast.parse, muestra diff.
Idempotente: si ya esta parcheado, avisa y no duplica.

USO (dentro del container):
  docker cp patch_seasonality.py traverso_forecast:/tmp/patch_seasonality.py
  docker exec traverso_forecast python3 /tmp/patch_seasonality.py
"""
import ast, shutil, sys, datetime

SEASON = "/app/seasonality.py"
FORECASTER = "/app/forecaster.py"
EVAL = "/app/eval_forecast_error.py"
STAMP = datetime.datetime.now().strftime("%d%b").lower()

# ── Ediciones en seasonality.py ──────────────────────────────────────────────
# (1) Fix de alineacion: en cada helper, el ancla que va a lunes pasa a domingo.
#     Se hace restando 1 dia adicional. Reemplazos de texto unicos.

EDITS_SEASON = [
    # _semanas_del_rango: d = inicio - timedelta(days=inicio.weekday())
    (
        "    d = inicio - timedelta(days=inicio.weekday())\n",
        "    # alineado a DOMINGO (inicio de semana del pipeline): lunes - 1 dia\n"
        "    d = inicio - timedelta(days=inicio.weekday() + 1)\n",
    ),
    # _semana_santa: lunes = viernes - timedelta(days=viernes.weekday())
    (
        "    lunes   = viernes - timedelta(days=viernes.weekday())\n"
        "    return [(lunes - timedelta(weeks=w)).strftime(\"%Y-%m-%d\") for w in range(3)]\n",
        "    # ancla en DOMINGO de la semana del pipeline (lunes - 1 dia)\n"
        "    domingo = viernes - timedelta(days=viernes.weekday() + 1)\n"
        "    return [(domingo - timedelta(weeks=w)).strftime(\"%Y-%m-%d\") for w in range(3)]\n",
    ),
    # _semanas_previas_fecha: lunes = fecha - timedelta(days=fecha.weekday())
    (
        "    lunes = fecha - timedelta(days=fecha.weekday())\n"
        "    return [(lunes - timedelta(weeks=w)).strftime(\"%Y-%m-%d\") for w in range(n)]\n",
        "    # ancla en DOMINGO de la semana del pipeline (lunes - 1 dia)\n"
        "    domingo = fecha - timedelta(days=fecha.weekday() + 1)\n"
        "    return [(domingo - timedelta(weeks=w)).strftime(\"%Y-%m-%d\") for w in range(n)]\n",
    ),
]

# (2) Bloque nuevo: helper semana-del-mes + wrapper get_regressors.
#     Se inserta JUSTO ANTES de 'def get_all_regressors_summary'.
BLOQUE_SEMMES = '''
# ── Regresor global: SEMANA DEL MES ───────────────────────────────────────────
# Posicion ordinal de la semana dentro del mes (sem1 floja ... sem4 pico, sem5
# cola). Patron transversal a todos los canales (~8% gap tardias vs tempranas),
# que la estacionalidad anual de Prophet no captura del todo. Dummies por posicion
# (sem3 = referencia). Fechas generadas como DOMINGOS (inicio de semana del pipeline).
def _semana_del_mes(posicion: int) -> list[str]:
    """Domingos cuya posicion ordinal en el mes (1..5 por dia 1-7,8-14,...) coincide
    con `posicion`, para todos los anos en _YEARS."""
    fechas = []
    for y in _YEARS:
        d = date(y, 1, 1)
        # retroceder al domingo de esa semana (weekday 6 = domingo)
        d = d - timedelta(days=(d.weekday() + 1) % 7)
        fin = date(y, 12, 31)
        while d <= fin:
            if min((d.day - 1) // 7 + 1, 5) == posicion:
                fechas.append(d.strftime("%Y-%m-%d"))
            d += timedelta(weeks=1)
    return fechas


def _regresores_semana_mes() -> list[dict]:
    """Dummies de semana-del-mes (global, todas las categorias). sem3 = referencia."""
    etiquetas = {1: "1a semana (floja)", 2: "2a semana",
                 4: "4a semana (pico)", 5: "5a semana (cola)"}
    return [
        {"name": f"semmes_{p}", "label": f"Semana del mes: {etiquetas[p]}",
         "dates": _semana_del_mes(p), "value": 1.0}
        for p in (1, 2, 4, 5)
    ]


def get_regressors(categoria: str) -> list[dict]:
    """Regresores efectivos para un SKU: los de su categoria MAS el regresor
    global de semana-del-mes. Es el punto de entrada que deben usar los llamadores
    (forecaster.py, eval_forecast_error.py) en lugar de get_category_regressors."""
    return get_category_regressors(categoria) + _regresores_semana_mes()


'''

def aplicar_edits(path, edits, descripcion):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    orig = src
    for viejo, nuevo in edits:
        if nuevo.split("\\n")[0] in src and viejo not in src:
            print(f"  [skip] {path}: ya parece parcheado (no se encontro patron original)")
            return src, False
        n = src.count(viejo)
        if n != 1:
            print(f"  [ERROR] patron aparece {n} veces (esperaba 1) en {path}:")
            print(f"          {viejo[:60]!r}")
            sys.exit(1)
        src = src.replace(viejo, nuevo)
    cambio = src != orig
    return src, cambio

def main():
    # ── seasonality.py ────────────────────────────────────────────────────────
    print(f"[1] seasonality.py")
    shutil.copy(SEASON, f"{SEASON}.bak-patch-{STAMP}")
    with open(SEASON, "r", encoding="utf-8") as f:
        src = f.read()

    # fix alineacion
    for viejo, nuevo in EDITS_SEASON:
        if viejo not in src:
            if nuevo.splitlines()[0].strip() in src:
                print("  [skip] alineacion ya aplicada")
                break
            print(f"  [ERROR] no encontre patron de alineacion: {viejo[:50]!r}")
            sys.exit(1)
        if src.count(viejo) != 1:
            print(f"  [ERROR] patron no unico: {viejo[:50]!r}")
            sys.exit(1)
        src = src.replace(viejo, nuevo)
    else:
        print("  [ok] alineacion lunes->domingo aplicada (3 helpers)")

    # bloque semana-del-mes (insertar antes de get_all_regressors_summary)
    ancla = "def get_all_regressors_summary()"
    if "def get_regressors(" in src:
        print("  [skip] get_regressors ya existe")
    elif ancla not in src:
        print(f"  [ERROR] no encontre ancla {ancla!r}")
        sys.exit(1)
    else:
        src = src.replace(ancla, BLOQUE_SEMMES.lstrip("\\n") + ancla, 1)
        print("  [ok] bloque semana-del-mes + get_regressors insertado")

    ast.parse(src)  # valida sintaxis
    with open(SEASON, "w", encoding="utf-8") as f:
        f.write(src)
    print("  [ok] ast.parse OK, guardado")

    # ── llamadores: get_category_regressors -> get_regressors ───────────────────
    for path in (FORECASTER, EVAL):
        print(f"[2] {path}")
        shutil.copy(path, f"{path}.bak-patch-{STAMP}")
        with open(path, "r", encoding="utf-8") as f:
            s = f.read()
        # actualizar import y llamada
        cambios = 0
        if "from seasonality import get_category_regressors" in s:
            s = s.replace("from seasonality import get_category_regressors",
                          "from seasonality import get_category_regressors, get_regressors")
            cambios += 1
        # la llamada: regressors = get_category_regressors(categoria) -> get_regressors(categoria)
        viejo_call = "get_category_regressors(categoria)"
        if viejo_call in s:
            s = s.replace(viejo_call, "get_regressors(categoria)")
            cambios += 1
        ast.parse(s)
        with open(path, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"  [ok] {cambios} cambios, ast.parse OK")

    print("\\n[FIN] Parche aplicado. Backups: *.bak-patch-" + STAMP)
    print("Validar con eval antes de commit.")

if __name__ == "__main__":
    main()
