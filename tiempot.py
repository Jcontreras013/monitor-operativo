import streamlit as st
import pandas as pd
import time
from datetime import datetime
import io
import re

# Importación segura de dependencias desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
        procesar_fechas_seguro,
        procesar_rendimiento_integral,
        generar_pdf_rendimiento_integral,
        leer_espejo_gcs,
        get_honduras_time
    )
except ImportError as e:
    st.error(f"Error al importar módulos de soporte desde tools.py: {e}")

# Constantes del sistema alineadas con expediente.py
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# MOTOR LOCAL CORREGIDO DE LECTURA DE ARCHIVOS (Evita falsos positivos HTML)
# ==============================================================================
def forzar_columnas_unicas_local(df):
    if df is None or df.empty: 
        return df
    df.columns = df.columns.astype(str).str.strip()
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        dup_indices = cols[cols == dup].index.tolist()
        for i, idx in enumerate(dup_indices):
            if i != 0:
                cols.iat[idx] = f"{dup}_{i}"
    df.columns = cols
    return df

def read_file_robust_local(uploaded_file):
    filename = uploaded_file.name.lower()
    uploaded_file.seek(0)
    content = uploaded_file.read()
    uploaded_file.seek(0)
    
    # 1. Forzar motores Excel para formatos modernos comprimidos (.xlsx, .xlsm)
    if filename.endswith('.xlsx') or filename.endswith('.xlsm'):
        try:
            df = pd.read_excel(uploaded_file, engine='openpyxl')
            return forzar_columnas_unicas_local(df)
        except Exception:
            pass

    # 2. Archivos antiguos XLS (BIFF8)
    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            df = pd.read_excel(uploaded_file, engine='xlrd')
            return forzar_columnas_unicas_local(df)
        except Exception:
            pass

    # 3. Comprobación estricta de HTML plano (Excluye archivos binarios ZIP que inician con PK)
    es_zip_binario = content.startswith(b'PK\x03\x04')
    if not es_zip_binario and (b'<table' in content.lower() or b'<html' in content.lower()):
        try:
            dfs = pd.read_html(io.BytesIO(content))
            if dfs:
                return forzar_columnas_unicas_local(max(dfs, key=len))
        except Exception:
            try:
                dfs = pd.read_html(io.BytesIO(content), encoding='latin-1')
                if dfs:
                    return forzar_columnas_unicas_local(max(dfs, key=len))
            except Exception:
                pass

    # 4. Alternativas de rescate (CSV o lectura por defecto)
    uploaded_file.seek(0)
    try:
        df = pd.read_excel(uploaded_file)
        return forzar_columnas_unicas_local(df)
    except Exception:
        pass

    uploaded_file.seek(0)
    try:
        df = pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip')
        return forzar_columnas_unicas_local(df)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding='latin-1', on_bad_lines='skip')
        return forzar_columnas_unicas_local(df)

# ==============================================================================
# GESTIÓN DE EXPEDIENTES COMPARTIDA
# ==============================================================================
def obtener_datos_expedientes(conn):
    """
    Recupera los datos de expedientes compartiendo la misma llave de sesión 
    que utiliza el módulo de gestión de expedientes para evitar lecturas duplicadas.
    """
    if 'df_exp_memoria' not in st.session_state:
        st.session_state['df_exp_memoria'] = None

    if st.session_state['df_exp_memoria'] is not None:
        return st.session_state['df_exp_memoria']
        
    if conn is None:
        return None
        
    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
        if df is None or df.empty:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        st.session_state['df_exp_memoria'] = df
        return df
    except Exception as e:
        st.warning(f"No se pudo cargar la base de expedientes automáticamente: {e}")
        return None

def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Panel Integral de Rendimiento y Disciplina</h2>", unsafe_allow_html=True)
    st.caption("Cruce consolidado: Órdenes de Trabajo vs Rutas GPS vs Expedientes Laborales de la Nube.")
    st.divider()

    # Carga inicial de expedientes
    df_exp_inicial = obtener_datos_expedientes(conn)

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
        
        if st.button("🔄 Sincronizar Expedientes de Nube", use_container_width=True):
            if conn:
                with st.spinner("Consultando base de datos de expedientes..."):
                    try:
                        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        if df is None or df.empty:
                            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ Datos de expedientes sincronizados y actualizados.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error durante la sincronización: {e}")
            else:
                st.error("❌ No se detectó conexión activa a la Nube. Verifique la inicialización de 'conn'.")
                
        if st.session_state.get('df_exp_memoria') is not None:
            st.success(f"Archivados: {len(st.session_state['df_exp_memoria'])} registros en memoria.")

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
                    # Lectura local corregida sin falsos positivos de HTML
                    try:
                        df_act_raw = read_file_robust_local(file_act)
                    except Exception as err_act:
                        st.error(f"No se pudo interpretar el archivo de actividades: {err_act}")
                        return
                    
                    df_gps_raw = None
                    if file_gps:
                        try:
                            df_gps_raw = read_file_robust_local(file_gps)
                        except Exception as err_gps:
                            st.warning(f"No se pudo interpretar el archivo GPS: {err_gps}. El cruce continuará sin telemetría.")

                    # Estandarización de nombres de columnas
                    df_act_mapped = procesar_dataframe_base(df_act_raw)
                    
                    df_act_ready = df_act_mapped.rename(columns={
                        'HORA_INI': 'FECHA ENTRADA',
                        'HORA_LIQ': 'FECHA LIQUIDADO'
                    })

                    # Limpieza preventiva de expedientes antes del cruce
                    df_exp_raw = st.session_state.get('df_exp_memoria', None)
                    df_exp_ready = None
                    
                    if df_exp_raw is not None and not df_exp_raw.empty:
                        df_exp_ready = df_exp_raw.copy()
                        if 'TECNICO' in df_exp_ready.columns:
                            df_exp_ready['TECNICO'] = df_exp_ready['TECNICO'].astype(str).str.replace(r'\s*\(.*\)$', '', regex=True).str.strip()

                    # Ejecución del cruce analítico
                    df_resultado, msg = procesar_rendimiento_integral(df_act_ready, df_gps_raw, df_exp_ready)
                    
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
        
        # Exportación del reporte
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
