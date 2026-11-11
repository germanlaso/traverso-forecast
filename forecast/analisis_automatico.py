"""
analisis_automatico.py — Disparo AUTOMÁTICO de Análisis de Línea por excepción (MVP 2).

Después del plan diario, abre un caso para cada línea en ROJO ("no está pudiendo cumplir"),
con las mismas reglas que el botón "Analizar" (diagnóstico + palancas + IA). El sistema abre
casos; NUNCA aplica cambios (decisión 11-11-26).

Para no llenar la bandeja de casos repetidos:
  · Solo líneas en rojo del semáforo.
  · Si la línea ya tiene un caso de los últimos DIAS_ENFRIAMIENTO días (abierto o decidido),
    NO se abre otro, salvo que la situación EMPEORÓ:
       - la carga requerida subió >= EMPEORA_PTS puntos, o
       - aparecieron SKU nuevos con quiebre por capacidad.
  · Máximo MAX_CASOS_DIA casos por corrida (prioriza mayor carga y más SKU en quiebre).

Uso (dentro del contenedor, después del cron del plan y de conocimiento_empirico):
  python3 /app/analisis_automatico.py --dry-run     # muestra qué abriría
  python3 /app/analisis_automatico.py               # abre los casos (con IA)
Crontab sugerido (08:00 Chile):
  0 11 * * * docker exec -e PYTHONPATH=/app -w /app traverso_forecast python3 /app/analisis_automatico.py >> /home/ubuntu/traverso_analisis_auto.log 2>&1
"""
import argparse
import json
import logging
from datetime import date

import sqlalchemy as sa

import analisis_diagnostico as _ad
import analisis_linea as _al
from db_mrp import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analisis_automatico")

DIAS_ENFRIAMIENTO = 7
EMPEORA_PTS = 0.10
MAX_CASOS_DIA = 5
SOLICITANTE = "Sistema (automático)"


def _ultimo_caso(c, linea):
    r = c.execute(sa.text("""SELECT id, creado_en, estado, decision, sintomas, diagnostico
                             FROM mrp_analisis_casos
                             WHERE linea = :l AND estado <> 'error'
                               AND creado_en >= now() - make_interval(days => :d)
                             ORDER BY creado_en DESC LIMIT 1"""), {"l": linea, "d": DIAS_ENFRIAMIENTO}).first()
    return dict(r._mapping) if r else None


def _skus_capacidad(ln):
    return {q["sku"] for q in (ln.get("quiebres") or {}).get("capacidad", [])}


def evaluar(hoy: date = None):
    """Devuelve (abrir, omitir): listas de dicts con la línea y el motivo."""
    with engine.connect() as c:
        plan, piezas, lineas, sku_lineas, params = _al._cargar_desde_bd(c)
        try:
            demo = _al.capacidad_demostrada(hoy or date.today())
        except Exception:
            demo = {}
        carga = _al.calcular_carga(piezas["detalle_diario"], piezas["uso_linea"], piezas["alertas"], lineas,
                                   sku_lineas, params, 6, demo, piezas.get("entradas_fijas"))
        abrir, omitir = [], []
        for ln in carga["lineas"]:
            if ln["semaforo"] != "rojo":
                continue
            ult = _ultimo_caso(c, ln["linea"])
            disparo = {"plan_id": plan.id, "motivos": ln["motivos"], "max_carga_3sem": ln["max_carga_requerida_3sem"],
                       "skus_quiebre_capacidad": sorted(_skus_capacidad(ln))}
            if ult is None:
                abrir.append({**disparo, "linea": ln["linea"], "razon": "Línea en rojo sin caso reciente."})
                continue
            carga_ant = float(((ult.get("sintomas") or {}).get("max_carga_requerida_3sem")) or 0)
            skus_ant = {x.get("sku") for x in ((ult.get("diagnostico") or {}).get("evidencia") or {}).get("skus_quiebre", [])}
            nuevos = _skus_capacidad(ln) - skus_ant
            if ln["max_carga_requerida_3sem"] >= carga_ant + EMPEORA_PTS:
                abrir.append({**disparo, "linea": ln["linea"], "caso_anterior": ult["id"],
                              "razon": f"Empeoró: carga requerida {carga_ant:.0%} -> {ln['max_carga_requerida_3sem']:.0%}."})
            elif nuevos:
                abrir.append({**disparo, "linea": ln["linea"], "caso_anterior": ult["id"],
                              "razon": f"Empeoró: {len(nuevos)} SKU nuevo(s) con quiebre por capacidad ({', '.join(sorted(nuevos))})."})
            else:
                omitir.append({"linea": ln["linea"], "caso_reciente": ult["id"],
                               "razon": f"Ya tiene el caso #{ult['id']} de los últimos {DIAS_ENFRIAMIENTO} días y no empeoró."})
    abrir.sort(key=lambda x: (-x["max_carga_3sem"], -len(x["skus_quiebre_capacidad"])))
    return abrir, omitir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="solo muestra qué casos abriría")
    ap.add_argument("--sin-ia", action="store_true", help="abre los casos sin recomendación IA")
    ap.add_argument("--max", type=int, default=MAX_CASOS_DIA)
    a = ap.parse_args()
    abrir, omitir = evaluar()
    log.info(f"Líneas en rojo: {len(abrir) + len(omitir)} | abrir: {len(abrir)} | omitir: {len(omitir)}")
    for o in omitir:
        log.info(f"  omitir {o['linea']}: {o['razon']}")
    for x in abrir[a.max:]:
        log.info(f"  POSTERGADA {x['linea']} (tope de {a.max} casos por corrida): {x['razon']}")
    costo = 0.0
    for x in abrir[:a.max]:
        if a.dry_run:
            log.info(f"  [dry-run] abriría {x['linea']}: {x['razon']}")
            continue
        try:
            caso = _ad.ejecutar_analisis(x["linea"], SOLICITANTE, not a.sin_ia, "automatico",
                                         {k: v for k, v in x.items() if k != "linea"})
            meta = ((caso.get("recomendacion") or {}).get("_meta") or {})
            costo += float(meta.get("costo_usd") or 0)
            log.info(f"  caso #{caso['id']} {x['linea']} ({caso['estado']}): {x['razon']}")
        except Exception as e:
            log.error(f"  ERROR {x['linea']}: {e}")
    if not a.dry_run:
        log.info(f"Costo IA aproximado de la corrida: US$ {costo:.2f}")


if __name__ == "__main__":
    main()
