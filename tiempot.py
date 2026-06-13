import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta
import io
import re

# Importaciones seguras desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
        procesar_fechas_seguro,
        generar_pdf_rendimiento_integral,
        leer_espejo_gcs,
        get_honduras_time
    )
except ImportError as e:
    st.error(f"Error al importar módulos desde tools.py: {e}")

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
    
    if filename.endswith('.xlsx') or filename.endswith('.xlsm'):
        try:
            df = pd.read_excel(uploaded_file, engine='openpyxl')
            return forzar_columnas_unicas_local(df)
        except Exception:
            pass

    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            df = pd.read_excel(uploaded_file, engine='xlrd')
            return forzar_columnas_unicas_local(df)
        except Exception:
            pass

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
# GESTIÓN DE EXPEDIENTES COMPARTIDA (SIN MENSAJES DE ERROR DE CONEXIÓN)
# ==============================================================================
def obtener_datos_expedientes(conn):
    if 'df_exp_memoria' not in st.session_state:
        st.session_state['df_exp_memoria'] = None

    if st.session_state['df_exp_memoria'] is not None:
        return st.session_state['df_exp_memoria']
        
    # Intento 1: Cargar directamente de GCS sin requerir 'conn'
    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
        if df is not None and not df.empty:
            st.session_state['df_exp_memoria'] = df
            return df
    except Exception:
        pass
        
    # Intento 2: Intentar conectar mediante conn de Google Sheets
    if conn is not None:
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            st.session_state['df_exp_memoria'] = df
            return df
        except Exception:
            pass
            
    return None

# ==============================================================================
# MOTOR RE-DISEÑADO DE CRUCE INTEGRAL Y PROCESAMIENTO ANALÍTICO
# ==============================================================================
def match_tecnico_inteligente(alias_gps, lista_tecnicos):
    alias_clean = str(alias_gps).upper().replace(',', '').replace('.', '')
    alias_clean = re.sub(r'MX-\d+', '', alias_clean)
    
    best_match = None
    max_coincidencias = 0
    for tec in lista_tecnicos:
        partes_tec = str(tec).upper().split()
        coincidencias = sum(1 for p in partes_tec if len(p) > 2 and p in alias_clean)
        if coincidencias > max_coincidencias:
            max_coincidencias = coincidencias
            best_match = tec
            
    return best_match if max_coincidencias >= 1 else None

def formatear_segundos_a_hora(secs):
    if pd.isna(secs) or secs is None or secs <= 0:
        return "--"
    h = int(secs // 3600) % 24
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def procesar_rendimiento_avanzado(df_act, df_gps, df_exp):
    try:
        # 1. Estandarizar columnas de Actividades
        df_act = procesar_dataframe_base(df_act)
        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
        df_act['Fecha_Dia'] = df_act['FECHA_LIQUIDADO'].dt.date
        
        # Calcular segmento
        act_upper = df_act['ACTIVIDAD'].fillna('').astype(str).str.upper()
        cli_upper = df_act['CLIENTE'].fillna('').astype(str).str.upper()
        com_upper = df_act['COMENTARIO'].fillna('').astype(str).str.upper()
        texto_seg = act_upper + " " + cli_upper + " " + com_upper
        df_act['SEGMENTO'] = pd.Series(
            ['PLEX' if ('PLEX' in t or 'PEXTERNO' in t or 'SPLITTEROPT' in t) else 'RESIDENCIAL' for t in texto_seg]
        )

        df_act['Minutos_Orden'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos_Orden'] = df_act['Minutos_Orden'].apply(lambda x: x if x > 0 else 0)
        
        # Filtrar técnicos no válidos
        df_act = df_act[df_act['TECNICO'].notna() & (df_act['TECNICO'] != 'N/D')]
        
        # Agrupar Productividad Pura por Técnico
        tecnicos_unicos = df_act['TECNICO'].unique()

        # 2. Procesar GPS con motor de promedios diarios reales (No mínimos globales)
        gps_consolidado = {}
        gps_diario = []

        if df_gps is not None and not df_gps.empty:
            col_placa = next((c for c in df_gps.columns if 'PLACA' in str(c).upper() or 'ALIAS' in str(c).upper()), None)
            col_h_in = next((c for c in df_gps.columns if 'HORA INGRESO' in str(c).upper() or 'LLEGADA' in str(c).upper()), None)
            col_h_out = next((c for c in df_gps.columns if 'HORA SALIDA' in str(c).upper() or 'SALIDA' in str(c).upper()), None)

            if col_placa and col_h_in and col_h_out:
                df_gps['Hora_Ingreso_DT'] = pd.to_datetime(df_gps[col_h_in], errors='coerce')
                df_gps['Hora_Salida_DT'] = pd.to_datetime(df_gps[col_h_out], errors='coerce')
                
                df_gps['Fecha_Ingreso'] = df_gps['Hora_Ingreso_DT'].dt.date
                df_gps['Fecha_Salida'] = df_gps['Hora_Salida_DT'].dt.date
                
                # Asignar técnico al GPS
                df_gps['TEC_KEY'] = df_gps[col_placa].apply(lambda x: match_tecnico_inteligente(x, tecnicos_unicos))
                df_gps_valid = df_gps.dropna(subset=['TEC_KEY'])

                # Extraer tiempos diarios por técnico
                for (tec, fecha), sub_df in df_gps_valid.groupby(['TEC_KEY', 'Fecha_Salida']):
                    primer_salida = sub_df['Hora_Salida_DT'].min()
                    # Buscar última entrada del mismo día
                    sub_ent = df_gps_valid[(df_gps_valid['TEC_KEY'] == tec) & (df_gps_valid['Fecha_Ingreso'] == fecha)]
                    ult_entrada = sub_ent['Hora_Ingreso_DT'].max() if not sub_ent.empty else pd.NaT
                    
                    secs_salida = primer_salida.hour * 3600 + primer_salida.minute * 60 + primer_salida.second if pd.notnull(primer_salida) else None
                    secs_entrada = ult_entrada.hour * 3600 + ult_entrada.minute * 60 + ult_entrada.second if pd.notnull(ult_entrada) else None
                    
                    gps_diario.append({
                        'TÉCNICO': tec,
                        'Fecha': fecha,
                        'Salida_Secs': secs_salida,
                        'Entrada_Secs': secs_entrada,
                        'Salida_Str': primer_salida.strftime('%H:%M:%S') if pd.notnull(primer_salida) else '--',
                        'Entrada_Str': ult_entrada.strftime('%H:%M:%S') if pd.notnull(ult_entrada) else '--'
                    })

                # Calcular promedios para la vista consolidada
                df_gps_diario = pd.DataFrame(gps_diario)
                if not df_gps_diario.empty:
                    for tec, g in df_gps_diario.groupby('TÉCNICO'):
                        prom_salida = g['Salida_Secs'].mean()
                        prom_entrada = g['Entrada_Secs'].mean()
                        gps_consolidado[tec] = {
                            'Salida_Plantel': formatear_segundos_a_hora(prom_salida),
                            'Retorno_Plantel': formatear_segundos_a_hora(prom_entrada)
                        }

        # 3. Procesar Expedientes (Llamados/Faltas)
        faltas_dict = {}
        llamados_dict = {}
        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            
            if col_tec_exp and col_tipo:
                df_exp['TEC_KEY'] = df_exp[col_tec_exp].astype(str).str.upper().str.strip()
                
                def es_falta(tipo_falta):
                    t = str(tipo_falta).upper()
                    return any(k in t for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA'])

                df_exp['Es_Falta'] = df_exp[col_tipo].apply(es_falta)
                
                for tec, sub_df in df_exp.groupby('TEC_KEY'):
                    f_clean = match_tecnico_inteligente(tec, tecnicos_unicos)
                    if f_clean:
                        faltas_dict[f_clean] = int(sub_df['Es_Falta'].sum())
                        llamados_dict[f_clean] = int((~sub_df['Es_Falta']).sum())

        # 4. Consolidar métricas finales
        datos_cons = []
        for tec in tecnicos_unicos:
            df_tec_act = df_act[df_act['TECNICO'] == tec]
            
            total_ord = len(df_tec_act)
            t_prom = df_tec_act['Minutos_Orden'].mean() if total_ord > 0 else 0
            plex_ord = sum(df_tec_act['SEGMENTO'] == 'PLEX')
            res_ord = sum(df_tec_act['SEGMENTO'] == 'RESIDENCIAL')
            
            primera_ord_dt = df_tec_act['FECHA_ENTRADA'].min()
            primera_ord_str = primera_ord_dt.strftime('%H:%M:%S') if pd.notnull(primera_ord_dt) else '--'
            
            gps_data = gps_consolidado.get(tec, {'Salida_Plantel': '--', 'Retorno_Plantel': '--'})
            
            datos_cons.append({
                'TÉCNICO': tec,
                'ÓRDENES EJECUTADAS': int(total_ord),
                'ÓRDENES PLEX': int(plex_ord),
                'ÓRDENES RESIDENCIAL': int(res_ord),
                'TIEMPO PROM. (Min)': round(t_prom, 1),
                'HORA 1ra ORDEN': primera_ord_str,
                'SALIDA PLANTEL (GPS)': gps_data['Salida_Plantel'],
                'RETORNO PLANTEL (GPS)': gps_data['Retorno_Plantel'],
                'DÍAS FALTADOS': int(faltas_dict.get(tec, 0)),
                'LLAMADOS DE ATENCIÓN': int(llamados_dict.get(tec, 0))
            })

        df_consolidado_final = pd.DataFrame(datos_cons)
        df_diario_final = pd.DataFrame(gps_diario) if gps_diario else pd.DataFrame()
        
        return df_consolidado_final, df_diario_final, "Procesamiento completado con éxito."
    except Exception as e:
        return None, None, f"Error en procesamiento analítico: {e}"

# ==============================================================================
# MÓDULO INTERFAZ STREAMLIT
# ==============================================================================
def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Panel Integral de Rendimiento y Disciplina</h2>", unsafe_allow_html=True)
    st.caption("Consolidación inteligente y cruce de datos: rep_actividades vs. InformeZonasRutas vs. Expedientes de la Nube.")
    st.divider()

    # Carga silenciosa y directa desde GCS para evitar el mensaje de conexión
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
        st.write("Sincronización de Base de Datos:")
        
        # El botón sincroniza directo a GCS evitando requerir 'conn' de Sheets de forma mandatoria
        if st.button("🔄 Sincronizar Expedientes de Nube", use_container_width=True):
            with st.spinner("Conectando con Google Cloud Storage..."):
                try:
                    df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                    if df is not None and not df.empty:
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ Datos sincronizados directamente desde GCS.")
                        time.sleep(1)
                        st.rerun()
                    elif conn:
                        df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ Sincronizado mediante Google Sheets.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ No se detectaron credenciales ni conexión activa de GCS/Sheets.")
                except Exception as e:
                    st.error(f"❌ Error durante la sincronización: {e}")
                
        if st.session_state.get('df_exp_memoria') is not None:
            st.success(f"Archivados: {len(st.session_state['df_exp_memoria'])} registros.")

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
                    df_act_raw = read_file_robust_local(file_act)
                    df_gps_raw = read_file_robust_local(file_gps) if file_gps else None
                    df_exp_raw = st.session_state.get('df_exp_memoria', None)

                    # Ejecución del cruce analítico avanzado
                    df_consolidado, df_diario, msg = procesar_rendimiento_avanzado(df_act_raw, df_gps_raw, df_exp_raw)
                    
                    if df_consolidado is not None:
                        st.session_state['df_rendimiento_integral'] = df_consolidado
                        st.session_state['df_gps_diario_integral'] = df_diario
                        st.success("✅ Análisis general consolidado con éxito.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"No se pudo procesar: {msg}")
                except Exception as e:
                    st.error(f"Ocurrió un error inesperado durante el procesamiento: {e}")

    # ==========================================================
    # 3. DASHBOARD Y VISUALIZACIÓN DE RESULTADOS
    # ==========================================================
    if 'df_rendimiento_integral' in st.session_state:
        df_res = st.session_state['df_rendimiento_integral'].copy()
        df_dia_gps = st.session_state.get('df_gps_diario_integral', pd.DataFrame())
        
        st.markdown("---")
        
        # Pestañas de Vista (Consolidado vs Detalle Diario)
        tab_consolidada, tab_diaria = st.tabs(["📅 Vista Consolidada (4 Semanas)", "🔍 Detalle Diario (Auditoría GPS)"])
        
        with tab_consolidada:
            st.markdown("### 🏆 Tablero de Rendimiento General")
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            with kpi1:
                st.metric("👥 Técnicos Evaluados", len(df_res))
            with kpi2:
                total_ord = df_res['ÓRDENES EJECUTADAS'].sum() if 'ÓRDENES EJECUTADAS' in df_res.columns else 0
                st.metric("📦 Órdenes Totales", int(total_ord))
            with kpi3:
                promedio_tiempo = df_res['TIEMPO PROM. (Min)'].mean() if 'TIEMPO PROM. (Min)' in df_res.columns else 0
                st.metric("⏳ Promedio de Orden", f"{round(promedio_tiempo, 1)} Min")
            with kpi4:
                dias_faltados = df_res['DÍAS FALTADOS'].sum() if 'DÍAS FALTADOS' in df_res.columns else 0
                llamados_atencion = df_res['LLAMADOS DE ATENCIÓN'].sum() if 'LLAMADOS DE ATENCIÓN' in df_res.columns else 0
                total_incidencias = int(dias_faltados + llamados_atencion)
                st.metric("🚨 Total Incidencias", total_incidencias)
                
            st.markdown("<br>", unsafe_allow_html=True)
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_tec = st.multiselect("👤 Filtrar por Técnico:", options=sorted(df_res['TÉCNICO'].unique()), key="filter_consolidado")
            with col_f2:
                st.markdown("<br>", unsafe_allow_html=True)
                ver_con_faltas = st.checkbox("🚨 Mostrar solo técnicos con incidencias (Faltas o Llamados de Atención)", key="chk_consolidado")
                
            if filtro_tec:
                df_res = df_res[df_res['TÉCNICO'].isin(filtro_tec)]
            if ver_con_faltas:
                cond_inc = (df_res['DÍAS FALTADOS'] > 0) | (df_res['LLAMADOS DE ATENCIÓN'] > 0)
                df_res = df_res[cond_inc]
                
            def alert_style(row):
                has_faltas = row.get('DÍAS FALTADOS', 0)
                has_llamados = row.get('LLAMADOS DE ATENCIÓN', 0)
                try:
                    val_faltas = int(float(has_faltas)) if pd.notna(has_faltas) else 0
                    val_llamados = int(float(has_llamados)) if pd.notna(has_llamados) else 0
                except:
                    val_faltas = 0
                    val_llamados = 0
                if val_faltas > 0 or val_llamados > 0:
                    return ['background-color: #fee2e2; color: #991b1b; font-weight: bold'] * len(row)
                return [''] * len(row)

            st.dataframe(df_res.style.apply(alert_style, axis=1), use_container_width=True, hide_index=True)
            
            # Exportar reporte PDF
            st.markdown("<br>", unsafe_allow_html=True)
            col_dl1, _ = st.columns([1, 2])
            with col_dl1:
                try:
                    pdf_data = generar_pdf_rendimiento_integral(df_res)
                    if pdf_data:
                        st.download_button(
                            label="📄 Descargar Consolidado (PDF)",
                            data=pdf_data,
                            file_name="Consolidado_Rendimiento.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                except Exception as e:
                    st.warning(f"No se pudo generar PDF: {e}")

        with tab_diaria:
            st.markdown("### 🔍 Auditoría Diaria de Tiempos y GPS")
            if not df_dia_gps.empty:
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    lista_fechas = sorted(df_dia_gps['Fecha'].dropna().unique())
                    fecha_sel = st.selectbox("📅 Seleccione el día a auditar:", options=lista_fechas, format_func=lambda x: x.strftime('%d/%m/%Y'))
                
                df_dia_fil = df_dia_gps[df_dia_gps['Fecha'] == fecha_sel].copy()
                
                with col_d2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    lista_tecs_dia = sorted(df_dia_fil['TÉCNICO'].unique())
                    filtro_tec_dia = st.multiselect("👤 Filtrar Técnicos para este día:", options=lista_tecs_dia)
                    
                if filtro_tec_dia:
                    df_dia_fil = df_dia_fil[df_dia_fil['TÉCNICO'].isin(filtro_tec_dia)]
                    
                df_dia_tabla = df_dia_fil[['TÉCNICO', 'Salida_Str', 'Entrada_Str']].copy()
                df_dia_tabla.columns = ['TÉCNICO', 'HORA SALIDA PLANTEL (GPS)', 'HORA RETORNO PLANTEL (GPS)']
                
                st.dataframe(df_dia_tabla, use_container_width=True, hide_index=True)
            else:
                st.info("💡 Por favor, suba el archivo 'InformeZonasRutas' para habilitar el detalle diario por GPS.")
