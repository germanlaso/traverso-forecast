"""
claude_api.py — Cliente mínimo de la API de Claude (solo librería estándar: urllib).

API key: variable de entorno ANTHROPIC_API_KEY o, si no existe, el archivo
/app/data/.anthropic_api_key (carpeta forecast/data/ del host, ignorada por git).
Sin la key, generar() lanza ClaudeNoConfigurado: el resto de la app sigue funcionando.

Prueba (dentro del contenedor):
  python3 /app/claude_api.py --test
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

URL = "https://api.anthropic.com/v1/messages"
VERSION_API = "2023-06-01"
MODELO_DEFECTO = os.environ.get("CLAUDE_MODELO", "claude-sonnet-5-5")
ARCHIVO_KEY = "/app/data/.anthropic_api_key"
# Precios de referencia (US$ por millón de tokens) para registrar el costo aproximado
PRECIOS = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


class ClaudeNoConfigurado(RuntimeError):
    pass


class ClaudeError(RuntimeError):
    pass


def _api_key() -> str:
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not k and os.path.exists(ARCHIVO_KEY):
        with open(ARCHIVO_KEY, encoding="utf-8") as f:
            k = f.read().strip()
    if not k:
        raise ClaudeNoConfigurado("No hay API key de Claude (ANTHROPIC_API_KEY o /app/data/.anthropic_api_key).")
    return k


def configurado() -> bool:
    try:
        _api_key()
        return True
    except ClaudeNoConfigurado:
        return False


def generar(system: str, usuario: str, max_tokens: int = 4000, modelo: str = None,
            temperatura: float = 0.2, reintentos: int = 3, timeout: int = 180) -> dict:
    """Una consulta (system + mensaje de usuario). Devuelve {texto, modelo, tokens_in, tokens_out,
    costo_usd, segundos}. Reintenta en 429/5xx con espera creciente."""
    modelo = modelo or MODELO_DEFECTO
    cuerpo = json.dumps({
        "model": modelo, "max_tokens": max_tokens, "temperature": temperatura,
        "system": system, "messages": [{"role": "user", "content": usuario}],
    }).encode("utf-8")
    headers = {"content-type": "application/json", "x-api-key": _api_key(), "anthropic-version": VERSION_API}
    t0, ultimo = time.time(), None
    for intento in range(reintentos + 1):
        try:
            req = urllib.request.Request(URL, data=cuerpo, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            texto = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            u = data.get("usage", {}) or {}
            ti, to = u.get("input_tokens", 0), u.get("output_tokens", 0)
            pin, pout = PRECIOS.get(modelo, (0, 0))
            return {"texto": texto, "modelo": data.get("model", modelo), "tokens_in": ti, "tokens_out": to,
                    "costo_usd": round(ti / 1e6 * pin + to / 1e6 * pout, 4),
                    "segundos": round(time.time() - t0, 1), "stop_reason": data.get("stop_reason")}
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", errors="replace")[:500]
            ultimo = ClaudeError(f"HTTP {e.code}: {detalle}")
            if e.code in (429, 500, 502, 503, 529) and intento < reintentos:
                time.sleep(5 * (2 ** intento))
                continue
            raise ultimo
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo = ClaudeError(f"Conexión: {e}")
            if intento < reintentos:
                time.sleep(5 * (2 ** intento))
                continue
            raise ultimo
    raise ultimo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        r = generar("Responde en español, en una sola línea.",
                    "Confirma que recibes este mensaje del sistema de planificación de Traverso.", max_tokens=60)
        print("OK |", r["modelo"], "|", r["texto"].strip(), "|", r["tokens_in"], "in /", r["tokens_out"], "out |",
              f"US$ {r['costo_usd']}", "|", r["segundos"], "s")
    else:
        ap.print_help()
