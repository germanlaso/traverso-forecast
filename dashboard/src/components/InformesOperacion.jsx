import React, { useEffect, useState } from 'react';

// Pestaña Control > Informe IA: muestra los informes de operación publicados en
// public/informes/ (index.json + un .html interactivo y un .pdf por informe).
// Sin backend: los archivos se sirven como estáticos del dashboard.

const BASE = `${process.env.PUBLIC_URL || ''}/informes`;

const C = { teal: '#1D9E75', border: '#D3D1C7', gray: '#5F5E5A', muted: '#888780' };
const btn = { padding: '6px 14px', borderRadius: 16, border: `1px solid ${C.border}`, background: '#fff',
  color: C.gray, fontSize: 13, cursor: 'pointer', textDecoration: 'none', display: 'inline-block' };

export default function InformesOperacion() {
  const [lista, setLista] = useState([]);
  const [sel, setSel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${BASE}/index.json`, { cache: 'no-store' })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => {
        const orden = [...d].sort((a, b) => (a.generado < b.generado ? 1 : -1));
        setLista(orden);
        setSel(orden[0] || null);
      })
      .catch(() => setError('No se encontró el índice de informes (public/informes/index.json).'));
  }, []);

  if (error) return <div style={{ padding: 16, color: '#A32D2D' }}>{error}</div>;
  if (!sel) return <div style={{ padding: 16, color: C.muted }}>Cargando informes…</div>;

  return (
    <div style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <select value={sel.id} onChange={(e) => setSel(lista.find((x) => x.id === e.target.value))}
          style={{ padding: '6px 8px', border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13 }}>
          {lista.map((x) => <option key={x.id} value={x.id}>{x.titulo} ({x.periodo})</option>)}
        </select>
        <span style={{ fontSize: 12, color: C.muted }}>Generado: {sel.generado}</span>
        <span style={{ flex: 1 }} />
        <a style={btn} href={`${BASE}/${sel.html}`} target="_blank" rel="noreferrer">Abrir en pestaña nueva</a>
        <a style={{ ...btn, background: C.teal, color: '#fff', borderColor: C.teal }} href={`${BASE}/${sel.pdf}`} download>Descargar PDF</a>
      </div>
      <iframe key={sel.id} title={sel.titulo} src={`${BASE}/${sel.html}`}
        style={{ width: '100%', height: 'calc(100vh - 170px)', border: `1px solid ${C.border}`, borderRadius: 10, background: '#F8F7F4' }} />
    </div>
  );
}
