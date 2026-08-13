// ConciliacionOF.jsx — Conciliación OF / Terminal Report · Tablero
// Dos vistas:
//   ADOPCIÓN   — cobertura semanal de SKU planificados por el sistema sobre los
//                producidos en SAP (la "curva del nacimiento") + desglose por línea.
//   CUMPLIMIENTO — OF de SAP vs Terminal Report (producido/planificado).
// Match de adopción por SKU en la MISMA semana (no por fecha: desalineación ~21d,
// ver DISENO §10.1). Línea inferida por linea_preferida. Solo lectura.

import React, { useState, useEffect, useMemo } from "react";
import {
  ResponsiveContainer, LineChart, Line, Brush,
  XAxis, YAxis, CartesianGrid, Tooltip,
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

const fmtN  = (n) => Math.round(n ?? 0).toLocaleString("es-CL");
const fmtP  = (n) => (n == null ? "—" : `${n.toFixed(1)}%`);
const fmtSem = (s) => { const p = String(s).split("-"); return p.length === 3 ? `${p[2]}-${p[1]}` : s; };

const EST_LABEL = { completa: "Completa", corta: "Corta", sobre: "Sobre", pendiente: "Pendiente" };
const estColor = (e) => e === "completa" ? C.teal : e === "corta" ? C.red : e === "sobre" ? C.amber : C.gray;
const estBg    = (e) => e === "completa" ? C.tealLt : e === "corta" ? C.redLt : e === "sobre" ? C.amberLt : C.grayLt;

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
  const [vista, setVista] = useState("adopcion");

  const [filtros, setFiltros] = useState(null);
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [linea, setLinea] = useState("");
  const [categoria, setCategoria] = useState("");
  const [skuFiltro, setSkuFiltro] = useState("");

  const [adopcion, setAdopcion] = useState(null);
  const [soloPt, setSoloPt] = useState(false);
  const [cumpl, setCumpl] = useState(null);
  const [tendencia, setTendencia] = useState([]);
  const [filtroEstado, setFiltroEstado] = useState("todo");
  const [expandido, setExpandido] = useState({});
  const [lineaAbierta, setLineaAbierta] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API}/of/filtros`).then((r) => r.json()).then((d) => {
      setFiltros(d);
      if (d.min_fecha) setDesde(d.min_fecha);
      if (d.max_fecha) setHasta(d.max_fecha);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (vista !== "adopcion") return;
    setLoading(true); setError(null);
    const qs = new URLSearchParams();
    if (desde) qs.set("desde", desde);
    if (hasta) qs.set("hasta", hasta);
    if (linea) qs.set("linea", linea);
    if (categoria) qs.set("categoria", categoria);
    if (skuFiltro) qs.set("sku", skuFiltro);
    fetch(`${API}/of/adopcion?${qs}`).then((r) => r.json()).then((d) => {
      setAdopcion(d); setLoading(false);
    }).catch((e) => { setError(String(e)); setLoading(false); });
  }, [vista, desde, hasta, linea, categoria, skuFiltro]);

  useEffect(() => {
    if (vista !== "cumplimiento") return;
    setLoading(true); setError(null);
    const qs = new URLSearchParams({ solo_pt: soloPt ? "true" : "false" });
    fetch(`${API}/of/cumplimiento?${qs}`).then((r) => r.json()).then((d) => {
      setCumpl(d); setLoading(false);
    }).catch((e) => { setError(String(e)); setLoading(false); });
    fetch(`${API}/of/tendencia?${qs}`).then((r) => r.json()).then((d) => {
      setTendencia(d.serie || []);
    }).catch(() => setTendencia([]));
  }, [vista, soloPt]);

  const toggleOF = async (orden) => {
    if (expandido[orden]) {
      setExpandido((e) => { const n = { ...e }; delete n[orden]; return n; });
      return;
    }
    try {
      const d = await fetch(`${API}/of/recepcion/${orden}`).then((r) => r.json());
      setExpandido((e) => ({ ...e, [orden]: d.serie || [] }));
    } catch { setExpandido((e) => ({ ...e, [orden]: [] })); }
  };

  const serie = adopcion?.serie || [];
  const ultConsolidada = useMemo(() => {
    if (serie.length < 2) return serie[serie.length - 1] || null;
    return serie[serie.length - 2];
  }, [serie]);
  const ultParcial = serie[serie.length - 1] || null;
  const chartAdop = useMemo(
    () => serie.map((r, i) => ({ ...r, name: fmtSem(r.semana), parcial: i === serie.length - 1 })),
    [serie]);
  // Rango seleccionado en el brush del gráfico (índices sobre chartAdop)
  const [brush, setBrush] = useState({ start: 0, end: 0 });
  useEffect(() => {
    // al cambiar la serie, el brush cubre todo por defecto
    setBrush({ start: 0, end: Math.max(0, serie.length - 1) });
  }, [serie.length]);

  // Resumen del tramo seleccionado (ponderado por plan; semanas plan=0 no pesan)
  const resumenTramo = useMemo(() => {
    const a = Math.min(brush.start, brush.end);
    const b = Math.max(brush.start, brush.end);
    const sel = serie.slice(a, b + 1);
    if (sel.length === 0) return null;
    const plan = sel.reduce((s, r) => s + (r.plan_cj || 0), 0);
    const sap = sel.reduce((s, r) => s + (r.sap_cj || 0), 0);
    const pct = plan > 0 ? Math.round(1000 * Math.min(sap, plan) / plan) / 10 : null;
    return {
      desde: sel[0].semana, hasta: sel[sel.length - 1].semana,
      semanas: sel.length, plan, sap, pct,
      unaSemana: sel.length === 1,
    };
  }, [serie, brush]);

  // Semanas (isoformat) cubiertas por el tramo del brush → para filtrar el detalle
  const semanasTramo = useMemo(() => {
    const a = Math.min(brush.start, brush.end);
    const b = Math.max(brush.start, brush.end);
    return new Set(serie.slice(a, b + 1).map((r) => r.semana));
  }, [serie, brush]);

  // Detalle por SKU reagregado al tramo seleccionado (desde por_sku_semana)
  const skuTramo = useMemo(() => {
    const det = adopcion?.por_sku_semana || [];
    const acc = {};
    det.forEach((r) => {
      if (!semanasTramo.has(r.semana)) return;
      const a = acc[r.sku] || (acc[r.sku] = {
        sku: r.sku, descripcion: r.descripcion, linea: r.linea, plan_cj: 0, sap_cj: 0 });
      a.plan_cj += r.plan_cj || 0;
      a.sap_cj += r.sap_cj || 0;
    });
    return Object.values(acc).map((x) => ({
      ...x,
      pct: x.plan_cj > 0 ? Math.round(1000 * Math.min(x.sap_cj, x.plan_cj) / x.plan_cj) / 10 : null,
    })).sort((p, q) => q.plan_cj - p.plan_cj);
  }, [adopcion, semanasTramo]);

  // Por línea reagregado al tramo (para los encabezados colapsables)
  const lineaTramo = useMemo(() => {
    const acc = {};
    skuTramo.forEach((x) => {
      const a = acc[x.linea] || (acc[x.linea] = { linea: x.linea, plan_cj: 0, sap_cj: 0 });
      a.plan_cj += x.plan_cj; a.sap_cj += x.sap_cj;
    });
    return Object.values(acc).map((l) => ({
      ...l,
      pct: l.plan_cj > 0 ? Math.round(1000 * Math.min(l.sap_cj, l.plan_cj) / l.plan_cj) / 10 : null,
    })).sort((p, q) => q.plan_cj - p.plan_cj);
  }, [skuTramo]);

  // SKU agrupados por línea, ya filtrados al tramo, para el detalle dentro de cada línea
  const skusPorLineaTramo = useMemo(() => {
    const m = {};
    skuTramo.forEach((x) => { (m[x.linea] = m[x.linea] || []).push(x); });
    return m;
  }, [skuTramo]);

  const resumen = cumpl?.resumen || null;
  const filasC = cumpl?.filas || [];
  const totalC = resumen ? Object.values(resumen).reduce((a, b) => a + b, 0) : 0;
  const cerradas = resumen ? totalC - (resumen.pendiente || 0) : 0;
  const fillRate = cerradas ? 100 * (resumen.completa || 0) / cerradas : null;
  const filasCF = useMemo(() => {
    let f = filasC;
    if (filtroEstado !== "todo") f = f.filter((r) => r.estado === filtroEstado);
    if (skuFiltro) f = f.filter((r) => String(r.sku).includes(skuFiltro));
    return f;
  }, [filasC, filtroEstado, skuFiltro]);
  const chartTend = useMemo(() => (tendencia || []).map((r) => ({ ...r, name: r.mes })), [tendencia]);

  const s = {
    card:  { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: 16, marginBottom: 14 },
    top:   { background: C.teal, color: "#fff", padding: "12px 20px", borderRadius: "10px 10px 0 0" },
    lbl:   { fontSize: 12, fontWeight: 600, color: C.textMuted },
    inp:   { fontSize: 13, padding: "6px 9px", borderRadius: 6, border: `0.5px solid ${C.border}`,
             background: "#fff", color: C.text, outline: "none" },
    th:    { padding: "8px 10px", fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3,
             borderBottom: `0.5px solid ${C.border}`, background: C.grayLt },
    td:    { padding: "7px 10px", fontSize: 13, color: C.text, borderBottom: `0.5px solid ${C.border}` },
    tab:   (activo) => ({ padding: "8px 18px", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600,
             background: activo ? C.teal : C.grayLt, color: activo ? "#fff" : C.textMuted,
             borderRadius: 7, transition: "all .15s" }),
  };

  return (
    <div>
      <div style={s.top}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>🏭 Conciliación OF / Terminal Report</div>
        <div style={{ fontSize: 12, opacity: .9, marginTop: 2 }}>
          Plan del sistema vs producción efectiva en SAP · adopción y cumplimiento
        </div>
      </div>

      <div style={{ ...s.card, borderRadius: "0 0 10px 10px", marginTop: 0 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <button style={s.tab(vista === "adopcion")} onClick={() => setVista("adopcion")}>
            📈 Adopción del sistema
          </button>
          <button style={s.tab(vista === "cumplimiento")} onClick={() => setVista("cumplimiento")}>
            ✅ Cumplimiento de OF
          </button>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end", marginBottom: 16 }}>
          {vista === "adopcion" && (
            <>
              <div>
                <div style={s.lbl}>Desde</div>
                <input type="date" value={desde} min={filtros?.min_fecha} max={hasta}
                  onChange={(e) => setDesde(e.target.value)} style={s.inp} />
              </div>
              <div>
                <div style={s.lbl}>Hasta</div>
                <input type="date" value={hasta} min={desde} max={filtros?.max_fecha}
                  onChange={(e) => setHasta(e.target.value)} style={s.inp} />
              </div>
              <div>
                <div style={s.lbl}>Línea</div>
                <select value={linea} onChange={(e) => setLinea(e.target.value)} style={s.inp}>
                  <option value="">Todas</option>
                  {(filtros?.lineas || []).map((l) => <option key={l} value={l}>{l}</option>)}
                </select>
              </div>
              <div>
                <div style={s.lbl}>Categoría</div>
                <select value={categoria} onChange={(e) => setCategoria(e.target.value)} style={s.inp}>
                  <option value="">Todas</option>
                  {(filtros?.categorias || []).map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </>
          )}
          {vista === "cumplimiento" && (
            <>
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
                <div style={s.lbl}>Alcance</div>
                <label style={{ fontSize: 13, color: C.text, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                  <input type="checkbox" checked={soloPt} onChange={(e) => setSoloPt(e.target.checked)} />
                  Excluir granel
                </label>
              </div>
            </>
          )}
          <div>
            <div style={s.lbl}>Buscar SKU</div>
            <input type="text" value={skuFiltro} placeholder="código SKU"
              onChange={(e) => setSkuFiltro(e.target.value.trim())} style={{ ...s.inp, width: 130 }} />
          </div>
        </div>

        {error && <div style={{ color: C.red, fontSize: 13, marginBottom: 10 }}>Error: {error}</div>}
        {loading && <div style={{ color: C.textMuted, fontSize: 13, marginBottom: 10 }}>Cargando…</div>}

        {vista === "adopcion" && adopcion && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 10, marginBottom: 16 }}>
              <KPI label="Adopción (últ. sem. consolidada)"
                   value={fmtP(ultConsolidada?.pct)} color={C.teal}
                   sub={ultConsolidada ? `sem ${fmtSem(ultConsolidada.semana)} · ${fmtN(ultConsolidada.sap_cj)}/${fmtN(ultConsolidada.plan_cj)} cj` : ""} />
              <KPI label="Semana en curso (parcial)"
                   value={fmtP(ultParcial?.pct)} color={C.gray}
                   sub={ultParcial ? `sem ${fmtSem(ultParcial.semana)} · aún abierta` : ""} />
              <KPI label="Adopción período seleccionado"
                   value={fmtP(resumenTramo?.pct)} color={C.purple}
                   sub={resumenTramo ? (resumenTramo.unaSemana
                        ? `sem ${fmtSem(resumenTramo.desde)}`
                        : `${fmtSem(resumenTramo.desde)}→${fmtSem(resumenTramo.hasta)} · ${resumenTramo.semanas} sem`) : "arrastrá el gráfico"} />
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 6 }}>
              <div style={{ fontSize: 12, color: C.textMuted, maxWidth: "60%" }}>
                Adopción semanal: % de cajas planificadas por el sistema que se materializaron como OF en SAP
                (topeado por SKU, ponderado por volumen). Arrastrá la barra inferior para seleccionar un tramo.
              </div>
              {resumenTramo && (
                <div style={{ background: C.tealLt, border: `0.5px solid ${C.teal}`, borderRadius: 8,
                              padding: "6px 12px", fontSize: 12, color: C.tealMid, textAlign: "right" }}>
                  <div style={{ fontWeight: 700 }}>
                    {resumenTramo.unaSemana
                      ? `Semana ${fmtSem(resumenTramo.desde)}`
                      : `Tramo ${fmtSem(resumenTramo.desde)} → ${fmtSem(resumenTramo.hasta)} (${resumenTramo.semanas} sem)`}
                  </div>
                  <div>
                    adopción <strong>{fmtP(resumenTramo.pct)}</strong> · plan {fmtN(resumenTramo.plan)} cj · SAP {fmtN(resumenTramo.sap)} cj
                  </div>
                </div>
              )}
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartAdop} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: C.textMuted }} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  formatter={(v, k, item) => {
                    if (k !== "pct") return null;
                    const p = item?.payload || {};
                    return [`${v}% · plan ${fmtN(p.plan_cj)} cj · SAP ${fmtN(p.sap_cj)} cj`, "Adopción"];
                  }}
                  labelFormatter={(l) => `Semana ${l}`}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${C.border}` }} />
                <Line type="monotone" dataKey="pct" stroke={C.teal} strokeWidth={2}
                      dot={{ r: 3, fill: C.teal }} connectNulls />
                <Brush dataKey="name" height={22} stroke={C.teal} travellerWidth={8}
                       tickFormatter={fmtSem}
                       onChange={(r) => { if (r && r.startIndex != null)
                         setBrush({ start: r.startIndex, end: r.endIndex }); }} />
              </LineChart>
            </ResponsiveContainer>

            <div style={{ fontSize: 15, fontWeight: 700, color: C.text, margin: "18px 0 10px" }}>
              Por línea {resumenTramo && !(brush.start === 0 && brush.end === serie.length - 1)
                ? `· tramo ${fmtSem(resumenTramo.desde)}→${fmtSem(resumenTramo.hasta)}` : "· período completo"} — clic para el detalle por SKU
            </div>
            <div style={{ border: `0.5px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
              {lineaTramo.map((L, i) => {
                const abierto = !!lineaAbierta[L.linea];
                const total = lineaTramo.length;
                const skus = skusPorLineaTramo[L.linea] || [];
                return (
                  <div key={L.linea} style={{ borderBottom: i < total - 1 ? `0.5px solid ${C.border}` : "none" }}>
                    <div onClick={() => setLineaAbierta((e) => ({ ...e, [L.linea]: !e[L.linea] }))}
                         style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                                  padding: "10px 14px", cursor: "pointer", background: i % 2 ? C.grayLt : "#fff" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
                        <span style={{ color: C.textMuted, marginRight: 8 }}>{abierto ? "▼" : "▶"}</span>
                        {L.linea}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                        <span style={{ fontSize: 12, color: C.textMuted }}>
                          {fmtN(L.sap_cj)}/{fmtN(L.plan_cj)} cj
                        </span>
                        <span style={{ fontSize: 14, fontWeight: 700, color: C.teal, minWidth: 54, textAlign: "right" }}>
                          {fmtP(L.pct)}
                        </span>
                        <div style={{ width: 120, height: 8, background: C.grayLt, borderRadius: 4, overflow: "hidden" }}>
                          <div style={{ width: `${L.pct || 0}%`, height: "100%", background: C.teal }} />
                        </div>
                      </div>
                    </div>
                    {abierto && (
                      <div style={{ padding: "4px 14px 12px 34px", background: C.tealLt }}>
                        <table style={{ width: "100%", borderCollapse: "collapse" }}>
                          <thead>
                            <tr>
                              {["SKU", "Descripción", "Plan (cj)", "SAP (cj)", "Adopción"].map((h, hi) => (
                                <th key={h} style={{ ...s.th, background: "transparent",
                                  textAlign: hi >= 2 ? "right" : "left" }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {skus.map((x) => (
                              <tr key={x.sku}>
                                <td style={{ ...s.td, fontWeight: 600, color: C.teal, borderBottom: "none" }}>{x.sku}</td>
                                <td style={{ ...s.td, color: C.textMuted, borderBottom: "none" }}>{x.descripcion}</td>
                                <td style={{ ...s.td, textAlign: "right", borderBottom: "none" }}>{fmtN(x.plan_cj)}</td>
                                <td style={{ ...s.td, textAlign: "right", borderBottom: "none" }}>{fmtN(x.sap_cj)}</td>
                                <td style={{ ...s.td, textAlign: "right", fontWeight: 700, borderBottom: "none",
                                  color: (x.pct ?? 0) >= 99.9 ? C.teal : (x.pct ?? 0) >= 70 ? C.amber : C.red }}>
                                  {fmtP(x.pct)}
                                </td>
                              </tr>
                            ))}
                            {skus.length === 0 && (
                              <tr><td colSpan={5} style={{ ...s.td, color: C.textMuted, borderBottom: "none" }}>
                                Sin SKU planificados por el sistema en esta línea.
                              </td></tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
              Cajas: plan del sistema (cantidad_real_cj) vs OF en SAP (cant_planificada), match cuando el
              lanzamiento del sistema cae dentro del tramo [ini, fin] de la OF. Adopción topeada al 100% por SKU.
              La línea se infiere del SKU (SAP no la registra). La última semana está en curso.
            </div>
          </>
        )}

        {vista === "cumplimiento" && cumpl && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginBottom: 16 }}>
              <KPI label="Fill-rate" value={fmtP(fillRate)} color={C.teal} sub="completas / OF cerradas" />
              <KPI label="Completas" value={fmtN(resumen?.completa)} color={C.teal} />
              <KPI label="Cortas" value={fmtN(resumen?.corta)} color={C.red} sub="produjo de menos" />
              <KPI label="Sobre" value={fmtN(resumen?.sobre)} color={C.amber} sub="produjo de más" />
              <KPI label="Pendientes" value={fmtN(resumen?.pendiente)} color={C.gray} sub="sin producir" />
            </div>

            <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 6 }}>
              Fill-rate mensual (% de OF completas sobre las cerradas del mes)
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chartTend} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: C.textMuted }} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v, k) => k === "fill_rate" ? [`${v}%`, "Fill-rate"] : [fmtN(v), k]}
                  labelFormatter={(l) => `Mes ${l}`}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${C.border}` }} />
                <Line type="monotone" dataKey="fill_rate" stroke={C.teal} strokeWidth={2}
                      dot={{ r: 3, fill: C.teal }} connectNulls />
              </LineChart>
            </ResponsiveContainer>

            <div style={{ fontSize: 15, fontWeight: 700, color: C.text, margin: "18px 0 10px" }}>
              Órdenes · {fmtN(filasCF.length)} {filtroEstado !== "todo" ? EST_LABEL[filtroEstado].toLowerCase() : ""}
            </div>
            <div style={{ overflowX: "auto", border: `0.5px solid ${C.border}`, borderRadius: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["", "OF", "SKU", "Descripción", "Estado", "Planif.", "Produc.", "Cumpl.", "Inicio", "Recibos"].map((h, i) => (
                      <th key={h || i} style={{ ...s.th, textAlign: (i >= 5 && i <= 7) ? "right" : "left" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filasCF.slice(0, 500).map((r, gi) => {
                    const abierto = expandido[r.orden_produccion] !== undefined;
                    const ser = expandido[r.orden_produccion] || [];
                    const puede = r.n_recibos > 0;
                    return (
                      <React.Fragment key={r.orden_produccion}>
                        <tr onClick={() => puede && toggleOF(r.orden_produccion)}
                            style={{ background: gi % 2 === 0 ? "#fff" : C.grayLt, cursor: puede ? "pointer" : "default" }}>
                          <td style={{ ...s.td, textAlign: "center", color: C.textMuted, width: 26 }}>
                            {puede ? (abierto ? "▼" : "▶") : ""}
                          </td>
                          <td style={{ ...s.td, fontWeight: 700, color: C.tealMid }}>{r.orden_produccion}</td>
                          <td style={{ ...s.td, fontWeight: 600, color: C.teal }}>
                            {r.sku}{r.es_granel && <span title="Granel/semi" style={{ color: C.purple }}> ●</span>}
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
                            {fmtP(r.ratio * 100)}
                          </td>
                          <td style={{ ...s.td, color: C.textMuted }}>{r.fecha_ini_planif || "—"}</td>
                          <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>{r.n_recibos}</td>
                        </tr>
                        {abierto && (
                          <tr style={{ background: C.tealLt }}>
                            <td style={s.td}></td>
                            <td style={s.td} colSpan={9}>
                              {ser.length === 0 ? (
                                <span style={{ fontSize: 12, color: C.textMuted }}>Sin recibos.</span>
                              ) : (
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                                  {ser.map((d) => (
                                    <span key={d.fecha} style={{ fontSize: 12, padding: "3px 10px", borderRadius: 6,
                                      background: "#fff", border: `0.5px solid ${C.border}`, color: C.text }}>
                                      {d.fecha}: <strong>{fmtN(d.producido)}</strong>
                                      {d.n_recibos > 1 && <span style={{ color: C.textMuted }}> ({d.n_recibos})</span>}
                                    </span>
                                  ))}
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
            {filasCF.length > 500 && (
              <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
                Mostrando 500 de {fmtN(filasCF.length)}. Usá los filtros para acotar.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
