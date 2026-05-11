import { useState, useEffect, useMemo } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend
} from "recharts";

const API = "";

// ── Parámetros MRP hardcodeados como fallback (se reemplazan con /plan/params) ──
const PARAMS_FALLBACK = {
  "410010185": { desc:"SOPA INST. CARNE TRAVERSO 12x65 POTE", tipo:"IMPORTACION", upj:12, ss_dias:90,  lt:6.0  },
  "260010105": { desc:"MOSTAZA TRAVERSO 10x1000 BOLSA",        tipo:"PRODUCCION",  upj:10, ss_dias:10,  lt:0.5  },
  "121010290": { desc:"JUGO LIMON TRAVERSO 30x500 PET",        tipo:"PRODUCCION",  upj:30, ss_dias:8,   lt:0.3  },
  "250010105": { desc:"KETCHUP TRAVERSO 10x1000 BOLSA",        tipo:"PRODUCCION",  upj:10, ss_dias:15,  lt:1.0  },
  "121010210": { desc:"JUGO LIMON TRAVERSO 20x1000 PET",       tipo:"PRODUCCION",  upj:20, ss_dias:10,  lt:0.5  },
  "113010290": { desc:"VINAGRE MANZANA TRAVERSO 30x500 PET",   tipo:"PRODUCCION",  upj:30, ss_dias:15,  lt:1.0  },
  "111010290": { desc:"VINAGRE BLANCO TRAVERSO 30x500 PET",    tipo:"PRODUCCION",  upj:30, ss_dias:12,  lt:0.8  },
  "112010290": { desc:"VINAGRE ROSADO TRAVERSO 30x500 PET",    tipo:"PRODUCCION",  upj:30, ss_dias:10,  lt:0.5  },
  "114010290": { desc:"VINAGRE INCOLORO TRAVERSO 30x500 PET",  tipo:"PRODUCCION",  upj:30, ss_dias:8,   lt:0.3  },
  "500170180": { desc:"SALSA SOYA KIKKOMAN 12x591 VIDRIO",     tipo:"IMPORTACION", upj:12, ss_dias:120, lt:12.0 },
};

// ── Colores ────────────────────────────────────────────────────────────────────
const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  blue:    "#378ADD", blueLt:  "#E6F1FB",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
};

const TIPO_COLOR = {
  PRODUCCION:  { bg: C.tealLt,   color: C.tealMid,  bar: C.teal   },
  IMPORTACION: { bg: C.purpleLt, color: C.purple,    bar: "#AFA9EC" },
  MAQUILA:     { bg: C.amberLt,  color: "#854F0B",   bar: C.amber  },
};

// ── Helpers ────────────────────────────────────────────────────────────────────
const fmtN  = (n) => Math.round(n ?? 0).toLocaleString("es-CL");
const fmtD  = (ds) => ds?.slice(0, 10) ?? "";
const fmtDs = (ds) => ds?.slice(5, 10) ?? "";   // MM-DD para eje X

// Normaliza una fecha al domingo de su semana (inicio de semana dom→sáb)
function getSemana(fecha) {
  if (!fecha) return fecha;
  const d = new Date(fecha + "T12:00:00");
  d.setDate(d.getDate() - d.getDay()); // retroceder al domingo
  return d.toISOString().slice(0, 10);
}

// ── Tooltip personalizado ──────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#fff", border: `0.5px solid ${C.border}`,
      borderRadius: 8, padding: "10px 14px", fontSize: 12, minWidth: 200,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: C.text }}>{label}</div>
      {payload.map((p, i) => p.value != null && (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 16,
          color: p.color ?? C.text, marginBottom: 2 }}>
          <span>{p.name}</span>
          <strong>{fmtN(p.value)} cj</strong>
        </div>
      ))}
    </div>
  );
}

// ── Componente KPI ─────────────────────────────────────────────────────────────
function KPI({ label, value, sub, color }) {
  return (
    <div style={{
      background: C.grayLt, borderRadius: 8, padding: "10px 14px",
    }}>
      <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase",
        letterSpacing: ".04em", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

// ── Componente principal ───────────────────────────────────────────────────────
export default function StockProyeccion({
  initialSku = '',
  planExterno = null,
  planLoading = false,
  onSolicitarPlan = null,
}) {
  const [skuList,    setSkuList]    = useState([]);
  const [params,     setParams]     = useState(PARAMS_FALLBACK);

  const [selSku,     setSelSku]     = useState(initialSku || "121010290");
  const [ordenes,    setOrdenes]    = useState([]);
  const [stockReal,  setStockReal]  = useState(0);
  const [stockInfo,  setStockInfo]  = useState(null);
  // V6.27 / Bloque B1: backend emite proyeccion_por_sku como fuente unica de verdad
  const [proyeccionBackend, setProyeccionBackend] = useState(null);

  // Cargar lista de SKUs y params al montar
  useEffect(() => {
    Promise.all([
      fetch(`${API}/plan/params`).then((r) => r.json()),
      fetch(`${API}/stock/summary`).then((r) => r.json()),
    ])
      .then(([p, s]) => {
        if (p.skus) {
          const map = {};
          p.skus.forEach((sk) => {
            map[sk.sku] = {
              desc:    sk.descripcion,
              tipo:    sk.tipo,
              upj:     sk.u_por_caja,
              ss_dias: sk.ss_dias,
              lt:      sk.lead_time_sem,
              linea:   sk.linea_preferida,
            };
          });
          setParams(map);

          const lista = p.skus.map((sk) => ({ sku: sk.sku, desc: sk.descripcion, tipo: sk.tipo }));
          setSkuList(lista);
          // Si hay un initialSku válido en la lista, asegurarlo como seleccionado
          if (initialSku && lista.some(sk => sk.sku === initialSku)) {
            setSelSku(initialSku);
          }
        }
        if (s.disponible) setStockInfo(s);
      })
      .catch(() => {});
  }, []);

  // Sincronizar con el plan del padre (App.js es la única fuente de verdad de /plan).
  // V6.27 / Bloque B1: leer proyeccion_por_sku del backend en vez de recalcular.
  useEffect(() => {
    if (!planExterno || !selSku) {
      setOrdenes([]);
      setStockReal(0);
      setProyeccionBackend(null);
      return;
    }
    const ordenesSku = (planExterno.ordenes ?? []).filter(o => o.sku === selSku);
    setOrdenes(ordenesSku);
    const proyBackend = planExterno.proyeccion_por_sku?.[selSku] ?? null;
    setProyeccionBackend(proyBackend);
    setStockReal(proyBackend?.stock_inicial_cj ?? 0);
  }, [planExterno, selSku]);

  const p       = params[selSku] ?? {};
  const ssDias  = p.ss_dias ?? 10;
  const tipoC   = TIPO_COLOR[p.tipo] ?? TIPO_COLOR.PRODUCCION;

  // V6.27 / Bloque B1: proyeccion derivada del backend.
  // El frontend solo mapea: sin recalculo de entradas, ventas, SS ni stock.
  // Las OFTs se cruzan por semana viz solo para mostrar N° OF y F. Entrada en la tabla
  // (lookup, no calculo paralelo — el backend ya las contó en n_ofts_semana).
  const proyeccion = useMemo(() => {
    if (!proyeccionBackend?.semanas) return [];
    const ofPorSemana = {};
    ordenes.forEach(o => {
      const fer = fmtD(o.fecha_entrada_real || o.semana_necesidad);
      const sem = getSemana(fer);
      if (!sem) return;
      if (!ofPorSemana[sem]) ofPorSemana[sem] = [];
      ofPorSemana[sem].push(o);
    });
    const tipoSku = params[selSku]?.tipo || "";
    return proyeccionBackend.semanas.map(s => {
      const primera = (ofPorSemana[s.semana] || [])[0];
      const fuente = s.entradas_aprobadas_cj > 0 ? "aprobada"
                   : s.entradas_sugeridas_cj > 0 ? "asumida" : "";
      return {
        ds: s.semana,
        stockIni: s.stock_ini_cj,
        entradas: s.entradas_cj,
        entradasAprobadas: s.entradas_aprobadas_cj,
        entradasSugeridas: s.entradas_sugeridas_cj,
        tipo: tipoSku,
        fuente,
        ventas: s.ventas_cj,
        stockFin: s.stock_fin_cj_visible,    // curva azul (clampeado >=0)
        stockFinReal: s.stock_fin_cj_real,   // KPIs y estado (puede ser <0)
        ss: s.ss_cj,
        estado: s.estado,                    // "OK" | "BAJO_SS" | "QUIEBRE"
        semanaParcial: s.semana_parcial,
        nOftsSemana: s.n_ofts_semana,
        tienePendiente: false,               // V6.26: backend ya consideró OFTs sugeridas
        numero_of: primera?.numero_of ?? null,
        fechaEntReal: primera ? fmtD(primera.fecha_entrada_real || primera.semana_necesidad) : null,
        fechaEntMRP: primera ? fmtD(primera.semana_necesidad) : null,
        fechaDifiere: false,
        // TODO V6.X: bandas reales de Prophet (yhat_lower/yhat_upper). Hoy ±20% aprox.
        yhat_lower: Math.round(s.ventas_cj * 0.8),
        yhat_upper: Math.round(s.ventas_cj * 1.2),
      };
    });
  }, [proyeccionBackend, ordenes, params, selSku]);

  // n órdenes incluidas en proyección — suma de n_ofts_semana del backend
  const nOrdenesProyeccion = useMemo(
    () => proyeccion.reduce((s, r) => s + (r.nOftsSemana ?? 0), 0),
    [proyeccion]
  );

  // KPIs derivados — usar stockFinReal y estado del backend
  const totalVentas   = proyeccion.reduce((s, r) => s + r.ventas,   0);
  const totalEntradas = proyeccion.reduce((s, r) => s + r.entradas, 0);
  const minStock      = proyeccion.length ? Math.min(...proyeccion.map((r) => r.stockFinReal)) : 0;
  const semBajoSS     = proyeccion.filter((r) => r.estado !== "OK").length;
  const stockColor    = minStock < 0 ? C.red : semBajoSS > 0 ? C.amber : C.teal;
  // Horizonte derivado del plan (ya no es input del usuario en este componente)
  const horizonte     = planExterno?.horizonte_sem ?? 4;

  // Datos para el gráfico — separar entradas por tipo
  const chartData = proyeccion.map((r) => ({
    name:       fmtDs(r.ds),
    fecha:      r.ds,
    produccion: r.tipo === "PRODUCCION"  ? r.entradas : 0,
    importacion:r.tipo === "IMPORTACION" ? r.entradas : 0,
    maquila:    r.tipo === "MAQUILA"     ? r.entradas : 0,
    ventas:     r.ventas,
    stock:      r.stockFin,
    ss:         r.ss,
  }));

  const s = {
    wrap:    { fontFamily: "Arial,sans-serif", color: C.text, padding: "0 0 24px" },
    topbar:  { background: C.teal, color: "#fff", padding: "12px 20px", borderRadius: "10px 10px 0 0",
               display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
    topTit:  { fontWeight: 700, fontSize: 14, letterSpacing: .3 },
    topSub:  { fontSize: 11, opacity: .85, marginTop: 2 },
    badge:   (bg, col) => ({ display: "inline-block", background: bg, color: col,
               fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10 }),
    card:    { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10,
               padding: "14px 18px", marginBottom: 14 },
    row:     { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 },
    lbl:     { fontSize: 12, fontWeight: 600, color: C.textMuted },
    sel:     { fontSize: 12, padding: "5px 8px", borderRadius: 6, border: `0.5px solid ${C.border}`,
               background: "#fff", color: C.text, cursor: "pointer" },
    kpis:    { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, marginBottom: 14 },
    leg:     { display: "flex", flexWrap: "wrap", gap: 14, marginBottom: 10, fontSize: 12, color: C.textMuted },
    legItem: { display: "flex", alignItems: "center", gap: 5 },
    legSq:   (bg) => ({ width: 10, height: 10, borderRadius: 2, background: bg }),
    tblWrap: { overflowX: "auto", border: `0.5px solid ${C.border}`, borderRadius: 8 },
    th:      { padding: "6px 10px", fontSize: 11, fontWeight: 600, color: C.textMuted,
               background: C.grayLt, borderBottom: `0.5px solid ${C.border}`, whiteSpace: "nowrap" },
    td:      { padding: "5px 10px", fontSize: 12, borderBottom: `0.5px solid ${C.border}` },
  };

  return (
    <div style={s.wrap}>
      {/* Topbar */}
      <div style={s.topbar}>
        <div>
          <div style={s.topTit}>Proyección de Stock por SKU</div>
          <div style={s.topSub}>
            Bodegas BSUR01 · VESP01 · VARA01
            {stockInfo && ` · Stock descargado: ${stockInfo.fecha_descarga_info ?? "—"}`}
          </div>
        </div>
        {p.tipo && (
          <span style={s.badge(tipoC.bg, tipoC.color)}>{p.tipo}</span>
        )}
      </div>

      {/* Banner: plan no generado — red de seguridad */}
      {!planExterno && (
        <div style={{
          background: C.amberLt, border: `0.5px solid ${C.amber}`, color: "#854F0B",
          borderRadius: 7, padding: "10px 14px", fontSize: 12, marginBottom: 12,
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
        }}>
          <span>
            {planLoading
              ? "⏳ Generando plan de producción... la proyección de stock se actualizará al terminar."
              : "⚠ No hay plan de producción generado. La proyección de stock no incluye órdenes futuras."}
          </span>
          {!planLoading && onSolicitarPlan && (
            <button onClick={onSolicitarPlan}
              style={{ fontSize: 12, padding: "6px 14px", borderRadius: 7, border: "none",
                       background: C.amber, color: "#fff", cursor: "pointer", fontWeight: 700,
                       whiteSpace: "nowrap" }}>
              Generar plan
            </button>
          )}
        </div>
      )}

      {/* Controles */}
      <div style={s.card}>
        <div style={s.row}>
          <span style={s.lbl}>SKU:</span>
          <select style={{ ...s.sel, minWidth: 320 }} value={selSku}
            onChange={(e) => setSelSku(e.target.value)}>
            {(skuList.length ? skuList : Object.entries(params).map(([k, v]) => ({ sku: k, desc: v.desc }))).map((sk) => (
              <option key={sk.sku} value={sk.sku}>{sk.sku} — {sk.desc ?? params[sk.sku]?.desc}</option>
            ))}
          </select>
          <span style={s.lbl}>Horizonte:</span>
          <select style={{ ...s.sel, opacity: 0.6, cursor: "not-allowed" }}
                  value={horizonte} disabled
                  title="El horizonte se define al generar el plan">
            {[4, 8, 13, 17, 26].map((h) => (
              <option key={h} value={h}>{h} sem. (~{Math.round(h / 4.3)} meses)</option>
            ))}
            {![4, 8, 13, 17, 26].includes(horizonte) && (
              <option key={horizonte} value={horizonte}>{horizonte} sem.</option>
            )}
          </select>
          <span style={{ fontSize: 11, color: C.textMuted, fontStyle: "italic" }}>(del plan)</span>
          {planLoading && <span style={{ fontSize: 12, color: C.textMuted }}>Cargando...</span>}
        </div>
        {p.desc && (
          <div style={{ fontSize: 11, color: C.textMuted }}>
            <span style={{ marginRight: 16 }}>Lead time: <strong>{p.lt} sem.</strong></span>
            <span style={{ marginRight: 16 }}>Stock seguridad: <strong>{ssDias} días</strong></span>
            <span style={{ marginRight: 16 }}>U./caja: <strong>{p.upj}</strong></span>
            {p.linea && <span>Línea preferida: <strong>{p.linea}</strong></span>}
          </div>
        )}
      </div>

      {/* KPIs */}
      <div style={s.kpis}>
        <KPI label="Stock actual (cj)" value={fmtN(stockReal)}
          sub={stockInfo?.disponible ? "desde SQL Server" : "sin datos de stock"} />
        <KPI label="Venta estimada (cj)" value={fmtN(totalVentas)}
          sub={`${horizonte} semanas · forecast`} />
        <KPI label="Producción/Import. (cj)" value={fmtN(totalEntradas)}
          sub={nOrdenesProyeccion > 0 ? `${nOrdenesProyeccion} órdenes en proyección` : "Sin órdenes"} />
        <KPI label="Stock mínimo proy. (cj)" value={fmtN(minStock)}
          color={stockColor}
          sub={semBajoSS > 0 ? `${semBajoSS} sem. bajo SS` : "Sobre stock seguridad"} />
        <KPI label="Cobertura actual" value={totalVentas > 0
            ? `${((stockReal / (totalVentas / horizonte)) * 7).toFixed(0)} días` : "—"}
          sub="en base al forecast" />
      </div>

      {/* Gráfico */}
      {proyeccion.length > 0 && (
        <div style={s.card}>
          <div style={{ fontWeight: 600, fontSize: 13, color: C.text, marginBottom: 10 }}>
            Entradas, salidas y stock proyectado — semanas desde hoy
          </div>
          <div style={s.leg}>
            {p.tipo === "PRODUCCION"  && <span style={s.legItem}><span style={s.legSq(C.teal)}/>Producción</span>}
            {p.tipo === "IMPORTACION" && <span style={s.legItem}><span style={s.legSq("#AFA9EC")}/>Importación</span>}
            {p.tipo === "MAQUILA"     && <span style={s.legItem}><span style={s.legSq(C.amber)}/>Maquila</span>}
            <span style={s.legItem}><span style={s.legSq("#F09595")}/>Ventas (forecast)</span>
            <span style={s.legItem}><span style={{ ...s.legSq(C.blue), borderRadius: 0 }}/>Stock proyectado</span>
            <span style={s.legItem}><span style={{ width: 14, height: 2, background: C.amber, display: "inline-block", marginRight: 5 }}/>Stock seguridad</span>
            <span style={s.legItem}><span style={{ fontSize: 12, marginRight: 4, color: C.teal }}>✓</span>Entrada aprobada</span>
            <span style={s.legItem}><span style={{ fontSize: 12, marginRight: 4, color: C.amber }}>~</span>Sugerida (sin aprobar)</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: C.textMuted }}
                interval={Math.floor(chartData.length / 12)} />
              <YAxis tick={{ fontSize: 10, fill: C.textMuted }}
                tickFormatter={(v) => v >= 1000 ? `${Math.round(v / 1000)}k` : v} />
              <Tooltip content={<CustomTooltip />} />

              {/* Entradas apiladas por tipo */}
              <Bar dataKey="produccion"  name="Producción (cj)"  stackId="e" fill={C.teal}    barSize={14} radius={[2,2,0,0]} />
              <Bar dataKey="importacion" name="Importación (cj)" stackId="e" fill="#AFA9EC"   barSize={14} />
              <Bar dataKey="maquila"     name="Maquila (cj)"     stackId="e" fill={C.amber}   barSize={14} />
              {/* Salidas */}
              <Bar dataKey="ventas"      name="Ventas FC (cj)"   stackId="s" fill="#F09595"   barSize={14} radius={[2,2,0,0]} />
              {/* Stock y SS */}
              <Line dataKey="stock" name="Stock proyectado (cj)" stroke={C.blue}
                strokeWidth={2.5} dot={{ r: 3, fill: C.blue }} activeDot={{ r: 5 }} />
              <Line dataKey="ss"    name="Stock seguridad (cj)"  stroke={C.amber}
                strokeWidth={1.5} strokeDasharray="5 4" dot={false} />

              <ReferenceLine y={0} stroke={C.red} strokeDasharray="3 3" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Tabla semanal */}
      {proyeccion.length > 0 && (
        <div style={s.card}>
          <div style={{ fontWeight: 600, fontSize: 13, color: C.text, marginBottom: 10 }}>
            Proyección semanal detallada
          </div>
          <div style={s.tblWrap}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["Semana", "Stock ini.", "N° OF", "F. Entrada", "Entradas (cj)", "Tipo",
                    "Ventas FC (cj)", "Stock fin.", "SS (cj)", "Cobertura", "Estado"].map((h, i) => (
                    <th key={h} style={{ ...s.th, textAlign: i === 0 ? "left" : "right" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {proyeccion.map((r, i) => {
                  const bajo     = r.stockFin < r.ss;
                  const negativo = r.stockFin < 0;
                  const cobDias  = r.ventas > 0 ? Math.round((r.stockFin / r.ventas) * 7) : 999;
                  const tc       = TIPO_COLOR[r.tipo];
                  return (
                    <tr key={i} style={{ background: negativo ? "#FFF0F0" : bajo ? "#FFFBF0" : i % 2 === 0 ? "#fff" : C.grayLt }}>
                      <td style={{ ...s.td, color: C.textMuted, textAlign: "left" }}>{r.ds}</td>
                      {/* Stock ini */}
                      <td style={{ ...s.td, textAlign:'right', fontWeight:700 }}>
                        {fmtN(r.stockIni)}
                      </td>
                      {/* N° OF */}
                      <td style={{ ...s.td, fontSize:10,
                        color: r.numero_of?.startsWith('OFT') ? C.amber : r.numero_of ? C.tealMid : C.textMuted,
                        fontWeight:600, whiteSpace:'nowrap' }}>
                        {r.numero_of ?? '—'}
                      </td>
                      {/* F. Entrada real */}
                      <td style={{ ...s.td, whiteSpace:'nowrap' }}>
                        {r.entradas > 0 ? (
                          <span
                            style={{ color: r.fechaDifiere ? C.amber : C.text, fontWeight: r.fechaDifiere ? 700 : 400 }}
                            title={r.fechaDifiere ? `MRP sugería: ${r.fechaEntMRP}` : (r.fechaEntReal ?? '')}>
                            {r.fechaDifiere && '📅 '}
                            {r.fechaEntReal ?? '—'}
                          </span>
                        ) : '—'}
                      </td>
                      {/* Entradas cj */}
                      <td style={{ ...s.td, textAlign:'right', color: r.entradas > 0 ? (r.fuente==='aprobada' ? C.tealMid : C.amber) : C.textMuted, fontWeight: r.entradas > 0 ? 700 : 400 }}>
                        {r.entradas > 0 ? (
                          <>
                            <span>{r.fuente==='aprobada' ? '✓' : '~'} +{r.entradas.toLocaleString('es-CL')}</span>
                            <div style={{fontSize:9,color:r.fuente==='aprobada'?C.teal:C.amber}}>
                              {r.fuente==='aprobada' ? '✓ aprobada' : 'asumida'}
                            </div>
                          </>
                        ) : '—'}
                      </td>
                      {/* Tipo */}
                      <td style={{ ...s.td, textAlign:'center' }}>
                        {r.tipo ? (
                          <span style={{fontSize:9,padding:'1px 5px',borderRadius:3,
                            background:r.tipo==='PRODUCCION'?C.tealLt:r.tipo==='IMPORTACION'?'#EEF':C.amberLt,
                            color:r.tipo==='PRODUCCION'?C.teal:r.tipo==='IMPORTACION'?'#534AB7':C.amber}}>
                            {r.tipo==='PRODUCCION'?'PROD':r.tipo==='IMPORTACION'?'IMP':'MAQ'}
                          </span>
                        ) : '—'}
                      </td>
                      {/* Ventas FC */}
                      <td style={{ ...s.td, textAlign:'right', color:C.red }}>
                        {(-r.ventas).toLocaleString('es-CL')}
                      </td>
                      {/* Stock fin */}
                      <td style={{ ...s.td, textAlign:'right', fontWeight:700,
                        color: r.stockFin < 0 ? C.red : r.stockFin < r.ss ? C.amber : C.text }}>
                        {fmtN(r.stockFin)}
                      </td>
                      {/* SS */}
                      <td style={{ ...s.td, textAlign:'right', color:C.textMuted }}>
                        {fmtN(r.ss)}
                      </td>
                      {/* Cobertura */}
                      <td style={{ ...s.td, textAlign:'right',
                        color: r.stockFin < r.ss ? C.amber : C.textMuted }}>
                        {r.stockFin > 0 && r.ventas > 0
                          ? `${Math.round((r.stockFin/r.ventas)*7)}d` : '0d'}
                      </td>
                      {/* Estado */}
                      <td style={{ ...s.td, textAlign:'center' }}>
                        {r.stockFin < 0
                          ? <span style={{fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:10,background:C.redLt,color:'#791F1F'}}>Rotura</span>
                          : r.stockFin < r.ss
                          ? <span style={{fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:10,background:C.amberLt,color:'#854F0B'}}>Bajo SS</span>
                          : <span style={{fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:10,background:C.tealLt,color:C.tealMid}}>OK</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {planExterno && proyeccion.length === 0 && (
        <div style={{ ...s.card, textAlign: "center", color: C.textMuted, padding: 40 }}>
          Sin datos disponibles para este SKU — verifica que hay forecast entrenado
        </div>
      )}
    </div>
  );
}
