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
        cargar_catalogo_tecnicos,
        guardar_orden_manual,
        cargar_ordenes_manuales
    )
except ImportError as e:
    st.error(f"⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'. Detalle: {e}")
    
# ==============================================================================
# CONSTANTES DE NEGOCIO Y CONFIGURACIÓN GLOBAL
# ==============================================================================
# ==============================================================================
# LISTA MAESTRA DE ACTIVIDADES
# ==============================================================================
# Esta es la ÚNICA fuente de verdad sobre qué actividades son visitas técnicas
# reales y por lo tanto pueden mostrarse en la aplicación (Gantt, reportes,
# asignadas, pendientes, PDFs, KPIs). Se aplica como filtro global sobre df_base,
# así que cualquier actividad que NO esté aquí queda descartada desde la raíz del
# pipeline y no puede reaparecer en ninguna vista.
# Para agregar o quitar una actividad, se edita SOLO esta lista.
ACTIVIDADES_PERMITIDAS = [
    'CEQUI', 'INSEQUIPO', 'INSFIBRA', 'INSFIBRACORP', 'INSHFC', 'INS-WA',
    'PEXTERNO', 'PLEXISCA', 'SOP', 'SOPCORP', 'SOPFIBRA', 'SOPFIBRACORP',
    'SOPRECONCORP', 'SOPRECONFIBRA', 'SOPRECONHFC', 'SPLITTEROPT',
    'TRASLADOEXTFIBRA', 'TRASLADOEXTFIBRACORP', 'TRASLADOINTERNOFIBRA',
    'TRASLADOINTFIBRACORP', 'TVADICIONAL'
]

# Las constantes de abajo se mantienen por compatibilidad con el resto del
# código, pero ya NO son listas independientes: todas apuntan a la lista maestra
# para que sea imposible que se vuelvan a desincronizar entre sí.
ACTIVIDADES_VALIDAS_NO_ASIGNADAS = ACTIVIDADES_PERMITIDAS
ACTIVIDADES_GANTT_PERMITIDAS = ACTIVIDADES_PERMITIDAS

PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
ACTIVIDADES_BASURA = ['ACTUALIZACIONDATOS', 'ACTUALIZACIOFW', 'ACTUALIZAINFOTECNICA', 'ACTUALIZARDATOSTECNICOS', 'ACTUALIZARSENSOR', 'ACTIVARRES', 'DESTEFO']
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

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

                df_nube = procesar_fechas_seguro(df_nube, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'], columnas_sin_asumir_hoy=['HORA_LIQ', 'FECHA_APE'])
                
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
    
    # Se fuerza es_movil a False para unificar la interfaz de escritorio en todos los roles
    es_movil = False

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
    
    # === SISTEMA DE NAVEGACIÓN RESISTENTE A REINICIOS ===
    if 'nav_menu_diamante' not in st.session_state:
        st.session_state['nav_menu_diamante'] = "⚡ Monitor en Vivo"

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
                key="mobile_nav_menu_opt",
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
                nav_menu_diamante = st.selectbox("Seleccione un módulo extra:", ["🏅 Control Calidad", "📅 Reprog / No Inst", "⚙️ Configuración", "📁 Expedientes"], key="mobile_extra_sel_opt")    
        else:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor", "Calidad"],
                icons=["lightning", "award"],
                default_index=0,
                orientation="horizontal",
                key="mobile_nav_menu_opt",
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
        st.session_state['nav_menu_diamante'] = nav_menu_diamante
    else:
        # Definición segura de las opciones según el rol
        if rol_usuario in ['admin', 'jefe']:
            opciones_menu = ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "🏅 Control Calidad", "📅 Reprog / No Inst", "🚙 Auditoría Vehículos", "⚙️ Configuración", "📁 Expedientes"]
        else:
            opciones_menu = ["⚡ Monitor en Vivo", "🏅 Control Calidad"]

        # Buscar el índice del valor actual de sesión para que nunca se pierda la selección
        default_val = st.session_state.get('nav_menu_diamante', "⚡ Monitor en Vivo")
        if default_val in opciones_menu:
            default_index = opciones_menu.index(default_val)
        else:
            default_index = 0

        with sidebar_top:
            if rol_usuario in ['admin', 'jefe']: 
                nav_menu_diamante = st.radio(
                    "MENÚ DE CONTROL:", 
                    opciones_menu, 
                    index=default_index, 
                    key="nav_menu_radio_admin"
                )
            else:
                st.markdown("### 🖥️ Menú de Control")
                nav_menu_diamante = st.radio(
                    "SELECCIONE EL MÓDULO:", 
                    opciones_menu, 
                    index=default_index, 
                    key="nav_menu_radio_user"
                )
            # Sincronizamos la variable de sesión persistente
            st.session_state['nav_menu_diamante'] = nav_menu_diamante

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
            st.markdown("### 📝 Ingresar Orden Manual")
            with st.expander("Ingresar una orden que no se refleja en el sistema", expanded=False):
                st.caption("Úsalo cuando la API falle y una orden real de un técnico no aparezca en el monitor.")

                num_orden_manual = st.text_input("Número de orden", key="input_num_orden_manual")

                actividades_orden_manual = sorted(ACTIVIDADES_GANTT_PERMITIDAS)
                actividad_manual_sel = st.selectbox("Actividad", options=actividades_orden_manual, key="sel_actividad_orden_manual")

                lista_tecs_principales_manual = []
                try:
                    df_cat_tecs_manual = cargar_catalogo_tecnicos()
                    if df_cat_tecs_manual is not None and not df_cat_tecs_manual.empty:
                        lista_tecs_principales_manual = sorted(
                            df_cat_tecs_manual[df_cat_tecs_manual['Clasificación'] == 'TÉCNICO PRINCIPAL']['Nombre'].dropna().unique().tolist()
                        )
                except Exception:
                    pass

                if lista_tecs_principales_manual:
                    tec_orden_manual_sel = st.selectbox("Técnico", options=lista_tecs_principales_manual, key="sel_tec_orden_manual")
                else:
                    tec_orden_manual_sel = st.text_input("Técnico (nombre exacto)", key="input_tec_orden_manual")

                fecha_orden_manual_sel = st.date_input("Fecha", value=get_honduras_time().date(), key="fecha_orden_manual_sel")
                col_omi, col_oml = st.columns(2)
                with col_omi:
                    hora_ini_orden_manual_txt = st.text_input("Hora inicio (HH:MM)", value="", placeholder="08:00", key="hora_ini_orden_manual", max_chars=5)
                with col_oml:
                    hora_liq_orden_manual_txt = st.text_input("Hora liquidada (HH:MM)", value="", placeholder="Dejar vacío si sigue abierta", key="hora_liq_orden_manual", max_chars=5)

                if st.button("💾 Guardar Orden Manual", use_container_width=True, key="btn_guardar_orden_manual"):
                    hora_ini_om_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_ini_orden_manual_txt.strip())
                    hora_liq_om_valida = (hora_liq_orden_manual_txt.strip() == "") or re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_liq_orden_manual_txt.strip())
                    if not num_orden_manual.strip():
                        st.warning("Ingresa el número de orden.")
                    elif not tec_orden_manual_sel:
                        st.warning("Selecciona o escribe un técnico.")
                    elif not hora_ini_om_valida:
                        st.warning("La hora de inicio debe tener formato HH:MM en 24 horas (ej. 08:00).")
                    elif not hora_liq_om_valida:
                        st.warning("La hora liquidada debe tener formato HH:MM en 24 horas (ej. 14:30), o dejarse vacía si la orden sigue abierta.")
                    else:
                        ok_orden_manual = guardar_orden_manual(
                            num_orden=num_orden_manual.strip(),
                            actividad=actividad_manual_sel,
                            tecnico=tec_orden_manual_sel,
                            fecha=fecha_orden_manual_sel.strftime('%Y-%m-%d'),
                            hora_inicio=hora_ini_orden_manual_txt.strip(),
                            hora_liq=hora_liq_orden_manual_txt.strip(),
                            registrado_por=st.session_state.get('usuario_actual', rol_usuario)
                        )
                        if ok_orden_manual:
                            st.success(f"✅ Orden {num_orden_manual.strip()} guardada manualmente para {tec_orden_manual_sel}.")
                            st.cache_data.clear()
                        else:
                            st.error("No se pudo guardar la orden manual.")
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

        # Indicador de antigüedad de los datos en memoria. Los datos NO se
        # refrescan solos: quedan congelados en la sesión desde que se cargaron.
        # Sin este aviso, una sesión abierta hace horas muestra información vieja
        # sin ninguna señal, y parece que "faltan órdenes" cuando en realidad lo
        # que falta es actualizar.
        _cargado_en = st.session_state.get('df_base_cargado_en')
        if _cargado_en is not None:
            try:
                _minutos_datos = int((get_honduras_time() - _cargado_en).total_seconds() // 60)
                _hora_datos = _cargado_en.strftime('%H:%M')
                if _minutos_datos >= 60:
                    st.warning(f"⚠️ Datos cargados a las {_hora_datos} (hace {_minutos_datos // 60}h {_minutos_datos % 60}min). Actualiza para ver las órdenes más recientes.")
                elif _minutos_datos >= 20:
                    st.info(f"🕒 Datos cargados a las {_hora_datos} (hace {_minutos_datos} min).")
                else:
                    st.caption(f"🟢 Datos actualizados a las {_hora_datos}.")
            except Exception:
                pass
        
        if es_admin:
            st.markdown("#### ⚡ Actualización Inmediata")
            btn_api_procesar = st.button("🔄 FORZAR ACTUALIZACIÓN INMEDIATA", use_container_width=True, type="primary", key="btn_forzar_act_admin")
            
            st.divider()
            st.markdown("#### 📄 Actividades (rep_actividades)")
            st.caption("Solo necesitas subir las actividades. El catálogo FTTX se toma automáticamente de la nube (pestaña FTTX / GCS).")
            archivo_actividades = st.file_uploader("Sube rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_actividades_admin")
            if archivo_actividades: file_act_ptr = archivo_actividades
            btn_reprocesar = st.button("🔄 PROCESAR ACTIVIDADES", use_container_width=True, key="btn_proc_act_admin")

            st.divider()
            st.markdown("#### 🚙 Catálogo FTTX")
            st.caption("Sube esto SOLO cuando necesites actualizar el catálogo de dispositivos en la nube. No requiere subir actividades a la vez.")
            archivo_fttx = st.file_uploader("Sube FttxActiveDevice", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_fttx_admin")
            btn_actualizar_fttx = st.button("🔄 ACTUALIZAR SOLO CATÁLOGO FTTX", use_container_width=True, key="btn_act_fttx_admin")

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
            archivo_unico = st.file_uploader("Sube únicamente el rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_unico_user")
            if archivo_unico: file_act_ptr = archivo_unico
            btn_reprocesar = st.button("🔄 PROCESAR ARCHIVO SUBIDO", use_container_width=True, key="btn_proc_act_user")
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

    # Marca de tiempo del "snapshot" de datos que vive en memoria de ESTA sesión.
    # df_base se guarda en st.session_state y NO se refresca solo: cada sesión
    # conserva la foto de los datos del momento en que se cargó. Por eso dos
    # usuarios distintos pueden ver información diferente al mismo tiempo si uno
    # abrió su sesión antes que el otro. Guardar la hora permite avisarlo.
    if btn_reprocesar or btn_api_procesar or st.session_state.get('df_base_cargado_en') is None:
        st.session_state['df_base_cargado_en'] = get_honduras_time()

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
            df_base['TECNICO_NORM'] = df_base['TECNICO'].apply(normalizar_nombre_cruce)
            
            def buscar_enlace_gps(tecnico_norm):
                if not tecnico_norm:
                    return ""
                if tecnico_norm in gps_map:
                    return gps_map[tecnico_norm]
                for gps_name, url in gps_map.items():
                    words_gps = set(gps_name.split())
                    words_tec = set(tecnico_norm.split())
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
    
    # Copia previa al filtro de actividad. Se define siempre (aunque no exista la
    # columna ACTIVIDAD) para que las vistas que dependen de ella nunca fallen.
    df_base_sin_filtro_actividad = df_base.copy()

    if 'ACTIVIDAD' in df_base.columns:
        # FILTRO GLOBAL POR LISTA BLANCA. Antes se usaba una lista negra
        # (ACTIVIDADES_BASURA), lo que obligaba a ir agregando cada actividad
        # indeseada una por una conforme aparecía. Ahora se invierte el criterio:
        # SOLO sobreviven las actividades de la lista maestra. Como este filtro se
        # aplica sobre df_base -- la raíz de la que derivan el Monitor, el Gantt,
        # asignadas, pendientes, reportes y PDFs -- cualquier otra actividad queda
        # descartada de toda la aplicación y no puede reaparecer en ninguna vista.
        mask_actividad_permitida = df_base['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_PERMITIDAS)
        df_base = df_base[mask_actividad_permitida].copy()

    if 'NUM' in df_base.columns:
        df_base['NUM'] = df_base['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        
        df_base['SORT_DATE'] = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce')
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.to_datetime(df_base['FECHA_APE'], errors='coerce'))
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
        
        PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
        df_base['ES_VIVA'] = df_base['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)

        # DEDUPLICACIÓN POR NUM: debe sobrevivir el registro MÁS RECIENTE.
        #
        # Antes se ordenaba por ES_VIVA primero (descendente) y se conservaba el
        # último, lo que hacía que CUALQUIER registro no-vivo le ganara siempre a
        # la versión viva, sin importar las fechas. Si una orden traía un registro
        # viejo CERRADA/ANULADA además del registro vivo actual, se conservaba el
        # viejo y la orden real desaparecía del Monitor, del Gantt y de pendientes.
        #
        # Ahora manda SORT_DATE (recencia). Esto sigue funcionando bien para las
        # órdenes genuinamente cerradas, porque su HORA_LIQ siempre es posterior a
        # su propia FECHA_APE, así que el registro cerrado gana por sí solo.
        # ES_VIVA queda únicamente como desempate: si dos registros tienen la misma
        # fecha, prevalece el estado final (no vivo).
        df_base = df_base.sort_values(by=['SORT_DATE', 'ES_VIVA'], ascending=[True, False])

        df_validos = df_base[df_base['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_invalidos = df_base[df_base['NUM'] == 'N/D']
        df_base = pd.concat([df_validos, df_invalidos]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')

    df_base = procesar_fechas_seguro(df_base, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'], columnas_sin_asumir_hoy=['HORA_LIQ', 'FECHA_APE'])

    # === INTEGRACIÓN DE ÓRDENES MANUALES ===
    # Se agregan las órdenes cargadas manualmente (para cuando la API falla y
    # una orden real no se refleja). Si la orden real ya llegó después por la
    # API/Sheets (mismo NUM), se descarta la versión manual para no duplicar.
    try:
        df_ordenes_manuales = cargar_ordenes_manuales()
        if df_ordenes_manuales is not None and not df_ordenes_manuales.empty:
            if 'NUM' in df_base.columns:
                nums_ya_reales = set(df_base['NUM'].astype(str).str.strip())
                df_ordenes_manuales = df_ordenes_manuales[~df_ordenes_manuales['NUM'].astype(str).str.strip().isin(nums_ya_reales)]
            if not df_ordenes_manuales.empty:
                df_base = pd.concat([df_base, df_ordenes_manuales], ignore_index=True)
    except Exception:
        pass
    
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
                rx_match = re.search(r'\brx:\s*(-?\d+\.?\d*)', t)
                if rx_match:
                    try: dbm_real = float(rx_match.group(1)) / 100.0
                    except: pass
                rxpower_match = re.search(r'rxpower:\s*(-?\d+\.?\d*)', t)
                if rxpower_match:
                    try: dbm_real = float(rxpower_match.group(1)) / 1000.0
                    except: pass
                if dbm_real is not None:
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
        
        mask_sop_c = act_upper_c.str.contains(r'SOP\s*FIBRA|SOP_FIBRA', regex=True)
        mask_falsos_c = act_upper_c.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)
        mask_est_abierto_c = est_upper_c != 'CERRADA'
        mask_com_off_c = com_upper_c.str.contains("ONU OFFLINE|OFF LINE|OFFLINE|LOS EN ROJO|PON ROJO", regex=True)
        mask_precisa_c = com_upper_c.apply(es_offline_preciso)
        
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
            st.caption("Órdenes asignadas que el técnico cerró como NO INSTALADAS durante el día de hoy.")
            # Se lee de la copia PREVIA al filtro global de actividad, porque
            # NOINSTALADO no está en la lista maestra y de otro modo esta vista
            # quedaría vacía. OJO: eso NO significa traer historial -- abajo se
            # sigue acotando estrictamente al día de hoy.
            df_fuente_noinst = df_base_sin_filtro_actividad

            # HORA_LIQ viene en UTC, así que se le restan 6h para obtener la fecha
            # real en hora de Honduras. Sin este ajuste, las órdenes cerradas ayer
            # entre las 6:00pm y medianoche caen en la misma fecha UTC que hoy y
            # se colaban en esta vista como si fueran del día actual.
            hora_liq_local_noinst = pd.to_datetime(df_fuente_noinst['HORA_LIQ'], errors='coerce') - pd.Timedelta(hours=6)

            mask_noinst_hoy = (
                df_fuente_noinst['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)
                & (hora_liq_local_noinst.dt.date == hoy_date_valor)
                & mascara_tecnico_asignado(df_fuente_noinst['TECNICO'])
            )

            df_noinst_hoy = df_fuente_noinst[mask_noinst_hoy].copy()
            if df_noinst_hoy.empty:
                st.success("✅ No hay órdenes cerradas como NOINSTALADO en el día de hoy.")
            else:
                st.metric("Total NOINSTALADO hoy", len(df_noinst_hoy))
                st.dataframe(df_noinst_hoy[['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']].sort_values(by='HORA_LIQ'), use_container_width=True, height=600, hide_index=True)
            
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
            
            filtro_actividad = st.multiselect("🛠️ Tipo de Actividad:", options=lista_actividades, default=[], placeholder="Todas las actividades", key="filtro_actividad_multiselect")
            filtro_estado = st.multiselect("🚦 Estado de Orden:", options=lista_estados, default=[], placeholder="Todos los estados", key="filtro_estado_multiselect")
            filtro_motivo = st.multiselect("⚠️ Motivo / Diagnóstico:", options=lista_motivos, default=[], placeholder="Todos los motivos", key="filtro_motivo_multiselect")
            
            st.divider() 
            st.markdown("### 🔍 Filtros en Vivo")
            
            m_viva_count = df_base_activa['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            
            if 'ES_OFFLINE' not in df_base_activa.columns:
                df_base_activa['ES_OFFLINE'] = False
            mascara_offline_segura = df_base_activa['ES_OFFLINE'] == True
            
            total_off_count_viva = int((mascara_offline_segura & m_viva_count).sum())
            
            # --- MODIFICACIÓN DE "NO ASIGNADAS": SE VALIDA QUE LA ACTIVIDAD ESTÉ EN LA LISTA PERMITIDA ---
            mask_no_asig_act_base = df_base_activa['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
            mascara_no_asignadas = (~mascara_tecnico_asignado(df_base_activa['TECNICO'])) & mask_no_asig_act_base
            total_no_asignadas_viva = int((mascara_no_asignadas & m_viva_count).sum())
            
            check_criticos_diamante = st.toggle(f"🚨 Ver solo Críticas ({total_off_count_viva})", key="toggle_criticos")
            check_no_asignadas = st.toggle(f"🚨 Ver NO Asignadas ({total_no_asignadas_viva})", key="toggle_no_asignadas")
         
            total_vivas = int(m_viva_count.sum()) 
            check_ordenes_totales = st.toggle(f"📋 Órdenes Totales Pendientes ({total_vivas})", key="toggle_totales")
            
            if check_ordenes_totales:
                if st.button("📄 GENERAR PDF DE ÓRDENES TOTALES", use_container_width=True, key="btn_generar_pdf_totales"):
                    with st.spinner("Generando documento PDF..."):
                        df_vivas_export = df_base_activa[m_viva_count].copy()
                        st.session_state['pdf_totales_gen'] = generar_pdf_ordenes_totales(df_vivas_export, hoy_date_valor)
                if 'pdf_totales_gen' in st.session_state and st.session_state['pdf_totales_gen']:
                    st.download_button("📥 DESCARGAR PDF TOTAL", data=st.session_state['pdf_totales_gen'], file_name=f"Ordenes_Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_download_pdf_totales")
            
            try:
                from tools import cargar_catalogo_tecnicos
                
                df_cat_tecs = cargar_catalogo_tecnicos()
                if not df_cat_tecs.empty:
                    df_principales = df_cat_tecs[
                        (df_cat_tecs['Clasificación'] == "TÉCNICO PRINCIPAL") & 
                        (df_cat_tecs['Estatus'] == "ACTIVO")
                    ]
                    tecs_validos_set = {normalizar_nombre_cruce(n) for n in df_principales['Nombre'].dropna()}
                    
                    tecs_en_base = df_base_activa['TECNICO'].dropna().unique().tolist()
                    tecs_filtrados = [t for t in tecs_en_base if normalizar_nombre_cruce(t) in tecs_validos_set]
                    lista_tecs_monitor = ["Todos"] + sorted(tecs_filtrados)
                else:
                    lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            except Exception:
                lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
                
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor, key="sel_tecnico_monitor")

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
            # --- SE APLICA EL FILTRO DE ACTIVIDAD AL FILTRAR EN VIVO LAS NO ASIGNADAS ---
            mask_no_asig_act_filtro = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
            mask_no_asignadas_filtro = (~mascara_tecnico_asignado(df_monitor_filtrado['TECNICO'])) & mask_no_asig_act_filtro
            df_monitor_filtrado = df_monitor_filtrado[mask_no_asignadas_filtro]
        if tec_filtro_monitor != "Todos": 
            df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro_monitor]

        # AVISO DE FILTROS ACTIVOS. Algunos filtros del panel lateral eliminan
        # categorías COMPLETAS de la vista -- por ejemplo, "Ver solo Críticas"
        # descarta todas las PLEXISCA, PEXTERNO, SPLITTEROPT e instalaciones --
        # y sin este aviso parecía que faltaban órdenes o que un técnico no
        # había trabajado, cuando en realidad estaban ocultas por un filtro.
        _filtros_activos = []
        if check_criticos_diamante:
            _filtros_activos.append("🚨 **Ver solo Críticas** — oculta TODAS las PLEX, PEXTERNO, SPLITTEROPT e instalaciones")
        if check_no_asignadas:
            _filtros_activos.append("🚨 **Ver NO Asignadas** — oculta todas las órdenes que ya tienen técnico")
        if len(filtro_actividad) > 0:
            _filtros_activos.append(f"🛠️ **Actividad**: {', '.join(map(str, filtro_actividad))}")
        if len(filtro_estado) > 0:
            _filtros_activos.append(f"🚦 **Estado**: {', '.join(map(str, filtro_estado))}")
        if len(filtro_motivo) > 0:
            _filtros_activos.append(f"⚠️ **Motivo**: {', '.join(map(str, filtro_motivo))}")
        if tec_filtro_monitor != "Todos":
            _filtros_activos.append(f"👤 **Técnico**: {tec_filtro_monitor}")

        if _filtros_activos:
            st.warning(
                "**Hay filtros activos ocultando información:**\n\n- "
                + "\n- ".join(_filtros_activos)
                + f"\n\nSe están mostrando **{len(df_monitor_filtrado)}** de **{len(df_base_activa)}** órdenes. "
                "Desactívalos en el panel lateral para ver todo."
            )
    else: 
        df_monitor_filtrado = df_base_activa.copy()

    # ==============================================================================
    # 5. PANTALLA: CENTRO DE REPORTES
    # ==============================================================================
    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        
        # MENSAJE DE AYUDA DE NAVEGADOR PARA DESCARGAS DE REPORTES
        st.info("💡 **Para Supervisores de Campo (Móvil):** Si estás descargando un reporte en PDF o Excel desde tu celular, asegúrate de haber abierto el monitor operativo en tu navegador nativo (**Chrome o Safari**). Si abres este monitor directamente dentro de un chat de WhatsApp o WATI, las descargas serán bloqueadas por seguridad del dispositivo móvil.")

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
                # --- AQUÍ TAMBIÉN SE FILTRAN LAS NO ASIGNADAS BAJO LA REGLA DE ACTIVIDAD ---
                mask_sin_tec_act = df_todas_vivas['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
                mask_sin_tec = (~mascara_tecnico_asignado(df_todas_vivas['TECNICO'])) & mask_sin_tec_act
                df_asig = df_todas_vivas[mascara_tecnico_asignado(df_todas_vivas['TECNICO'])].copy()
                df_no_asig = df_todas_vivas[mask_sin_tec].copy()
                
                def clasificas_dispatch(row):
                    act = str(row.get('ACTIVIDAD', '')).upper(); com = str(row.get('COMENTARIO', '')).upper(); txt = act + " " + com
                    if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act): return "INSTALACIONES"
                    elif re.search("SOP|FALLA|MANT", act): return "MANTENIMIENTOS"
                    elif re.search("PLEX|PEXTERNO|SPLITTEROPT", txt): return "PLEX"
                    else: return "OTRAS"
                    
                if not df_asig.empty:
                    df_asig['CATEGORIA'] = df_asig.apply(clasificas_dispatch, axis=1)
                    res_a = df_asig['CATEGORIA'].value_counts().reset_index()
                    res_a.columns = ['Categoría', 'Asignadas (En Ruta)']
                else: res_a = pd.DataFrame(columns=['Categoría', 'Asignadas (En Ruta)'])
                if not df_no_asig.empty:
                    df_no_asig['CATEGORIA'] = df_no_asig.apply(clasificas_dispatch, axis=1)
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
                    df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificas_dispatch, axis=1)
                    cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                    df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Manana')
                    st.download_button(label="📥 Exportar EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="btn_descargar_excel_pendientes")
                    if st.button("📄 Generar PDF", use_container_width=True, type="primary", key="btn_generar_pdf_dispatch_mobile"):
                        with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                    if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_dispatch_mobile")
                else:
                    col_d1, col_d2 = st.columns([2, 1])
                    with col_d1:
                        def highlight_total(row): return ['background-color: #2D3748; color: white; font-weight: bold' if row['Categoría'] == 'TOTAL PENDIENTES' else '' for _ in row.index]
                        st.dataframe(df_dispatch_final.style.apply(highlight_total, axis=1), use_container_width=True, hide_index=True, column_config={"Categoría": st.column_config.TextColumn("CLASIFICACIÓN"), "Asignadas (En Ruta)": st.column_config.NumberColumn("🚗 ASIGNADAS", format="%d"), "Nuevas (Sin Asignar)": st.column_config.NumberColumn("📥 SIN ASIGNAR", format="%d"), "TOTAL GENERAL": st.column_config.NumberColumn("📦 TOTAL", format="%d")})
                    with col_d2:
                        st.info("Genera los reportes para enviar al departamento de Dispatch.")
                        buffer = io.BytesIO()
                        df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificas_dispatch, axis=1)
                        cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                        df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Dispatch_Hoy')
                        st.download_button(label="📥 Exportar Resumen a EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_Dispatch_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="btn_descargar_excel_dispatch")
                        if st.button("📄 Generar PDF (Dispatch)", use_container_width=True, type="primary", key="btn_generar_pdf_dispatch_desktop"):
                            with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                        if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF Generado", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_Dispatch_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_dispatch_desktop")
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
                        if st.button("🚀 GENERAR PDF GERENCIAL COMPLETO", use_container_width=True, type="primary", key="btn_generar_pdf_gerencial"):
                            with st.spinner("Dibujando secciones por técnico..."): st.session_state['pdf_gerencial'] = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                        if 'pdf_gerencial' in st.session_state: st.download_button(label="📥 Descargar Reporte PDF", data=st.session_state['pdf_gerencial'], file_name=f"Reporte_Gerencial_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_gerencial")
                    except Exception as e: st.error(f"❌ Ocurrió un error procesando el reporte: {e}")
        
        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor, key="fecha_archivar_diario")
            
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
                    # Solo entran órdenes con hora de inicio real (HORA_INI) en el día
                    # seleccionado. Una orden sin HORA_INI está apenas asignada, no trabajada.
                    mask_ini_dia = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == fecha_cal_sel
                    df_para_gantt_diario = df_base[mask_ini_dia].copy()
                    # Mismo motivo que en el Gantt en vivo: índice único para que las
                    # asignaciones por máscara del recorte de barras no se crucen.
                    df_para_gantt_diario = df_para_gantt_diario.reset_index(drop=True)
                    
                    if not df_para_gantt_diario.empty:
                        ahora_hx_d = get_honduras_time()
                        
                        df_para_gantt_diario['GANTT_START'] = df_para_gantt_diario['HORA_INI']
                        hora_cierre_proyectada = ahora_hx_d if fecha_cal_sel == ahora_hx_d.date() else datetime.combine(fecha_cal_sel, dt_time(22, 0))
                        
                        # Mismo criterio que en el Gantt en vivo: se confía en el ESTADO por
                        # encima de HORA_LIQ para decidir si sigue realmente abierta, ya que
                        # a veces queda un timestamp provisional en HORA_LIQ antes del cierre
                        # confirmado (ver comentario detallado en el bloque del Gantt en vivo).
                        mask_estado_vivo_d = df_para_gantt_diario['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                        mask_abierta_d = mask_estado_vivo_d

                        df_para_gantt_diario['GANTT_END'] = df_para_gantt_diario['HORA_LIQ']
                        df_para_gantt_diario.loc[mask_abierta_d, 'GANTT_END'] = hora_cierre_proyectada

                        # Cerrada (o estado no vivo) sin HORA_LIQ utilizable: bloque acotado,
                        # no se proyecta un cierre inventado.
                        mask_cierre_desc_d = df_para_gantt_diario['GANTT_END'].isna()
                        df_para_gantt_diario.loc[mask_cierre_desc_d, 'GANTT_END'] = df_para_gantt_diario.loc[mask_cierre_desc_d, 'GANTT_START'] + pd.Timedelta(minutes=30)

                        # Ninguna barra puede extenderse más allá del inicio de la siguiente
                        # orden del mismo técnico: así se conservan los huecos reales entre
                        # una orden y la siguiente, y nada queda montado.
                        df_para_gantt_diario = df_para_gantt_diario.sort_values(by=['TECNICO', 'GANTT_START'])
                        siguiente_inicio_d = df_para_gantt_diario.groupby('TECNICO')['GANTT_START'].shift(-1)

                        mask_invade_d = siguiente_inicio_d.notna() & (df_para_gantt_diario['GANTT_END'] > siguiente_inicio_d) & (siguiente_inicio_d > df_para_gantt_diario['GANTT_START'])
                        df_para_gantt_diario.loc[mask_invade_d, 'GANTT_END'] = siguiente_inicio_d[mask_invade_d]

                        ancho_min_barra_d = pd.Timedelta(minutes=10)
                        fin_objetivo_d = df_para_gantt_diario['GANTT_START'] + ancho_min_barra_d
                        tope_permitido_d = siguiente_inicio_d.where(siguiente_inicio_d > df_para_gantt_diario['GANTT_START'], fin_objetivo_d).fillna(fin_objetivo_d)
                        fin_ajustado_d = pd.concat([fin_objetivo_d, tope_permitido_d], axis=1).min(axis=1)

                        mask_barra_corta_d = (df_para_gantt_diario['GANTT_END'] - df_para_gantt_diario['GANTT_START']) < ancho_min_barra_d
                        df_para_gantt_diario.loc[mask_barra_corta_d, 'GANTT_END'] = fin_ajustado_d[mask_barra_corta_d]

                        mask_inv = df_para_gantt_diario['GANTT_END'] < df_para_gantt_diario['GANTT_START']
                        df_para_gantt_diario.loc[mask_inv, 'GANTT_END'] = df_para_gantt_diario.loc[mask_inv, 'GANTT_START'] + ancho_min_barra_d
                        
                        df_para_gantt_diario['Inicio'] = df_para_gantt_diario['HORA_INI'].dt.strftime('%H:%M')
                        df_para_gantt_diario['Cierre'] = df_para_gantt_diario['HORA_LIQ'].apply(
                            lambda x: x.strftime('%H:%M') if pd.notnull(x) else "En curso (Abierta)"
                        )
                        
                        df_para_gantt_diario['TECNICO'] = df_para_gantt_diario['TECNICO'].apply(normalizar_nombre_cruce)
                        df_para_gantt_diario = df_para_gantt_diario.dropna(subset=['GANTT_START', 'GANTT_END']).sort_values(by=['TECNICO', 'GANTT_START'])

                        actividades_permitidas = ACTIVIDADES_GANTT_PERMITIDAS
                        
                        df_para_gantt_diario = df_para_gantt_diario[
                            df_para_gantt_diario['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_permitidas)
                        ]

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
                                    
                                    # Cálculo dinámico de la duración total del almuerzo
                                    duracion_alm_m_h = int((hf_alm_h - hi_alm_h).total_seconds() / 60)
                                    h_h, m_h = divmod(duracion_alm_m_h, 60)
                                    tiempo_real_alm_h = f"{h_h}h {m_h}m" if h_h > 0 else f"{m_h}m"
                                    
                                    filas_almuerzo_h.append({
                                        'TECNICO': tec_alm_h,
                                        'ACTIVIDAD': 'ALMUERZO',
                                        'NUM': '-',
                                        'CLIENTE': '-',
                                        'COLONIA': '-',
                                        'ESTADO': 'ALMUERZO',
                                        'GANTT_START': hi_alm_h,
                                        'GANTT_END': hf_alm_h,
                                        'Inicio': hi_alm_h.strftime('%H:%M'),
                                        'Cierre': hf_alm_h.strftime('%H:%M'),
                                        'TIEMPO_REAL': tiempo_real_alm_h
                                    })
                                except Exception:
                                    continue
                            if filas_almuerzo_h:
                                df_para_gantt_diario = pd.concat([df_para_gantt_diario, pd.DataFrame(filas_almuerzo_h)], ignore_index=True)
                                df_para_gantt_diario = df_para_gantt_diario.sort_values(by=['TECNICO', 'GANTT_START'])
                        
                        cli_series_d = df_para_gantt_diario['CLIENTE'].fillna('-').astype(str) if 'CLIENTE' in df_para_gantt_diario.columns else pd.Series(['-'] * len(df_para_gantt_diario), index=df_para_gantt_diario.index).astype(str)
                        
                        df_para_gantt_diario['INFO_HOVER'] = (
                            "ACTIVIDAD=" + df_para_gantt_diario['ACTIVIDAD'].astype(str) + "<br>" +
                            "NUM=" + df_para_gantt_diario['NUM'].astype(str) + "<br>" +
                            "CLIENTE=" + cli_series_d + "<br>" +
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
         
