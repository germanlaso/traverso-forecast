# Brief Gerente — RESUELTO (05/05/2026)

> **Documento histórico**. La conversación con el Gerente ya se hizo. Quedan registradas las decisiones para referencia futura. Útil si en algún momento alguien pregunta "¿por qué se decidió X?".

---

## Resumen del problema presentado

Después de cargar parámetros V4, el optimizador generaba planes con Sachetera al 0% de uso, 151 quiebres y objective ×15 vs F1 baseline. La causa raíz cuantificada fue:

- Sachetera capacidad nominal: 1,055 u/hr × 9 hrs = 9,500 u/día.
- Factor_velocidad Mostaza/Ketchup en Sachetera: 0.8 → cap_día_efectiva = 7,600 u.
- Setup primer día: -422 u → cap_día_neta = 7,178 u.
- batch_min_u Mostaza/Ketchup = 9,500.

Conclusión: batch_min > cap_día_efectiva → infactible producir un batch en un día. Solver elige no producir.

Test diagnóstico ejecutado (UPDATE temporal a batch_min=3000, regenerar /plan, REVERT):
- Sachetera 0% → 68%.
- Quiebres 151 → 0.
- Objective -78%.
- 109 OFTs nuevas para Mostaza+Ketchup.

---

## Decisiones tomadas por el Gerente

### D1 — `batch_min_u = 9,500` se mantiene

**Decisión**: el batch mínimo operativo real para Mostaza/Ketchup en Sachetera es 9,500 unidades (950 cajas). No se baja.

**Implicación aceptada**: Sachetera operará al 100% durante varios días seguidos cuando produzca Mostaza/Ketchup. Cero margen para imprevistos.

**Consecuencia técnica**: registra observación O12 — Sachetera con margen cero por diseño operativo. Decisión deliberada del negocio, no bug del software.

### D2 — `factor_velocidad = 1.0` para Mostaza/Ketchup en Sachetera

**Decisión**: la velocidad nominal 1,055 u/hr **ya incluye** la merma específica del producto. El factor 0.8 cargado en V4 era doble-conteo.

**Implicación**: cap_día_efectiva pasa de 7,600 a 9,500 unidades. Coincide exactamente con batch_min, lo que es marginalmente factible **si y solo si** se aplica también D3.

**Cambio en BD**:
```sql
UPDATE mrp_sku_lineas
SET factor_velocidad = 1.0
WHERE sku IN ('250010105', '260010105') AND linea = 'Sachetera';
```

**Consecuencia técnica**: cierra observación O2 (sospecha de doble-conteo abierta desde el domingo).

### D3 — REGLA R12: el primer SKU del día NO paga setup, en TODAS las líneas

**Decisión**: en cualquier línea, en cualquier día, el primer SKU programado no paga setup. Solo el segundo SKU en adelante (cambios intra-día) paga setup.

**Lógica del Gerente**: la limpieza/preparación de la línea para el primer SKU del día se hace al cierre del día anterior, después del cierre operativo de la línea. Es trabajo extra-jornada (turno de limpieza/mantenimiento) y NO consume horas productivas del día siguiente.

**Implicación**: cambio de modelo, no solo de parámetros. Requiere modificación quirúrgica en `optimizer.py` para reemplazar la detección de `inicio[d,k,l]` por una restricción agregada: `Σ_k inicio[d,k,l] ≥ Σ_k asig[d,k,l] - 1`.

**Consecuencia técnica**: probablemente reduce setups en un 50-70%, libera capacidad significativa especialmente en líneas con cambios frecuentes de SKU. Combinado con D2, hace Sachetera factible sin tener que bajar batch_min.

**Detalle técnico de implementación**: ver `R12_PRIMER_SETUP_GRATIS.md`.

---

## Por qué la combinación D1 + D2 + D3 funciona

| Caso | cap_día_efectiva | Necesario para batch | ¿Factible? |
|---|---|---|---|
| V4 original (factor=0.8, primer setup pago) | 9,500 × 0.8 - 422 = 7,178 | 9,500 | ❌ |
| Solo D2 (factor=1.0, primer setup pago) | 9,500 × 1.0 - 422 = 9,078 | 9,500 | ❌ marginal |
| **D2 + D3 (factor=1.0, primer setup gratis)** | **9,500 × 1.0 - 0 = 9,500** | **9,500** | **✅ exactamente al límite** |

Esto es **margen cero por diseño** (registra O12). El Gerente acepta esta restricción operacional porque corresponde a la realidad de planta.

Para días con cambio de SKU intra-día, ese cambio sí paga setup, lo que resta capacidad — pero el Gerente acepta que esos días no se va a poder cumplir el batch completo, y asume que la planificación va a tender a corridas largas (3+ días consecutivos del mismo SKU).

---

## Consecuencias para la planificación esperada

Después de aplicar las 3 decisiones, el optimizador debería tender a:

- **Corridas largas en Sachetera**: 3-5 días consecutivos del mismo SKU para amortizar el "costo cero" del primer día y maximizar producción semanal.
- **Cambios infrecuentes**: solo cuando hay urgencia operativa.
- **Bajo_ss tolerable**: ciertas semanas con margen apretado por O12, pero quiebres = 0.
- **Mejor uso de las otras líneas**: la R12 también aplica a L1Pet LV y L1Pet A, lo que puede bajar setups globales en 50-70%.

---

## Asuntos menores también discutidos con el Gerente

### SKU 121010290 (Jugo Limón Traverso 30×500 PET) — `ss_dias=8`

[A completar si se discutió. Si no, queda como tema pendiente.]

### Revisión sistemática de SS_dias y batch_min de los otros 8 SKUs

[A completar si se agendó otra reunión para esto.]

---

## Material entregado al Gerente (referencia)

En la conversación se mostraron:
- Tabla cuantitativa de capacidad real de Sachetera.
- Tabla con resultado del test diagnóstico B' (con números concretos).
- Las 3 opciones de fix (A: factor, B: batch_min, C: capacidad).

---

## Firma de cierre del documento

Documento generado al cierre de la sesión 05/05/2026.

Decisiones del Gerente registradas y validadas. Próximo paso: implementación técnica en próxima sesión (ver `MENSAJE_INICIO_CLAUDE_CODE.md`).
