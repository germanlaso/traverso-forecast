// ParametrosDiagnostico.jsx — Diagnóstico de parámetros MRP (línea / SKU)
// FASE 1: SOLO LECTURA. No modifica ningún parámetro.
// Estructura preparada para la Fase 2 (edición): el componente <Param> centraliza
// el render de cada valor; cuando llegue la edición, solo cambia ese componente.
// Los indicadores y semáforos los calcula el BACKEND (params_diagnostico.py), para
// que la validación del futuro formulario no pueda divergir del diagnóstico.

import React, { useState, useEffect, useMemo } from "react";
import ProyeccionModal from "./ProyeccionModal";

const API = process.env.REACT_APP_API_BASE || "";

const C = {
  teal:    "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  purple:  "#534AB7", purpleLt:"#EEEDFE",
  amber:   "#EF9F27", amberLt: "#FAEEDA",
  red:     "#E24B4A", redLt:   "#FCEBEB",
  gray:    "#5F5E5A", grayLt:  "#F1EFE8",
  border:  "#D3D1C7", text:    "#2C2C2A", textMuted: "#888780",
};

const fmtN  = (n) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("es-CL"));
const fmt1  = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("es-CL", { maximumFractionDigits: 1 }));

const NIVEL_COLOR = { error: C.red, warn: C.amber, info: C.gray };
const NIVEL_BG    = { error: C.redLt, warn: C.amberLt, info: C.grayLt };

// Etiquetas cortas para los chips de filtro
const ALERTA_LABEL = {
  BATCH_NO_CABE_DIA:       "Batch no cabe en el día",
  BATCH_NO_CABE_TURNO:     "Batch no cabe en un turno",
  CAP_BODEGA_INSUFICIENTE: "Bodega insuficiente",
  VELOCIDAD_CERO:          "Velocidad 0",
  SKU_SIN_PARAMS:          "SKU sin parámetros",
  SKU_INACTIVO:            "SKU inactivo",
  MARGEN_DIA_AJUSTADO:     "Margen diario ajustado",
  BATCH_NO_MULTIPLO:       "Batch no múltiplo",
  SOBRESTOCK:              "Sobrestock",
  MTO_CON_SS:              "MTO con SS",
  FACTOR_REDUCIDO:         "Factor reducido",
  SIN_FORECAST:            "Sin forecast",
  SIN_LINEA:               "Sin línea",
};

const s = {
  card:  { background: "#fff", border: `1px solid ${C.border}`, borderRadius: 10, marginBottom: 10, overflow: "hidden" },
  th:    { padding: "7px 10px", fontSize: 10.5, fontWeight: 700, color: C.textMuted, textTransform: "uppercase",
           letterSpacing: .3, borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap", background: "#FBFAF7" },
  td:    { padding: "6px 10px", fontSize: 12, borderBottom: `1px solid ${C.grayLt}`, whiteSpace: "nowrap" },
  pill:  (bg, col) => ({ display: "inline-block", fontSize: 10, fontWeight: 700, padding: "2px 7px",
           borderRadius: 10, background: bg, color: col, whiteSpace: "nowrap" }),
};

/* ── <Param>: punto único de render de un parámetro ────────────────────────
   Hoy renderiza texto. En Fase 2 recibirá `editable` y se convertirá en input,
   sin tocar el resto de la vista.                                            */
function Param({ value, sufijo, titulo, fuerte }) {
  return (
    <span title={titulo} style={{ fontWeight: fuerte ? 700 : 400 }}>
      {value}{sufijo ? <span style={{ color: C.textMuted, fontSize: 10 }}> {sufijo}</span> : null}
    </span>
  );
}

function BarraCarga({ pct, cautivaPct, flexiblePct }) {
  if (pct === null || pct === undefined) return <span style={{ color: C.textMuted, fontSize: 11 }}>s/d</span>;
  const ESCALA = 130;
  const col = pct > 100 ? C.red : pct > 85 ? C.amber : C.teal;
  const wCau = Math.max(0, Math.min(cautivaPct ?? pct, ESCALA)) / ESCALA * 100;
  const wFle = Math.max(0, Math.min(flexiblePct ?? 0, ESCALA)) / ESCALA * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 150 }}
         title={cautivaPct != null
           ? `Cautiva ${fmt1(cautivaPct)}% (no se puede mover) · Flexible ${fmt1(flexiblePct)}% (SKU con línea alternativa)`
           : undefined}>
      <div style={{ flex: 1, height: 8, background: C.grayLt, borderRadius: 4,
                    overflow: "hidden", minWidth: 80, display: "flex", position: "relative" }}>
        <div style={{ width: `${wCau}%`, height: "100%", background: col }} />
        <div style={{ width: `${wFle}%`, height: "100%", background: col, opacity: .38 }} />
        {/* marca del 100% */}
        <div style={{ position: "absolute", left: `${100 / ESCALA * 100}%`, top: 0, bottom: 0,
                      width: 1, background: C.text, opacity: .35 }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color: col, width: 44, textAlign: "right" }}>
        {fmt1(pct)}%
      </span>
    </div>
  );
}

function KPI({ label, value, color, sub }) {
  return (
    <div style={{ background: C.grayLt, borderRadius: 8, padding: "10px 14px", minWidth: 110 }}>
      <div style={{ fontSize: 10.5, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3 }}>{label}</div>
      <div style={{ fontSize: 21, fontWeight: 700, color: color || C.text, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: C.textMuted, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* Dato del panel de detalle: muestra el valor en unidades Y cajas a la vez. */
function Dato({ label, u, cj, texto, sufijo, resaltar }) {
  const hay = (v) => v !== null && v !== undefined;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "3px 0",
                  borderBottom: `1px dashed ${C.grayLt}` }}>
      <span style={{ fontSize: 11, color: C.textMuted }}>{label}</span>
      <span style={{ fontSize: 11.5, fontWeight: resaltar ? 700 : 500, color: resaltar ? C.amber : C.text,
                     textAlign: "right", whiteSpace: "nowrap" }}>
        {texto !== undefined ? texto : (
          <>
            {hay(u) ? fmtN(u) : "—"}<span style={{ color: C.textMuted, fontSize: 10 }}> u</span>
            {hay(cj) && <> · {fmt1(cj)}<span style={{ color: C.textMuted, fontSize: 10 }}> cj</span></>}
          </>
        )}
        {sufijo ? <span style={{ color: C.textMuted, fontSize: 10 }}> {sufijo}</span> : null}
      </span>
    </div>
  );
}

function Grupo({ titulo, children }) {
  return (
    <div style={{ flex: "1 1 230px", minWidth: 215 }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, color: C.tealMid, textTransform: "uppercase",
                    letterSpacing: .3, marginBottom: 4 }}>{titulo}</div>
      {children}
    </div>
  );
}

function DetalleSku({ it, onVerProyeccion }) {
  const d = it.derivados || {};
  const pp = it.params_producto || {};
  const pl = it.params_en_linea || {};
  return (
    <div style={{ padding: "12px 16px 14px 34px", background: "#FBFAF7",
                  borderBottom: `1px solid ${C.border}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{it.descripcion}</div>
        <button onClick={(e) => { e.stopPropagation(); onVerProyeccion(); }}
          style={{ padding: "4px 10px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                   border: `1px solid ${C.purple}`, background: C.purpleLt, color: C.purple,
                   fontWeight: 600 }}>
          📊 Ver proyección diaria
        </button>
      </div>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>

        <Grupo titulo="Parámetros del producto">
          <Dato label="Batch mínimo"   u={d.batch_min_u}  cj={d.batch_min_cj} />
          <Dato label="Múltiplo batch" u={d.batch_mult_u} cj={d.batch_mult_cj} />
          <Dato label="Cap. bodega"    u={d.cap_bodega_u} cj={d.cap_bodega_cj}
                texto={d.cap_bodega_u == null ? "sin límite" : undefined} />
          <Dato label="Unidades/caja"  texto={String(d.u_por_caja ?? pp.u_por_caja ?? "—")} />
          <Dato label="Stock seguridad" texto={`${d.ss_dias ?? pp.ss_dias ?? "—"} días`} />
          <Dato label="Lead time"      texto={`${d.lead_time_sem ?? pp.lead_time_sem ?? "—"} sem`} />
          <Dato label="Tipo"           texto={d.mto ? "MTO (contra pedido)" : "MTS (a stock)"} />
          <div style={{ fontSize: 9.5, color: C.textMuted, marginTop: 3 }}>
            Globales del SKU: aplican en todas sus líneas.
          </div>
        </Grupo>

        <Grupo titulo="En esta línea">
          <Dato label="Asignación"      texto={it.preferida ? "Preferida" : "Alternativa"} />
          <Dato label="Factor velocidad" texto={String(pl.factor_velocidad ?? "—")}
                resaltar={pl.factor_velocidad < 1} />
          <Dato label="Vel. efectiva"   texto={`${fmtN(d.vel_efectiva_u_hr)} u/hr`} />
          <Dato label="T. cambio"       texto={`${fmt1(pl.t_cambio_hrs ?? d.t_cambio_hrs)} h`} />
          <Dato label="Lotes por semana" texto={d.lotes_sem == null ? "—" : fmt1(d.lotes_sem)} />
          <Dato label="Días de máquina/sem"
                texto={d.dias_prod_sem == null ? "—" : `${fmt1(d.dias_prod_sem)} d`} />
          {(it.alternativas || []).length === 0 && (
            <div style={{ fontSize: 9.5, color: C.textMuted, marginTop: 3 }}>
              Sin línea alternativa: esta carga es cautiva.
            </div>
          )}
        </Grupo>

        <Grupo titulo="Capacidad efectiva">
          <Dato label="Por turno"  u={d.cap_turno_u} cj={d.cap_turno_cj} />
          <Dato label="Por día"    u={d.cap_dia_u}   cj={d.cap_dia_cj} />
          <Dato label="Por semana" u={d.cap_sem_u}   cj={d.cap_sem_cj} />
          <Dato label="Horas por batch" texto={d.horas_por_batch == null ? "—" : `${fmt1(d.horas_por_batch)} h`} />
          <Dato label="% del día por batch"
                texto={d.pct_dia_por_batch == null ? "—" : `${fmt1(d.pct_dia_por_batch)} %`}
                resaltar={d.pct_dia_por_batch > 90} />
        </Grupo>

        <Grupo titulo="Demanda (plan vigente)">
          <Dato label="Forecast semanal" u={d.forecast_sem_u}    cj={d.forecast_sem_cj} />
          <Dato label="Forecast diario"  u={d.forecast_diario_u} cj={d.forecast_diario_cj} />
          <Dato label="Cobertura del batch"
                texto={d.dias_cobertura_batch == null ? "sin forecast"
                       : `${fmt1(d.dias_cobertura_batch)} días (${fmt1(d.semanas_cobertura_batch)} sem)`}
                resaltar={d.dias_cobertura_batch > 30} />
          <Dato label="Bodega / batch"
                texto={d.ratio_cap_bodega == null ? "—" : `${fmt1(d.ratio_cap_bodega)}×`}
                resaltar={d.ratio_cap_bodega != null && d.ratio_cap_bodega < 2} />
          <div style={{ fontSize: 9.5, color: C.textMuted, marginTop: 3 }}>
            Promedio de las próximas 4 semanas completas; diario = semanal ÷ 5.
          </div>
        </Grupo>
      </div>

      {(it.alternativas || []).length > 0 && (
        <div style={{ marginTop: 10, padding: "8px 10px", background: "#fff",
                      border: `1px solid ${C.border}`, borderRadius: 8 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: C.purple, textTransform: "uppercase",
                        letterSpacing: .3, marginBottom: 5 }}>
            Líneas alternativas
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr>{["Línea", "Costaría", "Carga actual", "Holgura", "¿Absorbe?"].map((h, i) => (
                <th key={h} style={{ padding: "2px 12px 4px 0", textAlign: i === 0 ? "left" : "right",
                                     color: C.textMuted, fontSize: 10, fontWeight: 600 }}>{h}</th>))}</tr>
            </thead>
            <tbody>
              {it.alternativas.map((a) => (
                <tr key={a.linea}>
                  <td style={{ padding: "2px 12px 2px 0", fontWeight: 600 }}>{a.linea}</td>
                  <td style={{ padding: "2px 12px 2px 0", textAlign: "right" }}>
                    {a.dias_prod_sem == null ? "—" : `${fmt1(a.dias_prod_sem)} d`}
                  </td>
                  <td style={{ padding: "2px 12px 2px 0", textAlign: "right",
                               color: a.carga_pct > 100 ? C.red : a.carga_pct > 85 ? C.amber : C.text }}>
                    {fmt1(a.carga_pct)}%
                  </td>
                  <td style={{ padding: "2px 12px 2px 0", textAlign: "right", color: C.textMuted }}>
                    {a.holgura_dias == null ? "—" : `${fmt1(a.holgura_dias)} d`}
                  </td>
                  <td style={{ padding: "2px 0", textAlign: "right" }}>
                    <span style={s.pill(a.absorbe ? C.tealLt : C.redLt, a.absorbe ? C.tealMid : C.red)}>
                      {a.absorbe ? "Sí" : "No"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 9.5, color: C.textMuted, marginTop: 4 }}>
            "Costaría" son los días de máquina en esa línea (dependen de su velocidad y factor).
            "Absorbe" = la holgura de esa línea alcanza para tomar toda la demanda de este SKU.
          </div>
        </div>
      )}

      {(it.alertas || []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          {it.alertas.map((a, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 4 }}>
              <span style={{ ...s.pill(NIVEL_BG[a.nivel], NIVEL_COLOR[a.nivel]), flexShrink: 0 }}>
                {ALERTA_LABEL[a.codigo] || a.codigo}
              </span>
              <span style={{ fontSize: 11.5, color: C.text }}>{a.mensaje}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ParametrosDiagnostico() {
  const [data, setData]       = useState(null);
  const [cargando, setCargando] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [unidad, setUnidad]   = useState("u");        // 'u' | 'cj'
  const [abierta, setAbierta] = useState({});          // {codigo: true}
  const [skuAbierto, setSkuAbierto] = useState({});    // {"linea|sku": true}
  const [modal, setModal] = useState(null);            // {sku, descripcion, lista, indice} | null

  // Abre el modal de proyección recordando la lista visible de la línea, para
  // poder avanzar al SKU siguiente sin cerrar (revisión rápida de proyecciones).
  const abrirProyeccion = (items, idx) => setModal({
    sku: items[idx].sku, descripcion: items[idx].descripcion,
    lista: items.map((x) => ({ sku: x.sku, descripcion: x.descripcion })),
    indice: idx,
  });
  const navegarProyeccion = (i) => setModal((m) => {
    if (!m?.lista || i < 0 || i >= m.lista.length) return m;
    return { ...m, sku: m.lista[i].sku, descripcion: m.lista[i].descripcion, indice: i };
  });
  const [filtro, setFiltro]   = useState("todos");     // todos | alertas | errores
  const [ocultos, setOcultos] = useState({});          // {codigoAlerta: true} -> chip apagado

  useEffect(() => {
    setCargando(true);
    fetch(`${API}/params/diagnostico`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => { setData(d); setErrorMsg(""); })
      .catch((e) => setErrorMsg(String(e.message || e)))
      .finally(() => setCargando(false));
  }, []);

  // conteo de alertas por tipo (para los chips)
  const tiposAlerta = useMemo(() => {
    if (!data) return [];
    const c = {};
    (data.lineas || []).forEach((l) => (l.skus || []).forEach((it) =>
      (it.alertas || []).forEach((a) => { c[a.codigo] = c[a.codigo] || { n: 0, nivel: a.nivel }; c[a.codigo].n += 1; })));
    return Object.entries(c).sort((a, b) => b[1].n - a[1].n);
  }, [data]);

  const visible = (a) => !ocultos[a.codigo];

  // aplica filtros a los SKU de una línea
  const skusFiltrados = (linea) => (linea.skus || []).filter((it) => {
    const al = (it.alertas || []).filter(visible);
    if (filtro === "errores") return al.some((a) => a.nivel === "error");
    if (filtro === "alertas") return al.some((a) => a.nivel === "error" || a.nivel === "warn");
    return true;
  });

  if (cargando) return <div style={{ padding: 24, color: C.textMuted }}>Cargando diagnóstico de parámetros…</div>;
  if (errorMsg) return (
    <div style={{ padding: 24 }}>
      <div style={{ background: C.redLt, border: `1px solid ${C.red}`, borderRadius: 8, padding: 14, color: "#791F1F" }}>
        No se pudo cargar el diagnóstico: {errorMsg}
      </div>
    </div>
  );
  if (!data) return null;

  const r = data.resumen || {};
  const sobrecargadas = (data.lineas || []).filter((l) => (l.derivados?.carga_pct ?? 0) > 100);

  return (
    <div style={{ padding: "16px 24px 40px" }}>
      {/* Encabezado */}
      <div style={{ background: C.tealMid, color: "#fff", borderRadius: 10, padding: "12px 16px", marginBottom: 14 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>⚙️ Diagnóstico de Parámetros</div>
        <div style={{ fontSize: 11.5, opacity: .9, marginTop: 2 }}>
          Capacidades por línea y coherencia de parámetros por SKU · solo lectura
        </div>
      </div>

      {/* KPIs */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <KPI label="Líneas" value={r.n_lineas} />
        <KPI label="SKU activos" value={r.n_skus} sub={`${r.n_pares} pares SKU-línea`} />
        <KPI label="Errores" value={r.n_errores} color={r.n_errores ? C.red : C.teal} />
        <KPI label="Advertencias" value={r.n_warnings} color={r.n_warnings ? C.amber : C.teal} />
        <KPI label="Sin línea" value={r.n_sin_linea} color={C.gray} />
      </div>

      {/* Aviso de líneas sobrecargadas: el hallazgo que no es de parámetros sino de capacidad */}
      {sobrecargadas.length > 0 && (
        <div style={{ background: C.redLt, border: `1px solid ${C.red}`, borderRadius: 8,
                      padding: "10px 14px", marginBottom: 12, fontSize: 12.5, color: "#791F1F" }}>
          <b>Capacidad excedida:</b>{" "}
          {sobrecargadas.map((l) => `${l.codigo} (${fmt1(l.derivados.carga_pct)}%)`).join(", ")}
          {" "}— la demanda estimada supera la capacidad semanal. Ningún ajuste de parámetros
          resuelve esto: requiere más turnos, más velocidad o mover SKU de línea.
        </div>
      )}

      {/* Controles */}
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <div style={{ display: "flex", gap: 4 }}>
          {[["todos", "Todos"], ["alertas", "Con alertas"], ["errores", "Solo errores"]].map(([k, lbl]) => (
            <button key={k} onClick={() => setFiltro(k)} style={{
              padding: "5px 11px", fontSize: 11.5, borderRadius: 6, cursor: "pointer",
              border: `1px solid ${filtro === k ? C.teal : C.border}`,
              background: filtro === k ? C.tealLt : "#fff",
              color: filtro === k ? C.tealMid : C.text, fontWeight: filtro === k ? 700 : 400,
            }}>{lbl}</button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: C.textMuted }}>Unidades:</span>
          {[["u", "Unidades"], ["cj", "Cajas"]].map(([k, lbl]) => (
            <button key={k} onClick={() => setUnidad(k)} style={{
              padding: "5px 11px", fontSize: 11.5, borderRadius: 6, cursor: "pointer",
              border: `1px solid ${unidad === k ? C.purple : C.border}`,
              background: unidad === k ? C.purpleLt : "#fff",
              color: unidad === k ? C.purple : C.text, fontWeight: unidad === k ? 700 : 400,
            }}>{lbl}</button>
          ))}
        </div>

        <button onClick={() => {
          const todas = {}; (data.lineas || []).forEach((l) => { todas[l.codigo] = true; });
          setAbierta(Object.keys(abierta).length ? {} : todas);
        }} style={{ padding: "5px 11px", fontSize: 11.5, borderRadius: 6, cursor: "pointer",
                    border: `1px solid ${C.border}`, background: "#fff", color: C.text }}>
          {Object.keys(abierta).length ? "Colapsar todo" : "Expandir todo"}
        </button>
      </div>

      {/* Chips por tipo de alerta (clic = ocultar/mostrar) */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {tiposAlerta.map(([cod, info]) => {
          const off = !!ocultos[cod];
          return (
            <button key={cod} onClick={() => setOcultos((o) => ({ ...o, [cod]: !o[cod] }))}
              title={off ? "Mostrar" : "Ocultar"}
              style={{ padding: "3px 9px", fontSize: 11, borderRadius: 12, cursor: "pointer",
                border: `1px solid ${off ? C.border : NIVEL_COLOR[info.nivel]}`,
                background: off ? "#fff" : NIVEL_BG[info.nivel],
                color: off ? C.textMuted : NIVEL_COLOR[info.nivel],
                textDecoration: off ? "line-through" : "none", fontWeight: 600 }}>
              {ALERTA_LABEL[cod] || cod} · {info.n}
            </button>
          );
        })}
      </div>

      {/* Líneas */}
      {(data.lineas || []).map((l) => {
        const d = l.derivados || {};
        const items = skusFiltrados(l);
        const open = !!abierta[l.codigo];
        if (filtro !== "todos" && items.length === 0) return null;
        return (
          <div key={l.codigo} style={s.card}>
            {/* Encabezado de línea */}
            <div onClick={() => setAbierta((a) => ({ ...a, [l.codigo]: !a[l.codigo] }))}
              style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                       cursor: "pointer", background: open ? C.tealLt : "#fff" }}>
              <span style={{ color: C.textMuted, fontSize: 11, width: 10 }}>{open ? "▼" : "▶"}</span>
              <div style={{ minWidth: 150 }}>
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>{l.codigo}</div>
                <div style={{ fontSize: 10.5, color: C.textMuted }}>{l.area}</div>
              </div>
              <div style={{ fontSize: 11.5, color: C.textMuted, minWidth: 200 }}>
                {fmtN(d.velocidad_u_hr)} u/hr · {d.turnos_dia}t × {fmt1(d.horas_turno ? d.horas_turno : d.horas_dia / (d.turnos_dia || 1))}h × {d.dias_semana}d
              </div>
              <div style={{ fontSize: 11.5, minWidth: 175 }}>
                <span style={{ color: C.textMuted }}>día </span><b>{fmtN(d.cap_dia_u)}</b>
                <span style={{ color: C.textMuted }}> · sem </span><b>{fmtN(d.cap_sem_u)}</b>
                <span style={{ color: C.textMuted, fontSize: 10 }}> u</span>
              </div>
              <div style={{ fontSize: 11.5, minWidth: 128 }}
                   title="Días de máquina que requiere la demanda semanal, contra los días hábiles disponibles">
                <b style={{ color: (d.holgura_dias ?? 0) < 0 ? C.red : C.text }}>
                  {fmt1(d.dias_prod_necesarios)}
                </b>
                <span style={{ color: C.textMuted }}> / {d.dias_disponibles} días</span>
              </div>
              <BarraCarga pct={d.carga_pct} cautivaPct={d.carga_cautiva_pct}
                          flexiblePct={d.carga_flexible_pct} />
              <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                {l.n_flexibles > 0 && (
                  <span style={s.pill(C.purpleLt, C.purple)}
                        title={`${l.n_flexibles} SKU con línea alternativa · ${fmt1(d.dias_prod_flexibles)} días de máquina movibles`}>
                    {l.n_flexibles} movible{l.n_flexibles > 1 ? "s" : ""}
                  </span>
                )}
                <span style={{ fontSize: 11, color: C.textMuted }}>{l.n_skus} SKU</span>
                {l.n_errores > 0 && <span style={s.pill(C.redLt, "#791F1F")}>{l.n_errores} error{l.n_errores > 1 ? "es" : ""}</span>}
                {l.n_warnings > 0 && <span style={s.pill(C.amberLt, "#854F0B")}>{l.n_warnings} advert.</span>}
                {l.n_errores === 0 && l.n_warnings === 0 && <span style={s.pill(C.tealLt, C.tealMid)}>OK</span>}
              </div>
            </div>

            {/* SKU de la línea */}
            {open && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["SKU", "Descripción", "Asig.", "Factor", `Batch mín (${unidad})`,
                        `Cap. día (${unidad})`, `Fcst sem (${unidad})`, "Lotes/sem", "Días prod.",
                        "% día", "Hrs/batch", "Cobertura", "Diagnóstico"].map((h, i) => (
                        <th key={h} style={{ ...s.th, textAlign: i >= 3 && i <= 11 ? "right" : "left" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it, idxSku) => {
                      const dv = it.derivados || {};
                      const al = (it.alertas || []).filter(visible);
                      const hayErr = al.some((a) => a.nivel === "error");
                      const hayWarn = al.some((a) => a.nivel === "warn");
                      const batch = unidad === "u" ? dv.batch_min_u : dv.batch_min_cj;
                      const capd  = unidad === "u" ? dv.cap_dia_u   : dv.cap_dia_cj;
                      const fsem  = unidad === "u" ? dv.forecast_sem_u : dv.forecast_sem_cj;
                      const pct   = dv.pct_dia_por_batch;
                      const key   = `${l.codigo}|${it.sku}`;
                      const abierto = !!skuAbierto[key];
                      return (
                        <React.Fragment key={it.sku}>
                        <tr onClick={() => setSkuAbierto((o) => ({ ...o, [key]: !o[key] }))}
                            title="Ver todos los parámetros"
                            style={{ cursor: "pointer",
                                     background: abierto ? C.tealLt
                                               : hayErr ? "#FFF6F6" : hayWarn ? "#FFFCF5" : "#fff" }}>
                          <td style={{ ...s.td, fontWeight: 600 }}>
                            <span style={{ color: C.textMuted, fontSize: 9, marginRight: 5 }}>
                              {abierto ? "▼" : "▶"}
                            </span>
                            {it.sku}
                            <span onClick={(e) => { e.stopPropagation();
                                     abrirProyeccion(items, idxSku); }}
                                  title="Ver proyección diaria de inventario"
                                  style={{ marginLeft: 6, fontSize: 12, cursor: "pointer",
                                           padding: "1px 4px", borderRadius: 4,
                                           border: `1px solid ${C.border}`, background: "#fff",
                                           color: C.purple, userSelect: "none" }}>
                              📈
                            </span>
                            {(it.alternativas || []).length > 0 && (
                              <div style={{ fontSize: 9.5, marginLeft: 14, marginTop: 1 }}>
                                {it.alternativas.map((a) => (
                                  <div key={a.linea} style={{ color: a.absorbe ? C.tealMid : C.textMuted }}
                                       title={`En ${a.linea} costaría ${fmt1(a.dias_prod_sem)} días de máquina. `
                                            + `Esa línea está al ${fmt1(a.carga_pct)}% con ${fmt1(a.holgura_dias)} días libres.`}>
                                    → {a.linea} ({fmt1(a.carga_pct)}%) {a.absorbe ? "✓ absorbe" : "✕ sin holgura"}
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                          <td style={{ ...s.td, maxWidth: 230, overflow: "hidden", textOverflow: "ellipsis" }}
                              title={it.descripcion}>
                            {it.descripcion}
                            {dv.mto && <span style={{ ...s.pill(C.purpleLt, C.purple), marginLeft: 5 }}>MTO</span>}
                          </td>
                          <td style={s.td}>
                            {it.preferida
                              ? <span style={s.pill(C.tealLt, C.tealMid)}>preferida</span>
                              : <span style={s.pill(C.grayLt, C.gray)}>alternativa</span>}
                          </td>
                          <td style={{ ...s.td, textAlign: "right",
                                       color: dv.factor_velocidad < 1 ? C.amber : C.text }}>
                            <Param value={dv.factor_velocidad ?? "—"} fuerte={dv.factor_velocidad < 1} />
                          </td>
                          <td style={{ ...s.td, textAlign: "right" }}>
                            <Param value={unidad === "u" ? fmtN(batch) : fmt1(batch)} />
                          </td>
                          <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>
                            {unidad === "u" ? fmtN(capd) : fmt1(capd)}
                          </td>
                          <td style={{ ...s.td, textAlign: "right",
                                       color: fsem == null ? C.textMuted : C.purple }}>
                            {fsem == null ? "—" : (unidad === "u" ? fmtN(fsem) : fmt1(fsem))}
                          </td>
                          <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>
                            {dv.lotes_sem == null ? "—" : fmt1(dv.lotes_sem)}
                          </td>
                          <td style={{ ...s.td, textAlign: "right", fontWeight: 600 }}>
                            {dv.dias_prod_sem == null ? "—" : `${fmt1(dv.dias_prod_sem)} d`}
                          </td>
                          <td style={{ ...s.td, textAlign: "right", fontWeight: 700,
                                       color: pct == null ? C.textMuted : pct > 100 ? C.red : pct > 90 ? C.amber : C.teal }}>
                            {pct == null ? "—" : `${fmt1(pct)}%`}
                          </td>
                          <td style={{ ...s.td, textAlign: "right", color: C.textMuted }}>
                            {dv.horas_por_batch == null ? "—" : `${fmt1(dv.horas_por_batch)} h`}
                          </td>
                          <td style={{ ...s.td, textAlign: "right",
                                       color: dv.dias_cobertura_batch > 30 ? C.amber : C.textMuted }}>
                            {dv.dias_cobertura_batch == null ? "—" : `${fmt1(dv.dias_cobertura_batch)} d`}
                          </td>
                          <td style={{ ...s.td, whiteSpace: "normal", minWidth: 230 }}>
                            {al.length === 0
                              ? <span style={s.pill(C.tealLt, C.tealMid)}>OK</span>
                              : al.map((a, i) => (
                                  <div key={i} title={a.mensaje}
                                       style={{ ...s.pill(NIVEL_BG[a.nivel], NIVEL_COLOR[a.nivel]),
                                                marginRight: 4, marginBottom: 2, cursor: "help" }}>
                                    {ALERTA_LABEL[a.codigo] || a.codigo}
                                  </div>
                                ))}
                          </td>
                        </tr>
                        {abierto && (
                          <tr>
                            <td colSpan={13} style={{ padding: 0 }}>
                              <DetalleSku it={it}
                                onVerProyeccion={() => abrirProyeccion(items, idxSku)} />
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
          </div>
        );
      })}

      {/* SKU sin línea asignada */}
      {(data.sin_linea || []).length > 0 && (
        <div style={{ ...s.card, marginTop: 16 }}>
          <div style={{ padding: "10px 14px", fontWeight: 700, fontSize: 13, background: C.grayLt }}>
            Sin línea asignada · {data.sin_linea.length}
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>{["SKU", "Descripción", "Categoría", "Tipo", "Batch mín (u)", "Observación"].map((h, i) => (
                <th key={h} style={{ ...s.th, textAlign: i === 4 ? "right" : "left" }}>{h}</th>))}</tr>
            </thead>
            <tbody>
              {data.sin_linea.map((it) => (
                <tr key={it.sku}>
                  <td style={{ ...s.td, fontWeight: 600 }}>{it.sku}</td>
                  <td style={s.td}>{it.descripcion}</td>
                  <td style={{ ...s.td, color: C.textMuted }}>{it.categoria}</td>
                  <td style={{ ...s.td, color: C.textMuted }}>{it.tipo}</td>
                  <td style={{ ...s.td, textAlign: "right" }}>{fmtN(it.params_producto?.batch_min_u)}</td>
                  <td style={{ ...s.td, color: C.textMuted }}>
                    {(it.alertas || []).map((a) => a.mensaje).join(" ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: 14, fontSize: 11, color: C.textMuted }}>
        Umbrales: margen diario &gt; {Math.round((r.umbrales?.margen_dia ?? .9) * 100)}% ·
        cobertura &gt; {r.umbrales?.dias_cobertura ?? 30} días ·
        bodega &lt; {r.umbrales?.ratio_cap_bodega ?? 2}× batch mínimo.
        La demanda usada es el promedio de las próximas 4 semanas completas del plan vigente.
      </div>

      {modal && (
        <ProyeccionModal sku={modal.sku} descripcion={modal.descripcion}
                         lista={modal.lista} indice={modal.indice}
                         onNavegar={navegarProyeccion}
                         onClose={() => setModal(null)} />
      )}
    </div>
  );
}
