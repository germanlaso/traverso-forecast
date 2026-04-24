"""
mrp.py — Motor MRP Traverso S.A.
"""
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional


@dataclass
class SKUParams:
    sku:                str
    descripcion:        str
    categoria:          str
    tipo:               str
    unidades_por_caja:  int
    lead_time_semanas:  float
    stock_seguridad_dias: float
    batch_minimo:       int
    multiplo_batch:     int
    cap_bodega:         int
    compra_minima:      int   = 0
    linea_preferida:    str   = ''
    activo:             bool  = True


@dataclass
class LineaProduccion:
    codigo:         str
    nombre:         str
    turnos_dia:     int
    horas_turno:    float
    dias_semana:    int
    velocidad_u_hr: float

    @property
    def horas_disponibles_semana(self):
        return self.turnos_dia * self.horas_turno * self.dias_semana

    @property
    def capacidad_u_semana(self):
        return self.horas_disponibles_semana * self.velocidad_u_hr


@dataclass
class SKULinea:
    sku:          str
    linea:        str
    t_cambio_hrs: float
    preferida:    bool


@dataclass
class OrdenSugerida:
    sku:              str
    descripcion:      str
    tipo:             str
    semana_necesidad: str
    semana_emision:   str
    cantidad_cajas:   int
    cantidad_unidades: int
    linea:            Optional[str]
    motivo:           str
    alerta:           Optional[str]


def _normalize(s):
    """Normaliza string: minusculas, sin espacios ni tildes ni parentesis."""
    s = str(s).lower().strip()
    for a, b in [(' ',''),('(',''),(')',''),('.',''),
                 ('\xe3','a'),('\xe9','e'),('\xed','i'),('\xf3','o'),('\xfa','u'),('\xf1','n'),
                 ('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n'),
                 ('Á','a'),('É','e'),('Í','i'),('Ó','o'),('Ú','u'),('Ñ','n')]:
        s = s.replace(a, b)
    return s


def load_params_from_excel(path: str):
    xl = pd.ExcelFile(path)

    # ── SKU_PARAMS ────────────────────────────────────────────────────────────
    df = pd.read_excel(xl, sheet_name='SKU_PARAMS', header=2)
    
    # Mapeo flexible por nombre normalizado
    col_map = {}
    for col in df.columns:
        c = _normalize(col)
        if c.startswith('sku') or 'codigosap' in c:  col_map[col] = 'sku'
        elif 'descripcion' in c:                      col_map[col] = 'descripcion'
        elif 'unidades' in c and 'caja' in c:         col_map[col] = 'unidades_por_caja'
        elif 'categoria' in c:                        col_map[col] = 'categoria'
        elif 'tipoabastecimiento' in c or c == 'tipo': col_map[col] = 'tipo'
        elif 'leadtime' in c:                         col_map[col] = 'lead_time_semanas'
        elif 'stockseguridad' in c or 'diascobertura' in c: col_map[col] = 'stock_seguridad_dias'
        elif 'batchminimo' in c:                      col_map[col] = 'batch_minimo'
        elif 'multiplobatch' in c:                    col_map[col] = 'multiplo_batch'
        elif 'capbodega' in c:                        col_map[col] = 'cap_bodega'
        elif 'lineaproduccion' in c:                  col_map[col] = 'linea_produccion'
        elif 'tcambiobatch' in c:                     col_map[col] = 't_cambio'
        elif 'compraminima' in c:                     col_map[col] = 'compra_minima'
        elif 'paisorigen' in c:                       col_map[col] = 'pais_origen'
        elif c.startswith('activo'):                  col_map[col] = 'activo'

    df = df.rename(columns=col_map)
    
    if 'sku' not in df.columns:
        raise ValueError(f"Col SKU no encontrada. Cols: {df.columns.tolist()}")
    
    df['sku'] = df['sku'].astype(str).str.strip()
    df = df[df['sku'].str.match(r'^\d+$')]
    df = df.dropna(subset=['lead_time_semanas'])

    sku_params = {}
    for _, row in df.iterrows():
        try:
            sku_params[row['sku']] = SKUParams(
                sku=row['sku'],
                descripcion=str(row.get('descripcion', '')),
                categoria=str(row.get('categoria', '')),
                tipo=str(row.get('tipo', 'PRODUCCION')).upper().strip(),
                unidades_por_caja=int(row.get('unidades_por_caja', 1) or 1),
                lead_time_semanas=float(row.get('lead_time_semanas', 1)),
                stock_seguridad_dias=float(row.get('stock_seguridad_dias', 7) or 7),
                batch_minimo=int(row.get('batch_minimo', 0) or 0),
                multiplo_batch=int(row.get('multiplo_batch', 1) or 1),
                cap_bodega=int(row.get('cap_bodega', 999999) or 999999),
                compra_minima=int(row.get('compra_minima', 0) or 0),
                activo=str(row.get('activo', 'S')).upper().strip() == 'S',
            )
        except Exception as e:
            print(f"[MRP] SKU {row.get('sku','?')} ignorado: {e}")

    # ── LINEAS_PRODUCCION ─────────────────────────────────────────────────────
    df_lin = pd.read_excel(xl, sheet_name='LINEAS_PRODUCCION', header=2)
    col_map2 = {}
    for col in df_lin.columns:
        c = _normalize(col)
        if c.startswith('codigolinea') or c.startswith('codigo'): col_map2[col] = 'codigo'
        elif c.startswith('nombrelinea') or c.startswith('nombre'): col_map2[col] = 'nombre'
        elif 'turnospordia' in c or c.startswith('turnos'): col_map2[col] = 'turnos_dia'
        elif 'horasporturno' in c or ('horas' in c and 'turno' in c): col_map2[col] = 'horas_turno'
        elif 'diasproduccion' in c or 'diasporsemana' in c or ('dias' in c and 'sem' in c): col_map2[col] = 'dias_semana'
        elif 'velocidad' in c and 'hora' in c: col_map2[col] = 'velocidad_u_hr'
        elif c.startswith('activa'): col_map2[col] = 'activa'

    df_lin = df_lin.rename(columns=col_map2)
    
    lineas = {}
    if 'codigo' in df_lin.columns and 'velocidad_u_hr' in df_lin.columns:
        df_lin = df_lin.dropna(subset=['codigo', 'velocidad_u_hr'])
        df_lin['codigo'] = df_lin['codigo'].astype(str).str.strip()
        for _, row in df_lin.iterrows():
            try:
                if str(row.get('activa', 'S')).upper().strip() != 'S':
                    continue
                lineas[row['codigo']] = LineaProduccion(
                    codigo=row['codigo'],
                    nombre=str(row.get('nombre', '')),
                    turnos_dia=int(row.get('turnos_dia', 1) or 1),
                    horas_turno=float(row.get('horas_turno', 8) or 8),
                    dias_semana=int(row.get('dias_semana', 5) or 5),
                    velocidad_u_hr=float(row.get('velocidad_u_hr', 0) or 0),
                )
            except Exception as e:
                print(f"[MRP] Linea ignorada: {e}")

    # ── SKU_LINEA ─────────────────────────────────────────────────────────────
    df_sl = pd.read_excel(xl, sheet_name='SKU_LINEA', header=2)
    col_map3 = {}
    for col in df_sl.columns:
        c = _normalize(col)
        if c.startswith('sku') or 'codigosap' in c: col_map3[col] = 'sku'
        elif 'codigolinea' in c or c == 'codigo': col_map3[col] = 'linea'
        elif 'tcambio' in c or 'cambio' in c: col_map3[col] = 't_cambio_hrs'
        elif 'preferida' in c: col_map3[col] = 'preferida'

    df_sl = df_sl.rename(columns=col_map3)
    sku_lineas = []
    if 'sku' in df_sl.columns and 'linea' in df_sl.columns:
        df_sl = df_sl.dropna(subset=['sku', 'linea'])
        df_sl['sku'] = df_sl['sku'].astype(str).str.strip()
        for _, row in df_sl.iterrows():
            try:
                sku_lineas.append(SKULinea(
                    sku=row['sku'],
                    linea=str(row['linea']).strip(),
                    t_cambio_hrs=float(row.get('t_cambio_hrs', 0) or 0),
                    preferida=str(row.get('preferida', 'N')).upper().strip() == 'S',
                ))
            except Exception as e:
                print(f"[MRP] SKULinea ignorada: {e}")

    for sl in sku_lineas:
        if sl.preferida and sl.sku in sku_params:
            sku_params[sl.sku].linea_preferida = sl.linea

    return sku_params, lineas, sku_lineas


def calcular_stock_seguridad_cajas(params, forecast_semanal_cajas):
    return (forecast_semanal_cajas / 7) * params.stock_seguridad_dias


def redondear_a_batch(cantidad_cajas, params):
    cantidad_u = cantidad_cajas * params.unidades_por_caja
    if cantidad_u <= 0:
        return 0
    cantidad_u = max(cantidad_u, params.batch_minimo)
    if params.multiplo_batch > 1:
        cantidad_u = math.ceil(cantidad_u / params.multiplo_batch) * params.multiplo_batch
    return int(cantidad_u)


def calcular_fecha_emision(fecha_necesidad, lead_time_semanas):
    return fecha_necesidad - timedelta(days=round(lead_time_semanas * 7))


def generar_plan_sku(params, forecast, stock_actual_cajas=0,
                     ordenes_transito_cajas=0, lineas=None, horizonte_semanas=13):
    if lineas is None:
        lineas = {}
    ordenes = []
    stock_proyectado = stock_actual_cajas + ordenes_transito_cajas
    hoy = datetime.now().date()
    forecast_futuro = [f for f in forecast
                       if pd.to_datetime(f['ds']).date() >= hoy][:horizonte_semanas]

    for f in forecast_futuro:
        fecha_semana = pd.to_datetime(f['ds'])
        yhat_cajas   = max(0, f['yhat'])
        ss_cajas     = calcular_stock_seguridad_cajas(params, yhat_cajas)
        nec_neta     = yhat_cajas + ss_cajas - stock_proyectado

        if nec_neta <= 0:
            stock_proyectado = max(0, stock_proyectado - yhat_cajas)
            continue

        orden_u     = redondear_a_batch(nec_neta, params)
        orden_cajas = math.ceil(orden_u / params.unidades_por_caja)
        alerta      = None

        if stock_proyectado * params.unidades_por_caja + orden_u > params.cap_bodega:
            alerta = f"Excede cap. bodega ({params.cap_bodega:,} u.)"

        fecha_emision = calcular_fecha_emision(fecha_semana, params.lead_time_semanas)
        if fecha_emision.date() < hoy:
            dias = (hoy - fecha_emision.date()).days
            alerta = f"URGENTE: debio emitirse hace {dias} dias"

        linea_asignada = None
        if params.tipo == 'PRODUCCION' and params.linea_preferida:
            linea_asignada = params.linea_preferida
            if params.linea_preferida in lineas:
                linea = lineas[params.linea_preferida]
                cap_cajas = linea.capacidad_u_semana / params.unidades_por_caja
                if orden_cajas > cap_cajas:
                    alerta = (alerta or '') + f" Excede cap. linea {linea.nombre}"

        if orden_cajas > 0:
            ordenes.append(OrdenSugerida(
                sku=params.sku, descripcion=params.descripcion,
                tipo=params.tipo,
                semana_necesidad=fecha_semana.strftime('%Y-%m-%d'),
                semana_emision=fecha_emision.strftime('%Y-%m-%d'),
                cantidad_cajas=int(orden_cajas), cantidad_unidades=int(orden_u),
                linea=linea_asignada,
                motivo=f"FC:{yhat_cajas:.0f} SS:{ss_cajas:.0f} Stock:{stock_proyectado:.0f} Neta:{nec_neta:.0f}",
                alerta=alerta,
            ))
        stock_proyectado = max(0, stock_proyectado + orden_cajas - yhat_cajas)

    return ordenes


def generar_plan_completo(sku_params, forecasts, stocks_actuales=None,
                          lineas=None, horizonte_semanas=13):
    if stocks_actuales is None: stocks_actuales = {}
    if lineas is None: lineas = {}
    todas = []
    for sku, params in sku_params.items():
        if not params.activo or sku not in forecasts:
            continue
        for o in generar_plan_sku(params, forecasts[sku],
                                   stocks_actuales.get(sku, 0),
                                   lineas=lineas,
                                   horizonte_semanas=horizonte_semanas):
            todas.append({
                'sku': o.sku, 'descripcion': o.descripcion, 'tipo': o.tipo,
                'semana_necesidad': o.semana_necesidad, 'semana_emision': o.semana_emision,
                'cantidad_cajas': o.cantidad_cajas, 'cantidad_unidades': o.cantidad_unidades,
                'linea': o.linea, 'motivo': o.motivo, 'alerta': o.alerta,
                'tiene_alerta': o.alerta is not None,
            })
    return sorted(todas, key=lambda x: (x['semana_emision'], x['sku']))


def resumen_semanal(ordenes):
    df = pd.DataFrame(ordenes)
    if df.empty: return []
    return (df.groupby('semana_emision')
              .agg(n_ordenes=('sku','count'), n_alertas=('tiene_alerta','sum'))
              .reset_index().sort_values('semana_emision')
              .to_dict(orient='records'))


def resumen_por_linea(ordenes, lineas, sku_params):
    df = pd.DataFrame(ordenes)
    if df.empty or not lineas: return []
    df_prod = df[df['tipo'] == 'PRODUCCION'].copy()
    if df_prod.empty: return []

    def horas_req(row):
        if not row['linea'] or row['linea'] not in lineas: return 0
        u_hr = lineas[row['linea']].velocidad_u_hr
        return row['cantidad_unidades'] / u_hr if u_hr else 0

    df_prod['horas_req'] = df_prod.apply(horas_req, axis=1)
    resultado = []
    for cod, linea in lineas.items():
        df_l = df_prod[df_prod['linea'] == cod]
        if df_l.empty: continue
        for sem in df_l['semana_emision'].unique():
            hr = df_l[df_l['semana_emision']==sem]['horas_req'].sum()
            hd = linea.horas_disponibles_semana
            resultado.append({
                'linea': cod, 'nombre': linea.nombre, 'semana': sem,
                'horas_req': round(hr,1), 'horas_disp': round(hd,1),
                'uso_pct': round(hr/hd*100,1) if hd else 0,
                'sobrecarga': hr > hd,
            })
    return sorted(resultado, key=lambda x: (x['semana'], x['linea']))
