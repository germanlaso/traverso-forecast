"""
enviar_faltantes.py — Envía por correo el Informe de Quiebres de Stock de un día.

Lee los faltantes ya persistidos (tabla mrp_faltantes, que llena el cron de cálculo),
arma un correo HTML con el resumen del día + el Excel adjunto (faltantes_excel), y lo
envía por SMTP (Office 365, STARTTLS). Pensado para correr en el cron, DESPUÉS del
cálculo diario.

Configuración por variables de entorno (en el .env del container):
  SMTP_HOST      (default smtp.office365.com)
  SMTP_PORT      (default 587)
  SMTP_USER      (default operaciones@traverso.cl)
  SMTP_PWD       (obligatoria; la contraseña de la cuenta / app password)
  FALTANTES_DEST (obligatoria; destinatarios separados por coma)

Uso:
    python3 enviar_faltantes.py [YYYY-MM-DD]   # sin fecha => ayer
"""

import os
import sys
import ssl
import smtplib
import logging
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formataddr
from email.header import Header

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "operaciones@traverso.cl")
# Nombre visible del remitente (display name). Configurable por env.
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Operaciones Traverso - No Reply")

CAUSA_LABEL = {"sin_stock": "Sin stock (producción)",
               "vu_insuficiente": "VU insuficiente (rotación)"}


def _fecha_txt(f):
    p = str(f).split("-")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else str(f)


def _cuerpo_html(fecha, filas):
    """Arma el cuerpo HTML: total, split por causa, top SKU."""
    total = sum(float(r.get("faltante_cj", 0) or 0) for r in filas)
    por_causa = {}
    por_sku = {}
    for r in filas:
        cj = float(r.get("faltante_cj", 0) or 0)
        por_causa[r.get("causa", "")] = por_causa.get(r.get("causa", ""), 0) + cj
        k = (r["sku"], r.get("descripcion", ""))
        por_sku[k] = por_sku.get(k, 0) + cj
    top = sorted(por_sku.items(), key=lambda x: -x[1])[:5]

    if not filas:
        return (f"<p>Estimados,</p>"
                f"<p>El informe de quiebres del <b>{_fecha_txt(fecha)}</b> no registra "
                f"faltantes atribuibles a stock. </p>"
                f"<p>Saludos,<br>Sistema de Planificación de Producción · Traverso</p>")

    filas_causa = "".join(
        f"<tr><td style='padding:4px 12px'>{CAUSA_LABEL.get(c, c)}</td>"
        f"<td style='padding:4px 12px;text-align:right'><b>{v:,.0f}</b> cj</td></tr>"
        for c, v in sorted(por_causa.items(), key=lambda x: -x[1]))
    filas_top = "".join(
        f"<tr><td style='padding:3px 12px'>{d}</td>"
        f"<td style='padding:3px 12px;color:#666'>{s}</td>"
        f"<td style='padding:3px 12px;text-align:right'>{v:,.0f} cj</td></tr>"
        for (s, d), v in top)

    return f"""
    <div style="font-family:Arial,sans-serif;font-size:13px;color:#1A2332">
      <p>Estimados,</p>
      <p>Informe de quiebres de stock facturado del <b>{_fecha_txt(fecha)}</b>.</p>
      <p style="font-size:15px">Total del día: <b style="color:#C0392B">{total:,.0f} cajas</b>
         en {len(set(r['sku'] for r in filas))} productos.</p>
      <table style="border-collapse:collapse;margin:8px 0">
        <tr style="background:#1A2D4D;color:#fff">
          <th style="padding:6px 12px;text-align:left">Causa</th>
          <th style="padding:6px 12px;text-align:right">Cajas</th></tr>
        {filas_causa}
      </table>
      <p style="margin-top:14px"><b>Top 5 productos con faltante:</b></p>
      <table style="border-collapse:collapse">
        <tr style="background:#C0DCF0">
          <th style="padding:4px 12px;text-align:left">Cod. SAP</th>
          <th style="padding:4px 12px;text-align:left">Producto</th>
          <th style="padding:4px 12px;text-align:right">Faltante</th></tr>
        {filas_top}
      </table>
      <p style="margin-top:14px">Se adjunta el informe detallado en Excel
         (resumen por SKU + detalle por cliente).</p>
      <p style="color:#888;font-size:11px;margin-top:18px">
        Sistema de Planificación de Producción · Traverso · mensaje automático</p>
    </div>"""


def enviar(fecha=None, destinatarios=None):
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or os.environ.get("FALTANTES_DEST", "")
    dest_list = [d.strip() for d in dest.split(",") if d.strip()]
    if not dest_list:
        raise RuntimeError("Falta FALTANTES_DEST (destinatarios) en el entorno.")

    from db_mrp import get_faltantes_por_fecha
    import faltantes_excel
    filas = get_faltantes_por_fecha(fecha)
    logger.info("Faltantes del %s: %d filas.", fecha, len(filas))

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Informe de Quiebres de Stock — {_fecha_txt(fecha)} — Traverso"
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest_list)
    msg.attach(MIMEText(_cuerpo_html(fecha, filas), "html", "utf-8"))

    # adjuntar Excel (siempre, aunque no haya faltantes, para dejar registro)
    xls = faltantes_excel.generar_bytes(fecha, filas)
    adj = MIMEApplication(xls, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    adj.add_header("Content-Disposition", "attachment",
                   filename=f"Informe_Quiebres_{fecha}.xlsx")
    msg.attach(adj)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Correo enviado a: %s", ", ".join(dest_list))
    return True


def enviar_alerta(asunto, cuerpo_texto, destinatarios=None):
    """Envía un correo de alerta simple (texto plano). Usado por el wrapper del cron
    cuando el cálculo falla. Por defecto va solo al primer destinatario admin (o a
    FALTANTES_ALERTA si está definido)."""
    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or os.environ.get("FALTANTES_ALERTA") \
        or os.environ.get("FALTANTES_DEST", "").split(",")[0].strip()
    dest_list = [d.strip() for d in dest.split(",") if d.strip()] if isinstance(dest, str) else dest
    if not dest_list:
        raise RuntimeError("Sin destinatario para la alerta.")
    msg = MIMEText(cuerpo_texto, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest_list)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Alerta enviada a: %s", ", ".join(dest_list))
    return True


if __name__ == "__main__":
    f = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        enviar(f)
        print("ENVIO OK")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
