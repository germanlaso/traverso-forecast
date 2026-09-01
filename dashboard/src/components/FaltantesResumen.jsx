// FaltantesResumen.jsx — Resumen (heatmap) de faltantes de los últimos 30 días.
// Tab "Resumen 30d" dentro del menú Control. Consume /faltantes/resumen30.
// Filas = SKU con faltante en la ventana, agrupadas por grupo -> categoría.
// Columnas fijas: Cod · Nombre · Ventas 30d · Faltante 30d · % · Días c/falta.
// Luego 30 celdas heatmap (una por día, -30..-1): color por cajas faltantes/día,
// número en tooltip. Sin faltante ese día = celda vacía.
import React, { useState, useEffect, useMemo } from "react";

const API = process.env.REACT_APP_API_BASE || "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
  navy:    "#1A2D4D",
};

const fmtN = (n) => (n == null ? "" : Math.round(n).toLocaleString("es-CL"));
// 'YYYY-MM-DD' -> 'dd-mm'
const fmtDM = (iso) => {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  return `${d}-${m}`;
};
const DOW = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
// 'YYYY-MM-DD' -> 'mié 27-08' (día de la semana + fecha)
const fmtDiaFecha = (iso) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dow = DOW[new Date(y, m - 1, d).getDay()];
  return `${dow} ${String(d).padStart(2, "0")}-${String(m).padStart(2, "0")}`;
};

// Escala de color por cajas faltantes del día (cortes acordados)
//   0 -> vacío · 1-20 amarillo · 21-60 naranja · >60 rojo
const colorCelda = (cj) => {
  if (!cj || cj <= 0) return "transparent";
  if (cj <= 20) return "#F7D65A";   // amarillo
  if (cj <= 60) return "#EF9F27";   // naranja
  return "#E24B4A";                 // rojo
};
const colorTexto = (cj) => (cj > 60 ? "#fff" : "#2C2C2A");

const GRUPO_ORDEN = { "Producción": 0, "Importación": 1 };

export default function FaltantesResumen() {
  const [data, setData]       = useState(null);   // {desde, hasta, fechas[], filas[]}
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  useEffect(() => {
    setLoading(true); setError(null);
    fetch(`${API}/faltantes/resumen30`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => setData(d))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const fechas = data?.fechas || [];
  const filas  = data?.filas || [];
  const noHabil = data?.no_habil || [];

  // subtotales por grupo (para las bandas)
  const subtotGrupo = useMemo(() => {
    const t = {};
    for (const f of filas) {
      const g = t[f.grupo] || (t[f.grupo] = { ventas: 0, falta: 0 });
      g.ventas += (f.ventas_30 || 0);
      g.falta  += (f.faltante_30 || 0);
    }
    return t;
  }, [filas]);

  // subtotales por categoría (clave: grupo|cat)
  const subtotCat = useMemo(() => {
    const t = {};
    for (const f of filas) {
      const k = `${f.grupo}|${f.cat_comercial}`;
      const g = t[k] || (t[k] = { ventas: 0, falta: 0 });
      g.ventas += (f.ventas_30 || 0);
      g.falta  += (f.faltante_30 || 0);
    }
    return t;
  }, [filas]);

  // total general
  const totalGen = useMemo(() => {
    let ventas = 0, falta = 0;
    for (const f of filas) { ventas += (f.ventas_30 || 0); falta += (f.faltante_30 || 0); }
    return { ventas, falta, pct: ventas > 0 ? (falta / ventas * 100) : null };
  }, [filas]);

  const pctDe = (falta, ventas) => (ventas > 0 ? `${(falta / ventas * 100).toFixed(1)}%` : "—");

  const s = {
    wrap:  { padding: "16px 8px", fontFamily: "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif", color: C.text },
    th:    { padding: "4px 6px", fontSize: 10.5, fontWeight: 700, color: C.gray, borderBottom: `2px solid ${C.border}`, background: "#fff", position: "sticky", top: 0, whiteSpace: "nowrap" },
    td:    { padding: "3px 6px", fontSize: 11, borderBottom: `1px solid ${C.grayLt}`, whiteSpace: "nowrap" },
    cell:  { width: 20, minWidth: 20, height: 19, textAlign: "center", fontSize: 9, borderRight: `1px solid #fff`, borderBottom: `1px solid #fff` },
    hcell: { width: 20, minWidth: 20, fontSize: 9, color: C.textMuted, textAlign: "center", padding: "5px 0", borderBottom: `2px solid ${C.border}`, position: "sticky", top: 0 },
  };
  const HDR_NOHABIL = "#EAE6DA";   // fondo de encabezado para sábados, domingos y feriados

  if (loading) return <div style={s.wrap}>Cargando resumen de faltantes…</div>;
  if (error)   return <div style={{ ...s.wrap, color: C.red }}>Error al cargar: {error}</div>;
  if (!data || filas.length === 0)
    return <div style={s.wrap}>Sin faltantes en los últimos 30 días.</div>;

  const nCols = 6 + fechas.length; // columnas fijas + días

  // recorrido con bandas de grupo/categoría
  let grupoActual = null, catActual = null, zebra = 0;
  const rows = [];

  const bandaCols = (st, label, ventas, falta) => ([
    <td key="l" colSpan={2} style={{ ...st, padding: "5px 8px" }}>{label}</td>,
    <td key="v" style={{ ...st, padding: "5px 6px", textAlign: "right" }}>{fmtN(ventas)}</td>,
    <td key="f" style={{ ...st, padding: "5px 6px", textAlign: "right" }}>{fmtN(falta)}</td>,
    <td key="p" style={{ ...st, padding: "5px 6px", textAlign: "right" }}>{pctDe(falta, ventas)}</td>,
    <td key="d" style={{ ...st, padding: "5px 6px" }} />,
    <td key="h" colSpan={fechas.length} style={st} />,
  ]);

  filas.forEach((f) => {
    if (f.grupo !== grupoActual) {
      grupoActual = f.grupo; catActual = null; zebra = 0;
      const g = subtotGrupo[f.grupo] || { ventas: 0, falta: 0 };
      rows.push(
        <tr key={`g-${f.grupo}`}>
          {bandaCols({ background: C.navy, color: "#fff", fontWeight: 700, fontSize: 12, letterSpacing: 0.3 },
                     f.grupo.toUpperCase(), g.ventas, g.falta)}
        </tr>
      );
    }
    if (f.cat_comercial !== catActual) {
      catActual = f.cat_comercial; zebra = 0;
      const c = subtotCat[`${f.grupo}|${f.cat_comercial}`] || { ventas: 0, falta: 0 };
      rows.push(
        <tr key={`c-${f.grupo}-${f.cat_comercial}`}>
          {bandaCols({ background: C.grayLt, color: C.gray, fontWeight: 700, fontSize: 11 },
                     f.cat_comercial || "(sin categoría)", c.ventas, c.falta)}
        </tr>
      );
    }
    const bg = zebra % 2 ? C.grayLt : "#fff"; zebra += 1;
    rows.push(
      <tr key={f.sku} style={{ background: bg }}>
        <td style={{ ...s.td, fontWeight: 700, color: C.teal }}>{f.sku}</td>
        <td style={{ ...s.td, color: C.text, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }} title={f.descripcion}>{f.descripcion}</td>
        <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>{f.ventas_30 == null ? "—" : fmtN(f.ventas_30)}</td>
        <td style={{ ...s.td, textAlign: "right", fontWeight: 700, color: C.red }}>{fmtN(f.faltante_30)}</td>
        <td style={{ ...s.td, textAlign: "right", fontWeight: 600 }}>{f.pct == null ? "—" : `${f.pct}%`}</td>
        <td style={{ ...s.td, textAlign: "center" }}>{f.dias_con_falta}</td>
        {f.serie.map((cj, i) => (
          <td key={i}
              style={{ ...s.cell, background: colorCelda(cj), color: colorTexto(cj) }}
              title={cj > 0 ? `${fmtDiaFecha(fechas[i])} · ${fmtN(cj)} cj` : fmtDiaFecha(fechas[i])}>
            {cj > 0 ? fmtN(cj) : ""}
          </td>
        ))}
      </tr>
    );
  });

  return (
    <div style={s.wrap}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Resumen de faltantes — últimos 30 días</h2>
        <span style={{ color: C.textMuted, fontSize: 12 }}>
          {fmtDM(data.desde)} al {fmtDM(data.hasta)} · {filas.length} SKU con faltante
        </span>
      </div>

      {/* KPIs de total general */}
      <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { lbl: "Total Ventas 30d", val: `${fmtN(totalGen.ventas)} cj`, col: C.gray },
          { lbl: "Total Faltante 30d", val: `${fmtN(totalGen.falta)} cj`, col: C.red },
          { lbl: "% Faltante global", val: totalGen.pct == null ? "—" : `${totalGen.pct.toFixed(1)}%`, col: C.tealMid },
        ].map((k) => (
          <div key={k.lbl} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 16px", minWidth: 140, background: "#fff" }}>
            <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 2 }}>{k.lbl}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: k.col }}>{k.val}</div>
          </div>
        ))}
      </div>

      {/* leyenda de colores */}
      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 10, fontSize: 11, color: C.textMuted }}>
        <span>Profundidad del faltante (cj/día):</span>
        {[["1–20", "#F7D65A"], ["21–60", "#EF9F27"], [">60", "#E24B4A"]].map(([lbl, col]) => (
          <span key={lbl} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 12, height: 12, background: col, borderRadius: 2, display: "inline-block" }} />{lbl}
          </span>
        ))}
      </div>

      <div style={{ overflowX: "auto", border: `1px solid ${C.border}`, borderRadius: 8 }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={{ ...s.th, textAlign: "left" }}>Cod</th>
              <th style={{ ...s.th, textAlign: "left" }}>Producto</th>
              <th style={{ ...s.th, textAlign: "right" }}>Ventas 30d</th>
              <th style={{ ...s.th, textAlign: "right" }}>Faltante 30d</th>
              <th style={{ ...s.th, textAlign: "right" }}>% falt/venta</th>
              <th style={{ ...s.th, textAlign: "center" }}>Días</th>
              {fechas.map((iso, i) => (
                <th key={iso}
                    style={{ ...s.hcell, background: noHabil[i] ? HDR_NOHABIL : "#fff",
                             fontWeight: noHabil[i] ? 700 : 400,
                             color: noHabil[i] ? C.gray : C.textMuted }}
                    title={fmtDiaFecha(iso)}>
                  {i - fechas.length}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
  );
}
