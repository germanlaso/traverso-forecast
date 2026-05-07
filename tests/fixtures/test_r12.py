"""
test_r12.py - Validacion de la implementacion de R12 sobre un plan generado.

Ejecuta los 3 tests del documento R12_PRIMER_SETUP_GRATIS.md:
  Test 1: en cada (linea, dia) con OFT, N_setup == max(0, N_skus_distintos - 1)
  Test 2: total de OFTs con paga_setup baja vs baseline sin R12
  Test 3: dias con 1 solo SKU NUNCA tienen setup

Uso:
    python tests/fixtures/test_r12.py <plan_post_r12.json> [--baseline <plan_sin_r12.json>]

Si --baseline no se provee, Test 2 reporta solo el conteo absoluto.
"""
import argparse
import json
import sys
from collections import defaultdict


def cargar_buckets(path: str) -> dict:
    """Lee plan JSON, agrupa OFTs PRODUCCION por (linea, fecha_lanzamiento).

    Retorna dict {(linea, fecha): {'total': N_ofts, 'con_setup': N, 'skus': set}}.
    """
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    prod = [o for o in d['ordenes'] if o['tipo'] == 'PRODUCCION']
    buckets: dict = defaultdict(lambda: {'total': 0, 'con_setup': 0, 'skus': set()})
    for o in prod:
        key = (o['linea'], o['fecha_lanzamiento'])
        buckets[key]['total'] += 1
        buckets[key]['skus'].add(o['sku'])
        if o.get('paga_setup'):
            buckets[key]['con_setup'] += 1
    return buckets


def total_setups(buckets: dict) -> int:
    return sum(v['con_setup'] for v in buckets.values())


def test_1_n_setup(buckets: dict) -> tuple[int, list]:
    """N_setup == max(0, N_skus - 1) por (linea, dia)."""
    violaciones = []
    for (linea, fecha), v in buckets.items():
        n_skus = len(v['skus'])
        n_setup = v['con_setup']
        esperado = max(0, n_skus - 1)
        if n_setup != esperado:
            violaciones.append((linea, fecha, n_skus, n_setup, esperado))
    return len(buckets), violaciones


def test_3_dias_un_sku(buckets: dict) -> tuple[int, list]:
    """Dias con N_skus == 1 NUNCA deben tener setup."""
    dias_un_sku = [k for k, v in buckets.items() if len(v['skus']) == 1]
    con_setup_indebido = [k for k in dias_un_sku if buckets[k]['con_setup'] > 0]
    return len(dias_un_sku), con_setup_indebido


def distribucion_skus(buckets: dict) -> dict:
    dist: dict = defaultdict(int)
    for v in buckets.values():
        dist[len(v['skus'])] += 1
    return dict(dist)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('plan', help='Path al JSON del plan post-R12')
    parser.add_argument('--baseline', help='Path al JSON baseline sin R12 (opcional)')
    args = parser.parse_args()

    buckets = cargar_buckets(args.plan)
    setups = total_setups(buckets)

    # Test 1
    n_buckets, violaciones_t1 = test_1_n_setup(buckets)
    print('=== Test 1: N_setup == max(0, N_skus - 1) por (linea, dia) ===')
    if violaciones_t1:
        print(f'  FAIL: {len(violaciones_t1)} violaciones de {n_buckets} buckets')
        for linea, fecha, n_skus, n_setup, esp in violaciones_t1[:10]:
            print(f'    ({linea}, {fecha}): {n_skus} SKUs, {n_setup} setups, esperado {esp}')
    else:
        print(f'  OK: los {n_buckets} buckets (linea, dia) cumplen la regla')

    # Test 2
    print()
    print('=== Test 2: total OFTs con paga_setup ===')
    print(f'  plan ({args.plan}): {setups}')
    if args.baseline:
        baseline_buckets = cargar_buckets(args.baseline)
        baseline_setups = total_setups(baseline_buckets)
        print(f'  baseline ({args.baseline}): {baseline_setups}')
        if baseline_setups > 0:
            delta = baseline_setups - setups
            pct = 100 * delta / baseline_setups
            print(f'  Reduccion: {delta} ({pct:.1f}%)')

    # Test 3
    print()
    print('=== Test 3: Dias con 1 solo SKU NO deben tener setup ===')
    n_dias_un, indebido = test_3_dias_un_sku(buckets)
    print(f'  Dias con 1 SKU:                 {n_dias_un}')
    print(f'  De esos, con setup (no debe):   {len(indebido)}')
    if indebido:
        print('  FAIL: violaciones:')
        for k in indebido[:5]:
            print(f'    {k}')

    # Bonus
    print()
    print('=== Bonus: distribucion de N_skus por bucket ===')
    print(f'  Buckets totales: {n_buckets}')
    for n in sorted(distribucion_skus(buckets)):
        print(f'    {n} SKU(s): {distribucion_skus(buckets)[n]} buckets')

    # Exit code: 0 si pasan los 3 tests, 1 si falla algun test
    fail = bool(violaciones_t1) or bool(indebido)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
