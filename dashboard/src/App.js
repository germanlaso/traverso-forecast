import React, { useState, useEffect, useCallback } from 'react';
import {
  ComposedChart, Line, Area, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts';
import axios from 'axios';

const API = '';  // proxy via package.json → forecast:8000

// ── Paleta ────────────────────────────────────────────────────────────────────
const C = {
  teal:      '#1D9E75',
  tealLt:    '#E1F5EE',
  blue:      '#185FA5',
  blueLt:    '#E6F1FB',
  purple:    '#534AB7',
  purpleLt:  '#EEEDFE',
  amber:     '#EF9F27',
  amberLt:   '#FAEEDA',
  gray:      '#5F5E5A',
  grayLt:    '#F1EFE8',
  danger:    '#E24B4A',
  dangerLt:  '#FCEBEB',
  border:    '#D3D1C7',
  text:      '#2C2C2A',
  textMuted: '#888780',
};

const s = {
  app:       { fontFamily: 'Arial, sans-serif', background: '#F8F7F4', minHeight: '100vh', color: C.text },
  topbar:    { background: C.teal, color: '#fff', padding: '0 28px', height: 52, display: 'flex', alignItems: 'center', justifyContent: 'space-between' },
  topTitle:  { fontWeight: 700, fontSize: 15, letterSpacing: 0.3 },
  topSub:    { fontSize: 12, opacity: 0.8 },
  main:      { maxWidth: 1100, margin: '0 auto', padding: '24px 20px' },
  card:      { background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 10, padding: '16px 20px', marginBottom: 16 },
  cardTitle: { fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 12 },
  metric:    { background: C.grayLt, borderRadius: 8, padding: '10px 14px', textAlign: 'center' },
  mLabel:    { fontSize: 10, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' },
  mValue:    { fontSize: 22, fontWeight: 700, color: C.text, marginTop: 2 },
  mSub:      { fontSize: 11, color: C.textMuted, marginTop: 2 },
  grid4:     { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 },
  grid2:     { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 },
  select:    { fontSize: 13, padding: '6px 10px', borderRadius: 7, border: `0.5px solid ${C.border}`, background: '#fff', color: C.text, cursor: 'pointer' },
  btn:       { fontSize: 12, padding: '7px 14px', borderRadius: 7, border: `0.5px solid ${C.border}`, background: '#fff', color: C.text, cursor: 'pointer', fontWeight: 600 },
  btnPrimary:{ fontSize: 12, padding: '7px 14px', borderRadius: 7, border: 'none', background: C.teal, color: '#fff', cursor: 'pointer', fontWeight: 600 },
  badge:     (bg, color) => ({ display: 'inline-block', background: bg, color, fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10 }),
  row:       { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 },
  pill:      (color) => ({ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block', marginRight: 4 }),
  eventRow:  { display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0', borderBottom: `0.5px solid ${C.border}` },
  input:     { fontSize: 12, padding: '5px 8px', borderRadius: 6, border: `0.5px solid ${C.border}`, background: '#fff', color: C.text },
  alert:     (type) => ({
    background: type === 'ok' ? C.tealLt : type === 'warn' ? C.amberLt : C.dangerLt,
    border: `0.5px solid ${type === 'ok' ? C.teal : type === 'warn' ? C.amber : C.danger}`,
    color: type === 'ok' ? '#085041' : type === 'warn' ? '#633806' : '#A32D2D',
    borderRadius: 7, padding: '8px 12px', fontSize: 12, marginBottom: 10,
  }),
};

// ── Tooltip personalizado ─────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: C.text }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || C.text, marginBottom: 2 }}>
          <span style={s.pill(p.color || C.teal)} />
          {p.name}: <strong>{Math.round(p.value).toLocaleString('es-CL')}</strong>
        </div>
      ))}
    </div>
  );
};

// ── Componente principal ──────────────────────────────────────────────────────
export default function App() {
  const [skus,       setSkus]       = useState([]);
  const [selSku,     setSelSku]     = useState('');
  const [result,     setResult]     = useState(null);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState('');
  const [dbStatus,   setDbStatus]   = useState(null);
  const [csvMode,    setCsvMode]    = useState(false);
  const [csvPath,    setCsvPath]    = useState('/app/data/ventas.csv');
  const [periods,    setPeriods]    = useState(12);
  const [events,     setEvents]     = useState([
    { name: 'promo_verano', label: 'Promo verano', dates: '', value: 1.25, active: false },
    { name: 'nuevo_competidor', label: 'Nuevo competidor', dates: '', value: 0.88, active: false },
  ]);

  // ── Health check ────────────────────────────────────────────────────────────
  useEffect(() => {
    axios.get(`${API}/health`)
      .then(r => setDbStatus(r.data))
      .catch(() => setDbStatus({ status: 'error' }));
  }, []);

  // ── Cargar lista de SKUs ─────────────────────────────────────────────────
  useEffect(() => {
    const params = csvMode ? { use_csv: csvPath } : {};
    axios.get(`${API}/skus`, { params })
      .then(r => {
        setSkus(r.data);
        if (r.data.length > 0 && !selSku) setSelSku(r.data[0].sku);
      })
      .catch(e => setError(`Error cargando SKUs: ${e.message}`));
  }, [csvMode, csvPath]);

  // ── Generar forecast ─────────────────────────────────────────────────────
  const runForecast = useCallback(async (forceRetrain = false) => {
    if (!selSku) return;
    setLoading(true);
    setError('');
    setResult(null);

    const activeEvents = events
      .filter(e => e.active && e.dates.trim())
      .map(e => ({
        name:  e.name,
        dates: e.dates.split(',').map(d => d.trim()).filter(Boolean),
        value: parseFloat(e.value),
        label: e.label,
      }));

    try {
      const { data } = await axios.post(`${API}/forecast`, {
        sku:           selSku,
        periods:       Number(periods),
        freq:          'MS',
        events:        activeEvents,
        force_retrain: forceRetrain,
        use_csv:       csvMode ? csvPath : null,
      });
      setResult(data);
    } catch (e) {
      setError(`Error: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  }, [selSku, periods, events, csvMode, csvPath]);

  // ── Combinar historial + forecast para el gráfico ─────────────────────────
  const chartData = React.useMemo(() => {
    if (!result) return [];
    const hist = (result.history || []).map(h => ({
      fecha: h.fecha?.slice(0, 7),
      real:  Math.round(h.real),
    }));
    const lastHistDate = hist[hist.length - 1]?.fecha;
    const fore = (result.forecast || [])
      .filter(f => f.ds >= (lastHistDate || ''))
      .map(f => ({
        fecha:      f.ds?.slice(0, 7),
        forecast:   Math.round(f.yhat),
        lowerBound: Math.round(f.yhat_lower),
        upperBound: Math.round(f.yhat_upper),
        trend:      Math.round(f.trend),
      }));
    // Merge: historial primero, luego forecast
    const merged = {};
    hist.forEach(h => { merged[h.fecha] = { ...merged[h.fecha], ...h }; });
    fore.forEach(f => { merged[f.fecha] = { ...merged[f.fecha], ...f }; });
    return Object.values(merged).sort((a, b) => a.fecha.localeCompare(b.fecha));
  }, [result]);

  const metrics  = result?.metrics || {};
  const mapeOk   = metrics.mape !== null && metrics.mape !== undefined;
  const mapeType = !mapeOk ? 'warn' : metrics.mape < 10 ? 'ok' : metrics.mape < 20 ? 'warn' : 'error';
  const todayStr = new Date().toISOString().slice(0, 7);

  return (
    <div style={s.app}>
      {/* Topbar */}
      <div style={s.topbar}>
        <div>
          <div style={s.topTitle}>Traverso S.A. — Sistema de Forecast de Demanda</div>
          <div style={s.topSub}>Motor Prophet · Piloto v1.0</div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {dbStatus && (
            <span style={s.badge(dbStatus.db?.ok ? C.tealLt : C.dangerLt,
                                  dbStatus.db?.ok ? '#085041' : '#A32D2D')}>
              {dbStatus.db?.ok ? '● SQL conectado' : '● Sin conexión SQL'}
            </span>
          )}
          <span style={s.badge(C.purpleLt, C.purple)}>
            {result?.from_cache ? 'Modelo en caché' : result ? 'Modelo entrenado' : 'Sin forecast'}
          </span>
        </div>
      </div>

      <div style={s.main}>

        {/* Modo de datos */}
        <div style={{ ...s.card, marginBottom: 12 }}>
          <div style={s.row}>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.textMuted }}>Fuente de datos:</span>
            <label style={{ fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5 }}>
              <input type="radio" checked={!csvMode} onChange={() => setCsvMode(false)} />
              SQL Server (directo)
            </label>
            <label style={{ fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5 }}>
              <input type="radio" checked={csvMode} onChange={() => setCsvMode(true)} />
              CSV (modo offline)
            </label>
            {csvMode && (
              <input style={{ ...s.input, flex: 1, minWidth: 280 }}
                value={csvPath} onChange={e => setCsvPath(e.target.value)}
                placeholder="Ruta al CSV: /app/data/ventas.csv" />
            )}
          </div>
        </div>

        {/* Controles */}
        <div style={s.card}>
          <div style={s.row}>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.textMuted }}>SKU:</span>
            <select style={{ ...s.select, flex: 1, maxWidth: 400 }}
              value={selSku} onChange={e => setSelSku(e.target.value)}>
              {skus.map(sk => (
                <option key={sk.sku} value={sk.sku}>
                  {sk.sku} — {sk.descripcion} ({Math.round(sk.volumen_total || 0).toLocaleString('es-CL')} u. total)
                </option>
              ))}
            </select>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.textMuted }}>Períodos:</span>
            <select style={s.select} value={periods} onChange={e => setPeriods(e.target.value)}>
              {[3,6,9,12,18,24].map(p => <option key={p} value={p}>{p} meses</option>)}
            </select>
            <button style={s.btnPrimary} onClick={() => runForecast(false)} disabled={loading || !selSku}>
              {loading ? 'Calculando...' : '▶ Generar forecast'}
            </button>
            <button style={s.btn} onClick={() => runForecast(true)} disabled={loading || !selSku}
              title="Reentrena el modelo con los datos actuales">
              ↺ Reentrenar
            </button>
          </div>
        </div>

        {error && <div style={s.alert('error')}>{error}</div>}

        {/* Métricas */}
        {result && (
          <div style={s.grid4}>
            <div style={s.metric}>
              <div style={s.mLabel}>MAPE</div>
              <div style={{ ...s.mValue, color: mapeType === 'ok' ? C.teal : mapeType === 'warn' ? C.amber : C.danger }}>
                {mapeOk ? `${metrics.mape}%` : 'N/D'}
              </div>
              <div style={s.mSub}>Error promedio</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>MAE</div>
              <div style={s.mValue}>{mapeOk ? Math.round(metrics.mae).toLocaleString('es-CL') : 'N/D'}</div>
              <div style={s.mSub}>Error absoluto medio</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>Historial</div>
              <div style={s.mValue}>{metrics.n_train ?? '—'}</div>
              <div style={s.mSub}>Períodos de entrenamiento</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>Forecast</div>
              <div style={s.mValue}>{Math.round(result.forecast?.find(f => f.ds >= todayStr)?.yhat || 0).toLocaleString('es-CL')}</div>
              <div style={s.mSub}>Próximo mes (u.)</div>
            </div>
          </div>
        )}

        {/* Gráfico principal */}
        {result && chartData.length > 0 && (
          <div style={s.card}>
            <div style={s.cardTitle}>
              Demanda histórica y forecast — {selSku}
              {result.from_cache && <span style={{ ...s.badge(C.grayLt, C.textMuted), marginLeft: 8 }}>desde caché</span>}
            </div>
            {mapeOk && (
              <div style={s.alert(mapeType)}>
                {mapeType === 'ok'
                  ? `Precisión del modelo: MAPE ${metrics.mape}% — Excelente (objetivo: <10%)`
                  : mapeType === 'warn'
                  ? `Precisión del modelo: MAPE ${metrics.mape}% — Aceptable. Mejorará con más historial y regressores.`
                  : `Precisión del modelo: MAPE ${metrics.mape}% — Alta. Considerar más historial o ajuste de parámetros.`}
              </div>
            )}
            {/* Leyenda custom */}
            <div style={{ display: 'flex', gap: 18, marginBottom: 10, fontSize: 12, color: C.textMuted }}>
              {[['Venta real', C.blue], ['Forecast', C.teal], ['Intervalo 90%', C.teal]].map(([label, color]) => (
                <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ ...s.pill(color), opacity: label.includes('Intervalo') ? 0.3 : 1 }} />
                  {label}
                </span>
              ))}
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="fecha" tick={{ fontSize: 11, fill: C.textMuted }}
                  tickFormatter={v => v?.slice(0, 7)} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 11, fill: C.textMuted }}
                  tickFormatter={v => v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine x={todayStr} stroke={C.amber} strokeDasharray="4 4"
                  label={{ value: 'Hoy', fill: C.amber, fontSize: 10 }} />
                <Area dataKey="upperBound" fill={C.teal} stroke="none" fillOpacity={0.12} name="Límite superior" />
                <Area dataKey="lowerBound" fill="#fff" stroke="none" fillOpacity={1} name="Límite inferior" />
                <Bar dataKey="real"     fill={C.blueLt}  stroke={C.blue}  strokeWidth={1} name="Venta real" barSize={14} />
                <Line dataKey="forecast" stroke={C.teal}  strokeWidth={2.5} dot={false}  name="Forecast" />
                <Line dataKey="trend"    stroke={C.purple} strokeWidth={1}   dot={false}  strokeDasharray="4 3" name="Tendencia" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Eventos comerciales */}
        <div style={s.grid2}>
          <div style={s.card}>
            <div style={s.cardTitle}>Ajustes comerciales (regressores)</div>
            <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 10 }}>
              Activa eventos para ver su impacto en el forecast. Ingresa fechas separadas por coma (AAAA-MM-DD).
            </div>
            {events.map((ev, i) => (
              <div key={i} style={s.eventRow}>
                <input type="checkbox" checked={ev.active}
                  onChange={e => setEvents(events.map((x, j) => j === i ? { ...x, active: e.target.checked } : x))} />
                <input style={{ ...s.input, width: 130 }} value={ev.label}
                  onChange={e => setEvents(events.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
                <input style={{ ...s.input, flex: 1 }} placeholder="2025-02-01, 2025-02-28"
                  value={ev.dates}
                  onChange={e => setEvents(events.map((x, j) => j === i ? { ...x, dates: e.target.value } : x))} />
                <input type="number" style={{ ...s.input, width: 64 }} step="0.01" min="0"
                  value={ev.value} title="1.25 = +25%, 0.85 = -15%"
                  onChange={e => setEvents(events.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <span style={{ fontSize: 10, color: C.textMuted, width: 50 }}>
                  {ev.value >= 1 ? `+${Math.round((ev.value - 1) * 100)}%` : `-${Math.round((1 - ev.value) * 100)}%`}
                </span>
              </div>
            ))}
            <button style={{ ...s.btn, marginTop: 10, fontSize: 11 }}
              onClick={() => setEvents([...events, { name: `evento_${events.length + 1}`, label: 'Nuevo evento', dates: '', value: 1.0, active: true }])}>
              + Agregar evento
            </button>
          </div>

          {/* Tabla de forecast */}
          <div style={s.card}>
            <div style={s.cardTitle}>Forecast mensual detallado</div>
            <div style={{ overflowY: 'auto', maxHeight: 280 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: C.grayLt }}>
                    {['Mes', 'Forecast', 'Mín (90%)', 'Máx (90%)'].map(h => (
                      <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: C.textMuted,
                        borderBottom: `0.5px solid ${C.border}`, fontWeight: 600, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(result?.forecast || []).filter(f => f.ds >= todayStr).map((f, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : C.grayLt }}>
                      <td style={{ padding: '5px 10px', color: C.textMuted }}>{f.ds?.slice(0, 7)}</td>
                      <td style={{ padding: '5px 10px', fontWeight: 700, color: C.teal }}>
                        {Math.round(f.yhat).toLocaleString('es-CL')}
                      </td>
                      <td style={{ padding: '5px 10px', color: C.textMuted }}>
                        {Math.round(f.yhat_lower).toLocaleString('es-CL')}
                      </td>
                      <td style={{ padding: '5px 10px', color: C.textMuted }}>
                        {Math.round(f.yhat_upper).toLocaleString('es-CL')}
                      </td>
                    </tr>
                  ))}
                  {!result && (
                    <tr><td colSpan={4} style={{ padding: '20px 10px', color: C.textMuted, textAlign: 'center' }}>
                      Selecciona un SKU y genera el forecast
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* SKUs disponibles */}
        {skus.length > 0 && (
          <div style={s.card}>
            <div style={s.cardTitle}>SKUs disponibles en el historial ({skus.length})</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: C.grayLt }}>
                    {['SKU', 'Descripción', 'Vol. total', 'Primera venta', 'Última venta', 'Meses'].map(h => (
                      <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: C.textMuted,
                        borderBottom: `0.5px solid ${C.border}`, fontWeight: 600, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {skus.slice(0, 20).map((sk, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : C.grayLt, cursor: 'pointer' }}
                      onClick={() => setSelSku(sk.sku)}>
                      <td style={{ padding: '5px 10px', fontWeight: 700, color: C.teal }}>{sk.sku}</td>
                      <td style={{ padding: '5px 10px' }}>{sk.descripcion}</td>
                      <td style={{ padding: '5px 10px' }}>{Math.round(sk.volumen_total || 0).toLocaleString('es-CL')}</td>
                      <td style={{ padding: '5px 10px', color: C.textMuted }}>{sk.primera_venta?.slice(0, 7)}</td>
                      <td style={{ padding: '5px 10px', color: C.textMuted }}>{sk.ultima_venta?.slice(0, 7)}</td>
                      <td style={{ padding: '5px 10px' }}>{sk.meses_con_venta}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {skus.length > 20 && (
                <div style={{ fontSize: 11, color: C.textMuted, padding: '8px 10px' }}>
                  Mostrando 20 de {skus.length} SKUs. Usa el selector para acceder a todos.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
