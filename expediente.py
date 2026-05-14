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
# CONFIGURACIÓN Y CARGA DE PERSONAL
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

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

# ==============================================================================
# 1. LÓGICA DE PDF (Clase Base)
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
        self.cell(0, 5, "Reporte Oficial de Gestión de Personal", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
        
    def footer(self):
        self.set_y(-15); self.set_text_color(150, 150, 150); self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto) or texto is None: return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# 2. GENERADORES DE DOCUMENTOS PDF
# ==============================================================================
def generar_pdf_consolidado(df):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10); pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)
    if df.empty:
        pdf.set_font("Helvetica", "I", 12); pdf.cell(0, 10, "No hay registros disponibles.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen por Tipo de Evento:", ln=True)
        for cat, total in df['TIPO_FALTA'].value_counts().items():
            pdf.set_font("Helvetica", "", 11); pdf.cell(0, 7, f"- {cat}: {total}", ln=True)
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Desglose de Eventos:", ln=True)
        for _, row in df.iterrows():
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, sanitizar(f"[{row.get('FECHA_REGISTRO','')}] - {row.get('TECNICO','')}"), ln=True)
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(0, 4, f"   {sanitizar(row.get('TIPO_FALTA',''))}: {sanitizar(str(row.get('COMENTARIO',''))[:100])}...", ln=True)
            pdf.ln(2)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    es_medica = str(row_dict.get('TIPO_FALTA', '')).upper() in ["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"]
    
    if es_medica:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0, 102, 204)
        titulo = "CONSTANCIA DE INCIDENCIA MEDICA"
    else:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
        titulo = "MEMORANDUM: LLAMADO DE ATENCION"
        
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(45, 8, " Colaborador:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(145, 8, f" {sanitizar(row_dict.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(45, 8, " Motivo:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(145, 8, f" {sanitizar(row_dict.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(45, 8, " Fecha del Suceso:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(145, 8, f" {row_dict.get('FECHA_INCIDENCIA')}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(45, 8, " Registro (Fecha/Hora):", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(145, 8, f" {row_dict.get('FECHA_REGISTRO')}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(45, 8, " Supervisor:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(145, 8, f" {sanitizar(row_dict.get('SUPERVISOR'))}", border=1, ln=True)
    
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
    urls = str(row_dict.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=10)
            if r.status_code == 200:
                fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
                with open(tp, 'wb') as f: f.write(r.content)
                if pdf.get_y() > 140: pdf.add_page()
                pdf.image(tp, x=15, w=170); pdf.ln(5); os.remove(tp)
        except: pass
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES (CONEXIÓN EXACTA ORIGINAL)
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    supervisor_actual = st.session_state.get('usuario', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    with st.expander("➕ Crear Nuevo Registro", expanded=True):
        st.info(f"✍️ Supervisor registrando: **{supervisor_actual}**")
        with st.form("form_incidencia_txt", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_nombres = cargar_personal("personal_tecnico.txt")
                colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres)
                tipo_falta = st.selectbox("🚫 Motivo:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Mala Documentación", "Incidencia Médica", "Otro"
                ])
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR EN EXPEDIENTE"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ Complete el nombre y el comentario.")
                else:
                    try:
                        urls = []
                        if archivos:
                            with st.spinner("Subiendo evidencias..."):
                                for a in archivos:
                                    res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                    if res.status_code == 200: urls.append(res.json()["image"]["url"])
                                    time.sleep(1)
                        
                        nueva_fila = pd.DataFrame([{
                            "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO": colaborador_sel,
                            "TIPO_FALTA": tipo_falta,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        # --- TU CÓDIGO BASE ORIGINAL EXACTO DE GUARDADO ---
                        df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        df_final = df_final.fillna("").astype(str)
                        
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        st.cache_data.clear()
                        st.success(f"✅ ¡Guardado con éxito para {colaborador_sel}!")
                        time.sleep(1.5); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        df_view = df_view.fillna("").astype(str)
        
        # Filtramos para no mostrar filas vacías en la pantalla
        df_view = df_view[df_view['TECNICO'].str.strip() != ""]
        df_view = df_view[~df_view['TECNICO'].str.lower().isin(["nan", "none", "null"])]
        
        if not df_view.empty:
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.upper().str.strip()
            
            col_vacia, col_boton = st.columns([3, 1])
            with col_boton:
                st.download_button("📊 Reporte Gerencial", data=generar_pdf_consolidado(df_view), file_name="Reporte_General_Expedientes.pdf", mime="application/pdf", use_container_width=True)

            filtro = st.selectbox("🔍 Buscar Colaborador:", options=["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist()))
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                es_m = str(row.get('TIPO_FALTA', '')).upper() in ["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"]
                c_tag = "#3B82F6" if es_m else "#EF4444"
                
                with st.container():
                    st.markdown(f"""<div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {c_tag}; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <h3 style="margin:0; color:white;">{row['TECNICO']}</h3>
                        <p style="color:#94A3B8; margin-bottom: 2px;"><b>Motivo:</b> {row['TIPO_FALTA']} | <b>Fecha Suceso:</b> {row['FECHA_INCIDENCIA']}</p>
                        <p style="font-size:12px; color:#64748B; margin-top: 0;">⏰ <b>Registrado el:</b> {row['FECHA_REGISTRO']} por {row.get('SUPERVISOR', 'N/D')}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; color:white; margin-top: 10px;">{row['COMENTARIO']}</div>
                    </div>""", unsafe_allow_html=True)
                    
                    urls_foto = str(row.get('URL_FOTO', '')).split(',')
                    urls_validas = [u.strip() for u in urls_foto if u.strip().startswith('http')]
                    
                    if urls_validas:
                        with st.expander("🖼️ Ver Evidencia Adjunta"):
                            for url in urls_validas:
                                st.image(url, use_container_width=True)
                    
                    c_p, c_d = st.columns(2)
                    with c_p:
                        st.download_button(f"📄 Descargar {'Constancia Medica' if es_m else 'Documento'}", data=generar_pdf_memo(row.to_dict()), file_name=f"Reporte_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
                    with c_d:
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                                df_new = df_view.drop(idx)
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                                st.cache_data.clear(); st.rerun()
        else: st.info("No hay registros aún.")
    except Exception as e: st.warning(f"⚠️ Cargando historial... ({e})")
