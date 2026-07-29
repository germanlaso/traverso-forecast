// campanaBandas.js — Bandas de campaña de granel para los gráficos de inventario.
//
// Marca en el gráfico las semanas segun el granel activo de la planta, de modo que
// se vea POR QUE aparece un hueco de stock: un SKU de mostaza no puede envasarse en
// una semana de ketchup, y al revés.
//
// Se usa en StockDiario (pestaña) y ProyeccionModal (modal), que comparten el mismo
// endpoint de proyección pero tienen ejes X con nombres de clave distintos.
//
// Uso:
//   const { calendario, grupoDeSku, listo } = useCampanas();
//   const bandas = bandasCampana({ calendario, grupo: grupoDeSku(sku), puntos });
//   ...
//   <ComposedChart data={serie}>
//     {renderBandas(bandas)}          {/* ANTES de las series, para quedar de fondo */}
//     ...
//   </ComposedChart>
//
// `puntos` = [{ iso: "2026-08-03", eje: "08-03" }, ...] en el mismo orden del eje X.
// El eje de estos gráficos es CATEGORICO (strings MM-DD), asi que x1/x2 tienen que
// coincidir EXACTO con valores presentes en los datos: por eso las bandas se recortan
// al primer y ultimo punto disponible de cada semana.

import React, { useEffect, useState } from "react";
import { ReferenceArea } from "recharts";

const API = "";

// Mismos colores que el tablero de Campañas y la paleta del dashboard.
export const COLOR_MODO = {
  ketchup: { fill: "#E24B4A", label: "ketchup" },
  mostaza: { fill: "#EF9F27", label: "mostaza" },
};

/* ── Hook: calendario + mapa sku -> grupo de granel ────────────────────────
   Una sola carga por montaje. Si los endpoints no estan disponibles (por ejemplo
   el backend todavia no expone /campanas), devuelve vacio y los graficos se
   dibujan igual que antes: la feature es aditiva, nunca rompe la vista.        */
export function useCampanas() {
  const [calendario, setCalendario] = useState([]);
  const [mapaGrupo, setMapaGrupo] = useState({});
  const [listo, setListo] = useState(false);

  useEffect(() => {
    let vivo = true;
    Promise.all([
      fetch(`${API}/campanas/calendario?semanas=14`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${API}/campanas/skus`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([cal, sk]) => {
        if (!vivo) return;
        setCalendario((cal && cal.calendario) || []);
        const m = {};
        const grupos = (sk && sk.grupos) || {};
        Object.keys(grupos).forEach((g) => {
          if (!COLOR_MODO[g]) return;          // ignora "(independiente)"
          grupos[g].forEach((x) => { m[String(x.sku)] = g; });
        });
        setMapaGrupo(m);
      })
      .catch(() => { /* silencioso: sin campañas, sin bandas */ })
      .finally(() => { if (vivo) setListo(true); });
    return () => { vivo = false; };
  }, []);

  const grupoDeSku = (sku) => mapaGrupo[String(sku)] || "";
  return { calendario, grupoDeSku, listo };
}

/* ── Calculo de bandas ─────────────────────────────────────────────────────
   Devuelve [{ x1, x2, modo, bloquea }] donde `bloquea` indica que en esa semana
   este SKU NO puede envasarse (el granel activo es de otro grupo).

   Si `grupo` viene vacio (SKU independiente, 209 de 250) no devuelve nada: las
   bandas serian ruido porque su produccion no depende del granel.               */
export function bandasCampana({ calendario, grupo, puntos }) {
  if (!grupo || !COLOR_MODO[grupo]) return [];
  if (!Array.isArray(calendario) || !calendario.length) return [];
  if (!Array.isArray(puntos) || !puntos.length) return [];

  const out = [];
  calendario.forEach((c) => {
    const modo = (c.modo || "").toLowerCase();
    if (!COLOR_MODO[modo]) return;                    // semana sin granel: no se marca
    const ini = c.semana;                             // lunes ISO
    const fin = sumaDias(ini, 6);                     // domingo
    const dentro = puntos.filter((p) => p.iso >= ini && p.iso <= fin);
    if (!dentro.length) return;                       // semana fuera del horizonte del grafico
    out.push({
      x1: dentro[0].eje,
      x2: dentro[dentro.length - 1].eje,
      modo,
      bloquea: modo !== grupo,
      fijado: !!c.fijado,
    });
  });
  return out;
}

function sumaDias(iso, n) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

/* ── Render ────────────────────────────────────────────────────────────────
   Se devuelve un array de <ReferenceArea> (no un componente que los envuelva):
   recharts necesita reconocer los hijos directos del grafico.

   Las semanas que BLOQUEAN al SKU se pintan mas marcadas — son las que explican
   el hueco de stock. Las semanas propias quedan casi transparentes.             */
export function renderBandas(bandas) {
  if (!bandas || !bandas.length) return null;
  return bandas.map((b, i) => (
    <ReferenceArea
      key={`campana-${i}`}
      x1={b.x1}
      x2={b.x2}
      fill={COLOR_MODO[b.modo].fill}
      fillOpacity={b.bloquea ? 0.16 : 0.05}
      ifOverflow="extendDomain"
      label={{
        value: b.bloquea ? `sin ${invertir(b.modo)}` : COLOR_MODO[b.modo].label,
        position: "insideTop",
        fontSize: 9,
        fill: COLOR_MODO[b.modo].fill,
        opacity: b.bloquea ? 0.95 : 0.5,
      }}
    />
  ));
}

function invertir(modo) {
  return modo === "ketchup" ? "mostaza" : "ketchup";
}

/* ── Leyenda ───────────────────────────────────────────────────────────────
   Nota corta para poner debajo del grafico. Aclara que el calendario es el
   PREVISTO: si el plan vigente se genero sin campaña, las bandas son referencia.  */
export function NotaCampana({ grupo, hayBandas }) {
  if (!grupo || !hayBandas) return null;
  return (
    <div style={{ fontSize: 10.5, color: "#888780", marginTop: 6 }}>
      Franjas = granel de salsa previsto por semana. Las más marcadas son semanas en
      que <strong>este SKU no puede envasarse</strong> (se fabrica el otro granel).
      El calendario se administra en la pestaña <strong>Campañas</strong>.
    </div>
  );
}
