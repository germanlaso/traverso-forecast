// PrecisionForecast.js — Dashboard de precisión del forecast (06-10-2026)
//
// Compara la venta real con lo que el forecast predijo con 1 o 2 semanas de
// anticipación. Reglas (ver precision_api.py):
//   - Los horizontes NUNCA se mezclan: todo lo que se ve corresponde a UNA anticipación.
//   - Sesgo% = (Σ forecast − Σ real) / Σ real  → + sobredimensionado, − subdimensionado.
//   - WMAPE% = Σ |forecast − real| / Σ real    → magnitud del error, no se cancela entre SKU.
//   - Agregación en cajas. Línea = línea preferida (cada SKU en UNA línea).
//   - Semanas sin forecast para la anticipación elegida se muestran como hueco, no se interpolan.
import React, { useState, useEffect, useMemo } from 'react';
import { ComposedChart, Bar, Line, Cell, LabelList, XAxis, YAxis, CartesianGrid,
         Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import axios from 'axios';

const API = process.env.REACT_APP_API_BASE || '';

const C = {
  teal:'#1D9E75', tealLt:'#E1F5EE', blue:'#185FA5', blueLt:'#E6F1FB',
  purple:'#534AB7', purpleLt:'#EEEDFE', amber:'#EF9F27', amberLt:'#FAEEDA',
  gray:'#5F5E5A', grayLt:'#F1EFE8', danger:'#E24B4A', dangerLt:'#FCEBEB',
  border:'#D3D1C7', text:'#2C2C2A', textMuted:'#888780',
};
// Sobredimensionado → riesgo de sobrestock/merma (ámbar). Subdimensionado → riesgo de quiebre (rojo).
const COLOR_SOBRE = C.amber;
const COLOR_SUB = C.danger;

const s = {
  card: {background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:10,padding:'16px 20px',marginBottom:16},
  cardTitle: {fontSize:13,fontWeight:700,color:C.text,marginBottom:12},
  grid: {display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:10,marginBottom:16},
  metric: {background:C.grayLt,borderRadius:8,padding:'10px 14px',textAlign:'center'},
  mLabel: {fontSize:10,color:C.textMuted,textTransform:'uppercase',letterSpacing:'0.05em'},
  mValue: {fontSize:22,fontWeight:700,color:C.text,marginTop:2},
  mSub: {fontSize:11,color:C.textMuted,marginTop:2},
  row: {display:'flex',alignItems:'center',gap:10,flexWrap:'wrap',marginBottom:14},
  label: {fontSize:11,color:C.textMuted,fontWeight:600},
  input: {fontSize:12,padding:'6px 8px',borderRadius:6,border:`0.5px solid ${C.border}`,background:'#fff',color:C.text},
  btn: (activo)=>({fontSize:12,padding:'7px 14px',borderRadius:7,cursor:'pointer',fontWeight:600,
    border: activo ? 'none' : `0.5px solid ${C.border}`, background: activo ? C.teal : '#fff', color: activo ? '#fff' : C.text}),
  chip: {display:'inline-flex',alignItems:'center',gap:6,background:C.tealLt,color:C.teal,fontSize:11,fontWeight:700,padding:'3px 10px',borderRadius:12},
  badge: (bg,color)=>({display:'inline-block',background:bg,color,fontSize:10,fontWeight:700,padding:'2px 7px',borderRadius:10,marginLeft:4}),
  th: {textAlign:'left',padding:'7px 8px',fontSize:11,color:C.textMuted,borderBottom:`0.5px solid ${C.border}`,cursor:'pointer',whiteSpace:'nowrap',userSelect:'none'},
  td: {padding:'6px 8px',fontSize:12,borderBottom:`0.5px solid ${C.border}`},
  alert: {background:C.dangerLt,border:`0.5px solid ${C.danger}`,color:'#A32D2D',borderRadius:7,padding:'8px 12px',fontSize:12,marginBottom:10},
};

// ── Formato es-CL ─────────────────────────────────────────────────────────────
const fmtNum = (v, dec = 0) => (v == null || isNaN(v)) ? '—'
  : Number(v).toLocaleString('es-CL', {minimumFractionDigits: dec, maximumFractionDigits: dec});
const fmtPct = (v, signo = true) => (v == null || isNaN(v)) ? '—'
  : `${signo && v > 0 ? '+' : ''}${fmtNum(v, 1)}%`;
const sentido = (v) => v == null ? '' : Math.abs(v) < 0.5 ? 'en línea' : v > 0 ? 'sobredimensionado' : 'subdimensionado';
const rangoSemana = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  const f = new Date(d); f.setDate(d.getDate() + 6);
  const dm = (x) => `${String(x.getDate()).padStart(2,'0')}-${String(x.getMonth()+1).padStart(2,'0')}`;
  return `${dm(d)} – ${dm(f)}`;
};

function TooltipSemana({active, payload}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:8,padding:'10px 14px',fontSize:12,maxWidth:340}}>
      <div style={{fontWeight:700,marginBottom:6,color:C.text}}>Semana {p.rango}</div>
      {p.hueco ? (
        <div style={{color:C.textMuted}}>Sin forecast con esta anticipación (no hubo reentrenamiento en el corte correspondiente).</div>
      ) : (
        <>
          <div style={{marginBottom:6,color:C.text}}>{p.frase}</div>
          <div>Venta real: <strong>{fmtNum(p.real_cj)} cj</strong></div>
          <div>Forecast: <strong>{fmtNum(p.yhat_cj)} cj</strong> <span style={{color:C.textMuted}}>(corte {p.corte})</span></div>
          <div>Sesgo: <strong style={{color: p.sesgo_pct > 0 ? COLOR_SOBRE : COLOR_SUB}}>{fmtPct(p.sesgo_pct)}</strong> · WMAPE: <strong style={{color:C.purple}}>{fmtPct(p.wmape_pct, false)}</strong></div>
          <div style={{color:C.textMuted,marginTop:4}}>{p.n_sku} SKU en el cálculo</div>
        </>
      )}
    </div>
  );
}

const COLUMNAS = [
  ['sku','SKU'], ['descripcion','Descripción'], ['categoria','Categoría'], ['linea','Línea'],
  ['real_cj','Real (cj)'], ['yhat_cj','Forecast (cj)'], ['error_abs_cj','Error abs. (cj)'],
  ['sesgo_pct','Sesgo'], ['wmape_pct','WMAPE'],
];

export default function PrecisionForecast() {
  const [filtros, setFiltros] = useState(null);
  const [horizonte, setHorizonte] = useState(1);
  const [categoria, setCategoria] = useState('');
  const [linea, setLinea] = useState('');
  const [texto, setTexto] = useState('');
  const [q, setQ] = useState('');                 // texto con debounce
  const [skuSel, setSkuSel] = useState('');       // drill-down desde el ranking
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [data, setData] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [orden, setOrden] = useState({col:'error_abs_cj', asc:false});
  const [verTodos, setVerTodos] = useState(false);

  useEffect(() => {
    axios.get(`${API}/precision/filtros`)
      .then(r => setFiltros(r.data))
      .catch(() => setError('No se pudieron cargar los filtros.'));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setQ(texto.trim()), 400);
    return () => clearTimeout(t);
  }, [texto]);

  // Al cambiar de horizonte, el rango de semanas cambia: se limpia.
  useEffect(() => { setDesde(''); setHasta(''); }, [horizonte]);

  useEffect(() => {
    const params = {horizonte};
    if (categoria) params.categoria = categoria;
    if (linea) params.linea = linea;
    if (q) params.q = q;
    if (skuSel) params.skus = skuSel;
    if (desde) params.desde = desde;
    if (hasta) params.hasta = hasta;
    setCargando(true); setError('');
    axios.get(`${API}/precision`, {params})
      .then(r => setData(r.data))
      .catch(e => setError(e?.response?.data?.detail || 'Error al cargar la precisión del forecast.'))
      .finally(() => setCargando(false));
  }, [horizonte, categoria, linea, q, skuSel, desde, hasta]);

  const nombreLinea = useMemo(() => {
    const m = {};
    (filtros?.lineas || []).forEach(l => { m[l.codigo] = l.nombre; });
    return m;
  }, [filtros]);

  const semanasH = filtros?.semanas_evaluables?.[String(horizonte)] || [];

  // Serie + huecos ordenados por semana (los huecos se ven, no se interpolan)
  const serieGrafico = useMemo(() => {
    if (!data) return [];
    const pts = (data.serie || []).map(p => ({...p, hueco:false}));
    (data.semanas_sin_vintage || []).forEach(w => {
      pts.push({semana:w, rango:rangoSemana(w), hueco:true, sesgo_pct:null, wmape_pct:null});
    });
    return pts.sort((a, b) => a.semana.localeCompare(b.semana));
  }, [data]);

  const ranking = useMemo(() => {
    const filas = [...(data?.ranking_sku || [])];
    const {col, asc} = orden;
    filas.sort((a, b) => {
      const va = a[col], vb = b[col];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;                    // nulos (bajo volumen) siempre al final
      if (vb == null) return -1;
      const r = typeof va === 'string' ? va.localeCompare(vb) : va - vb;
      return asc ? r : -r;
    });
    return filas;
  }, [data, orden]);

  const kpi = data?.kpi;
  const ultima = serieGrafico.filter(p => !p.hueco).slice(-1)[0];
  const skuInfo = skuSel ? (filtros?.skus || []).find(x => x.sku === skuSel) : null;
  const filasVisibles = verTodos ? ranking : ranking.slice(0, 30);

  const ordenarPor = (col) => setOrden(o => ({col, asc: o.col === col ? !o.asc : false}));

  return (
    <div>
      {/* ── Encabezado y selector de anticipación ── */}
      <div style={s.card}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:12}}>
          <div>
            <div style={{fontSize:15,fontWeight:700,color:C.text}}>Precisión del forecast</div>
            <div style={{fontSize:12,color:C.textMuted,marginTop:2}}>
              Venta real vs. lo que el forecast predijo con anticipación. Cada anticipación se evalúa por separado.
            </div>
          </div>
          <div style={{display:'flex',gap:6}}>
            <button style={s.btn(horizonte === 1)} onClick={() => setHorizonte(1)}>1 semana de anticipación</button>
            <button style={s.btn(horizonte === 2)} onClick={() => setHorizonte(2)}>2 semanas de anticipación</button>
          </div>
        </div>

        {/* ── Filtros ── */}
        <div style={{...s.row, marginTop:14, marginBottom:0}}>
          <span style={s.label}>SKU / nombre</span>
          <input style={{...s.input, width:220}} placeholder="Código o parte del nombre..."
                 value={texto} onChange={e => { setTexto(e.target.value); setSkuSel(''); }} />
          <span style={s.label}>Categoría</span>
          <select style={s.input} value={categoria} onChange={e => setCategoria(e.target.value)}>
            <option value="">Todas</option>
            {(filtros?.categorias || []).map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <span style={s.label}>Línea</span>
          <select style={s.input} value={linea} onChange={e => setLinea(e.target.value)}>
            <option value="">Todas</option>
            {(filtros?.lineas || []).map(l => (
              <option key={l.codigo} value={l.codigo}>
                {l.codigo === 'SIN_LINEA' ? l.nombre : `${l.codigo}${l.nombre && l.nombre !== l.codigo ? ' — ' + l.nombre : ''}`}
              </option>
            ))}
          </select>
          <span style={s.label}>Semanas</span>
          <select style={s.input} value={desde} onChange={e => setDesde(e.target.value)}>
            <option value="">desde el inicio</option>
            {semanasH.map(w => <option key={w} value={w}>{rangoSemana(w)}</option>)}
          </select>
          <select style={s.input} value={hasta} onChange={e => setHasta(e.target.value)}>
            <option value="">hasta la última</option>
            {semanasH.map(w => <option key={w} value={w}>{rangoSemana(w)}</option>)}
          </select>
          {(categoria || linea || texto || skuSel || desde || hasta) && (
            <button style={s.btn(false)} onClick={() => { setCategoria(''); setLinea(''); setTexto(''); setSkuSel(''); setDesde(''); setHasta(''); }}>
              Limpiar filtros
            </button>
          )}
        </div>
        {skuSel && (
          <div style={{marginTop:10}}>
            <span style={s.chip}>
              {skuSel}{skuInfo ? ` — ${skuInfo.descripcion}` : ''}
              <span style={{cursor:'pointer'}} onClick={() => setSkuSel('')} title="Quitar">✕</span>
            </span>
          </div>
        )}
      </div>

      {error && <div style={s.alert}>{error}</div>}
      {cargando && !data && <div style={{fontSize:12,color:C.textMuted,marginBottom:12}}>Cargando…</div>}

      {data && !kpi && (
        <div style={s.card}><div style={{fontSize:12,color:C.textMuted}}>Sin semanas evaluables para los filtros seleccionados.</div></div>
      )}

      {kpi && (
        <>
          {/* ── Frase de la última semana ── */}
          {ultima && (
            <div style={{...s.card, borderLeft:`4px solid ${ultima.sesgo_pct > 0 ? COLOR_SOBRE : COLOR_SUB}`}}>
              <div style={{fontSize:13,color:C.text}}>{ultima.frase}</div>
              <div style={{fontSize:11,color:C.textMuted,marginTop:4}}>
                Última semana cerrada evaluada · WMAPE {fmtPct(ultima.wmape_pct, false)} · {ultima.n_sku} SKU
              </div>
            </div>
          )}

          {/* ── KPI de la ventana ── */}
          <div style={s.grid}>
            <div style={s.metric}>
              <div style={s.mLabel}>Sesgo neto</div>
              <div style={{...s.mValue, color: kpi.sesgo_pct > 0 ? COLOR_SOBRE : COLOR_SUB}}>{fmtPct(kpi.sesgo_pct)}</div>
              <div style={s.mSub}>{sentido(kpi.sesgo_pct)}</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>WMAPE</div>
              <div style={{...s.mValue, color:C.purple}}>{fmtPct(kpi.wmape_pct, false)}</div>
              <div style={s.mSub}>magnitud del error por SKU</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>Venta real</div>
              <div style={s.mValue}>{fmtNum(kpi.real_cj)}</div>
              <div style={s.mSub}>cajas en la ventana</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>Forecast</div>
              <div style={s.mValue}>{fmtNum(kpi.yhat_cj)}</div>
              <div style={s.mSub}>cajas en la ventana</div>
            </div>
            <div style={s.metric}>
              <div style={s.mLabel}>Semanas evaluadas</div>
              <div style={s.mValue}>{kpi.n_semanas}</div>
              <div style={s.mSub}>
                {kpi.n_sku} SKU{(data.semanas_sin_vintage || []).length ? ` · ${data.semanas_sin_vintage.length} sin forecast` : ''}
              </div>
            </div>
          </div>

          {/* ── Gráfico: desviación en el tiempo ── */}
          <div style={s.card}>
            <div style={s.cardTitle}>
              Desviación semanal — {horizonte === 1 ? '1 semana' : '2 semanas'} de anticipación
              {skuSel ? ` · SKU ${skuSel}` : ''}
            </div>
            <div style={{display:'flex',gap:16,fontSize:11,color:C.textMuted,marginBottom:8,flexWrap:'wrap'}}>
              <span><span style={{display:'inline-block',width:10,height:10,background:COLOR_SOBRE,borderRadius:2,marginRight:4}}/>Sesgo sobre 0: sobredimensionado (riesgo de sobrestock)</span>
              <span><span style={{display:'inline-block',width:10,height:10,background:COLOR_SUB,borderRadius:2,marginRight:4}}/>Sesgo bajo 0: subdimensionado (riesgo de quiebre)</span>
              <span><span style={{display:'inline-block',width:14,height:2,background:C.purple,marginRight:4,verticalAlign:'middle'}}/>WMAPE (magnitud)</span>
            </div>
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={serieGrafico} margin={{top:20,right:20,left:0,bottom:5}}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="rango" tick={{fontSize:11}}
                       tickFormatter={(v) => {
                         const p = serieGrafico.find(x => x.rango === v);
                         return p && p.hueco ? `${v} (sin forecast)` : v;
                       }} />
                <YAxis tick={{fontSize:11}} tickFormatter={(v) => `${v}%`} />
                <Tooltip content={<TooltipSemana />} />
                <ReferenceLine y={0} stroke={C.gray} strokeWidth={1.5} />
                <Bar dataKey="sesgo_pct" name="Sesgo" maxBarSize={56}>
                  {serieGrafico.map((p, i) => (
                    <Cell key={i} fill={p.sesgo_pct > 0 ? COLOR_SOBRE : COLOR_SUB} />
                  ))}
                  <LabelList dataKey="sesgo_pct" position="top" style={{fontSize:11,fontWeight:700,fill:C.text}}
                             formatter={(v) => (v == null ? '' : fmtPct(v))} />
                </Bar>
                <Line dataKey="wmape_pct" name="WMAPE" stroke={C.purple} strokeWidth={2}
                      dot={{r:3}} connectNulls={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* ── Ranking por SKU ── */}
          <div style={s.card}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'baseline',flexWrap:'wrap',gap:8}}>
              <div style={s.cardTitle}>Detalle por SKU — ordenado por error absoluto</div>
              <div style={{fontSize:11,color:C.textMuted}}>Clic en una fila para ver su evolución en el gráfico</div>
            </div>
            <div style={{overflowX:'auto'}}>
              <table style={{width:'100%',borderCollapse:'collapse'}}>
                <thead>
                  <tr>
                    {COLUMNAS.map(([col, lbl]) => (
                      <th key={col} style={s.th} onClick={() => ordenarPor(col)}>
                        {lbl}{orden.col === col ? (orden.asc ? ' ▲' : ' ▼') : ''}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filasVisibles.map((r, i) => (
                    <tr key={r.sku} onClick={() => setSkuSel(r.sku)}
                        style={{cursor:'pointer',background: r.sku === skuSel ? C.tealLt : i % 2 ? C.grayLt : '#fff'}}>
                      <td style={{...s.td,fontWeight:700,color:C.teal}}>{r.sku}</td>
                      <td style={s.td}>
                        {r.descripcion}
                        {r.con_evento && <span style={s.badge(C.purpleLt, C.purple)} title="Forecast con eventos manuales">evento</span>}
                        {r.bajo_volumen && <span style={s.badge(C.grayLt, C.gray)} title="Venta promedio bajo el umbral: no se informa %">bajo vol.</span>}
                      </td>
                      <td style={s.td}>{r.categoria}</td>
                      <td style={s.td} title={nombreLinea[r.linea] || ''}>{r.linea === 'SIN_LINEA' ? 'Sin línea' : r.linea}</td>
                      <td style={{...s.td,textAlign:'right'}}>{fmtNum(r.real_cj, 1)}</td>
                      <td style={{...s.td,textAlign:'right'}}>{fmtNum(r.yhat_cj, 1)}</td>
                      <td style={{...s.td,textAlign:'right',fontWeight:600}}>{fmtNum(r.error_abs_cj, 1)}</td>
                      <td style={{...s.td,textAlign:'right',fontWeight:700,color: r.sesgo_pct == null ? C.textMuted : r.sesgo_pct > 0 ? COLOR_SOBRE : COLOR_SUB}}>
                        {fmtPct(r.sesgo_pct)}
                      </td>
                      <td style={{...s.td,textAlign:'right',color:C.purple}}>{fmtPct(r.wmape_pct, false)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ranking.length > 30 && (
              <div style={{marginTop:10}}>
                <button style={s.btn(false)} onClick={() => setVerTodos(v => !v)}>
                  {verTodos ? 'Ver solo los 30 primeros' : `Ver los ${ranking.length} SKU`}
                </button>
              </div>
            )}
          </div>

          {/* ── Cómo leer ── */}
          <div style={{fontSize:11,color:C.textMuted,lineHeight:1.6,marginBottom:16}}>
            <strong>Sesgo</strong> = (forecast − real) / real, sumando los SKU del filtro: indica la dirección neta.
            Los errores de signo opuesto entre SKU se compensan, por eso se acompaña del <strong>WMAPE</strong>
            = Σ|forecast − real| / real, que mide la magnitud total sin compensar.
            Totales en cajas. Solo semanas cerradas. Los SKU con venta promedio bajo {fmtNum(data.meta?.umbral_cj_semana, 0)} cj/semana
            no informan %, porque con denominadores tan chicos el porcentaje no es interpretable.
          </div>
        </>
      )}
    </div>
  );
}
