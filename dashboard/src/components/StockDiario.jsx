import { useState, useEffect, useMemo, useRef } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend
} from "recharts";

// Pestaña "Stock Diario": apertura DIARIA del stock del plan vigente, diferenciando
// la demanda por forecast vs pedidos (OV). Lee el backend como fuente de verdad
// (GET /plan/proyeccion_diaria/{sku}); NO recalcula nada en el cliente (§5.1).

const API = "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  blue:    "#378ADD", blueLt:  "#E6F1FB",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
  // naranja dedicado a la OFT propuesta (amber ya se usa en la línea de SS)
  orange:  "#E8862B",
};

const fmtN  = (n) => Math.round(n ?? 0).toLocaleString("es-CL");
const fmtDs = (ds) => ds?.slice(5, 10) ?? "";   // MM-DD para eje X

// ── Tooltip: desglosa forecast / pedidos / demanda(corr) / stock / SS ─────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
  const line = (nombre, val, color) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, color, marginBottom: 2 }}>
      <span>{nombre}</span><strong>{fmtN(val)} cj</strong>
    </div>
  );
  return (
    <div style={{ background: "#fff", border: `0.5px solid ${C.border}`,
      borderRadius: 8, padding: "10px 14px", fontSize: 12, minWidth: 210 }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: C.text }}>{label}</div>
      {line("Forecast", row.forecast_cj, "#F09595")}
      {line("Pedidos (OV)", row.pedidos_cj, C.purple)}
      {line("Demanda (corr.)", row.demanda_corr_cj, C.gray)}
      {(row.oft_cj > 0 || row.entrada_cj > 0) && (
        <div style={{ borderTop: `0.5px solid ${C.border}`, margin: "5px 0" }} />
      )}
      {row.oft_cj > 0     && line("OFT propuesta", row.oft_cj, C.orange)}
      {row.entrada_cj > 0 && line("OF aprobada / OFM", row.entrada_cj, C.teal)}
      <div style={{ borderTop: `0.5px solid ${C.border}`, margin: "5px 0" }} />
      {row.stock_fin_cj != null && line("Stock final", row.stock_fin_cj, C.blue)}
      {row.ss_cj > 0 && line("Stock seguridad", row.ss_cj, C.amber)}
    </div>
  );
}

function KPI({ label, value, sub, color }) {
  return (
    <div style={{ background: C.grayLt, borderRadius: 8, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase",
        letterSpacing: ".04em", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

// ── Buscador de SKU (patrón de StockProyeccion, compacto) ─────────────────────
function SkuSearch({ skus, value, onChange }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = skus.find((s) => s.sku === value);
  const filtered = query.trim() === ""
    ? skus.slice(0, 100)
    : skus.filter((s) => s.sku.toLowerCase().includes(query.toLowerCase())
        || (s.descripcion || "").toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setQuery(""); } };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const select = (sk) => { onChange(sk.sku); setQuery(""); setOpen(false); };
  return (
    <div ref={ref} style={{ position: "relative", flex: 1, maxWidth: 480 }}>
      <input
        style={{ fontSize: 13, padding: "7px 10px", borderRadius: 6,
          border: `0.5px solid ${C.border}`, background: "#fff", color: C.text,
          width: "100%", outline: "none", boxSizing: "border-box" }}
        placeholder="Buscar por código o nombre de SKU..."
        value={open ? query : (selected ? `${selected.sku} — ${selected.descripcion}` : "")}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => { setOpen(true); setQuery(""); }}
      />
      {open && filtered.length > 0 && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 200,
          background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 8,
          boxShadow: "0 4px 16px rgba(0,0,0,.10)", maxHeight: 320, overflowY: "auto", marginTop: 2 }}>
          {filtered.map((sk, i) => (
            <div key={sk.sku} onMouseDown={() => select(sk)}
              style={{ padding: "8px 12px", cursor: "pointer", fontSize: 12,
                background: sk.sku === value ? C.tealLt : i % 2 === 0 ? "#fff" : C.grayLt,
                borderBottom: `0.5px solid ${C.border}`, display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ fontWeight: 700, color: C.teal, minWidth: 90, flexShrink: 0 }}>{sk.sku}</span>
              <span style={{ color: C.text }}>{sk.descripcion}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function StockDiario({ initialSku = "", ordenesAprobadas = [], ordenesPlan = [] }) {
  const [skuList, setSkuList] = useState([]);
  const [selSku,  setSelSku]  = useState(initialSku || "121010290");
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  // Lista de SKUs (para el buscador)
  useEffect(() => {
    fetch(`${API}/plan/params`).then((r) => r.json()).then((p) => {
      if (p.skus) setSkuList(p.skus.map((sk) => ({ sku: sk.sku, descripcion: sk.descripcion, u_por_caja: sk.u_por_caja })));
    }).catch(() => {});
  }, []);

  useEffect(() => { if (initialSku) setSelSku(initialSku); }, [initialSku]);

  // Serie diaria del backend
  // (13-07) firma de las aprobadas: cambia si se edita/agrega/quita una OF -> re-fetch
  const aprobFirma = useMemo(() => (ordenesAprobadas || [])
    .map(a => `${a.numero_of}:${a.cantidad_real_cj}:${a.fecha_entrada_real}`).join("|"),
    [ordenesAprobadas]);
  useEffect(() => {
    if (!selSku) return;
    setLoading(true); setError(null);
    // (13-07) endpoint LIVE: recalcula el balance con las OF aprobadas vivas
    fetch(`${API}/plan/proyeccion_diaria_live/${selSku}`)
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch((e) => { setError(String(e)); setLoading(false); });
  }, [selSku, aprobFirma]);

  const dias = data?.dias ?? [];
  const enc  = data?.encabezado ?? null;
  // (21-07) N° OFT por día. Dos fuentes con dos fechas de cruce distintas:
  //  · SUGERIDAS (OFT sin aprobar): vienen en ordenesPlan (plan.ordenes, con numero_of
  //    enriquecido), se ubican por fecha_lanzamiento -> día con oft_cajas.
  //  · APROBADAS (OF/OFM firmes): vienen en ordenesAprobadas (/ordenes/aprobadas),
  //    se ubican por fecha_entrada_real -> día con entrada_aprobada_u.
  // El endpoint diario_live NO trae numero_of, por eso el número se resuelve acá.
  const ofPorFecha = useMemo(() => {
    const idx = {};
    const push = (fecha, obj) => {
      if (!fecha) return;
      if (!idx[fecha]) idx[fecha] = [];
      idx[fecha].push(obj);
    };
    // sugeridas del plan (no aprobadas), por fecha_lanzamiento
    (ordenesPlan || []).forEach((o) => {
      if (o.sku !== selSku || o.aprobada) return;
      push(o.fecha_lanzamiento, { numero_of: o.numero_of, aprobada: false });
    });
    // aprobadas (OF/OFM), por fecha_entrada_real
    (ordenesAprobadas || []).forEach((o) => {
      if (o.sku !== selSku) return;
      push(o.fecha_entrada_real, { numero_of: o.numero_of, aprobada: true });
    });
    return idx;
  }, [ordenesPlan, ordenesAprobadas, selSku]);
  // u_por_caja del SKU seleccionado, para convertir entrada_aprobada_u (unidades) a cajas.
  const upcSel = (skuList.find((x) => x.sku === selSku)?.u_por_caja) || 1;
// (29-07-2026) PRODUCCIÓN EN EL GRÁFICO: dos series distintas, no una.
//   · oft_cj     = OFT PROPUESTA por el optimizador (aún sin aprobar) -> NARANJA.
//   · entrada_cj = OF / OFM ya APROBADA (entrada_aprobada_u del endpoint) -> VERDE.
// Al aprobar una OFT el optimizador deja de proponerla: `oft_cajas` pasa a null y la
// cantidad se mueve a `entrada_aprobada_u`. El gráfico dibujaba sólo `oft_cajas`, así
// que la barra DESAPARECÍA al aprobar aunque el balance de stock la siguiera contando.
// Lo APROBADO manda para el cálculo; lo propuesto queda como referencia visual (barra
// más tenue, con borde punteado).
  const chartData = useMemo(() => dias.map((r) => ({
    name: fmtDs(r.fecha), fecha: r.fecha,
    forecast_cj: r.forecast_cj, pedidos_cj: r.pedidos_cj,
    demanda_corr_cj: r.demanda_corr_cj, stock_fin_cj: r.stock_fin_cj, ss_cj: r.ss_cj,
    oft_cj: r.oft_cajas || 0,
    entrada_cj: r.entrada_aprobada_u ? r.entrada_aprobada_u / upcSel : 0,
  })), [dias, upcSel]);

  // Totales para tarjetas (demanda del horizonte)
  const totFc   = dias.reduce((sum, r) => sum + (r.forecast_cj || 0), 0);
  const totPed  = dias.reduce((sum, r) => sum + (r.pedidos_cj || 0), 0);
  const diasPed = dias.filter((r) => (r.pedidos_cj || 0) > 0).length;

  // Encabezado (viene del snapshot; sin clamp): físico, comprometido, disponible,
  // final, mínimo, SS(días). El mínimo real detecta quiebre (< 0).
  const minStk   = enc?.stock_min_cj;
  const dispIni  = enc?.disponible_inicial_cj;
  const stkColor = minStk != null && minStk < 0 ? C.red : minStk === 0 ? C.amber : C.teal;
  const dispColor= dispIni != null && dispIni < 0 ? C.red : C.text;

  const s = {
    wrap:  { fontFamily: "Arial,sans-serif", color: C.text, padding: "0 0 24px" },
    top:   { background: C.teal, color: "#fff", padding: "12px 20px", borderRadius: "10px 10px 0 0",
             marginBottom: 16 },
    card:  { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10,
             padding: "14px 18px", marginBottom: 14 },
    row:   { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 },
    lbl:   { fontSize: 12, fontWeight: 600, color: C.textMuted },
    kpis:  { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 10, marginBottom: 14 },
    leg:   { display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 10, fontSize: 12, color: C.textMuted },
    legItem:{ display: "flex", alignItems: "center", gap: 5 },
    legSq: (bg, r=2) => ({ width: 12, height: 12, borderRadius: r, background: bg }),
    tblWrap:{ overflowX: "auto", border: `0.5px solid ${C.border}`, borderRadius: 8 },
    th:    { padding: "8px 10px", fontSize: 11, color: C.textMuted, textTransform: "uppercase",
             letterSpacing: ".03em", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" },
    td:    { padding: "6px 10px", fontSize: 12, borderBottom: `0.5px solid ${C.border}`, whiteSpace: "nowrap" },
  };

  return (
    <div style={s.wrap}>
      <div style={s.top}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>📊 Stock Diario</div>
        <div style={{ fontSize: 11, opacity: .85, marginTop: 2 }}>
          Apertura diaria del stock del plan vigente · demanda desglosada en forecast vs pedidos (OV)
        </div>
      </div>

      <div style={s.card}>
        <div style={s.row}>
          <span style={s.lbl}>SKU:</span>
          <SkuSearch skus={skuList} value={selSku} onChange={setSelSku} />
          {data?.plan_id && (
            <span style={{ fontSize: 11, color: C.textMuted, marginLeft: "auto" }}>
              plan #{data.plan_id} · inicio {data.fecha_inicio} · H {Math.round((data.horizonte_dias||0)/7)} sem
            </span>
          )}
        </div>

        {loading && <div style={{ color: C.textMuted, padding: 20 }}>Cargando…</div>}
        {error && <div style={{ color: C.red, padding: 12 }}>Error: {error}</div>}
        {!loading && data && !data.disponible && (
          <div style={{ color: C.textMuted, padding: 20, textAlign: "center" }}>
            {data.plan_viejo
              ? <>El plan vigente es anterior al detalle diario corregido.<br/>
                  <span style={{ fontSize: 12 }}>Regenerá el plan (cron) para ver la vista nueva.</span></>
              : (data.mensaje || "Sin plan vigente.")}
          </div>
        )}

        {!loading && data?.disponible && (
          <>
            <div style={{ fontSize: 13, color: C.text, marginBottom: 12 }}>
              <strong>{data.sku}</strong> — {data.descripcion}
            </div>

            <div style={s.kpis}>
              <KPI label="Stock físico" value={enc?.stock_fisico_cj != null ? `${fmtN(enc.stock_fisico_cj)} cj` : "—"}
                   sub="stock real (SQL)" />
              <KPI label="Comprometido (OV venc.)" value={enc?.comprometido_cj != null ? `${fmtN(enc.comprometido_cj)} cj` : "—"}
                   color={enc?.comprometido_cj > 0 ? C.purple : C.textMuted}
                   sub="OV vencida (rebaja)" />
              <KPI label="Disponible inicial" value={dispIni != null ? `${fmtN(dispIni)} cj` : "—"}
                   color={dispColor}
                   sub={dispIni != null && dispIni < 0 ? "negativo = quiebre" : "físico − comprometido"} />
              <KPI label="Stock final" value={enc?.stock_final_cj != null ? `${fmtN(enc.stock_final_cj)} cj` : "—"}
                   sub="cierre del horizonte" />
              <KPI label="Stock mínimo" value={minStk != null ? `${fmtN(minStk)} cj` : "—"}
                   color={stkColor} sub={minStk === 0 ? "toca 0 (sin quiebre)" : minStk < 0 ? "quiebre" : "OK"} />
              <KPI label="SS (días hábiles)" value={data.ss_dias ? `${data.ss_dias} d` : "MTO (0)"} />
            </div>

            <div style={s.leg}>
              <span style={s.legItem}><span style={s.legSq("#F09595")} />Forecast</span>
              <span style={s.legItem}><span style={s.legSq(C.purple)} />Pedidos (OV)</span>
              <span style={s.legItem}><span style={s.legSq(C.orange)} />OFT propuesta</span>
              <span style={s.legItem}><span style={s.legSq(C.teal)} />OF aprobada / OFM</span>
              <span style={s.legItem}><span style={{ width: 14, height: 2, background: C.blue, display: "inline-block" }} />Stock final</span>
              <span style={s.legItem}><span style={{ width: 14, height: 2, background: C.amber, display: "inline-block" }} />Stock seguridad</span>
              <span style={s.legItem}><span style={{ width: 14, height: 2, background: C.gray, display: "inline-block" }} />Demanda corr.</span>
            </div>

            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }}
                  interval={Math.max(0, Math.floor(chartData.length / 14))} />
                <YAxis tick={{ fontSize: 10, fill: C.textMuted }}
                  tickFormatter={(v) => v >= 1000 ? `${Math.round(v / 1000)}k` : v} />
                <Tooltip content={<CustomTooltip />} />
                {/* Demanda: forecast y pedidos LADO A LADO (no apilados: demanda = max, no suma) */}
                <Bar dataKey="forecast_cj" name="Forecast (cj)" fill="#F09595" barSize={9} radius={[2,2,0,0]} />
                <Bar dataKey="pedidos_cj"  name="Pedidos OV (cj)" fill={C.purple} barSize={9} radius={[2,2,0,0]} />
                {/* Producción: propuesta (referencia, tenue) vs aprobada (manda) */}
                <Bar dataKey="oft_cj" name="OFT propuesta (cj)" fill={C.orange} fillOpacity={0.35}
                     stroke={C.orange} strokeDasharray="3 2" barSize={11} radius={[2,2,0,0]} />
                <Bar dataKey="entrada_cj" name="OF aprobada / OFM (cj)" fill={C.teal} fillOpacity={0.75}
                     stroke={C.tealMid} barSize={11} radius={[2,2,0,0]} />
                {/* Demanda corregida (max) como línea fina de referencia */}
                <Line dataKey="demanda_corr_cj" name="Demanda corr. (cj)" stroke={C.gray}
                  strokeWidth={1} dot={false} strokeDasharray="2 2" />
                {/* Stock final del plan (sin clamp) */}
                <Line dataKey="stock_fin_cj" name="Stock final (cj)" stroke={C.blue}
                  strokeWidth={2.5} dot={{ r: 2, fill: C.blue }} activeDot={{ r: 5 }} connectNulls />
                <Line dataKey="ss_cj" name="Stock seguridad (cj)" stroke={C.amber}
                  strokeWidth={1.5} strokeDasharray="5 4" dot={false} />
                <ReferenceLine y={0} stroke={C.red} strokeDasharray="3 3" />
              </ComposedChart>
            </ResponsiveContainer>

            <div style={{ ...s.tblWrap, marginTop: 14 }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Fecha","N° OFT","Stock disponible","Pedidos","Forecast","Demanda (corr.)","Cantidad OFT","Stock final","SS (u)","Estado"].map((h, i) => (
                      <th key={h} style={{ ...s.th, textAlign: i === 0 ? "left" : "right" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dias.map((r, i) => {
                    const neg  = r.estado === "QUIEBRE";
                    const bajo = r.estado === "BAJO_SS";
                    const tieneOft = r.oft_cajas != null && r.oft_cajas > 0;
                    // Entrada aprobada (OF/OFM): viene en unidades -> a cajas. Es producción
                    // FIRME (aprobada), distinta de una OFT sugerida por el solver.
                    const entApr = r.entrada_aprobada_u != null && r.entrada_aprobada_u > 0
                      ? r.entrada_aprobada_u / upcSel : 0;
                    // (21-07) "asumida" = hay OFT pero SIN entrada aprobada -> sugerida por el solver.
                    const esAsumida = tieneOft && entApr === 0;
                    // N° OFT del día (ver ofPorFecha: sugeridas + aprobadas; puede haber >1).
                    const ofsDia = ofPorFecha[r.fecha] || [];
                    return (
                      <tr key={r.fecha} style={{ background: neg ? "#FFF0F0" : bajo ? "#FFFBF0" : i % 2 === 0 ? "#fff" : C.grayLt }}>
                        {/* 1. Fecha */}
                        <td style={{ ...s.td, color: C.textMuted, textAlign: "left" }}>{r.fecha}</td>
                        {/* 2. N° OFT (número limpio; "—" si no hay orden ese día) */}
                        <td style={{ ...s.td, textAlign: "right" }}>
                          {ofsDia.length > 0
                            ? ofsDia.map((o, k) => (
                                <div key={o.numero_of || k}
                                  style={{ color: o.aprobada ? C.purple : C.teal, fontWeight: 700, whiteSpace: "nowrap" }}
                                  title={o.aprobada ? "OF/OFM aprobada (firme)" : "OFT sugerida"}>
                                  {o.numero_of || "—"}
                                </div>
                              ))
                            : <span style={{ color: C.textMuted }}>—</span>}
                        </td>
                        {/* 3. Stock disponible */}
                        <td style={{ ...s.td, textAlign: "right",
                          color: (r.stock_ini_disp_cj != null && r.stock_ini_disp_cj < 0) ? C.red : C.text }}>
                          {r.stock_ini_disp_cj != null ? fmtN(r.stock_ini_disp_cj) : "—"}</td>
                        {/* 4. Pedidos (OV cruda real; fallback a pedidos_cj si snapshot viejo) */}
                        {(() => {
                          const pedCrudo = r.pedidos_crudos_cj != null ? r.pedidos_crudos_cj : r.pedidos_cj;
                          return (
                            <td style={{ ...s.td, textAlign: "right", color: pedCrudo > 0 ? C.purple : C.textMuted, fontWeight: pedCrudo > 0 ? 700 : 400 }}>
                              {pedCrudo > 0 ? fmtN(pedCrudo) : "—"}</td>
                          );
                        })()}
                        {/* 5. Forecast */}
                        <td style={{ ...s.td, textAlign: "right", color: r.forecast_cj > 0 ? "#C96B6B" : C.textMuted }}>
                          {r.forecast_cj > 0 ? fmtN(r.forecast_cj) : "—"}</td>
                        {/* 6. Demanda (corr.) */}
                        <td style={{ ...s.td, textAlign: "right", fontWeight: 600 }}>{fmtN(r.demanda_corr_cj)}</td>
                        {/* 7. Cantidad OFT: sugerida (+ "asumida") y/o aprobada firme (✓) */}
                        <td style={{ ...s.td, textAlign: "right" }}>
                          {tieneOft && (
                            <span style={{ color: C.teal, fontWeight: 700 }}>{fmtN(r.oft_cajas)} cj</span>
                          )}
                          {tieneOft && entApr > 0 && <span style={{ color: C.textMuted }}> + </span>}
                          {entApr > 0 && (
                            <span style={{ color: C.purple, fontWeight: 700 }} title="OF/OFM aprobada (producción firme)">
                              {fmtN(entApr)} cj ✓
                            </span>
                          )}
                          {tieneOft && esAsumida && (
                            <div style={{ fontSize: 10, color: C.textMuted, fontStyle: "italic", lineHeight: 1.2 }}>asumida</div>
                          )}
                          {!tieneOft && entApr === 0 && <span style={{ color: C.textMuted }}>—</span>}
                        </td>
                        {/* 8. Stock final */}
                        <td style={{ ...s.td, textAlign: "right", fontWeight: 700,
                          color: neg ? C.red : bajo ? C.amber : C.text }}>
                          {r.stock_fin_cj != null ? fmtN(r.stock_fin_cj) : "—"}</td>
                        {/* 9. SS (u) */}
                        <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>{r.ss_u > 0 ? fmtN(r.ss_u) : "—"}</td>
                        {/* 10. Estado */}
                        <td style={{ ...s.td, textAlign: "center" }}>
                          {neg
                            ? <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 10, background: C.redLt, color: "#791F1F" }}>Quiebre</span>
                            : bajo
                            ? <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 10, background: C.amberLt, color: "#854F0B" }}>Bajo SS</span>
                            : <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 10, background: C.tealLt, color: C.tealMid }}>OK</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
