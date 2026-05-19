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
# CONFIGURACIÓN TÉCNICA Y TIEMPO
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def aplicar_estilos_nativos_expedientes():
    """Inyecta el CSS de UI_COMPONENTS para consistencia visual"""
    st.markdown("""
        <style>
        #MainMenu {visibility: hidden;} header {visibility: hidden;} footer {visibility: hidden;}
        .block-container { padding-top: 1rem !important; padding-bottom: 6rem !important; }
        
        /* Estilos de Tarjetas Estilo ui_components */
        .expediente-card {
            background-color: #1A1D24;
            padding: 15px;
            border-radius: 10px;
            border-left: 5px solid #2D2F39;
            margin-bottom: 12px;
            border: 1px solid #2D2F39;
        }
        
        /* Badges de Colores */
        .badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            text-transform: uppercase;
            margin-bottom: 5px;
            display: inline-block;
        }
        .badge-rojo { background-color: #9b111e; color: white; }
        .badge-azul { background-color: #3b82f6; color: white; }
        .badge-naranja { background-color: #f57c00; color: white; }
        </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# DIÁLOGOS (MODALES) - ESTILO UI_COMPONENTS
# ==============================================================================
@st.dialog("Detalle Completo del Expediente")
def mostrar_detalle_expediente(row):
    st.markdown(f"### 📋 Registro de: {row['TECNICO']}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**📌 Motivo:** {row['TIPO_FALTA']}")
        st.write(f"**📅 Fecha Suceso:** {row['FECHA_INCIDENCIA']}")
    with col2:
        st.write(f"**👤 Supervisor:** {row.get('SUPERVISOR', 'N/D')}")
        st.write(f"**🕒 Registro:** {row['FECHA_REGISTRO']}")

    st.markdown("---")
    st.markdown("##### 📝 Descripción de los Hechos")
    st.info(row['COMENTARIO'])

    if row.get('URL_FOTO'):
        st.markdown("##### 🖼️ Evidencias Registradas")
        urls = str(row['URL_FOTO']).split(',')
        for url in urls:
            if url.strip().startswith('http'):
                st.image(url.strip(), use_container_width=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar Detalle", use_container_width=True):
        st.rerun()

# ==============================================================================
# LÓGICA DE DATOS Y PDF (SE MANTIENE IGUAL POR FUNCIONALIDAD)
# ==============================================================================
def leer_expedientes_limpio(conn):
    st.cache_data.clear()
    df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    columnas = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
    if df.empty: return pd.DataFrame(columns=columnas)
    df.columns = df.columns.astype(str).str.strip().str.upper()
    for col in columnas:
        if col not in df.columns: df[col] = ""
    return df[df['TECNICO'].astype(str).str.strip() != ""][columnas]

@st.cache_data(show_spinner=False)
def cargar_personal(filepath="personal_tecnico.txt"):
    try:
        if not os.path.exists(filepath): return []
        with open(filepath, 'r', encoding='utf-8') as f:
            nombres = [linea.split(',')[0].strip().upper() for linea in f if linea.strip()]
        return sorted(list(set(nombres)))
    except: return []

# ... (Mantener aquí tus funciones generar_pdf_consolidado y generar_pdf_memo del turno anterior) ...

# ==============================================================================
# MÓDULO PRINCIPAL (PARA APP.PY)
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    aplicar_estilos_nativos_expedientes()
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'

    st.markdown("### 📁 Gestión de Personal y Expedientes")

    # --- MÉTRICAS SUPERIORES (Estilo ui_components) ---
    df_raw = leer_expedientes_limpio(conn)
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total General", len(df_raw))
    with m2:
        médicos = len(df_raw[df_raw['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)])
        st.metric("Médicos", médicos)
    with m3:
        st.metric("Faltas", len(df_raw) - médicos)

    # --- FORMULARIO DE INGRESO (MODERNO) ---
    with st.expander("➕ NUEVO REGISTRO", expanded=False):
        with st.form("form_incidencia_v3", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                lista_personal = cargar_personal()
                colaborador = st.selectbox("👤 Técnico", options=["---"] + lista_personal)
                motivo = st.selectbox("📋 Motivo", ["Llegada Tarde", "Exceso de Velocidad", "Abandono de Ruta", "Mala Documentación", "Incidencia Médica", "Otro"])
            with col_b:
                f_inc = st.date_input("📅 Fecha Incidencia", value=get_honduras_time().date())
                evidencias = st.file_uploader("🖼️ Fotos", type=['jpg','png'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción de los hechos")
            if st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True):
                if colaborador == "---" or not comentario:
                    st.error("Campos obligatorios faltantes")
                else:
                    with st.spinner("Subiendo..."):
                        urls = []
                        if evidencias:
                            for img in evidencias:
                                res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(img.getvalue()).decode('utf-8'), "format": "json"})
                                if res.status_code == 200: urls.append(res.json()["image"]["url"])
                        
                        nueva_fila = [get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"), colaborador, motivo, f_inc.strftime("%d/%m/%Y"), comentario, ", ".join(urls), supervisor_actual]
                        doc = conn.client.open_by_url(st.secrets["url_base_datos"]); hoja = doc.worksheet("Expedientes")
                        hoja.append_row(nueva_fila)
                        st.cache_data.clear(); st.success("✅ Guardado"); time.sleep(1); st.rerun()

    st.markdown("---")

    # --- BUSCADOR Y FILTROS ---
    c_busq, c_tipo = st.columns([2, 1])
    with c_busq:
        filtro_nombre = st.selectbox("🔍 Buscar Técnico:", ["VER TODOS"] + sorted(df_raw['TECNICO'].unique().tolist()))
    with c_tipo:
        filtro_tipo = st.selectbox("📋 Filtro:", ["Todos", "Llamados Atención", "Médicos"])

    # --- LISTADO ESTILO UI_COMPONENTS ---
    df_f = df_raw.copy()
    if filtro_nombre != "VER TODOS": df_f = df_f[df_f['TECNICO'] == filtro_nombre]
    
    if filtro_tipo == "Médicos":
        df_f = df_f[df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    elif filtro_tipo == "Llamados Atención":
        df_f = df_f[~df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]

    if df_f.empty:
        st.info("No hay registros para mostrar.")
    else:
        for idx, row in df_f.iloc[::-1].iterrows():
            # Determinar color de badge
            tipo_upper = str(row['TIPO_FALTA']).upper()
            if "MEDICA" in tipo_upper: b_style = "badge-azul"
            elif tipo_upper in ["EXCESO DE VELOCIDAD", "ABANDONO DE RUTA"]: b_style = "badge-rojo"
            else: b_style = "badge-naranja"

            st.markdown(f"""
                <div class="expediente-card">
                    <div class="badge {b_style}">{row['TIPO_FALTA']}</div>
                    <div style="display: flex; justify-content: space-between;">
                        <b style="color: white; font-size: 16px;">{row['TECNICO']}</b>
                        <span style="color: #94A3B8; font-size: 12px;">{row['FECHA_INCIDENCIA']}</span>
                    </div>
                    <div style="color: #CBD5E1; font-size: 13px; margin-top: 8px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">
                        {row['COMENTARIO']}
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Botones de Acción
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
            with btn_col1:
                if st.button("👁️ Detalles", key=f"view_{idx}", use_container_width=True):
                    mostrar_detalle_expediente(row)
            with btn_col2:
                # Generar PDF Memo (Usa tu función generar_pdf_memo)
                try:
                    pdf_data = generar_pdf_memo(row.to_dict())
                    st.download_button("📄 PDF", data=pdf_data, file_name=f"Exp_{idx}.pdf", key=f"pdf_{idx}", use_container_width=True)
                except: st.button("📄 PDF", disabled=True, key=f"pdf_err_{idx}")
            with btn_col3:
                if es_admin:
                    if st.button("🗑️", key=f"del_{idx}", use_container_width=True):
                        doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                        hoja = doc.worksheet("Expedientes")
                        hoja.delete_rows(idx + 2)
                        st.cache_data.clear(); st.rerun()
