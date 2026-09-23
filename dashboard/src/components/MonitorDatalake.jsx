// MonitorDatalake.jsx — Salud del datalake (submenu de Control).
// Gráfico de latencia SQL (ms, tooltip) + banda de estado HANA + log de eventos.
// Datos del watchdog vía GET /monitor/datalake?horas=N.
// Zoom: arrastrar sobre el gráfico selecciona un período; doble clic o
// "Restablecer zoom" vuelve a la ventana completa. El log de eventos se filtra
// al período del zoom; los KPIs siguen en vivo (sin filtrar).
import React, { useState, useEffect } from "react";
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceDot, ReferenceArea,
} from "recharts";

const API = process.env.REACT_APP_API_BASE || "";

const C = {
  teal: "#1D9E75", tealLt: "#E1F5EE", tealMid: "#0F6E56",
  amber: "#EF9F27", red: "#E24B4A", redLt: "#FCEBEB",
  gray: "#5F5E5A", grayLt: "#F1EFE8", border: "#D3D1C7",
  text: "#2C2C2A", textMuted: "#888780",
};

const VENTANAS = [[24, "24 h"], [48, "48 h"], [168, "7 días"]];

// 'ISO' -> 'dd-mm HH:MM'
const fmtTs = (iso) => {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}-${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const fmtHM = (iso) => {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};

// segundos -> "2d 04:15:30" (o "04:15:30" si <1 día)
const fmtDur = (seg) => {
  if (seg == null) return "—";
  const d = Math.floor(seg / 86400);
  const h = Math.floor((seg % 86400) / 3600);
  const m = Math.floor((seg % 3600) / 60);
  const s = seg % 60;
  const p = (n) => String(n).padStart(2, "0");
  const hms = `${p(h)}:${p(m)}:${p(s)}`;
  return d > 0 ? `${d}d ${hms}` : hms;
};

// mínimo de sondeos para aceptar una selección (evita que un clic simple haga zoom)
const ZOOM_MIN_PUNTOS = 3;

export default function MonitorDatalake() {
  const [horas, setHoras] = useState(24);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  // zoom aplicado: { ini, fin } en epoch ms (NO índices: la ventana rueda con el refresh)
  const [zoom, setZoom] = useState(null);
  // selección en curso durante el arrastre: { a, b } = labels ISO del eje X
  const [sel, setSel] = useState(null);

  const cargar = (h) => {
    setLoading(true); setErr(null);
    fetch(`${API}/monitor/datalake?horas=${h}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => setData(d))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => { cargar(horas); }, [horas]);
  // auto-refresh cada 60s (no toca el zoom)
  useEffect(() => {
    const id = setInterval(() => cargar(horas), 60000);
    return () => clearInterval(id);
  }, [horas]);
  // cambiar la ventana (24h/48h/7d) resetea el zoom
  useEffect(() => { setZoom(null); setSel(null); }, [horas]);

  const s = {
    wrap: { padding: "16px 8px", fontFamily: "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif", color: C.text },
    card: { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: "14px 16px", marginBottom: 14 },
    kpi: (bg) => ({ background: bg, borderRadius: 8, padding: "10px 14px", minWidth: 120, flex: 1, textAlign: "center" }),
    btn: (on) => ({ fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 7, cursor: "pointer",
                    border: `1px solid ${on ? C.teal : C.border}`, background: on ? C.teal : "#fff", color: on ? "#fff" : C.text }),
  };

  const serieFull = (data?.serie || []).map((p) => ({
    ...p,
    t: p.ts,
    tms: Date.parse(p.ts),
    ms: (p.sql_login && p.sql_login_ms != null) ? p.sql_login_ms : null,
    // latencia de login HANA (ms); null si HANA no responde en ese sondeo
    msHana: (p.hana_tcp && p.hana_login_ms != null) ? p.hana_login_ms : null,
    _hanaOk: !!p.hana_tcp,
    _vpn: p.transporte === "vpn",
    // marca de caída SQL
    falla: p.estado === "FALLA",
  }));
  const enZoom = (tms) => !zoom || (tms >= zoom.ini && tms <= zoom.fin);
  const serie0 = serieFull.filter((p) => enZoom(p.tms));

  // si el refresh sacó el período del zoom fuera de la ventana, volver a la vista completa
  useEffect(() => {
    if (zoom && serieFull.length > 0 && serie0.length === 0) setZoom(null);
  }, [zoom, serieFull.length, serie0.length]);

  const fallas = serie0.filter((p) => p.falla);
  // escala Y calculada sobre lo VISIBLE: al hacer zoom el eje se reajusta
  const maxMs = Math.max(100, ...serie0.map((p) => Math.max(p.ms || 0, p.msHana || 0)));
  const yTop = Math.ceil(maxMs * 1.1);
  // bandas escaladas al eje (si usaran valor 1 sobre un eje de ~3600ms serían 1px invisible):
  //  - HANA: franja fina en la base (6% inferior) cuando HANA está OK
  //  - VPN: tinte de TODO el alto (opacidad baja) en los tramos por VPN
  const serie = serie0.map((p) => ({
    ...p,
    hana: p._hanaOk ? yTop * 0.06 : 0,
    vpn: p._vpn ? yTop : 0,
  }));

  const eventosVista = (data?.eventos || []).filter((e) => enZoom(Date.parse(e.ts)));

  // --- zoom por arrastre ---
  const onDown = (e) => { if (e && e.activeLabel) setSel({ a: e.activeLabel, b: e.activeLabel }); };
  const onMove = (e) => {
    if (sel && e && e.activeLabel && e.activeLabel !== sel.b) setSel({ a: sel.a, b: e.activeLabel });
  };
  const aplicarZoom = () => {
    if (!sel) return;
    const ia = serie.findIndex((p) => p.t === sel.a);
    const ib = serie.findIndex((p) => p.t === sel.b);
    setSel(null);
    if (ia < 0 || ib < 0) return;
    const [i0, i1] = ia <= ib ? [ia, ib] : [ib, ia];
    if (i1 - i0 + 1 < ZOOM_MIN_PUNTOS) return;   // clic o arrastre mínimo: ignorar
    setZoom({ ini: serie[i0].tms, fin: serie[i1].tms });
  };
  const resetZoom = () => { setZoom(null); setSel(null); };

  return (
    <div style={s.wrap}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Salud del datalake</h2>
        <span style={{ color: C.textMuted, fontSize: 12 }}>Conectividad SQL Server y HANA · watchdog</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {VENTANAS.map(([h, lbl]) => (
            <button key={h} onClick={() => setHoras(h)} style={s.btn(horas === h)}>{lbl}</button>
          ))}
        </div>
      </div>

      {loading && !data && <div style={{ color: C.textMuted }}>Cargando…</div>}
      {err && <div style={{ color: C.red }}>Error: {err}</div>}

      {data && (
        <>
          {/* KPIs (en vivo, NO se filtran por zoom) */}
          <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <div style={s.kpi(data.sql_arriba === false ? C.redLt : C.tealLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: data.sql_arriba === false ? C.red : C.tealMid }}>
                {data.sql_arriba == null ? "—" : `${data.sql_arriba ? "↑" : "↓"} ${fmtDur(data.sql_uptime_seg)}`}
              </div>
              <div style={{ fontSize: 11, color: C.textMuted }}>SQL {data.sql_arriba === false ? "caído hace" : "arriba hace"}</div>
            </div>
            <div style={s.kpi(data.hana_arriba === false ? C.redLt : C.tealLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: data.hana_arriba === false ? C.red : C.tealMid }}>
                {data.hana_arriba == null ? "—" : `${data.hana_arriba ? "↑" : "↓"} ${fmtDur(data.hana_uptime_seg)}`}
              </div>
              <div style={{ fontSize: 11, color: C.textMuted }}>HANA {data.hana_arriba === false ? "caído hace" : "arriba hace"}</div>
            </div>
            <div style={s.kpi(C.grayLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text }}>{data.lat_media_ms == null ? "—" : `${data.lat_media_ms}ms`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Latencia media SQL</div>
            </div>
            <div style={s.kpi((data.lat_max_ms || 0) > 1000 ? C.redLt : C.grayLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: (data.lat_max_ms || 0) > 1000 ? C.red : C.text }}>{data.lat_max_ms == null ? "—" : `${data.lat_max_ms}ms`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Latencia máx SQL</div>
            </div>
            <div style={s.kpi(C.grayLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.amber }}>{data.lat_media_hana_ms == null ? "—" : `${data.lat_media_hana_ms}ms`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Latencia media HANA</div>
            </div>
            <div style={s.kpi(data.transporte_actual === "vpn" ? C.grayLt : C.tealLt)}>
              <div style={{ fontSize: 20, fontWeight: 700, color: data.transporte_actual === "vpn" ? C.amber : C.tealMid }}>
                {data.transporte_actual == null ? "—" : (data.transporte_actual === "vpn" ? "VPN" : data.transporte_actual === "mpls" ? "MPLS" : "?")}
              </div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Conexión actual</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: C.textMuted, marginTop: -6, marginBottom: 12 }}>
            Uptime SQL {data.uptime_sql_pct ?? "—"}% · HANA {data.uptime_hana_pct ?? "—"}% (últimas {data.horas}h)
          </div>

          {/* Gráfico: latencia SQL (línea) + banda HANA (área abajo) + marcas de caída */}
          <div style={s.card}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>
                Latencia de conexión (ms) · caídas en rojo
                <span style={{ fontWeight: 400, fontSize: 11, color: C.textMuted, marginLeft: 8 }}>
                  <span style={{ color: C.teal }}>■</span> SQL&nbsp;&nbsp;<span style={{ color: C.amber }}>■</span> HANA
                </span>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
                {zoom ? (
                  <>
                    <span style={{ fontSize: 11, color: C.text }}>
                      Zoom: <strong>{fmtTs(zoom.ini)}</strong> a <strong>{fmtTs(zoom.fin)}</strong> ({serie.length} sondeos)
                    </span>
                    <button onClick={resetZoom} style={s.btn(false)}>Restablecer zoom</button>
                  </>
                ) : (
                  <span style={{ fontSize: 11, color: C.textMuted }}>Arrastrá sobre el gráfico para acercar un período</span>
                )}
              </div>
            </div>
            <div onDoubleClick={resetZoom}
                 style={{ userSelect: "none", cursor: sel ? "col-resize" : "crosshair" }}>
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={serie} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
                               onMouseDown={onDown} onMouseMove={onMove}
                               onMouseUp={aplicarZoom} onMouseLeave={aplicarZoom}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} />
                  <XAxis dataKey="t" tickFormatter={zoom || horas > 24 ? fmtTs : fmtHM}
                         tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" minTickGap={40} />
                  <YAxis tick={{ fontSize: 10, fill: C.textMuted }} domain={[0, yTop]} label={{ value: "ms", angle: -90, position: "insideLeft", fontSize: 10, fill: C.textMuted }} />
                  <Tooltip
                    labelFormatter={fmtTs}
                    formatter={(v, name) => {
                      if (name === "ms") return [v == null ? "sin conexión" : `${v} ms`, "Latencia SQL"];
                      if (name === "msHana") return [v == null ? "sin conexión" : `${v} ms`, "Latencia HANA"];
                      if (name === "vpn") return [v > 0 ? "por VPN" : "por MPLS", "Transporte"];
                      if (name === "hana") return [v > 0 ? "OK" : "FALLA", "HANA"];
                      return [v, name];
                    }}
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.border}` }}
                    labelStyle={{ color: C.text, fontWeight: 700, marginBottom: 2 }}
                    itemStyle={{ color: C.text }}
                  />
                  {/* banda VPN: tinte ámbar de fondo (contingencia) — va al fondo, alto completo */}
                  <Area type="stepAfter" dataKey="vpn" stroke="none"
                        fill={C.amber} fillOpacity={0.14} yAxisId={0}
                        isAnimationActive={false} baseValue={0} />
                  {/* banda HANA: franja verde en la base (6% inferior) cuando HANA OK */}
                  <Area type="stepAfter" dataKey="hana" stroke="none"
                        fill={C.tealLt} fillOpacity={0.6} yAxisId={0}
                        isAnimationActive={false} baseValue={0} />
                  <Line type="monotone" dataKey="ms" stroke={C.teal} strokeWidth={1.6} dot={false}
                        connectNulls={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="msHana" stroke={C.amber} strokeWidth={1.6} dot={false}
                        connectNulls={false} isAnimationActive={false} />
                  {/* marcas de caída SQL (rojo) en la base */}
                  {fallas.map((p, i) => (
                    <ReferenceDot key={i} x={p.t} y={0} r={3} fill={C.red} stroke="none" />
                  ))}
                  {/* selección en curso (arrastre) */}
                  {sel && sel.a !== sel.b && (
                    <ReferenceArea x1={sel.a} x2={sel.b} fill={C.gray} fillOpacity={0.15}
                                   stroke={C.gray} strokeOpacity={0.4} />
                  )}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4 }}>
              Líneas = latencia del login (verde SQL, ámbar HANA; los huecos son caídas). Puntos rojos abajo = sondeos en FALLA.
              Franja verde inferior = HANA disponible. Franja ámbar = conexión por VPN (contingencia).
              Doble clic en el gráfico = restablecer zoom.
            </div>
          </div>

          {/* Log de eventos (filtrado al período del zoom, si hay) */}
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
              Log de eventos <span style={{ fontWeight: 400, color: C.textMuted }}>(cambios de estado y logins lentos &gt;1000ms)</span>
              {zoom && (
                <span style={{ fontWeight: 400, fontSize: 11, color: C.text, marginLeft: 8 }}>
                  · período del zoom ({eventosVista.length} de {(data.eventos || []).length})
                </span>
              )}
            </div>
            {eventosVista.length === 0 ? (
              <div style={{ fontSize: 12, color: C.textMuted }}>
                {zoom ? "Sin eventos en el período seleccionado." : "Sin eventos en la ventana."}
              </div>
            ) : (
              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    {["Hora", "Servicio", "Estado", "Detalle", "ms"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "5px 8px", borderBottom: `2px solid ${C.border}`, color: C.gray, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {eventosVista.map((e, i) => {
                    const col = e.estado === "FALLA" ? C.red : e.estado === "OK" ? C.tealMid : C.amber;
                    return (
                      <tr key={i} style={{ background: i % 2 ? C.grayLt : "#fff" }}>
                        <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>{fmtTs(e.ts)}</td>
                        <td style={{ padding: "4px 8px", fontWeight: 700 }}>{e.servicio}</td>
                        <td style={{ padding: "4px 8px", fontWeight: 600, color: col }}>{e.estado}</td>
                        <td style={{ padding: "4px 8px" }}>{e.detalle}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right", color: C.textMuted }}>{e.ms != null ? `${e.ms}` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
