// LoAprendido.jsx — Capa de aprendizaje: qué sabe el sistema y de dónde lo sacó.
//   1) Capacidad teórica vs demostrada por línea (conocimiento empírico, con confianza)
//   2) Intervenciones: qué se cambió, qué se esperaba, qué pasó y el veredicto
//   3) Efectividad por palanca (cuántas funcionaron / no / no concluyentes)
//   4) Decisiones: casos por origen y decisión, motivos de descarte, acciones pendientes
import React, { useEffect, useState } from "react";

const API = process.env.REACT_APP_API_BASE || "";
const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56", purple: "#534AB7", purpleLt: "#EEEDFE",
  amber: "#EF9F27", amberLt: "#FAEEDA", amberDk: "#854F0B", red: "#E24B4A", redLt: "#FCEBEB", redDk: "#A32D2D",
  gray: "#5F5E5A", grayLt: "#F1EFE8", border: "#D3D1C7", text: "#2C2C2A", muted: "#888780", blue: "#185FA5", blueLt: "#E6F1FB",
};
const VER = {
  funciono: [C.tealLt, C.tealMid, "Funcionó"], funciono_con_efecto_secundario: [C.amberLt, C.amberDk, "Funcionó con efecto secundario"],
  no_funciono: [C.redLt, C.redDk, "No funcionó"], no_concluyente: [C.grayLt, C.gray, "No concluyente"], pendiente: [C.blueLt, C.blue, "Pendiente de evaluar"],
};
const PAL = { param_batch: "Batch mínimo", param_cap_bodega: "Cap. bodega", param_factor: "Factor de velocidad", param_ss: "SS",
  param_velocidad: "Velocidad", turnos: "Turnos", linea_alternativa: "Línea alternativa", ampliacion: "Ampliación", forecast: "Forecast", otro: "Otro" };
const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const ddmm = (s) => (s ? new Date(s).toLocaleDateString("es-CL", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "–");
const st = {
  wrap: { padding: 16, fontFamily: "Arial, sans-serif", color: C.text },
  card: { background: "#fff", border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, marginBottom: 12 },
  h3: { margin: "0 0 4px", fontSize: 15 }, cap: { margin: "0 0 10px", fontSize: 12, color: C.gray },
  pill: (bg, col) => ({ display: "inline-block", fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: 10, background: bg, color: col, whiteSpace: "nowrap" }),
  th: { textAlign: "left", fontSize: 11, color: C.muted, padding: "5px 8px", borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap" },
  td: { fontSize: 12.5, padding: "6px 8px", borderBottom: `1px solid ${C.grayLt}`, verticalAlign: "top" },
  kpi: { flex: "1 1 150px", background: C.grayLt, borderRadius: 10, padding: "10px 12px" },
};

function BarraCapacidad({ x }) {
  const max = 2, w = 220, esc = (v) => Math.min(v || 0, max) / max * w;
  return (
    <svg width={w + 10} height={22}>
      <rect x={0} y={7} width={esc(x.p90)} height={8} fill={C.grayLt} rx={2} />
      <rect x={esc(x.p10)} y={7} width={Math.max(1, esc(x.p90) - esc(x.p10))} height={8} fill="#CFE8DE" rx={2}>
        <title>{`p10 ${pct(x.p10)} · p90 ${pct(x.p90)}`}</title></rect>
      <line x1={esc(1)} x2={esc(1)} y1={2} y2={20} stroke={C.red} strokeDasharray="3 2" />
      <circle cx={esc(x.p50)} cy={11} r={4} fill={C.gray}><title>{`semana normal (p50) ${pct(x.p50)}`}</title></circle>
      <circle cx={esc(x.valor_empirico)} cy={11} r={5} fill={C.teal}><title>{`3 mejores semanas ${pct(x.valor_empirico)}`}</title></circle>
    </svg>
  );
}

export default function LoAprendido() {
  const [d, setD] = useState(null), [err, setErr] = useState(null), [abierta, setAbierta] = useState(null);
  useEffect(() => {
    fetch(`${API}/aprendizaje/resumen`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setD).catch((e) => setErr(e.message));
  }, []);
  if (err) return <div style={st.wrap}><div style={{ ...st.card, color: C.redDk }}>{err}</div></div>;
  if (!d) return <div style={st.wrap}><div style={st.card}>Cargando base de conocimiento…</div></div>;

  const cap = d.conocimiento.filter((x) => x.metrica === "capacidad_semanal_pct");
  const ivs = d.intervenciones;
  const evaluadas = ivs.filter((x) => x.veredicto !== "pendiente");
  const funcionaron = evaluadas.filter((x) => x.veredicto.startsWith("funciono")).length;
  const efect = {};
  d.efectividad.forEach((e) => { (efect[e.palanca] = efect[e.palanca] || {})[e.veredicto] = e.n; });
  const nCasos = d.casos.reduce((a, x) => a + x.n, 0);
  const porDecision = d.casos.reduce((m, x) => ({ ...m, [x.decision]: (m[x.decision] || 0) + x.n }), {});
  const auto = d.casos.filter((x) => x.origen === "automatico").reduce((a, x) => a + x.n, 0);

  return (
    <div style={st.wrap}>
      <h2 style={{ margin: "0 0 2px", fontSize: 20 }}>Base de conocimiento</h2>
      <p style={{ margin: "0 0 12px", fontSize: 12.5, color: C.gray }}>
        Lo que el sistema sabe a partir de los datos reales y de las decisiones tomadas: capacidad real de cada línea,
        qué cambios funcionaron y por qué se descartaron recomendaciones. Esta memoria es la que usa la IA en cada análisis.
      </p>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={st.kpi}><div style={{ fontSize: 11, color: C.gray }}>Intervenciones registradas</div><div style={{ fontSize: 22, fontWeight: 700 }}>{ivs.length}</div>
          <div style={{ fontSize: 11, color: C.muted }}>{ivs.length - evaluadas.length} pendientes de evaluar</div></div>
        <div style={st.kpi}><div style={{ fontSize: 11, color: C.gray }}>Funcionaron</div><div style={{ fontSize: 22, fontWeight: 700, color: C.tealMid }}>{funcionaron} de {evaluadas.length}</div>
          <div style={{ fontSize: 11, color: C.muted }}>de las ya evaluadas</div></div>
        <div style={st.kpi}><div style={{ fontSize: 11, color: C.gray }}>Casos de análisis</div><div style={{ fontSize: 22, fontWeight: 700 }}>{nCasos}</div>
          <div style={{ fontSize: 11, color: C.muted }}>{auto} automáticos · {porDecision.pendiente || 0} por decidir</div></div>
        <div style={st.kpi}><div style={{ fontSize: 11, color: C.gray }}>Acciones pendientes</div><div style={{ fontSize: 22, fontWeight: 700, color: d.acciones_pendientes.length ? C.amberDk : C.text }}>{d.acciones_pendientes.length}</div>
          <div style={{ fontSize: 11, color: C.muted }}>aceptadas, aún sin ejecutar</div></div>
      </div>

      <div style={st.card}>
        <h3 style={st.h3}>Capacidad real vs parametrizada</h3>
        <p style={st.cap}>100% (línea roja) = capacidad con que planifica el sistema. <b style={{ color: C.teal }}>●</b> promedio de las 3 mejores semanas ·
          <b style={{ color: C.gray }}> ●</b> semana normal (mediana) · banda = rango habitual (p10–p90). Últimas 12 semanas.</p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Línea", "Mejores semanas", "Semana normal", "Rango", "Semanas", "Confianza", "Lectura"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
          <tbody>{cap.map((x) => (
            <tr key={x.clave}>
              <td style={{ ...st.td, fontWeight: 700 }}>{x.clave}</td>
              <td style={{ ...st.td, fontWeight: 700, color: x.valor_empirico > 1.05 ? C.amberDk : C.text }}>{pct(x.valor_empirico)}</td>
              <td style={st.td}>{pct(x.p50)}</td>
              <td style={st.td}><BarraCapacidad x={x} /></td>
              <td style={st.td}>{x.n_obs}</td>
              <td style={st.td}><span style={st.pill(x.confianza === "alta" ? C.tealLt : C.amberLt, x.confianza === "alta" ? C.tealMid : C.amberDk)}>{x.confianza}</span></td>
              <td style={{ ...st.td, fontSize: 12, color: C.gray }}>
                {x.p50 > 1.05 ? "Opera habitualmente sobre su capacidad parametrizada: revisar turnos reales."
                  : x.valor_empirico > 1.05 ? "Extiende en semanas puntuales de alta demanda."
                  : x.valor_empirico < 0.5 ? "Holgura amplia." : "Dentro de lo parametrizado."}</td>
            </tr>))}</tbody>
        </table>
      </div>

      <div style={st.card}>
        <h3 style={st.h3}>Intervenciones: qué se cambió y qué pasó</h3>
        <p style={st.cap}>Se evalúan solas a los 7 días (preliminar) y a los 14 (veredicto), comparando el plan antes y después contra el resto de los SKU (grupo de control).</p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{["Fecha", "Palanca", "Dónde", "Veredicto", "Lección"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
          <tbody>{ivs.map((x) => (
            <React.Fragment key={x.id}>
              <tr onClick={() => setAbierta(abierta === x.id ? null : x.id)} style={{ cursor: "pointer" }}>
                <td style={{ ...st.td, whiteSpace: "nowrap" }}>{ddmm(x.aplicado_en || x.creado_en)}</td>
                <td style={st.td}>{PAL[x.palanca] || x.palanca}</td>
                <td style={st.td}>{x.linea || "–"}{x.skus?.length ? <span style={{ color: C.muted }}> · {x.skus.length} SKU</span> : ""}{x.caso_id ? <span style={{ color: C.muted }}> · caso #{x.caso_id}</span> : ""}</td>
                <td style={st.td}><span style={st.pill(...(VER[x.veredicto] || VER.pendiente).slice(0, 2))}>{(VER[x.veredicto] || VER.pendiente)[2]}</span>
                  {x.veredicto === "pendiente" && x.evaluacion?.etapa === "preliminar" && <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>preliminar: {(VER[x.evaluacion.veredicto] || [])[2]}</div>}</td>
                <td style={{ ...st.td, fontSize: 12, color: C.gray }}>{x.aprendizaje || x.evaluacion?.texto || x.hipotesis}</td>
              </tr>
              {abierta === x.id && (
                <tr><td colSpan={5} style={{ ...st.td, background: C.grayLt, fontSize: 12 }}>
                  <div><b>Hipótesis:</b> {x.hipotesis}</div>
                  {x.evaluacion && <div style={{ marginTop: 4 }}><b>Evaluación automática ({x.evaluacion.etapa}):</b> {x.evaluacion.texto} · planes #{x.evaluacion.planes?.join(" → #")}</div>}
                  {x.evaluacion_manual && <div style={{ marginTop: 4 }}><b>Evaluación manual:</b> {x.evaluacion_manual.metodo} · planes {(x.evaluacion_manual.planes || []).join(", ")}</div>}
                  {x.efecto_observado && <div style={{ marginTop: 4, color: C.muted }}>Efecto observado: {JSON.stringify(x.efecto_observado)}</div>}
                  <div style={{ marginTop: 4, color: C.muted }}>{x.evaluado_por ? `Evaluado por ${x.evaluado_por} el ${ddmm(x.evaluado_en)}` : "Sin evaluar todavía"}</div>
                </td></tr>)}
            </React.Fragment>))}</tbody>
        </table>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))", gap: 12 }}>
        <div style={st.card}>
          <h3 style={st.h3}>Efectividad por palanca</h3>
          <p style={st.cap}>Con el tiempo, esta tabla dice qué palancas conviene probar primero en cada tipo de caso.</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>{["Palanca", "Funcionó", "Con efecto 2°", "No funcionó", "No concluyente", "Pendiente"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
            <tbody>{Object.entries(efect).map(([p, v]) => (
              <tr key={p}><td style={{ ...st.td, fontWeight: 700 }}>{PAL[p] || p}</td>
                {["funciono", "funciono_con_efecto_secundario", "no_funciono", "no_concluyente", "pendiente"].map((k) => <td key={k} style={st.td}>{v[k] || "–"}</td>)}</tr>))}</tbody>
          </table>
        </div>
        <div style={st.card}>
          <h3 style={st.h3}>Recomendaciones descartadas y por qué</h3>
          <p style={st.cap}>Los motivos de descarte también enseñan: la IA los ve en los próximos análisis de la línea.</p>
          {d.descartes.length === 0 ? <div style={{ fontSize: 12, color: C.muted }}>Sin descartes todavía.</div> : d.descartes.map((x) => (
            <div key={x.id} style={{ fontSize: 12.5, padding: "5px 0", borderBottom: `1px solid ${C.grayLt}` }}>
              <b>{x.linea}</b> · caso #{x.id} · {ddmm(x.decision_en)} · {x.decision_por}<div style={{ color: C.gray }}>{x.decision_motivo}</div></div>))}
        </div>
      </div>

      {d.acciones_pendientes.length > 0 && (
        <div style={st.card}>
          <h3 style={st.h3}>Acciones aceptadas pendientes</h3>
          <p style={st.cap}>Se cierran en Control → Análisis de Línea (en el caso) o, si son de parámetros, al aplicarlas en Herramientas → Parámetros.</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>{["Desde", "Línea", "Caso", "Palanca", "Acción"].map((h) => <th key={h} style={st.th}>{h}</th>)}</tr></thead>
            <tbody>{d.acciones_pendientes.map((a) => (
              <tr key={a.id}><td style={st.td}>{ddmm(a.creado_en)}</td><td style={st.td}><b>{a.linea}</b></td><td style={st.td}>#{a.caso_id}</td>
                <td style={st.td}>{a.palanca}{a.recomendaciones ? " (en el panel)" : ""}</td><td style={{ ...st.td, color: C.gray }}>{a.accion}</td></tr>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}
