// MiniStock.jsx — Gráfico compacto de stock diario para embeber en modales.
// Ubicación: dashboard/src/components/MiniStock.jsx
//
// Por qué un componente aparte y no ProyeccionModal: ProyeccionModal es un modal
// completo (overlay + KPIs + bandas de campaña + tooltip detallado) y no se puede
// anidar dentro de otro modal. Este es solo la curva, con lo mínimo que el
// operador necesita para decidir CANTIDAD y FECHA sin cambiar de pantalla.
//
// Usa el MISMO endpoint que Stock Diario y ProyeccionModal
// (/plan/proyeccion_diaria_live/{sku}), así que no introduce otra fuente de
// verdad: el backend calcula, el front sólo dibuja.
//
// Aporte clave sobre el gráfico grande: marca con una línea vertical la FECHA
// que el operador está eligiendo en el formulario, de modo que se vea si la
// entrada llega antes o después del quiebre.

import { useEffect, useState } from "react";
import axios from "axios";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

const API = "";
const C = {
  teal: "#1D9E75", amber: "#EF9F27", red: "#E24B4A", blue: "#3B6FD4",
  purple: "#6D4AC4", grayMid: "#D3D1C7", textMuted: "#888780", text: "#2C2C2A",
};

const fmt = (n) => (n == null ? "—" : Math.round(n).toLocaleString("es-CL"));

function TT({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload || {};
  const row = (k, v, col, bold) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 14, color: col || C.text,
                  fontWeight: bold ? 600 : 400 }}>
      <span>{k}</span><span>{fmt(v)}</span>
    </div>
  );
  return (
    <div style={{ background: "#fff", border: `0.5px solid ${C.grayMid}`, borderRadius: 7,
                  padding: "8px 11px", fontSize: 11.5, boxShadow: "0 4px 14px rgba(0,0,0,.1)" }}>
      <div style={{ fontWeight: 700, marginBottom: 5 }}>{label}</div>
      {p.stock_ini != null && row("Stock inicial", p.stock_ini)}
      {p.demanda != null && row("− Demanda", -p.demanda, C.textMuted)}
      {p.stock_disp != null && row(
        p.stock_disp < 0 ? "= Disponible ⚠" : "= Disponible",
        p.stock_disp, p.stock_disp < 0 ? C.red : C.blue, true)}
      {p.prod > 0 && row("+ Producción", p.prod, C.amber)}
      {p.stock != null && row("= Stock final", p.stock, C.textMuted)}
      {p.ss > 0 && row("Stock seguridad", p.ss, C.amber)}
    </div>
  );
}

/**
 * @param sku          SKU a graficar
 * @param fechaFoco    "YYYY-MM-DD" a marcar con línea vertical (la que el
 *                     operador está eligiendo). Opcional.
 * @param labelFoco    texto de la marca (ej. "entrada")
 * @param alto         altura del gráfico en px (default 180)
 */
export default function MiniStock({ sku, fechaFoco, labelFoco = "entrada", alto = 180 }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    if (!sku) { setD(null); setCargando(false); return; }
    let vivo = true;
    setCargando(true);
    axios.get(`${API}/plan/proyeccion_diaria_live/${sku}`)
      .then((r) => { if (vivo) { setD(r.data); setErr(null); } })
      .catch((e) => { if (vivo) setErr(e?.message || "error"); })
      .finally(() => { if (vivo) setCargando(false); });
    return () => { vivo = false; };
  }, [sku]);

  if (!sku) return null;
  if (cargando) return <Caja><span style={{ color: C.textMuted }}>Cargando stock…</span></Caja>;
  if (err) return <Caja><span style={{ color: C.red }}>No se pudo cargar el stock ({err})</span></Caja>;

  const dias = d?.dias ?? [];
  if (!dias.length) return <Caja><span style={{ color: C.textMuted }}>Sin proyección para este SKU</span></Caja>;

  const upc = d?.upc || 1;
  const serie = dias.map((x) => ({
    iso: String(x.fecha).slice(0, 10),
    fecha: String(x.fecha).slice(5),
    stock: x.stock_fin_cj,
    stock_disp: x.stock_disp_cj,
    stock_ini: x.stock_ini_disp_cj,
    ss: x.ss_u != null ? x.ss_u / upc : null,
    demanda: x.demanda_corr_cj,
    prod: (x.oft_cajas || 0) + (x.entrada_aprobada_u ? x.entrada_aprobada_u / upc : 0),
  }));

  // KPIs mínimos: el piso del horizonte y cuántos días quedan en quiebre.
  const minDisp = Math.min(...serie.map((x) => x.stock_disp ?? 0));
  const nQuiebre = serie.filter((x) => (x.stock_disp ?? 0) < 0).length;
  const focoEje = fechaFoco
    ? (serie.find((x) => x.iso === String(fechaFoco).slice(0, 10))?.fecha ?? null)
    : null;

  return (
    <div style={{ border: `0.5px solid ${C.grayMid}`, borderRadius: 8, padding: "9px 11px 4px",
                  background: "#fff", marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                    marginBottom: 6, fontSize: 10.5, color: C.textMuted }}>
        <span>Stock proyectado (cajas) · <b style={{ color: C.text }}>{sku}</b></span>
        <span>
          piso <b style={{ color: minDisp < 0 ? C.red : C.text }}>{fmt(minDisp)}</b>
          {nQuiebre > 0 && (
            <span style={{ color: C.red, fontWeight: 600 }}> · {nQuiebre} d en quiebre</span>
          )}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={alto}>
        <ComposedChart data={serie} margin={{ top: 4, right: 6, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="#EFEDE6" />
          <XAxis dataKey="fecha" tick={{ fontSize: 9, fill: C.textMuted }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 9, fill: C.textMuted }} width={44} />
          <Tooltip content={<TT />} />
          <ReferenceLine y={0} stroke={C.red} strokeWidth={1} />
          {focoEje && (
            <ReferenceLine x={focoEje} stroke={C.purple} strokeWidth={1.5} strokeDasharray="4 3"
              label={{ value: labelFoco, position: "top", fontSize: 9.5, fill: C.purple }} />
          )}
          <Bar dataKey="demanda" name="Demanda" fill={C.grayMid} barSize={5} />
          <Bar dataKey="prod" name="Producción" fill={C.amber} barSize={5} />
          <Line type="monotone" dataKey="ss" name="SS" stroke={C.amber} strokeWidth={1}
                strokeDasharray="4 3" dot={false} />
          <Line type="monotone" dataKey="stock_disp" name="Stock disponible" stroke={C.blue}
                strokeWidth={1.8} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 12, fontSize: 9.5, color: C.textMuted, paddingBottom: 4 }}>
        <Lg c={C.blue} t="Stock disponible" />
        <Lg c={C.amber} t="SS" />
        <Lg c={C.amber} t="Producción" />
        <Lg c={C.grayMid} t="Demanda" />
      </div>
    </div>
  );
}

function Lg({ c, t }) {
  return (
    <span>
      <i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2,
                  background: c, marginRight: 4 }} />
      {t}
    </span>
  );
}

function Caja({ children }) {
  return (
    <div style={{ border: `0.5px solid ${C.grayMid}`, borderRadius: 8, padding: "14px 11px",
                  background: "#fff", marginBottom: 12, fontSize: 11.5, textAlign: "center" }}>
      {children}
    </div>
  );
}
