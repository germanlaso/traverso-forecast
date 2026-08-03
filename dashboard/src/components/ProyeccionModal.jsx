// ProyeccionModal.jsx — Modal con la proyección diaria de inventario de un SKU.
// Componente compartido: lo usan la pestaña Parámetros y Detalle Producción.
// Lee /plan/proyeccion_diaria_live/{sku}, el MISMO endpoint que la pestaña Stock
// Diario, de modo que los números coinciden exactamente con esa vista (incluye el
// recálculo reactivo con las OF aprobadas vigentes).
//
// Uso:
//   const [modal, setModal] = useState(null);        // {sku, descripcion} | null
//   {modal && <ProyeccionModal {...modal} onClose={() => setModal(null)} />}
//
// Navegación entre SKU (opcional): si se pasan `lista` (array {sku, descripcion}),
// `indice` (posición actual) y `onNavegar(nuevoIndice)`, el modal muestra los
// controles ◀ ▶ y responde a las flechas del teclado. Permite barrer los SKU de
// la tabla sin cerrar el modal. Si no se pasan, el modal funciona igual que antes.

import React, { useState, useEffect } from "react";
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ReferenceLine,
} from "recharts";
import { useCampanas, bandasCampana, renderBandas, NotaCampana } from "./campanaBandas";

const API = "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
  blue:    "#378ADD",
  // naranja dedicado a la OFT propuesta (amber ya se usa en la línea de SS)
  orange:  "#E8862B",
};

const fmtN = (n) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("es-CL"));
const fmt1 = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("es-CL", { maximumFractionDigits: 1 }));

const navBtn = {
  background: "rgba(255,255,255,.16)", border: "1px solid rgba(255,255,255,.35)",
  color: "#fff", borderRadius: 6, width: 26, height: 24, fontSize: 11,
  lineHeight: 1, display: "flex", alignItems: "center", justifyContent: "center",
};

/* Tooltip: agrega la LINEA de produccion a las series de OFT y OF aprobada.
   Un mismo dia puede tener produccion en dos lineas (el optimizer puede partir),
   por eso se lista cada una con su cantidad. */
function TooltipLineas({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload || {};
  const lineasDe = (arr, etiqueta) =>
    (arr || []).map((l, i) => (
      <div key={`${etiqueta}-${i}`} style={{ fontSize: 11, marginLeft: 8, color: C.textMuted }}>
        ↳ {l.linea}
        {l.preferida === true ? " (preferida)" : l.alternativa ? " (alternativa)" : ""}
        {" · "}{fmt1(l.cajas)} cj
        {l.numero_of ? ` · ${l.numero_of}` : ""}
      </div>
    ));
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.border}`, borderRadius: 8,
                  padding: "8px 10px", fontSize: 12, boxShadow: "0 2px 8px rgba(0,0,0,.12)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {/* Las lineas van INMEDIATAMENTE debajo de su serie, no al final, para que
          se lea "OFT propuesta: 213 cj / ↳ L1Pet (alternativa) · 213 cj". */}
      {payload.map((e) => (
        <React.Fragment key={e.dataKey}>
          <div style={{ color: e.color }}>
            {e.name}: {e.value == null ? "—" : `${fmt1(e.value)} cj`}
          </div>
          {e.dataKey === "oft" && lineasDe(p.oftLineas, "oft")}
          {e.dataKey === "aprobada" && lineasDe(p.aprobLineas, "apr")}
        </React.Fragment>
      ))}
      {/* Balance del dia: ini - demanda = disponible(+prod) = stock final */}
      <div style={{ borderTop: `0.5px solid ${C.border}`, margin: "5px 0" }} />
      {p.stock_ini != null && (
        <div style={{ color: C.text }}>Stock inicial: {fmt1(p.stock_ini)} cj</div>)}
      {p.demanda != null && (
        <div style={{ color: C.gray }}>− Demanda: {fmt1(-p.demanda)} cj</div>)}
      {p.stock_disp != null && (
        <div style={{ color: p.stock_disp < 0 ? C.red : C.purple, fontWeight: 600 }}>
          = Disponible: {fmt1(p.stock_disp)} cj{p.stock_disp < 0 ? " ⚠" : ""}</div>)}
      {((p.oft || 0) + (p.aprobada || 0)) > 0 && (
        <div style={{ color: C.orange }}>+ Produccion/entrada: {fmt1((p.oft || 0) + (p.aprobada || 0))} cj</div>)}
      {p.stock != null && (
        <div style={{ color: C.textMuted }}>= Stock final: {fmt1(p.stock)} cj</div>)}
    </div>
  );
}

function KPI({ label, value, color, sub, sub2, aviso }) {
  return (
    <div style={{ background: C.grayLt, borderRadius: 8, padding: "10px 14px", minWidth: 110 }}>
      <div style={{ fontSize: 10.5, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 700, color: color || C.text, marginTop: 2 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 10.5, color: aviso ? C.amber : C.textMuted, marginTop: 2 }}
             title={aviso || undefined}>
          {sub}{aviso ? " ⚠" : ""}
        </div>
      )}
      {sub2 && <div style={{ fontSize: 9.5, color: C.textMuted, marginTop: 1 }}>{sub2}</div>}
    </div>
  );
}

/* ── Modal: proyección diaria de inventario ───────────────────────────────
   Lee /plan/proyeccion_diaria_live/{sku} (el mismo endpoint de Stock Diario).
   Se abre bajo demanda: NO se carga al expandir la fila, para no disparar una
   consulta por cada SKU que el usuario abra.                                */
export default function ProyeccionModal({ sku, descripcion, onClose,
                                          lista, indice, onNavegar }) {
  const { reglas, cals, infoDe } = useCampanas();
  const [d, setD]   = useState(null);
  const [err, setErr] = useState("");
  const [cargando, setCargando] = useState(true);

  // ── Navegación entre SKU (opcional) ──────────────────────────────────────
  const hayNav = Array.isArray(lista) && lista.length > 1
                 && typeof onNavegar === "function" && Number.isInteger(indice);
  const hayPrev = hayNav && indice > 0;
  const haySig  = hayNav && indice < lista.length - 1;
  const irPrev = () => { if (hayPrev) onNavegar(indice - 1); };
  const irSig  = () => { if (haySig)  onNavegar(indice + 1); };

  useEffect(() => {
    const teclas = (e) => {
      if (e.key === "Escape") { onClose(); return; }
      if (!hayNav) return;
      if (e.key === "ArrowLeft"  && indice > 0)                { e.preventDefault(); onNavegar(indice - 1); }
      if (e.key === "ArrowRight" && indice < lista.length - 1) { e.preventDefault(); onNavegar(indice + 1); }
    };
    window.addEventListener("keydown", teclas);
    return () => window.removeEventListener("keydown", teclas);
  }, [onClose, hayNav, indice, lista, onNavegar]);

  useEffect(() => {
    if (!sku) return;
    setCargando(true);
    setErr("");
    fetch(`${API}/plan/proyeccion_diaria_live/${sku}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((j) => { setD(j); setErr(""); })
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setCargando(false));
  }, [sku]);

  const dias = d?.dias ?? [];
// (29-07-2026) PRODUCCIÓN EN EL GRÁFICO: dos series distintas, no una.
//   · oft_cj     = OFT PROPUESTA por el optimizador (aún sin aprobar) -> NARANJA.
//   · entrada_cj = OF / OFM ya APROBADA (entrada_aprobada_u del endpoint) -> VERDE.
// Al aprobar una OFT el optimizador deja de proponerla: `oft_cajas` pasa a null y la
// cantidad se mueve a `entrada_aprobada_u`. El gráfico dibujaba sólo `oft_cajas`, así
// que la barra DESAPARECÍA al aprobar aunque el balance de stock la siguiera contando.
// Lo APROBADO manda para el cálculo; lo propuesto queda como referencia visual (barra
// más tenue, con borde punteado).
  const serie = dias.map((x) => ({
    fecha: String(x.fecha).slice(5),          // MM-DD
    stock: x.stock_fin_cj,
    stock_disp: x.stock_disp_cj,
    stock_ini: x.stock_ini_disp_cj,
    ss: x.ss_u != null && d?.upc ? x.ss_u / d.upc : null,
    demanda: x.demanda_corr_cj,
    pedidos: x.pedidos_cj || 0,               // OV: faltaba en el modal
    oft: x.oft_cajas || 0,                    // propuesta (referencia)
    aprobada: x.entrada_aprobada_u && d?.upc ? x.entrada_aprobada_u / d.upc : 0,
    estado: x.estado,
    // (30-07) lineas del dia: el tooltip muestra en que linea se produce y si
    // es la preferida o una alternativa (traspaso de carga entre lineas).
    oftLineas: x.oft_lineas || [],
    aprobLineas: x.aprob_lineas || [],
  }));

  // Bandas de campaña (granel de planta y formato de linea), solo si la regla
  // afecta a este SKU.
  const bandas = bandasCampana({
    reglas, cals, info: infoDe(sku),
    puntos: dias.map((x) => ({ iso: String(x.fecha).slice(0, 10), eje: String(x.fecha).slice(5) })),
  });

  // Encabezado del plan: stock físico de apertura y lo comprometido por OV vencida.
  const enc      = d?.encabezado || {};
  const emp      = enc.por_empresa || {};
  const stockIni = enc.stock_fisico_cj;
  const compro   = enc.comprometido_cj;
  const dispIni  = enc.disponible_inicial_cj;
  const hayEmp   = (emp.T || 0) + (emp.M || 0) > 0;
  const avisoEmp = hayEmp && emp.cuadra === false
    ? "La apertura por empresa viene del stock actual y no coincide con el total del plan "
      + "(el stock se refrescó después de generarlo)."
    : null;

  const nQuiebre = dias.filter((x) => x.estado === "QUIEBRE").length;
  const nBajoSS  = dias.filter((x) => x.estado === "BAJO_SS").length;
  // cuenta días con producción de CUALQUIER origen: si todo está aprobado,
  // `oft_cajas` es null y el KPI mostraría 0 aunque haya producción planificada.
  const nOft     = dias.filter((x) => (x.oft_cajas || 0) > 0
                                   || (x.entrada_aprobada_u || 0) > 0).length;
  const stockMin = dias.length ? Math.min(...dias.map((x) => x.stock_disp_cj ?? 0)) : null;
  const stockFin = dias.length ? dias[dias.length - 1].stock_fin_cj : null;

  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(20,20,18,.45)", zIndex: 1000,
               display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", borderRadius: 12, width: "min(1080px, 96vw)",
                 maxHeight: "92vh", overflowY: "auto", boxShadow: "0 12px 40px rgba(0,0,0,.25)" }}>

        {/* Cabecera */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "13px 18px",
                      background: C.tealMid, color: "#fff", borderRadius: "12px 12px 0 0" }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14.5 }}>📊 {sku} — {descripcion}</div>
            <div style={{ fontSize: 11, opacity: .9 }}>
              Proyección diaria de inventario · plan vigente
              {d?.plan_id ? ` #${d.plan_id}` : ""}
            </div>
          </div>
          {hayNav && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginRight: 4 }}>
              <button onClick={irPrev} disabled={!hayPrev} title="SKU anterior (←)"
                style={{ ...navBtn, opacity: hayPrev ? 1 : .35,
                         cursor: hayPrev ? "pointer" : "default" }}>◀</button>
              <span style={{ fontSize: 11.5, opacity: .95, minWidth: 52, textAlign: "center",
                             fontVariantNumeric: "tabular-nums" }}>
                {indice + 1} / {lista.length}
              </span>
              <button onClick={irSig} disabled={!haySig} title="SKU siguiente (→)"
                style={{ ...navBtn, opacity: haySig ? 1 : .35,
                         cursor: haySig ? "pointer" : "default" }}>▶</button>
            </div>
          )}
          <button onClick={onClose} title="Cerrar (Esc)"
            style={{ background: "transparent", border: "none", color: "#fff", fontSize: 20,
                     cursor: "pointer", lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: 18 }}>
          {cargando && <div style={{ color: C.textMuted, padding: 30, textAlign: "center" }}>Cargando proyección…</div>}
          {err && (
            <div style={{ background: C.redLt, border: `1px solid ${C.red}`, borderRadius: 8,
                          padding: 12, color: "#791F1F", fontSize: 12.5 }}>
              No se pudo cargar la proyección: {err}
            </div>
          )}
          {!cargando && !err && d?.disponible === false && (
            <div style={{ background: C.amberLt, borderRadius: 8, padding: 12, fontSize: 12.5 }}>
              {d.mensaje || "No hay plan vigente."}
            </div>
          )}

          {!cargando && !err && serie.length > 0 && (
            <>
              {/* KPIs */}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                <KPI label="Stock inicial" value={`${fmtN(stockIni)} cj`}
                     sub={hayEmp ? `TRA ${fmt1(emp.T_cj)} · MON ${fmt1(emp.M_cj)}` : null}
                     aviso={avisoEmp}
                     sub2={compro > 0 ? `disponible ${fmt1(dispIni)} cj` : null} />
                <KPI label="Comprometido" value={`${fmtN(compro)} cj`}
                     color={compro > 0 ? C.amber : C.text}
                     sub="OV vencidas" />
                <KPI label="Stock final" value={`${fmtN(stockFin)} cj`} />
                <KPI label="Stock mínimo" value={`${fmtN(stockMin)} cj`}
                     color={stockMin < 0 ? C.red : stockMin === 0 ? C.amber : C.text} />
                <KPI label="Días en quiebre" value={nQuiebre} color={nQuiebre ? C.red : C.teal} />
                <KPI label="Días bajo SS" value={nBajoSS} color={nBajoSS ? C.amber : C.teal} />
                <KPI label="Días con producción" value={nOft} sub={`${dias.length} días`} />
              </div>

              {/* Gráfico */}
              <div style={{ height: 330 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={serie} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                    {renderBandas(bandas)}
                    <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} />
                    <XAxis dataKey="fecha" tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: C.textMuted }}
                           tickFormatter={(v) => v.toLocaleString("es-CL")} />
                    <Tooltip content={<TooltipLineas />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke={C.red} strokeWidth={1} />
                    <Bar dataKey="oft" name="OFT propuesta" fill={C.orange} fillOpacity={0.35}
                         stroke={C.orange} strokeDasharray="3 2" barSize={10} />
                    <Bar dataKey="aprobada" name="OF aprobada / OFM" fill={C.teal} fillOpacity={0.75}
                         stroke={C.tealMid} barSize={10} />
                    <Bar dataKey="demanda" name="Demanda" fill="#B85C5C" fillOpacity={0.42}
                         barSize={5} />
                    <Bar dataKey="pedidos" name="Pedidos (OV)" fill={C.purple} fillOpacity={0.65}
                         barSize={5} />
                    <Line type="monotone" dataKey="stock_disp" name="Stock disponible" stroke={C.purple}
                          strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="ss" name="Stock seguridad" stroke={C.amber}
                          strokeWidth={1.5} strokeDasharray="5 4" dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              <NotaCampana hayBandas={bandas.length > 0} />

              <div style={{ fontSize: 10.5, color: C.textMuted, marginTop: 8 }}>
                Mismos datos que la pestaña Stock Diario (endpoint reactivo: recalcula el balance
                con las OF aprobadas vigentes). Valores en cajas.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
