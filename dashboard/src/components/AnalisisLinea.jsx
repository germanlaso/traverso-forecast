// AnalisisLinea.jsx — Análisis de Línea (MVP 1).
// 1) Semáforo de líneas: carga requerida vs programada vs demostrada (GET /analisis/lineas)
// 2) "Analizar línea": diagnóstico + palancas en orden de esfuerzo + recomendación IA (POST .../analizar)
// 3) Ficha del caso y decisión (aceptar / parcial / descartar) con PIN; los cambios de parámetros
//    propuestos van al panel de parámetros como recomendaciones. Nada se aplica solo.
import React, { useEffect, useState } from "react";

const API = process.env.REACT_APP_API_BASE || "";
const KEY_EDITOR = "params_editor";
const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56", blue: "#185FA5", blueLt: "#E6F1FB",
  purple: "#534AB7", purpleLt: "#EEEDFE", amber: "#EF9F27", amberLt: "#FAEEDA", amberDk: "#854F0B",
  red: "#E24B4A", redLt: "#FCEBEB", redDk: "#A32D2D", gray: "#5F5E5A", grayLt: "#F1EFE8",
  border: "#D3D1C7", text: "#2C2C2A", muted: "#888780",
};
const SEM = { rojo: [C.redLt, C.redDk, "No cumple"], ambar: [C.amberLt, C.amberDk, "En riesgo"], verde: [C.tealLt, C.tealMid, "OK"] };
const PALANCA = { parametros: "Parámetros", turnos: "Turnos", linea_alternativa: "Línea alternativa", ampliacion: "Ampliación", forecast: "Forecast", otro: "Otro" };
const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const h1 = (v) => (v == null ? "–" : Number(v).toLocaleString("es-CL", { maximumFractionDigits: 1 }));
const ddmm = (s) => (s ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : "");

const st = {
  wrap: { padding: 16, fontFamily: "Arial, sans-serif", color: C.text },
  card: { background: "#fff", border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, marginBottom: 12 },
  pill: (bg, col) => ({ display: "inline-block", fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: 10, background: bg, color: col, whiteSpace: "nowrap" }),
  btn: { padding: "6px 12px", border: `1px solid ${C.border}`, borderRadius: 6, background: "#fff", cursor: "pointer", fontSize: 12.5 },
  btnPri: { padding: "7px 14px", border: "none", borderRadius: 6, background: C.teal, color: "#fff", cursor: "pointer", fontSize: 12.5, fontWeight: 700 },
  th: { textAlign: "left", fontSize: 11, color: C.muted, padding: "5px 8px", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" },
  td: { fontSize: 12.5, padding: "6px 8px", borderBottom: `1px solid ${C.grayLt}`, verticalAlign: "top" },
  sec: { fontSize: 11, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: .4, margin: "14px 0 6px" },
  input: { padding: "6px 8px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, width: "100%", boxSizing: "border-box" },
};

async function api(method, path, body) {
  const r = await fetch(`${API}${path}`, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  let d = null; try { d = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : d?.detail?.mensaje || `HTTP ${r.status}`);
  return d;
}

// Mini gráfico por semana: barra = carga requerida, marca = uso programado, línea = 100%
function Semanas({ semanas, demostrada }) {
  const W = 300, H = 46, n = semanas.length, bw = W / n, max = 1.6;
  const y = (v) => H - 6 - Math.min(v, max) / max * (H - 12);
  return (
    <svg viewBox={`0 0 ${W} ${H + 12}`} width="100%" style={{ maxWidth: 320 }}>
      <line x1={0} x2={W} y1={y(1)} y2={y(1)} stroke={C.red} strokeDasharray="3 3" />
      {demostrada && <line x1={0} x2={W} y1={y(demostrada)} y2={y(demostrada)} stroke={C.teal} strokeDasharray="2 3" />}
      {semanas.map((s, i) => {
        const v = s.carga_requerida || 0, col = v > 0.95 ? C.red : v > 0.85 ? C.amber : C.teal;
        return (
          <g key={s.semana}>
            <title>{`Sem ${s.semana_iso}${s.parcial ? ` (en curso: ${s.dias_habiles} días hábiles, ${ddmm(s.desde)}–${ddmm(s.hasta)})` : ""}: requerida ${pct(s.carga_requerida)} (${h1(s.horas_requeridas)} h de ${h1(s.horas_nominales)} h nominales) · programada ${pct(s.uso_programado)}`}</title>
            <rect x={i * bw + bw * .2} y={y(v)} width={bw * .6} height={H - 6 - y(v)} fill={col} opacity={.75} rx={2} />
            <rect x={i * bw + bw * .12} y={y(s.uso_programado || 0) - 1} width={bw * .76} height={2.5} fill={C.text} />
            <text x={i * bw + bw / 2} y={H + 9} fontSize={9} textAnchor="middle" fill={C.muted}>S{s.semana_iso}{s.parcial ? "*" : ""}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Caso({ caso, onCerrar, onDecidido }) {
  const r = caso.recomendacion || {}, dg = caso.diagnostico || {}, pal = caso.escenarios || [];
  const [editor, setEditor] = useState(() => { try { return localStorage.getItem(KEY_EDITOR) || ""; } catch { return ""; } });
  const [pin, setPin] = useState(""), [motivo, setMotivo] = useState(""), [msg, setMsg] = useState(null), [enviando, setEnviando] = useState(false);
  // acciones marcadas para aceptar (por defecto todas)
  const [marcadas, setMarcadas] = useState(() => new Set((r.acciones || []).map((a) => a.orden)));
  const [comentarios, setComentarios] = useState({});
  const nAcc = (r.acciones || []).length;
  const decidir = async (decision) => {
    setMsg(null); setEnviando(true);
    try {
      const d = await api("POST", `/analisis/casos/${caso.id}/decision`,
        { decision, motivo, editor, pin, enviar_al_panel: true, acciones_aceptadas: decision === "parcial" ? [...marcadas] : null });
      try { localStorage.setItem(KEY_EDITOR, editor.trim()); } catch { /* sin storage */ }
      setMsg({ ok: true, t: `Decisión registrada (${d.decision}): ${d.acciones_aceptadas} acción(es) aceptada(s).` +
        (d.recomendaciones_creadas ? ` ${d.recomendaciones_creadas} cambio(s) de parámetros enviados a Herramientas → Parámetros.` : "") });
      onDecidido && onDecidido();
    } catch (e) { setMsg({ ok: false, t: e.message }); } finally { setEnviando(false); }
  };
  const resolver = async (accion, estado) => {
    setMsg(null);
    try {
      await api("POST", `/analisis/acciones/${accion.id}/estado`, { estado, comentario: comentarios[accion.id] || "", editor, pin });
      try { localStorage.setItem(KEY_EDITOR, editor.trim()); } catch { /* sin storage */ }
      onDecidido && onDecidido();
    } catch (e) { setMsg({ ok: false, t: e.message }); }
  };
  const accDe = (orden) => (caso.acciones || []).find((x) => x.orden === orden);
  // (11-11-2026) validación nocturna con el solver (2 semillas, sin promover)
  const [nivelVal, setNivelVal] = useState(dg.primera_palanca_suficiente && dg.primera_palanca_suficiente <= 3 ? dg.primera_palanca_suficiente : 2);
  const validar = async () => {
    setMsg(null);
    try {
      const d = await api("POST", `/analisis/casos/${caso.id}/validar`, { solicitado_por: editor || "planificador", nivel: nivelVal });
      setMsg({ ok: true, t: `Validación #${d.id} programada (${d.descripcion}). ${d.aviso}` });
      onDecidido && onDecidido();
    } catch (e) { setMsg({ ok: false, t: e.message }); }
  };
  const VAL = { evita_quiebres: [C.tealLt, C.tealMid, "Evita quiebres"], empeora: [C.redLt, C.redDk, "Empeora"],
                no_concluyente: [C.grayLt, C.gray, "No concluyente"] };
  const ESTADO_ACC = { aceptada: [C.amberLt, C.amberDk, "Pendiente"], hecha: [C.tealLt, C.tealMid, "Hecha"],
                       rechazada: [C.grayLt, C.gray, "No aceptada"], descartada: [C.grayLt, C.gray, "Descartada"] };
  const decidido = !!caso.decision;
  return (
    <div style={{ ...st.card, borderColor: C.purple, borderWidth: 2 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: .4 }}>Caso #{caso.id} · {caso.linea} · {new Date(caso.creado_en).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" })} · {caso.solicitado_por}</div>
          <div style={{ fontSize: 16, fontWeight: 700, margin: "4px 0" }}>{r.causa_principal || "Diagnóstico"}</div>
        </div>
        <span onClick={onCerrar} style={{ cursor: "pointer", fontSize: 18, color: C.gray }} title="Cerrar">✕</span>
      </div>
      {caso.estado === "error" && <div style={{ color: C.redDk }}>El análisis falló: {caso.error}</div>}
      {r.resumen && <p style={{ fontSize: 13.5, margin: "6px 0 10px" }}>{r.resumen}</p>}
      {r.alerta_forecast && (
        <div style={{ background: C.amberLt, color: C.amberDk, borderRadius: 8, padding: "8px 10px", fontSize: 12.5, marginBottom: 10 }}>
          <b>Revisar el forecast:</b> {r.alerta_forecast}</div>
      )}

      <div style={st.sec}>Acciones recomendadas (en orden de esfuerzo)</div>
      {(r.acciones || []).map((a) => { const ac = accDe(a.orden); return (
        <div key={a.orden} style={{ display: "flex", gap: 10, padding: "8px 10px", border: `1px solid ${C.grayLt}`, borderRadius: 8, marginBottom: 6,
                                    opacity: ac && ac.estado === "rechazada" ? .55 : 1 }}>
          {!caso.decision && (
            <input type="checkbox" style={{ marginTop: 4 }} checked={marcadas.has(a.orden)} title="Marcar para aceptar"
                   onChange={(e) => { const n = new Set(marcadas); e.target.checked ? n.add(a.orden) : n.delete(a.orden); setMarcadas(n); }} />)}
          <div style={{ fontSize: 18, fontWeight: 700, color: C.purple, minWidth: 18 }}>{a.orden}</div>
          <div style={{ flex: 1, fontSize: 12.5 }}>
            <span style={st.pill(C.purpleLt, C.purple)}>{PALANCA[a.palanca] || a.palanca}</span>
            <div style={{ fontWeight: 700, margin: "4px 0 2px" }}>{a.accion}</div>
            <div style={{ color: C.gray }}><b>Efecto:</b> {a.efecto_esperado} · <b>Costo o riesgo:</b> {a.costo_o_riesgo}</div>
            {(a.cambios_parametros || []).length > 0 && (
              <div style={{ color: C.muted, marginTop: 3 }}>Cambios propuestos: {a.cambios_parametros.map((c) => `${c.sku} ${c.campo}=${c.valor}`).join(" · ")}</div>
            )}
            {ac && (
              <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={st.pill(...ESTADO_ACC[ac.estado])}>{ESTADO_ACC[ac.estado][2]}</span>
                {ac.comentario && <span style={{ color: C.gray }}>{ac.comentario}{ac.resuelto_por ? ` · ${ac.resuelto_por}` : ""}</span>}
                {ac.estado === "aceptada" && ac.recomendaciones > 0 && (
                  <span style={{ color: C.amberDk }}>Aplicar en Herramientas → Parámetros (recomendación "Análisis de línea #{caso.id}")</span>)}
                {ac.estado === "aceptada" && !ac.recomendaciones && (<>
                  <input style={{ ...st.input, width: 280, padding: "4px 6px", fontSize: 12 }} placeholder="Qué se hizo / por qué se descarta"
                         value={comentarios[ac.id] || ""} onChange={(e) => setComentarios({ ...comentarios, [ac.id]: e.target.value })} />
                  <button style={{ ...st.btn, padding: "3px 9px", fontSize: 11.5 }} onClick={() => resolver(ac, "hecha")}>Marcar hecha</button>
                  <button style={{ ...st.btn, padding: "3px 9px", fontSize: 11.5 }} onClick={() => resolver(ac, "descartada")}>Descartar</button>
                </>)}
              </div>)}
          </div>
        </div>
      ); })}
      {r.pregunta_para_produccion && <div style={{ fontSize: 12.5, background: C.blueLt, color: C.blue, borderRadius: 8, padding: "8px 10px", marginTop: 6 }}><b>Para Producción:</b> {r.pregunta_para_produccion}</div>}

      <details style={{ marginTop: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 12.5, color: C.gray }}>Ver detalle del diagnóstico (causas, palancas y evidencia)</summary>
        <div style={st.sec}>Causas detectadas</div>
        {(dg.causas || []).map((c) => <div key={c.codigo} style={{ fontSize: 12.5, marginBottom: 4 }}><b>{c.titulo}.</b> <span style={{ color: C.gray }}>{c.evidencia}</span></div>)}
        <div style={st.sec}>Palancas · necesidad {h1(dg.evidencia?.necesidad_h_horizonte)} h en {dg.evidencia?.semanas_horizonte} semanas</div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Nivel", "Palanca", "Aporte (h)", "Acumulado (h)", "¿Alcanza?", "Detalle"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
          <tbody>{pal.map((p) => (
            <tr key={p.nivel} style={{ background: dg.primera_palanca_suficiente === p.nivel ? C.tealLt : "transparent" }}>
              <td style={st.td}>{p.nivel}</td><td style={st.td}><b>{p.titulo}</b></td>
              <td style={st.td}>{h1(p.aporte_h)}</td><td style={st.td}>{h1(p.acumulado_h)}</td>
              <td style={st.td}>{p.cubre_acumulado ? "✓" : "—"}</td>
              <td style={{ ...st.td, color: C.gray }}>{p.equivale_a ? `${p.equivale_a}. ` : ""}{(p.candidatas || []).map((c) => `${c.linea} (${h1(c.horas_libres_sem)} h/sem, ${c.estado})`).join(" · ")}{p.candidatas?.length ? ". " : ""}{p.nota}</td>
            </tr>))}</tbody>
        </table>
        <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>{dg.metodo}{r._meta ? ` · IA: ${r._meta.modelo}, ${r._meta.segundos} s, US$ ${r._meta.costo_usd}` : ""}</div>
      </details>

      <div style={st.sec}>Validación con el solver</div>
      <div style={{ fontSize: 12, color: C.gray, marginBottom: 6 }}>
        El análisis estima las palancas con un modelo de horas. Para confirmarlas, el sistema puede correr esta noche el plan completo
        con la palanca aplicada (sin cambiar nada real), con 2 semillas, y compararlo contra el plan sin cambios.</div>
      {(caso.validaciones || []).map((v) => (
        <div key={v.id} style={{ border: `1px solid ${C.grayLt}`, borderRadius: 8, padding: "7px 10px", marginBottom: 6, fontSize: 12.5 }}>
          <b>#{v.id}</b> · palancas 1 a {v.nivel} · {v.descripcion} ·{" "}
          {v.estado === "lista" && v.resultado?.veredicto
            ? <span style={st.pill(...(VAL[v.resultado.veredicto] || VAL.no_concluyente).slice(0, 2))}>{(VAL[v.resultado.veredicto] || VAL.no_concluyente)[2]}</span>
            : <span style={st.pill(C.blueLt, C.blue)}>{v.estado}</span>}
          {v.resultado?.texto && <div style={{ color: C.gray, marginTop: 3 }}>{v.resultado.texto}
            {v.resultado.consistente_entre_semillas === false && " Las semillas no coinciden: el efecto está dentro del ruido del solver."}</div>}
          {v.estado === "programada" && <div style={{ color: C.muted, marginTop: 3 }}>Se ejecuta desde las 21:00, en la cola del solver.</div>}
        </div>))}
      {!(caso.validaciones || []).some((v) => ["programada", "ejecutando"].includes(v.estado)) && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
          <select style={{ ...st.input, width: 280 }} value={nivelVal} onChange={(e) => setNivelVal(Number(e.target.value))}>
            <option value={1}>Palanca 1: parámetros</option>
            <option value={2}>Palancas 1 y 2: parámetros + horas extra</option>
            <option value={3}>Palancas 1 a 3: + línea alternativa (hipótesis)</option>
          </select>
          <button style={st.btn} onClick={validar}>Validar con solver esta noche</button>
        </div>)}

      <div style={st.sec}>Tu decisión</div>
      {decidido ? (<>
        <div style={{ fontSize: 12.5 }}><b>{caso.decision}</b> por {caso.decision_por}: {caso.decision_motivo}
          <span style={{ marginLeft: 8, ...st.pill(caso.estado === "cerrado" ? C.tealLt : C.amberLt, caso.estado === "cerrado" ? C.tealMid : C.amberDk) }}>
            {caso.estado === "en_seguimiento" ? "en seguimiento" : caso.estado}</span></div>
        {(caso.acciones || []).some((x) => x.estado === "aceptada" && !x.recomendaciones) && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 120px", gap: 8, marginTop: 8, maxWidth: 420 }}>
            <input style={st.input} placeholder="Tu nombre" value={editor} onChange={(e) => setEditor(e.target.value)} />
            <input style={st.input} placeholder="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
          </div>)}
      </>) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 120px 2fr", gap: 8 }}>
            <input style={st.input} placeholder="Tu nombre" value={editor} onChange={(e) => setEditor(e.target.value)} />
            <input style={st.input} placeholder="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
            <input style={st.input} placeholder="Motivo (también si descartas: el sistema aprende de eso)" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button style={st.btnPri} disabled={enviando} onClick={() => decidir("aceptada")}>Aceptar todo</button>
            <button style={st.btn} disabled={enviando || marcadas.size === 0 || marcadas.size === nAcc}
                    title="Acepta solo las acciones marcadas" onClick={() => decidir("parcial")}>
              Aceptar marcadas ({marcadas.size} de {nAcc})</button>
            <button style={{ ...st.btn, color: C.redDk }} disabled={enviando} onClick={() => decidir("descartada")}>Descartar</button>
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>
            Nada se aplica solo. Las acciones aceptadas con cambios de parámetros quedan como recomendaciones en Herramientas → Parámetros;
            las demás (turnos, línea alternativa, forecast) quedan pendientes en este caso hasta marcarlas hechas o descartadas.
            Cada acción aceptada se registra para evaluar después su efecto.</div>
        </>
      )}
      {msg && <div style={{ marginTop: 8, fontSize: 12.5, color: msg.ok ? C.tealMid : C.redDk }}>{msg.t}</div>}
    </div>
  );
}

export default function AnalisisLinea() {
  const [data, setData] = useState(null), [error, setError] = useState(null);
  const [analizando, setAnalizando] = useState(null), [caso, setCaso] = useState(null), [casos, setCasos] = useState([]);
  const [abiertas, setAbiertas] = useState({});          // {linea: true} -> fila de análisis desplegada
  const cargar = () => {
    api("GET", "/analisis/lineas?semanas=6").then(setData).catch((e) => setError(e.message));
    api("GET", "/analisis/casos?limit=200").then((d) => setCasos(d.casos || [])).catch(() => {});
  };
  useEffect(() => { cargar(); }, []);   // eslint-disable-line

  const analizar = async (linea) => {
    let quien = ""; try { quien = localStorage.getItem(KEY_EDITOR) || ""; } catch { /* */ }
    if (!quien) quien = window.prompt("¿Quién solicita el análisis?") || "";
    if (quien.trim().length < 3) return;
    setAnalizando(linea); setCaso(null); setError(null);
    try { const c = await api("POST", `/analisis/lineas/${encodeURIComponent(linea)}/analizar`, { solicitado_por: quien, con_ia: true }); setCaso(c); cargar(); }
    catch (e) { setError(e.message); } finally { setAnalizando(null); }
  };
  // la ficha del caso se muestra arriba de la tabla: llevar la vista hasta ella
  const abrirCaso = (id) => api("GET", `/analisis/casos/${id}`)
    .then((c) => { setCaso(c); window.scrollTo({ top: 0, behavior: "smooth" }); })
    .catch((e) => setError(e.message));

  const rojos = (data?.lineas || []).filter((l) => l.semaforo === "rojo").length;
  const casosDe = (linea) => casos.filter((c) => c.linea === linea);
  return (
    <div style={st.wrap}>
      <h2 style={{ margin: "0 0 2px", fontSize: 20 }}>Análisis de Línea</h2>
      <p style={{ margin: "0 0 12px", fontSize: 12.5, color: C.gray }}>
        ¿Puede cada línea cumplir lo que viene? <b>Barra</b> = carga requerida: producción neta que hace falta (demanda − stock disponible, manteniendo el SS) · <b>marca negra</b> = lo programado en el plan ·
        <span style={{ color: C.red }}> línea roja</span> = capacidad nominal · <span style={{ color: C.teal }}>línea verde</span> = capacidad demostrada. * = semana en curso: solo cuentan los días hábiles que quedan.
        {data && ` Plan #${data.plan?.id}.`}
      </p>
      {error && <div style={{ ...st.card, background: C.redLt, color: C.redDk }}>{error}</div>}
      {analizando && <div style={{ ...st.card, background: C.purpleLt, color: C.purple }}>Analizando <b>{analizando}</b>: diagnóstico, palancas y recomendación IA (≈1 minuto)…</div>}
      {caso && <Caso key={caso.id} caso={caso} onCerrar={() => setCaso(null)} onDecidido={() => abrirCaso(caso.id)} />}

      {!data ? <div style={st.card}>Calculando carga por línea…</div> : (
        <div style={st.card}>
          <div style={{ fontSize: 13, marginBottom: 8 }}><b>{rojos}</b> línea(s) que no están pudiendo cumplir en las próximas 3 semanas.</div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>{["Línea", "Estado", "Por qué", "Carga próx. 3 sem", "Demostrada", "Semanas", ""].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
            <tbody>{data.lineas.map((l) => (
              <React.Fragment key={l.linea}>
              <tr>
                <td style={{ ...st.td, fontWeight: 700 }}>{l.linea}</td>
                <td style={st.td}><span style={st.pill(SEM[l.semaforo][0], SEM[l.semaforo][1])}>{SEM[l.semaforo][2]}</span></td>
                <td style={{ ...st.td, fontSize: 12, color: C.gray, maxWidth: 320 }}>{l.motivos.join(" ") || "—"}</td>
                <td style={{ ...st.td, fontWeight: 700 }}>{pct(l.max_carga_requerida_3sem)}</td>
                <td style={st.td}>{pct(l.capacidad_demostrada?.top3)}</td>
                <td style={{ ...st.td, minWidth: 220 }}><Semanas semanas={l.semanas} demostrada={l.capacidad_demostrada?.top3} /></td>
                <td style={{ ...st.td, whiteSpace: "nowrap" }}>
                  {l.semaforo !== "verde" && (
                    <button style={st.btnPri} disabled={!!analizando} onClick={() => analizar(l.linea)}>Analizar</button>)}
                  {casosDe(l.linea).length > 0 && (
                    <button style={{ ...st.btn, marginLeft: 6 }} onClick={() => setAbiertas({ ...abiertas, [l.linea]: !abiertas[l.linea] })}
                            title="Ver los análisis anteriores de esta línea">
                      {abiertas[l.linea] ? "▲" : "▼"} Análisis ({casosDe(l.linea).length}
                      {casosDe(l.linea).filter((c) => !c.decision && c.estado === "listo").length > 0 &&
                        <b style={{ color: C.purple }}> · {casosDe(l.linea).filter((c) => !c.decision && c.estado === "listo").length} por decidir</b>})
                    </button>)}
                </td>
              </tr>
              {abiertas[l.linea] && (
                <tr><td colSpan={7} style={{ ...st.td, background: C.grayLt, padding: "6px 12px" }}>
                  {casosDe(l.linea).map((c) => (
                    <div key={c.id} onClick={() => abrirCaso(c.id)}
                         style={{ display: "flex", gap: 10, padding: "5px 6px", cursor: "pointer", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                      <b style={{ minWidth: 34 }}>#{c.id}</b>
                      <span style={{ minWidth: 92, color: C.gray }}>{new Date(c.creado_en).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" })}</span>
                      <span style={{ minWidth: 80 }}>{c.decision || "pendiente"}</span>
                      <span style={{ minWidth: 76 }}>{c.origen === "automatico"
                        ? <span style={st.pill(C.blueLt, C.blue)} title="Abierto por el sistema después del plan diario">automático</span>
                        : <span style={st.pill(C.grayLt, C.gray)}>manual</span>}</span>
                      <span style={{ color: C.gray, flex: 1 }}>{(c.resumen || c.estado || "").slice(0, 200)}{(c.resumen || "").length > 200 ? "…" : ""}</span>
                    </div>))}
                </td></tr>)}
              </React.Fragment>))}</tbody>
          </table>
        </div>
      )}

    </div>
  );
}
