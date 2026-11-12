// Academia.jsx — Soporte > Academia: rutas de aprendizaje con unidades, cuestionarios, desafíos,
// puntos, insignias por módulo y certificado por ruta. Mostacín acompaña en portada, unidades y logros.
// Identificación por nombre (misma clave que la bitácora) hasta que exista login con Entra ID.
// Backend: /soporte/academia/* (router_soporte.py). La corrección de cuestionarios la hace el backend.
// Props: onAbrirEnAyuda(id) abre un artículo de Ayuda.
import React, { useEffect, useState } from "react";
import MarkdownSoporte, { CS } from "./MarkdownSoporte";
import caraMostacin from "./img/mostacin_cara.png";
import cuerpoMostacin from "./img/mostacin_cuerpo.png";

const API = process.env.REACT_APP_API_BASE || "";
const KEY_NOMBRE = "bitacora_registrado_por";          // mismo nombre que la bitácora
const M = { mostaza: "#F2B705", mostazaLt: "#FFF6D6", mostazaDk: "#8A6500", crema: "#FFFBEF" };

const api = async (metodo, ruta, cuerpo) => {
  const r = await fetch(`${API}${ruta}`, { method: metodo, headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
    body: cuerpo ? JSON.stringify(cuerpo) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
  return d;
};
const leerNombre = () => { try { return localStorage.getItem(KEY_NOMBRE) || ""; } catch { return ""; } };
const guardarNombre = (v) => { try { localStorage.setItem(KEY_NOMBRE, v); } catch { /* sin storage */ } };

const st = {
  wrap: { fontFamily: "Arial, sans-serif", color: CS.text, maxWidth: 1100, margin: "0 auto" },
  card: { background: "#fff", border: `1px solid ${CS.border}`, borderRadius: 12, padding: "16px 20px", marginBottom: 14 },
  btn: { border: "none", background: CS.teal, color: "#fff", borderRadius: 8, padding: "8px 16px", fontSize: 13.5,
    fontWeight: 700, cursor: "pointer" },
  btnSec: { border: `1px solid ${CS.teal}`, background: "#fff", color: CS.tealMid, borderRadius: 8, padding: "7px 14px",
    fontSize: 13, fontWeight: 700, cursor: "pointer" },
  link: { border: "none", background: "transparent", color: CS.tealMid, cursor: "pointer", fontSize: 13, padding: 0 },
};

function Barra({ pct, alto = 8 }) {
  return (
    <div style={{ background: CS.grayLt, borderRadius: alto, height: alto, overflow: "hidden" }} aria-label={`Avance ${pct}%`}>
      <div style={{ width: `${pct}%`, height: "100%", background: pct >= 100 ? CS.teal : M.mostaza, transition: "width .4s" }} />
    </div>
  );
}

function Globo({ children, grande = false }) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <img src={caraMostacin} alt="Mostacín" width={grande ? 56 : 44} height={grande ? 56 : 44} style={{ borderRadius: "50%", flexShrink: 0 }} />
      <div style={{ position: "relative", background: M.mostazaLt, border: `1px solid ${M.mostaza}`, borderRadius: 12,
        padding: "10px 14px", fontSize: 14, lineHeight: 1.5 }}>
        <span style={{ position: "absolute", left: -7, top: 16, width: 12, height: 12, background: M.mostazaLt,
          borderLeft: `1px solid ${M.mostaza}`, borderBottom: `1px solid ${M.mostaza}`, transform: "rotate(45deg)" }} />
        {children}
      </div>
    </div>
  );
}

function abrirCertificado(persona, ruta) {
  const img = new URL(cuerpoMostacin, window.location.href).href;
  const fecha = new Date(ruta.certificado.emitido_en).toLocaleDateString("es-CL", { day: "numeric", month: "long", year: "numeric" });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Certificado ${esc(ruta.titulo)}</title>
<style>@page{size:A4 landscape;margin:0}body{margin:0;font-family:Arial,sans-serif;color:#2C2C2A}
.c{box-sizing:border-box;width:297mm;height:210mm;padding:18mm 22mm;border:10px solid #1D9E75;outline:3px solid #F2B705;outline-offset:-22px;
display:flex;gap:18mm;align-items:center}.t{flex:1}.k{font-size:15px;color:#0F6E56;font-weight:700}
h1{font-size:40px;margin:6px 0 18px}.n{font-size:32px;font-weight:700;border-bottom:2px solid #F2B705;display:inline-block;padding-bottom:4px}
p{font-size:16px;line-height:1.6}.f{font-size:12px;color:#888780;margin-top:26px}img{height:150mm}
.b{position:fixed;top:10px;right:10px}@media print{.b{display:none}}</style></head><body>
<button class="b" onclick="print()">Imprimir / Guardar PDF</button><div class="c"><div class="t">
<div class="k">Traverso S.A. · Academia del Sistema de Planificación</div><h1>Certificado de ruta</h1>
<p>Se certifica que</p><div class="n">${esc(persona.nombre)}</div>
<p>completó la ruta <b>${esc(ruta.titulo)}</b>, con ${ruta.unidades} unidades aprobadas.</p>
<div class="f">Emitido el ${esc(fecha)} · Código de verificación ${esc(ruta.certificado.codigo)}</div></div>
<img src="${img}" alt="Mostacín"></div></body></html>`;
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  window.open(url, "_blank");
}

// ── Identificación ───────────────────────────────────────────────────────────
function Identificacion({ onListo, error }) {
  const [nombre, setNombre] = useState(leerNombre());
  return (
    <div style={{ ...st.card, display: "flex", gap: 24, alignItems: "center", background: M.crema, borderColor: M.mostaza }}>
      <img src={cuerpoMostacin} alt="Mostacín" style={{ height: 200 }} />
      <div style={{ flex: 1 }}>
        <h2 style={{ margin: "0 0 6px", fontSize: 24 }}>Bienvenido a la Academia</h2>
        <p style={{ margin: "0 0 14px", fontSize: 14.5, lineHeight: 1.5, maxWidth: 520 }}>
          Soy Mostacín. Aquí aprendes a usar el sistema paso a paso, con pantallazos reales, cuestionarios cortos e insignias.
          Para guardar tu avance, dime tu nombre y apellido.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Nombre y apellido"
            onKeyDown={(e) => e.key === "Enter" && nombre.trim().length >= 3 && onListo(nombre.trim())}
            style={{ padding: "9px 12px", border: `1px solid ${CS.border}`, borderRadius: 8, fontSize: 14, width: 260 }} />
          <button style={st.btn} disabled={nombre.trim().length < 3} onClick={() => onListo(nombre.trim())}>Comenzar</button>
        </div>
        {error && <p style={{ color: "#A32D2D", fontSize: 13 }}>{error}</p>}
        <p style={{ fontSize: 12, color: CS.muted, marginTop: 10 }}>Usa siempre el mismo nombre: así tu avance te sigue en cualquier equipo.</p>
      </div>
    </div>
  );
}

// ── Portada ──────────────────────────────────────────────────────────────────
function Portada({ persona, rutas, avance, onRuta, onCambiarPersona }) {
  const av = Object.fromEntries((avance?.rutas || []).map((r) => [r.id, r]));
  const insignias = (avance?.rutas || []).flatMap((r) => r.modulos);
  const ganadas = insignias.filter((m) => m.insignia_ganada).length;
  const certs = (avance?.rutas || []).filter((r) => r.certificado).length;
  const fund = av.fundamentos;
  const mensaje = !fund || fund.aprobadas === 0
    ? "Te recomiendo empezar por Fundamentos: en menos de una hora conoces lo esencial del sistema."
    : fund.completa ? "¡Completaste Fundamentos! Sigue con la ruta de tu área." : `Vas en ${fund.aprobadas} de ${fund.unidades} unidades de Fundamentos. ¡Sigue así!`;
  return (
    <>
      <div style={{ display: "flex", gap: 22, alignItems: "flex-end", background: M.crema, border: `1px solid ${M.mostaza}`,
        borderRadius: 14, padding: "18px 22px 0", marginBottom: 16, flexWrap: "wrap" }}>
        <img src={cuerpoMostacin} alt="Mostacín" style={{ height: 190, marginBottom: -1 }} />
        <div style={{ flex: 1, minWidth: 280, paddingBottom: 18 }}>
          <div style={{ fontSize: 13, color: M.mostazaDk, fontWeight: 700 }}>Academia</div>
          <h2 style={{ margin: "2px 0 8px", fontSize: 26 }}>Hola, {persona.nombre.split(" ")[0]}</h2>
          <Globo>{mensaje}</Globo>
          <div style={{ display: "flex", gap: 22, marginTop: 14, flexWrap: "wrap" }}>
            {[["Puntos", avance?.puntos ?? 0], ["Insignias", `${ganadas} de ${insignias.length}`], ["Certificados", certs]].map(([k, v]) => (
              <div key={k}><div style={{ fontSize: 24, fontWeight: 700 }}>{v}</div><div style={{ fontSize: 12, color: CS.gray }}>{k}</div></div>
            ))}
            <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 26 }} aria-label="Insignias">
              {insignias.map((m) => <span key={m.id} title={`${m.titulo}${m.insignia_ganada ? " · ganada" : " · pendiente"}`}
                style={{ filter: m.insignia_ganada ? "none" : "grayscale(1)", opacity: m.insignia_ganada ? 1 : 0.35 }}>{m.insignia}</span>)}
            </div>
          </div>
          <button style={{ ...st.link, fontSize: 12, marginTop: 10 }} onClick={onCambiarPersona}>¿No eres {persona.nombre}? Cambiar</button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
        {rutas.map((r) => {
          const a = av[r.id] || { unidades: 0, aprobadas: 0, avance_pct: 0 };
          const vacia = !r.modulos.length;
          return (
            <div key={r.id} style={{ ...st.card, marginBottom: 0, display: "flex", flexDirection: "column",
              borderTop: `4px solid ${r.id === "fundamentos" ? M.mostaza : CS.teal}`, opacity: vacia ? 0.7 : 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                <h3 style={{ margin: 0, fontSize: 18 }}>{r.titulo}</h3>
                {r.id === "fundamentos" && <span style={{ fontSize: 11, fontWeight: 700, color: M.mostazaDk, background: M.mostazaLt,
                  borderRadius: 10, padding: "2px 8px", whiteSpace: "nowrap" }}>Recomendada para empezar</span>}
              </div>
              <div style={{ fontSize: 12, color: CS.muted, margin: "2px 0 8px" }}>Para: {r.publico}</div>
              <p style={{ fontSize: 13.5, lineHeight: 1.5, margin: "0 0 12px", flex: 1 }}>{r.descripcion}</p>
              {vacia ? <div style={{ fontSize: 13, color: CS.gray }}>Próximamente</div> : (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: CS.gray, marginBottom: 4 }}>
                    <span>{a.aprobadas} de {a.unidades} unidades</span>
                    <span>{r.modulos.map((m) => m.insignia).join(" ")}</span>
                  </div>
                  <Barra pct={a.avance_pct} />
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button style={st.btn} onClick={() => onRuta(r.id)}>{a.aprobadas === 0 ? "Comenzar" : a.completa ? "Repasar" : "Continuar"}</button>
                    {a.certificado && <button style={st.btnSec} onClick={() => abrirCertificado(persona, { ...a, titulo: r.titulo })}>Ver certificado</button>}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ── Ruta ─────────────────────────────────────────────────────────────────────
function VistaRuta({ persona, ruta, avance, onUnidad, onVolver }) {
  const avR = (avance?.rutas || []).find((r) => r.id === ruta.id) || {};
  const avU = avance?.unidades || {};
  return (
    <>
      <button style={st.link} onClick={onVolver}>← Academia</button>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, margin: "6px 0 14px", flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 24 }}>{ruta.titulo}</h2>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: CS.gray, maxWidth: 640 }}>{ruta.descripcion}</p>
        </div>
        <div style={{ width: 260 }}>
          <div style={{ fontSize: 12, color: CS.gray, marginBottom: 4 }}>{avR.aprobadas || 0} de {avR.unidades || 0} unidades · {avR.avance_pct || 0}%</div>
          <Barra pct={avR.avance_pct || 0} alto={10} />
          {avR.certificado && <button style={{ ...st.btnSec, marginTop: 10 }} onClick={() => abrirCertificado(persona, { ...avR, titulo: ruta.titulo })}>Ver certificado</button>}
        </div>
      </div>
      {ruta.modulos.map((m) => {
        const mAv = (avR.modulos || []).find((x) => x.id === m.id) || {};
        return (
          <div key={m.id} style={st.card}>
            <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 10 }}>
              <span style={{ fontSize: 34, filter: mAv.insignia_ganada ? "none" : "grayscale(1)", opacity: mAv.insignia_ganada ? 1 : 0.45 }}>{m.insignia}</span>
              <div style={{ flex: 1 }}>
                <h3 style={{ margin: 0, fontSize: 17 }}>{m.titulo}</h3>
                <div style={{ fontSize: 13, color: CS.gray }}>{m.descripcion}</div>
              </div>
              <span style={{ fontSize: 12, color: mAv.insignia_ganada ? CS.tealMid : CS.muted, fontWeight: 700 }}>
                {mAv.insignia_ganada ? "Insignia ganada" : `${mAv.aprobadas || 0} de ${m.unidades.length}`}</span>
            </div>
            {m.unidades.map((u) => {
              const e = avU[u.id];
              const ok = e && e.estado === "aprobada";
              return (
                <button key={u.id} onClick={() => onUnidad(u.id)} style={{ display: "flex", width: "100%", gap: 12, alignItems: "center",
                  textAlign: "left", border: `1px solid ${CS.grayLt}`, background: ok ? "#F6FBF8" : "#fff", borderRadius: 8,
                  padding: "10px 12px", marginBottom: 6, cursor: "pointer", fontSize: 14 }}>
                  <span style={{ width: 24, height: 24, borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center",
                    justifyContent: "center", fontSize: 13, fontWeight: 700, color: "#fff",
                    background: ok ? CS.teal : e ? M.mostaza : CS.border }}>{ok ? "✓" : e ? "…" : ""}</span>
                  <span style={{ flex: 1 }}><b>{u.titulo}</b><span style={{ display: "block", fontSize: 12.5, color: CS.gray }}>{u.objetivo}</span></span>
                  <span style={{ fontSize: 12, color: CS.muted, whiteSpace: "nowrap" }}>
                    {u.tiene_desafio && <span title="Incluye desafío práctico">🎯 </span>}{u.minutos ? `${u.minutos} min · ` : ""}{u.puntos} pts</span>
                </button>
              );
            })}
          </div>
        );
      })}
    </>
  );
}

// ── Unidad ───────────────────────────────────────────────────────────────────
function VistaUnidad({ persona, ruta, unidadId, avance, onAvance, onUnidad, onVolver, onAbrirEnAyuda, titulos }) {
  const [u, setU] = useState(null), [err, setErr] = useState(null);
  const [resp, setResp] = useState({}), [res, setRes] = useState(null), [enviando, setEnviando] = useState(false);
  const [logro, setLogro] = useState(null);
  const avU = (avance?.unidades || {})[unidadId];
  const orden = ruta.modulos.flatMap((m) => m.unidades.map((x) => x.id));
  const sig = orden[orden.indexOf(unidadId) + 1];
  const modulo = ruta.modulos.find((m) => m.unidades.some((x) => x.id === unidadId));

  useEffect(() => {
    let vivo = true;
    setU(null); setResp({}); setRes(null); setLogro(null); setErr(null);
    api("GET", `/soporte/academia/unidad/${unidadId}`).then((d) => vivo && setU(d)).catch((e) => vivo && setErr(e.message));
    window.scrollTo(0, 0);
    return () => { vivo = false; };
  }, [unidadId]);

  const enviar = async () => {
    setEnviando(true); setErr(null);
    try {
      const antes = new Set((avance?.rutas || []).flatMap((r) => r.modulos.filter((m) => m.insignia_ganada).map((m) => m.id)));
      const r = await api("POST", `/soporte/academia/unidad/${unidadId}/responder`, { persona_id: persona.id, respuestas: resp });
      setRes(r);
      const nuevo = await onAvance();
      if (r.aprobado && nuevo) {
        const ins = nuevo.rutas.flatMap((x) => x.modulos).find((m) => m.insignia_ganada && !antes.has(m.id));
        const cert = nuevo.rutas.find((x) => x.id === ruta.id && x.completa);
        setLogro({ insignia: ins, certificado: cert && !(avance?.rutas || []).find((x) => x.id === ruta.id)?.completa ? cert : null });
      }
    } catch (e) { setErr(e.message); } finally { setEnviando(false); }
  };

  const desafio = async () => {
    try { await api("POST", `/soporte/academia/unidad/${unidadId}/desafio`, { persona_id: persona.id }); await onAvance(); }
    catch (e) { setErr(e.message); }
  };

  if (err && !u) return <div style={st.card}><button style={st.link} onClick={onVolver}>← {ruta.titulo}</button><p style={{ color: "#A32D2D" }}>{err}</p></div>;
  if (!u) return <div style={st.card}>Cargando unidad…</div>;
  const completas = u.preguntas.every((p) => resp[p.id] !== undefined);
  const porPregunta = Object.fromEntries((res?.preguntas || []).map((p) => [p.id, p]));

  return (
    <>
      <button style={st.link} onClick={onVolver}>← {ruta.titulo}{modulo ? ` · ${modulo.titulo}` : ""}</button>
      <div style={{ ...st.card, marginTop: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
          <h2 style={{ margin: 0, fontSize: 23 }}>{u.titulo}</h2>
          <span style={{ fontSize: 12.5, color: CS.muted }}>{u.minutos ? `${u.minutos} min · ` : ""}{u.puntos} puntos
            {avU && avU.estado === "aprobada" && <b style={{ color: CS.tealMid }}> · Aprobada</b>}</span>
        </div>
        <p style={{ fontSize: 14.5, margin: "6px 0 14px" }}><b>Objetivo:</b> {u.objetivo}</p>
        {u.por_que && <div style={{ marginBottom: 14 }}><Globo grande><b>Por qué importa.</b> {u.por_que}</Globo></div>}
        <MarkdownSoporte texto={u.cuerpo} onTermino={(t) => onAbrirEnAyuda(`__glosario:${t}`)} onArticulo={onAbrirEnAyuda} />
        {u.ayuda && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 10, fontSize: 13, color: CS.gray }}>
            Más detalle en la Ayuda:
            {u.ayuda.split(",").map((a) => a.trim()).filter(Boolean).map((a) => (
              <button key={a} style={st.btnSec} onClick={() => onAbrirEnAyuda(a)}>{titulos[a] || a}</button>
            ))}
          </div>
        )}
      </div>

      {u.desafio && (
        <div style={{ ...st.card, borderLeft: `4px solid ${M.mostaza}` }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 16 }}>🎯 Desafío práctico</h3>
          <p style={{ margin: "0 0 10px", fontSize: 14, lineHeight: 1.5 }}>{u.desafio}</p>
          <p style={{ margin: "0 0 10px", fontSize: 12, color: CS.muted }}>Solo hay que mirar y navegar: el desafío no cambia nada en el sistema.</p>
          {avU && avU.desafio_ok ? <b style={{ color: CS.tealMid, fontSize: 13.5 }}>✓ Desafío completado</b>
            : <button style={st.btnSec} onClick={desafio}>Lo hice</button>}
        </div>
      )}

      {u.preguntas.length > 0 && (
        <div style={st.card}>
          <h3 style={{ margin: "0 0 4px", fontSize: 17 }}>Cuestionario</h3>
          <p style={{ margin: "0 0 14px", fontSize: 13, color: CS.gray }}>{u.preguntas.length} preguntas · apruebas con {Math.round(u.aprobacion * 100)}%. Puedes reintentar las veces que quieras.</p>
          {u.preguntas.map((p, i) => {
            const r = porPregunta[p.id];
            return (
              <fieldset key={p.id} style={{ border: "none", padding: 0, margin: "0 0 16px" }}>
                <legend style={{ fontWeight: 700, fontSize: 14.5, marginBottom: 6 }}>{i + 1}. {p.pregunta}</legend>
                {p.opciones.map((o, j) => {
                  const marcada = resp[p.id] === j;
                  const fondo = r ? (j === r.opcion_correcta ? "#E1F5EE" : marcada ? "#FCEBEB" : "#fff") : marcada ? M.mostazaLt : "#fff";
                  return (
                    <label key={j} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "7px 10px", marginBottom: 4,
                      border: `1px solid ${marcada ? M.mostaza : CS.grayLt}`, borderRadius: 8, background: fondo, cursor: r ? "default" : "pointer", fontSize: 14 }}>
                      <input type="radio" name={p.id} checked={marcada} disabled={!!r} onChange={() => setResp({ ...resp, [p.id]: j })} style={{ marginTop: 3 }} />
                      {o}
                    </label>
                  );
                })}
                {r && <div style={{ fontSize: 13, marginTop: 4, color: r.correcta ? CS.tealMid : "#A32D2D" }}>
                  <b>{r.correcta ? "Correcto." : "Incorrecto."}</b> <span style={{ color: CS.text }}>{r.explicacion}</span></div>}
              </fieldset>
            );
          })}
          {err && <p style={{ color: "#A32D2D", fontSize: 13 }}>{err}</p>}
          {!res ? (
            <button style={{ ...st.btn, opacity: completas && !enviando ? 1 : 0.5 }} disabled={!completas || enviando} onClick={enviar}>
              {enviando ? "Revisando…" : "Enviar respuestas"}</button>
          ) : res.aprobado ? (
            <div style={{ display: "flex", gap: 18, alignItems: "center", background: M.crema, border: `1px solid ${M.mostaza}`,
              borderRadius: 12, padding: "12px 16px", flexWrap: "wrap" }}>
              <img src={cuerpoMostacin} alt="Mostacín celebrando" style={{ height: 120 }} />
              <div style={{ flex: 1, minWidth: 240 }}>
                <div style={{ fontSize: 20, fontWeight: 700 }}>¡Aprobada! {res.correctas} de {res.total}</div>
                <div style={{ fontSize: 14, margin: "4px 0 10px" }}>
                  {avU && avU.intentos > 1 ? "Puntos de esta unidad: " : "Sumaste "}<b>{res.puntos} puntos</b>.
                  {logro?.insignia && <> Ganaste la insignia <b>{logro.insignia.insignia} {logro.insignia.titulo}</b>.</>}
                  {logro?.certificado && <> ¡Y completaste la ruta! Tu certificado está listo.</>}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {sig ? <button style={st.btn} onClick={() => onUnidad(sig)}>Siguiente unidad</button>
                    : <button style={st.btn} onClick={onVolver}>Volver a la ruta</button>}
                  {logro?.certificado && <button style={st.btnSec} onClick={() => abrirCertificado(persona, { ...logro.certificado, titulo: ruta.titulo })}>Ver certificado</button>}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ marginTop: 4 }}>
              <Globo>Obtuviste {res.puntaje_pct}% ({res.correctas} de {res.total}). Necesitas {Math.round(u.aprobacion * 100)}%.
                Revisa las explicaciones de arriba y vuelve a intentarlo: ¡la próxima sale!</Globo>
              <button style={{ ...st.btn, marginTop: 10 }} onClick={() => { setRes(null); setResp({}); }}>Reintentar</button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

// ── Componente principal ─────────────────────────────────────────────────────
export default function Academia({ onAbrirEnAyuda = () => {} }) {
  const [persona, setPersona] = useState(null), [rutas, setRutas] = useState(null), [avance, setAvance] = useState(null);
  const [vista, setVista] = useState({ tipo: "portada" }), [err, setErr] = useState(null), [pedirNombre, setPedirNombre] = useState(false);
  const [titulos, setTitulos] = useState({});

  const cargarAvance = async (p = persona) => {
    if (!p) return null;
    const d = await api("GET", `/soporte/academia/avance/${p.id}`);
    setAvance(d);
    return d;
  };

  const identificar = async (nombre) => {
    try {
      const p = await api("POST", "/soporte/academia/personas", { nombre });
      guardarNombre(p.nombre);
      setPersona(p); setPedirNombre(false); setErr(null);
      await cargarAvance(p);
    } catch (e) { setErr(e.message); setPedirNombre(true); }
  };

  useEffect(() => {
    api("GET", "/soporte/academia/rutas").then((d) => setRutas(d.rutas)).catch((e) => setErr(e.message));
    api("GET", "/soporte/ayuda/indice").then((d) => setTitulos(Object.fromEntries(d.map((a) => [a.id, a.titulo])))).catch(() => {});
    const n = leerNombre();
    if (n.trim().length >= 3) identificar(n.trim()); else setPedirNombre(true);
  }, []); // eslint-disable-line

  if (!rutas) return <div style={st.wrap}><div style={st.card}>{err ? <span style={{ color: "#A32D2D" }}>{err}</span> : "Cargando Academia…"}</div></div>;
  if (pedirNombre || !persona) return <div style={st.wrap}><Identificacion onListo={identificar} error={err} /></div>;

  const ruta = vista.ruta && rutas.find((r) => r.id === vista.ruta);
  return (
    <div style={st.wrap}>
      {vista.tipo === "portada" && <Portada persona={persona} rutas={rutas} avance={avance}
        onRuta={(id) => setVista({ tipo: "ruta", ruta: id })} onCambiarPersona={() => setPedirNombre(true)} />}
      {vista.tipo === "ruta" && ruta && <VistaRuta persona={persona} ruta={ruta} avance={avance}
        onUnidad={(u) => setVista({ tipo: "unidad", ruta: ruta.id, unidad: u })} onVolver={() => setVista({ tipo: "portada" })} />}
      {vista.tipo === "unidad" && ruta && <VistaUnidad persona={persona} ruta={ruta} unidadId={vista.unidad} avance={avance}
        onAvance={() => cargarAvance()} onUnidad={(u) => setVista({ tipo: "unidad", ruta: ruta.id, unidad: u })}
        onVolver={() => setVista({ tipo: "ruta", ruta: ruta.id })} onAbrirEnAyuda={onAbrirEnAyuda} titulos={titulos} />}
    </div>
  );
}
