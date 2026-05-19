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
# 1. FUNCIONES DE APOYO Y TIEMPO
# ==============================================================================
def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto) or texto is None: return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

@st.cache_data(show_spinner=False)
def cargar_personal(filepath="personal_tecnico.txt"):
    try:
        if not os.path.exists(filepath): return []
        with open(filepath, 'r', encoding='utf-8') as f:
            lineas = f.readlines()
        nombres = []
        for linea in lineas:
            linea = linea.strip()
            if linea:
                nombre_crudo = linea.split(',')[0]
                nombre_limpio = " ".join(nombre_crudo.replace('\t', ' ').split()).upper()
                if nombre_limpio: nombres.append(nombre_limpio)
        return sorted(list(set(nombres)))
    except: return []

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
# 2. LÓGICA DE PDF (CLASE Y GENERADORES)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try: self.image('logo.png', 10, 6, 35)
            except: pass
        self.set_y(10); self.set_x(50); self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 8); self.set_x(50)
        self.cell(0, 5, "Reporte Oficial de Gestion de Personal", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
        
    def footer(self):
        self.set_y(-15); self.set_text_color(150, 150, 150); self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def generar_pdf_consolidado(df):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "REPORTE CONSOLIDADO", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(30, 8, " Fecha", border=1, fill=True); pdf.cell(50, 8, " Tecnico", border=1, fill=True)
    pdf.cell(40, 8, " Motivo", border=1, fill=True); pdf.cell(70, 8, " Comentario", border=1, ln=True, fill=True)
    pdf.set_font("Helvetica", "", 8)
    for _, r in df.iterrows():
        pdf.cell(30, 7, sanitizar(r['FECHA_INCIDENCIA']), border=1)
        pdf.cell(50, 7, sanitizar(r['TECNICO']), border=1)
        pdf.cell(40, 7, sanitizar(r['TIPO_FALTA']), border=1)
        pdf.cell(70, 7, sanitizar(str(r['COMENTARIO'])[:45]), border=1, ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    es_m = "MEDICA" in str(row_dict.get('TIPO_FALTA')).upper()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0,102,204) if es_m else pdf.set_text_color(180,0,0)
    pdf.cell(0, 10, "INCIDENCIA MEDICA" if es_m else "MEMORANDUM DE ATENCION", ln=True, align="C")
    pdf.ln(5); pdf.set_text_color(0,0,0); pdf.set_font("Helvetica", "B", 10)
    for k, v in [("Colaborador", "TECNICO"), ("Motivo", "TIPO_FALTA"), ("Fecha", "FECHA_INCIDENCIA"), ("Supervisor", "SUPERVISOR")]:
        pdf.cell(40, 8, f" {k}:", border=1, fill=True); pdf.set_font("Helvetica", "", 10)
        pdf.cell(150, 8, f" {sanitizar(row_dict.get(v))}", border=1, ln=True); pdf.set_font("Helvetica", "B", 10)
    pdf.ln(5); pdf.cell(0, 8, "Detalle:", ln=True); pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, sanitizar(row_dict.get('COMENTARIO')))
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 3. LÓGICA DE DATOS (LECTURA Y MODALES)
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

@st.dialog("Detalle del Expediente")
def mostrar_detalle_expediente(row):
    st.markdown(f"### 📋 {row['TECNICO']}")
    st.markdown(f"**Motivo:** {row['TIPO_FALTA']} | **Fecha:** {row['FECHA_INCIDENCIA']}")
    st.markdown("---")
    st.info(row['COMENTARIO'])
    if row.get('URL_FOTO'):
        for url in str(row['URL_FOTO']).split(','):
            if url.strip().startswith('http'): st.image(url.strip(), use_container_width=True)
    if st.button("Cerrar", use_container_width=True): st.rerun()

# ==============================================================================
# 4. FUNCIÓN PRINCIPAL LLAMADA POR APP.PY
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    aplicar_estilos_nativos_expedientes()
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'
    API_KEY = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

    st.markdown("### 📁 Gestión de Expedientes")

    # MÉTRICAS
    df_raw = leer_expedientes_limpio(conn)
    m1, m2, m3 = st.columns(3)
    med = len(df_raw[df_raw['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)])
    m1.metric("Total", len(df_raw)); m2.metric("Médicos", med); m3.metric("Faltas", len(df_raw)-med)

    # FORMULARIO
    with st.expander("➕ NUEVO REGISTRO", expanded=False):
        with st.form("form_inc", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                tecnico = st.selectbox("👤 Técnico", options=["---"] + cargar_personal())
                motivo = st.selectbox("📋 Motivo", ["Llegada Tarde", "Exceso de Velocidad", "Abandono de Ruta", "Mala Documentación", "Incidencia Médica", "Otro"])
            with c2:
                fecha = st.date_input("📅 Fecha", value=get_honduras_time().date())
                fotos = st.file_uploader("📸 Fotos", type=['jpg','png'], accept_multiple_files=True)
            obs = st.text_area("📝 Descripción")
            if st.form_submit_button("💾 GUARDAR", use_container_width=True):
                if tecnico == "---" or not obs: st.error("Faltan datos")
                else:
                    with st.spinner("Guardando..."):
                        urls = []
                        if fotos:
                            for f in fotos:
                                r = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY, "action": "upload", "source": base64.b64encode(f.getvalue()).decode('utf-8'), "format": "json"})
                                if r.status_code == 200: urls.append(r.json()["image"]["url"])
                        nueva_f = [get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"), tecnico, motivo, fecha.strftime("%d/%m/%Y"), obs, ", ".join(urls), supervisor_actual]
                        doc = conn.client.open_by_url(st.secrets["url_base_datos"]); h = doc.worksheet("Expedientes")
                        h.append_row(nueva_f); st.cache_data.clear(); st.success("Guardado"); time.sleep(1); st.rerun()

    # FILTROS
    st.markdown("---")
    f1, f2 = st.columns(2)
    with f1:
        f_nom = st.selectbox("👤 Colaborador:", ["TODOS"] + sorted(df_raw['TECNICO'].unique().tolist()))
        f_rango = st.date_input("📅 Rango:", value=(get_honduras_time().date()-timedelta(days=60), get_honduras_time().date()))
    with f2:
        f_tipo = st.selectbox("📋 Tipo:", ["Todos", "Llamado de Atención", "Incidencia Médica"])
        if not df_raw.empty: st.download_button("📊 Reporte General", data=generar_pdf_consolidado(df_raw), file_name="Reporte.pdf", use_container_width=True)

    # FILTRADO LÓGICO
    df_f = df_raw.copy()
    if f_nom != "TODOS": df_f = df_f[df_f['TECNICO'] == f_nom]
    if f_tipo == "Incidencia Médica": df_f = df_f[df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    elif f_tipo == "Llamado de Atención": df_f = df_f[~df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    if isinstance(f_rango, (list, tuple)) and len(f_rango) == 2:
        df_f['FECHA_DT'] = pd.to_datetime(df_f['FECHA_INCIDENCIA'], format='%d/%m/%Y', errors='coerce').dt.date
        df_f = df_f[(df_f['FECHA_DT'] >= f_rango[0]) & (df_f['FECHA_DT'] <= f_rango[1])]

    # TARJETAS
    if df_f.empty: st.info("Sin registros.")
    else:
        for idx, row in df_f.iloc[::-1].iterrows():
            es_m = "MEDICA" in str(row['TIPO_FALTA']).upper() or "MÉDICA" in str(row['TIPO_FALTA']).upper()
            b_s = "badge-azul" if es_m else "badge-naranja"
            st.markdown(f'<div class="expediente-card"><div class="badge {b_s}">{row["TIPO_FALTA"]}</div><div style="display:flex;justify-content:space-between;"><b style="color:white;">{row["TECNICO"]}</b><span style="color:#94A3B8;font-size:11px;">{row["FECHA_INCIDENCIA"]}</span></div><p style="color:#CBD5E1;font-size:13px;margin-top:5px;height:35px;overflow:hidden;">{row["COMENTARIO"]}</p></div>', unsafe_allow_html=True)
            b1, b2, b3 = st.columns([1,1,1])
            with b1: 
                if st.button("👁️ Ver", key=f"v_{idx}", use_container_width=True): mostrar_detalle_expediente(row)
            with b2: 
                st.download_button("📄 PDF", data=generar_pdf_memo(row.to_dict()), file_name=f"Exp_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
            with b3:
                if es_admin:
                    if st.button("🗑️", key=f"del_{idx}", use_container_width=True):
                        doc = conn.client.open_by_url(st.secrets["url_base_datos"]); h = doc.worksheet("Expedientes")
                        h.delete_rows(idx + 2); st.cache_data.clear(); st.rerun()
