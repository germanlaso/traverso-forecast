"""
enviar_informe_ventas.py — Envía por correo el informe diario de ventas + stock.

Recibe el reporte de `informe_ventas.ejecutar()` y manda un correo HTML con el resumen
y el Excel adjunto.

Config por entorno:
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PWD
  INFORME_VENTAS_DEST    destinatarios — OBLIGATORIA, SIN fallback.
                         Es un informe comercial: su público NO es el del informe de
                         faltantes ni el del vigía. Caer en otra lista lo mandaría a
                         quien no corresponde, y en silencio.
  INFORME_VENTAS_ALERTA  errores (fallback: FALTANTES_ALERTA — el admin es el mismo).
"""

# ── Ruta de los módulos compartidos ──────────────────────────────────────────
# Este paquete vive en una subcarpeta, pero usa módulos que están en la raíz de la
# app (db.py, stock.py). Se agrega esa raíz al path para poder importarlos.
# TRAVERSO_APP_DIR permite override si el montaje cambia.
import os as _os
import sys as _sys
_APP_DIR = _os.environ.get("TRAVERSO_APP_DIR", "/app")
if _APP_DIR not in _sys.path:
    _sys.path.insert(0, _APP_DIR)


import os
import ssl
import smtplib
import logging
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
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Operaciones Traverso - No Reply")

NAVY = "#1A2D4D"
CELESTE = "#C0DCF0"
AMBAR = "#B87309"

# Fuera de la f-string a propósito: Python < 3.12 no admite backslashes dentro de la
# expresión de una f-string, y el container corre una versión anterior.
_EN_CURSO = ' <span style="color:#888">(en curso)</span>'


def _fecha_txt(iso):
    p = str(iso).split("-")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else str(iso)


def _dest(env):
    return [x.strip() for x in os.environ.get(env, "").split(",") if x.strip()]


def _cuerpo_html(rep):
    df, meses = rep["df"], rep["meses"]

    # Top 10 por venta del período
    top = df.nlargest(10, "total")[["sku", "nombre", "total", "stock_cj"]]
    filas_top = "".join(
        f"<tr><td style='padding:3px 10px'>{r['sku']}</td>"
        f"<td style='padding:3px 10px'>{str(r['nombre'])[:44]}</td>"
        f"<td style='padding:3px 10px;text-align:right'>{int(r['total']):,}</td>"
        f"<td style='padding:3px 10px;text-align:right'>{int(r['stock_cj']):,}</td></tr>"
        for _, r in top.iterrows())

    # Resumen por categoría
    cat = (df.groupby("categoria")[["total", "stock_cj"]].sum()
           .sort_values("total", ascending=False))
    filas_cat = "".join(
        f"<tr><td style='padding:3px 10px'>{c}</td>"
        f"<td style='padding:3px 10px;text-align:right'>{int(v['total']):,}</td>"
        f"<td style='padding:3px 10px;text-align:right'>{int(v['stock_cj']):,}</td></tr>"
        for c, v in cat.iterrows())

    # Últimos dos meses cerrados + mes en curso, para ver la tendencia de un vistazo
    ult = meses[-3:]
    filas_mes = "".join(
        f"<tr><td style='padding:3px 10px'>{m}"
        f"{_EN_CURSO if m == meses[-1] else ''}</td>"
        f"<td style='padding:3px 10px;text-align:right'>{int(df[m].sum()):,}</td></tr>"
        for m in ult)

    # Excluidos: se informa SIEMPRE, aunque sea para decir que no hay
    n_ex = len(rep["excluidos"])
    if n_ex:
        ventas_ex = sum(int(e["total"]) for e in rep["excluidos"])
        top_ex = "".join(
            f"<li>{e['sku']} — {str(e['nombre'])[:40]} "
            f"({int(e['total']):,} cj)</li>"
            for e in rep["excluidos"][:5] if int(e["total"]) > 0)
        bloque_ex = f"""
      <div style="background:#FAEEDA;border-left:3px solid {AMBAR};padding:8px 12px;margin:14px 0">
        <p style="margin:0 0 4px"><b>{n_ex} SKU quedaron fuera del informe</b>
           por no tener U por caja cargada
           {f'({ventas_ex:,} cj de venta en el período)' if ventas_ex else ''}.</p>
        <ul style="margin:4px 0 4px 18px;font-size:12px">{top_ex}</ul>
        <p style="margin:4px 0 0;font-size:11.5px">Se listan todos en la hoja
           <b>Excluidos</b> del Excel. Para que aparezcan, cargarlos en
           <i>Parametros_Informe_Ventas.xlsx</i>.</p>
      </div>"""
    else:
        bloque_ex = ("<p style='font-size:12px;color:#888;margin:14px 0'>Todos los SKU "
                     "con venta o stock tienen sus datos maestros cargados.</p>")

    return f"""
    <div style="font-family:Arial,sans-serif;font-size:13px;color:#1A2332">
      <p>Estimados,</p>
      <p>Informe de <b>ventas por mes y stock por SKU</b> al {_fecha_txt(rep['hoy'])}.</p>
      <p style="font-size:12px;color:#555">
        Período: <b>{meses[0]} a {meses[-1]}</b> ({len(meses)-1} meses enteros + mes en
        curso) · ventas brutas (sólo Facturas, sin NC ni ND) · en cajas ·
        stock al {rep['fecha_stock']} (Traverso + Montaner, 3 bodegas despachables).</p>

      <p style="font-size:15px;margin-top:14px">
        {len(df)} productos · ventas del período
        <b style="color:{NAVY}">{rep['total_ventas']:,} cajas</b> ·
        stock actual <b style="color:{NAVY}">{rep['total_stock']:,} cajas</b></p>

      <table style="border-collapse:collapse;font-size:12px;margin:10px 0">
        <tr style="background:{NAVY};color:#fff">
          <th style="padding:5px 10px;text-align:left">Últimos meses</th>
          <th style="padding:5px 10px;text-align:right">Cajas</th></tr>
        {filas_mes}
      </table>

      <p style="margin-top:14px"><b>Por categoría:</b></p>
      <table style="border-collapse:collapse;font-size:12px">
        <tr style="background:{CELESTE}">
          <th style="padding:4px 10px;text-align:left">Categoría</th>
          <th style="padding:4px 10px;text-align:right">Ventas período</th>
          <th style="padding:4px 10px;text-align:right">Stock</th></tr>
        {filas_cat}
      </table>

      <p style="margin-top:14px"><b>Top 10 por venta del período:</b></p>
      <table style="border-collapse:collapse;font-size:12px">
        <tr style="background:{CELESTE}">
          <th style="padding:4px 10px;text-align:left">Cod. SAP</th>
          <th style="padding:4px 10px;text-align:left">Producto</th>
          <th style="padding:4px 10px;text-align:right">Ventas</th>
          <th style="padding:4px 10px;text-align:right">Stock</th></tr>
        {filas_top}
      </table>

      {bloque_ex}

      <p style="margin-top:14px">Se adjunta el detalle completo en Excel (una fila por
         SKU, con U por caja, formato, color, stock y las ventas de cada mes).</p>
      <p style="color:#888;font-size:11px;margin-top:18px">
        Sistema de Planificación de Producción · Traverso · mensaje automático</p>
    </div>"""


def enviar(rep, ruta_xlsx, destinatarios=None):
    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or _dest("INFORME_VENTAS_DEST")
    if not dest:
        raise RuntimeError(
            "Falta INFORME_VENTAS_DEST en el entorno. Este informe NO usa los "
            "destinatarios de faltantes ni del vigía: son públicos distintos. "
            "Definirla en el .env, declararla en el environment: del docker-compose.yml "
            "(que está en la RAÍZ) y recrear con 'docker compose up -d forecast'.")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = (f"Informe de Ventas y Stock por SKU — "
                      f"{_fecha_txt(rep['hoy'])} — Traverso")
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest)
    msg.attach(MIMEText(_cuerpo_html(rep), "html", "utf-8"))

    with open(ruta_xlsx, "rb") as f:
        adj = MIMEApplication(
            f.read(),
            _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    adj.add_header("Content-Disposition", "attachment",
                   filename=os.path.basename(ruta_xlsx))
    msg.attach(adj)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Informe enviado a: %s (adjunto %s)",
                ", ".join(dest), os.path.basename(ruta_xlsx))
    return True


def enviar_alerta(asunto, cuerpo_texto, destinatarios=None):
    """Alerta de error, sólo al admin."""
    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or _dest("INFORME_VENTAS_ALERTA") or _dest("FALTANTES_ALERTA")
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
    logger.info("Alerta enviada a: %s", ", ".join(dest))
    return True
