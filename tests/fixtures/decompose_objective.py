"""
decompose_objective.py - Diagnostico de la funcion objetivo del optimizador.

Descompone obj_reported en sus componentes (W_DEFICIT, W_EXCESO, W_ALT,
W_INICIO_SIMBOLICO) usando datos disponibles en el JSON del endpoint /plan.

Limitacion conocida: el campo 'alerta' por orden solo captura def/exc en
dias con produccion (OFT). Dias SIN produccion donde tambien hay deficit
o exceso no aparecen aqui — quedan en el residuo (diff obj - suma).

Uso:
    python tests/fixtures/decompose_objective.py <plan.json> [<plan2.json> ...]
"""
import json
import re
import sys

# Pesos del optimizador (deben coincidir con forecast/optimizer.py)
W_DEFICIT = 100_000
W_EXCESO  = 50_000
W_ALT     = 50
W_INICIO  = 1


def parse_alerts(prod_orders: list) -> tuple[int, int]:
    """Suma unidades faltantes y unidades sobre cap parseando 'alerta'.

    Retorna (deficit_u_total, exceso_u_total) sumadas sobre todas las OFTs.
    """
    deficit_u = 0
    exceso_u = 0
    for o in prod_orders:
        a = o.get('alerta') or ''
        m = re.search(r'bajo SS \((\d+) u faltantes\)', a)
        if m:
            deficit_u += int(m.group(1))
        m = re.search(r'excede cap\. bodega \((\d+) u sobre cap\)', a)
        if m:
            exceso_u += int(m.group(1))
    return deficit_u, exceso_u


def descomponer(path: str, has_r12: bool) -> None:
    with open(path, encoding='utf-8') as f:
        d = json.load(f)

    opt = d.get('optimizacion', {})
    obj_reported = opt.get('objective_value', 0) or 0
    prod = [o for o in d['ordenes'] if o['tipo'] == 'PRODUCCION']

    deficit_u, exceso_u = parse_alerts(prod)
    setup_total = sum(1 for o in prod if o.get('paga_setup'))

    # Componentes (aproximacion via parsing de alertas en OFTs)
    c_def = deficit_u * W_DEFICIT
    c_exc = exceso_u * W_EXCESO
    c_ini = setup_total * W_INICIO if has_r12 else 0
    suma = c_def + c_exc + c_ini

    print(f'=== {path} ===')
    print(f'  obj_reported          : {obj_reported:>20,.0f}')
    print(f'  alertas opt (eventos) : {opt.get("alertas")}')
    print(f'  ofts_generadas        : {opt.get("ofts_generadas")}')
    print(f'  ofts paga_setup       : {setup_total:>20}')
    print(f'  ---  componentes  ---')
    print(f'  deficit_u (alert text): {deficit_u:>20,}')
    print(f'  exceso_u  (alert text): {exceso_u:>20,}')
    print(f'  W_DEFICIT * deficit_u : {c_def:>20,}')
    print(f'  W_EXCESO  * exceso_u  : {c_exc:>20,}')
    if has_r12:
        print(f'  W_INICIO  * setups    : {c_ini:>20,}')
    print(f'  suma componentes      : {suma:>20,}')
    print(f'  diff (obj - suma)     : {obj_reported - suma:>20,.0f}')
    print(f'  (residuo = W_ALT*asig_alt + def/exc en dias sin OFT)')
    print()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        # Convencion: si filename tiene 'r12' o 'post_r12', has_r12=True
        has_r12 = 'r12' in path.lower()
        descomponer(path, has_r12=has_r12)
