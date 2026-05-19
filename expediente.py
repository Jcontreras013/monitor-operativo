import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta, timezone
import os
import tempfile
import textwrap
import time
from fpdf import FPDF

# ==============================================================================
# CONFIGURACIÓN TÉCNICA
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def aplicar_estilos_nativos_expedientes():
    st.markdown("""
        <style>
        #MainMenu {visibility: hidden;} header {visibility: hidden;} footer {visibility: hidden;}
        .block-container { padding-top: 1rem !important; padding-bottom: 6rem !important; }
        
        .expediente-card {
            background-color: #1A1D24;
            padding: 15px;
            border-radius: 10px;
            border: 1px solid #2D2F39;
            margin-bottom: 12px;
        }
        
        .badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            text-transform: uppercase;
            display: inline-block;
            margin-bottom: 8px;
        }
        .badge-rojo { background-color: #9b111e; color: white; }
        .badge-azul { background-color: #3b82f6; color: white; }
        .badge-naranja { background-color: #f57c00; color: white; }
        </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# DIÁLOGOS (MODALES)
# ==============================================================================
@st.dialog("Detalle del Expediente")
def mostrar_detalle_expediente(row):
    st.markdown(f"### 📋 {row['TECNICO']}")
    st.markdown(f"**Motivo:** {row['TIPO_FALTA']} | **Fecha:** {row['FECHA_INCIDENCIA']}")
    st.markdown("---")
    st.markdown("##### 📝 Descripción de los Hechos")
    st.info(row['COMENTARIO'])
    
    if row.get('URL_FOTO'):
        st.markdown("##### 🖼️ Evidencias")
        for url in str(row['URL_FOTO']).split(','):
            if url.strip().startswith('http'):
                st.image(url.strip(), use_container_width=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar", use_container_width=True): st.rerun()

# ==============================================================================
# LÓGICA DE DATOS Y PDF
# ==============================================================================
def leer_expedientes_limpio(conn):
    st.cache_data.clear()
    df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    cols = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
    if df.empty: return pd.DataFrame(columns=cols)
    df.columns = df.columns.astype(str).str.strip().str.upper()
    for c in cols: 
        if c not in df.columns: df[c] = ""
    return df[df['TECNICO'].astype(str).str.strip() != ""][cols]

# ... (Aquí irían tus clases MemoPDF y funciones generar_pdf_memo / consolidado) ...
# [Mantenlas igual que en tu código original para no perder la capacidad de impresión]

# ==============================================================================
# MÓDULO PRINCIPAL
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    aplicar_estilos_nativos_expedientes()
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'

    st.markdown("### 📁 Gestión de Expedientes")

    # --- MÉTRICAS ---
    df_raw = leer_expedientes_limpio(conn)
    m1, m2, m3 = st.columns(3)
    m_count = len(df_raw[df_raw['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)])
    m1.metric("Total", len(df_raw))
    m2.metric("Médicos", m_count)
    m3.metric("Faltas", len(df_raw) - m_count)

    # --- FORMULARIO DE INGRESO ---
    with st.expander("➕ NUEVO REGISTRO", expanded=False):
        with st.form("form_incidencias", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                lista_tecnicos = cargar_personal("personal_tecnico.txt")
                colab = st.selectbox("👤 Técnico", options=["---"] + lista_tecnicos)
                falta = st.selectbox("📋 Motivo", ["Llegada Tarde", "Exceso de Velocidad", "Abandono de Ruta", "Mala Documentación", "Incidencia Médica", "Otro"])
            with col_b:
                f_inc = st.date_input("📅 Fecha", value=get_honduras_time().date())
                fotos = st.file_uploader("📸 Fotos", type=['jpg','png'], accept_multiple_files=True)
            
            coment = st.text_area("📝 Descripción")
            if st.form_submit_button("💾 GUARDAR", use_container_width=True):
                if colab == "---" or not coment: st.error("Faltan datos")
                else:
                    with st.spinner("Guardando..."):
                        # (Lógica de subida FreeImage y append_row)
                        st.success("Guardado"); time.sleep(1); st.rerun()

    st.markdown("---")

    # --- FILTROS (REINCORPORADOS) ---
    st.subheader("🔍 Filtros de Búsqueda")
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        filtro_nombre = st.selectbox("👤 Colaborador:", ["TODOS"] + sorted(df_raw['TECNICO'].unique().tolist()))
        # SELECTOR DE FECHAS (REINCORPORADO)
        rango_fechas = st.date_input("📅 Rango de Fechas:", value=(get_honduras_time().date() - timedelta(days=60), get_honduras_time().date()))
    with f_col2:
        # SELECTOR DE TIPO (REINCORPORADO)
        filtro_tipo = st.selectbox("📋 Tipo de Registro:", ["Todos", "Llamado de Atención", "Incidencia Médica"])
        if not df_raw.empty:
            st.download_button("📊 Reporte General PDF", data=generar_pdf_consolidado(df_raw), file_name="Reporte.pdf", use_container_width=True)

    # --- LÓGICA DE FILTRADO ---
    df_f = df_raw.copy()
    
    # Filtro Nombre
    if filtro_nombre != "TODOS": df_f = df_f[df_f['TECNICO'] == filtro_nombre]
    
    # Filtro Tipo
    if filtro_tipo == "Incidencia Médica":
        df_f = df_f[df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    elif filtro_tipo == "Llamado de Atención":
        df_f = df_f[~df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    
    # Filtro Fecha (Reincorporado)
    if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
        f_inicio, f_fin = rango_fechas
        df_f['FECHA_DT'] = pd.to_datetime(df_f['FECHA_INCIDENCIA'], format='%d/%m/%Y', errors='coerce').dt.date
        df_f = df_f[(df_f['FECHA_DT'] >= f_inicio) & (df_f['FECHA_DT'] <= f_fin)]

    # --- LISTADO DE TARJETAS CON BOTÓN ELIMINAR ---
    if df_f.empty:
        st.info("No se encontraron registros.")
    else:
        for idx, row in df_f.iloc[::-1].iterrows():
            tipo = str(row['TIPO_FALTA']).upper()
            b_style = "badge-azul" if "MEDICA" in tipo else ("badge-rojo" if tipo in ["EXCESO DE VELOCIDAD", "ABANDONO DE RUTA"] else "badge-naranja")

            with st.container():
                st.markdown(f"""
                    <div class="expediente-card">
                        <div class="badge {b_style}">{row['TIPO_FALTA']}</div>
                        <div style="display: flex; justify-content: space-between;">
                            <b style="color: white; font-size: 15px;">{row['TECNICO']}</b>
                            <span style="color: #94A3B8; font-size: 11px;">{row['FECHA_INCIDENCIA']}</span>
                        </div>
                        <p style="color: #CBD5E1; font-size: 13px; margin-top: 5px; height: 35px; overflow: hidden;">{row['COMENTARIO']}</p>
                    </div>
                """, unsafe_allow_html=True)
                
                # BOTONES DE ACCIÓN (Eliminar incluido)
                b1, b2, b3 = st.columns([1, 1, 1])
                with b1:
                    if st.button("👁️ Ver", key=f"v_{idx}", use_container_width=True): 
                        mostrar_detalle_expediente(row)
                with b2:
                    st.download_button("📄 PDF", data=generar_pdf_memo(row.to_dict()), file_name=f"Exp_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
                with b3:
                    # BOTÓN ELIMINAR (Solo Admin)
                    if es_admin:
                        if st.button("🗑️", key=f"del_{idx}", use_container_width=True, help="Eliminar permanentemente"):
                            doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                            hoja = doc.worksheet("Expedientes")
                            # Buscamos la fila exacta en Google Sheets (idx es el indice del dataframe original)
                            # Google Sheets empieza en 1 y tiene cabecera, por eso se ajusta
                            hoja.delete_rows(idx + 2) 
                            st.cache_data.clear()
                            st.success("Eliminado")
                            time.sleep(0.5)
                            st.rerun()
