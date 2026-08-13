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
  BarChart, Bar, Cell,
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

// Color por umbral de cumplimiento (rojo <90, ámbar 90-99, verde >=100)
const cumplColor = (p) => p == null ? C.textMuted : p < 90 ? C.red : p < 100 ? C.amber : C.teal;
const cumplBg    = (p) => p == null ? C.grayLt : p < 90 ? C.redLt : p < 100 ? C.amberLt : C.tealLt;

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
  const [cumplSku, setCumplSku] = useState(null);   // {periodo, buckets:[...]}
  const [cumplEvol, setCumplEvol] = useState([]);   // barras: cumplimiento % por semana
  const [semanaSel, setSemanaSel] = useState(null); // bucket (semana) seleccionado
  const [lineaAbiertaC, setLineaAbiertaC] = useState({}); // colapsables en cumplimiento
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
    const qs = new URLSearchParams();
    if (desde) qs.set("desde", desde);
    if (hasta) qs.set("hasta", hasta);
    if (linea) qs.set("linea", linea);
    if (categoria) qs.set("categoria", categoria);
    if (skuFiltro) qs.set("sku", skuFiltro);
    fetch(`${API}/of/cumplimiento_sku?periodo=semana&${qs}`).then((r) => r.json()).then((d) => {
      setCumplSku(d);
      // seleccionar la última semana por defecto
      const bs = d.buckets || [];
      setSemanaSel(bs.length ? bs[bs.length - 1].bucket : null);
      setLoading(false);
    }).catch((e) => { setError(String(e)); setLoading(false); });
    fetch(`${API}/of/cumplimiento_evolutivo?${qs}`).then((r) => r.json()).then((d) => {
      setCumplEvol(d.serie || []);
    }).catch(() => setCumplEvol([]));
  }, [vista, desde, hasta, linea, categoria, skuFiltro]);


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

  // Resumen del tramo seleccionado. OJO: el % se calcula topeando POR SKU y después
  // sumando (Σ min(sap,plan)_sku / Σ plan_sku), NO min de las sumas — si no, el
  // exceso de un SKU tapa el déficit de otro y da 100% falso. Sale de skuTramo, que
  // ya trae min(sap,plan) por SKU. Las cajas del recuadro sí son las brutas del tramo.
  const resumenTramo = useMemo(() => {
    const a = Math.min(brush.start, brush.end);
    const b = Math.max(brush.start, brush.end);
    const sel = serie.slice(a, b + 1);
    if (sel.length === 0) return null;
    const planBruto = sel.reduce((s, r) => s + (r.plan_cj || 0), 0);
    const sapBruto = sel.reduce((s, r) => s + (r.sap_cj || 0), 0);
    return {
      desde: sel[0].semana, hasta: sel[sel.length - 1].semana,
      semanas: sel.length, plan: planBruto, sap: sapBruto,
      unaSemana: sel.length === 1,
    };
  }, [serie, brush]);

  // Adopción del tramo: topeada por SKU (desde skuTramo) y ponderada por plan.
  // Se define más abajo porque depende de skuTramo; se calcula en adopcionTramoPct.

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

  // Adopción del tramo, topeada por SKU y ponderada por plan (Σ sap_topeado / Σ plan).
  // skuTramo.sap_cj ya es min(sap,plan) por SKU, así que sumarlo da el numerador correcto.
  const adopcionTramoPct = useMemo(() => {
    const plan = skuTramo.reduce((s, x) => s + (x.plan_cj || 0), 0);
    const sap = skuTramo.reduce((s, x) => s + (x.sap_cj || 0), 0);
    return plan > 0 ? Math.round(1000 * sap / plan) / 10 : null;
  }, [skuTramo]);

  // Datos del gráfico de barras (cumplimiento % por semana)
  const chartBarras = useMemo(
    () => (cumplEvol || []).map((r) => ({ ...r, name: fmtSem(r.semana) })), [cumplEvol]);

  // Bucket (semana) seleccionado en las barras
  const bucketSel = useMemo(
    () => (cumplSku?.buckets || []).find((b) => b.bucket === semanaSel) || null,
    [cumplSku, semanaSel]);

  // Filas de la semana seleccionada, agrupadas por línea (colapsable)
  const cumplPorLinea = useMemo(() => {
    if (!bucketSel) return [];
    const grupos = {};
    bucketSel.filas.forEach((f) => {
      const ln = f.linea || "(sin línea)";
      const g = grupos[ln] || (grupos[ln] = { linea: ln, filas: [], solicitado: 0, producido: 0 });
      g.filas.push(f);
      g.solicitado += f.solicitado || 0;
      g.producido += f.producido || 0;
    });
    return Object.values(grupos).map((g) => ({
      ...g,
      pct: g.solicitado > 0 ? Math.round(1000 * g.producido / g.solicitado) / 10 : null,
    })).sort((a, b) => b.solicitado - a.solicitado);
  }, [bucketSel]);

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
                   value={fmtP(adopcionTramoPct)} color={C.purple}
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
                    adopción <strong>{fmtP(adopcionTramoPct)}</strong> · plan {fmtN(resumenTramo.plan)} cj · SAP {fmtN(resumenTramo.sap)} cj
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

        {vista === "cumplimiento" && (
          <>
            {/* Gráfico de barras: cumplimiento % por semana; clic selecciona la semana */}
            <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 6 }}>
              Cumplimiento semanal (Producido / Solicitado, sin topear). Clic en una barra para ver el detalle.
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartBarras} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: C.textMuted }} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  formatter={(v, k, item) => {
                    const p = item?.payload || {};
                    return [`${v}% · sol ${fmtN(p.solicitado)} · prod ${fmtN(p.producido)} cj`, "Cumplimiento"];
                  }}
                  labelFormatter={(l) => `Semana ${l}`}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `0.5px solid ${C.border}` }} />
                <Bar dataKey="pct" radius={[3, 3, 0, 0]} cursor="pointer"
                     onClick={(d) => d && d.semana && setSemanaSel(d.semana)}>
                  {chartBarras.map((r) => (
                    <Cell key={r.semana} fill={cumplColor(r.pct)}
                          fillOpacity={r.semana === semanaSel ? 1 : 0.55}
                          stroke={r.semana === semanaSel ? C.text : "none"} strokeWidth={1} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {/* Detalle de la semana seleccionada, por línea colapsable */}
            {bucketSel ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                              margin: "18px 0 10px" }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>
                    Semana {fmtSem(bucketSel.bucket)} — detalle por línea
                  </div>
                  <div style={{ fontSize: 13, color: cumplColor(bucketSel.total.pct), fontWeight: 700 }}>
                    Total {fmtP(bucketSel.total.pct)} · {fmtN(bucketSel.total.producido)}/{fmtN(bucketSel.total.solicitado)} cj
                  </div>
                </div>
                <div style={{ border: `0.5px solid ${C.border}`, borderRadius: 8, overflow: "hidden" }}>
                  {cumplPorLinea.map((L, i) => {
                    const abierto = !!lineaAbiertaC[L.linea];
                    return (
                      <div key={L.linea} style={{ borderBottom: i < cumplPorLinea.length - 1 ? `0.5px solid ${C.border}` : "none" }}>
                        <div onClick={() => setLineaAbiertaC((e) => ({ ...e, [L.linea]: !e[L.linea] }))}
                             style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                                      padding: "10px 14px", cursor: "pointer", background: i % 2 ? C.grayLt : "#fff" }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
                            <span style={{ color: C.textMuted, marginRight: 8 }}>{abierto ? "▼" : "▶"}</span>
                            {L.linea} <span style={{ color: C.textMuted, fontWeight: 400 }}>· {L.filas.length} SKU</span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                            <span style={{ fontSize: 12, color: C.textMuted }}>
                              {fmtN(L.producido)}/{fmtN(L.solicitado)} cj
                            </span>
                            <span style={{ fontSize: 12, fontWeight: 700, padding: "2px 10px", borderRadius: 20,
                              minWidth: 54, textAlign: "center",
                              color: cumplColor(L.pct), background: cumplBg(L.pct) }}>
                              {fmtP(L.pct)}
                            </span>
                          </div>
                        </div>
                        {abierto && (
                          <div style={{ padding: "4px 14px 12px 34px", background: C.grayLt }}>
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                              <thead>
                                <tr>
                                  {["SKU", "Descripción", "Solicitado", "Producido", "Cumpl."].map((h, hi) => (
                                    <th key={h} style={{ ...s.th, background: "transparent",
                                      textAlign: hi >= 2 ? "right" : "left" }}>{h}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {L.filas.sort((a, b) => b.solicitado - a.solicitado).map((f) => (
                                  <tr key={f.sku}>
                                    <td style={{ ...s.td, fontWeight: 600, color: C.teal, borderBottom: "none" }}>{f.sku}</td>
                                    <td style={{ ...s.td, color: C.textMuted, borderBottom: "none" }}>{f.descripcion}</td>
                                    <td style={{ ...s.td, textAlign: "right", borderBottom: "none" }}>{fmtN(f.solicitado)}</td>
                                    <td style={{ ...s.td, textAlign: "right", borderBottom: "none" }}>{fmtN(f.producido)}</td>
                                    <td style={{ ...s.td, textAlign: "right", fontWeight: 700, borderBottom: "none",
                                      color: cumplColor(f.pct) }}>{fmtP(f.pct)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
                  Cumplimiento = Producido (TR) / Solicitado (OF), sin topear: &gt;100% indica sobreproducción.
                  Umbral: rojo &lt;90%, ámbar 90-99%, verde ≥100%. Semana por centro del tramo [ini, fin].
                </div>
              </>
            ) : (
              <div style={{ fontSize: 13, color: C.textMuted, padding: "20px 0" }}>
                Seleccioná una semana en el gráfico para ver el detalle.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
