import streamlit as st
import pandas as pd
import time
from tools import read_file_robust

# Asegurarse de cargar las funciones nuevas (debe ser la última actualización de tools)
try:
    from tools import procesar_rendimiento_integral, generar_pdf_rendimiento_integral
except ImportError:
    pass

def mostrar_tiempos_tecnicos(conn=None, df_base=None, *args):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Panel Integral de Rendimiento y Disciplina</h2>", unsafe_allow_html=True)
    st.caption("Cruce automatizado: Tiempos de Órdenes vs Registros GPS vs Expedientes Laborales.")
    st.divider()

    # ==========================================================
    # 1. ZONA DE CARGA DE DATOS
    # ==========================================================
    st.markdown("### 📥 1. Carga y Sincronización de Datos")
    
    col_c1, col_c2, col_c3 = st.columns(3)
    
    with col_c1:
        st.info("📦 Órdenes y Tiempos")
        file_act = st.file_uploader("Sube 'rep_actividades'", type=['csv', 'xlsx', 'xls'])
        
    with col_c2:
        st.info("📡 GPS y Entradas/Salidas")
        file_gps = st.file_uploader("Sube 'InformeZonasRutas'", type=['csv', 'xlsx', 'xls'])
        
    with col_c3:
        st.info("☁️ Expedientes (Llamados/Faltas)")
        st.write("Conexión a Base de Datos:")
        if st.button("🔄 Sincronizar Expedientes de Nube", use_container_width=True):
            if conn:
                with st.spinner("Descargando historial de incidencias..."):
                    try:
                        df_exp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_expedientes'] = df_exp
                        st.success("✅ ¡Expedientes sincronizados!")
                    except Exception as e:
                        st.error(f"Error al conectar con la hoja 'Expedientes': {e}")
            else:
                st.error("No se detectó conexión activa a la Nube.")
                
        if 'df_expedientes' in st.session_state:
            st.success(f"Archivados: {len(st.session_state['df_expedientes'])} registros.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ==========================================================
    # 2. MOTOR DE CRUCE Y PROCESAMIENTO
    # ==========================================================
    if st.button("🚀 INICIAR ANÁLISIS INTEGRAL", type="primary", use_container_width=True):
        if file_act is None:
            st.error("⚠️ Para calcular la eficiencia es OBLIGATORIO subir el archivo 'rep_actividades'.")
        else:
            with st.spinner("🧠 Fusionando datos operativos, GPS y recursos humanos..."):
                df_act = read_file_robust(file_act)
                df_gps = read_file_robust(file_gps) if file_gps else None
                df_exp = st.session_state.get('df_expedientes', None)
                
                try:
                    df_resultado, msg = procesar_rendimiento_integral(df_act, df_gps, df_exp)
                    
                    if df_resultado is not None:
                        st.session_state['df_rendimiento_integral'] = df_resultado
                        st.success("✅ ¡Magia completada! El panorama general ha sido generado con éxito.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Error interno: {msg}")
                except NameError:
                    st.error("⚠️ Asegúrate de haber copiado la función procesar_rendimiento_integral en tu archivo tools.py")

    # ==========================================================
    # 3. DASHBOARD Y VISUALIZACIÓN
    # ==========================================================
    if 'df_rendimiento_integral' in st.session_state:
        df_res = st.session_state['df_rendimiento_integral'].copy()
        
        st.markdown("---")
        st.markdown("### 🏆 Tablero Gerencial (KPIs)")
        
        # Cajas de Indicadores Visuales
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("👥 Técnicos Activos", len(df_res))
        with kpi2:
            st.metric("📦 Órdenes Totales", int(df_res['ÓRDENES EJECUTADAS'].sum()))
        with kpi3:
            st.metric("⏳ Promedio de Orden (Min)", round(df_res['TIEMPO PROM. (Min)'].mean(), 1))
        with kpi4:
            total_incidencias = int(df_res['DÍAS FALTADOS'].sum() + df_res['LLAMADOS DE ATENCIÓN'].sum())
            st.metric("🚨 Total Incidencias", total_incidencias, delta_color="inverse")
            
        st.markdown("---")
        st.markdown("### 🔍 Filtros Avanzados y Tabla de Resultados")
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_tec = st.multiselect("👤 Filtrar por Técnico(s):", options=sorted(df_res['TÉCNICO'].unique()))
        with col_f2:
            st.markdown("<br>", unsafe_allow_html=True)
            ver_con_faltas = st.checkbox("🚨 Mostrar solo técnicos con Días Faltados o Llamados de Atención")
            
        # Lógica de Filtros
        if filtro_tec:
            df_res = df_res[df_res['TÉCNICO'].isin(filtro_tec)]
        if ver_con_faltas:
            df_res = df_res[(df_res['DÍAS FALTADOS'] > 0) | (df_res['LLAMADOS DE ATENCIÓN'] > 0)]
            
        # Dar estilo rojo claro a quienes tienen faltas o incidentes
        def alert_style(row):
            if row['DÍAS FALTADOS'] > 0 or row['LLAMADOS DE ATENCIÓN'] > 0:
                return ['background-color: #ffcccc; color: #b30000; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(df_res.style.apply(alert_style, axis=1), use_container_width=True, hide_index=True)
        
        # Opciones de exportación
        st.markdown("<br>", unsafe_allow_html=True)
        col_dl1, col_dl2 = st.columns([1, 2])
        with col_dl1:
            try:
                pdf_data = generar_pdf_rendimiento_integral(df_res)
                if pdf_data:
                    st.download_button(
                        label="📄 Descargar Reporte PDF",
                        data=pdf_data,
                        file_name="Reporte_Rendimiento_Tecnicos.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
            except NameError:
                st.warning("El módulo de PDF aún no está en tools.py")
