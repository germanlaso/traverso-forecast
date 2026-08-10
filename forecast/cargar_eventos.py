#!/usr/bin/env python3
"""
cargar_eventos.py — Crea, carga, lista y valida `mrp_eventos` · Traverso S.A.

Por defecto NO escribe nada: sin argumentos hace `--listar`.

SUBCOMANDOS
-----------
  --crear    Crea la tabla (idempotente, via crear_tablas_params()).
  --cargar   Carga el evento del competidor 2024 en 250010495 (2 filas).
             ESCRIBE EN LA BD. Es idempotente: borra las filas de ese
             (nombre, sku) y las reinserta. Hacer backup antes.
  --listar   Muestra las filas y los domingos a los que expanden.
  --validar  Cruza los domingos expandidos contra el `ds` del modelo entrenado.
             Es la guarda contra el bug de regresor inerte: si las fechas no
             coinciden EXACTO con el ds, Prophet genera una columna de ceros y
             lo ignora sin error. Correr SIEMPRE después de --cargar.

EL EVENTO QUE SE CARGA
----------------------
Ventana elegida con `tuning/exp_evento_holdout.py` (10-08-2026): holdout
out-of-sample entrenando hasta 2025-09-28 y prediciendo oct-nov 2025 contra el
real de 639 cj/sem.

    sin evento                       3.210 cj/sem   +402%
    un regresor, todo el evento      1.186 cj/sem    +86%
    dos fases (esta ventana)           748 cj/sem    +17%
    tres fases                       1.549 cj/sem   +142%
    corte una semana antes             561 cj/sem    -12%

Se eligió el corte del 29-09 sobre el del 22-09 (que tiene |sesgo| algo mejor,
-12% vs +17%) por robustez, no por el número: los separa UNA sola semana y el
holdout son 9 semanas sobre una serie grumosa, así que esos 5 puntos son ruido.
Criterios: sesgo POSITIVO antes que negativo (subestimar en una línea al 100% de
uso genera quiebres), y un corte explicable al negocio ("arrancó suave a
mediados de agosto y se agravó en octubre").

USO
---
    python3 /app/cargar_eventos.py                  # listar (no escribe)
    python3 /app/cargar_eventos.py --crear
    python3 /app/cargar_eventos.py --cargar
    python3 /app/cargar_eventos.py --validar
"""
import argparse
import sys

sys.path.insert(0, "/app")

# Definición auditable de lo que se carga. Fechas NATURALES: eventos.py las
# snapea a domingo. Estas ya son domingos, así que el snap es idempotente.
EVENTO_COMPETIDOR = {
    "nombre": "competidor sachet 2024",
    "sku": "250010495",
    "filas": [
        {
            "etiqueta": "suave",
            "fecha_desde": "2024-08-18",
            "fecha_hasta": "2024-09-29",
            "nota": "Escalon inicial: las semanas ISO 31-32 estan al nivel "
                    "pre-evento (250 y 229 cj vs 267 de base) y la 33 salta a "
                    "1.466. Estimacion de negocio: mediados de agosto. "
                    "Intensidad ~3,4x sobre el nivel pre-evento.",
        },
        {
            "etiqueta": "fuerte",
            "fecha_desde": "2024-10-06",
            "fecha_hasta": "2024-12-29",
            "nota": "Fase severa. Media de las semanas ISO 40-52: 1.852 cj vs "
                    "913 de las semanas 33-39, un escalon de 2,0x. Intensidad "
                    "~7,4x sobre el nivel pre-evento. Incluye diciembre "
                    "(semanas 49, 51 y 52 con ratios de 9-10x).",
        },
    ],
}

# SKU con eco pendiente de ventana propia. NO se cargan todavia: su ago-sep esta
# sano (0,94 y 0,92) y su problema es oct-nov (1,60 y 1,88), que entra al
# horizonte mas adelante. Requieren su propio holdout antes de definir fases.
PENDIENTES = {"260010495": "MOSTAZA (oct-nov 1,60x)",
              "270010495": "MAYONESA (oct-nov 1,88x)"}


def cmd_crear() -> None:
    from db_mrp import crear_tablas_params
    crear_tablas_params()
    print("[crear] crear_tablas_params() ejecutado (idempotente).")
    from db_mrp import get_eventos
    print(f"[crear] mrp_eventos accesible, {len(get_eventos(solo_activos=False))} fila(s).")


def cmd_cargar() -> None:
    from db_mrp import borrar_eventos, upsert_evento

    nombre = EVENTO_COMPETIDOR["nombre"]
    sku = EVENTO_COMPETIDOR["sku"]

    n_borradas = borrar_eventos(nombre, sku)
    if n_borradas:
        print(f"[cargar] {n_borradas} fila(s) previa(s) de '{nombre}' / {sku} borradas.")

    for f in EVENTO_COMPETIDOR["filas"]:
        new_id = upsert_evento(
            nombre=nombre, sku=sku, etiqueta=f["etiqueta"],
            fecha_desde=f["fecha_desde"], fecha_hasta=f["fecha_hasta"],
            tipo="pasado", magnitud=None, unidad=None,
            activo=True, nota=f["nota"])
        print(f"[cargar] id={new_id}  {f['etiqueta']:<7} "
              f"{f['fecha_desde']} .. {f['fecha_hasta']}")

    print()
    print("[cargar] LISTO. Nada consume esta tabla todavia: el enganche en")
    print("         cron_plan.py va en un commit aparte. Correr --validar ahora.")
    if PENDIENTES:
        print()
        for s, d in PENDIENTES.items():
            print(f"[cargar] NO cargado: {s} — {d}")


def cmd_listar() -> None:
    from db_mrp import get_eventos
    from eventos import cargar_eventos_activos, expandir_a_domingos

    filas = get_eventos(solo_activos=False)
    if not filas:
        print("mrp_eventos esta vacia (o no existe: correr --crear).")
        return

    print(f"=== mrp_eventos: {len(filas)} fila(s) ===")
    print(f"{'id':>4} {'sku':<11}{'nombre':<26}{'etiqueta':<9}"
          f"{'desde':<12}{'hasta':<12}{'tipo':<8}{'act':<4}sem")
    print("-" * 92)
    for f in filas:
        dom = expandir_a_domingos(f["fecha_desde"], f["fecha_hasta"])
        print(f"{f['id']:>4} {str(f['sku']):<11}{str(f['nombre'])[:25]:<26}"
              f"{str(f['etiqueta']):<9}{str(f['fecha_desde']):<12}"
              f"{str(f['fecha_hasta']):<12}{str(f['tipo']):<8}"
              f"{'si' if f['activo'] else 'NO':<4}{len(dom)}")

    print()
    print("=== regresores efectivos (lo que recibiria train_model) ===")
    reg = cargar_eventos_activos()
    if not reg:
        print("ninguno.")
        return
    for sku, regs in sorted(reg.items()):
        print(f"{sku}:")
        for r in regs:
            print(f"    {r['name']:<38} {len(r['dates']):>3} sem  "
                  f"{r['dates'][0]} .. {r['dates'][-1]}")


def cmd_validar() -> None:
    """Guarda contra regresor inerte: los domingos deben existir en el ds del modelo."""
    from eventos import cargar_eventos_activos
    from forecaster import load_model, make_key

    reg = cargar_eventos_activos()
    if not reg:
        print("Sin eventos activos de tipo 'pasado'. Nada que validar.")
        return

    import pandas as pd

    problemas = 0
    for sku, regs in sorted(reg.items()):
        cached = load_model(make_key(sku, None, None))
        if not cached:
            print(f"{sku}: SIN MODELO en cache — no se puede validar la alineacion.")
            problemas += 1
            continue
        model, _ = cached
        ds = set(pd.to_datetime(model.history["ds"]).dt.strftime("%Y-%m-%d"))
        print(f"{sku}: historia del modelo {min(ds)} .. {max(ds)} ({len(ds)} sem)")
        for r in regs:
            dentro = sorted(set(r["dates"]) & ds)
            fuera = sorted(set(r["dates"]) - ds)
            estado = "OK" if len(dentro) == len(r["dates"]) else "REVISAR"
            if not dentro:
                estado = "INERTE"
            print(f"    [{estado:<7}] {r['name']:<38} "
                  f"{len(dentro)}/{len(r['dates'])} semanas coinciden con el ds")
            if fuera:
                problemas += 1
                print(f"              fuera del ds: {fuera[:6]}"
                      f"{' ...' if len(fuera) > 6 else ''}")
                print(f"              -> esas semanas NO aportan nada al regresor")

    print()
    if problemas:
        print(f"VALIDACION CON OBSERVACIONES ({problemas}). Un regresor INERTE es una")
        print("columna de ceros: Prophet lo ignora sin error y el forecast queda igual")
        print("que sin evento. NO enganchar en cron_plan hasta resolverlo.")
    else:
        print("VALIDACION OK: todas las semanas declaradas existen en el ds del modelo.")
        print("El regresor se va a activar de verdad.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crear", action="store_true")
    ap.add_argument("--cargar", action="store_true")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--validar", action="store_true")
    args = ap.parse_args()

    if args.crear:
        cmd_crear()
    elif args.cargar:
        cmd_cargar()
    elif args.validar:
        cmd_validar()
    else:
        cmd_listar()


if __name__ == "__main__":
    main()
