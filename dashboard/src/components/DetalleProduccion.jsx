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

function OrdenBadge({orden,esPreferida,estaAprobada,onClick}){
  const esDesborde=orden.esDesborde;
  // estaAprobada viene del aprobMap del padre (fuente de verdad: /ordenes/aprobadas).
  // Usar esto en vez de orden.aprobada evita un parpadeo ámbar→verde mientras
  // el plan se regenera tras aprobar (el plan tarda ~60s, las aprobadas son instantáneas).
  const esOFT = estaAprobada !== undefined ? !estaAprobada : !orden.aprobada;
  const bg=esDesborde?"#FFF0F0":esOFT?C.amberLt:C.tealLt;
  const color=esDesborde?C.red:esOFT?C.amber:C.tealMid;
  const bord=esDesborde?C.red:esOFT?C.amber:C.teal;
  // Tooltip multi-línea: SKU, descripción, cantidad y (si aplica) setup
  const tooltipLines = [
    `${orden.numero_of}`,
    `${orden.sku} — ${orden.descripcion || ""}`,
    `${fmtN(orden.cantidad_cajas || 0)} cj · ${fmtN(orden.uProduccion)} u (${fmtPct(orden.usoPct)})`,
  ];
  if (orden.paga_setup) {
    tooltipLines.push(orden.setup_unidades
      ? `⚙ Setup: ${fmtN(orden.setup_unidades)} u`
      : `⚙ Paga setup`);
  }
  tooltipLines.push("", "Click para desplazar");
  return(
    <div onClick={onClick}
      title={tooltipLines.join("\n")}
      style={{background:bg,border:`0.5px solid ${bord}`,borderRadius:4,
              padding:"3px 5px",marginBottom:2,cursor:"pointer",fontSize:9.5,color}}>
      <div style={{fontWeight:700,display:"flex",justifyContent:"space-between"}}>
        <span>{orden.numero_of}</span>
        <span style={{fontSize:8.5,opacity:.8}}>
          {esDesborde?"↪":""}
          {!esPreferida?" Alt":""}
          {orden.paga_setup?" ⚙":""}
        </span>
      </div>
      <div style={{fontSize:8.5,color:esDesborde?C.red:C.tealMid,marginTop:1}}>
        {fmtN(orden.uProduccion)} u · {fmtPct(orden.usoPct)}
      </div>
    </div>
  );
}

function ModalDesplazar({orden,aprobacion,onGuardar,onCerrar}){
  // v1.2: prefill con la fecha exacta del optimizador (día), no el agrupador.
  const fechaActual=String(
    aprobacion?.fecha_lanzamiento_real
    || orden?.fecha_lanzamiento
    || orden?.semana_emision
    || ""
  ).slice(0,10);
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
        // semana_emision/semana_necesidad: claves de aprobación en BD — no tocar
        semana_emision:orden.semana_emision,semana_necesidad:orden.semana_necesidad,
        cantidad_sugerida_cj:orden.cantidad_cajas,cantidad_real_cj:aprobacion.cantidad_real_cj,
        u_por_caja:aprobacion.u_por_caja??1,responsable:aprobacion.responsable,
        comentario:aprobacion.comentario||"",linea:orden.linea||"",
        fecha_lanzamiento_real:nuevaFecha,
        // Fallback en cascada: aprobada → backend day-exact → semana
        fecha_entrada_real:aprobacion.fecha_entrada_real||orden.fecha_entrada_real||orden.semana_necesidad,
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
  // v1.2: prefill con fechas exactas del optimizador
  const [fechaLanz,setFechaLanz]=useState(String(
    aprobacion?.fecha_lanzamiento_real
    || orden?.fecha_lanzamiento
    || orden?.semana_emision
    || ""
  ).slice(0,10));
  const [fechaEnt,setFechaEnt]=useState(String(
    aprobacion?.fecha_entrada_real
    || orden?.fecha_entrada_real
    || orden?.semana_necesidad
    || ""
  ).slice(0,10));
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
  // v1.2: cada OFT representa UN día de producción. Las cajas vienen ya
  // dimensionadas por el optimizador para caber en la capacidad de ese día
  // (junto con otros SKUs si hay multi-SKU intra-día). El frontend NO
  // redistribuye: dibuja la OFT en su fecha_lanzamiento exacta.
  const capDia=linea.cap_u_semana/5;
  const mapa={};const capUsada={};
  diasExt.forEach(d=>{mapa[d.fecha]=[];capUsada[d.fecha]=0;});

  ordenesLinea.forEach(o=>{
    // v1.2: lookup por numero_of (estable). Si la orden está aprobada,
    // la sub-OFTs de la misma corrida (mismo numero_of) reciben los
    // datos de la única fila en mrp_aprobaciones.
    const aprobacion=aprobMap[o.numero_of];

    // Día de la OFT: backend (fecha_lanzamiento) > aprobación manual > fallback semanal
    const fechaIni=String(
      aprobacion?.fecha_lanzamiento_real
      || o.fecha_lanzamiento
      || o.semana_emision
    ).slice(0,10);

    // Solo dibujar si cae en la ventana visible
    if(mapa[fechaIni]===undefined) return;

    const upj=params[o.sku]?.upj??1;
    const cajasReales=Number(aprobacion?.cantidad_real_cj??o.cantidad_cajas);
    const uProd=Math.round(cajasReales*upj);
    const usoPctReal=uProd/capDia;

    mapa[fechaIni].push({
      ...o,
      usoPct:Math.round(usoPctReal*100)/100,
      esDesborde:false,        // v1.2: el backend nunca desborda — la cap es por construcción
      uProduccion:uProd,
      ultimoDiaProd:fechaIni,  // mismo día (legacy: lo consume ModalDesplazar)
      fechaEntradaCalc:o.fecha_entrada_real||o.semana_necesidad,
    });
    capUsada[fechaIni]=(capUsada[fechaIni]||0)+usoPctReal;
  });
  return{mapa,capUsada};
}

export default function DetalleProduccion({
  onAprobar,
  ordenesPlan=[],
  onPlanChanged,
  planLoading=false,
  onSolicitarPlan=null,
}){
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

  // Sincronizar órdenes con el plan que viene del padre (App.js es la única
  // fuente de verdad de /plan: garantiza correlativos OFT consistentes entre
  // pestañas). Sin fallback de fetch propio.
  useEffect(()=>{
    setOrdenes(ordenesPlan ?? []);
    setLoading(false);
  },[ordenesPlan]);

  const recargar=useCallback(()=>{
    axios.get(`${API}/ordenes/aprobadas`).then(r=>setAprobadas(r.data??[]));
    if(onPlanChanged) onPlanChanged();
  },[onPlanChanged]);

  const diasExt=useMemo(()=>diasDesde(semanaBase,2),[semanaBase]);
  const dias=useMemo(()=>diasExt.slice(0,7),[diasExt]);
  const aprobMap=useMemo(()=>{
    // v1.2: indexar por numero_of (PK estable en mrp_aprobaciones).
    // Si una corrida del optimizer dura varios días, todas sus sub-OFTs
    // comparten numero_of → todas se pintan verdes con una sola aprobación.
    const m={};aprobadas.forEach(a=>{m[a.numero_of]=a;});return m;
  },[aprobadas]);
  const hoy=new Date().toISOString().slice(0,10);
  const ordenesProd=useMemo(()=>ordenes.filter(o=>o.tipo==="PRODUCCION"),[ordenes]);
  function getOrdenesLinea(linea){
    // v1.2: el optimizer asigna línea explícitamente a toda OFT de PRODUCCION.
    // Si o.linea viene vacío (orden manual sin asignar), recién entonces
    // caemos a la línea preferida del SKU. El OR previo generaba doble dibujo:
    // una OFT con linea=L002 también aparecía en L001 si su SKU tenía L001
    // como preferida, inflando la grilla a >100% por suma duplicada.
    return ordenesProd.filter(o => {
      if (o.linea) return o.linea === linea.codigo;
      // Fallback solo cuando o.linea está vacío
      return params[o.sku]?.linea === linea.codigo;
    });
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

      {/* Banner: plan no generado — red de seguridad */}
      {(!ordenesPlan || ordenesPlan.length===0) && (
        <div style={{
          background:C.amberLt,border:`0.5px solid ${C.amber}`,color:"#854F0B",
          borderRadius:7,padding:"10px 14px",fontSize:12,marginBottom:14,
          display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,
        }}>
          <span>
            {planLoading
              ? "⏳ Generando plan de producción... el detalle por línea se actualizará al terminar."
              : "⚠ No hay plan de producción generado. Las líneas se ven sin órdenes pendientes."}
          </span>
          {!planLoading && onSolicitarPlan && (
            <button onClick={onSolicitarPlan}
              style={{fontSize:12,padding:"6px 14px",borderRadius:7,border:"none",
                      background:C.amber,color:"#fff",cursor:"pointer",fontWeight:700,
                      whiteSpace:"nowrap"}}>
              Generar plan
            </button>
          )}
        </div>
      )}

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
        const pendientes=ordenesLinea.filter(o=>!aprobMap[o.numero_of]);
        const aprobadas_lin=ordenesLinea.filter(o=>!!aprobMap[o.numero_of]);
        // Fechas de la semana visible: dom→sáb
        const iniSem = semanaBase;                    // domingo
        const finSem = addDias(semanaBase, 6);        // sábado
        const finSemSig = addDias(semanaBase, 13);    // sábado de la semana siguiente

        const ordenesTabla = ordenesLinea.filter(o => {
          const aprobada = aprobMap[o.numero_of];
          // v1.2: pivote es la fecha exacta del optimizador (día), no el agrupador semanal.
          const fechaLanz = String(
            aprobada?.fecha_lanzamiento_real
            || o.fecha_lanzamiento
            || o.semana_emision
          ).slice(0,10);
          if (aprobada) {
            // Aprobadas: solo si su fecha de lanzamiento real cae en esta semana
            return fechaLanz >= iniSem && fechaLanz <= finSem;
          } else {
            // Pendientes: si fecha de lanzamiento cae en esta semana o la siguiente
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
                {(() => {
                  // Setup total de la semana visible (suma de setup_unidades de OFTs en días visibles)
                  const setupSem = dias.reduce((s, d) => {
                    const ords = ordenesXDia[d.fecha] ?? [];
                    return s + ords.reduce((acc, o) => acc + (o.setup_unidades || 0), 0);
                  }, 0);
                  const setupPctSem = linea.cap_u_semana > 0 ? setupSem / linea.cap_u_semana : 0;
                  if (setupSem === 0) return null;
                  return (
                    <span style={{padding:"2px 8px",borderRadius:10,background:"#F4EAD5",color:"#7B5C1A",fontWeight:600}}
                      title={`Setup total esta semana: ${fmtN(setupSem)} u (${fmtPct(setupPctSem)} de cap. semanal)`}>
                      ⚙ {fmtPct(setupPctSem)} setup
                    </span>
                  );
                })()}
                <span style={{padding:"2px 8px",borderRadius:10,background:C.tealLt,color:C.tealMid,fontWeight:600}}>{aprobadas_lin.length} aprobadas</span>
                <span style={{padding:"2px 8px",borderRadius:10,background:C.amberLt,color:"#854F0B",fontWeight:600}}>{pendientes.length} pendientes</span>
              </div>
            </div>

            <div style={{display:"flex",gap:4,marginBottom:12}}>
              {dias.map(dia=>{
                const ords=ordenesXDia[dia.fecha]??[];
                const uso=capUsada[dia.fecha]??0;
                const desborde=uso>1;
                const capDia=linea.cap_u_semana/5;
                const setupUDia=ords.reduce((s,o)=>s+(o.setup_unidades||0),0);
                const setupPctDia=capDia>0?setupUDia/capDia:0;
                return(
                  <div key={dia.fecha} style={s.dayCol(dia.feriado,dia.finDeSemana)}>
                    <div style={s.dayLbl(dia.habil,dia.feriado)}>
                      {dia.feriado?dia.label+" 🇨🇱":dia.label}
                      {!dia.habil&&<div style={{fontSize:8,color:dia.feriado?"#854F0B":C.textMuted}}>{dia.feriado?"Feriado":"Fin de semana"}</div>}
                    </div>
                    <div style={{minHeight:44}}>
                      {ords.map((o,i)=>{
                        const aprobacion=aprobMap[o.numero_of];
                        const esPreferida=params[o.sku]?.linea===linea.codigo;
                        return(<OrdenBadge key={i} orden={o} esPreferida={esPreferida}
                          estaAprobada={!!aprobacion}
                          onClick={()=>setModalDesplazar({orden:o,aprobacion})}/>);
                      })}
                      {ords.length===0&&<div style={{fontSize:9,color:C.textMuted,textAlign:"center",paddingTop:8}}>—</div>}
                    </div>
                    <CapBar uso={Math.min(1,uso)}/>
                    <div style={s.capRow}>
                      <span style={{color:desborde?C.red:C.text}}>{desborde?`⚠ ${fmtPct(uso)}`:fmtPct(uso)}</span>
                      <span style={{color:uso>0.9?C.red:C.tealMid}}>{fmtPct(Math.max(0,1-uso))} libre</span>
                    </div>
                    {setupUDia>0&&(
                      <div style={{fontSize:8.5,color:"#7B5C1A",marginTop:2,textAlign:"center"}}
                        title={`Setup en este día: ${fmtN(setupUDia)} u`}>
                        ⚙ {fmtPct(setupPctDia)} setup
                      </div>
                    )}
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
                      const aprobada=aprobMap[o.numero_of];
                      const esPreferida=params[o.sku]?.linea===linea.codigo;
                      const fechaLanzReal = String(
                        aprobada?.fecha_lanzamiento_real
                        || o.fecha_lanzamiento
                        || o.semana_emision
                      ).slice(0,10);
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
                              // v1.2: el backend propone fecha_lanzamiento al día.
                              // semana_emision es solo el agrupador semanal (domingo).
                              const sugerida = String(o.fecha_lanzamiento || o.semana_emision).slice(0,10);
                              const fechaReal = String(aprobada?.fecha_lanzamiento_real || sugerida).slice(0,10);
                              const difiere   = aprobada && fechaReal !== sugerida;
                              const esPasada  = fechaReal <= hoy && !aprobada;
                              return (
                                <span style={{color: esPasada ? C.red : difiere ? C.amber : C.text,
                                              fontWeight: esPasada||difiere ? 700 : 400}}
                                  title={difiere ? `Sugerido: ${sugerida}` : ""}>
                                  {esPasada && "🔴 "}
                                  {difiere && "📅 "}
                                  {fechaReal}
                                </span>
                              );
                            })()}
                          </td>
                          <td style={{...s.tblCell,whiteSpace:"nowrap"}}>
                            {(() => {
                              // v1.2: backend entrega fecha_entrada_real al día exacto.
                              // No re-simulamos producción aquí — confiamos en el backend.
                              const sugerida = String(o.fecha_entrada_real || o.semana_necesidad).slice(0,10);
                              const fechaEnt = String(aprobada?.fecha_entrada_real || sugerida).slice(0,10);
                              const difiere = aprobada && fechaEnt !== sugerida;
                              return (
                                <span style={{color: difiere ? C.amber : C.text, fontWeight: difiere ? 700 : 400}}
                                  title={difiere ? `Sugerido: ${sugerida}` : ""}>
                                  {difiere && "📅 "}
                                  {fechaEnt}
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
