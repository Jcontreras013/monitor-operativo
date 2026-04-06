import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime, timedelta
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt

# NUEVA IMPORTACIÓN PARA DETECTAR EL TELÉFONO
from streamlit_js_eval import streamlit_js_eval

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

# ---> AQUÍ HICIMOS LA CONEXIÓN CON TU NUEVO MÓDULO DE AUDITORÍA <---
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
        generar_pdf_mensual
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

# --- LISTA MAESTRA DE ESTADOS ACTIVOS (Para no perder órdenes iniciadas) ---
PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

# ==============================================================================
# FUNCIÓN COMPARTIDA DE SINCRONIZACIÓN (MODO ESPEJO BLINDADO)
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("Descargando y aplicando formato espejo estricto..."):
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

                for col_f in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                    if col_f in df_nube.columns:
                        test_parse = pd.to_datetime(df_nube[col_f], dayfirst=True, errors='coerce')
                        if (test_parse.dt.year <= 1970).any() or (test_parse.dt.year == 1899).any():
                            nums = pd.to_numeric(df_nube[col_f], errors='coerce')
                            df_nube[col_f] = pd.to_datetime(nums, unit='D', origin='1899-12-30')
                        else:
                            df_nube[col_f] = test_parse
                
                for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
                    if col_b in df_nube.columns:
                        df_nube[col_b] = df_nube[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])

                # --- GUILLOTINA ANTI-FALSOS CRÍTICOS EN LA NUBE ---
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
                        
                if 'DIAS_RETRASO' in df_nube.columns:
                    df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
                    
                if 'MINUTOS_CALC' in df_nube.columns:
                    df_nube['MINUTOS_CALC'] = pd.to_numeric(df_nube['MINUTOS_CALC'], errors='coerce').fillna(0.0)

                if 'ESTADO' in df_nube.columns:
                    df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                # --- ESCUDO PARA NO BORRAR ÓRDENES PASADAS QUE SIGUEN ASIGNADAS ---
                ahora_momento_ts = pd.Timestamp(datetime.utcnow() - timedelta(hours=6))
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
                st.success("✅ Sincronización Exitosa: Columnas Fijadas y Críticos Depurados.")
                st.rerun()
            else:
                st.warning("La base de datos en la nube está vacía. Debes subir un archivo primero.")
    except Exception as e:
        st.error(f"Error al conectar con la nube: {e}")

# ==============================================================================
# 2. VENTANA EMERGENTE (DIÁLOGOS DE GESTIÓN DETALLADA)
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

# ==============================================================================
# 3. LÓGICA DE ESTILOS VISUALES 
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
        'DIAS_RETRASO', 'NUM', 'ACTIVIDAD', 'MOTIVO', 'CLIENTE', 'NOMBRE', 'COLONIA', 
        'TECNICO', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL', 
        'ESTADO', 'COMENTARIO', 'ES_OFFLINE', 'MINUTOS_CALC'
    ]
    columnas_finales = [c for c in cols_a_mostrar if c in df_visual_procesado.columns]
    return df_visual_procesado[columnas_finales], row_styler_logic

# ==============================================================================
# 4. FUNCIÓN MAESTRA DE CARGA Y DEPURACIÓN LOCAL
# ==============================================================================
@st.cache_data(show_spinner="Depurando datos al estilo Macro de Excel...", ttl=60)
def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos)
        
        for col_f in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
            if col_f in df_act.columns:
                df_act[col_f] = pd.to_datetime(df_act[col_f], dayfirst=True, errors='coerce')
        
        ahora_momento = datetime.utcnow() - timedelta(hours=6)
        ahora_momento_ts = pd.Timestamp(ahora_momento)
        fecha_limite_7d_ventana = ahora_momento_ts - timedelta(days=7) 
        
        # --- ESCUDO PARA NO BORRAR ÓRDENES PASADAS QUE SIGUEN ASIGNADAS LOCALMENTE ---
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
            if 'PLEX' in texto_p_scan: return 'PLEX'
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
# 5. INTERFAZ PRINCIPAL (MAIN)
# ==============================================================================
def main():
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    
    ancho_pantalla = streamlit_js_eval(js_expressions='window.innerWidth', key='WIDTH_CHECK', want_output=True)
    es_movil = (ancho_pantalla is not None) and (ancho_pantalla < 800)

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

    # ==============================================================================
    # 🎯 PANTALLA DE INICIO DINÁMICA
    # ==============================================================================
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
                    with st.spinner("☁️ Sincronizando datos con la nube para el equipo..."):
                        try:
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=res_p_diamante)
                            st.success("✅ Datos sincronizados y guardados en la nube correctamente.")
                        except Exception as e:
                            st.warning(f"Se procesó localmente, pero falló la sincronización con la nube: {e}")
                else:
                    st.success("✅ Datos procesados localmente.")
            else:
                return

    df_base = st.session_state.df_base.copy()
    
    # -------------------------------------------------------------
    # 🛡️ BLINDAJE GLOBAL EN MEMORIA Y CLASIFICACIÓN DE MOTIVO
    # -------------------------------------------------------------
    if 'SUSCRIPTOR' in df_base.columns and 'NOMBRE' not in df_base.columns:
        df_base.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
    elif 'NOMBRE CLIENTE' in df_base.columns and 'NOMBRE' not in df_base.columns:
        df_base.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)

    for col_f in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
        if col_f in df_base.columns:
            test_parse = pd.to_datetime(df_base[col_f], dayfirst=True, errors='coerce')
            if (test_parse.dt.year == 1970).any() or (test_parse.dt.year == 1899).any():
                nums = pd.to_numeric(df_base[col_f], errors='coerce')
                df_base[col_f] = pd.to_datetime(nums, unit='D', origin='1899-12-30')
            else:
                df_base[col_f] = test_parse
            
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
            
        # --- CREACIÓN DE COLUMNA 'MOTIVO' PARA EL FILTRO ---
        def extraer_motivo_falla(row):
            act = str(row.get('ACTIVIDAD', '')).upper()
            com = str(row.get('COMENTARIO', '')).upper()
            texto = act + " " + com
            
            if row.get('ES_OFFLINE', False) == True: return "🔴 Offline / Caída"
            if re.search("TV|CABLE|SEÑAL", texto): return "📺 Falla de TV"
            if re.search("NIVEL|DB|POTENCIA|ATENU", texto): return "⚡ Niveles Alterados"
            if re.search("NAV|INTERNET|LENT", texto): return "🌐 Lentitud / Navegación"
            if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", texto): return "📦 Instalación / Cambio"
            return "🔧 Mantenimiento General"
            
        df_base['MOTIVO'] = df_base.apply(extraer_motivo_falla, axis=1)

    for col_n in ['DIAS_RETRASO', 'MINUTOS_CALC']:
        if col_n in df_base.columns:
            df_base[col_n] = pd.to_numeric(df_base[col_n], errors='coerce').fillna(0)
            
    for col_txt in ['NUM', 'CLIENTE']:
        if col_txt in df_base.columns:
            df_base[col_txt] = pd.to_numeric(df_base[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
            df_base[col_txt] = df_base[col_txt].replace('0', 'N/D')
    # -------------------------------------------------------------
    
    ahora_local = datetime.utcnow() - timedelta(hours=6)
    hoy_date_valor = ahora_local.date()

    # --- 2. MENÚ SUPERIOR Y MULTIFILTROS LATERALES ---
    with sidebar_top:
        if rol_usuario in ['admin', 'jefe']:
            # ---> SE AGREGÓ LA NUEVA PESTAÑA "🚙 Auditoría Vehículos" <---
            nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "📚 Histórico", "🚫 NOINSTALADO", "📅 REPROGRAMADAS", "🚙 Auditoría Vehículos"])
        else:
            nav_menu_diamante = "⚡ Monitor en Vivo"
            
        df_base_activa = df_base[df_base['DIAS_RETRASO'] >= 0].copy()
        
        # INICIALIZAR VARIABLES DE FILTRO VACÍAS
        filtro_actividad = []
        filtro_estado = []
        filtro_motivo = []
        
        # DIBUJAR LOS MULTIFILTROS SOLO SI ESTAMOS EN EL MONITOR
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
            
            # --- APLICAR MULTIFILTROS LATERALES ---
            if len(filtro_actividad) > 0:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
                
            if len(filtro_estado) > 0:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
                
            if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
            
            # --- APLICAR FILTROS PRINCIPALES ---
            if check_criticos_diamante:
                mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado['ALERTA_TIEMPO']
                mask_sop_fibra = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('SOP|FIBRA', na=False)
                mask_falsos = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
                
                df_monitor_filtrado = df_monitor_filtrado[mask_critica & mask_sop_fibra & ~mask_falsos]
                
            if tec_filtro_monitor != "Todos":
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro_monitor]
        else:
            df_monitor_filtrado = df_base_activa.copy()

    # ==============================================================================
    # PANTALLA: AUDITORÍA DE VEHÍCULOS (LLAMANDO A LA FUNCIÓN EXTERNA)
    # ==============================================================================
    if nav_menu_diamante == "🚙 Auditoría Vehículos":
        # Se manda a llamar la función pasándole la variable es_movil
        try:
            mostrar_auditoria(es_movil)
        except Exception as e:
            st.error(f"Ocurrió un error al cargar el módulo de Auditoría: {e}")
        return

    # ==============================================================================
    # PANTALLA EXISTENTES (NO INSTALADO, REPROGRAMADAS, HISTÓRICO)
    # ==============================================================================
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

    # ==============================================================================
    # PANTALLA: CENTRO DE REPORTES
    # ==============================================================================
    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        
        tab_dinamico, tab_diario, tab_semanal, tab_mensual = st.tabs([
            "⚡ Reporte Dinámico", "📦 Cierre Diario", "🗓️ Analítico Semanal", "🏢 Macro Mensual"
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

        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor)
            df_cierre_filtrado = df_base[(df_base['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()
            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cierre_filtrado))
            
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
                    df_plex = df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('PLEX', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_plex, hide_index=True, use_container_width=True)
                    st.write(f"**Total PLEX: {df_plex['Cant'].sum()}**")
                    
                with co_col:
                    st.write("**Otros**")
                    txt_otr_c = df_cierre_filtrado['ACTIVIDAD'].astype(str).str.upper() + " " + df_cierre_filtrado['COMENTARIO'].astype(str).str.upper()
                    mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_otros = df_cierre_filtrado[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_otros, hide_index=True, use_container_width=True)
                    st.write(f"**Total Otros: {df_otros['Cant'].sum()}**")

            st.divider()
            
            st.markdown("### 📈 Resumen Consolidado por Actividad")
            if not df_cierre_filtrado.empty:
                df_resumen_act = df_cierre_filtrado['ACTIVIDAD'].value_counts().reset_index()
                df_resumen_act.columns = ['Actividad Realizada', 'Total de Órdenes']
                st.dataframe(df_resumen_act, hide_index=True, use_container_width=True)

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
    
    mask_hoy = df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor
    mask_asignadas = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)

    df_monitor_vivas_full = df_monitor_filtrado[mask_hoy | mask_asignadas].copy()
    df_tablero_kpi_monitor = df_monitor_filtrado[mask_asignadas].copy()

    df_tablero_kpi_monitor['DIAS_RETRASO'] = (pd.Timestamp(ahora_local).normalize() - df_tablero_kpi_monitor['FECHA_APE'].dt.normalize()).dt.days
    df_tablero_kpi_monitor['DIAS_RETRASO'] = df_tablero_kpi_monitor['DIAS_RETRASO'].fillna(0).astype(int)
    
    if 'TECNICO' in df_tablero_kpi_monitor.columns:
        mask_josue_kpi = df_tablero_kpi_monitor['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
        df_tablero_kpi_monitor.loc[mask_josue_kpi, 'DIAS_RETRASO'] = 0

    df_tablero_kpi_monitor['CatD'] = df_tablero_kpi_monitor['DIAS_RETRASO'].apply(
        lambda d: ">= 7 Dia" if d >= 7 else (f"= {int(d)} Dia" if d > 0 else "= 0 Dia")
    )

    st.title("⚡ Monitor Operativo Maxcom")

    with st.expander("📊 TABLERO DE CARGA ACTUAL (SOLO ÓRDENES ASIGNADAS)", expanded=True):
        col_tab_1, col_tab_2, col_tab_3, col_tab_4 = st.columns([1, 1.2, 1.2, 1])
        with col_tab_1:
            st.caption("📅 Resumen de Retraso")
            res_retraso_v = df_tablero_kpi_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 Dia","= 1 Dia","= 0 Dia"], fill_value=0).reset_index()
            res_retraso_v.columns = ['Dias', 'Cant']
            sum_total_pendientes_v = res_retraso_v['Cant'].sum()
            res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_pendientes_v*100):.0f}%" if sum_total_pendientes_v > 0 else "0%")
            st.dataframe(res_retraso_v, hide_index=True, use_container_width=True)
            
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

    with st.expander("📊 CONSOLIDADO POR SEGMENTO (SOLO ASIGNADAS)", expanded=False):
        res_segmentos_monitor = df_tablero_kpi_monitor.groupby(['TECNICO', 'SEGMENTO']).size().reset_index(name='Cant')
        col_plex_m, col_resi_m = st.columns(2)
        with col_plex_m:
            st.write("🏢 PLEX ASIGNADOS")
            st.dataframe(res_segmentos_monitor[res_segmentos_monitor['SEGMENTO']=='PLEX'][['TECNICO','Cant']], hide_index=True, use_container_width=True)
        with col_resi_m:
            st.write("🏠 RESIDENCIAL ASIGNADOS")
            st.dataframe(res_segmentos_monitor[res_segmentos_monitor['SEGMENTO']=='RESIDENCIAL'][['TECNICO','Cant']], hide_index=True, use_container_width=True)

    with st.expander("📋 CONSOLIDADO GENERAL DE OPERACIONES", expanded=False):
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.info("Distribución de Órdenes por Técnico (Total en Vista)")
            st.dataframe(df_monitor_vivas_full.groupby('TECNICO')['NUM'].count().reset_index(name='Órdenes').sort_values(by='Órdenes', ascending=False), use_container_width=True, hide_index=True)
        with col_c2:
            st.info("Distribución por Tipo de Actividad (Total en Vista)")
            st.dataframe(df_monitor_vivas_full['ACTIVIDAD'].value_counts().reset_index(name='Total'), use_container_width=True, hide_index=True)

    st.divider()
    
    if 'st_btn_v_active' not in st.session_state or st.session_state.st_btn_v_active == "CONSOL": 
        st.session_state.st_btn_v_active = "PENDIENTE"
        
    col_bt1_v, col_bt2_v, col_bt3_v = st.columns(3)
    
    if col_bt1_v.button("⏳ ACTIVAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary"): 
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

    met_v1, met_v2, met_v3 = st.columns(3)
    met_v1.metric("🏢 PLEX", len(df_v_tabla_monitor[df_v_tabla_monitor['SEGMENTO'] == 'PLEX']))
    met_v2.metric("🏠 RESIDENCIAL", len(df_v_tabla_monitor[df_v_tabla_monitor['SEGMENTO'] == 'RESIDENCIAL']))
    met_v3.metric("📋 TOTAL EN VISTA", len(df_v_tabla_monitor))

    t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL DE CONTROL OPERATIVO", "📊 ANALISIS Y GANTT", "📈 ANALÍTICA"])
    
    with t_panel_v:
        if not df_v_tabla_monitor.empty:
            df_estilo_v, row_styler_final_v = aplicar_estilos_df(df_v_tabla_monitor)
            evento_monitor_diam = st.dataframe(
                df_estilo_v.style.apply(row_styler_final_v, axis=1).hide(axis=1, subset=['ES_OFFLINE']), 
                column_config={"GPS": st.column_config.LinkColumn("UBICACIÓN GPS")}, 
                use_container_width=True, height=600, hide_index=True, on_select="rerun", selection_mode="single-row"
            )
            if evento_monitor_diam.selection.rows:
                mostrar_comentario_cierre(df_v_tabla_monitor.iloc[evento_monitor_diam.selection.rows[0]])
        else:
            st.warning("No hay registros disponibles para mostrar.")

    with t_graphs_v:
        df_para_gantt_final = df_v_tabla_monitor[df_v_tabla_monitor['HORA_INI'].notnull()].copy()
        if not df_para_gantt_final.empty:
            df_para_gantt_final['FIN_LIMITE'] = df_para_gantt_final['HORA_LIQ'].fillna(datetime.now())
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
    if not st.session_state['autenticado']:
        mostrar_pantalla_login()
    else:
        main()
        mostrar_boton_logout()
