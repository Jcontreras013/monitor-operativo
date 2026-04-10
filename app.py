import streamlit as st
import pandas as pd
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as dt_time
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt
from streamlit_js_eval import streamlit_js_eval

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'. Asegúrate de crearlo en la misma carpeta para ver la Auditoría de Vehículos.")

try:
    from tools import (
        COLUMNS_MAPPING, 
        es_offline_preciso, 
        procesar_dataframe_base, 
        depurar_archivos_en_crudo,
        logica_generar_pdf,
        generar_pdf_cierre_diario,
        generar_pdf_semanal,
        generar_pdf_mensual,
        generar_pdf_trimestral_detallado
    )
except ImportError:
    st.error("⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'. Asegúrese de que ambos archivos estén en la misma carpeta.")

# ==============================================================================
# 1. CONFIGURACIÓN INICIAL DE LA INTERFAZ
# ==============================================================================
st.set_page_config(
    layout="wide", 
    page_title="Monitor Operativo Maxcom PRO", 
    page_icon="⚡",
    initial_sidebar_state="expanded" 
)

# ==============================================================================
# 📱 MODO APP NATIVA (CSS SEGURO Y BLOQUEO NUCLEAR DE RECARGA)
# ==============================================================================
estilo_app_nativa = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 1rem !important;
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
}

/* 🚨 BLOQUEO NUCLEAR DEL PULL-TO-REFRESH (ANTI-RECARGA) 🚨 */
:root {
    overscroll-behavior: none !important;
}

html, body, #root, .stApp, [data-testid="stAppViewContainer"], .main {
    overscroll-behavior: none !important;
    overscroll-behavior-y: none !important;
    overscroll-behavior-x: none !important;
}
</style>
"""
st.markdown(estilo_app_nativa, unsafe_allow_html=True)

# PATRONES DE ESTADO
PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
PATRON_SOLO_ASIGNADAS_STR = 'INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

# ==============================================================================
# 🛡️ MOTOR SEGURO DE FECHAS Y ZONA HORARIA
# ==============================================================================
def get_honduras_time():
    """Fuerza la hora de Honduras (UTC-6)"""
    return datetime.utcnow() - timedelta(hours=6)

def parse_date_ultra_safe(val):
    if pd.isnull(val) or str(val).strip() == "" or str(val).upper() in ["NONE", "NAN", "NAT", "NULL"]:
        return pd.NaT
    
    str_val = str(val).strip()
    
    if str_val in ["0", "0.0", "00:00", "00:00:00", "12:00:00 AM", "1899-12-30 00:00:00"]:
        return pd.NaT

    hoy = pd.Timestamp(get_honduras_time()).normalize()

    try:
        if isinstance(val, dt_time):
            if val.hour == 0 and val.minute == 0: return pd.NaT
            return pd.Timestamp.combine(hoy.date(), val)

        if isinstance(val, datetime):
            if val.hour == 0 and val.minute == 0 and val.second == 0: return pd.NaT
            if val.year <= 1970:
                return hoy + pd.Timedelta(hours=val.hour, minutes=val.minute, seconds=val.second)
            return pd.Timestamp(val)
        
        if isinstance(val, (int, float)):
            if val == 0 or val == 0.0: return pd.NaT
            if val > 10000:
                dt = pd.to_datetime(val, unit='D', origin='1899-12-30')
                if dt.hour == 0 and dt.minute == 0: return pd.NaT
                return dt
            elif 0 < val < 1:
                return hoy + pd.to_timedelta(val, unit='D')
            else:
                return pd.NaT

        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', str_val):
            if str_val.startswith("00:00") or str_val == "0:00": return pd.NaT
            parsed_time = pd.to_datetime(str_val).time()
            return pd.Timestamp.combine(hoy.date(), parsed_time)

        if re.match(r'^\d{4}-\d{2}-\d{2}', str_val):
            parsed = pd.to_datetime(str_val, errors='coerce')
        else:
            parsed = pd.to_datetime(str_val, dayfirst=True, errors='coerce')

        if pd.notnull(parsed):
            if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0: return pd.NaT
            if parsed.year <= 1970:
                return hoy + pd.Timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
            return parsed
            
        return pd.NaT
    except:
        return pd.NaT

def procesar_fechas_seguro(df_input, columnas):
    df = df_input.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = df[col].apply(parse_date_ultra_safe)
    return df

# ==============================================================================
# FUNCIÓN DE PROCESAMIENTO GERENCIAL
# ==============================================================================
def generar_tablas_gerenciales(df_crudo):
    df = df_crudo.copy()
    
    df['HORA_INI'] = df['HORA_INI'].apply(parse_date_ultra_safe)
    df['HORA_LIQ'] = df['HORA_LIQ'].apply(parse_date_ultra_safe)
    
    df = df.dropna(subset=['HORA_INI', 'HORA_LIQ'])
    df['FECHA'] = df['HORA_LIQ'].dt.date
    
    totales_tec = df.groupby('TECNICO').size().reset_index(name='Total_Tecnico')
    conteo_act = df.groupby(['TECNICO', 'ACTIVIDAD']).size().reset_index(name='Cantidad')
    tabla_produccion = pd.merge(conteo_act, totales_tec, on='TECNICO')
    tabla_produccion['Participacion_%'] = (tabla_produccion['Cantidad'] / tabla_produccion['Total_Tecnico'] * 100).round(1)

    df['MINUTOS'] = (df['HORA_LIQ'] - df['HORA_INI']).dt.total_seconds() / 60
    df.loc[df['MINUTOS'] <= 0, 'MINUTOS'] = None 
    
    tabla_eficiencia = df.groupby(['TECNICO', 'ACTIVIDAD'])['MINUTOS'].mean().reset_index()
    tabla_eficiencia.columns = ['TECNICO', 'ACTIVIDAD', 'Promedio_Minutos']
    tabla_eficiencia['Promedio_Minutos'] = tabla_eficiencia['Promedio_Minutos'].round(1)

    jornada = df.groupby(['TECNICO', 'FECHA']).agg(
        Hora_Apertura=('HORA_INI', 'min'),
        Hora_Cierre=('HORA_LIQ', 'max'),
        Total_Ordenes=('NUM', 'count')
    ).reset_index()
    
    jornada['Horas_En_Calle'] = (jornada['Hora_Cierre'] - jornada['Hora_Apertura']).dt.total_seconds() / 3600
    jornada.loc[jornada['Horas_En_Calle'] <= 0, 'Horas_En_Calle'] = None

    resumen_jornada = jornada.groupby('TECNICO').agg(
        Promedio_Horas_Dia=('Horas_En_Calle', 'mean'),
        Dias_Laborados=('FECHA', 'nunique'),
        Max_Horas_Dia=('Horas_En_Calle', 'max')
    ).reset_index()
    
    resumen_jornada['Promedio_Horas_Dia'] = resumen_jornada['Promedio_Horas_Dia'].round(2)
    resumen_jornada['Max_Horas_Dia'] = resumen_jornada['Max_Horas_Dia'].round(2)

    return tabla_produccion, tabla_eficiencia, resumen_jornada

# ==============================================================================
# FUNCIÓN COMPARTIDA DE SINCRONIZACIÓN
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("Descargando historial y limpiando duplicados..."):
            df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
            
            if not df_nube.empty:
                df_nube = df_nube.dropna(how='all')
                df_nube.columns = df_nube.columns.str.upper().str.strip()

                if 'SUSCRIPTOR' in df_nube.columns and 'NOMBRE' not in df_nube.columns:
                    df_nube.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns:
                    df_nube.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE_CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns:
                    df_nube.rename(columns={'NOMBRE_CLIENTE': 'NOMBRE'}, inplace=True)

                df_nube = procesar_fechas_seguro(df_nube, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
                
                if 'HORA_INI' in df_nube.columns and 'HORA_LIQ' in df_nube.columns:
                    df_nube['MINUTOS_CALC'] = (df_nube['HORA_LIQ'] - df_nube['HORA_INI']).dt.total_seconds() / 60
                    df_nube['MINUTOS_CALC'] = df_nube['MINUTOS_CALC'].fillna(0.0)
                    
                    def format_duracion_recalculada(r):
                        if pd.isnull(r['HORA_INI']) or pd.isnull(r['HORA_LIQ']): return "---"
                        diff = r['HORA_LIQ'] - r['HORA_INI']
                        hrs, rem = divmod(diff.total_seconds(), 3600)
                        mins, _ = divmod(rem, 60)
                        return f"{int(hrs)}h {int(mins)}m"
                    df_nube['TIEMPO_REAL'] = df_nube.apply(format_duracion_recalculada, axis=1)

                for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
                    if col_b in df_nube.columns:
                        df_nube[col_b] = df_nube[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])

                if 'ACTIVIDAD' in df_nube.columns:
                    act_upper = df_nube['ACTIVIDAD'].astype(str).str.upper()
                    mask_falsos = act_upper.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
                    mask_solo_sop = act_upper.str.contains('SOP|FIBRA', na=False)
                    
                    if 'ES_OFFLINE' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ES_OFFLINE'] = False
                        df_nube.loc[~mask_solo_sop, 'ES_OFFLINE'] = False
                        
                    if 'ALERTA_TIEMPO' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ALERTA_TIEMPO'] = False
                        df_nube.loc[~mask_solo_sop, 'ALERTA_TIEMPO'] = False
                
                for col_txt in ['NUM', 'CLIENTE']:
                    if col_txt in df_nube.columns:
                        df_nube[col_txt] = pd.to_numeric(df_nube[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
                        df_nube[col_txt] = df_nube[col_txt].replace('0', 'N/D')
                        
                if 'NUM' in df_nube.columns:
                    temp_date = df_nube.get('HORA_LIQ', df_nube.get('FECHA_APE', pd.NaT))
                    df_nube['FECHA_SORT'] = pd.to_datetime(temp_date, errors='coerce')
                    df_nube = df_nube.sort_values(by='FECHA_SORT', na_position='first')
                    
                    df_validos = df_nube[df_nube['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                    df_invalidos = df_nube[df_nube['NUM'] == 'N/D']
                    df_nube = pd.concat([df_validos, df_invalidos])
                    df_nube = df_nube.drop(columns=['FECHA_SORT'], errors='ignore')
                        
                if 'DIAS_RETRASO' in df_nube.columns:
                    df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)

                if 'ESTADO' in df_nube.columns:
                    df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                ahora_momento_ts = pd.Timestamp(get_honduras_time())
                fecha_limite_7d = ahora_momento_ts - timedelta(days=7) 
                
                if 'HORA_LIQ' in df_nube.columns and 'FECHA_APE' in df_nube.columns and 'ESTADO' in df_nube.columns:
                    mask_vivas = df_nube['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                    df_nube = df_nube[
                        (df_nube['HORA_LIQ'] >= fecha_limite_7d) | 
                        (df_nube['FECHA_APE'] >= fecha_limite_7d) | 
                        (df_nube['HORA_LIQ'].isna()) |
                        mask_vivas
                    ].copy()

                cols_orden_ideal = [
                    'DIAS_RETRASO', 'NUM', 'ACTIVIDAD', 'CLIENTE', 'NOMBRE', 'COLONIA',
                    'TECNICO', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL',
                    'ESTADO', 'COMENTARIO', 'ES_OFFLINE', 'MINUTOS_CALC', 'SEGMENTO', 'ALERTA_TIEMPO'
                ]
                cols_presentes = [c for c in cols_orden_ideal if c in df_nube.columns]
                cols_restantes = [c for c in df_nube.columns if c not in cols_presentes]
                df_nube = df_nube[cols_presentes + cols_restantes]

                st.session_state.df_base = df_nube
                st.success("✅ Sincronización Exitosa. Datos históricos cargados y limpios.")
                st.rerun()
            else:
                st.warning("La base de datos en la nube está vacía.")
    except Exception as e:
        st.error(f"Error al conectar con la nube: {e}")

# ==============================================================================
# VENTANAS EMERGENTES (MODALES)
# ==============================================================================
@st.dialog("Detalle de Gestión de la Orden")
def mostrar_comentario_cierre(fila):
    st.markdown(f"### 📋 Información Detallada: Orden N° {fila['NUM']}")
    
    col_modal_a, col_modal_b = st.columns(2)
    with col_modal_a:
        st.markdown("##### 👤 Datos del Cliente")
        st.write(f"**N° Cuenta:** {fila.get('CLIENTE', 'N/D')}")
        nombre_real = fila.get('NOMBRE', fila.get('SUSCRIPTOR', fila.get('NOMBRE CLIENTE', fila.get('NOMBRE_CLIENTE', 'N/D'))))
        if nombre_real != 'N/D':
            st.write(f"**Nombre:** {nombre_real}")
        st.write(f"**Ubicación (Colonia):** {fila.get('COLONIA', 'N/D')}")
    with col_modal_b:
        st.markdown("##### 🚦 Datos de Operación")
        st.write(f"**Estado Actual:** {fila['ESTADO']}")
        st.write(f"**Técnico:** {fila['TECNICO']}")
        if 'MX' in fila: st.write(f"**Vehículo:** {fila.get('MX', 'S/N')}")
        if 'GPS' in fila: st.write(f"**GPS:** {fila.get('GPS', 'S/N')}")
    
    st.divider()
    estatus_final_check = str(fila.get('ESTADO','')).upper().strip()
    if estatus_final_check == 'CERRADA':
        st.success("✅ **COMENTARIO DE LIQUIDACIÓN / CIERRE FINAL:**")
    else:
        st.markdown("**📝 COMENTARIO DE SEGUIMIENTO (EN PROCESO):**")
        
    texto_comentario_registrado = fila.get('COMENTARIO', '')
    if pd.isnull(texto_comentario_registrado) or texto_comentario_registrado == "":
        texto_comentario_registrado = "No existen observaciones registradas para esta gestión."
    st.info(texto_comentario_registrado)
    if st.button("Cerrar Detalles y Volver al Monitor", use_container_width=True):
        st.rerun()

@st.dialog("Resumen de Operaciones")
def mostrar_detalle_avance(segmento, asignadas_df, cerradas_df):
    st.subheader(f"📊 Desglose: {segmento}")
    
    if not asignadas_df.empty:
        p = asignadas_df.groupby('ACTIVIDAD').size().reset_index(name='Carga Total Asignada')
    else:
        p = pd.DataFrame(columns=['ACTIVIDAD', 'Carga Total Asignada'])

    if not cerradas_df.empty:
        c = cerradas_df.groupby('ACTIVIDAD').size().reset_index(name='Cerradas Hoy')
    else:
        c = pd.DataFrame(columns=['ACTIVIDAD', 'Cerradas Hoy'])

    resumen = pd.merge(p, c, on='ACTIVIDAD', how='outer').fillna(0)

    if not resumen.empty:
        resumen['Carga Total Asignada'] = resumen['Carga Total Asignada'].astype(int)
        resumen['Cerradas Hoy'] = resumen['Cerradas Hoy'].astype(int)
        resumen.rename(columns={'ACTIVIDAD': 'Actividad Realizada'}, inplace=True)
        resumen = resumen.sort_values(by='Actividad Realizada').reset_index(drop=True)

        total_p = resumen['Carga Total Asignada'].sum()
        total_c = resumen['Cerradas Hoy'].sum()
        fila_total = pd.DataFrame([{'Actividad Realizada': 'TOTAL GENERAL', 'Carga Total Asignada': total_p, 'Cerradas Hoy': total_c}])
        resumen = pd.concat([resumen, fila_total], ignore_index=True)

        # 🚨 MOSTRAR COMO DATAFRAME SIMPLE PARA EVITAR BUG DE COLUMNAS EN BLANCO
        st.dataframe(resumen, use_container_width=True, hide_index=True)
    else:
        st.info("No hay datos de operaciones para este segmento.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar Resumen", use_container_width=True):
        st.rerun()

# ==============================================================================
# LÓGICA DE ESTILOS VISUALES 
# ==============================================================================
def aplicar_estilos_df(df_original_para_estilo):
    df_visual_procesado = df_original_para_estilo.copy()
    
    def row_styler_logic(fila_v):
        estilos_fila = [''] * len(fila_v)
        if fila_v.get('ES_OFFLINE') == True:
            if 'NUM' in fila_v.index:
                estilos_fila[fila_v.index.get_loc('NUM')] = 'background-color: #9b111e; color: white; font-weight: bold'
        
        est_val = str(fila_v.get('ESTADO','')).upper().strip()
        if est_val == 'CERRADA':
            if 'TIEMPO_REAL' in fila_v.index:
                idx_tr = fila_v.index.get_loc('TIEMPO_REAL')
                minutos_trabajados = fila_v.get('MINUTOS_CALC', 0)
                if minutos_trabajados < 60: estilos_fila[idx_tr] = 'background-color: #4caf50; color: white; font-weight: bold'
                elif minutos_trabajados > 119: estilos_fila[idx_tr] = 'background-color: #d32f2f; color: white; font-weight: bold'

        if fila_v.get('ALERTA_TIEMPO') == True:
            if 'HORA_INI' in fila_v.index:
                estilos_fila[fila_v.index.get_loc('HORA_INI')] = 'background-color: #ff5722; color: white; font-weight: bold'
        
        if 'DIAS_RETRASO' in fila_v.index:
            idx_dias = fila_v.index.get_loc('DIAS_RETRASO')
            val_dias = fila_v['DIAS_RETRASO']
            if val_dias >= 7: estilos_fila[idx_dias] = 'background-color: red; color: white' 
            elif 4 <= val_dias <= 6: estilos_fila[idx_dias] = 'background-color: darkorange; color: white' 
            elif 1 <= val_dias <= 3: estilos_fila[idx_dias] = 'background-color: yellow; color: black' 
            elif val_dias == 0: estilos_fila[idx_dias] = 'background-color: green; color: black' 
                
        return estilos_fila

    if 'NUM' in df_visual_procesado.columns:
        df_visual_procesado['NUM'] = df_visual_procesado.apply(lambda r: f"⚠️ {r['NUM']}" if r.get('ALERTA_TIEMPO') else r['NUM'], axis=1)
    
    if 'HORA_INI' in df_visual_procesado.columns:
        df_visual_procesado['HORA_INI'] = pd.to_datetime(df_visual_procesado['HORA_INI'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    if 'HORA_LIQ' in df_visual_procesado.columns:
        df_visual_procesado['HORA_LIQ'] = pd.to_datetime(df_visual_procesado['HORA_LIQ'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    
    cols_a_mostrar = [
        'DIAS_RETRASO', 'NUM', 'HORA_INI','HORA_LIQ', 'TIEMPO_REAL',
        'ESTADO', 'TECNICO', 'ACTIVIDAD', 'MOTIVO', 'CLIENTE',
        'NOMBRE', 'COLONIA', 'COMENTARIO', 'ES_OFFLINE', 'MINUTOS_CALC'
    ]
    columnas_finales = [c for c in cols_a_mostrar if c in df_visual_procesado.columns]
    return df_visual_procesado[columnas_finales], row_styler_logic

# ==============================================================================
# FUNCIÓN MAESTRA DE CARGA Y DEPURACIÓN LOCAL
# ==============================================================================
@st.cache_data(show_spinner="Depurando datos al estilo Macro de Excel...", ttl=60)
def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos)
        
        df_act = procesar_fechas_seguro(df_act, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
        
        ahora_momento_ts = pd.Timestamp(get_honduras_time())
        fecha_limite_7d_ventana = ahora_momento_ts - timedelta(days=7) 
        
        mask_vivas_loc = df_act['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        df_act = df_act[
            (df_act['HORA_LIQ'] >= fecha_limite_7d_ventana) | 
            (df_act['FECHA_APE'] >= fecha_limite_7d_ventana) | 
            (df_act['HORA_LIQ'].isna()) |
            mask_vivas_loc
        ].copy()
        
        df_act['DIAS_RETRASO'] = (ahora_momento_ts.normalize() - df_act['FECHA_APE'].dt.normalize()).dt.days.fillna(0).astype(int)
        df_act.loc[df_act['TECNICO'].str.strip().str.upper() == 'JOSUE MIGUEL SAUCEDA', 'DIAS_RETRASO'] = 0
        
        def alert_2h_logic_diamante(row_check):
            if pd.notnull(row_check['HORA_INI']) and pd.isnull(row_check['HORA_LIQ']):
                m_diff_val = (ahora_momento_ts - row_check['HORA_INI']).total_seconds() / 60
                act_v = str(row_check.get('ACTIVIDAD', '')).upper()
                
                if any(p in act_v for p in ['PLEXISCA', 'PEXTERNO', 'SPLITTEROPT', 'PLEX', 'INS', 'NUEVA', 'ADIC', 'CAMBIO', 'RECU', 'TVADICIONAL', 'MIGRACI']):
                    return False
                if 'SOP' not in act_v and 'FIBRA' not in act_v:
                    return False
                    
                if m_diff_val > 120 and str(row_check.get('ESTADO','')).upper().strip() != 'CERRADA':
                    return True
            return False
            
        df_act['ALERTA_TIEMPO'] = df_act.apply(alert_2h_logic_diamante, axis=1)
        
        def offline_seguro_diamante_logic(r_off):
            if str(r_off.get('TECNICO', '')).strip().upper() == 'JOSUE MIGUEL SAUCEDA': return False
            if str(r_off.get('ESTADO','')).upper().strip() == 'CERRADA': return False
            act_v_name = str(r_off.get('ACTIVIDAD', '')).upper()
            
            if any(p in act_v_name for p in ['PLEXISCA', 'PEXTERNO', 'SPLITTEROPT', 'PLEX', 'INS', 'NUEVA', 'ADIC', 'CAMBIO', 'RECU', 'TVADICIONAL', 'MIGRACI']): 
                return False
            if 'SOP' not in act_v_name and 'FIBRA' not in act_v_name: 
                return False

            comentario_v_val = str(r_off.get('COMENTARIO', '')).upper()
            if "ONU OFFLINE" in comentario_v_val or "OFF LINE" in comentario_v_val or "FUERA DE SERVICIO" in comentario_v_val or "OFFLINE" in comentario_v_val: return True
            return es_offline_preciso(comentario_v_val)
        
        df_act['ES_OFFLINE'] = df_act.apply(offline_seguro_diamante_logic, axis=1)
        df_act['MINUTOS_CALC'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds() / 60
        
        def segmentar_plex_diamante_logic(r_seg):
            texto_p_scan = f"{r_seg.get('ACTIVIDAD', '')} {r_seg.get('CLIENTE', '')} {r_seg.get('COMENTARIO', '')}".upper()
            if re.search(r'PLEX|PEXTERNO|SPLITTEROPT', texto_p_scan): return 'PLEX'
            return 'RESIDENCIAL'
        df_act['SEGMENTO'] = df_act.apply(segmentar_plex_diamante_logic, axis=1)
        
        def format_duracion_diamante_human(r_dur):
            if pd.isnull(r_dur['HORA_INI']) or pd.isnull(r_dur['HORA_LIQ']): return "---"
            diff_temporal = r_dur['HORA_LIQ'] - r_dur['HORA_INI']
            hrs_val, segs_rem = divmod(diff_temporal.total_seconds(), 3600)
            mins_val, _ = divmod(segs_rem, 60)
            return f"{int(hrs_val)}h {int(mins_val)}m"
        df_act['TIEMPO_REAL'] = df_act.apply(format_duracion_diamante_human, axis=1)
        
        return df_act, df_hst
    except Exception as e:
        st.error(f"❌ Error fatal en el motor de depuración: {e}")
        return None, None

# ==============================================================================
# INTERFAZ PRINCIPAL (MAIN)
# ==============================================================================
def main():
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    
    ancho_pantalla = streamlit_js_eval(js_expressions='window.innerWidth', key='WIDTH_CHECK', want_output=True)
    es_movil = (ancho_pantalla is not None) and (ancho_pantalla < 800)

    if rol_usuario in ['admin', 'jefe']:
        es_movil = False

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error("Error al inicializar la conexión con Google Sheets. Verifica tus secretos.")
        conn = None

    sidebar_top = st.sidebar.container()
    sidebar_bottom = st.sidebar.container()
    
    with sidebar_bottom:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.divider()

        st.markdown("### ☁️ Sincronización")
        if st.button("📥 ACTUALIZAR DESDE LA NUBE", help="Sincronizar con Google Sheets", use_container_width=True, key="btn_nube_sidebar"):
            if conn is not None:
                sincronizar_datos_nube(conn)
            else:
                st.error("La conexión a la nube no está disponible.")

        st.markdown("<br>", unsafe_allow_html=True)
        mostrar_boton_logout()

        mostrar_cargador = False
        if rol_usuario == 'admin':
            mostrar_cargador = True
        elif rol_usuario == 'jefe' and not es_movil:
            mostrar_cargador = True

        file_act_ptr = None
        file_disp_ptr = None
        btn_reprocesar = False
        
        if mostrar_cargador:
            st.divider()
            st.markdown("### 📥 Archivos Crudos (Modo PC)")
            archivos_uploader_diamante = st.file_uploader(
                "Sube rep_actividades y FttxActiveDevice", 
                type=["xlsx", "csv"], 
                accept_multiple_files=True
            )
            
            if archivos_uploader_diamante:
                for file_item in archivos_uploader_diamante:
                    f_name_lwr = file_item.name.lower()
                    if "actividades" in f_name_lwr: file_act_ptr = file_item
                    elif "device" in f_name_lwr or "dispositivos" in f_name_lwr: file_disp_ptr = file_item

            btn_reprocesar = st.button("🔄 ACTUALIZAR TODO", use_container_width=True)
        elif rol_usuario == 'jefe' and es_movil:
            st.caption("📱 _Modo Móvil: Usa el botón de arriba para actualizar._")

    if 'df_base' not in st.session_state or btn_reprocesar:
        if file_act_ptr is None or file_disp_ptr is None:
            if st.session_state.get('df_base') is None:
                st.title("⚡ Monitor Operativo Maxcom PRO")
                st.info("💡 Sesión iniciada correctamente. Los datos de la operación no están cargados en memoria.")
                
                st.markdown("<br><br>", unsafe_allow_html=True)
                col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
                with col_c2:
                    if st.button("📥 DESCARGAR DATOS AHORA", type="primary", use_container_width=True, key="btn_nube_central"):
                        if conn is not None:
                            sincronizar_datos_nube(conn)
                        else:
                            st.error("Conexión no disponible.")
                return
        else:
            res_p_diamante, res_h_diamante = cargar_y_limpiar_crudos_diamante_monitor(file_act_ptr, file_disp_ptr)
            if res_p_diamante is not None:
                st.session_state.df_base = res_p_diamante
                st.session_state.df_hist = res_h_diamante
                
                if conn is not None:
                    with st.spinner("☁️ Sincronizando y uniendo con histórico..."):
                        try:
                            df_new = res_p_diamante.copy()
                            if 'NUM' in df_new.columns:
                                df_new['NUM'] = pd.to_numeric(df_new['NUM'], errors='coerce').fillna(0).astype(int).astype(str)
                                df_new['NUM'] = df_new['NUM'].replace('0', 'N/D')
                            
                            df_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                            
                            if not df_cloud.empty:
                                df_cloud.columns = df_cloud.columns.str.upper().str.strip()
                                if 'NUM' in df_cloud.columns:
                                    df_cloud['NUM'] = pd.to_numeric(df_cloud['NUM'], errors='coerce').fillna(0).astype(int).astype(str)
                                    df_cloud['NUM'] = df_cloud['NUM'].replace('0', 'N/D')
                                
                                df_combined = pd.concat([df_cloud, df_new])
                            else:
                                df_combined = df_new
                                
                            if 'NUM' in df_combined.columns:
                                temp_date_c = df_combined.get('HORA_LIQ', df_combined.get('FECHA_APE', pd.NaT))
                                df_combined['FECHA_SORT'] = pd.to_datetime(temp_date_c, errors='coerce')
                                df_combined = df_combined.sort_values(by='FECHA_SORT', na_position='first')
                                
                                df_valid_num = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                                df_nd = df_combined[df_combined['NUM'] == 'N/D']
                                df_combined = pd.concat([df_valid_num, df_nd])
                                df_combined = df_combined.drop(columns=['FECHA_SORT'], errors='ignore')

                            df_to_upload = df_combined.copy()
                            for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                                if c_date in df_to_upload.columns:
                                    df_to_upload[c_date] = pd.to_datetime(df_to_upload[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                                    
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=df_to_upload)
                            st.success("✅ Datos sincronizados y unidos al histórico correctamente sin duplicados.")
                        except Exception as e:
                            st.warning(f"Se procesó localmente, pero falló la sincronización con la nube: {e}")
                else:
                    st.success("✅ Datos procesados localmente.")
            else:
                return

    df_base = st.session_state.df_base.copy()
    
    if 'NUM' in df_base.columns:
        df_base['NUM'] = df_base['NUM'].astype(str)
        temp_date_b = df_base.get('HORA_LIQ', df_base.get('FECHA_APE', pd.NaT))
        df_base['FECHA_SORT'] = pd.to_datetime(temp_date_b, errors='coerce')
        df_base = df_base.sort_values(by='FECHA_SORT', na_position='first')
        
        df_validos = df_base[df_base['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_invalidos = df_base[df_base['NUM'] == 'N/D']
        df_base = pd.concat([df_validos, df_invalidos])
        df_base = df_base.drop(columns=['FECHA_SORT'], errors='ignore')

    df_base = procesar_fechas_seguro(df_base, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])

    if 'SUSCRIPTOR' in df_base.columns and 'NOMBRE' not in df_base.columns:
        df_base.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
    elif 'NOMBRE CLIENTE' in df_base.columns and 'NOMBRE' not in df_base.columns:
        df_base.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)

    for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
        if col_b in df_base.columns:
            df_base[col_b] = df_base[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])
            
    if 'ACTIVIDAD' in df_base.columns:
        act_upper_global = df_base['ACTIVIDAD'].astype(str).str.upper()
        mask_no_criticas_g = act_upper_global.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
        mask_solo_sop_g = act_upper_global.str.contains('SOP|FIBRA', na=False)
        
        if 'ES_OFFLINE' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ES_OFFLINE'] = False
            df_base.loc[~mask_solo_sop_g, 'ES_OFFLINE'] = False
            
        if 'ALERTA_TIEMPO' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ALERTA_TIEMPO'] = False
            df_base.loc[~mask_solo_sop_g, 'ALERTA_TIEMPO'] = False
            
        def extraer_motivo_falla(row):
            act = str(row.get('ACTIVIDAD', '')).upper()
            com = str(row.get('COMENTARIO', '')).upper()
            texto = act + " " + com
            
            if row.get('ES_OFFLINE', False) == True: return "🔴 Offline / Caída"
            if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", texto): return "📦 Instalación / Cambio"
            if re.search("TV|CABLE|SEÑAL", texto): return "📺 Falla de TV"
            if re.search("NIVEL|DB|POTENCIA|ATENU", texto): return "⚡ Niveles Alterados"
            if re.search("NAV|INTERNET|LENT", texto): return "🌐 Lentitud / Navegación"
            
            return "🔧 Mantenimiento General"
            
        df_base['MOTIVO'] = df_base.apply(extraer_motivo_falla, axis=1)

        def extraer_segmento_global(row):
            texto_p_scan = f"{row.get('ACTIVIDAD', '')} {row.get('CLIENTE', '')} {row.get('COMENTARIO', '')}".upper()
            if re.search(r'PLEX|PEXTERNO|SPLITTEROPT', texto_p_scan): return 'PLEX'
            return 'RESIDENCIAL'
            
        df_base['SEGMENTO'] = df_base.apply(extraer_segmento_global, axis=1)

    for col_n in ['DIAS_RETRASO', 'MINUTOS_CALC']:
        if col_n in df_base.columns:
            df_base[col_n] = pd.to_numeric(df_base[col_n], errors='coerce').fillna(0)
            
    for col_txt in ['NUM', 'CLIENTE']:
        if col_txt in df_base.columns:
            df_base[col_txt] = pd.to_numeric(df_base[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
            df_base[col_txt] = df_base[col_txt].replace('0', 'N/D')
    
    ahora_local = get_honduras_time()
    hoy_date_valor = ahora_local.date()

    with sidebar_top:
        if rol_usuario in ['admin', 'jefe']:
            nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "📚 Histórico", "🚫 NOINSTALADO", "📅 REPROGRAMADAS", "🚙 Auditoría Vehículos"])
        else:
            nav_menu_diamante = "⚡ Monitor en Vivo"
            
        df_base_activa = df_base[df_base['DIAS_RETRASO'] >= 0].copy()
        
        filtro_actividad = []
        filtro_estado = []
        filtro_motivo = []
        
        if nav_menu_diamante == "⚡ Monitor en Vivo":
            st.divider()
            st.markdown("### 🎛️ Filtros Múltiples")
            
            lista_actividades = sorted(df_base_activa['ACTIVIDAD'].dropna().unique().tolist())
            lista_estados = sorted(df_base_activa['ESTADO'].dropna().unique().tolist())
            lista_motivos = sorted(df_base_activa['MOTIVO'].dropna().unique().tolist()) if 'MOTIVO' in df_base_activa.columns else []
            
            filtro_actividad = st.multiselect("🛠️ Tipo de Actividad:", options=lista_actividades, default=[], placeholder="Todas las actividades")
            filtro_estado = st.multiselect("🚦 Estado de Orden:", options=lista_estados, default=[], placeholder="Todos los estados")
            filtro_motivo = st.multiselect("⚠️ Motivo / Diagnóstico:", options=lista_motivos, default=[], placeholder="Todos los motivos")
            
        if nav_menu_diamante == "⚡ Monitor en Vivo":
            if rol_usuario in ['admin', 'jefe']:
                st.divider() 
                
            st.header("🔍 Filtros en Vivo")
            m_viva_count = df_base_activa['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            
            mascara_offline_segura = df_base_activa['ES_OFFLINE'] == True
            total_off_count_viva = int((mascara_offline_segura & m_viva_count).sum())
            
            check_criticos_diamante = st.toggle(f"Ver solo Órdenes Críticas ({total_off_count_viva})")
            lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor)
            
            df_monitor_filtrado = df_base_activa.copy()
            
            if len(filtro_actividad) > 0:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
            if len(filtro_estado) > 0:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
            if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
            
            if check_criticos_diamante:
                mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado['ALERTA_TIEMPO']
                mask_sop_fibra = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('SOP|FIBRA', na=False)
                mask_falsos = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
                
                df_monitor_filtrado = df_monitor_filtrado[mask_critica & mask_sop_fibra & ~mask_falsos]
                
            if tec_filtro_monitor != "Todos":
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro_monitor]
        else:
            df_monitor_filtrado = df_base_activa.copy()

    if nav_menu_diamante == "🚙 Auditoría Vehículos":
        try:
            mostrar_auditoria(es_movil, conn)
        except Exception as e:
            st.error(f"Ocurrió un error al cargar el módulo de Auditoría: {e}")
        return

    if nav_menu_diamante == "🚫 NOINSTALADO":
        st.title("🚫 Órdenes NOINSTALADO (Cerradas Hoy)")
        mask_noinst_hoy = (df_base['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)) & (df_base['HORA_LIQ'].dt.date == hoy_date_valor)
        st.dataframe(df_base[mask_noinst_hoy][['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']], use_container_width=True, height=600, hide_index=True)
        return

    if nav_menu_diamante == "📅 REPROGRAMADAS":
        st.title("📅 Órdenes Reprogramadas (Futuras)")
        st.caption("Visor exclusivo de órdenes agendadas para el futuro (Días negativos).")
        mask_reprog = (df_base['DIAS_RETRASO'] < 0)
        df_reprog = df_base[mask_reprog].copy()
        
        st.metric("Total Agendadas a Futuro", len(df_reprog))
        
        if not df_reprog.empty:
            cols_visibles = ['DIAS_RETRASO', 'NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'TECNICO', 'ESTADO', 'COMENTARIO']
            cols_finales = [c for c in cols_visibles if c in df_reprog.columns]
            st.dataframe(
                df_reprog[cols_finales].style.set_properties(
                    **{'background-color': '#1a2a3a', 'color': '#58a6ff', 'font-weight': 'bold'}, 
                    subset=['DIAS_RETRASO']
                ),
                use_container_width=True, height=600, hide_index=True
            )
        else:
            st.success("✅ No hay órdenes reprogramadas para fechas futuras en este momento.")
        return

    if nav_menu_diamante == "📚 Histórico":
        from historico import main_historico
        main_historico(st.session_state.df_hist)
        return

    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        
        tab_dinamico, tab_diario, tab_semanal, tab_mensual, tab_gerencial = st.tabs([
            "⚡ Reporte Dinámico", "📦 Cierre Diario", "🗓️ Analítico Semanal", "🏢 Macro Mensual", "💼 Gerencial (Trimestral)"
        ])

        with tab_dinamico:
            st.subheader("📄 Reporte Dinámico en Vivo")
            col_f1, col_f2 = st.columns(2)
            m_viva_rep = df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            total_off_rep = int((df_base['ES_OFFLINE'] == True & m_viva_rep).sum())
            
            with col_f1: check_criticos_rep = st.toggle(f"Filtrar solo Críticas ({total_off_rep})", key="tgg_rep")
            with col_f2: tec_filtro_rep = st.selectbox("Filtrar por Técnico:", ["Todos"] + sorted(df_base['TECNICO'].dropna().unique().tolist()), key="sel_tec_rep")
                
            df_dinamico_filtrado = df_base.copy()
            if check_criticos_rep: df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['ES_OFFLINE'] | df_dinamico_filtrado['ALERTA_TIEMPO']]
            if tec_filtro_rep != "Todos": df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['TECNICO'] == tec_filtro_rep]
                
            if st.button("📄 GENERAR REPORTE DINÁMICO (PDF)", use_container_width=True, type="primary"):
                pdf_bytes_rendimiento = logica_generar_pdf(df_dinamico_filtrado)
                st.download_button("📥 Descargar PDF Dinámico", data=pdf_bytes_rendimiento, file_name=f"Reporte_Dinamico_{hoy_date_valor}.pdf")

        with tab_gerencial:
            st.subheader("📊 Reporte Gerencial Unificado")
            st.caption("Sube el archivo en crudo. El sistema cruzará la productividad, tiempos y jornadas en una sola tabla maestra.")
            
            archivo_gerencial = st.file_uploader("📂 Subir Reporte de Actividades (Excel/CSV)", type=['xlsx', 'csv'], key="uploader_gerencial")
            
            if archivo_gerencial:
                with st.spinner("⏳ Analizando datos, cruzando tablas y calculando jornadas..."):
                    try:
                        if archivo_gerencial.name.endswith('.csv'): df_raw = pd.read_csv(archivo_gerencial)
                        else: df_raw = pd.read_excel(archivo_gerencial)
                        
                        df_limpio = procesar_dataframe_base(df_raw)
                        tabla_prod, tabla_efi, res_jornada = generar_tablas_gerenciales(df_limpio)
                        
                        df_merge_1 = pd.merge(tabla_prod, tabla_efi, on=['TECNICO', 'ACTIVIDAD'], how='left')
                        df_maestra = pd.merge(df_merge_1, res_jornada, on='TECNICO', how='left')
                        
                        df_maestra = df_maestra.rename(columns={
                            'TECNICO': 'Técnico',
                            'Dias_Laborados': 'Días Trabajados',
                            'Promedio_Horas_Dia': 'Hrs / Día',
                            'ACTIVIDAD': 'Actividad',
                            'Cantidad': 'Volumen',
                            'Participacion_%': '% del Total',
                            'Promedio_Minutos': 'Min. Promedio'
                        })
                        
                        columnas_ordenadas = ['Técnico', 'Días Trabajados', 'Hrs / Día', 'Actividad', 'Volumen', '% del Total', 'Min. Promedio']
                        df_maestra = df_maestra[columnas_ordenadas]
                        
                        st.success("✅ Datos procesados y unificados correctamente.")
                        
                        ordenes_con_error = df_maestra['Min. Promedio'].isna().sum()
                        if ordenes_con_error > 0:
                            st.warning(f"⚠️ Se detectaron {ordenes_con_error} órdenes con errores de tiempo (negativos/cero). Se incluyeron en el volumen de producción pero se ignoraron para el promedio de minutos.")

                        st.dataframe(
                            df_maestra,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Técnico": st.column_config.TextColumn("👨‍🔧 Técnico", width="medium"),
                                "Días Trabajados": st.column_config.NumberColumn("📅 Días", format="%d"),
                                "Hrs / Día": st.column_config.NumberColumn("⏱️ Hrs/Día", format="%.1f h"),
                                "Actividad": st.column_config.TextColumn("🛠️ Actividad", width="medium"),
                                "Volumen": st.column_config.NumberColumn("📦 Volumen", format="%d ord."),
                                "% del Total": st.column_config.ProgressColumn("📊 Participación", format="%.1f%%", min_value=0, max_value=100),
                                "Min. Promedio": st.column_config.NumberColumn("⏳ Min. Prom.", format="%.0f min")
                            }
                        )
                        
                        st.divider()
                        
                        if st.button("🚀 GENERAR PDF GERENCIAL COMPLETO", use_container_width=True, type="primary"):
                            with st.spinner("Dibujando secciones por técnico..."):
                                pdf_bytes = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                                st.download_button(
                                    label="📥 Descargar Reporte PDF",
                                    data=pdf_bytes,
                                    file_name=f"Reporte_Gerencial_{datetime.now().strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    type="primary",
                                    use_container_width=True
                                )
                    except Exception as e:
                        st.error(f"❌ Ocurrió un error procesando el reporte: {e}")
        
        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor)
            
            mask_tec_valido_rep = (
                df_base['TECNICO'].notna() & 
                (df_base['TECNICO'].astype(str).str.strip() != '') & 
                (~df_base['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
            )
            df_base_valido_rep = df_base[mask_tec_valido_rep]

            df_cierre_filtrado = df_base_valido_rep[(df_base_valido_rep['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_base_valido_rep['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()
            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cierre_filtrado))
            
            st.markdown("### 📊 Indicadores de Avance Operativo")
            
            # 🚨 AQUÍ EL TOTAL DE LA CARGA (ASIGNADAS + PENDIENTES TOTALES DE LA EMPRESA)
            mask_totales_dia = (
                (df_base['FECHA_APE'].dt.date <= fecha_cal_sel) & 
                (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False))
            )
            df_vivas_totales_hoy = df_base[mask_totales_dia]
            
            df_plex_pend_rep = df_vivas_totales_hoy[df_vivas_totales_hoy['SEGMENTO'] == 'PLEX']
            df_plex_cerr_rep = df_cierre_filtrado[df_cierre_filtrado['SEGMENTO'] == 'PLEX']
            
            df_resi_pend_rep = df_vivas_totales_hoy[df_vivas_totales_hoy['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_cerr_rep = df_cierre_filtrado[df_cierre_filtrado['SEGMENTO'] == 'RESIDENCIAL']

            total_p_rep = len(df_plex_pend_rep) + len(df_plex_cerr_rep)
            avance_plex_rep = (len(df_plex_cerr_rep) / total_p_rep * 100) if total_p_rep > 0 else 0
            
            total_r_rep = len(df_resi_pend_rep) + len(df_resi_cerr_rep)
            avance_resi_rep = (len(df_resi_cerr_rep) / total_r_rep * 100) if total_r_rep > 0 else 0
            
            total_v_rep = len(df_vivas_totales_hoy) + len(df_cierre_filtrado)
            avance_global_rep = (len(df_cierre_filtrado) / total_v_rep * 100) if total_v_rep > 0 else 0

            def crear_velocimetro_rep(valor, titulo):
                color_v = "#EF4444" if valor < 50 else ("#F59E0B" if valor < 80 else "#10B981") 
                fig = go.Figure(go.Pie(
                    values=[valor, max(0, 100 - valor)], labels=['Completado', 'Pendiente'], hole=0.8,
                    marker=dict(colors=[color_v, '#2D2F39']), textinfo='none', hoverinfo='none', direction='clockwise', sort=False
                ))
                fig.update_layout(
                    showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}},
                    annotations=[dict(text=f"{valor:.0f}%", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")]
                )
                return fig

            col_gr1, col_gr2, col_gr3 = st.columns(3)
            with col_gr1: st.plotly_chart(crear_velocimetro_rep(avance_resi_rep, "🏠 Residencial"), use_container_width=True)
            with col_gr2: st.plotly_chart(crear_velocimetro_rep(avance_plex_rep, "🏢 PLEX"), use_container_width=True)
            with col_gr3: st.plotly_chart(crear_velocimetro_rep(avance_global_rep, "🌍 Global"), use_container_width=True)
            
            st.divider()

            if not df_cierre_filtrado.empty:
                st.markdown("### 📊 Desglose de Producción por Categoría")
                cs_col, ci_col, cp_col, co_col = st.columns(4)
                
                with cs_col:
                    st.write("**SOP**")
                    df_sop = df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_sop, hide_index=True, use_container_width=True)
                    st.write(f"**Total SOP: {df_sop['Cant'].sum()}**")
                    
                with ci_col:
                    st.write("**Instalaciones**")
                    txt_ins_c = df_cierre_filtrado['ACTIVIDAD'].astype(str).str.upper() + " " + df_cierre_filtrado['COMENTARIO'].astype(str).str.upper()
                    mask_ins_general = txt_ins_c.str.contains('INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_ins_cierre = df_cierre_filtrado[mask_ins_general].copy()
                    
                    if not df_ins_cierre.empty:
                        def clasificar_ins_cierre(row):
                            txt = (str(row.get('ACTIVIDAD','')) + " " + str(row.get('COMENTARIO',''))).upper()
                            if re.search('ADIC', txt): return 'Adición'
                            if re.search('CAMBIO|MIGRACI', txt): return 'Cambio / Migración'
                            if re.search('RECUP', txt): return 'Recuperado'
                            return 'Nueva'
                        
                        df_ins_cierre['SUBTIPO'] = df_ins_cierre.apply(clasificar_ins_cierre, axis=1)
                        df_ins_grouped = df_ins_cierre['SUBTIPO'].value_counts().reset_index()
                        df_ins_grouped.columns = ['Instalaciones', 'Cant']
                        st.dataframe(df_ins_grouped, hide_index=True, use_container_width=True)
                        st.write(f"**Total INS: {df_ins_grouped['Cant'].sum()}**")
                    else:
                        st.write("Sin datos")
                    
                with cp_col:
                    st.write("**Plex**")
                    df_plex = df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('PLEX|PEXTERNO|SPLITTEROPT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_plex, hide_index=True, use_container_width=True)
                    st.write(f"**Total PLEX: {df_plex['Cant'].sum()}**")
                    
                with co_col:
                    st.write("**Otros**")
                    txt_otr_c = df_cierre_filtrado['ACTIVIDAD'].astype(str).str.upper() + " " + df_cierre_filtrado['COMENTARIO'].astype(str).str.upper()
                    mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|PEXTERNO|SPLITTEROPT|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_otros = df_cierre_filtrado[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_otros, hide_index=True, use_container_width=True)
                    st.write(f"**Total Otros: {df_otros['Cant'].sum()}**")

            st.divider()
            
            # 🚨 AQUÍ EL CONSOLIDADO TOTAL SIN ERRORES DE COLUMNA EN BLANCO
            st.markdown("### 📈 Resumen Consolidado: Carga Asignada vs Cierres")
            
            p_rep = df_vivas_totales_hoy.groupby('ACTIVIDAD').size().reset_index(name='Carga Total Asignada')
            c_rep = df_cierre_filtrado.groupby('ACTIVIDAD').size().reset_index(name='Cerradas Hoy')
            
            resumen_global_rep = pd.merge(p_rep, c_rep, on='ACTIVIDAD', how='outer').fillna(0)
            
            if not resumen_global_rep.empty:
                resumen_global_rep['Carga Total Asignada'] = resumen_global_rep['Carga Total Asignada'].astype(int)
                resumen_global_rep['Cerradas Hoy'] = resumen_global_rep['Cerradas Hoy'].astype(int)
                resumen_global_rep.rename(columns={'ACTIVIDAD': 'Actividad Realizada'}, inplace=True)
                resumen_global_rep = resumen_global_rep.sort_values(by='Actividad Realizada').reset_index(drop=True)
                
                tot_p = resumen_global_rep['Carga Total Asignada'].sum()
                tot_c = resumen_global_rep['Cerradas Hoy'].sum()
                fila_tot = pd.DataFrame([{'Actividad Realizada': 'TOTAL GENERAL', 'Carga Total Asignada': tot_p, 'Cerradas Hoy': tot_c}])
                resumen_global_rep = pd.concat([resumen_global_rep, fila_tot], ignore_index=True)
                
                # Se renderiza de forma sencilla y estable
                st.dataframe(resumen_global_rep, use_container_width=True, hide_index=True)
            else:
                st.info("No hay datos de operaciones consolidadas para esta fecha.")

            st.markdown("### ⏱️ Tiempos de Atención Promedio")
            if not df_cierre_filtrado.empty:
                df_pivot_diario = df_cierre_filtrado.groupby(['TECNICO', 'ACTIVIDAD']).agg(
                    Órdenes=('NUM', 'count'),
                    Prom_Duracion_Min=('MINUTOS_CALC', 'mean')
                ).round(1)
                st.dataframe(df_pivot_diario, use_container_width=True)

            st.markdown("### 📥 Exportación")
            if st.button("🚀 GENERAR PDF DE CIERRE DIARIO", use_container_width=True, type="primary"):
                pdf_bytes_archivo_diario = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
                st.download_button("📥 Descargar Archivo (PDF)", data=pdf_bytes_archivo_diario, file_name=f"Cierre_{fecha_cal_sel}.pdf")
            
            st.divider()
            with st.expander("Ver Lista Detallada"):
                st.dataframe(df_cierre_filtrado[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)

        with tab_semanal:
            st.subheader("Rendimiento y Tiempos Semanales")
            rango_fecha = st.date_input("Rango de evaluación:", value=(hoy_date_valor - timedelta(days=7), hoy_date_valor), key="date_semanal")
            if len(rango_fecha) == 2:
                df_sem = df_base[(df_base['HORA_LIQ'].dt.date >= rango_fecha[0]) & (df_base['HORA_LIQ'].dt.date <= rango_fecha[1]) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))]
                
                if st.button("🚀 GENERAR PDF SEMANAL", use_container_width=True, type="primary"):
                    pdf_sem_bytes = generar_pdf_semanal(df_base, rango_fecha[0], rango_fecha[1])
                    st.download_button("📥 Descargar PDF Semanal", data=pdf_sem_bytes, file_name=f"Semanal_{rango_fecha[0]}_al_{rango_fecha[1]}.pdf")

        with tab_mensual:
            st.subheader("Visión Macro Gerencial")
            col_mes, col_anio = st.columns(2)
            meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            with col_mes: mes_sel = st.selectbox("Mes:", meses, index=hoy_date_valor.month - 1)
            with col_anio: anio_sel = st.number_input("Año:", min_value=2024, max_value=2030, value=2026)
            
            st.markdown("### 🏢 Comparativa Segmento")
            fig_pie_mensual = px.pie(df_base, names='SEGMENTO', hole=.4, template="plotly_dark")
            st.plotly_chart(fig_pie_mensual, use_container_width=True)
            
            if st.button("🚀 GENERAR PDF MENSUAL", use_container_width=True, type="primary"):
                mes_num = meses.index(mes_sel) + 1
                pdf_men_bytes = generar_pdf_mensual(df_base, mes_num, anio_sel)
                st.download_button("📥 Descargar PDF Mensual", data=pdf_men_bytes, file_name=f"Mensual_{mes_sel}_{anio_sel}.pdf")
            
        return

    # ==============================================================================
    # 7. MONITOR OPERATIVO EN VIVO 
    # ==============================================================================
    if nav_menu_diamante == "⚡ Monitor en Vivo":
        
        mask_tec_valido = (
            df_monitor_filtrado['TECNICO'].notna() & 
            (df_monitor_filtrado['TECNICO'].astype(str).str.strip() != '') & 
            (~df_monitor_filtrado['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
        )
        
        # 1. TABLAS DE ARRIBA: EXCLUSIVAS DE LOS TÉCNICOS (SOLO ASIGNADAS)
        df_monitor_valido = df_monitor_filtrado[mask_tec_valido]
        mask_hoy = df_monitor_valido['HORA_LIQ'].dt.date == hoy_date_valor
        mask_solo_asignadas = df_monitor_valido['ESTADO'].astype(str).str.contains(PATRON_SOLO_ASIGNADAS_STR, na=False, case=False)

        df_monitor_vivas_full = df_monitor_valido[mask_hoy | mask_solo_asignadas].copy()
        df_tablero_kpi_monitor = df_monitor_valido[mask_solo_asignadas].copy()

        df_tablero_kpi_monitor['DIAS_RETRASO'] = (pd.Timestamp(ahora_local).normalize() - df_tablero_kpi_monitor['FECHA_APE'].dt.normalize()).dt.days
        df_tablero_kpi_monitor['DIAS_RETRASO'] = df_tablero_kpi_monitor['DIAS_RETRASO'].fillna(0).astype(int)
        
        if 'TECNICO' in df_tablero_kpi_monitor.columns:
            mask_josue_kpi = df_tablero_kpi_monitor['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
            df_tablero_kpi_monitor.loc[mask_josue_kpi, 'DIAS_RETRASO'] = 0

        # RANGOS EXACTOS PARA LOS DÍAS
        df_tablero_kpi_monitor['CatD'] = df_tablero_kpi_monitor['DIAS_RETRASO'].apply(
            lambda d: ">= 7 Dia" if d >= 7 else ("= 4 Dia" if d >= 4 else ("= 1 Dia" if d >= 1 else "= 0 Dia"))
        )

        st.title("⚡ Monitor Operativo Maxcom")

        st.markdown("""
        <style>
        .kpi-container {
            display: flex;
            justify-content: space-between;
            gap: 15px;
            margin-bottom: 20px;
            margin-top: 10px;
        }
        .kpi-card {
            background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%);
            padding: 20px;
            border-radius: 12px;
            border-left: 5px solid #3B82F6; 
            flex: 1;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            border-top: 1px solid #2D2F39;
            border-right: 1px solid #2D2F39;
            border-bottom: 1px solid #2D2F39;
        }
        .kpi-card.green { border-left-color: #10B981; }
        .kpi-card.orange { border-left-color: #F59E0B; }
        .kpi-card.red { border-left-color: #EF4444; }
        
        .kpi-title {
            color: #94A3B8;
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 5px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .kpi-val {
            color: #FFFFFF;
            font-size: 2.2rem;
            font-weight: 700;
            margin: 0;
            line-height: 1.2;
        }
        .kpi-val.text-green { color: #10B981; }
        .kpi-val.text-red { color: #EF4444; }
        </style>
        """, unsafe_allow_html=True)

        vivas_count = len(df_tablero_kpi_monitor)
        cerradas_hoy = len(df_monitor_valido[(df_monitor_valido['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_valido['ESTADO'].str.contains('CERRADA', na=False, case=False))])
        tecs_activos = df_tablero_kpi_monitor['TECNICO'].nunique()
        offline_criticos = int((df_tablero_kpi_monitor.get('ES_OFFLINE', pd.Series([False]*len(df_tablero_kpi_monitor))) == True).sum())

        html_kpis = f"""
        <div class="kpi-container">
            <div class="kpi-card">
                <div class="kpi-title">PENDIENTES ASIGNADAS</div>
                <div class="kpi-val">{vivas_count}</div>
            </div>
            <div class="kpi-card green">
                <div class="kpi-title">CERRADAS HOY</div>
                <div class="kpi-val text-green">{cerradas_hoy}</div>
            </div>
            <div class="kpi-card orange">
                <div class="kpi-title">TÉCNICOS EN RUTA</div>
                <div class="kpi-val">{tecs_activos}</div>
            </div>
            <div class="kpi-card red">
                <div class="kpi-title">CAÍDAS (OFFLINE)</div>
                <div class="kpi-val text-red">{offline_criticos}</div>
            </div>
        </div>
        """
        st.markdown(html_kpis, unsafe_allow_html=True)

        with st.expander("📊 TABLERO DE CARGA ACTUAL (SOLO ÓRDENES ASIGNADAS)", expanded=True):
            col_tab_1, col_tab_2, col_tab_3, col_tab_4 = st.columns([1, 1.2, 1.2, 1])
            
            with col_tab_1:
                st.caption("📅 Resumen de Retraso")
                res_retraso_v = df_tablero_kpi_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 Dia","= 1 Dia","= 0 Dia"], fill_value=0).reset_index()
                res_retraso_v.columns = ['Dias', 'Cant']
                sum_total_pendientes_v = res_retraso_v['Cant'].sum()
                res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_pendientes_v*100):.0f}%" if sum_total_pendientes_v > 0 else "0%")
                
                # 🚨 COLORES DE RETRASO RESTAURADOS 🚨
                def highlight_dias(val):
                    if val == ">= 7 Dia": return 'background-color: #d32f2f; color: white; font-weight: bold'
                    if val == "= 4 Dia": return 'background-color: #f57c00; color: white; font-weight: bold'
                    if val == "= 1 Dia": return 'background-color: #fbc02d; color: black; font-weight: bold'
                    if val == "= 0 Dia": return 'background-color: #388e3c; color: white; font-weight: bold'
                    return ''
                    
                st.dataframe(res_retraso_v.style.map(highlight_dias, subset=['Dias']), hide_index=True, use_container_width=True)
                
            with col_tab_2:
                st.caption("🛠️ SOP / Mantenimiento")
                act_tab_sop = df_tablero_kpi_monitor['ACTIVIDAD'].astype(str).str.upper()
                res_sop_visual_v = {
                    "FTTH / FIBRA": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("FIBRA|FTTH", na=False)]),
                    "Navegación / Internet": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("NAV|INTERNET", na=False)]),
                    "ONT/ONU Offline": int((df_tablero_kpi_monitor['ES_OFFLINE'] == True).sum()), 
                    "Niveles alterados": len(df_tablero_kpi_monitor[df_tablero_kpi_monitor['COMENTARIO'].astype(str).str.upper().str.contains("NIVEL|DB", na=False)]),
                    "Sin señal de TV": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("TV|CABLE", na=False)])
                }
                st.dataframe(pd.DataFrame(list(res_sop_visual_v.items()), columns=['SOP', 'Cant']), hide_index=True, use_container_width=True)
                st.write(f"**Total General SOP: {sum(res_sop_visual_v.values())}**")
                st.metric("Exceden 2 Horas ⚠️", int((df_tablero_kpi_monitor['ALERTA_TIEMPO'] == True).sum()))

            with col_tab_3:
                st.caption("📦 Instalaciones")
                txt_ins_v = df_tablero_kpi_monitor['ACTIVIDAD'].astype(str).str.upper() + " " + df_tablero_kpi_monitor['COMENTARIO'].astype(str).str.upper()
                
                res_ins_visual_v = {
                    "Adición": len(df_tablero_kpi_monitor[txt_ins_v.str.contains("ADIC", na=False)]),
                    "Cambio / Migración": len(df_tablero_kpi_monitor[txt_ins_v.str.contains("CAMBIO|MIGRACI", na=False)]),
                    "Recuperado": len(df_tablero_kpi_monitor[txt_ins_v.str.contains("RECUP", na=False)])
                }
                mask_base_ins = txt_ins_v.str.contains("INS|NUEVA", na=False)
                mask_excl_ins = txt_ins_v.str.contains("ADIC|CAMBIO|MIGRACI|RECUP", na=False)
                res_ins_visual_v["Nueva"] = len(df_tablero_kpi_monitor[mask_base_ins & ~mask_excl_ins])
                
                st.dataframe(pd.DataFrame(list(res_ins_visual_v.items()), columns=['Instalaciones', 'Cant']), hide_index=True, use_container_width=True)
                st.write(f"**Total General INS: {sum(res_ins_visual_v.values())}**")

            with col_tab_4:
                st.caption("⚙️ Otros")
                txt_otr_v = df_tablero_kpi_monitor['ACTIVIDAD'].astype(str).str.upper() + " " + df_tablero_kpi_monitor['COMENTARIO'].astype(str).str.upper()
                mask_otros_monitor = ~txt_otr_v.str.contains("SOP|FALLA|MANT|INS|ADIC|CAMBIO|MIGRACI|NUEVA|RECUP", na=False)
                res_otros_monitor = df_tablero_kpi_monitor[mask_otros_monitor]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                res_otros_monitor.columns = ['Otros', 'Cant']
                st.dataframe(res_otros_monitor.head(8), hide_index=True, use_container_width=True)
                st.write(f"**Total Otros: {res_otros_monitor['Cant'].sum()}**")

        # 🚨 TABLA 2: CONSOLIDADO POR SEGMENTO Y AVANCE (INCLUYE TOTAL DE LA EMPRESA, INCLUSO SIN ASIGNAR)
        with st.expander("📊 CONSOLIDADO POR SEGMENTO Y AVANCE", expanded=False):
            
            mask_todas_vivas = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            df_todas_vivas_monitor = df_monitor_filtrado[mask_todas_vivas]
            
            df_cerradas_hoy_segmento = df_monitor_filtrado[(df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))]
            
            df_plex_pend = df_todas_vivas_monitor[df_todas_vivas_monitor['SEGMENTO'] == 'PLEX']
            df_plex_cerr = df_cerradas_hoy_segmento[df_cerradas_hoy_segmento['SEGMENTO'] == 'PLEX']
            
            df_resi_pend = df_todas_vivas_monitor[df_todas_vivas_monitor['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_cerr = df_cerradas_hoy_segmento[df_cerradas_hoy_segmento['SEGMENTO'] == 'RESIDENCIAL']

            total_p = len(df_plex_pend) + len(df_plex_cerr)
            avance_plex = (len(df_plex_cerr) / total_p * 100) if total_p > 0 else 0
            
            total_r = len(df_resi_pend) + len(df_resi_cerr)
            avance_resi = (len(df_resi_cerr) / total_r * 100) if total_r > 0 else 0
            
            total_v = len(df_todas_vivas_monitor) + len(df_cerradas_hoy_segmento)
            avance_global = (len(df_cerradas_hoy_segmento) / total_v * 100) if total_v > 0 else 0

            def crear_velocimetro_circular(valor, titulo):
                color_v = "#EF4444" if valor < 50 else ("#F59E0B" if valor < 80 else "#10B981") 
                fig = go.Figure(go.Pie(
                    values=[valor, max(0, 100 - valor)],
                    labels=['Completado', 'Pendiente'],
                    hole=0.8,
                    marker=dict(colors=[color_v, '#2D2F39']),
                    textinfo='none',
                    hoverinfo='none',
                    direction='clockwise',
                    sort=False
                ))
                fig.update_layout(
                    showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}},
                    annotations=[dict(text=f"{valor:.0f}%", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")]
                )
                return fig

            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.plotly_chart(crear_velocimetro_circular(avance_resi, "🏠 Avance Residencial"), use_container_width=True, key="pie_resi")
                if st.button("🔍 Ver Resumen Residencial", use_container_width=True, key="btn_resi"):
                    mostrar_detalle_avance("RESIDENCIAL", df_resi_pend, df_resi_cerr)
                    
            with col_g2:
                st.plotly_chart(crear_velocimetro_circular(avance_plex, "🏢 Avance PLEX"), use_container_width=True, key="pie_plex")
                if st.button("🔍 Ver Resumen PLEX", use_container_width=True, key="btn_plex"):
                    mostrar_detalle_avance("PLEX", df_plex_pend, df_plex_cerr)
                
            espacio_izq, col_global, espacio_der = st.columns([1, 1.5, 1])
            
            with col_global:
                st.plotly_chart(crear_velocimetro_circular(avance_global, "🌍 Avance Global"), use_container_width=True, key="pie_global")
                if st.button("🔍 Ver Resumen Global", use_container_width=True, key="btn_global"):
                    mostrar_detalle_avance("GLOBAL", df_todas_vivas_monitor, df_cerradas_hoy_segmento)

        st.divider()
        
        if 'st_btn_v_active' not in st.session_state or st.session_state.st_btn_v_active == "CONSOL": 
            st.session_state.st_btn_v_active = "PENDIENTE"
            
        col_bt1_v, col_bt2_v, col_bt3_v = st.columns(3)
        
        if col_bt1_v.button("⏳ ASIGNADAS ACTIVAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary"): 
            st.session_state.st_btn_v_active = "PENDIENTE"; st.rerun()
        if col_bt2_v.button("✅ CERRADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "C_HOY" else "secondary"): 
            st.session_state.st_btn_v_active = "C_HOY"; st.rerun()
        if col_bt3_v.button("❌ ANULADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "A_HOY" else "secondary"): 
            st.session_state.st_btn_v_active = "A_HOY"; st.rerun()

        status_final_btn = st.session_state.st_btn_v_active

        if status_final_btn == "PENDIENTE": 
            df_v_tabla_monitor = df_tablero_kpi_monitor
        elif status_final_btn == "C_HOY": 
            df_v_tabla_monitor = df_monitor_vivas_full[(df_monitor_vivas_full['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))]
        else: 
            df_v_tabla_monitor = df_monitor_vivas_full[(df_monitor_vivas_full['ESTADO'].astype(str).str.contains('ANULADA', na=False, case=False))]

        t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL DE CONTROL OPERATIVO", "📊 ANALISIS Y GANTT", "📈 ANALÍTICA"])
        
        with t_panel_v:
            if not df_v_tabla_monitor.empty:
                df_estilo_v, _ = aplicar_estilos_df(df_v_tabla_monitor)
                df_mostrar = df_estilo_v.drop(columns=['ES_OFFLINE'], errors='ignore')
                
                evento_monitor_diam = st.dataframe(
                    df_mostrar,
                    column_config={
                        "GPS": st.column_config.LinkColumn("UBICACIÓN GPS"),
                        "NOMBRE": st.column_config.TextColumn("NOMBRE", width="medium"),
                        "COLONIA": st.column_config.TextColumn("COLONIA", width="medium"),
                        "COMENTARIO": st.column_config.TextColumn("COMENTARIO", width="large")
                    }, 
                    use_container_width=True, 
                    height=600, 
                    hide_index=True, 
                    on_select="rerun", 
                    selection_mode="single-row"
                )
                
                if evento_monitor_diam.selection.rows:
                    mostrar_comentario_cierre(df_v_tabla_monitor.iloc[evento_monitor_diam.selection.rows[0]])
            else:
                st.warning("No hay registros disponibles para mostrar.")

        with t_graphs_v:
            df_para_gantt_final = df_v_tabla_monitor[df_v_tabla_monitor['HORA_INI'].notnull()].copy()
            if not df_para_gantt_final.empty:
                df_para_gantt_final['FIN_LIMITE'] = df_para_gantt_final['HORA_LIQ'].fillna(get_honduras_time())
                figura_gantt_final = px.timeline(
                    df_para_gantt_final, x_start="HORA_INI", x_end="FIN_LIMITE", 
                    y="TECNICO", color="ACTIVIDAD", text="ACTIVIDAD", 
                    template="plotly_dark", height=450
                )
                figura_gantt_final.update_yaxes(autorange="reversed")
                st.plotly_chart(figura_gantt_final, use_container_width=True)
                
            st.divider(); st.subheader("📈 Órdenes Cerradas por Hora (Hoy)")
            df_productividad_v = df_base[df_base['HORA_LIQ'].dt.date == hoy_date_valor].copy()
            if not df_productividad_v.empty:
                df_productividad_v['Hr_C'] = df_productividad_v['HORA_LIQ'].dt.hour
                conteo_horario_v = df_productividad_v.groupby('Hr_C').size().reset_index(name='Ord')
                fig_barras_v = px.bar(
                    conteo_horario_v, x='Hr_C', y='Ord', 
                    labels={'Hr_C':'Hora del Día','Ord':'Cant. Cerradas'}, 
                    template="plotly_dark"
                )
                st.plotly_chart(fig_barras_v, use_container_width=True)
            else:
                st.info("Sin datos de cierres para generar gráfico horario.")

        with t_analitica_v:
            st.markdown("### 📈 Análisis de Rendimiento Operativo")
            plt.style.use('dark_background')
            
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                fig1, ax1 = plt.subplots(figsize=(6, 4))
                conteo_seg = df_v_tabla_monitor['SEGMENTO'].value_counts()
                if not conteo_seg.empty:
                    conteo_seg.plot(kind='bar', color=['#1f6feb', '#2ea043'], ax=ax1)
                    ax1.set_title("Volumen de Órdenes por Segmento", fontsize=12, fontweight='bold')
                    ax1.set_ylabel("Cantidad de Órdenes")
                    ax1.tick_params(axis='x', rotation=0)
                    ax1.spines['top'].set_visible(False)
                    ax1.spines['right'].set_visible(False)
                    st.pyplot(fig1)

            with col_m2:
                fig2, ax2 = plt.subplots(figsize=(6, 4))
                tiempos_validos = df_v_tabla_monitor[df_v_tabla_monitor['MINUTOS_CALC'] > 0]['MINUTOS_CALC']
                if not tiempos_validos.empty:
                    ax2.hist(tiempos_validos, bins=15, color='#a371f7', edgecolor='white', alpha=0.8)
                    ax2.set_title("Distribución de Tiempos de Resolución", fontsize=12, fontweight='bold')
                    ax2.set_xlabel("Minutos de Trabajo")
                    ax2.set_ylabel("Frecuencia")
                    ax2.spines['top'].set_visible(False)
                    ax2.spines['right'].set_visible(False)
                    st.pyplot(fig2)

            st.divider()

            fig3, ax3 = plt.subplots(figsize=(10, 3))
            df_offline = df_v_tabla_monitor[df_v_tabla_monitor['ES_OFFLINE'] == True]
            if not df_offline.empty and 'HORA_INI' in df_offline.columns:
                tendencia = df_offline.dropna(subset=['HORA_INI']).groupby(df_offline['HORA_INI'].dt.date).size()
                if not tendencia.empty:
                    tendencia.plot(kind='line', marker='o', color='#f85149', linewidth=2, markersize=8, ax=ax3)
                    ax3.set_title("Tendencia de Fallas Críticas (Offline) por Día", fontsize=12, fontweight='bold')
                    ax3.set_ylabel("Cantidad de Fallas")
                    ax3.grid(True, linestyle='--', alpha=0.3)
                    ax3.spines['top'].set_visible(False)
                    ax3.spines['right'].set_visible(False)
                    st.pyplot(fig3)
                else:
                    st.info("Datos insuficientes de fechas para la tendencia Offline.")
            else:
                st.success("¡Excelente! No hay fallas Offline registradas en esta vista.")

if __name__ == "__main__": 
    verificar_autenticacion()
    if st.session_state.get('autenticado'):
        main()
    else:
        mostrar_pantalla_login()
