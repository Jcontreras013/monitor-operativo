import streamlit as st
import pandas as pd
import time
from datetime import datetime
import io
import re
import unicodedata
import plotly.express as px
import plotly.graph_objects as go

# Importaciones seguras de dependencias desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
        procesar_fechas_seguro,
        generar_pdf_rendimiento_integral,
        leer_espejo_gcs,
        get_honduras_time
    )
except ImportError as e:
    st.error(f"Error al importar módulos de soporte desde tools.py: {e}")

NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# MOTOR DE LECTURA DE ARCHIVOS
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
            return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='openpyxl'))
        except: pass

    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='xlrd'))
        except: pass

    es_zip_binario = content.startswith(b'PK\x03\x04')
    if not es_zip_binario and (b'<table' in content.lower() or b'<html' in content.lower()):
        try:
            dfs = pd.read_html(io.BytesIO(content))
            if dfs: return forzar_columnas_unicas_local(max(dfs, key=len))
        except:
            try:
                dfs = pd.read_html(io.BytesIO(content), encoding='latin-1')
                if dfs: return forzar_columnas_unicas_local(max(dfs, key=len))
            except: pass

    uploaded_file.seek(0)
    try: return forzar_columnas_unicas_local(pd.read_excel(uploaded_file))
    except: pass

    uploaded_file.seek(0)
    try: return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip'))
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='latin-1', on_bad_lines='skip'))

# ==============================================================================
# GESTIÓN DE EXPEDIENTES (CONEXIÓN ROBUSTA)
# ==============================================================================
def obtener_datos_expedientes(conn):
    if 'df_exp_memoria' not in st.session_state:
        st.session_state['df_exp_memoria'] = None

    if st.session_state['df_exp_memoria'] is not None:
        return st.session_state['df_exp_memoria']
        
    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
        if df is not None and not df.empty:
            st.session_state['df_exp_memoria'] = df
            return df
    except: pass
        
    if conn is None:
        try:
            from streamlit_gsheets import GSheetsConnection
            conn = st.connection("gsheets", type=GSheetsConnection)
        except: pass
            
    if conn is not None:
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            st.session_state['df_exp_memoria'] = df
            return df
        except: pass
            
    return None

# ==============================================================================
# MOTOR SUPERIOR DE DEPURACIÓN Y EMPAREJAMIENTO DE NOMBRES
# ==============================================================================
def limpiar_texto_nombres(texto):
    """Limpia acentos, caracteres raros y deja solo letras mayúsculas para comparar."""
    if pd.isna(texto): return ""
    t = str(texto).upper().strip()
    # Quitar paréntesis y contenido
    t = re.sub(r'\(.*?\)', '', t)
    # Normalizar acentos (á -> a)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('utf-8')
    # Dejar solo letras y espacios
    t = re.sub(r'[^A-Z\s]', '', t)
    return " ".join(t.split())

def encontrar_tecnico_maestro(nombre_buscar, lista_maestros_limpios, lista_original):
    """Encuentra el nombre del técnico evaluando qué tantas palabras coinciden."""
    n_buscar = limpiar_texto_nombres(nombre_buscar)
    if not n_buscar: return None
    
    tokens_buscar = set(n_buscar.split())
    mejor_match = None
    max_score = 0
    
    for i, m_limpio in enumerate(lista_maestros_limpios):
        tokens_maestro = set(m_limpio.split())
        # Contar cuántas palabras comparten (Ej: "Juan Perez" y "Perez Juan" comparten 2)
        score = len(tokens_buscar.intersection(tokens_maestro))
        
        if score > max_score:
            max_score = score
            mejor_match = lista_original[i]
            
    # Si al menos 1 palabra clave (nombre o apellido) coincide, lo damos por bueno
    return mejor_match if max_score >= 1 else None

# ==============================================================================
# PROCESAMIENTO ANALÍTICO CENTRAL
# ==============================================================================
def formatear_hora(secs):
    if pd.isna(secs) or secs is None or secs <= 0: return "--"
    h = int(secs // 3600) % 24
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def procesar_rendimiento_avanzado(df_act, df_gps, df_exp):
    try:
        # --- 1. PROCESAR ÓRDENES (ACTIVIDADES) ---
        df_act = procesar_dataframe_base(df_act)
        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
        
        # Eliminar registros sin técnico
        df_act = df_act[df_act['TECNICO'].notna() & (df_act['TECNICO'].str.strip() != '') & (df_act['TECNICO'] != 'N/D')]
        
        # Base de nombres maestros (El catálogo oficial de técnicos)
        tecnicos_originales = df_act['TECNICO'].unique()
        tecnicos_limpios = [limpiar_texto_nombres(t) for t in tecnicos_originales]

        df_act['Minutos_Orden'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos_Orden'] = df_act['Minutos_Orden'].apply(lambda x: x if x > 0 else 0)

        # Extraer métricas de órdenes
        resumen_act = df_act.groupby('TECNICO').agg(
            Ordenes_Totales=('NUM', 'count'),
            Minutos_Promedio=('Minutos_Orden', 'mean'),
            Hora_Primera_Orden=('FECHA_ENTRADA', 'min')
        ).reset_index()

        # --- 2. PROCESAR GPS ---
        gps_consolidado = []
        if df_gps is not None and not df_gps.empty:
            df_gps.columns = [str(c).strip().upper().replace('"', '').replace("'", "") for c in df_gps.columns]
            col_placa = next((c for c in df_gps.columns if 'PLACA' in c or 'ALIAS' in c), None)
            col_in = next((c for c in df_gps.columns if 'INGRESO' in c or 'LLEGADA' in c), None)
            col_out = next((c for c in df_gps.columns if 'SALIDA' in c), None)

            if col_placa and col_in and col_out:
                df_gps['DT_IN'] = pd.to_datetime(df_gps[col_in], errors='coerce')
                df_gps['DT_OUT'] = pd.to_datetime(df_gps[col_out], errors='coerce')
                df_gps['Fecha'] = df_gps['DT_OUT'].dt.date
                
                # Asignar técnico con Motor de Inteligencia Textual
                df_gps['TEC_MAESTRO'] = df_gps[col_placa].apply(lambda x: encontrar_tecnico_maestro(x, tecnicos_limpios, tecnicos_originales))
                df_gps_valid = df_gps.dropna(subset=['TEC_MAESTRO'])

                for (tec, fecha), sub_df in df_gps_valid.groupby(['TEC_MAESTRO', 'Fecha']):
                    p_salida = sub_df['DT_OUT'].min()
                    u_llegada = sub_df['DT_IN'].max()
                    
                    s_salida = p_salida.hour * 3600 + p_salida.minute * 60 + p_salida.second if pd.notnull(p_salida) else None
                    s_llegada = u_llegada.hour * 3600 + u_llegada.minute * 60 + u_llegada.second if pd.notnull(u_llegada) else None
                    
                    gps_consolidado.append({
                        'TECNICO': tec, 'Fecha': fecha,
                        'Salida_Secs': s_salida, 'Entrada_Secs': s_llegada,
                        'Salida_Str': p_salida.strftime('%H:%M:%S') if pd.notnull(p_salida) else '--',
                        'Entrada_Str': u_llegada.strftime('%H:%M:%S') if pd.notnull(u_llegada) else '--'
                    })

        df_gps_diario = pd.DataFrame(gps_consolidado)
        gps_promedios = {}
        if not df_gps_diario.empty:
            for tec, g in df_gps_diario.groupby('TECNICO'):
                p_sal = g['Salida_Secs'].dropna().mean()
                p_ent = g['Entrada_Secs'].dropna().mean()
                gps_promedios[tec] = {
                    'Salida': formatear_hora(p_sal) if pd.notnull(p_sal) else '--',
                    'Entrada': formatear_hora(p_ent) if pd.notnull(p_ent) else '--'
                }

        # --- 3. PROCESAR EXPEDIENTES (FALTAS Y LLAMADOS) ---
        faltas_dict = {}
        llamados_dict = {}
        df_exp_detallado = pd.DataFrame()
        
        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            
            if col_tec_exp and col_tipo:
                # Filtrar y emparejar
                df_exp['TEC_MAESTRO'] = df_exp[col_tec_exp].apply(lambda x: encontrar_tecnico_maestro(x, tecnicos_limpios, tecnicos_originales))
                df_exp_detallado = df_exp.dropna(subset=['TEC_MAESTRO']).copy()
                
                def es_falta(t): return any(k in str(t).upper() for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA'])
                df_exp_detallado['ES_FALTA'] = df_exp_detallado[col_tipo].apply(es_falta)
                
                for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                    faltas_dict[tec] = int(g['ES_FALTA'].sum())
                    llamados_dict[tec] = int((~g['ES_FALTA']).sum())

        # --- 4. CONSOLIDAR TODO EN LA TABLA MAESTRA ---
        datos_finales = []
        for _, row in resumen_act.iterrows():
            tec = row['TECNICO']
            h_primera = row['Hora_Primera_Orden'].strftime('%H:%M:%S') if pd.notnull(row['Hora_Primera_Orden']) else '--'
            gps = gps_promedios.get(tec, {'Salida': '--', 'Entrada': '--'})
            
            datos_finales.append({
                'TÉCNICO': tec,
                'ÓRDENES CANTIDAD': int(row['Ordenes_Totales']),
                'TIEMPO PROM. EN ORDEN (Min)': round(row['Minutos_Promedio'], 1),
                'HORA 1ra ORDEN': h_primera,
                'SALIDA PLANTEL (GPS)': gps['Salida'],
                'ENTRADA PLANTEL (GPS)': gps['Entrada'],
                'DÍAS FALTADOS': int(faltas_dict.get(tec, 0)),
                'LLAMADOS ATENCIÓN': int(llamados_dict.get(tec, 0))
            })

        return pd.DataFrame(datos_finales), df_gps_diario, df_exp_detallado, "Exitoso"
    except Exception as e:
        return None, None, None, f"Error: {e}"

# ==============================================================================
# INTERFAZ STREAMLIT (DASHBOARD)
# ==============================================================================
def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Dashboard de Rendimiento Integral</h2>", unsafe_allow_html=True)
    st.caption("Depuración Inteligente: Órdenes + GPS + Expedientes Laborales")
    st.divider()

    obtener_datos_expedientes(conn)

    # ================= 1. CARGA DE ARCHIVOS =================
    st.markdown("#### 📥 Carga de Archivos Base")
    c1, c2, c3 = st.columns(3)
    with c1: act_file = st.file_uploader("1. rep_actividades (Órdenes)", type=['csv', 'xlsx'])
    with c2: gps_file = st.file_uploader("2. InformeZonasRutas (GPS)", type=['csv', 'xlsx'])
    with c3:
        st.write("3. Base de Datos Nube")
        if st.button("🔄 Sincronizar Expedientes"):
            with st.spinner("Conectando..."):
                if conn:
                    try:
                        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        if df is None or df.empty: df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ BD Sincronizada.")
                        time.sleep(1); st.rerun()
                    except Exception as e: st.error(e)
                else: st.error("Sin conexión.")
        if st.session_state.get('df_exp_memoria') is not None:
            st.success(f"Expedientes listos ({len(st.session_state['df_exp_memoria'])} reg.)")

    st.markdown("<br>", unsafe_allow_html=True)

    # ================= 2. BOTÓN DE EJECUCIÓN =================
    if st.button("🚀 INICIAR ANÁLISIS CRUZADO", type="primary", use_container_width=True):
        if act_file:
            with st.spinner("🤖 Depurando nombres de técnicos y cruzando bases de datos..."):
                df_act = read_file_robust_local(act_file)
                df_gps = read_file_robust_local(gps_file) if gps_file else None
                df_exp = st.session_state.get('df_exp_memoria', None)

                df_maestra, df_diario, df_disciplina, msg = procesar_rendimiento_avanzado(df_act, df_gps, df_exp)
                
                if df_maestra is not None:
                    st.session_state['rs_maestra'] = df_maestra
                    st.session_state['rs_diario'] = df_diario
                    st.session_state['rs_disciplina'] = df_disciplina
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.warning("Debe subir al menos el archivo 'rep_actividades'.")

    # ================= 3. VISUALIZACIÓN DEL DASHBOARD =================
    if 'rs_maestra' in st.session_state:
        df_m = st.session_state['rs_maestra'].copy()
        df_d = st.session_state['rs_diario']
        df_exp_det = st.session_state['rs_disciplina']

        # Filtro global
        tecs_disp = sorted(df_m['TÉCNICO'].unique())
        tec_filtro = st.multiselect("🔍 Filtrar Técnico(s) para todo el reporte:", tecs_disp)
        if tec_filtro:
            df_m = df_m[df_m['TÉCNICO'].isin(tec_filtro)]

        # --- PESTAÑAS DEL DASHBOARD ---
        tab_graficos, tab_maestra, tab_gps, tab_exp = st.tabs([
            "📈 Gráficos y KPIs", 
            "📋 Tabla Maestra Integral", 
            "📍 Tiempos GPS Diarios", 
            "🚨 Registro Disciplinario"
        ])

        # --- TAB 1: GRÁFICOS Y KPIs ---
        with tab_graficos:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("👥 Técnicos Analizados", len(df_m))
            k2.metric("📦 Total Órdenes", df_m['ÓRDENES CANTIDAD'].sum())
            k3.metric("⏳ Promedio Gral (Min)", round(df_m['TIEMPO PROM. EN ORDEN (Min)'].mean(), 1))
            k4.metric("🚨 Total Incidencias", df_m['DÍAS FALTADOS'].sum() + df_m['LLAMADOS ATENCIÓN'].sum())
            
            st.markdown("---")
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                # Gráfico de Órdenes
                fig_ord = px.bar(df_m.sort_values('ÓRDENES CANTIDAD', ascending=True), 
                                 x='ÓRDENES CANTIDAD', y='TÉCNICO', orientation='h',
                                 title="📦 Productividad (Cant. Órdenes)", text_auto=True, color_discrete_sequence=['#10B981'])
                fig_ord.update_layout(height=400, yaxis_title="")
                st.plotly_chart(fig_ord, use_container_width=True)

            with col_g2:
                # Gráfico de Tiempo Promedio
                fig_time = px.bar(df_m.sort_values('TIEMPO PROM. EN ORDEN (Min)', ascending=False), 
                                 x='TIEMPO PROM. EN ORDEN (Min)', y='TÉCNICO', orientation='h',
                                 title="⏳ Tiempo Promedio por Orden (Minutos)", text_auto='.1f', color_discrete_sequence=['#3B82F6'])
                fig_time.update_layout(height=400, yaxis_title="")
                st.plotly_chart(fig_time, use_container_width=True)

            # Gráfico de Incidencias (Solo si hay)
            df_incidencias = df_m[(df_m['DÍAS FALTADOS'] > 0) | (df_m['LLAMADOS ATENCIÓN'] > 0)]
            if not df_incidencias.empty:
                df_melt = df_incidencias.melt(id_vars='TÉCNICO', value_vars=['DÍAS FALTADOS', 'LLAMADOS ATENCIÓN'], var_name='Tipo', value_name='Cantidad')
                fig_inc = px.bar(df_melt, x='TÉCNICO', y='Cantidad', color='Tipo', title="🚨 Mapa de Incidencias Disciplinarias",
                                 color_discrete_map={'DÍAS FALTADOS': '#EF4444', 'LLAMADOS ATENCIÓN': '#F59E0B'}, text_auto=True)
                st.plotly_chart(fig_inc, use_container_width=True)

        # --- TAB 2: TABLA MAESTRA INTEGRAL ---
        with tab_maestra:
            st.markdown("### 📋 Vista Consolidada")
            st.caption("Esta tabla contiene el resumen perfecto del rendimiento y disciplina de cada técnico.")
            
            # Formato condicional (Rojo para incidencias)
            def highlight_incidencias(row):
                if row['DÍAS FALTADOS'] > 0 or row['LLAMADOS ATENCIÓN'] > 0:
                    return ['background-color: #fee2e2; color: #991b1b'] * len(row)
                return [''] * len(row)

            st.dataframe(df_m.style.apply(highlight_incidencias, axis=1), use_container_width=True, hide_index=True)

            # Botón de Descarga
            try:
                pdf_bytes = generar_pdf_rendimiento_integral(df_m)
                if pdf_bytes:
                    st.download_button("📄 Descargar Reporte PDF", data=pdf_bytes, file_name="Reporte_Gerencial.pdf", mime="application/pdf", type="primary")
            except: pass

        # --- TAB 3: TIEMPOS GPS DIARIOS ---
        with tab_gps:
            if not df_d.empty:
                df_d_fil = df_d[df_d['TECNICO'].isin(tec_filtro)] if tec_filtro else df_d
                fechas = sorted(df_d_fil['Fecha'].unique())
                if fechas:
                    fecha_sel = st.selectbox("📅 Seleccione la fecha:", fechas)
                    df_d_show = df_d_fil[df_d_fil['Fecha'] == fecha_sel][['TECNICO', 'Salida_Str', 'Entrada_Str']]
                    df_d_show.columns = ['TÉCNICO', 'SALIDA DEL PLANTEL (GPS)', 'RETORNO AL PLANTEL (GPS)']
                    st.dataframe(df_d_show, use_container_width=True, hide_index=True)
            else:
                st.info("No se subió archivo GPS o no se lograron cruzar los datos de placa/alias.")

        # --- TAB 4: REGISTRO DISCIPLINARIO ---
        with tab_exp:
            if df_exp_det is not None and not df_exp_det.empty:
                df_e_fil = df_exp_det[df_exp_det['TEC_MAESTRO'].isin(tec_filtro)] if tec_filtro else df_exp_det
                if not df_e_fil.empty:
                    # Mostrar las columnas más relevantes de la BD
                    cols_mostrar = [c for c in df_e_fil.columns if c not in ['TEC_MAESTRO', 'ES_FALTA']]
                    st.dataframe(df_e_fil[cols_mostrar], use_container_width=True, hide_index=True)
                else:
                    st.success("✨ ¡Excelente! Los técnicos seleccionados no tienen incidencias ni llamados de atención.")
            else:
                st.info("La base de datos de expedientes está limpia o no ha sido sincronizada.")
