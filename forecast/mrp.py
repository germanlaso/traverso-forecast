"""
mrp.py — Motor de planificación MRP (Material Requirements Planning)
Traverso S.A. · Sistema de Planificación de Producción
Etapa 2: Plan de producción / abastecimiento

Lógica central:
  Necesidad bruta     = Forecast semanal (cajas)
  Stock seguridad     = Días cobertura × Demanda diaria promedio
  Necesidad neta      = Necesidad bruta + Stock seguridad - Inventario disponible - Órdenes en tránsito
  Orden sugerida      = Redondeo al múltiplo de batch superior al batch mínimo
  Fecha emisión       = Fecha de necesidad - Lead time

Tipos de orden:
  PRODUCCION  → Orden de Producción (OP)
  MAQUILA     → Orden de Compra a Maquila (OCM)
  IMPORTACION → Orden de Importación (OI)
"""

import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class SKUParams:
    sku:                str
    descripcion:        str
    categoria:          str
    tipo:               str          # PRODUCCION / MAQUILA / IMPORTACION
    unidades_por_caja:  int          # factor conversión unidades → cajas
    lead_time_semanas:  float        # semanas desde emisión hasta disponible
    stock_seguridad_dias: float      # días de cobertura mínima
    batch_minimo:       int          # unidades mínimas por orden
    multiplo_batch:     int          # órdenes múltiplos de este número
    cap_bodega:         int          # máximo unidades en bodega
    compra_minima:      int   = 0    # solo IMPORTACION/MAQUILA
    linea_preferida:    str   = ''   # código de línea preferida
    activo:             bool  = True


@dataclass
class LineaProduccion:
    codigo:         str
    nombre:         str
    turnos_dia:     int
    horas_turno:    float
    dias_semana:    int
    velocidad_u_hr: float            # unidades/hora

    @property
    def horas_disponibles_semana(self) -> float:
        return self.turnos_dia * self.horas_turno * self.dias_semana

    @property
    def capacidad_u_semana(self) -> float:
        return self.horas_disponibles_semana * self.velocidad_u_hr


@dataclass
class SKULinea:
    sku:            str
    linea:          str
    t_cambio_hrs:   float
    preferida:      bool


@dataclass
class OrdenSugerida:
    sku:            str
    descripcion:    str
    tipo:           str              # PRODUCCION / MAQUILA / IMPORTACION
    semana_necesidad: str            # fecha ISO lunes de la semana
    semana_emision:   str            # fecha ISO cuando emitir la orden
    cantidad_cajas:   int            # cajas a producir/comprar
    cantidad_unidades: int           # unidades equivalentes
    linea:          Optional[str]    # línea asignada (solo PRODUCCION)
    motivo:         str              # descripción del cálculo
    alerta:         Optional[str]    # None si todo OK


# ── Carga de parámetros desde Excel ──────────────────────────────────────────

def load_params_from_excel(path: str) -> tuple[dict, dict, list]:
    """
    Lee el Excel de parámetros MRP y retorna:
      - sku_params:  dict[sku → SKUParams]
      - lineas:      dict[codigo → LineaProduccion]
      - sku_lineas:  list[SKULinea]
    """
    xl = pd.ExcelFile(path)

    # ── SKU_PARAMS ────────────────────────────────────────────────────────────
    df_sku = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
    # Renombrar columnas (pueden venir con saltos de línea)
    col_map = {}
    for col in df_sku.columns:
        c = str(col).lower().replace('\n', ' ').strip()
        if 'sku' in c or 'código sap' in c:          col_map[col] = 'sku'
        elif 'descripci' in c:                        col_map[col] = 'descripcion'
        elif 'unidades' in c and 'caja' in c:         col_map[col] = 'unidades_por_caja'
        elif 'categ' in c:                            col_map[col] = 'categoria'
        elif 'tipo' in c:                             col_map[col] = 'tipo'
        elif 'lead' in c:                             col_map[col] = 'lead_time_semanas'
        elif 'seguridad' in c or 'cobertura' in c:   col_map[col] = 'stock_seguridad_dias'
        elif 'batch' in c and 'mín' in c.lower():    col_map[col] = 'batch_minimo'
        elif 'múltiplo' in c or 'multiplo' in c:     col_map[col] = 'multiplo_batch'
        elif 'bodega' in c:                           col_map[col] = 'cap_bodega'
        elif 'compra' in c:                           col_map[col] = 'compra_minima'
        elif 'activo' in c:                           col_map[col] = 'activo'

    df_sku = df_sku.rename(columns=col_map)
    df_sku = df_sku.dropna(subset=['sku', 'lead_time_semanas'])
    df_sku['sku'] = df_sku['sku'].astype(str).str.strip()

    sku_params = {}
    for _, row in df_sku.iterrows():
        try:
            sku_params[row['sku']] = SKUParams(
                sku=row['sku'],
                descripcion=str(row.get('descripcion', '')),
                categoria=str(row.get('categoria', '')),
                tipo=str(row.get('tipo', 'PRODUCCION')).upper().strip(),
                unidades_por_caja=int(row.get('unidades_por_caja', 1)),
                lead_time_semanas=float(row.get('lead_time_semanas', 1)),
                stock_seguridad_dias=float(row.get('stock_seguridad_dias', 7)),
                batch_minimo=int(row.get('batch_minimo', 0)),
                multiplo_batch=int(row.get('multiplo_batch', 1)),
                cap_bodega=int(row.get('cap_bodega', 999999)),
                compra_minima=int(row.get('compra_minima', 0) or 0),
                activo=str(row.get('activo', 'S')).upper().strip() == 'S',
            )
        except Exception as e:
            pass  # SKUs incompletos se ignoran

    # ── LINEAS_PRODUCCION ─────────────────────────────────────────────────────
    df_lin = pd.read_excel(xl, sheet_name='LINEAS_PRODUCCION', header=2)
    col_map2 = {}
    for col in df_lin.columns:
        c = str(col).lower().replace('\n', ' ').strip()
        if 'código' in c and 'línea' in c:           col_map2[col] = 'codigo'
        elif 'nombre' in c:                           col_map2[col] = 'nombre'
        elif 'turnos' in c:                           col_map2[col] = 'turnos_dia'
        elif 'horas' in c and 'turno' in c:           col_map2[col] = 'horas_turno'
        elif 'días' in c or 'dias' in c:              col_map2[col] = 'dias_semana'
        elif 'velocidad' in c:                        col_map2[col] = 'velocidad_u_hr'
        elif 'activa' in c:                           col_map2[col] = 'activa'

    df_lin = df_lin.rename(columns=col_map2)
    df_lin = df_lin.dropna(subset=['codigo', 'velocidad_u_hr'])
    df_lin['codigo'] = df_lin['codigo'].astype(str).str.strip()

    lineas = {}
    for _, row in df_lin.iterrows():
        try:
            if str(row.get('activa', 'S')).upper().strip() != 'S':
                continue
            lineas[row['codigo']] = LineaProduccion(
                codigo=row['codigo'],
                nombre=str(row.get('nombre', '')),
                turnos_dia=int(row.get('turnos_dia', 1)),
                horas_turno=float(row.get('horas_turno', 8)),
                dias_semana=int(row.get('dias_semana', 5)),
                velocidad_u_hr=float(row.get('velocidad_u_hr', 0)),
            )
        except Exception:
            pass

    # ── SKU_LINEA ─────────────────────────────────────────────────────────────
    df_sl = pd.read_excel(xl, sheet_name='SKU_LINEA', header=2)
    col_map3 = {}
    for col in df_sl.columns:
        c = str(col).lower().replace('\n', ' ').strip()
        if 'sku' in c or 'código sap' in c:          col_map3[col] = 'sku'
        elif 'código' in c and 'línea' in c:          col_map3[col] = 'linea'
        elif 'cambio' in c:                           col_map3[col] = 't_cambio_hrs'
        elif 'preferida' in c:                        col_map3[col] = 'preferida'

    df_sl = df_sl.rename(columns=col_map3)
    df_sl = df_sl.dropna(subset=['sku', 'linea'])
    df_sl['sku'] = df_sl['sku'].astype(str).str.strip()

    sku_lineas = []
    for _, row in df_sl.iterrows():
        try:
            sku_lineas.append(SKULinea(
                sku=row['sku'],
                linea=str(row['linea']).strip(),
                t_cambio_hrs=float(row.get('t_cambio_hrs', 0) or 0),
                preferida=str(row.get('preferida', 'N')).upper().strip() == 'S',
            ))
        except Exception:
            pass

    # Asignar línea preferida a sku_params
    for sl in sku_lineas:
        if sl.preferida and sl.sku in sku_params:
            sku_params[sl.sku].linea_preferida = sl.linea

    return sku_params, lineas, sku_lineas


# ── Motor MRP ─────────────────────────────────────────────────────────────────

def calcular_stock_seguridad_cajas(params: SKUParams,
                                    forecast_semanal_cajas: float) -> float:
    """
    Convierte días de cobertura a cajas.
    Stock seguridad (cajas) = demanda_diaria × días_cobertura
    Demanda diaria = forecast_semanal / 7
    """
    demanda_diaria = forecast_semanal_cajas / 7
    return demanda_diaria * params.stock_seguridad_dias


def redondear_a_batch(cantidad_cajas: float, params: SKUParams) -> int:
    """
    Convierte necesidad en cajas a orden en unidades, respetando:
    - Batch mínimo
    - Múltiplo de batch
    """
    # Convertir cajas → unidades para comparar con batch (que está en unidades)
    cantidad_u = cantidad_cajas * params.unidades_por_caja

    if cantidad_u <= 0:
        return 0

    # Aplicar batch mínimo
    cantidad_u = max(cantidad_u, params.batch_minimo)

    # Redondear al múltiplo superior
    if params.multiplo_batch > 1:
        cantidad_u = math.ceil(cantidad_u / params.multiplo_batch) * params.multiplo_batch

    return int(cantidad_u)


def calcular_fecha_emision(fecha_necesidad: datetime,
                            lead_time_semanas: float) -> datetime:
    """Fecha en que debe emitirse la orden para llegar a tiempo."""
    dias_lead = round(lead_time_semanas * 7)
    return fecha_necesidad - timedelta(days=dias_lead)


def generar_plan_sku(params: SKUParams,
                     forecast: list[dict],
                     stock_actual_cajas: float = 0,
                     ordenes_transito_cajas: float = 0,
                     lineas: dict = None,
                     horizonte_semanas: int = 13) -> list[OrdenSugerida]:
    """
    Genera el plan de producción/abastecimiento para un SKU.

    Args:
        params:                  Parámetros del SKU
        forecast:                Lista de dicts con ds (fecha) y yhat (cajas)
        stock_actual_cajas:      Inventario disponible hoy en cajas
        ordenes_transito_cajas:  Órdenes ya emitidas y en camino (cajas)
        lineas:                  Dict de líneas disponibles
        horizonte_semanas:       Semanas a planificar (default 13 = 3 meses)

    Returns:
        Lista de órdenes sugeridas
    """
    if lineas is None:
        lineas = {}

    ordenes = []
    stock_proyectado = stock_actual_cajas + ordenes_transito_cajas
    hoy = datetime.now().date()

    # Filtrar forecast futuro
    forecast_futuro = [
        f for f in forecast
        if pd.to_datetime(f['ds']).date() >= hoy
    ][:horizonte_semanas]

    for f in forecast_futuro:
        fecha_semana = pd.to_datetime(f['ds'])
        yhat_cajas   = max(0, f['yhat'])

        # Stock de seguridad requerido esta semana
        ss_cajas = calcular_stock_seguridad_cajas(params, yhat_cajas)

        # Necesidad neta
        necesidad_neta_cajas = yhat_cajas + ss_cajas - stock_proyectado

        if necesidad_neta_cajas <= 0:
            # Stock suficiente — consumir forecast del proyectado
            stock_proyectado = max(0, stock_proyectado - yhat_cajas)
            continue

        # Calcular orden
        orden_u     = redondear_a_batch(necesidad_neta_cajas, params)
        orden_cajas = math.ceil(orden_u / params.unidades_por_caja)

        # Verificar capacidad de bodega
        alerta = None
        stock_post_orden = stock_proyectado + orden_cajas
        if stock_post_orden * params.unidades_por_caja > params.cap_bodega:
            alerta = f"⚠ Excede capacidad de bodega ({params.cap_bodega:,} u.)"
            # Limitar al máximo de bodega
            max_cajas = params.cap_bodega // params.unidades_por_caja
            orden_cajas = max(0, max_cajas - int(stock_proyectado))
            orden_u = orden_cajas * params.unidades_por_caja

        # Fecha de emisión
        fecha_emision = calcular_fecha_emision(fecha_semana, params.lead_time_semanas)

        # Alerta si ya pasó la fecha de emisión
        if fecha_emision.date() < hoy:
            dias_atraso = (hoy - fecha_emision.date()).days
            alerta = f"🔴 URGENTE: debió emitirse hace {dias_atraso} días"

        # Línea asignada
        linea_asignada = None
        if params.tipo == 'PRODUCCION' and params.linea_preferida:
            linea_asignada = params.linea_preferida
            # Verificar capacidad de línea
            if params.linea_preferida in lineas:
                linea = lineas[params.linea_preferida]
                cap_cajas = linea.capacidad_u_semana / params.unidades_por_caja
                if orden_cajas > cap_cajas:
                    alerta = (alerta or '') + \
                             f" ⚠ Excede capacidad línea {linea.nombre} ({cap_cajas:,.0f} cajas/sem)"

        # Motivo del cálculo (para trazabilidad)
        motivo = (f"Forecast: {yhat_cajas:.0f} cj | SS: {ss_cajas:.0f} cj | "
                  f"Stock proy.: {stock_proyectado:.0f} cj | "
                  f"Nec. neta: {necesidad_neta_cajas:.0f} cj")

        if orden_cajas > 0:
            ordenes.append(OrdenSugerida(
                sku=params.sku,
                descripcion=params.descripcion,
                tipo=params.tipo,
                semana_necesidad=fecha_semana.strftime('%Y-%m-%d'),
                semana_emision=fecha_emision.strftime('%Y-%m-%d'),
                cantidad_cajas=int(orden_cajas),
                cantidad_unidades=int(orden_u),
                linea=linea_asignada,
                motivo=motivo,
                alerta=alerta,
            ))

        # Actualizar stock proyectado
        stock_proyectado = max(0, stock_proyectado + orden_cajas - yhat_cajas)

    return ordenes


def generar_plan_completo(sku_params: dict,
                          forecasts: dict,
                          stocks_actuales: dict = None,
                          lineas: dict = None,
                          horizonte_semanas: int = 13) -> list[dict]:
    """
    Genera el plan completo para todos los SKUs con parámetros definidos.

    Args:
        sku_params:       dict[sku → SKUParams]
        forecasts:        dict[sku → list[dict]] (output de Prophet)
        stocks_actuales:  dict[sku → float] en cajas (default 0 si no se provee)
        lineas:           dict[codigo → LineaProduccion]
        horizonte_semanas: semanas a planificar

    Returns:
        Lista de dicts con todas las órdenes sugeridas
    """
    if stocks_actuales is None:
        stocks_actuales = {}
    if lineas is None:
        lineas = {}

    todas_ordenes = []

    for sku, params in sku_params.items():
        if not params.activo:
            continue
        if sku not in forecasts:
            continue

        forecast = forecasts[sku]
        stock    = stocks_actuales.get(sku, 0)

        ordenes = generar_plan_sku(
            params=params,
            forecast=forecast,
            stock_actual_cajas=stock,
            lineas=lineas,
            horizonte_semanas=horizonte_semanas,
        )

        for o in ordenes:
            todas_ordenes.append({
                'sku':               o.sku,
                'descripcion':       o.descripcion,
                'tipo':              o.tipo,
                'semana_necesidad':  o.semana_necesidad,
                'semana_emision':    o.semana_emision,
                'cantidad_cajas':    o.cantidad_cajas,
                'cantidad_unidades': o.cantidad_unidades,
                'linea':             o.linea,
                'motivo':            o.motivo,
                'alerta':            o.alerta,
                'tiene_alerta':      o.alerta is not None,
            })

    return sorted(todas_ordenes, key=lambda x: (x['semana_emision'], x['sku']))


# ── Resumen semanal para dashboard ────────────────────────────────────────────

def resumen_semanal(ordenes: list[dict]) -> list[dict]:
    """
    Agrupa las órdenes por semana de emisión para vista de calendario.
    Retorna una lista de semanas con total de órdenes y alertas.
    """
    df = pd.DataFrame(ordenes)
    if df.empty:
        return []

    resumen = (
        df.groupby('semana_emision')
          .agg(
              n_ordenes=('sku', 'count'),
              n_alertas=('tiene_alerta', 'sum'),
              tipos=('tipo', lambda x: list(x.value_counts().to_dict().items())),
          )
          .reset_index()
          .sort_values('semana_emision')
    )
    return resumen.to_dict(orient='records')


def resumen_por_linea(ordenes: list[dict],
                      lineas: dict,
                      sku_params: dict) -> list[dict]:
    """
    Calcula la carga proyectada por línea de producción para detectar
    semanas de sobre o sub utilización.
    """
    df = pd.DataFrame(ordenes)
    if df.empty or lineas is None:
        return []

    df_prod = df[df['tipo'] == 'PRODUCCION'].copy()
    if df_prod.empty:
        return []

    # Calcular horas requeridas por orden
    def horas_requeridas(row):
        if row['linea'] not in lineas:
            return 0
        linea = lineas[row['linea']]
        sku   = row['sku']
        u_hr  = linea.velocidad_u_hr
        if u_hr == 0:
            return 0
        return row['cantidad_unidades'] / u_hr

    df_prod['horas_req'] = df_prod.apply(horas_requeridas, axis=1)

    resultado = []
    for linea_cod, linea in lineas.items():
        df_linea = df_prod[df_prod['linea'] == linea_cod]
        if df_linea.empty:
            continue
        for semana in df_linea['semana_emision'].unique():
            df_sem = df_linea[df_linea['semana_emision'] == semana]
            horas_req  = df_sem['horas_req'].sum()
            horas_disp = linea.horas_disponibles_semana
            uso_pct    = (horas_req / horas_disp * 100) if horas_disp > 0 else 0
            resultado.append({
                'linea':       linea_cod,
                'nombre':      linea.nombre,
                'semana':      semana,
                'horas_req':   round(horas_req, 1),
                'horas_disp':  round(horas_disp, 1),
                'uso_pct':     round(uso_pct, 1),
                'sobrecarga':  uso_pct > 100,
            })

    return sorted(resultado, key=lambda x: (x['semana'], x['linea']))
