import React, { useEffect, useState } from 'react';

// Pestaña Informes > Informe semanal (clave 'informeia').
//   · Informes AUTOMÁTICOS (semanales): guardados en la BD, servidos por el backend
//     (/informes/lista y /informes/{id}/html). PDF: imprimir desde el navegador.
//   · Informes estáticos anteriores: public/informes/index.json (+ .html y .pdf).

const BASE = `${process.env.PUBLIC_URL || ''}/informes`;
const API = process.env.REACT_APP_API_BASE || '';
// (11-11-2026) En dev, el servidor del dashboard (:3000) reenvía al backend solo los fetch;
// una NAVEGACIÓN (iframe src, pestaña nueva) a /informes/... devuelve la app. Por eso los
// informes automáticos se descargan con fetch y se muestran con srcDoc / blob, y el enlace
// para compartir apunta directo al backend (:8000 si no hay REACT_APP_API_BASE).
const API_DIRECTA = API || `${window.location.protocol}//${window.location.hostname}:8000`;

const C = { teal: '#1D9E75', border: '#D3D1C7', gray: '#5F5E5A', muted: '#888780', red: '#A32D2D' };
const btn = { padding: '6px 14px', borderRadius: 16, border: `1px solid ${C.border}`, background: '#fff',
  color: C.gray, fontSize: 13, cursor: 'pointer', textDecoration: 'none', display: 'inline-block' };

function fmtFecha(s) {
  try { return new Date(s).toLocaleString('es-CL', { dateStyle: 'short', timeStyle: 'short' }); } catch { return s; }
}

export default function InformesOperacion() {
  const [lista, setLista] = useState([]);
  const [sel, setSel] = useState(null);
  const [error, setError] = useState(null);
  const [copiado, setCopiado] = useState(false);
  const [generando, setGenerando] = useState(false);
  const [doc, setDoc] = useState(null);           // HTML del informe automático seleccionado

  useEffect(() => {
    setDoc(null);
    if (!sel || !sel.automatico) return;
    fetch(sel.htmlUrl).then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setDoc).catch((e) => setError(`No se pudo cargar el informe: ${e.message}`));
  }, [sel]);

  // abre el HTML ya descargado en una pestaña nueva (blob: mismo origen, permite imprimir)
  const abrirDoc = (imprimir) => {
    if (!doc) return;
    const url = URL.createObjectURL(new Blob([doc], { type: 'text/html' }));
    const w = window.open(url, '_blank');
    if (imprimir && w) w.addEventListener('load', () => w.print());
  };

  const cargar = (seleccionarId) => Promise.all([
    fetch(`${API}/informes/lista`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : { informes: [] })).catch(() => ({ informes: [] })),
    fetch(`${BASE}/index.json`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : [])).catch(() => []),
  ]).then(([auto, estaticos]) => {
    const a = (auto.informes || []).map((x) => ({
      id: `auto-${x.id}`, titulo: x.titulo, periodo: `Sem ${x.semana_iso}`, generado: fmtFecha(x.creado_en), orden: x.creado_en,
      htmlUrl: `${API}/informes/${x.id}/html`, enlace: `${API_DIRECTA}/informes/${x.id}/html`, pdfUrl: null, automatico: true,
    }));
    const e = (estaticos || []).map((x) => ({ ...x, orden: x.generado, htmlUrl: `${BASE}/${x.html}`, enlace: `${BASE}/${x.html}`, pdfUrl: x.pdf ? `${BASE}/${x.pdf}` : null }));
    const todos = [...a, ...e].sort((p, q) => (String(p.orden) < String(q.orden) ? 1 : -1));
    setLista(todos);
    setSel(todos.find((x) => x.id === seleccionarId) || todos[0] || null);
    if (!todos.length) setError('Todavía no hay informes.');
  });

  useEffect(() => { cargar(); }, []);   // eslint-disable-line

  const generar = async () => {
    if (!window.confirm('¿Generar ahora el informe de la semana pasada? Tarda 1 a 2 minutos.')) return;
    setGenerando(true); setError(null);
    try {
      const r = await fetch(`${API}/informes/generar`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ solicitado_por: 'app' }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      await cargar(`auto-${d.id}`);
    } catch (e) { setError(`No se pudo generar: ${e.message}`); } finally { setGenerando(false); }
  };

  const imprimir = () => abrirDoc(true);

  return (
    <div style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        {sel && (
          <select value={sel.id} onChange={(e) => setSel(lista.find((x) => x.id === e.target.value))}
            style={{ padding: '6px 8px', border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13 }}>
            {lista.map((x) => <option key={x.id} value={x.id}>{x.automatico ? '● ' : ''}{x.titulo} ({x.periodo})</option>)}
          </select>)}
        {sel && <span style={{ fontSize: 12, color: C.muted }}>Generado: {sel.generado}{sel.automatico ? ' · automático' : ''}</span>}
        <span style={{ flex: 1 }} />
        <span style={btn} onClick={generando ? undefined : generar}>{generando ? 'Generando…' : 'Generar semana pasada'}</span>
        {sel && <>
          <span style={btn} onClick={() => {
            const url = new URL(sel.enlace, window.location.origin).href;
            const ok = () => { setCopiado(true); setTimeout(() => setCopiado(false), 2000); };
            if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(url).then(ok).catch(() => window.prompt('Copia el enlace:', url));
            else window.prompt('Copia el enlace:', url);
          }}>{copiado ? 'Enlace copiado ✓' : 'Copiar enlace'}</span>
          {sel.automatico
            ? <span style={btn} onClick={() => abrirDoc(false)}>Abrir en pestaña nueva</span>
            : <a style={btn} href={sel.htmlUrl} target="_blank" rel="noreferrer">Abrir en pestaña nueva</a>}
          {sel.pdfUrl
            ? <a style={{ ...btn, background: C.teal, color: '#fff', borderColor: C.teal }} href={sel.pdfUrl} download>Descargar PDF</a>
            : <span style={{ ...btn, background: C.teal, color: '#fff', borderColor: C.teal }} onClick={imprimir} title="Abre el informe e imprime (guardar como PDF, A4 apaisado)">Imprimir / PDF</span>}
        </>}
      </div>
      {error && <div style={{ padding: '6px 0', color: C.red, fontSize: 13 }}>{error}</div>}
      {sel && (sel.automatico
        ? (doc
          ? <iframe key={sel.id} title={sel.titulo} srcDoc={doc}
              style={{ display: 'block', width: '100%', height: 'calc(100vh - 150px)', border: `1px solid ${C.border}`, borderRadius: 10, background: '#F8F7F4' }} />
          : <div style={{ padding: 16, color: C.muted }}>Cargando informe…</div>)
        : <iframe key={sel.id} title={sel.titulo} src={sel.htmlUrl}
            style={{ display: 'block', width: '100%', height: 'calc(100vh - 150px)', border: `1px solid ${C.border}`, borderRadius: 10, background: '#F8F7F4' }} />)}
    </div>
  );
}
