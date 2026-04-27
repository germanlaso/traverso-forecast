import { useState, useEffect, useMemo } from "react";
import axios from "axios";

const API = "";

const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56", tealDk: "#085041",
  blue: "#378ADD", blueLt: "#E6F1FB",
  purple: "#534AB7", purpleLt: "#EEEDFE",
  amber: "#EF9F27", amberLt: "#FAEEDA",
  red: "#E24B4A", redLt: "#FCEBEB",
  gray: "#5F5E5A", grayLt: "#F1EFE8", grayMid: "#D3D1C7",
  text: "#2C2C2A", textMuted: "#888780", border: "#D3D1C7",
};

// Feriados Chile 2026
const FERIADOS_CL = new Set([
  "2026-01-01","2026-03-29","2026-03-30", // Año nuevo, Viernes/Sábado Santo
  "2026-04-06",                           // Lunes Santo (si aplica)
  "2026-05-01","2026-05-21",              // Día del Trabajo, Día de las Glorias Navales
  "2026-06-29",                           // San Pedro y San Pablo
  "2026-07-16",                           // Virgen del Carmen
  "2026-08-15",                           // Asunción de la Virgen
  "2026-09-18","2026-09-19",              // Fiestas Patrias
  "2026-10-12",                           // Día de la Raza
  "2026-10-31",                           // Día de las Iglesias Evangélicas
  "2026-11-01","2026-11-02",              // Todos los Santos, Día de los Difuntos (si aplica)
  "2026-12-08","2026-12-25",              // Inmaculada Concepción, Navidad
]);

function esFeriado(fecha) { return FERIADOS_CL.has(fecha); }

// Día hábil: lun-vie que no sea feriado
function esDiaHabil(fecha) {
  const d = new Date(fecha + "T12:00:00");
  const dow = d.getDay();
  return dow !== 0 && dow !== 6 && !esFeriado(fecha);
}

// Etiqueta del día con indicador de feriado
function labelDia(dia) {
  if (esFeriado(dia.fecha)) return dia.label + " 🇨🇱";
  return dia.label;
}

function semanaDesde(fechaLunes) {
  const dias = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(fechaLunes + "T12:00:00");
    d.setDate(d.getDate() + i);
    const fecha = d.toISOString().slice(0, 10);
    const dow = d.getDay();
    const feriado = esFeriado(fecha);
    const finDeSemana = dow === 0 || dow === 6;
    dias.push({
      fecha,
      label: d.toLocaleDateString("es-CL", { weekday: "short", day: "2-digit", month: "2-digit" }),
      habil: esDiaHabil(fecha),
      feriado,
      finDeSemana,
      dow,
    });
  }
  return dias;
}

function getDomingoActual() {
  const hoy = new Date();
  const dow = hoy.getDay(); // 0=dom
  const diff = -dow; // retroceder al domingo
  const dom = new Date(hoy);
  dom.setDate(hoy.getDate() + diff);
  return dom.toISOString().slice(0, 10);
}

function addSemanas(fechaDomingo, n) {
  const d = new Date(fechaDomingo + "T12:00:00");
  d.setDate(d.getDate() + n * 7);
  return d.toISOString().slice(0, 10);
}

function fmtN(n) { return Math.round(n ?? 0).toLocaleString("es-CL"); }
function fmtPct(n) { return `${Math.round((n ?? 0) * 100)}%`; }

// ── Barra de capacidad ────────────────────────────────────────────────────────
function CapBar({ uso }) {
  const raw = uso ?? 0;
  const pct = Math.min(1, raw);
  const color = raw > 1 ? C.red : raw >= 0.8 ? C.amber : C.teal;
  return (
    <div style={{ height: 6, background: C.grayLt, borderRadius: 3, marginTop: 3 }}>
      <div style={{ height: 6, width: `${pct * 100}%`, background: color, borderRadius: 3, transition: "width .3s" }} />
    </div>
  );
}

// ── Badge de orden ────────────────────────────────────────────────────────────
function OrdenBadge({ orden, esPreferida, onClick }) {
  const aprobada = orden.aprobada;
  const tentativa = orden.numero_of?.startsWith("OFT");
  const esDesborde = orden.esDesborde;
  const bg    = esDesborde ? "#FFF0F0" : aprobada ? C.tealLt : tentativa ? C.amberLt : C.grayLt;
  const color = esDesborde ? C.red : aprobada ? C.tealMid : tentativa ? "#854F0B" : C.gray;
  const border= esDesborde ? C.red : aprobada ? C.teal : tentativa ? C.amber : C.grayMid;
  return (
    <div onClick={onClick}
      title={`${orden.numero_of} · ${orden.sku} · ${orden.descripcion?.slice(0,40)} · ${fmtN(orden.cantidad_cajas)} cj · ${esPreferida ? "Línea preferida" : "Línea alternativa"}`}
      style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
               background: bg, border: `0.5px solid ${border}`, borderRadius: 4,
               padding: "2px 5px", marginBottom: 2, cursor: onClick ? "pointer" : "default",
               fontSize: 10, color }}>
      <span style={{ fontWeight: 700 }}>{orden.numero_of}</span>
      <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
        {orden.esDesborde && <span title="Desborde del día anterior" style={{ fontSize: 9 }}>↪</span>}
        {!esPreferida && <span title="Línea alternativa" style={{ fontSize: 9, opacity: .7 }}>Alt</span>}
        {aprobada && !orden.esDesborde && <span>✓</span>}
      </span>
    </div>
  );
}

// ── Distribuir órdenes con desborde en días siguientes ───────────────────────
// Usa directamente los campos del plan (aprobada, numero_of, fecha_lanzamiento_real)
function distribuirOrdenes(ordenesLinea, dias, aprobMap, params, linea) {
  const capDia = linea.cap_u_semana / 5;
  const mapa = {};
  const capUsada = {};
  dias.forEach(d => { mapa[d.fecha] = []; capUsada[d.fecha] = 0; });

  // Solo órdenes aprobadas
  const aprobadas = ordenesLinea.filter(o => o.aprobada);

  aprobadas.forEach(o => {
    const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
    const aprobacion = aprobMap[key];

    const fechaIni = String(
      aprobacion?.fecha_lanzamiento_real || o.semana_emision
    ).slice(0, 10);

    // La orden solo pertenece a la semana que contiene su fechaIni
    // Si fechaIni está fuera del rango de días visible → ignorar
    const inicioDias = dias[0]?.fecha;
    const finDias    = dias[dias.length - 1]?.fecha;
    if (fechaIni < inicioDias || fechaIni > finDias) return;

    const upj = params[o.sku]?.upj ?? 1;
    const capReal = Number(aprobacion?.cantidad_real_cj ?? o.cantidad_cajas);
    let uRestantes = capReal * upj;

    let primerDia = true;
    for (const dia of dias) {
      if (dia.fecha < fechaIni) continue;
      if (uRestantes <= 0) break;

      const capDisponible = Math.max(0, capDia - capUsada[dia.fecha]);
      if (capDisponible <= 0 && !primerDia) continue;

      const uEnEste = primerDia
        ? Math.min(uRestantes, capDia)
        : Math.min(uRestantes, capDisponible);
      const usoPct = uEnEste / capDia;

      mapa[dia.fecha].push({
        ...o,
        usoPct: Math.round(usoPct * 100) / 100,
        esDesborde: !primerDia,
        uProduccion: Math.round(uEnEste),
      });
      capUsada[dia.fecha] += usoPct;
      uRestantes -= uEnEste;
      primerDia = false;
    }
  });

  return { mapa, capUsada };
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function DetalleProduccion({ onAprobar }) {
  const [semanaBase, setSemanaBase] = useState(getDomingoActual());
  const [lineas,     setLineas]     = useState([]);
  const [params,     setParams]     = useState({});    // {sku → {upj, linea_pref, ...}}
  const [ordenes,    setOrdenes]    = useState([]);
  const [aprobadas,  setAprobadas]  = useState([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState("");

  // Cargar parámetros y líneas al montar
  useEffect(() => {
    Promise.all([
      axios.get(`${API}/plan/params`),
      axios.get(`${API}/ordenes/aprobadas`),
    ]).then(([p, a]) => {
      setLineas(p.data.lineas ?? []);
      const map = {};
      (p.data.skus ?? []).forEach(s => {
        map[s.sku] = { upj: s.u_por_caja, linea: s.linea_preferida, ss_dias: s.ss_dias };
      });
      setParams(map);
      setAprobadas(a.data ?? []);
    }).catch(e => {
      setError('Error cargando parámetros: ' + (e.response?.data?.detail || e.message));
    });
  }, []);

  // Cargar plan cuando cambia semana (horizonte 4 semanas desde semanaBase)
  useEffect(() => {
    setLoading(true); setError("");
    axios.post(`${API}/plan`, { horizonte_semanas: 8 })
      .then(r => setOrdenes(r.data.ordenes ?? []))
      .catch(e => {
      if (e.message?.includes('timeout') || e.message?.includes('SQL') || e.message?.includes('500')) {
        setError('Sin conexión SQL Server — verifica la VPN. Mostrando datos en caché si hay.');
      } else {
        setError(e.message);
      }
    })
      .finally(() => setLoading(false));
  }, [semanaBase]);

  // Recargar aprobadas cuando el padre indica un cambio
  const recargarAprobadas = () => {
    axios.get(`${API}/ordenes/aprobadas`).then(r => setAprobadas(r.data ?? []));
  };

  const dias = useMemo(() => semanaDesde(semanaBase), [semanaBase]);
  const aprobMap = useMemo(() => {
    const m = {};
    aprobadas.forEach(a => { m[a.key] = a; });
    return m;
  }, [aprobadas]);

  const hoy = new Date().toISOString().slice(0, 10);

  // Órdenes de PRODUCCIÓN que corresponden a esta semana o anteriores sin aprobar
  const ordenesProd = useMemo(() => {
    return ordenes.filter(o => {
      if (o.tipo !== "PRODUCCION") return false;
      const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
      const aprobada = aprobMap[key];
      // Incluir si: semana_necesidad está en el horizonte visible, o si es pasada y no aprobada
      return true;
    });
  }, [ordenes, aprobMap]);

  // Para cada línea, agrupar órdenes por día de producción
  // Distribuimos la orden de forma uniforme entre los días hábiles de su semana de emisión
  function getOrdenesLinea(linea) {
    return ordenesProd.filter(o => {
      const p = params[o.sku];
      return o.linea === linea.codigo || p?.linea === linea.codigo;
    });
  }

  function getUsoDelDia(linea, fecha, ordenesLinea) {
    // Días hábiles de la semana que contiene esta fecha
    const capDia = linea.cap_u_semana / 5;
    let uso = 0, cambio = 0;
    const ordenesDelDia = [];

    // Buscar órdenes APROBADAS cuyo fecha_lanzamiento_real = este día
    // (puede ser fin de semana o feriado si se programó así)
    ordenesLinea.forEach(o => {
      const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
      const aprobacion = aprobMap[key];
      if (!aprobacion) return;

      const fechaLanz = String(
        aprobacion.fecha_lanzamiento_real || o.semana_emision
      ).slice(0, 10);

      if (fechaLanz !== fecha) return;

      const upj = params[o.sku]?.upj ?? 1;
      const capReal = Number(aprobacion.cantidad_real_cj ?? o.cantidad_cajas);
      const uTotales = capReal * upj;
      const usoPct = uTotales / capDia;

      // Si desborda el día actual, distribuir el exceso en días siguientes
      // (lo manejamos acumulando — la barra mostrará >100%)
      uso += usoPct;
      cambio += 0.2;
      ordenesDelDia.push({
        ...o,
        numero_of: aprobacion.numero_of || o.numero_of,
        aprobada: true,
        usoPct: Math.round(usoPct * 100) / 100,
        uTotales,
      });
    });

    // Capacidad disponible: puede ser negativa si hay desborde
    const capDisp = Math.max(0, 1 - uso);
    return {
      ordenes: ordenesDelDia,
      uso: Math.round(uso * 100) / 100,
      cambio: Math.round(cambio * 100) / 100,
      desborde: uso > 1,
    };
  }

  const s = {
    card:    { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: "12px 16px", marginBottom: 14 },
    linHdr:  { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
    linTit:  { fontSize: 13, fontWeight: 700, color: C.tealMid },
    linSub:  { fontSize: 11, color: C.textMuted },
    dayCol:  (habil, feriado) => ({
      flex: 1, minWidth: 90,
      background: feriado ? "#FFF8E7" : habil ? "#fff" : C.grayLt,
      border: `0.5px solid ${feriado ? C.amber : C.border}`,
      borderRadius: 6, padding: "6px 8px",
    }),
    dayLbl:  (habil, feriado) => ({
      fontSize: 10, fontWeight: 600,
      color: feriado ? "#854F0B" : habil ? C.tealMid : C.textMuted,
      marginBottom: 4, textAlign: "center", whiteSpace: "nowrap",
    }),
    capRow:  { display: "flex", justifyContent: "space-between", fontSize: 9, color: C.textMuted, marginTop: 4 },
    tblHdr:  { padding: "5px 8px", fontSize: 10, fontWeight: 600, color: C.textMuted,
               background: C.grayLt, borderBottom: `0.5px solid ${C.border}`, whiteSpace: "nowrap" },
    tblCell: { padding: "4px 8px", fontSize: 11, borderBottom: `0.5px solid ${C.border}` },
  };

  return (
    <div style={{ fontFamily: "Arial,sans-serif", color: C.text }}>
      {/* Controles de semana */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <button onClick={() => setSemanaBase(addSemanas(semanaBase, -1))}
          style={{ fontSize: 13, padding: "5px 12px", borderRadius: 6, border: `0.5px solid ${C.border}`,
                   background: "#fff", cursor: "pointer" }}>← Sem ant.</button>
        <span style={{ fontSize: 13, fontWeight: 600, color: C.tealMid }}>
          {(() => {
            const ini = new Date(semanaBase + "T12:00:00");
            const fin = new Date(semanaBase + "T12:00:00"); fin.setDate(fin.getDate() + 6);
            const fmt = d => `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}`;
            return `Semana ${fmt(ini)} al ${fmt(fin)}/${fin.getFullYear()}`;
          })()}
        </span>
        <button onClick={() => setSemanaBase(addSemanas(semanaBase, 1))}
          style={{ fontSize: 13, padding: "5px 12px", borderRadius: 6, border: `0.5px solid ${C.border}`,
                   background: "#fff", cursor: "pointer" }}>Sem sig. →</button>
        <button onClick={() => setSemanaBase(getDomingoActual())}
          style={{ fontSize: 11, padding: "5px 10px", borderRadius: 6, border: `0.5px solid ${C.teal}`,
                   background: C.tealLt, color: C.tealMid, cursor: "pointer" }}>Hoy</button>
        {loading && <span style={{ fontSize: 12, color: C.textMuted }}>Cargando...</span>}
        {error && <span style={{ fontSize: 12, color: C.red }}>{error}</span>}
      </div>

      {/* Una sección por línea de producción */}
      {lineas.map(linea => {
        const ordenesLinea = getOrdenesLinea(linea);
        const capacidadSem = linea.cap_u_semana;
        const { mapa: ordenesXDia, capUsada } = distribuirOrdenes(
          ordenesLinea, dias, aprobMap, params, linea
        );

        // Órdenes pendientes de aprobación para esta línea (para la tabla inferior)
        const pendientes = ordenesLinea.filter(o => !aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`]);
        const aprobadas_linea = ordenesLinea.filter(o => !!aprobMap[`${o.sku}__${o.semana_necesidad}__${o.semana_emision}`]);

        // Filtrar tabla: pendientes siempre + aprobadas solo hasta fin de semana visible
        const finSemanaVis = addSemanas(semanaBase, 1);
        const ordenesTabla = ordenesLinea.filter(o => {
          const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
          const aprobada = aprobMap[key];
          if (!aprobada) return true;                   // pendientes: siempre
          return o.semana_emision <= finSemanaVis;      // aprobadas: solo hasta esta semana
        });

        return (
          <div key={linea.codigo} style={s.card}>
            {/* Header de la línea */}
            <div style={s.linHdr}>
              <div>
                <span style={s.linTit}>{linea.codigo} — {linea.nombre}</span>
                <span style={{ ...s.linSub, marginLeft: 10 }}>
                  Cap. semanal: {fmtN(capacidadSem)} u. · {linea.horas_disp_sem}h/sem
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, fontSize: 11 }}>
                <span style={{ padding: "2px 8px", borderRadius: 10, background: C.tealLt, color: C.tealMid, fontWeight: 600 }}>
                  {aprobadas_linea.length} aprobadas
                </span>
                <span style={{ padding: "2px 8px", borderRadius: 10, background: C.amberLt, color: "#854F0B", fontWeight: 600 }}>
                  {pendientes.length} pendientes
                </span>
              </div>
            </div>

            {/* Grid de días */}
            <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
              {dias.map(dia => {
                const ords = ordenesXDia[dia.fecha] ?? [];
                const uso = capUsada[dia.fecha] ?? 0;
                const cambio = ords.length > 0 ? Math.min(0.2, 1 - uso) : 0;
                const desborde = uso > 1;
                const usoTotal = Math.min(1, uso + cambio);
                const capDisp = Math.max(0, 1 - uso - cambio);

                return (
                  <div key={dia.fecha} style={s.dayCol(dia.habil, dia.feriado)}>
                    <div style={s.dayLbl(dia.habil, dia.feriado)}>
                      {dia.feriado ? dia.label + ' 🇨🇱' : dia.label}
                      {!dia.habil && <div style={{ fontSize: 8, color: dia.feriado ? "#854F0B" : C.textMuted }}>{dia.feriado ? "Feriado" : "Fin de semana"}</div>}
                    </div>

                    {(
                      <>
                        {/* Órdenes del día — incluso en días no hábiles si hay producción asignada */}
                        <div style={{ minHeight: 40 }}>
                          {ords.map((o, i) => {
                            const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
                            const esPreferida = params[o.sku]?.linea === linea.codigo;
                            return (
                              <OrdenBadge key={i} orden={{...o, aprobada: !!aprobMap[key]}}
                                esPreferida={esPreferida}
                                onClick={() => onAprobar && onAprobar(o)} />
                            );
                          })}
                          {ords.length === 0 && (
                            <div style={{ fontSize: 9, color: C.textMuted, textAlign: "center", paddingTop: 4 }}>—</div>
                          )}
                        </div>

                        {/* Cambio de batch */}
                        {cambio > 0 && (
                          <div style={{ fontSize: 9, color: C.textMuted, marginTop: 3 }}>
                            Cambio: {fmtPct(cambio)}
                          </div>
                        )}

                        {/* Barra de capacidad */}
                        <CapBar uso={usoTotal} />
                        <div style={s.capRow}>
                          <span style={{ color: desborde ? C.red : C.text }}>
                            {desborde ? `⚠ ${fmtPct(uso + cambio)}` : `Usado: ${fmtPct(usoTotal)}`}
                          </span>
                          <span style={{ color: capDisp < 0.1 ? C.red : C.tealMid }}>
                            Disp: {fmtPct(capDisp)}
                          </span>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Tabla de órdenes pendientes de aprobación */}
            {ordenesTabla.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr>
                      {["N° Orden", "SKU", "Descripción", "F. Lanzamiento", "F. Entrada", "Cajas", "Stock ini.", "Cobertura", "Línea", "Estado", ""].map(h => (
                        <th key={h} style={s.tblHdr}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ordenesTabla.map((o, i) => {
                      const key = `${o.sku}__${o.semana_necesidad}__${o.semana_emision}`;
                      const aprobada = aprobMap[key];
                      const esPreferida = params[o.sku]?.linea === linea.codigo;
                      const tentativa = o.numero_of?.startsWith("OFT");
                      const pasada = o.semana_emision <= hoy;
                      const stockIni = parseFloat(o.motivo?.match(/Stock:([\d.]+)/)?.[1] ?? 0);
                      const ss = o.ss_cajas ?? 0;
                      const cobDias = o.forecast_cajas > 0
                        ? Math.round((stockIni / o.forecast_cajas) * 7) : "—";
                      const rowBg = aprobada ? "#F0FAF5" : pasada && !aprobada ? "#FFF5F5" : i % 2 === 0 ? "#fff" : C.grayLt;

                      return (
                        <tr key={i} style={{ background: rowBg }}>
                          <td style={{ ...s.tblCell, fontWeight: 700, color: tentativa ? "#854F0B" : C.tealMid, whiteSpace: "nowrap" }}>
                            {o.numero_of}
                          </td>
                          <td style={{ ...s.tblCell, fontWeight: 700, color: C.teal }}>{o.sku}</td>
                          <td style={{ ...s.tblCell, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {o.descripcion}
                          </td>
                          <td style={{ ...s.tblCell,
                            color: pasada && !aprobada ? C.red : C.text,
                            fontWeight: pasada && !aprobada ? 700 : 400,
                            whiteSpace: "nowrap" }}>
                            {pasada && !aprobada && "🔴 "}{o.semana_emision}
                          </td>
                          <td style={{ ...s.tblCell, whiteSpace: "nowrap" }}>{o.semana_necesidad}</td>
                          <td style={{ ...s.tblCell, textAlign: "right", fontWeight: 700, color: C.teal }}>
                            {fmtN(aprobada ? aprobada.cantidad_real_cj : o.cantidad_cajas)}
                          </td>
                          <td style={{ ...s.tblCell, textAlign: "right" }}>{fmtN(stockIni)}</td>
                          <td style={{ ...s.tblCell, textAlign: "right", color: cobDias < (params[o.sku]?.ss_dias ?? 10) ? C.red : C.text }}>
                            {cobDias !== "—" ? `${cobDias}d` : "—"}
                          </td>
                          <td style={{ ...s.tblCell, textAlign: "center" }}>
                            <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3,
                              background: esPreferida ? C.tealLt : C.amberLt,
                              color: esPreferida ? C.tealMid : "#854F0B" }}>
                              {esPreferida ? "Pref." : "Alt."}
                            </span>
                          </td>
                          <td style={{ ...s.tblCell, textAlign: "center" }}>
                            {aprobada
                              ? <span style={{ fontSize: 10, fontWeight: 700, color: C.tealMid }}>✓ Aprobada</span>
                              : pasada
                              ? <span style={{ fontSize: 10, fontWeight: 700, color: C.red }}>⚡ Urgente</span>
                              : <span style={{ fontSize: 10, fontWeight: 700, color: "#854F0B" }}>Pendiente</span>
                            }
                          </td>
                          <td style={{ ...s.tblCell, textAlign: "center" }}>
                            {!aprobada && (
                              <button onClick={() => onAprobar && onAprobar(o)}
                                style={{ fontSize: 10, padding: "2px 8px", borderRadius: 5,
                                         border: `0.5px solid ${C.teal}`, background: C.tealLt,
                                         color: C.tealMid, cursor: "pointer", fontWeight: 600 }}>
                                Aprobar
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {ordenesLinea.length === 0 && (
              <div style={{ fontSize: 12, color: C.textMuted, textAlign: "center", padding: "12px 0" }}>
                Sin órdenes de producción para esta línea en el horizonte visible
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
