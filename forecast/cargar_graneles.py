#!/usr/bin/env python3
"""
cargar_graneles.py — Catalogo de graneles y carga de `granel_grupo` por prefijo.

Paso 1 del diseno de niveles de agrupacion (ver MODELO_CAMPANAS.md §6 y el
snapshot del 03-08-2026).

QUE HACE
--------
1. Crea `mrp_graneles`: catalogo de graneles con su familia y el ORDEN PREFERENTE
   de secuencia. Es catalogo y no columnas en `mrp_sku_params` porque son ~8
   graneles contra 249 SKU: asi por SKU se carga UNA columna (`granel_grupo`) y
   familia/orden se derivan, sin repetir el orden 53 veces ni arriesgar que dos
   SKU del mismo granel queden con ordenes distintos.

2. Asigna `granel_grupo` a los SKU deduciendolo del CODIGO (3 primeros digitos),
   VALIDANDO contra la descripcion. Los digitos 4-6 son la marca (010 Traverso,
   011 Montaner, 030 Tottus, 033 Cuisine&Co, 038 Nuestra Cocina, 013 Higueras,
   012 Frescolim) y los ultimos el formato/embalaje, asi que el granel esta en el
   prefijo.

POR QUE ES SEGURO CARGAR granel_grupo
-------------------------------------
`granel_grupo` alimenta el gate de campanas de SALSAS, pero el optimizer tiene
guard (optimizer.py:801-802):

    _grupo = (sku_params[s].get("granel_grupo") or "").strip().lower()
    if _grupo not in GRANEL_MODOS:      # ("ketchup", "mostaza")
        continue

Un SKU con granel_grupo='vinagre_blanco' se IGNORA en el gate: no se bloquea ni
rompe el modelo. Verificado el 03-08 antes de escribir este script.

ORDEN PREFERENTE (confirmado con Produccion el 03-08)
-----------------------------------------------------
  vinagre: incoloro -> manzana -> blanco -> rosado   (claro a oscuro)
  limon:   sin orden preferido declarado (pendiente)
  entre familias: sin preferencia declarada
VINAGRE TINTO comparte granel con ROSADO (mismo granel, nombre comercial de
marca privada).

PENDIENTE: Produccion indica que puede haber 5 recetas de limon distintas segun
marca. Por eso el catalogo es una tabla: subdividir despues = agregar filas y
reasignar los SKU afectados, sin rehacer la carga ni cambiar la estructura.

Uso:
    python3 /app/cargar_graneles.py                 # DRY-RUN: reporta, no escribe
    python3 /app/cargar_graneles.py --aplicar       # crea tabla + backup + UPDATE
    python3 /app/cargar_graneles.py --linea "L1Pet LV" --aplicar   # acotado
"""

import argparse
import datetime as dt
import sys

from sqlalchemy import text

# ── Catalogo ─────────────────────────────────────────────────────────────────
# (granel_grupo, familia, orden_familia, orden_granel, notas)
# orden_familia: sin preferencia declarada el 03-08 -> valores arbitrarios pero
# DETERMINISTAS, para que el sort sea reproducible. Ajustar cuando Produccion
# defina si conviene limon antes que vinagre.
CATALOGO = [
    ("limon",            "limon",   1, 1, "provisional: Produccion evalua 5 recetas por marca"),
    ("limon_pica",       "limon",   1, 2, "provisional: sin orden preferido dentro de limon"),
    ("vinagre_incoloro", "vinagre", 2, 1, "orden claro->oscuro confirmado 03-08"),
    ("vinagre_manzana",  "vinagre", 2, 2, ""),
    ("vinagre_blanco",   "vinagre", 2, 3, ""),
    ("vinagre_rosado",   "vinagre", 2, 4, "incluye VINAGRE TINTO (mismo granel)"),
    ("ketchup",          "ketchup", 3, 1, "gate de campana salsas (nivel 0), ya en uso"),
    ("mostaza",          "mostaza", 4, 1, "gate de campana salsas (nivel 0), ya en uso"),
]

# ── Reglas de deduccion: prefijo -> granel, validado contra la descripcion ───
# El prefijo solo no alcanza: si la descripcion no confirma, se reporta como
# EXCEPCION y NO se actualiza (mejor dejarlo vacio que asignarlo mal).
REGLAS = [
    ("114", "vinagre_incoloro", ("VINAGRE INCOLORO",)),
    ("113", "vinagre_manzana",  ("VINAGRE MANZANA",)),
    ("111", "vinagre_blanco",   ("VINAGRE BLANCO",)),
    ("112", "vinagre_rosado",   ("VINAGRE ROSADO", "VINAGRE TINTO")),
    ("122", "limon_pica",       ("LIMON PICA", "LIMÓN PICA")),
    ("121", "limon",            ("LIMON", "LIMÓN")),
]

DDL = """
CREATE TABLE IF NOT EXISTS mrp_graneles (
    granel_grupo   VARCHAR(40)  PRIMARY KEY,
    familia        VARCHAR(30)  NOT NULL,
    orden_familia  INTEGER      NOT NULL DEFAULT 0,
    orden_granel   INTEGER      NOT NULL DEFAULT 0,
    activo         BOOLEAN      NOT NULL DEFAULT TRUE,
    notas          VARCHAR(200),
    updated_at     TIMESTAMP    DEFAULT NOW()
)
"""


def deducir(sku: str, desc: str) -> tuple[str | None, str]:
    """(granel_grupo, motivo). None si no se puede deducir con seguridad."""
    d = (desc or "").upper()
    pref = (sku or "")[:3]
    for p, granel, marcas in REGLAS:
        if pref != p:
            continue
        if any(mk in d for mk in marcas):
            return granel, "ok"
        return None, f"prefijo {p} pero la descripcion no confirma ({marcas[0]})"
    return None, "prefijo sin regla"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="sin este flag es dry-run: no escribe nada")
    ap.add_argument("--linea", type=str, default=None,
                    help="acotar a una linea_preferida (default: todos los SKU)")
    args = ap.parse_args()

    sys.path.insert(0, "/app")
    from db_mrp import SessionLocal

    hoy = dt.date.today().strftime("%Y%m%d")
    modo = "APLICAR" if args.aplicar else "DRY-RUN (no escribe)"
    print(f"=== cargar_graneles · {modo} ===")
    print()

    # ── 1. catalogo ──────────────────────────────────────────────────────────
    if args.aplicar:
        with SessionLocal() as s:
            s.execute(text(DDL))
            for g, fam, of, og, nt in CATALOGO:
                s.execute(text("""
                    INSERT INTO mrp_graneles
                        (granel_grupo, familia, orden_familia, orden_granel, notas, updated_at)
                    VALUES (:g, :f, :of, :og, :nt, NOW())
                    ON CONFLICT (granel_grupo) DO UPDATE SET
                        familia = EXCLUDED.familia,
                        orden_familia = EXCLUDED.orden_familia,
                        orden_granel = EXCLUDED.orden_granel,
                        notas = EXCLUDED.notas,
                        updated_at = NOW()
                """), dict(g=g, f=fam, of=of, og=og, nt=nt))
            s.commit()
        print(f"[1] mrp_graneles creada/actualizada: {len(CATALOGO)} graneles")
    else:
        print(f"[1] mrp_graneles: se crearia con {len(CATALOGO)} graneles")
        for g, fam, of, og, nt in CATALOGO:
            print(f"      {g:<18} familia={fam:<9} orden={of}.{og}  {nt}")
    print()

    # ── 2. deducir por SKU ───────────────────────────────────────────────────
    q = ("SELECT sku, descripcion, linea_preferida, granel_grupo "
         "FROM mrp_sku_params WHERE activo")
    params = {}
    if args.linea:
        q += " AND linea_preferida = :ln"
        params["ln"] = args.linea
    q += " ORDER BY sku"
    with SessionLocal() as s:
        rows = s.execute(text(q), params).fetchall()

    a_set, ya_ok, conflicto, excep = [], [], [], []
    for sku, desc, ln, actual in rows:
        g, motivo = deducir(sku, desc)
        cur = (actual or "").strip()
        if g is None:
            if motivo != "prefijo sin regla":
                excep.append((sku, desc, ln, motivo))
            continue
        if cur == g:
            ya_ok.append(sku)
        elif cur:
            conflicto.append((sku, desc, ln, cur, g))
        else:
            a_set.append((sku, desc, ln, g))

    print(f"[2] SKU evaluados: {len(rows)}"
          + (f" (linea={args.linea})" if args.linea else ""))
    print(f"      a asignar         : {len(a_set)}")
    print(f"      ya correctos      : {len(ya_ok)}")
    print(f"      CONFLICTO         : {len(conflicto)}  (tienen otro valor, NO se tocan)")
    print(f"      EXCEPCION         : {len(excep)}  (prefijo sin confirmar en descripcion)")
    print()

    if a_set:
        print("--- a asignar ---")
        porg = {}
        for sku, desc, ln, g in a_set:
            porg.setdefault(g, []).append((sku, ln, desc))
        for g in sorted(porg):
            print(f"  {g}  ({len(porg[g])} SKU)")
            for sku, ln, desc in porg[g]:
                print(f"      {sku}  [{(ln or '-'):<13}] {(desc or '')[:44]}")
        print()
    if conflicto:
        print("--- CONFLICTO (revisar a mano, no se modifican) ---")
        for sku, desc, ln, cur, g in conflicto:
            print(f"  {sku} actual='{cur}' deducido='{g}' | {(desc or '')[:40]}")
        print()
    if excep:
        print("--- EXCEPCION (prefijo con regla pero descripcion no confirma) ---")
        for sku, desc, ln, motivo in excep:
            print(f"  {sku} [{(ln or '-'):<13}] {(desc or '')[:40]} -> {motivo}")
        print()

    # ── 3. aplicar ───────────────────────────────────────────────────────────
    if not args.aplicar:
        print("DRY-RUN: nada escrito. Revisar el listado y correr con --aplicar.")
        return 0
    if not a_set:
        print("[3] nada que actualizar")
        return 0

    bkp = f"mrp_sku_params_bkp_{hoy}"
    with SessionLocal() as s:
        s.execute(text(f"CREATE TABLE IF NOT EXISTS {bkp} AS SELECT * FROM mrp_sku_params"))
        s.commit()
    print(f"[3] backup: {bkp}")

    with SessionLocal() as s:
        n = 0
        for sku, desc, ln, g in a_set:
            r = s.execute(text("""
                UPDATE mrp_sku_params
                   SET granel_grupo = :g, updated_at = NOW()
                 WHERE sku = :sku
                   AND COALESCE(NULLIF(TRIM(granel_grupo), ''), '') = ''
            """), dict(g=g, sku=sku))
            n += r.rowcount or 0
        s.commit()
    print(f"[4] SKU actualizados: {n}")

    with SessionLocal() as s:
        print()
        print("--- verificacion: granel_grupo por valor ---")
        for v, c in s.execute(text("""
            SELECT COALESCE(NULLIF(TRIM(granel_grupo),''),'(vacio)') AS g, COUNT(*)
              FROM mrp_sku_params WHERE activo GROUP BY 1 ORDER BY 2 DESC
        """)).fetchall():
            print(f"      {v:<20} {c}")
    print()
    print("Recordar: el gate de salsas ignora los graneles fuera de "
          "GRANEL_MODOS (guard en optimizer.py:801). No afecta al plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
