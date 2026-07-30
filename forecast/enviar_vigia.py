"""
enviar_vigia.py — Correo de alerta del Vigía de OV.

Recibe el reporte de `vigia_ov.evaluar()` ya FILTRADO por el anti-spam (sólo los
tramos que hay que notificar) y arma un correo HTML con el mismo formato visual del
informe de faltantes.

Config por entorno (reusa la del informe de faltantes si no se define aparte):
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PWD   (obligatoria la contraseña)
  VIGIA_DEST    destinatarios del aviso   (fallback: FALTANTES_DEST)
  VIGIA_ALERTA  destinatario de errores   (fallback: FALTANTES_ALERTA)

Uso directo (test, no pasa por el anti-spam):
    python3 -c "import vigia_ov, enviar_vigia; enviar_vigia.enviar(vigia_ov.evaluar())"
"""

import os
import ssl
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email.header import Header

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "operaciones@traverso.cl")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Operaciones Traverso - No Reply")

NAVY = "#1A2D4D"
CELESTE = "#C0DCF0"
ROJO = "#C0392B"
AMBAR = "#B87309"


def _f(iso):
    p = str(iso).split("-")
    return f"{p[2]}-{p[1]}" if len(p) == 3 else str(iso)


def _dest(env_principal, env_fallback):
    d = os.environ.get(env_principal) or os.environ.get(env_fallback, "")
    return [x.strip() for x in d.split(",") if x.strip()]


def _bloque_sku(r):
    """HTML de un SKU: sus tramos + las OV que lo causaron."""
    filas_tr = []
    for t in r["tramos"]:
        rango = (_f(t["desde"]) if t["dias"] == 1
                 else f"{_f(t['desde'])} al {_f(t['hasta'])} ({t['dias']} días)")
        if t["clase"] == "CRITICO":
            etq = f"<b style='color:{ROJO}'>CRÍTICO</b>"
            accion = (f"Ni con las OFT propuestas del plan ({t['oft_acum_cj']:,.0f} cj) "
                      f"se cubre: quedaría {t['con_oft_cj']:,.0f} cj. "
                      f"<b>Requiere decisión</b> (OFM express, mover carga o avisar al cliente).")
        else:
            etq = f"<b style='color:{AMBAR}'>Aprobar OFT</b>"
            accion = (f"Se cubre aprobando las OFT que el plan ya propuso "
                      f"({t['oft_acum_cj']:,.0f} cj acumuladas): quedaría "
                      f"{t['con_oft_cj']:,.0f} cj.")
        filas_tr.append(
            f"<tr><td style='padding:4px 10px'>{rango}</td>"
            f"<td style='padding:4px 10px'>{etq}</td>"
            f"<td style='padding:4px 10px;text-align:right;color:{ROJO}'>"
            f"<b>−{t['deficit_max_cj']:,.0f} cj</b></td>"
            f"<td style='padding:4px 10px;font-size:11.5px'>{accion}</td></tr>")

    filas_ov = []
    for inc in r.get("incrementos", []):
        for o in inc["ovs"]:
            v = " <span style='color:#888'>(vencida, arrastrada a hoy)</span>" if o["vencida"] else ""
            filas_ov.append(
                f"<tr><td style='padding:3px 10px'>{_f(inc['fecha'])}</td>"
                f"<td style='padding:3px 10px'>OV {o['doc']} <span style='color:#888'>"
                f"[{o['bd']}]</span></td>"
                f"<td style='padding:3px 10px'>{o.get('cliente', '')}</td>"
                f"<td style='padding:3px 10px;text-align:right'>{o['cajas']:,.0f} cj</td>"
                f"</tr>{v}")
    tabla_ov = ""
    if filas_ov:
        tabla_ov = f"""
        <p style="margin:8px 0 2px;font-size:12px"><b>Pedidos nuevos respecto al plan:</b></p>
        <table style="border-collapse:collapse;font-size:12px">
          <tr style="background:{CELESTE}">
            <th style="padding:3px 10px;text-align:left">Entrega</th>
            <th style="padding:3px 10px;text-align:left">OV</th>
            <th style="padding:3px 10px;text-align:left">Cliente</th>
            <th style="padding:3px 10px;text-align:right">Cantidad</th></tr>
          {''.join(filas_ov)}
        </table>"""
    else:
        tabla_ov = ("<p style='margin:8px 0;font-size:11.5px;color:#888'>Sin pedidos "
                    "nuevos en la ventana: el déficit viene del arrastre de OV anteriores.</p>")

    aviso = ""
    if r["arrastre_ov_vencida_u"] > 0:
        aviso = ("<p style='margin:6px 0;font-size:11.5px;color:#B87309'>⚠ Este SKU tiene "
                 "OV vencidas arrastradas al día de hoy. Si alguna debía anularse en SAP, "
                 "parte de este déficit puede no ser real.</p>")

    return f"""
      <div style="border-left:3px solid {NAVY};padding:6px 0 6px 12px;margin:16px 0">
        <p style="margin:0 0 6px"><b>{r['sku']}</b> — {r['descripcion']}
           <span style="color:#888;font-size:12px">· línea {r['linea'] or '—'}</span></p>
        <table style="border-collapse:collapse;font-size:12px;width:100%">
          <tr style="background:{NAVY};color:#fff">
            <th style="padding:4px 10px;text-align:left">Días</th>
            <th style="padding:4px 10px;text-align:left">Situación</th>
            <th style="padding:4px 10px;text-align:right">Déficit máx.</th>
            <th style="padding:4px 10px;text-align:left">Acción</th></tr>
          {''.join(filas_tr)}
        </table>
        {aviso}
        {tabla_ov}
      </div>"""


def _cuerpo_html(rep, notificar):
    n_crit = len([r for r in notificar if r["criticos"]])
    intro_crit = (f"<span style='color:{ROJO}'><b>{n_crit} crítico(s)</b></span> · "
                  if n_crit else "")
    return f"""
    <div style="font-family:Arial,sans-serif;font-size:13px;color:#1A2332">
      <p>Estimados,</p>
      <p>Se detectaron <b>{len(notificar)} producto(s)</b> que quedarían en quiebre por
         pedidos cargados <b>después</b> de generarse el plan vigente.</p>
      <p style="font-size:12px;color:#555">
        {intro_crit}Ventana evaluada: {_f(rep['ventana'][0])} al {_f(rep['ventana'][1])}
        (5 días hábiles) · Plan #{rep['plan_id']} · Stock al momento de ese plan.</p>
      <p style="font-size:12px;color:#555">
        La evaluación considera <b>sólo órdenes aprobadas</b> (OF/OFM). Las OFT propuestas
        por el plan no cuentan como cobertura hasta que se aprueban, y se indica cuándo
        alcanza con aprobarlas.</p>
      {''.join(_bloque_sku(r) for r in notificar)}
      <p style="color:#888;font-size:11px;margin-top:18px">
        Vigía de OV · Sistema de Planificación de Producción · Traverso · mensaje automático</p>
    </div>"""


def enviar(rep, notificar=None, destinatarios=None):
    """Envía el aviso. `notificar` = subconjunto de rep['sku_alerta'] a informar.

    Si no se pasa `notificar`, se informa todo lo detectado (modo test: no pasa por
    el anti-spam del wrapper).
    """
    notificar = notificar if notificar is not None else rep.get("sku_alerta", [])
    if not notificar:
        logger.info("Nada que notificar.")
        return False

    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or _dest("VIGIA_DEST", "FALTANTES_DEST")
    if not dest:
        raise RuntimeError("Falta VIGIA_DEST/FALTANTES_DEST en el entorno.")

    n_crit = len([r for r in notificar if r["criticos"]])
    pref = "🔴 " if n_crit else "⚠ "
    msg = MIMEMultipart("alternative")
    msg["Subject"] = (f"{pref}Vigía de OV — {len(notificar)} producto(s) en riesgo por "
                      f"pedidos nuevos — Traverso")
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest)
    msg.attach(MIMEText(_cuerpo_html(rep, notificar), "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Aviso del vigía enviado a: %s (%d SKU, %d críticos)",
                ", ".join(dest), len(notificar), n_crit)
    return True


def enviar_alerta(asunto, cuerpo_texto, destinatarios=None):
    """Alerta de error, sólo al admin. Igual patrón que enviar_faltantes."""
    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or _dest("VIGIA_ALERTA", "FALTANTES_ALERTA") \
        or _dest("FALTANTES_DEST", "FALTANTES_DEST")[:1]
    if not dest:
        raise RuntimeError("Sin destinatario para la alerta.")
    msg = MIMEText(cuerpo_texto, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Alerta de error enviada a: %s", ", ".join(dest))
    return True
