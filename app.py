import streamlit as st
import pandas as pd
import os
import io
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as dt_time
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt
from streamlit_js_eval import streamlit_js_eval
from streamlit.runtime.uploaded_file_manager import UploadedFile

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'. Asegúrate de crearlo en la misma carpeta para ver la Auditoría de Vehículos.")

# 🚨 IMPORTACIÓN MÓDULO BIOMÉTRICO 🚨
try:
    import biometrico
except ImportError:
    st.error("⚠️ Falta el archivo 'biometrico.py'. Asegúrate de crearlo en la misma carpeta para ver el reporte Biométrico.")

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
        generar_pdf_trimestral_detallado,
        generar_pdf_primera_orden
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

# PATRON ORIGINAL
PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

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
    
    if str_val in ["0", "0.0", "1899-12-30 00:00:00"]:
        return pd.NaT

    hoy = pd.Timestamp(get_honduras_time()).normalize()

    try:
        if isinstance(val, dt_time):
            return pd.Timestamp.combine(hoy.date(), val)

        if isinstance(val, datetime):
            if val.year <= 1970:
                return hoy + pd.Timedelta(hours=val.hour, minutes=val.minute, seconds=val.second)
            return pd.Timestamp(val)
        
        if isinstance(val, (int, float)):
            if val == 0 or val == 0.0:
                return pd.NaT
            if val > 10000:
                dt = pd.to_datetime(val, unit='D', origin='1899-12-30')
                return dt
            elif 0 < val < 1:
                return hoy + pd.to_timedelta(val, unit='D')
            else:
                return pd.NaT

        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', str_val):
            parsed_time = pd.to_datetime(str_val).time()
            return pd.Timestamp.combine(hoy.date(), parsed_time)

        if re.match(r'^\d{4}-\d{2}-\d{2}', str_val):
            parsed = pd.to_datetime(str_val, errors='coerce')
        else:
            parsed = pd.to_datetime(str_val, dayfirst=True, errors='coerce')

        if pd.notnull(parsed):
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
                    mask_solo_sop = act_upper.str.contains('SOPFIBRA', na=False)
                    
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
                    if 'DIAS_RETRASO' in df_nube.columns:
                        df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns:
                        df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

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
        if 'MX' in fila:
            st.write(f"**Vehículo:** {fila.get('MX', 'S/N')}")
        if 'GPS' in fila:
            st.write(f"**GPS:** {fila.get('GPS', 'S/N')}")
    
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

@st.dialog("Resumen de Operaciones", width="large")
def mostrar_detalle_avance(segmento, asignadas_df, cerradas_df, inicio_mora_df=None):
    st.subheader(f"📊 Desglose: {segmento}")
    
    # 1. Agrupar Pendientes Actuales
    if not asignadas_df.empty:
        p = asignadas_df.groupby('ACTIVIDAD').size().reset_index(name='Pendientes (Hoy)')
    else:
        p = pd.DataFrame(columns=['ACTIVIDAD', 'Pendientes (Hoy)'])

    # 2. Agrupar Cerradas Hoy
    if not cerradas_df.empty:
        c = cerradas_df.groupby('ACTIVIDAD').size().reset_index(name='Cerradas')
    else:
        c = pd.DataFrame(columns=['ACTIVIDAD', 'Cerradas'])

    resumen = pd.merge(p, c, on='ACTIVIDAD', how='outer').fillna(0)

    # 3. Lógica para la 4ta Columna: INICIO (MORA)
    if inicio_mora_df is not None:
        if not inicio_mora_df.empty:
            m = inicio_mora_df.groupby('ACTIVIDAD').size().reset_index(name='Inicio (Mora)')
        else:
            m = pd.DataFrame(columns=['ACTIVIDAD', 'Inicio (Mora)'])
        resumen = pd.merge(m, resumen, on='ACTIVIDAD', how='outer').fillna(0)
    else:
        # Modo izquierda (Carga Total)
        resumen.rename(columns={'Pendientes (Hoy)': 'Asignadas'}, inplace=True)

    if not resumen.empty:
        # Limpieza de tipos de datos
        for col in resumen.columns:
            if col != 'ACTIVIDAD':
                resumen[col] = resumen[col].astype(int)
        
        resumen.rename(columns={'ACTIVIDAD': 'Tipo'}, inplace=True)
        resumen = resumen.sort_values(by='Tipo').reset_index(drop=True)

        # Totales
        fila_total = {'Tipo': 'TOTAL GENERAL'}
        for col in resumen.columns:
            if col != 'Tipo':
                fila_total[col] = resumen[col].sum()
        
        resumen = pd.concat([resumen, pd.DataFrame([fila_total])], ignore_index=True)

        # Configuración de visualización
        col_config = {"Tipo": st.column_config.TextColumn("TIPO DE ORDEN", width="medium")}
        if 'Inicio (Mora)' in resumen.columns:
            col_config["Inicio (Mora)"] = st.column_config.NumberColumn("INICIO (MORA)", format="%d")
            col_config["Pendientes (Hoy)"] = st.column_config.NumberColumn("PENDIENTES", format="%d")
        else:
            col_config["Asignadas"] = st.column_config.NumberColumn("ASIGNADAS (Total)", format="%d")
            
        col_config["Cerradas"] = st.column_config.NumberColumn("CERRADAS", format="%d")

        st.dataframe(
            resumen,
            use_container_width=True,
            hide_index=True,
            column_config=col_config
        )
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
                if minutos_trabajados < 60:
                    estilos_fila[idx_tr] = 'background-color: #4caf50; color: white; font-weight: bold'
                elif minutos_trabajados > 119:
                    estilos_fila[idx_tr] = 'background-color: #d32f2f; color: white; font-weight: bold'

        if fila_v.get('ALERTA_TIEMPO') == True:
            if 'HORA_INI' in fila_v.index:
                estilos_fila[fila_v.index.get_loc('HORA_INI')] = 'background-color: #ff5722; color: white; font-weight: bold'
        
        if 'DIAS_RETRASO' in fila_v.index:
            idx_dias = fila_v.index.get_loc('DIAS_RETRASO')
            val_dias = fila_v['DIAS_RETRASO']
            if val_dias >= 7:
                estilos_fila[idx_dias] = 'background-color: #d32f2f; color: white; font-weight: bold' 
            elif 4 <= val_dias <= 6:
                estilos_fila[idx_dias] = 'background-color: #f57c00; color: white; font-weight: bold' 
            elif 1 <= val_dias <= 3:
                estilos_fila[idx_dias] = 'background-color: #fbc02d; color: black; font-weight: bold' 
            elif val_dias <= 0:
                estilos_fila[idx_dias] = 'background-color: #388e3c; color: white; font-weight: bold' 
                
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
@st.cache_data(show_spinner="Depurando datos al estilo Macro de Excel...", ttl=60, hash_funcs={io.BytesIO: lambda _: None, UploadedFile: lambda _: None, bytes: lambda _: None})
def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        if isinstance(file_dispos, bytes):
            file_dispos_obj = io.BytesIO(file_dispos)
            file_dispos_obj.name = "FttxActiveDevice_cached.xlsx"
        elif hasattr(file_dispos, 'read'):
            file_dispos.seek(0)
            file_dispos_obj = file_dispos
        else:
            file_dispos_obj = file_dispos

        if hasattr(file_activ, 'read'):
            file_activ.seek(0)

        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos_obj)
        
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
                if 'SOPFIBRA' not in act_v:
                    return False
                    
                if m_diff_val > 120 and str(row_check.get('ESTADO','')).upper().strip() != 'CERRADA':
                    return True
            return False
            
        df_act['ALERTA_TIEMPO'] = df_act.apply(alert_2h_logic_diamante, axis=1)
        
        def offline_seguro_diamante_logic(r_off):
            if str(r_off.get('TECNICO', '')).strip().upper() == 'JOSUE MIGUEL SAUCEDA':
                return False
            if str(r_off.get('ESTADO','')).upper().strip() == 'CERRADA':
                return False
            act_v_name = str(r_off.get('ACTIVIDAD', '')).upper()
            
            if any(p in act_v_name for p in ['PLEXISCA', 'PEXTERNO', 'SPLITTEROPT', 'PLEX', 'INS', 'NUEVA', 'ADIC', 'CAMBIO', 'RECU', 'TVADICIONAL', 'MIGRACI']): 
                return False
            if 'SOPFIBRA' not in act_v_name: 
                return False

            comentario_v_val = str(r_off.get('COMENTARIO', '')).upper()
            if "ONU OFFLINE" in comentario_v_val or "OFF LINE" in comentario_v_val or "FUERA DE SERVICIO" in comentario_v_val or "OFFLINE" in comentario_v_val:
                return True
            return es_offline_preciso(comentario_v_val)
        
        df_act['ES_OFFLINE'] = df_act.apply(offline_seguro_diamante_logic, axis=1)
        df_act['MINUTOS_CALC'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds() / 60
        
        def segmentar_plex_diamante_logic(r_seg):
            texto_p_scan = f"{r_seg.get('ACTIVIDAD', '')} {r_seg.get('CLIENTE', '')} {r_seg.get('COMENTARIO', '')}".upper()
            if re.search(r'PLEX|PEXTERNO|SPLITTEROPT', texto_p_scan):
                return 'PLEX'
            return 'RESIDENCIAL'
        df_act['SEGMENTO'] = df_act.apply(segmentar_plex_diamante_logic, axis=1)
        
        def format_duracion_diamante_human(r_dur):
            if pd.isnull(r_dur['HORA_INI']) or pd.isnull(r_dur['HORA_LIQ']):
                return "---"
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
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    
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

    if 'df_base' not in st.session_state or st.session_state.get('btn_reprocesar', False):
        pass 

    filtro_actividad = []
    filtro_estado = []
    filtro_motivo = []
    check_criticos_diamante = False
    check_no_asignadas = False 
    tec_filtro_monitor = "Todos"
    
    with sidebar_top:
        if rol_usuario in ['admin', 'jefe']:
            nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "📚 Histórico", "🚫 NOINSTALADO", "📅 REPROGRAMADAS", "🚙 Auditoría Vehículos"])
        else:
            nav_menu_diamante = "⚡ Monitor en Vivo"
            
        if nav_menu_diamante == "⚡ Monitor en Vivo":
            st.divider()
            st.markdown("### 🎛️ Filtros Múltiples")
            
            if 'df_base' in st.session_state and st.session_state.df_base is not None:
                df_base_activa_temp = st.session_state.df_base.copy()
                lista_actividades = sorted(df_base_activa_temp['ACTIVIDAD'].dropna().unique().tolist())
                lista_estados = sorted(df_base_activa_temp['ESTADO'].dropna().unique().tolist())
                lista_motivos = sorted(df_base_activa_temp['MOTIVO'].dropna().unique().tolist()) if 'MOTIVO' in df_base_activa_temp.columns else []
                
                filtro_actividad = st.multiselect("🛠️ Tipo de Actividad:", options=lista_actividades, default=[], placeholder="Todas las actividades")
                filtro_estado = st.multiselect("🚦 Estado de Orden:", options=lista_estados, default=[], placeholder="Todos los estados")
                filtro_motivo = st.multiselect("⚠️ Motivo / Diagnóstico:", options=lista_motivos, default=[], placeholder="Todos los motivos")
                
                st.divider() 
                st.markdown("### 🔍 Filtros en Vivo")
                if rol_usuario in ['admin', 'jefe']:
                    m_viva_count = df_base_activa_temp['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                    mascara_offline_segura = df_base_activa_temp['ES_OFFLINE'] == True
                    total_off_count_viva = int((mascara_offline_segura & m_viva_count).sum())
                    
                    mascara_no_asignadas = (df_base_activa_temp['TECNICO'].isna()) | (df_base_activa_temp['TECNICO'].astype(str).str.strip() == '') | (df_base_activa_temp['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
                    total_no_asignadas_viva = int((mascara_no_asignadas & m_viva_count).sum())
                    
                    check_criticos_diamante = st.toggle(f"🚨 Ver solo Críticas ({total_off_count_viva})")
                    check_no_asignadas = st.toggle(f"🚨 Ver NO Asignadas ({total_no_asignadas_viva})")
                    
                    lista_tecs_monitor = ["Todos"] + sorted(df_base_activa_temp['TECNICO'].dropna().unique().tolist())
                    tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor)

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
        if rol_usuario in ['admin', 'jefe'] and not es_movil:
            mostrar_cargador = True

        file_act_ptr = None
        file_disp_ptr = None
        btn_reprocesar = False
        
        if mostrar_cargador:
            st.divider()
            st.markdown("### 📥 Carga de Archivos")
            
            if es_admin:
                st.caption("Eres Admin: Sube los dos archivos (Actividades y FTTX).")
                archivos_uploader_diamante = st.file_uploader(
                    "Sube rep_actividades y FttxActiveDevice", 
                    type=["xlsx", "csv"], 
                    accept_multiple_files=True
                )
                
                if archivos_uploader_diamante:
                    for file_item in archivos_uploader_diamante:
                        f_name_lwr = file_item.name.lower()
                        if "actividades" in f_name_lwr: 
                            file_act_ptr = file_item
                        elif "device" in f_name_lwr or "dispositivos" in f_name_lwr: 
                            file_disp_ptr = file_item
                            try:
                                with open("cache_fttx.tmp", "wb") as f:
                                    f.write(file_item.getvalue())
                            except:
                                pass
            else:
                st.caption("Solo necesitas subir las actividades. FTTX se bajará de la nube.")
                archivo_unico = st.file_uploader(
                    "Sube únicamente el rep_actividades", 
                    type=["xlsx", "csv"], 
                    accept_multiple_files=False
                )
                if archivo_unico:
                    file_act_ptr = archivo_unico

            ahora_hx = get_honduras_time()
            es_horario_tarde = ahora_hx.hour >= 17
            es_fin_de_semana = (ahora_hx.weekday() == 5 and ahora_hx.hour >= 13) or (ahora_hx.weekday() == 6)
            
            condicion_usar_cache = es_horario_tarde or es_fin_de_semana
            
            if condicion_usar_cache and file_act_ptr is not None and file_disp_ptr is None and es_admin:
                if os.path.exists("cache_fttx.tmp"):
                    try:
                        with open("cache_fttx.tmp", "rb") as f:
                            file_disp_ptr = f.read()
                        st.info("🕒 **Modo Caché Activo:** Se cargó automáticamente el último archivo FTTX guardado.")
                    except:
                        pass

            btn_reprocesar = st.button("🔄 PROCESAR ARCHIVOS", use_container_width=True)
            
        elif rol_usuario == 'jefe' and es_movil:
            st.caption("📱 _Modo Móvil: Usa el botón de arriba para actualizar._")

    if 'df_base' not in st.session_state or btn_reprocesar:
        
        if not es_admin and file_act_ptr is not None and file_disp_ptr is None:
            with st.spinner("☁️ Descargando base de Vehículos/Dispositivos desde la nube..."):
                try:
                    df_fttx_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", ttl=600)
                    
                    if not df_fttx_cloud.empty:
                        b_io = io.BytesIO()
                        df_fttx_cloud.to_csv(b_io, index=False)
                        b_io.seek(0)
                        b_io.name = "fttx_nube.csv"
                        file_disp_ptr = b_io
                        st.info("☁️ Base de vehículos (FTTX) cargada automáticamente desde la nube.")
                    else:
                        raise ValueError("La pestaña está vacía.")
                        
                except Exception as e:
                    st.warning(f"⚠️ No se pudo cargar FTTX de la nube. Usando modo sin vehículos.")
                    b_io = io.BytesIO()
                    pd.DataFrame(columns=['ID']).to_excel(b_io, index=False)
                    b_io.seek(0)
                    b_io.name = "dummy_fttx.xlsx"
                    file_disp_ptr = b_io

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
                            # 1. Preparamos la NUEVA carga (La verdad absoluta de las Vivas de hoy)
                            df_new = res_p_diamante.copy()
                            if 'NUM' in df_new.columns:
                                df_new['NUM'] = df_new['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                df_new.loc[df_new['NUM'] == 'nan', 'NUM'] = 'N/D'
                            
                            # 2. Leemos la Nube
                            df_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                            
                            if not df_cloud.empty:
                                df_cloud.columns = df_cloud.columns.str.upper().str.strip()
                                if 'NUM' in df_cloud.columns:
                                    df_cloud['NUM'] = df_cloud['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    df_cloud.loc[df_cloud['NUM'] == 'nan', 'NUM'] = 'N/D'
                                
                                # 3. LÓGICA DE ESPEJO ABSOLUTO INVERSO
                                PATRON_VIVAS_NUBE = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                mask_vivas_nube = df_cloud['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS_NUBE, na=False)
                                df_historial_puro = df_cloud[~mask_vivas_nube].copy()
                                
                                # 4. Unimos el historial puro con tu archivo nuevo crudo (que trae las vivas reales de hoy)
                                df_combined = pd.concat([df_historial_puro, df_new])
                            else:
                                df_combined = df_new
                                
                            # 5. Limpieza final de seguridad por si una "viva" nueva ya estaba en el historial como cerrada
                            if 'NUM' in df_combined.columns:
                                df_combined['TIENE_LIQ'] = df_combined.get('HORA_LIQ').notna()
                                df_combined = df_combined.sort_values(by=['TIENE_LIQ'], ascending=True)
                                
                                df_valid_num = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                                df_nd = df_combined[df_combined['NUM'] == 'N/D']
                                df_combined = pd.concat([df_valid_num, df_nd])
                                df_combined = df_combined.drop(columns=['TIENE_LIQ'], errors='ignore')

                            df_to_upload = df_combined.copy()
                            for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                                if c_date in df_to_upload.columns:
                                    df_to_upload[c_date] = pd.to_datetime(df_to_upload[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                                    
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=df_to_upload)
                            
                            if es_admin and file_disp_ptr is not None and not isinstance(file_disp_ptr, bytes):
                                try:
                                    if hasattr(file_disp_ptr, 'read'):
                                        file_disp_ptr.seek(0)
                                    if getattr(file_disp_ptr, 'name', '').lower().endswith('.csv'):
                                        df_fttx_up = pd.read_csv(file_disp_ptr, sep=None, engine='python')
                                    else:
                                        df_fttx_up = pd.read_excel(file_disp_ptr, engine='openpyxl')
                                    conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", data=df_fttx_up)
                                    st.success("✅ Base de vehículos (FTTX) actualizada en la nube.")
                                except Exception as e_fttx:
                                    st.warning(f"⚠️ No se pudo actualizar FTTX en la nube: {e_fttx}")

                            st.success("✅ Datos sincronizados en modo Espejo Inverso y unidos al historial correctamente.")
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
        mask_solo_sop_g = act_upper_global.str.contains('SOPFIBRA', na=False)
        
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
            
            if row.get('ES_OFFLINE', False) == True:
                return "🔴 Offline / Caída"
            if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", texto):
                return "📦 Instalación / Cambio"
            if re.search("TV|CABLE|SEÑAL", texto):
                return "📺 Falla de TV"
            if re.search("NIVEL|DB|POTENCIA|ATENU", texto):
                return "⚡ Niveles Alterados"
            if re.search("NAV|INTERNET|LENT", texto):
                return "🌐 Lentitud / Navegación"
            
            return "🔧 Mantenimiento General"
            
        df_base['MOTIVO'] = df_base.apply(extraer_motivo_falla, axis=1)

        def extraer_segmento_global(row):
            texto_p_scan = f"{row.get('ACTIVIDAD', '')} {row.get('CLIENTE', '')} {row.get('COMENTARIO', '')}".upper()
            if re.search(r'PLEX|PEXTERNO|SPLITTEROPT', texto_p_scan):
                return 'PLEX'
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

    df_base_activa = df_base.copy()

    if nav_menu_diamante == "⚡ Monitor en Vivo" or nav_menu_diamante == "📊 Centro de Reportes":
        df_monitor_filtrado = df_base_activa.copy()
        
        if len(filtro_actividad) > 0:
            df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
        if len(filtro_estado) > 0:
            df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
        if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns:
            df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
        
        if check_criticos_diamante:
            mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado['ALERTA_TIEMPO']
            mask_sop_fibra = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('SOPFIBRA', na=False)
            mask_falsos = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
            df_monitor_filtrado = df_monitor_filtrado[mask_critica & mask_sop_fibra & ~mask_falsos]
            
        if check_no_asignadas:
            mask_no_asignadas_filtro = (df_monitor_filtrado['TECNICO'].isna()) | (df_monitor_filtrado['TECNICO'].astype(str).str.strip() == '') | (df_monitor_filtrado['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
            df_monitor_filtrado = df_monitor_filtrado[mask_no_asignadas_filtro]
            
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
        
        df_base['DIAS_RETRASO_REAL'] = (pd.Timestamp(ahora_local).normalize() - pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).astype(int)
        mask_reprog = (df_base['DIAS_RETRASO_REAL'] < 0) & (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False))
        df_reprog = df_base[mask_reprog].copy()
        
        st.metric("Total Agendadas a Futuro", len(df_reprog))
        
        if not df_reprog.empty:
            cols_visibles = ['DIAS_RETRASO_REAL', 'NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'TECNICO', 'ESTADO', 'COMENTARIO', 'FECHA_APE']
            cols_finales = [c for c in cols_visibles if c in df_reprog.columns]
            
            def highlight_reprog(row):
                return ['background-color: #1a2a3a; color: #58a6ff; font-weight: bold' if col == 'DIAS_RETRASO_REAL' else '' for col in row.index]

            st.dataframe(
                df_reprog[cols_finales].style.apply(highlight_reprog, axis=1),
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
        
        tab_diario, tab_gerencial, tab_biometrico = st.tabs([
            "📦 Cierre Diario", "💼 Gerencial (Trimestral)", "⏱️ Biométrico"
        ])

        with tab_biometrico:
            try:
                biometrico.vista_biometrico()
            except Exception as e:
                st.error(f"Error al cargar la vista del biométrico: {e}")

        with tab_gerencial:
            st.subheader("📊 Reporte Gerencial Unificado")
            st.caption("Sube el archivo en crudo. El sistema cruzará la productividad, tiempos y jornadas en una sola tabla maestra.")
            
            archivo_gerencial = st.file_uploader("📂 Subir Reporte de Actividades (Excel/CSV)", type=['xlsx', 'csv'], key="uploader_gerencial")
            
            if archivo_gerencial:
                with st.spinner("⏳ Analizando datos, cruzando tablas y calculando jornadas..."):
                    try:
                        if archivo_gerencial.name.endswith('.csv'):
                            df_raw = pd.read_csv(archivo_gerencial)
                        else:
                            df_raw = pd.read_excel(archivo_gerencial)
                        
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
                                st.session_state['pdf_gerencial'] = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                        
                        if 'pdf_gerencial' in st.session_state:
                            st.download_button(
                                label="📥 Descargar Reporte PDF",
                                data=st.session_state['pdf_gerencial'],
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
            
            mask_vivas_espejo = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            mask_cerradas_espejo = (df_monitor_filtrado['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_monitor_filtrado['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
            
            df_vivas_espejo = df_monitor_filtrado[mask_vivas_espejo].copy()
            mask_tec_valido_esp = df_vivas_espejo['TECNICO'].notna() & (df_vivas_espejo['TECNICO'].astype(str).str.strip() != '') & (~df_vivas_espejo['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
            df_asignadas_espejo = df_vivas_espejo[mask_tec_valido_esp].copy()
            df_cerradas_espejo = df_monitor_filtrado[mask_cerradas_espejo].copy()

            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cerradas_espejo))
            st.markdown("### 📊 Indicadores de Avance Operativo")
            
            df_plex_asignadas_rep = df_asignadas_espejo[df_asignadas_espejo['SEGMENTO'] == 'PLEX']
            df_plex_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['SEGMENTO'] == 'PLEX']
            
            df_resi_asignadas_rep = df_asignadas_espejo[df_asignadas_espejo['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['SEGMENTO'] == 'RESIDENCIAL']

            total_p_rep = len(df_plex_asignadas_rep) + len(df_plex_cerr_rep)
            avance_plex_rep = (len(df_plex_cerr_rep) / total_p_rep * 100) if total_p_rep > 0 else 0
            
            total_r_rep = len(df_resi_asignadas_rep) + len(df_resi_cerr_rep)
            avance_resi_rep = (len(df_resi_cerr_rep) / total_r_rep * 100) if total_r_rep > 0 else 0
            
            total_v_rep = len(df_asignadas_espejo) + len(df_cerradas_espejo)
            avance_global_rep = (len(df_cerradas_espejo) / total_v_rep * 100) if total_v_rep > 0 else 0

            def crear_velocimetro_rep(valor, titulo):
                color_v = "#EF4444" if valor < 50 else ("#F59E0B" if valor < 80 else "#10B981") 
                fig = go.Figure(go.Pie(values=[valor, max(0, 100 - valor)], labels=['Completado', 'Pendiente'], hole=0.8, marker=dict(colors=[color_v, '#2D2F39']), textinfo='none', hoverinfo='none', direction='clockwise', sort=False))
                fig.update_layout(showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}}, annotations=[dict(text=f"{valor:.0f}%", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")])
                return fig

            col_gr1, col_gr2, col_gr3 = st.columns(3)
            with col_gr1: st.plotly_chart(crear_velocimetro_rep(avance_resi_rep, "🏠 Residencial"), use_container_width=True)
            with col_gr2: st.plotly_chart(crear_velocimetro_rep(avance_plex_rep, "🏢 PLEX"), use_container_width=True)
            with col_gr3: st.plotly_chart(crear_velocimetro_rep(avance_global_rep, "🌍 Global"), use_container_width=True)
            
            st.divider()

            if not df_cerradas_espejo.empty:
                st.markdown("### 📊 Desglose de Producción por Categoría")
                cs_col, ci_col, cp_col, co_col = st.columns(4)
                with cs_col:
                    st.write("**SOP**")
                    df_sop = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_sop, hide_index=True, use_container_width=True)
                    st.write(f"**Total SOP: {df_sop['Cant'].sum()}**")
                with ci_col:
                    st.write("**Instalaciones**")
                    txt_ins_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_ins_general = txt_ins_c.str.contains('INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_ins_cierre = df_cerradas_espejo[mask_ins_general].copy()
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
                    else: st.write("Sin datos")
                with cp_col:
                    st.write("**Plex**")
                    df_plex = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('PLEX|PEXTERNO|SPLITTEROPT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_plex, hide_index=True, use_container_width=True)
                    st.write(f"**Total PLEX: {df_plex['Cant'].sum()}**")
                with co_col:
                    st.write("**Otros**")
                    txt_otr_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|PEXTERNO|SPLITTEROPT|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_otros = df_cerradas_espejo[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_otros, hide_index=True, use_container_width=True)
                    st.write(f"**Total Otros: {df_otros['Cant'].sum()}**")

            st.divider()
            
            st.markdown("### 📈 Resumen Consolidado: Carga Asignada vs Cierres")
            
            p_rep = df_asignadas_espejo.groupby('ACTIVIDAD').size().reset_index(name='ASIGNADAS')
            c_rep = df_cerradas_espejo.groupby('ACTIVIDAD').size().reset_index(name='CERRADAS')
            
            resumen_global_rep = pd.merge(p_rep, c_rep, on='ACTIVIDAD', how='outer').fillna(0)
            
            if not resumen_global_rep.empty:
                resumen_global_rep['ASIGNADAS'] = resumen_global_rep['ASIGNADAS'].astype(int)
                resumen_global_rep['CERRADAS'] = resumen_global_rep['CERRADAS'].astype(int)
                
                resumen_global_rep.rename(columns={'ACTIVIDAD': 'TIPO'}, inplace=True)
                resumen_global_rep = resumen_global_rep[['TIPO', 'ASIGNADAS', 'CERRADAS']].sort_values(by='TIPO').reset_index(drop=True)
                
                tot_p = resumen_global_rep['ASIGNADAS'].sum()
                tot_c = resumen_global_rep['CERRADAS'].sum()
                fila_tot = pd.DataFrame([{'TIPO': 'TOTAL GENERAL', 'ASIGNADAS': tot_p, 'CERRADAS': tot_c}])
                resumen_global_rep = pd.concat([resumen_global_rep, fila_tot], ignore_index=True)
                
                st.dataframe(
                    resumen_global_rep, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TIPO": st.column_config.TextColumn("TIPO"),
                        "ASIGNADAS": st.column_config.NumberColumn("ASIGNADAS", format="%d"),
                        "CERRADAS": st.column_config.NumberColumn("CERRADAS", format="%d")
                    }
                )
            else:
                st.info("No hay datos de operaciones consolidadas para esta fecha.")

            st.markdown("### ⏱️ Tiempos de Atención Promedio")
            if not df_cerradas_espejo.empty:
                df_pivot_diario = df_cerradas_espejo.groupby(['TECNICO', 'ACTIVIDAD']).agg(
                    Órdenes=('NUM', 'count'),
                    Prom_Duracion_Min=('MINUTOS_CALC', 'mean')
                ).round(1)
                st.dataframe(df_pivot_diario, use_container_width=True)

            st.markdown("### 🌅 Primera Orden del Día por Técnico")
            
            df_universo_diario = pd.concat([df_asignadas_espejo, df_cerradas_espejo]).drop_duplicates(subset=['NUM'])
            
            if 'HORA_INI' in df_universo_diario.columns:
                df_universo_diario['HORA_INI_DT'] = pd.to_datetime(df_universo_diario['HORA_INI'], errors='coerce')
                df_universo_diario = df_universo_diario.dropna(subset=['HORA_INI_DT'])
                
                mask_fecha_ini = df_universo_diario['HORA_INI_DT'].dt.date == pd.to_datetime(fecha_cal_sel).date()
                df_primera = df_universo_diario[mask_fecha_ini].sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO'], keep='first')
                
                if not df_primera.empty:
                    df_primera_mostrar = df_primera[['TECNICO', 'HORA_INI_DT', 'COLONIA', 'NUM']].copy()
                    
                    df_primera_mostrar = df_primera_mostrar.sort_values(by='HORA_INI_DT')
                    
                    df_primera_mostrar['HORA_INI'] = df_primera_mostrar['HORA_INI_DT'].dt.strftime('%H:%M:%S')
                    df_primera_mostrar = df_primera_mostrar.drop(columns=['HORA_INI_DT'])
                    
                    df_primera_mostrar = df_primera_mostrar[['TECNICO', 'HORA_INI', 'COLONIA', 'NUM']]
                    
                    st.dataframe(
                        df_primera_mostrar, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "TECNICO": st.column_config.TextColumn("Técnico"),
                            "HORA_INI": st.column_config.TextColumn("Hora de Inicio"),
                            "COLONIA": st.column_config.TextColumn("Colonia"),
                            "NUM": st.column_config.TextColumn("N° Orden")
                        }
                    )

                    st.markdown("<br>", unsafe_allow_html=True)
                    col_btn1, col_btn2 = st.columns([1, 2])
                    with col_btn1:
                        if st.button("📄 GENERAR PDF PRIMERA ORDEN", use_container_width=True):
                            try:
                                with st.spinner("Generando PDF..."):
                                    st.session_state['pdf_primera'] = generar_pdf_primera_orden(df_base, fecha_cal_sel)
                            except Exception as e:
                                st.error(f"Error generando PDF: {e}")
                        
                        if 'pdf_primera' in st.session_state and st.session_state['pdf_primera']:
                            st.download_button("📥 Descargar PDF (Inicio Jornada)", data=st.session_state['pdf_primera'], file_name=f"Primeras_Ordenes_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                else:
                    st.info("No hay registros de inicio de órdenes para esta fecha.")
            else:
                 st.info("No hay registros de inicio de órdenes para esta fecha.")

            st.markdown("### 📥 Exportación")
            if st.button("🚀 GENERAR PDF DE CIERRE DIARIO", use_container_width=True, type="primary"):
                with st.spinner("Preparando archivo de cierre..."):
                    st.session_state['pdf_cierre'] = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
            
            if 'pdf_cierre' in st.session_state:
                st.download_button("📥 Descargar Archivo (PDF)", data=st.session_state['pdf_cierre'], file_name=f"Cierre_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            
            st.divider()
            with st.expander("Ver Lista Detallada"):
                st.dataframe(df_cerradas_espejo[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)
            
        return

    # ==============================================================================
    # 7. MONITOR OPERATIVO EN VIVO 
    # ==============================================================================
    if nav_menu_diamante == "⚡ Monitor en Vivo":
        
        mask_vivas_monitor = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        df_todas_pendientes_monitor = df_monitor_filtrado[mask_vivas_monitor].copy()

        df_cerradas_hoy_monitor = df_monitor_filtrado[(df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()

        df_todas_pendientes_monitor['DIAS_RETRASO'] = (pd.Timestamp(ahora_local).normalize() - pd.to_datetime(df_todas_pendientes_monitor['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).astype(int)
        
        if 'TECNICO' in df_todas_pendientes_monitor.columns:
            mask_josue_kpi = df_todas_pendientes_monitor['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
            df_todas_pendientes_monitor.loc[mask_josue_kpi, 'DIAS_RETRASO'] = 0
            
        df_todas_pendientes_monitor.loc[df_todas_pendientes_monitor['DIAS_RETRASO'] < 0, 'DIAS_RETRASO'] = 0

        df_todas_pendientes_monitor['CatD'] = df_todas_pendientes_monitor['DIAS_RETRASO'].apply(
            lambda d: ">= 7 Dia" if d >= 7 else ("= 4 a 6 Dias" if d >= 4 else ("= 1 a 3 Dias" if d >= 1 else "= 0 Dia"))
        )

        st.title("⚡ Monitor Operativo Maxcom")

        mask_tec_valido_mon = df_todas_pendientes_monitor['TECNICO'].notna() & (df_todas_pendientes_monitor['TECNICO'].astype(str).str.strip() != '') & (~df_todas_pendientes_monitor['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
        
        if check_no_asignadas:
            df_solo_asignadas_monitor = df_todas_pendientes_monitor[~mask_tec_valido_mon].copy()
        else:
            df_solo_asignadas_monitor = df_todas_pendientes_monitor[mask_tec_valido_mon].copy()

        vivas_count_asignadas = len(df_solo_asignadas_monitor)
        cerradas_hoy = len(df_cerradas_hoy_monitor)
        tecs_activos = df_solo_asignadas_monitor['TECNICO'].nunique() if not check_no_asignadas else 0
        offline_criticos_asignadas = int((df_solo_asignadas_monitor.get('ES_OFFLINE', pd.Series([False]*len(df_solo_asignadas_monitor))) == True).sum())

        html_kpis = f"""
        <div style="display: flex; justify-content: space-between; gap: 15px; margin-bottom: 20px; margin-top: 10px;">
            <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #3B82F6; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">PENDIENTES ASIGNADAS</div>
                <div style="color: #FFFFFF; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{vivas_count_asignadas}</div>
            </div>
            <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #10B981; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">CERRADAS HOY</div>
                <div style="color: #10B981; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{cerradas_hoy}</div>
            </div>
            <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #F59E0B; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">TÉCNICOS EN RUTA</div>
                <div style="color: #FFFFFF; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{tecs_activos}</div>
            </div>
            <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #EF4444; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">CAÍDAS (OFFLINE)</div>
                <div style="color: #EF4444; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{offline_criticos_asignadas}</div>
            </div>
        </div>
        """
        st.markdown(html_kpis, unsafe_allow_html=True)

        with st.expander("📊 TABLERO DE CARGA ACTUAL (TODAS LAS PENDIENTES)", expanded=True):
            col_tab_1, col_tab_2, col_tab_3, col_tab_4 = st.columns([1, 1.2, 1.2, 1])
            
            with col_tab_1:
                st.caption("📅 Resumen de Retraso")
                res_retraso_v = df_todas_pendientes_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 a 6 Dias","= 1 a 3 Dias","= 0 Dia"], fill_value=0).reset_index()
                res_retraso_v.columns = ['Dias', 'Cant']
                sum_total_asignadas_v = res_retraso_v['Cant'].sum()
                res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_asignadas_v*100):.0f}%" if sum_total_asignadas_v > 0 else "0%")
                
                def style_dias_apply(row):
                    v = row['Dias']
                    bg_color, font_color = '', 'white'
                    if v == ">= 7 Dia":
                        bg_color = '#d32f2f'
                    elif v == "= 4 a 6 Dias":
                        bg_color = '#f57c00'
                    elif v == "= 1 a 3 Dias":
                        bg_color, font_color = '#fbc02d', 'black'
                    elif v == "= 0 Dia":
                        bg_color = '#388e3c'
                    return [f'background-color: {bg_color}; color: {font_color}; font-weight: bold' if i == 0 else '' for i in range(len(row))]

                st.dataframe(res_retraso_v.style.apply(style_dias_apply, axis=1), hide_index=True, use_container_width=True)
                st.markdown(f"<div style='text-align: center; padding-top: 5px; font-weight: bold; font-size: 16px; color: black;'>Total Órdenes: {len(df_todas_pendientes_monitor)}</div>", unsafe_allow_html=True)

            g_tab_list = []
            sub_tab_list = []
            for idx, r in df_todas_pendientes_monitor.iterrows():
                act = str(r.get('ACTIVIDAD', '')).upper()
                com = str(r.get('COMENTARIO', '')).upper()
                txt = act + " " + com
                is_off = r.get('ES_OFFLINE', False)
                
                if not re.search("SOP|FALLA|MANT|INS|ADIC|CAMBIO|MIGRACI|NUEVA|RECUP", txt):
                    g_tab_list.append("OTROS")
                    sub_tab_list.append(act if act != "" else "N/A")
                elif re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act):
                    g_tab_list.append("INS")
                    if re.search("ADIC", txt):
                        sub_tab_list.append("Adición")
                    elif re.search("CAMBIO|MIGRACI", txt):
                        sub_tab_list.append("Cambio / Migración")
                    elif re.search("RECUP", txt):
                        sub_tab_list.append("Recuperado")
                    else:
                        sub_tab_list.append("Nueva")
                else:
                    g_tab_list.append("SOP")
                    if is_off:
                        sub_tab_list.append("ONT/ONU Offline")
                    elif re.search("NIVEL|DB", com):
                        sub_tab_list.append("Niveles alterados")
                    elif re.search("FIBRA|FTTH", act):
                        sub_tab_list.append("FTTH / FIBRA")
                    elif re.search("NAV|INTERNET", act):
                        sub_tab_list.append("Navegación / Internet")
                    elif re.search("TV|CABLE", act):
                        sub_tab_list.append("Sin señal de TV")
                    else:
                        sub_tab_list.append("SOP General")
                    
            df_tablero = df_todas_pendientes_monitor.copy()
            df_tablero['G_TAB'] = g_tab_list
            df_tablero['SUB_TAB'] = sub_tab_list
                
            with col_tab_2:
                st.caption("🛠️ SOP / Mantenimiento")
                df_sop = df_tablero[df_tablero['G_TAB'] == 'SOP']
                res_sop = df_sop['SUB_TAB'].value_counts().reset_index()
                res_sop.columns = ['SOP', 'Cant']
                st.dataframe(res_sop, hide_index=True, use_container_width=True)
                st.write(f"**Total General SOP: {df_sop.shape[0]}**")
                st.metric("Exceden 2 Horas ⚠️", int((df_sop['ALERTA_TIEMPO'] == True).sum()))

            with col_tab_3:
                st.caption("📦 Instalaciones")
                df_ins = df_tablero[df_tablero['G_TAB'] == 'INS']
                res_ins = df_ins['SUB_TAB'].value_counts().reset_index()
                res_ins.columns = ['Instalaciones', 'Cant']
                
                cats_ins = ['Nueva', 'Adición', 'Cambio / Migración', 'Recuperado']
                for c in cats_ins:
                    if c not in res_ins['Instalaciones'].values:
                        res_ins = pd.concat([res_ins, pd.DataFrame([{'Instalaciones': c, 'Cant': 0}])], ignore_index=True)
                        
                st.dataframe(res_ins, hide_index=True, use_container_width=True)
                st.write(f"**Total General INS: {df_ins.shape[0]}**")

            with col_tab_4:
                st.caption("⚙️ Otros")
                df_otros = df_tablero[df_tablero['G_TAB'] == 'OTROS']
                res_otr = df_otros['SUB_TAB'].value_counts().reset_index()
                res_otr.columns = ['Otros', 'Cant']
                st.dataframe(res_otr.head(8), hide_index=True, use_container_width=True)
                st.write(f"**Total Otros: {df_otros.shape[0]}**")

        with st.expander("📊 CONSOLIDADO POR SEGMENTO Y AVANCE", expanded=False):
            st.markdown("<h4 style='text-align: center; color: #E2E8F0;'>Control de Gestión Operativa (Carga Total vs Evacuación de Mora Inicial)</h4><br>", unsafe_allow_html=True)
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            
            # =====================================================================
            # --- LÓGICA IZQUIERDA: CARGA TOTAL (El día completo: Mora + Nuevas) ---
            # =====================================================================
            df_plex_asignadas = df_solo_asignadas_monitor[df_solo_asignadas_monitor['SEGMENTO'] == 'PLEX']
            df_plex_cerr = df_cerradas_hoy_monitor[df_cerradas_hoy_monitor['SEGMENTO'] == 'PLEX']
            
            df_resi_asignadas = df_solo_asignadas_monitor[df_solo_asignadas_monitor['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_cerr = df_cerradas_hoy_monitor[df_cerradas_hoy_monitor['SEGMENTO'] == 'RESIDENCIAL']

            total_p = len(df_plex_asignadas) + len(df_plex_cerr)
            avance_plex = (len(df_plex_cerr) / total_p * 100) if total_p > 0 else 0
            
            total_r = len(df_resi_asignadas) + len(df_resi_cerr)
            avance_resi = (len(df_resi_cerr) / total_r * 100) if total_r > 0 else 0
            
            total_v = len(df_solo_asignadas_monitor) + len(df_cerradas_hoy_monitor)
            avance_global = (len(df_cerradas_hoy_monitor) / total_v * 100) if total_v > 0 else 0

            # =====================================================================
            # --- LÓGICA DERECHA: EFECTIVIDAD DE MORA (Solo órdenes de ayer o antes) ---
            # =====================================================================
            
            # 1. PENDIENTES DE MORA ACTUAL: Órdenes vivas que se crearon ayer o antes (DIAS_RETRASO > 0)
            df_mora_pendiente_actual = df_solo_asignadas_monitor[df_solo_asignadas_monitor['DIAS_RETRASO'] > 0].copy()
            
            # 2. CERRADAS DE MORA HOY: Órdenes que se cerraron hoy, pero se crearon ayer o antes
            df_cerradas_hoy_monitor['FECHA_APE_DT'] = pd.to_datetime(df_cerradas_hoy_monitor['FECHA_APE'], errors='coerce')
            df_mora_cerrada_hoy = df_cerradas_hoy_monitor[df_cerradas_hoy_monitor['FECHA_APE_DT'].dt.date < hoy_date_valor].copy()
            
            # 3. INICIO DE MORA (El Universo Real): Es la suma de lo que está vivo con retraso + lo viejo que ya mataste hoy
            df_inicio_mora_total = pd.concat([df_mora_pendiente_actual, df_mora_cerrada_hoy]).drop_duplicates(subset=['NUM'])

            # Segmentamos la Mora para los velocímetros
            df_plex_m_pend = df_mora_pendiente_actual[df_mora_pendiente_actual['SEGMENTO'] == 'PLEX']
            df_plex_m_cerr = df_mora_cerrada_hoy[df_mora_cerrada_hoy['SEGMENTO'] == 'PLEX']
            df_plex_m_inicio = df_inicio_mora_total[df_inicio_mora_total['SEGMENTO'] == 'PLEX']
            
            df_resi_m_pend = df_mora_pendiente_actual[df_mora_pendiente_actual['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_cerr = df_mora_cerrada_hoy[df_mora_cerrada_hoy['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_inicio = df_inicio_mora_total[df_inicio_mora_total['SEGMENTO'] == 'RESIDENCIAL']

            # Cálculos de efectividad: (Cerradas Viejas / Inicio Total Viejo)
            tot_mora_plex = len(df_plex_m_inicio)
            av_mora_plex = (len(df_plex_m_cerr) / tot_mora_plex * 100) if tot_mora_plex > 0 else 0
            
            tot_mora_resi = len(df_resi_m_inicio)
            av_mora_resi = (len(df_resi_m_cerr) / tot_mora_resi * 100) if tot_mora_resi > 0 else 0
            
            tot_mora_global = len(df_inicio_mora_total)
            av_mora_global = (len(df_mora_cerrada_hoy) / tot_mora_global * 100) if tot_mora_global > 0 else 0

            # FUNCIÓN PARA CREAR VELOCÍMETRO CIRCULAR
            def crear_velocimetro_6cols(valor, titulo, es_mora=False, total_ordenes=0):
                if es_mora:
                    color_v = "#EF4444" if valor < 60 else ("#F59E0B" if valor < 90 else "#10B981")
                else:
                    color_v = "#EF4444" if valor < 50 else ("#F59E0B" if valor < 80 else "#10B981") 
                
                if total_ordenes == 0:
                    color_v = "#4B5563"
                    
                fig = go.Figure(go.Pie(
                    values=[valor, max(0, 100 - valor)] if total_ordenes > 0 else [0, 100],
                    labels=['Completado', 'Pendiente'],
                    hole=0.8,
                    marker=dict(colors=[color_v, '#2D2F39']),
                    textinfo='none',
                    hoverinfo='none',
                    direction='clockwise',
                    sort=False
                ))
                
                texto_central = f"{valor:.0f}%" if total_ordenes > 0 else "N/A"
                
                fig.update_layout(
                    showlegend=False, 
                    height=140, 
                    margin=dict(l=10, r=10, t=30, b=10), 
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 13}},
                    annotations=[dict(text=texto_central, x=0.5, y=0.5, font_size=22, font_color=color_v, showarrow=False, font_weight="bold")]
                )
                return fig

            # --- DIBUJAR LAS 6 COLUMNAS ---
            
            with col1:
                st.plotly_chart(crear_velocimetro_6cols(avance_resi, "🏠 Total Residencial", total_ordenes=total_r), use_container_width=True, key="p1")
                if st.button("🔍 Ver", use_container_width=True, key="b1"):
                    mostrar_detalle_avance("RESIDENCIAL (TOTAL)", df_resi_asignadas, df_resi_cerr)

            with col2:
                st.plotly_chart(crear_velocimetro_6cols(avance_plex, "🏢 Total PLEX", total_ordenes=total_p), use_container_width=True, key="p2")
                if st.button("🔍 Ver", use_container_width=True, key="b2"):
                    mostrar_detalle_avance("PLEX (TOTAL)", df_plex_asignadas, df_plex_cerr)

            with col3:
                st.plotly_chart(crear_velocimetro_6cols(avance_global, "🌍 Avance Global", total_ordenes=total_v), use_container_width=True, key="p3")
                if st.button("🔍 Ver Global", use_container_width=True, key="b3"):
                    mostrar_detalle_avance("GLOBAL (TOTAL)", df_solo_asignadas_monitor, df_cerradas_hoy_monitor)
            
            st.markdown("<div style='border-top: 1px solid #333; margin: 15px 0;'></div>", unsafe_allow_html=True)

            with col4:
                st.plotly_chart(crear_velocimetro_6cols(av_mora_resi, "🏠 Mora Resi", es_mora=True, total_ordenes=len(df_resi_m_inicio)), use_container_width=True, key="p4")
                if st.button("🔍 Ver Mora", use_container_width=True, key="b4"):
                    mostrar_detalle_avance("MORA RESIDENCIAL", df_resi_m_pend, df_resi_m_cerr, df_resi_m_inicio)

            with col5:
                st.plotly_chart(crear_velocimetro_6cols(av_mora_plex, "🏢 Mora PLEX", es_mora=True, total_ordenes=len(df_plex_m_inicio)), use_container_width=True, key="p5")
                if st.button("🔍 Ver Mora", use_container_width=True, key="b5"):
                    mostrar_detalle_avance("MORA PLEX", df_plex_m_pend, df_plex_m_cerr, df_plex_m_inicio)

            with col6:
                st.plotly_chart(crear_velocimetro_6cols(av_mora_global, "🌍 Mora Global", es_mora=True, total_ordenes=len(df_inicio_mora_total)), use_container_width=True, key="p6")
                if st.button("🔍 Mora Global", use_container_width=True, key="b6"):
                    mostrar_detalle_avance("MORA GLOBAL", df_mora_pendiente_actual, df_mora_cerrada_hoy, df_inicio_mora_total)

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
            if check_criticos_diamante:
                df_v_tabla_monitor = df_todas_pendientes_monitor[df_todas_pendientes_monitor['ES_OFFLINE'] == True]
            else:
                df_v_tabla_monitor = df_solo_asignadas_monitor
        elif status_final_btn == "C_HOY": 
            df_v_tabla_monitor = df_cerradas_hoy_monitor
        else: 
            df_v_tabla_monitor = df_monitor_filtrado[(df_monitor_filtrado['ESTADO'].astype(str).str.contains('ANULADA', na=False, case=False)) & (df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor)]

        t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL DE CONTROL OPERATIVO", "📊 ANALISIS Y GANTT", "📈 ANALÍTICA"])
        
        with t_panel_v:
            if not df_v_tabla_monitor.empty:
                df_estilo_v, row_styler = aplicar_estilos_df(df_v_tabla_monitor)
                
                evento_monitor_diam = st.dataframe(
                    df_estilo_v.style.apply(row_styler, axis=1),
                    column_config={
                        "GPS": st.column_config.LinkColumn("UBICACIÓN GPS"),
                        "NOMBRE": st.column_config.TextColumn("NOMBRE", width="medium"),
                        "COLONIA": st.column_config.TextColumn("COLONIA", width="medium"),
                        "COMENTARIO": st.column_config.TextColumn("COMENTARIO", width="large"),
                        "ES_OFFLINE": None,
                        "MINUTOS_CALC": None
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
