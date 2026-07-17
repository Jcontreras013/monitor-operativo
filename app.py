import streamlit as st
import pandas as pd
import numpy as np
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
import sys
import expediente # Importación modular correcta al inicio [3]

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout
from ui_components import (
    aplicar_estilos_nativos, 
    mostrar_comentario_cierre, 
    mostrar_detalle_avance, 
    aplicar_estilos_df,
    mostrar_seguimientos_tecnico
)

import settings 

try:
    from streamlit_option_menu import option_menu
except ImportError:
    st.error("⚠️ Falta la librería. Asegúrate de agregar 'streamlit-option-menu' a tu requirements.txt")
    option_menu = None

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'. Asegúrate de crearlo en la misma carpeta para ver la Auditoría de Vehículos.")

try:
    import biometrico
except ImportError:
    st.error("⚠️ Falta el archivo 'biometrico.py'. Asegúrate de crearlo en la misma carpeta para ver el reporte Biométrico.")

try:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from tools import (
        COLUMNS_MAPPING, 
        es_offline_preciso, 
        procesar_dataframe_base, 
        depurar_archivos_en_crudo,
        depurar_api_con_dispositivos,
        consultar_api_ordenes,
        logica_generar_pdf,
        generar_pdf_cierre_diario,
        generar_pdf_semanal,
        generar_pdf_mensual,
        generar_pdf_trimestral_detallado,
        generar_pdf_primera_orden,
        generar_pdf_pendientes_dispatch,
        get_honduras_time,
        parse_date_ultra_safe,
        procesar_fechas_seguro,
        generar_pdf_tiempos_muertos,
        generar_pdf_promedio_arranque,
        generar_tablas_gerenciales,
        cargar_y_limpiar_crudos_diamante_monitor,
        extraer_seguimientos_tecnico_unificado,
        generar_pdf_ordenes_totales,
        sobrescribir_archivo_gcs,
        leer_espejo_gcs,
        clasificar_materiales,               
        generar_pdf_materiales_mensual
    )
except ImportError as e:
    st.error(f"⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'. Detalle: {e}")

# ==============================================================================
# 1. CONFIGURACIÓN INICIAL DE LA INTERFAZ
# ==============================================================================
st.set_page_config(
    layout="wide", 
    page_title="Monitor Operativo Maxcom PRO", 
    page_icon="⚡",
    initial_sidebar_state="collapsed" 
)

st.markdown("""
    <style>
    .js-plotly-plot .plotly text {
        user-select: text !important;
        pointer-events: auto !important;
        cursor: text !important;
    }
    </style>
""", unsafe_allow_html=True)

PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
ACTIVIDADES_BASURA = ['ACTUALIZACIONDATOS', 'ACTUALIZACIOFW', 'ACTUALIZAINFOTECNICA', 'ACTUALIZARDATOSTECNICOS', 'ACTUALIZARSENSOR']
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# SIFCRONIZACIÓN DE DATOS CON LA NUBE
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("☁️ Descargando historial desde GCS (Alta Velocidad)..."):
            df_nube = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
            
            if df_nube is None or df_nube.empty:
                df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                
            if df_nube is not None and not df_nube.empty:
                df_nube = df_nube.dropna(how='all')
                df_nube.columns = df_nube.columns.str.upper().str.strip()

                if 'SUSCRIPTOR' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE_CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'NOMBRE_CLIENTE': 'NOMBRE'}, inplace=True)

                if 'ACTIVIDAD' in df_nube.columns:
                    mask_basura_sync = df_nube['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
                    df_nube = df_nube[~mask_basura_sync].copy()

            if 'EMPRESA' in df_nube.columns:
                mask_empresas_sync = df_nube['EMPRESA'].astype(str).str.strip().str.upper().str.contains('ISCA|CEQUI', na=False)
                df_nube = df_nube[mask_empresas_sync].copy()

                df_nube = procesar_fechas_seguro(df_nube, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
                
                if 'HORA_INI' in df_nube.columns and 'HORA_LIQ' in df_nube.columns:
                    df_nube['MINUTOS_CALC'] = (df_nube['HORA_LIQ'] - df_nube['HORA_INI']).dt.total_seconds() / 60
                    df_nube['MINUTOS_CALC'] = df_nube['MINUTOS_CALC'].fillna(0.0)
                    
                    diff_nube = df_nube['HORA_LIQ'] - df_nube['HORA_INI']
                    df_nube['TIEMPO_REAL'] = np.where(
                        df_nube['HORA_INI'].isnull() | df_nube['HORA_LIQ'].isnull(),
                        "---",
                        (diff_nube.dt.total_seconds() // 3600).fillna(0).astype(int).astype(str) + "h " +
                        ((diff_nube.dt.total_seconds() % 3600) // 60).fillna(0).astype(int).astype(str) + "m"
                    )

                for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
                    if col_b in df_nube.columns: df_nube[col_b] = df_nube[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])

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
                    df_nube = pd.concat([df_validos, df_invalidos]).drop(columns=['FECHA_SORT'], errors='ignore')
                        
                if 'DIAS_RETRASO' in df_nube.columns: df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
                if 'ESTADO' in df_nube.columns: df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                ahora_momento_ts = pd.Timestamp(get_honduras_time())
                fecha_limite_7d = ahora_momento_ts - timedelta(days=7) 
                
                if 'HORA_LIQ' in df_nube.columns and 'FECHA_APE' in df_nube.columns and 'ESTADO' in df_nube.columns:
                    mask_vivas = df_nube['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                    df_nube = df_nube[(df_nube['HORA_LIQ'] >= fecha_limite_7d) | (df_nube['FECHA_APE'] >= fecha_limite_7d) | (df_nube['HORA_LIQ'].isna()) | mask_vivas].copy()

                cols_orden_ideal = ['DIAS_RETRASO', 'NUM', 'ACTIVIDAD', 'CLIENTE', 'NOMBRE', 'COLONIA', 'TECNICO', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL', 'ESTADO', 'COMENTARIO', 'ES_OFFLINE', 'SOP', 'RAZON_CIERRE_SOP', 'SEGMENTO', 'ALERTA_TIEMPO']
                cols_presentes = [c for c in cols_orden_ideal if c in df_nube.columns]
                cols_restantes = [c for c in df_nube.columns if c not in cols_presentes]
                df_nube = df_nube[cols_presentes + cols_restantes]

                st.session_state.df_base = df_nube
                
                st.success(f"✅ Sincronización Exitosa. Se cargaron {len(df_nube)} órdenes de la nube.")
                import time
                time.sleep(1.5)
                st.rerun()
            else: 
                st.warning("⚠️ La base de datos en la nube está completamente vacía. Sube archivos como Admin primero.")
                import time
                time.sleep(3)
    except Exception as e: 
        st.error(f"❌ Error crítico al conectar con la nube: {e}")
        import time
        time.sleep(3)

# ==============================================================================
# INTERFAZ PRINCIPAL (MAIN)
# ==============================================================================
def main():
    settings.inicializar_configuracion() 

    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    
    ancho_pantalla = streamlit_js_eval(js_expressions='window.screen.width', key='WIDTH_CHECK', want_output=True)
    es_movil = (ancho_pantalla is not None) and (ancho_pantalla < 800)

    if rol_usuario in ['admin', 'jefe']:
        es_movil = False

    if es_movil:
        aplicar_estilos_nativos()

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error("Error al inicializar la conexión con Google Sheets.")
        conn = None

    if str(rol_usuario).strip().lower() == 'llamados':
        expediente.mostrar_modulo_expedientes(conn, pd.DataFrame())
        mostrar_boton_logout() 
        st.stop() 

    sidebar_top = st.sidebar.container()
    sidebar_bottom = st.sidebar.container()

    if es_movil and option_menu is not None:
        st.markdown("""
            <style>
            [data-testid="collapsedControl"] { display: none; }
            .bottom-menu-container {
                position: fixed; bottom: 0; left: 0; width: 100%; z-index: 9999;
                background-color: #1A1D24; padding-bottom: 10px; padding-top: 5px;
                border-top: 1px solid #2D2F39; box-shadow: 0px -2px 10px rgba(0,0,0,0.5);
            }
            </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="bottom-menu-container">', unsafe_allow_html=True)
        
        if rol_usuario in ['admin', 'jefe']:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor", "Reportes", "Vehículos", "Más"],
                icons=["lightning", "bar-chart", "car-front", "list"],
                default_index=0,
                orientation="horizontal",
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#94A3B8", "font-size": "20px"}, 
                    "nav-link": {"font-size": "11px", "text-align": "center", "margin":"0px", "--hover-color": "#2D2F39", "padding": "5px"},
                    "nav-link-selected": {"background-color": "transparent", "color": "#3B82F6", "font-weight": "bold"},
                }
            )
            if selected_nav == "Monitor": nav_menu_diamante = "⚡ Monitor en Vivo"
            elif selected_nav == "Reportes": nav_menu_diamante = "📊 Centro de Reportes"
            elif selected_nav == "Vehículos": nav_menu_diamante = "🚙 Auditoría Vehículos"   
            else: 
                nav_menu_diamante = st.selectbox("Seleccione un módulo extra:", ["📅 Reprog / No Inst", "⚙️ Configuración", "📁 Expedientes"])
        else:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor"],
                icons=["lightning"],
                default_index=0,
                orientation="horizontal",
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#94A3B8", "font-size": "20px"}, 
                    "nav-link": {"font-size": "11px", "text-align": "center", "margin":"0px", "--hover-color": "#2D2F39", "padding": "5px"},
                    "nav-link-selected": {"background-color": "transparent", "color": "#3B82F6", "font-weight": "bold"},
                }
            )
            nav_menu_diamante = "⚡ Monitor en Vivo"
            
        st.markdown('</div>', unsafe_allow_html=True)
        if nav_menu_diamante != "⚡ Monitor en Vivo": st.divider()
    else:
        with sidebar_top:
            if rol_usuario in ['admin', 'jefe']:
                nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "📅 Reprog / No Inst", "🚙 Auditoría Vehículos", "⚙️ Configuración", "📁 Expedientes"])
            else:
                st.markdown("### 🖥️ Menú de Control")
                st.info("🔒 Tienes acceso exclusivo al Monitor en Vivo.")
                nav_menu_diamante = "⚡ Monitor en Vivo"

    with sidebar_bottom:
        if not es_movil: st.markdown("<br><br>", unsafe_allow_html=True)
        st.divider()
        st.markdown("### ☁️ Sincronización")
        if st.button("📥 ACTUALIZAR DESDE LA NUBE", help="Descargar última versión desde Google Cloud", use_container_width=True, key="btn_nube_sidebar"):
            if conn is not None: sincronizar_datos_nube(conn)
            else: st.error("La conexión a la nube no está disponible.")
        st.markdown("<br>", unsafe_allow_html=True)
        mostrar_boton_logout()

        mostrar_cargador = False
        if str(rol_usuario).strip().lower() != 'monitoreo' and not es_movil:
            mostrar_cargador = True

        file_act_ptr = None
        file_disp_ptr = None
        btn_reprocesar = False
        btn_api_procesar = False
        
        if mostrar_cargador:
            st.divider()
            st.markdown("### 📥 Carga de Archivos")
            
            if es_admin:
                st.markdown("#### ⚡ Sincronización por API (Cepheus)")
                fecha_inicio_api = st.date_input("Fecha de Extracción API:", value=get_honduras_time().date() - timedelta(days=7), key="api_date_input_sidebar")
                btn_api_procesar = st.button("🔌 DESCARGAR DE CEPHEUS API", use_container_width=True, type="primary")
                
                st.divider()
                st.markdown("#### 🚙 Carga FTTX e Históricos")
                st.caption("Subida tradicional manual de Dispositivos FTTX o rep_actividades en caso de contingencia.")
                archivos_uploader_diamante = st.file_uploader("Sube rep_actividades y/o FttxActiveDevice", type=["xlsx", "csv"], accept_multiple_files=True)
                
                if archivos_uploader_diamante:
                    for file_item in archivos_uploader_diamante:
                        f_name_lwr = file_item.name.lower()
                        if "actividades" in f_name_lwr: 
                            file_act_ptr = file_item
                        elif "device" in f_name_lwr or "dispositivos" in f_name_lwr: 
                            file_disp_ptr = file_item
                            try:
                                with open("cache_fttx.tmp", "wb") as f: f.write(file_item.getvalue())
                            except: pass
                btn_reprocesar = st.button("🔄 PROCESAR ARCHIVOS SUBIDOS", use_container_width=True)
            else:
                st.caption("Solo necesitas subir las actividades. FTTX se bajará de la nube.")
                archivo_unico = st.file_uploader("Sube únicamente el rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False)
                if archivo_unico: file_act_ptr = archivo_unico
                btn_reprocesar = st.button("🔄 PROCESAR ARCHIVO SUBIDO", use_container_width=True)

            ahora_hx = get_honduras_time()
            es_horario_tarde = ahora_hx.hour >= 17
            es_fin_de_semana = (ahora_hx.weekday() == 5 and ahora_hx.hour >= 13) or (ahora_hx.weekday() == 6)
            condicion_usar_cache = es_horario_tarde or es_fin_de_semana
            
            if condicion_usar_cache and file_act_ptr is not None and file_disp_ptr is None and es_admin:
                if os.path.exists("cache_fttx.tmp"):
                    try:
                        with open("cache_fttx.tmp", "rb") as f: file_disp_ptr = f.read()
                        st.info("🕒 **Modo Caché Activo:** Se cargó automáticamente el último archivo FTTX guardado.")
                    except: pass

    # ==============================================================================
    # 2. CARGA Y PROCESAMIENTO DE DATOS (MIGRADO A GCS CON API INTEGRADA)
    # ==============================================================================
    if 'df_base' not in st.session_state or btn_reprocesar or btn_api_procesar:
        if btn_api_procesar:
            with st.spinner("🔌 Conectando y descargando actividades de Cepheus API en Vivo..."):
                try:
                    fecha_dt_api = datetime.combine(fecha_inicio_api, dt_time(0, 0))
                    df_api_raw = consultar_api_ordenes(fecha_dt_api)
                    
                    if df_api_raw is None or df_api_raw.empty:
                        st.error("❌ No se obtuvieron órdenes de la API de Cepheus para el rango de fecha configurado.")
                    else:
                        # Descargar o resolver catálogo FTTX
                        df_fttx_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                        if df_fttx_cloud is None or df_fttx_cloud.empty:
                            df_fttx_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", ttl=0)
                        
                        df_depurado = depurar_api_con_dispositivos(df_api_raw, df_fttx_cloud)
                        df_depurado = procesar_fechas_seguro(df_depurado, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
                        
                        ahora_momento_ts = pd.Timestamp(get_honduras_time())
                        fecha_limite_7d_ventana = ahora_momento_ts - timedelta(days=7) 
                        mask_vivas_loc = df_depurado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                        df_depurado = df_depurado[(df_depurado['HORA_LIQ'] >= fecha_limite_7d_ventana) | (df_depurado['FECHA_APE'] >= fecha_limite_7d_ventana) | (df_depurado['HORA_LIQ'].isna()) | mask_vivas_loc].copy()
                        
                        df_depurado['DIAS_RETRASO'] = (ahora_momento_ts.normalize() - df_depurado['FECHA_APE'].dt.normalize()).dt.days.fillna(0).astype(int)
                        if 'TECNICO' in df_depurado.columns:
                            df_depurado.loc[df_depurado['TECNICO'].str.strip().str.upper() == 'JOSUE MIGUEL SAUCEDA', 'DIAS_RETRASO'] = 0

                        # Cálculos operativos básicos en vivo
                        act_upper = df_depurado['ACTIVIDAD'].fillna('').astype(str).str.upper()
                        est_upper = df_depurado['ESTADO'].fillna('').astype(str).str.upper().str.strip()
                        com_upper = df_depurado['COMENTARIO'].fillna('').astype(str).str.upper()
                        cli_upper = df_depurado['CLIENTE'].fillna('').astype(str).str.upper()
                        mins_diff = (ahora_momento_ts - df_depurado['HORA_INI']).dt.total_seconds() / 60

                        mask_sop = act_upper.str.contains('SOPFIBRA', regex=True)
                        mask_falsos = act_upper.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)

                        df_depurado['ALERTA_TIEMPO'] = (
                            (df_depurado['HORA_INI'].notnull()) & (df_depurado['HORA_LIQ'].isnull()) & (mins_diff > 120) & 
                            (est_upper != 'CERRADA') & mask_sop & ~mask_falsos
)

                    # === 1. DEFINICIÓN DE LA VARIABLE FALTANTE ===
                        mask_est_abierto = est_upper != 'CERRADA'

                    # === 2. CÁLCULO SEGURO ===
                        df_depurado['ES_OFFLINE'] = ((df_depurado['TECNICO'].astype(str).str.upper() != 'JOSUE MIGUEL SAUCEDA') & mask_est_abierto & mask_sop & ~mask_falsos & (com_upper.str.contains("ONU OFFLINE|OFF LINE|OFFLINE|LOS EN ROJO|PON ROJO", regex=True) | com_upper.apply(es_offline_preciso)))

                        df_depurado['MINUTOS_CALC'] = (df_depurado['HORA_LIQ'] - df_depurado['HORA_INI']).dt.total_seconds() / 60
                        
                        texto_seg = act_upper + " " + cli_upper + " " + com_upper
                        df_depurado['SEGMENTO'] = np.where(texto_seg.str.contains('PLEX|PEXTERNO|SPLITTEROPT', regex=True), 'PLEX', 'RESIDENCIAL')
                        
                        diff_temp = df_depurado['HORA_LIQ'] - df_depurado['HORA_INI']
                        df_depurado['TIEMPO_REAL'] = np.where(
                            df_depurado['HORA_INI'].isnull() | df_depurado['HORA_LIQ'].isnull(),
                            "---",
                            (diff_temp.dt.total_seconds() // 3600).fillna(0).astype(int).astype(str) + "h " +
                            ((diff_temp.dt.total_seconds() % 3600) // 60).fillna(0).astype(int).astype(str) + "m"
                        )

                        # Consolidar con el histórico maestro
                        df_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                        if df_cloud is None or df_cloud.empty:
                            df_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                            
                        if df_cloud is not None and not df_cloud.empty:
                            df_cloud.columns = df_cloud.columns.str.upper().str.strip()
                            if 'NUM' in df_cloud.columns:
                                df_cloud['NUM'] = df_cloud['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                df_cloud.loc[df_cloud['NUM'] == 'nan', 'NUM'] = 'N/D'
                            if 'ACTIVIDAD' in df_cloud.columns:
                                mask_basura_cloud = df_cloud['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
                                df_cloud = df_cloud[~mask_basura_cloud].copy()
                            if 'EMPRESA' in df_cloud.columns:
                                mask_isca_cloud = df_cloud['EMPRESA'].astype(str).str.strip().str.upper().str.contains('ISCA', na=False)
                                df_cloud = df_cloud[mask_isca_cloud].copy()

                            mask_vivas_nube = df_cloud['ESTADO'].astype(str).str.upper().str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False)
                            df_historial_puro = df_cloud[~mask_vivas_nube].copy()
                            df_combined = pd.concat([df_historial_puro, df_depurado])
                        else:
                            df_combined = df_depurado
                            
                        if 'NUM' in df_combined.columns:
                            df_combined['TIENE_LIQ'] = df_combined.get('HORA_LIQ').notna()
                            df_combined = df_combined.sort_values(by=['TIENE_LIQ'], ascending=True)
                            df_valid_num = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                            df_nd = df_combined[df_combined['NUM'] == 'N/D']
                            df_combined = pd.concat([df_valid_num, df_nd]).drop(columns=['TIENE_LIQ'], errors='ignore')

                        # Formatear fechas antes de persistir
                        df_to_upload = df_combined.copy()
                        for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                            if c_date in df_to_upload.columns:
                                df_to_upload[c_date] = pd.to_datetime(df_to_upload[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                                
                        sobrescribir_archivo_gcs(df_to_upload, NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=df_to_upload)
                        
                        st.session_state.df_base = df_combined
                        st.success("✅ ¡Actualización manual completada en la nube y pantalla recargada!")
                        import time
                        time.sleep(1)
                        st.rerun()
                except Exception as e_manual:
                    st.error(f"❌ Error al intentar forzar la consulta manual: {e_manual}")

        elif btn_reprocesar:
            if not es_admin and file_act_ptr is not None and file_disp_ptr is None:
                with st.spinner("☁️ Descargando base de Vehículos/Dispositivos desde GCS..."):
                    try:
                        df_fttx_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                        if df_fttx_cloud is None or df_fttx_cloud.empty:
                            df_fttx_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", ttl=600)
                        
                        if df_fttx_cloud is not None and not df_fttx_cloud.empty:
                            b_io = io.BytesIO()
                            with pd.ExcelWriter(b_io, engine='openpyxl') as writer:
                                df_fttx_cloud.to_excel(writer, index=False)
                            file_disp_ptr = b_io.getvalue()
                        else: raise ValueError("La pestaña FTTX está vacía.")
                    except Exception as e:
                        b_io = io.BytesIO()
                        with pd.ExcelWriter(b_io, engine='openpyxl') as writer:
                            pd.DataFrame(columns=['ID']).to_excel(writer, index=False)
                        file_disp_ptr = b_io.getvalue()

            if file_act_ptr is None or file_disp_ptr is None:
                if st.session_state.get('df_base') is None:
                    if os.path.exists("Logotipo monitor.png"):
                        col1_img, col2_img, col3_img = st.columns([1, 2, 1])
                        with col2_img:
                            st.image("Logotipo monitor.png", use_container_width=True)
                    else:
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
                    st.session_state.df_hist = res_h_diamante
                    if conn is not None:
                        with st.spinner("☁️ Sincronizando y uniendo con histórico en GCS..."):
                            try:
                                df_new = res_p_diamante.copy()
                                if 'NUM' in df_new.columns:
                                    df_new['NUM'] = df_new['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    df_new.loc[df_new['NUM'] == 'nan', 'NUM'] = 'N/D'
                                    
                                df_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                                if df_cloud is None or df_cloud.empty:
                                    df_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                                    
                                if df_cloud is not None and not df_cloud.empty:
                                    df_cloud.columns = df_cloud.columns.str.upper().str.strip()
                                    if 'NUM' in df_cloud.columns:
                                        df_cloud['NUM'] = df_cloud['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                        df_cloud.loc[df_cloud['NUM'] == 'nan', 'NUM'] = 'N/D'
                                    if 'ACTIVIDAD' in df_cloud.columns:
                                        mask_basura_cloud = df_cloud['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
                                        df_cloud = df_cloud[~mask_basura_cloud].copy()
                                    
                                    if 'EMPRESA' in df_cloud.columns:
                                        mask_isca_cloud = df_cloud['EMPRESA'].astype(str).str.strip().str.upper().str.contains('ISCA', na=False)
                                        df_cloud = df_cloud[mask_isca_cloud].copy()

                                    PATRON_VIVAS_NUBE = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                    mask_vivas_nube = df_cloud['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS_NUBE, na=False)
                                    df_historial_puro = df_cloud[~mask_vivas_nube].copy()
                                    df_combined = pd.concat([df_historial_puro, df_new])
                                else: df_combined = df_new
                                    
                                if 'NUM' in df_combined.columns:
                                    df_combined['TIENE_LIQ'] = df_combined.get('HORA_LIQ').notna()
                                    df_combined = df_combined.sort_values(by=['TIENE_LIQ'], ascending=True)
                                    df_valid_num = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                                    df_nd = df_combined[df_combined['NUM'] == 'N/D']
                                    df_combined = pd.concat([df_valid_num, df_nd]).drop(columns=['TIENE_LIQ'], errors='ignore')

                                df_to_upload = df_combined.copy()
                                for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                                    if c_date in df_to_upload.columns:
                                        df_to_upload[c_date] = pd.to_datetime(df_to_upload[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                                        
                                sobrescribir_archivo_gcs(df_to_upload, NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=df_to_upload)
                                st.session_state.df_base = df_combined
                                
                                if es_admin and file_disp_ptr is not None and not isinstance(file_disp_ptr, bytes):
                                    try:
                                        if hasattr(file_disp_ptr, 'read'): 
                                            file_disp_ptr.seek(0)
                                            bytes_fttx = file_disp_ptr.read()
                                            sobrescribir_archivo_gcs(bytes_fttx, NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                                            file_disp_ptr.seek(0)

                                        if getattr(file_disp_ptr, 'name', '').lower().endswith('.csv'): 
                                            df_fttx_up = pd.read_csv(file_disp_ptr, sep=None, engine='python')
                                        else: 
                                            df_fttx_up = pd.read_excel(file_disp_ptr, engine='openpyxl')
                                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", data=df_fttx_up)
                                    except Exception as e_fttx: pass
                                
                                st.success("✅ Datos sincronizados en GCS y unidos al historial correctamente.")
                                import time
                                time.sleep(1)
                                st.rerun()
                            except Exception as e: 
                                st.warning(f"Se procesó localmente, pero falló la sincronización con la nube: {e}")
                                st.session_state.df_base = res_p_diamante
                    else: 
                        st.session_state.df_base = res_p_diamante
                        st.success("✅ Datos procesados localmente.")
                else: return

        if 'df_base' not in st.session_state:
            df_gcs_init = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
            if df_gcs_init is not None and not df_gcs_init.empty:
                st.session_state.df_base = df_gcs_init
            else:
                return

    df_base = st.session_state.df_base.copy()
    
    if not df_base.empty:
        if 'TECNICO' in df_base.columns:
            df_base['TECNICO'] = df_base['TECNICO'].astype(str).str.strip().str.upper()
            valores_invalidos_tec = ['NONE', 'NAN', 'N/D', 'NULL', '', '0']
            df_base = df_base[~df_base['TECNICO'].isin(valores_invalidos_tec) & df_base['TECNICO'].notna()]
            
        if 'ACTIVIDAD' in df_base.columns:
            df_base['ACTIVIDAD'] = df_base['ACTIVIDAD'].astype(str).str.strip().str.upper()
            df_base = df_base[(df_base['ACTIVIDAD'] != '') & (df_base['ACTIVIDAD'] != 'NAN') & df_base['ACTIVIDAD'].notna()]

        df_base = df_base.drop_duplicates()
        
        if 'HORA_LIQ' in df_base.columns:
            df_base['HORA_LIQ'] = pd.to_datetime(df_base['HORA_LIQ'], dayfirst=True, errors='coerce')
    
    if 'ACTIVIDAD' in df_base.columns:
        mask_basura_global = df_base['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
        df_base = df_base[~mask_basura_global].copy()

    if 'NUM' in df_base.columns:
        df_base['NUM'] = df_base['NUM'].astype(str)
        temp_date_b = df_base.get('HORA_LIQ', df_base.get('FECHA_APE', pd.NaT))
        df_base['FECHA_SORT'] = pd.to_datetime(temp_date_b, errors='coerce')
        df_base = df_base.sort_values(by='FECHA_SORT', na_position='first')
        df_validos = df_base[df_base['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_invalidos = df_base[df_base['NUM'] == 'N/D']
        df_base = pd.concat([df_validos, df_invalidos]).drop(columns=['FECHA_SORT'], errors='ignore')

    df_base = procesar_fechas_seguro(df_base, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
    if 'SUSCRIPTOR' in df_base.columns and 'NOMBRE' not in df_base.columns: df_base.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
    elif 'NOMBRE CLIENTE' in df_base.columns and 'NOMBRE' not in df_base.columns: df_base.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)

    for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
        if col_b in df_base.columns: df_base[col_b] = df_base[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])
            
    if 'ACTIVIDAD' in df_base.columns:
        act_upper_global = df_base['ACTIVIDAD'].fillna('').astype(str).str.upper()
        mask_no_criticas_g = act_upper_global.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)
        mask_solo_sop_g = act_upper_global.str.contains('SOPFIBRA', regex=True)
        
        if 'ES_OFFLINE' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ES_OFFLINE'] = False
            df_base.loc[~mask_solo_sop_g, 'ES_OFFLINE'] = False
        if 'ALERTA_TIEMPO' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ALERTA_TIEMPO'] = False
            df_base.loc[~mask_solo_sop_g, 'ALERTA_TIEMPO'] = False
            
        def extraer_motivo_falla(row): return "🔧 Mantenimiento General"
        def extraer_segmento_global(row): return "RESIDENCIAL"

        com_up_g = df_base['COMENTARIO'].fillna('').astype(str).str.upper()
        cli_up_g = df_base['CLIENTE'].fillna('').astype(str).str.upper()
        texto_g = act_upper_global + " " + com_up_g

        cond_off = df_base.get('ES_OFFLINE', pd.Series([False]*len(df_base))) == True
        cond_ins = texto_g.str.contains("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", regex=True)
        cond_niv = texto_g.str.contains("NIVEL|DB|POTENCIA|ATENU", regex=True)
        cond_tv  = texto_g.str.contains("TV|CABLE|SEÑAL", regex=True)
        cond_nav = texto_g.str.contains("NAV|INTERNET|LENT", regex=True)

        df_base['MOTIVO'] = np.select(
            [cond_off, cond_ins, cond_niv, cond_tv, cond_nav],
            ["🔴 Offline / Caída", "📦 Instalación / Cambio", "⚡ Niveles Alterados", "📺 Falla de TV", "🌐 Lentitud / Navegación"],
            default="🔧 Mantenimiento General"
        )

        texto_seg_g = act_upper_global + " " + cli_up_g + " " + com_up_g
        df_base['SEGMENTO'] = np.where(texto_seg_g.str.contains('PLEX|PEXTERNO|SPLITTEROPT', regex=True), 'PLEX', 'RESIDENCIAL')

    for col_n in ['DIAS_RETRASO', 'MINUTOS_CALC']:
        if col_n in df_base.columns: df_base[col_n] = pd.to_numeric(df_base[col_n], errors='coerce').fillna(0)
    for col_txt in ['NUM', 'CLIENTE']:
        if col_txt in df_base.columns:
            df_base[col_txt] = pd.to_numeric(df_base[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
            df_base[col_txt] = df_base[col_txt].replace('0', 'N/D')
    
    ahora_local = get_honduras_time()
    hoy_date_valor = ahora_local.date()
    df_base_activa = df_base.copy()

    # ==============================================================================
    # 3. RENDERIZADO DE PANTALLAS Y CONFIGURACIÓN
    # ==============================================================================
    if nav_menu_diamante == "⚙️ Configuración":
        settings.mostrar_configuracion()
        return

    if nav_menu_diamante == "📁 Expedientes":
        expediente.mostrar_modulo_expedientes(conn, df_base)
        return

    if nav_menu_diamante == "🚙 Auditoría Vehículos":
        tab1, tab2 = st.tabs(["🚙 Auditoría Vehículos", "⏱️ Tiempo Tecnicos"])
        
        with tab1:
            try: mostrar_auditoria(es_movil, conn)
            except Exception as e: st.error(f"Ocurrió un error al cargar el módulo de Auditoría: {e}")
            
        with tab2:
            try:
                import tiempot
                tiempot.mostrar_tiempos_tecnicos()
            except ImportError:
                st.warning("⚠️ Falta el archivo 'tiempot.py'. Asegúrate de crearlo en la misma carpeta.")
            except Exception as e:
                st.error(f"Ocurrió un error al cargar el módulo de Tiempo Técnicos: {e}")
                
        return

    if nav_menu_diamante == "📅 Reprog / No Inst":
        st.title("📅 Reprogramadas y No Instalados")
        tab_reprog, tab_noinst = st.tabs(["📅 Reprogramadas (Futuras)", "🚫 NOINSTALADO (Hoy)"])
        
        with tab_reprog:
            st.subheader("📅 Órdenes Agendadas a Futuro")
            df_base['DIAS_RETRASO_REAL'] = (pd.Timestamp(ahora_local).normalize() - pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).astype(int)
            mask_reprog = (df_base['DIAS_RETRASO_REAL'] < 0) & (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False))
            df_reprog = df_base[mask_reprog].copy()
            st.metric("Total Agendadas a Futuro", len(df_reprog))
            if not df_reprog.empty:
                cols_visibles = ['DIAS_RETRASO_REAL', 'NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'TECNICO', 'ESTADO', 'COMENTARIO', 'FECHA_APE']
                cols_finales = [c for c in cols_visibles if c in df_reprog.columns]
                def highlight_reprog(row): return ['background-color: #1a2a3a; color: #58a6ff; font-weight: bold' if col == 'DIAS_RETRASO_REAL' else '' for col in row.index]
                st.dataframe(df_reprog[cols_finales].style.apply(highlight_reprog, axis=1), use_container_width=True, height=600, hide_index=True)
            else: st.success("✅ No hay órdenes reprogramadas para fechas futuras en este momento.")

        with tab_noinst:
            st.subheader("🚫 Órdenes Cerradas como NOINSTALADO Hoy")
            mask_noinst_hoy = (df_base['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)) & (df_base['HORA_LIQ'].dt.date == hoy_date_valor)
            st.dataframe(df_base[mask_noinst_hoy][['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']], use_container_width=True, height=600, hide_index=True)
            
        return

    # ==============================================================================
    # 4. FILTROS Y LÓGICA COMPARTIDA PARA MONITOR Y REPORTES
    # ==============================================================================
    filtro_actividad = []
    filtro_estado = []
    filtro_motivo = []
    check_criticos_diamante = False
    check_no_asignadas = False 
    tec_filtro_monitor = "Todos"

    if nav_menu_diamante == "⚡ Monitor en Vivo":
        filtro_container = st.expander("🎛️ Filtros Rápidos y Búsqueda", expanded=False) if es_movil else sidebar_top
        with filtro_container:
            if not es_movil: st.markdown("---")
            st.markdown("### 🎛️ Filtros Múltiples")
            
            lista_actividades = sorted(df_base_activa['ACTIVIDAD'].dropna().unique().tolist())
            lista_estados = sorted(df_base_activa['ESTADO'].dropna().unique().tolist())
            lista_motivos = sorted(df_base_activa['MOTIVO'].dropna().unique().tolist()) if 'MOTIVO' in df_base_activa.columns else []
            
            filtro_actividad = st.multiselect("🛠️ Tipo de Actividad:", options=lista_actividades, default=[], placeholder="Todas las actividades")
            filtro_estado = st.multiselect("🚦 Estado de Orden:", options=lista_estados, default=[], placeholder="Todos los estados")
            filtro_motivo = st.multiselect("⚠️ Motivo / Diagnóstico:", options=lista_motivos, default=[], placeholder="Todos los motivos")
            
            st.divider() 
            st.markdown("### 🔍 Filtros en Vivo")
            
            m_viva_count = df_base_activa['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            
            if 'ES_OFFLINE' not in df_base_activa.columns:
                df_base_activa['ES_OFFLINE'] = False
            mascara_offline_segura = df_base_activa['ES_OFFLINE'] == True
            
            total_off_count_viva = int((mascara_offline_segura & m_viva_count).sum())
            
            mascara_no_asignadas = (df_base_activa['TECNICO'].isna()) | (df_base_activa['TECNICO'].astype(str).str.strip() == '') | (df_base_activa['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
            total_no_asignadas_viva = int((mascara_no_asignadas & m_viva_count).sum())
            
            check_criticos_diamante = st.toggle(f"🚨 Ver solo Críticas ({total_off_count_viva})")
            check_no_asignadas = st.toggle(f"🚨 Ver NO Asignadas ({total_no_asignadas_viva})")
         
            total_vivas = int(m_viva_count.sum()) 
            check_ordenes_totales = st.toggle(f"📋 Órdenes Totales Pendientes ({total_vivas})")
            
            if check_ordenes_totales:
                if st.button("📄 GENERAR PDF DE ÓRDENES TOTALES", use_container_width=True):
                    with st.spinner("Generando documento PDF..."):
                        df_vivas_export = df_base_activa[m_viva_count].copy()
                        st.session_state['pdf_totales_gen'] = generar_pdf_ordenes_totales(df_vivas_export, hoy_date_valor)
                if 'pdf_totales_gen' in st.session_state and st.session_state['pdf_totales_gen']:
                    st.download_button("📥 DESCARGAR PDF TOTAL", data=st.session_state['pdf_totales_gen'], file_name=f"Ordenes_Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            
            lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor)

        df_monitor_filtrado = df_base_activa.copy()
        if len(filtro_actividad) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
        if len(filtro_estado) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
        if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
        if check_criticos_diamante:
            mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado.get('ALERTA_TIEMPO', False)
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

    # ==============================================================================
    # 5. PANTALLA: CENTRO DE REPORTES
    # ==============================================================================
    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        tab_diario, tab_pendientes, tab_gerencial, tab_biometrico, tab_materiales = st.tabs([
            "📦 Cierre Diario", 
            "📋 Pendientes Generales", 
            "💼 Gerencial (Trimestral)", 
            "⏱️ Biométrico",
            "🔌 Control de Materiales"
        ])

        with tab_pendientes:
            st.subheader("📋 Resumen de Pendientes Generales")
            df_todas_vivas = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)].copy()
            if not df_todas_vivas.empty:
                mask_sin_tec = (df_todas_vivas['TECNICO'].isna()) | (df_todas_vivas['TECNICO'].astype(str).str.strip() == '') | (df_todas_vivas['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
                df_asig = df_todas_vivas[~mask_sin_tec].copy()
                df_no_asig = df_todas_vivas[mask_sin_tec].copy()
                
                def clasificar_dispatch(row):
                    act = str(row.get('ACTIVIDAD', '')).upper(); com = str(row.get('COMENTARIO', '')).upper(); txt = act + " " + com
                    if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act): return "INSTALACIONES"
                    elif re.search("SOP|FALLA|MANT", act): return "MANTENIMIENTOS"
                    elif re.search("PLEX|PEXTERNO|SPLITTEROPT", txt): return "PLEX"
                    else: return "OTRAS"
                    
                if not df_asig.empty:
                    df_asig['CATEGORIA'] = df_asig.apply(clasificar_dispatch, axis=1)
                    res_a = df_asig['CATEGORIA'].value_counts().reset_index()
                    res_a.columns = ['Categoría', 'Asignadas (En Ruta)']
                else: res_a = pd.DataFrame(columns=['Categoría', 'Asignadas (En Ruta)'])
                if not df_no_asig.empty:
                    df_no_asig['CATEGORIA'] = df_no_asig.apply(clasificar_dispatch, axis=1)
                    res_n = df_no_asig['CATEGORIA'].value_counts().reset_index()
                    res_n.columns = ['Categoría', 'Nuevas (Sin Asignar)']
                else: res_n = pd.DataFrame(columns=['Categoría', 'Nuevas (Sin Asignar)'])
                
                df_dispatch = pd.merge(res_a, res_n, on='Categoría', how='outer').fillna(0)
                df_dispatch['Asignadas (En Ruta)'] = df_dispatch['Asignadas (En Ruta)'].astype(int)
                df_dispatch['Nuevas (Sin Asignar)'] = df_dispatch['Nuevas (Sin Asignar)'].astype(int)
                df_dispatch['TOTAL GENERAL'] = df_dispatch['Asignadas (En Ruta)'] + df_dispatch['Nuevas (Sin Asignar)']
                tot_a = df_dispatch['Asignadas (En Ruta)'].sum()
                tot_n = df_dispatch['Nuevas (Sin Asignar)'].sum()
                tot_g = df_dispatch['TOTAL GENERAL'].sum()
                df_totales = pd.DataFrame([{'Categoría': 'TOTAL PENDIENTES', 'Asignadas (En Ruta)': tot_a, 'Nuevas (Sin Asignar)': tot_n, 'TOTAL GENERAL': tot_g}])
                df_dispatch_final = pd.concat([df_dispatch, df_totales], ignore_index=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil: col_kpi1, col_kpi2 = st.columns(2)
                else: col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                with col_kpi1: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #3B82F6; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">ASIGNADAS</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_a}</div></div>""", unsafe_allow_html=True)
                with col_kpi2: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #F59E0B; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">SIN ASIGNAR</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_n}</div></div>""", unsafe_allow_html=True)
                if not es_movil:
                    with col_kpi3: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #10B981; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">TOTAL</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_g}</div></div>""", unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil:
                    def highlight_total(row): return ['background-color: #2D3748; color: white; font-weight: bold' if row['Categoría'] == 'TOTAL PENDIENTES' else '' for _ in row.index]
                    st.dataframe(df_dispatch_final.style.apply(highlight_total, axis=1), use_container_width=True, hide_index=True)
                    st.info("Genera reportes para Dispatch.")
                    buffer = io.BytesIO()
                    df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificar_dispatch, axis=1)
                    cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                    df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Manana')
                    st.download_button(label="📥 Exportar EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                    if st.button("📄 Generar PDF", use_container_width=True, type="primary"):
                        with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                    if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                else:
                    col_d1, col_d2 = st.columns([2, 1])
                    with col_d1:
                        def highlight_total(row): return ['background-color: #2D3748; color: white; font-weight: bold' if row['Categoría'] == 'TOTAL PENDIENTES' else '' for _ in row.index]
                        st.dataframe(df_dispatch_final.style.apply(highlight_total, axis=1), use_container_width=True, hide_index=True, column_config={"Categoría": st.column_config.TextColumn("CLASIFICACIÓN"), "Asignadas (En Ruta)": st.column_config.NumberColumn("🚗 ASIGNADAS", format="%d"), "Nuevas (Sin Asignar)": st.column_config.NumberColumn("📥 SIN ASIGNAR", format="%d"), "TOTAL GENERAL": st.column_config.NumberColumn("📦 TOTAL", format="%d")})
                    with col_d2:
                        st.info("Genera los reportes para enviar al departamento de Dispatch.")
                        buffer = io.BytesIO()
                        df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificar_dispatch, axis=1)
                        cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                        df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Manana')
                        st.download_button(label="📥 Exportar Resumen a EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_Dispatch_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                        if st.button("📄 Generar PDF (Dispatch)", use_container_width=True, type="primary"):
                            with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                        if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF Generado", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_Dispatch_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            else: st.success("🎉 No hay órdenes pendientes registradas. ¡Operación limpia!")

        with tab_biometrico:
            try: biometrico.vista_biometrico()
            except Exception as e: st.error(f"Error al cargar la vista del biométrico: {e}")

        with tab_gerencial:
            st.subheader("📊 Reporte Gerencial Unificado")
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
                        df_maestra = df_maestra.rename(columns={'TECNICO': 'Técnico', 'Dias_Laborados': 'Días Trabajados', 'Promedio_Horas_Dia': 'Hrs / Día', 'ACTIVIDAD': 'Actividad', 'Cantidad': 'Volumen', 'Participacion_%': '% del Total', 'Promedio_Minutos': 'Min. Promedio'})
                        df_maestra = df_maestra[['Técnico', 'Días Trabajados', 'Hrs / Día', 'Actividad', 'Volumen', '% del Total', 'Min. Promedio']]
                        st.success("✅ Datos processed y unificados correctamente.")
                        ordenes_con_error = df_maestra['Min. Promedio'].isna().sum()
                        if ordenes_con_error > 0: st.warning(f"⚠️ Se detectaron {ordenes_con_error} órdenes con errores de tiempo.")
                        st.dataframe(df_maestra, use_container_width=True, hide_index=True)
                        st.markdown("---")
                        if st.button("🚀 GENERAR PDF GERENCIAL COMPLETO", use_container_width=True, type="primary"):
                            with st.spinner("Dibujando secciones por técnico..."): st.session_state['pdf_gerencial'] = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                        if 'pdf_gerencial' in st.session_state: st.download_button(label="📥 Descargar Reporte PDF", data=st.session_state['pdf_gerencial'], file_name=f"Reporte_Gerencial_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                    except Exception as e: st.error(f"❌ Ocurrió un error procesando el reporte: {e}")
        
        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor)
            
            mask_ini_dia = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == fecha_cal_sel
            mask_liq_dia = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce').dt.date == fecha_cal_sel
            mask_ape_dia = (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)) & (pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.date == fecha_cal_sel)
            
            df_para_gantt_diario = df_base[mask_ini_dia | mask_liq_dia | mask_ape_dia].copy()
            
            mask_sin_ini_c = df_para_gantt_diario['HORA_INI'].isna() & df_para_gantt_diario['HORA_LIQ'].notnull()
            df_para_gantt_diario.loc[mask_sin_ini_c, 'HORA_INI'] = df_para_gantt_diario.loc[mask_sin_ini_c, 'HORA_LIQ'] - pd.Timedelta(minutes=30)
            
            df_para_gantt_diario = df_para_gantt_diario[df_para_gantt_diario['HORA_INI'].notnull()].copy()
            
            df_cerradas_espejo = df_para_gantt_diario[(df_para_gantt_diario['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_para_gantt_diario['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()
            df_asignadas_espejo = df_para_gantt_diario[df_para_gantt_diario['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)].copy()

            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cerradas_espejo))
            st.markdown("### 📊 Indicadores de Avance Operativo (Mora)")
            df_asignadas_espejo['FECHA_APE_DT'] = pd.to_datetime(df_asignadas_espejo['FECHA_APE'], errors='coerce')
            df_cerradas_espejo['FECHA_APE_DT'] = pd.to_datetime(df_cerradas_espejo['FECHA_APE'], errors='coerce')
            df_mora_pend_rep = df_asignadas_espejo[df_asignadas_espejo['FECHA_APE_DT'].dt.date < fecha_cal_sel].copy()
            df_mora_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['FECHA_APE_DT'].dt.date < fecha_cal_sel].copy()
            df_inicio_mora_rep = pd.concat([df_mora_pend_rep, df_mora_cerr_rep]).drop_duplicates(subset=['NUM'])
            
            df_plex_m_pend_rep = df_mora_pend_rep[df_mora_pend_rep['SEGMENTO'] == 'PLEX']
            df_plex_m_cerr_rep = df_mora_cerr_rep[df_mora_cerr_rep['SEGMENTO'] == 'PLEX']
            df_plex_m_inicio_rep = df_inicio_mora_rep[df_inicio_mora_rep['SEGMENTO'] == 'PLEX']
            
            df_resi_m_pend_rep = df_mora_pend_rep[df_mora_pend_rep['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_cerr_rep = df_mora_cerr_rep[df_mora_cerr_rep['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_inicio_rep = df_inicio_mora_rep[df_inicio_mora_rep['SEGMENTO'] == 'RESIDENCIAL']
            
            tot_mora_plex_rep = len(df_plex_m_inicio_rep)
            avance_mora_plex_rep = (len(df_plex_m_cerr_rep) / tot_mora_plex_rep * 100) if tot_mora_plex_rep > 0 else 0
            
            tot_mora_resi_rep = len(df_resi_m_inicio_rep)
            avance_mora_resi_rep = (len(df_resi_m_cerr_rep) / tot_mora_resi_rep * 100) if tot_mora_resi_rep > 0 else 0
            
            tot_mora_global_rep = len(df_inicio_mora_rep)
            avance_mora_global_rep = (len(df_mora_cerr_rep) / tot_mora_global_rep * 100) if tot_mora_global_rep > 0 else 0
            
            def crear_velocimetro_rep(valor, titulo, total_ordenes=0):
                color_v = "#EF4444" if valor < 60 else ("#F59E0B" if valor < 90 else "#10B981") 
                if total_ordenes == 0: color_v = "#4B5563"
                fig = go.Figure(go.Pie(values=[valor, max(0, 100 - valor)] if total_ordenes > 0 else [0, 100], labels=['Completado', 'Pendiente'], hole=0.8, marker=dict(colors=[color_v, '#2D2F39']), textinfo='none', hoverinfo='none', direction='clockwise', sort=False))
                fig.update_layout(showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}}, annotations=[dict(text=f"{valor:.0f}%" if total_ordenes > 0 else "N/A", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")])
                return fig

            if es_movil:
                st.plotly_chart(crear_velocimetro_rep(avance_mora_resi_rep, "🏠 Mora Residencial", len(df_resi_m_inicio_rep)), use_container_width=True)
                st.plotly_chart(crear_velocimetro_rep(avance_mora_plex_rep, "🏢 Mora PLEX", len(df_plex_m_inicio_rep)), use_container_width=True)
                st.plotly_chart(crear_velocimetro_rep(avance_mora_global_rep, "🌍 Mora Global", len(df_inicio_mora_rep)), use_container_width=True)
            else:
                col_gr1, col_gr2, col_gr3 = st.columns(3)
                with col_gr1: st.plotly_chart(crear_velocimetro_rep(avance_mora_resi_rep, "🏠 Mora Residencial", len(df_resi_m_inicio_rep)), use_container_width=True)
                with col_gr2: st.plotly_chart(crear_velocimetro_rep(avance_mora_plex_rep, "🏢 Mora PLEX", len(df_plex_m_inicio_rep)), use_container_width=True)
                with col_gr3: st.plotly_chart(crear_velocimetro_rep(avance_mora_global_rep, "🌍 Mora Global", len(df_inicio_mora_rep)), use_container_width=True)
            
            st.markdown("---")

            if not es_movil:
                st.markdown("<h4 style='text-align: center; color: #1F2937;'>⏳ Eficiencia y Tiempos Operativos (Gantt Histórico)</h4><br>", unsafe_allow_html=True)
                
                with st.expander("⏳ LÍNEA DE TIEMPO OPERATIVA (GANTT)", expanded=False):
                    mask_ini_dia = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == fecha_cal_sel
                    df_para_gantt_diario = df_base[mask_ini_dia].copy()
                    
                    if not df_para_gantt_diario.empty:
                        ahora_hx_d = get_honduras_time()
                        
                        df_para_gantt_diario['GANTT_START'] = df_para_gantt_diario['HORA_INI']
                        hora_cierre_proyectada = ahora_hx_d if fecha_cal_sel == ahora_hx_d.date() else datetime.combine(fecha_cal_sel, dt_time(22, 0))
                        
                        df_para_gantt_diario['GANTT_END'] = df_para_gantt_diario['HORA_LIQ'].fillna(hora_cierre_proyectada)
                        
                        mask_inv = df_para_gantt_diario['GANTT_END'] < df_para_gantt_diario['GANTT_START']
                        df_para_gantt_diario.loc[mask_inv, 'GANTT_END'] = df_para_gantt_diario.loc[mask_inv, 'GANTT_START'] + pd.Timedelta(minutes=30)
                        
                        df_para_gantt_diario['Inicio'] = df_para_gantt_diario['HORA_INI'].dt.strftime('%H:%M')
                        df_para_gantt_diario['Cierre'] = df_para_gantt_diario['HORA_LIQ'].apply(
                            lambda x: x.strftime('%H:%M') if pd.notnull(x) else "En curso (Abierta)"
                        )
                        
                        df_para_gantt_diario['TECNICO'] = df_para_gantt_diario['TECNICO'].astype(str).str.strip().str.upper()
                        df_para_gantt_diario = df_para_gantt_diario.dropna(subset=['GANTT_START', 'GANTT_END']).sort_values(by=['TECNICO', 'GANTT_START'])

                        actividades_permitidas = [
                            'CEQUI', 'INSEQUIPO', 'INSFIBRA', 'INSFIBRACORP', 'INSHFC', 
                            'INS-WA', 'NOINSTALADO', 'PEXTERNO', 'PLEXISCA', 'SOP', 
                            'SOPCORP', 'SOPFIBRA', 'SOPFIBRACORP', 'SOPRECONCORP', 
                            'SOPRECONHFC', 'SPLITTEROPT', 'TRASLADOEXTFIBRA', 
                            'TRASLADOEXTFIBRACORP', 'TRASLADOINTERNOFIBRA', 
                            'TRASLADOINTFIBRACORP', 'TVADICIONAL'
                        ]
                        
                        df_para_gantt_diario = df_para_gantt_diario[
                            df_para_gantt_diario['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_permitidas)
                        ]
                        
                        df_para_gantt_diario['INFO_HOVER'] = (
                            "ACTIVIDAD=" + df_para_gantt_diario['ACTIVIDAD'].astype(str) + "<br>" +
                            "NUM=" + df_para_gantt_diario['NUM'].astype(str) + "<br>" +
                            "COLONIA=" + df_para_gantt_diario['COLONIA'].astype(str) + "<br>" +
                            "ESTADO=" + df_para_gantt_diario['ESTADO'].astype(str) + "<br>" +
                            "Inicio=" + df_para_gantt_diario['Inicio'].astype(str) + "<br>" +
                            "Cierre=" + df_para_gantt_diario['Cierre'].astype(str) + "<br>" +
                            "Tiempo Total=" + df_para_gantt_diario['TIEMPO_REAL'].astype(str)
                        )

                        colores_solidos = {
                            "SOPFIBRA": "#d32f2f",         
                            "SOP": "#d32f2f",                
                            "INSFIBRA": "#1976d2",         
                            "INSFIBRACORP": "#0d47a1",     
                            "PEXTERNO": "#f57c00",         
                            "PLEXISCA": "#e65100",         
                            "TRASLADOEXTFIBRA": "#8e24aa",  
                            "SOPRECONHFC": "#c2185b",       
                            "TVADICIONAL": "#00897b"        
                        }

                        fig_gantt_d = px.timeline(
                            df_para_gantt_diario, 
                            x_start="GANTT_START", 
                            x_end="GANTT_END", 
                            y="TECNICO", 
                            color="ACTIVIDAD", 
                            text="ACTIVIDAD",  
                            custom_data=["INFO_HOVER"], 
                            color_discrete_map=colores_solidos,
                            height=max(400, len(df_para_gantt_diario['TECNICO'].unique()) * 45)
                        )
                        
                        fig_gantt_d.update_yaxes(autorange="reversed", title_text="", type="category")
                        hora_inicio_pantalla_d = datetime.combine(fecha_cal_sel, dt_time(6, 0)).strftime('%Y-%m-%d %H:%M:%S')
                        hora_fin_pantalla_d = datetime.combine(fecha_cal_sel, dt_time(22, 0)).strftime('%Y-%m-%d %H:%M:%S')
                        
                        fig_gantt_d.update_xaxes(range=[hora_inicio_pantalla_d, hora_fin_pantalla_d], tickformat="%H:%M", title_text=f"Cronograma Operativo - {fecha_cal_sel.strftime('%d/%m/%Y')}")
                        fig_gantt_d.update_traces(textposition='inside', insidetextanchor='middle', marker_line_color='white', marker_line_width=1.5, opacity=0.9, hovertemplate="%{customdata[0]}<extra></extra>")
                        fig_gantt_d.update_layout(showlegend=True, legend_title_text='Identificador', legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02), margin=dict(t=10, b=20, l=0, r=150), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.02)")
                        
                        st.plotly_chart(fig_gantt_d, use_container_width=True)

                        col_bpdf1, col_bpdf2 = st.columns([1, 2])
                        with col_bpdf1:
                            if st.button("📄 GENERAR PDF TIEMPOS Y TIEMPO PERDIDO", use_container_width=True):
                                with st.spinner("Calculando rendimientos de 8 horas..."):
                                    st.session_state['pdf_tiempos_muertos'] = generar_pdf_tiempos_muertos(df_para_gantt_diario, fecha_cal_sel)
                                    
                            if 'pdf_tiempos_muertos' in st.session_state and st.session_state['pdf_tiempos_muertos']:
                                st.download_button(
                                    label=f"📥 Descargar PDF (Eficiencia {fecha_cal_sel.strftime('%d-%m')})", 
                                    data=st.session_state['pdf_tiempos_muertos'], 
                                    file_name=f"Eficiencia_Tiempos_{fecha_cal_sel}.pdf", 
                                    mime="application/pdf", 
                                    type="primary", 
                                    use_container_width=True
                                )
                        st.markdown("---")
                    else:
                        st.info("No hay actividades registradas en esta fecha para generar el Gantt.")

            if not df_cerradas_espejo.empty:
                st.markdown("### 📊 Desglose de Producción")
                if es_movil: cs_col, ci_col = st.columns(2)
                else: cs_col, ci_col, cp_col, co_col = st.columns(4)
                
                with cs_col:
                    st.write("**SOP**")
                    df_sop = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_sop, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_sop['Cant'].sum()}**")
                with ci_col:
                    st.write("**Instalaciones**")
                    txt_ins_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_ins_general = txt_ins_c.str.contains('INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_ins_cierre = df_cerradas_espejo[mask_ins_general].copy()
                    if not df_ins_cierre.empty:
                        def clasificiar_ins_cierre(row):
                            txt = (str(row.get('ACTIVIDAD','')) + " " + str(row.get('COMENTARIO',''))).upper()
                            if re.search('ADIC', txt): return 'Adición'
                            if re.search('CAMBIO|MIGRACI', txt): return 'Cambio / Migración'
                            if re.search('RECUP', txt): return 'Recuperado'
                            return 'Nueva'
                        df_ins_cierre['SUBTIPO'] = df_ins_cierre.apply(clasificiar_ins_cierre, axis=1)
                        df_ins_grouped = df_ins_cierre['SUBTIPO'].value_counts().reset_index()
                        df_ins_grouped.columns = ['Instalaciones', 'Cant']
                        st.dataframe(df_ins_grouped, hide_index=True, use_container_width=True)
                        st.write(f"**Total: {df_ins_grouped['Cant'].sum()}**")
                    else: st.write("Sin datos")
                
                if es_movil: cp_col, co_col = st.columns(2)

                with cp_col:
                    st.write("**Plex**")
                    df_plex = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('PLEX|PEXTERNO|SPLITTEROPT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_plex, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_plex['Cant'].sum()}**")
                with co_col:
                    st.write("**Otros**")
                    txt_otr_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|PEXTERNO|SPLITTEROPT|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_otros = df_cerradas_espejo[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_otros, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_otros['Cant'].sum()}**")

            st.markdown("---")
            
            st.markdown("### ⚖️ Resumen Consolidado: Efectividad de Mora")
            m_rep = df_inicio_mora_rep.groupby('ACTIVIDAD').size().reset_index(name='INICIO (MORA)')
            p_rep = df_mora_pend_rep.groupby('ACTIVIDAD').size().reset_index(name='PENDIENTES')
            c_rep = df_mora_cerr_rep.groupby('ACTIVIDAD').size().reset_index(name='CERRADAS')
            resumen_global_rep = pd.merge(m_rep, p_rep, on='ACTIVIDAD', how='outer').fillna(0)
            resumen_global_rep = pd.merge(resumen_global_rep, c_rep, on='ACTIVIDAD', how='outer').fillna(0)
            
            if not resumen_global_rep.empty:
                resumen_global_rep['INICIO (MORA)'] = resumen_global_rep['INICIO (MORA)'].astype(int)
                resumen_global_rep['PENDIENTES'] = resumen_global_rep['PENDIENTES'].astype(int)
                resumen_global_rep['CERRADAS'] = resumen_global_rep['CERRADAS'].astype(int)
                resumen_global_rep.rename(columns={'ACTIVIDAD': 'TIPO'}, inplace=True)
                resumen_global_rep = resumen_global_rep[['TIPO', 'INICIO (MORA)', 'PENDIENTES', 'CERRADAS']].sort_values(by='TIPO').reset_index(drop=True)
                tot_m = resumen_global_rep['INICIO (MORA)'].sum()
                tot_p = resumen_global_rep['PENDIENTES'].sum()
                tot_c = resumen_global_rep['CERRADAS'].sum()
                fila_tot = pd.DataFrame([{'TIPO': 'TOTAL GENERAL', 'INICIO (MORA)': tot_m, 'PENDIENTES': tot_p, 'CERRADAS': tot_c}])
                resumen_global_rep = pd.concat([resumen_global_rep, fila_tot], ignore_index=True)
                st.dataframe(resumen_global_rep, use_container_width=True, hide_index=True)
            else: st.info("No hay datos de mora consolidada para esta fecha.")

            st.markdown("### ⏱️ Tiempos de Atencion Promedio")
            if not df_cerradas_espejo.empty:
                df_pivot_diario = df_cerradas_espejo.groupby(['TECNICO', 'ACTIVIDAD']).agg(Órdenes=('NUM', 'count'), Prom_Duracion_Min=('MINUTOS_CALC', 'mean')).round(1)
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
                    st.dataframe(df_primera_mostrar, use_container_width=True, hide_index=True)

                    st.markdown("<br>", unsafe_allow_html=True)
                    if es_movil: col_btn1, col_btn2 = st.columns(2)
                    else: col_btn1, col_btn2 = st.columns([1, 2])
                    with col_btn1:
                        if st.button("📄 GENERAR PDF PRIMERA ORDEN", use_container_width=True):
                            try:
                                with st.spinner("Generando PDF..."): st.session_state['pdf_primera'] = generar_pdf_primera_orden(df_base, fecha_cal_sel)
                            except Exception as e: st.error(f"Error generando PDF: {e}")
                        if 'pdf_primera' in st.session_state and st.session_state['pdf_primera']: st.download_button("📥 Descargar PDF (Inicio Jornada)", data=st.session_state['pdf_primera'], file_name=f"Primeras_Ordenes_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                else: st.info("No hay registros de inicio de órdenes para esta fecha.")
            else: st.info("No hay registros de inicio de órdenes para esta fecha.")

            st.markdown("---")
            st.markdown("### 📅 Promedio Semanal: Primera Orden del Día")
            st.caption("Calcula el promedio de la hora en la que cada técnico inicia su primera orden dentro del rango seleccionado.")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                f_inicio_primera = st.date_input("Fecha Inicio:", value=hoy_date_valor - timedelta(days=6), key="f_ini_arranque")
            with col_sel2:
                f_fin_primera = st.date_input("Fecha Fin:", value=hoy_date_valor, key="f_fin_arranque")
                
            if st.button("⚙️ Calcular Promedio de Inicio", use_container_width=True):
                if f_inicio_primera > f_fin_primera:
                    st.warning("⚠️ La Fecha de Inicio no puede ser mayor que la Fecha Fin.")
                else:
                    df_base_prom = df_base.copy()
                    if 'HORA_INI' in df_base_prom.columns:
                        df_base_prom['HORA_INI_DT'] = pd.to_datetime(df_base_prom['HORA_INI'], errors='coerce')
                        df_base_prom = df_base_prom.dropna(subset=['HORA_INI_DT'])
                        
                        mask_rango = (df_base_prom['HORA_INI_DT'].dt.date >= f_inicio_primera) & (df_base_prom['HORA_INI_DT'].dt.date <= f_fin_primera)
                        df_rango = df_base_prom[mask_rango].copy()
                        
                        if not df_rango.empty:
                            df_rango['Fecha_Sola'] = df_rango['HORA_INI_DT'].dt.date
                            primeras_ordenes_rango = df_rango.sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO', 'Fecha_Sola'], keep='first')
                            
                            primeras_ordenes_rango['Segundos_Inicio'] = primeras_ordenes_rango['HORA_INI_DT'].dt.hour * 3600 + \
                                                                        primeras_ordenes_rango['HORA_INI_DT'].dt.minute * 60 + \
                                                                        primeras_ordenes_rango['HORA_INI_DT'].dt.second
                                                                        
                            promedios_inicio = primeras_ordenes_rango.groupby('TECNICO').agg(
                                Dias_Computados=('Fecha_Sola', 'nunique'),
                                Promedio_Segundos=('Segundos_Inicio', 'mean')
                            ).reset_index()
                            
                            def secs_to_time_str(s):
                                if pd.isnull(s): return "N/D"
                                h, r = divmod(int(s), 3600)
                                m, sec = divmod(r, 60)
                                return f"{h:02d}:{m:02d}:{sec:02d}"
                                
                            promedios_inicio['Hora_Promedio_Inicio'] = promedios_inicio['Promedio_Segundos'].apply(secs_to_time_str)
                            promedios_inicio = promedios_inicio.sort_values('Promedio_Segundos')
                            
                            mask_tecnicos_validos = (promedios_inicio['TECNICO'].notna()) & (promedios_inicio['TECNICO'].str.strip() != '')
                            promedios_inicio = promedios_inicio[mask_tecnicos_validos]

                            st.session_state['df_promedios_inicio'] = promedios_inicio
                        else:
                            st.session_state['df_promedios_inicio'] = pd.DataFrame()
                            st.warning("⚠️ No se encontraron órdenes iniciadas en este rango de fechas.")
                            
            if 'df_promedios_inicio' in st.session_state and not st.session_state['df_promedios_inicio'].empty:
                promedios_mostrar = st.session_state['df_promedios_inicio']
                
                st.dataframe(
                    promedios_mostrar[['TECNICO', 'Dias_Computados', 'Hora_Promedio_Inicio']], 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TECNICO": st.column_config.TextColumn("👨‍🔧 Técnico"),
                        "Dias_Computados": st.column_config.NumberColumn("📅 Días Evaluados", format="%d"),
                        "Hora_Promedio_Inicio": st.column_config.TextColumn("⏰ Hora Promedio de Arranque")
                    }
                )
                
                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil: col_btn_p1, col_btn_p2 = st.columns(2)
                else: col_btn_p1, col_btn_p2 = st.columns([1, 2])
                
                with col_btn_p1:
                    if st.button("📄 GENERAR PDF PROMEDIO SEMANAL", use_container_width=True):
                        try:
                            with st.spinner("Generando PDF..."):
                                st.session_state['pdf_promedio_arranque'] = generar_pdf_promedio_arranque(promedios_mostrar, f_inicio_primera, f_fin_primera)
                        except Exception as e:
                            st.error(f"Error generando PDF: {e}")
                            
                    if 'pdf_promedio_arranque' in st.session_state and st.session_state['pdf_promedio_arranque']:
                        st.download_button(
                            "📥 Descargar PDF (Promedio Semanal)", 
                            data=st.session_state['pdf_promedio_arranque'], 
                            file_name=f"Promedio_Arranque_{f_inicio_primera}.pdf", 
                            mime="application/pdf", 
                            type="primary", 
                            use_container_width=True
                        )

            st.markdown("---")
            st.markdown("### 📥 Exportación")
            if st.button("🚀 GENERAR PDF DE CIERRE DIARIO", use_container_width=True, type="primary"):
                with st.spinner("Preparando archivo de cierre..."): st.session_state['pdf_cierre'] = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
            if 'pdf_cierre' in st.session_state: st.download_button("📥 Descargar Archivo (PDF)", data=st.session_state['pdf_cierre'], file_name=f"Cierre_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            st.markdown("---")
            with st.expander("Ver Lista Detallada"): st.dataframe(df_cerradas_espejo[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)

        with tab_materiales:
            st.subheader("🔌 Control de Materiales e Inventario (Equipos y Acometidas)")
            st.caption("Reporte histórico completo de cambios de equipos terminales (ONT/ONU/CPE) y reemplazos de cable acometida (Drop).")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                meses_nombres = [
                    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
                ]
                mes_seleccionado = st.selectbox("📅 Seleccione el Mes:", meses_nombres, index=get_honduras_time().month - 1)
                numero_mes = meses_nombres.index(mes_seleccionado) + 1
            with col_sel2:
                anio_seleccionado = st.selectbox("📅 Seleccione el Año:", [2025, 2026, 2027], index=1)

            if 'df_materiales_master' not in st.session_state:
                with st.spinner("📥 Cargando base histórica completa para inventario..."):
                    try:
                        df_m_master = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                        if df_m_master is None or df_m_master.empty:
                            if conn is not None:
                                df_m_master = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                        
                        if df_m_master is not None and not df_m_master.empty:
                            df_m_master.columns = df_m_master.columns.str.upper().str.strip()
                            st.session_state['df_materiales_master'] = df_m_master
                        else:
                            st.session_state['df_materiales_master'] = df_base.copy()
                    except Exception as e:
                        st.session_state['df_materiales_master'] = df_base.copy()

            df_m = st.session_state.get('df_materiales_master', df_base).copy()

            df_m['FECHA_REPORTE'] = pd.to_datetime(df_m['HORA_LIQ'], dayfirst=True, errors='coerce')
            df_m['FECHA_REPORTE'] = df_m['FECHA_REPORTE'].fillna(pd.to_datetime(df_m['FECHA_APE'], dayfirst=True, errors='coerce'))
            df_m = df_m[df_m['FECHA_REPORTE'].notna()]
            
            df_m_filtrado = df_m[
                (df_m['FECHA_REPORTE'].dt.month == numero_mes) & 
                (df_m['FECHA_REPORTE'].dt.year == anio_seleccionado)
            ].copy()
            
            if not df_m_filtrado.empty:
                act_upper = df_m_filtrado['ACTIVIDAD'].astype(str).str.upper().str.strip()
                mask_actividades_sop = act_upper.str.contains("SOP", na=False) | (act_upper == "CEQUI")
                df_m_filtrado = df_m_filtrado[mask_actividades_sop].copy()
            
            if not df_m_filtrado.empty:
                mask_validos = ~df_m_filtrado['TECNICO'].astype(str).str.upper().str.contains("LILIAN|WILFREDO", na=False)
                df_m_filtrado = df_m_filtrado[mask_validos].copy()
            
            if not df_m_filtrado.empty:
                df_m_filtrado['CLASIF_MATERIAL'] = df_m_filtrado.apply(clasificar_materiales, axis=1)
                
                df_equipos = df_m_filtrado[df_m_filtrado['CLASIF_MATERIAL'] == 'CAMBIO_EQUIPO']
                df_acometidas = df_m_filtrado[df_m_filtrado['CLASIF_MATERIAL'] == 'CAMBIO_ACOMETIDA']
                
                total_equipos = len(df_equipos)
                total_acometidas = len(df_acometidas)
                
                col_k1, col_k2 = st.columns(2)
                with col_k1:
                    st.markdown(f"""
                    <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #3B82F6; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #2D2F39;">
                        <div style="color: #94A3B8; font-size: 0.85rem; font-weight: bold; text-transform: uppercase;">🔌 CAMBIOS DE EQUIPO (ONT/ONU/CPE)</div>
                        <div style="color: #3B82F6; font-size: 2.5rem; font-weight: bold; margin-top: 5px;">{total_equipos}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col_k2:
                    st.markdown(f"""
                    <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #F59E0B; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #2D2F39;">
                        <div style="color: #94A3B8; font-size: 0.85rem; font-weight: bold; text-transform: uppercase;">🎗️ REEMPLAZOS DE ACOMETIDA (DROP)</div>
                        <div style="color: #F59E0B; font-size: 2.5rem; font-weight: bold; margin-top: 5px;">{total_acometidas}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("### 📊 Desglose de Cambios por Técnico")
                
                if total_equipos > 0:
                    eq_tech = df_equipos.groupby('TECNICO').size().reset_index(name='Equipos Cambiados')
                else:
                    eq_tech = pd.DataFrame(columns=['TECNICO', 'Equipos Cambiados'])
                    
                if total_acometidas > 0:
                    ac_tech = df_acometidas.groupby('TECNICO').size().reset_index(name='Acometidas Cambiadas')
                else:
                    ac_tech = pd.DataFrame(columns=['TECNICO', 'Acometidas Cambiadas'])
                    
                tech_summary = pd.merge(eq_tech, ac_tech, on='TECNICO', how='outer').fillna(0)
                tech_summary['Equipos Cambiados'] = tech_summary['Equipos Cambiados'].astype(int)
                tech_summary['Acometidas Cambiadas'] = tech_summary['Acometidas Cambiadas'].astype(int)
                tech_summary['Total Intervenciones'] = tech_summary['Equipos Cambiados'] + tech_summary['Acometidas Cambiadas']
                
                tech_summary = tech_summary[tech_summary['Total Intervenciones'] > 0]
                tech_summary = tech_summary.sort_values(by='Total Intervenciones', ascending=False)
                
                st.dataframe(
                    tech_summary, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TECNICO": st.column_config.TextColumn("👨‍🔧 Técnico"),
                        "Equipos Cambiados": st.column_config.NumberColumn("🔌 Equipos Cambiados", format="%d"),
                        "Acometidas Cambiadas": st.column_config.NumberColumn("🎗️ Acometidas Cambiadas", format="%d"),
                        "Total Intervenciones": st.column_config.NumberColumn("📦 Total General", format="%d")
                    }
                )
                
                st.markdown("### 📥 Descargar Reporte en Formato PDF")
                
                if st.button(f"📄 GENERAR REPORTE PDF ({mes_seleccionado} {anio_seleccionado})", use_container_width=True, type="primary"):
                    with st.spinner("Dibujando celdas y empaquetando reporte..."):
                        st.session_state['pdf_materiales_cargado'] = generar_pdf_materiales_mensual(
                            df_equipos, 
                            df_acometidas, 
                            tech_summary, 
                            mes_seleccionado, 
                            anio_seleccionado
                        )
                
                if 'pdf_materiales_cargado' in st.session_state and st.session_state['pdf_materiales_cargado'] is not None:
                    st.download_button(
                        label=f"📥 Descargar Reporte en PDF",
                        data=st.session_state['pdf_materiales_cargado'],
                        file_name=f"Reporte_Materiales_{mes_seleccionado}_{anio_seleccionado}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                
                with st.expander("🔍 Ver Vista Previa del Detalle de Transacciones"):
                    df_view_table = pd.concat([df_equipos, df_acometidas]).sort_values(by='FECHA_REPORTE')
                    if not df_view_table.empty:
                        df_view_table['FECHA_REPORTE'] = df_view_table['FECHA_REPORTE'].dt.strftime('%d/%m/%Y %H:%M')
                        df_view_table = df_view_table[['NUM', 'CLIENTE', 'TECNICO', 'COMENTARIO', 'FECHA_REPORTE']]
                        df_view_table.columns = ['Orden', 'Cliente', 'Técnico', 'Comentario de Cierre', 'Fecha']
                    st.dataframe(df_view_table, use_container_width=True, hide_index=True)
            else:
                st.warning(f"⚠️ No se encontraron transacciones u órdenes procesadas para el mes de {mes_seleccionado} {anio_seleccionado}.")

    # ==============================================================================
    # 6. MONITOR OPERATIVO EN VIVO 
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

        if os.path.exists("Logotipo monitor.png"):
            st.image("Logotipo monitor.png", width=400) 
        else:
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

        if es_movil:
            st.markdown(f"""
            <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; margin-top: 10px;">
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #3B82F6; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">ASIGNADAS</div>
                    <div style="color: #FFFFFF; font-size: 1.8rem; font-weight: bold;">{vivas_count_asignadas}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #10B981; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">CERRADAS</div>
                    <div style="color: #10B981; font-size: 1.8rem; font-weight: bold;">{cerradas_hoy}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #F59E0B; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">EN RUTA</div>
                    <div style="color: #FFFFFF; font-size: 1.8rem; font-weight: bold;">{tecs_activos}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #EF4444; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">CAÍDAS</div>
                    <div style="color: #EF4444; font-size: 1.8rem; font-weight: bold;">{offline_criticos_asignadas}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
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

        if st.session_state.get('config_ver_tablero', True):
            with st.expander("📊 TABLERO DE CARGA ACTUAL (TODAS LAS PENDIENTES)", expanded=not es_movil):
                if es_movil:
                    st.caption("📅 Resumen de Retraso")
                    res_retraso_v = df_todas_pendientes_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 a 6 Dias","= 1 a 3 Dias","= 0 Dia"], fill_value=0).reset_index()
                    res_retraso_v.columns = ['Dias', 'Cant']
                    sum_total_asignadas_v = res_retraso_v['Cant'].sum()
                    res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_asignadas_v*100):.0f}%" if sum_total_asignadas_v > 0 else "0%")
                    def style_dias_apply(row):
                        v = row['Dias']
                        bg_color, font_color = '', 'white'
                        if v == ">= 7 Dia": bg_color = '#d32f2f'
                        elif v == "= 4 a 6 Dias": bg_color = '#f57c00'
                        elif v == "= 1 a 3 Dias": bg_color, font_color = '#fbc02d', 'black'
                        elif v == "= 0 Dia": bg_color = '#388e3c'
                        return [f'background-color: {bg_color}; color: {font_color}; font-weight: bold' if i == 0 else '' for i in range(len(row))]
                    st.dataframe(res_retraso_v.style.apply(style_dias_apply, axis=1), hide_index=True, use_container_width=True)
                    st.write(f"**Total General Retraso: {sum_total_asignadas_v}**")
               
                else:
                    col_t1, col_t2 = st.columns([1, 2])
                    with col_t1:
                        st.caption("📅 Resumen de Retraso")
                        res_retraso_v = df_todas_pendientes_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 a 6 Dias","= 1 a 3 Dias","= 0 Dia"], fill_value=0).reset_index()
                        res_retraso_v.columns = ['Dias', 'Cant']
                        sum_total_asignadas_v = res_retraso_v['Cant'].sum()
                        res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_asignadas_v*100):.0f}%" if sum_total_asignadas_v > 0 else "0%")
                        def style_dias_apply(row):
                            v = row['Dias']
                            bg_color, font_color = '', 'white'
                            if v == ">= 7 Dia": bg_color = '#d32f2f'
                            elif v == "= 4 a 6 Dias": bg_color = '#f57c00'
                            elif v == "= 1 a 3 Dias": bg_color, font_color = '#fbc02d', 'black'
                            elif v == "= 0 Dia": bg_color = '#388e3c'
                            return [f'background-color: {bg_color}; color: {font_color}; font-weight: bold' if i == 0 else '' for i in range(len(row))]
                        st.dataframe(res_retraso_v.style.apply(style_dias_apply, axis=1), hide_index=True, use_container_width=True)
                        st.write(f"**Total General Retraso: {sum_total_asignadas_v}**")

                g_tab_list = []
                sub_tab_list = []
                for idx, r in df_todas_pendientes_monitor.iterrows():
                    act = str(r.get('ACTIVIDAD', '')).upper()
                    com = str(r.get('COMENTARIO', '')).upper()
                    txt = act + " " + com
                    is_off = r.get('ES_OFFLINE', False)
                    if not re.search("SOP|FALLA|MANT|INS|ADIC|CAMBIO|MIGRACI|NUEVA|RECUP", txt):
                        g_tab_list.append("OTROS"); sub_tab_list.append(act if act != "" else "N/A")
                    elif re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act):
                        g_tab_list.append("INS")
                        if re.search("ADIC", txt): sub_tab_list.append("Adición")
                        elif re.search("CAMBIO|MIGRACI", txt): sub_tab_list.append("Cambio / Migración")
                        elif re.search("RECUP", txt): sub_tab_list.append("Recuperado")
                        else: sub_tab_list.append("Nueva")
                    else:
                        g_tab_list.append("SOP")
                        if is_off: sub_tab_list.append("ONT/ONU Offline")
                        elif re.search("NIVEL|DB", com): sub_tab_list.append("Niveles alterados")
                        elif re.search("FIBRA|FTTH", act): sub_tab_list.append("FTTH / FIBRA")
                        elif re.search("NAV|INTERNET", act): sub_tab_list.append("Navegación / Internet")
                        elif re.search("TV|CABLE", act): sub_tab_list.append("Sin señal de TV")
                        else: sub_tab_list.append("SOP General")
                        
                df_tablero = df_todas_pendientes_monitor.copy()
                df_tablero['G_TAB'] = g_tab_list
                df_tablero['SUB_TAB'] = sub_tab_list
                
                if es_movil:
                    st.caption("🛠️ SOP / Mantenimiento")
                    df_sop = df_tablero[df_tablero['G_TAB'] == 'SOP']
                    res_sop = df_sop['SUB_TAB'].value_counts().reset_index()
                    res_sop.columns = ['SOP', 'Cant']
                    st.dataframe(res_sop, hide_index=True, use_container_width=True)
                    
                    st.caption("📦 Compartido / Tipo")
                    df_ins = df_tablero[df_tablero['G_TAB'] == 'INS']
                    res_ins = df_ins['SUB_TAB'].value_counts().reset_index()
                    res_ins.columns = ['Instalaciones', 'Cant']
                    cats_ins = ['Nueva', 'Adición', 'Cambio / Migración', 'Recuperado']
                    for c in cats_ins:
                        if c not in res_ins['Instalaciones'].values: 
                            res_ins = pd.concat([res_ins, pd.DataFrame([{'Instalaciones': c, 'Cant': 0}])], ignore_index=True)
                    st.dataframe(res_ins, hide_index=True, use_container_width=True)
                else:
                    with col_t2:
                        st.caption("🛠️ SOP / Mantenimiento")
                        df_sop = df_tablero[df_tablero['G_TAB'] == 'SOP']
                        res_sop = df_sop['SUB_TAB'].value_counts().reset_index()
                        res_sop.columns = ['SOP', 'Cant']
                        st.dataframe(res_sop, hide_index=True, use_container_width=True)
                        st.write(f"**Total General SOP: {df_sop.shape[0]}**")
                        st.metric("Exceden 2 Horas ⚠️", int((df_sop['ALERTA_TIEMPO'] == True).sum()))

                    with col_t1:
                        st.markdown("<br><br>", unsafe_allow_html=True)
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

                    with col_t2:
                        st.caption("⚙️ Otros")
                        df_otros = df_tablero[df_tablero['G_TAB'] == 'OTROS']
                        res_otr = df_otros['SUB_TAB'].value_counts().reset_index()
                        res_otr.columns = ['Otros', 'Cant']
                        st.dataframe(res_otr.head(8), hide_index=True, use_container_width=True)
                        st.write(f"**Total Otros: {df_otros.shape[0]}**")

        if st.session_state.get('config_ver_consolidado', True):
            with st.expander("📊 CONSOLIDADO POR SEGMENTO (MORA VS AL DÍA)", expanded=True):
                st.markdown("<h4 style='text-align: center; color: #1F2937;'>Avance Operativo Detallado</h4><br>", unsafe_allow_html=True)
                
                df_cerradas_hoy_monitor['FECHA_APE_DT'] = pd.to_datetime(df_cerradas_hoy_monitor['FECHA_APE'], errors='coerce')
                
                def calcular_metricas(segmento):
                    if segmento == 'GLOBAL':
                        p = df_solo_asignadas_monitor
                        c = df_cerradas_hoy_monitor
                    else:
                        p = df_solo_asignadas_monitor[df_solo_asignadas_monitor['SEGMENTO'] == segmento]
                        c = df_cerradas_hoy_monitor[df_cerradas_hoy_monitor['SEGMENTO'] == segmento]

                    p_mora = len(p[p['DIAS_RETRASO'] > 0])
                    p_hoy = len(p[p['DIAS_RETRASO'] == 0])
                    c_mora = len(c[c['FECHA_APE_DT'].dt.date < hoy_date_valor])
                    c_hoy = len(c[c['FECHA_APE_DT'].dt.date == hoy_date_valor])

                    tot_mora, tot_hoy = p_mora + c_mora, p_hoy + c_hoy
                    tot_global = tot_mora + tot_hoy
                    cerr_global = c_mora + c_hoy

                    pct_mora = (c_mora / tot_mora * 100) if tot_mora > 0 else 0
                    pct_hoy = (c_hoy / tot_hoy * 100) if tot_hoy > 0 else 0
                    pct_global = (cerr_global / tot_global * 100) if tot_global > 0 else 0

                    return {
                        'tot_g': tot_global, 'cerr_g': cerr_global, 'pct_g': pct_global,
                        'tot_m': tot_mora, 'cerr_m': c_mora, 'pct_m': pct_mora,
                        'tot_h': tot_hoy, 'cerr_h': c_hoy, 'pct_h': pct_hoy,
                        'df_p': p, 'df_c': c
                    }

                stats_resi = calcular_metricas('RESIDENCIAL')
                stats_plex = calcular_metricas('PLEX')
                stats_global = calcular_metricas('GLOBAL')

                def renderizar_metrica(col_ui, stats, titulo, color_hex, key_btn):
                    with col_ui:
                        fig = go.Figure(go.Pie(
                            values=[stats['pct_g'], max(0, 100 - stats['pct_g'])] if stats['tot_g'] > 0 else [0, 100],
                            labels=['Completado', 'Pendiente'], hole=0.8,
                            marker=dict(colors=[color_hex, '#2D2F39']),
                            textinfo='none', hoverinfo='none', direction='clockwise', sort=False
                        ))
                        
                        texto_central = f"{stats['pct_g']:.0f}%" if stats['tot_g'] > 0 else "N/A"
                        subtexto = f"Total: {stats['cerr_g']} de {stats['tot_g']}" if stats['tot_g'] > 0 else "Sin asignaciones"
                        
                        fig.update_layout(
                            showlegend=False, height=150, margin=dict(l=5, r=5, t=30, b=5),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#1F2937', 'size': 14, 'weight': 'bold'}},
                            annotations=[
                                dict(text=texto_central, x=0.5, y=0.42, font_size=26, font_color=color_hex, showarrow=False, font_weight="bold"),
                                dict(text=subtexto, x=0.5, y=0.68, font_size=11, font_color="#6B7280", showarrow=False)
                            ]
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"pie_{key_btn}")

                        html_badges = f"""
                        <div style="display:flex; justify-content:center; gap:8px; font-size:11px; margin-top:-15px; margin-bottom:10px;">
                            <div style="background-color:#fee2e2; color:#b91c1c; padding:3px 8px; border-radius:10px; font-weight:bold; border:1px solid #fca5a5;">
                                🔴 Mora: {stats['cerr_m']}/{stats['tot_m']} ({stats['pct_m']:.0f}%)
                            </div>
                            <div style="background-color:#dbeafe; color:#1d4ed8; padding:3px 8px; border-radius:10px; font-weight:bold; border:1px solid #93c5fd;">
                                🔵 Hoy: {stats['cerr_h']}/{stats['tot_h']} ({stats['pct_h']:.0f}%)
                            </div>
                        </div>
                        """
                        st.markdown(html_badges, unsafe_allow_html=True)

                        if st.button("🔍 Ver Desglose", use_container_width=True, key=f"btn_{key_btn}"):
                            mostrar_detalle_avance(titulo.upper(), stats['df_p'], stats['df_c'])

                if es_movil:
                    renderizar_metrica(st.container(), stats_resi, "🏠 Residencial", "#EF4444", "resi_m")
                    renderizar_metrica(st.container(), stats_plex, "🏢 PLEX", "#F59E0B", "plex_m")
                    renderizar_metrica(st.container(), stats_global, "🌍 Global", "#10B981", "glob_m")
                else:
                    col1, col2, col3 = st.columns(3)
                    renderizar_metrica(col1, stats_resi, "🏠 Residencial", "#EF4444", "resi")
                    renderizar_metrica(col2, stats_plex, "🏢 PLEX", "#F59E0B", "plex")
                    renderizar_metrica(col3, stats_global, "🌍 Global", "#10B981", "glob")

                st.markdown("---")
        
        if st.session_state.get('config_mostrar_panel', True):
            if not es_movil:
                if st.session_state.get('config_ver_gantt', True):
                    with st.expander("⏳ LÍNEA DE TIEMPO OPERATIVA (GANTT)", expanded=False):
                        
                        mask_cerradas_gantt = (df_monitor_filtrado['ESTADO'].astype(str).str.upper() == 'CERRADA') & (df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor)
                        mask_abiertas_gantt = (df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)) & (df_monitor_filtrado['HORA_INI'].dt.date == hoy_date_valor)
                        
                        df_para_gantt_final = df_monitor_filtrado[mask_cerradas_gantt | mask_abiertas_gantt].copy()
                        
                        mask_sin_inicio = df_para_gantt_final['HORA_INI'].isna() & df_para_gantt_final['HORA_LIQ'].notnull()
                        df_para_gantt_final.loc[mask_sin_inicio, 'HORA_INI'] = df_para_gantt_final.loc[mask_sin_inicio, 'HORA_LIQ'] - pd.Timedelta(minutes=30)
                        
                        df_para_gantt_final = df_para_gantt_final[df_para_gantt_final['HORA_INI'].notnull()].copy()
                        
                        if not df_para_gantt_final.empty:
                            ahora_hx = get_honduras_time()
                            
                            df_para_gantt_final['GANTT_START'] = df_para_gantt_final['HORA_INI']
                            df_para_gantt_final['GANTT_END'] = df_para_gantt_final['HORA_LIQ'].fillna(ahora_hx)
                            
                            mask_cero_min = df_para_gantt_final['GANTT_START'] == df_para_gantt_final['GANTT_END']
                            df_para_gantt_final.loc[mask_cero_min, 'GANTT_START'] = df_para_gantt_final.loc[mask_cero_min, 'GANTT_END'] - pd.Timedelta(minutes=30)
                            
                            mask_inv_m = df_para_gantt_final['GANTT_END'] < df_para_gantt_final['GANTT_START']
                            df_para_gantt_final.loc[mask_inv_m, 'GANTT_END'] = df_para_gantt_final.loc[mask_inv_m, 'GANTT_START'] + pd.Timedelta(minutes=30)
                            
                            df_para_gantt_final['Inicio'] = df_para_gantt_final['HORA_INI'].dt.strftime('%H:%M')
                            df_para_gantt_final['Cierre'] = df_para_gantt_final['HORA_LIQ'].apply(
                                lambda x: x.strftime('%H:%M') if pd.notnull(x) else "En curso (Abierta)"
                            )
                            
                            df_para_gantt_final['TECNICO'] = df_para_gantt_final['TECNICO'].astype(str).str.strip().str.upper()
                            df_para_gantt_final = df_para_gantt_final.sort_values(by=['TECNICO', 'GANTT_START'])

                            actividades_permitidas = [
                                'CEQUI', 'INSEQUIPO', 'INSFIBRA', 'INSFIBRACORP', 'INSHFC', 
                                'INS-WA', 'PEXTERNO', 'PLEXISCA', 'SOP', 
                                'SOPCORP', 'SOPFIBRA', 'SOPFIBRACORP', 'SOPRECONCORP', 
                                'SOPRECONHFC', 'SPLITTEROPT', 'TRASLADOEXTFIBRA', 
                                'TRASLADOEXTFIBRACORP', 'TRASLADOINTERNOFIBRA', 
                                'TRASLADOINTFIBRACORP', 'TVADICIONAL'
                            ]
                            
                            df_para_gantt_final = df_para_gantt_final[
                                df_para_gantt_final['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_permitidas)
                            ]
                            
                            df_para_gantt_final['INFO_HOVER'] = (
                                "ACTIVIDAD=" + df_para_gantt_final['ACTIVIDAD'].astype(str) + "<br>" +
                                "NUM=" + df_para_gantt_final['NUM'].astype(str) + "<br>" +
                                "COLONIA=" + df_para_gantt_final['COLONIA'].astype(str) + "<br>" +
                                "ESTADO=" + df_para_gantt_final['ESTADO'].astype(str) + "<br>" +
                                "Inicio=" + df_para_gantt_final['Inicio'].astype(str) + "<br>" +
                                "Cierre=" + df_para_gantt_final['Cierre'].astype(str) + "<br>" +
                                "Tiempo Total=" + df_para_gantt_final['TIEMPO_REAL'].astype(str)
                            )

                            st.markdown("<h5 style='text-align: left; color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px;'>👨‍🔧 Productividad Diaria (Actividades Aperturadas Hoy)</h5>", unsafe_allow_html=True)
                            
                            colores_solidos = {
                                "SOPFIBRA": "#d32f2f",         
                                "SOP": "#d32f2f",                
                                "INSFIBRA": "#1976d2",         
                                "INSFIBRACORP": "#0d47a1",     
                                "PEXTERNO": "#f57c00",         
                                "PLEXISCA": "#e65100",         
                                "TRASLADOEXTFIBRA": "#8e24aa",  
                                "SOPRECONHFC": "#c2185b",       
                                "TVADICIONAL": "#00897b",
                                "CEQUI": "#fbc02d",          
                                "CAMBIO": "#fbc02d",
                                "MANTENIMIENTO": "#512da8",
                                "REVISION": "#0288d1"
                            }

                            fig_gantt = px.timeline(
                                df_para_gantt_final, 
                                x_start="GANTT_START", 
                                x_end="GANTT_END", 
                                y="TECNICO", 
                                color="ACTIVIDAD", 
                                text="ACTIVIDAD",  
                                custom_data=["INFO_HOVER"], 
                                color_discrete_map=colores_solidos,
                                height=max(400, len(df_para_gantt_final['TECNICO'].unique()) * 45)
                            )
                            
                            fig_gantt.update_yaxes(autorange="reversed", title_text="", type="category")
                            hora_inicio_pantalla = datetime.combine(hoy_date_valor, dt_time(6, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            hora_fin_pantalla = datetime.combine(hoy_date_valor, dt_time(22, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            
                            fig_gantt.update_xaxes(range=[hora_inicio_pantalla, hora_fin_pantalla], tickformat="%H:%M", title_text="Cronograma de Actividades")
                            fig_gantt.update_traces(textposition='inside', insidetextanchor='middle', marker_line_color='white', marker_line_width=1.5, opacity=0.9, hovertemplate="%{customdata[0]}<extra></extra>")
                            fig_gantt.update_layout(showlegend=True, legend_title_text='Identificador de Actividades', legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02), margin=dict(t=10, b=20, l=0, r=150), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.02)")
                            
                            st.plotly_chart(fig_gantt, use_container_width=True)

            st.markdown("---")
            if st.session_state.get('config_ver_panel', True):
                with st.expander("🎛️ PANEL DE CONTROL Y ANÁLISIS DETALLADO", expanded=True):
                    if 'st_btn_v_active' not in st.session_state or st.session_state.st_btn_v_active == "CONSOL": 
                        st.session_state.st_btn_v_active = "PENDIENTE"
                        
                    if es_movil:
                        st.write("Filtros:")
                        if st.button("⏳ ASIGNADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary"): 
                            st.session_state.st_btn_v_active = "PENDIENTE"; st.rerun()
                        col_m1, col_m2 = st.columns(2)
                        if col_m1.button("✅ CERRADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "C_HOY" else "secondary"): 
                            st.session_state.st_btn_v_active = "C_HOY"; st.rerun()
                        if col_m2.button("❌ ANULADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "A_HOY" else "secondary"): 
                            st.session_state.st_btn_v_active = "A_HOY"; st.rerun()
                    else:
                        col_bt1_v, col_bt2_v, col_bt3_v = st.columns(3)
                        if col_bt1_v.button("⏳ ASIGNADAS ACTIVAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary"): 
                            st.session_state.st_btn_v_active = "PENDIENTE"; st.rerun()
                        if col_bt2_v.button("✅ CERRADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "C_HOY" else "secondary"): 
                            st.session_state.st_btn_v_active = "C_HOY"; st.rerun()
                        if col_bt3_v.button("❌ ANULADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "A_HOY" else "secondary"): 
                            st.session_state.st_btn_v_active = "A_HOY"; st.rerun()

                status_final_btn = st.session_state.st_btn_v_active

                if check_ordenes_totales:
                    df_v_tabla_monitor = df_todas_pendientes_monitor 
                else:
                    if status_final_btn == "PENDIENTE": 
                        if check_criticos_diamante:
                            df_v_tabla_monitor = df_todas_pendientes_monitor[df_todas_pendientes_monitor['ES_OFFLINE'] == True]
                        else:
                            df_v_tabla_monitor = df_solo_asignadas_monitor
                    elif status_final_btn == "C_HOY": 
                        df_v_tabla_monitor = df_cerradas_hoy_monitor
                    else: 
                        df_v_tabla_monitor = df_monitor_filtrado[(df_monitor_filtrado['ESTADO'].astype(str).str.contains('ANULADA', na=False, case=False)) & (df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor)]
                        

# Este bloque completo está a 12 espacios del borde izquierdo
            t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL OPERATIVO", "📊 PRODUCTIVIDAD", "📈 ANALÍTICA"])
            
            with t_panel_v:
                if not df_v_tabla_monitor.empty:
                    if es_movil:
                        st.markdown("<br>", unsafe_allow_html=True)
                        for idx, row in df_v_tabla_monitor.iterrows():
                            color_borde = "#EF4444" if row.get('ES_OFFLINE') else ("#F59E0B" if row.get('ALERTA_TIEMPO') else "#3B82F6")
                            estado_txt = str(row.get('ESTADO', 'N/D')).upper()
                            bg_estado = "#10B981" if estado_txt == "CERRADA" else ("#d32f2f" if estado_txt == "ANULADA" else "#2D3748")
                            
                            st.markdown(f"""
                            <div style="background-color: #1A1D24; padding: 15px; border-radius: 12px; margin-bottom: 12px; border-left: 5px solid {color_borde}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <span style="color: white; font-weight: bold; font-size: 16px;">ORD-{row.get('NUM', 'N/D')}</span>
                                    <span style="background: {bg_estado}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">{estado_txt}</span>
                                </div>
                                <div style="color: #94A3B8; font-size: 13px; margin-bottom: 8px; line-height: 1.4;">
                                    👤 <b>{str(row.get('NOMBRE', 'N/D'))[:25]}</b> <br>
                                    📍 {str(row.get('COLONIA', 'N/D'))[:30]}
                                </div>
                                <div style="color: #E2E8F0; font-size: 12px; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                                    🛠️ {str(row.get('ACTIVIDAD', ''))} <br>
                                    👨‍🔧 {str(row.get('TECNICO', ''))[:20]}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            if st.button(f"👁️ Ver Detalle de Orden {row.get('NUM')}", key=f"btn_mobile_{row.get('NUM')}_{idx}", use_container_width=True):
                                mostrar_comentario_cierre(row)
                            st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px; border-color: #2D2F39;'>", unsafe_allow_html=True)
                    else:
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
                st.subheader("📈 Órdenes Cerradas por Hora (Hoy)")
            
                df_graficas = df_base.copy()
                df_graficas['HORA_LIQ_LOCAL'] = df_graficas['HORA_LIQ'] - pd.Timedelta(hours=6)
            
                df_productividad_v = df_graficas[df_graficas['HORA_LIQ_LOCAL'].dt.date == hoy_date_valor].copy()
            
                if not df_productividad_v.empty:
                    df_productividad_v['Hr_C'] = df_productividad_v['HORA_LIQ_LOCAL'].dt.hour
                    conteo_horario_v = df_productividad_v.groupby('Hr_C').size().reset_index(name='Ord')
                    
                    conteo_horario_v['Hora_Format'] = conteo_horario_v['Hr_C'].apply(lambda x: f"{int(x):02d}:00")
                    
                    fig_barras_v = px.bar(
                        conteo_horario_v, x='Hora_Format', y='Ord', 
                        labels={'Hora_Format':'Hora del Día (Honduras)','Ord':'Cant. Cerradas'}, 
                        template="plotly_dark", height=300
                    )
                    st.plotly_chart(fig_barras_v, use_container_width=True)
                else:
                    st.info("Sin datos de cierres para generar gráfico horario.")

            with t_analitica_v:
                st.markdown("### 📈 Análisis de Rendimiento Operativo")
                
                # === PROTECCIÓN: Si no hay datos, muestra un mensaje amigable en lugar de fallar ===
                if df_v_tabla_monitor.empty:
                    st.info("ℹ️ No hay datos disponibles para mostrar el análisis gráfico en este momento.")
                else:
                    plt.style.use('dark_background')
                    
                    # Generamos los conteos de forma segura
                    segmentos_conteo = df_v_tabla_monitor['SEGMENTO'].value_counts()
                    motivos_conteo = df_v_tabla_monitor['MOTIVO'].value_counts() if 'MOTIVO' in df_v_tabla_monitor.columns else pd.Series()
                    
                    if es_movil:
                        if not segmentos_conteo.empty:
                            fig, ax = plt.subplots(figsize=(6, 4))
                            segmentos_conteo.plot(kind='bar', ax=ax, color=['#3B82F6', '#10B981'])
                            ax.set_title("Órdenes por Segmento")
                            st.pyplot(fig)
                        else:
                            st.caption("Sin datos de segmentos.")
                    else:
                        col_an1, col_an2 = st.columns(2)
                        with col_an1:
                            if not segmentos_conteo.empty:
                                fig, ax = plt.subplots(figsize=(6, 4))
                                segmentos_conteo.plot(kind='bar', ax=ax, color=['#3B82F6', '#10B981'])
                                ax.set_title("Órdenes por Segmento")
                                st.pyplot(fig)
                            else:
                                st.caption("Sin datos de segmentos para graficar.")
                                
                        with col_an2:
                            if not motivos_conteo.empty:
                                fig, ax = plt.subplots(figsize=(6, 4))
                                motivos_conteo.plot(kind='pie', autopct='%1.1f%%', ax=ax, cmap='viridis')
                                ax.set_ylabel('')
                                ax.set_title("Motivo / Diagnóstico")
                                st.pyplot(fig)
                            else:
                                st.caption("Sin datos de diagnósticos para graficar.")

# Este bloque final de ejecución queda al ras del margen izquierdo (0 espacios)
if __name__ == '__main__':
    if verificar_autenticacion():
        main()
    else:
        mostrar_pantalla_login()
