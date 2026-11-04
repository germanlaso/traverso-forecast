import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

// Bitácora de eventos diarios por línea (menú Control).
// "Registrado por" se recuerda en este navegador hasta tener perfil de usuario (Entra ID).

const API = process.env.REACT_APP_API_BASE || '';
const KEY_USUARIO = 'bitacora_registrado_por';

const hoyLocal = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

const leerUsuario = () => {
  try { return localStorage.getItem(KEY_USUARIO) || ''; } catch { return ''; }
};
const guardarUsuario = (v) => {
  try { localStorage.setItem(KEY_USUARIO, v); } catch { /* sin storage: no pasa nada */ }
};

const FORM_VACIO = { linea: '', tipo: '', duracion_min: '', sku: '', comentario: '' };

const estilos = {
  wrap: { padding: 16, maxWidth: 1100 },
  card: { border: '1px solid #d0d7de', borderRadius: 6, padding: 16, marginBottom: 16, background: '#fff' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 },
  label: { display: 'flex', flexDirection: 'column', fontSize: 13, gap: 4 },
  input: { padding: '6px 8px', border: '1px solid #c7cdd4', borderRadius: 4, fontSize: 14 },
  btn: { padding: '8px 16px', border: 'none', borderRadius: 4, background: '#1f6feb', color: '#fff', cursor: 'pointer', fontSize: 14 },
  btnSec: { padding: '4px 10px', border: '1px solid #c7cdd4', borderRadius: 4, background: '#fff', cursor: 'pointer', fontSize: 12 },
  tabla: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: { textAlign: 'left', borderBottom: '2px solid #d0d7de', padding: '6px 8px', whiteSpace: 'nowrap' },
  td: { borderBottom: '1px solid #eaeef2', padding: '6px 8px', verticalAlign: 'top' },
  error: { color: '#b42318', fontSize: 13, marginTop: 8 },
  ok: { color: '#1a7f37', fontSize: 13, marginTop: 8 },
};

export default function BitacoraEventos() {
  const [catalogos, setCatalogos] = useState({ tipos: [], lineas: [] });
  const [usuario, setUsuario] = useState(leerUsuario());
  const [fecha, setFecha] = useState(hoyLocal());
  const [form, setForm] = useState(FORM_VACIO);
  const [eventos, setEventos] = useState([]);
  const [filtroLinea, setFiltroLinea] = useState('');
  const [msg, setMsg] = useState(null);
  const [guardando, setGuardando] = useState(false);

  const tipoSel = useMemo(
    () => catalogos.tipos.find((t) => t.codigo === form.tipo),
    [catalogos.tipos, form.tipo]
  );
  const pideDuracion = tipoSel ? tipoSel.requiere_duracion : true;

  const cargarEventos = async () => {
    try {
      const params = filtroLinea ? { linea: filtroLinea } : {};
      const { data } = await axios.get(`${API}/bitacora/eventos`, { params });
      setEventos(data.eventos || []);
    } catch (e) {
      setMsg({ tipo: 'error', texto: 'No se pudieron cargar los eventos. Revisa la conexión con el servidor.' });
    }
  };

  useEffect(() => {
    axios.get(`${API}/bitacora/catalogos`)
      .then(({ data }) => setCatalogos(data))
      .catch(() => setMsg({ tipo: 'error', texto: 'No se pudieron cargar líneas y tipos de evento.' }));
  }, []);

  useEffect(() => { cargarEventos(); /* eslint-disable-next-line */ }, [filtroLinea]);

  const set = (campo) => (e) => setForm({ ...form, [campo]: e.target.value });

  const guardar = async () => {
    setMsg(null);
    if (!usuario.trim()) return setMsg({ tipo: 'error', texto: 'Indica quién registra el evento.' });
    if (!form.linea || !form.tipo) return setMsg({ tipo: 'error', texto: 'Selecciona línea y tipo de evento.' });
    if (pideDuracion && !form.duracion_min) return setMsg({ tipo: 'error', texto: 'Este tipo de evento requiere duración en minutos.' });

    setGuardando(true);
    try {
      await axios.post(`${API}/bitacora/eventos`, {
        fecha,
        linea: form.linea,
        tipo: form.tipo,
        registrado_por: usuario.trim(),
        duracion_min: pideDuracion && form.duracion_min ? Number(form.duracion_min) : null,
        sku: form.sku || null,
        comentario: form.comentario || null,
      });
      guardarUsuario(usuario.trim());
      setForm({ ...FORM_VACIO, linea: form.linea });   // mantiene la línea para cargas seguidas
      setMsg({ tipo: 'ok', texto: 'Evento registrado.' });
      cargarEventos();
    } catch (e) {
      const detalle = e?.response?.data?.detail;
      setMsg({ tipo: 'error', texto: typeof detalle === 'string' ? detalle : 'No se pudo registrar el evento.' });
    } finally {
      setGuardando(false);
    }
  };

  const anular = async (ev) => {
    if (!usuario.trim()) return setMsg({ tipo: 'error', texto: 'Indica quién anula el evento (campo "Registrado por").' });
    if (!window.confirm(`¿Anular el evento de ${ev.linea} del ${ev.fecha} (${ev.tipo_nombre})?`)) return;
    try {
      await axios.post(`${API}/bitacora/eventos/${ev.id}/anular`, { anulado_por: usuario.trim() });
      setMsg({ tipo: 'ok', texto: 'Evento anulado.' });
      cargarEventos();
    } catch (e) {
      const detalle = e?.response?.data?.detail;
      setMsg({ tipo: 'error', texto: typeof detalle === 'string' ? detalle : 'No se pudo anular el evento.' });
    }
  };

  return (
    <div style={estilos.wrap}>
      <h2 style={{ marginTop: 0 }}>Bitácora de eventos por línea</h2>

      <div style={estilos.card}>
        <div style={estilos.grid}>
          <label style={estilos.label}>Registrado por
            <input style={estilos.input} value={usuario} onChange={(e) => setUsuario(e.target.value)} placeholder="Nombre y apellido" />
          </label>
          <label style={estilos.label}>Fecha
            <input style={estilos.input} type="date" value={fecha} max={hoyLocal()} onChange={(e) => setFecha(e.target.value)} />
          </label>
          <label style={estilos.label}>Línea
            <select style={estilos.input} value={form.linea} onChange={set('linea')}>
              <option value="">Seleccionar…</option>
              {catalogos.lineas.map((l) => <option key={l.codigo} value={l.codigo}>{l.nombre && l.nombre !== l.codigo ? `${l.codigo} · ${l.nombre}` : l.codigo}</option>)}
            </select>
          </label>
          <label style={estilos.label}>Tipo de evento
            <select style={estilos.input} value={form.tipo} onChange={set('tipo')}>
              <option value="">Seleccionar…</option>
              {catalogos.tipos.map((t) => <option key={t.codigo} value={t.codigo}>{t.nombre}</option>)}
            </select>
          </label>
          {pideDuracion && (
            <label style={estilos.label}>Duración (min)
              <input style={estilos.input} type="number" min="1" max="1440" value={form.duracion_min} onChange={set('duracion_min')} />
            </label>
          )}
          <label style={estilos.label}>SKU (opcional)
            <input style={estilos.input} value={form.sku} onChange={set('sku')} />
          </label>
        </div>
        <label style={{ ...estilos.label, marginTop: 12 }}>Comentario (opcional)
          <textarea style={{ ...estilos.input, minHeight: 50 }} value={form.comentario} onChange={set('comentario')} />
        </label>
        <div style={{ marginTop: 12 }}>
          <button style={estilos.btn} onClick={guardar} disabled={guardando}>
            {guardando ? 'Registrando…' : 'Registrar evento'}
          </button>
        </div>
        {msg && <div style={msg.tipo === 'error' ? estilos.error : estilos.ok}>{msg.texto}</div>}
      </div>

      <div style={estilos.card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <strong>Últimos 7 días</strong>
          <select style={estilos.input} value={filtroLinea} onChange={(e) => setFiltroLinea(e.target.value)}>
            <option value="">Todas las líneas</option>
            {catalogos.lineas.map((l) => <option key={l.codigo} value={l.codigo}>{l.nombre && l.nombre !== l.codigo ? `${l.codigo} · ${l.nombre}` : l.codigo}</option>)}
          </select>
        </div>
        {eventos.length === 0 ? (
          <p style={{ color: '#57606a', fontSize: 13 }}>No hay eventos registrados en este período.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={estilos.tabla}>
              <thead>
                <tr>
                  {['Fecha', 'Línea', 'Tipo', 'Min', 'SKU', 'Comentario', 'Registrado por', ''].map((h) => (
                    <th key={h} style={estilos.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {eventos.map((ev) => (
                  <tr key={ev.id}>
                    <td style={estilos.td}>{ev.fecha}</td>
                    <td style={estilos.td}>{ev.linea}</td>
                    <td style={estilos.td}>{ev.tipo_nombre}</td>
                    <td style={estilos.td}>{ev.duracion_min ?? ''}</td>
                    <td style={estilos.td}>{ev.sku ?? ''}</td>
                    <td style={estilos.td}>{ev.comentario ?? ''}</td>
                    <td style={estilos.td}>{ev.registrado_por}</td>
                    <td style={estilos.td}><button style={estilos.btnSec} onClick={() => anular(ev)}>Anular</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
