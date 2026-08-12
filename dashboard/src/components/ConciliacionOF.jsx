// ConciliacionOF.jsx — Conciliación OF / Terminal Report
// Cumplimiento de OF (producido vs planificado), tendencia mensual del fill-rate,
// y tabla de OF con filtro por estado + drill-down de recepción diaria por OF.
// Solo lectura de mrp_of_sap (materializado por cron_of_sap.py); no recalcula en el cliente.

import React, { useState, useEffect, useMemo } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  LineChart, Line,
} from "recharts";

const API = process.env.REACT_APP_API_BASE || "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
};

const fmtN = (n) => Math.round(n ?? 0).toLocaleString("es-CL");
const fmtPct = (n) => (n == null ? "—" : `${n.toFixed(1)}%`);

// Estado -> etiqueta y color. completa=teal, corta=rojo, sobre=ambar, pendiente=gris.
const EST_LABEL = { completa: "Completa", corta: "Corta", sobre: "Sobre", pendiente: "Pendiente" };
const estColor = (e) =>
  e === "completa" ? C.teal : e === "corta" ? C.red : e === "sobre" ? C.amber : C.gray;
const estBg = (e) =>
  e === "completa" ? C.tealLt : e === "corta" ? C.redLt : e === "sobre" ? C.amberLt : C.grayLt;

function KPI({ label, value, color, sub }) {
  return (
    <div style={{ background: C.grayLt, borderRadius: 8, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || C.text, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

export default function ConciliacionOF() {
  const [soloPt, setSoloPt]     = useState(false);   // excluir granel (9x)
  const [resumen, setResumen]   = useState(null);    // {completa, corta, sobre, pendiente}
  const [filas, setFilas]       = useState([]);      // OF a nivel cumplimiento
  const [tendencia, setTendencia] = useState([]);    // fill-rate mensual
  const [filtroEstado, setFiltroEstado] = useState("todo");
  const [skuFiltro, setSkuFiltro] = useState("");
  const [expandido, setExpandido] = useState({});    // {orden: [serie recepcion]}
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  // 1. Cumplimiento (con o sin granel)
  useEffect(() => {
    setLoading(true); setError(null);
    const qs = new URLSearchParams({ solo_pt: soloPt ? "true" : "false" });
    fetch(`${API}/of/cumplimiento?${qs}`).then((r) => r.json()).then((d) => {
      setResumen(d.resumen || null);
      setFilas(d.filas || []);
      setLoading(false);
    }).catch((e) => { setError(String(e)); setLoading(false); });
  }, [soloPt]);

  // 2. Tendencia mensual del fill-rate
  useEffect(() => {
    const qs = new URLSearchParams({ solo_pt: soloPt ? "true" : "false" });
    fetch(`${API}/of/tendencia?${qs}`).then((r) => r.json()).then((d) => {
      setTendencia(d.serie || []);
    }).catch(() => setTendencia([]));
  }, [soloPt]);

  // Drill-down: recepción diaria de una OF (carga perezosa al expandir)
  const toggleOF = async (orden) => {
    if (expandido[orden]) {
      setExpandido((e) => { const n = { ...e }; delete n[orden]; return n; });
      return;
    }
    try {
      const d = await fetch(`${API}/of/recepcion/${orden}`).then((r) => r.json());
      setExpandido((e) => ({ ...e, [orden]: d.serie || [] }));
    } catch {
      setExpandido((e) => ({ ...e, [orden]: [] }));
    }
  };

  // KPIs derivados del resumen
  const total = useMemo(
    () => (resumen ? Object.values(resumen).reduce((a, b) => a + b, 0) : 0), [resumen]);
  const cerradas = useMemo(
    () => (resumen ? total - (resumen.pendiente || 0) : 0), [resumen, total]);
  const fillRate = useMemo(
    () => (cerradas ? 100 * (resumen.completa || 0) / cerradas : null), [resumen, cerradas]);

  // Tabla filtrada por estado + SKU
  const filasF = useMemo(() => {
    let f = filas;
    if (filtroEstado !== "todo") f = f.filter((r) => r.estado === filtroEstado);
    if (skuFiltro) f = f.filter((r) => String(r.sku).includes(skuFiltro));
    return f;
  }, [filas, filtroEstado, skuFiltro]);

  // Datos del gráfico de tendencia
  const chartTend = useMemo(
    () => tendencia.map((r) => ({ ...r, name: r.mes })), [tendencia]);

  const s = {
    card:  { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: 16, marginBottom: 14 },
    top:   { background: C.teal, color: "#fff", padding: "12px 20px", borderRadius: "10px 10px 0 0" },
    lbl:   { fontSize: 12, fontWeight: 600, color: C.textMuted },
    inp:   { fontSize: 13, padding: "6px 9px", borderRadius: 6, border: `0.5px solid ${C.border}`,
             background: "#fff", color: C.text, outline: "none" },
    th:    { padding: "8px 10px", fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3,
             borderBottom: `0.5px solid ${C.border}`, background: C.grayLt },
    td:    { padding: "7px 10px", fontSize: 13, color: C.text, borderBottom: `0.5px solid ${C.border}` },
  };

  return (
    <div>
      <div style={s.top}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>🏭 Conciliación OF / Terminal Report</div>
        <div style={{ fontSize: 12, opacity: .9, marginTop: 2 }}>
          Producción efectiva en SAP · cumplimiento de OF (producido vs planificado) · ventana ~6 meses
        </div>
      </div>

      <div style={{ ...s.card, borderRadius: "0 0 10px 10px", marginTop: 0 }}>
        {/* Controles */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end", marginBottom: 16 }}>
          <div>
            <div style={s.lbl}>Estado</div>
            <select value={filtroEstado} onChange={(e) => setFiltroEstado(e.target.value)} style={s.inp}>
              <option value="todo">Todos</option>
              <option value="completa">Completa</option>
              <option value="corta">Corta</option>
              <option value="sobre">Sobre</option>
              <option value="pendiente">Pendiente</option>
            </select>
          </div>
          <div>
            <div style={s.lbl}>Filtrar SKU (opcional)</div>
            <input type="text" value={skuFiltro} placeholder="código SKU"
              onChange={(e) => setSkuFiltro(e.target.value.trim())} style={{ ...s.inp, width: 140 }} />
          </div>
          <div>
            <div style={s.lbl}>Alcance</div>
            <label style={{ fontSize: 13, color: C.text, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input type="checkbox" checked={soloPt} onChange={(e) => setSoloPt(e.target.checked)} />
              Solo producto terminado (excluir granel)
            </label>
          </div>
        </div>

        {/* KPIs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginBottom: 16 }}>
          <KPI label="Fill-rate" value={fmtPct(fillRate)} color={C.teal}
               sub="completas / OF cerradas" />
          <KPI label="Completas" value={fmtN(resumen?.completa)} color={C.teal} />
          <KPI label="Cortas" value={fmtN(resumen?.corta)} color={C.red} sub="produjo de menos" />
          <KPI label="Sobre" value={fmtN(resumen?.sobre)} color={C.amber} sub="produjo de más" />
          <KPI label="Pendientes" value={fmtN(resumen?.pendiente)} color={C.gray} sub="aún sin producir" />
          <KPI label="OF totales" value={fmtN(total)} />
        </div>

        {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 10 }}>Error: {error}</div>}
        {loading && <div style={{ color: C.textMuted, fontSize: 13, marginBottom: 10 }}>Cargando…</div>}

        {/* Tendencia mensual del fill-rate */}
        <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 6 }}>
          Fill-rate mensual (% de OF completas sobre las cerradas del mes)
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartTend} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: C.textMuted }}
                   tickFormatter={(v) => `${v}%`} />
            <Tooltip
              formatter={(v, k) => (k === "fill_rate" ? [`${v}%`, "Fill-rate"] : [fmtN(v), k])}
              labelFormatter={(l) => `Mes ${l}`}
              contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${C.border}` }} />
            <Line type="monotone" dataKey="fill_rate" stroke={C.teal} strokeWidth={2}
                  dot={{ r: 3, fill: C.teal }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Tabla de OF */}
      <div style={s.card}>
        <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 12 }}>
          Órdenes de fabricación · {fmtN(filasF.length)} {filtroEstado !== "todo" ? EST_LABEL[filtroEstado].toLowerCase() : ""}
        </div>
        {filasF.length === 0 ? (
          <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>
            Sin OF para el filtro seleccionado.
          </div>
        ) : (
          <div style={{ overflowX: "auto", border: `0.5px solid ${C.border}`, borderRadius: 8 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["", "OF", "SKU", "Descripción", "Estado", "Planificado", "Producido", "Cumpl.", "Inicio planif.", "Recibos"].map((h, i) => (
                    <th key={h || i} style={{ ...s.th, textAlign: (i >= 5 && i <= 7) ? "right" : "left" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filasF.slice(0, 500).map((r, gi) => {
                  const abierto = expandido[r.orden_produccion] !== undefined;
                  const serie = expandido[r.orden_produccion] || [];
                  const puedeExpandir = r.n_recibos > 0;
                  return (
                    <React.Fragment key={r.orden_produccion}>
                      <tr onClick={() => puedeExpandir && toggleOF(r.orden_produccion)}
                          style={{ background: gi % 2 === 0 ? "#fff" : C.grayLt,
                                   cursor: puedeExpandir ? "pointer" : "default" }}>
                        <td style={{ ...s.td, textAlign: "center", color: C.textMuted, width: 26 }}>
                          {puedeExpandir ? (abierto ? "▼" : "▶") : ""}
                        </td>
                        <td style={{ ...s.td, fontWeight: 700, color: C.tealMid }}>{r.orden_produccion}</td>
                        <td style={{ ...s.td, fontWeight: 600, color: C.teal }}>
                          {r.sku}{r.es_granel && <span title="Granel / semielaborado" style={{ color: C.purple }}> ●</span>}
                        </td>
                        <td style={{ ...s.td, color: C.textMuted }}>{r.descripcion}</td>
                        <td style={s.td}>
                          <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 20,
                            color: estColor(r.estado), background: estBg(r.estado) }}>
                            {EST_LABEL[r.estado] || r.estado}
                          </span>
                        </td>
                        <td style={{ ...s.td, textAlign: "right" }}>{fmtN(r.planificada)}</td>
                        <td style={{ ...s.td, textAlign: "right" }}>{fmtN(r.producida)}</td>
                        <td style={{ ...s.td, textAlign: "right", fontWeight: 700, color: estColor(r.estado) }}>
                          {fmtPct(r.ratio * 100)}
                        </td>
                        <td style={{ ...s.td, color: C.textMuted }}>{r.fecha_ini_planif || "—"}</td>
                        <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>{r.n_recibos}</td>
                      </tr>
                      {/* Drill-down: recepción diaria */}
                      {abierto && (
                        <tr style={{ background: C.tealLt }}>
                          <td style={s.td}></td>
                          <td style={s.td} colSpan={9}>
                            {serie.length === 0 ? (
                              <span style={{ fontSize: 12, color: C.textMuted }}>Sin recibos registrados.</span>
                            ) : (
                              <div>
                                <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 4 }}>
                                  Recepción por día ({serie.length} {serie.length === 1 ? "fecha" : "fechas"}):
                                </div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                                  {serie.map((d) => (
                                    <span key={d.fecha} style={{ fontSize: 12, padding: "3px 10px", borderRadius: 6,
                                      background: "#fff", border: `0.5px solid ${C.border}`, color: C.text }}>
                                      {d.fecha}: <strong>{fmtN(d.producido)}</strong>
                                      {d.n_recibos > 1 && <span style={{ color: C.textMuted }}> ({d.n_recibos} recibos)</span>}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {filasF.length > 500 && (
          <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
            Mostrando las primeras 500 de {fmtN(filasF.length)} OF. Usá los filtros para acotar.
          </div>
        )}
        <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
          ● Granel / semielaborado (SKU 9xxxxxxx). Clic en una OF recibida para ver su recepción por día.
        </div>
      </div>
    </div>
  );
}
