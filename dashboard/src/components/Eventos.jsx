import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
         ResponsiveContainer, ReferenceArea } from 'recharts';

const API = process.env.REACT_APP_API_BASE || '';

// Paleta replicada de App.js: C y s no se exportan, cada componente define la suya.
const C = {
  teal:'#1D9E75', tealLt:'#E1F5EE', tealMid:'#0F6E56',
  blue:'#185FA5', blueLt:'#E6F1FB',
  purple:'#534AB7', purpleLt:'#EEEDFE',
  amber:'#EF9F27', amberLt:'#FAEEDA',
  gray:'#5F5E5A', grayLt:'#F1EFE8',
  danger:'#E24B4A', dangerLt:'#FCEBEB',
  border:'#D3D1C7', text:'#2C2C2A', textMuted:'#888780',
};

const s = {
  card: {background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:10,padding:'16px 20px',marginBottom:16},
  cardTitle: {fontSize:13,fontWeight:700,color:C.text,marginBottom:12},
  row: {display:'flex',alignItems:'center',gap:10,flexWrap:'wrap',marginBottom:14},
  input: {fontSize:12,padding:'5px 8px',borderRadius:6,border:`0.5px solid ${C.border}`,background:'#fff',color:C.text},
  btn: {fontSize:12,padding:'7px 14px',borderRadius:7,border:`0.5px solid ${C.border}`,background:'#fff',color:C.text,cursor:'pointer',fontWeight:600},
  btnPrimary:{fontSize:12,padding:'7px 14px',borderRadius:7,border:'none',background:C.teal,color:'#fff',cursor:'pointer',fontWeight:600},
  metric: {background:C.grayLt,borderRadius:8,padding:'10px 14px',textAlign:'center'},
  mLabel: {fontSize:10,color:C.textMuted,textTransform:'uppercase',letterSpacing:'0.05em'},
  mValue: {fontSize:22,fontWeight:700,color:C.text,marginTop:2},
  mSub: {fontSize:11,color:C.textMuted,marginTop:2},
  grid3: {display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:10,marginBottom:12},
  th: {textAlign:'left',fontSize:11,color:C.textMuted,fontWeight:600,padding:'6px 8px',borderBottom:`0.5px solid ${C.border}`},
  td: {fontSize:12,padding:'6px 8px',borderBottom:`0.5px solid ${C.border}`},
  badge: (bg,color)=>({display:'inline-block',background:bg,color,fontSize:10,fontWeight:700,padding:'2px 8px',borderRadius:10}),
  alert: (type)=>({
    background:type==='ok'?C.tealLt:type==='warn'?C.amberLt:C.dangerLt,
    border:`0.5px solid ${type==='ok'?C.teal:type==='warn'?C.amber:C.danger}`,
    color:type==='ok'?'#085041':type==='warn'?'#633806':'#A32D2D',
    borderRadius:7,padding:'10px 12px',fontSize:12,marginBottom:10,lineHeight:1.5,
  }),
};

const fmt = (n) => (n === null || n === undefined || Number.isNaN(n))
  ? '—' : Math.round(n).toLocaleString('es-CL');

function errMsg(e) {
  const d = e?.response?.data?.detail;
  if (!d) return e?.message || 'Error desconocido';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => x.msg || JSON.stringify(x)).join(' · ');
  return JSON.stringify(d);
}

const COLOR_FASE = {suave: C.amber, fuerte: C.danger, base: C.purple};

/**
 * Buscador de SKU que filtra por CODIGO o por DESCRIPCION y muestra las dos.
 * No usa <datalist> a proposito: Chrome, Firefox y Safari renderizan el `value`
 * y el texto de la opcion de forma distinta, asi que la descripcion no se veria
 * de manera confiable.
 */
function BuscadorSku({skus, value, onChange}) {
  const [q, setQ] = useState('');
  const [abierto, setAbierto] = useState(false);

  const desc = skus.find(x => String(x.sku) === String(value))?.descripcion || '';
  const texto = abierto ? q : (value ? `${value}${desc ? ` — ${desc}` : ''}` : '');

  const filtrados = useMemo(() => {
    const t = q.trim().toLowerCase();
    const base = !t ? skus : skus.filter(x =>
      String(x.sku).toLowerCase().includes(t) ||
      String(x.descripcion || '').toLowerCase().includes(t));
    return base.slice(0, 12);
  }, [q, skus]);

  const elegir = (s) => { onChange(String(s)); setQ(''); setAbierto(false); };

  return (
    <div style={{position:'relative', minWidth:330}}>
      <input
        style={{...s.input, width:'100%'}}
        value={texto}
        placeholder="Código o nombre del producto"
        onFocus={() => {setQ(''); setAbierto(true);}}
        onChange={e => {setQ(e.target.value); setAbierto(true);}}
        onBlur={() => setTimeout(() => setAbierto(false), 120)}
        onKeyDown={e => {
          if (e.key === 'Escape') setAbierto(false);
          // Enter con un solo resultado: lo toma, para no obligar al mouse
          if (e.key === 'Enter' && filtrados.length === 1) elegir(filtrados[0].sku);
        }}
      />
      {abierto && filtrados.length > 0 && (
        <div style={{position:'absolute',top:'100%',left:0,right:0,zIndex:20,
                     background:'#fff',border:`0.5px solid ${C.border}`,
                     borderRadius:6,marginTop:2,maxHeight:260,overflowY:'auto',
                     boxShadow:'0 4px 12px rgba(0,0,0,.10)'}}>
          {filtrados.map(x => (
            // onMouseDown y no onClick: dispara ANTES del blur del input
            <div key={x.sku} onMouseDown={() => elegir(x.sku)}
                 style={{padding:'6px 10px',cursor:'pointer',fontSize:12,
                          borderBottom:`0.5px solid ${C.border}`}}
                 onMouseEnter={e => e.currentTarget.style.background = C.grayLt}
                 onMouseLeave={e => e.currentTarget.style.background = '#fff'}>
              <span style={{fontWeight:600}}>{x.sku}</span>
              <span style={{color:C.textMuted,marginLeft:8}}>{x.descripcion || '—'}</span>
            </div>
          ))}
        </div>
      )}
      {abierto && q.trim() && filtrados.length === 0 && (
        <div style={{position:'absolute',top:'100%',left:0,right:0,zIndex:20,
                     background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:6,
                     marginTop:2,padding:'8px 10px',fontSize:12,color:C.textMuted}}>
          Ningún producto coincide con "{q.trim()}"
        </div>
      )}
    </div>
  );
}

export default function Eventos({skus = []}) {
  const [lista, setLista]     = useState([]);
  const [sku, setSku]         = useState('');
  const [nombre, setNombre]   = useState('');
  const [desde, setDesde]     = useState('');
  const [hasta, setHasta]     = useState('');
  const [analisis, setAnalisis] = useState(null);
  const [fases, setFases]     = useState([]);
  const [preview, setPreview] = useState(null);
  const [cargando, setCargando] = useState('');   // '', 'analizar', 'preview', 'guardar'
  const [error, setError]     = useState('');
  const [aviso, setAviso]     = useState('');

  // La respuesta de /eventos son filas crudas de mrp_eventos y no trae
  // descripcion; se resuelve con el listado de SKU que ya tiene el dashboard.
  const descPorSku = useMemo(() => {
    const m = {};
    (skus || []).forEach(x => { m[String(x.sku)] = x.descripcion || ''; });
    return m;
  }, [skus]);

  const recargar = useCallback(() => {
    axios.get(`${API}/eventos`)
      .then(r => setLista(Array.isArray(r.data?.eventos) ? r.data.eventos : []))
      .catch(e => setError(errMsg(e)));
  }, []);

  useEffect(() => { recargar(); }, [recargar]);

  // Cualquier cambio en las fases invalida el preview: guardar con un preview
  // viejo seria guardar sin haber visto el efecto real de lo que se guarda.
  const editarFase = (i, campo, valor) => {
    setFases(fases.map((f, j) => j === i ? {...f, [campo]: valor} : f));
    setPreview(null);
  };

  const analizar = () => {
    setError(''); setAviso(''); setPreview(null); setAnalisis(null); setFases([]);
    if (!sku || !desde || !hasta) { setError('Elegí el SKU y las dos fechas.'); return; }
    if (desde > hasta) { setError('La fecha "desde" es posterior a la fecha "hasta".'); return; }
    setCargando('analizar');
    axios.post(`${API}/eventos/analizar`, {sku, fecha_desde: desde, fecha_hasta: hasta})
      .then(r => {
        const d = r.data || {};
        setAnalisis(d);
        setFases(Array.isArray(d.fases) ? d.fases : []);
        if (d.ok === false) setAviso(d.mensaje || 'No se pudo analizar el período.');
      })
      .catch(e => setError(errMsg(e)))
      .finally(() => setCargando(''));
  };

  const comprobar = () => {
    setError(''); setCargando('preview');
    axios.post(`${API}/eventos/preview`, {sku, fases})
      .then(r => setPreview(r.data || {}))
      .catch(e => setError(errMsg(e)))
      .finally(() => setCargando(''));
  };

  const guardar = () => {
    setError('');
    if (!nombre.trim()) { setError('Ponele un nombre al evento.'); return; }
    setCargando('guardar');
    axios.post(`${API}/eventos`, {nombre: nombre.trim(), sku, fases, tipo: 'pasado'})
      .then(() => {
        setAviso(`Evento guardado. Va a aplicarse en la próxima corrida del plan.`);
        setAnalisis(null); setFases([]); setPreview(null);
        setNombre(''); setDesde(''); setHasta('');
        recargar();
      })
      .catch(e => setError(errMsg(e)))
      .finally(() => setCargando(''));
  };

  const desactivar = (ev) => {
    setError('');
    axios.delete(`${API}/eventos`, {params: {nombre: ev.nombre, sku: ev.sku, solo_desactivar: true}})
      .then(() => { setAviso(`"${ev.nombre}" desactivado. El plan vuelve a calcularse sin esa corrección.`); recargar(); })
      .catch(e => setError(errMsg(e)));
  };

  const datosGrafico = (analisis?.semanas || []).map(w => ({
    semana: w.ds, real: w.real, habitual: w.base,
  }));

  const skuDesc = descPorSku[String(sku)] || '';
  const puedeGuardar = fases.length > 0 && preview !== null && cargando === '';

  return (
    <div>
      {error && <div style={s.alert('err')}>{error}</div>}
      {aviso && <div style={s.alert('ok')}>{aviso}</div>}

      {/* ── 1. Eventos cargados ─────────────────────────────────────────── */}
      <div style={s.card}>
        <div style={s.cardTitle}>Eventos registrados</div>
        {lista.length === 0 ? (
          <div style={{fontSize:12,color:C.textMuted}}>
            Todavía no hay eventos cargados.
          </div>
        ) : (
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead><tr>
              {['Evento','SKU','Descripción','Tramo','Desde','Hasta','Semanas','Estado',''].map(h =>
                <th key={h} style={s.th}>{h}</th>)}
            </tr></thead>
            <tbody>
              {lista.map(ev => (
                <tr key={ev.id}>
                  <td style={s.td}>{ev.nombre}</td>
                  <td style={s.td}>{ev.sku}</td>
                  <td style={{...s.td,color:C.textMuted,maxWidth:220,overflow:'hidden',
                               textOverflow:'ellipsis',whiteSpace:'nowrap'}}
                      title={descPorSku[String(ev.sku)] || ''}>
                    {descPorSku[String(ev.sku)] || '—'}
                  </td>
                  <td style={s.td}>
                    <span style={s.badge(C.grayLt, COLOR_FASE[ev.etiqueta] || C.gray)}>{ev.etiqueta}</span>
                  </td>
                  <td style={s.td}>{ev.fecha_desde}</td>
                  <td style={s.td}>{ev.fecha_hasta}</td>
                  <td style={s.td}>{ev.n_semanas}</td>
                  <td style={s.td}>
                    {ev.activo
                      ? <span style={s.badge(C.tealLt, C.tealMid)}>activo</span>
                      : <span style={s.badge(C.grayLt, C.textMuted)}>inactivo</span>}
                  </td>
                  <td style={s.td}>
                    {ev.activo && <button style={s.btn} onClick={() => desactivar(ev)}>Desactivar</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{fontSize:11,color:C.textMuted,marginTop:10}}>
          Desactivar no borra nada: la fila queda registrada y el plan vuelve a
          calcularse sin esa corrección. Para reactivarlo, volvé a guardarlo.
        </div>
      </div>

      {/* ── 2. Nuevo evento ─────────────────────────────────────────────── */}
      <div style={s.card}>
        <div style={s.cardTitle}>Registrar un evento pasado</div>
        <div style={{fontSize:12,color:C.textMuted,marginBottom:12,lineHeight:1.5}}>
          Indicá el período en que ocurrió algo que hizo vender distinto de lo
          normal — un quiebre de un competidor, una promoción grande, un cliente
          que compró de más. El sistema analiza las semanas y propone cómo
          corregirlo; después te muestra qué habría pasado el año pasado para que
          puedas decidir.
        </div>
        <div style={s.row}>
          <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Producto:</span>
          <BuscadorSku skus={skus} value={sku}
                       onChange={v => {setSku(v); setAnalisis(null); setPreview(null);}}/>
        </div>
        <div style={s.row}>
          <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Nombre:</span>
          <input style={{...s.input,width:250}} value={nombre}
                 onChange={e => setNombre(e.target.value)}
                 placeholder="quiebre del competidor 2024"/>
          <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Desde:</span>
          <input type="date" style={s.input} value={desde}
                 onChange={e => {setDesde(e.target.value); setAnalisis(null); setPreview(null);}}/>
          <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Hasta:</span>
          <input type="date" style={s.input} value={hasta}
                 onChange={e => {setHasta(e.target.value); setAnalisis(null); setPreview(null);}}/>
          <button style={s.btnPrimary} onClick={analizar} disabled={cargando !== ''}>
            {cargando === 'analizar' ? 'Analizando...' : 'Analizar período'}
          </button>
        </div>
        <div style={{fontSize:11,color:C.textMuted}}>
          Las fechas pueden ser aproximadas: el sistema las ajusta a semanas
          completas. Los eventos futuros (una promoción que todavía no ocurrió)
          todavía no se pueden cargar acá.
        </div>
      </div>

      {/* ── 3. Análisis ─────────────────────────────────────────────────── */}
      {analisis?.ok && (
        <div style={s.card}>
          <div style={s.cardTitle}>
            Qué encontró el sistema — {sku}{skuDesc ? ` · ${skuDesc}` : ''}
          </div>
          <div style={s.alert('ok')}>{analisis.mensaje}</div>

          {datosGrafico.length > 0 && (
            <>
              <div style={{display:'flex',gap:18,marginBottom:8,fontSize:11,color:C.textMuted}}>
                <span>■ <span style={{color:C.blue}}>Venta real</span> de esas semanas</span>
                <span>— <span style={{color:C.textMuted}}>Venta habitual</span> (misma semana de otros años)</span>
                {fases.map(f => (
                  <span key={f.etiqueta} style={{color:COLOR_FASE[f.etiqueta] || C.gray}}>
                    ▧ fase {f.etiqueta}
                  </span>
                ))}
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={datosGrafico} margin={{top:4,right:16,left:0,bottom:4}}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border}/>
                  <XAxis dataKey="semana" tick={{fontSize:10,fill:C.textMuted}}
                         interval={Math.max(0, Math.floor(datosGrafico.length/10))}/>
                  <YAxis tick={{fontSize:11,fill:C.textMuted}}
                         tickFormatter={v => v >= 1000 ? `${Math.round(v/1000)}k` : v}/>
                  <Tooltip formatter={(v,n) => [fmt(v), n]}/>
                  {fases.map(f => (
                    <ReferenceArea key={f.etiqueta} x1={f.fecha_desde} x2={f.fecha_hasta}
                                   fill={COLOR_FASE[f.etiqueta] || C.gray} fillOpacity={0.10}/>
                  ))}
                  <Bar dataKey="real" fill={C.blueLt} stroke={C.blue} strokeWidth={1}
                       name="Venta real" barSize={12}/>
                  <Line dataKey="habitual" stroke={C.textMuted} strokeWidth={1.5} dot={false}
                        strokeDasharray="4 3" name="Venta habitual"/>
                </ComposedChart>
              </ResponsiveContainer>
            </>
          )}

          <div style={{marginTop:14}}>
            <table style={{width:'100%',borderCollapse:'collapse'}}>
              <thead><tr>
                {['Fase','Desde','Hasta','Semanas','Intensidad'].map(h =>
                  <th key={h} style={s.th}>{h}</th>)}
              </tr></thead>
              <tbody>
                {fases.map((f, i) => (
                  <tr key={i}>
                    <td style={s.td}>
                      <span style={s.badge(C.grayLt, COLOR_FASE[f.etiqueta] || C.gray)}>{f.etiqueta}</span>
                    </td>
                    <td style={s.td}>
                      <input type="date" style={s.input} value={f.fecha_desde}
                             onChange={e => editarFase(i, 'fecha_desde', e.target.value)}/>
                    </td>
                    <td style={s.td}>
                      <input type="date" style={s.input} value={f.fecha_hasta}
                             onChange={e => editarFase(i, 'fecha_hasta', e.target.value)}/>
                    </td>
                    <td style={s.td}>{f.n_semanas ?? '—'}</td>
                    <td style={s.td}>{f.nivel ? `${f.nivel}× lo habitual` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
              Podés mover las fechas si conocés mejor el período. Cualquier cambio
              obliga a comprobar el efecto de nuevo.
            </div>
          </div>

          <div style={{...s.row,marginTop:14,marginBottom:0}}>
            <button style={s.btnPrimary} onClick={comprobar} disabled={cargando !== '' || fases.length === 0}>
              {cargando === 'preview' ? 'Comprobando (demora unos segundos)...' : 'Comprobar el efecto'}
            </button>
          </div>
        </div>
      )}

      {analisis && analisis.ok === false && (
        <div style={s.card}>
          <div style={s.alert('warn')}>{analisis.mensaje}</div>
        </div>
      )}

      {/* ── 4. Preview ──────────────────────────────────────────────────── */}
      {preview && (
        <div style={s.card}>
          <div style={s.cardTitle}>Qué habría pasado el año pasado</div>
          {preview.ok === false ? (
            <div style={s.alert('warn')}>{preview.mensaje}</div>
          ) : (
            <>
              <div style={s.grid3}>
                <div style={s.metric}>
                  <div style={s.mLabel}>Se vendió</div>
                  <div style={s.mValue}>{fmt(preview.real)}</div>
                  <div style={s.mSub}>cajas/semana reales</div>
                </div>
                <div style={s.metric}>
                  <div style={s.mLabel}>Sin corregir</div>
                  <div style={{...s.mValue,color:C.danger}}>{fmt(preview.sin_evento)}</div>
                  <div style={s.mSub}>error {fmt(Math.abs(preview.sesgo_sin))}%</div>
                </div>
                <div style={s.metric}>
                  <div style={s.mLabel}>Con la corrección</div>
                  <div style={{...s.mValue,color:C.teal}}>{fmt(preview.con_evento)}</div>
                  <div style={s.mSub}>error {fmt(Math.abs(preview.sesgo_con))}%</div>
                </div>
              </div>
              <div style={s.alert(
                Math.abs(preview.sesgo_con) < Math.abs(preview.sesgo_sin) ? 'ok' : 'warn')}>
                {preview.mensaje}
              </div>
              {Array.isArray(preview.inertes) && preview.inertes.length > 0 && (
                <div style={s.alert('err')}>
                  Atención: {preview.inertes.length} fase(s) no coinciden con ninguna
                  semana del historial, así que no harían ningún efecto. Revisá las fechas.
                </div>
              )}
              <div style={{...s.row,marginTop:10,marginBottom:0}}>
                <button style={s.btnPrimary} onClick={guardar} disabled={!puedeGuardar}>
                  {cargando === 'guardar' ? 'Guardando...' : 'Guardar evento'}
                </button>
                <span style={{fontSize:11,color:C.textMuted}}>
                  Se aplica en la próxima corrida del plan (mañana a las 06:00).
                </span>
              </div>
            </>
          )}
          {preview.ok === false && (
            <div style={{...s.row,marginTop:10,marginBottom:0}}>
              <button style={s.btnPrimary} onClick={guardar} disabled={!puedeGuardar}>
                Guardar de todos modos
              </button>
              <span style={{fontSize:11,color:C.textMuted}}>
                No se pudo comprobar el efecto, así que se guarda sin verificar.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
