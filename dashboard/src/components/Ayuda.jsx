// Ayuda.jsx — Soporte > Ayuda: índice por sección, buscador, artículo por pantalla, glosario,
// preguntas frecuentes, novedades y contacto. Contenido desde /soporte/ayuda/* (soporte_contenido.py).
// Props:
//   destino       {id, t} a abrir (lo fija el "?" con "Abrir en Ayuda"); id "__glosario:<termino>" abre el
//                 glosario en ese término; t cambia en cada pedido para reabrir aunque el id se repita
//   onIrPantalla  (tab) => navega a la pantalla del artículo
//   pantallasNavegables  Set de tabs a los que se puede ir desde el menú
import React, { useEffect, useMemo, useState } from "react";
import MarkdownSoporte, { CS, useGlosario } from "./MarkdownSoporte";

const API = process.env.REACT_APP_API_BASE || "";
const ORDEN_SECCIONES = ["Inicio", "Forecast", "Planificación", "Control", "Herramientas", "General"];
const GLOSARIO = "__glosario";

const st = {
  wrap: { display: "flex", gap: 20, alignItems: "flex-start", fontFamily: "Arial, sans-serif", color: CS.text },
  lateral: { width: 260, flexShrink: 0, background: "#fff", border: `1px solid ${CS.border}`, borderRadius: 10, padding: 12,
    position: "sticky", top: 12, maxHeight: "calc(100vh - 40px)", overflowY: "auto" },
  input: { width: "100%", boxSizing: "border-box", padding: "8px 10px", border: `1px solid ${CS.border}`, borderRadius: 7, fontSize: 13 },
  grupo: { fontSize: 11.5, color: CS.muted, fontWeight: 700, margin: "12px 0 4px" },
  item: (activo) => ({ display: "block", width: "100%", textAlign: "left", border: "none", cursor: "pointer", fontSize: 13,
    padding: "5px 8px", borderRadius: 6, background: activo ? CS.tealLt : "transparent", color: activo ? CS.tealMid : CS.text,
    fontWeight: activo ? 700 : 400 }),
  cuerpo: { flex: 1, minWidth: 0, background: "#fff", border: `1px solid ${CS.border}`, borderRadius: 10, padding: "20px 26px" },
  btn: { border: `1px solid ${CS.teal}`, background: "#fff", color: CS.tealMid, borderRadius: 7, padding: "6px 12px",
    fontSize: 12.5, fontWeight: 700, cursor: "pointer" },
};

function Glosario({ resaltado }) {
  const g = useGlosario();
  const [filtro, setFiltro] = useState("");
  const norm = (s) => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const lista = Object.values(g || {}).sort((a, b) => norm(a.termino).localeCompare(norm(b.termino)))
    .filter((t) => !filtro || norm(`${t.termino} ${t.nombre} ${(t.sinonimos || []).join(" ")} ${t.definicion}`).includes(norm(filtro)));
  useEffect(() => {
    if (!resaltado) return;
    const el = document.getElementById(`glosario-${resaltado}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [resaltado, g]);
  return (
    <div>
      <h2 style={{ margin: "0 0 4px", fontSize: 20 }}>Glosario</h2>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: CS.gray }}>Qué significa cada término que usa el sistema.</p>
      <input style={{ ...st.input, maxWidth: 320, marginBottom: 12 }} placeholder="Filtrar términos…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
      {lista.map((t) => (
        <div key={t.id} id={`glosario-${t.id}`} style={{ padding: "10px 12px", borderBottom: `1px solid ${CS.grayLt}`,
          background: t.id === resaltado ? CS.amberLt : "transparent", borderRadius: 6, maxWidth: 760 }}>
          <div style={{ fontSize: 14 }}><b>{t.termino}</b>{t.nombre && t.nombre !== t.termino && <span style={{ color: CS.gray }}> · {t.nombre}</span>}</div>
          <div style={{ fontSize: 13.5, lineHeight: 1.5, marginTop: 2 }}>{t.definicion}</div>
          {t.sinonimos && t.sinonimos.length > 0 && <div style={{ fontSize: 12, color: CS.muted, marginTop: 3 }}>También: {t.sinonimos.join(", ")}</div>}
        </div>
      ))}
      {!lista.length && <p style={{ fontSize: 13, color: CS.muted }}>Ningún término coincide con “{filtro}”.</p>}
    </div>
  );
}

export default function Ayuda({ destino = null, onIrPantalla = null, pantallasNavegables = new Set() }) {
  const [indice, setIndice] = useState(null), [err, setErr] = useState(null);
  const [sel, setSel] = useState(null), [art, setArt] = useState(null);
  const [q, setQ] = useState(""), [res, setRes] = useState(null);
  const [termino, setTermino] = useState(null);

  useEffect(() => {
    let vivo = true;
    fetch(`${API}/soporte/ayuda/indice`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (!vivo) return; setIndice(d); setSel((s) => s || (d[0] && d[0].id) || GLOSARIO); })
      .catch((e) => vivo && setErr(`No se pudo cargar la Ayuda (${e.message}).`));
    return () => { vivo = false; };
  }, []);

  useEffect(() => {
    if (!destino || !destino.id) return;
    if (destino.id.startsWith("__glosario:")) { setTermino(destino.id.split(":")[1]); setSel(GLOSARIO); }
    else setSel(destino.id);
    setQ("");
  }, [destino]);

  useEffect(() => {
    if (!sel || sel === GLOSARIO) { setArt(null); return; }
    let vivo = true;
    setArt(null);
    fetch(`${API}/soporte/ayuda/articulo/${sel}`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => vivo && setArt(d)).catch(() => vivo && setArt({ error: true }));
    return () => { vivo = false; };
  }, [sel]);

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    let vivo = true;
    const t = setTimeout(() => {
      fetch(`${API}/soporte/ayuda/buscar?q=${encodeURIComponent(q.trim())}`).then((r) => (r.ok ? r.json() : []))
        .then((d) => vivo && setRes(d)).catch(() => vivo && setRes([]));
    }, 250);
    return () => { vivo = false; clearTimeout(t); };
  }, [q]);

  const grupos = useMemo(() => {
    const g = {};
    (indice || []).forEach((a) => { (g[a.seccion] = g[a.seccion] || []).push(a); });
    return Object.keys(g).sort((a, b) => (ORDEN_SECCIONES.indexOf(a) + 99) % 99 - (ORDEN_SECCIONES.indexOf(b) + 99) % 99)
      .map((s) => [s, g[s]]);
  }, [indice]);

  const abrirTermino = (id) => { setTermino(id); setSel(GLOSARIO); setQ(""); };
  const abrirResultado = (r) => {
    if (r.tipo === "glosario") abrirTermino(r.id);
    else if (r.tipo === "articulo") { setSel(r.id); setQ(""); }
  };

  if (err) return <div style={{ ...st.cuerpo, color: "#A32D2D" }}>{err}</div>;

  return (
    <div style={st.wrap}>
      <nav style={st.lateral} aria-label="Índice de Ayuda">
        <input style={st.input} placeholder="Buscar en la Ayuda…" value={q} onChange={(e) => setQ(e.target.value)} />
        {res ? (
          <div style={{ marginTop: 8 }}>
            <div style={st.grupo}>{res.length ? `${res.length} resultado${res.length > 1 ? "s" : ""}` : "Sin resultados"}</div>
            {res.filter((r) => r.tipo !== "unidad").map((r, n) => (
              <button key={n} style={{ ...st.item(false), padding: "7px 8px" }} onClick={() => abrirResultado(r)}>
                <div style={{ fontWeight: 700 }}>{r.titulo}{r.subtitulo ? <span style={{ fontWeight: 400, color: CS.gray }}> › {r.subtitulo}</span> : null}</div>
                <div style={{ fontSize: 11.5, color: CS.muted, marginTop: 2, lineHeight: 1.35 }}>{r.extracto.replace(/^#+\s*/, "").slice(0, 110)}…</div>
              </button>
            ))}
            {!res.length && <p style={{ fontSize: 12, color: CS.gray, lineHeight: 1.45 }}>Prueba con otra palabra, revisa el glosario o pregúntale a Mostacín.</p>}
          </div>
        ) : !indice ? <p style={{ fontSize: 13, color: CS.muted }}>Cargando…</p> : (
          <>
            {grupos.map(([sec, arts]) => (
              <div key={sec}>
                <div style={st.grupo}>{sec}</div>
                {arts.map((a) => <button key={a.id} style={st.item(sel === a.id)} onClick={() => setSel(a.id)}>{a.titulo}</button>)}
              </div>
            ))}
            <div style={st.grupo}>Referencia</div>
            <button style={st.item(sel === GLOSARIO)} onClick={() => { setTermino(null); setSel(GLOSARIO); }}>Glosario</button>
          </>
        )}
      </nav>

      <main style={st.cuerpo}>
        {sel === GLOSARIO ? <Glosario resaltado={termino} /> : !art ? <p style={{ color: CS.muted }}>Cargando…</p> : art.error ? (
          <p style={{ color: CS.gray }}>Este artículo todavía no está disponible. Elige otro en el índice.</p>
        ) : (
          <article>
            <div style={{ fontSize: 12, color: CS.muted }}>{art.seccion}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
              <h2 style={{ margin: "2px 0 4px", fontSize: 22 }}>{art.titulo}</h2>
              {onIrPantalla && pantallasNavegables.has(art.id) && (
                <button style={st.btn} onClick={() => onIrPantalla(art.id)}>Ir a la pantalla</button>
              )}
            </div>
            {art.resumen && <p style={{ margin: "0 0 8px", fontSize: 14, color: CS.gray }}>{art.resumen}</p>}
            <MarkdownSoporte texto={art.cuerpo} onTermino={abrirTermino} />
            {art.actualizado && <p style={{ fontSize: 11.5, color: CS.muted, marginTop: 24 }}>Actualizado: {art.actualizado.split("-").reverse().join("-")}</p>}
          </article>
        )}
      </main>
    </div>
  );
}
