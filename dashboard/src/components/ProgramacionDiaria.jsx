import { useState, useMemo, useEffect } from "react";
const API = process.env.REACT_APP_API_BASE || "";

// Paleta minima (importar la global hubiera requerido cambios estructurales)
const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  text: "#1A1A1A", textMuted: "#6B6A66",
  border: "#D3D1C7", grayLt: "#F1EFE8",
  amber: "#EF9F27", amberLt: "#FAEEDA",
  white: "#FFFFFF",
};

// Formateo de fecha ISO YYYY-MM-DD → "Lunes 12 de mayo de 2026"
const MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
const DIAS = ["domingo","lunes","martes","miercoles","jueves","viernes","sabado"];
function formatearFechaLarga(iso) {
  if (!iso) return "";
  // Parseo manual para evitar problemas de timezone
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const diaSem = DIAS[dt.getDay()];
  return `${diaSem.charAt(0).toUpperCase() + diaSem.slice(1)} ${d} de ${MESES[m-1]} de ${y}`;
}
// Version corta para encabezado de dia dentro de un rango: "Lun 12 may"
const DIAS_CORTO = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];
const MESES_CORTO = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
function formatearFechaCorta(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return `${DIAS_CORTO[dt.getDay()]} ${d} ${MESES_CORTO[m-1]}`;
}

const fmtN = (v) => Number(v ?? 0).toLocaleString("es-CL");

// Lista de fechas ISO entre desde y hasta (inclusive). Vacia si el rango es invalido.
function rangoFechas(desde, hasta) {
  if (!desde || !hasta || hasta < desde) return [];
  const out = [];
  const [y, m, d] = desde.split("-").map(Number);
  let cur = new Date(y, m - 1, d);
  const [hy, hm, hd] = hasta.split("-").map(Number);
  const fin = new Date(hy, hm - 1, hd);
  // tope defensivo: 62 dias (2 meses) para no colgar el navegador si el rango es absurdo
  let guard = 0;
  while (cur <= fin && guard < 62) {
    const iso = `${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, "0")}-${String(cur.getDate()).padStart(2, "0")}`;
    out.push(iso);
    cur.setDate(cur.getDate() + 1);
    guard++;
  }
  return out;
}

export default function ProgramacionDiaria({ ordenesAprobadas = [] }) {
  // Rango de fechas. Default: hoy → hoy (equivale al comportamiento de un solo dia).
  const hoyIso = () => {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, "0")}-${String(h.getDate()).padStart(2, "0")}`;
  };
  const [fechaDesde, setFechaDesde] = useState(hoyIso);
  const [fechaHasta, setFechaHasta] = useState(hoyIso);

  // Si el usuario pone "hasta" antes que "desde", corregir para no romper el rango.
  const desde = fechaDesde;
  const hasta = fechaHasta < fechaDesde ? fechaDesde : fechaHasta;
  const esRango = hasta > desde;

  // Lineas del maestro (todas las lineas activas), no solo las que tienen OF
  // aprobadas. Fetch a /plan/params (misma fuente que StockDiario/Detalle).
  const [lineasMaestro, setLineasMaestro] = useState([]);
  useEffect(() => {
    fetch(`${API}/plan/params`).then(r => r.json()).then(p => {
      if (p.lineas) setLineasMaestro(p.lineas.map(l => l.codigo));
    }).catch(() => {});
  }, []);
  // Fallback: si el maestro aun no cargo, derivar de las OF aprobadas.
  const lineasDisponibles = useMemo(() => {
    if (lineasMaestro.length > 0) return [...lineasMaestro].sort();
    const set = new Set();
    ordenesAprobadas.forEach(o => o.linea && set.add(o.linea));
    return Array.from(set).sort();
  }, [lineasMaestro, ordenesAprobadas]);

  // Filtro de lineas (multi-select). Default: todas seleccionadas
  const [lineasFiltro, setLineasFiltro] = useState(null);
  // Sincronizar al cargar (primera vez que ordenesAprobadas tiene datos)
  if (lineasFiltro === null && lineasDisponibles.length > 0) {
    setLineasFiltro(new Set(lineasDisponibles));
  }

  // Toggle de una linea en el filtro
  const toggleLinea = (linea) => {
    setLineasFiltro(prev => {
      const next = new Set(prev || []);
      if (next.has(linea)) next.delete(linea);
      else next.add(linea);
      return next;
    });
  };
  const seleccionarTodas = () => setLineasFiltro(new Set(lineasDisponibles));
  const limpiarTodas = () => setLineasFiltro(new Set());

  // OFs aprobadas del rango, filtradas por lineas, agrupadas fecha -> linea.
  // Solo ordenes APROBADAS (cantidad_real_*), igual que antes.
  const fechas = useMemo(() => rangoFechas(desde, hasta), [desde, hasta]);

  const porFecha = useMemo(() => {
    if (!lineasFiltro) return {};
    const setFechas = new Set(fechas);
    const acc = {};  // { iso: { linea: [ofs] } }
    ordenesAprobadas.forEach(o => {
      const fl = String(o.fecha_lanzamiento_real || "").slice(0, 10);
      if (!setFechas.has(fl)) return;
      if (!lineasFiltro.has(o.linea)) return;
      const lin = o.linea || "Sin linea";
      if (!acc[fl]) acc[fl] = {};
      if (!acc[fl][lin]) acc[fl][lin] = [];
      acc[fl][lin].push(o);
    });
    // ordenar las OFs dentro de cada linea por SKU
    Object.values(acc).forEach(lineas => {
      Object.values(lineas).forEach(ofs =>
        ofs.sort((a, b) => (a.sku || "").localeCompare(b.sku || "")));
    });
    return acc;
  }, [ordenesAprobadas, fechas, lineasFiltro]);

  // Totales globales del rango
  const totalesRango = useMemo(() => {
    let ofs = 0, cajas = 0, unidades = 0;
    Object.values(porFecha).forEach(lineas =>
      Object.values(lineas).forEach(arr => arr.forEach(o => {
        ofs += 1;
        cajas += Number(o.cantidad_real_cj || 0);
        unidades += Number(o.cantidad_real_u || 0);
      })));
    return { ofs, cajas, unidades };
  }, [porFecha]);

  // Fechas del rango que efectivamente tienen OFs (para no imprimir dias vacios)
  const fechasConOFs = fechas.filter(f => porFecha[f] && Object.keys(porFecha[f]).length > 0);

  // Estilos
  const s = {
    container: { padding: "0 4px" },
    card: { background: C.white, border: `0.5px solid ${C.border}`, borderRadius: 10, padding: "16px 20px", marginBottom: 14 },
    controlsRow: { display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" },
    label: { fontSize: 12, fontWeight: 600, color: C.textMuted },
    dateInput: { fontSize: 13, padding: "6px 10px", border: `1px solid ${C.border}`, borderRadius: 6, cursor: "pointer" },
    btnPrint: { fontSize: 13, fontWeight: 600, padding: "6px 14px", border: `1px solid ${C.teal}`, background: C.tealLt, color: C.tealMid, borderRadius: 6, cursor: "pointer", marginLeft: "auto" },
    chip: (activa) => ({
      fontSize: 11, padding: "4px 10px", borderRadius: 14, cursor: "pointer", userSelect: "none",
      border: `1px solid ${activa ? C.teal : C.border}`,
      background: activa ? C.tealLt : C.white,
      color: activa ? C.tealMid : C.textMuted,
      fontWeight: activa ? 700 : 400,
    }),
    chipAccion: { fontSize: 10, padding: "3px 8px", borderRadius: 12, cursor: "pointer", background: "none", border: `1px solid ${C.border}`, color: C.textMuted, marginLeft: 4 },
    title: { fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 4 },
    subtitle: { fontSize: 13, color: C.textMuted, marginBottom: 16 },
    kpiRow: { display: "flex", gap: 24, fontSize: 12, color: C.textMuted, marginBottom: 12, flexWrap: "wrap" },
    kpiVal: { color: C.text, fontWeight: 700 },
    // Encabezado de dia (solo visible/relevante en rango)
    diaHdr: { fontSize: 15, fontWeight: 700, color: C.text, marginTop: 8, marginBottom: 8, paddingBottom: 5, borderBottom: `2px solid ${C.text}` },
    diaKpi: { fontSize: 11, fontWeight: 400, color: C.textMuted, marginLeft: 10 },
    linHdr: { fontSize: 14, fontWeight: 700, color: C.tealMid, marginTop: 14, marginBottom: 6, paddingBottom: 4, borderBottom: `1.5px solid ${C.teal}` },
    table: { width: "100%", borderCollapse: "collapse", fontSize: 12, tableLayout: "fixed" },
    th: { background: C.grayLt, padding: "6px 10px", textAlign: "left", borderBottom: `1px solid ${C.border}`, fontWeight: 600, color: C.text },
    td: { padding: "6px 10px", borderBottom: `0.5px solid ${C.border}` },
    tdNum: { padding: "6px 10px", borderBottom: `0.5px solid ${C.border}`, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" },
    tdCenter: { padding: "6px 10px", borderBottom: `0.5px solid ${C.border}`, textAlign: "center" },
    tfoot: { fontWeight: 700, background: C.tealLt, color: C.tealMid },
    empty: { fontSize: 13, color: C.textMuted, fontStyle: "italic", padding: "32px 0", textAlign: "center" },
  };

  return (
    <div style={s.container}>
      {/* CSS de impresion: oculta controles, navbar, deja solo el contenido tabular.
          En rango, cada dia arranca en pagina nueva (page-break-before). */}
      <style>{`
        @media print {
          body, html { background: white !important; margin: 0; padding: 0; }
          /* Ocultar elementos fuera de la programacion */
          body > *:not(#root) { display: none !important; }
          #root > div > div:first-child,  /* Topbar */
          #root > div > nav,                /* Tabs */
          .no-print { display: none !important; }
          /* Layout limpio */
          #pd-imprimible { padding: 0 !important; }
          .pd-card { box-shadow: none !important; border: none !important; padding: 0 !important; margin-bottom: 8px !important; }
          .pd-section-print-only { display: block !important; }
          /* Compactacion para piso: fuentes y padding reducidos */
          .pd-table { font-size: 9px !important; }
          .pd-table th, .pd-table td { padding: 2px 6px !important; }
          .pd-dia-hdr { font-size: 13px !important; margin-top: 0 !important; margin-bottom: 6px !important; }
          .pd-lin-hdr { font-size: 11px !important; margin-top: 8px !important; margin-bottom: 3px !important; }
          .pd-doc-title { font-size: 13px !important; }
          /* Salto de pagina antes de cada dia (menos el primero) */
          .pd-dia { page-break-before: always; }
          .pd-dia:first-of-type { page-break-before: avoid; }
          /* No cortar una tabla de linea a la mitad entre paginas */
          .pd-linea-bloque { page-break-inside: avoid; }
          @page { size: A4; margin: 1.2cm; }
        }
        .pd-section-print-only { display: none; }
      `}</style>

      {/* Controles (no se imprimen) */}
      <div className="no-print" style={s.card}>
        <div style={s.controlsRow}>
          <span style={s.label}>Desde:</span>
          <input type="date" style={s.dateInput} value={fechaDesde}
                 onChange={(e) => setFechaDesde(e.target.value)} />
          <span style={s.label}>Hasta:</span>
          <input type="date" style={s.dateInput} value={fechaHasta} min={fechaDesde}
                 onChange={(e) => setFechaHasta(e.target.value)} />
          <button style={s.btnPrint} onClick={() => {
            const tituloOriginal = document.title;
            // Controla el nombre sugerido del PDF al "Guardar como PDF" del browser
            document.title = esRango
              ? `Plan de Produccion ${desde}_a_${hasta}`
              : `Plan de Produccion ${desde}`;
            window.print();
            // Restaurar tras impresion (afterprint dispara tanto en print como en cancel)
            const restore = () => {
              document.title = tituloOriginal;
              window.removeEventListener('afterprint', restore);
            };
            window.addEventListener('afterprint', restore);
          }}>🖨️ Imprimir / Guardar PDF</button>
        </div>
        {lineasDisponibles.length > 0 && (
          <div style={{ ...s.controlsRow, marginTop: 12, gap: 6 }}>
            <span style={s.label}>Lineas:</span>
            {lineasDisponibles.map(l => (
              <span key={l} style={s.chip(lineasFiltro?.has(l))} onClick={() => toggleLinea(l)}>{l}</span>
            ))}
            <button style={s.chipAccion} onClick={seleccionarTodas}>Todas</button>
            <button style={s.chipAccion} onClick={limpiarTodas}>Ninguna</button>
          </div>
        )}
      </div>

      {/* Documento imprimible */}
      <div id="pd-imprimible">
        {/* Cabecera del documento (una sola vez, arriba) */}
        <div className="pd-card" style={s.card}>
          <div className="pd-doc-title" style={s.title}>Traverso S.A. — Programacion Diaria</div>
          <div style={s.subtitle}>
            {esRango
              ? `${formatearFechaLarga(desde)}  —  ${formatearFechaLarga(hasta)}`
              : formatearFechaLarga(desde)}
          </div>
          <div style={s.kpiRow}>
            <span>OFs aprobadas: <span style={s.kpiVal}>{totalesRango.ofs}</span></span>
            <span>Total cajas: <span style={s.kpiVal}>{fmtN(totalesRango.cajas)}</span></span>
            <span>Total unidades: <span style={s.kpiVal}>{fmtN(totalesRango.unidades)}</span></span>
            {esRango && (
              <span>Dias con produccion: <span style={s.kpiVal}>{fechasConOFs.length}</span> de {fechas.length}</span>
            )}
            {lineasFiltro && lineasFiltro.size < lineasDisponibles.length && (
              <span style={{ color: C.amber }}>(Lineas filtradas: {Array.from(lineasFiltro).join(", ") || "ninguna"})</span>
            )}
          </div>
        </div>

        {/* Sin OFs en todo el rango */}
        {totalesRango.ofs === 0 && (
          <div className="pd-card" style={s.card}>
            <div style={s.empty}>
              No hay ordenes aprobadas {esRango
                ? `entre ${formatearFechaLarga(desde)} y ${formatearFechaLarga(hasta)}`
                : `para ${formatearFechaLarga(desde)}`}.<br />
              Aprueba ordenes desde "Plan de Produccion" o "Detalle Produccion" para verlas aqui.
            </div>
          </div>
        )}

        {/* Por cada fecha con OFs -> dentro, por cada linea */}
        {fechasConOFs.map((fIso) => {
          const lineasDelDia = porFecha[fIso];
          // totales del dia
          let cajasDia = 0, uDia = 0, ofsDia = 0;
          Object.values(lineasDelDia).forEach(arr => arr.forEach(o => {
            ofsDia += 1;
            cajasDia += Number(o.cantidad_real_cj || 0);
            uDia += Number(o.cantidad_real_u || 0);
          }));
          const lineasOrden = Object.keys(lineasDelDia).sort();

          return (
            <div key={fIso} className="pd-dia pd-card" style={s.card}>
              {/* Encabezado del dia — visible siempre; en modo 1 dia es redundante
                  con la cabecera pero no molesta y ordena el impreso. */}
              <div className="pd-dia-hdr" style={s.diaHdr}>
                {formatearFechaLarga(fIso)}
                <span style={s.diaKpi}>
                  · {ofsDia} OF · {fmtN(cajasDia)} cj · {fmtN(uDia)} u
                </span>
              </div>

              {lineasOrden.map((linea) => {
                const ofs = lineasDelDia[linea];
                const cajasLinea = ofs.reduce((acc, o) => acc + Number(o.cantidad_real_cj || 0), 0);
                const uLinea = ofs.reduce((acc, o) => acc + Number(o.cantidad_real_u || 0), 0);
                return (
                  <div key={linea} className="pd-linea-bloque">
                    <div className="pd-lin-hdr" style={s.linHdr}>Linea: {linea}</div>
                    <table className="pd-table" style={s.table}>
                      <colgroup>
                        <col style={{ width: "10%" }} />
                        <col style={{ width: "9%" }} />
                        <col style={{ width: "22%" }} />
                        <col style={{ width: "7%" }} />
                        <col style={{ width: "8%" }} />
                        <col style={{ width: "12%" }} />
                        <col style={{ width: "32%" }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th style={s.th}>N° OF</th>
                          <th style={s.th}>SKU</th>
                          <th style={s.th}>Descripcion</th>
                          <th style={{ ...s.th, textAlign: "right" }}>Cajas</th>
                          <th style={{ ...s.th, textAlign: "right" }}>Unidades</th>
                          <th style={s.th}>Responsable</th>
                          <th style={s.th}>Comentarios</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ofs.map(o => (
                          <tr key={o.numero_of}>
                            <td style={{ ...s.td, fontWeight: 700, color: C.tealMid, whiteSpace: "nowrap" }}>{o.numero_of}</td>
                            <td style={{ ...s.td, fontFamily: "monospace" }}>{o.sku}</td>
                            <td style={s.td}>{o.descripcion}</td>
                            <td style={s.tdNum}>{fmtN(o.cantidad_real_cj)}</td>
                            <td style={s.tdNum}>{fmtN(o.cantidad_real_u)}</td>
                            <td style={s.td}>{o.responsable || "—"}</td>
                            <td style={{ ...s.td, fontStyle: o.comentario ? "normal" : "italic", color: o.comentario ? C.text : C.textMuted, wordBreak: "break-word" }}>
                              {o.comentario || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr style={s.tfoot}>
                          <td style={s.td} colSpan={3}>Total {linea}</td>
                          <td style={s.tdNum}>{fmtN(cajasLinea)}</td>
                          <td style={s.tdNum}>{fmtN(uLinea)}</td>
                          <td style={s.td} colSpan={2}></td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                );
              })}
            </div>
          );
        })}

        {/* Footer print-only */}
        <div className="pd-section-print-only" style={{ fontSize: 9, color: C.textMuted, textAlign: "center", marginTop: 16, fontStyle: "italic" }}>
          Generado el {new Date().toLocaleString("es-CL")} — Traverso S.A. Sistema de Planificacion de Produccion
        </div>
      </div>
    </div>
  );
}
