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
// Dos aportes sobre el gráfico grande:
//  1. Marca con una línea vertical la FECHA que el operador está eligiendo.
//  2. SIMULACIÓN en vivo (prop `simular`): dibuja una segunda curva punteada con
//     el efecto de la cantidad y fecha que se están tipeando, y compara el piso y
//     los días en quiebre contra el plan actual.
//
// Sobre la simulación y el principio "el stock lo calcula el backend": la curva
// del backend se dibuja SIEMPRE y sin tocar. La simulada es un desplazamiento
// vertical desde la fecha de entrada hacia adelante — aritmética de arrastre, no
// lógica de negocio — y se muestra punteada y rotulada como proyección del
// formulario, no como verdad. No sustituye el recálculo del backend, que llega
// cuando la OF se guarda.
//
// LIMITACIÓN conocida: la simulación ignora cap_bodega y los mínimos de lote, así
// que puede mostrar un stock que el optimizador no permitiría. Sirve para decidir
// cantidad y fecha, no para validar factibilidad.

import { useEffect, useState } from "react";
import axios from "axios";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";

const API = process.env.REACT_APP_API_BASE || "";
const C = {
  teal: "#1D9E75", amber: "#EF9F27", red: "#E24B4A", blue: "#3B6FD4",
  purple: "#6D4AC4", orange: "#E8862B", grayMid: "#D3D1C7", textMuted: "#888780", text: "#2C2C2A",
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
      {p.oft > 0 && row("+ OFT propuesta", p.oft, C.orange)}
      {p.aprobada > 0 && row("+ OF aprobada / OFM", p.aprobada, C.teal)}
      {p.pedidos > 0 && row("Pedidos (OV)", p.pedidos, C.purple)}
      {p.stock != null && row("= Stock final", p.stock, C.textMuted)}
      {p.ss > 0 && row("Stock seguridad", p.ss, C.amber)}
      {p.sim_disp != null && (
        <div style={{ borderTop: `0.5px solid ${C.grayMid}`, marginTop: 4, paddingTop: 4 }}>
          {row("Con tu cambio", p.sim_disp, p.sim_disp < 0 ? C.red : C.purple, true)}
        </div>
      )}
    </div>
  );
}

/**
 * @param sku          SKU a graficar
 * @param fechaFoco    "YYYY-MM-DD" a marcar con línea vertical (la que el
 *                     operador está eligiendo). Opcional.
 * @param labelFoco    texto de la marca (ej. "entrada")
 * @param alto         altura del gráfico en px (default 180)
 * @param simular      { fecha, cantidadCj, fechaOriginal, reemplazaCj } | null
 *                     fecha/cantidadCj: lo que el operador está ingresando (la
 *                     fecha es la de ENTRADA al stock, no la de lanzamiento).
 *                     fechaOriginal/reemplazaCj: la OF que este cambio REEMPLAZA
 *                     y que ya viene incluida en la curva del backend (la OFT
 *                     propuesta al aprobar, o la aprobación previa al editar).
 *                     En creación se omiten, porque no hay nada que reemplazar.
 */
export default function MiniStock({ sku, fechaFoco, labelFoco = "entrada", alto = 180,
                                    simular = null }) {
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
    // (06-08) Separadas como en ProyeccionModal: OFT propuesta (naranja),
    // OF/OFM aprobada (teal) y OV (purpura). Antes iban sumadas en `prod`.
    oft: x.oft_cajas || 0,
    aprobada: x.entrada_aprobada_u ? x.entrada_aprobada_u / upc : 0,
    pedidos: x.pedidos_cj || 0,
    // (11-08-2026) Entrada que el plan NO cuenta (recepción de hoy o pasada). Se usa
    // abajo para no descontar dos veces en la simulación.
    pendiente: x.entrada_pendiente_u ? x.entrada_pendiente_u / upc : 0,
  }));

  // ── Simulación: desplazamiento vertical desde la fecha de entrada ──────────
  // La producción está disponible EN la fecha de entrada, así que el ajuste
  // aplica desde ese día INCLUSIVE. Se resta primero lo que el cambio reemplaza
  // (si ya está en la curva) y se suma la cantidad nueva.
  const iso10 = (x) => (x ? String(x).slice(0, 10) : null);
  const simFecha = iso10(simular?.fecha);
  const simCant = Number(simular?.cantidadCj) || 0;
  const simFechaOrig = iso10(simular?.fechaOriginal);
  const simReemp = Number(simular?.reemplazaCj) || 0;
  const haySim = !!(simular && (simCant > 0 || simReemp > 0)
                    && (simFecha !== simFechaOrig || simCant !== simReemp));

  if (haySim) {
    const ajuste = {};
    // (11-08-2026) OJO: `reemplazaCj` se resta porque se asume que esa OF YA está en
    // la curva del backend. Desde que el endpoint aplica la regla del plan
    // (`fer > hoy`), una OF con recepción HOY quedó FUERA de la curva — restarla
    // descontaría cajas que nunca se sumaron y el piso simulado saldría demasiado
    // bajo. Si la fecha original tiene entrada pendiente, no hay nada que restar.
    const origExcluida = simFechaOrig
      ? (serie.find((x) => x.iso === simFechaOrig)?.pendiente || 0) > 0
      : false;
    if (simFechaOrig && simReemp && !origExcluida) ajuste[simFechaOrig] = (ajuste[simFechaOrig] || 0) - simReemp;
    if (simFecha && simCant) ajuste[simFecha] = (ajuste[simFecha] || 0) + simCant;
    let acum = 0;
    serie.forEach((x) => {
      acum += ajuste[x.iso] || 0;
      x.sim_disp = (x.stock_disp ?? 0) + acum;
      x.sim_delta = acum;
    });
  }

  // KPIs mínimos: el piso del horizonte y cuántos días quedan en quiebre.
  const minDisp = Math.min(...serie.map((x) => x.stock_disp ?? 0));
  const nQuiebre = serie.filter((x) => (x.stock_disp ?? 0) < 0).length;
  const minSim = haySim ? Math.min(...serie.map((x) => x.sim_disp ?? 0)) : null;
  const nQuiebreSim = haySim ? serie.filter((x) => (x.sim_disp ?? 0) < 0).length : null;
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
          {haySim && (
            <>
              {" \u2192 "}
              <b style={{ color: minSim < 0 ? C.red : C.teal }}>{fmt(minSim)}</b>
            </>
          )}
          {" · "}
          <b style={{ color: nQuiebre > 0 ? C.red : C.text }}>{nQuiebre}</b>
          {haySim && (
            <>
              {"\u2192"}
              <b style={{ color: nQuiebreSim > 0 ? C.red : C.teal }}>{nQuiebreSim}</b>
            </>
          )}
          {" d en quiebre"}
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
          <Bar dataKey="demanda" name="Demanda" fill={C.grayMid} barSize={4} />
          <Bar dataKey="pedidos" name="Pedidos (OV)" fill={C.purple} fillOpacity={0.65} barSize={4} />
          <Bar dataKey="oft" name="OFT propuesta" fill={C.orange} fillOpacity={0.4} barSize={4} />
          <Bar dataKey="aprobada" name="OF aprobada / OFM" fill={C.teal} fillOpacity={0.8} barSize={4} />
          <Line type="monotone" dataKey="ss" name="SS" stroke={C.amber} strokeWidth={1}
                strokeDasharray="4 3" dot={false} />
          <Line type="monotone" dataKey="stock_disp" name="Stock disponible" stroke={C.blue}
                strokeWidth={1.8} dot={false} />
          {haySim && (
            <Line type="monotone" dataKey="sim_disp" name="Con tu cambio" stroke={C.purple}
                  strokeWidth={2} strokeDasharray="5 3" dot={false} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 12, fontSize: 9.5, color: C.textMuted, paddingBottom: 4 }}>
        <Lg c={C.blue} t="Stock disponible" />
        {haySim && <Lg c={C.purple} t="Con tu cambio (simulado)" />}
        <Lg c={C.amber} t="SS" />
        <Lg c={C.orange} t="OFT propuesta" />
        <Lg c={C.teal} t="OF aprobada" />
        <Lg c={C.purple} t="OV" />
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
