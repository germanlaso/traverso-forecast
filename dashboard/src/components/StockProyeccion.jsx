import { useState, useEffect, useRef, useMemo } from "react";
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

function getSemanaActual() {
  const hoy = new Date();
  const lunes = new Date(hoy);
  lunes.setDate(hoy.getDate() - hoy.getDay() + 1);
  return lunes.toISOString().slice(0, 10);
}

function calcularProyeccion(forecast, ordenesPlan, stockInicial, ssDias, ordenesAprobadas = []) {
  const semanaActual = getSemanaActual();

  // Mapa de aprobadas por sku+semana_necesidad para lookup rápido
  const aprobMap = {};
  ordenesAprobadas.forEach(a => {
    const k = `${a.sku}__${fmtD(a.semana_necesidad)}`;
    aprobMap[k] = a;
  });

  // Construir entradas por semana aplicando la regla:
  // semana_emision > hoy → asumir como aprobada (cantidad MRP) — aún hay tiempo de lanzar
  // semana_emision <= hoy + sin aprobar → NO incluir — ya debió lanzarse y no se hizo
  // Aprobada explícitamente → incluir en fecha_entrada_real (puede diferir de semana_necesidad)
  const entradasPorSemana = {};
  ordenesPlan.forEach(o => {
    const dsNecesidad = fmtD(o.semana_necesidad);
    const dsEmision   = fmtD(o.semana_emision);
    const aprobada    = aprobMap[`${o.sku}__${dsNecesidad}`];
    let cantidad = 0;
    let fuente   = "";
    let dsEntrada = dsNecesidad; // por defecto entrada en semana_necesidad

    if (aprobada) {
      // Siempre usar cantidad real aprobada
      // Si tiene fecha_entrada_real ajustada, usarla
      cantidad  = aprobada.cantidad_real_cj;
      dsEntrada = fmtD(aprobada.fecha_entrada_real ?? aprobada.semana_necesidad);
      fuente    = "aprobada";
    } else if (dsEmision > semanaActual) {
      // Lanzamiento futuro → asumir como aprobada con cantidad MRP
      cantidad = o.cantidad_cajas ?? 0;
      fuente   = "asumida";
    }
    // si dsEmision <= semanaActual y no aprobada → cantidad = 0 (no se incluye)

    if (cantidad > 0) {
      if (!entradasPorSemana[dsEntrada]) entradasPorSemana[dsEntrada] = [];
      entradasPorSemana[dsEntrada].push({ cantidad, tipo: o.tipo, fuente });
    }
  });

  let stock = stockInicial;
  return forecast.map((f) => {
    const ds      = fmtD(f.ds);
    const ents    = entradasPorSemana[ds] ?? [];
    const entradas = ents.reduce((s, e) => s + e.cantidad, 0);
    const tipo    = ents[0]?.tipo ?? "";
    const fuente  = ents[0]?.fuente ?? "";
    const ss      = Math.round((f.yhat / 7) * ssDias);
    const stockIni = Math.round(stock);
    stock         = Math.max(0, stock + entradas - f.yhat);
    const stockFin = Math.round(stock);
    return {
      ds, stockIni, entradas: Math.round(entradas), tipo, fuente,
      ventas: Math.round(f.yhat), stockFin, ss,
      tienePendiente: false,  // se calcula fuera con el SKU correcto
      yhat_lower: Math.round(f.yhat_lower ?? f.yhat * 0.8),
      yhat_upper: Math.round(f.yhat_upper ?? f.yhat * 1.2),
    };
  });
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
export default function StockProyeccion() {
  const [skuList,    setSkuList]    = useState([]);
  const [params,     setParams]     = useState(PARAMS_FALLBACK);
  const [selSku,     setSelSku]     = useState("121010290");
  const [horizonte,  setHorizonte]  = useState(13);
  const [forecast,   setForecast]   = useState([]);
  const [ordenes,    setOrdenes]    = useState([]);
  const [stockReal,  setStockReal]  = useState(0);
  const [stockInfo,  setStockInfo]  = useState(null);
  const [loading,    setLoading]    = useState(false);
  const [ordenesAprobadas, setOrdenesAprobadas] = useState([]);
  const [error,      setError]      = useState("");

  // Cargar lista de SKUs y params al montar
  useEffect(() => {
    Promise.all([
      fetch(`${API}/plan/params`).then((r) => r.json()),
      fetch(`${API}/stock/summary`).then((r) => r.json()),
      fetch(`${API}/ordenes/aprobadas`).then((r) => r.json()),
    ])
      .then(([p, s, aprobadas]) => {
        setOrdenesAprobadas(Array.isArray(aprobadas) ? aprobadas : []);
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
          setSkuList(p.skus.map((sk) => ({ sku: sk.sku, desc: sk.descripcion, tipo: sk.tipo })));
        }
        if (s.disponible) setStockInfo(s);
      })
      .catch(() => {});
  }, []);

  // Cargar datos cuando cambia SKU u horizonte
  useEffect(() => {
    if (!selSku) return;
    setLoading(true);
    setError("");

    const hoy = new Date().toISOString().slice(0, 10);

    // Recargar aprobadas por si cambiaron
    fetch(`${API}/ordenes/aprobadas`).then((r) => r.json())
      .then((a) => setOrdenesAprobadas(Array.isArray(a) ? a : []))
      .catch(() => {});

    Promise.all([
      fetch(`${API}/forecast`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sku: selSku, periods: horizonte + 4 }),
      }).then((r) => { if (!r.ok) throw new Error(`Forecast error ${r.status}`); return r.json(); }),
      fetch(`${API}/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ horizonte_semanas: horizonte, skus: [selSku] }),
      }).then((r) => { if (!r.ok) throw new Error(`Plan error ${r.status}`); return r.json(); }),
    ])
      .then(([fc, plan]) => {
        if (fc.detail) throw new Error(String(fc.detail));
        const fcFuturo = (fc.forecast ?? []).filter((f) => f.ds >= hoy).slice(0, horizonte);
        setForecast(fcFuturo);
        setOrdenes(plan.ordenes ?? []);
        // Stock inicial desde motivo de primera orden del SKU
        const motivo = plan.ordenes?.[0]?.motivo ?? "";
        const m = motivo.match(/Stock:([\d.]+)/);
        setStockReal(m ? parseFloat(m[1]) : 0);
      })
      .catch((e) => setError(e.message ?? "Error cargando datos"))
      .finally(() => setLoading(false));
  }, [selSku, horizonte]);

  const p       = params[selSku] ?? {};
  const ssDias  = p.ss_dias ?? 10;
  const tipoC   = TIPO_COLOR[p.tipo] ?? TIPO_COLOR.PRODUCCION;

  // Órdenes aprobadas para este SKU
  const aprobSku = useMemo(
    () => ordenesAprobadas.filter(a => a.sku === selSku),
    [ordenesAprobadas, selSku]
  );

  const proyeccion = useMemo(() => {
    const semActualLocal = getSemanaActual();
    const rows = calcularProyeccion(forecast, ordenes, stockReal, ssDias, aprobSku);
    // Post-proceso: calcular tienePendiente filtrando por SKU correcto
    return rows.map(r => {
      const tienePendiente = ordenes.some(o => {
        if (o.sku !== selSku) return false;
        const dsN = fmtD(o.semana_necesidad);
        const dsE = fmtD(o.semana_emision);
        const aprobada = aprobSku.find(a => fmtD(a.semana_necesidad) === dsN);
        return dsN === r.ds && dsE <= semActualLocal && !aprobada;
      });
      return { ...r, tienePendiente };
    });
  }, [forecast, ordenes, stockReal, ssDias, aprobSku, selSku]);

  // n órdenes incluidas en proyección (aprobadas + futuras asumidas)
  const semActual = getSemanaActual();
  const nOrdenesProyeccion = useMemo(() => {
    return ordenes.filter(o => {
      const ds = fmtD(o.semana_necesidad);
      return aprobSku.find(a => fmtD(a.semana_necesidad) === ds) || ds > semActual;
    }).length;
  }, [ordenes, aprobSku, semActual]);

  // KPIs
  const totalVentas   = proyeccion.reduce((s, r) => s + r.ventas,   0);
  const totalEntradas = proyeccion.reduce((s, r) => s + r.entradas, 0);
  const minStock      = proyeccion.length ? Math.min(...proyeccion.map((r) => r.stockFin)) : 0;
  const semBajoSS     = proyeccion.filter((r) => r.stockFin < r.ss).length;
  const stockColor    = minStock < 0 ? C.red : semBajoSS > 0 ? C.amber : C.teal;

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

      {error && (
        <div style={{ background: C.redLt, border: `0.5px solid ${C.red}`, color: "#A32D2D",
          borderRadius: 7, padding: "8px 12px", fontSize: 12, marginBottom: 12 }}>
          {error}
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
          <select style={s.sel} value={horizonte} onChange={(e) => setHorizonte(Number(e.target.value))}>
            {[4, 8, 13, 17, 26].map((h) => (
              <option key={h} value={h}>{h} sem. (~{Math.round(h / 4.3)} meses)</option>
            ))}
          </select>
          {loading && <span style={{ fontSize: 12, color: C.textMuted }}>Cargando...</span>}
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
            {nOrdenesProyeccion === 0 && ordenes.length > 0 && (
              <span style={{ fontSize: 11, fontWeight: 400, color: C.amber, marginLeft: 10 }}>
                ⚡ {ordenes.length} órdenes sugeridas pendientes de aprobación — no se muestran en la proyección
              </span>
            )}
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
                  {["Semana", "Stock ini. (cj)", "Entradas (cj)", "Tipo", "Ventas FC (cj)",
                    "Stock fin. (cj)", "SS (cj)", "Cobertura", "Estado"].map((h, i) => (
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
                      <td style={{ ...s.td, textAlign: "right" }}>{fmtN(r.stockIni)}</td>
                      <td style={{ ...s.td, textAlign: "right", color: r.entradas > 0 ? (r.aprobada ? C.tealMid : C.amber) : C.textMuted, fontWeight: r.entradas > 0 ? 700 : 400 }}>
                        {r.entradas > 0 ? (
                          <span title={r.aprobada ? `Aprobada por ${r.responsable}` : "Sugerida por MRP — pendiente de aprobación"}>
                            {r.aprobada ? "✓ " : "~ "}{`+${fmtN(r.entradas)}`}
                          </span>
                        ) : "—"}
                      </td>
                      <td style={{ ...s.td, textAlign: "right" }}>
                        {tc ? (
                          <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:2}}>
                            <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 6px",
                              borderRadius: 4, background: tc.bg, color: tc.color }}>{r.tipo.slice(0,4)}</span>
                            {r.fuente === "aprobada" && <span style={{fontSize:9,color:C.tealMid}}>✓ aprobada</span>}
                            {r.fuente === "asumida"  && <span style={{fontSize:9,color:C.amber}}>asumida</span>}
                          </div>
                        ) : "—"}
                      </td>
                      <td style={{ ...s.td, textAlign: "right", color: C.red }}>
                        -{fmtN(r.ventas)}
                      </td>
                      <td style={{ ...s.td, textAlign: "right", fontWeight: 700,
                        color: negativo ? C.red : bajo ? C.amber : C.text }}>
                        {fmtN(r.stockFin)}
                      </td>
                      <td style={{ ...s.td, textAlign: "right", color: C.amber }}>{fmtN(r.ss)}</td>
                      <td style={{ ...s.td, textAlign: "right", color: cobDias < ssDias ? C.red : C.textMuted }}>
                        {cobDias >= 999 ? "—" : `${cobDias}d`}
                      </td>
                      <td style={{ ...s.td, textAlign: "right" }}>
                        {negativo
                          ? <span style={{ fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:10, background:C.redLt,   color:"#791F1F" }}>Rotura</span>
                          : bajo
                          ? <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:2}}>
                              <span style={{ fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:10, background:C.amberLt, color:"#854F0B" }}>Bajo SS</span>
                              {r.tienePendiente && (
                                <span style={{ fontSize:9, color:C.amber, whiteSpace:"nowrap" }}
                                  title="Hay una orden pendiente de aprobación que cubriría este período">
                                  ⚡ Aprobar orden
                                </span>
                              )}
                            </div>
                          : <span style={{ fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:10, background:C.tealLt,  color:C.tealMid }}>OK</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && !error && proyeccion.length === 0 && (
        <div style={{ ...s.card, textAlign: "center", color: C.textMuted, padding: 40 }}>
          Sin datos disponibles para este SKU — verifica que hay forecast entrenado
        </div>
      )}
    </div>
  );
}
