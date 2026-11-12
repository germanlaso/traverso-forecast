// EditorParametros.jsx — Fase 2 del Diagnóstico de Parámetros: edición con validación.
// La validación la hace el BACKEND con el mismo motor del diagnóstico (params_diagnostico.py):
//   🔴 error  -> no se puede guardar   ·   🟡 advertencia -> se puede guardar, queda a la vista
// Cada cambio pide nombre + PIN + motivo y queda en el historial (se puede revertir).
// Los cambios aplican en la PRÓXIMA corrida del plan.

import React, { useEffect, useMemo, useRef, useState } from "react";

const API = process.env.REACT_APP_API_BASE || "";
const KEY_EDITOR = "params_editor";
const SIN_LIMITE = 999999;

const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  purple: "#534AB7", purpleLt: "#EEEDFE",
  amber: "#EF9F27", amberLt: "#FAEEDA", amberDk: "#854F0B",
  red: "#E24B4A", redLt: "#FCEBEB", redDk: "#791F1F",
  gray: "#5F5E5A", grayLt: "#F1EFE8",
  border: "#D3D1C7", text: "#2C2C2A", textMuted: "#888780",
};
const fmtN = (n) => (n === null || n === undefined || n === "" ? "—" : Math.round(Number(n)).toLocaleString("es-CL"));
const fmt1 = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("es-CL", { maximumFractionDigits: 1 }));
const fmt2 = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("es-CL", { maximumFractionDigits: 2 }));

export const ETIQUETA_CAMPO = {
  batch_min_u: "Batch mínimo", cap_bodega_u: "Cap. bodega", factor_velocidad: "Factor de velocidad",
  velocidad_u_hr: "Velocidad de línea", turnos_dia: "Turnos por día", horas_turno: "Horas por turno",
  dias_semana: "Días por semana", carga_masiva_excel: "Carga masiva desde Excel",
};
const PRIORIDAD = {
  alta: [C.redLt, C.redDk], "media-alta": [C.amberLt, C.amberDk], media: ["#E6F1FB", "#185FA5"], baja: [C.grayLt, C.gray],
};

const st = {
  overlay: { position: "fixed", inset: 0, background: "rgba(44,44,42,0.45)", zIndex: 1000,
             display: "flex", alignItems: "center", justifyContent: "center", padding: 16 },
  box: { background: "#fff", borderRadius: 12, width: "min(980px, 100%)", maxHeight: "92vh", overflowY: "auto",
         boxShadow: "0 10px 40px rgba(0,0,0,.2)", fontFamily: "Arial, sans-serif", color: C.text },
  head: { padding: "14px 18px", borderBottom: `1px solid ${C.border}`, display: "flex", justifyContent: "space-between",
          alignItems: "flex-start", gap: 12, position: "sticky", top: 0, background: "#fff", zIndex: 1 },
  body: { padding: "14px 18px" },
  label: { display: "flex", flexDirection: "column", gap: 3, fontSize: 11.5, color: C.gray },
  input: { padding: "6px 8px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, width: "100%", boxSizing: "border-box" },
  pill: (bg, col) => ({ display: "inline-block", fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 10,
                        background: bg, color: col, whiteSpace: "nowrap" }),
  btn: { padding: "7px 14px", border: `1px solid ${C.border}`, borderRadius: 6, background: "#fff", cursor: "pointer", fontSize: 12.5 },
  btnPri: { padding: "7px 16px", border: "none", borderRadius: 6, background: C.teal, color: "#fff", cursor: "pointer",
            fontSize: 12.5, fontWeight: 700 },
  th: { textAlign: "left", fontSize: 10.5, color: C.textMuted, padding: "4px 8px", borderBottom: `1px solid ${C.border}`,
        fontWeight: 700, whiteSpace: "nowrap" },
  td: { fontSize: 12, padding: "5px 8px", borderBottom: `1px solid ${C.grayLt}`, verticalAlign: "top" },
  sec: { fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: .4, margin: "14px 0 6px" },
};

const NIVEL = { error: [C.redLt, C.redDk, "Error"], warn: [C.amberLt, C.amberDk, "Advertencia"], info: [C.grayLt, C.gray, "Info"] };

function detalleError(e) {
  const d = e?.detail ?? e;
  if (typeof d === "string") return d;
  if (d?.mensaje) return d.mensaje;
  return "No se pudo completar la operación.";
}

async function api(method, path, body) {
  const r = await fetch(`${API}${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) throw Object.assign(new Error(detalleError(data)), { status: r.status, data });
  return data;
}

function useDebounced(value, ms) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

function Alertas({ alertas, mostrarLinea }) {
  const al = (alertas || []).filter((a) => a.nivel !== "info");
  if (!al.length) return <span style={st.pill(C.tealLt, C.tealMid)}>Sin alertas</span>;
  return al.map((a, i) => (
    <div key={i} style={{ display: "flex", gap: 6, marginBottom: 3, alignItems: "flex-start" }}>
      <span style={{ ...st.pill(NIVEL[a.nivel][0], NIVEL[a.nivel][1]), flexShrink: 0 }}>
        {NIVEL[a.nivel][2]}{mostrarLinea && a.linea ? ` · ${a.linea}` : ""}
      </span>
      <span style={{ fontSize: 11.5 }}>{a.mensaje}</span>
    </div>
  ));
}

// ── Autorización (nombre + PIN + motivo) ──────────────────────────────────────
function useAuth() {
  const [editor, setEditor] = useState(() => { try { return localStorage.getItem(KEY_EDITOR) || ""; } catch { return ""; } });
  const [pin, setPin] = useState("");
  const [motivo, setMotivo] = useState("");
  const recordar = () => { try { localStorage.setItem(KEY_EDITOR, editor.trim()); } catch { /* sin storage */ } };
  const completa = editor.trim().length >= 3 && pin.length >= 4 && motivo.trim().length >= 5;
  return { editor, setEditor, pin, setPin, motivo, setMotivo, recordar, completa };
}

function CamposAuth({ auth }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 140px 2fr", gap: 10, marginTop: 6 }}>
      <label style={st.label}>Quien edita
        <input style={st.input} value={auth.editor} onChange={(e) => auth.setEditor(e.target.value)} placeholder="Nombre y apellido" />
      </label>
      <label style={st.label}>PIN de edición
        <input style={st.input} type="password" value={auth.pin} onChange={(e) => auth.setPin(e.target.value)} autoComplete="off" />
      </label>
      <label style={st.label}>Motivo del cambio
        <input style={st.input} value={auth.motivo} onChange={(e) => auth.setMotivo(e.target.value)}
               placeholder="Ej.: Informe semanal Sem 45 · cap. bodega menor a batch + SS" />
      </label>
    </div>
  );
}

// ── Recomendaciones ───────────────────────────────────────────────────────────
// (11-11-2026) descartar una recomendación IA: pide el motivo (queda en la recomendación y,
// si venía de un caso, cierra la acción y alimenta el aprendizaje)
async function descartarReco(r, editor, pin) {
  if (!(editor || "").trim() || (editor || "").trim().length < 3 || !pin || pin.length < 4)
    throw new Error("Completa tu nombre y el PIN para descartar.");
  const motivo = window.prompt(`¿Por qué descartas "${ETIQUETA_CAMPO[r.campo] || r.campo}" de ${r.clave}? (queda registrado)`);
  if (motivo === null) return false;
  if (motivo.trim().length < 5) throw new Error("El motivo debe tener al menos 5 caracteres.");
  await api("POST", `/params/recomendaciones/${r.id}/estado`, { estado: "descartada", editor, pin, motivo });
  try { localStorage.setItem(KEY_EDITOR, editor.trim()); } catch { /* sin storage */ }
  return true;
}

function ListaRecos({ recos, onUsar, editables, auth, onDescartada }) {
  const [err, setErr] = useState(null);
  if (!recos.length) return null;
  return (
    <div>
      <div style={st.sec}>Recomendaciones del análisis IA</div>
      {recos.map((r) => {
        const usable = r.valor_sugerido != null && editables.includes(r.campo);
        return (
          <div key={r.id} style={{ border: `1px solid ${C.purple}33`, background: C.purpleLt, borderRadius: 8,
                                   padding: "8px 10px", marginBottom: 6, display: "flex", gap: 10, alignItems: "flex-start" }}>
            <div style={{ flex: 1, fontSize: 12 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span style={st.pill(...(PRIORIDAD[r.prioridad] || PRIORIDAD.media))}>{r.prioridad}</span>
                <b>{ETIQUETA_CAMPO[r.campo] || r.campo}</b>
                {r.linea && <span style={{ color: C.textMuted }}>· {r.linea}</span>}
                <span>· vigente <b>{fmt2(r.valor_vigente)}</b></span>
                {r.valor_sugerido != null && <span>→ sugerido <b style={{ color: C.purple }}>{fmt2(r.valor_sugerido)}</b></span>}
                {r.rango && <span style={{ color: C.textMuted }}>({r.rango})</span>}
              </div>
              <div style={{ color: C.gray, marginTop: 3 }}>{r.motivo}</div>
              <div style={{ color: C.textMuted, fontSize: 10.5, marginTop: 2 }}>{r.fuente}</div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {usable && <button style={{ ...st.btn, borderColor: C.purple, color: C.purple, whiteSpace: "nowrap" }}
                                 onClick={() => onUsar(r)}>Usar sugerencia</button>}
              {auth && <button style={{ ...st.btn, whiteSpace: "nowrap", fontSize: 11.5, padding: "4px 10px" }}
                               onClick={async () => { setErr(null); try { if (await descartarReco(r, auth.editor, auth.pin)) onDescartada && onDescartada(r); } catch (e) { setErr(e.message); } }}>
                Descartar</button>}
            </div>
          </div>
        );
      })}
      {err && <div style={{ fontSize: 12, color: C.redDk, marginBottom: 4 }}>{err}</div>}
      <div style={{ fontSize: 10.5, color: C.textMuted }}>"Usar sugerencia" solo completa el formulario: el cambio se guarda recién al confirmar.
        "Descartar" pide el motivo y usa el nombre y PIN de abajo.</div>
    </div>
  );
}

// ── Historial ─────────────────────────────────────────────────────────────────
function Historial({ query, auth, onRevertido }) {
  const [filas, setFilas] = useState(null);
  const [msg, setMsg] = useState(null);
  const cargar = () => api("GET", `/params/historial?${query}`).then((d) => setFilas(d.historial)).catch((e) => setMsg(e.message));
  useEffect(() => { cargar(); /* eslint-disable-next-line */ }, [query]);
  const revertir = async (h) => {
    setMsg(null);
    if (!(auth.editor.trim().length >= 3 && auth.pin.length >= 4)) return setMsg("Completa tu nombre y el PIN para revertir.");
    if (!window.confirm(`¿Revertir ${ETIQUETA_CAMPO[h.campo] || h.campo}: ${fmt2(h.valor_nuevo)} → ${fmt2(h.valor_anterior)}?`)) return;
    try {
      await api("POST", `/params/historial/${h.id}/revertir`,
                { editor: auth.editor, pin: auth.pin, motivo: auth.motivo.trim() || `Reversión del cambio #${h.id}` });
      auth.recordar(); setMsg("Cambio revertido."); cargar(); onRevertido && onRevertido();
    } catch (e) { setMsg(e.message); }
  };
  if (!filas) return <div style={{ fontSize: 12, color: C.textMuted }}>Cargando historial…</div>;
  return (
    <div>
      {filas.length === 0 ? <div style={{ fontSize: 12, color: C.textMuted }}>Sin cambios registrados.</div> : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Fecha", "Campo", "Anterior → nuevo", "Quién", "Motivo", ""].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
          <tbody>{filas.map((h) => (
            <tr key={h.id}>
              <td style={{ ...st.td, whiteSpace: "nowrap" }}>{new Date(h.ts).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" })}</td>
              <td style={st.td}>{ETIQUETA_CAMPO[h.campo] || h.campo}{h.linea && h.sku ? ` · ${h.linea}` : ""}
                {h.origen !== "panel" && <span style={{ ...st.pill(C.grayLt, C.gray), marginLeft: 4 }}>{h.origen}</span>}</td>
              <td style={{ ...st.td, whiteSpace: "nowrap" }}>{fmt2(h.valor_anterior)} → <b>{fmt2(h.valor_nuevo)}</b></td>
              <td style={st.td}>{h.editor}</td>
              <td style={{ ...st.td, maxWidth: 280 }}>{h.motivo}</td>
              <td style={st.td}>{h.revertido_por
                ? <span style={st.pill(C.grayLt, C.gray)}>revertido</span>
                : h.origen !== "carga_masiva" && h.valor_anterior != null &&
                  <button style={{ ...st.btn, padding: "3px 8px", fontSize: 11 }} onClick={() => revertir(h)}>Revertir</button>}</td>
            </tr>))}</tbody>
        </table>
      )}
      {msg && <div style={{ fontSize: 12, marginTop: 6, color: msg.startsWith("Cambio") ? C.tealMid : C.redDk }}>{msg}</div>}
      <div style={{ fontSize: 10.5, color: C.textMuted, marginTop: 4 }}>Revertir usa el nombre y PIN de arriba. Solo se puede revertir el cambio más reciente de cada campo.</div>
    </div>
  );
}

function Tabs({ tab, setTab, items }) {
  return (
    <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
      {items.map(([k, l]) => (
        <button key={k} onClick={() => setTab(k)} style={{ ...st.btn, borderRadius: 16, padding: "5px 12px",
          background: tab === k ? C.teal : "#fff", color: tab === k ? "#fff" : C.gray, borderColor: tab === k ? C.teal : C.border,
          fontWeight: tab === k ? 700 : 400 }}>{l}</button>
      ))}
    </div>
  );
}

function useEsc(onClose) {
  useEffect(() => {
    const f = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f);
  }, [onClose]);
}

// ── Modal: editar SKU ─────────────────────────────────────────────────────────
// item = elemento del diagnóstico (params_producto, params_en_linea, derivados) en la línea abierta
export function ModalEditarSku({ item, linea, onClose, onGuardado }) {
  useEsc(onClose);
  const pp = item.params_producto || {};
  const pl = item.params_en_linea || {};
  const upc = pp.u_por_caja || 1;
  const ini = useMemo(() => ({ batch_min_u: pp.batch_min_u ?? 0, cap_bodega_u: pp.cap_bodega_u ?? SIN_LIMITE,
                               factor_velocidad: pl.factor_velocidad ?? 1 }), [pp, pl]);
  const [form, setForm] = useState({ batch_min_u: String(ini.batch_min_u), cap_bodega_u: String(ini.cap_bodega_u),
                                     factor_velocidad: String(ini.factor_velocidad) });
  const [sinLimite, setSinLimite] = useState(Number(ini.cap_bodega_u) >= SIN_LIMITE);
  const [recos, setRecos] = useState([]);
  const [recoIds, setRecoIds] = useState([]);
  const [val, setVal] = useState(null);
  const [valErr, setValErr] = useState(null);
  const [tab, setTab] = useState("editar");
  const [guardando, setGuardando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const auth = useAuth();

  const cambios = useMemo(() => {
    const cp = {}, fa = {};
    const b = Number(form.batch_min_u), cap = sinLimite ? SIN_LIMITE : Number(form.cap_bodega_u), f = Number(form.factor_velocidad);
    if (form.batch_min_u !== "" && b !== Number(ini.batch_min_u)) cp.batch_min_u = b;
    if ((sinLimite || form.cap_bodega_u !== "") && cap !== Number(ini.cap_bodega_u)) cp.cap_bodega_u = cap;
    if (form.factor_velocidad !== "" && Math.abs(f - Number(ini.factor_velocidad)) > 1e-9) fa[linea] = f;
    return { cambios_producto: cp, factores: fa };
  }, [form, sinLimite, ini, linea]);
  const hayCambios = Object.keys(cambios.cambios_producto).length + Object.keys(cambios.factores).length > 0;
  const cambiosDeb = useDebounced(cambios, 400);
  const vivo = useRef(true);
  // En modo desarrollo (React StrictMode) el efecto se monta, desmonta y vuelve a montar:
  // hay que volver a marcar el componente como vivo en cada montaje.
  useEffect(() => { vivo.current = true; return () => { vivo.current = false; }; }, []);

  useEffect(() => {
    api("GET", `/params/recomendaciones?sku=${encodeURIComponent(item.sku)}`).then((d) => setRecos(d.recomendaciones || [])).catch(() => {});
  }, [item.sku]);

  useEffect(() => {
    setValErr(null);
    api("POST", `/params/sku/${encodeURIComponent(item.sku)}/validar`, cambiosDeb)
      .then((d) => vivo.current && setVal(d)).catch((e) => vivo.current && setValErr(e.message));
  }, [cambiosDeb, item.sku]);

  const usar = (r) => {
    if (r.campo === "factor_velocidad") setForm((f) => ({ ...f, factor_velocidad: String(r.valor_sugerido) }));
    else { setForm((f) => ({ ...f, [r.campo]: String(Math.round(r.valor_sugerido)) })); if (r.campo === "cap_bodega_u") setSinLimite(false); }
    setRecoIds((ids) => [...new Set([...ids, r.id])]);
    // motivo prellenado con la fuente y la explicación de la recomendación (queda en el historial)
    if (!auth.motivo.trim()) auth.setMotivo(`${r.fuente}: ${r.motivo || ETIQUETA_CAMPO[r.campo]}`.slice(0, 600));
  };

  const guardar = async () => {
    setResultado(null); setGuardando(true);
    try {
      const d = await api("PUT", `/params/sku/${encodeURIComponent(item.sku)}`,
        { ...cambios, editor: auth.editor, pin: auth.pin, motivo: auth.motivo, recomendacion_ids: recoIds });
      auth.recordar();
      setResultado({ ok: true, texto: `Guardado: ${d.cambios.length} cambio(s). ${d.aviso}`, adv: d.advertencias });
      onGuardado && onGuardado();
    } catch (e) {
      setResultado({ ok: false, texto: e.message, errores: e.data?.detail?.errores });
    } finally { setGuardando(false); }
  };

  const prop = val?.por_linea?.find((x) => x.linea === linea)?.propuesto?.derivados || {};
  const act = val?.por_linea?.find((x) => x.linea === linea)?.actual?.derivados || {};
  const errores = val?.errores || [];
  const advert = val?.advertencias || [];
  const puede = hayCambios && !errores.length && auth.completa && !guardando && !valErr;

  return (
    <div style={st.overlay} onClick={onClose}>
      <div style={st.box} onClick={(e) => e.stopPropagation()}>
        <div style={st.head}>
          <div>
            <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .4 }}>Editar parámetros · SKU</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{item.sku} · {item.descripcion}</div>
            <div style={{ fontSize: 12, color: C.gray }}>Línea {linea}{item.preferida ? " (preferida)" : " (alternativa)"} · {upc} u/caja</div>
          </div>
          <span onClick={onClose} style={{ cursor: "pointer", fontSize: 20, color: C.gray }} title="Cerrar (Esc)">✕</span>
        </div>
        <div style={st.body}>
          <Tabs tab={tab} setTab={setTab} items={[["editar", "Editar"], ["historial", "Historial"]]} />
          {tab === "editar" && <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              <label style={st.label}>Batch mínimo (u) · global del SKU
                <input style={st.input} type="number" min="1" value={form.batch_min_u}
                       onChange={(e) => setForm({ ...form, batch_min_u: e.target.value })} />
                <span style={{ fontSize: 10.5, color: C.textMuted }}>
                  = {fmt1(Number(form.batch_min_u) / upc)} cj · {fmt1(prop.horas_por_batch)} h de línea (hoy {fmt1(act.horas_por_batch)} h)
                </span>
              </label>
              <label style={st.label}>Cap. bodega (u) · global del SKU
                <input style={{ ...st.input, background: sinLimite ? C.grayLt : "#fff" }} type="number" min="1" disabled={sinLimite}
                       value={sinLimite ? "" : form.cap_bodega_u} onChange={(e) => setForm({ ...form, cap_bodega_u: e.target.value })} />
                <span style={{ fontSize: 10.5, color: C.textMuted, display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={sinLimite} onChange={(e) => setSinLimite(e.target.checked)} /> sin límite
                  {prop.batch_mas_ss_u != null && <> · batch + SS estimado: {fmtN(prop.batch_mas_ss_u)} u</>}
                </span>
              </label>
              <label style={st.label}>Factor de velocidad · solo en {linea}
                <input style={st.input} type="number" step="0.01" min="0.05" max="3" value={form.factor_velocidad}
                       onChange={(e) => setForm({ ...form, factor_velocidad: e.target.value })} />
                <span style={{ fontSize: 10.5, color: C.textMuted }}>
                  velocidad efectiva {fmtN(prop.vel_efectiva_u_hr)} u/h · cap. día {fmtN(prop.cap_dia_u)} u
                </span>
              </label>
            </div>

            <div style={st.sec}>Validación {hayCambios ? "del cambio propuesto" : "(valores actuales)"}</div>
            {valErr ? <div style={{ fontSize: 12, color: C.redDk }}>{valErr}</div> : !val ? (
              <div style={{ fontSize: 12, color: C.textMuted }}>Validando…</div>) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr>{["Línea", "Horas por batch", "% del día", "Cap. día (u)", "Alertas con el valor propuesto"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
                <tbody>{val.por_linea.map((x) => (
                  <tr key={x.linea}>
                    <td style={{ ...st.td, fontWeight: 700 }}>{x.linea}{x.preferida ? <span style={{ ...st.pill(C.tealLt, C.tealMid), marginLeft: 4 }}>pref.</span> : null}</td>
                    <td style={st.td}>{fmt1(x.actual.derivados.horas_por_batch)} → <b>{fmt1(x.propuesto.derivados.horas_por_batch)}</b> h</td>
                    <td style={st.td}>{fmt1(x.propuesto.derivados.pct_dia_por_batch)}%</td>
                    <td style={st.td}>{fmtN(x.propuesto.derivados.cap_dia_u)}</td>
                    <td style={st.td}><Alertas alertas={x.propuesto.alertas} /></td>
                  </tr>))}</tbody>
              </table>
            )}
            {errores.length > 0 && <div style={{ background: C.redLt, color: C.redDk, borderRadius: 8, padding: "8px 10px", marginTop: 8, fontSize: 12 }}>
              <b>No se puede guardar:</b> hay {errores.length} error(es) con los valores propuestos.</div>}
            {!errores.length && advert.length > 0 && hayCambios && <div style={{ background: C.amberLt, color: C.amberDk, borderRadius: 8, padding: "8px 10px", marginTop: 8, fontSize: 12 }}>
              Se puede guardar, pero quedan {advert.length} advertencia(s): revísalas antes de confirmar.</div>}

            <ListaRecos recos={recos} onUsar={usar} editables={["batch_min_u", "cap_bodega_u", "factor_velocidad"]}
                        auth={auth} onDescartada={(r) => { setRecos(recos.filter((x) => x.id !== r.id)); onGuardado && onGuardado(); }} />

            <div style={st.sec}>Confirmar</div>
            <CamposAuth auth={auth} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, gap: 10 }}>
              <span style={{ fontSize: 11, color: C.textMuted }}>El batch mínimo y la cap. bodega aplican en todas las líneas del SKU. Los cambios rigen desde la próxima corrida del plan.</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={st.btn} onClick={onClose}>Cerrar</button>
                <button style={{ ...st.btnPri, opacity: puede ? 1 : .45, cursor: puede ? "pointer" : "not-allowed" }} disabled={!puede} onClick={guardar}>
                  {guardando ? "Guardando…" : "Guardar cambios"}</button>
              </div>
            </div>
            {resultado && <div style={{ marginTop: 10, fontSize: 12.5, color: resultado.ok ? C.tealMid : C.redDk }}>
              {resultado.texto}{resultado.errores && <div style={{ marginTop: 4 }}><Alertas alertas={resultado.errores} mostrarLinea /></div>}</div>}
          </>}
          {tab === "historial" && <>
            <CamposAuth auth={auth} />
            <div style={{ height: 10 }} />
            <Historial query={`sku=${encodeURIComponent(item.sku)}`} auth={auth} onRevertido={onGuardado} />
          </>}
        </div>
      </div>
    </div>
  );
}

// ── Modal: editar línea ───────────────────────────────────────────────────────
export function ModalEditarLinea({ linea, onClose, onGuardado }) {
  useEsc(onClose);
  const p = linea.params || {};
  const tcIni = useMemo(() => (p.turnos_config || null), [p]);
  // Con calendario (turnos_config) se edita velocidad + horas por día y turno; sin él, los campos anteriores.
  const ini = useMemo(() => (tcIni ? { velocidad_u_hr: p.velocidad_u_hr }
    : { velocidad_u_hr: p.velocidad_u_hr, turnos_dia: p.turnos_dia, horas_turno: p.horas_turno, dias_semana: p.dias_semana }), [p, tcIni]);
  const [turnos, setTurnos] = useState(() => (tcIni || []).map((t) => (t.horas || []).map((h) => String(h))));
  // (11-11-2026) vigencia por turno (desde / hasta; vacío = sin límite). El turno 1 no lleva fechas.
  const [vig, setVig] = useState(() => (tcIni || []).map((t) => ({ desde: t.desde || "", hasta: t.hasta || "" })));
  const [calActivo, setCalActivo] = useState(null);
  useEffect(() => { api("GET", "/params/config").then((c) => setCalActivo(!!c.calendario_activo)).catch(() => {}); }, []);
  const [form, setForm] = useState(Object.fromEntries(Object.entries(ini).map(([k, v]) => [k, String(v ?? "")])));
  const [imp, setImp] = useState(null);
  const [impErr, setImpErr] = useState(null);
  const [recos, setRecos] = useState([]);
  const [tab, setTab] = useState("editar");
  const [guardando, setGuardando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const auth = useAuth();

  const turnosNum = useMemo(() => turnos.map((t, i) => ({ horas: t.map((h) => Number(h || 0)),
    ...(i > 0 && vig[i]?.desde ? { desde: vig[i].desde } : {}), ...(i > 0 && vig[i]?.hasta ? { hasta: vig[i].hasta } : {}) })), [turnos, vig]);
  const _norm = (arr) => JSON.stringify((arr || []).map((t) => [(t.horas || []).map(Number), t.desde || "", t.hasta || ""]));
  const turnosCambiaron = useMemo(() => tcIni && _norm(turnosNum) !== _norm(tcIni), [turnosNum, tcIni]); // eslint-disable-line
  const cambios = useMemo(() => {
    const c = {};
    Object.keys(ini).forEach((k) => { if (form[k] !== "" && Number(form[k]) !== Number(ini[k])) c[k] = Number(form[k]); });
    if (turnosCambiaron) c.turnos_config = turnosNum;
    return c;
  }, [form, ini, turnosCambiaron, turnosNum]);
  const hayCambios = Object.keys(cambios).length > 0;
  const cambiosDeb = useDebounced(cambios, 400);

  useEffect(() => {
    api("GET", `/params/recomendaciones?linea=${encodeURIComponent(linea.codigo)}`)
      .then((d) => setRecos((d.recomendaciones || []).filter((r) => r.entidad === "linea"))).catch(() => {});
  }, [linea.codigo]);
  useEffect(() => {
    if (!Object.keys(cambiosDeb).length) { setImp(null); setImpErr(null); return; }
    setImpErr(null);
    api("POST", `/params/linea/${encodeURIComponent(linea.codigo)}/validar`, { cambios: cambiosDeb })
      .then(setImp).catch((e) => { setImp(null); setImpErr(e.message); });
  }, [cambiosDeb, linea.codigo]);

  const guardar = async () => {
    setResultado(null); setGuardando(true);
    try {
      const d = await api("PUT", `/params/linea/${encodeURIComponent(linea.codigo)}`,
        { cambios, editor: auth.editor, pin: auth.pin, motivo: auth.motivo });
      auth.recordar(); setResultado({ ok: true, texto: `Guardado: ${d.cambios.length} cambio(s). ${d.aviso}` });
      onGuardado && onGuardado();
    } catch (e) { setResultado({ ok: false, texto: e.message }); } finally { setGuardando(false); }
  };

  const puede = hayCambios && imp && imp.puede_guardar && auth.completa && !guardando;
  const campo = (k, lab, extra) => (
    <label style={st.label}>{lab}
      <input style={st.input} type="number" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} {...extra} />
    </label>
  );
  const da = imp?.derivados_actual, dp = imp?.derivados_propuesto;

  return (
    <div style={st.overlay} onClick={onClose}>
      <div style={st.box} onClick={(e) => e.stopPropagation()}>
        <div style={st.head}>
          <div>
            <div style={{ fontSize: 11, color: C.textMuted, textTransform: "uppercase", letterSpacing: .4 }}>Editar parámetros · línea</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{linea.codigo}</div>
            <div style={{ fontSize: 12, color: C.gray }}>{linea.n_skus} SKU asignados · los cambios afectan a todos</div>
          </div>
          <span onClick={onClose} style={{ cursor: "pointer", fontSize: 20, color: C.gray }} title="Cerrar (Esc)">✕</span>
        </div>
        <div style={st.body}>
          <Tabs tab={tab} setTab={setTab} items={[["editar", "Editar"], ["excepciones", "Excepciones por fecha"], ["historial", "Historial"]]} />
          {calActivo === false && tcIni && (
            <div style={{ background: C.amberLt, color: C.amberDk, borderRadius: 8, padding: "7px 10px", fontSize: 12, marginBottom: 10 }}>
              El calendario de capacidad está <b>apagado</b>: el plan todavía usa {p.turnos_dia} turno × {fmt1(p.horas_turno)} h × {p.dias_semana} días.
              Lo que configures aquí se aplicará cuando se active.</div>)}
          {tab === "editar" && <>
            {tcIni ? <>
              <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 12, alignItems: "end" }}>
                {campo("velocidad_u_hr", "Velocidad (u/h)", { min: 1 })}
                <div style={{ fontSize: 11.5, color: C.gray }}>Jornada legal: 42 h semanales (lunes y martes 9 h, miércoles a viernes 8 h). Cada turno se configura por día; un día en 0 = sin ese turno.</div>
              </div>
              <div style={st.sec}>Horas por día y turno</div>
              <table style={{ borderCollapse: "collapse" }}>
                <thead><tr><th style={st.th}></th>{["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((d) => <th key={d} style={{ ...st.th, textAlign: "center" }}>{d}</th>)}<th style={st.th}>Semana</th><th style={st.th}>Vigencia</th><th style={st.th}></th></tr></thead>
                <tbody>
                  {turnos.map((t, i) => (
                    <tr key={i}>
                      <td style={{ ...st.td, fontWeight: 700, whiteSpace: "nowrap" }}>Turno {i + 1}</td>
                      {t.map((h, d) => (
                        <td key={d} style={st.td}>
                          <input style={{ ...st.input, width: 52, textAlign: "center", padding: "4px" }} type="number" min="0" max="12" step="0.5" value={h}
                                 onChange={(e) => setTurnos(turnos.map((tt, ii) => ii !== i ? tt : tt.map((hh, dd) => dd === d ? e.target.value : hh)))} />
                        </td>))}
                      <td style={{ ...st.td, fontWeight: 700 }}>{fmt1(t.reduce((a, x) => a + Number(x || 0), 0))} h</td>
                      <td style={{ ...st.td, whiteSpace: "nowrap" }}>{i === 0 ? <span style={{ fontSize: 11, color: C.textMuted }}>siempre (jornada base)</span> : <>
                        <input type="date" title="Desde (vacío = desde ya)" style={{ ...st.input, width: 132, padding: "3px 5px", fontSize: 11.5 }} value={vig[i]?.desde || ""}
                               onChange={(e) => setVig(vig.map((v, ii) => ii !== i ? v : { ...v, desde: e.target.value }))} />
                        <span style={{ margin: "0 3px", color: C.textMuted }}>→</span>
                        <input type="date" title="Hasta (vacío = sin fecha de término)" style={{ ...st.input, width: 132, padding: "3px 5px", fontSize: 11.5 }} value={vig[i]?.hasta || ""}
                               onChange={(e) => setVig(vig.map((v, ii) => ii !== i ? v : { ...v, hasta: e.target.value }))} />
                        <label style={{ fontSize: 11, color: C.gray, marginLeft: 6 }}>
                          <input type="checkbox" checked={!vig[i]?.hasta} onChange={(e) => e.target.checked && setVig(vig.map((v, ii) => ii !== i ? v : { ...v, hasta: "" }))} /> sin término</label>
                      </>}</td>
                      <td style={st.td}>{i > 0 && <button style={{ ...st.btn, padding: "3px 8px", fontSize: 11 }} onClick={() => { setTurnos(turnos.filter((_, ii) => ii !== i)); setVig(vig.filter((_, ii) => ii !== i)); }}>Quitar</button>}</td>
                    </tr>))}
                  <tr>
                    <td style={{ ...st.td, color: C.gray }}>Total día</td>
                    {[0, 1, 2, 3, 4, 5, 6].map((d) => <td key={d} style={{ ...st.td, textAlign: "center", fontWeight: 700 }}>{fmt1(turnos.reduce((a, t) => a + Number(t[d] || 0), 0))}</td>)}
                    <td style={{ ...st.td, fontWeight: 700, color: C.tealMid }}>{fmt1(turnos.reduce((a, t) => a + t.reduce((b, x) => b + Number(x || 0), 0), 0))} h</td><td style={st.td}></td><td style={st.td}></td>
                  </tr>
                </tbody>
              </table>
              {turnos.length < 3 && <button style={{ ...st.btn, marginTop: 6 }} onClick={() => { setTurnos([...turnos, ["0", "0", "0", "0", "0", "0", "0"]]); setVig([...vig, { desde: "", hasta: "" }]); }}>＋ Agregar turno</button>}
              <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4 }}>
                Un turno con vigencia (temporada, evento) solo suma horas entre sus fechas; sin fecha de término, rige indefinidamente.
                Los totales de arriba suman todos los turnos; la vista previa de impacto considera los turnos vigentes hoy.</div>
            </> : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
                {campo("velocidad_u_hr", "Velocidad (u/h)", { min: 1 })}
                {campo("turnos_dia", "Turnos por día", { min: 1, max: 3 })}
                {campo("horas_turno", "Horas por turno", { min: 1, max: 12, step: 0.5 })}
                {campo("dias_semana", "Días por semana", { min: 1, max: 7 })}
              </div>)}

            <div style={st.sec}>Impacto en los SKU de la línea</div>
            {!hayCambios ? <div style={{ fontSize: 12, color: C.textMuted }}>Modifica un valor para ver el impacto antes de guardar.</div>
              : impErr ? <div style={{ fontSize: 12, color: C.redDk }}>{impErr}</div>
              : !imp ? <div style={{ fontSize: 12, color: C.textMuted }}>Calculando impacto…</div> : <>
                <div style={{ display: "flex", gap: 18, fontSize: 12.5, flexWrap: "wrap", marginBottom: 8 }}>
                  <span>Capacidad día{dp.calendario ? " (día más largo)" : ""}: {fmtN(da.cap_dia_u)} → <b>{fmtN(dp.cap_dia_u)}</b> u</span>
                  {dp.calendario && <span>Horas semana: {fmt1(da.horas_semana)} → <b>{fmt1(dp.horas_semana)}</b> h</span>}
                  <span>Capacidad semana: {fmtN(da.cap_sem_u)} → <b>{fmtN(dp.cap_sem_u)}</b> u</span>
                  <span style={{ color: imp.n_nuevos_errores ? C.redDk : C.text }}>Errores nuevos: <b>{imp.n_nuevos_errores}</b></span>
                  <span style={{ color: imp.n_nuevas_advertencias ? C.amberDk : C.text }}>Advertencias nuevas: <b>{imp.n_nuevas_advertencias}</b></span>
                  <span style={{ color: C.tealMid }}>Alertas que se resuelven: <b>{imp.n_resueltas}</b></span>
                </div>
                {imp.skus_afectados.length > 0 && (
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr>{["SKU", "Horas por batch", "Alertas nuevas", "Se resuelven"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
                    <tbody>{imp.skus_afectados.map((x) => (
                      <tr key={x.sku}>
                        <td style={st.td}><b>{x.sku}</b> <span style={{ color: C.textMuted }}>{x.descripcion}</span></td>
                        <td style={{ ...st.td, whiteSpace: "nowrap" }}>{fmt1(x.horas_batch_actual)} → <b>{fmt1(x.horas_batch_propuesto)}</b> h</td>
                        <td style={st.td}><Alertas alertas={x.nuevas} /></td>
                        <td style={st.td}>{x.resueltas.map((a, i) => <div key={i} style={{ fontSize: 11.5, color: C.tealMid }}>✓ {a.mensaje}</div>)}</td>
                      </tr>))}</tbody>
                  </table>
                )}
                {!imp.puede_guardar && <div style={{ background: C.redLt, color: C.redDk, borderRadius: 8, padding: "8px 10px", marginTop: 8, fontSize: 12 }}>
                  <b>No se puede guardar:</b> el cambio genera errores nuevos en SKU de la línea.</div>}
              </>}

            <ListaRecos recos={recos} onUsar={() => {}} editables={[]}
                        auth={auth} onDescartada={(r) => { setRecos(recos.filter((x) => x.id !== r.id)); onGuardado && onGuardado(); }} />

            <div style={st.sec}>Confirmar</div>
            <CamposAuth auth={auth} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, gap: 10 }}>
              <span style={{ fontSize: 11, color: C.textMuted }}>Cambia la capacidad de toda la línea en el plan. Rige desde la próxima corrida.</span>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={st.btn} onClick={onClose}>Cerrar</button>
                <button style={{ ...st.btnPri, opacity: puede ? 1 : .45, cursor: puede ? "pointer" : "not-allowed" }} disabled={!puede} onClick={guardar}>
                  {guardando ? "Guardando…" : "Guardar cambios"}</button>
              </div>
            </div>
            {resultado && <div style={{ marginTop: 10, fontSize: 12.5, color: resultado.ok ? C.tealMid : C.redDk }}>{resultado.texto}</div>}
          </>}
          {tab === "excepciones" && <Excepciones linea={linea.codigo} auth={auth} />}
          {tab === "historial" && <>
            <CamposAuth auth={auth} />
            <div style={{ height: 10 }} />
            <Historial query={`linea=${encodeURIComponent(linea.codigo)}`} auth={auth} onRevertido={onGuardado} />
          </>}
        </div>
      </div>
    </div>
  );
}

// ── Excepciones de capacidad por fecha (sábado trabajado, extensión, día sin producción) ──
const TIPOS_EXC = [["extension", "Extensión de turno"], ["sabado", "Sábado trabajado"], ["domingo_feriado", "Domingo o feriado trabajado"],
                   ["sin_produccion", "Día sin producción"], ["otro", "Otro"]];
function Excepciones({ linea, auth }) {
  const [filas, setFilas] = useState(null), [msg, setMsg] = useState(null);
  const [f, setF] = useState({ fecha: "", horas: "", tipo: "sabado" });
  const cargar = () => api("GET", `/params/excepciones?linea=${encodeURIComponent(linea)}`).then((d) => setFilas(d.excepciones || [])).catch((e) => setMsg(e.message));
  useEffect(() => { cargar(); /* eslint-disable-next-line */ }, [linea]);
  const ok = f.fecha && f.horas !== "" && auth.completa;
  const crear = async () => {
    setMsg(null);
    try {
      await api("POST", "/params/excepciones", { linea, fecha: f.fecha, horas: Number(f.horas), tipo: f.tipo, editor: auth.editor, pin: auth.pin, motivo: auth.motivo });
      auth.recordar(); setMsg("Excepción guardada. Aplica desde la próxima corrida del plan."); setF({ fecha: "", horas: "", tipo: f.tipo }); cargar();
    } catch (e) { setMsg(e.message); }
  };
  const anular = async (x) => {
    setMsg(null);
    if (!(auth.editor.trim().length >= 3 && auth.pin.length >= 4)) return setMsg("Completa tu nombre y el PIN para anular.");
    try { await api("POST", `/params/excepciones/${x.id}/anular`, { editor: auth.editor, pin: auth.pin, motivo: auth.motivo.trim() || "Anulación" }); cargar(); }
    catch (e) { setMsg(e.message); }
  };
  return (
    <div>
      <div style={{ fontSize: 12, color: C.gray, marginBottom: 8 }}>
        Las horas indicadas son el <b>total del día</b> (todos los turnos) y reemplazan al patrón semanal ese día, incluso si es feriado.
        Úsalo para sábados trabajados, extensiones de turno o días sin producción (0 h).</div>
      <div style={{ display: "grid", gridTemplateColumns: "160px 110px 1fr", gap: 10 }}>
        <label style={st.label}>Fecha<input style={st.input} type="date" value={f.fecha} onChange={(e) => setF({ ...f, fecha: e.target.value })} /></label>
        <label style={st.label}>Horas del día<input style={st.input} type="number" min="0" max="24" step="0.5" value={f.horas} onChange={(e) => setF({ ...f, horas: e.target.value })} /></label>
        <label style={st.label}>Tipo
          <select style={st.input} value={f.tipo} onChange={(e) => setF({ ...f, tipo: e.target.value })}>
            {TIPOS_EXC.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
      </div>
      <CamposAuth auth={auth} />
      <div style={{ marginTop: 8 }}><button style={{ ...st.btnPri, opacity: ok ? 1 : .45 }} disabled={!ok} onClick={crear}>Guardar excepción</button></div>
      {msg && <div style={{ fontSize: 12, marginTop: 6, color: msg.startsWith("Excepción") ? C.tealMid : C.redDk }}>{msg}</div>}
      <div style={st.sec}>Excepciones vigentes</div>
      {!filas ? <div style={{ fontSize: 12, color: C.textMuted }}>Cargando…</div> : filas.length === 0 ? <div style={{ fontSize: 12, color: C.textMuted }}>Sin excepciones.</div> : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Fecha", "Horas", "Tipo", "Motivo", "Quién", ""].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
          <tbody>{filas.map((x) => (
            <tr key={x.id}>
              <td style={st.td}>{new Date(x.fecha + "T12:00:00").toLocaleDateString("es-CL", { weekday: "short", day: "2-digit", month: "2-digit" })}</td>
              <td style={st.td}><b>{fmt1(x.horas)} h</b></td>
              <td style={st.td}>{(TIPOS_EXC.find(([k]) => k === x.tipo) || [0, x.tipo])[1]}</td>
              <td style={{ ...st.td, maxWidth: 260 }}>{x.motivo}</td>
              <td style={st.td}>{x.creado_por}</td>
              <td style={st.td}><button style={{ ...st.btn, padding: "3px 8px", fontSize: 11 }} onClick={() => anular(x)}>Anular</button></td>
            </tr>))}</tbody>
        </table>)}
    </div>
  );
}

// ── Panel resumen de recomendaciones abiertas ─────────────────────────────────
export function PanelRecomendaciones({ recos, onAbrir, onCambio }) {
  const [abierto, setAbierto] = useState(false);
  const [editor, setEditor] = useState(() => { try { return localStorage.getItem(KEY_EDITOR) || ""; } catch { return ""; } });
  const [pin, setPin] = useState(""), [err, setErr] = useState(null);
  if (!recos.length) return null;
  const porPrioridad = recos.reduce((m, r) => ({ ...m, [r.prioridad]: (m[r.prioridad] || 0) + 1 }), {});
  return (
    <div style={{ background: C.purpleLt, border: `1px solid ${C.purple}55`, borderRadius: 10, marginBottom: 12 }}>
      <div onClick={() => setAbierto(!abierto)} style={{ padding: "10px 14px", cursor: "pointer", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: C.purple }}>{abierto ? "▼" : "▶"}</span>
        <b style={{ color: C.purple }}>{recos.length} recomendaciones abiertas del análisis IA</b>
        {Object.entries(porPrioridad).map(([p, n]) => <span key={p} style={st.pill(...(PRIORIDAD[p] || PRIORIDAD.media))}>{n} {p}</span>)}
        <span style={{ fontSize: 11, color: C.gray }}>· clic en una para abrir el editor</span>
      </div>
      {abierto && (
        <div style={{ padding: "0 14px 12px", maxHeight: 360, overflowY: "auto" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, fontSize: 11.5, color: C.gray }}>
            Para descartar:
            <input style={{ ...st.input, width: 180, padding: "4px 6px" }} placeholder="Tu nombre" value={editor} onChange={(e) => setEditor(e.target.value)} />
            <input style={{ ...st.input, width: 90, padding: "4px 6px" }} placeholder="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
            {err && <span style={{ color: C.redDk }}>{err}</span>}
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: 8 }}>
            <thead><tr>{["Prioridad", "Qué", "Dónde", "Vigente", "Sugerido", "Motivo", ""].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
            <tbody>{recos.map((r) => (
              <tr key={r.id} onClick={() => onAbrir(r)} style={{ cursor: "pointer" }}>
                <td style={st.td}><span style={st.pill(...(PRIORIDAD[r.prioridad] || PRIORIDAD.media))}>{r.prioridad}</span></td>
                <td style={{ ...st.td, whiteSpace: "nowrap" }}>{ETIQUETA_CAMPO[r.campo] || r.campo}</td>
                <td style={{ ...st.td, whiteSpace: "nowrap" }}>{r.entidad === "linea" ? `Línea ${r.clave}` : `${r.clave}${r.linea ? ` · ${r.linea}` : ""}`}</td>
                <td style={st.td}>{fmt2(r.valor_vigente)}</td>
                <td style={{ ...st.td, color: C.purple, fontWeight: 700 }}>{r.valor_sugerido != null ? fmt2(r.valor_sugerido) : (r.rango || "—")}</td>
                <td style={{ ...st.td, fontSize: 11.5, color: C.gray }}>{r.motivo}</td>
                <td style={st.td}><button style={{ ...st.btn, padding: "3px 8px", fontSize: 11 }}
                  onClick={async (e) => { e.stopPropagation(); setErr(null);
                    try { if (await descartarReco(r, editor, pin)) onCambio && onCambio(); } catch (x) { setErr(x.message); } }}>Descartar</button></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
