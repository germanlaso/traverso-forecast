// Landing.jsx — Panel de inicio (SOLO LECTURA).
// Fuentes: GET /plan/quiebres_grid (lector puro del snapshot vigente) y
//          GET /stock/summary. No dispara el optimizador ni escribe nada.
// Cada tarjeta degrada sola si su fetch falla: no rompe la landing.
// Convencion del proyecto: axios + API relativa ('' con proxy). NO hardcodear IP.

import React, { useEffect, useState, useMemo } from 'react';
import axios from 'axios';

const API = process.env.REACT_APP_API_BASE || '';

// Paleta local (misma que App.js; los componentes del proyecto no comparten C).
const C = {
  teal: '#1D9E75', tealLt: '#E1F5EE',
  amber: '#EF9F27', amberLt: '#FAEEDA',
  danger: '#E24B4A', dangerLt: '#FCEBEB',
  gray: '#5F5E5A', grayLt: '#F1EFE8',
  border: '#D3D1C7', text: '#2C2C2A', textMuted: '#888780',
};

// Accesos por seccion. Los keys son los MISMOS tab-keys de App.js.
const ACCESOS = [
  { seccion: 'forecast', titulo: '📈 Forecast', items: [
      ['forecast', 'Forecast de Demanda'], ['eventos', 'Eventos'] ] },
  { seccion: 'planificacion', titulo: '🏭 Planificación', items: [
      ['stockdiario', 'Stock Diario'], ['plan', 'Plan de Producción'],
      ['detalle', 'Detalle Producción'], ['campanas', 'Campañas'],
      ['programacion', 'Programación Diaria'] ] },
  { seccion: 'control', titulo: '📊 Control', items: [
      ['stockdiario', 'Stock Diario'], ['faltantes', 'Faltantes'],
      ['resumen30', 'Resumen 30d'], ['quiebres', 'Mapa de Quiebres'] ] },   // Conciliación oculta temporalmente (pendiente de mas pruebas)
  { seccion: 'herramientas', titulo: '🛠️ Herramientas', items: [
      ['parametros', 'Parámetros'] ] },
];

const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
function fmtFecha(iso) {
  if (!iso) return '—';
  const p = String(iso).slice(0, 10).split('-');
  if (p.length !== 3) return String(iso);
  return `${p[2]} ${MES[Number(p[1]) - 1] || ''} ${p[0]}`;
}

export default function Landing({ onNavegar }) {
  const [grid, setGrid] = useState(null);
  const [gridErr, setGridErr] = useState(false);
  const [stock, setStock] = useState(null);
  const [falt30, setFalt30] = useState(null);

  useEffect(() => {
    let vivo = true;
    axios.get(`${API}/plan/quiebres_grid`)
      .then(r => { if (vivo) setGrid(r.data); })
      .catch(() => { if (vivo) setGridErr(true); });
    axios.get(`${API}/stock/summary`)
      .then(r => { if (vivo) setStock(r.data); })
      .catch(() => { /* la tarjeta de stock se oculta si falla */ });
    axios.get(`${API}/faltantes/resumen30`)
      .then(r => { if (vivo) setFalt30(r.data); })
      .catch(() => { /* la tarjeta de faltantes se oculta si falla */ });
    return () => { vivo = false; };
  }, []);

  // KPIs de faltantes 30d (mismo cálculo que FaltantesResumen: % global = Σfalt/Σventa)
  const f30 = useMemo(() => {
    if (!falt30 || !Array.isArray(falt30.filas) || falt30.filas.length === 0) return null;
    let ventas = 0, falta = 0;
    const rc = falt30.resumen_cat || {};
    for (const k of Object.keys(rc)) ventas += (rc[k].ventas_total || 0);
    for (const f of falt30.filas) falta += (f.faltante_30 || 0);
    return { ventas, falta, pct: ventas > 0 ? (falta / ventas * 100) : null, nSku: falt30.filas.length };
  }, [falt30]);

  // Totales del mapa de quiebres (misma reduccion que MapaQuiebres.jsx).
  const tot = useMemo(() => {
    if (!grid || !grid.disponible || !Array.isArray(grid.lineas)) return null;
    const t = { skus: 0, quiebre: 0, riesgo: 0, bajoss: 0, dias_quiebre: 0 };
    grid.lineas.forEach(ln => (ln.skus || []).forEach(sk => {
      t.skus += 1;
      if (sk.peor_sev === 3) t.quiebre += 1;
      else if (sk.peor_sev === 2) t.riesgo += 1;
      else if (sk.peor_sev === 1) t.bajoss += 1;
      t.dias_quiebre += Object.values(sk.dias || {}).filter(d => d && d.sev === 3).length;
    }));
    return t;
  }, [grid]);

  const card = { background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 10, padding: '16px 20px' };
  const kpi = (bg) => ({ background: bg, borderRadius: 8, padding: '12px 14px', textAlign: 'center', minWidth: 110, flex: 1 });
  const stamp = stock && (stock.timestamp_refresh || stock.timestamp || stock.fecha);

  return (
    <div>
      <div style={{ marginBottom: 6, fontSize: 18, fontWeight: 700, color: C.text }}>Panel de control</div>
      <div style={{ marginBottom: 18, fontSize: 13, color: C.textMuted }}>
        Resumen del plan vigente y accesos. Vista de solo lectura.
      </div>

      {/* ── Plan vigente + mapa de quiebres resumido ── */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>
            {grid && grid.disponible ? `Plan vigente #${grid.plan_id}` : 'Plan vigente'}
          </div>
          {grid && grid.disponible && (
            <div style={{ fontSize: 12, color: C.textMuted }}>
              inicio {fmtFecha(grid.fecha_inicio)} · horizonte {grid.horizonte_dias} días
            </div>
          )}
        </div>

        {gridErr && <div style={{ fontSize: 13, color: C.textMuted }}>No se pudo cargar el estado del plan.</div>}
        {!gridErr && !grid && <div style={{ fontSize: 13, color: C.textMuted }}>Cargando…</div>}
        {grid && !grid.disponible && <div style={{ fontSize: 13, color: C.textMuted }}>{grid.mensaje || 'No hay plan vigente.'}</div>}

        {tot && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <div style={kpi(tot.quiebre > 0 ? C.dangerLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: tot.quiebre > 0 ? C.danger : C.text }}>{tot.quiebre}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>SKU en quiebre</div>
            </div>
            <div style={kpi(tot.dias_quiebre > 0 ? C.dangerLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: tot.dias_quiebre > 0 ? C.danger : C.text }}>{tot.dias_quiebre}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>días en quiebre</div>
            </div>
            <div style={kpi(tot.riesgo > 0 ? C.amberLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: tot.riesgo > 0 ? '#8a5a00' : C.text }}>{tot.riesgo}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>SKU en riesgo</div>
            </div>
            <div style={kpi(C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{tot.bajoss}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>SKU bajo SS</div>
            </div>
            <div style={kpi(C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{tot.skus}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>SKU en el plan</div>
            </div>
          </div>
        )}

        {grid && grid.disponible && (
          <div style={{ marginTop: 14 }}>
            <button onClick={() => onNavegar && onNavegar('quiebres', 'control')}
              style={{ fontSize: 12, padding: '7px 14px', borderRadius: 7, border: 'none', background: C.teal, color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
              Ver Mapa de Quiebres →
            </button>
          </div>
        )}
      </div>

      {/* ── Stock (frescura de la última descarga) ── */}
      {stock && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 10 }}>Stock</div>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13, color: C.text }}>
            {stamp && <div><span style={{ color: C.textMuted }}>Última descarga: </span>{String(stamp)}</div>}
            {stock.n_skus != null && <div><span style={{ color: C.textMuted }}>SKU con stock: </span>{stock.n_skus}</div>}
            {stock.n_lotes_proximos_vencer != null &&
              <div><span style={{ color: stock.n_lotes_proximos_vencer > 0 ? '#8a5a00' : C.textMuted }}>Próximos a vencer: </span>{stock.n_lotes_proximos_vencer}</div>}
            {stock.n_lotes_vencidos != null &&
              <div><span style={{ color: stock.n_lotes_vencidos > 0 ? C.danger : C.textMuted }}>Vencidos excluidos: </span>{stock.n_lotes_vencidos}</div>}
          </div>
        </div>
      )}

      {/* ── Faltantes últimos 30 días (KPIs + acceso) ── */}
      {f30 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Faltantes — últimos 30 días</div>
            <div style={{ fontSize: 12, color: C.textMuted }}>{f30.nSku} SKU con faltante</div>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <div style={kpi(C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{Math.round(f30.ventas).toLocaleString('es-CL')}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Ventas 30d (cj)</div>
            </div>
            <div style={kpi(f30.falta > 0 ? C.dangerLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: f30.falta > 0 ? C.danger : C.text }}>{Math.round(f30.falta).toLocaleString('es-CL')}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Faltante 30d (cj)</div>
            </div>
            <div style={kpi(C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.teal }}>{f30.pct == null ? '—' : `${f30.pct.toFixed(1)}%`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>% faltante global</div>
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <button onClick={() => onNavegar && onNavegar('resumen30', 'control')}
              style={{ fontSize: 12, padding: '7px 14px', borderRadius: 7, border: 'none', background: C.teal, color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
              Ver Resumen 30d →
            </button>
          </div>
        </div>
      )}

      {/* ── Accesos ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 12 }}>
        {ACCESOS.map(g => (
          <div key={g.seccion} style={card}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 10 }}>{g.titulo}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {g.items.map(([tab, label]) => (
                <button key={g.seccion + '-' + tab} onClick={() => onNavegar && onNavegar(tab, g.seccion)}
                  style={{ textAlign: 'left', fontSize: 12, padding: '7px 10px', borderRadius: 7, border: `0.5px solid ${C.border}`, background: '#fff', color: C.text, cursor: 'pointer' }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
