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
# 1. UTILIDADES Y CONFIGURACIÓN (RESTAURADO)
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
            nombres = [l.split(',')[0].strip().upper() for l in f if l.strip()]
        return sorted(list(set(nombres)))
    except: return []

# ==============================================================================
# 2. ESTILOS CSS (ESTÉTICA PREMIUM)
# ==============================================================================
def aplicar_estilos_premium():
    st.markdown("""
        <style>
        .metric-card {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.1); text-align: center;
        }
        .expediente-card {
            background-color: #1A1D24; padding: 15px; border-radius: 10px;
            border: 1px solid #2D2F39; margin-bottom: 10px;
        }
        .badge {
            padding: 2px 10px; border-radius: 20px; font-size: 10px; font-weight: bold; text-transform: uppercase;
        }
        .badge-rojo { background-color: #9b111e; color: white; }
        .badge-azul { background-color: #3b82f6; color: white; }
        .badge-naranja { background-color: #f57c00; color: white; }
        </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# 3. LÓGICA DE PDF (RESTAURADA COMPLETA)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try: self.image('logo.png', 10, 6, 35)
            except: pass
        self.set_y(10); self.set_x(50); self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - CONTROL OPERATIVO", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
    def footer(self):
        self.set_y(-15); self.set_font("Helvetica", "I", 8); self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def generar_pdf_memo(row):
    pdf = MemoPDF(); pdf.add_page()
    es_m = "MEDICA" in str(row['TIPO_FALTA']).upper()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180,0,0)
    pdf.cell(0, 10, "MEMORANDUM" if not es_m else "CONSTANCIA MEDICA", ln=True, align="C")
    pdf.ln(5); pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0,0,0)
    for k, v in [("Tecnico", row['TECNICO']), ("Motivo", row['TIPO_FALTA']), ("Fecha", row['FECHA_INCIDENCIA'])]:
        pdf.cell(40, 8, f" {k}:", border=1, fill=True); pdf.cell(150, 8, f" {sanitizar(v)}", border=1, ln=True)
    pdf.ln(5); pdf.multi_cell(0, 6, f"Comentario: {sanitizar(row['COMENTARIO'])}", border=1)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

def generar_pdf_consolidado(df):
    pdf = MemoPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 14); pdf.cell(0, 10, "REPORTE DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "B", 8); pdf.set_fill_color(240, 240, 240)
    pdf.cell(30, 8, " Fecha", border=1, fill=True); pdf.cell(50, 8, " Tecnico", border=1, fill=True); pdf.cell(110, 8, " Motivo", border=1, ln=True, fill=True)
    pdf.set_font("Helvetica", "", 8)
    for _, r in df.iterrows():
        pdf.cell(30, 7, r['FECHA_INCIDENCIA'], border=1); pdf.cell(50, 7, sanitizar(r['TECNICO']), border=1); pdf.cell(110, 7, sanitizar(r['TIPO_FALTA']), border=1, ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 4. LÓGICA DE DATOS (EL MOTOR)
# ==============================================================================
def leer_datos_maestros(conn):
    st.cache_data.clear()
    df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    
    # Limpieza
    columnas_esperadas = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
    if df.empty:
        df = pd.DataFrame(columns=columnas_esperadas)
    else:
        df.columns = df.columns.astype(str).str.strip().str.upper()
        df = df[df['TECNICO'].notna() & (df['TECNICO'].astype(str) != "")]

    # ANTI-LAG: Inyectar lo que acabamos de guardar en esta sesión
    if 'buffer_expedientes' in st.session_state:
        for reg in st.session_state['buffer_expedientes']:
            if reg['FECHA_REGISTRO'] not in df['FECHA_REGISTRO'].astype(str).values:
                df = pd.concat([df, pd.DataFrame([reg])], ignore_index=True)
    
    return df

# ==============================================================================
# 5. MÓDULO PRINCIPAL
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    aplicar_estilos_premium()
    supervisor = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'

    st.title("📁 Expedientes y Personal")

    # --- MÉTRICAS ---
    df_full = leer_datos_maestros(conn)
    m1, m2, m3 = st.columns(3)
    medicos_n = len(df_full[df_full['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)])
    with m1: st.markdown(f'<div class="metric-card"><small>TOTAL</small><br><b>{len(df_full)}</b></div>', unsafe_allow_html=True)
    with m2: st.markdown(f'<div class="metric-card"><small>MÉDICOS</small><br><b>{medicos_n}</b></div>', unsafe_allow_html=True)
    with m3: st.markdown(f'<div class="metric-card"><small>FALTAS</small><br><b>{len(df_full)-medicos_n}</b></div>', unsafe_allow_html=True)

    # --- FORMULARIO ---
    with st.expander("➕ REGISTRAR NUEVA INCIDENCIA", expanded=False):
        with st.form("f_nuevo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                tecnico = st.selectbox("Técnico", options=["---"] + cargar_personal())
                motivo = st.selectbox("Motivo", ["Llegada Tarde", "Exceso de Velocidad", "Abandono de Ruta", "Incidencia Médica", "Otro"])
            with c2:
                fecha = st.date_input("Fecha Suceso", value=get_honduras_time().date())
                fotos = st.file_uploader("Fotos", type=['jpg','png','jpeg'], accept_multiple_files=True)
            obs = st.text_area("Descripción de los hechos")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True):
                if tecnico == "---" or not obs:
                    st.error("Por favor llene los campos obligatorios.")
                else:
                    try:
                        with st.spinner("Guardando..."):
                            urls = []
                            if fotos:
                                for f in fotos:
                                    r = requests.post("https://freeimage.host/api/1/upload", data={"key": "6d207e02198a847aa98d0a2a901485a5", "action": "upload", "source": base64.b64encode(f.getvalue()).decode('utf-8'), "format": "json"})
                                    if r.status_code == 200: urls.append(r.json()["image"]["url"])
                            
                            nuevo_reg = {
                                "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                                "TECNICO": tecnico, "TIPO_FALTA": motivo,
                                "FECHA_INCIDENCIA": fecha.strftime("%d/%m/%Y"),
                                "COMENTARIO": obs, "URL_FOTO": ", ".join(urls), "SUPERVISOR": supervisor
                            }
                            
                            # Guardar en Buffer y Google
                            if 'buffer_expedientes' not in st.session_state: st.session_state['buffer_expedientes'] = []
                            st.session_state['buffer_expedientes'].append(nuevo_reg)
                            
                            doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                            hoja = doc.worksheet("Expedientes")
                            hoja.append_row(list(nuevo_reg.values()))
                            
                            st.cache_data.clear()
                            st.success("✅ Guardado correctamente")
                            time.sleep(1); st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

    # --- FILTROS ---
    st.markdown("---")
    f1, f2 = st.columns(2)
    with f1:
        f_tec = st.selectbox("🔍 Buscar Técnico", ["TODOS"] + sorted(df_full['TECNICO'].unique().tolist()))
        f_date = st.date_input("📅 Rango", value=(get_honduras_time().date() - timedelta(days=60), get_honduras_time().date()))
    with f2:
        f_tipo = st.selectbox("📋 Filtrar Tipo", ["Todos", "Llamado Atención", "Incidencia Médica"])
        if not df_full.empty:
            st.download_button("📊 Reporte General PDF", data=generar_pdf_consolidado(df_full), file_name="Reporte.pdf", use_container_width=True)

    # Lógica Filtrado
    df_f = df_full.copy()
    if f_tec != "TODOS": df_f = df_f[df_f['TECNICO'] == f_tec]
    if f_tipo == "Incidencia Médica": df_f = df_f[df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    elif f_tipo == "Llamado Atención": df_f = df_f[~df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False)]
    
    if isinstance(f_date, (list, tuple)) and len(f_date) == 2:
        df_f['DT'] = pd.to_datetime(df_f['FECHA_INCIDENCIA'], format='%d/%m/%Y', errors='coerce').dt.date
        df_f = df_f[(df_f['DT'] >= f_date[0]) & (df_f['DT'] <= f_date[1])]

    # --- LISTADO ---
    if df_f.empty:
        st.info("No se encontraron registros.")
    else:
        for idx, row in df_f.iloc[::-1].iterrows():
            es_m = "MEDICA" in str(row['TIPO_FALTA']).upper() or "MÉDICA" in str(row['TIPO_FALTA']).upper()
            badge_class = "badge-azul" if es_m else "badge-naranja"
            
            with st.container():
                st.markdown(f"""
                <div class="expediente-card">
                    <span class="badge {badge_class}">{row['TIPO_FALTA']}</span>
                    <div style="display:flex; justify-content:space-between; margin-top:5px;">
                        <b>{row['TECNICO']}</b> <small>{row['FECHA_INCIDENCIA']}</small>
                    </div>
                    <p style="font-size:13px; color:#CBD5E1; margin-top:5px;">{row['COMENTARIO']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                c_b1, c_b2, c_b3 = st.columns(3)
                with c_b1:
                    st.download_button("📄 PDF", data=generar_pdf_memo(row), file_name=f"Exp_{idx}.pdf", key=f"pdf_{idx}")
                with c_b2:
                    with st.popover("🖼️ Ver Fotos"):
                        if row['URL_FOTO']:
                            for u in str(row['URL_FOTO']).split(','): st.image(u.strip())
                        else: st.write("Sin fotos")
                with c_b3:
                    if es_admin:
                        if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                            doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                            hoja = doc.worksheet("Expedientes")
                            # El índice de la fila es idx + 2 (cabecera + base 1)
                            hoja.delete_rows(idx + 2)
                            st.session_state['buffer_expedientes'] = [] # Limpiar buffer para forzar recarga
                            st.cache_data.clear()
                            st.success("Eliminado"); time.sleep(1); st.rerun()
