// MapaQuiebres.jsx — Mapa de Quiebres y Riesgo (SKU x semana)
// PARA REVISION. Ubicacion sugerida: dashboard/src/components/MapaQuiebres.jsx
// Estilos inline autocontenidos: ajustar a la estetica de las otras pestanas
// (Campanas.jsx / StockDiario.jsx) al integrar. Archivo en LF.
//
// Fuente: GET /plan/quiebres_grid  (endpoint lector puro del snapshot vigente).
// Props:
//   onOpenSku(sku)  -> abre ProyeccionModal para ese SKU. Conectar al MISMO
//                      handler que ya usa StockDiario al clickear un SKU.
//
// Convencion del proyecto: axios + API relativa ('' con proxy). NO hardcodear IP.

import React, { useEffect, useState, useMemo } from "react";
import axios from "axios";
import ProyeccionModal from "./ProyeccionModal";

const API = process.env.REACT_APP_API_BASE || "";

// severidad -> color (hex propio del dashboard; NO tokens CDS)
const COLORS = {
  0: { bg: "transparent", fg: "#9aa0a6", bd: "#e6e6e3" }, // OK
  1: { bg: "#FBF0CF", fg: "#7a5c00", bd: "#F0DFA0" },     // bajo SS
  2: { bg: "#F3A63B", fg: "#3d2600", bd: "#D98E22" },     // riesgo <=10% SS
  3: { bg: "#D64545", fg: "#ffffff", bd: "#B93636" },     // quiebre
};
const NIV = ["OK", "Bajo SS", "Riesgo", "Quiebre"];
const DOW = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

// filtros: umbral minimo de peor_sev para mostrar el SKU
const FILTROS = [
  { key: "todos", label: "Todos", min: 1 },
  { key: "riesgo", label: "Riesgo y quiebre", min: 2 },
  { key: "quiebre", label: "Solo quiebre", min: 3 },
];

function addDaysISO(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + n);
  const p = (x) => String(x).padStart(2, "0");
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
}

export default function MapaQuiebres({ onOpenSku }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // (04-08) Por defecto "solo quiebre": es lo que se revisa primero en la
  // reunion de produccion. Los otros niveles quedan a un clic.
  const [filtro, setFiltro] = useState("quiebre");
  const [colapsadas, setColapsadas] = useState({}); // codigo -> true si colapsada
  const [celda, setCelda] = useState(null);         // {sku, wk} abierto (drill-down)
  // (04-08) El clic en el SKU abre el modal de stock AQUI MISMO, en vez de
  // navegar a la pestana Stock Diario: revisando el mapa no se pierde el
  // contexto ni el scroll.
  const [modalSku, setModalSku] = useState(null);  // {sku, descripcion} | null

  useEffect(() => {
    let vivo = true;
    setLoading(true);
    axios
      .get(`${API}/plan/quiebres_grid`)
      .then((r) => { if (vivo) { setData(r.data); setError(null); } })
      .catch((e) => { if (vivo) setError(e?.message || "Error al cargar"); })
      .finally(() => { if (vivo) setLoading(false); });
    return () => { vivo = false; };
  }, []);

  const minSev = FILTROS.find((f) => f.key === filtro).min;

  // aplica filtro por peor_sev del SKU y recalcula resumen/lineas visibles
  const lineasVis = useMemo(() => {
    if (!data?.lineas) return [];
    return data.lineas
      .map((ln) => {
        const skus = ln.skus.filter((s) => s.peor_sev >= minSev);
        const res = { n_skus: skus.length, n_quiebre: 0, n_riesgo: 0, n_bajo_ss: 0,
                      n_dias_quiebre: 0 };
        skus.forEach((s) => {
          if (s.peor_sev === 3) res.n_quiebre++;
          else if (s.peor_sev === 2) res.n_riesgo++;
          else if (s.peor_sev === 1) res.n_bajo_ss++;
          // (04-08) dias-SKU en quiebre: n_quiebre cuenta SKU distintos y no
          // dice cuanto duran los quiebres. Un SKU con 12 dias caidos y otro
          // con 1 pesan igual en ese conteo.
          res.n_dias_quiebre += Object.values(s.dias || {})
            .filter((d) => d && d.sev === 3).length;
        });
        return { ...ln, skus, resumen: res };
      })
      .filter((ln) => ln.skus.length > 0);
  }, [data, minSev]);

  const totales = useMemo(() => {
    const t = { skus: 0, quiebre: 0, riesgo: 0, rp: 0, dias_quiebre: 0 };
    lineasVis.forEach((ln) =>
      ln.skus.forEach((s) => {
        t.skus++;
        if (s.peor_sev === 3) t.quiebre++;
        if (s.peor_sev === 2) t.riesgo++;
        if (s.recepcion_pendiente) t.rp++;
        t.dias_quiebre += Object.values(s.dias || {}).filter((d) => d && d.sev === 3).length;
      })
    );
    return t;
  }, [lineasVis]);

  // (04-08) La recepcion pendiente es un aviso de CALIDAD DE DATOS, no de
  // severidad: hay que verlo siempre. Contarlo solo sobre los SKU visibles lo
  // esconde cuando el filtro es "solo quiebre" (ahora el default), justo en el
  // caso en que sirve: una OF lanzada que no se refleja en el stock puede
  // significar tanto un quiebre falso como produccion sin registrar.
  const rpTotal = useMemo(() => {
    if (!data?.lineas) return 0;
    return data.lineas.reduce(
      (n, ln) => n + ln.skus.filter((s) => s.recepcion_pendiente).length, 0);
  }, [data]);

  if (loading) return <div style={{ padding: 24, color: "#666" }}>Cargando mapa de quiebres…</div>;
  if (error) return <div style={{ padding: 24, color: "#B93636" }}>Error: {error}</div>;
  if (!data?.disponible) return <div style={{ padding: 24, color: "#666" }}>{data?.mensaje || "No hay plan vigente."}</div>;

  const semanas = data.semanas || [];
  const gridCols = `260px repeat(${semanas.length}, minmax(46px, 1fr))`;

  const toggleLinea = (cod) => setColapsadas((c) => ({ ...c, [cod]: !c[cod] }));
  const toggleCelda = (sku, wk) =>
    setCelda((c) => (c && c.sku === sku && c.wk === wk ? null : { sku, wk }));

  return (
    <div style={{ padding: "8px 4px 24px" }}>
      {/* barra: filtro + totales */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {FILTROS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFiltro(f.key)}
              style={{
                padding: "5px 12px", fontSize: 13, borderRadius: 6, cursor: "pointer",
                border: "1px solid " + (filtro === f.key ? "#333" : "#ddd"),
                background: filtro === f.key ? "#333" : "#fff",
                color: filtro === f.key ? "#fff" : "#333",
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 18, fontSize: 13, color: "#555", flexWrap: "wrap" }}>
          <span><b>{totales.skus}</b> SKU</span>
          <span style={{ color: "#B93636" }}><b>{totales.quiebre}</b> SKU con quiebre</span>
          {totales.dias_quiebre > 0 && (
            <span style={{ color: "#B93636" }}><b>{totales.dias_quiebre}</b> días quiebre</span>
          )}
          <span style={{ color: "#B4790F" }}><b>{totales.riesgo}</b> en riesgo</span>
          <span title="OF lanzada que no se refleja en el stock: el quiebre puede ser falso, o hay producción sin registrar">
            <b>{rpTotal}</b> recepción pend.
            {rpTotal > totales.rp && (
              <span style={{ color: "#B4790F" }}>
                {" "}({rpTotal - totales.rp} fuera del filtro)
              </span>
            )}
          </span>
        </div>
      </div>

      {/* cabecera de semanas */}
      <div style={{ display: "grid", gridTemplateColumns: gridCols, gap: 3, marginBottom: 3 }}>
        <div />
        {semanas.map((s) => (
          <div key={s.iso} style={{ fontSize: 12, color: "#777", textAlign: "center", whiteSpace: "nowrap" }}>{s.label}</div>
        ))}
      </div>

      {lineasVis.map((ln) => {
        const col = colapsadas[ln.codigo];
        return (
          <div key={ln.codigo} style={{ marginBottom: 6 }}>
            {/* encabezado de linea (colapsable + resumen visual) */}
            <div
              onClick={() => toggleLinea(ln.codigo)}
              style={{
                display: "flex", alignItems: "center", gap: 10, cursor: "pointer",
                padding: "6px 10px", background: "#f5f5f2", borderRadius: 6, userSelect: "none",
              }}
            >
              <span style={{ fontSize: 12, color: "#888", width: 12 }}>{col ? "▸" : "▾"}</span>
              {/* (31-07) linea.nombre es la CATEGORIA (LIQUIDOS, SALSAS...), no la linea:
                  varios codigos comparten nombre y los grupos se veian repetidos. El
                  identificador util es el codigo. Mismo formato que DetalleProduccion. */}
              <span style={{ fontWeight: 600, fontSize: 14 }}>{ln.codigo}</span>
              {ln.nombre && ln.nombre !== ln.codigo && (
                <span style={{ fontSize: 12, color: "#888" }}>— {ln.nombre}</span>
              )}
              <span style={{ fontSize: 12, color: "#999" }}>{ln.resumen.n_skus} SKU</span>
              <div style={{ display: "flex", gap: 5, marginLeft: "auto" }}>
                {ln.resumen.n_quiebre > 0 && <Pill n={ln.resumen.n_quiebre} sev={3} txt="SKU con quiebre" />}
                {ln.resumen.n_dias_quiebre > 0 && <Pill n={ln.resumen.n_dias_quiebre} sev={3} txt="días quiebre" hueco />}
                {ln.resumen.n_riesgo > 0 && <Pill n={ln.resumen.n_riesgo} sev={2} txt="SKU en riesgo" />}
                {ln.resumen.n_bajo_ss > 0 && <Pill n={ln.resumen.n_bajo_ss} sev={1} txt="SKU bajo SS" />}
              </div>
            </div>

            {!col && (
              <div style={{ display: "grid", gridTemplateColumns: gridCols, gap: 3, marginTop: 3 }}>
                {ln.skus.map((s) => (
                  <SkuRow
                    key={s.sku}
                    s={s}
                    semanas={semanas}
                    celda={celda}
                    onToggleCelda={toggleCelda}
                    onOpenSku={(sk) => setModalSku({ sku: sk, descripcion: s.descripcion || "" })}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      <Leyenda />

      {modalSku && (
        <ProyeccionModal
          sku={modalSku.sku}
          descripcion={modalSku.descripcion}
          onClose={() => setModalSku(null)}
        />
      )}
    </div>
  );
}

function Pill({ n, sev, txt, hueco }) {
  const c = COLORS[sev];
  const label = txt || NIV[sev].toLowerCase();
  // `hueco`: mismo color pero sin relleno, para que "dias quiebre" no compita
  // visualmente con "SKU con quiebre" siendo la misma severidad.
  return (
    <span style={{
      fontSize: 12, fontWeight: 600, padding: "1px 8px", borderRadius: 10,
      background: hueco ? "transparent" : (c.bg === "transparent" ? "#eee" : c.bg),
      color: hueco ? c.bd : c.fg,
      border: hueco ? `1px solid ${c.bd}` : "none",
    }}>{n} {label}</span>
  );
}

function SkuRow({ s, semanas, celda, onToggleCelda, onOpenSku }) {
  const byWk = s.semanas || {};
  return (
    <React.Fragment>
      {/* col 1: SKU + desc + recepcion pendiente */}
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", padding: "2px 8px", minHeight: 40 }}>
        <span
          onClick={() => onOpenSku && onOpenSku(s.sku)}
          style={{ fontSize: 13, fontWeight: 600, color: "#1a6fc4", cursor: "pointer", textDecoration: "none" }}
          onMouseEnter={(e) => (e.target.style.textDecoration = "underline")}
          onMouseLeave={(e) => (e.target.style.textDecoration = "none")}
        >
          {s.sku}
        </span>
        <span style={{ fontSize: 11, color: "#999", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 244 }}>
          {s.descripcion}
        </span>
        {s.recepcion_pendiente && (
          <span style={{ fontSize: 11, color: "#B4790F", display: "inline-flex", alignItems: "center", gap: 3 }}>
            ⚠ recepción pend.
          </span>
        )}
      </div>

      {/* celdas por semana */}
      {semanas.map((wk) => {
        const w = byWk[wk.iso] || { sev: 0, dias: 0, def_cj: 0 };
        const c = COLORS[w.sev];
        const flag = s.recepcion_pendiente && w.sev >= 2;
        const abierta = celda && celda.sku === s.sku && celda.wk === wk.iso;
        return (
          <div
            key={wk.iso}
            onClick={() => w.sev > 0 && onToggleCelda(s.sku, wk.iso)}
            title={NIV[w.sev]}
            style={{
              minHeight: 40, borderRadius: 4, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", lineHeight: 1.15,
              background: c.bg, color: c.fg,
              border: flag ? "1.5px dashed #B93636" : "0.5px solid " + (w.sev === 0 ? c.bd : "transparent"),
              cursor: w.sev > 0 ? "pointer" : "default",
              outline: abierta ? "2px solid #333" : "none",
            }}
          >
            {w.sev === 3 && <span style={{ fontSize: 11, fontWeight: 600 }}>-{w.def_cj} cj</span>}
            {w.sev >= 1 && <span style={{ fontSize: 11, fontWeight: 600 }}>{w.dias}d</span>}
          </div>
        );
      })}

      {/* drill-down a dia: fila que ocupa todo el ancho de semanas */}
      {celda && celda.sku === s.sku && (
        <DiaDetalle s={s} wk={celda.wk} nSem={semanas.length} />
      )}
    </React.Fragment>
  );
}

function DiaDetalle({ s, wk, nSem }) {
  const dias = [];
  for (let i = 0; i < 7; i++) {
    const iso = addDaysISO(wk, i);
    const d = s.dias[iso];
    // (31-07) dm = dia/mes para que el drill-down muestre la fecha, no solo el dia
    const dm = iso.slice(8, 10) + "/" + iso.slice(5, 7);
    dias.push({ dow: DOW[i], dm, iso, sev: d ? d.sev : 0, def: d ? d.def_cj : 0 });
  }
  return (
    <React.Fragment>
      <div style={{ gridColumn: "1", display: "flex", alignItems: "center", fontSize: 11, color: "#777", padding: "2px 8px" }}>
        {s.sku} · semana del {wk.slice(8, 10)}/{wk.slice(5, 7)}
      </div>
      <div style={{ gridColumn: `2 / span ${nSem}`, display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 3, padding: "2px 0 8px" }}>
        {dias.map((d) => {
          const c = COLORS[d.sev];
          return (
            <div key={d.iso} style={{
              minHeight: 34, borderRadius: 4, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              background: c.bg, color: c.fg,
              border: "0.5px solid " + (d.sev === 0 ? c.bd : "transparent"),
            }}>
              <span style={{ fontSize: 9.5, color: d.sev >= 2 ? c.fg : "#999", whiteSpace: "nowrap" }}>
                {d.dow} {d.dm}
              </span>
              {d.sev === 3 && <span style={{ fontSize: 10, fontWeight: 600 }}>-{d.def}</span>}
            </div>
          );
        })}
      </div>
    </React.Fragment>
  );
}

function Leyenda() {
  const item = (sev, txt) => (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 14, height: 14, borderRadius: 3,
        background: COLORS[sev].bg === "transparent" ? "#eee" : COLORS[sev].bg,
        border: "0.5px solid " + COLORS[sev].bd,
      }} />
      {txt}
    </span>
  );
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginTop: 16, fontSize: 12, color: "#666", alignItems: "center" }}>
      {item(1, "Bajo SS")}
      {item(2, "Riesgo ≤10% SS")}
      {item(3, "Quiebre (nº = cajas faltantes)")}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span style={{ width: 14, height: 14, borderRadius: 3, border: "1.5px dashed #B93636" }} />
        Recepción pendiente (posible falso)
      </span>
      <span style={{ color: "#999" }}>Clic en celda: ver días · clic en SKU: abre stock diario</span>
    </div>
  );
}
