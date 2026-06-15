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
# CLASIFICADOR DE TIPO DE ORDEN
# Detecta si es Residencial, Plex o tipo SOP/SOPFibra/etc. según el campo TIPO
# ==============================================================================
def clasificar_segmento(tipo_valor):
    """Clasifica una orden como Residencial o Plex según el campo TIPO de la orden."""
    t = str(tipo_valor).upper().strip()
    if any(k in t for k in ['PLEX', 'EMPRESA', 'CORPORAT', 'BUSINESS', 'SME']):
        return 'Plex'
    return 'Residencial'

def clasificar_tipo_orden(tipo_valor):
    """
    Devuelve el tipo específico de orden: SOP, SOPFibra, Instalacion, etc.
    Se basa en el campo TIPO o SUBTIPO del archivo rep_actividades.
    """
    t = str(tipo_valor).upper().strip()
    # SOP Fibra tiene prioridad sobre SOP genérico
    if 'SOPFIB' in t or ('SOP' in t and 'FIBR' in t):
        return 'SOPFibra'
    if 'SOP' in t:
        return 'SOP'
    if 'INSTAL' in t:
        return 'Instalación'
    if 'MANTEN' in t or 'MTTO' in t:
        return 'Mantenimiento'
    if 'RETIRO' in t or 'DESCONEX' in t:
        return 'Retiro'
    if 'MIGRACI' in t:
        return 'Migración'
    if 'VISITA' in t:
        return 'Visita'
    return 'Otro'

# ==============================================================================
# DETECTOR DE INASISTENCIAS EN COMENTARIOS DE EXPEDIENTES
# ==============================================================================
PALABRAS_INASISTENCIA = [
    'NO SE PRESENTO', 'NO SE PRESENTÓ', 'AUSENTE', 'FALTA',
    'INASISTENCIA', 'NO LABORES', 'NO TRABAJO', 'NO TRABAJÓ',
    'NO ASISTIO', 'NO ASISTIÓ', 'ABANDONO', 'NO SE PRESENTÓ A LABORES',
    'NO SE PRESENTO A LABORES', 'NO SE PRESENTO AL TRABAJO',
    'INCAPACIDAD', 'PERMISO SIN GOCE', 'SUSPENSION', 'SUSPENSIÓN'
]

def es_comentario_inasistencia(comentario):
    """Devuelve True si el comentario de expediente indica que el técnico no se presentó."""
    if pd.isna(comentario):
        return False
    c = str(comentario).upper().strip()
    c = unicodedata.normalize('NFKD', c).encode('ASCII', 'ignore').decode('utf-8')
    return any(p in c for p in PALABRAS_INASISTENCIA)

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
        except:
            pass

    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            return forzar_columnas_unicas_local(pd.read_excel(uploaded_file, engine='xlrd'))
        except:
            pass

    es_zip_binario = content.startswith(b'PK\x03\x04')
    if not es_zip_binario and (b'<table' in content.lower() or b'<html' in content.lower()):
        try:
            dfs = pd.read_html(io.BytesIO(content))
            if dfs:
                return forzar_columnas_unicas_local(max(dfs, key=len))
        except:
            try:
                dfs = pd.read_html(io.BytesIO(content), encoding='latin-1')
                if dfs:
                    return forzar_columnas_unicas_local(max(dfs, key=len))
            except:
                pass

    uploaded_file.seek(0)
    try:
        return forzar_columnas_unicas_local(pd.read_excel(uploaded_file))
    except:
        pass

    uploaded_file.seek(0)
    try:
        return forzar_columnas_unicas_local(pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip'))
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
    except:
        pass

    if conn is None:
        try:
            from streamlit_gsheets import GSheetsConnection
            conn = st.connection("gsheets", type=GSheetsConnection)
        except:
            pass

    if conn is not None:
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            st.session_state['df_exp_memoria'] = df
            return df
        except:
            pass

    return None

# ==============================================================================
# MOTOR SUPERIOR DE DEPURACIÓN Y EMPAREJAMIENTO DE NOMBRES
# ==============================================================================
def limpiar_texto_nombres(texto):
    """Limpia acentos, caracteres raros y deja solo letras mayúsculas para comparar."""
    if pd.isna(texto):
        return ""
    t = str(texto).upper().strip()
    t = re.sub(r'\(.*?\)', '', t)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('utf-8')
    t = re.sub(r'[^A-Z\s]', '', t)
    return " ".join(t.split())

def encontrar_tecnico_maestro(nombre_buscar, lista_maestros_limpios, lista_original):
    """Encuentra el nombre del técnico evaluando qué tantas palabras coinciden."""
    n_buscar = limpiar_texto_nombres(nombre_buscar)
    if not n_buscar:
        return None

    tokens_buscar = set(n_buscar.split())
    mejor_match = None
    max_score = 0

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
    if pd.isna(secs) or secs is None or secs <= 0:
        return "--"
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

        # Base de nombres maestros
        tecnicos_originales = df_act['TECNICO'].unique()
        tecnicos_limpios = [limpiar_texto_nombres(t) for t in tecnicos_originales]

        df_act['Minutos_Orden'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos_Orden'] = df_act['Minutos_Orden'].apply(lambda x: x if x > 0 else 0)

        # --- Clasificar Segmento (Residencial / Plex) ---
        col_tipo_raw = next((c for c in df_act.columns if 'TIPO' in str(c).upper()), None)
        if col_tipo_raw:
            df_act['Segmento'] = df_act[col_tipo_raw].apply(clasificar_segmento)
            df_act['TipoOrden'] = df_act[col_tipo_raw].apply(clasificar_tipo_orden)
        else:
            df_act['Segmento'] = 'Residencial'
            df_act['TipoOrden'] = 'Otro'

        # Resumen global por técnico
        resumen_act = df_act.groupby('TECNICO').agg(
            Ordenes_Totales=('NUM', 'count'),
            Minutos_Promedio=('Minutos_Orden', 'mean'),
            Hora_Primera_Orden=('FECHA_ENTRADA', 'min')
        ).reset_index()

        # Resumen por técnico + segmento (para gráfico productividad)
        resumen_segmento = df_act.groupby(['TECNICO', 'Segmento']).agg(
            Ordenes=('NUM', 'count')
        ).reset_index()

        # Resumen por técnico + tipo de orden (para gráfico tiempo promedio)
        resumen_tipo = df_act.groupby(['TECNICO', 'TipoOrden']).agg(
            Ordenes=('NUM', 'count'),
            MinProm=('Minutos_Orden', 'mean')
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
                df_gps['Mes'] = df_gps['DT_OUT'].dt.to_period('M').astype(str)

                df_gps['TEC_MAESTRO'] = df_gps[col_placa].apply(
                    lambda x: encontrar_tecnico_maestro(x, tecnicos_limpios, tecnicos_originales)
                )
                df_gps_valid = df_gps.dropna(subset=['TEC_MAESTRO'])

                for (tec, fecha), sub_df in df_gps_valid.groupby(['TEC_MAESTRO', 'Fecha']):
                    p_salida = sub_df['DT_OUT'].min()
                    u_llegada = sub_df['DT_IN'].max()
                    mes = sub_df['Mes'].iloc[0] if not sub_df['Mes'].isna().all() else '--'

                    s_salida = p_salida.hour * 3600 + p_salida.minute * 60 + p_salida.second if pd.notnull(p_salida) else None
                    s_llegada = u_llegada.hour * 3600 + u_llegada.minute * 60 + u_llegada.second if pd.notnull(u_llegada) else None

                    gps_consolidado.append({
                        'TECNICO': tec,
                        'Fecha': fecha,
                        'Mes': mes,
                        'Salida_Secs': s_salida,
                        'Entrada_Secs': s_llegada,
                        'Salida_Str': p_salida.strftime('%H:%M:%S') if pd.notnull(p_salida) else '--',
                        'Entrada_Str': u_llegada.strftime('%H:%M:%S') if pd.notnull(u_llegada) else '--'
                    })

        df_gps_diario = pd.DataFrame(gps_consolidado)

        # Promedios de GPS por técnico (para tabla maestra)
        gps_promedios = {}
        # Promedios MENSUALES de GPS (para tabla maestra ampliada)
        gps_promedios_mensuales = pd.DataFrame()

        if not df_gps_diario.empty:
            for tec, g in df_gps_diario.groupby('TECNICO'):
                p_sal = g['Salida_Secs'].dropna().mean()
                p_ent = g['Entrada_Secs'].dropna().mean()
                gps_promedios[tec] = {
                    'Salida': formatear_hora(p_sal) if pd.notnull(p_sal) else '--',
                    'Entrada': formatear_hora(p_ent) if pd.notnull(p_ent) else '--'
                }

            # Promedios mensuales por técnico y mes
            filas_mens = []
            for (tec, mes), g in df_gps_diario.groupby(['TECNICO', 'Mes']):
                p_sal = g['Salida_Secs'].dropna().mean()
                p_ent = g['Entrada_Secs'].dropna().mean()
                filas_mens.append({
                    'TÉCNICO': tec,
                    'MES': mes,
                    'PROM. SALIDA MENSUAL (GPS)': formatear_hora(p_sal) if pd.notnull(p_sal) else '--',
                    'PROM. ENTRADA MENSUAL (GPS)': formatear_hora(p_ent) if pd.notnull(p_ent) else '--'
                })
            gps_promedios_mensuales = pd.DataFrame(filas_mens)

        # --- 3. PROCESAR EXPEDIENTES ---
        # Se buscan: faltas estructuradas (campo TIPO_FALTA) Y comentarios de inasistencia en la nube
        faltas_dict = {}
        llamados_dict = {}
        dias_no_presentados_dict = {}   # <- NUEVO: conteo desde comentarios de la nube
        df_exp_detallado = pd.DataFrame()

        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            # Columna de comentarios/observaciones de la nube
            col_comentario = next((c for c in df_exp.columns if any(k in str(c).upper() for k in [
                'COMENTARIO', 'OBSERVACION', 'OBSERVACIÓN', 'NOTA', 'DESCRIPCION', 'DESCRIPCIÓN', 'DETALLE'
            ])), None)

            if col_tec_exp:
                df_exp['TEC_MAESTRO'] = df_exp[col_tec_exp].apply(
                    lambda x: encontrar_tecnico_maestro(x, tecnicos_limpios, tecnicos_originales)
                )
                df_exp_detallado = df_exp.dropna(subset=['TEC_MAESTRO']).copy()

                if col_tipo:
                    def es_falta(t):
                        return any(k in str(t).upper() for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA'])

                    df_exp_detallado['ES_FALTA'] = df_exp_detallado[col_tipo].apply(es_falta)

                    for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                        faltas_dict[tec] = int(g['ES_FALTA'].sum())
                        llamados_dict[tec] = int((~g['ES_FALTA']).sum())

                # Contar días no presentados desde comentarios de la nube
                if col_comentario:
                    df_exp_detallado['ES_NO_PRESENTADO'] = df_exp_detallado[col_comentario].apply(es_comentario_inasistencia)
                    for tec, g in df_exp_detallado.groupby('TEC_MAESTRO'):
                        dias_no_presentados_dict[tec] = int(g['ES_NO_PRESENTADO'].sum())
                else:
                    # Si no hay columna de comentario, usar las faltas del campo TIPO
                    dias_no_presentados_dict = faltas_dict.copy()

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
                'DÍAS NO PRESENTADO': int(dias_no_presentados_dict.get(tec, 0)),
                'DÍAS FALTADOS': int(faltas_dict.get(tec, 0)),
                'LLAMADOS ATENCIÓN': int(llamados_dict.get(tec, 0))
            })

        return (
            pd.DataFrame(datos_finales),
            df_gps_diario,
            df_exp_detallado,
            resumen_segmento,
            resumen_tipo,
            gps_promedios_mensuales,
            "Exitoso"
        )
    except Exception as e:
        import traceback
        return None, None, None, None, None, None, f"Error: {e}\n{traceback.format_exc()}"

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
    with c1:
        act_file = st.file_uploader("1. rep_actividades (Órdenes)", type=['csv', 'xlsx'])
    with c2:
        gps_file = st.file_uploader("2. InformeZonasRutas (GPS)", type=['csv', 'xlsx'])
    with c3:
        st.write("3. Base de Datos Nube")
        if st.button("🔄 Sincronizar Expedientes"):
            with st.spinner("Conectando..."):
                if conn:
                    try:
                        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        if df is None or df.empty:
                            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        st.session_state['df_exp_memoria'] = df
                        st.success("✅ BD Sincronizada.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(e)
                else:
                    st.error("Sin conexión.")
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

                resultado = procesar_rendimiento_avanzado(df_act, df_gps, df_exp)
                df_maestra, df_diario, df_disciplina, df_seg, df_tipo_ord, df_gps_mens, msg = resultado

                if df_maestra is not None:
                    st.session_state['rs_maestra'] = df_maestra
                    st.session_state['rs_diario'] = df_diario
                    st.session_state['rs_disciplina'] = df_disciplina
                    st.session_state['rs_segmento'] = df_seg
                    st.session_state['rs_tipo_orden'] = df_tipo_ord
                    st.session_state['rs_gps_mensual'] = df_gps_mens
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.warning("Debe subir al menos el archivo 'rep_actividades'.")

    # ================= 3. VISUALIZACIÓN DEL DASHBOARD =================
    if 'rs_maestra' in st.session_state:
        df_m = st.session_state['rs_maestra'].copy()
        df_d = st.session_state.get('rs_diario', pd.DataFrame())
        df_exp_det = st.session_state.get('rs_disciplina', pd.DataFrame())
        df_seg = st.session_state.get('rs_segmento', pd.DataFrame())
        df_tipo_ord = st.session_state.get('rs_tipo_orden', pd.DataFrame())
        df_gps_mens = st.session_state.get('rs_gps_mensual', pd.DataFrame())

        # Filtro global
        tecs_disp = sorted(df_m['TÉCNICO'].unique())
        tec_filtro = st.multiselect("🔍 Filtrar Técnico(s) para todo el reporte:", tecs_disp)
        if tec_filtro:
            df_m = df_m[df_m['TÉCNICO'].isin(tec_filtro)]
            if not df_seg.empty:
                df_seg = df_seg[df_seg['TECNICO'].isin(tec_filtro)]
            if not df_tipo_ord.empty:
                df_tipo_ord = df_tipo_ord[df_tipo_ord['TECNICO'].isin(tec_filtro)]

        # --- PESTAÑAS DEL DASHBOARD (solo 3 ahora) ---
        tab_graficos, tab_maestra, tab_exp = st.tabs([
            "📈 Gráficos y KPIs",
            "📋 Tabla Maestra Integral",
            "🚨 Registro Disciplinario"
        ])

        # ================================================================
        # TAB 1: GRÁFICOS Y KPIs
        # ================================================================
        with tab_graficos:
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("👥 Técnicos Analizados", len(df_m))
            k2.metric("📦 Total Órdenes", df_m['ÓRDENES CANTIDAD'].sum())
            k3.metric("⏳ Promedio Gral (Min)", round(df_m['TIEMPO PROM. EN ORDEN (Min)'].mean(), 1))
            k4.metric(
                "🚨 Total Incidencias",
                df_m['DÍAS FALTADOS'].sum() + df_m['LLAMADOS ATENCIÓN'].sum() + df_m['DÍAS NO PRESENTADO'].sum()
            )

            st.markdown("---")

            # ---- GRÁFICO 1: PRODUCTIVIDAD (Residencial vs Plex) ----
            st.markdown("#### 📦 Productividad por Técnico — Residencial vs Plex")
            if not df_seg.empty:
                # Ordenar técnicos por total de órdenes para mejor lectura
                orden_tecs = df_seg.groupby('TECNICO')['Ordenes'].sum().sort_values(ascending=True).index.tolist()

                fig_ord = px.bar(
                    df_seg,
                    x='Ordenes',
                    y='TECNICO',
                    color='Segmento',
                    orientation='h',
                    title="📦 Productividad por Técnico (Residencial vs Plex)",
                    text_auto=True,
                    color_discrete_map={
                        'Residencial': '#10B981',
                        'Plex': '#6366F1'
                    },
                    category_orders={'TECNICO': orden_tecs},
                    barmode='stack'
                )
                fig_ord.update_layout(
                    height=max(350, len(orden_tecs) * 32),
                    yaxis_title="",
                    legend_title="Segmento",
                    xaxis_title="Cantidad de Órdenes"
                )
                st.plotly_chart(fig_ord, use_container_width=True)
            else:
                # Fallback: gráfico simple si no hay campo TIPO disponible
                fig_ord = px.bar(
                    df_m.sort_values('ÓRDENES CANTIDAD', ascending=True),
                    x='ÓRDENES CANTIDAD', y='TÉCNICO', orientation='h',
                    title="📦 Productividad (Cant. Órdenes)", text_auto=True,
                    color_discrete_sequence=['#10B981']
                )
                fig_ord.update_layout(height=max(350, len(df_m) * 32), yaxis_title="")
                st.plotly_chart(fig_ord, use_container_width=True)
                st.info("ℹ️ No se detectó columna TIPO en el archivo. El gráfico muestra totales sin desglose de segmento.")

            st.markdown("---")

            # ---- GRÁFICO 2: TIEMPO PROMEDIO por técnico y tipo de orden ----
            st.markdown("#### ⏳ Tiempo Promedio por Orden — Todos los Técnicos por Tipo")
            if not df_tipo_ord.empty:
                # Incluir TODOS los técnicos (sin filtro de top)
                orden_tecs_tiempo = (
                    df_tipo_ord.groupby('TECNICO')['MinProm'].mean()
                    .sort_values(ascending=False)
                    .index.tolist()
                )

                fig_time = px.bar(
                    df_tipo_ord,
                    x='MinProm',
                    y='TECNICO',
                    color='TipoOrden',
                    orientation='h',
                    title="⏳ Tiempo Promedio por Orden (Min) — Por Tipo de Orden",
                    text_auto='.1f',
                    color_discrete_sequence=px.colors.qualitative.Set2,
                    category_orders={'TECNICO': orden_tecs_tiempo},
                    barmode='group'
                )
                fig_time.update_layout(
                    height=max(400, len(orden_tecs_tiempo) * 40),
                    yaxis_title="",
                    legend_title="Tipo de Orden",
                    xaxis_title="Minutos Promedio"
                )
                st.plotly_chart(fig_time, use_container_width=True)

                # Tabla de apoyo con detalle por tipo
                with st.expander("📊 Ver detalle numérico por tipo de orden"):
                    df_tipo_pivot = df_tipo_ord.pivot_table(
                        index='TECNICO', columns='TipoOrden', values='MinProm', aggfunc='mean'
                    ).round(1).reset_index()
                    df_tipo_pivot.columns.name = None
                    st.dataframe(df_tipo_pivot, use_container_width=True, hide_index=True)
            else:
                fig_time = px.bar(
                    df_m.sort_values('TIEMPO PROM. EN ORDEN (Min)', ascending=False),
                    x='TIEMPO PROM. EN ORDEN (Min)', y='TÉCNICO', orientation='h',
                    title="⏳ Tiempo Promedio por Orden (Minutos)", text_auto='.1f',
                    color_discrete_sequence=['#3B82F6']
                )
                fig_time.update_layout(height=max(400, len(df_m) * 32), yaxis_title="")
                st.plotly_chart(fig_time, use_container_width=True)
                st.info("ℹ️ No se detectó columna TIPO en el archivo. Mostrando tiempo promedio global.")

            # ---- GRÁFICO 3: INCIDENCIAS ----
            df_incidencias = df_m[
                (df_m['DÍAS FALTADOS'] > 0) |
                (df_m['LLAMADOS ATENCIÓN'] > 0) |
                (df_m['DÍAS NO PRESENTADO'] > 0)
            ]
            if not df_incidencias.empty:
                st.markdown("---")
                st.markdown("#### 🚨 Mapa de Incidencias Disciplinarias")
                df_melt = df_incidencias.melt(
                    id_vars='TÉCNICO',
                    value_vars=['DÍAS FALTADOS', 'LLAMADOS ATENCIÓN', 'DÍAS NO PRESENTADO'],
                    var_name='Tipo',
                    value_name='Cantidad'
                )
                df_melt = df_melt[df_melt['Cantidad'] > 0]
                fig_inc = px.bar(
                    df_melt, x='TÉCNICO', y='Cantidad', color='Tipo',
                    title="🚨 Incidencias por Técnico",
                    color_discrete_map={
                        'DÍAS FALTADOS': '#EF4444',
                        'LLAMADOS ATENCIÓN': '#F59E0B',
                        'DÍAS NO PRESENTADO': '#DC2626'
                    },
                    text_auto=True, barmode='group'
                )
                st.plotly_chart(fig_inc, use_container_width=True)

        # ================================================================
        # TAB 2: TABLA MAESTRA INTEGRAL
        # ================================================================
        with tab_maestra:
            st.markdown("### 📋 Vista Consolidada")
            st.caption("Tabla con el resumen de rendimiento, disciplina y promedios GPS mensuales de cada técnico.")

            # KPI rápido de días no presentados filtrados
            total_no_presentados = df_m['DÍAS NO PRESENTADO'].sum()
            if total_no_presentados > 0:
                st.warning(f"⚠️ Se detectaron **{total_no_presentados} día(s)** con comentarios de inasistencia en la nube (ej. 'Técnico no se presentó a labores').")

            # Formato condicional
            def highlight_incidencias(row):
                if row.get('DÍAS NO PRESENTADO', 0) > 0 or row.get('DÍAS FALTADOS', 0) > 0 or row.get('LLAMADOS ATENCIÓN', 0) > 0:
                    return ['background-color: #fee2e2; color: #991b1b'] * len(row)
                return [''] * len(row)

            st.dataframe(df_m.style.apply(highlight_incidencias, axis=1), use_container_width=True, hide_index=True)

            # ---- PROMEDIOS MENSUALES GPS ----
            if not df_gps_mens.empty:
                st.markdown("---")
                st.markdown("#### 📅 Promedios Mensuales de Hora de Salida / Entrada — InformeZonasRutas")
                st.caption("Promedio de hora de salida del plantel y regreso al plantel por técnico y mes.")

                # Filtrar por los técnicos seleccionados
                df_gps_mens_fil = df_gps_mens
                if tec_filtro:
                    df_gps_mens_fil = df_gps_mens[df_gps_mens['TÉCNICO'].isin(tec_filtro)]

                # Selector de mes
                meses_disp = sorted(df_gps_mens_fil['MES'].unique())
                if meses_disp:
                    mes_sel = st.selectbox("📆 Filtrar por mes:", ["Todos"] + meses_disp)
                    if mes_sel != "Todos":
                        df_gps_mens_fil = df_gps_mens_fil[df_gps_mens_fil['MES'] == mes_sel]

                st.dataframe(
                    df_gps_mens_fil.sort_values(['TÉCNICO', 'MES']),
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("ℹ️ No se subió archivo InformeZonasRutas o no se encontraron datos GPS para promediar.")

            # Botón de Descarga PDF
            try:
                pdf_bytes = generar_pdf_rendimiento_integral(df_m)
                if pdf_bytes:
                    st.download_button(
                        "📄 Descargar Reporte PDF",
                        data=pdf_bytes,
                        file_name="Reporte_Gerencial.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
            except:
                pass

        # ================================================================
        # TAB 3: REGISTRO DISCIPLINARIO (Tab 4 original, ahora Tab 3)
        # Al hacer clic en un nombre de la columna se muestra la incidencia
        # ================================================================
        with tab_exp:
            st.markdown("### 🚨 Registro Disciplinario")

            if df_exp_det is not None and not df_exp_det.empty:
                df_e_fil = df_exp_det[df_exp_det['TEC_MAESTRO'].isin(tec_filtro)] if tec_filtro else df_exp_det.copy()

                if not df_e_fil.empty:
                    # ---- SELECTOR DE TÉCNICO para ver incidencias individuales ----
                    st.markdown("#### 🔎 Consultar Incidencias por Técnico")
                    st.caption("Selecciona un técnico de la lista para ver el detalle de sus incidencias registradas en la nube.")

                    tecnicos_con_exp = sorted(df_e_fil['TEC_MAESTRO'].dropna().unique())
                    tec_seleccionado = st.selectbox(
                        "👤 Seleccionar Técnico:",
                        ["-- Selecciona un técnico --"] + tecnicos_con_exp,
                        key="sel_tec_disciplina"
                    )

                    if tec_seleccionado and tec_seleccionado != "-- Selecciona un técnico --":
                        if st.button(f"📋 Ver Incidencias de {tec_seleccionado}", type="primary", use_container_width=True):
                            st.session_state['tec_incidencia_activo'] = tec_seleccionado

                    # Mostrar incidencia del técnico activo
                    tec_activo = st.session_state.get('tec_incidencia_activo', None)
                    if tec_activo and tec_activo in tecnicos_con_exp:
                        df_inc_tec = df_e_fil[df_e_fil['TEC_MAESTRO'] == tec_activo].copy()

                        # Columnas relevantes excluyendo las internas
                        cols_excluir = {'TEC_MAESTRO', 'ES_FALTA', 'ES_NO_PRESENTADO'}
                        cols_mostrar = [c for c in df_inc_tec.columns if c not in cols_excluir]

                        st.markdown(f"---")
                        st.markdown(f"#### 📁 Incidencias registradas para: **{tec_activo}**")

                        total_inc = len(df_inc_tec)
                        dias_no_pres = int(df_inc_tec.get('ES_NO_PRESENTADO', pd.Series([False] * len(df_inc_tec))).sum()) if 'ES_NO_PRESENTADO' in df_inc_tec.columns else 0
                        faltas_tipo = int(df_inc_tec.get('ES_FALTA', pd.Series([False] * len(df_inc_tec))).sum()) if 'ES_FALTA' in df_inc_tec.columns else 0

                        ki1, ki2, ki3 = st.columns(3)
                        ki1.metric("📋 Total Registros", total_inc)
                        ki2.metric("🚫 Días No Presentado", dias_no_pres)
                        ki3.metric("📌 Faltas Registradas", faltas_tipo)

                        # Highlight en la tabla: rojo = no presentado, amarillo = otra falta
                        def highlight_exp_row(row):
                            if 'ES_NO_PRESENTADO' in df_inc_tec.columns:
                                idx = row.name
                                if idx in df_inc_tec.index:
                                    if df_inc_tec.loc[idx, 'ES_NO_PRESENTADO']:
                                        return ['background-color: #fee2e2; color: #991b1b'] * len(row)
                            if 'ES_FALTA' in df_inc_tec.columns:
                                idx = row.name
                                if idx in df_inc_tec.index and df_inc_tec.loc[idx, 'ES_FALTA']:
                                    return ['background-color: #fef3c7; color: #92400e'] * len(row)
                            return [''] * len(row)

                        df_mostrar_tec = df_inc_tec[cols_mostrar].reset_index(drop=True)
                        st.dataframe(
                            df_mostrar_tec.style.apply(highlight_exp_row, axis=1),
                            use_container_width=True,
                            hide_index=True
                        )

                        if st.button("❌ Cerrar detalle", key="cerrar_incidencia"):
                            st.session_state['tec_incidencia_activo'] = None
                            st.rerun()

                    st.markdown("---")
                    st.markdown("#### 📊 Vista General — Todos los Registros Disciplinarios")
                    cols_mostrar_gral = [c for c in df_e_fil.columns if c not in {'TEC_MAESTRO', 'ES_FALTA', 'ES_NO_PRESENTADO'}]
                    st.dataframe(df_e_fil[cols_mostrar_gral], use_container_width=True, hide_index=True)

                else:
                    st.success("✨ ¡Excelente! Los técnicos seleccionados no tienen incidencias ni llamados de atención.")
            else:
                st.info("La base de datos de expedientes está limpia o no ha sido sincronizada.")
