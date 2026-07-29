import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";

/**
 * Campanas.jsx — Tablero de campanas de linea (V6, 29-07-2026).
 *
 * Filas = recurso, columnas = semana. Cada celda muestra el modo de granel:
 *   - Con candado (borde solido)  = pin del planificador. El optimizer lo fuerza.
 *   - Punteada                    = propuesta del solver de la ultima corrida.
 *
 * Click en una celda -> elegir modo (fija pin) o "Soltar" (vuelve a decidir el solver).
 *
 * NOTA: las OF/OFM manuales NO estan sujetas a la campana. Se pueden crear en
 * cualquier semana (cambio de formato de emergencia, sobrante de granel).
 */

// Path relativo, igual que App.js: funciona con el proxy del dev-server.
const API = '';
const RECURSO = "GRANEL_SALSAS";

const COLORES = {
  ketchup: { bg: "#FCEBEB", fg: "#791F1F", br: "#E24B4A" },
  mostaza: { bg: "#FAEEDA", fg: "#633806", br: "#EF9F27" },
  "": { bg: "#F1EFE8", fg: "#5F5E5A", br: "#B4B2A9" },
};

const NAVY = "#1A2D4D";

function fmtSemana(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const meses = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${String(d).padStart(2, "0")}-${meses[m - 1]}`;
}

export default function Campanas() {
  const [cal, setCal] = useState([]);
  const [reglas, setReglas] = useState([]);
  const [conteo, setConteo] = useState({});
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [sel, setSel] = useState(null);          // semana seleccionada (panel de acciones)
  const [guardando, setGuardando] = useState("");

  const cargar = useCallback(async () => {
    setCargando(true);
    setError("");
    try {
      const [rc, rr, rs] = await Promise.all([
        axios.get(`${API}/campanas/calendario`, { params: { recurso: RECURSO, semanas: 10 } }),
        axios.get(`${API}/campanas/reglas`),
        axios.get(`${API}/campanas/skus`),
      ]);
      setCal(rc.data.calendario || []);
      setReglas(rr.data.reglas || []);
      setConteo(rs.data.conteo || {});
    } catch (e) {
      setError(String((e.response && e.response.data && e.response.data.detail) || e.message || e));
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);

  const modosDisponibles = (() => {
    const r = reglas.find((x) => x.recurso === RECURSO);
    return (r && r.modos) || ["ketchup", "mostaza"];
  })();

  async function fijar(semana, modo) {
    setGuardando(semana);
    try {
      await axios.put(`${API}/campanas/pin`, { semana, modo, autor: "dashboard" },
                      { params: { recurso: RECURSO } });
      await cargar();
    } catch (e) {
      setError(`No se pudo fijar ${semana}: ${(e.response && e.response.data && e.response.data.detail) || e.message}`);
    } finally {
      setGuardando("");
      setSel(null);
    }
  }

  async function soltar(semana) {
    setGuardando(semana);
    try {
      await axios.delete(`${API}/campanas/pin`,
                         { params: { recurso: RECURSO, semana } });
      await cargar();
    } catch (e) {
      setError(`No se pudo soltar ${semana}: ${(e.response && e.response.data && e.response.data.detail) || e.message}`);
    } finally {
      setGuardando("");
      setSel(null);
    }
  }

  const nFijadas = cal.filter((c) => c.fijado).length;

  return (
    <div style={{ fontFamily: "Arial, Helvetica, sans-serif", color: "#222" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 4 }}>
        <h2 style={{ color: NAVY, margin: 0, fontSize: 20 }}>
          Campañas de línea — granel de salsas
        </h2>
        <span style={{ fontSize: 13, color: "#666" }}>
          {nFijadas} de {cal.length} semanas fijadas
        </span>
      </div>

      <p style={{ fontSize: 13, color: "#555", marginTop: 4, maxWidth: 900 }}>
        La semana que se fabrica granel de <b>ketchup</b> se pueden envasar ketchup,
        barbecue y los productos independientes; la semana de <b>mostaza</b>, las
        mostazas y los independientes. Las celdas con candado las fija el planificador;
        el resto las propone el optimizador.
      </p>

      {Object.keys(conteo).length > 0 && (
        <div style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>
          SKU por grupo:{" "}
          {Object.entries(conteo)
            .sort((a, b) => b[1] - a[1])
            .map(([g, n]) => `${g}: ${n}`)
            .join("  ·  ")}
        </div>
      )}

      {error && (
        <div style={{
          background: "#FCEBEB", color: "#791F1F", border: "1px solid #E24B4A",
          borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 12,
        }}>
          {error}
        </div>
      )}

      {cargando ? (
        <div style={{ fontSize: 14, color: "#666", padding: "20px 0" }}>
          Cargando calendario…
        </div>
      ) : (
        <>
          {/* Grilla de semanas. CSS grid (no <table>) para que las celdas tengan
              tamano predecible, y sin overflow que recorte nada. */}
          <div style={{
            display: "grid",
            gridTemplateColumns: `repeat(${Math.min(cal.length, 5)}, minmax(150px, 1fr))`,
            gap: 8, marginBottom: 16,
          }}>
            {cal.map((c) => {
              const col = COLORES[c.modo] || COLORES[""];
              const activa = sel === c.semana;
              return (
                <button
                  key={c.semana}
                  onClick={() => setSel(activa ? null : c.semana)}
                  disabled={guardando === c.semana}
                  title={c.fijado ? `Fijado por ${c.autor || "planificador"}`
                                  : "Propuesta del optimizador — click para fijar"}
                  style={{
                    textAlign: "left", cursor: "pointer", fontFamily: "inherit",
                    background: col.bg, color: col.fg,
                    border: `${c.fijado ? 2 : 1}px ${c.fijado ? "solid" : "dashed"} ${col.br}`,
                    outline: activa ? `2px solid ${NAVY}` : "none",
                    outlineOffset: 1,
                    borderRadius: 8, padding: "10px 12px",
                    opacity: guardando === c.semana ? 0.5 : 1,
                  }}
                >
                  <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 3 }}>
                    semana del {fmtSemana(c.semana)}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {c.fijado ? "🔒 " : ""}{c.modo || "sin definir"}
                  </div>
                  <div style={{ fontSize: 10.5, opacity: 0.7, marginTop: 2 }}>
                    {c.fijado ? "fijado" : (c.modo ? "propuesto por el plan" : "—")}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Panel de acciones de la semana seleccionada. Va DEBAJO de la grilla,
              sin position:absolute, asi no puede quedar oculto por el contenedor. */}
          {sel && (() => {
            const c = cal.find((x) => x.semana === sel) || {};
            const btn = {
              fontFamily: "inherit", fontSize: 12.5, padding: "7px 14px",
              borderRadius: 6, cursor: "pointer", border: "1px solid #bbb",
              background: "#fff",
            };
            return (
              <div style={{
                background: "#F7F7F4", border: "1px solid #DDD", borderRadius: 8,
                padding: "12px 14px", marginBottom: 14,
                display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
              }}>
                <strong style={{ fontSize: 13 }}>Semana del {fmtSemana(sel)}:</strong>
                {modosDisponibles.map((mo) => (
                  <button key={mo} onClick={() => fijar(sel, mo)}
                    style={{ ...btn,
                      background: (COLORES[mo] || COLORES[""]).bg,
                      color: (COLORES[mo] || COLORES[""]).fg,
                      borderColor: (COLORES[mo] || COLORES[""]).br }}>
                    Fijar {mo}
                  </button>
                ))}
                <button onClick={() => fijar(sel, "")} style={btn}>Sin granel</button>
                {c.fijado && (
                  <button onClick={() => soltar(sel)}
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
        </>
      )}

      <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                    fontSize: 12, color: "#555", marginTop: 12 }}>
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
          propuesto por el optimizador en la ultima corrida
        </span>
      </div>

      <div style={{ fontSize: 12, color: "#777", marginTop: 10, maxWidth: 900 }}>
        Los cambios se aplican en la <b>próxima corrida del plan</b> (cron 6 AM) o al
        regenerar manualmente. Las OF y OFM manuales no están sujetas a la campaña.
      </div>

      <button
        onClick={cargar}
        style={{ marginTop: 14, fontSize: 12, fontFamily: "inherit",
                 padding: "6px 12px", borderRadius: 6,
                 border: "1px solid #bbb", background: "#fff", cursor: "pointer" }}
      >
        Recargar
      </button>
    </div>
  );
}
