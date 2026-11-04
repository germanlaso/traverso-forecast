import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  ComposedChart, BarChart, LineChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';

// Dashboard de rendimiento de la operación (menú Control).
// Fuente: GET /operacion/dashboard. Todas las cifras vienen calculadas del backend (kpi_operacion.py).

const API = process.env.REACT_APP_API_BASE || '';

// Paleta del dashboard principal (App.js)
const C = {
  teal: '#1D9E75', tealLt: '#E1F5EE', tealMid: '#0F6E56',
  blue: '#185FA5', blueLt: '#E6F1FB',
  purple: '#534AB7', purpleLt: '#EEEDFE',
  amber: '#EF9F27', amberLt: '#FAEEDA',
  gray: '#5F5E5A', grayLt: '#F1EFE8',
  danger: '#E24B4A', dangerLt: '#FCEBEB',
  border: '#D3D1C7', text: '#2C2C2A', textMuted: '#888780', bg: '#F8F7F4',
};

const s = {
  wrap: { padding: 16, fontFamily: 'Arial,sans-serif', color: C.text, background: C.bg },
  card: { background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 10, padding: 16, marginBottom: 16 },
  h2: { margin: '0 0 4px', fontSize: 20 },
  h3: { margin: '0 0 2px', fontSize: 15 },
  sub: { fontSize: 12, color: C.textMuted, margin: '0 0 12px' },
  filtros: { display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' },
  label: { display: 'flex', flexDirection: 'column', fontSize: 12, gap: 4, color: C.gray },
  input: { padding: '6px 8px', border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, background: '#fff' },
  chip: (on) => ({
    padding: '5px 10px', borderRadius: 14, fontSize: 12, cursor: 'pointer',
    border: `1px solid ${on ? C.teal : C.border}`, background: on ? C.tealLt : '#fff', color: on ? C.tealMid : C.gray,
  }),
  btn: { padding: '7px 16px', border: 'none', borderRadius: 6, background: C.teal, color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  kpis: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginBottom: 16 },
  kpi: { background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 10, padding: '12px 14px' },
  kpiLabel: { fontSize: 11, color: C.textMuted, textTransform: 'uppercase', letterSpacing: 0.4 },
  kpiValor: { fontSize: 24, fontWeight: 700, margin: '4px 0 0' },
  kpiNota: { fontSize: 11, color: C.textMuted },
  grid2: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 16 },
  tabla: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th: { textAlign: 'left', padding: '6px 8px', borderBottom: `1.5px solid ${C.border}`, color: C.gray, whiteSpace: 'nowrap', fontWeight: 600 },
  td: { padding: '5px 8px', borderBottom: `0.5px solid ${C.grayLt}` },
  num: { textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
  aviso: { background: C.amberLt, color: '#633806', borderRadius: 8, padding: '8px 12px', fontSize: 12, marginBottom: 12 },
  error: { background: C.dangerLt, color: '#A32D2D', borderRadius: 8, padding: '8px 12px', fontSize: 13, marginBottom: 12 },
};

// ---------- utilidades ----------
const iso = (d) => {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};
const ultimoDomingo = () => {
  const d = new Date();
  const dow = (d.getDay() + 6) % 7;       // lunes = 0
  d.setDate(d.getDate() - dow - 1);
  return d;
};
const rangoSemanas = (n) => {
  const hasta = ultimoDomingo();
  const desde = new Date(hasta);
  desde.setDate(desde.getDate() - n * 7 + 1);
  return { desde: iso(desde), hasta: iso(hasta) };
};
const etiquetaSemana = (isoStr) => `${isoStr.slice(8, 10)}/${isoStr.slice(5, 7)}`;
const pct = (v, dec = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(dec)}%`);
const cj = (v) => (v === null || v === undefined ? '–' : Math.round(v).toLocaleString('es-CL'));
const h1 = (v) => (v === null || v === undefined ? '–' : v.toLocaleString('es-CL', { maximumFractionDigits: 1 }));

const colorPct = (v, indicador) => {
  if (v === null || v === undefined) return { background: '#fff', color: C.textMuted };
  if (indicador !== 'cumplimiento_vs_sap' && v > 1.05) return { background: C.amberLt, color: '#854F0B', fontWeight: 700 };
  if (indicador === 'cumplimiento_vs_sap') {
    if (v < 0.7) return { background: C.dangerLt, color: '#A32D2D' };
    if (v > 1.3) return { background: C.amberLt, color: '#854F0B' };
  }
  const a = Math.max(0.06, Math.min(v, 1)) * 0.85;
  return { background: `rgba(29,158,117,${a.toFixed(2)})`, color: a > 0.45 ? '#fff' : C.text };
};

const INDICADORES = [
  ['eficiencia', 'Eficiencia (real / nominal)'],
  ['ocupacion_programada_sap', 'Ocupación programada SAP'],
  ['cumplimiento_vs_sap', 'Cumplimiento real vs SAP'],
];

const CLASES_FUERA = {
  IMPORTADO_ETIQUETADO: 'Importado + etiquetado',
  MAQUILA: 'Maquila',
  ARMADO: 'Armado (multipacks)',
  SEMIELABORADO: 'Semielaborado',
  POR_CLASIFICAR: 'Por clasificar',
};

const TooltipBox = ({ active, payload, label, fmt }) => {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{ background: '#fff', border: `0.5px solid ${C.border}`, borderRadius: 8, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }}>{p.name}: {fmt ? fmt(p.value, p.dataKey) : p.value}</div>
      ))}
    </div>
  );
};

const Kpi = ({ label, valor, nota, serie, campo, color = C.teal }) => (
  <div style={s.kpi}>
    <div style={s.kpiLabel}>{label}</div>
    <div style={{ ...s.kpiValor, color }}>{valor}</div>
    <div style={s.kpiNota}>{nota}</div>
    {serie && serie.length > 1 && (
      <div style={{ height: 32, marginTop: 4 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={serie}>
            <Line type="monotone" dataKey={campo} stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    )}
  </div>
);

// ---------- componente ----------
export default function DashboardOperacion() {
  const inicial = rangoSemanas(8);
  const [filtros, setFiltros] = useState({ ...inicial, categoria: '', linea: '' });
  const [aplicados, setAplicados] = useState({ ...inicial, categoria: '', linea: '' });
  const [preset, setPreset] = useState(8);
  const [data, setData] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState(null);
  const [indicador, setIndicador] = useState('eficiencia');
  const [verTodoConc, setVerTodoConc] = useState(false);

  useEffect(() => {
    let vivo = true;
    setCargando(true);
    setError(null);
    const params = { desde: aplicados.desde, hasta: aplicados.hasta };
    if (aplicados.categoria) params.categoria = aplicados.categoria;
    if (aplicados.linea) params.linea = aplicados.linea;
    axios.get(`${API}/operacion/dashboard`, { params })
      .then(({ data }) => { if (vivo) setData(data); })
      .catch((e) => {
        if (!vivo) return;
        const d = e?.response?.data?.detail;
        setError(typeof d === 'string' ? d : 'No se pudo cargar el dashboard. Revisa la conexión con el servidor.');
      })
      .finally(() => { if (vivo) setCargando(false); });
    return () => { vivo = false; };
  }, [aplicados]);

  const opciones = data?.opciones || { lineas: [], categorias: [] };
  const lineasFiltradas = opciones.lineas.filter((l) => !filtros.categoria || l.categoria === filtros.categoria);

  const evo = useMemo(() => (data?.evolutivo || []).map((e) => ({
    ...e, etiqueta: etiquetaSemana(e.semana) + (e.parcial ? '*' : ''),
  })), [data]);

  const ocupacion = useMemo(() => (data?.lineas || []).map((x) => {
    const n = x.horas.nominal || 0;
    const p = (v) => (n ? Math.round((v / n) * 1000) / 10 : 0);
    return {
      linea: x.linea,
      producido: p(x.horas.heq_producidas),
      parada_plan: p(x.horas.parada_planificada),
      parada_noplan: p(x.horas.parada_no_planificada),
      sin_programa: p(x.horas.sin_programa),
      no_explicada: p(x.horas.no_explicadas),
      prog_sap: p(x.horas.heq_programadas_sap),
      bitacora: x.con_bitacora,
    };
  }).sort((a, b) => b.producido - a.producido), [data]);

  const semanasHeat = useMemo(() => evo.map((e) => e.semana), [evo]);
  const filasHeat = useMemo(() => {
    const el = data?.evolutivo_lineas || {};
    return Object.keys(el).sort().map((lin) => {
      const porSem = Object.fromEntries(el[lin].map((p) => [p.semana, p]));
      return { linea: lin, celdas: semanasHeat.map((sem) => porSem[sem]?.[indicador] ?? null) };
    });
  }, [data, semanasHeat, indicador]);

  const concTop = useMemo(() => {
    const rows = (data?.conciliacion_sku || []).filter((c) => c.clase === 'LINEA');
    const orden = [...rows].sort((a, b) =>
      Math.abs(b.cj_programado_sap - b.cj_real) + Math.abs(b.desvio_sap_vs_app_cj)
      - (Math.abs(a.cj_programado_sap - a.cj_real) + Math.abs(a.desvio_sap_vs_app_cj)));
    return verTodoConc ? orden : orden.slice(0, 12);
  }, [data, verTodoConc]);

  const eventosPorTipo = useMemo(() => {
    const m = {};
    (data?.eventos || []).forEach((e) => {
      const k = e.tipo_nombre;
      m[k] = m[k] || { tipo: k, categoria: e.categoria, minutos: 0, n: 0, lineas: new Set() };
      m[k].minutos += Number(e.minutos);
      m[k].n += Number(e.n);
      m[k].lineas.add(e.linea);
    });
    return Object.values(m).sort((a, b) => b.minutos - a.minutos);
  }, [data]);

  const aplicarPreset = (n) => {
    setPreset(n);
    const r = rangoSemanas(n);
    const f = { ...filtros, ...r };
    setFiltros(f);
    setAplicados(f);
  };

  const r = data?.resumen;
  const adv = data?.advertencias || {};
  const fuera = data?.fuera_de_lineas || {};
  const hayFuera = Object.keys(fuera).length > 0;

  return (
    <div style={s.wrap}>
      <h2 style={s.h2}>Rendimiento de la operación</h2>
      <p style={s.sub}>
        Programado en la app vs programado en SAP vs producido (Terminal Report). Horas expresadas en
        horas-equivalentes a velocidad nominal. Semanas lunes a domingo.
      </p>

      {/* ---------- Filtros ---------- */}
      <div style={s.card}>
        <div style={s.filtros}>
          <label style={s.label}>Desde
            <input type="date" style={s.input} value={filtros.desde}
              onChange={(e) => { setPreset(null); setFiltros({ ...filtros, desde: e.target.value }); }} />
          </label>
          <label style={s.label}>Hasta
            <input type="date" style={s.input} value={filtros.hasta}
              onChange={(e) => { setPreset(null); setFiltros({ ...filtros, hasta: e.target.value }); }} />
          </label>
          <label style={s.label}>Categoría
            <select style={s.input} value={filtros.categoria}
              onChange={(e) => setFiltros({ ...filtros, categoria: e.target.value, linea: '' })}>
              <option value="">Todas</option>
              {opciones.categorias.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label style={s.label}>Línea
            <select style={s.input} value={filtros.linea} onChange={(e) => setFiltros({ ...filtros, linea: e.target.value })}>
              <option value="">Todas</option>
              {lineasFiltradas.map((l) => <option key={l.codigo} value={l.codigo}>{l.codigo}</option>)}
            </select>
          </label>
          <button style={s.btn} onClick={() => setAplicados({ ...filtros })} disabled={cargando}>
            {cargando ? 'Calculando…' : 'Aplicar'}
          </button>
          <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
            {[1, 4, 8, 13, 26].map((n) => (
              <span key={n} style={s.chip(preset === n)} onClick={() => aplicarPreset(n)}>
                {n === 1 ? 'Última semana' : `${n} sem`}
              </span>
            ))}
          </div>
        </div>
      </div>

      {error && <div style={s.error}>{error}</div>}
      {!data && cargando && <div style={s.card}>Calculando indicadores…</div>}

      {data && r && (
        <>
          {r.lineas_con_bitacora < r.n_lineas && (
            <div style={s.aviso}>
              {r.lineas_con_bitacora} de {r.n_lineas} líneas tienen eventos en la bitácora para este período.
              Sin eventos, la capacidad ociosa queda como "no explicada" y no se puede separar entre paradas y falta de programa.
            </div>
          )}

          {/* ---------- KPIs ---------- */}
          <div style={s.kpis}>
            <Kpi label="Programado app" valor={cj(r.cj_programado_app)} nota="cajas (OF aprobadas)" serie={evo} campo="cj_programado_app" color={C.purple} />
            <Kpi label="Programado SAP" valor={cj(r.cj_programado_sap)} nota="cajas (OF SAP)" serie={evo} campo="cj_programado_sap" color={C.blue} />
            <Kpi label="Producido real" valor={cj(r.cj_real)} nota="cajas (Terminal Report)" serie={evo} campo="cj_real" color={C.teal} />
            <Kpi label="Adopción app" valor={pct(r.adopcion_app_sobre_sap)} nota="programa SAP con OF de la app" serie={evo} campo="adopcion_app_sobre_sap" color={C.purple} />
            <Kpi label="Cumplimiento" valor={pct(r.cumplimiento_vs_sap)} nota="real / programado SAP" serie={evo} campo="cumplimiento_vs_sap" color={C.blue} />
            <Kpi label="Eficiencia" valor={pct(r.eficiencia)} nota={`${h1(r.heq_producidas)} h-eq de ${h1(r.horas_nominales)} h nominales`} serie={evo} campo="eficiencia" color={C.teal} />
            <Kpi label="Ocupación programada" valor={pct(r.ocupacion_programada_sap)} nota="h-eq programadas SAP / nominal" serie={evo} campo="ocupacion_programada_sap" color={C.amber} />
          </div>

          {/* ---------- App vs SAP / SAP vs Real ---------- */}
          <div style={s.grid2}>
            <div style={s.card}>
              <h3 style={s.h3}>Programado en la app vs programado en SAP</h3>
              <p style={s.sub}>Cajas por semana y % del programa SAP que tiene OF en la app.</p>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={evo} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} />
                  <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: C.textMuted }} />
                  <YAxis yAxisId="cj" tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                  <YAxis yAxisId="pct" orientation="right" domain={[0, 1.2]} tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={(v) => pct(v)} />
                  <Tooltip content={<TooltipBox fmt={(v, k) => (k === 'adopcion_app_sobre_sap' ? pct(v, 1) : cj(v))} />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar yAxisId="cj" dataKey="cj_programado_app" name="App" fill={C.purple} radius={[3, 3, 0, 0]} />
                  <Bar yAxisId="cj" dataKey="cj_programado_sap" name="SAP" fill={C.blue} radius={[3, 3, 0, 0]} />
                  <Line yAxisId="pct" dataKey="adopcion_app_sobre_sap" name="Adopción" stroke={C.amber} strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div style={s.card}>
              <h3 style={s.h3}>Programado en SAP vs producido real</h3>
              <p style={s.sub}>Cajas por semana y cumplimiento (real / SAP).</p>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={evo} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} />
                  <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: C.textMuted }} />
                  <YAxis yAxisId="cj" tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                  <YAxis yAxisId="pct" orientation="right" domain={[0, 1.4]} tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={(v) => pct(v)} />
                  <Tooltip content={<TooltipBox fmt={(v, k) => (k === 'cumplimiento_vs_sap' ? pct(v, 1) : cj(v))} />} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <ReferenceLine yAxisId="pct" y={1} stroke={C.textMuted} strokeDasharray="4 4" />
                  <Bar yAxisId="cj" dataKey="cj_programado_sap" name="SAP" fill={C.blue} radius={[3, 3, 0, 0]} />
                  <Bar yAxisId="cj" dataKey="cj_real" name="Real" fill={C.teal} radius={[3, 3, 0, 0]} />
                  <Line yAxisId="pct" dataKey="cumplimiento_vs_sap" name="Cumplimiento" stroke={C.danger} strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* ---------- Ocupación por línea ---------- */}
          <div style={s.card}>
            <h3 style={s.h3}>Ocupación por línea</h3>
            <p style={s.sub}>
              % de las horas nominales del período: producido, paradas registradas en la bitácora, sin programa y
              ociosidad no explicada. Sobre 100% = producción mayor a la capacidad nominal parametrizada.
            </p>
            <ResponsiveContainer width="100%" height={Math.max(220, ocupacion.length * 26 + 60)}>
              <BarChart data={ocupacion} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grayLt} horizontal={false} />
                <XAxis type="number" domain={[0, (max) => Math.max(100, Math.ceil(max / 20) * 20)]} tick={{ fontSize: 11, fill: C.textMuted }} tickFormatter={(v) => `${v}%`} />
                <YAxis type="category" dataKey="linea" width={96} tick={{ fontSize: 11, fill: C.text }} />
                <Tooltip content={<TooltipBox fmt={(v) => `${v}%`} />} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine x={100} stroke={C.gray} strokeDasharray="4 4" />
                <Bar dataKey="producido" name="Producido" stackId="o" fill={C.teal} />
                <Bar dataKey="parada_plan" name="Parada planificada" stackId="o" fill={C.blue} />
                <Bar dataKey="parada_noplan" name="Parada no planificada" stackId="o" fill={C.danger} />
                <Bar dataKey="sin_programa" name="Sin programa" stackId="o" fill={C.amber} />
                <Bar dataKey="no_explicada" name="Ociosa no explicada" stackId="o" fill={C.grayLt} />
              </BarChart>
            </ResponsiveContainer>

            <div style={{ ...s.grid2, marginTop: 12 }}>
              <div>
                <strong style={{ fontSize: 13 }}>Detalle por línea</strong>
                <div style={{ overflowX: 'auto' }}>
                  <table style={s.tabla}>
                    <thead><tr>
                      {['Línea', 'Nominal h', 'Producido', 'Prog. SAP', 'Cumpl.', 'Bitácora'].map((h) => <th key={h} style={s.th}>{h}</th>)}
                    </tr></thead>
                    <tbody>
                      {(data.lineas || []).map((x) => (
                        <tr key={x.linea}>
                          <td style={s.td}>{x.linea}{x.alertas.length > 0 && <span title={x.alertas.join('\n')} style={{ color: C.amber, marginLeft: 4 }}>⚠</span>}</td>
                          <td style={{ ...s.td, ...s.num }}>{h1(x.horas.nominal)}</td>
                          <td style={{ ...s.td, ...s.num }}>{pct(x.kpi.eficiencia)}</td>
                          <td style={{ ...s.td, ...s.num }}>{pct(x.kpi.ocupacion_programada_sap)}</td>
                          <td style={{ ...s.td, ...s.num, ...colorPct(x.kpi.cumplimiento_vs_sap, 'cumplimiento_vs_sap') }}>{pct(x.kpi.cumplimiento_vs_sap)}</td>
                          <td style={{ ...s.td, ...s.num }}>{x.n_eventos || '–'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <strong style={{ fontSize: 13 }}>Eventos de la bitácora en el período</strong>
                {eventosPorTipo.length === 0 ? (
                  <p style={{ fontSize: 12, color: C.textMuted }}>No hay eventos registrados para el filtro seleccionado.</p>
                ) : (
                  <table style={s.tabla}>
                    <thead><tr>{['Tipo', 'Horas', 'Eventos', 'Líneas'].map((h) => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
                    <tbody>
                      {eventosPorTipo.map((e) => (
                        <tr key={e.tipo}>
                          <td style={s.td}>{e.tipo}</td>
                          <td style={{ ...s.td, ...s.num }}>{h1(e.minutos / 60)}</td>
                          <td style={{ ...s.td, ...s.num }}>{e.n}</td>
                          <td style={s.td}>{[...e.lineas].join(', ')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* ---------- Evolutivo por línea ---------- */}
          <div style={s.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <div>
                <h3 style={s.h3}>Evolutivo por línea</h3>
                <p style={{ ...s.sub, marginBottom: 0 }}>Semanas lunes a domingo; * = semana parcial o en curso.</p>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {INDICADORES.map(([k, l]) => <span key={k} style={s.chip(indicador === k)} onClick={() => setIndicador(k)}>{l}</span>)}
              </div>
            </div>
            <div style={{ overflowX: 'auto', marginTop: 12 }}>
              <table style={{ ...s.tabla, borderCollapse: 'separate', borderSpacing: 2 }}>
                <thead><tr>
                  <th style={s.th}>Línea</th>
                  {evo.map((e) => <th key={e.semana} style={{ ...s.th, textAlign: 'center' }}>{e.etiqueta}</th>)}
                </tr></thead>
                <tbody>
                  {filasHeat.map((f) => (
                    <tr key={f.linea}>
                      <td style={{ ...s.td, whiteSpace: 'nowrap' }}>{f.linea}</td>
                      {f.celdas.map((v, i) => (
                        <td key={i} style={{ ...s.td, ...s.num, textAlign: 'center', borderRadius: 4, minWidth: 46, ...colorPct(v, indicador) }}>{pct(v)}</td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <td style={{ ...s.td, fontWeight: 700 }}>Total</td>
                    {evo.map((e) => (
                      <td key={e.semana} style={{ ...s.td, ...s.num, textAlign: 'center', fontWeight: 700, ...colorPct(e[indicador], indicador) }}>{pct(e[indicador])}</td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* ---------- Desvíos por SKU ---------- */}
          <div style={s.card}>
            <h3 style={s.h3}>Mayores desvíos por SKU</h3>
            <p style={s.sub}>Ordenados por desvío app vs SAP más desvío SAP vs real (cajas). Solo SKU planificados en líneas.</p>
            <div style={{ overflowX: 'auto' }}>
              <table style={s.tabla}>
                <thead><tr>
                  {['SKU', 'Línea', 'Situación', 'App cj', 'SAP cj', 'Real cj', 'SAP − App', 'Cumpl.'].map((h) => <th key={h} style={s.th}>{h}</th>)}
                </tr></thead>
                <tbody>
                  {concTop.map((c) => (
                    <tr key={c.sku}>
                      <td style={s.td}>{c.sku}</td>
                      <td style={s.td}>{c.linea_atribuida || '–'}</td>
                      <td style={s.td}>{{ ambos: 'App y SAP', solo_sap: 'Solo SAP', solo_app: 'Solo app', sin_programa: 'Sin programa' }[c.categoria]}</td>
                      <td style={{ ...s.td, ...s.num }}>{cj(c.cj_programado_app)}</td>
                      <td style={{ ...s.td, ...s.num }}>{cj(c.cj_programado_sap)}</td>
                      <td style={{ ...s.td, ...s.num }}>{cj(c.cj_real)}</td>
                      <td style={{ ...s.td, ...s.num, color: c.desvio_sap_vs_app_cj ? C.text : C.textMuted }}>{cj(c.desvio_sap_vs_app_cj)}</td>
                      <td style={{ ...s.td, ...s.num, ...colorPct(c.cumplimiento_vs_sap, 'cumplimiento_vs_sap') }}>{pct(c.cumplimiento_vs_sap)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <span style={{ ...s.chip(false), display: 'inline-block', marginTop: 8 }} onClick={() => setVerTodoConc(!verTodoConc)}>
              {verTodoConc ? 'Ver solo los 12 mayores' : 'Ver todos'}
            </span>
          </div>

          {/* ---------- Fuera de líneas y calidad de datos ---------- */}
          <div style={s.grid2}>
            {hayFuera && (
              <div style={s.card}>
                <h3 style={s.h3}>Producción fuera de líneas MRP</h3>
                <p style={s.sub}>No entra a los KPIs de línea ni a los totales de arriba.</p>
                <table style={s.tabla}>
                  <thead><tr>{['Clase', 'SKU', 'SAP cj', 'Real cj', 'Cumpl.'].map((h) => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
                  <tbody>
                    {Object.entries(fuera).map(([k, v]) => (
                      <tr key={k}>
                        <td style={s.td}>{CLASES_FUERA[k] || k}</td>
                        <td style={{ ...s.td, ...s.num }}>{v.n_skus}</td>
                        <td style={{ ...s.td, ...s.num }}>{cj(v.cj_programado_sap)}</td>
                        <td style={{ ...s.td, ...s.num }}>{cj(v.cj_real)}</td>
                        <td style={{ ...s.td, ...s.num }}>{v.cj_programado_sap ? pct(v.cj_real / v.cj_programado_sap) : '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {Object.keys(adv).length > 0 && (
              <div style={s.card}>
                <h3 style={s.h3}>Calidad de datos</h3>
                <p style={s.sub}>Elementos que el cálculo no pudo medir o que requieren validación.</p>
                {Object.entries(adv).map(([k, v]) => (
                  <div key={k} style={{ fontSize: 12, marginBottom: 6 }}>
                    <strong>{k.replace(/_/g, ' ')}</strong> ({v.length}): <span style={{ color: C.textMuted }}>{v.slice(0, 12).join(', ')}{v.length > 12 ? '…' : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
