import streamlit as st
import pandas as pd
import time
from datetime import datetime
import io
import re
import unicodedata
import plotly.express as px
import plotly.graph_objects as go
import tempfile
import os

# Importaciones seguras de dependencias desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
        procesar_fechas_seguro,
        generar_pdf_rendimiento_integral_360,
        leer_espejo_gcs,
        get_honduras_time
    )
except ImportError as e:
    st.error(f"Error al importar módulos de soporte desde tools.py: {e}")

NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# CLASIFICADOR DE TIPO DE ORDEN
# ==============================================================================
def clasificar_segmento(actividad_valor):
    t = str(actividad_valor).upper().strip()
    if any(k in t for k in ['PLEX', 'EMPRESA', 'CORPORAT', 'BUSINESS', 'SME', 'PEXTERNO', 'SPLITTEROPT']):
        return 'Plex'
    return 'Residencial'

# ==============================================================================
# DETECTOR DE INASISTENCIAS
# ==============================================================================
PALABRAS_INASISTENCIA = [
    'NO SE PRESENTO', 'NO SE PRESENTÓ', 'AUSENTE', 'FALTA',
    'INASISTENCIA', 'NO LABORES', 'NO TRABAJO', 'NO TRABAJÓ',
    'NO ASISTIO', 'NO ASISTIÓ', 'NO SE PRESENTÓ A LABORES',
    'NO SE PRESENTO A LABORES', 'NO SE PRESENTO AL TRABAJO',
    'INCAPACIDAD', 'PERMISO SIN GOCE', 'SUSPENSION', 'SUSPENSIÓN'
]

def es_comentario_inasistencia(comentario):
    if pd.isna(comentario):
        return False
    c = str(comentario).upper().strip()
    c = unicodedata.normalize('NFKD', c).encode('ASCII', 'ignore').decode('utf-8')
    return any(p in c for p in PALABRAS_INASISTENCIA)

# ==============================================================================
# MOTOR DE LECTURA DE ARCHIVOS
# ==============================================================================
def forzar_columnas_unicas_local(df):
    if df is None or df.empty:
        return df
    df.columns = df.columns.astype(str).str.strip()
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        dup_indices = cols[cols == dup].index.tolist()
        for i, idx in enumerate(dup_indices):
            if i != 0:
                cols.iat[idx] = f"{dup}_{i}"
    df.columns = cols
    return df

def read_file_robust_local(uploaded_file):
    filename = uploaded_file.name.lower()
    uploaded_file.seek(0)
    content = uploaded_file.read()
    uploaded_file.seek(0)

    if filename.endswith('.xlsx') or filename.endswith('.xlsm'):
        try:
            return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='openpyxl'))
        except:
            pass

    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='xlrd'))
        except:
            pass

    es_zip_binario = content.startswith(b'PK\x03\x04')
    if not es_zip_binario and (b'<table' in content.lower() or b'<html' in content.lower()):
        try:
            dfs = pd.read_html(io.BytesIO(content))
            if dfs:
                return forzar_columnas_unicas_local(max(dfs, key=len))
        except:
            try:
                dfs = pd.read_html(io.BytesIO(content), encoding='latin-1')
                if dfs:
                    return forzar_columnas_unicas_local(max(dfs, key=len))
            except:
                pass

    uploaded_file.seek(0)
    try:
        return forzar_columnas_unicas_local(pd.read_excel(uploaded_file))
    except:
        pass

    uploaded_file.seek(0)
    try:
        return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip'))
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='latin-1', on_bad_lines='skip'))

# ==============================================================================
# GESTIÓN DE EXPEDIENTES
# ==============================================================================
def obtener_datos_expedientes(conn):
    if 'df_exp_memoria' not in st.session_state:
        st.session_state['df_exp_memoria'] = None

    if st.session_state['df_exp_memoria'] is not None:
        return st.session_state['df_exp_memoria']

    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
        if df is not None and not df.empty:
            st.session_state['df_exp_memoria'] = df
            return df
    except:
        pass

    if conn is None:
        try:
            from streamlit_gsheets import GSheetsConnection
            conn = st.connection("gsheets", type=GSheetsConnection)
        except:
            pass

    if conn is not None:
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            st.session_state['df_exp_memoria'] = df
            return df
        except:
            pass

    return None

# ==============================================================================
# EMPAREJAMIENTO DE NOMBRES
# ==============================================================================
def limpiar_texto_nombres(texto):
    if pd.isna(texto):
        return ""
    t = str(texto).upper().strip()
    t = re.sub(r'\(.*?\)', '', t)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('utf-8')
    t = re.sub(r'[^A-Z\s]', '', t)
    return " ".join(t.split())

def encontrar_tecnico_maestro(nombre_buscar, lista_maestros_limpios, lista_original):
    n_buscar = limpiar_texto_nombres(nombre_buscar)
    if not n_buscar:
        return None

    for i, m_limpio in enumerate(lista_maestros_limpios):
        if n_buscar == m_limpio or n_buscar in m_limpio or m_limpio in n_buscar:
            return lista_original[i]

    palabras_comunes = {'DE', 'EL', 'LA', 'LOS', 'LAS', 'Y'}
    tokens_buscar = set([w for w in n_buscar.split() if len(w) > 2 and w not in palabras_comunes])

    mejor_match = None
    max_score = 0

    for i, m_limpio in enumerate(lista_maestros_limpios):
        tokens_maestro = set([w for w in m_limpio.split() if len(w) > 2 and w not in palabras_comunes])
        score = len(tokens_buscar.intersection(tokens_maestro))
        if score > max_score:
            max_score = score
            mejor_match = lista_original[i]

    if max_score >= 1:
        return mejor_match

    return None

# ==============================================================================
# HELPERS
# ==============================================================================
def formatear_hora(secs):
    if pd.isna(secs) or secs is None or secs <= 0:
        return "--"
    h = int(secs // 3600) % 24
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def extraer_numero_mx(texto):
    if pd.isna(texto) or not str(texto).strip():
        return None
    val = str(texto).upper().strip()
    match = re.search(r'MX[-_ ]*(\d+)', val)
    if match:
        return int(match.group(1))
    match_num = re.search(r'^\s*(\d+)\s*$', val)
    if match_num:
        return int(match_num.group(1))
    return None

def calcular_promedio_real(x):
    tiempos_validos = x[x > 4]
    return tiempos_validos.mean() if len(tiempos_validos) > 0 else 0

# ==============================================================================
# CÁLCULO DE RENDIMIENTO INDIVIDUAL POR ORDEN
# ==============================================================================
def calcular_rendimiento_fila(row):
    tipo = str(row.get('ACTIVIDAD', '')).upper().strip()
    t_min = row.get('Minutos_Orden', 0)
    
    slas = {
        'INSEQUIPO': 60,
        'INSFIBRA': 120,
        'SOP': 80,
        'SOPFIBRA': 80,
        'INSFIBRACOPR': 120,      # Tolerancia a typos comunes
        'INSFIBRACORP': 120,
        'SOPFIBRACORP': 80,
        'TRASLADOEXTFIBRA': 120,
        'TRASLADOINTERNOFIBRA': 80,
        'TVADICIONAL': 80
    }
    
    if tipo not in slas or pd.isna(t_min) or t_min <= 0:
        return None
        
    sla = slas[tipo]
    if t_min <= sla:
        # Si cumple o es más rápido, el rendimiento sube por encima de 100% (tope de 120%)
        rend = (2.0 - (t_min / sla)) * 100.0
        return round(min(120.0, rend), 1)
    else:
        # Si se pasa, el rendimiento decae proporcionalmente
        rend = (sla / t_min) * 100.0
        return round(max(0.0, rend), 1)

# ==============================================================================
# PROCESAMIENTO ANALÍTICO CENTRAL
# ==============================================================================
def procesar_rendimiento_avanzado(df_act, df_gps, df_exp):
    try:
        # --- 1. PROCESAR ÓRDENES ---
        df_act = procesar_dataframe_base(df_act)

        if 'TECNICO' not in df_act.columns:
            alt_c = next((c for c in df_act.columns if 'TECNICO' in str(c).upper() or 'TÉCNICO' in str(c).upper() or 'OPERADOR' in str(c).upper()), None)
            df_act['TECNICO'] = df_act[alt_c] if alt_c else "N/D"

        if 'ACTIVIDAD' not in df_act.columns:
            alt_c = next((c for c in df_act.columns if 'ACTIVIDAD' in str(c).upper() or 'TIPO' in str(c).upper() or 'ORDEN' in str(c).upper()), None)
            df_act['ACTIVIDAD'] = df_act[alt_c] if alt_c else "OTRO"

        if 'HORA_INI' not in df_act.columns:
            alt_c = next((c for c in df_act.columns if 'INI' in str(c).upper() or 'ENTRADA' in str(c).upper() or 'INICIO' in str(c).upper()), None)
            if alt_c:
                df_act['HORA_INI'] = df_act[alt_c]

        if 'HORA_LIQ' not in df_act.columns:
            alt_c = next((c for c in df_act.columns if 'LIQ' in str(c).upper() or 'CIERRE' in str(c).upper() or 'SALIDA' in str(c).upper()), None)
            if alt_c:
                df_act['HORA_LIQ'] = df_act[alt_c]

        if 'NUM' not in df_act.columns:
            alt_c = next((c for c in df_act.columns if 'NUM' in str(c).upper() or 'ORDEN' in str(c).upper() or 'ID' in str(c).upper()), None)
            df_act['NUM'] = df_act[alt_c] if alt_c else range(len(df_act))

        if 'ESTADO' in df_act.columns:
            estado_upper = df_act['ESTADO'].astype(str).str.upper().str.strip()
            df_act = df_act[estado_upper.str.contains('CERRADA|LIQUIDADA|FINALIZADA|COMPLETADA', na=False)]

        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce', dayfirst=True)
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce', dayfirst=True)
        df_act['Fecha_Dia'] = df_act['FECHA_LIQUIDADO'].dt.date

        df_act = df_act[df_act['TECNICO'].notna() & (df_act['TECNICO'].astype(str).str.strip() != '') & (df_act['TECNICO'] != 'N/D')]

        def filtrar_ordenes_allan(row):
            tec_limpio = limpiar_texto_nombres(row['TECNICO'])
            if 'ECHEVERRY' in tec_limpio or ('ALLAN' in tec_limpio and 'RICARDO' in tec_limpio):
                act_val = str(row.get('ACTIVIDAD', '')).upper()
                return 'INSEQUIPO' in act_val
            return True

        df_act = df_act[df_act.apply(filtrar_ordenes_allan, axis=1)]

        if df_act.empty:
            return None, None, None, None, "El archivo de actividades quedó vacío tras aplicar los filtros."

        df_act['Minutos_Orden'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos_Orden'] = df_act['Minutos_Orden'].apply(lambda x: x if x > 0 else 0)
        
        # ==============================================================================
        # 🚨 FILTRO DE SEGURIDAD OPERATIVA: ELIMINAR CLICS ACCIDENTALES (<= 4 MINUTOS)
        # ==============================================================================
        # Si una orden se abre y cierra en 4 minutos o menos, se considera un error y se
        # descarta por completo del análisis para no alterar volumenes, promedios ni eficiencia.
        df_act = df_act[df_act['Minutos_Orden'] > 4]
        
        if df_act.empty:
            return None, None, None, None, "No quedaron órdenes válidas para analizar tras filtrar los tiempos mínimos de ejecución."

        df_act['Segmento'] = df_act['ACTIVIDAD'].apply(clasificar_segmento)
        df_act['TipoOrden'] = df_act['ACTIVIDAD'].astype(str).str.strip().str.upper()

        # Cálculo de rendimiento fila por fila (evalúa solo las órdenes que pasaron el filtro)
        df_act['Rendimiento_Pct'] = df_act.apply(calcular_rendimiento_fila, axis=1)

        tecnicos_originales = df_act['TECNICO'].unique()
        tecnicos_limpios = [limpiar_texto_nombres(t) for t in tecnicos_originales]

        tec_to_mx = {}
        mx_to_tec = {}
        col_mx = next((c for c in df_act.columns if 'MX' in str(c).upper() or 'VEHICULO' in str(c).upper() or 'UNIDAD' in str(c).upper()), None)
        if col_mx:
            for tec, g in df_act.groupby('TECNICO'):
                mx_val = g[col_mx].dropna().iloc[0] if not g[col_mx].dropna().empty else None
                mx_num = extraer_numero_mx(mx_val)
                if mx_num:
                    tec_to_mx[tec] = mx_num
                    mx_to_tec[mx_num] = tec

        # --- 2. PROCESAR GPS ---
        df_diario_gps = pd.DataFrame()
        gps_promedios = {}

        if df_gps is not None and not df_gps.empty:
            df_gps.columns = [str(c).strip().upper().replace('"', '').replace("'", "") for c in df_gps.columns]

            col_placa = next((c for c in df_gps.columns if 'PLACA' in c or 'ALIAS' in c), None)
            col_in = next((c for c in df_gps.columns if ('HORA' in c or 'FECHA' in c) and ('INGRESO' in c or 'LLEGADA' in c)), None)
            if not col_in:
                col_in = next((c for c in df_gps.columns if 'INGRESO' in c or 'LLEGADA' in c), None)
            col_out = next((c for c in df_gps.columns if ('HORA' in c or 'FECHA' in c) and 'SALIDA' in c), None)
            if not col_out:
                col_out = next((c for c in df_gps.columns if 'SALIDA' in c), None)

            if col_placa and col_in and col_out:
                df_gps['DT_IN'] = pd.to_datetime(df_gps[col_in], errors='coerce')
                df_gps['DT_OUT'] = pd.to_datetime(df_gps[col_out], errors='coerce')
                df_gps['Fecha'] = df_gps['DT_OUT'].dt.date

                def encontrar_tecnico_hibrido(placa_alias):
                    mx_gps = extraer_numero_mx(placa_alias)
                    if mx_gps and mx_gps in mx_to_tec:
                        return mx_to_tec[mx_gps]
                    match = encontrar_tecnico_maestro(placa_alias, tecnicos_limpios, tecnicos_originales)
                    if match:
                        return match
                    placa_clean = limpiar_texto_nombres(placa_alias)
                    for original, limpio in zip(tecnicos_originales, tecnicos_limpios):
                        partes = [p for p in limpio.split() if len(p) > 3]
                        if any(p in placa_clean for p in partes):
                            return original
                    return None

                df_gps['TEC_MAESTRO'] = df_gps[col_placa].apply(encontrar_tecnico_hibrido)
                df_gps_valid = df_gps.dropna(subset=['TEC_MAESTRO']).copy()

                gps_diario_list = []
                for (tec, fecha), sub_df in df_gps_valid.groupby(['TEC_MAESTRO', 'Fecha']):
                    p_salida = sub_df['DT_OUT'].min()
                    u_llegada = sub_df['DT_IN'].max()
                    week_val = str(p_salida.to_period('W')) if pd.notnull(p_salida) else '--'
                    s_secs = p_salida.hour * 3600 + p_salida.minute * 60 + p_salida.second if pd.notnull(p_salida) else None
                    e_secs = u_llegada.hour * 3600 + u_llegada.minute * 60 + u_llegada.second if pd.notnull(u_llegada) else None
                    salida_valida = s_secs if (s_secs and 5 * 3600 <= s_secs <= 13 * 3600) else None
                    entrada_valida = e_secs if (e_secs and 12 * 3600 <= e_secs <= 22 * 3600) else None
                    gps_diario_list.append({
                        'TECNICO': tec,
                        'Fecha': fecha,
                        'Week': week_val,
                        'Salida_Secs': salida_valida,
                        'Entrada_Secs': entrada_valida
                    })

                df_diario_gps = pd.DataFrame(gps_diario_list)

                if not df_diario_gps.empty:
                    df_semanal_gps = df_diario_gps.groupby(['TECNICO', 'Week']).agg(
                        Semanal_Salida=('Salida_Secs', 'mean'),
                        Semanal_Entrada=('Entrada_Secs', 'mean')
                    ).reset_index()
                    df_mensual_final = df_semanal_gps.groupby('TECNICO').agg(
                        Mensual_Salida=('Semanal_Salida', 'mean'),
                        Mensual_Entrada=('Semanal_Entrada', 'mean')
                    ).reset_index()
                    for _, row_m in df_mensual_final.iterrows():
                        tec = row_m['TECNICO']
                        gps_promedios[tec] = {
                            'Salida': formatear_hora(row_m['Mensual_Salida']),
                            'Entrada': formatear_hora(row_m['Mensual_Entrada'])
                        }

        # --- 3. PROCESAR EXPEDIENTES ---
        df_exp_detallado = pd.DataFrame()
        faltas_dict = {}
        llamados_dict = {}
        dias_no_presentados_dict = {}

        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            col_comentario = next((c for c in df_exp.columns if any(k in str(c).upper() for k in [
                'COMENTARIO', 'OBSERVACION', 'OBSERVACIÓN', 'NOTA', 'DESCRIPCION', 'DESCRIPCIÓN', 'DETALLE'
            ])), None)

            if col_tec_exp:
                df_exp['TEC_MAESTRO'] = df_exp[col_tec_exp].apply(
                    lambda x: encontrar_tecnico_maestro(x, tecnicos_limpios, tecnicos_originales)
                )
                df_exp_detallado = df_exp.dropna(subset=['TEC_MAESTRO']).copy()

                if col_tipo:
                    def es_falta(t):
                        return any(k in str(t).upper() for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA'])
                    df_exp_detallado['ES_FALTA'] = df_exp_detallado[col_tipo].apply(es_falta)
                    for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                        faltas_dict[tec] = int(g['ES_FALTA'].sum())
                        llamados_dict[tec] = int((~g['ES_FALTA']).sum())

                if col_comentario:
                    df_exp_detallado['ES_NO_PRESENTADO'] = df_exp_detallado[col_comentario].apply(es_comentario_inasistencia)
                    for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                        dias_no_presentados_dict[tec] = int(g['ES_NO_PRESENTADO'].sum())
                else:
                    dias_no_presentados_dict = faltas_dict.copy()

        return df_act, df_diario_gps, df_exp_detallado, gps_promedios, "Exitoso"

    except Exception as e:
        import traceback
        return None, None, None, None, f"Error: {e}\n{traceback.format_exc()}"


# ==============================================================================
# FUNCIÓN QUE CONSTRUYE LOS RESÚMENES A PARTIR DE UN df_act YA FILTRADO POR FECHA
# ==============================================================================
def construir_resumenes(df_act_filtrado, gps_promedios, faltas_dict, llamados_dict,
                        dias_no_presentados_dict, df_exp_detallado):
    if df_act_filtrado.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    last_order_dict = {}
    df_last_daily = df_act_filtrado.dropna(subset=['FECHA_LIQUIDADO']).groupby(
        ['TECNICO', 'Fecha_Dia'])['FECHA_LIQUIDADO'].max().reset_index()
    df_last_daily['Last_Secs'] = (
        df_last_daily['FECHA_LIQUIDADO'].dt.hour * 3600 +
        df_last_daily['FECHA_LIQUIDADO'].dt.minute * 60 +
        df_last_daily['FECHA_LIQUIDADO'].dt.second
    )
    df_last_avg = df_last_daily.groupby('TECNICO')['Last_Secs'].mean().reset_index()
    for _, r in df_last_avg.iterrows():
        last_order_dict[r['TECNICO']] = formatear_hora(r['Last_Secs'])

    resumen_act = df_act_filtrado.groupby('TECNICO').agg(
        Ordenes_Totales=('NUM', 'count'),
        Minutos_Promedio=('Minutos_Orden', calcular_promedio_real),
        Rendimiento_Promedio=('Rendimiento_Pct', 'mean'),  # Promedio de eficiencias
        Hora_Primera_Orden=('FECHA_ENTRADA', 'min')
    ).reset_index()

    resumen_segmento = df_act_filtrado.groupby(['TECNICO', 'Segmento']).agg(
        Ordenes=('NUM', 'count')
    ).reset_index()

    resumen_tipo = df_act_filtrado.groupby(['TECNICO', 'TipoOrden']).agg(
        Ordenes=('NUM', 'count'),
        MinProm=('Minutos_Orden', calcular_promedio_real),
        Rendimiento_Prom=('Rendimiento_Pct', 'mean')  # Rendimiento promedio por tipo
    ).reset_index()

    datos_finales = []
    for _, row in resumen_act.iterrows():
        tec = row['TECNICO']
        h_primera = row['Hora_Primera_Orden'].strftime('%H:%M:%S') if pd.notnull(row['Hora_Primera_Orden']) else '--'
        h_ultima = last_order_dict.get(tec, '--')
        gps = gps_promedios.get(tec, {'Salida': '--', 'Entrada': '--'})
        plex_ord = int(resumen_segmento[(resumen_segmento['TECNICO'] == tec) & (resumen_segmento['Segmento'] == 'Plex')]['Ordenes'].sum())
        res_ord = int(resumen_segmento[(resumen_segmento['TECNICO'] == tec) & (resumen_segmento['Segmento'] == 'Residencial')]['Ordenes'].sum())
        
        rend_global = round(row['Rendimiento_Promedio'], 1) if pd.notna(row['Rendimiento_Promedio']) else 0.0

        datos_finales.append({
            'TÉCNICO': tec,
            'ÓRDENES CANTIDAD': int(row['Ordenes_Totales']),
            'ÓRDENES PLEX': plex_ord,
            'ÓRDENES RESIDENCIAL': res_ord,
            'TIEMPO PROM. EN ORDEN (Min)': round(row['Minutos_Promedio'], 1),
            'RENDIMIENTO GLOBAL (%)': rend_global,
            'HORA 1ra ORDEN': h_primera,
            'HORA ÚLT. ORDEN': h_ultima,
            'SALIDA PLANTEL (GPS)': gps['Salida'],
            'ENTRADA PLANTEL (GPS)': gps['Entrada'],
            'DÍAS NO PRESENTADO': int(dias_no_presentados_dict.get(tec, 0)),
            'DÍAS FALTADOS': int(faltas_dict.get(tec, 0)),
            'LLAMADOS ATENCIÓN': int(llamados_dict.get(tec, 0)),
        })

    return pd.DataFrame(datos_finales), resumen_segmento, resumen_tipo


# ==============================================================================
# INTERFAZ STREAMLIT (DASHBOARD)
# ==============================================================================
def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Dashboard de Rendimiento Integral</h2>", unsafe_allow_html=True)
    st.caption("Depuración Inteligente: Órdenes + GPS + Expedientes Laborales")
    st.divider()

    obtener_datos_expedientes(conn)

    # ================= 1. CARGA DE ARCHIVOS =================
    st.markdown("#### 📥 Carga de Archivos Base")
    c1, c2, c3 = st.columns(3)
    with c1:
        act_file = st.file_uploader("1. rep_actividades (Órdenes)", type=['csv', 'xlsx'])
    with c2:
        gps_file = st.file_uploader("2. InformeZonasRutas (GPS)", type=['csv', 'xlsx'])
    with c3:
        st.write("3. Base de Datos Nube")
        if st.button("🔄 Sincronizar Expedientes"):
            with st.spinner("Conectando..."):
                if conn:
                    try:
                        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        if df is None or df.empty:
                            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ BD Sincronizada.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(e)
                else:
                    st.error("Sin conexión.")
        if st.session_state.get('df_exp_memoria') is not None:
            st.success(f"Expedientes listos ({len(st.session_state['df_exp_memoria'])} reg.)")

    st.markdown("<br>", unsafe_allow_html=True)

    # ================= 2. BOTÓN DE EJECUCIÓN =================
    if st.button("🚀 INICIAR ANÁLISIS CRUZADO", type="primary", use_container_width=True):
        if act_file:
            with st.spinner("🤖 Depurando tiempos reales y cruzando bases de datos..."):
                df_act_raw = read_file_robust_local(act_file)
                df_gps_raw = read_file_robust_local(gps_file) if gps_file else None
                df_exp_raw = st.session_state.get('df_exp_memoria', None)

                df_act_proc, df_diario_gps, df_exp_det, gps_promedios, msg = procesar_rendimiento_avanzado(
                    df_act_raw, df_gps_raw, df_exp_raw
                )

                if df_act_proc is not None:
                    # Reconstruir dicts de expedientes
                    faltas_dict = {}
                    llamados_dict = {}
                    dias_no_presentados_dict = {}
                    if df_exp_det is not None and not df_exp_det.empty:
                        if 'ES_FALTA' in df_exp_det.columns:
                            for tec, g in df_exp_det.groupby('TEC_MAESTRO'):
                                faltas_dict[tec] = int(g['ES_FALTA'].sum())
                                llamados_dict[tec] = int((~g['ES_FALTA']).sum())
                        if 'ES_NO_PRESENTADO' in df_exp_det.columns:
                            for tec, g in df_exp_det.groupby('TEC_MAESTRO'):
                                dias_no_presentados_dict[tec] = int(g['ES_NO_PRESENTADO'].sum())
                        else:
                            dias_no_presentados_dict = faltas_dict.copy()

                    st.session_state['rs_act_proc'] = df_act_proc
                    st.session_state['rs_diario'] = df_diario_gps
                    st.session_state['rs_disciplina'] = df_exp_det
                    st.session_state['rs_gps_promedios'] = gps_promedios
                    st.session_state['rs_faltas'] = faltas_dict
                    st.session_state['rs_llamados'] = llamados_dict
                    st.session_state['rs_no_presentados'] = dias_no_presentados_dict
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.warning("Debe subir al menos el archivo 'rep_actividades'.")

    # ================= 3. VISUALIZACIÓN DEL DASHBOARD =================
    if 'rs_act_proc' not in st.session_state:
        return

    df_act_proc        = st.session_state['rs_act_proc']
    df_exp_det         = st.session_state.get('rs_disciplina', pd.DataFrame())
    gps_promedios      = st.session_state.get('rs_gps_promedios', {})
    faltas_dict        = st.session_state.get('rs_faltas', {})
    llamados_dict      = st.session_state.get('rs_llamados', {})
    dias_no_pres_dict  = st.session_state.get('rs_no_presentados', {})

    fechas_disponibles = pd.to_datetime(df_act_proc['Fecha_Dia'].dropna().astype(str), errors='coerce').dropna()

    if not fechas_disponibles.empty:
        min_date = fechas_disponibles.min().date()
        max_date = fechas_disponibles.max().date()

        rango_fechas = st.date_input(
            "📅 Filtrar por Rango de Fechas (afecta las 3 pestañas):",
            value=[min_date, max_date],
            min_value=min_date,
            max_value=max_date,
            key="filtro_fechas_global"
        )

        if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) >= 1:
            fecha_inicio = rango_fechas[0]
            fecha_fin = rango_fechas[1] if len(rango_fechas) > 1 else rango_fechas[0]
        else:
            fecha_inicio = min_date
            fecha_fin = max_date

        mascara = (
            pd.to_datetime(df_act_proc['Fecha_Dia'].astype(str), errors='coerce').dt.date >= fecha_inicio
        ) & (
            pd.to_datetime(df_act_proc['Fecha_Dia'].astype(str), errors='coerce').dt.date <= fecha_fin
        )
        df_act_filtrado = df_act_proc[mascara].copy()
    else:
        fecha_inicio = None
        fecha_fin = None
        df_act_filtrado = df_act_proc.copy()

    df_m, df_seg, df_tipo_ord = construir_resumenes(
        df_act_filtrado, gps_promedios, faltas_dict, llamados_dict, dias_no_pres_dict, df_exp_det
    )

    if df_m.empty:
        st.warning("⚠️ No hay órdenes en el rango de fechas seleccionado.")
        return

    tab_graficos, tab_maestra, tab_exp = st.tabs([
        "📈 Gráficos y KPIs",
        "📋 Tabla Maestra Integral",
        "🚨 Registro Disciplinario"
    ])

    # ================================================================
    # TAB 1: GRÁFICOS Y KPIs
    # ================================================================
    with tab_graficos:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("👥 Técnicos Analizados", len(df_m))
        k2.metric("📦 Total Órdenes", int(df_m['ÓRDENES CANTIDAD'].sum()))
        k3.metric("⏳ Promedio Gral (Min)", f"{round(df_m['TIEMPO PROM. EN ORDEN (Min)'].mean(), 1)} Min")
        k4.metric(
            "🚨 Total Incidencias",
            int(df_m['DÍAS FALTADOS'].sum() + df_m['LLAMADOS ATENCIÓN'].sum() + df_m['DÍAS NO PRESENTADO'].sum())
        )

        st.markdown("---")

        st.markdown("#### 📦 Productividad por Técnico — Residencial vs Plex")
        if not df_seg.empty:
            orden_tecs = df_seg.groupby('TECNICO')['Ordenes'].sum().sort_values(ascending=True).index.tolist()
            fig_ord = px.bar(
                df_seg,
                x='Ordenes', y='TECNICO', color='Segmento', orientation='h',
                title="📦 Productividad por Técnico (Residencial vs Plex)",
                text_auto=True,
                color_discrete_map={'Residencial': '#10B981', 'Plex': '#6366F1'},
                category_orders={'TECNICO': orden_tecs},
                barmode='stack'
            )
            fig_ord.update_layout(
                height=max(350, len(orden_tecs) * 32),
                yaxis_title="", legend_title="Segmento", xaxis_title="Cantidad de Órdenes"
            )
            st.plotly_chart(fig_ord, use_container_width=True)
        else:
            fig_ord = px.bar(
                df_m.sort_values('ÓRDENES CANTIDAD', ascending=True),
                x='ÓRDENES CANTIDAD', y='TÉCNICO', orientation='h',
                title="📦 Productividad (Cant. Órdenes)", text_auto=True,
                color_discrete_sequence=['#10B981']
            )
            fig_ord.update_layout(height=max(350, len(df_m) * 32), yaxis_title="")
            st.plotly_chart(fig_ord, use_container_width=True)
            st.info("ℹ️ No se detectó columna TIPO en el archivo.")

        st.markdown("---")

        st.markdown("#### ⏳ Tiempo Promedio por Orden — Todos los Técnicos por Tipo")
        act_filtro = []
        if not df_tipo_ord.empty:
            actividades_disponibles = sorted(df_tipo_ord['TipoOrden'].unique())
            try:
                act_filtro = st.pills(
                    "🎯 Haz clic en una o varias actividades para aislar el gráfico (Vacío = Muestra todas):",
                    options=actividades_disponibles, selection_mode="multi"
                )
            except AttributeError:
                act_filtro = st.multiselect(
                    "🎯 Selecciona la actividad para aislar el gráfico (Vacío = Muestra todas):",
                    actividades_disponibles
                )

            df_tipo_show = df_tipo_ord[df_tipo_ord['TipoOrden'].isin(act_filtro)] if act_filtro else df_tipo_ord

            if not df_tipo_show.empty:
                orden_tecs_tiempo = (
                    df_tipo_show.groupby('TECNICO')['MinProm'].mean()
                    .sort_values(ascending=False).index.tolist()
                )
                fig_time = px.bar(
                    df_tipo_show,
                    x='MinProm', y='TECNICO', color='TipoOrden', orientation='h',
                    title="⏳ Tiempo Promedio por Orden (Min)", text_auto='.1f',
                    color_discrete_sequence=px.colors.qualitative.Set2,
                    category_orders={'TECNICO': orden_tecs_tiempo},
                    barmode='group'
                )
                fig_time.update_layout(
                    height=max(400, len(orden_tecs_tiempo) * 40),
                    yaxis_title="", legend_title="Tipo de Actividad", xaxis_title="Minutos Promedio"
                )
                st.plotly_chart(fig_time, use_container_width=True)

                with st.expander("📊 Ver detalle numérico por tipo de orden"):
                    df_tipo_pivot = df_tipo_ord.pivot_table(
                        index='TECNICO', columns='TipoOrden', values='MinProm', aggfunc='mean'
                    ).round(1).reset_index()
                    df_tipo_pivot.columns.name = None
                    st.dataframe(df_tipo_pivot, use_container_width=True, hide_index=True)
            else:
                st.warning("⚠️ No hay datos para la actividad seleccionada.")
        else:
            fig_time = px.bar(
                df_m.sort_values('TIEMPO PROM. EN ORDEN (Min)', ascending=False),
                x='TIEMPO PROM. EN ORDEN (Min)', y='TÉCNICO', orientation='h',
                title="⏳ Tiempo Promedio por Orden (Minutos)", text_auto='.1f',
                color_discrete_sequence=['#3B82F6']
            )
            fig_time.update_layout(height=max(400, len(df_m) * 32), yaxis_title="")
            st.plotly_chart(fig_time, use_container_width=True)
            st.info("ℹ️ No se detectó columna TIPO en el archivo.")

        st.markdown("---")
        st.markdown("#### 📊 Matriz Detallada: Volumen, Tiempo y Eficiencia por Actividad")
        st.caption("Esta tabla combina la cantidad de trabajos realizados, el tiempo de ejecución y el porcentaje de eficiencia (Rendimiento).")

        if not df_tipo_ord.empty:
            df_matriz_input = df_tipo_ord[df_tipo_ord['TipoOrden'].isin(act_filtro)] if act_filtro else df_tipo_ord
            df_matriz_final = df_matriz_input.copy()

            df_pivot_cant = df_matriz_final.pivot(index='TECNICO', columns='TipoOrden', values='Ordenes').fillna(0).astype(int)
            df_pivot_time = df_matriz_final.pivot(index='TECNICO', columns='TipoOrden', values='MinProm').fillna(0).round(1)
            df_pivot_rend = df_matriz_final.pivot(index='TECNICO', columns='TipoOrden', values='Rendimiento_Prom').fillna(0).round(1)

            tab_vista_cant, tab_vista_time, tab_vista_rend = st.tabs(["📦 Solo Cantidad", "⏳ Solo Tiempo Promedio", "📈 Rendimiento (%)"])

            with tab_vista_cant:
                st.dataframe(
                    df_pivot_cant.style.background_gradient(cmap='Greens', axis=0),
                    use_container_width=True
                )

            with tab_vista_time:
                def color_tiempos(val):
                    if val == 0:
                        return 'color: #475569'
                    color = '#10B981' if val < 45 else ('#F59E0B' if val < 90 else '#EF4444')
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    df_pivot_time.style.map(color_tiempos),
                    use_container_width=True
                )

            with tab_vista_rend:
                def color_rendimiento(val):
                    if val == 0:
                        return 'color: #475569'
                    # Verde (>=100% óptimo), Amarillo (80%-99% regular), Rojo (<80% retrasado)
                    color = '#10B981' if val >= 100 else ('#F59E0B' if val >= 80 else '#EF4444')
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    df_pivot_rend.style.map(color_rendimiento),
                    use_container_width=True
                )

            with st.expander("📝 Ver Resumen Listado (Técnico | Tipo | Cantidad | Promedio | Rendimiento)", expanded=True):
                df_listado_unido = df_matriz_input.sort_values(['TECNICO', 'Ordenes'], ascending=[True, False])
                st.dataframe(
                    df_listado_unido,
                    column_config={
                        "TECNICO": "👨‍🔧 Técnico",
                        "TipoOrden": "🛠️ Tipo de Actividad",
                        "Ordenes": st.column_config.NumberColumn("📦 Cantidad", format="%d 🏗️"),
                        "MinProm": st.column_config.ProgressColumn(
                            "⏳ Tiempo Promedio", help="Minutos promedio por orden",
                            min_value=0, max_value=180, format="%.1f min"
                        ),
                        "Rendimiento_Prom": st.column_config.NumberColumn("📈 Rendimiento", format="%.1f %%")
                    },
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("No hay datos suficientes para generar la matriz de actividad.")

        # ================================================================
        # TAB 2: TABLA MAESTRA INTEGRAL
        # ================================================================
        with tab_maestra:
            st.markdown("### 📋 Vista Consolidada Integral")
            
            total_no_presentados = df_m['DÍAS NO PRESENTADO'].sum()
            if total_no_presentados > 0:
                st.warning(f"⚠️ Se detectaron **{total_no_presentados} día(s)** con comentarios de inasistencia en la nube para el grupo actual.")

            st.dataframe(
                df_m,
                use_container_width=True,
                hide_index=True
            )

            try:
                pdf_bytes = generar_pdf_rendimiento_integral_360(df_m, df_tipo_ord, df_exp_det)
                if pdf_bytes:
                    st.download_button(
                        "📄 Descargar Reporte PDF 360°",
                        data=pdf_bytes,
                        file_name="Reporte_Gerencial_Integral.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
            except Exception as e:
                st.error(f"No se pudo generar el PDF. Asegúrate de haber pegado el código en tools.py. Error: {e}")
    # ================================================================
    # TAB 3: REGISTRO DISCIPLINARIO
    # ================================================================
    with tab_exp:
        st.markdown("### 🚨 Registro Disciplinario")

        if df_exp_det is not None and not df_exp_det.empty:
            df_e_fil = df_exp_det.copy()

            if not df_e_fil.empty:
                st.markdown("#### 🔎 Consultar Incidencias por Técnico")
                st.caption("Selecciona un técnico de la lista para ver el detalle al instante.")

                tecnicos_con_exp = sorted(df_e_fil['TEC_MAESTRO'].dropna().unique())

                tec_seleccionado = st.selectbox(
                    "👤 Seleccionar Técnico:",
                    ["-- Selecciona un técnico --"] + tecnicos_con_exp,
                    key="sel_tec_disciplina"
                )

                if tec_seleccionado != "-- Selecciona un técnico --":
                    df_inc_tec = df_e_fil[df_e_fil['TEC_MAESTRO'] == tec_seleccionado].copy()

                    cols_excluir = {'TEC_MAESTRO', 'ES_FALTA', 'ES_NO_PRESENTADO'}
                    cols_mostrar = [c for c in df_inc_tec.columns if c not in cols_excluir]

                    st.markdown("---")
                    st.markdown(f"#### 📁 Incidencias registradas para: **{tec_seleccionado}**")

                    total_inc = len(df_inc_tec)
                    dias_no_pres = int(df_inc_tec['ES_NO_PRESENTADO'].sum()) if 'ES_NO_PRESENTADO' in df_inc_tec.columns else 0
                    faltas_tipo = int(df_inc_tec['ES_FALTA'].sum()) if 'ES_FALTA' in df_inc_tec.columns else 0

                    ki1, ki2, ki3 = st.columns(3)
                    ki1.metric("📋 Total Registros", total_inc)
                    ki2.metric("🚫 Días No Presentado", dias_no_pres)
                    ki3.metric("📌 Faltas Registradas", faltas_tipo)

                    def highlight_exp_row(row):
                        if 'ES_NO_PRESENTADO' in df_inc_tec.columns:
                            idx = row.name
                            if idx in df_inc_tec.index and df_inc_tec.loc[idx, 'ES_NO_PRESENTADO']:
                                return ['background-color: #fee2e2; color: #991b1b'] * len(row)
                        if 'ES_FALTA' in df_inc_tec.columns:
                            idx = row.name
                            if idx in df_inc_tec.index and df_inc_tec.loc[idx, 'ES_FALTA']:
                                return ['background-color: #fef3c7; color: #92400e'] * len(row)
                        return [''] * len(row)

                    df_mostrar_tec = df_inc_tec[cols_mostrar].reset_index(drop=True)
                    st.dataframe(
                        df_mostrar_tec.style.apply(highlight_exp_row, axis=1),
                        use_container_width=True,
                        hide_index=True
                    )

                st.markdown("---")
                st.markdown("#### 📊 Vista General — Todos los Registros Disciplinarios")
                cols_mostrar_gral = [c for c in df_e_fil.columns if c not in {'TEC_MAESTRO', 'ES_FALTA', 'ES_NO_PRESENTADO'}]
                st.dataframe(df_e_fil[cols_mostrar_gral], use_container_width=True, hide_index=True)

            else:
                st.success("✨ ¡Excelente! Los técnicos seleccionados no tienen incidencias ni llamados de atención.")
        else:
            st.info("La base de datos de expedientes está limpia o no ha sido sincronizada.")
