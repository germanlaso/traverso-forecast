import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';

// Modal de bitácora para un día + línea, pensado para abrirse desde cualquier grilla
// (Detalle Producción). Muestra los eventos del día y permite registrar / anular.
// Reutiliza los endpoints /bitacora/* (bitacora.py).
//
// Uso:
//   const { conteo, recargar } = useBitacoraConteo(desde, hasta);   // badge por celda
//   conteo[`${linea}|${fecha}`] -> { n, minutos, min_detencion, min_sin_programa, categorias }
//   min_detencion = paradas planificadas + no planificadas (lo que descuenta capacidad)
//   <MinutosDetencion info={conteo[k]} />  -> texto para el pie de la celda
//   <ModalBitacora fecha="2026-11-05" linea="Miele LV" onClose={...} onCambio={recargar} />

const API = process.env.REACT_APP_API_BASE || '';
const KEY_USUARIO = 'bitacora_registrado_por';   // mismo key que la pestaña Bitácora

const C = {
  teal: '#1D9E75', tealLt: '#E1F5EE', tealMid: '#0F6E56',
  amber: '#EF9F27', amberLt: '#FAEEDA', danger: '#E24B4A', dangerLt: '#FCEBEB',
  gray: '#5F5E5A', grayLt: '#F1EFE8', border: '#D3D1C7', text: '#2C2C2A', textMuted: '#888780',
};
const COLOR_CATEGORIA = {
  PARADA_PLANIFICADA: '#185FA5',
  PARADA_NO_PLANIFICADA: C.danger,
  SIN_PROGRAMA: C.amber,
  INFORMATIVO: C.gray,
};
// En fechas futuras solo se anotan estas categorías (mismo criterio que bitacora.py)
export const CATEGORIAS_FUTURAS = ['PARADA_PLANIFICADA', 'SIN_PROGRAMA'];
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

const hoyLocal = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};
const semanaIso = (isoStr) => {
  const d = new Date(Date.UTC(+isoStr.slice(0, 4), +isoStr.slice(5, 7) - 1, +isoStr.slice(8, 10)));
  const dia = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dia);
  const inicio = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - inicio) / 86400000 + 1) / 7);
};
const tituloFecha = (isoStr) => {
  const d = new Date(+isoStr.slice(0, 4), +isoStr.slice(5, 7) - 1, +isoStr.slice(8, 10));
  return `${DIAS[d.getDay()]} ${isoStr.slice(8, 10)}/${isoStr.slice(5, 7)} · Sem ${semanaIso(isoStr)}`;
};
const leerUsuario = () => { try { return localStorage.getItem(KEY_USUARIO) || ''; } catch { return ''; } };
const guardarUsuario = (v) => { try { localStorage.setItem(KEY_USUARIO, v); } catch { /* sin storage */ } };
const detalleError = (e, porDefecto) => {
  const d = e?.response?.data?.detail;
  return typeof d === 'string' ? d : porDefecto;
};

// ---------------------------------------------------------------------------
// Hook: conteo de eventos por línea|fecha para pintar badges en una grilla
// ---------------------------------------------------------------------------
export function useBitacoraConteo(desde, hasta) {
  const [conteo, setConteo] = useState({});
  const recargar = useCallback(() => {
    if (!desde || !hasta) return;
    axios.get(`${API}/bitacora/eventos`, { params: { desde, hasta } })
      .then(({ data }) => {
        const m = {};
        (data.eventos || []).forEach((e) => {
          const k = `${e.linea}|${e.fecha}`;
          m[k] = m[k] || { n: 0, minutos: 0, min_detencion: 0, min_sin_programa: 0, categorias: new Set() };
          const min = e.duracion_min || 0;
          m[k].n += 1;
          m[k].minutos += min;
          if (e.categoria === 'PARADA_PLANIFICADA' || e.categoria === 'PARADA_NO_PLANIFICADA') m[k].min_detencion += min;
          if (e.categoria === 'SIN_PROGRAMA') m[k].min_sin_programa += min;
          m[k].categorias.add(e.categoria);
        });
        setConteo(m);
      })
      .catch(() => setConteo({}));   // la grilla sigue funcionando sin badges
  }, [desde, hasta]);
  useEffect(() => { recargar(); }, [recargar]);
  return { conteo, recargar };
}

// ---------------------------------------------------------------------------
// Badge / botón para la celda de la grilla
// ---------------------------------------------------------------------------
export function BotonBitacora({ info, onClick, atenuado }) {
  const n = info?.n || 0;
  const hayParadaNoPlan = info?.categorias?.has('PARADA_NO_PLANIFICADA');
  return (
    <span
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      title={n ? `${n} evento(s), ${info.minutos} min — clic para ver o agregar`
        : atenuado ? 'Día futuro' : 'Registrar evento en la bitácora'}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 2,
        minWidth: 18, height: 18, padding: '0 4px', borderRadius: 9, fontSize: 10, fontWeight: 700,
        cursor: 'pointer', userSelect: 'none',
        opacity: atenuado && !n ? 0.35 : 1,
        background: n ? (hayParadaNoPlan ? C.dangerLt : C.tealLt) : 'transparent',
        color: n ? (hayParadaNoPlan ? '#A32D2D' : C.tealMid) : C.textMuted,
        border: `1px solid ${n ? (hayParadaNoPlan ? C.danger : C.teal) : C.border}`,
      }}
    >
      {n ? n : '+'}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Pie de celda: minutos de detención del día (junto a la ocupación sugerida/aprobada)
// ---------------------------------------------------------------------------
export function MinutosDetencion({ info }) {
  if (!info || (!info.min_detencion && !info.min_sin_programa)) return null;
  const rojo = info.categorias?.has('PARADA_NO_PLANIFICADA');
  return (
    <div style={{ fontSize: 10, lineHeight: '13px', color: rojo ? '#A32D2D' : C.gray, whiteSpace: 'nowrap' }}
      title="Minutos registrados en la bitácora">
      {info.min_detencion > 0 && <span>⏸ {info.min_detencion} min</span>}
      {info.min_sin_programa > 0 && <span style={{ color: '#854F0B', marginLeft: info.min_detencion ? 4 : 0 }}>∅ {info.min_sin_programa} min</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
const FORM_VACIO = { tipo: '', duracion_min: '', sku: '', comentario: '' };

export default function ModalBitacora({ fecha, linea, onClose, onCambio }) {
  const [tipos, setTipos] = useState([]);
  const [eventos, setEventos] = useState([]);
  const [usuario, setUsuario] = useState(leerUsuario());
  const [form, setForm] = useState(FORM_VACIO);
  const [msg, setMsg] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const futuro = fecha > hoyLocal();

  const tiposDisp = useMemo(
    () => (futuro ? tipos.filter((t) => CATEGORIAS_FUTURAS.includes(t.categoria)) : tipos),
    [tipos, futuro]);
  const tipoSel = useMemo(() => tipos.find((t) => t.codigo === form.tipo), [tipos, form.tipo]);
  const pideDuracion = tipoSel ? tipoSel.requiere_duracion : true;
  const totalMin = eventos.reduce((a, e) => a + (e.duracion_min || 0), 0);

  const cargarEventos = useCallback(() => {
    axios.get(`${API}/bitacora/eventos`, { params: { desde: fecha, hasta: fecha, linea } })
      .then(({ data }) => setEventos(data.eventos || []))
      .catch((e) => setMsg({ tipo: 'error', texto: detalleError(e, 'No se pudieron cargar los eventos del día.') }));
  }, [fecha, linea]);

  useEffect(() => {
    axios.get(`${API}/bitacora/catalogos`)
      .then(({ data }) => setTipos(data.tipos || []))
      .catch(() => setMsg({ tipo: 'error', texto: 'No se pudieron cargar los tipos de evento.' }));
    cargarEventos();
  }, [cargarEventos]);

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  const set = (campo) => (e) => setForm({ ...form, [campo]: e.target.value });

  const guardar = async () => {
    setMsg(null);
    if (!usuario.trim()) return setMsg({ tipo: 'error', texto: 'Indica quién registra el evento.' });
    if (!form.tipo) return setMsg({ tipo: 'error', texto: 'Selecciona el tipo de evento.' });
    if (pideDuracion && !form.duracion_min) return setMsg({ tipo: 'error', texto: 'Este tipo de evento requiere duración en minutos.' });
    setGuardando(true);
    try {
      await axios.post(`${API}/bitacora/eventos`, {
        fecha, linea, tipo: form.tipo, registrado_por: usuario.trim(),
        duracion_min: pideDuracion && form.duracion_min ? Number(form.duracion_min) : null,
        sku: form.sku || null, comentario: form.comentario || null,
      });
      guardarUsuario(usuario.trim());
      setForm(FORM_VACIO);
      setMsg({ tipo: 'ok', texto: 'Evento registrado.' });
      cargarEventos();
      if (onCambio) onCambio();
    } catch (e) {
      setMsg({ tipo: 'error', texto: detalleError(e, 'No se pudo registrar el evento.') });
    } finally {
      setGuardando(false);
    }
  };

  const anular = async (ev) => {
    if (!usuario.trim()) return setMsg({ tipo: 'error', texto: 'Indica quién anula el evento.' });
    if (!window.confirm(`¿Anular "${ev.tipo_nombre}" (${ev.duracion_min ?? 0} min)?`)) return;
    try {
      await axios.post(`${API}/bitacora/eventos/${ev.id}/anular`, { anulado_por: usuario.trim() });
      setMsg({ tipo: 'ok', texto: 'Evento anulado.' });
      cargarEventos();
      if (onCambio) onCambio();
    } catch (e) {
      setMsg({ tipo: 'error', texto: detalleError(e, 'No se pudo anular el evento.') });
    }
  };

  const input = { padding: '6px 8px', border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, width: '100%', boxSizing: 'border-box' };
  const label = { display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: C.gray };

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(44,44,42,0.45)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: '#fff', borderRadius: 12, padding: 20, width: 'min(640px, 100%)', maxHeight: '90vh',
        overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', fontFamily: 'Arial,sans-serif', color: C.text,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 11, color: C.textMuted, textTransform: 'uppercase', letterSpacing: 0.4 }}>Bitácora</div>
            <div style={{ fontSize: 17, fontWeight: 700 }}>{linea}</div>
            <div style={{ fontSize: 13, color: C.gray, textTransform: 'capitalize' }}>{tituloFecha(fecha)}</div>
          </div>
          <span onClick={onClose} title="Cerrar (Esc)" style={{ cursor: 'pointer', fontSize: 20, color: C.gray }}>✕</span>
        </div>

        {/* Eventos del día */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>
            Eventos del día {eventos.length > 0 && <span style={{ fontWeight: 400, color: C.gray }}>· {eventos.length} evento(s), {totalMin} min</span>}
          </div>
          {eventos.length === 0 ? (
            <div style={{ fontSize: 12, color: C.textMuted, background: C.grayLt, borderRadius: 8, padding: '8px 10px' }}>
              No hay eventos registrados para esta línea en este día.
            </div>
          ) : eventos.map((ev) => (
            <div key={ev.id} style={{
              display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 10px', marginBottom: 6,
              borderRadius: 8, border: `1px solid ${C.grayLt}`, borderLeft: `4px solid ${COLOR_CATEGORIA[ev.categoria] || C.gray}`,
            }}>
              <div style={{ flex: 1, fontSize: 12 }}>
                <div><strong>{ev.tipo_nombre}</strong>{ev.duracion_min ? ` · ${ev.duracion_min} min` : ''}{ev.sku ? ` · SKU ${ev.sku}` : ''}</div>
                {ev.comentario && <div style={{ color: C.gray, marginTop: 2 }}>{ev.comentario}</div>}
                <div style={{ color: C.textMuted, marginTop: 2 }}>Registrado por {ev.registrado_por}</div>
              </div>
              <span onClick={() => anular(ev)} style={{
                fontSize: 11, cursor: 'pointer', color: C.gray, border: `1px solid ${C.border}`, borderRadius: 4, padding: '2px 8px',
              }}>Anular</span>
            </div>
          ))}
        </div>

        {/* Formulario */}
        {(
          <div style={{ borderTop: `1px solid ${C.grayLt}`, paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{futuro ? 'Anotar evento planificado' : 'Registrar evento'}</div>
            {futuro && (
              <div style={{ fontSize: 12, background: C.amberLt, color: '#633806', borderRadius: 8, padding: '6px 10px', marginBottom: 10 }}>
                Día futuro: solo se pueden anotar paradas planificadas (mantención, limpieza, cambio de formato) y
                línea disponible sin programa. Si el plan cambia, anúlalo.
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label style={label}>Registrado por
                <input style={input} value={usuario} onChange={(e) => setUsuario(e.target.value)} placeholder="Nombre y apellido" />
              </label>
              <label style={label}>Tipo de evento
                <select style={input} value={form.tipo} onChange={set('tipo')}>
                  <option value="">Seleccionar…</option>
                  {tiposDisp.map((t) => <option key={t.codigo} value={t.codigo}>{t.nombre}</option>)}
                </select>
              </label>
              {pideDuracion && (
                <label style={label}>Duración (min)
                  <input style={input} type="number" min="1" max="1440" value={form.duracion_min} onChange={set('duracion_min')} />
                </label>
              )}
              <label style={label}>SKU (opcional)
                <input style={input} value={form.sku} onChange={set('sku')} />
              </label>
            </div>
            <label style={{ ...label, marginTop: 10 }}>Comentario (opcional)
              <textarea style={{ ...input, minHeight: 50 }} value={form.comentario} onChange={set('comentario')} />
            </label>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
              <button onClick={onClose} style={{ padding: '7px 14px', border: `1px solid ${C.border}`, borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 13 }}>Cerrar</button>
              <button onClick={guardar} disabled={guardando} style={{ padding: '7px 16px', border: 'none', borderRadius: 6, background: C.teal, color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
                {guardando ? 'Registrando…' : 'Registrar evento'}
              </button>
            </div>
          </div>
        )}
        {msg && <div style={{ marginTop: 10, fontSize: 12, color: msg.tipo === 'error' ? '#A32D2D' : C.tealMid }}>{msg.texto}</div>}
      </div>
    </div>
  );
}
