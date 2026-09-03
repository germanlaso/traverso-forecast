// MonitorDatalake.jsx — Salud del datalake (submenu de Control).
// Gráfico de latencia SQL (ms, tooltip) + banda de estado HANA + log de eventos.
// Datos del watchdog vía GET /monitor/datalake?horas=N.
import React, { useState, useEffect } from "react";
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceDot,
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

export default function MonitorDatalake() {
  const [horas, setHoras] = useState(24);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const cargar = (h) => {
    setLoading(true); setErr(null);
    fetch(`${API}/monitor/datalake?horas=${h}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => setData(d))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => { cargar(horas); }, [horas]);
  // auto-refresh cada 60s
  useEffect(() => {
    const id = setInterval(() => cargar(horas), 60000);
    return () => clearInterval(id);
  }, [horas]);

  const s = {
    wrap: { padding: "16px 8px", fontFamily: "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif", color: C.text },
    card: { background: "#fff", border: `0.5px solid ${C.border}`, borderRadius: 10, padding: "14px 16px", marginBottom: 14 },
    kpi: (bg) => ({ background: bg, borderRadius: 8, padding: "10px 14px", minWidth: 120, flex: 1, textAlign: "center" }),
    btn: (on) => ({ fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 7, cursor: "pointer",
                    border: `1px solid ${on ? C.teal : C.border}`, background: on ? C.teal : "#fff", color: on ? "#fff" : C.text }),
  };

  const serie = (data?.serie || []).map((p) => ({
    ...p,
    t: p.ts,
    ms: (p.sql_login && p.sql_login_ms != null) ? p.sql_login_ms : null,
    // banda HANA (arriba del gráfico): valor fijo si OK, para pintar área
    hana: p.hana_tcp ? 1 : 0,
    // marca de caída SQL
    falla: p.estado === "FALLA",
  }));
  const fallas = serie.filter((p) => p.falla);
  const maxMs = Math.max(100, ...serie.map((p) => p.ms || 0));

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
          {/* KPIs */}
          <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
            <div style={s.kpi(data.n_falla > 0 ? C.redLt : C.tealLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: data.n_falla > 0 ? C.red : C.tealMid }}>{data.uptime_pct == null ? "—" : `${data.uptime_pct}%`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Uptime SQL ({data.horas}h)</div>
            </div>
            <div style={s.kpi(data.n_falla > 0 ? C.redLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: data.n_falla > 0 ? C.red : C.text }}>{data.n_falla}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Sondeos en falla</div>
            </div>
            <div style={s.kpi(C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{data.lat_media_ms == null ? "—" : `${data.lat_media_ms}ms`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Latencia media SQL</div>
            </div>
            <div style={s.kpi((data.lat_max_ms || 0) > 1000 ? C.redLt : C.grayLt)}>
              <div style={{ fontSize: 22, fontWeight: 700, color: (data.lat_max_ms || 0) > 1000 ? C.red : C.text }}>{data.lat_max_ms == null ? "—" : `${data.lat_max_ms}ms`}</div>
              <div style={{ fontSize: 11, color: C.textMuted }}>Latencia máx SQL</div>
            </div>
          </div>

          {/* Gráfico: latencia SQL (línea) + banda HANA (área abajo) + marcas de caída */}
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Latencia de conexión SQL (ms) · caídas en rojo</div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={serie} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} />
                <XAxis dataKey="t" tickFormatter={fmtHM} tick={{ fontSize: 10, fill: C.textMuted }} interval="preserveStartEnd" minTickGap={40} />
                <YAxis tick={{ fontSize: 10, fill: C.textMuted }} domain={[0, Math.ceil(maxMs * 1.1)]} label={{ value: "ms", angle: -90, position: "insideLeft", fontSize: 10, fill: C.textMuted }} />
                <Tooltip
                  labelFormatter={fmtTs}
                  formatter={(v, name) => {
                    if (name === "ms") return [v == null ? "sin conexión" : `${v} ms`, "Latencia SQL"];
                    return [v ? "OK" : "FALLA", "HANA"];
                  }}
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.border}` }}
                />
                {/* banda HANA: área verde/roja en la base */}
                <Area type="stepAfter" dataKey="hana" stroke="none"
                      fill={C.tealLt} fillOpacity={0.5} yAxisId={0}
                      // escalar la banda al 6% inferior del gráfico
                      isAnimationActive={false}
                      baseValue={0} />
                <Line type="monotone" dataKey="ms" stroke={C.teal} strokeWidth={1.6} dot={false}
                      connectNulls={false} isAnimationActive={false} />
                {/* marcas de caída SQL (rojo) en la base */}
                {fallas.map((p, i) => (
                  <ReferenceDot key={i} x={p.t} y={0} r={3} fill={C.red} stroke="none" />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
            <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4 }}>
              Línea = latencia del login SQL (los huecos son caídas). Puntos rojos abajo = sondeos en FALLA.
              Franja verde inferior = HANA disponible.
            </div>
          </div>

          {/* Log de eventos */}
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
              Log de eventos <span style={{ fontWeight: 400, color: C.textMuted }}>(cambios de estado y logins lentos &gt;1000ms)</span>
            </div>
            {(!data.eventos || data.eventos.length === 0) ? (
              <div style={{ fontSize: 12, color: C.textMuted }}>Sin eventos en la ventana.</div>
            ) : (
              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    {["Hora", "Evento", "Detalle", "ms"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "5px 8px", borderBottom: `2px solid ${C.border}`, color: C.gray, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.eventos.map((e, i) => {
                    const col = e.estado === "FALLA" ? C.red : e.estado === "OK" ? C.tealMid : C.amber;
                    return (
                      <tr key={i} style={{ background: i % 2 ? C.grayLt : "#fff" }}>
                        <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>{fmtTs(e.ts)}</td>
                        <td style={{ padding: "4px 8px", fontWeight: 600, color: col }}>{e.tipo === "cambio_estado" ? "Cambio de estado" : "Login lento"}</td>
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
