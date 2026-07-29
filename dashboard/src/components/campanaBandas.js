// campanaBandas.js — Bandas de campana en los graficos de inventario.
//
// Marca en el grafico las semanas segun las campanas activas, para que se vea POR QUE
// aparece un hueco de stock:
//   · Granel (planta): un SKU de mostaza no puede envasarse en semana de ketchup.
//   · Formato (linea): un SKU de 500 ml no puede envasarse en semana de 1000 ml,
//     pero SOLO si el SKU corre en esa linea.
//
// Generico sobre mrp_campana_reglas: al agregar una regla nueva (otra linea, otra
// dimension) las bandas aparecen sin tocar este archivo.
//
// Uso:
//   const { reglas, cals, infoDe, listo } = useCampanas();
//   const bandas = bandasCampana({ reglas, cals, info: infoDe(sku), puntos });
//   <ComposedChart data={serie}>
//     {renderBandas(bandas)}      {/* ANTES de las series, para quedar de fondo */}
//
// `puntos` = [{ iso: "2026-08-03", eje: "08-03" }, ...] en el orden del eje X.
// El eje es CATEGORICO (strings MM-DD): x1/x2 tienen que coincidir EXACTO con valores
// presentes en los datos, por eso cada banda se recorta al primer y ultimo punto de
// su semana que exista en el grafico.

import React, { useEffect, useState } from "react";
import { ReferenceArea } from "recharts";

const API = "";

export const COLOR_MODO = {
  ketchup: "#E24B4A",
  mostaza: "#EF9F27",
  "1000": "#378ADD",
  "500": "#1D9E75",
};
const colorDe = (m) => COLOR_MODO[m] || "#B4B2A9";

/* ── Hook: reglas + calendarios + info por SKU ─────────────────────────────
   Una carga por montaje. Si /campanas no esta disponible devuelve vacio y los
   graficos se dibujan igual que antes: la feature es aditiva, nunca rompe.     */
export function useCampanas() {
  const [reglas, setReglas] = useState([]);
  const [cals, setCals] = useState({});
  const [skuInfo, setSkuInfo] = useState({});
  const [listo, setListo] = useState(false);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const rr = await fetch(`${API}/campanas/reglas`).then((r) => (r.ok ? r.json() : null));
        const rs = (rr && rr.reglas) || [];
        const pares = await Promise.all(rs.map((r) =>
          fetch(`${API}/campanas/calendario?recurso=${encodeURIComponent(r.recurso)}&semanas=14`)
            .then((x) => (x.ok ? x.json() : null))
            .then((j) => [r.recurso, (j && j.calendario) || []])
        ));
        const sk = await fetch(`${API}/campanas/skus`).then((r) => (r.ok ? r.json() : null));
        if (!vivo) return;
        setReglas(rs);
        setCals(Object.fromEntries(pares));
        setSkuInfo((sk && sk.sku_info) || {});
      } catch (e) {
        /* silencioso: sin campanas, sin bandas */
      } finally {
        if (vivo) setListo(true);
      }
    })();
    return () => { vivo = false; };
  }, []);

  const infoDe = (sku) => skuInfo[String(sku)] || null;
  return { reglas, cals, infoDe, listo };
}

/* ── Calculo de bandas ─────────────────────────────────────────────────────
   Devuelve [{ x1, x2, modo, bloquea, dimension, etiqueta }].
   Solo se generan bandas de las reglas que AFECTAN a este SKU:
     · granel_grupo -> el SKU tiene granel_grupo no vacio.
     · formato      -> el SKU corre en la linea de la regla y su formato esta en modos.
   Para los SKU no afectados no se dibuja nada (serian ruido).                   */
export function bandasCampana({ reglas, cals, info, puntos }) {
  if (!info || !Array.isArray(reglas) || !reglas.length) return [];
  if (!Array.isArray(puntos) || !puntos.length) return [];

  const out = [];
  reglas.forEach((r) => {
    const dim = r.dimension || "";
    const modos = (r.modos || []).map(String);
    let propio = "";

    if (dim === "granel_grupo") {
      propio = (info.granel_grupo || "").toLowerCase();
      if (!propio) return;                            // independiente: sin bandas
    } else if (dim === "formato") {
      if (!r.linea) return;
      if (!(info.lineas || []).includes(r.linea)) return;  // no corre en esa linea
      propio = String(info.formato || "");
      if (!modos.includes(propio)) return;            // formato ajeno a la regla
    } else {
      return;
    }

    (cals[r.recurso] || []).forEach((c) => {
      const modo = String(c.modo || "");
      if (!modo || !modos.includes(modo)) return;     // semana libre: no se marca
      const fin = sumaDias(c.semana, 6);
      const dentro = puntos.filter((p) => p.iso >= c.semana && p.iso <= fin);
      if (!dentro.length) return;                     // semana fuera del grafico
      const bloquea = modo !== propio;
      out.push({
        x1: dentro[0].eje,
        x2: dentro[dentro.length - 1].eje,
        modo,
        bloquea,
        dimension: dim,
        etiqueta: bloquea
          ? (dim === "formato" ? `linea en ${modo} ml` : `planta en ${modo}`)
          : (dim === "formato" ? `${modo} ml` : modo),
      });
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
   Array de <ReferenceArea> (no un componente que los envuelva): recharts necesita
   reconocer los hijos directos del grafico.

   Las semanas que BLOQUEAN al SKU van mas marcadas — son las que explican el hueco.
   Ambas etiquetas van arriba; la de formato con un dy para no solaparse.          */
export function renderBandas(bandas) {
  if (!bandas || !bandas.length) return null;
  return bandas.map((b, i) => (
    <ReferenceArea
      key={`campana-${b.dimension}-${i}`}
      x1={b.x1}
      x2={b.x2}
      fill={colorDe(b.modo)}
      fillOpacity={b.bloquea ? 0.15 : 0.05}
      ifOverflow="extendDomain"
      label={{
        value: b.etiqueta,
        // Ambas arriba. El formato baja unos px para no pisar la del granel
        // cuando un SKU esta afectado por las dos reglas a la vez.
        position: "insideTop",
        dy: b.dimension === "formato" ? 12 : 0,
        fontSize: 9,
        fill: colorDe(b.modo),
        opacity: b.bloquea ? 0.95 : 0.5,
      }}
    />
  ));
}

/* ── Leyenda ───────────────────────────────────────────────────────────────  */
export function NotaCampana({ hayBandas }) {
  if (!hayBandas) return null;
  return (
    <div style={{ fontSize: 10.5, color: "#888780", marginTop: 6 }}>
      Franjas = campaña prevista por semana (granel de planta y formato de línea).
      Las más marcadas son semanas en que <strong>este SKU no puede
      envasarse</strong>. El calendario se administra en la pestaña <strong>Campañas</strong>.
    </div>
  );
}
