// Faltantes.jsx — Informe de Faltantes por Quiebre
// Gráfico evolutivo (barra por día, faltante en cajas) + detalle del día seleccionado.
// Click en una barra → carga el detalle de ese día. Por defecto: último día disponible.
// Solo lectura de mrp_faltantes (materializado por el cron); no recalcula en el cliente.

import React, { useState, useEffect, useMemo } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from "recharts";

const API = "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
};

const fmtN = (n) => Math.round(n ?? 0).toLocaleString("es-CL");
const fmtDs = (s) => {
  // "2026-07-15" -> "15-07"
  const p = String(s).split("-");
  return p.length === 3 ? `${p[2]}-${p[1]}` : s;
};

// resta d días a una fecha YYYY-MM-DD con aritmética local (sin toISOString)
const restarDias = (iso, dias) => {
  if (!iso) return iso;
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() - dias);
  const p = (n) => String(n).padStart(2, "0");
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
};

function KPI({ label, value, color, sub }) {
  return (
    <div style={{ background: C.grayLt, borderRadius: 8, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || C.text, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

export default function Faltantes() {
  const [rango, setRango]       = useState(null);   // {min_fecha, max_fecha, dias}
  const [desde, setDesde]       = useState("");
  const [hasta, setHasta]       = useState("");
  const [serie, setSerie]       = useState([]);      // [{fecha, faltante_cj}]
  const [selFecha, setSelFecha] = useState("");      // día seleccionado
  const [detalle, setDetalle]   = useState([]);      // filas del día
  const [skuFiltro, setSkuFiltro] = useState("");    // filtro opcional por SKU (evolutivo)
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  // 1. Rango disponible al montar; default: últimos 30 días hasta el último día
  useEffect(() => {
    fetch(`${API}/faltantes/rango`).then((r) => r.json()).then((d) => {
      setRango(d);
      if (d.max_fecha) {
        const ini = d.min_fecha && restarDias(d.max_fecha, 29) < d.min_fecha
          ? d.min_fecha : restarDias(d.max_fecha, 29);
        setDesde(ini);
        setHasta(d.max_fecha);
        setSelFecha(d.max_fecha);   // último día por defecto
      }
    }).catch((e) => setError(String(e)));
  }, []);

  // 2. Evolutivo cuando cambia el rango o el filtro de SKU
  useEffect(() => {
    if (!desde || !hasta) return;
    setLoading(true); setError(null);
    const qs = new URLSearchParams({ desde, hasta });
    if (skuFiltro) qs.set("sku", skuFiltro);
    fetch(`${API}/faltantes/evolutivo?${qs}`).then((r) => r.json()).then((d) => {
      setSerie(d.serie || []);
      setLoading(false);
    }).catch((e) => { setError(String(e)); setLoading(false); });
  }, [desde, hasta, skuFiltro]);

  // 3. Detalle del día seleccionado
  useEffect(() => {
    if (!selFecha) return;
    fetch(`${API}/faltantes?fecha=${selFecha}`).then((r) => r.json()).then((d) => {
      setDetalle(d.filas || []);
    }).catch(() => setDetalle([]));
  }, [selFecha]);

  const totalRango = useMemo(() => serie.reduce((s, r) => s + (r.faltante_cj || 0), 0), [serie]);
  const totalDia   = useMemo(() => detalle.reduce((s, r) => s + (r.faltante_cj || 0), 0), [detalle]);
  const skusDia    = useMemo(() => new Set(detalle.map((r) => r.sku)).size, [detalle]);
  const chartData  = useMemo(
    () => serie.map((r) => ({ ...r, name: fmtDs(r.fecha) })), [serie]);

  const s = {
    card:  { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: 16, marginBottom: 14 },
    top:   { background: C.teal, color: "#fff", padding: "12px 20px", borderRadius: "10px 10px 0 0" },
    lbl:   { fontSize: 12, fontWeight: 600, color: C.textMuted },
    inp:   { fontSize: 13, padding: "6px 9px", borderRadius: 6, border: `0.5px solid ${C.border}`,
             background: "#fff", color: C.text, outline: "none" },
    th:    { padding: "8px 10px", fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3,
             borderBottom: `0.5px solid ${C.border}`, background: C.grayLt },
    td:    { padding: "7px 10px", fontSize: 13, color: C.text, borderBottom: `0.5px solid ${C.border}` },
    btn:   { fontSize: 13, fontWeight: 600, padding: "7px 14px", borderRadius: 7, border: "none",
             cursor: "pointer", background: C.tealLt, color: C.tealMid },
  };

  return (
    <div>
      <div style={s.top}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>📉 Faltantes por Quiebre</div>
        <div style={{ fontSize: 12, opacity: .9, marginTop: 2 }}>
          SKU no despachados por falta de stock · desglose por cliente · datos hasta ayer
        </div>
      </div>

      <div style={{ ...s.card, borderRadius: "0 0 10px 10px", marginTop: 0 }}>
        {/* Controles */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end", marginBottom: 16 }}>
          <div>
            <div style={s.lbl}>Desde</div>
            <input type="date" value={desde} min={rango?.min_fecha} max={hasta}
              onChange={(e) => setDesde(e.target.value)} style={s.inp} />
          </div>
          <div>
            <div style={s.lbl}>Hasta</div>
            <input type="date" value={hasta} min={desde} max={rango?.max_fecha}
              onChange={(e) => setHasta(e.target.value)} style={s.inp} />
          </div>
          <div>
            <div style={s.lbl}>Filtrar SKU (opcional)</div>
            <input type="text" value={skuFiltro} placeholder="código SKU"
              onChange={(e) => setSkuFiltro(e.target.value.trim())} style={{ ...s.inp, width: 140 }} />
          </div>
          {rango && (
            <div style={{ fontSize: 12, color: C.textMuted }}>
              Disponible: {rango.min_fecha} → {rango.max_fecha} ({rango.dias} días con datos)
            </div>
          )}
        </div>

        {/* KPIs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 10, marginBottom: 16 }}>
          <KPI label="Faltante del rango" value={`${fmtN(totalRango)} cj`} color={C.red} />
          <KPI label={`Faltante del día (${selFecha ? fmtDs(selFecha) : "—"})`} value={`${fmtN(totalDia)} cj`} color={C.red} />
          <KPI label="SKU con faltante (día)" value={skusDia} />
          <KPI label="Líneas del día" value={detalle.length} sub="SKU × cliente" />
        </div>

        {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 10 }}>Error: {error}</div>}
        {loading && <div style={{ color: C.textMuted, fontSize: 13, marginBottom: 10 }}>Cargando…</div>}

        {/* Gráfico evolutivo — click en barra selecciona el día */}
        <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 6 }}>
          Faltante diario (cajas) · <strong>clic en una barra</strong> para ver el detalle de ese día
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData} margin={{ top: 8, right: 10, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: C.textMuted }} />
            <Tooltip
              formatter={(v) => [`${fmtN(v)} cj`, "Faltante"]}
              labelFormatter={(l) => `Día ${l}`}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${C.border}` }} />
            <Bar dataKey="faltante_cj" radius={[3, 3, 0, 0]} cursor="pointer"
              onClick={(d) => d && d.fecha && setSelFecha(d.fecha)}>
              {chartData.map((entry) => (
                <Cell key={entry.fecha}
                  fill={entry.fecha === selFecha ? C.red : C.amber} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Detalle del día seleccionado */}
      <div style={s.card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>
            Detalle del {selFecha || "—"} · {fmtN(totalDia)} cj en {skusDia} SKU
          </div>
          <button style={s.btn} title="Próximamente"
            onClick={() => alert("Descarga de Excel: disponible en la próxima versión.")}>
            ↓ Excel
          </button>
        </div>
        {detalle.length === 0 ? (
          <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>
            Sin faltantes registrados ese día.
          </div>
        ) : (
          <div style={{ overflowX: "auto", border: `0.5px solid ${C.border}`, borderRadius: 8 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["SKU", "Descripción", "Cliente", "Stock", "Programado", "Faltante"].map((h, i) => (
                    <th key={h} style={{ ...s.th, textAlign: i >= 3 ? "right" : "left" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detalle.map((r, i) => (
                  <tr key={`${r.sku}-${r.cod_cliente}`} style={{ background: i % 2 === 0 ? "#fff" : C.grayLt }}>
                    <td style={{ ...s.td, fontWeight: 700, color: C.teal }}>
                      {r.sku}{r.stock_estimado && <span title="Stock estimado (día sin snapshot)" style={{ color: C.amber }}> *</span>}
                    </td>
                    <td style={{ ...s.td, color: C.textMuted }}>{r.descripcion}</td>
                    <td style={s.td}>{r.nom_cliente}</td>
                    <td style={{ ...s.td, textAlign: "right" }}>{fmtN(r.stock_ini_cj)}</td>
                    <td style={{ ...s.td, textAlign: "right" }}>{fmtN(r.programado_cj)}</td>
                    <td style={{ ...s.td, textAlign: "right", fontWeight: 700, color: C.red }}>{fmtN(r.faltante_cj)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
          * Stock estimado: ese día no tenía snapshot; se usó el snapshot anterior más cercano.
        </div>
      </div>
    </div>
  );
}
