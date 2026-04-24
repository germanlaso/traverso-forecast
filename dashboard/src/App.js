import React, { useState, useEffect, useRef } from 'react';
import {
  ComposedChart, Line, Area, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import axios from 'axios';

const API = '';

const C = {
  teal:'#1D9E75',tealLt:'#E1F5EE',tealMid:'#0F6E56',
  blue:'#185FA5',blueLt:'#E6F1FB',
  purple:'#534AB7',purpleLt:'#EEEDFE',
  amber:'#EF9F27',amberLt:'#FAEEDA',
  gray:'#5F5E5A',grayLt:'#F1EFE8',
  danger:'#E24B4A',dangerLt:'#FCEBEB',
  border:'#D3D1C7',text:'#2C2C2A',textMuted:'#888780',
};

const s = {
  app:       {fontFamily:'Arial,sans-serif',background:'#F8F7F4',minHeight:'100vh',color:C.text},
  topbar:    {background:C.teal,color:'#fff',padding:'0 28px',height:52,display:'flex',alignItems:'center',justifyContent:'space-between'},
  topTitle:  {fontWeight:700,fontSize:15,letterSpacing:.3},
  topSub:    {fontSize:12,opacity:.8},
  main:      {maxWidth:1100,margin:'0 auto',padding:'24px 20px'},
  card:      {background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:10,padding:'16px 20px',marginBottom:16},
  cardTitle: {fontSize:13,fontWeight:700,color:C.text,marginBottom:12},
  metric:    {background:C.grayLt,borderRadius:8,padding:'10px 14px',textAlign:'center'},
  mLabel:    {fontSize:10,color:C.textMuted,textTransform:'uppercase',letterSpacing:'0.05em'},
  mValue:    {fontSize:22,fontWeight:700,color:C.text,marginTop:2},
  mSub:      {fontSize:11,color:C.textMuted,marginTop:2},
  grid4:     {display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:10,marginBottom:16},
  grid2:     {display:'grid',gridTemplateColumns:'1fr 1fr',gap:16,marginBottom:16},
  btn:       {fontSize:12,padding:'7px 14px',borderRadius:7,border:`0.5px solid ${C.border}`,background:'#fff',color:C.text,cursor:'pointer',fontWeight:600},
  btnPrimary:{fontSize:12,padding:'7px 14px',borderRadius:7,border:'none',background:C.teal,color:'#fff',cursor:'pointer',fontWeight:600},
  badge:     (bg,color)=>({display:'inline-block',background:bg,color,fontSize:10,fontWeight:700,padding:'2px 8px',borderRadius:10}),
  row:       {display:'flex',alignItems:'center',gap:10,flexWrap:'wrap',marginBottom:14},
  pill:      (color)=>({width:10,height:10,borderRadius:2,background:color,display:'inline-block',marginRight:4}),
  eventRow:  {display:'flex',gap:8,alignItems:'center',padding:'6px 0',borderBottom:`0.5px solid ${C.border}`},
  input:     {fontSize:12,padding:'5px 8px',borderRadius:6,border:`0.5px solid ${C.border}`,background:'#fff',color:C.text},
  alert:     (type)=>({
    background:type==='ok'?C.tealLt:type==='warn'?C.amberLt:C.dangerLt,
    border:`0.5px solid ${type==='ok'?C.teal:type==='warn'?C.amber:C.danger}`,
    color:type==='ok'?'#085041':type==='warn'?'#633806':'#A32D2D',
    borderRadius:7,padding:'8px 12px',fontSize:12,marginBottom:10,
  }),
};

const CustomTooltip = ({active,payload,label})=>{
  if(!active||!payload?.length) return null;
  return(
    <div style={{background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:8,padding:'10px 14px',fontSize:12}}>
      <div style={{fontWeight:700,marginBottom:6,color:C.text}}>{label}</div>
      {payload.map((p,i)=>(
        <div key={i} style={{color:p.color||C.text,marginBottom:2}}>
          <span style={s.pill(p.color||C.teal)}/>{p.name}: <strong>{Math.round(p.value).toLocaleString('es-CL')}</strong>
        </div>
      ))}
    </div>
  );
};

function SkuSearch({skus,value,onChange}){
  const [query,setQuery]=useState('');
  const [open,setOpen]=useState(false);
  const [focused,setFocused]=useState(false);
  const ref=useRef(null);
  const selected=skus.find(s=>s.sku===value);
  const filtered=query.trim()===''?skus.slice(0,100):skus.filter(s=>
    s.sku.toLowerCase().includes(query.toLowerCase())||(s.descripcion||'').toLowerCase().includes(query.toLowerCase())
  );
  useEffect(()=>{
    const h=(e)=>{if(ref.current&&!ref.current.contains(e.target)){setOpen(false);setQuery('');}};
    document.addEventListener('mousedown',h);
    return()=>document.removeEventListener('mousedown',h);
  },[]);
  const select=(sku)=>{onChange(sku.sku);setQuery('');setOpen(false);};
  return(
    <div ref={ref} style={{position:'relative',flex:1,maxWidth:480}}>
      <input style={{...s.input,width:'100%',fontSize:13,padding:'7px 10px',borderColor:focused?C.teal:C.border,outline:'none',boxSizing:'border-box'}}
        placeholder="Buscar por código o nombre de SKU..."
        value={open?query:(selected?`${selected.sku} — ${selected.descripcion}`:'')}
        onChange={e=>{setQuery(e.target.value);setOpen(true);}}
        onFocus={()=>{setFocused(true);setOpen(true);setQuery('');}}
        onBlur={()=>setFocused(false)}/>
      {open&&filtered.length>0&&(
        <div style={{position:'absolute',top:'100%',left:0,right:0,zIndex:200,background:'#fff',border:`0.5px solid ${C.border}`,borderRadius:8,boxShadow:'0 4px 16px rgba(0,0,0,.10)',maxHeight:320,overflowY:'auto',marginTop:2}}>
          {query.trim()===''&&<div style={{fontSize:10,color:C.textMuted,padding:'6px 12px',borderBottom:`0.5px solid ${C.border}`}}>Top 100 por volumen · escribe para buscar todos</div>}
          {filtered.map((sk,i)=>(
            <div key={sk.sku} onMouseDown={()=>select(sk)}
              style={{padding:'8px 12px',cursor:'pointer',fontSize:12,background:sk.sku===value?C.tealLt:i%2===0?'#fff':C.grayLt,borderBottom:`0.5px solid ${C.border}`,display:'flex',gap:8,alignItems:'baseline'}}>
              <span style={{fontWeight:700,color:C.teal,minWidth:90,flexShrink:0}}>{sk.sku}</span>
              <span style={{color:C.text}}>{sk.descripcion}</span>
              <span style={{color:C.textMuted,marginLeft:'auto',fontSize:11,flexShrink:0}}>{Math.round(sk.volumen_total||0).toLocaleString('es-CL')} u.</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function App(){
  const [skus,setSkus]=useState([]);
  const [selSku,setSelSku]=useState('');
  const [result,setResult]=useState(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [dbStatus,setDbStatus]=useState(null);
  const [csvMode,setCsvMode]=useState(false);
  const [csvPath,setCsvPath]=useState('/app/data/ventas.csv');
  const [periods,setPeriods]=useState(26);
  const [canal,setCanal]=useState('');
  const [canales,setCanales]=useState([]);
  const [activeTab,setActiveTab]=useState('forecast');
  const [plan,setPlan]=useState(null);
  const [planLoading,setPlanLoading]=useState(false);
  const [planHorizonte,setPlanHorizonte]=useState(13);
  const [events,setEvents]=useState([
    {name:'promo_verano',label:'Promo verano',dates:'',value:1.25,active:false},
    {name:'nuevo_competidor',label:'Nuevo competidor',dates:'',value:0.88,active:false},
  ]);
  const canalRef=useRef('');

  useEffect(()=>{
    axios.get(`${API}/health`).then(r=>setDbStatus(r.data)).catch(()=>setDbStatus({status:'error'}));
  },[]);

  useEffect(()=>{
    axios.get(`${API}/dimensions`).then(r=>{setCanales(r.data.canales||[]);}).catch(()=>{});
  },[]);

  useEffect(()=>{
    const params=csvMode?{use_csv:csvPath}:{};
    axios.get(`${API}/skus`,{params}).then(r=>{setSkus(r.data);if(r.data.length>0&&!selSku)setSelSku(r.data[0].sku);}).catch(e=>setError(`Error cargando SKUs: ${e.message}`));
  },[csvMode,csvPath]);

  const runForecast=async(forceRetrain=false)=>{
    if(!selSku) return;
    setLoading(true);setError('');setResult(null);
    const canalVal=canalRef.current||null;
    const activeEvents=events.filter(e=>e.active&&e.dates.trim()).map(e=>({name:e.name,dates:e.dates.split(',').map(d=>d.trim()).filter(Boolean),value:parseFloat(e.value),label:e.label}));
    try{
      const{data}=await axios.post(`${API}/forecast`,{sku:selSku,canal:canalVal,zona:null,periods:Number(periods),freq:'W',events:activeEvents,force_retrain:forceRetrain,use_csv:csvMode?csvPath:null});
      setResult(data);
    }catch(e){setError(`Error: ${e.response?.data?.detail||e.message}`);}
    finally{setLoading(false);}
  };

  const runPlan=async()=>{
    setPlanLoading(true);setPlan(null);setError('');
    try{
      const{data}=await axios.post(`${API}/plan`,{horizonte_semanas:Number(planHorizonte),canal:canalRef.current||null});
      setPlan(data);
    }catch(e){setError(`Error plan: ${e.response?.data?.detail||e.message}`);}
    finally{setPlanLoading(false);}
  };

  const chartData=React.useMemo(()=>{
    if(!result) return [];
    const hist=(result.history||[]).map(h=>({fecha:h.fecha?.slice(0,10),real:Math.round(h.real)}));
    const lastHistDate=hist[hist.length-1]?.fecha;
    const fore=(result.forecast||[]).filter(f=>f.ds>=(lastHistDate||'')).map(f=>({fecha:f.ds?.slice(0,10),forecast:Math.round(f.yhat),lowerBound:Math.round(f.yhat_lower),upperBound:Math.round(f.yhat_upper),trend:Math.round(f.trend)}));
    const merged={};
    hist.forEach(h=>{merged[h.fecha]={...merged[h.fecha],...h};});
    fore.forEach(f=>{merged[f.fecha]={...merged[f.fecha],...f};});
    return Object.values(merged).sort((a,b)=>a.fecha.localeCompare(b.fecha));
  },[result]);

  const metrics=result?.metrics||{};
  const mapeOk=metrics.mape!==null&&metrics.mape!==undefined;
  const mapeType=!mapeOk?'warn':metrics.mape<10?'ok':metrics.mape<20?'warn':'error';
  const todayStr=new Date().toISOString().slice(0,10);
  const selectedSku=skus.find(s=>s.sku===selSku);

  const tipoColor=(tipo)=>tipo==='PRODUCCION'?{bg:C.tealLt,color:C.teal}:tipo==='IMPORTACION'?{bg:C.purpleLt,color:C.purple}:{bg:C.amberLt,color:C.amber};

  return(
    <div style={s.app}>
      {/* Topbar */}
      <div style={s.topbar}>
        <div>
          <div style={s.topTitle}>Traverso S.A. — Sistema de Planificación de Producción</div>
          <div style={s.topSub}>Motor Prophet · Segmento Comercial · Piloto v1.0</div>
        </div>
        <div style={{display:'flex',gap:10,alignItems:'center'}}>
          {dbStatus&&<span style={s.badge(dbStatus.db?.ok?C.tealLt:C.dangerLt,dbStatus.db?.ok?'#085041':'#A32D2D')}>{dbStatus.db?.ok?'● SQL conectado':'● Sin conexión SQL'}</span>}
        </div>
      </div>

      {/* Tabs */}
      <div style={{background:'#fff',borderBottom:`1px solid ${C.border}`,padding:'0 24px',display:'flex',gap:4}}>
        {[['forecast','📈 Forecast de Demanda'],['plan','🏭 Plan de Producción']].map(([tab,label])=>(
          <button key={tab} onClick={()=>setActiveTab(tab)} style={{padding:'12px 20px',border:'none',cursor:'pointer',fontSize:13,fontWeight:500,background:'transparent',color:activeTab===tab?C.teal:C.textMuted,borderBottom:activeTab===tab?`2px solid ${C.teal}`:'2px solid transparent',transition:'all .15s'}}>
            {label}
          </button>
        ))}
      </div>

      <div style={s.main}>
        {error&&<div style={s.alert('error')}>{error}</div>}

        {/* ══ FORECAST TAB ══ */}
        {activeTab==='forecast'&&(
          <div>
            <div style={{...s.card,marginBottom:12}}>
              <div style={s.row}>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Fuente:</span>
                <label style={{fontSize:12,cursor:'pointer',display:'flex',alignItems:'center',gap:5}}><input type="radio" checked={!csvMode} onChange={()=>setCsvMode(false)}/>SQL Server</label>
                <label style={{fontSize:12,cursor:'pointer',display:'flex',alignItems:'center',gap:5}}><input type="radio" checked={csvMode} onChange={()=>setCsvMode(true)}/>CSV offline</label>
                {csvMode&&<input style={{...s.input,flex:1,minWidth:280}} value={csvPath} onChange={e=>setCsvPath(e.target.value)} placeholder="/app/data/ventas.csv"/>}
              </div>
            </div>

            <div style={s.card}>
              <div style={s.row}>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>SKU:</span>
                <SkuSearch skus={skus} value={selSku} onChange={(v)=>{setSelSku(v);setResult(null);setError('');}}/>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Semanas:</span>
                <select style={{...s.input,fontSize:13,padding:'6px 10px',cursor:'pointer'}} value={periods} onChange={e=>setPeriods(e.target.value)}>
                  {[4,8,12,16,26,39,52].map(p=><option key={p} value={p}>{p} sem. (~{Math.round(p/4.3)} meses)</option>)}
                </select>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Canal:</span>
                <select style={{...s.input,fontSize:13,padding:'6px 10px',cursor:'pointer',minWidth:180}} value={canal} onChange={e=>{canalRef.current=e.target.value;setCanal(e.target.value);setResult(null);setError('');}}>
                  <option value="">Todos los canales</option>
                  {canales.filter(c=>c!=='OFICINA').map(c=><option key={c} value={c}>{c}</option>)}
                </select>
                <button style={s.btnPrimary} onClick={()=>runForecast(false)} disabled={loading||!selSku}>{loading?'Calculando...':'▶ Generar forecast'}</button>
                <button style={s.btn} onClick={()=>runForecast(true)} disabled={loading||!selSku}>↺ Reentrenar</button>
              </div>
              {selectedSku&&<div style={{fontSize:11,color:C.textMuted,marginTop:-6}}>
                <span style={{marginRight:16}}>Marca: <strong>{selectedSku.marca||'—'}</strong></span>
                <span style={{marginRight:16}}>Categoría: <strong>{selectedSku.categoria||'—'}</strong></span>
                <span style={{marginRight:16}}>Semanas con venta: <strong>{selectedSku.semanas_con_venta}</strong></span>
                <span style={{marginRight:16}}>Canales: <strong>{selectedSku.n_canales}</strong></span>
                <span>Zonas: <strong>{selectedSku.n_zonas}</strong></span>
              </div>}
            </div>

            {result&&(
              <div style={s.grid4}>
                <div style={s.metric}><div style={s.mLabel}>MAPE</div><div style={{...s.mValue,color:mapeType==='ok'?C.teal:mapeType==='warn'?C.amber:C.danger}}>{mapeOk?`${metrics.mape}%`:'N/D'}</div><div style={s.mSub}>Error promedio</div></div>
                <div style={s.metric}><div style={s.mLabel}>MAE (unidades)</div><div style={s.mValue}>{mapeOk?Math.round(metrics.mae).toLocaleString('es-CL'):'N/D'}</div><div style={s.mSub}>Error absoluto medio</div></div>
                <div style={s.metric}><div style={s.mLabel}>Semanas entrenamiento</div><div style={s.mValue}>{metrics.n_train??'—'}</div><div style={s.mSub}>Historial usado</div></div>
                <div style={s.metric}><div style={s.mLabel}>Próxima semana</div><div style={s.mValue}>{Math.round(result.forecast?.find(f=>f.ds>=todayStr)?.yhat||0).toLocaleString('es-CL')}</div><div style={s.mSub}>unidades forecast</div></div>
              </div>
            )}

            {result&&chartData.length>0&&(
              <div style={s.card}>
                <div style={s.cardTitle}>Demanda histórica y forecast semanal — {selSku} · {selectedSku?.descripcion}{canal?` · ${canal}`:' · Todos los canales'}{result.from_cache&&<span style={{...s.badge(C.grayLt,C.textMuted),marginLeft:8}}>desde caché</span>}</div>
                {mapeOk&&<div style={s.alert(mapeType)}>{mapeType==='ok'?`Precisión: MAPE ${metrics.mape}% — Excelente`:mapeType==='warn'?`Precisión: MAPE ${metrics.mape}% — Aceptable. Mejorará con más historial.`:`Precisión: MAPE ${metrics.mape}% — Revisar parámetros.`}</div>}
                <div style={{display:'flex',gap:18,marginBottom:10,fontSize:12,color:C.textMuted}}>
                  {[['Venta real (sem.)',C.blue],['Forecast',C.teal],['Intervalo 90%',C.teal],['Tendencia',C.purple]].map(([label,color])=>(
                    <span key={label} style={{display:'flex',alignItems:'center',gap:5}}><span style={{...s.pill(color),opacity:label.includes('Intervalo')?.3:1}}/>{label}</span>
                  ))}
                </div>
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={chartData} margin={{top:4,right:16,left:0,bottom:4}}>
                    <CartesianGrid strokeDasharray="3 3" stroke={C.border}/>
                    <XAxis dataKey="fecha" tick={{fontSize:10,fill:C.textMuted}} tickFormatter={v=>v?.slice(0,10)} interval={Math.floor(chartData.length/12)}/>
                    <YAxis tick={{fontSize:11,fill:C.textMuted}} tickFormatter={v=>v>=1000?`${Math.round(v/1000)}k`:v}/>
                    <Tooltip content={<CustomTooltip/>}/>
                    <ReferenceLine x={todayStr} stroke={C.amber} strokeDasharray="4 4" label={{value:'Hoy',fill:C.amber,fontSize:10}}/>
                    <Area dataKey="upperBound" fill={C.teal} stroke="none" fillOpacity={.12} name="Límite superior"/>
                    <Area dataKey="lowerBound" fill="#fff" stroke="none" fillOpacity={1} name="Límite inferior"/>
                    <Bar dataKey="real" fill={C.blueLt} stroke={C.blue} strokeWidth={1} name="Venta real (sem.)" barSize={10}/>
                    <Line dataKey="forecast" stroke={C.teal} strokeWidth={2.5} dot={false} name="Forecast"/>
                    <Line dataKey="trend" stroke={C.purple} strokeWidth={1} dot={false} strokeDasharray="4 3" name="Tendencia"/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}

            <div style={s.grid2}>
              <div style={s.card}>
                <div style={s.cardTitle}>Ajustes comerciales (regressores)</div>
                <div style={{fontSize:11,color:C.textMuted,marginBottom:10}}>Activa eventos para ver su impacto. Fechas separadas por coma (AAAA-MM-DD).</div>
                {events.map((ev,i)=>(
                  <div key={i} style={s.eventRow}>
                    <input type="checkbox" checked={ev.active} onChange={e=>setEvents(events.map((x,j)=>j===i?{...x,active:e.target.checked}:x))}/>
                    <input style={{...s.input,width:130}} value={ev.label} onChange={e=>setEvents(events.map((x,j)=>j===i?{...x,label:e.target.value}:x))}/>
                    <input style={{...s.input,flex:1}} placeholder="2025-02-03, 2025-02-10" value={ev.dates} onChange={e=>setEvents(events.map((x,j)=>j===i?{...x,dates:e.target.value}:x))}/>
                    <input type="number" style={{...s.input,width:64}} step="0.01" min="0" value={ev.value} onChange={e=>setEvents(events.map((x,j)=>j===i?{...x,value:e.target.value}:x))}/>
                    <span style={{fontSize:10,color:C.textMuted,width:50}}>{ev.value>=1?`+${Math.round((ev.value-1)*100)}%`:`-${Math.round((1-ev.value)*100)}%`}</span>
                  </div>
                ))}
                <button style={{...s.btn,marginTop:10,fontSize:11,width:'100%'}} onClick={()=>setEvents([...events,{name:`evento_${events.length+1}`,label:'Nuevo evento',dates:'',value:1.0,active:true}])}>+ Agregar evento</button>
              </div>
              <div style={s.card}>
                <div style={s.cardTitle}>Forecast semanal detallado</div>
                <div style={{overflowY:'auto',maxHeight:280}}>
                  <table style={{width:'100%',borderCollapse:'collapse',fontSize:12}}>
                    <thead><tr style={{background:C.grayLt}}>{['Semana','Forecast','Mín (90%)','Máx (90%)'].map(h=><th key={h} style={{padding:'6px 10px',textAlign:'left',color:C.textMuted,borderBottom:`0.5px solid ${C.border}`,fontWeight:600,fontSize:11}}>{h}</th>)}</tr></thead>
                    <tbody>
                      {(result?.forecast||[]).filter(f=>f.ds>=todayStr).map((f,i)=>(
                        <tr key={i} style={{background:i%2===0?'#fff':C.grayLt}}>
                          <td style={{padding:'5px 10px',color:C.textMuted}}>{f.ds?.slice(0,10)}</td>
                          <td style={{padding:'5px 10px',fontWeight:700,color:C.teal}}>{Math.round(f.yhat).toLocaleString('es-CL')}</td>
                          <td style={{padding:'5px 10px',color:C.textMuted}}>{Math.round(f.yhat_lower).toLocaleString('es-CL')}</td>
                          <td style={{padding:'5px 10px',color:C.textMuted}}>{Math.round(f.yhat_upper).toLocaleString('es-CL')}</td>
                        </tr>
                      ))}
                      {!result&&<tr><td colSpan={4} style={{padding:'20px 10px',color:C.textMuted,textAlign:'center'}}>Selecciona un SKU y genera el forecast</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {skus.length>0&&(
              <div style={s.card}>
                <div style={s.cardTitle}>SKUs disponibles — Segmento Comercial ({skus.length.toLocaleString('es-CL')} productos)</div>
                <div style={{overflowX:'auto'}}>
                  <table style={{width:'100%',borderCollapse:'collapse',fontSize:12}}>
                    <thead><tr style={{background:C.grayLt}}>{['Código','Descripción','Marca','Categoría','Vol. total','Semanas','Canales','Zonas'].map(h=><th key={h} style={{padding:'6px 10px',textAlign:'left',color:C.textMuted,borderBottom:`0.5px solid ${C.border}`,fontWeight:600,fontSize:11}}>{h}</th>)}</tr></thead>
                    <tbody>
                      {skus.slice(0,30).map((sk,i)=>(
                        <tr key={i} style={{background:sk.sku===selSku?C.tealLt:i%2===0?'#fff':C.grayLt,cursor:'pointer'}} onClick={()=>setSelSku(sk.sku)}>
                          <td style={{padding:'5px 10px',fontWeight:700,color:C.teal}}>{sk.sku}</td>
                          <td style={{padding:'5px 10px'}}>{sk.descripcion}</td>
                          <td style={{padding:'5px 10px',color:C.textMuted}}>{sk.marca}</td>
                          <td style={{padding:'5px 10px',color:C.textMuted}}>{sk.categoria}</td>
                          <td style={{padding:'5px 10px'}}>{Math.round(sk.volumen_total||0).toLocaleString('es-CL')}</td>
                          <td style={{padding:'5px 10px'}}>{sk.semanas_con_venta}</td>
                          <td style={{padding:'5px 10px'}}>{sk.n_canales}</td>
                          <td style={{padding:'5px 10px'}}>{sk.n_zonas}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {skus.length>30&&<div style={{fontSize:11,color:C.textMuted,padding:'8px 10px'}}>Mostrando 30 de {skus.length.toLocaleString('es-CL')} SKUs.</div>}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══ PLAN DE PRODUCCIÓN TAB ══ */}
        {activeTab==='plan'&&(
          <div>
            <div style={s.card}>
              <div style={s.row}>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Horizonte:</span>
                <select style={{...s.input,fontSize:13,padding:'6px 10px',cursor:'pointer'}} value={planHorizonte} onChange={e=>setPlanHorizonte(e.target.value)}>
                  {[4,8,13,17,26].map(p=><option key={p} value={p}>{p} sem. (~{Math.round(p/4.3)} meses)</option>)}
                </select>
                <span style={{fontSize:12,fontWeight:600,color:C.textMuted}}>Canal:</span>
                <select style={{...s.input,fontSize:13,padding:'6px 10px',cursor:'pointer',minWidth:180}} value={canal} onChange={e=>{canalRef.current=e.target.value;setCanal(e.target.value);}}>
                  <option value="">Todos los canales</option>
                  {canales.filter(c=>c!=='OFICINA').map(c=><option key={c} value={c}>{c}</option>)}
                </select>
                <button style={s.btnPrimary} onClick={runPlan} disabled={planLoading}>{planLoading?'Calculando...':'▶ Generar plan'}</button>
              </div>
            </div>

            {plan&&(
              <div style={s.grid4}>
                <div style={s.metric}><div style={s.mLabel}>SKUs planificados</div><div style={s.mValue}>{plan.n_skus}</div></div>
                <div style={s.metric}><div style={s.mLabel}>Órdenes sugeridas</div><div style={s.mValue}>{plan.n_ordenes}</div></div>
                <div style={s.metric}><div style={s.mLabel}>Con alertas</div><div style={{...s.mValue,color:plan.n_alertas>0?C.danger:C.teal}}>{plan.n_alertas}</div></div>
                <div style={s.metric}><div style={s.mLabel}>Horizonte</div><div style={s.mValue}>{planHorizonte} sem.</div></div>
              </div>
            )}

            {plan&&(
              <div style={s.card}>
                <div style={s.cardTitle}>Órdenes de producción / abastecimiento sugeridas</div>
                <div style={{overflowX:'auto'}}>
                  <table style={{width:'100%',borderCollapse:'collapse',fontSize:12}}>
                    <thead>
                      <tr style={{background:C.grayLt}}>
                        {['SKU','Descripción','Tipo','Sem. Necesidad','Fecha Emisión','Cajas','Unidades','Línea','Alerta'].map(h=>(
                          <th key={h} style={{padding:'6px 10px',textAlign:'left',color:C.textMuted,borderBottom:`0.5px solid ${C.border}`,fontWeight:600,fontSize:11}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(plan.ordenes||[]).map((o,i)=>{
                        const tc=tipoColor(o.tipo);
                        return(
                          <tr key={i} style={{background:o.tiene_alerta?'#FFF5F5':i%2===0?'#fff':C.grayLt}}>
                            <td style={{padding:'5px 10px',fontWeight:700,color:C.teal}}>{o.sku}</td>
                            <td style={{padding:'5px 10px',maxWidth:180,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{o.descripcion}</td>
                            <td style={{padding:'5px 10px'}}><span style={{fontSize:10,fontWeight:700,padding:'2px 6px',borderRadius:4,background:tc.bg,color:tc.color}}>{o.tipo}</span></td>
                            <td style={{padding:'5px 10px',color:C.textMuted}}>{o.semana_necesidad}</td>
                            <td style={{padding:'5px 10px',fontWeight:o.tiene_alerta?700:400,color:o.tiene_alerta?C.danger:C.text}}>{o.tiene_alerta?'🔴 ':''}{o.semana_emision}</td>
                            <td style={{padding:'5px 10px',fontWeight:700,color:C.teal}}>{o.cantidad_cajas.toLocaleString('es-CL')}</td>
                            <td style={{padding:'5px 10px',color:C.textMuted}}>{o.cantidad_unidades.toLocaleString('es-CL')}</td>
                            <td style={{padding:'5px 10px',color:C.textMuted}}>{o.linea||'—'}</td>
                            <td style={{padding:'5px 10px',fontSize:11,color:C.danger,maxWidth:160,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{o.alerta||''}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {plan&&plan.resumen_semanal&&plan.resumen_semanal.length>0&&(
              <div style={s.card}>
                <div style={s.cardTitle}>Resumen semanal de emisión</div>
                <table style={{width:'100%',borderCollapse:'collapse',fontSize:12}}>
                  <thead><tr style={{background:C.grayLt}}>{['Semana emisión','N° órdenes','Con alertas'].map(h=><th key={h} style={{padding:'6px 10px',textAlign:'left',color:C.textMuted,borderBottom:`0.5px solid ${C.border}`,fontWeight:600,fontSize:11}}>{h}</th>)}</tr></thead>
                  <tbody>
                    {plan.resumen_semanal.map((r,i)=>(
                      <tr key={i} style={{background:r.n_alertas>0?'#FFF5F5':i%2===0?'#fff':C.grayLt}}>
                        <td style={{padding:'5px 10px',fontWeight:700}}>{r.semana_emision}</td>
                        <td style={{padding:'5px 10px'}}>{r.n_ordenes}</td>
                        <td style={{padding:'5px 10px',color:r.n_alertas>0?C.danger:C.teal,fontWeight:r.n_alertas>0?700:400}}>{r.n_alertas>0?`🔴 ${r.n_alertas}`:'✓ 0'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {!plan&&!planLoading&&(
              <div style={{...s.card,textAlign:'center',color:C.textMuted,padding:40}}>
                Selecciona el horizonte y haz clic en "Generar plan" para ver las órdenes sugeridas
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
