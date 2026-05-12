import { useState, useMemo } from "react";

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

const fmtN = (v) => Number(v ?? 0).toLocaleString("es-CL");

export default function ProgramacionDiaria({ ordenesAprobadas = [] }) {
  // Fecha por defecto: hoy
  const [fecha, setFecha] = useState(() => {
    const hoy = new Date();
    return hoy.toISOString().slice(0, 10);
  });

  // Lineas disponibles: derivadas de ordenes aprobadas (todas las que existen en BD)
  const lineasDisponibles = useMemo(() => {
    const set = new Set();
    ordenesAprobadas.forEach(o => o.linea && set.add(o.linea));
    return Array.from(set).sort();
  }, [ordenesAprobadas]);

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

  // OFs aprobadas filtradas por fecha (fecha_lanzamiento_real) y lineas
  const ofsDelDia = useMemo(() => {
    if (!lineasFiltro) return [];
    return ordenesAprobadas
      .filter(o => {
        const fl = String(o.fecha_lanzamiento_real || "").slice(0, 10);
        return fl === fecha && lineasFiltro.has(o.linea);
      })
      .sort((a, b) => {
        // Ordenar por linea, despues por SKU
        if (a.linea !== b.linea) return (a.linea || "").localeCompare(b.linea || "");
        return (a.sku || "").localeCompare(b.sku || "");
      });
  }, [ordenesAprobadas, fecha, lineasFiltro]);

  // Agrupar por linea
  const grupos = useMemo(() => {
    const m = {};
    ofsDelDia.forEach(o => {
      const l = o.linea || "Sin linea";
      if (!m[l]) m[l] = [];
      m[l].push(o);
    });
    return m;
  }, [ofsDelDia]);

  const totalOFs = ofsDelDia.length;
  const totalCajas = ofsDelDia.reduce((acc, o) => acc + Number(o.cantidad_real_cj || 0), 0);
  const totalUnidades = ofsDelDia.reduce((acc, o) => acc + Number(o.cantidad_real_u || 0), 0);

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
    linHdr: { fontSize: 14, fontWeight: 700, color: C.tealMid, marginTop: 16, marginBottom: 6, paddingBottom: 4, borderBottom: `1.5px solid ${C.teal}` },
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
      {/* CSS de impresion: oculta controles, navbar, deja solo el contenido tabular */}
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
          .pd-card { box-shadow: none !important; border: none !important; padding: 0 !important; margin-bottom: 12px !important; }
          .pd-section-print-only { display: block !important; }
          /* Reduccion de fuentes para que entre mas en una pagina */
          .pd-table { font-size: 10px !important; }
          .pd-table th, .pd-table td { padding: 4px 8px !important; }
          @page { size: A4; margin: 1.5cm; }
        }
        .pd-section-print-only { display: none; }
      `}</style>

      {/* Controles (no se imprimen) */}
      <div className="no-print" style={s.card}>
        <div style={s.controlsRow}>
          <span style={s.label}>Fecha:</span>
          <input type="date" style={s.dateInput} value={fecha} onChange={(e) => setFecha(e.target.value)} />
          <button style={s.btnPrint} onClick={() => {
            const tituloOriginal = document.title;
            // Controla el nombre sugerido del PDF al "Guardar como PDF" del browser
            document.title = `Plan de Produccion ${fecha}`;
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

      {/* Cabecera del documento imprimible */}
      <div id="pd-imprimible">
        <div className="pd-card" style={s.card}>
          <div style={s.title}>Traverso S.A. — Programacion Diaria</div>
          <div style={s.subtitle}>{formatearFechaLarga(fecha)}</div>
          <div style={s.kpiRow}>
            <span>OFs aprobadas: <span style={s.kpiVal}>{totalOFs}</span></span>
            <span>Total cajas: <span style={s.kpiVal}>{fmtN(totalCajas)}</span></span>
            <span>Total unidades: <span style={s.kpiVal}>{fmtN(totalUnidades)}</span></span>
            {lineasFiltro && lineasFiltro.size < lineasDisponibles.length && (
              <span style={{ color: C.amber }}>(Lineas filtradas: {Array.from(lineasFiltro).join(", ") || "ninguna"})</span>
            )}
          </div>
        </div>

        {/* Si no hay OFs */}
        {totalOFs === 0 && (
          <div className="pd-card" style={s.card}>
            <div style={s.empty}>
              No hay ordenes aprobadas para {formatearFechaLarga(fecha)}.<br />
              Aprueba ordenes desde "Plan de Produccion" o "Detalle Produccion" para verlas aqui.
            </div>
          </div>
        )}

        {/* Por cada linea con OFs */}
        {Object.entries(grupos).map(([linea, ofs]) => {
          const cajasLinea = ofs.reduce((acc, o) => acc + Number(o.cantidad_real_cj || 0), 0);
          const uLinea = ofs.reduce((acc, o) => acc + Number(o.cantidad_real_u || 0), 0);
          return (
            <div key={linea} className="pd-card" style={s.card}>
              <div style={s.linHdr}>Linea: {linea}</div>
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

        {/* Footer print-only */}
        <div className="pd-section-print-only" style={{ fontSize: 9, color: C.textMuted, textAlign: "center", marginTop: 16, fontStyle: "italic" }}>
          Generado el {new Date().toLocaleString("es-CL")} — Traverso S.A. Sistema de Planificacion de Produccion
        </div>
      </div>
    </div>
  );
}
