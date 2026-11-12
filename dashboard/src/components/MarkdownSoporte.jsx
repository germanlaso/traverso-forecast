// MarkdownSoporte.jsx — Renderizador acotado del contenido de Soporte (Ayuda y Academia).
// Sin dependencias: soporta ## / ### títulos, párrafos, listas (- y 1.) con un nivel de anidación,
// **negrita**, `código`, [texto](https://...), imágenes ![alt](archivo.png) y términos del glosario
// [[g:id]] / [[g:id|texto]] (subrayado punteado con su definición al pasar el mouse) y enlaces a
// artículos de la Ayuda [[a:id|texto]] (id = nombre del archivo sin .md; en pantallas = clave del tab).
// El enlace a artículo navega solo si quien usa el componente pasa onArticulo; si no, queda como texto.
// Las imágenes se cargan con fetch → blob: en dev, el servidor :3000 solo reenvía al backend los fetch.
import React, { useEffect, useState } from "react";

const API = process.env.REACT_APP_API_BASE || "";
export const CS = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56", gray: "#5F5E5A", grayLt: "#F1EFE8",
  border: "#D3D1C7", text: "#2C2C2A", muted: "#888780", amber: "#EF9F27", amberLt: "#FAEEDA",
};

// ── Glosario compartido (una sola descarga por sesión) ────────────────────────
let _glosarioPromesa = null;
export function cargarGlosario() {
  if (!_glosarioPromesa) {
    _glosarioPromesa = fetch(`${API}/soporte/ayuda/glosario`)
      .then((r) => (r.ok ? r.json() : []))
      .then((lista) => Object.fromEntries((lista || []).map((t) => [t.id, t])))
      .catch(() => { _glosarioPromesa = null; return {}; });
  }
  return _glosarioPromesa;
}
export function useGlosario() {
  const [g, setG] = useState(null);   // null = cargando
  useEffect(() => { let vivo = true; cargarGlosario().then((x) => vivo && setG(x)); return () => { vivo = false; }; }, []);
  return g;
}

// Texto visible de un término: "Quiebre" → "quiebre" dentro de una frase; siglas ("SS", "OF aprobada") se respetan.
const textoTermino = (t) => {
  const s = t.termino || t.id;
  return /^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]/.test(s) && !/[A-ZÁÉÍÓÚÑ]/.test(s.slice(1)) ? s[0].toLowerCase() + s.slice(1) : s;
};

function Termino({ t, texto, onTermino }) {
  const [ver, setVer] = useState(false);
  return (
    <span style={{ position: "relative" }} onMouseEnter={() => setVer(true)} onMouseLeave={() => setVer(false)}>
      <span role="button" tabIndex={0} onClick={() => onTermino && onTermino(t.id)}
        onKeyDown={(e) => e.key === "Enter" && onTermino && onTermino(t.id)}
        onFocus={() => setVer(true)} onBlur={() => setVer(false)}
        style={{ borderBottom: `1.5px dotted ${CS.teal}`, cursor: onTermino ? "pointer" : "help", color: "inherit" }}>
        {texto || textoTermino(t)}
      </span>
      {ver && (
        <span style={{ position: "absolute", left: 0, top: "1.6em", zIndex: 30, width: 300, background: "#fff",
          border: `1px solid ${CS.border}`, borderLeft: `3px solid ${CS.teal}`, borderRadius: 6, padding: "8px 10px",
          fontSize: 12, lineHeight: 1.45, color: CS.text, boxShadow: "0 4px 14px rgba(0,0,0,.08)", fontWeight: 400 }}>
          <b>{t.termino}</b>{t.nombre && t.nombre !== t.termino ? ` — ${t.nombre}` : ""}<br />{t.definicion}
        </span>
      )}
    </span>
  );
}

export function ImagenSoporte({ archivo, alt }) {
  const [url, setUrl] = useState(null), [err, setErr] = useState(false), [zoom, setZoom] = useState(false);
  useEffect(() => {
    let vivo = true, obj = null;
    fetch(`${API}/soporte/img/${encodeURIComponent(archivo)}`)
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(r.status))))
      .then((b) => { obj = URL.createObjectURL(b); if (vivo) setUrl(obj); })
      .catch(() => vivo && setErr(true));
    return () => { vivo = false; if (obj) URL.revokeObjectURL(obj); };
  }, [archivo]);
  if (err) return <div style={{ fontSize: 12, color: CS.muted, padding: 8, border: `1px dashed ${CS.border}`, borderRadius: 6 }}>Imagen no disponible: {archivo}</div>;
  if (!url) return <div style={{ height: 120, background: CS.grayLt, borderRadius: 6 }} />;
  return (
    <figure style={{ margin: "12px 0" }}>
      <img src={url} alt={alt} onClick={() => setZoom(true)} title="Clic para ampliar"
        style={{ maxWidth: "100%", border: `1px solid ${CS.border}`, borderRadius: 6, cursor: "zoom-in" }} />
      {alt && <figcaption style={{ fontSize: 12, color: CS.muted, marginTop: 4 }}>{alt} · clic para ampliar</figcaption>}
      {zoom && (
        <div onClick={() => setZoom(false)} role="dialog" aria-label={alt || "Imagen ampliada"}
          style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(20,20,20,.75)", display: "flex",
            alignItems: "center", justifyContent: "center", padding: 20, cursor: "zoom-out" }}>
          <img src={url} alt={alt} style={{ maxWidth: "96vw", maxHeight: "94vh", borderRadius: 6, background: "#fff" }} />
        </div>
      )}
    </figure>
  );
}

// ── Inline ────────────────────────────────────────────────────────────────────
const RE_INLINE = /\*\*(.+?)\*\*|`([^`]+)`|\[\[g:([a-z0-9_-]+)(?:\|([^\]]+))?\]\]|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|\[\[a:([a-z0-9_-]+)\|([^\]]+)\]\]/g;

function inline(texto, ctx, k = "i") {
  const out = [];
  let ultimo = 0, n = 0, m;
  const re = new RegExp(RE_INLINE.source, "g");
  while ((m = re.exec(texto)) !== null) {
    if (m.index > ultimo) out.push(texto.slice(ultimo, m.index));
    const key = `${k}-${n++}`;
    if (m[1] !== undefined) out.push(<strong key={key}>{inline(m[1], ctx, key)}</strong>);
    else if (m[2] !== undefined) out.push(<code key={key} style={{ background: CS.grayLt, padding: "1px 4px", borderRadius: 3, fontSize: "0.92em" }}>{m[2]}</code>);
    else if (m[3] !== undefined) {
      const t = ctx.glosario[m[3]];
      out.push(t ? <Termino key={key} t={t} texto={m[4]} onTermino={ctx.onTermino} /> : <span key={key}>{m[4] || m[3]}</span>);
    } else if (m[7] !== undefined) {
      out.push(ctx.onArticulo
        ? <span key={key} role="link" tabIndex={0} onClick={() => ctx.onArticulo(m[7])}
            onKeyDown={(e) => e.key === "Enter" && ctx.onArticulo(m[7])}
            style={{ color: CS.tealMid, textDecoration: "underline", cursor: "pointer" }}>{m[8]}</span>
        : <span key={key}>{m[8]}</span>);
    } else out.push(<a key={key} href={m[6]} target="_blank" rel="noreferrer" style={{ color: CS.tealMid }}>{m[5]}</a>);
    ultimo = re.lastIndex;
  }
  if (ultimo < texto.length) out.push(texto.slice(ultimo));
  return out;
}

// ── Bloques ───────────────────────────────────────────────────────────────────
function parsear(md) {
  const lineas = (md || "").replace(/\r\n/g, "\n").split("\n");
  const bloques = [];
  let i = 0;
  while (i < lineas.length) {
    const l = lineas[i];
    if (!l.trim()) { i++; continue; }
    let m;
    if ((m = l.match(/^(#{2,3})\s+(.*)$/))) { bloques.push({ tipo: "h", nivel: m[1].length, texto: m[2] }); i++; continue; }
    if ((m = l.match(/^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/))) { bloques.push({ tipo: "img", alt: m[1], archivo: m[2] }); i++; continue; }
    if (/^(\s*)([-*]|\d+\.)\s+/.test(l)) {
      const items = [];
      while (i < lineas.length && /^(\s*)([-*]|\d+\.)\s+/.test(lineas[i])) {
        const mm = lineas[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
        const nivel = mm[1].length >= 2 ? 1 : 0, ordenada = /\d/.test(mm[2]);
        if (nivel === 1 && items.length) {
          const padre = items[items.length - 1];
          (padre.hijos = padre.hijos || { ordenada, items: [] }).items.push(mm[3]);
        } else items.push({ texto: mm[3], ordenada });
        i++;
      }
      bloques.push({ tipo: "lista", ordenada: items[0].ordenada, items });
      continue;
    }
    const parr = [];
    while (i < lineas.length && lineas[i].trim() && !/^(#{2,3}\s|!\[|\s*([-*]|\d+\.)\s+)/.test(lineas[i])) parr.push(lineas[i++].trim());
    bloques.push({ tipo: "p", texto: parr.join(" ") });
  }
  return bloques;
}

export default function MarkdownSoporte({ texto, onTermino, onArticulo = null }) {
  const glosario = useGlosario();
  if (glosario === null) return <p style={{ fontSize: 13, color: CS.muted }}>Cargando…</p>;
  const ctx = { glosario, onTermino, onArticulo };
  const estiloLista = { margin: "6px 0 10px", paddingLeft: 22, lineHeight: 1.6 };
  return (
    <div style={{ fontSize: 14, lineHeight: 1.6, color: CS.text, maxWidth: 760 }}>
      {parsear(texto).map((b, j) => {
        const k = `b${j}`;
        if (b.tipo === "h") return b.nivel === 2
          ? <h3 key={k} style={{ fontSize: 16, margin: "20px 0 6px", color: CS.tealMid }}>{inline(b.texto, ctx, k)}</h3>
          : <h4 key={k} style={{ fontSize: 14, margin: "14px 0 4px" }}>{inline(b.texto, ctx, k)}</h4>;
        if (b.tipo === "img") return <ImagenSoporte key={k} archivo={b.archivo} alt={b.alt} />;
        if (b.tipo === "lista") {
          const Tag = b.ordenada ? "ol" : "ul";
          return (
            <Tag key={k} style={estiloLista}>
              {b.items.map((it, n) => {
                const Sub = it.hijos && (it.hijos.ordenada ? "ol" : "ul");
                return (
                  <li key={n} style={{ marginBottom: 3 }}>{inline(it.texto, ctx, `${k}-${n}`)}
                    {Sub && <Sub style={{ ...estiloLista, margin: "4px 0" }}>
                      {it.hijos.items.map((h, z) => <li key={z}>{inline(h, ctx, `${k}-${n}-${z}`)}</li>)}
                    </Sub>}
                  </li>
                );
              })}
            </Tag>
          );
        }
        return <p key={k} style={{ margin: "6px 0 10px" }}>{inline(b.texto, ctx, k)}</p>;
      })}
    </div>
  );
}
