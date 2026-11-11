// Mostacin.jsx — Chat de ayuda "Mostacín" (etapa 1): responde cómo usar la app con el contenido de Soporte.
// No ve datos ni modifica nada; si le piden un cambio, explica y ofrece ir a la pantalla.
// Las preguntas se registran de forma anónima (POST /soporte/mostacin/preguntar).
//   <MostacinFlotante pantalla={activeTab} onIrPantalla={fn} onAbrirEnAyuda={fn} />   botón en todas las pantallas
//   <MostacinChat pantalla="mostacin" ... ancho />                                   página Soporte > Mostacín
import React, { useEffect, useRef, useState } from "react";
import MarkdownSoporte, { CS } from "./MarkdownSoporte";
import caraMostacin from "./img/mostacin_cara.png";
import cuerpoMostacin from "./img/mostacin_cuerpo.png";

const API = process.env.REACT_APP_API_BASE || "";
const MOSTAZA = "#F2B705", MOSTAZA_LT = "#FFF6D6";

const SUGERENCIAS = {
  _: ["¿Qué muestra esta pantalla?", "¿Cómo apruebo una orden de fabricación?", "¿Qué diferencia hay entre quiebre y bajo SS?"],
  analisislinea: ["¿Qué significa el semáforo rojo?", "¿Cómo decido un caso?", "¿Qué es la capacidad demostrada?"],
  parametros: ["¿Cómo edito el batch mínimo?", "¿Por qué no me deja guardar?", "¿Cuándo se aplican los cambios?"],
  faltantes: ["¿Qué significa VU insuficiente?", "¿Cómo descargo el informe en Excel?", "¿A qué hora llega el informe?"],
  bitacora: ["¿Cómo registro una parada planificada?", "¿Qué eventos restan horas al plan?", "¿Cómo anulo un evento?"],
};

function Mensaje({ m, onFeedback, onEnlace }) {
  if (m.rol === "usuario") {
    return (
      <div style={{ alignSelf: "flex-end", maxWidth: "85%", background: CS.tealLt, color: CS.text, borderRadius: "12px 12px 2px 12px",
        padding: "8px 12px", fontSize: 13.5, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>{m.texto}</div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", maxWidth: "94%" }}>
      <img src={caraMostacin} alt="" width={30} height={30} style={{ borderRadius: "50%", flexShrink: 0, marginTop: 2 }} />
      <div style={{ background: m.error ? "#FCEBEB" : "#fff", border: `1px solid ${m.error ? "#F2C4C4" : CS.border}`,
        borderRadius: "12px 12px 12px 2px", padding: "6px 12px", minWidth: 0 }}>
        {m.error ? <p style={{ fontSize: 13.5, margin: "4px 0", color: "#A32D2D" }}>{m.texto}</p>
          : <div style={{ fontSize: 13.5 }}><MarkdownSoporte texto={m.texto} /></div>}
        {m.enlaces && m.enlaces.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "2px 0 6px" }}>
            {m.enlaces.map((e, i) => (
              <button key={i} onClick={() => onEnlace(e)} style={{ border: `1px solid ${CS.teal}`, background: "#fff", color: CS.tealMid,
                borderRadius: 14, padding: "3px 10px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                {e.tipo === "ir" ? `Ir a ${e.titulo}` : `Ver ayuda: ${e.titulo}`}
              </button>
            ))}
          </div>
        )}
        {m.id && (
          <div style={{ display: "flex", gap: 4, alignItems: "center", fontSize: 11.5, color: CS.muted, marginBottom: 2 }}>
            {m.util ? (m.util === 1 ? "Gracias por tu respuesta." : "Gracias: lo usaremos para mejorar la Ayuda.") : (
              <>
                ¿Te sirvió?
                <button onClick={() => onFeedback(m, 1)} aria-label="Me sirvió" style={btnPulgar}>👍</button>
                <button onClick={() => onFeedback(m, -1)} aria-label="No me sirvió" style={btnPulgar}>👎</button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
const btnPulgar = { border: "none", background: "transparent", cursor: "pointer", fontSize: 14, padding: "0 2px" };

export function MostacinChat({ pantalla, onIrPantalla, onAbrirEnAyuda, ancho = false, onCerrar = null }) {
  const [msgs, setMsgs] = useState([]), [txt, setTxt] = useState(""), [esperando, setEsperando] = useState(false);
  const finRef = useRef(null), inputRef = useRef(null);

  useEffect(() => { if (finRef.current) finRef.current.scrollIntoView({ block: "end" }); }, [msgs, esperando]);
  useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

  const enviar = async (pregunta) => {
    const q = (pregunta || "").trim();
    if (!q || esperando) return;
    const historial = msgs.filter((m) => !m.error).slice(-6).map((m) => ({ rol: m.rol, texto: m.texto }));
    setMsgs((x) => [...x, { rol: "usuario", texto: q }]);
    setTxt(""); setEsperando(true);
    try {
      const r = await fetch(`${API}/soporte/mostacin/preguntar`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pregunta: q, pantalla, historial }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
      setMsgs((x) => [...x, { rol: "mostacin", texto: d.respuesta, enlaces: d.enlaces, id: d.id }]);
    } catch (e) {
      setMsgs((x) => [...x, { rol: "mostacin", error: true, texto: e.message || "No pude responder. Intenta de nuevo." }]);
    } finally { setEsperando(false); }
  };

  const feedback = async (m, util) => {
    setMsgs((x) => x.map((y) => (y === m ? { ...y, util } : y)));
    try {
      await fetch(`${API}/soporte/mostacin/feedback`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: m.id, util }) });
    } catch { /* el feedback es opcional */ }
  };

  const enlace = (e) => {
    if (e.tipo === "ir" && onIrPantalla) onIrPantalla(e.id);
    else if (onAbrirEnAyuda) onAbrirEnAyuda(e.id);
    if (onCerrar) onCerrar();
  };

  const sugerencias = SUGERENCIAS[pantalla] || SUGERENCIAS._;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", fontFamily: "Arial, sans-serif", color: CS.text,
      background: "#FBFAF6" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: MOSTAZA_LT,
        borderBottom: `2px solid ${MOSTAZA}` }}>
        <img src={caraMostacin} alt="Mostacín" width={38} height={38} style={{ borderRadius: "50%" }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Mostacín</div>
          <div style={{ fontSize: 11.5, color: CS.gray }}>Te ayudo a usar el sistema de planificación</div>
        </div>
        {onCerrar && <button onClick={onCerrar} aria-label="Cerrar Mostacín" style={{ border: "none", background: "transparent",
          fontSize: 22, lineHeight: 1, cursor: "pointer", color: CS.gray }}>×</button>}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px 6px", display: "flex", flexDirection: "column", gap: 10 }}>
        {!msgs.length && (
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexDirection: ancho ? "row" : "column" }}>
            <img src={cuerpoMostacin} alt="Mostacín" style={{ height: ancho ? 220 : 150, alignSelf: ancho ? "auto" : "center" }} />
            <div>
              <p style={{ fontSize: 14, margin: "0 0 6px", lineHeight: 1.5 }}>
                ¡Hola! Soy <b>Mostacín</b>. Pregúntame cómo usar cualquier pantalla o qué significa un término.
              </p>
              <p style={{ fontSize: 12, color: CS.gray, margin: "0 0 10px", lineHeight: 1.45 }}>
                Solo explico cómo usar la app: no veo datos del plan ni puedo modificar nada. Las preguntas se guardan
                de forma anónima para mejorar la Ayuda.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                {sugerencias.map((s) => (
                  <button key={s} onClick={() => enviar(s)} style={{ border: `1px solid ${MOSTAZA}`, background: "#fff",
                    borderRadius: 14, padding: "5px 12px", fontSize: 12.5, cursor: "pointer", color: CS.text, textAlign: "left" }}>{s}</button>
                ))}
              </div>
            </div>
          </div>
        )}
        {msgs.map((m, i) => <Mensaje key={i} m={m} onFeedback={feedback} onEnlace={enlace} />)}
        {esperando && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5, color: CS.gray }}>
            <img src={caraMostacin} alt="" width={30} height={30} style={{ borderRadius: "50%" }} />Mostacín está pensando…
          </div>
        )}
        <div ref={finRef} />
      </div>

      <div style={{ display: "flex", gap: 8, padding: 10, borderTop: `1px solid ${CS.border}`, background: "#fff" }}>
        <textarea ref={inputRef} value={txt} rows={2} maxLength={800} placeholder="Escribe tu pregunta…"
          onChange={(e) => setTxt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(txt); } }}
          style={{ flex: 1, resize: "none", border: `1px solid ${CS.border}`, borderRadius: 8, padding: "7px 9px",
            fontSize: 13.5, fontFamily: "Arial, sans-serif" }} />
        <button onClick={() => enviar(txt)} disabled={esperando || !txt.trim()}
          style={{ border: "none", borderRadius: 8, padding: "0 14px", fontWeight: 700, fontSize: 13,
            background: esperando || !txt.trim() ? CS.grayLt : CS.teal, color: esperando || !txt.trim() ? CS.muted : "#fff",
            cursor: esperando || !txt.trim() ? "default" : "pointer" }}>Enviar</button>
      </div>
    </div>
  );
}

export default function MostacinFlotante({ pantalla, onIrPantalla, onAbrirEnAyuda }) {
  const [abierto, setAbierto] = useState(false);
  return (
    <div className="no-print">
      {/* Se mantiene montado (oculto) para no perder la conversación al cerrar */}
      {(
        <div role="dialog" aria-label="Chat con Mostacín" style={{ display: abierto ? "block" : "none", position: "fixed", right: 20, bottom: 92, zIndex: 900,
          width: "min(380px, calc(100vw - 32px))", height: "min(560px, calc(100vh - 120px))", borderRadius: 14,
          overflow: "hidden", border: `1px solid ${CS.border}`, boxShadow: "0 10px 30px rgba(0,0,0,.18)" }}>
          <MostacinChat pantalla={pantalla} onIrPantalla={onIrPantalla} onAbrirEnAyuda={onAbrirEnAyuda} onCerrar={() => setAbierto(false)} />
        </div>
      )}
      <button onClick={() => setAbierto((x) => !x)} title={abierto ? "Cerrar Mostacín" : "Pregúntale a Mostacín"}
        aria-label={abierto ? "Cerrar Mostacín" : "Pregúntale a Mostacín"}
        style={{ position: "fixed", right: 20, bottom: 20, zIndex: 900, width: 60, height: 60, borderRadius: "50%", padding: 0,
          border: `3px solid ${MOSTAZA}`, background: "#fff", cursor: "pointer", boxShadow: "0 4px 14px rgba(0,0,0,.2)" }}>
        <img src={caraMostacin} alt="" width={54} height={54} style={{ borderRadius: "50%", display: "block" }} />
      </button>
    </div>
  );
}
