import streamlit as st
import pandas as pd
import io
import re
import unicodedata
import plotly.express as px
import time

# Importaciones seguras de dependencias desde tools.py
try:
    from tools import (
        procesar_dataframe_base,
        generar_pdf_rendimiento_integral,
        leer_espejo_gcs
    )
except ImportError as e:
    st.error(f"Error al importar módulos de soporte desde tools.py: {e}")

NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# MOTOR DE LECTURA Y LIMPIEZA
# ==============================================================================
def forzar_columnas_unicas_local(df):
    if df is None or df.empty: return df
    df.columns = df.columns.astype(str).str.strip().str.upper()
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

    try: return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip'))
    except: 
        uploaded_file.seek(0)
        try: return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='latin-1', on_bad_lines='skip'))
        except: pass
    
    uploaded_file.seek(0)
    try: return forzar_columnas_unicas_local(pd.read_html(io.BytesIO(content))[0])
    except: return None

# ==============================================================================
# CONEXIÓN A RRHH (EXPEDIENTES)
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
# MOTOR SUPER AGRESIVO DE EMPAREJAMIENTO DE NOMBRES
# ==============================================================================
def limpiar_texto(texto):
    if pd.isna(texto): return ""
    t = str(texto).upper().strip()
    t = re.sub(r'[^A-Z0-9\s]', '', unicodedata.normalize('NFD', t).encode('ascii', 'ignore').decode('utf-8'))
    return " ".join(t.split())

def extraer_mx(texto):
    match = re.search(r'MX\s*(\d+)', limpiar_texto(texto))
    return int(match.group(1)) if match else None

def encontrar_tecnico(texto_busqueda, tec_to_mx, lista_maestros):
    if not texto_busqueda: return None
    t_clean = limpiar_texto(texto_busqueda)
    
    # 1. Intentar por código MX
    mx = extraer_mx(t_clean)
    if mx and mx in tec_to_mx:
        return tec_to_mx[mx]
        
    # 2. Intentar por coincidencia de palabras clave (nombres/apellidos)
    palabras_busqueda = set([w for w in t_clean.split() if len(w) > 3])
    mejor_match = None
    max_score = 0
    
    for maestro in lista_maestros:
        palabras_maestro = set([w for w in limpiar_texto(maestro).split() if len(w) > 3])
        score = len(palabras_busqueda.intersection(palabras_maestro))
        if score > max_score:
            max_score = score
            mejor_match = maestro
            
    return mejor_match if max_score > 0 else None

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
        diagnostico = {"gps_huerfanos": [], "exp_huerfanos": []}

        # --- 1. PROCESAR ÓRDENES ---
        df_act = df_act.copy()
        if 'TECNICO' not in df_act.columns:
            return None, None, None, None, "El archivo de actividades no tiene la columna 'TECNICO'."
            
        df_act = df_act[df_act['TECNICO'].notna() & (df_act['TECNICO'].str.strip() != '') & (df_act['TECNICO'] != 'N/D')]
        df_act = df_act[~df_act['ACTIVIDAD'].astype(str).str.upper().str.contains('ACTUALIZARDATOSTECNICOS')]
        
        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
        
        texto_seg = df_act['ACTIVIDAD'].fillna('') + " " + df_act['CLIENTE'].fillna('') + " " + df_act['COMENTARIO'].fillna('')
        texto_seg = texto_seg.astype(str).str.upper()
        df_act['SEGMENTO'] = ['PLEX' if any(x in t for x in ['PLEX', 'PEXTERNO', 'SPLITTEROPT']) else 'RESIDENCIAL' for t in texto_seg]

        tecnicos_maestros = df_act['TECNICO'].unique().tolist()

        # Extraer MX asignados en rep_actividades
        tec_to_mx = {}
        col_mx = next((c for c in df_act.columns if 'MX' in c), None)
        if col_mx:
            for _, r in df_act.dropna(subset=[col_mx]).groupby('TECNICO').first().reset_index().iterrows():
                m_val = extraer_mx(r[col_mx])
                if m_val: tec_to_mx[m_val] = r['TECNICO']

        df_act['Minutos'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos'] = df_act['Minutos'].apply(lambda x: x if pd.notnull(x) and x > 0 else 0)

        df_time_act = df_act[df_act['Minutos'] > 0].groupby(['TECNICO', 'ACTIVIDAD'])['Minutos'].mean().reset_index()
        
        resumen_act = df_act.groupby('TECNICO').agg(
            Ordenes_Totales=('NUM', 'count'),
            Ordenes_Plex=('SEGMENTO', lambda x: (x == 'PLEX').sum()),
            Ordenes_Res=('SEGMENTO', lambda x: (x == 'RESIDENCIAL').sum()),
            Minutos_Promedio=('Minutos', lambda x: x[x > 0].mean() if len(x[x > 0]) > 0 else 0),
        ).reset_index()

        # --- 2. PROCESAR GPS ---
        gps_promedios = {}
        if df_gps is not None and not df_gps.empty:
            col_placa = next((c for c in df_gps.columns if 'PLACA' in c or 'ALIAS' in c), None)
            col_in = next((c for c in df_gps.columns if 'INGRESO' in c or 'LLEGADA' in c), None)
            col_out = next((c for c in df_gps.columns if 'SALIDA' in c), None)

            if col_placa and col_in and col_out:
                # Cruce de nombres con diagnóstico
                def mapear_y_diagnosticar(val):
                    match = encontrar_tecnico(val, tec_to_mx, tecnicos_maestros)
                    if not match: diagnostico["gps_huerfanos"].append(val)
                    return match

                df_gps['TEC_MAESTRO'] = df_gps[col_placa].apply(mapear_y_diagnosticar)
                diagnostico["gps_huerfanos"] = list(set(diagnostico["gps_huerfanos"])) # Limpiar duplicados
                
                df_gps_valid = df_gps.dropna(subset=['TEC_MAESTRO']).copy()
                df_gps_valid['DT_OUT'] = pd.to_datetime(df_gps_valid[col_out], errors='coerce')
                df_gps_valid['DT_IN'] = pd.to_datetime(df_gps_valid[col_in], errors='coerce')
                df_gps_valid = df_gps_valid[df_gps_valid['DT_OUT'].dt.year > 2000].copy()

                df_gps_valid['Fecha_Cal'] = df_gps_valid['DT_OUT'].dt.date
                
                primeras = df_gps_valid.groupby(['TEC_MAESTRO', 'Fecha_Cal'])['DT_OUT'].min().reset_index()
                primeras['Secs'] = primeras['DT_OUT'].dt.hour * 3600 + primeras['DT_OUT'].dt.minute * 60 + primeras['DT_OUT'].dt.second
                prom_sal = primeras.groupby('TEC_MAESTRO')['Secs'].mean().to_dict()

                ultimas = df_gps_valid.groupby(['TEC_MAESTRO', 'Fecha_Cal'])['DT_IN'].max().reset_index()
                ultimas['Secs'] = ultimas['DT_IN'].dt.hour * 3600 + ultimas['DT_IN'].dt.minute * 60 + ultimas['DT_IN'].dt.second
                prom_ent = ultimas.groupby('TEC_MAESTRO')['Secs'].mean().to_dict()

                for tec in tecnicos_maestros:
                    gps_promedios[tec] = {
                        'Salida': formatear_hora(prom_sal.get(tec, None)),
                        'Entrada': formatear_hora(prom_ent.get(tec, None))
                    }

        # --- 3. PROCESAR EXPEDIENTES (RRHH) ---
        faltas_dict = {}
        df_exp_detallado = pd.DataFrame()
        
        if df_exp is not None and not df_exp.empty:
            df_exp.columns = df_exp.columns.astype(str).str.strip().str.upper()
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in c or 'NOMBRE' in c), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO' in c or 'FALTA' in c), None)
            col_com = next((c for c in df_exp.columns if 'COMENTARIO' in c or 'DESC' in c), None)
            
            if col_tec_exp:
                def mapear_exp(val):
                    match = encontrar_tecnico(val, tec_to_mx, tecnicos_maestros)
                    if not match and pd.notnull(val): diagnostico["exp_huerfanos"].append(val)
                    return match

                df_exp['TEC_MAESTRO'] = df_exp[col_tec_exp].apply(mapear_exp)
                diagnostico["exp_huerfanos"] = list(set(diagnostico["exp_huerfanos"]))
                
                df_exp_detallado = df_exp.dropna(subset=['TEC_MAESTRO']).copy()
                
                def escanear_ausencia(row):
                    texto = f"{row.get(col_tipo, '')} {row.get(col_com, '')}".upper()
                    claves = ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'NO SE PRESENT', 'NO ASISTI', 'INCAPACIDAD', 'NO TRABAJO']
                    return any(p in texto for p in claves)

                df_exp_detallado['ES_FALTA'] = df_exp_detallado.apply(escanear_ausencia, axis=1)
                faltas_dict = df_exp_detallado.groupby('TEC_MAESTRO')['ES_FALTA'].sum().to_dict()

        # --- 4. CONSOLIDAR MATRIZ FINAL ---
        datos_finales = []
        for _, row in resumen_act.iterrows():
            tec = row['TECNICO']
            gps = gps_promedios.get(tec, {'Salida': '--', 'Entrada': '--'})
            
            datos_finales.append({
                'TÉCNICO': tec,
                'TOTAL ÓRDENES': int(row['Ordenes_Totales']),
                'PLEX': int(row['Ordenes_Plex']),
                'RESIDENCIAL': int(row['Ordenes_Res']),
                'TIEMPO PROM. (Min)': round(row['Minutos_Promedio'], 1),
                'SALIDA PLANTEL (GPS)': gps['Salida'],
                'ENTRADA PLANTEL (GPS)': gps['Entrada'],
                'DÍAS FALTADOS': int(faltas_dict.get(tec, 0))
            })

        return pd.DataFrame(datos_finales), df_time_act, df_exp_detallado, diagnostico, "Exitoso"
    except Exception as e:
        return None, None, None, None, f"Error interno: {str(e)}"

# ==============================================================================
# INTERFAZ STREAMLIT (DASHBOARD)
# ==============================================================================
def mostrar_tiempos_tecnicos(es_movil=False, conn=None, df_base=None, *args, **kwargs):
    st.markdown("<h2 style='text-align: center; color: #10B981;'>📊 Dashboard Integral Operativo</h2>", unsafe_allow_html=True)
    st.caption("Cruce inteligente de productividad, tiempos GPS y registros de RRHH.")
    st.divider()

    obtener_datos_expedientes(conn)

    # ================= 1. CARGA DE DATOS =================
    c1, c2, c3 = st.columns(3)
    with c1: act_file = st.file_uploader("1. rep_actividades (Obligatorio)", type=['csv', 'xlsx'])
    with c2: gps_file = st.file_uploader("2. InformeZonasRutas (GPS)", type=['csv', 'xlsx'])
    with c3:
        st.write("3. Base de Datos RRHH")
        if st.button("🔄 Sincronizar Expedientes"):
            with st.spinner("Sincronizando..."):
                if conn:
                    try:
                        df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ BD Sincronizada.")
                        time.sleep(1); st.rerun()
                    except Exception as e: st.error(e)
        if st.session_state.get('df_exp_memoria') is not None:
            st.success(f"Expedientes listos ({len(st.session_state['df_exp_memoria'])} reg.)")

    st.markdown("<br>", unsafe_allow_html=True)

    # ================= 2. BOTÓN EJECUCIÓN =================
    if st.button("🚀 INICIAR ANÁLISIS CRUZADO", type="primary", use_container_width=True):
        if act_file:
            with st.spinner("🤖 Analizando y cruzando bases de datos..."):
                df_act = read_file_robust_local(act_file)
                df_gps = read_file_robust_local(gps_file) if gps_file else None
                df_exp = st.session_state.get('df_exp_memoria', None)

                df_maestra, df_time_act, df_disciplina, diag, msg = procesar_rendimiento_avanzado(df_act, df_gps, df_exp)
                
                if df_maestra is not None:
                    st.session_state['rs_maestra'] = df_maestra
                    st.session_state['rs_time_act'] = df_time_act
                    st.session_state['rs_disciplina'] = df_disciplina
                    st.session_state['rs_diag'] = diag
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.warning("Debe subir al menos el archivo 'rep_actividades'.")

    # ================= 3. RENDERIZADO DE RESULTADOS =================
    if 'rs_maestra' in st.session_state:
        df_m = st.session_state['rs_maestra'].copy()
        df_time_act = st.session_state['rs_time_act']
        df_exp_det = st.session_state['rs_disciplina']
        diag = st.session_state['rs_diag']

        # --- PANEL DE DIAGNÓSTICO DE ERRORES ---
        if diag['gps_huerfanos'] or diag['exp_huerfanos']:
            with st.expander("⚠️ Alertas de Sincronización (Datos no cruzados)", expanded=False):
                st.warning("Los siguientes registros no se pudieron asignar a ningún técnico porque el nombre no coincide con el archivo de actividades:")
                if diag['gps_huerfanos']:
                    st.write("**Vehículos GPS no identificados:**", ", ".join(str(x) for x in diag['gps_huerfanos']))
                if diag['exp_huerfanos']:
                    st.write("**Nombres en RRHH no identificados:**", ", ".join(str(x) for x in diag['exp_huerfanos']))

        # Filtro global
        tecs_disp = sorted(df_m['TÉCNICO'].unique())
        tec_filtro = st.multiselect("🔍 Filtrar Técnico(s):", tecs_disp)
        if tec_filtro: df_m = df_m[df_m['TÉCNICO'].isin(tec_filtro)]

        # --- PESTAÑAS ---
        tab_graficos, tab_maestra, tab_exp = st.tabs(["📈 Gráficos y KPIs", "📋 Tabla Maestra", "🚨 Registro Disciplinario"])

        with tab_graficos:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("👥 Técnicos", len(df_m))
            k2.metric("📦 Órdenes", df_m['TOTAL ÓRDENES'].sum())
            k3.metric("⏳ Promedio (Min)", round(df_m['TIEMPO PROM. (Min)'].mean(), 1))
            k4.metric("🚨 Días Ausencia", df_m['DÍAS FALTADOS'].sum())
            
            st.markdown("---")
            
            # Gráfico 1: PLEX vs RESIDENCIAL (Stackeado)
            df_segmentado = df_m[['TÉCNICO', 'PLEX', 'RESIDENCIAL']].melt(id_vars='TÉCNICO', var_name='Segmento', value_name='Cantidad')
            df_segmentado = df_segmentado[df_segmentado['Cantidad'] > 0]
            orden_tecnicos = df_m.sort_values('TOTAL ÓRDENES', ascending=True)['TÉCNICO'].tolist()
            
            alto_g1 = max(450, len(df_m) * 35)
            fig_ord = px.bar(df_segmentado, x='Cantidad', y='TÉCNICO', color='Segmento', orientation='h',
                             title="📦 Productividad (PLEX vs Residencial)", text_auto=True, 
                             color_discrete_map={'PLEX': '#8B5CF6', 'RESIDENCIAL': '#10B981'})
            fig_ord.update_yaxes(categoryorder='array', categoryarray=orden_tecnicos)
            fig_ord.update_layout(height=alto_g1, barmode='stack', yaxis_title="")
            st.plotly_chart(fig_ord, use_container_width=True)

            # Gráfico 2: Tiempos por ACTIVIDAD (Stackeado)
            if not df_time_act.empty:
                df_time_fil = df_time_act[df_time_act['TECNICO'].isin(tec_filtro)] if tec_filtro else df_time_act
                alto_g2 = max(450, len(df_time_fil['TECNICO'].unique()) * 40)
                
                fig_time = px.bar(df_time_fil, x='Minutos', y='TECNICO', color='ACTIVIDAD', orientation='h',
                                 title="⏳ Tiempo Promedio (Dividido por Tipo de Orden)", text_auto='.1f', barmode='stack')
                fig_time.update_layout(height=alto_g2, yaxis_title="")
                st.plotly_chart(fig_time, use_container_width=True)

        with tab_maestra:
            st.markdown("### 📋 Tabla de Rendimiento General")
            def highlight_faltas(row): return ['background-color: #fee2e2; color: #991b1b'] * len(row) if row['DÍAS FALTADOS'] > 0 else [''] * len(row)
            st.dataframe(df_m.style.apply(highlight_faltas, axis=1), use_container_width=True, hide_index=True)

            try:
                pdf_bytes = generar_pdf_rendimiento_integral(df_m)
                if pdf_bytes: st.download_button("📄 Descargar PDF", data=pdf_bytes, file_name="Reporte.pdf", mime="application/pdf", type="primary")
            except: pass

        with tab_exp:
            st.markdown("### 🚨 Expedientes e Incidencias")
            if df_exp_det is not None and not df_exp_det.empty:
                df_e_fil = df_exp_det[df_exp_det['TEC_MAESTRO'].isin(tec_filtro)] if tec_filtro else df_exp_det
                if not df_e_fil.empty:
                    tecnicos_con_incidencias = sorted(df_e_fil['TEC_MAESTRO'].unique())
                    st.info("💡 Seleccione un técnico para ver sus reportes:")
                    tec_sel = st.selectbox("👤 Seleccionar Técnico:", ["-- Seleccione --"] + tecnicos_con_incidencias)
                    
                    if tec_sel != "-- Seleccione --":
                        for _, row in df_e_fil[df_e_fil['TEC_MAESTRO'] == tec_sel].iterrows():
                            # Búsqueda dinámica de columnas
                            fecha = row.get(next((c for c in row.keys() if 'FECHA' in c), 'N/D'), 'Sin fecha')
                            tipo = row.get(next((c for c in row.keys() if 'TIPO' in c or 'FALTA' in c), 'N/D'), 'Registro')
                            comentario = row.get(next((c for c in row.keys() if 'COMENTARIO' in c or 'DESC' in c), 'N/D'), 'Sin comentarios.')
                            
                            es_falta = row.get('ES_FALTA', False)
                            color = "#ef4444" if es_falta else "#f59e0b"
                            icono = "❌ Ausencia/Falta" if es_falta else "⚠️ Llamado de Atención"
                            
                            st.markdown(f"""
                            <div style="border-left: 5px solid {color}; padding: 15px; background-color: #f9fafb; margin-bottom: 12px; border-radius: 5px;">
                                <h4 style="margin: 0px;">{icono}</h4>
                                <p style="margin: 5px 0px; font-size: 0.9em;"><strong>Fecha:</strong> {fecha} | <strong>Tipo:</strong> {tipo}</p>
                                <p style="margin: 0px; font-size: 1.05em;"><em>"{comentario}"</em></p>
                            </div>
                            """, unsafe_allow_html=True)
                else: st.success("Los técnicos analizados no tienen incidencias.")
            else: st.info("No hay datos disciplinarios cargados.")
