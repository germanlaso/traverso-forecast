import { useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";

const API = "";
const C = {
  teal:"#1D9E75",tealLt:"#E1F5EE",tealMid:"#0F6E56",tealDk:"#085041",
  amber:"#EF9F27",amberLt:"#FAEEDA",red:"#E24B4A",redLt:"#FCEBEB",
  gray:"#5F5E5A",grayLt:"#F1EFE8",grayMid:"#D3D1C7",
  text:"#2C2C2A",textMuted:"#888780",border:"#D3D1C7",
};

const FERIADOS_CL = new Set([
  "2026-01-01","2026-03-29","2026-03-30","2026-04-06",
  "2026-05-01","2026-05-21","2026-06-29","2026-07-16",
  "2026-08-15","2026-09-18","2026-09-19","2026-10-12",
  "2026-10-31","2026-11-01","2026-11-02","2026-12-08","2026-12-25",
]);

function esFeriado(f){return FERIADOS_CL.has(f);}
function esDiaHabil(f){const d=new Date(f+"T12:00:00");const dow=d.getDay();return dow!==0&&dow!==6&&!esFeriado(f);}
function addDias(f,n){const d=new Date(f+"T12:00:00");d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function getDomingoActual(){const h=new Date();const d=new Date(h);d.setDate(h.getDate()-h.getDay());return d.toISOString().slice(0,10);}
function addSemanas(f,n){const d=new Date(f+"T12:00:00");d.setDate(d.getDate()+n*7);return d.toISOString().slice(0,10);}
function diasDesde(fechaDom,nSem){
  const dias=[];
  for(let i=0;i<nSem*7;i++){
    const d=new Date(fechaDom+"T12:00:00");d.setDate(d.getDate()+i);
    const fecha=d.toISOString().slice(0,10);const dow=d.getDay();
    dias.push({fecha,dow,habil:esDiaHabil(fecha),feriado:esFeriado(fecha),
      finDeSemana:dow===0||dow===6,
      label:d.toLocaleDateString("es-CL",{weekday:"short",day:"2-digit",month:"2-digit"})});
  }
  return dias;
}
function fmtN(n){return Math.round(n??0).toLocaleString("es-CL");}
function fmtPct(n){return `${Math.round((n??0)*100)}%`;}

function CapBar({uso}){
  const pct=Math.min(1,uso??0);
  const color=uso>1?C.red:uso>=0.8?C.amber:C.teal;
  return(<div style={{height:6,background:C.grayLt,borderRadius:3,marginTop:3}}>
    <div style={{height:6,width:`${pct*100}%`,background:color,borderRadius:3}}/></div>);
}

function OrdenBadge({orden,esPreferida,onClick}){
  const esDesborde=orden.esDesborde;
  const esOFT=orden.esOFT;
  const bg=esDesborde?"#FFF0F0":esOFT?C.amberLt:C.tealLt;
  const color=esDesborde?C.red:esOFT?C.amber:C.tealMid;
  const bord=esDesborde?C.red:esOFT?C.amber:C.teal;
  return(
    <div onClick={onClick}
      title={`Click para desplazar · ${orden.numero_of} · ${fmtN(orden.uProduccion)} u.`}
      style={{background:bg,border:`0.5px solid ${bord}`,borderRadius:4,
              padding:"3px 5px",marginBottom:2,cursor:"pointer",fontSize:9.5,color}}>
      <div style={{fontWeight:700,display:"flex",justifyContent:"space-between"}}>
        <span>{orden.numero_of}</span>
        <span style={{fontSize:8.5,opacity:.8}}>{esDesborde?"↪":""}{!esPreferida?" Alt":""}</span>
      </div>
      <div style={{fontSize:8.5,color:esDesborde?C.red:C.tealMid,marginTop:1}}>
        {fmtN(orden.uProduccion)} u · {fmtPct(orden.usoPct)}
      </div>
    </div>
  );
}

function ModalDesplazar({orden,aprobacion,onGuardar,onCerrar}){
  const fechaActual=String(aprobacion?.fecha_lanzamiento_real||orden?.semana_emision||"").slice(0,10);
  const [nuevaFecha,setNuevaFecha]=useState(fechaActual);
  const [guardando,setGuardando]=useState(false);
  if(!orden) return null;
  const diasDiff=Math.round((new Date(nuevaFecha)-new Date(fechaActual))/86400000);
  const esHabil=esDiaHabil(nuevaFecha);
  const handleGuardar=async()=>{
    setGuardando(true);
    try{
      await axios.post(`${API}/ordenes/aprobar`,{
        sku:orden.sku,descripcion:orden.descripcion,tipo:orden.tipo,
        semana_emision:orden.semana_emision,semana_necesidad:orden.semana_necesidad,
        cantidad_sugerida_cj:orden.cantidad_cajas,cantidad_real_cj:aprobacion.cantidad_real_cj,
        u_por_caja:aprobacion.u_por_caja??1,responsable:aprobacion.responsable,
        comentario:aprobacion.comentario||"",linea:orden.linea||"",
        fecha_lanzamiento_real:nuevaFecha,
        fecha_entrada_real:aprobacion.fecha_entrada_real||orden.semana_necesidad,
      });
      onGuardar();
    }catch(e){alert("Error: "+(e.response?.data?.detail||e.message));}
    finally{setGuardando(false);}
  };
  return(
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.45)",zIndex:1000,
                 display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{background:"#fff",borderRadius:12,padding:24,width:380,
                   boxShadow:"0 8px 32px rgba(0,0,0,.18)"}}>
        <div style={{fontSize:14,fontWeight:700,color:C.tealMid,marginBottom:4}}>Desplazar orden</div>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:16}}>
          {orden.numero_of} · {orden.sku} · {orden.descripcion?.slice(0,40)}
        </div>
        <div style={{marginBottom:10}}>
          <label style={{fontSize:11,fontWeight:600,display:"block",marginBottom:4}}>Fecha actual</label>
          <div style={{fontSize:13,fontWeight:700}}>{fechaActual}</div>
        </div>
        <div style={{marginBottom:12}}>
          <label style={{fontSize:11,fontWeight:600,display:"block",marginBottom:4}}>Nueva fecha de lanzamiento</label>
          <input type="date" value={nuevaFecha} onChange={e=>setNuevaFecha(e.target.value)}
            style={{width:"100%",fontSize:13,padding:"6px 10px",borderRadius:7,
                    border:`1.5px solid ${C.teal}`,outline:"none"}}/>
          {nuevaFecha!==fechaActual&&(
            <div style={{fontSize:11,marginTop:4,color:diasDiff>0?C.amber:C.red}}>
              {diasDiff>0?`▶ Avanza ${diasDiff} día(s)`:`◀ Retrocede ${Math.abs(diasDiff)} día(s)`}
              {!esHabil&&<span style={{color:C.amber,marginLeft:8}}>
                ⚠ {esFeriado(nuevaFecha)?"Feriado":"Fin de semana"}
              </span>}
            </div>
          )}
        </div>
        <div style={{display:"flex",gap:6,marginBottom:16,flexWrap:"wrap"}}>
          {[-2,-1,1,2,7].map(d=>(
            <button key={d} onClick={()=>setNuevaFecha(addDias(fechaActual,d))}
              style={{fontSize:10,padding:"3px 8px",borderRadius:5,border:`0.5px solid ${C.border}`,
                      background:C.grayLt,cursor:"pointer",color:d<0?C.red:C.tealMid}}>
              {d>0?`+${d}d`:`${d}d`}
            </button>
          ))}
        </div>
        <div style={{display:"flex",gap:8,justifyContent:"flex-end"}}>
          <button onClick={onCerrar}
            style={{padding:"7px 16px",borderRadius:7,border:`0.5px solid ${C.border}`,
                    background:"#fff",cursor:"pointer",fontSize:12}}>Cancelar</button>
          <button onClick={handleGuardar} disabled={guardando||nuevaFecha===fechaActual}
            style={{padding:"7px 16px",borderRadius:7,border:"none",
                    background:nuevaFecha===fechaActual?C.grayMid:C.teal,
                    color:"#fff",cursor:"pointer",fontSize:12,fontWeight:700}}>
            {guardando?"Guardando...":"Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModalEditar({orden,aprobacion,onGuardar,onCancelarAprobacion,onCerrar}){
  const [cantReal,setCantReal]=useState(aprobacion?.cantidad_real_cj??orden?.cantidad_cajas??0);
  const [fechaLanz,setFechaLanz]=useState(String(aprobacion?.fecha_lanzamiento_real||orden?.semana_emision||"").slice(0,10));
  const [fechaEnt,setFechaEnt]=useState(String(aprobacion?.fecha_entrada_real||orden?.semana_necesidad||"").slice(0,10));
  const [comentario,setComentario]=useState(aprobacion?.comentario||"");
  const [guardando,setGuardando]=useState(false);
  const [cancelando,setCancelando]=useState(false);
  if(!orden) return null;
  const handleGuardar=async()=>{
    setGuardando(true);
    try{
      await axios.post(`${API}/ordenes/aprobar`,{
        sku:orden.sku,descripcion:orden.descripcion,tipo:orden.tipo,
        semana_emision:orden.semana_emision,semana_necesidad:orden.semana_necesidad,
        cantidad_sugerida_cj:orden.cantidad_cajas,cantidad_real_cj:Number(cantReal),
        u_por_caja:aprobacion?.u_por_caja??1,responsable:aprobacion?.responsable||"—",
        comentario,linea:orden.linea||"",
        fecha_lanzamiento_real:fechaLanz,fecha_entrada_real:fechaEnt,
      });
      onGuardar();
    }catch(e){alert("Error: "+(e.response?.data?.detail||e.message));}
    finally{setGuardando(false);}
  };
  const handleCancelar=async()=>{
    if(!window.confirm(`¿Retirar aprobación de ${orden.numero_of}?`)) return;
    setCancelando(true);
    try{
      const key=`${orden.sku}__${orden.semana_necesidad}__${orden.semana_emision}`;
      await axios.delete(`${API}/ordenes/cancelar/${key}`);
      onCancelarAprobacion();
    }catch(e){alert("Error: "+(e.response?.data?.detail||e.message));}
    finally{setCancelando(false);}
  };
  return(
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.45)",zIndex:1000,
                 display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{background:"#fff",borderRadius:12,padding:24,width:420,
                   boxShadow:"0 8px 32px rgba(0,0,0,.18)"}}>
        <div style={{fontSize:14,fontWeight:700,color:C.tealMid,marginBottom:4}}>Editar orden aprobada</div>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:16}}>
          {orden.numero_of} · {orden.sku} · {orden.descripcion?.slice(0,45)}
        </div>
        {[
          ["Cantidad real (cj)",<input type="number" value={cantReal} onChange={e=>setCantReal(e.target.value)}
            style={{width:"100%",fontSize:13,padding:"6px 10px",borderRadius:7,border:`1.5px solid ${C.teal}`,outline:"none"}}/>],
          ["Fecha lanzamiento real",<input type="date" value={fechaLanz} onChange={e=>setFechaLanz(e.target.value)}
            style={{width:"100%",fontSize:13,padding:"6px 10px",borderRadius:7,border:`0.5px solid ${C.border}`,outline:"none"}}/>],
          ["Fecha entrada stock real",<input type="date" value={fechaEnt} onChange={e=>setFechaEnt(e.target.value)}
            style={{width:"100%",fontSize:13,padding:"6px 10px",borderRadius:7,border:`0.5px solid ${C.border}`,outline:"none"}}/>],
          ["Comentario",<input type="text" value={comentario} onChange={e=>setComentario(e.target.value)}
            style={{width:"100%",fontSize:13,padding:"6px 10px",borderRadius:7,border:`0.5px solid ${C.border}`,outline:"none"}}/>],
        ].map(([lbl,inp])=>(
          <div key={lbl} style={{marginBottom:10}}>
            <label style={{fontSize:11,fontWeight:600,display:"block",marginBottom:3}}>{lbl}</label>
            {inp}
          </div>
        ))}
        <div style={{display:"flex",gap:8,justifyContent:"space-between",marginTop:18}}>
          <button onClick={handleCancelar} disabled={cancelando}
            style={{padding:"7px 12px",borderRadius:7,border:`0.5px solid ${C.red}`,
                    background:C.redLt,color:C.red,cursor:"pointer",fontSize:11}}>
            {cancelando?"...":"↩ Retirar aprobación"}
          </button>
          <div style={{display:"flex",gap:8}}>
            <button onClick={onCerrar}
              style={{padding:"7px 14px",borderRadius:7,border:`0.5px solid ${C.border}`,
                      background:"#fff",cursor:"pointer",fontSize:12}}>Cancelar</button>
            <button onClick={handleGuardar} disabled={guardando}
              style={{padding:"7px 14px",borderRadius:7,border:"none",
                      background:C.teal,color:"#fff",cursor:"pointer",fontSize:12,fontWeight:700}}>
              {guardando?"Guardando...":"Guardar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Genera días globales desde una fecha de inicio para N semanas hacia atrás y adelante
function diasGlobalesDesde(fechaIni,nSemanas){
  const dias=[];
  const d=new Date(fechaIni+"T12:00:00");
  let i=0; let habiles=0; const maxHabiles=nSemanas*5;
  while(habiles<maxHabiles && i<nSemanas*14){
    const dd=new Date(d);dd.setDate(d.getDate()+i);
    const fecha=dd.toISOString().slice(0,10);
    if(esDiaHabil(fecha)){dias.push({fecha,habil:true});habiles++;}
    i++;
  }
  return dias;
}

function distribuirOrdenes(ordenesLinea,diasExt,aprobMap,params,linea){
  const capDia=linea.cap_u_semana/5;
  const mapa={};const capUsada={};
  diasExt.forEach(d=>{mapa[d.fecha]=[];capUsada[d.fecha]=0;});
  // Incluir aprobadas Y OFTs (pendientes) en el grid
  const todasOrdenes=ordenesLinea;

  todasOrdenes.forEach(o=>{
    const key=`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
    const aprobacion=aprobMap[key];
    // Ajustar fechaIni al primer día hábil si cae en fin de semana o feriado
    let _fechaIniRaw=String(aprobacion?.fecha_lanzamiento_real||o.semana_emision).slice(0,10);
    let _dIni=new Date(_fechaIniRaw+"T12:00:00");
    while(!esDiaHabil(_dIni.toISOString().slice(0,10))){_dIni.setDate(_dIni.getDate()+1);}
    const fechaIni=_dIni.toISOString().slice(0,10);

    const upj=params[o.sku]?.upj??1;
    const capReal=Number(aprobacion?.cantidad_real_cj??o.cantidad_cajas);
    let uRestantes=capReal*upj;

    // Calcular los días exactos que ocupa esta orden desde su fechaIni
    // Usar hasta 4 semanas desde fechaIni para encontrar todos los días necesarios
    const diasOrden=diasGlobalesDesde(fechaIni,4);
    const diasOcupados={}; // fecha → uProduccion

    let cap_usada_local={};
    let primerDia=true;
    for(const dia of diasOrden){
      if(uRestantes<=0) break;
      // Usar capacidad de 1 día (sin compartir con otras órdenes para este pre-cálculo)
      const uEnEste=Math.min(uRestantes,capDia);
      diasOcupados[dia.fecha]=Math.round(uEnEste);
      uRestantes-=uEnEste;
      primerDia=false;
    }

    // Calcular último día de producción (para fecha de entrada ajustada)
    const fechasOcupadas = Object.keys(diasOcupados).sort();
    const ultimoDiaProd  = fechasOcupadas[fechasOcupadas.length - 1] || fechaIni;

    // Fecha entrada = último día de producción + lead_time_sem semanas
    const ltSem  = params[o.sku]?.lead_time_sem ?? 1;
    const ltDias = ltSem * 7;
    const dUltimo = new Date(ultimoDiaProd + "T12:00:00");
    dUltimo.setDate(dUltimo.getDate() + ltDias);
    const fechaEntradaCalc = dUltimo.toISOString().slice(0,10);

    // Agregar solo los días visibles (en diasExt)
    for(const [fecha,uProd] of Object.entries(diasOcupados)){
      if(mapa[fecha]===undefined) continue;
      const usoPctReal=uProd/capDia;
      mapa[fecha].push({
        ...o,
        usoPct:Math.round(usoPctReal*100)/100,
        esDesborde: fecha!==fechaIni,
        uProduccion:uProd,
        ultimoDiaProd,
        fechaEntradaCalc,
        esOFT: !o.aprobada,
      });
      capUsada[fecha]=(capUsada[fecha]||0)+usoPctReal;
    }
  });
  return{mapa,capUsada};
}

export default function DetalleProduccion({onAprobar, ordenesPlan=[], onPlanChanged}){
  const [semanaBase,setSemanaBase]=useState(getDomingoActual());
  const [lineas,setLineas]=useState([]);
  const [params,setParams]=useState({});
  const [ordenes,setOrdenes]=useState([]);
  const [aprobadas,setAprobadas]=useState([]);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [modalDesplazar,setModalDesplazar]=useState(null);
  const [modalEditar,setModalEditar]=useState(null);

  useEffect(()=>{
    Promise.all([axios.get(`${API}/plan/params`),axios.get(`${API}/ordenes/aprobadas`)])
      .then(([p,a])=>{
        setLineas(p.data.lineas??[]);
        const map={};(p.data.skus??[]).forEach(s=>{map[s.sku]={upj:s.u_por_caja,linea:s.linea_preferida,ss_dias:s.ss_dias,lead_time_sem:s.lead_time_sem??1};});
        setParams(map);setAprobadas(a.data??[]);
      }).catch(e=>setError("Error cargando parámetros: "+(e.response?.data?.detail||e.message)));
  },[]);

  // Usar plan externo si viene, sino fetch propio
  useEffect(()=>{
    if(ordenesPlan && ordenesPlan.length > 0){
      setOrdenes(ordenesPlan);
      setLoading(false);
    } else {
      setLoading(true);setError("");
      axios.post(`${API}/plan`,{horizonte_semanas:8})
        .then(r=>setOrdenes(r.data.ordenes??[]))
        .catch(e=>setError("Error plan: "+e.message))
        .finally(()=>setLoading(false));
    }
  },[ordenesPlan]);

  const recargar=useCallback(()=>{
    axios.get(`${API}/ordenes/aprobadas`).then(r=>setAprobadas(r.data??[]));
    if(onPlanChanged) onPlanChanged();
    else axios.post(`${API}/plan`,{horizonte_semanas:8}).then(r=>setOrdenes(r.data.ordenes??[]));
  },[onPlanChanged]);

  const diasExt=useMemo(()=>diasDesde(semanaBase,2),[semanaBase]);
  const dias=useMemo(()=>diasExt.slice(0,7),[diasExt]);
  const aprobMap=useMemo(()=>{const m={};aprobadas.forEach(a=>{m[a.key]=a;});return m;},[aprobadas]);
  const hoy=new Date().toISOString().slice(0,10);
  const ordenesProd=useMemo(()=>ordenes.filter(o=>o.tipo==="PRODUCCION"),[ordenes]);
  function getOrdenesLinea(linea){
    return ordenesProd.filter(o=>o.linea===linea.codigo||params[o.sku]?.linea===linea.codigo);
  }

  const s={
    card:{background:"#fff",border:`0.5px solid ${C.border}`,borderRadius:10,padding:"12px 16px",marginBottom:14},
    linHdr:{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:8},
    linTit:{fontSize:13,fontWeight:700,color:C.tealMid},
    linSub:{fontSize:11,color:C.textMuted},
    dayCol:(feriado,finDeSemana)=>({flex:1,minWidth:100,
      background:feriado?"#FFF8E7":finDeSemana?C.grayLt:"#fff",
      border:`0.5px solid ${feriado?C.amber:C.border}`,borderRadius:6,padding:"6px 8px"}),
    dayLbl:(habil,feriado)=>({fontSize:10,fontWeight:600,
      color:feriado?"#854F0B":habil?C.tealMid:C.textMuted,marginBottom:4,textAlign:"center",whiteSpace:"nowrap"}),
    capRow:{display:"flex",justifyContent:"space-between",fontSize:9,color:C.textMuted,marginTop:4},
    tblHdr:{padding:"5px 8px",fontSize:10,fontWeight:600,color:C.textMuted,
            background:C.grayLt,borderBottom:`0.5px solid ${C.border}`,whiteSpace:"nowrap"},
    tblCell:{padding:"4px 8px",fontSize:11,borderBottom:`0.5px solid ${C.border}`},
  };

  return(
    <div style={{fontFamily:"Arial,sans-serif",color:C.text}}>
      {modalDesplazar&&<ModalDesplazar orden={modalDesplazar.orden} aprobacion={modalDesplazar.aprobacion}
        onGuardar={()=>{setModalDesplazar(null);recargar();}} onCerrar={()=>setModalDesplazar(null)}/>}
      {modalEditar&&<ModalEditar orden={modalEditar.orden} aprobacion={modalEditar.aprobacion}
        onGuardar={()=>{setModalEditar(null);recargar();}}
        onCancelarAprobacion={()=>{setModalEditar(null);recargar();}}
        onCerrar={()=>setModalEditar(null)}/>}

      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:14,flexWrap:"wrap"}}>
        <button onClick={()=>setSemanaBase(addSemanas(semanaBase,-1))}
          style={{fontSize:13,padding:"5px 12px",borderRadius:6,border:`0.5px solid ${C.border}`,background:"#fff",cursor:"pointer"}}>← Sem ant.</button>
        <span style={{fontSize:13,fontWeight:600,color:C.tealMid}}>
          {(()=>{const ini=new Date(semanaBase+"T12:00:00");const fin=new Date(semanaBase+"T12:00:00");fin.setDate(fin.getDate()+6);
            const fmt=d=>`${String(d.getDate()).padStart(2,"0")}/${String(d.getMonth()+1).padStart(2,"0")}`;
            return `Semana ${fmt(ini)} al ${fmt(fin)}/${fin.getFullYear()}`;})()}
        </span>
        <button onClick={()=>setSemanaBase(addSemanas(semanaBase,1))}
          style={{fontSize:13,padding:"5px 12px",borderRadius:6,border:`0.5px solid ${C.border}`,background:"#fff",cursor:"pointer"}}>Sem sig. →</button>
        <button onClick={()=>setSemanaBase(getDomingoActual())}
          style={{fontSize:11,padding:"5px 10px",borderRadius:6,border:`0.5px solid ${C.teal}`,
                  background:C.tealLt,color:C.tealMid,cursor:"pointer"}}>Hoy</button>
        {loading&&<span style={{fontSize:12,color:C.textMuted}}>⏳ Cargando...</span>}
        {error&&<span style={{fontSize:12,color:C.red,maxWidth:300}}>{error}</span>}
      </div>

      {lineas.map(linea=>{
        const ordenesLinea=getOrdenesLinea(linea);
        const{mapa:ordenesXDia,capUsada}=distribuirOrdenes(ordenesLinea,diasExt,aprobMap,params,linea);
        const pendientes=ordenesLinea.filter(o=>!aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`]);
        const aprobadas_lin=ordenesLinea.filter(o=>!!aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`]);
        // Fechas de la semana visible: dom→sáb
        const iniSem = semanaBase;                    // domingo
        const finSem = addDias(semanaBase, 6);        // sábado
        const finSemSig = addDias(semanaBase, 13);    // sábado de la semana siguiente

        const ordenesTabla = ordenesLinea.filter(o => {
          const aprobada = aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`];
          const fechaLanz = String(aprobada?.fecha_lanzamiento_real || o.semana_emision).slice(0,10);
          if (aprobada) {
            // Aprobadas: solo si su fecha de lanzamiento real cae en esta semana
            return fechaLanz >= iniSem && fechaLanz <= finSem;
          } else {
            // Pendientes: si fecha de lanzamiento MRP cae en esta semana o la siguiente
            return fechaLanz >= iniSem && fechaLanz <= finSemSig;
          }
        });

        return(
          <div key={linea.codigo} style={s.card}>
            <div style={s.linHdr}>
              <div>
                <span style={s.linTit}>{linea.codigo} — {linea.nombre}</span>
                <span style={{...s.linSub,marginLeft:10}}>Cap. semanal: {fmtN(linea.cap_u_semana)} u. · {linea.horas_disp_sem}h/sem</span>
              </div>
              <div style={{display:"flex",gap:8,fontSize:11}}>
                <span style={{padding:"2px 8px",borderRadius:10,background:C.tealLt,color:C.tealMid,fontWeight:600}}>{aprobadas_lin.length} aprobadas</span>
                <span style={{padding:"2px 8px",borderRadius:10,background:C.amberLt,color:"#854F0B",fontWeight:600}}>{pendientes.length} pendientes</span>
              </div>
            </div>

            <div style={{display:"flex",gap:4,marginBottom:12}}>
              {dias.map(dia=>{
                const ords=ordenesXDia[dia.fecha]??[];
                const uso=capUsada[dia.fecha]??0;
                const desborde=uso>1;
                return(
                  <div key={dia.fecha} style={s.dayCol(dia.feriado,dia.finDeSemana)}>
                    <div style={s.dayLbl(dia.habil,dia.feriado)}>
                      {dia.feriado?dia.label+" 🇨🇱":dia.label}
                      {!dia.habil&&<div style={{fontSize:8,color:dia.feriado?"#854F0B":C.textMuted}}>{dia.feriado?"Feriado":"Fin de semana"}</div>}
                    </div>
                    <div style={{minHeight:44}}>
                      {ords.map((o,i)=>{
                        const aprobacion=aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`];
                        const esPreferida=params[o.sku]?.linea===linea.codigo;
                        return(<OrdenBadge key={i} orden={o} esPreferida={esPreferida}
                          onClick={()=>setModalDesplazar({orden:o,aprobacion})}/>);
                      })}
                      {ords.length===0&&<div style={{fontSize:9,color:C.textMuted,textAlign:"center",paddingTop:8}}>—</div>}
                    </div>
                    <CapBar uso={Math.min(1,uso)}/>
                    <div style={s.capRow}>
                      <span style={{color:desborde?C.red:C.text}}>{desborde?`⚠ ${fmtPct(uso)}`:fmtPct(uso)}</span>
                      <span style={{color:uso>0.9?C.red:C.tealMid}}>{fmtPct(Math.max(0,1-uso))} libre</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {ordenesTabla.length>0&&(
              <div style={{overflowX:"auto"}}>
                <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
                  <thead><tr>
                    {["N° Orden","SKU","Descripción","F. Lanzamiento","F. Entrada","Cajas","Stock ini.","Cobertura","Línea","Estado",""].map(h=>(
                      <th key={h} style={s.tblHdr}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {ordenesTabla.map((o,i)=>{
                      const key=`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
                      const aprobada=aprobMap[key];
                      const esPreferida=params[o.sku]?.linea===linea.codigo;
                      const fechaLanzReal = String(aprobada?.fecha_lanzamiento_real || o.semana_emision).slice(0,10);
                      const pasada = fechaLanzReal <= hoy && !aprobada;
                      const stockIni=parseFloat(o.motivo?.match(/Stock:([\d.]+)/)?.[1]??0);
                      const cobDias=o.forecast_cajas>0?Math.round((stockIni/o.forecast_cajas)*7):"—";
                      const rowBg=aprobada?"#F0FAF5":pasada?"#FFF5F5":i%2===0?"#fff":C.grayLt;
                      return(
                        <tr key={i} style={{background:rowBg}}>
                          <td style={{...s.tblCell,fontWeight:700,color:o.numero_of?.startsWith("OFT")?"#854F0B":C.tealMid,whiteSpace:"nowrap"}}>{o.numero_of}</td>
                          <td style={{...s.tblCell,fontWeight:700,color:C.teal}}>{o.sku}</td>
                          <td style={{...s.tblCell,maxWidth:160,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{o.descripcion}</td>
                          <td style={{...s.tblCell,whiteSpace:"nowrap"}}>
                            {(() => {
                              const fechaReal = String(aprobada?.fecha_lanzamiento_real || o.semana_emision).slice(0,10);
                              const fechaMRP  = String(o.semana_emision).slice(0,10);
                              const difiere   = aprobada && fechaReal !== fechaMRP;
                              const esPasada  = fechaReal <= hoy && !aprobada;
                              return (
                                <span style={{color: esPasada ? C.red : difiere ? C.amber : C.text,
                                              fontWeight: esPasada||difiere ? 700 : 400}}
                                  title={difiere ? `MRP sugería: ${fechaMRP}` : ""}>
                                  {esPasada && "🔴 "}
                                  {difiere && "📅 "}
                                  {fechaReal}
                                </span>
                              );
                            })()}
                          </td>
                          <td style={{...s.tblCell,whiteSpace:"nowrap"}}>
                            {(() => {
                              const fechaEntMRP = String(o.semana_necesidad).slice(0,10);
                              const ltSem = params[o.sku]?.lead_time_sem ?? 1;
                              const ltDias = ltSem * 7;

                              // Calcular fecha entrada con nueva definición:
                              // último día de producción + lead_time_sem semanas
                              const fechaLanz = String(aprobada?.fecha_lanzamiento_real || o.semana_emision).slice(0,10);
                              const upj = params[o.sku]?.upj ?? 1;
                              const capReal = Number(aprobada?.cantidad_real_cj ?? o.cantidad_cajas);
                              const uTotales = capReal * upj;
                              const capDia = linea.cap_u_semana / 5;

                              // Simular días de producción desde fechaLanz
                              let uRest = uTotales;
                              let ultimoDia = fechaLanz;
                              const diasSim = diasGlobalesDesde(fechaLanz, 4);
                              for (const d of diasSim) {
                                if (uRest <= 0) break;
                                const uHoy = Math.min(uRest, capDia);
                                ultimoDia = d.fecha;
                                uRest -= uHoy;
                              }

                              const dUlt = new Date(ultimoDia + "T12:00:00");
                              dUlt.setDate(dUlt.getDate() + ltDias);
                              const fechaEntCalc = dUlt.toISOString().slice(0,10);
                              const difiere = fechaEntCalc !== fechaEntMRP;
                              const tooltip = `Lead time: ${ltSem} sem desde fin producción (${ultimoDia})${difiere ? ` · MRP sugería: ${fechaEntMRP}` : ""}`;
                              return (
                                <span style={{color: difiere ? C.amber : C.text, fontWeight: difiere ? 700 : 400}}
                                  title={tooltip}>
                                  {difiere && "📅 "}
                                  {fechaEntCalc}
                                </span>
                              );
                            })()}
                          </td>
                          <td style={{...s.tblCell,textAlign:"right",fontWeight:700,color:C.teal}}>
                            {fmtN(aprobada?aprobada.cantidad_real_cj:o.cantidad_cajas)}</td>
                          <td style={{...s.tblCell,textAlign:"right"}}>{fmtN(stockIni)}</td>
                          <td style={{...s.tblCell,textAlign:"right",color:cobDias!=="—"&&cobDias<(params[o.sku]?.ss_dias??10)?C.red:C.text}}>
                            {cobDias!=="—"?`${cobDias}d`:"—"}</td>
                          <td style={{...s.tblCell,textAlign:"center"}}>
                            <span style={{fontSize:9,padding:"1px 5px",borderRadius:3,
                              background:esPreferida?C.tealLt:C.amberLt,color:esPreferida?C.tealMid:"#854F0B"}}>
                              {esPreferida?"Pref.":"Alt."}
                            </span>
                          </td>
                          <td style={{...s.tblCell,textAlign:"center"}}>
                            {aprobada
                              ?<span style={{fontSize:10,fontWeight:700,color:C.tealMid}}>✓ Aprobada</span>
                              :pasada
                              ?<span style={{fontSize:10,fontWeight:700,color:C.red}}>⚡ Urgente</span>
                              :<span style={{fontSize:10,fontWeight:700,color:"#854F0B"}}>Pendiente</span>}
                          </td>
                          <td style={{...s.tblCell,textAlign:"center"}}>
                            {aprobada?(
                              <button onClick={()=>setModalEditar({orden:o,aprobacion:aprobada})}
                                style={{fontSize:10,padding:"2px 8px",borderRadius:5,
                                        border:`0.5px solid ${C.border}`,background:C.grayLt,cursor:"pointer"}}>✏️ Editar</button>
                            ):(
                              <button onClick={()=>onAprobar&&onAprobar(o)}
                                style={{fontSize:10,padding:"2px 8px",borderRadius:5,
                                        border:`0.5px solid ${C.teal}`,background:C.tealLt,
                                        color:C.tealMid,cursor:"pointer",fontWeight:600}}>Aprobar</button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {ordenesLinea.length===0&&(
              <div style={{fontSize:12,color:C.textMuted,textAlign:"center",padding:"12px 0"}}>
                Sin órdenes de producción para esta línea en el horizonte visible
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
