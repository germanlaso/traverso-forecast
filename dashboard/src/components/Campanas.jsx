import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";

/**
 * Campanas.jsx — Tablero de campanas de linea (V6, 29-07-2026).
 *
 * Una seccion por REGLA activa (mrp_campana_reglas):
 *   · GRANEL_SALSAS (dimension granel_grupo, linea NULL) = estado de PLANTA.
 *     La semana de ketchup se envasa ketchup/barbecue + independientes; la de
 *     mostaza, las mostazas + independientes.
 *   · L1PET_LV (dimension formato, linea L1Pet LV) = formato de esa linea.
 *     Evita el cambio de formato (180 min) agrupando el mismo envase por semana.
 *
 * Celda con candado = pin del planificador (el plan lo respeta).
 * Celda punteada    = lo que propuso el optimizador en la ultima corrida.
 *
 * Las OF y OFM manuales NO estan sujetas a la campana: entran como entradas
 * fijas, asi que un cambio de formato de emergencia o el envasado de un sobrante
 * de granel se pueden crear en cualquier semana.
 */

// Path relativo, igual que App.js: funciona con el proxy del dev-server.
const API = '';

const NAVY = "#1A2D4D";

// Paleta por modo. Los formatos usan escala azul/verde para no competir
// visualmente con los colores del granel.
const COLORES = {
  ketchup: { bg: "#FCEBEB", fg: "#791F1F", br: "#E24B4A" },
  mostaza: { bg: "#FAEEDA", fg: "#633806", br: "#EF9F27" },
  "1000":  { bg: "#E6F1FB", fg: "#0C447C", br: "#378ADD" },
  "500":   { bg: "#E1F5EE", fg: "#085041", br: "#1D9E75" },
  "":      { bg: "#F1EFE8", fg: "#5F5E5A", br: "#B4B2A9" },
};
const colorDe = (modo) => COLORES[modo] || COLORES[""];

function fmtSemana(iso) {
  const p = iso.split("-").map(Number);
  const meses = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${String(p[2]).padStart(2, "0")}-${meses[p[1] - 1]}`;
}

const etiquetaModo = (r, modo) =>
  !modo ? "sin definir" : (r.dimension === "formato" ? `${modo} ml` : modo);

export default function Campanas() {
  const [reglas, setReglas] = useState([]);
  const [cals, setCals] = useState({});      // {recurso: [{semana,modo,fijado,autor}]}
  const [conteo, setConteo] = useState({});
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [sel, setSel] = useState(null);      // {recurso, semana}
  const [guardando, setGuardando] = useState("");

  const cargar = useCallback(async () => {
    setCargando(true);
    setError("");
    try {
      const rr = await axios.get(`${API}/campanas/reglas`);
      const rs = rr.data.reglas || [];
      setReglas(rs);
      const pares = await Promise.all(rs.map((r) =>
        axios.get(`${API}/campanas/calendario`,
                  { params: { recurso: r.recurso, semanas: 10 } })
             .then((x) => [r.recurso, x.data.calendario || []])
      ));
      setCals(Object.fromEntries(pares));
      try {
        const sk = await axios.get(`${API}/campanas/skus`);
        setConteo(sk.data.conteo || {});
      } catch (e) { /* el conteo es informativo */ }
    } catch (e) {
      setError(String((e.response && e.response.data && e.response.data.detail)
                      || e.message || e));
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  async function fijar(recurso, semana, modo) {
    setGuardando(`${recurso}|${semana}`);
    try {
      await axios.put(`${API}/campanas/pin`,
                      { semana, modo, autor: "dashboard" },
                      { params: { recurso } });
      await cargar();
    } catch (e) {
      setError(`No se pudo fijar ${semana}: ${
        (e.response && e.response.data && e.response.data.detail) || e.message}`);
    } finally {
      setGuardando("");
      setSel(null);
    }
  }

  async function soltar(recurso, semana) {
    setGuardando(`${recurso}|${semana}`);
    try {
      await axios.delete(`${API}/campanas/pin`, { params: { recurso, semana } });
      await cargar();
    } catch (e) {
      setError(`No se pudo soltar ${semana}: ${
        (e.response && e.response.data && e.response.data.detail) || e.message}`);
    } finally {
      setGuardando("");
      setSel(null);
    }
  }

  const btn = {
    fontFamily: "inherit", fontSize: 12.5, padding: "7px 14px",
    borderRadius: 6, cursor: "pointer", border: "1px solid #bbb", background: "#fff",
  };

  return (
    <div style={{ fontFamily: "Arial, Helvetica, sans-serif", color: "#222" }}>
      <h2 style={{ color: NAVY, margin: "0 0 4px", fontSize: 20 }}>
        Campañas de línea
      </h2>
      <p style={{ fontSize: 13, color: "#555", marginTop: 4, maxWidth: 900 }}>
        Reglas de planificación de alto nivel: el <b>granel de salsas</b> habilita qué
        productos se pueden envasar cada semana, y el <b>formato</b> de una línea agrupa
        el mismo envase para evitar los cambios de formato. Las celdas con candado las
        fija el planificador; el resto las propone el optimizador.
      </p>

      {Object.keys(conteo).length > 0 && (
        <div style={{ fontSize: 12, color: "#666", marginBottom: 14 }}>
          SKU por grupo de granel:{" "}
          {Object.entries(conteo).sort((a, b) => b[1] - a[1])
            .map(([g, n]) => `${g}: ${n}`).join("  ·  ")}
        </div>
      )}

      {error && (
        <div style={{ background: "#FCEBEB", color: "#791F1F",
                      border: "1px solid #E24B4A", borderRadius: 6,
                      padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {cargando && (
        <div style={{ fontSize: 14, color: "#666", padding: "20px 0" }}>
          Cargando calendarios…
        </div>
      )}

      {!cargando && reglas.length === 0 && (
        <div style={{ fontSize: 13, color: "#666" }}>
          No hay reglas de campaña activas.
        </div>
      )}

      {!cargando && reglas.map((r) => {
        const cal = cals[r.recurso] || [];
        const nFij = cal.filter((c) => c.fijado).length;
        const modos = (r.modos || []).map(String);
        const nCols = Math.min(Math.max(cal.length, 1), 5);
        return (
          <div key={r.recurso} style={{ marginBottom: 26 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10,
                          marginBottom: 8, flexWrap: "wrap" }}>
              <h3 style={{ margin: 0, fontSize: 15, color: NAVY }}>
                {r.dimension === "formato"
                  ? `Formato — línea ${r.linea}`
                  : "Granel de salsas — planta"}
              </h3>
              <span style={{ fontSize: 12, color: "#777" }}>
                {modos.map((m) => etiquetaModo(r, m)).join(" / ")}
                {" · "}máx {r.max_modos_semana}/semana
                {" · "}{nFij} de {cal.length} fijadas
              </span>
            </div>

            <div style={{ display: "grid", gap: 8,
                          gridTemplateColumns: `repeat(${nCols}, minmax(150px, 1fr))` }}>
              {cal.map((c) => {
                const col = colorDe(c.modo);
                const activa = sel && sel.recurso === r.recurso && sel.semana === c.semana;
                const clave = `${r.recurso}|${c.semana}`;
                return (
                  <button
                    key={c.semana}
                    onClick={() => setSel(activa ? null : { recurso: r.recurso, semana: c.semana })}
                    disabled={guardando === clave}
                    title={c.fijado ? `Fijado por ${c.autor || "planificador"}`
                                    : "Propuesta del optimizador — click para fijar"}
                    style={{
                      textAlign: "left", cursor: "pointer", fontFamily: "inherit",
                      background: col.bg, color: col.fg,
                      border: `${c.fijado ? 2 : 1}px ${c.fijado ? "solid" : "dashed"} ${col.br}`,
                      outline: activa ? `2px solid ${NAVY}` : "none", outlineOffset: 1,
                      borderRadius: 8, padding: "10px 12px",
                      opacity: guardando === clave ? 0.5 : 1,
                    }}
                  >
                    <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 3 }}>
                      semana del {fmtSemana(c.semana)}
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>
                      {c.fijado ? "🔒 " : ""}{etiquetaModo(r, c.modo)}
                    </div>
                    <div style={{ fontSize: 10.5, opacity: 0.7, marginTop: 2 }}>
                      {c.fijado ? "fijado" : (c.modo ? "propuesto por el plan" : "—")}
                    </div>
                  </button>
                );
              })}
            </div>

            {sel && sel.recurso === r.recurso && (() => {
              const c = cal.find((x) => x.semana === sel.semana) || {};
              return (
                <div style={{ background: "#F7F7F4", border: "1px solid #DDD",
                              borderRadius: 8, padding: "12px 14px", marginTop: 10,
                              display: "flex", alignItems: "center", gap: 10,
                              flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 13 }}>
                    Semana del {fmtSemana(sel.semana)}:
                  </strong>
                  {modos.map((mo) => (
                    <button key={mo} onClick={() => fijar(r.recurso, sel.semana, mo)}
                      style={{ ...btn, background: colorDe(mo).bg,
                               color: colorDe(mo).fg, borderColor: colorDe(mo).br }}>
                      Fijar {etiquetaModo(r, mo)}
                    </button>
                  ))}
                  <button onClick={() => fijar(r.recurso, sel.semana, "")} style={btn}>
                    {r.dimension === "formato" ? "Sin restricción" : "Sin granel"}
                  </button>
                  {c.fijado && (
                    <button onClick={() => soltar(r.recurso, sel.semana)}
                      style={{ ...btn, color: "#185FA5", borderColor: "#9CC4EA" }}>
                      Soltar (decide el plan)
                    </button>
                  )}
                  <button onClick={() => setSel(null)}
                    style={{ ...btn, border: "none", background: "transparent", color: "#777" }}>
                    Cancelar
                  </button>
                </div>
              );
            })()}
          </div>
        );
      })}

      <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                    fontSize: 12, color: "#555", marginTop: 4 }}>
        <span>
          <span style={{ display: "inline-block", width: 22, height: 12,
                         border: "2px solid #888", borderRadius: 3,
                         verticalAlign: "-1px", marginRight: 4 }} />
          🔒 fijado por el planificador (el plan lo respeta)
        </span>
        <span>
          <span style={{ display: "inline-block", width: 22, height: 12,
                         border: "1px dashed #888", borderRadius: 3,
                         verticalAlign: "-1px", marginRight: 4 }} />
          propuesto por el optimizador en la última corrida
        </span>
      </div>

      <div style={{ fontSize: 12, color: "#777", marginTop: 10, maxWidth: 900 }}>
        Los cambios se aplican en la <b>próxima corrida del plan</b> (cron 6 AM) o al
        regenerar manualmente. Las OF y OFM manuales no están sujetas a la campaña.
      </div>

      <button onClick={cargar} style={{ ...btn, marginTop: 14 }}>Recargar</button>
    </div>
  );
}
