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
import unicodedata

# ==============================================================================
# CONFIGURACIÓN DE RUTAS DEL SISTEMA (VITAL)
# ==============================================================================
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
import expediente
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
    import ccalidad
except ImportError:
    st.error("⚠️ Falta el archivo 'ccalidad.py'. Asegúrate de crearlo en la misma carpeta para ver el módulo de Control de Calidad.")


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
        generar_pdf_materiales_mensual,
        normalizar_nombre_cruce,
        guardar_almuerzo,
        cargar_almuerzos,
        cargar_catalogo_tecnicos
    )
except ImportError as e:
    st.error(f"⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'. Detalle: {e}")
    
# ==============================================================================
# FUNCIONES AUXILIARES DE SOPORTE GLOBAL
# ==============================================================================
def normalizar_nombre_cruce(texto):
    """
    Normaliza texto eliminando acentos, caracteres invisibles (como el Zero-Width Non-Joiner)
    y espacios extra para asegurar un cruce de nombres óptimo.
    """
    if pd.isnull(texto): 
        return ""
    t = str(texto).upper().strip()
    t = t.replace('\u200c', '').replace('\u200b', '')
    t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    t = ' '.join(t.split())
    
    alias_map = {
        "JOSUE MIGUEL SAUCEDA": "JOSE MIGUEL SAUCEDA",
        "JERMY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "JEREMY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "JERMY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JEREMY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JERNY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JERNY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "ELIAS MIZAEL SABILLON": "ELIAS MISAEL ALONZO SABILLON",
        "ELIAS MISAEL SABILLON": "ELIAS MISAEL ALONZO SABILLON",
        "ELIAS MISAEL ALONZO": "ELIAS MISAEL ALONZO SABILLON",
        "DANIEL EZEQUIEL PONCE GUZMAN": "DANIEL EZEQUIEL GUZMAN PONCE",
        "NELAON RAMON FERRUFINO LEON": "NELSON RAMON FERRUFINO LEON"
    }
    
    if t in alias_map:
        return alias_map[t]
    return t

def mascara_tecnico_asignado(serie_tecnicos):
    """
    Retorna una serie booleana con True para técnicos asignados válidos
    y False para técnicos nulos, vacíos o no asignados.
    """
    s = serie_tecnicos.fillna('').astype(str).str.strip().str.upper()
    valores_invalidos = {'', 'NONE', 'NAN', 'N/D', 'NULL', '0'}
    return ~s.isin(valores_invalidos)

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
# SINCROFONIZACIÓN DE DATOS CON LA NUBE
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
                empresa_upper_sync = df_nube['EMPRESA'].astype(str).str.strip().str.upper()
                mask_otra_empresa_sync = (empresa_upper_sync != '') & (empresa_upper_sync != 'NAN') & (empresa_upper_sync != 'NONE') & (~empresa_upper_sync.str.contains('ISCA', na=False))
                df_nube = df_nube[~mask_otra_empresa_sync].copy()

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
                    df_nube['NUM'] = df_nube['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    df_nube['SORT_DATE'] = pd.to_datetime(df_nube['HORA_LIQ'], errors='coerce')
                    df_nube['SORT_DATE'] = df_nube['SORT_DATE'].fillna(pd.to_datetime(df_nube['FECHA_APE'], errors='coerce'))
                    df_nube['SORT_DATE'] = df_nube['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
                    
                    PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                    df_nube['ES_VIVA'] = df_nube['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
                    df_nube = df_nube.sort_values(by=['ES_VIVA', 'SORT_DATE'], ascending=[False, True])
                    
                    df_validos = df_nube[df_nube['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                    df_invalidos = df_nube[df_nube['NUM'] == 'N/D']
                    df_nube = pd.concat([df_validos, df_invalidos]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')
                            
                if 'DIAS_RETRASO' in df_nube.columns: df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
                if 'ESTADO' in df_nube.columns: df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                ahora_momento_ts = pd.Timestamp(get_honduras_time())
                if df_nube['HORA_LIQ'].dt.tz is None:
                    ahora_naive = ahora_momento_ts.tz_localize(None)
                else:
                    ahora_naive = ahora_momento_ts
                fecha_limite_7d = ahora_naive - timedelta(days=7) 
                
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
    es_admin_o_supervisor = str(rol_usuario).strip().lower() in ['admin', 'jefe']
    
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
                nav_menu_diamante = st.selectbox("Seleccione un módulo extra:", ["🏅 Control Calidad", "📅 Reprog / No Inst", "⚙️ Configuración", "📁 Expedientes"])    
        else:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor", "Calidad"],
                icons=["lightning", "award"],
                default_index=0,
                orientation="horizontal",
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#94A3B8", "font-size": "20px"}, 
                    "nav-link": {"font-size": "11px", "text-align": "center", "margin":"0px", "--hover-color": "#2D2F39", "padding": "5px"},
                    "nav-link-selected": {"background-color": "transparent", "color": "#3B82F6", "font-weight": "bold"},
                }
            )
            if selected_nav == "Monitor": 
                nav_menu_diamante = "⚡ Monitor en Vivo"
            else: 
                nav_menu_diamante = "🏅 Control Calidad"
            
        st.markdown('</div>', unsafe_allow_html=True)
        if nav_menu_diamante != "⚡ Monitor en Vivo": st.divider()
    else:
        with sidebar_top:
            if rol_usuario in ['admin', 'jefe']: 
                nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "🏅 Control Calidad", "📅 Reprog / No Inst", "🚙 Auditoría Vehículos", "⚙️ Configuración", "📁 Expedientes"])
            else:
                st.markdown("### 🖥️ Menú de Control")
                nav_menu_diamante = st.radio("SELECCIONE EL MÓDULO:", ["⚡ Monitor en Vivo", "🏅 Control Calidad"])    

    with sidebar_top:
        mostrar_boton_logout()
        st.divider()

    with sidebar_bottom:
        btn_api_procesar = False
        file_act_ptr = None
        file_disp_ptr = None

        if not es_movil: st.markdown("<br><br>", unsafe_allow_html=True)
        st.divider()

        if es_admin_o_supervisor:
            st.markdown("### 🍽️ Registrar Almuerzo")
            with st.expander("Ingresar hora de almuerzo de un técnico", expanded=False):
                lista_tecs_almuerzo = []
                df_base_for_tecs = st.session_state.get('df_base')
                
                if df_base_for_tecs is not None and not df_base_for_tecs.empty and 'TECNICO' in df_base_for_tecs.columns:
                    lista_tecs_almuerzo = sorted(df_base_for_tecs['TECNICO'].dropna().unique().tolist())
                
                if not lista_tecs_almuerzo:
                    try:
                        df_cat_tecs = cargar_catalogo_tecnicos()
                        if df_cat_tecs is not None and not df_cat_tecs.empty:
                            lista_tecs_almuerzo = sorted(df_cat_tecs['Nombre'].dropna().unique().tolist())
                    except Exception:
                        pass
                
                if not lista_tecs_almuerzo and os.path.exists("gps.txt"):
                    try:
                        with open("gps.txt", "r", encoding="utf-8") as f:
                            for line in f:
                                parts = line.strip().split(",")
                                if len(parts) >= 3:
                                    lista_tecs_almuerzo.append(parts[2].strip().rstrip("."))
                        lista_tecs_almuerzo = sorted(list(set(lista_tecs_almuerzo)))
                    except Exception:
                        pass

                if lista_tecs_almuerzo:
                    tec_almuerzo_sel = st.selectbox("Técnico", options=lista_tecs_almuerzo, key="sel_tec_almuerzo")
                else:
                    tec_almuerzo_sel = st.text_input("Técnico (nombre exacto)", key="input_tec_almuerzo")

                fecha_almuerzo_sel = st.date_input("Fecha", value=get_honduras_time().date(), key="fecha_almuerzo_sel")
                col_hi, col_hf = st.columns(2)
                with col_hi:
                    hora_ini_almuerzo_txt = st.text_input("Hora inicio (HH:MM)", value="12:00", key="hora_ini_almuerzo", max_chars=5)
                with col_hf:
                    hora_fin_almuerzo_txt = st.text_input("Hora fin (HH:MM)", value="13:00", key="hora_fin_almuerzo", max_chars=5)

                if st.button("💾 Guardar Almuerzo", use_container_width=True, key="btn_guardar_almuerzo"):
                    hora_ini_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_ini_almuerzo_txt.strip())
                    hora_fin_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_fin_almuerzo_txt.strip())
                    if not tec_almuerzo_sel:
                        st.warning("Selecciona o escribe un técnico.")
                    elif not hora_ini_valida or not hora_fin_valida:
                        st.warning("La hora debe tener formato HH:MM en 24 horas (ej. 12:00, 13:30).")
                    else:
                        ok_almuerzo = guardar_almuerzo(
                            conn,
                            tecnico=tec_almuerzo_sel,
                            fecha=fecha_almuerzo_sel.strftime('%Y-%m-%d'),
                            hora_inicio=hora_ini_almuerzo_txt.strip(),
                            hora_fin=hora_fin_almuerzo_txt.strip(),
                            registrado_por=st.session_state.get('usuario_actual', rol_usuario)
                        )
                        if ok_almuerzo:
                            st.success(f"✅ Almuerzo de {tec_almuerzo_sel} guardado para el {fecha_almuerzo_sel.strftime('%d/%m/%Y')}.")
                        else:
                            st.error("No se pudo guardar el almuerzo. Revisa la conexión con Sheets.")
        st.divider()

        st.markdown("### ☁️ Sincronización")
        if st.button("☁️ ACTUALIZAR DESDE LA NUBE", use_container_width=True, key="btn_nube_sidebar"):
            if conn is not None:
                sincronizar_datos_nube(conn)
            else:
                st.error("Conexión no disponible.")

        st.divider()
        st.markdown("### 📥 Carga de Archivos")
        
        if es_admin:
            st.markdown("#### ⚡ Actualización Inmediata")
            btn_api_procesar = st.button("🔄 FORZAR ACTUALIZACIÓN INMEDIATA", use_container_width=True, type="primary")
            
            st.divider()
            st.markdown("#### 📄 Actividades (rep_actividades)")
            st.caption("Solo necesitas subir las actividades. El catálogo FTTX se toma automáticamente de la nube (pestaña FTTX / GCS).")
            archivo_actividades = st.file_uploader("Sube rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_actividades_admin")
            if archivo_actividades: file_act_ptr = archivo_actividades
            btn_reprocesar = st.button("🔄 PROCESAR ACTIVIDADES", use_container_width=True)

            st.divider()
            st.markdown("#### 🚙 Catálogo FTTX")
            st.caption("Sube esto SOLO cuando necesites actualizar el catálogo de dispositivos en la nube. No requiere subir actividades a la vez.")
            archivo_fttx = st.file_uploader("Sube FttxActiveDevice", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_fttx_admin")
            btn_actualizar_fttx = st.button("🔄 ACTUALIZAR SOLO CATÁLOGO FTTX", use_container_width=True)

            if archivo_fttx:
                try:
                    with open("cache_fttx.tmp", "wb") as f: f.write(archivo_fttx.getvalue())
                except: pass

            if btn_actualizar_fttx:
                if archivo_fttx is None:
                    st.warning("Primero selecciona un archivo FttxActiveDevice para subir.")
                elif conn is None:
                    st.error("Conexión no disponible.")
                else:
                    with st.spinner("⏳ Subiendo catálogo FTTX a la nube..."):
                        try:
                            archivo_fttx.seek(0)
                            if archivo_fttx.name.lower().endswith('.csv'):
                                df_fttx_subir = pd.read_csv(archivo_fttx, sep=None, engine='python')
                            else:
                                df_fttx_subir = pd.read_excel(archivo_fttx, engine='openpyxl')

                            if df_fttx_subir is None or df_fttx_subir.empty:
                                st.error("El archivo se leyó pero está vacío.")
                            else:
                                # Sheets es la fuente confiable, se sobrescribe la pestaña FTTX completa.
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", data=df_fttx_subir)
                                st.success(f"✅ Catálogo FTTX actualizado en la nube ({len(df_fttx_subir)} registros).")

                                try:
                                    sobrescribir_archivo_gcs(df_fttx_subir, NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                                except Exception:
                                    pass
                        except Exception as e_fttx_up:
                            st.error(f"No se pudo procesar/subir el archivo FTTX: {e_fttx_up}")
        else:
            st.caption("Solo necesitas subir las actividades. FTTX se bajará de la nube.")
            archivo_unico = st.file_uploader("Sube únicamente el rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False)
            if archivo_unico: file_act_ptr = archivo_unico
            btn_reprocesar = st.button("🔄 PROCESAR ARCHIVO SUBIDO", use_container_width=True)
            btn_actualizar_fttx = False

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
            if conn is not None:
                sincronizar_datos_nube(conn)
            else:
                st.error("Conexión no disponible.")

        elif btn_reprocesar:
            if file_act_ptr is not None and file_disp_ptr is None:
                with st.spinner("⏳ Descargando base de Vehículos/Dispositivos..."):
                    try:
                        df_fttx_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", ttl=600)
                        if df_fttx_cloud is None or df_fttx_cloud.empty:
                            df_fttx_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                        
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
                        with st.spinner("⏳ Sincronizando y uniendo con histórico en GCS..."):
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
                                        # Descartar solo si indica explícitamente otra empresa (ver nota arriba)
                                        empresa_upper_cloud = df_cloud['EMPRESA'].astype(str).str.strip().str.upper()
                                        mask_otra_empresa_cloud = (empresa_upper_cloud != '') & (empresa_upper_cloud != 'NAN') & (empresa_upper_cloud != 'NONE') & (~empresa_upper_cloud.str.contains('ISCA', na=False))
                                        df_cloud = df_cloud[~mask_otra_empresa_cloud].copy()

                                    PATRON_VIVAS_NUBE = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                    mask_vivas_nube = df_cloud['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS_NUBE, na=False)
                                    df_historial_puro = df_cloud[~mask_vivas_nube].copy()
                                    df_combined = pd.concat([df_historial_puro, df_new])
                                else: df_combined = df_new
                                    
                                if 'NUM' in df_combined.columns:
                                    df_combined['NUM'] = df_combined['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    
                                    df_combined['SORT_DATE'] = pd.to_datetime(df_combined['HORA_LIQ'], errors='coerce')
                                    df_combined['SORT_DATE'] = df_combined['SORT_DATE'].fillna(pd.to_datetime(df_combined['FECHA_APE'], errors='coerce'))
                                    df_combined['SORT_DATE'] = df_combined['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
                                    
                                    PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                    df_combined['ES_VIVA'] = df_combined['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
                                    
                                    df_combined = df_combined.sort_values(by=['ES_VIVA', 'SORT_DATE'], ascending=[False, True])
                                    
                                    df_validos = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                                    df_nd = df_combined[df_combined['NUM'] == 'N/D']
                                    df_combined = pd.concat([df_validos, df_nd]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')

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
                    if st.button("📥 DESCARGAR DATOS AHORA", type="primary", use_container_width=True, key="btn_nube_fallback_inicial"):
                        if conn is not None:
                            sincronizar_datos_nube(conn)
                        else:
                            st.error("Conexión no disponible.")
                return

    df_base = st.session_state.df_base.copy()

    # ==============================================================================
    # EXTRACCIÓN Y MAPEO DINÁMICO DEL ARCHIVO GPS.TXT
    # ==============================================================================
    gps_map = {}
    if os.path.exists("gps.txt"):
        try:
            with open("gps.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) >= 3:
                        g_url = parts[0].strip()
                        g_name = parts[2].strip().rstrip(".")
                        gps_map[normalizar_nombre_cruce(g_name)] = g_url
        except Exception as e:
            pass
    
    if not df_base.empty:
        if 'TECNICO' in df_base.columns:
            df_base['TECNICO'] = df_base['TECNICO'].astype(str).str.strip().str.upper()
            
            # Asignar la columna GPS dinámicamente mediante cruce de nombres normalizados
            df_base['TECNICO_NORM'] = df_base['TECNICO'].apply(normalizar_nombre_cruce)
            
            # === BUSCADOR INTELIGENTE CON TOLERANCIA A NOMBRES INCOMPLETOS ===
            def buscar_enlace_gps(tecnico_norm):
                if not tecnico_norm:
                    return ""
                # 1. Coincidencia exacta post-normalización
                if tecnico_norm in gps_map:
                    return gps_map[tecnico_norm]
                # 2. Coincidencia parcial por sub-palabras (ej: "Nelson Ferrufino" dentro de "Nelson Ramon Ferrufino Leon")
                for gps_name, url in gps_map.items():
                    words_gps = set(gps_name.split())
                    words_tec = set(tecnico_norm.split())
                    # Si el nombre de gps.txt está completamente contenido en el de la base de datos
                    if words_gps.issubset(words_tec) and len(words_gps) >= 2:
                        return url
                    if words_tec.issubset(words_gps) and len(words_tec) >= 2:
                        return url
                return ""
                
            df_base['GPS'] = df_base['TECNICO_NORM'].apply(buscar_enlace_gps)
            df_base.drop(columns=['TECNICO_NORM'], errors='ignore', inplace=True)
        else:
            df_base['GPS'] = ""
            
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
        df_base['NUM'] = df_base['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        
        df_base['SORT_DATE'] = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce')
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.to_datetime(df_base['FECHA_APE'], errors='coerce'))
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
        
        PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
        df_base['ES_VIVA'] = df_base['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
        
        df_base = df_base.sort_values(by=['ES_VIVA', 'SORT_DATE'], ascending=[False, True])
        
        df_validos = df_base[df_base['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_invalidos = df_base[df_base['NUM'] == 'N/D']
        df_base = pd.concat([df_validos, df_invalidos]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')

    df_base = procesar_fechas_seguro(df_base, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
    
    # === FILTRADO AVANZADO DE FALSOS OFFLINE USANDO TELEMETRÍA REAL FTTX ===
    col_olt_info = None
    for col in df_base.columns:
        sample_vals = df_base[col].dropna().astype(str)
        if sample_vals.str.contains("onustatus|statusText|adminState|rxPower", case=False, regex=True).any():
            col_olt_info = col
            break
            
    if col_olt_info:
        def determinar_si_esta_online(val):
            if pd.isnull(val):
                return False
            t = str(val).lower().strip()
            if not t:
                return False
            if "onustatus: down" in t or "onustatus:down" in t or "status: offline" in t or "status_text: offline" in t or "statustext: offline" in t or "statustext:offline" in t:
                return False
            is_up = "onustatus: up" in t or "onustatus:up" in t or "statustext: online" in t or "status_text: online" in t or "statustext:online" in t
            if is_up:
                dbm_real = None

                # Formato "rx:" (ej. vendorId CDKT / equipos ONU residenciales)
                # El valor crudo viene en CENTÉSIMAS de dBm → dividir entre 100.
                # Ej: rx: -3045  ==  -30.45 dBm reales
                rx_match = re.search(r'\brx:\s*(-?\d+\.?\d*)', t)
                if rx_match:
                    try: dbm_real = float(rx_match.group(1)) / 100.0
                    except: pass

                # Formato "rxPower:" (ej. type GPNC14C / tarjetas OLT)
                # El valor crudo viene en MILÉSIMAS de dBm → dividir entre 1000.
                # Ej: rxPower: -16460.000  ==  -16.46 dBm reales
                rxpower_match = re.search(r'rxpower:\s*(-?\d+\.?\d*)', t)
                if rxpower_match:
                    try: dbm_real = float(rxpower_match.group(1)) / 1000.0
                    except: pass

                if dbm_real is not None:
                    # Umbral real de potencia óptica degradada: -30 dBm o peor
                    # (ya convertido a dBm real, ambos formatos quedan en la misma escala)
                    if dbm_real <= -30:
                        return False
                return True
            return False
            
        mask_realmente_online = df_base[col_olt_info].apply(determinar_si_esta_online)
        df_base.loc[mask_realmente_online, 'ES_OFFLINE'] = False

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

    # === CORRECCIÓN DE ESPACIOS EN SOP FIBRA PARA ES_OFFLINE (RESUELVE CAÍDAS 0) ===
    if 'ACTIVIDAD' in df_base_activa.columns and 'COMENTARIO' in df_base_activa.columns:
        act_upper_c = df_base_activa['ACTIVIDAD'].fillna('').astype(str).str.upper().str.strip()
        est_upper_c = df_base_activa['ESTADO'].fillna('').astype(str).str.upper().str.strip()
        com_upper_c = df_base_activa['COMENTARIO'].fillna('').astype(str).str.upper().str.strip()
        
        # Mapea SOP FIBRA con espacio, sin espacio u otros formatos típicos de red
        mask_sop_c = act_upper_c.str.contains(r'SOP\s*FIBRA|SOP_FIBRA', regex=True)
        mask_falsos_c = act_upper_c.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)
        mask_est_abierto_c = est_upper_c != 'CERRADA'
        mask_com_off_c = com_upper_c.str.contains("ONU OFFLINE|OFF LINE|OFFLINE|LOS EN ROJO|PON ROJO", regex=True)
        mask_precisa_c = com_upper_c.apply(es_offline_preciso)
        
        # Sobrescribe el campo de caídas garantizando la lectura del espacio
        df_base_activa['ES_OFFLINE'] = (mask_est_abierto_c & mask_sop_c & ~mask_falsos_c & (mask_com_off_c | mask_precisa_c))
        
        if 'TECNICO' in df_base_activa.columns:
            mask_josue_c = df_base_activa['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
            df_base_activa.loc[mask_josue_c, 'ES_OFFLINE'] = False

    # ==============================================================================
    # 3. RENDERIZADO DE PANTALLAS Y CONFIGURACIÓN
    # ==============================================================================
    if nav_menu_diamante == "⚙️ Configuración":
        settings.mostrar_configuracion()
        return

    if nav_menu_diamante == "📁 Expedientes":
        expediente.mostrar_modulo_expedientes(conn, df_base)
        return
        
    if nav_menu_diamante == "🏅 Control Calidad":
        ccalidad.mostrar_modulo_calidad(conn, df_base)
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
            
            mascara_no_asignadas = ~mascara_tecnico_asignado(df_base_activa['TECNICO'])
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
            
            try:
                # === IMPORTACIÓN INTERNA DIRECTA ===
                from tools import cargar_catalogo_tecnicos
                
                df_cat_tecs = cargar_catalogo_tecnicos()
                if not df_cat_tecs.empty:
                    # === FILTRACIÓN ESTRICTA: Debe ser Técnico Principal y estar ACTIVO ===
                    df_principales = df_cat_tecs[
                        (df_cat_tecs['Clasificación'] == "TÉCNICO PRINCIPAL") & 
                        (df_cat_tecs['Estatus'] == "ACTIVO")
                    ]
                    tecs_validos_set = {normalizar_nombre_cruce(n) for n in df_principales['Nombre'].dropna()}
                    
                    tecs_en_base = df_base_activa['TECNICO'].dropna().unique().tolist()
                    # Filtramos la lista de la pantalla quedándonos únicamente con los activos autorizados
                    tecs_filtrados = [t for t in tecs_en_base if normalizar_nombre_cruce(t) in tecs_validos_set]
                    lista_tecs_monitor = ["Todos"] + sorted(tecs_filtrados)
                else:
                    lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            except Exception:
                lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
                
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor)

        df_monitor_filtrado = df_base_activa.copy()
        if len(filtro_actividad) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
        if len(filtro_estado) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
        if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
        if check_criticos_diamante:
            mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado.get('ALERTA_TIEMPO', False)
            mask_sop_fibra = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('SOP', na=False)
            mask_falsos = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
            df_monitor_filtrado = df_monitor_filtrado[mask_critica & mask_sop_fibra & ~mask_falsos]
        if check_no_asignadas:
            mask_no_asignadas_filtro = ~mascara_tecnico_asignado(df_monitor_filtrado['TECNICO'])
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
                mask_sin_tec = ~mascara_tecnico_asignado(df_todas_vivas['TECNICO'])
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
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Dispatch_Hoy')
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
                        
                        df_para_gantt_diario['TECNICO'] = df_para_gantt_diario['TECNICO'].apply(normalizar_nombre_cruce)
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

                        # Agregar barras de ALMUERZO registradas manualmente para la fecha seleccionada
                        try:
                            df_almuerzos_hist = cargar_almuerzos(conn, fecha=fecha_cal_sel.strftime('%Y-%m-%d'))
                        except Exception:
                            df_almuerzos_hist = pd.DataFrame()

                        if df_almuerzos_hist is not None and not df_almuerzos_hist.empty:
                            filas_almuerzo_h = []
                            for _, fila_alm_h in df_almuerzos_hist.iterrows():
                                try:
                                    tec_alm_h = normalizar_nombre_cruce(fila_alm_h['TECNICO'])
                                    hi_alm_h = datetime.combine(fecha_cal_sel, datetime.strptime(str(fila_alm_h['HORA_INICIO']), '%H:%M').time())
                                    hf_alm_h = datetime.combine(fecha_cal_sel, datetime.strptime(str(fila_alm_h['HORA_FIN']), '%H:%M').time())
                                    filas_almuerzo_h.append({
                                        'TECNICO': tec_alm_h,
                                        'ACTIVIDAD': 'ALMUERZO',
                                        'NUM': '-',
                                        'COLONIA': '-',
                                        'ESTADO': 'ALMUERZO',
                                        'GANTT_START': hi_alm_h,
                                        'GANTT_END': hf_alm_h,
                                        'Inicio': hi_alm_h.strftime('%H:%M'),
                                        'Cierre': hf_alm_h.strftime('%H:%M'),
                                        'TIEMPO_REAL': '-'
                                    })
                                except Exception:
                                    continue
                            if filas_almuerzo_h:
                                df_para_gantt_diario = pd.concat([df_para_gantt_diario, pd.DataFrame(filas_almuerzo_h)], ignore_index=True)
                                df_para_gantt_diario = df_para_gantt_diario.sort_values(by=['TECNICO', 'GANTT_START'])
                        
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
                            "TVADICIONAL": "#00897b",
                            "ALMUERZO": "#78909c"
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

                        # ==============================================================================
                        # CÁLCULOS DINÁMICOS BASADOS EN LA FECHA SELECCIONADA EN EL CALENDARIO (fecha_cal_sel)
                        # ==============================================================================
                        target_date = fecha_cal_sel
                        limite_9am = datetime.combine(target_date, dt_time(9, 0))
                        ahora_local_naive = ahora_local.replace(tzinfo=None)

                        # Define el límite de la jornada laboral según la fecha seleccionada
                        if target_date < hoy_date_valor:
                            referencia_fin = datetime.combine(target_date, dt_time(18, 0))  # Fin de jornada estándar 6:00 PM
                        else:
                            referencia_fin = ahora_local_naive

                        alertas_9am_list = []
                        filas_muerto_list = []

                        # Universo de datos activo de la fecha seleccionada
                        mask_ini_target = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == target_date
                        mask_liq_target = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce').dt.date == target_date
                        mask_ape_target = (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)) & (pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.date == target_date)
                        df_dia_universo = df_base[mask_ini_target | mask_liq_target | mask_ape_target].copy()

                        if not df_dia_universo.empty:
                            tecnicos_activos_dia = df_dia_universo[mascara_tecnico_asignado(df_dia_universo['TECNICO'])]['TECNICO'].unique()
                            
                            for tec in tecnicos_activos_dia:
                                df_tec_dia = df_dia_universo[df_dia_universo['TECNICO'] == tec].copy()
                                
                                # Buscar la primera orden que el técnico inició en esa fecha específica
                                ordenes_iniciadas_dia = df_tec_dia[
                                    df_tec_dia['HORA_INI'].notna() & 
                                    (df_tec_dia['HORA_INI'].dt.date == target_date)
                                ].sort_values(by='HORA_INI')
                                
                                if ordenes_iniciadas_dia.empty:
                                    # Caso: Técnico programado pero no inició actividades
                                    minutos_retraso = max(0, int((referencia_fin - limite_9am).total_seconds() / 60))
                                    if minutos_retraso > 0:
                                        alertas_9am_list.append({
                                            "👨‍🔧 Técnico": tec,
                                            "⏰ Hora de Inicio": "Sin iniciar",
                                            "🚨 Estado de Alerta": f"Aún sin iniciar ({minutos_retraso} min tarde)",
                                            "minutos": minutos_retraso
                                        })
                                    continue
                                    
                                primera_orden_ini = ordenes_iniciadas_dia['HORA_INI'].min()
                                primera_orden_ini_naive = primera_orden_ini.replace(tzinfo=None) if hasattr(primera_orden_ini, 'tzinfo') and primera_orden_ini.tzinfo is not None else primera_orden_ini
                                
                                # --- 1. APERTURA TARDÍA (9:00 AM en adelante) ---
                                if primera_orden_ini_naive >= limite_9am:
                                    minutos_retraso = int((primera_orden_ini_naive - limite_9am).total_seconds() / 60)
                                    alertas_9am_list.append({
                                        "👨‍🔧 Técnico": tec,
                                        "⏰ Hora de Inicio": primera_orden_ini_naive.strftime('%I:%M %p'),
                                        "🚨 Estado de Alerta": f"Inició tarde ({minutos_retraso} min tarde)",
                                        "minutos": minutos_retraso
                                    })
                                    
                                # --- 2. EVALUACIÓN DE TIEMPO MUERTO NETO (SIN DEDUCCIÓN AUTOMÁTICA) ---
                                tiempo_transcurrido_min = max(0.0, (referencia_fin - primera_orden_ini_naive).total_seconds() / 60)
                                tiempo_trabajado_min = 0.0
                                
                                for _, r_ord in ordenes_iniciadas_dia.iterrows():
                                    ini_r = r_ord.get('HORA_INI')
                                    liq_r = r_ord.get('HORA_LIQ')
                                    if pd.isnull(ini_r):
                                        continue
                                    ini_r_naive = ini_r.replace(tzinfo=None) if hasattr(ini_r, 'tzinfo') and ini_r.tzinfo is not None else ini_r
                                    
                                    if pd.notnull(liq_r):
                                        liq_r_naive = liq_r.replace(tzinfo=None) if hasattr(liq_r, 'tzinfo') and liq_r.tzinfo is not None else liq_r
                                        fin_r_naive = min(liq_r_naive, referencia_fin)
                                    else:
                                        fin_r_naive = referencia_fin
                                        
                                    if fin_r_naive > ini_r_naive:
                                        tiempo_trabajado_min += (fin_r_naive - ini_r_naive).total_seconds() / 60

                                # El tiempo muerto es la diferencia directa (almuerzo ya se suma al tiempo trabajado)
                                tiempo_muerto_neto = int(round(max(0.0, tiempo_transcurrido_min - tiempo_trabajado_min)))
                                
                                tiene_orden_activa = not ordenes_iniciadas_dia[ordenes_iniciadas_dia['HORA_LIQ'].isnull()].empty
                                if tiene_orden_activa:
                                    estado_actual = "🔧 En orden activa"
                                else:
                                    last_closed = ordenes_iniciadas_dia[ordenes_iniciadas_dia['HORA_LIQ'].notna()]
                                    if not last_closed.empty:
                                        liq_last = last_closed['HORA_LIQ'].max()
                                        liq_last_naive = liq_last.replace(tzinfo=None) if hasattr(liq_last, 'tzinfo') and liq_last.tzinfo is not None else liq_last
                                        estado_actual = f"Libre desde {liq_last_naive.strftime('%I:%M %p')}"
                                    else:
                                        estado_actual = "Libre (Sin cierres)"

                                filas_muerto_list.append({
                                    "👨‍🔧 Técnico": tec,
                                    "🌅 Hora 1ra Orden": primera_orden_ini_naive.strftime('%I:%M %p'),
                                    "🚦 Estado Actual": estado_actual,
                                    "Tiempo Transcurrido (min)": int(tiempo_transcurrido_min),
                                    "Tiempo Trabajado (min)": int(tiempo_trabajado_min),
                                    "🕳️ Tiempo Muerto Neto (min)": tiempo_muerto_neto
                                })

                        # === DESPLIEGUE DE TABLAS DE ANÁLISIS DE TIEMPOS ===
                        with st.expander("📋 Detalle de Apertura Tardía (Inicios >= 9:00 AM)", expanded=False):
                            if not alertas_9am_list:
                                st.success("🎉 ¡Excelente! Todos los técnicos iniciaron sus labores antes de las 9:00 AM hoy.")
                            else:
                                df_tabla_apertura = pd.DataFrame(alertas_9am_list)
                                df_tabla_apertura = df_tabla_apertura.sort_values(by='minutos', ascending=False)
                                df_tabla_apertura_mostrar = df_tabla_apertura[["👨‍🔧 Técnico", "⏰ Hora de Inicio", "🚨 Estado de Alerta"]]
                                
                                st.dataframe(
                                    df_tabla_apertura_mostrar,
                                    use_container_width=True,
                                    hide_index=True
                                )

                        with st.expander("🕳️ Detalle de Tiempo Muerto Total de la Jornada", expanded=False):
                            if not filas_muerto_list:
                                st.info("ℹ️ No hay registros de actividades para calcular tiempos muertos en esta fecha.")
                            else:
                                df_tabla_muerto = pd.DataFrame(filas_muerto_list)
                                df_tabla_muerto = df_tabla_muerto.sort_values(by="🕳️ Tiempo Muerto Neto (min)", ascending=False)
                                
                                st.dataframe(
                                    df_tabla_muerto,
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        "Tiempo Transcurrido (min)": st.column_config.NumberColumn("⏳ Transcurrido (min)", format="%d"),
                                        "Tiempo Trabajado (min)": st.column_config.NumberColumn("🔧 Trabajado (min)", format="%d"),
                                        "🕳️ Tiempo Muerto Neto (min)": st.column_config.NumberColumn("🕳️ Muerto Neto (min)", format="%d")
                                    }
                                )
                                
                                # --- SUMATORIA TOTAL DEL TIEMPO MUERTO PERDIDO ---
                                total_minutos_perdidos = df_tabla_muerto["🕳️ Tiempo Muerto Neto (min)"].sum()
                                horas_perdidas, minutos_restantes = divmod(total_minutos_perdidos, 60)
                                
                                st.markdown(f"""
                                <div style="background-color: rgba(239, 68, 68, 0.1); padding: 15px; border-radius: 8px; border-left: 5px solid #EF4444; margin-top: 15px;">
                                    <span style="color: #EF4444; font-weight: bold; font-size: 1.05rem;">⏱️ TOTAL DE TIEMPO MUERTO NETO PERDIDO POR EL EQUIPO EN ESTA JORNADA:</span>
                                    <span style="color: white; font-weight: bold; font-size: 1.2rem; margin-left: 10px;">{horas_perdidas} horas y {minutos_restantes} minutos</span>
                                </div>
                                """, unsafe_allow_html=True)

                        # ==============================================================================
                        # BOTÓN DE REPORTE EN PDF
                        # ==============================================================================
                        col_bpdf1, col_bpdf2 = st.columns([1, 2])
                        with col_bpdf1:
                            if st.button("📄 GENERAR PDF TIEMPOS Y TIEMPO PERDIDO", use_container_width=True):
                                with st.spinner("Calculando rendimientos de la jornada..."):
                                    st.session_state['pdf_tiempos_muertos'] = generar_pdf_tiempos_muertos(df_para_gantt_final, fecha_cal_sel)
                                    
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
    # 7. TABLA DE MONITOREO PRINCIPAL (RENDIMIENTO DE FILAS)
    # ==============================================================================        
    if nav_menu_diamante == "⚡ Monitor en Vivo":
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
                    

        t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL OPERATIVO", "📊 PRODUCTIVIDAD", "📈 ANALÍTICA"])
        
        with t_panel_v:
            if not df_v_tabla_monitor.empty:
                if es_movil:
                    st.markdown("<br>", unsafe_allow_html=True)
                    for idx, row in df_v_tabla_monitor.iterrows():
                        color_borde = "#EF4444" if row.get('ES_OFFLINE') else ("#F59E0B" if row.get('ALERTA_TIEMPO') else "#3B82F6")
                        estado_txt = str(row.get('ESTADO', 'N/D')).upper()
                        bg_estado = "#10B981" if estado_txt == "CERRADA" else ("#d32f2f" if estado_txt == "ANULADA" else "#2D3748")
                        
                        # Identificar si la orden está aperturada en móvil
                        raw_hi = row.get('HORA_INI')
                        hi_str = str(raw_hi).strip().upper() if pd.notnull(raw_hi) else ""
                        is_hi_val = pd.notnull(raw_hi) and hi_str not in ['', '---', 'NAT', 'NONE', 'NAN']
                        is_est_act = str(row.get('ESTADO', '')).upper().strip() in ['INICIADA', 'PROCESO', 'SITIO', 'VIAJANDO', 'LLEGADA', 'RUTA', 'CAMINO']
                        
                        show_gps_mobile = (is_hi_val or is_est_act) and row.get('GPS')
                        gps_link_html = f'<br>📍 <a href="{row.get("GPS")}" target="_blank" style="color: #3B82F6; font-weight: bold; text-decoration: none;">UBICACIÓN GPS ↗</a>' if show_gps_mobile else ""
                        
                        st.markdown(f"""
                        <div style="background-color: #1A1D24; padding: 15px; border-radius: 12px; margin-bottom: 12px; border-left: 5px solid {color_borde}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <span style="color: white; font-weight: bold; font-size: 16px;">ORD-{row.get('NUM', 'N/D')}</span>
                                <span style="background: {bg_estado}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">{estado_txt}</span>
                            </div>
                            <div style="color: #94A3B8; font-size: 13px; margin-bottom: 8px; line-height: 1.4;">
                                👤 <b>{str(row.get('NOMBRE', 'N/D'))[:25]}</b> <br>
                                📍 {str(row.get('COLONIA', 'N/D'))[:30]}
                                {gps_link_html}
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
                    
                    # === CONTROL DE COLUMNA GPS Y CONDICIONES DE APERTURA ===
                    if "GPS" in df_v_tabla_monitor.columns:
                        raw_hora_ini = df_v_tabla_monitor['HORA_INI']
                        hora_ini_str = raw_hora_ini.astype(str).str.strip().str.upper()
                        is_hora_ini_valid = raw_hora_ini.notna() & (~hora_ini_str.isin(['', '---', 'NAT', 'NONE', 'NAN']))
                        
                        is_estado_active = df_v_tabla_monitor['ESTADO'].astype(str).str.upper().str.strip().isin(
                            ['INICIADA', 'PROCESO', 'SITIO', 'VIAJANDO', 'LLEGADA', 'RUTA', 'CAMINO']
                        )
                        
                        mask_aperturada = is_hora_ini_valid | is_estado_active
                        
                        gps_filtrado = np.where(mask_aperturada, df_v_tabla_monitor["GPS"].fillna(""), "")
                        df_estilo_v["GPS"] = gps_filtrado
                        
                        cols = list(df_estilo_v.columns)
                        if "GPS" in cols:
                            cols.remove("GPS")
                        if "COLONIA" in cols:
                            idx_colonia = cols.index("COLONIA")
                            cols.insert(idx_colonia, "GPS")
                        else:
                            cols.append("GPS")
                        df_estilo_v = df_estilo_v[cols]
                    
                    evento_monitor_diam = st.dataframe(
                        df_estilo_v.style.apply(row_styler, axis=1),
                        column_config={
                            "GPS": st.column_config.LinkColumn("UBICACIÓN GPS", display_text="🔍 Ver"),
                            "NOMBRE": st.column_config.TextColumn("NOMBRE", width="medium"),
                            "COLONIA": st.column_config.TextColumn("COLONIA", width="medium"),
                            "COMENTARIO": st.column_config.TextColumn("COMENTARIO", width="large"),
                            "ES_OFFLINE": st.column_config.CheckboxColumn("🔴 OFFLINE"), # <--- ACTIVADO VISIBLE EN LA TABLA
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
            
            if df_v_tabla_monitor.empty:
                st.info("ℹ️ No hay datos disponibles para mostrar el análisis gráfico en este momento.")
            else:
                plt.style.use('dark_background')
                
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

if __name__ == '__main__':
    if verificar_autenticacion():
        main()
    else:
        mostrar_pantalla_login()
