import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime, timedelta
import re
from streamlit_gsheets import GSheetsConnection

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

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

# ==============================================================================
# 3. LÓGICA DE ESTILOS VISUALES 
# ==============================================================================
def aplicar_estilos_df(df_original_para_estilo):
    df_visual_procesado = df_original_para_estilo.copy()
    
    def row_styler_logic(fila_v):
        estilos_fila = [''] * len(fila_v)
        
        if fila_v.get('ES_OFFLINE') == True:
            if 'NUM' in fila_v.index:
                idx_n = fila_v.index.get_loc('NUM')
                estilos_fila[idx_n] = 'background-color: #9b111e; color: white; font-weight: bold'
        
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
                idx_ini = fila_v.index.get_loc('HORA_INI')
                estilos_fila[idx_ini] = 'background-color: #ff5722; color: white; font-weight: bold'
        
        if 'DIAS_RETRASO' in fila_v.index:
            idx_dias = fila_v.index.get_loc('DIAS_RETRASO')
            val_dias = fila_v['DIAS_RETRASO']
            
            if val_dias >= 7: estilos_fila[idx_dias] = 'background-color: #d32f2f; color: white' 
            elif val_dias >= 4 and val_dias <= 6: estilos_fila[idx_dias] = 'background-color: #ef6c00; color: white' 
            elif val_dias >= 1 and val_dias <= 3: estilos_fila[idx_dias] = 'background-color: #fdd835; color: black' 
            elif val_dias == 0: estilos_fila[idx_dias] = 'background-color: #4caf50; color: white' 
                
        return estilos_fila

    if 'NUM' in df_visual_procesado.columns:
        df_visual_procesado['NUM'] = df_visual_procesado.apply(
            lambda r: f"⚠️ {r['NUM']}" if r.get('ALERTA_TIEMPO') else r['NUM'], axis=1
        )
    if 'HORA_INI' in df_visual_procesado.columns:
        df_visual_procesado['HORA_INI'] = pd.to_datetime(df_visual_procesado['HORA_INI'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    if 'HORA_LIQ' in df_visual_procesado.columns:
        df_visual_procesado['HORA_LIQ'] = pd.to_datetime(df_visual_procesado['HORA_LIQ'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    
    cols_a_mostrar = [
        'DIAS_RETRASO', 'NUM', 'ACTIVIDAD', 'CLIENTE', 'NOMBRE', 'NOMBRE_CLIENTE', 'NOMBRE CLIENTE', 'SUSCRIPTOR', 'NOMBRE_SUSCRIPTOR', 'COLONIA', 
        'TECNICO', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL', 
        'ESTADO', 'COMENTARIO', 'ES_OFFLINE', 'MINUTOS_CALC'
    ]
    
    columnas_finales = [c for c in cols_a_mostrar if c in df_visual_procesado.columns]
    
    return df_visual_procesado[columnas_finales], row_styler_logic

# ==============================================================================
# 4. FUNCIÓN MAESTRA DE CARGA Y DEPURACIÓN
# ==============================================================================
@st.cache_data(show_spinner="Depurando datos al estilo Macro de Excel...", ttl=60)
def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos)
        
        columnas_fechas_depuracion = ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']
        for col_f in columnas_fechas_depuracion:
            if col_f in df_act.columns:
                df_act[col_f] = pd.to_datetime(df_act[col_f], dayfirst=True, errors='coerce')
        
        ahora_momento = pd.Timestamp(datetime.now())
        fecha_limite_7d_ventana = ahora_momento - timedelta(days=7) 
        
        df_act = df_act[
            (df_act['HORA_LIQ'] >= fecha_limite_7d_ventana) | 
            (df_act['FECHA_APE'] >= fecha_limite_7d_ventana) | 
            (df_act['HORA_LIQ'].isna())
        ].copy()
        
        df_act['DIAS_RETRASO'] = (ahora_momento.normalize() - df_act['FECHA_APE'].dt.normalize()).dt.days.fillna(0).clip(lower=0).astype(int)
        df_act.loc[df_act['TECNICO'].str.strip().str.upper() == 'JOSUE MIGUEL SAUCEDA', 'DIAS_RETRASO'] = 0
        
        def alert_2h_logic_diamante(row_check):
            if pd.notnull(row_check['HORA_INI']) and pd.isnull(row_check['HORA_LIQ']):
                m_diff_val = (ahora_momento - row_check['HORA_INI']).total_seconds() / 60
                if m_diff_val > 120 and str(row_check.get('ESTADO','')).upper().strip() != 'CERRADA':
                    return True
            return False
        df_act['ALERTA_TIEMPO'] = df_act.apply(alert_2h_logic_diamante, axis=1)
        
        def offline_seguro_diamante_logic(r_off):
            if str(r_off.get('TECNICO', '')).strip().upper() == 'JOSUE MIGUEL SAUCEDA': return False
            if str(r_off.get('ESTADO','')).upper().strip() == 'CERRADA': return False
            act_v_name = str(r_off.get('ACTIVIDAD', '')).upper()
            if any(p in act_v_name for p in ['INS', 'NUEVA', 'ADIC', 'CAMBIO', 'RECU']): return False
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
    # --- CONEXIÓN A LA NUBE ---
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

        # --- BOTÓN PARA JEFES: Cargar desde la nube ---
        st.markdown("### ☁️ Sincronización")
        if st.button("📥 ACTUALIZAR DESDE LA NUBE", help="Trae los últimos datos de la oficina", use_container_width=True):
            if conn is not None:
                try:
                    df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1")
                    if not df_nube.empty:
                        # 💎 FILTRO DE SEGURIDAD AL DESCARGAR:
                        # Convertimos las columnas de fecha para que el filtro funcione
                        df_nube['HORA_LIQ'] = pd.to_datetime(df_nube['HORA_LIQ'], errors='coerce')
                        df_nube['FECHA_APE'] = pd.to_datetime(df_nube['FECHA_APE'], errors='coerce')
                        
                        # Guardamos en la sesión
                        st.session_state.df_base = df_nube
                        st.success("✅ Datos sincronizados. Aplicando filtros de hoy...")
                        st.rerun()
                    else:
                        st.warning("La base de datos en la nube está vacía. Jaison debe subir un archivo primero.")
                except Exception as e:
                    st.error(f"Error al conectar con la nube: {e}")
            else:
                st.error("La conexión a la nube no está disponible.")
        
        st.divider()

        st.markdown("### 📥 Archivos Crudos")
        archivos_uploader_diamante = st.file_uploader(
            "Sube rep_actividades y FttxActiveDevice", 
            type=["xlsx", "csv"], 
            accept_multiple_files=True
        )
        
        file_act_ptr = None
        file_disp_ptr = None
        
        if archivos_uploader_diamante:
            for file_item in archivos_uploader_diamante:
                f_name_lwr = file_item.name.lower()
                if "actividades" in f_name_lwr: file_act_ptr = file_item
                elif "device" in f_name_lwr or "dispositivos" in f_name_lwr: file_disp_ptr = file_item

        btn_reprocesar = st.button("🔄 ACTUALIZAR TODO", use_container_width=True)

    if 'df_base' not in st.session_state or btn_reprocesar:
        if file_act_ptr is None or file_disp_ptr is None:
            st.title("⚡ Monitor Operativo Maxcom PRO")
            st.info("💡 Consejo: Usa 'ACTUALIZAR DESDE LA NUBE' en el menú izquierdo si estás fuera de la oficina, o sube los archivos crudos para guardar una nueva copia en la nube.")
            st.warning("⚠️ Para modo editor: Sube 'Actividades' y 'Dispositivos'.")
            return
        
        res_p_diamante, res_h_diamante = cargar_y_limpiar_crudos_diamante_monitor(file_act_ptr, file_disp_ptr)
        if res_p_diamante is not None:
            st.session_state.df_base = res_p_diamante
            st.session_state.df_hist = res_h_diamante
            
            # --- GUARDADO AUTOMÁTICO EN LA NUBE ---
            if conn is not None:
                with st.spinner("☁️ Sincronizando datos con la nube para el equipo..."):
                    try:
                        conn.update(
                            spreadsheet=st.secrets["url_base_datos"],
                            worksheet="Sheet1",
                            data=res_p_diamante
                        )
                        st.success("✅ Datos sincronizados y guardados en la nube correctamente.")
                    except Exception as e:
                        st.warning(f"Se procesó localmente, pero falló la sincronización con la nube: {e}")
            else:
                st.success("✅ Datos procesados localmente.")
        else:
            return

    df_base = st.session_state.df_base.copy()
    
    # -------------------------------------------------------------
    # 🛡️ BLINDAJE DE DATOS (REGLA DE DIAMANTE CONTRA GOOGLE SHEETS)
    # -------------------------------------------------------------
    # 1. Asegurar que las fechas regresen como Fechas (no como texto)
    for col_f in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
        if col_f in df_base.columns:
            df_base[col_f] = pd.to_datetime(df_base[col_f], errors='coerce')
            
    # 2. Asegurar que los estados lógicos regresen como Verdadero/Falso matemáticos
    for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
        if col_b in df_base.columns:
            df_base[col_b] = df_base[col_b].astype(str).str.upper() == 'TRUE'
            
    # 3. Asegurar que los números regresen como valores calculables
    for col_n in ['DIAS_RETRASO', 'MINUTOS_CALC']:
        if col_n in df_base.columns:
            df_base[col_n] = pd.to_numeric(df_base[col_n], errors='coerce').fillna(0)
    # -------------------------------------------------------------
    hoy_date_valor = datetime.now().date()
    patron_asignadas_viva_str = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO'

    # --- 2. MENÚ SUPERIOR CON RESTRICCIÓN RADICAL DE ROLES ---
    with sidebar_top:
        rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
        
        if rol_usuario in ['admin', 'jefe']:
            nav_menu_diamante = st.radio("MENÚ DE CONTROL:", ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "📚 Histórico", "🚫 NOINSTALADO"])
        else:
            nav_menu_diamante = "⚡ Monitor en Vivo"
        
        if nav_menu_diamante == "⚡ Monitor en Vivo":
            if rol_usuario in ['admin', 'jefe']:
                st.divider() 
                
            st.header("🔍 Filtros en Vivo")
            m_viva_count = df_base['ESTADO'].astype(str).str.contains(patron_asignadas_viva_str, na=False, case=False)
            total_off_count_viva = int((df_base['ES_OFFLINE'] & m_viva_count).sum())
            
            check_criticos_diamante = st.toggle(f"Ver solo Órdenes Críticas ({total_off_count_viva})")
            lista_tecs_monitor = ["Todos"] + sorted(df_base['TECNICO'].dropna().unique().tolist())
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor)
            
            df_monitor_filtrado = df_base.copy()
            if check_criticos_diamante:
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado['ALERTA_TIEMPO']]
            if tec_filtro_monitor != "Todos":
                df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro_monitor]
        else:
            df_monitor_filtrado = df_base

    # ==============================================================================
    # RUTAS SECUNDARIAS
    # ==============================================================================
    if nav_menu_diamante == "🚫 NOINSTALADO":
        st.title("🚫 Órdenes NOINSTALADO (Cerradas Hoy)")
        mask_noinst_hoy = (df_base['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)) & (df_base['HORA_LIQ'].dt.date == hoy_date_valor)
        st.dataframe(df_base[mask_noinst_hoy][['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']], use_container_width=True, hide_index=True)
        return

    if nav_menu_diamante == "📚 Histórico":
        from historico import main_historico
        main_historico(st.session_state.df_hist)
        return

    # ==============================================================================
    # CENTRO ÚNICO DE REPORTES
    # ==============================================================================
    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        
        tab_dinamico, tab_diario, tab_semanal, tab_mensual = st.tabs([
            "⚡ Reporte Dinámico", 
            "📦 Cierre Diario", 
            "🗓️ Analítico Semanal", 
            "🏢 Macro Mensual"
        ])

        with tab_dinamico:
            st.subheader("📄 Reporte Dinámico en Vivo")
            col_f1, col_f2 = st.columns(2)
            m_viva_rep = df_base['ESTADO'].astype(str).str.contains(patron_asignadas_viva_str, na=False, case=False)
            total_off_rep = int((df_base['ES_OFFLINE'] & m_viva_rep).sum())
            
            with col_f1: check_criticos_rep = st.toggle(f"Filtrar solo Críticas ({total_off_rep})", key="tgg_rep")
            with col_f2: tec_filtro_rep = st.selectbox("Filtrar por Técnico:", ["Todos"] + sorted(df_base['TECNICO'].dropna().unique().tolist()), key="sel_tec_rep")
                
            df_dinamico_filtrado = df_base.copy()
            if check_criticos_rep: df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['ES_OFFLINE'] | df_dinamico_filtrado['ALERTA_TIEMPO']]
            if tec_filtro_rep != "Todos": df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['TECNICO'] == tec_filtro_rep]
                
            if st.button("📄 GENERAR REPORTE DINÁMICO (PDF)", use_container_width=True, type="primary"):
                pdf_bytes_rendimiento = logica_generar_pdf(df_dinamico_filtrado)
                st.download_button("📥 Descargar PDF Dinámico", data=pdf_bytes_rendimiento, file_name=f"Reporte_Dinamico_{hoy_date_valor}.pdf")

        # --- PESTAÑA CIERRE DIARIO ---
        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor)
            df_cierre_filtrado = df_base[(df_base['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()
            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cierre_filtrado))
            
            if not df_cierre_filtrado.empty:
                st.markdown("### 📊 Desglose de Producción por Categoría")
                cs_col, ci_col, cp_col, co_col = st.columns(4)
                with cs_col:
                    st.write("**SOP**"); st.dataframe(df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant'), hide_index=True)
                with ci_col:
                    st.write("**Instalaciones**"); st.dataframe(df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('INS|NUEVA|ADIC|CAMBIO', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant'), hide_index=True)
                with cp_col:
                    st.write("**Plex**"); st.dataframe(df_cierre_filtrado[df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('PLEX', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant'), hide_index=True)
                with co_col:
                    st.write("**Otros**"); st.dataframe(df_cierre_filtrado[~(df_cierre_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|MANT|INS|PLEX|NUEVA|ADIC', na=False, case=False))]['ACTIVIDAD'].value_counts().reset_index(name='Cant'), hide_index=True)

            st.divider()
            
            st.markdown("### 📈 Resumen Consolidado por Actividad")
            if not df_cierre_filtrado.empty:
                df_resumen_act = df_cierre_filtrado['ACTIVIDAD'].value_counts().reset_index()
                df_resumen_act.columns = ['Actividad Realizada', 'Total de Órdenes']
                st.dataframe(df_resumen_act, hide_index=True, use_container_width=True)

            st.markdown("### ⏱️ Tiempos de Atención Promedio por Colaborador y Actividad")
            if not df_cierre_filtrado.empty:
                df_pivot_diario = df_cierre_filtrado.groupby(['TECNICO', 'ACTIVIDAD']).agg(
                    Órdenes=('NUM', 'count'),
                    Prom_Duracion_Min=('MINUTOS_CALC', 'mean')
                ).round(1)
                st.dataframe(df_pivot_diario, use_container_width=True)

            st.markdown("### 📥 Exportación de Consolidados")
            if st.button("🚀 GENERAR PDF DE CIERRE DIARIO (INCLUYE CONSOLIDADO GENERAL)", use_container_width=True, type="primary"):
                pdf_bytes_archivo_diario = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
                st.download_button("📥 Descargar Archivo (PDF)", data=pdf_bytes_archivo_diario, file_name=f"Cierre_{fecha_cal_sel}.pdf", key="dl_pdf_diario")
            
            st.divider()
            with st.expander("Ver Lista Detallada de Órdenes Liquidadas en Pantalla"):
                st.dataframe(df_cierre_filtrado[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)

        with tab_semanal:
            st.subheader("Rendimiento y Tiempos Semanales")
            rango_fecha = st.date_input("Rango de evaluación (Sugerido 7 días):", value=(hoy_date_valor - timedelta(days=7), hoy_date_valor), key="date_semanal")
            if len(rango_fecha) == 2:
                df_sem = df_base[(df_base['HORA_LIQ'].dt.date >= rango_fecha[0]) & (df_base['HORA_LIQ'].dt.date <= rango_fecha[1]) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))]
                
                st.markdown("#### 🏆 Cumplimiento de Meta (2400 min)")
                ranking_sem = df_sem.groupby('TECNICO')['MINUTOS_CALC'].sum().reset_index()
                ranking_sem.columns = ['Técnico', 'Minutos Totales']
                ranking_sem['% Meta (2400 min)'] = (ranking_sem['Minutos Totales'] / 2400 * 100).map("{:.1f}%".format)
                st.dataframe(ranking_sem.sort_values(by='Minutos Totales', ascending=False), use_container_width=True, hide_index=True)
                
                st.markdown("#### ⏱️ Desglose Promedio por Actividad")
                if not df_sem.empty:
                    df_pivot_sem = df_sem.groupby(['TECNICO', 'ACTIVIDAD']).agg(
                        Órdenes=('NUM', 'count'),
                        Prom_Duracion_Min=('MINUTOS_CALC', 'mean')
                    ).round(1)
                    st.dataframe(df_pivot_sem, use_container_width=True)

                if st.button("🚀 GENERAR PDF SEMANAL", use_container_width=True, type="primary"):
                    pdf_sem_bytes = generar_pdf_semanal(df_base, rango_fecha[0], rango_fecha[1])
                    st.download_button("📥 Descargar PDF Semanal", data=pdf_sem_bytes, file_name=f"Semanal_{rango_fecha[0]}_al_{rango_fecha[1]}.pdf")

        with tab_mensual:
            st.subheader("Visión Macro Gerencial")
            col_mes, col_anio = st.columns(2)
            meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            with col_mes: mes_sel = st.selectbox("Mes:", meses, index=hoy_date_valor.month - 1)
            with col_anio: anio_sel = st.number_input("Año:", min_value=2024, max_value=2030, value=2026)
            
            st.markdown("### 🏢 Comparativa Segmento: Plex vs Residencial")
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
        mask_asignadas = df_monitor_filtrado['ESTADO'].astype(str).str.contains(patron_asignadas_viva_str, na=False, case=False)

        df_monitor_vivas_full = df_monitor_filtrado[mask_hoy | mask_asignadas].copy()
        df_tablero_kpi_monitor = df_monitor_filtrado[mask_asignadas].copy()

    st.title("⚡ Monitor Operativo Maxcom")

    with st.expander("📊 TABLERO DE CARGA ACTUAL (SOLO ÓRDENES ASIGNADAS)", expanded=True):
        col_tab_1, col_tab_2, col_tab_3, col_tab_4 = st.columns([1, 1.2, 1.2, 1])
        with col_tab_1:
            st.caption("📅 Resumen de Retraso")
            df_tablero_kpi_monitor['CatD'] = df_tablero_kpi_monitor['DIAS_RETRASO'].apply(lambda d: ">= 7 Dia" if d>=7 else f"= {d} Dia")
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
                "ONT/ONU Offline": int(df_tablero_kpi_monitor['ES_OFFLINE'].sum()),
                "Niveles alterados": len(df_tablero_kpi_monitor[df_tablero_kpi_monitor['COMENTARIO'].astype(str).str.upper().str.contains("NIVEL|DB", na=False)]),
                "Sin señal de TV": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("TV|CABLE", na=False)])
            }
            st.dataframe(pd.DataFrame(list(res_sop_visual_v.items()), columns=['SOP', 'Cant']), hide_index=True, use_container_width=True)
            st.write(f"**Total General SOP: {sum(res_sop_visual_v.values())}**")
            st.metric("Exceden 2 Horas ⚠️", int(df_tablero_kpi_monitor['ALERTA_TIEMPO'].sum()))

        with col_tab_3:
            st.caption("📦 Instalaciones")
            res_ins_visual_v = {
                "Adición": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("ADIC", na=False)]),
                "Cambio de Medio": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("CAMBIO", na=False)]),
                "Nueva": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("NUEVA|INSFIBRA", na=False) & ~act_tab_sop.str.contains("ADIC|CAMBIO", na=False)]),
                "Recuperado": len(df_tablero_kpi_monitor[act_tab_sop.str.contains("RECUP", na=False)])
            }
            st.dataframe(pd.DataFrame(list(res_ins_visual_v.items()), columns=['Instalaciones', 'Cant']), hide_index=True, use_container_width=True)
            st.write(f"**Total General INS: {sum(res_ins_visual_v.values())}**")

        with col_tab_4:
            st.caption("⚙️ Otros")
            mask_otros_monitor = ~act_tab_sop.str.contains("SOP|FALLA|MANT|INS|ADIC|CAMBIO|NUEVA", na=False)
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

    t_panel_v, t_graphs_v = st.tabs(["📋 PANEL DE CONTROL OPERATIVO", "📊 ANALISIS Y GANTT"])
    
    with t_panel_v:
        if not df_v_tabla_monitor.empty:
            df_estilo_v, row_styler_final_v = aplicar_estilos_df(df_v_tabla_monitor)
            evento_monitor_diam = st.dataframe(
                df_estilo_v.style.apply(row_styler_final_v, axis=1).hide(axis=1, subset=['ES_OFFLINE']), 
                column_config={"GPS": st.column_config.LinkColumn("UBICACIÓN GPS")}, 
                use_container_width=True, height=550, hide_index=True, on_select="rerun", selection_mode="single-row"
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

# ==============================================================================
# 8. SISTEMA DE LOGIN Y ARRANQUE DE LA APLICACIÓN
# ==============================================================================
if __name__ == "__main__": 
    # 1. El sistema verifica si ya iniciaste sesión antes
    verificar_autenticacion()

    # 2. El Guardián decide qué mostrar:
    if not st.session_state['autenticado']:
        mostrar_pantalla_login()
    else:
        main()
        mostrar_boton_logout()
