import streamlit as st
import pandas as pd
import time
from datetime import datetime, date
import io
import re
import unicodedata
import plotly.express as px

# Importaciones seguras de dependencias desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
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
            if i != 0: cols.iat[idx] = f"{dup}_{i}"
    df.columns = cols
    return df

def read_file_robust_local(uploaded_file):
    filename = uploaded_file.name.lower()
    uploaded_file.seek(0)
    content = uploaded_file.read()
    uploaded_file.seek(0)
    
    if filename.endswith('.xlsx') or filename.endswith('.xlsm'):
        try: return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='openpyxl'))
        except: pass

    es_zip_binario = content.startswith(b'PK\x03\x04')
    if not es_zip_binario and (b'<table' in content.lower() or b'<html' in content.lower()):
        try:
            dfs = pd.read_html(io.BytesIO(content))
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
        
    if conn is not None:
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            st.session_state['df_exp_memoria'] = df
            return df
        except: pass
    return None

# ==============================================================================
# DEPURACIÓN Y EMPAREJAMIENTO DE NOMBRES / MX
# ==============================================================================
def limpiar_texto_nombres(texto):
    if pd.isna(texto): return ""
    t = str(texto).upper().strip()
    t = re.sub(r'\(.*?\)', '', t)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('utf-8')
    t = re.sub(r'[^A-Z\s]', '', t)
    return " ".join(t.split())

def extraer_numero_mx(texto):
    if pd.isna(texto) or not str(texto).strip(): return None
    val = str(texto).upper().strip()
    match = re.search(r'MX[-_ ]*(\d+)', val)
    if match: return int(match.group(1))
    match_num = re.search(r'^\s*(\d+)\s*$', val)
    if match_num: return int(match_num.group(1))
    return None

def encontrar_tecnico_maestro(placa_gps, tec_to_mx, lista_maestros_limpios, lista_original):
    # 1. Intentar buscar por MX (El método más exacto para el GPS)
    mx_val = extraer_numero_mx(placa_gps)
    if mx_val is not None and mx_val in tec_to_mx:
        return tec_to_mx[mx_val]
        
    # 2. Intentar buscar por similitud de texto
    n_buscar = limpiar_texto_nombres(placa_gps)
    if not n_buscar: return None
    
    tokens_buscar = set(n_buscar.split())
    mejor_match, max_score = None, 0
    
    for i, m_limpio in enumerate(lista_maestros_limpios):
        tokens_maestro = set(m_limpio.split())
        score = len(tokens_buscar.intersection(tokens_maestro))
        if score > max_score:
            max_score = score
            mejor_match = lista_original[i]
            
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
        
        # Filtros importantes de limpieza operativa
        df_act = df_act[df_act['TECNICO'].notna() & (df_act['TECNICO'].str.strip() != '') & (df_act['TECNICO'] != 'N/D')]
        df_act = df_act[~df_act['ACTIVIDAD'].astype(str).str.upper().str.contains('ACTUALIZARDATOSTECNICOS')]
        
        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
        
        # Segmentación PLEX vs Residencial
        act_upper = df_act['ACTIVIDAD'].fillna('').astype(str).str.upper()
        cli_upper = df_act['CLIENTE'].fillna('').astype(str).str.upper()
        com_upper = df_act['COMENTARIO'].fillna('').astype(str).str.upper()
        texto_seg = act_upper + " " + cli_upper + " " + com_upper
        df_act['SEGMENTO'] = ['PLEX' if any(x in t for x in ['PLEX', 'PEXTERNO', 'SPLITTEROPT']) else 'RESIDENCIAL' for t in texto_seg]

        tecnicos_originales = df_act['TECNICO'].unique()
        tecnicos_limpios = [limpiar_texto_nombres(t) for t in tecnicos_originales]

        # Crear diccionario de vehículos (MX)
        tec_to_mx = {}
        col_mx = next((c for c in df_act.columns if 'MX' in str(c).upper()), None)
        if col_mx:
            for _, r in df_act.dropna(subset=[col_mx]).groupby('TECNICO').first().reset_index().iterrows():
                m_val = extraer_numero_mx(r[col_mx])
                if m_val is not None: tec_to_mx[m_val] = r['TECNICO']

        # Cálculo de tiempo invertido
        tiempo_mins = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Tiempo_Ejecucion'] = tiempo_mins.apply(lambda x: x if pd.notnull(x) and x > 0 else 0)

        resumen_act = df_act.groupby('TECNICO').agg(
            Ordenes_Totales=('NUM', 'count'),
            Ordenes_Plex=('SEGMENTO', lambda x: (x == 'PLEX').sum()),
            Ordenes_Res=('SEGMENTO', lambda x: (x == 'RESIDENCIAL').sum()),
            Minutos_Promedio=('Tiempo_Ejecucion', lambda x: x[x > 0].mean() if len(x[x > 0]) > 0 else 0),
            Hora_Primera_Orden=('FECHA_ENTRADA', 'min')
        ).reset_index()

        # Extraer Actividades (Tipos de Orden) para Gráfico
        df_tipos_orden = df_act.groupby('ACTIVIDAD')['NUM'].count().reset_index().sort_values('NUM', ascending=False)

        # --- 2. PROCESAR GPS ---
        gps_consolidado = []
        if df_gps is not None and not df_gps.empty:
            df_gps.columns = [str(c).strip().upper().replace('"', '').replace("'", "") for c in df_gps.columns]
            col_placa = next((c for c in df_gps.columns if 'PLACA' in c or 'ALIAS' in c), None)
            col_in = next((c for c in df_gps.columns if 'INGRESO' in c or 'LLEGADA' in c or 'ENTRADA' in c), None)
            col_out = next((c for c in df_gps.columns if 'SALIDA' in c), None)
            col_fecha = next((c for c in df_gps.columns if 'FECHA' in c), None)

            if col_placa and col_in and col_out:
                df_gps['TEC_MAESTRO'] = df_gps[col_placa].apply(lambda x: encontrar_tecnico_maestro(x, tec_to_mx, tecnicos_limpios, tecnicos_originales))
                df_gps_valid = df_gps.dropna(subset=['TEC_MAESTRO']).copy()

                # Arreglo Inteligente de Fechas
                if col_fecha:
                    df_gps_valid['Fecha_Real'] = pd.to_datetime(df_gps_valid[col_fecha], errors='coerce', dayfirst=True).dt.date
                else:
                    df_gps_valid['Fecha_Real'] = pd.to_datetime(df_gps_valid[col_out], errors='coerce').dt.date
                
                # Descartar fechas 1970
                df_gps_valid.loc[df_gps_valid['Fecha_Real'] == pd.Timestamp('1970-01-01').date(), 'Fecha_Real'] = pd.NaT

                df_gps_valid['Hora_Out_DT'] = pd.to_datetime(df_gps_valid[col_out], errors='coerce')
                df_gps_valid['Hora_In_DT'] = pd.to_datetime(df_gps_valid[col_in], errors='coerce')

                for (tec, fecha), sub_df in df_gps_valid.dropna(subset=['Fecha_Real']).groupby(['TEC_MAESTRO', 'Fecha_Real']):
                    p_salida = sub_df['Hora_Out_DT'].min()
                    u_llegada = sub_df['Hora_In_DT'].max()
                    
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
        faltas_dict, llamados_dict = {}, {}
        df_exp_detallado = pd.DataFrame()
        
        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            
            if col_tec_exp and col_tipo:
                df_exp['TEC_MAESTRO'] = df_exp[col_tec_exp].apply(lambda x: encontrar_tecnico_maestro(x, tec_to_mx, tecnicos_limpios, tecnicos_originales))
                df_exp_detallado = df_exp.dropna(subset=['TEC_MAESTRO']).copy()
                
                def es_falta(t): return any(k in str(t).upper() for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA'])
                df_exp_detallado['ES_FALTA'] = df_exp_detallado[col_tipo].apply(es_falta)
                
                for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                    faltas_dict[tec] = int(g['ES_FALTA'].sum())
                    llamados_dict[tec] = int((~g['ES_FALTA']).sum())

        # --- 4. CONSOLIDAR EN LA TABLA MAESTRA ---
        datos_finales = []
        for _, row in resumen_act.iterrows():
            tec = row['TECNICO']
            h_primera = row['Hora_Primera_Orden'].strftime('%H:%M:%S') if pd.notnull(row['Hora_Primera_Orden']) else '--'
            gps = gps_promedios.get(tec, {'Salida': '--', 'Entrada': '--'})
            
            datos_finales.append({
                'TÉCNICO': tec,
                'TOTAL ÓRDENES': int(row['Ordenes_Totales']),
                'PLEX': int(row['Ordenes_Plex']),
                'RESIDENCIAL': int(row['Ordenes_Res']),
                'TIEMPO PROM. (Min)': round(row['Minutos_Promedio'], 1),
                'HORA 1ra ORDEN': h_primera,
                'SALIDA PLANTEL (GPS)': gps['Salida'],
                'ENTRADA PLANTEL (GPS)': gps['Entrada'],
                'DÍAS FALTADOS': int(faltas_dict.get(tec, 0)),
                'LLAMADOS ATENCIÓN': int(llamados_dict.get(tec, 0))
            })

        return pd.DataFrame(datos_finales), df_gps_diario, df_exp_detallado, df_tipos_orden, "Exitoso"
    except Exception as e:
        return None, None, None, None, f"Error: {e}"

# ==============================================================================
# INTERFAZ STREAMLIT (DASHBOARD)
# ==============================================================================
def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Dashboard de Rendimiento Integral</h2>", unsafe_allow_html=True)
    st.caption("Cruce perfeccionado: Órdenes (Plex/Res) + Rutas GPS Reales + Nube Disciplinaria")
    st.divider()

    obtener_datos_expedientes(conn)

    # ================= 1. CARGA DE ARCHIVOS =================
    st.markdown("#### 📥 Carga de Archivos Base")
    c1, c2, c3 = st.columns(3)
    with c1: act_file = st.file_uploader("1. rep_actividades", type=['csv', 'xlsx'])
    with c2: gps_file = st.file_uploader("2. InformeZonasRutas", type=['csv', 'xlsx'])
    with c3:
        st.write("3. Base de Datos Nube")
        if st.button("🔄 Sincronizar Expedientes", use_container_width=True):
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
            with st.spinner("🤖 Depurando placas vehiculares, fechas y cruzando bases de datos..."):
                df_act = read_file_robust_local(act_file)
                df_gps = read_file_robust_local(gps_file) if gps_file else None
                df_exp = st.session_state.get('df_exp_memoria', None)

                df_maestra, df_diario, df_disciplina, df_tipos, msg = procesar_rendimiento_avanzado(df_act, df_gps, df_exp)
                
                if df_maestra is not None:
                    st.session_state['rs_maestra'] = df_maestra
                    st.session_state['rs_diario'] = df_diario
                    st.session_state['rs_disciplina'] = df_disciplina
                    st.session_state['rs_tipos'] = df_tipos
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
        df_tipos = st.session_state.get('rs_tipos', pd.DataFrame())

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
            k1.metric("👥 Técnicos", len(df_m))
            k2.metric("📦 Total Órdenes", df_m['TOTAL ÓRDENES'].sum())
            k3.metric("⏳ Promedio (Min)", round(df_m['TIEMPO PROM. (Min)'].mean(), 1))
            k4.metric("🚨 Incidencias", df_m['DÍAS FALTADOS'].sum() + df_m['LLAMADOS ATENCIÓN'].sum())
            
            st.markdown("---")
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                # 1. Gráfico Segmentado PLEX vs RESIDENCIAL
                df_segmentado = df_m[['TÉCNICO', 'PLEX', 'RESIDENCIAL']].melt(id_vars='TÉCNICO', var_name='Segmento', value_name='Cantidad')
                df_segmentado = df_segmentado[df_segmentado['Cantidad'] > 0]
                
                # Calcular el total para ordenar el gráfico
                orden_tecnicos = df_m.sort_values('TOTAL ÓRDENES', ascending=True)['TÉCNICO'].tolist()
                
                fig_ord = px.bar(df_segmentado, x='Cantidad', y='TÉCNICO', color='Segmento', orientation='h',
                                 title="📦 Productividad (PLEX vs Residencial)", text_auto=True, 
                                 color_discrete_map={'PLEX': '#8B5CF6', 'RESIDENCIAL': '#10B981'})
                fig_ord.update_yaxes(categoryorder='array', categoryarray=orden_tecnicos)
                fig_ord.update_layout(height=450, yaxis_title="")
                st.plotly_chart(fig_ord, use_container_width=True)

            with col_g2:
                # 2. Gráfico Tipos de Orden
                if not df_tipos.empty:
                    top_tipos = df_tipos.head(7) # Mostramos el Top 7 de actividades
                    fig_tipos = px.pie(top_tipos, values='NUM', names='ACTIVIDAD', hole=0.4, 
                                       title="📋 Tipos de Ordenes (Top Actividades Generales)", 
                                       color_discrete_sequence=px.colors.sequential.Teal)
                    fig_tipos.update_traces(textposition='inside', textinfo='percent+label')
                    fig_tipos.update_layout(height=450, showlegend=False)
                    st.plotly_chart(fig_tipos, use_container_width=True)

            # 3. Gráfico de Tiempo
            st.markdown("<br>", unsafe_allow_html=True)
            fig_time = px.bar(df_m.sort_values('TIEMPO PROM. (Min)', ascending=False), 
                             x='TIEMPO PROM. (Min)', y='TÉCNICO', orientation='h',
                             title="⏳ Tiempo Promedio Invertido en Órdenes (Minutos)", text_auto='.1f', color_discrete_sequence=['#3B82F6'])
            fig_time.update_layout(height=400, yaxis_title="")
            st.plotly_chart(fig_time, use_container_width=True)

        # --- TAB 2: TABLA MAESTRA INTEGRAL ---
        with tab_maestra:
            st.markdown("### 📋 Vista Consolidada General")
            def highlight_incidencias(row):
                if row['DÍAS FALTADOS'] > 0 or row['LLAMADOS ATENCIÓN'] > 0:
                    return ['background-color: #fee2e2; color: #991b1b'] * len(row)
                return [''] * len(row)

            st.dataframe(df_m.style.apply(highlight_incidencias, axis=1), use_container_width=True, hide_index=True)

            try:
                pdf_bytes = generar_pdf_rendimiento_integral(df_m)
                if pdf_bytes:
                    st.download_button("📄 Descargar Reporte PDF", data=pdf_bytes, file_name="Reporte_Gerencial.pdf", mime="application/pdf", type="primary")
            except: pass

        # --- TAB 3: TIEMPOS GPS DIARIOS ---
        with tab_gps:
            st.markdown("### 📍 Auditoría GPS de Salidas y Entradas")
            if not df_d.empty:
                df_d_fil = df_d[df_d['TECNICO'].isin(tec_filtro)] if tec_filtro else df_d
                fechas = [f for f in df_d_fil['Fecha'].unique() if pd.notnull(f)]
                
                if fechas:
                    # Nuevo Calendario Normal y Funcional
                    fecha_sel = st.date_input("📅 Seleccione la fecha a auditar:", value=fechas[-1], min_value=min(fechas), max_value=max(fechas))
                    
                    df_d_show = df_d_fil[df_d_fil['Fecha'] == fecha_sel][['TECNICO', 'Salida_Str', 'Entrada_Str']]
                    df_d_show.columns = ['TÉCNICO', 'SALIDA DEL PLANTEL (GPS)', 'RETORNO AL PLANTEL (GPS)']
                    st.dataframe(df_d_show, use_container_width=True, hide_index=True)
                else:
                    st.warning("⚠️ El archivo GPS contiene tiempos, pero no se detectaron fechas válidas en el formato.")
            else:
                st.info("Sube el archivo GPS para activar la auditoría diaria.")

        # --- TAB 4: REGISTRO DISCIPLINARIO ---
        with tab_exp:
            st.markdown("### 🚨 Detalle de Incidencias y Faltas")
            if df_exp_det is not None and not df_exp_det.empty:
                df_e_fil = df_exp_det[df_exp_det['TEC_MAESTRO'].isin(tec_filtro)] if tec_filtro else df_exp_det
                if not df_e_fil.empty:
                    cols_mostrar = [c for c in df_e_fil.columns if c not in ['TEC_MAESTRO', 'ES_FALTA']]
                    st.dataframe(df_e_fil[cols_mostrar], use_container_width=True, hide_index=True)
                else:
                    st.success("✨ ¡Excelente! Los técnicos seleccionados tienen un expediente limpio.")
            else:
                st.info("Sin registros disciplinarios.")
