// Faltantes.jsx — Informe de Faltantes por Quiebre
// Gráfico evolutivo (barra por día, faltante en cajas) + detalle del día seleccionado.
// Click en una barra → carga el detalle de ese día. Por defecto: último día disponible.
// Solo lectura de mrp_faltantes (materializado por el cron); no recalcula en el cliente.

import React, { useState, useEffect, useMemo } from "react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
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
const fmtDs = (s) => {
  // "2026-07-15" -> "15-07"
  const p = String(s).split("-");
  return p.length === 3 ? `${p[2]}-${p[1]}` : s;
};

// Causa: etiqueta legible y color. sin_stock = rojo (produccion), vu_insuficiente = ambar (rotacion).
const CAUSA_LABEL = { sin_stock: "Sin stock", vu_insuficiente: "VU insuficiente" };
const causaColor = (causa, C) => (causa === "vu_insuficiente" ? C.amber : C.red);
const causaBg    = (causa, C) => (causa === "vu_insuficiente" ? C.amberLt : C.redLt);

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
  const [expandido, setExpandido] = useState({});   // {sku: true} filas abiertas
  const [explic, setExplic] = useState({});          // {sku: {explicacion, autor, congelada}}
  const [explicSaving, setExplicSaving] = useState({}); // {sku: 'saving'|'ok'|'err'}
  const [filtroCausa, setFiltroCausa] = useState("todo"); // todo | sin_stock | vu_insuficiente

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
    setExpandido({});   // al cambiar de día, todo colapsado
    fetch(`${API}/faltantes?fecha=${selFecha}`).then((r) => r.json()).then((d) => {
      setDetalle(d.filas || []);
    }).catch(() => setDetalle([]));
  }, [selFecha]);

  // 3b. Explicaciones del día seleccionado (feature 2026-07-23)
  useEffect(() => {
    if (!selFecha) { setExplic({}); return; }
    fetch(`${API}/faltantes/explicaciones?fecha=${selFecha}`)
      .then((r) => r.json())
      .then((d) => setExplic(d.explicaciones || {}))
      .catch(() => setExplic({}));
  }, [selFecha]);

  // Guarda la explicación de un SKU (al perder foco). No permite editar si está congelada.
  const guardarExplicacion = async (sku, texto) => {
    const actual = explic[sku] || {};
    if (actual.congelada) return;                       // read-only
    if ((actual.explicacion || "") === (texto || "")) return;  // sin cambios
    setExplicSaving((s) => ({ ...s, [sku]: "saving" }));
    try {
      const resp = await fetch(`${API}/faltantes/explicaciones`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sku, fecha: selFecha, explicacion: texto, autor: "" }),
      });
      if (!resp.ok) throw new Error(resp.status === 409 ? "congelada" : "error");
      setExplic((e) => ({ ...e, [sku]: { ...(e[sku] || {}), explicacion: texto } }));
      setExplicSaving((s) => ({ ...s, [sku]: "ok" }));
      setTimeout(() => setExplicSaving((s) => { const n = { ...s }; delete n[sku]; return n; }), 1500);
    } catch (err) {
      setExplicSaving((s) => ({ ...s, [sku]: "err" }));
    }
  };

  const totalRango = useMemo(() => serie.reduce((s, r) => s + (r.faltante_cj || 0), 0), [serie]);
  // detalle filtrado por causa (para tabla y KPIs del dia)
  const detalleF = useMemo(
    () => (filtroCausa === "todo" ? detalle : detalle.filter((r) => r.causa === filtroCausa)),
    [detalle, filtroCausa]);
  const totalDia   = useMemo(() => detalleF.reduce((s, r) => s + (r.faltante_cj || 0), 0), [detalleF]);
  // faltante del dia partido por causa (para KPIs, siempre sobre el detalle completo)
  const totSinStock = useMemo(() => detalle.filter(r=>r.causa==="sin_stock").reduce((s,r)=>s+(r.faltante_cj||0),0), [detalle]);
  const totVU       = useMemo(() => detalle.filter(r=>r.causa==="vu_insuficiente").reduce((s,r)=>s+(r.faltante_cj||0),0), [detalle]);
  const skusDia    = useMemo(() => new Set(detalleF.map((r) => r.sku)).size, [detalleF]);
  const chartData  = useMemo(
    () => serie.map((r) => ({ ...r, name: fmtDs(r.fecha) })), [serie]);

  // Agrupar el detalle por SKU: fila resumen (faltante total del SKU) + clientes.
  const porSku = useMemo(() => {
    const m = new Map();
    for (const r of detalleF) {
      if (!m.has(r.sku)) {
        m.set(r.sku, { sku: r.sku, descripcion: r.descripcion,
          stock_ini_cj: r.stock_ini_cj, programado_cj: r.programado_cj,
          stock_estimado: r.stock_estimado, faltante_cj: 0, clientes: [], causas: new Set() });
      }
      const g = m.get(r.sku);
      g.faltante_cj += (r.faltante_cj || 0);
      g.clientes.push(r);
      if (r.causa) g.causas.add(r.causa);
    }
    return Array.from(m.values()).sort((a, b) => b.faltante_cj - a.faltante_cj);
  }, [detalleF]);

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
          <div>
            <div style={s.lbl}>Causa</div>
            <select value={filtroCausa} onChange={(e) => setFiltroCausa(e.target.value)} style={s.inp}>
              <option value="todo">Todas</option>
              <option value="sin_stock">Sin stock</option>
              <option value="vu_insuficiente">VU insuficiente</option>
            </select>
          </div>
          {rango && (
            <div style={{ fontSize: 12, color: C.textMuted }}>
              Disponible: {rango.min_fecha} → {rango.max_fecha} ({rango.dias} días con datos)
            </div>
          )}
        </div>

        {/* KPIs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginBottom: 16 }}>
          <KPI label="Faltante del rango" value={`${fmtN(totalRango)} cj`} color={C.red} />
          <KPI label={`Faltante del día (${selFecha ? fmtDs(selFecha) : "—"})`} value={`${fmtN(totalDia)} cj`} color={C.red} />
          <KPI label="Por falta de stock" value={`${fmtN(totSinStock)} cj`} color={C.red} sub="problema de producción" />
          <KPI label="Por VU insuficiente" value={`${fmtN(totVU)} cj`} color={C.amber} sub="problema de rotación" />
          <KPI label="SKU con faltante (día)" value={skusDia} />
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
          <button style={{ ...s.btn, opacity: selFecha ? 1 : 0.5 }}
            title="Descargar informe del día en Excel"
            disabled={!selFecha}
            onClick={async () => {
              if (!selFecha) return;
              try {
                // fetch + blob: pasa por el proxy de CRA (como los otros llamados),
                // a diferencia de window.open que navega y abre la app.
                const resp = await fetch(`${API}/faltantes/excel?fecha=${selFecha}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `Informe_Quiebres_${selFecha}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
              } catch (e) {
                alert("No se pudo descargar el Excel: " + e.message);
              }
            }}>
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
                  {["", "SKU", "Descripción", "Causa", "Clientes", "Stock", "Programado", "Faltante", "Explicación"].map((h, i) => (
                    <th key={h || i} style={{ ...s.th, textAlign: (i >= 5 && i <= 7) ? "right" : "left" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {porSku.map((g, gi) => {
                  const abierto = !!expandido[g.sku];
                  return (
                    <React.Fragment key={g.sku}>
                      {/* Fila resumen del SKU (clickeable) */}
                      <tr onClick={() => setExpandido((e) => ({ ...e, [g.sku]: !e[g.sku] }))}
                          style={{ background: gi % 2 === 0 ? "#fff" : C.grayLt, cursor: "pointer" }}>
                        <td style={{ ...s.td, textAlign: "center", color: C.textMuted, width: 26 }}>
                          {abierto ? "▼" : "▶"}
                        </td>
                        <td style={{ ...s.td, fontWeight: 700, color: C.teal }}>
                          {g.sku}{g.stock_estimado && <span title="Stock estimado (día sin snapshot)" style={{ color: C.amber }}> *</span>}
                        </td>
                        <td style={{ ...s.td, color: C.textMuted }}>{g.descripcion}</td>
                        <td style={s.td}>
                          {(() => {
                            const cs = Array.from(g.causas || []);
                            if (cs.length === 0) return null;
                            if (cs.length > 1) return (
                              <span style={{ fontSize: 11, fontWeight: 600, color: C.gray }}>Mixta</span>);
                            const cz = cs[0];
                            return (
                              <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 20,
                                color: causaColor(cz, C), background: causaBg(cz, C) }}>
                                {CAUSA_LABEL[cz] || cz}
                              </span>);
                          })()}
                        </td>
                        <td style={s.td}>{g.clientes.length}</td>
                        <td style={{ ...s.td, textAlign: "right" }}>{fmtN(g.stock_ini_cj)}</td>
                        <td style={{ ...s.td, textAlign: "right" }}>{fmtN(g.programado_cj)}</td>
                        <td style={{ ...s.td, textAlign: "right", fontWeight: 700, color: C.red }}>{fmtN(g.faltante_cj)}</td>
                        {/* Explicación (por SKU). Editable salvo si congelada. */}
                        <td style={{ ...s.td, minWidth: 220 }} onClick={(ev) => ev.stopPropagation()}>
                          {(() => {
                            const ex = explic[g.sku] || {};
                            const estado = explicSaving[g.sku];
                            if (ex.congelada) {
                              return (
                                <div style={{ fontSize: 12, color: C.textMuted }}>
                                  {ex.explicacion || <span style={{ fontStyle: "italic" }}>—</span>}
                                  <span title="Enviada — no editable" style={{ marginLeft: 6, color: C.gray }}>🔒</span>
                                </div>
                              );
                            }
                            return (
                              <div>
                                <textarea
                                  defaultValue={ex.explicacion || ""}
                                  placeholder="Agregar explicación…"
                                  onClick={(ev) => ev.stopPropagation()}
                                  onBlur={(ev) => guardarExplicacion(g.sku, ev.target.value.trim())}
                                  rows={2}
                                  style={{ width: "100%", fontSize: 12, fontFamily: "inherit",
                                    border: `1px solid ${C.grayLt}`, borderRadius: 6, padding: "4px 6px",
                                    resize: "vertical", boxSizing: "border-box" }}
                                />
                                {estado === "saving" && <span style={{ fontSize: 10, color: C.textMuted }}>guardando…</span>}
                                {estado === "ok" && <span style={{ fontSize: 10, color: C.teal }}>✓ guardado</span>}
                                {estado === "err" && <span style={{ fontSize: 10, color: C.red }}>error al guardar</span>}
                              </div>
                            );
                          })()}
                        </td>
                      </tr>
                      {/* Sub-filas por cliente (al expandir) */}
                      {abierto && g.clientes
                        .slice().sort((a, b) => b.faltante_cj - a.faltante_cj)
                        .map((r) => (
                        <tr key={`${g.sku}-${r.cod_cliente}`} style={{ background: C.tealLt }}>
                          <td style={s.td}></td>
                          <td style={s.td}></td>
                          <td style={{ ...s.td, color: C.textMuted, paddingLeft: 20 }} colSpan={2}>
                            ↳ {r.nom_cliente}
                          </td>
                          <td style={s.td}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: causaColor(r.causa, C) }}>
                              {CAUSA_LABEL[r.causa] || ""}
                            </span>
                          </td>
                          <td style={s.td}></td>
                          <td style={s.td}></td>
                          <td style={{ ...s.td, textAlign: "right", color: causaColor(r.causa, C) }}>{fmtN(r.faltante_cj)}</td>
                          <td style={s.td}></td>
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })}
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
