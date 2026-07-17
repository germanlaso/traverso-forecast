"""
faltantes_excel.py — Genera el Excel del "Informe de Quiebres de Stock Facturado"
para un día, replicando el formato del informe manual de Traverso (Planificación).

Dos pestañas:
  - "Informe": encabezado + KPIs del día + tabla RESUMEN POR SKU (Producto, Cod SAP,
    Causa, Stock, Programado, Faltante, %). % = faltante del SKU / total del día.
  - "Detalle por cliente": Producto, Cod SAP, Cliente, Causa, Faltante.

Lee los datos ya persistidos vía db_mrp.get_faltantes_por_fecha(fecha) (solo lectura).
Devuelve los bytes del .xlsx (para servir por el endpoint) o lo escribe a un path.
"""

import io
from datetime import date, datetime
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Paleta corporativa (del informe de referencia)
AZUL   = "1A2D4D"
CELESTE = "C0DCF0"
GRIS   = "F2F4F7"
GRIS_TXT = "4A5568"
BLANCO = "FFFFFF"

CAUSA_LABEL = {"sin_stock": "SIN STOCK", "vu_insuficiente": "VU INSUFICIENTE"}

_thin = Side(style="thin", color="D3D1C7")
BORDE = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _f(size=9, bold=False, color=AZUL, name="Arial"):
    return Font(name=name, size=size, bold=bold, color=color)


def _fill(hexcolor):
    return PatternFill("solid", fgColor=hexcolor)


def _fecha_txt(f):
    if isinstance(f, (date, datetime)):
        return f.strftime("%d-%m-%Y")
    # 'YYYY-MM-DD' -> 'DD-MM-YYYY'
    p = str(f).split("-")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else str(f)


def construir(fecha, filas):
    """fecha: str YYYY-MM-DD | date. filas: list de dicts de get_faltantes_por_fecha.
    Devuelve un openpyxl Workbook."""
    fecha_str = fecha if isinstance(fecha, str) else fecha.isoformat()

    # --- agregación por SKU ---
    porsku = {}
    for r in filas:
        sku = r["sku"]
        g = porsku.get(sku)
        if g is None:
            g = {"sku": sku, "descripcion": r.get("descripcion", ""),
                 "stock_ini_cj": r.get("stock_ini_cj", 0),
                 "programado_cj": r.get("programado_cj", 0),
                 "faltante_cj": 0.0, "causas": set(), "n_cli": 0}
            porsku[sku] = g
        g["faltante_cj"] += float(r.get("faltante_cj", 0) or 0)
        g["n_cli"] += 1
        if r.get("causa"):
            g["causas"].add(r["causa"])
    resumen = sorted(porsku.values(), key=lambda x: -x["faltante_cj"])

    total_cj   = sum(g["faltante_cj"] for g in resumen)
    n_prod     = len(resumen)
    n_lineas   = len(filas)
    n_causas   = len({r.get("causa") for r in filas if r.get("causa")})

    wb = openpyxl.Workbook()

    # ══════════════════════ Pestaña "Informe" ══════════════════════
    ws = wb.active
    ws.title = "Informe"
    ws.sheet_view.showGridLines = False
    for col, w in zip("BCDEFGHI", [2, 40, 14, 22, 13, 14, 13, 9]):
        ws.column_dimensions[col].width = w

    # Encabezado
    ws.merge_cells("C3:I3")
    ws["C3"] = "TRAVERSO · Planificación"
    ws["C3"].font = _f(9, True, BLANCO); ws["C3"].fill = _fill(AZUL)
    ws["C3"].alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("C4:I4")
    ws["C4"] = "Informe de Quiebres de Stock Facturado"
    ws["C4"].font = _f(16, True, BLANCO); ws["C4"].fill = _fill(AZUL)
    ws["C4"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[4].height = 26

    ws["C6"] = "Día del informe:"; ws["C6"].font = _f(9, True)
    ws["D6"] = _fecha_txt(fecha_str); ws["D6"].font = _f(9)
    ws["F6"] = "Fecha de emisión:"; ws["F6"].font = _f(9, True)
    ws["G6"] = _fecha_txt(date.today()); ws["G6"].font = _f(9)

    # Resumen del día
    ws["C8"] = "Resumen del día"; ws["C8"].font = _f(12, True)

    def kpi(rango_val, rango_lbl, valor, etiqueta):
        # rango_val/rango_lbl: p.ej. "C9:D9" / "C10:D10" (merge + centrar)
        ws.merge_cells(rango_val); ws.merge_cells(rango_lbl)
        cv = rango_val.split(":")[0]; cl = rango_lbl.split(":")[0]
        ws[cv] = valor
        ws[cv].font = _f(22, True); ws[cv].fill = _fill(CELESTE)
        ws[cv].alignment = Alignment(horizontal="center", vertical="center")
        ws[cl] = etiqueta
        ws[cl].font = _f(8, True, GRIS_TXT); ws[cl].fill = _fill(CELESTE)
        ws[cl].alignment = Alignment(horizontal="center", vertical="center")
        # pintar el resto de las celdas del merge (para que el fill cubra todo el ancho)
        for rng in (rango_val, rango_lbl):
            ini, fin = rng.split(":")
            col_i = openpyxl.utils.column_index_from_string(ini[0])
            col_f = openpyxl.utils.column_index_from_string(fin[0])
            fila = int(ini[1:])
            for cc in range(col_i, col_f + 1):
                ws.cell(fila, cc).fill = _fill(CELESTE)

    # C:D | E:F | G:I (este último 3 celdas, para que "CAJAS CON QUIEBRE" no desborde)
    kpi("C9:D9", "C10:D10", n_prod, "PRODUCTOS CON QUIEBRE")
    kpi("E9:F9", "E10:F10", n_lineas, "LÍNEAS (SKU × CLIENTE)")
    kpi("G9:I9", "G10:I10", int(round(total_cj)), "CAJAS CON QUIEBRE")
    ws.row_dimensions[9].height = 34

    # Tabla resumen por SKU
    hdr_row = 12
    headers = ["Producto", "Cod. SAP", "Causa", "Stock (cj)", "Programado (cj)", "Faltante (cj)", "%"]
    for i, h in enumerate(headers):
        cell = ws.cell(hdr_row, 3 + i, h)
        cell.font = _f(9, True); cell.fill = _fill(CELESTE)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDE

    r = hdr_row + 1
    for g in resumen:
        causas = g["causas"]
        causa_txt = "MIXTA" if len(causas) > 1 else (CAUSA_LABEL.get(next(iter(causas)), "") if causas else "")
        pct = (g["faltante_cj"] / total_cj) if total_cj else 0
        vals = [g["descripcion"], g["sku"], causa_txt,
                round(g["stock_ini_cj"], 0), round(g["programado_cj"], 0),
                round(g["faltante_cj"], 0), pct]
        for i, v in enumerate(vals):
            cell = ws.cell(r, 3 + i, v)
            cell.font = _f(8, False, "1A2332", name="Calibri")
            cell.fill = _fill(GRIS if (r - hdr_row) % 2 else BLANCO)
            cell.border = BORDE
            if i == 0:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            elif i in (3, 4, 5):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
            elif i == 6:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.number_format = "0.0%"
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        r += 1

    # fila total
    ws.cell(r, 3, "TOTAL").font = _f(9, True)
    tc = ws.cell(r, 8, round(total_cj, 0)); tc.font = _f(9, True)
    tc.number_format = "#,##0"; tc.alignment = Alignment(horizontal="right")

    # ══════════════════════ Pestaña "Detalle por cliente" ══════════════════════
    ws2 = wb.create_sheet("Detalle por cliente")
    ws2.sheet_view.showGridLines = False
    for col, w in zip("BCDEFG", [2, 40, 14, 34, 18, 14]):
        ws2.column_dimensions[col].width = w

    ws2.merge_cells("C2:G2")
    ws2["C2"] = f"Detalle por cliente · {_fecha_txt(fecha_str)}"
    ws2["C2"].font = _f(13, True, BLANCO); ws2["C2"].fill = _fill(AZUL)
    ws2["C2"].alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[2].height = 22

    # KPIs de la pestaña detalle (mismos valores del día)
    def kpi2(rango_val, rango_lbl, valor, etiqueta):
        ws2.merge_cells(rango_val); ws2.merge_cells(rango_lbl)
        cv = rango_val.split(":")[0]; cl = rango_lbl.split(":")[0]
        ws2[cv] = valor
        ws2[cv].font = _f(20, True); ws2[cv].alignment = Alignment(horizontal="center", vertical="center")
        ws2[cl] = etiqueta
        ws2[cl].font = _f(8, True, GRIS_TXT); ws2[cl].alignment = Alignment(horizontal="center", vertical="center")
        for rng in (rango_val, rango_lbl):
            ini, fin = rng.split(":")
            ci = openpyxl.utils.column_index_from_string(ini[0]); cf = openpyxl.utils.column_index_from_string(fin[0])
            fila = int(ini[1:])
            for cc in range(ci, cf + 1):
                ws2.cell(fila, cc).fill = _fill(CELESTE)
    kpi2("C4:C4", "C5:C5", n_prod, "PRODUCTOS")
    kpi2("D4:E4", "D5:E5", n_lineas, "LÍNEAS (SKU × CLIENTE)")
    kpi2("F4:G4", "F5:G5", int(round(total_cj)), "CAJAS CON QUIEBRE")
    ws2.row_dimensions[4].height = 30

    h2 = ["Producto", "Cod. SAP", "Cliente", "Causa", "Faltante (cj)"]
    for i, h in enumerate(h2):
        cell = ws2.cell(7, 3 + i, h)
        cell.font = _f(9, True); cell.fill = _fill(CELESTE)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDE

    filas_ord = sorted(filas, key=lambda x: (x["sku"], -float(x.get("faltante_cj", 0) or 0)))
    rr = 8
    for r0 in filas_ord:
        causa_txt = CAUSA_LABEL.get(r0.get("causa"), r0.get("causa", ""))
        vals = [r0.get("descripcion", ""), r0["sku"], r0.get("nom_cliente", ""),
                causa_txt, round(float(r0.get("faltante_cj", 0) or 0), 0)]
        for i, v in enumerate(vals):
            cell = ws2.cell(rr, 3 + i, v)
            cell.font = _f(8, False, "1A2332", name="Calibri")
            cell.fill = _fill(GRIS if (rr % 2) else BLANCO)
            cell.border = BORDE
            if i == 4:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "#,##0"
            elif i in (0, 2, 3):
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        rr += 1

    return wb


def generar_bytes(fecha, filas):
    """Devuelve los bytes del .xlsx (para servir por HTTP)."""
    wb = construir(fecha, filas)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


if __name__ == "__main__":
    # Prueba: genera el informe de un día a un archivo local.
    import sys
    from db_mrp import get_faltantes_por_fecha
    f = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    filas = get_faltantes_por_fecha(f)
    wb = construir(f, filas)
    out = f"/tmp/informe_faltantes_{f}.xlsx"
    wb.save(out)
    print(f"OK: {out} | {len(filas)} filas | {len(set(r['sku'] for r in filas))} SKU")
