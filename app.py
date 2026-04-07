import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime, timedelta
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt

# IMPORTACIÓN PARA DETECTAR EL TELÉFONO
from streamlit_js_eval import streamlit_js_eval

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'. Asegúrate de crearlo en la misma carpeta.")

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
        safestr
    )
except ImportError:
    st.error("⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'.")

# ==============================================================================
# 1. CONFIGURACIÓN INICIAL DE LA INTERFAZ Y ESTILOS
# ==============================================================================
st.set_page_config(layout="wide", page_title="Monitor Operativo Maxcom PRO", page_icon="⚡", initial_sidebar_state="expanded")
PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

# Estilo Global (Look Dashboard Gerencial)
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    .kpi-card {
        background-color: #1A1C24;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #2D2F39;
        text-align: center;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
        margin-bottom: 10px;
    }
    .kpi-label { color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; }
    .kpi-value { color: #FFFFFF; font-size: 2rem; font-weight: 700; margin: 0; }
    .kpi-value-green { color: #10B981; font-size: 2rem; font-weight: 700; margin: 0; }
    .kpi-value-red { color: #EF4444; font-size: 2rem; font-weight: 700; margin: 0; }
    div[data-testid="stExpander"] div[role="button"] p { font-weight: bold; color: #E2E8F0; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# FUNCIONES MATEMÁTICAS GERENCIALES
# ==============================================================================
def generar_tablas_gerenciales(df_limpio):
    df = df_limpio.copy()
    df['HORA_INI'] = pd.to_datetime(df['HORA_INI'], errors='coerce')
    df['HORA_LIQ'] = pd.to_datetime(df['HORA_LIQ'], errors='coerce')
    df = df.dropna(subset=['HORA_INI', 'HORA_LIQ'])
    df['FECHA'] = df['HORA_LIQ'].dt.date
    
    totales_tec = df.groupby('TECNICO').size().reset_index(name='Total_Tecnico')
    conteo_act = df.groupby(['TECNICO', 'ACTIVIDAD']).size().reset_index(name='Cantidad')
    tabla_produccion = pd.merge(conteo_act, totales_tec, on='TECNICO')
    tabla_produccion['Participacion_%'] = (tabla_produccion['Cantidad'] / tabla_produccion['Total_Tecnico'] * 100).round(1)

    df['MINUTOS'] = (df['HORA_LIQ'] - df['HORA_INI']).dt.total_seconds() / 60
    tabla_eficiencia = df.groupby(['TECNICO', 'ACTIVIDAD'])['MINUTOS'].mean().reset_index()
    tabla_eficiencia.columns = ['TECNICO', 'ACTIVIDAD', 'Promedio_Minutos']
    tabla_eficiencia['Promedio_Minutos'] = tabla_eficiencia['Promedio_Minutos'].round(1)

    jornada = df.groupby(['TECNICO', 'FECHA']).agg(
        Hora_Apertura=('HORA_INI', 'min'),
        Hora_Cierre=('HORA_LIQ', 'max'),
        Total_Ordenes=('NUM', 'count')
    ).reset_index()
    jornada['Horas_En_Calle'] = (jornada['Hora_Cierre'] - jornada['Hora_Apertura']).dt.total_seconds() / 3600
    resumen_jornada = jornada.groupby('TECNICO').agg(
        Promedio_Horas_Dia=('Horas_En_Calle', 'mean'),
        Dias_Laborados=('FECHA', 'nunique'),
        Max_Horas_Dia=('Horas_En_Calle', 'max')
    ).reset_index()
    resumen_jornada['Promedio_Horas_Dia'] = resumen_jornada['Promedio_Horas_Dia'].round(2)
    resumen_jornada['Max_Horas_Dia'] = resumen_jornada['Max_Horas_Dia'].round(2)

    return tabla_produccion, tabla_eficiencia, resumen_jornada

def calcular_metricas_escalonadas(df_limpio):
    df = df_limpio.copy()
    df['HORA_INI'] = pd.to_datetime(df['HORA_INI'], errors='coerce')
    df['HORA_LIQ'] = pd.to_datetime(df['HORA_LIQ'], errors='coerce')
    df = df.dropna(subset=['HORA_INI', 'HORA_LIQ'])

    df['FECHA'] = df['HORA_LIQ'].dt.date
    df['SEMANA'] = df['HORA_LIQ'].dt.isocalendar().year.astype(str) + '-W' + df['HORA_LIQ'].dt.isocalendar().week.astype(str).str.zfill(2)
    df['MES'] = df['HORA_LIQ'].dt.year.astype(str) + '-' + df['HORA_LIQ'].dt.month.astype(str).str.zfill(2)

    base_jornada = df.groupby(['TECNICO', 'FECHA']).agg(
        Primera_Orden=('HORA_INI', 'min'),
        Ultima_Orden=('HORA_LIQ', 'max'),
        Total_Ordenes=('NUM', 'count')
    ).reset_index()
    
    base_jornada['Horas_Jornada'] = (base_jornada['Ultima_Orden'] - base_jornada['Primera_Orden']).dt.total_seconds() / 3600
    base_jornada['Horas_Jornada'] = base_jornada['Horas_Jornada'].round(2)

    tipos_orden_dia = df.pivot_table(index=['TECNICO', 'FECHA'], columns='ACTIVIDAD', aggfunc='size', fill_value=0).reset_index()
    base_diaria = pd.merge(base_jornada, tipos_orden_dia, on=['TECNICO', 'FECHA'])

    mapa_fechas = df[['FECHA', 'SEMANA', 'MES']].drop_duplicates()
    base_diaria = pd.merge(base_diaria, mapa_fechas, on='FECHA', how='left')

    columnas_num = ['Horas_Jornada', 'Total_Ordenes'] + list(tipos_orden_dia.columns[2:])
    
    prom_semanal = base_diaria.groupby(['TECNICO', 'SEMANA'])[columnas_num].mean().round(1).reset_index()
    prom_mensual = base_diaria.groupby(['TECNICO', 'MES'])[columnas_num].mean().round(1).reset_index()
    prom_general = base_diaria.groupby('TECNICO')[columnas_num].mean().round(1).reset_index()

    return base_diaria, prom_semanal, prom_mensual, prom_general

# ==============================================================================
# FUNCIÓN COMPARTIDA DE SINCRONIZACIÓN
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("Descargando y aplicando formato espejo estricto..."):
            df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
            if not df_nube.empty:
                df_nube = df_nube.dropna(how='all')
                df_nube.columns = df_nube.columns.str.upper().str.strip()

                if 'SUSCRIPTOR' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)

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

                if 'ACTIVIDAD' in df_nube.columns:
                    act_upper = df_nube['ACTIVIDAD'].astype(str).str.upper()
                    mask_falsos = act_upper.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
                    mask_solo_sop = act_upper.str.contains('SOP|FIBRA', na=False)
                    if 'ES_OFFLINE' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ES_OFFLINE'] = False; df_nube.loc[~mask_solo_sop, 'ES_OFFLINE'] = False
                    if 'ALERTA_TIEMPO' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ALERTA_TIEMPO'] = False; df_nube.loc[~mask_solo_sop, 'ALERTA_TIEMPO'] = False
                
                for col_txt in ['NUM', 'CLIENTE']:
                    if col_txt in df_nube.columns:
                        df_nube[col_txt] = pd.to_numeric(df_nube[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
                        df_nube[col_txt] = df_nube[col_txt].replace('0', 'N/D')
                        
                if 'DIAS_RETRASO' in df_nube.columns: df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
                if 'MINUTOS_CALC' in df_nube.columns: df_nube['MINUTOS_CALC'] = pd.to_numeric(df_nube['MINUTOS_CALC'], errors='coerce').fillna(0.0)
                if 'ESTADO' in df_nube.columns: df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                ahora_momento_ts = pd.Timestamp(datetime.utcnow() - timedelta(hours=6))
                fecha_limite_7d = ahora_momento_ts - timedelta(days=7) 
                
                if 'HORA_LIQ' in df_nube.columns and 'FECHA_APE' in df_nube.columns and 'ESTADO' in df_nube.columns:
                    mask_vivas = df_nube['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                    df_nube = df_nube[(df_nube['HORA_LIQ'] >= fecha_limite_7d) | (df_nube['FECHA_APE'] >= fecha_limite_7d) | (df_nube['HORA_LIQ'].isna()) | mask_vivas].copy()

                st.session_state.df_base = df_nube
                st.success("✅ Sincronización Exitosa.")
                st.rerun()
            else: st.warning("La base de datos está vacía.")
    except Exception as e: st.error(f"Error al conectar con la nube: {e}")

@st.dialog("Detalle de Gestión de la Orden")
def mostrar_comentario_cierre(fila):
    st.markdown(f"### 📋 Información Detallada: Orden N° {fila['NUM']}")
    col_a, col_b = st.columns(2)
    with col_a:
        st.write(f"**N° Cuenta:** {fila.get('CLIENTE', 'N/D')}")
        st.write(f"**Nombre:** {fila.get('NOMBRE', 'N/D')}")
    with col_b:
        st.write(f"**Estado:** {fila['ESTADO']}")
        st.write(f"**Técnico:** {fila['TECNICO']}")
    st.divider()
    st.info(fila.get('COMENTARIO', 'Sin observaciones.'))
    if st.button("Cerrar Detalles"): st.rerun()

def aplicar_estilos_df(df_original):
    df_v = df_original.copy()
    def row_styler_logic(fila_v):
        estilos = [''] * len(fila_v)
        if fila_v.get('ES_OFFLINE') == True and 'NUM' in fila_v.index:
            estilos[fila_v.index.get_loc('NUM')] = 'background-color: #9b111e; color: white; font-weight: bold'
        return estilos
    
    if 'HORA_INI' in df_v.columns:
        df_v['HORA_INI'] = pd.to_datetime(df_v['HORA_INI'], errors='coerce').dt.strftime('%I:%M %p').fillna("---")
    if 'HORA_LIQ' in df_v.columns:
        df_v['HORA_LIQ'] = pd.to_datetime(df_v['HORA_LIQ'], errors='coerce').dt.strftime('%I:%M %p').fillna("---")
        
    return df_v, row_styler_logic

@st.cache_data(show_spinner="Depurando datos...", ttl=60)
def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos)
        ahora_momento_ts = pd.Timestamp(datetime.utcnow() - timedelta(hours=6))
        
        if 'HORA_INI' in df_act.columns and 'HORA_LIQ' in df_act.columns:
            def alert_2h_logic(row):
                if pd.notnull(row['HORA_INI']) and pd.isnull(row['HORA_LIQ']):
                    m_diff = (ahora_momento_ts - row['HORA_INI']).total_seconds() / 60
                    if m_diff > 120 and str(row.get('ESTADO','')).upper().strip() != 'CERRADA':
                        return True
                return False
            df_act['ALERTA_TIEMPO'] = df_act.apply(alert_2h_logic, axis=1)
            
        def segmentar_plex(row):
            texto = f"{row.get('ACTIVIDAD', '')} {row.get('CLIENTE', '')} {row.get('COMENTARIO', '')}".upper()
            return 'PLEX' if 'PLEX' in texto else 'RESIDENCIAL'
        df_act['SEGMENTO'] = df_act.apply(segmentar_plex, axis=1)
        
        return df_act, df_hst
    except Exception as e:
        return None, None

# ==============================================================================
# 5. INTERFAZ PRINCIPAL (MAIN)
# ==============================================================================
def main():
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_movil = (streamlit_js_eval(js_expressions='window.innerWidth', key='W_CHK') or 1000) < 800

    try: conn = st.connection("gsheets", type=GSheetsConnection)
    except: conn = None

    # --- BARRA LATERAL (MENÚS Y FILTROS) ---
    with st.sidebar:
        st.markdown("### ☁️ Sincronización")
        if st.button("📥 ACTUALIZAR NUBE", use_container_width=True): sincronizar_datos_nube(conn)
        
        file_act_ptr, file_disp_ptr, btn_reprocesar = None, None, False
        if rol_usuario in ['admin', 'jefe'] and not es_movil:
            st.divider()
            archivos = st.file_uploader("Sube rep_actividades y FttxActiveDevice", type=["xlsx", "csv"], accept_multiple_files=True)
            if archivos:
                for f in archivos:
                    if "actividades" in f.name.lower(): file_act_ptr = f
                    elif "device" in f.name.lower(): file_disp_ptr = f
            btn_reprocesar = st.button("🔄 ACTUALIZAR TODO", use_container_width=True)

    if 'df_base' not in st.session_state or btn_reprocesar:
        if file_act_ptr is None or file_disp_ptr is None:
            if st.session_state.get('df_base') is None:
                st.title("⚡ Monitor Operativo")
                if st.button("📥 DESCARGAR DATOS", type="primary"): sincronizar_datos_nube(conn)
                return
        else:
            res_p, res_h = cargar_y_limpiar_crudos_diamante_monitor(file_act_ptr, file_disp_ptr)
            if res_p is not None:
                st.session_state.df_base = res_p
                st.session_state.df_hist = res_h
                if conn: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=res_p)
            else: return

    df_base = st.session_state.df_base.copy()
    for c in ['HORA_INI', 'HORA_LIQ']: df_base[c] = pd.to_datetime(df_base[c], errors='coerce')
    df_base_activa = df_base[pd.to_numeric(df_base.get('DIAS_RETRASO', 0), errors='coerce') >= 0].copy()

    ahora_local = datetime.utcnow() - timedelta(hours=6)
    hoy_date_valor = ahora_local.date()

    # RESTAURACIÓN: Menú Completo
    with st.sidebar:
        st.divider()
        if rol_usuario in ['admin', 'jefe']:
            opciones_menu = ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "🚫 NOINSTALADO", "📅 REPROGRAMADAS", "🚙 Auditoría Vehículos"]
        else:
            opciones_menu = ["⚡ Monitor en Vivo"]
        
        nav_menu = st.radio("MENÚ DE CONTROL:", opciones_menu)
        
        if nav_menu == "⚡ Monitor en Vivo":
            st.divider()
            st.markdown("### 🎛️ Filtros Rápidos")
            lista_tecs = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            tec_filtro = st.selectbox("👤 Técnico:", lista_tecs)
            filtro_est = st.multiselect("🚦 Estado:", sorted(df_base_activa['ESTADO'].dropna().unique().tolist()))
            
            df_monitor_filtrado = df_base_activa.copy()
            if tec_filtro != "Todos": df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro]
            if filtro_est: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_est)]
        else:
            df_monitor_filtrado = df_base_activa.copy()

    # ==============================================================================
    # PANTALLAS SECUNDARIAS RESTAURADAS
    # ==============================================================================
    if nav_menu == "🚙 Auditoría Vehículos":
        mostrar_auditoria(es_movil, conn)
        return

    if nav_menu == "🚫 NOINSTALADO":
        st.title("🚫 Órdenes NOINSTALADO (Cerradas Hoy)")
        mask_noinst = (df_base['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)) & (df_base['HORA_LIQ'].dt.date == hoy_date_valor)
        st.dataframe(df_base[mask_noinst][['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']], use_container_width=True, height=600, hide_index=True)
        return

    if nav_menu == "📅 REPROGRAMADAS":
        st.title("📅 Órdenes Reprogramadas (Futuras)")
        mask_reprog = (df_base['DIAS_RETRASO'] < 0)
        df_reprog = df_base[mask_reprog].copy()
        st.metric("Total Agendadas a Futuro", len(df_reprog))
        if not df_reprog.empty:
            cols_visibles = ['DIAS_RETRASO', 'NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'TECNICO', 'ESTADO', 'COMENTARIO']
            cols_finales = [c for c in cols_visibles if c in df_reprog.columns]
            st.dataframe(df_reprog[cols_finales].style.set_properties(**{'background-color': '#1a2a3a', 'color': '#58a6ff', 'font-weight': 'bold'}, subset=['DIAS_RETRASO']), use_container_width=True, height=600, hide_index=True)
        else: 
            st.success("✅ No hay órdenes reprogramadas para fechas futuras en este momento.")
        return

    if nav_menu == "📊 Centro de Reportes":
        st.title("📊 Centro de Reportes Operativos")
        tab_dinamico, tab_gerencial = st.tabs(["⚡ Reporte Dinámico", "💼 Gerencial (Productividad)"])

        with tab_dinamico:
            st.subheader("📄 PDF Rápido")
            if st.button("📄 GENERAR", type="primary"): 
                st.download_button("📥 Descargar", data=logica_generar_pdf(df_base_activa), file_name="Rep.pdf")

        with tab_gerencial:
            st.subheader("📈 Auditoría de Jornada Efectiva y Productividad")
            st.caption("Sube el archivo crudo. Calcularemos horas y órdenes agrupadas por Día, Semana y Mes.")
            archivo_ger = st.file_uploader("📂 Subir Reporte", type=['xlsx', 'csv'], key="up_g")
            if archivo_ger:
                with st.spinner("Procesando fechas y tiempos muertos..."):
                    df_raw = pd.read_csv(archivo_ger) if archivo_ger.name.endswith('.csv') else pd.read_excel(archivo_ger)
                    df_limpio = procesar_dataframe_base(df_raw) 
                    b_diaria, p_semanal, p_mensual, p_general = calcular_metricas_escalonadas(df_limpio)
                    t_prod, t_efi, t_jor = generar_tablas_gerenciales(df_limpio)
                    
                    st.markdown("### 🎛️ Nivel de Análisis (Agrupación)")
                    vista = st.radio("Selecciona la temporalidad:", ["Promedio General (Trimestre)", "Promedio Mensual", "Promedio Semanal", "Detalle Diario Exacto"], horizontal=True)
                    if vista == "Promedio General (Trimestre)": st.dataframe(p_general, use_container_width=True, hide_index=True)
                    elif vista == "Promedio Mensual": st.dataframe(p_mensual, use_container_width=True, hide_index=True)
                    elif vista == "Promedio Semanal": st.dataframe(p_semanal, use_container_width=True, hide_index=True)
                    else: st.dataframe(b_diaria, use_container_width=True, hide_index=True)
                    
                    st.divider()
                    if st.button("🚀 GENERAR PDF GERENCIAL", type="primary", use_container_width=True):
                        st.download_button("📥 Descargar PDF", data=generar_pdf_trimestral_detallado(t_prod, t_efi, t_jor), file_name="Gerencial.pdf")
        return

    # ==============================================================================
    # 💎 INTERFAZ DASHBOARD "CENTRO DE CONTROL" (MONITOR EN VIVO)
    # ==============================================================================
    if nav_menu == "⚡ Monitor en Vivo":
        st.markdown(f"<h2>📊 Monitor Operativo <span style='font-size:1rem; color:#94A3B8; font-weight:normal;'>| Actualizado: {ahora_local.strftime('%I:%M %p')}</span></h2>", unsafe_allow_html=True)

        m_viva = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        df_asignadas = df_monitor_filtrado[m_viva].copy()
        
        # PREPARAR DATOS DEL TABLERO (Restaurando lógica real de las 4 columnas)
        df_asignadas['DIAS_RETRASO'] = df_asignadas.get('DIAS_RETRASO', 0).fillna(0).astype(int)
        if 'TECNICO' in df_asignadas.columns:
            df_asignadas.loc[df_asignadas['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False), 'DIAS_RETRASO'] = 0
            
        df_asignadas['CatD'] = df_asignadas['DIAS_RETRASO'].apply(
            lambda d: ">= 7 Dia" if d >= 7 else (f"= {int(d)} Dia" if d > 0 else "= 0 Dia")
        )
        
        # --- FILA 1: KPIs SUPERIORES ---
        vivas_count = len(df_asignadas)
        cerradas_hoy = len(df_monitor_filtrado[(df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].str.contains('CERRADA', na=False, case=False))])
        tecs_activos = df_asignadas['TECNICO'].nunique()
        offline_criticos = int((df_asignadas.get('ES_OFFLINE', pd.Series([False]*len(df_asignadas))) == True).sum())

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1: st.markdown(f'<div class="kpi-card"><p class="kpi-label">TOTAL ASIGNADAS</p><p class="kpi-value">{vivas_count}</p></div>', unsafe_allow_html=True)
        with kpi2: st.markdown(f'<div class="kpi-card"><p class="kpi-label">CERRADAS HOY</p><p class="kpi-value-green">{cerradas_hoy}</p></div>', unsafe_allow_html=True)
        with kpi3: st.markdown(f'<div class="kpi-card"><p class="kpi-label">TÉCNICOS EN RUTA</p><p class="kpi-value">{tecs_activos}</p></div>', unsafe_allow_html=True)
        with kpi4: st.markdown(f'<div class="kpi-card"><p class="kpi-label">CAÍDAS (OFFLINE)</p><p class="kpi-value-red">{offline_criticos}</p></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # --- FILA 2: TABLERO DE CARGA EXACTO (4 COLUMNAS) ---
        with st.expander("✅ TABLERO DE CARGA ACTUAL (SOLO ÓRDENES ASIGNADAS)", expanded=True):
            col_tab_1, col_tab_2, col_tab_3, col_tab_4 = st.columns([1, 1.2, 1.2, 1])
            
            with col_tab_1:
                st.caption("📅 Resumen de Retraso")
                res_retraso_v = df_asignadas['CatD'].value_counts().reindex([">= 7 Dia","= 4 Dia","= 1 Dia","= 0 Dia"], fill_value=0).reset_index()
                res_retraso_v.columns = ['Dias', 'Cant']
                sum_total_pendientes_v = res_retraso_v['Cant'].sum()
                res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_pendientes_v*100):.0f}%" if sum_total_pendientes_v > 0 else "0%")
                st.dataframe(res_retraso_v, hide_index=True, use_container_width=True)
                
            with col_tab_2:
                st.caption("🛠️ SOP / Mantenimiento")
                act_tab_sop = df_asignadas['ACTIVIDAD'].astype(str).str.upper()
                res_sop_visual_v = {
                    "FTTH / FIBRA": len(df_asignadas[act_tab_sop.str.contains("FIBRA|FTTH", na=False)]),
                    "Navegación / Internet": len(df_asignadas[act_tab_sop.str.contains("NAV|INTERNET", na=False)]),
                    "ONT/ONU Offline": int((df_asignadas.get('ES_OFFLINE', pd.Series([False]*len(df_asignadas))) == True).sum()), 
                    "Niveles alterados": len(df_asignadas[df_asignadas['COMENTARIO'].astype(str).str.upper().str.contains("NIVEL|DB", na=False)]),
                    "Sin señal de TV": len(df_asignadas[act_tab_sop.str.contains("TV|CABLE", na=False)])
                }
                st.dataframe(pd.DataFrame(list(res_sop_visual_v.items()), columns=['SOP', 'Cant']), hide_index=True, use_container_width=True)
                st.write(f"**Total General SOP: {sum(res_sop_visual_v.values())}**")

            with col_tab_3:
                st.caption("📦 Instalaciones")
                txt_ins_v = df_asignadas['ACTIVIDAD'].astype(str).str.upper() + " " + df_asignadas['COMENTARIO'].astype(str).str.upper()
                res_ins_visual_v = {
                    "Adición": len(df_asignadas[txt_ins_v.str.contains("ADIC", na=False)]),
                    "Cambio / Migración": len(df_asignadas[txt_ins_v.str.contains("CAMBIO|MIGRACI", na=False)]),
                    "Recuperado": len(df_asignadas[txt_ins_v.str.contains("RECUP", na=False)])
                }
                mask_base_ins = txt_ins_v.str.contains("INS|NUEVA", na=False)
                mask_excl_ins = txt_ins_v.str.contains("ADIC|CAMBIO|MIGRACI|RECUP", na=False)
                res_ins_visual_v["Nueva"] = len(df_asignadas[mask_base_ins & ~mask_excl_ins])
                
                st.dataframe(pd.DataFrame(list(res_ins_visual_v.items()), columns=['Instalaciones', 'Cant']), hide_index=True, use_container_width=True)
                st.write(f"**Total General INS: {sum(res_ins_visual_v.values())}**")

            with col_tab_4:
                st.caption("⚙️ Otros")
                txt_otr_v = df_asignadas['ACTIVIDAD'].astype(str).str.upper() + " " + df_asignadas['COMENTARIO'].astype(str).str.upper()
                mask_otros_monitor = ~txt_otr_v.str.contains("SOP|FALLA|MANT|INS|ADIC|CAMBIO|MIGRACI|NUEVA|RECUP", na=False)
                res_otros_monitor = df_asignadas[mask_otros_monitor]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                res_otros_monitor.columns = ['Otros', 'Cant']
                st.dataframe(res_otros_monitor.head(8), hide_index=True, use_container_width=True)
                st.write(f"**Total Otros: {res_otros_monitor['Cant'].sum()}**")
                
                alertas_2h = int((df_asignadas.get('ALERTA_TIEMPO', pd.Series([False]*len(df_asignadas))) == True).sum())
                st.markdown(f"""<div style="background-color: #452714; padding: 10px; border-radius: 5px; border-left: 5px solid #FF9800; text-align: center; margin-top: 10px;">
                    <span style="color: #FF9800; font-weight: bold;">⚠️ EXCESEN 2 HORAS: {alertas_2h}</span>
                </div>""", unsafe_allow_html=True)

        st.divider()

        # --- RESTAURACIÓN: GANTT Y TABLA PRINCIPAL ---
        tab_tabla, tab_gantt = st.tabs(["📑 Listado Táctico de Órdenes", "⏱️ Análisis de Tiempos (GANTT)"])
        
        with tab_tabla:
            vista_tabla = st.radio("Filtro de Vista:", ["Órdenes Asignadas / Pendientes", "Órdenes Cerradas Hoy", "Órdenes Anuladas Hoy"], horizontal=True)
            
            if vista_tabla == "Órdenes Asignadas / Pendientes": df_mostrar = df_asignadas
            elif vista_tabla == "Órdenes Cerradas Hoy": df_mostrar = df_monitor_filtrado[(df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].str.contains('CERRADA', na=False, case=False))]
            else: df_mostrar = df_monitor_filtrado[(df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].str.contains('ANULADA', na=False, case=False))]

            if not df_mostrar.empty:
                df_estilo, row_styler = aplicar_estilos_df(df_mostrar)
                columnas_finales = ['DIAS_RETRASO', 'NUM', 'CLIENTE', 'NOMBRE', 'ACTIVIDAD', 'COLONIA', 'TECNICO', 'ESTADO', 'HORA_INI']
                df_estilo = df_estilo[[c for c in columnas_finales if c in df_estilo.columns]]
                
                evento = st.dataframe(
                    df_estilo.style.apply(row_styler, axis=1),
                    use_container_width=True, hide_index=True, height=500, on_select="rerun", selection_mode="single-row"
                )
                if evento.selection.rows:
                    mostrar_comentario_cierre(df_mostrar.iloc[evento.selection.rows[0]])
            else:
                st.info("No hay órdenes para mostrar en esta vista.")

        with tab_gantt:
            st.subheader("⏱️ Timeline de Ejecución de Técnicos")
            df_gantt = df_asignadas[df_asignadas['HORA_INI'].notnull()].copy()
            if not df_gantt.empty:
                df_gantt['FIN_L'] = df_gantt['HORA_LIQ'].fillna(pd.Timestamp(ahora_local))
                fig_gantt = px.timeline(df_gantt, x_start="HORA_INI", x_end="FIN_L", y="TECNICO", color="ACTIVIDAD", text="ACTIVIDAD", template="plotly_dark", height=500)
                fig_gantt.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_gantt, use_container_width=True)
            else:
                st.warning("No hay órdenes con Hora de Inicio registrada para graficar en tiempo real.")

if __name__ == "__main__": 
    verificar_autenticacion()
    if not st.session_state['autenticado']: mostrar_pantalla_login()
    else: main(); mostrar_boton_logout()
