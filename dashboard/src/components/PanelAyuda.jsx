// PanelAyuda.jsx — Ayuda contextual: el botón "?" de la barra superior abre este panel lateral con
// el artículo de la pantalla actual (id del artículo = clave del tab en App.js).
// Props: pantalla (activeTab), onClose(), onAbrirEnAyuda(id)
import React, { useEffect, useState } from "react";
import MarkdownSoporte, { CS } from "./MarkdownSoporte";

const API = process.env.REACT_APP_API_BASE || "";
// Pantallas sin artículo propio → artículo que se muestra
const EQUIVALENTE = { ayuda: "faq" };

export default function PanelAyuda({ pantalla, onClose, onAbrirEnAyuda }) {
  const id = EQUIVALENTE[pantalla] || pantalla;
  const [art, setArt] = useState(null);

  useEffect(() => {
    let vivo = true;
    setArt(null);
    fetch(`${API}/soporte/ayuda/articulo/${id}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then((d) => vivo && setArt(d)).catch(() => vivo && setArt({ error: true }));
    return () => { vivo = false; };
  }, [id]);

  useEffect(() => {
    const tecla = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [onClose]);

  return (
    <div className="no-print" style={{ position: "fixed", inset: 0, zIndex: 1000 }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(44,44,42,.25)" }} />
      <aside role="dialog" aria-label="Ayuda de esta pantalla"
        style={{ position: "absolute", top: 0, right: 0, bottom: 0, width: "min(460px, 100vw)", background: "#fff",
          borderLeft: `3px solid ${CS.teal}`, display: "flex", flexDirection: "column", fontFamily: "Arial, sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px",
          borderBottom: `1px solid ${CS.border}` }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: CS.tealMid }}>Ayuda de esta pantalla</span>
          <span style={{ display: "flex", gap: 8 }}>
            {art && !art.error && (
              <button onClick={() => onAbrirEnAyuda(id)} style={{ border: `1px solid ${CS.teal}`, background: "#fff",
                color: CS.tealMid, borderRadius: 7, padding: "4px 10px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                Abrir en Ayuda
              </button>
            )}
            <button onClick={onClose} aria-label="Cerrar ayuda" style={{ border: "none", background: "transparent",
              fontSize: 20, lineHeight: 1, cursor: "pointer", color: CS.gray }}>×</button>
          </span>
        </div>
        <div style={{ padding: "14px 18px 30px", overflowY: "auto" }}>
          {!art ? <p style={{ color: CS.muted, fontSize: 13 }}>Cargando…</p> : art.error ? (
            <div style={{ fontSize: 13.5, color: CS.gray, lineHeight: 1.5 }}>
              <p>Esta pantalla todavía no tiene artículo de ayuda.</p>
              <button onClick={() => onAbrirEnAyuda(null)} style={{ border: `1px solid ${CS.teal}`, background: "#fff",
                color: CS.tealMid, borderRadius: 7, padding: "6px 12px", fontSize: 12.5, fontWeight: 700, cursor: "pointer" }}>
                Ir al índice de Ayuda
              </button>
            </div>
          ) : (
            <>
              <h2 style={{ margin: "0 0 4px", fontSize: 19 }}>{art.titulo}</h2>
              {art.resumen && <p style={{ margin: "0 0 6px", fontSize: 13.5, color: CS.gray }}>{art.resumen}</p>}
              <MarkdownSoporte texto={art.cuerpo} onTermino={(t) => onAbrirEnAyuda(`__glosario:${t}`)} />
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
