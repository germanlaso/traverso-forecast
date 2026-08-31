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


def _faltantes_v2_on() -> bool:
    """True si el feature Faltantes V2 está activo (mismo flag que el backend)."""
    return os.environ.get("FALTANTES_V2_ENABLED", "0") in ("1", "true", "True", "yes")


def _repo_map_de(filas):
    """Mapa de reposición {sku: {tipo, valor}} para las filas del informe (Faltantes V2).

    Regla (b): para CADA SKU la reposición se calcula contra la fecha MÁS RECIENTE
    en que ESE SKU tuvo faltante dentro del informe — NO contra una única fecha del
    rango. Esto hace que el correo coincida con el dashboard (que evalúa la
    reposición por la fecha de la fila): una OF del 29 es 'futura' para un quiebre
    del 28 aunque el informe llegue hasta el 30.

    Antes se usaba ref = max(fechas) para todas las filas -> un SKU que solo quebró
    el 28 se medía contra el 30 y una OF del 29 salía como 'Sin OF futura' (bug).

    Devuelve {} si V2 está off o no hay filas."""
    if not _faltantes_v2_on() or not filas:
        return {}
    try:
        from db_mrp import get_fecha_reposicion_map
        # última fecha de quiebre por SKU (regla b)
        ultima_por_sku = {}
        for r in filas:
            sku = r.get("sku")
            f = str(r.get("fecha", ""))[:10]
            if not sku or not f:
                continue
            if sku not in ultima_por_sku or f > ultima_por_sku[sku]:
                ultima_por_sku[sku] = f
        # un mapa por cada fecha involucrada (cacheado: máx. una llamada por fecha),
        # y se toma la entrada del SKU contra SU última fecha de quiebre.
        cache, out = {}, {}
        for sku, f in ultima_por_sku.items():
            m = cache.get(f)
            if m is None:
                m = get_fecha_reposicion_map(f)
                cache[f] = m
            if sku in m:
                out[sku] = m[sku]
        return out
    except Exception as e:
        logger.warning("No se pudo calcular reposición V2 (%s). Se omite.", e)
        return {}


def _repo_txt_html(rp):
    """Texto de reposición para el cuerpo HTML del correo (Faltantes V2)."""
    if not rp:
        return ""
    tipo = rp.get("tipo"); valor = rp.get("valor")
    if tipo == "auto":
        return _fecha_txt(valor) if valor else ""
    if tipo == "inactivo":
        return "SKU inactivo"
    if tipo == "sin_of":
        return "Sin OF futura"
    if tipo == "manual":
        return _fecha_txt(valor) if valor else "—"
    return ""


def _fecha_txt(f):
    p = str(f).split("-")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else str(f)


def _fechas_iso(desde, hasta):
    """Lista de fechas ISO del rango, inclusive."""
    from datetime import date as _d
    d1 = desde if isinstance(desde, _d) else datetime.strptime(str(desde)[:10], "%Y-%m-%d").date()
    d2 = hasta if isinstance(hasta, _d) else datetime.strptime(str(hasta)[:10], "%Y-%m-%d").date()
    out, d = [], d1
    while d <= d2:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _filas_de(fechas):
    """Concatena los faltantes de varias fechas. Cada fila conserva su campo `fecha`,
    así que el detalle por día no se pierde (el dashboard los sigue mostrando
    separados porque mrp_faltantes guarda por fecha)."""
    from db_mrp import get_faltantes_por_fecha
    filas = []
    for f in fechas:
        filas.extend(get_faltantes_por_fecha(f))
    return filas


def _tabla_por_dia(filas):
    """Desglose por día. Solo se usa cuando el informe cubre más de una fecha
    (típicamente el lunes, que reporta viernes + fin de semana)."""
    por_dia = {}
    for r in filas:
        k = str(r.get("fecha", ""))[:10]
        por_dia[k] = por_dia.get(k, 0) + float(r.get("faltante_cj", 0) or 0)
    if len(por_dia) <= 1:
        return ""
    filas_html = "".join(
        f"<tr><td style='padding:4px 12px'>{_fecha_txt(d)}</td>"
        f"<td style='padding:4px 12px;text-align:right'><b>{v:,.0f}</b> cj</td></tr>"
        for d, v in sorted(por_dia.items()))
    return f"""
      <p style="margin-top:14px"><b>Detalle por día:</b></p>
      <table style="border-collapse:collapse;margin:4px 0">
        <tr style="background:#C0DCF0">
          <th style="padding:6px 12px;text-align:left">Fecha</th>
          <th style="padding:6px 12px;text-align:right">Cajas</th></tr>
        {filas_html}
      </table>"""


def _cuerpo_html(fecha, filas, reposicion=None):
    """Arma el cuerpo HTML: total, split por causa, top SKU.
    reposicion: dict opcional {sku: {tipo, valor}} — si se pasa (Faltantes V2),
    agrega la columna 'Reposición' a la tabla de productos."""
    reposicion = reposicion or {}
    con_repo = bool(reposicion)
    total = sum(float(r.get("faltante_cj", 0) or 0) for r in filas)
    por_causa = {}
    por_sku = {}
    for r in filas:
        cj = float(r.get("faltante_cj", 0) or 0)
        por_causa[r.get("causa", "")] = por_causa.get(r.get("causa", ""), 0) + cj
        k = (r["sku"], r.get("descripcion", ""))
        por_sku[k] = por_sku.get(k, 0) + cj
    top = sorted(por_sku.items(), key=lambda x: -x[1])

    if not filas:
        return (f"<p>Estimados,</p>"
                f"<p>El informe de quiebres del <b>{_fecha_txt(fecha)}</b> no registra "
                f"faltantes atribuibles a stock. </p>"
                f"<p>Saludos,<br>Sistema de Planificación de Producción · Traverso</p>")

    filas_causa = "".join(
        f"<tr><td style='padding:4px 12px'>{CAUSA_LABEL.get(c, c)}</td>"
        f"<td style='padding:4px 12px;text-align:right'><b>{v:,.0f}</b> cj</td></tr>"
        for c, v in sorted(por_causa.items(), key=lambda x: -x[1]))
    # columna extra de reposición (Faltantes V2)
    col_repo_hdr = ("<th style='padding:4px 12px;text-align:left'>Reposición</th>"
                    if con_repo else "")
    filas_top = "".join(
        f"<tr><td style='padding:3px 12px'>{d}</td>"
        f"<td style='padding:3px 12px;color:#666'>{s}</td>"
        f"<td style='padding:3px 12px;text-align:right'>{v:,.0f} cj</td>"
        + (f"<td style='padding:3px 12px;color:#444'>{_repo_txt_html(reposicion.get(s))}</td>"
           if con_repo else "")
        + "</tr>"
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
      <p style="margin-top:14px"><b>Productos con faltante (ordenados por magnitud):</b></p>
      <table style="border-collapse:collapse">
        <tr style="background:#C0DCF0">
          <th style="padding:4px 12px;text-align:left">Cod. SAP</th>
          <th style="padding:4px 12px;text-align:left">Producto</th>
          <th style="padding:4px 12px;text-align:right">Faltante</th>{col_repo_hdr}</tr>
        {filas_top}
      </table>
      {_tabla_por_dia(filas)}
      <p style="margin-top:14px">Se adjunta el informe detallado en Excel
         (resumen por SKU + detalle por cliente).</p>
      <p style="color:#888;font-size:11px;margin-top:18px">
        Sistema de Planificación de Producción · Traverso · mensaje automático</p>
    </div>"""


def enviar(fecha=None, destinatarios=None, desde=None, hasta=None):
    """Correo de las 8 AM.

    Modo día único (comportamiento histórico): se pasa `fecha`.
    Modo rango: se pasan `desde` y `hasta`; el correo cubre todos esos días en un
    solo envío. Lo usa cron_faltantes.py para que el lunes reporte viernes + fin de
    semana sin mandar correos en días no hábiles.
    """
    if desde is not None and hasta is not None:
        from dias_informe import etiqueta_rango
        import datetime as _dt
        d1 = desde if isinstance(desde, date) else _dt.date.fromisoformat(str(desde)[:10])
        d2 = hasta if isinstance(hasta, date) else _dt.date.fromisoformat(str(hasta)[:10])
        fechas = _fechas_iso(d1, d2)
        etiqueta = etiqueta_rango(d1, d2)
        sufijo_archivo = d1.isoformat() if d1 == d2 else f"{d1.isoformat()}_a_{d2.isoformat()}"
    else:
        fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
        fechas = [str(fecha)[:10]]
        etiqueta = str(fecha)[:10]
        sufijo_archivo = str(fecha)[:10]

    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or os.environ.get("FALTANTES_DEST_AM") \
        or os.environ.get("FALTANTES_DEST", "")
    dest_list = [d.strip() for d in dest.split(",") if d.strip()]
    if not dest_list:
        raise RuntimeError("Falta FALTANTES_DEST_AM/FALTANTES_DEST (destinatarios) en el entorno.")

    import faltantes_excel
    filas = _filas_de(fechas)
    logger.info("Faltantes de %s (%d día/s): %d filas.", etiqueta, len(fechas), len(filas))

    # Faltantes V2: el correo 8 AM lleva la fecha de reposición (automática, y la
    # manual autollenada si existe), pero NO explicación ni solución (aún nadie las
    # cargó — la ventana de carga es 8-11).
    repo_map = _repo_map_de(filas)
    con_v2 = _faltantes_v2_on()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Informe de Quiebres de Stock — {_fecha_txt(etiqueta)} — Traverso"
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest_list)
    msg.attach(MIMEText(_cuerpo_html(etiqueta, filas, reposicion=repo_map), "html", "utf-8"))

    # adjuntar Excel (siempre, aunque no haya faltantes, para dejar registro)
    xls = faltantes_excel.generar_bytes(etiqueta, filas, reposicion=repo_map, con_v2=con_v2)
    adj = MIMEApplication(xls, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    adj.add_header("Content-Disposition", "attachment",
                   filename=f"Informe_Quiebres_{sufijo_archivo}.xlsx")
    msg.attach(adj)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Correo enviado a: %s", ", ".join(dest_list))
    return True


def _cuerpo_html_final(fecha, filas, explicaciones, soluciones=None, reposicion=None):
    """Cuerpo HTML del correo final (11 AM): base + tabla de explicaciones por SKU.
    soluciones/reposicion: Faltantes V2. Si se pasan, el cuerpo base lleva la
    columna Reposición y la tabla de gestión incluye la Solución junto a la
    Explicación."""
    soluciones = soluciones or {}
    reposicion = reposicion or {}
    con_v2 = bool(soluciones) or bool(reposicion)
    base = _cuerpo_html(fecha, filas, reposicion=reposicion)
    # tabla de explicaciones (+ solución en V2) por SKU
    skus_con_falta = {}
    for r in filas:
        k = (r["sku"], r.get("descripcion", ""))
        skus_con_falta[k] = skus_con_falta.get(k, 0) + float(r.get("faltante_cj", 0) or 0)

    filas_exp = []
    for (sku, desc), cj in sorted(skus_con_falta.items(), key=lambda x: -x[1]):
        ex = explicaciones.get(sku, {})
        txt = (ex.get("explicacion") or "").strip()
        autor = (ex.get("autor") or "").strip()
        so = soluciones.get(sku, {})
        txt_sol = (so.get("solucion") or "").strip()
        aut_sol = (so.get("solucion_autor") or "").strip()
        # En V2 mostramos la fila si hay explicación O solución; sin V2, solo si hay explicación
        if con_v2:
            if not txt and not txt_sol:
                continue
        else:
            if not txt:
                continue
        meta = f"<span style='color:#888;font-size:11px'> — {autor}</span>" if autor else ""
        celda_expl = f"{txt}{meta}" if txt else "<span style='color:#bbb'>—</span>"
        if con_v2:
            meta_sol = f"<span style='color:#888;font-size:11px'> — {aut_sol}</span>" if aut_sol else ""
            celda_sol = f"{txt_sol}{meta_sol}" if txt_sol else "<span style='color:#bbb'>—</span>"
            filas_exp.append(
                f"<tr><td style='padding:4px 12px;vertical-align:top'><b>{sku}</b><br>"
                f"<span style='color:#666;font-size:11px'>{desc}</span></td>"
                f"<td style='padding:4px 12px;vertical-align:top'>{celda_expl}</td>"
                f"<td style='padding:4px 12px;vertical-align:top'>{celda_sol}</td></tr>")
        else:
            filas_exp.append(
                f"<tr><td style='padding:4px 12px;vertical-align:top'><b>{sku}</b><br>"
                f"<span style='color:#666;font-size:11px'>{desc}</span></td>"
                f"<td style='padding:4px 12px'>{celda_expl}</td></tr>")

    if filas_exp:
        if con_v2:
            cab = ("<th style='padding:6px 12px;text-align:left'>Producto</th>"
                   "<th style='padding:6px 12px;text-align:left'>Explicación</th>"
                   "<th style='padding:6px 12px;text-align:left'>Solución propuesta</th>")
            titulo = "Explicaciones y soluciones incorporadas por las áreas:"
        else:
            cab = ("<th style='padding:6px 12px;text-align:left'>Producto</th>"
                   "<th style='padding:6px 12px;text-align:left'>Explicación</th>")
            titulo = "Explicaciones incorporadas por las áreas:"
        tabla_exp = f"""
      <p style="margin-top:16px"><b>{titulo}</b></p>
      <table style="border-collapse:collapse;width:100%">
        <tr style="background:#1A2D4D;color:#fff">
          {cab}</tr>
        {''.join(filas_exp)}
      </table>"""
    else:
        tabla_exp = ("<p style='margin-top:16px;color:#888'>No se incorporaron "
                     "explicaciones para los faltantes de este día.</p>")

    # insertar la tabla de explicaciones antes del pie del cuerpo base
    marca = '<p style="color:#888;font-size:11px;margin-top:18px">'
    if marca in base:
        return base.replace(marca, tabla_exp + "\n      " + marca, 1)
    return base + tabla_exp


def enviar_final(fecha=None, destinatarios=None, desde=None, hasta=None):
    """Correo FINAL (11 AM) al grupo ampliado, con las explicaciones incorporadas.
    Se envía aunque no haya explicaciones. Usa FALTANTES_DEST_FINAL.

    Acepta día único (`fecha`) o rango (`desde`/`hasta`), igual que enviar()."""
    if desde is not None and hasta is not None:
        from dias_informe import etiqueta_rango
        import datetime as _dt
        d1 = desde if isinstance(desde, date) else _dt.date.fromisoformat(str(desde)[:10])
        d2 = hasta if isinstance(hasta, date) else _dt.date.fromisoformat(str(hasta)[:10])
        fechas = _fechas_iso(d1, d2)
        etiqueta = etiqueta_rango(d1, d2)
        sufijo_archivo = d1.isoformat() if d1 == d2 else f"{d1.isoformat()}_a_{d2.isoformat()}"
    else:
        fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
        fechas = [str(fecha)[:10]]
        etiqueta = str(fecha)[:10]
        sufijo_archivo = str(fecha)[:10]

    pwd = os.environ.get("SMTP_PWD")
    if not pwd:
        raise RuntimeError("Falta SMTP_PWD en el entorno.")
    dest = destinatarios or os.environ.get("FALTANTES_DEST_FINAL", "")
    dest_list = [d.strip() for d in dest.split(",") if d.strip()]
    if not dest_list:
        raise RuntimeError("Falta FALTANTES_DEST_FINAL (destinatarios) en el entorno.")

    from db_mrp import get_explicaciones_faltantes
    import faltantes_excel
    filas = _filas_de(fechas)
    # Explicaciones de todas las fechas del rango. Si un mismo SKU tiene explicación
    # en más de un día, gana la más reciente (se recorre en orden cronológico).
    explic = {}
    for f in fechas:
        explic.update(get_explicaciones_faltantes(f) or {})

    # Faltantes V2: soluciones + reposición (solo si el feature está on)
    con_v2 = _faltantes_v2_on()
    soluc = {}
    if con_v2:
        try:
            from db_mrp import get_soluciones_faltantes
            for f in fechas:
                soluc.update(get_soluciones_faltantes(f) or {})
        except Exception as e:
            logger.warning("No se pudieron leer soluciones V2 (%s). Se omiten.", e)
    repo_map = _repo_map_de(filas)

    logger.info("Informe final de %s (%d día/s): %d filas, %d explicaciones.",
                etiqueta, len(fechas), len(filas),
                len([e for e in explic.values() if (e.get('explicacion') or '').strip()]))

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Informe de Quiebres de Stock (final) — {_fecha_txt(etiqueta)} — Traverso"
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = ", ".join(dest_list)
    msg.attach(MIMEText(_cuerpo_html_final(etiqueta, filas, explic,
                                           soluciones=soluc, reposicion=repo_map),
                        "html", "utf-8"))

    xls = faltantes_excel.generar_bytes(etiqueta, filas, explic,
                                        soluciones=soluc, reposicion=repo_map, con_v2=con_v2)
    adj = MIMEApplication(xls, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    adj.add_header("Content-Disposition", "attachment",
                   filename=f"Informe_Quiebres_{sufijo_archivo}.xlsx")
    msg.attach(adj)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(SMTP_USER, pwd)
        s.send_message(msg)
    logger.info("Correo FINAL enviado a: %s", ", ".join(dest_list))
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
