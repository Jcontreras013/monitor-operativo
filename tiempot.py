import streamlit as st
import pandas as pd
import time
from datetime import datetime

# Importación segura de dependencias desde tools.py
try:
    from tools import (
        read_file_robust,
        procesar_dataframe_base,
        procesar_fechas_seguro,
        procesar_rendimiento_integral,
        generar_pdf_rendimiento_integral,
        leer_espejo_gcs,
        get_honduras_time
    )
except ImportError as e:
    st.error(f"Error al importar módulos de soporte desde tools.py: {e}")

def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Panel Integral de Rendimiento y Disciplina</h2>", unsafe_allow_html=True)
    st.caption("Cruce automatizado y consolidación: Órdenes, Tiempos de Atención, Registros GPS y Expedientes Laborales.")
    st.divider()

    # ==========================================================
    # 1. CARGA Y SINCRONIZACIÓN DE DATOS
    # ==========================================================
    st.markdown("### 📥 1. Carga y Sincronización de Datos")
    
    col_c1, col_c2, col_c3 = st.columns(3)
    
    with col_c1:
        st.info("📦 Órdenes y Tiempos")
        file_act = st.file_uploader("Sube 'rep_actividades'", type=['csv', 'xlsx', 'xls'], key="uploader_act")
        
    with col_c2:
        st.info("📡 GPS y Entradas/Salidas")
        file_gps = st.file_uploader("Sube 'InformeZonasRutas'", type=['csv', 'xlsx', 'xls'], key="uploader_gps")
        
    with col_c3:
        st.info("☁️ Expedientes (Llamados/Faltas)")
        st.write("Conexión a Base de Datos:")
        
        # Sincronización automática silenciosa si no existe en estado de sesión
        if 'df_expedientes' not in st.session_state:
            st.session_state['df_expedientes'] = None

        if st.session_state['df_expedientes'] is None and conn is not None:
            try:
                NOMBRE_BUCKET = "jovial-trilogy-306216.appspot.com"
                df_exp = leer_espejo_gcs(NOMBRE_BUCKET, "expedientes_maestro.csv")
                if df_exp is None or df_exp.empty:
                    df_exp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                st.session_state['df_expedientes'] = df_exp
            except Exception:
                pass

        if st.button("🔄 Sincronizar Expedientes de Nube", use_container_width=True):
            if conn:
                with st.spinner("Descargando historial maestro..."):
                    try:
                        NOMBRE_BUCKET = "jovial-trilogy-306216.appspot.com"
                        df_exp = None
                        
                        try:
                            df_exp = leer_espejo_gcs(NOMBRE_BUCKET, "expedientes_maestro.csv")
                        except Exception:
                            pass
                            
                        if df_exp is None or df_exp.empty:
                            df_exp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            
                        st.session_state['df_expedientes'] = df_exp
                        st.success("✅ ¡Expedientes sincronizados con éxito!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al conectar con la base de datos: {e}")
            else:
                st.error("❌ No se detectó conexión activa a la Nube.")
                
        if st.session_state['df_expedientes'] is not None:
            st.success(f"Archivados: {len(st.session_state['df_expedientes'])} registros.")

    st.markdown("<br>", unsafe_allow_html=True)

    # ==========================================================
    # 2. MOTOR DE CRUCE Y PROCESAMIENTO
    # ==========================================================
    if st.button("🚀 INICIAR ANÁLISIS INTEGRAL", type="primary", use_container_width=True):
        if file_act is None:
            st.error("⚠️ Para calcular la eficiencia es necesario subir el archivo 'rep_actividades'.")
        else:
            with st.spinner("Procesando y alineando datos operativos, GPS y recursos humanos..."):
                try:
                    # Lectura e inmunización contra fallos de formato ("No tables found", codificaciones, etc.)
                    try:
                        df_act_raw = read_file_robust(file_act)
                    except Exception as err_act:
                        st.error(f"No se pudo interpretar el archivo de actividades: {err_act}")
                        return
                    
                    df_gps_raw = None
                    if file_gps:
                        try:
                            df_gps_raw = read_file_robust(file_gps)
                        except Exception as err_gps:
                            st.warning(f"No se pudo interpretar el archivo GPS: {err_gps}. El cruce continuará sin telemetría.")

                    # Pre-procesamiento de nombres de columna usando el mapa maestro para estandarizar
                    df_act_mapped = procesar_dataframe_base(df_act_raw)
                    
                    # Alineación de nombres requeridos específicamente por el procesador integral
                    df_act_ready = df_act_mapped.rename(columns={
                        'HORA_INI': 'FECHA ENTRADA',
                        'HORA_LIQ': 'FECHA LIQUIDADO'
                    })

                    df_exp = st.session_state.get('df_expedientes', None)
                    
                    # Ejecución del cruce analítico
                    df_resultado, msg = procesar_rendimiento_integral(df_act_ready, df_gps_raw, df_exp)
                    
                    if df_resultado is not None:
                        st.session_state['df_rendimiento_integral'] = df_resultado
                        st.success("✅ Análisis general consolidado con éxito.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"No se pudo procesar el rendimiento: {msg}")
                except Exception as e:
                    st.error(f"Ocurrió un error inesperado durante el procesamiento: {e}")

    # ==========================================================
    # 3. DASHBOARD Y VISUALIZACIÓN DE RESULTADOS
    # ==========================================================
    if 'df_rendimiento_integral' in st.session_state:
        df_res = st.session_state['df_rendimiento_integral'].copy()
        
        st.markdown("---")
        st.markdown("### 🏆 Tablero Gerencial (KPIs)")
        
        # Cálculo de métricas
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("👥 Técnicos Evaluados", len(df_res))
        with kpi2:
            total_ordenes = df_res['ÓRDENES EJECUTADAS'].sum() if 'ÓRDENES EJECUTADAS' in df_res.columns else 0
            st.metric("📦 Órdenes Totales", int(total_ordenes))
        with kpi3:
            promedio_tiempo = df_res['TIEMPO PROM. (Min)'].mean() if 'TIEMPO PROM. (Min)' in df_res.columns else 0
            st.metric("⏳ Promedio de Orden", f"{round(promedio_tiempo, 1)} Min")
        with kpi4:
            dias_faltados = df_res['DÍAS FALTADOS'].sum() if 'DÍAS FALTADOS' in df_res.columns else 0
            llamados_atencion = df_res['LLAMADOS DE ATENCIÓN'].sum() if 'LLAMADOS DE ATENCIÓN' in df_res.columns else 0
            total_incidencias = int(dias_faltados + llamados_atencion)
            st.metric("🚨 Total Incidencias", total_incidencias)
            
        st.markdown("---")
        st.markdown("### 🔍 Filtros de Búsqueda y Resultados")
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_tec = st.multiselect("👤 Filtrar por Técnico:", options=sorted(df_res['TÉCNICO'].unique()))
        with col_f2:
            st.markdown("<br>", unsafe_allow_html=True)
            ver_con_faltas = st.checkbox("🚨 Mostrar solo técnicos con incidencias (Faltas o Llamados de Atención)")
            
        # Lógica de Filtrado
        if filtro_tec:
            df_res = df_res[df_res['TÉCNICO'].isin(filtro_tec)]
        if ver_con_faltas:
            condicion_incidencias = (df_res['DÍAS FALTADOS'] > 0) | (df_res['LLAMADOS DE ATENCIÓN'] > 0)
            df_res = df_res[condicion_incidencias]
            
        # Formateador visual para destacar filas con incidencias de manera sutil
        def alert_style(row):
            has_faltas = row.get('DÍAS FALTADOS', 0)
            has_llamados = row.get('LLAMADOS DE ATENCIÓN', 0)
            try:
                val_faltas = int(float(has_faltas)) if pd.notna(has_faltas) else 0
                val_llamados = int(float(has_llamados)) if pd.notna(has_llamados) else 0
            except ValueError:
                val_faltas = 0
                val_llamados = 0
                
            if val_faltas > 0 or val_llamados > 0:
                return ['background-color: #fee2e2; color: #991b1b; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df_res.style.apply(alert_style, axis=1), 
            use_container_width=True, 
            hide_index=True
        )
        
        # Sección de exportación de reportes
        st.markdown("<br>", unsafe_allow_html=True)
        col_dl1, col_dl2 = st.columns([1, 2])
        with col_dl1:
            try:
                pdf_data = generar_pdf_rendimiento_integral(df_res)
                if pdf_data:
                    st.download_button(
                        label="📄 Descargar Reporte PDF",
                        data=pdf_data,
                        file_name="Reporte_Rendimiento_Integral.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
            except Exception as e:
                st.warning(f"No se pudo generar la descarga de PDF: {e}")
