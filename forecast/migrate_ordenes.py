"""
migrate_ordenes.py — Migración de ordenes_aprobadas.json a PostgreSQL MRP

Ejecutar UNA SOLA VEZ antes de hacer docker compose down:
    python3 migrate_ordenes.py

El script:
1. Lee el JSON actual desde /app/data/ordenes_aprobadas.json
2. Conecta al nuevo PostgreSQL (ya debe estar corriendo)
3. Inserta cada orden en mrp_ordenes con su número OF asignado
4. Inserta cada aprobación en mrp_aprobaciones
5. Inicializa el contador en mrp_contador_of para que el próximo OF sea correcto
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ajustar path para importar db_mrp
sys.path.insert(0, "/app")

from db_mrp import init_db, upsert_orden, aprobar_orden_db, get_session
from sqlalchemy import text

JSON_PATH = Path("/app/data/ordenes_aprobadas.json")

# Órdenes hardcodeadas como backup (en caso de que el JSON no esté disponible)
ORDENES_JSON = [
    {
        "key": "250010105__2026-04-26__2026-04-19",
        "sku": "250010105",
        "descripcion": "KETCHUP TRAVERSO 10x1000 BOLSA",
        "tipo": "PRODUCCION",
        "semana_emision": "2026-04-19",
        "semana_necesidad": "2026-04-26",
        "fecha_lanzamiento_real": "2026-04-19",
        "fecha_entrada_real": "2026-04-26",
        "cantidad_sugerida_cj": 1500.0,
        "cantidad_real_cj": 1500.0,
        "cantidad_real_u": 1500,
        "u_por_caja": 1.0,
        "responsable": "Germán",
        "comentario": "Primera prueba de aprobación de Orden de Producción",
        "linea": "S002",
        "timestamp": "2026-04-26T00:39:31.283900"
    },
    {
        "key": "113010290__2026-04-26__2026-04-19",
        "sku": "113010290",
        "descripcion": "VINAGRE MANZANA TRAVERSO 30x500 PET",
        "tipo": "PRODUCCION",
        "semana_emision": "2026-04-19",
        "semana_necesidad": "2026-04-26",
        "fecha_lanzamiento_real": "2026-04-19",
        "fecha_entrada_real": "2026-04-26",
        "cantidad_sugerida_cj": 1167.0,
        "cantidad_real_cj": 1167.0,
        "cantidad_real_u": 1167,
        "u_por_caja": 1.0,
        "responsable": "Germán",
        "comentario": "Test",
        "linea": "L001",
        "timestamp": "2026-04-26T00:57:10.113416"
    }
]


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def main():
    print("=" * 60)
    print("Migración ordenes_aprobadas.json → PostgreSQL MRP")
    print("=" * 60)

    # Inicializar tablas
    print("\n[1/4] Inicializando tablas en PostgreSQL...")
    init_db()
    print("      OK")

    # Cargar datos
    print("\n[2/4] Cargando órdenes desde JSON...")
    if JSON_PATH.exists():
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        ordenes = list(data.values()) if isinstance(data, dict) else data
        print(f"      Encontradas {len(ordenes)} órdenes en {JSON_PATH}")
    else:
        print(f"      JSON no encontrado en {JSON_PATH} — usando datos hardcodeados")
        ordenes = ORDENES_JSON

    # Migrar cada orden
    print("\n[3/4] Migrando órdenes...")
    numeros_asignados = []

    for i, o in enumerate(ordenes, 1):
        # Asignar número OF (OF-2026-00001, OF-2026-00002, ...)
        year = 2026
        numero_of = f"OF-{year}-{i:05d}"
        numeros_asignados.append(numero_of)

        print(f"\n  Orden {i}: {o['sku']} · {o.get('semana_necesidad', '')} → {numero_of}")

        # Insertar en mrp_ordenes
        upsert_orden({
            "numero_of":            numero_of,
            "sku":                  o["sku"],
            "descripcion":          o.get("descripcion", ""),
            "tipo":                 o.get("tipo", "PRODUCCION"),
            "semana_emision":       parse_date(o.get("semana_emision")),
            "semana_necesidad":     parse_date(o.get("semana_necesidad")),
            "cantidad_sugerida_cj": o.get("cantidad_sugerida_cj", 0),
            "cantidad_sugerida_u":  o.get("cantidad_sugerida_cj", 0) * o.get("u_por_caja", 1),
            "u_por_caja":           o.get("u_por_caja", 1),
            "linea":                o.get("linea", ""),
        })
        print(f"    ✓ mrp_ordenes insertado")

        # Insertar aprobación
        aprobar_orden_db(numero_of, {
            "sku":                    o["sku"],
            "cantidad_real_cj":       o.get("cantidad_real_cj", o.get("cantidad_sugerida_cj")),
            "cantidad_real_u":        o.get("cantidad_real_u", 0),
            "fecha_lanzamiento_real": parse_date(o.get("fecha_lanzamiento_real") or o.get("semana_emision")),
            "fecha_entrada_real":     parse_date(o.get("fecha_entrada_real") or o.get("semana_necesidad")),
            "responsable":            o.get("responsable", "Migración"),
            "comentario":             o.get("comentario", "Migrado desde JSON"),
            "semana_emision":         o.get("semana_emision", ""),
            "semana_necesidad":       o.get("semana_necesidad", ""),
        })
        print(f"    ✓ mrp_aprobaciones insertado")

    # Inicializar contador para que el próximo OF sea correcto
    print(f"\n[4/4] Inicializando contador OF...")
    n_migradas = len(ordenes)
    with get_session() as session:
        session.execute(text("""
            INSERT INTO mrp_contador_of (año, ultimo)
            VALUES (:y, :n)
            ON CONFLICT (año) DO UPDATE SET ultimo = :n
        """), {"y": 2026, "n": n_migradas})
    print(f"      Contador 2026 = {n_migradas} (próximo OF será OF-2026-{n_migradas+1:05d})")

    print("\n" + "=" * 60)
    print("✓ MIGRACIÓN COMPLETADA")
    print(f"  {n_migradas} órdenes migradas:")
    for num in numeros_asignados:
        print(f"    · {num}")
    print("=" * 60)


if __name__ == "__main__":
    main()
