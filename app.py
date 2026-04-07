import streamlit as st
import pandas as pd
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt
from streamlit_js_eval import streamlit_js_eval

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'.")

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
        generar_pdf_trimestral_detallado
    )
except ImportError:
    st.error("⚠️ Error Crítico: No se pudo localizar 'tools.py'.")

# ==============================================================================
# 1. CONFIGURACIÓN INICIAL Y ESTILO APP NATIVA
# ==============================================================================
st.set_page_config(
    layout="wide", 
    page_title="Monitor Maxcom PRO", 
    page_icon="⚡",
    initial_sidebar_state="collapsed"
)

# CSS AJUSTADO: Oculta la basura pero SALVA la flecha del menú
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Cabecera transparente */
    header[data-testid="stHeader"] {
        background-color: transparent !important;
    }
    
    /* Ocultar botones de GitHub/Deploy de la derecha */
    div[data-testid="stToolbar"] {
        visibility: hidden !important;
    }
    
    /* Hacer el botón del menú estilo App Nativa */
    button[data-testid="stSidebarCollapseButton"] {
        background-color: #1A1D24 !important;
        border: 1px solid #3B82F6 !important;
        border-radius: 8px !important;
        color: #3B82F6 !important;
        visibility: visible !important;
    }
    
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    html, body { touch-action: manipulation; overscroll-behavior: none; }
    </style>
""", unsafe_allow_html=True)

PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

# ==============================================================================
# 🛡️ MOTOR DE FECHAS ULTRA-PRECISO (REPARA EL ERROR 00:00 PARA SIEMPRE)
# ==============================================================================
def parse_date_ultra_safe(val):
    if pd.isnull(val) or str(val).strip() == "" or str(val) == "None":
        return pd.NaT
    
    # Usamos la hora de Honduras como referencia para "Hoy"
    hoy = pd.Timestamp(datetime.utcnow() - timedelta(hours=6)).normalize()

    try:
        if isinstance(val, datetime):
            return val
        
        if isinstance(val, (int, float)):
            if val > 10000:
                return pd.to_datetime(val, unit='D', origin='1899-12-30')
            elif val >= 0 and val < 1:
                # Es solo una fracción de hora de Excel. Le pegamos el día de hoy.
                return hoy + pd.to_timedelta(val, unit='D')

        str_val = str(val).strip()
        parsed = pd.to_datetime(str_val, dayfirst=True, errors='coerce')
        
        if pd.notnull(parsed):
            # Si el parseo arroja un año viejo (1900 o 1970), es porque era solo texto de HORA ("11:30")
            if parsed.year <= 1970:
                # Le inyectamos la fecha actual para que no se pierda el cierre del día
                return hoy + pd.Timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
            return parsed
            
        return pd.NaT
    except:
        return pd.NaT

def procesar_fechas_seguro(df_input, columnas):
    df = df_input.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = df[col].apply(parse_date_ultra_safe)
    return df

# ==============================================================================
# FUNCIONES GERENCIALES Y MODALES
# ==============================================================================
def generar_tablas_gerenciales(df_crudo):
    df = df_crudo.copy()
    df['HORA_INI'] = df['HORA_INI'].apply(parse_date_ultra_safe)
    df['HORA_LIQ'] = df['HORA_LIQ'].apply(parse_date_ultra_safe)
    df = df.dropna(subset=['HORA_INI', 'HORA_LIQ'])
    df['FECHA'] = df['HORA_LIQ'].dt.date
    
    totales_tec = df.groupby('TECNICO').size().reset_index(name='Total_Tecnico')
    conteo_act = df.groupby(['TECNICO', 'ACTIVIDAD']).size().reset_index(name='Cantidad')
    tabla_produccion = pd.merge(conteo_act, totales_tec, on='TECNICO')
    tabla_produccion['Participacion_%'] = (tabla_produccion['Cantidad'] / tabla_produccion['Total_Tecnico'] * 100).round(1)

    df['MINUTOS'] = (df['HORA_LIQ'] - df['HORA_INI']).dt.total_seconds() / 60
    df.loc[df['MINUTOS'] <= 0, 'MINUTOS'] = None 
    
    tabla_eficiencia = df.groupby(['TECNICO', 'ACTIVIDAD'])['MINUTOS'].mean().reset_index()
    tabla_eficiencia.columns = ['TECNICO', 'ACTIVIDAD', 'Promedio_Minutos']
    return tabla_produccion, tabla_eficiencia, df.groupby(['TECNICO', 'FECHA']).size().reset_index()

@st.dialog("Detalle de Gestión")
def mostrar_comentario_cierre(fila):
    st.write(f"### Orden N° {fila['NUM']}")
    st.write(f"**Técnico:** {fila['TECNICO']} | **Estado:** {fila['ESTADO']}")
    st.divider()
    st.info(fila.get('COMENTARIO', 'Sin observaciones.'))
    if st.button("Cerrar", use_container_width=True): st.rerun()

# ------------------------------------------------------------------------------
# MODAL OPTIMIZADO PARA MÓVILES (CON COLUMN_CONFIG APLICADO)
# ------------------------------------------------------------------------------
@st.dialog("Resumen de Operaciones")
def mostrar_detalle_avance(segmento, pendientes_df, cerradas_df):
    st.subheader(f"📊 Desglose: {segmento}")
    
    if not pendientes_df.empty:
        p = pendientes_df.groupby('ACTIVIDAD').size().reset_index(name='Pendiente')
    else:
        p = pd.DataFrame(columns=['ACTIVIDAD', 'Pendiente'])

    if not cerradas_df.empty:
        c = cerradas_df.groupby('ACTIVIDAD').size().reset_index(name='Cerradas')
    else:
        c = pd.DataFrame(columns=['ACTIVIDAD', 'Cerradas'])

    resumen = pd.merge(p, c, on='ACTIVIDAD', how='outer').fillna(0)

    if not resumen.empty:
        resumen['Pendiente'] = resumen['Pendiente'].astype(int)
        resumen['Cerradas'] = resumen['Cerradas'].astype(int)
        resumen.rename(columns={'ACTIVIDAD': 'Tipo'}, inplace=True)
        resumen = resumen.sort_values(by='Tipo').reset_index(drop=True)

        total_p = resumen['Pendiente'].sum()
        total_c = resumen['Cerradas'].sum()
        fila_total = pd.DataFrame([{'Tipo': 'TOTAL GENERAL', 'Pendiente': total_p, 'Cerradas': total_c}])
        resumen = pd.concat([resumen, fila_total], ignore_index=True)

        # AQUÍ ESTÁ LA MAGIA PARA QUE ENCAJE EN EL CELULAR
        st.dataframe(
            resumen,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Tipo": st.column_config.TextColumn("TIPO"),
                "Pendiente": st.column_config.NumberColumn("PEND.", format="%d"),
                "Cerradas": st.column_config.NumberColumn("CERR.", format="%d")
            }
        )
    else:
        st.info("No hay datos de operaciones para este segmento.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar Resumen", use_container_width=True): st.rerun()

# ==============================================================================
# SINCRONIZACIÓN Y LÓGICA BASE
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("Sincronizando..."):
            df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
            if not df_nube.empty:
                df_nube.columns = df_nube.columns.str.upper().str.strip()
                df_nube = procesar_fechas_seguro(df_nube, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
                
                if 'SUSCRIPTOR' in df_nube.columns: df_nube.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
                for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
                    if col_b in df_nube.columns: df_nube[col_b] = df_nube[col_b].astype(str).str.upper().isin(['TRUE', '1', '1.0'])
                
                st.session_state.df_base = df_nube
                st.success("✅ Datos sincronizados correctamente.")
                st.rerun()
    except Exception as e:
        st.error(f"Error nube: {e}")

def aplicar_estilos_df(df_original):
    df = df_original.copy()
    if 'HORA_INI' in df.columns:
        df['HORA_INI'] = pd.to_datetime(df['HORA_INI'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    if 'HORA_LIQ' in df.columns:
        df['HORA_LIQ'] = pd.to_datetime(df['HORA_LIQ'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    
    cols = ['DIAS_RETRASO', 'NUM', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL', 'ESTADO', 'TECNICO', 'ACTIVIDAD', 'MOTIVO', 'CLIENTE', 'NOMBRE', 'COLONIA', 'COMENTARIO']
    return df[[c for c in cols if c in df.columns]], None

# ==============================================================================
# INTERFAZ PRINCIPAL
# ==============================================================================
def main():
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    ancho = streamlit_js_eval(js_expressions='window.innerWidth', key='WIDTH', want_output=True)
    
    conn = st.connection("gsheets", type=GSheetsConnection)

    with st.sidebar:
        st.title("⚙️ Menú Maxcom")
        if st.button("📥 ACTUALIZAR NUBE", use_container_width=True): sincronizar_datos_nube(conn)
        nav = st.radio("IR A:", ["⚡ Monitor en Vivo", "📊 Reportes", "🚙 Vehículos"])
        st.divider()
        mostrar_boton_logout()

    if 'df_base' not in st.session_state:
        st.title("⚡ Monitor Maxcom")
        if st.button("🚀 CARGAR DATOS AHORA", type="primary", use_container_width=True): sincronizar_datos_nube(conn)
        return

    df_base = st.session_state.df_base.copy()
    ahora_local = datetime.now() - timedelta(hours=6)
    hoy = ahora_local.date()

    if nav == "⚡ Monitor en Vivo":
        st.title("⚡ Monitor en Vivo")
        
        vivas = df_base[df_base['ESTADO'].str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)]
        cerradas_hoy_df = df_base[(df_base['HORA_LIQ'].dt.date == hoy) & (df_base['ESTADO'].str.contains('CERRADA', na=False, case=False))]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ASIGNADAS", len(vivas))
        c2.metric("CERRADAS HOY", len(cerradas_hoy_df))
        c3.metric("TÉCNICOS", vivas['TECNICO'].nunique())
        c4.metric("OFFLINE", int(vivas['ES_OFFLINE'].sum()) if 'ES_OFFLINE' in vivas.columns else 0)

        with st.expander("📊 AVANCE POR SEGMENTO", expanded=True):
            df_p_plex = vivas[vivas['SEGMENTO'] == 'PLEX']
            df_c_plex = cerradas_hoy_df[cerradas_hoy_df['SEGMENTO'] == 'PLEX']
            df_p_resi = vivas[vivas['SEGMENTO'] == 'RESIDENCIAL']
            df_c_resi = cerradas_hoy_df[cerradas_hoy_df['SEGMENTO'] == 'RESIDENCIAL']

            def crear_donut(pend, cerr, titulo):
                total = pend + cerr
                val = (cerr / total * 100) if total > 0 else 0
                color = "#EF4444" if val < 50 else ("#F59E0B" if val < 80 else "#10B981")
                fig = go.Figure(go.Pie(values=[val, 100-val], hole=0.8, marker=dict(colors=[color, '#2D2F39']), textinfo='none', hoverinfo='none', sort=False))
                fig.update_layout(showlegend=False, height=140, margin=dict(l=5, r=5, t=25, b=5), paper_bgcolor="rgba(0,0,0,0)",
                                  title={'text': titulo, 'x': 0.5, 'font': {'size': 12, 'color': '#94A3B8'}},
                                  annotations=[dict(text=f"{val:.0f}%", x=0.5, y=0.5, font_size=20, font_color=color, showarrow=False, font_weight="bold")])
                return fig

            g1, g2 = st.columns(2)
            with g1:
                st.plotly_chart(crear_donut(len(df_p_resi), len(df_c_resi), "🏠 RESIDENCIAL"), use_container_width=True)
                if st.button("🔍 Detalle RESI", use_container_width=True, key="br"): mostrar_detalle_avance("RESIDENCIAL", df_p_resi, df_c_resi)
            with g2:
                st.plotly_chart(crear_donut(len(df_p_plex), len(df_c_plex), "🏢 PLEX"), use_container_width=True)
                if st.button("🔍 Detalle PLEX", use_container_width=True, key="bp"): mostrar_detalle_avance("PLEX", df_p_plex, df_c_plex)

        st.divider()
        
        btn_act, btn_cer = st.columns(2)
        if 'view' not in st.session_state: st.session_state.view = "ACT"
        if btn_act.button("⏳ ACTIVAS", use_container_width=True): st.session_state.view = "ACT"; st.rerun()
        if btn_cer.button("✅ CERRADAS HOY", use_container_width=True): st.session_state.view = "CER"; st.rerun()

        df_ver = vivas if st.session_state.view == "ACT" else cerradas_hoy_df
        df_estilo, _ = aplicar_estilos_df(df_ver)
        
        # LA TABLA PRINCIPAL TAMBIÉN TIENE EL COLUMN_CONFIG PARA OPTIMIZAR EL ESPACIO
        tabla = st.dataframe(
            df_estilo, 
            use_container_width=True, 
            height=500, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row",
            column_config={
                "GPS": st.column_config.LinkColumn("UBICACIÓN GPS"),
                "NOMBRE": st.column_config.TextColumn("NOMBRE", width="medium"),
                "COLONIA": st.column_config.TextColumn("COLONIA", width="medium"),
                "COMENTARIO": st.column_config.TextColumn("COMENTARIO", width="large")
            }
        )
        
        if tabla.selection.rows:
            mostrar_comentario_cierre(df_ver.iloc[tabla.selection.rows[0]])

    elif nav == "📊 Reportes":
        st.title("📊 Centro de Reportes")
        st.info("Función en mantenimiento de formato.")

    elif nav == "🚙 Vehículos":
        mostrar_auditoria(ancho < 800, conn)

if __name__ == "__main__": 
    verificar_autenticacion()
    if st.session_state.get('autenticado'):
        main()
    else:
        mostrar_pantalla_login()
