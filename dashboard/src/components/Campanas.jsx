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
  const [abierta, setAbierta] = useState(null); // semana con el selector abierto
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
      setAbierta(null);
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
      setAbierta(null);
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
        <div style={{ overflowX: "auto", paddingBottom: 8 }}>
          <table style={{ borderCollapse: "separate", borderSpacing: 4 }}>
            <thead>
              <tr>
                <th style={{
                  textAlign: "left", fontSize: 11, color: "#777",
                  fontWeight: 600, padding: "2px 6px", minWidth: 120,
                }}>
                  Recurso
                </th>
                {cal.map((c) => (
                  <th key={c.semana} style={{
                    fontSize: 11, color: "#777", fontWeight: 600, minWidth: 86,
                  }}>
                    {fmtSemana(c.semana)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontSize: 13, fontWeight: 600, padding: "2px 6px" }}>
                  Granel salsas
                </td>
                {cal.map((c) => {
                  const col = COLORES[c.modo] || COLORES[""];
                  const esta = guardando === c.semana;
                  return (
                    <td key={c.semana} style={{ position: "relative" }}>
                      <button
                        onClick={() => setAbierta(abierta === c.semana ? null : c.semana)}
                        disabled={esta}
                        title={c.fijado
                          ? `Fijado por ${c.autor || "planificador"}`
                          : "Propuesta del optimizador — click para fijar"}
                        style={{
                          width: "100%", cursor: esta ? "wait" : "pointer",
                          background: col.bg, color: col.fg,
                          border: `${c.fijado ? 2 : 1}px ${c.fijado ? "solid" : "dashed"} ${col.br}`,
                          borderRadius: 6, padding: "8px 4px",
                          fontSize: 12, fontFamily: "inherit",
                          opacity: esta ? 0.5 : 1,
                        }}
                      >
                        {c.fijado ? "🔒 " : ""}
                        {c.modo || "ninguno"}
                      </button>

                      {abierta === c.semana && (
                        <div style={{
                          position: "absolute", zIndex: 20, top: "100%", left: 0,
                          background: "#fff", border: "1px solid #ccc",
                          borderRadius: 6, padding: 6, minWidth: 130,
                          boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
                        }}>
                          {modosDisponibles.map((mo) => (
                            <div
                              key={mo}
                              onClick={() => fijar(c.semana, mo)}
                              style={{
                                padding: "6px 8px", fontSize: 12, cursor: "pointer",
                                borderRadius: 4, color: (COLORES[mo] || COLORES[""]).fg,
                              }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = "#F2F7FC")}
                              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                            >
                              Fijar {mo}
                            </div>
                          ))}
                          <div
                            onClick={() => fijar(c.semana, "")}
                            style={{ padding: "6px 8px", fontSize: 12, cursor: "pointer",
                                     borderRadius: 4, color: "#5F5E5A" }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "#F2F7FC")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                          >
                            Sin granel
                          </div>
                          {c.fijado && (
                            <div
                              onClick={() => soltar(c.semana)}
                              style={{ padding: "6px 8px", fontSize: 12, cursor: "pointer",
                                       borderRadius: 4, color: "#185FA5",
                                       borderTop: "1px solid #eee", marginTop: 4 }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = "#F2F7FC")}
                              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                            >
                              Soltar (decide el solver)
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", gap: 18, flexWrap: "wrap",
                    fontSize: 12, color: "#555", marginTop: 12 }}>
        <span>
          <span style={{ display: "inline-block", width: 22, height: 12,
                         border: "2px solid #888", borderRadius: 3,
                         verticalAlign: "-1px", marginRight: 4 }} />
          🔒 fijado por el planificador
        </span>
        <span>
          <span style={{ display: "inline-block", width: 22, height: 12,
                         border: "1px dashed #888", borderRadius: 3,
                         verticalAlign: "-1px", marginRight: 4 }} />
          propuesto por el optimizador
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
