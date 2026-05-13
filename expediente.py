import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta
import os
import tempfile
import textwrap
import time
from fpdf import FPDF

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.utcnow() - timedelta(hours=6)

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
        self.cell(0, 5, "Reporte Disciplinario Oficial", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
        
    def footer(self):
        self.set_y(-15); self.set_text_color(150, 150, 150); self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto): return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

def generar_pdf_memo(row):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0); pdf.cell(0, 10, "MEMORANDUM: LLAMADO DE ATENCION", ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 8, " Implicado:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(35, 8, " Tipo Falta:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row.get('COMENTARIO')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 2. INTERFAZ DE EXPEDIENTES
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', 'Supervisor')

    st.title("📁 Gestión de Expedientes Disciplinarios")
    
    # --- REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=True):
        with st.form("form_incidencia_unificado", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                # Limpiamos nombres de la lista para que aparezcan bonitos
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                tecnico_sel = st.selectbox("👤 Seleccionar Técnico (Si es Ayudante usar cuadro abajo):", options=["---"] + lista_tecs)
                nombre_ayudante = st.text_input("👷 Escriba nombre del AYUDANTE (Prioridad):", help="Si escribe aquí, el sistema ignorará el selector de arriba.")
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Otro"])
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Detalle detallado de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                # DETERMINAR NOMBRE FINAL CON UNIFICACIÓN (MAYÚSCULAS)
                final_name = ""
                if nombre_ayudante.strip() != "":
                    final_name = f"{nombre_ayudante.strip().upper()} (AYUDANTE)"
                elif tecnico_sel != "---":
                    final_name = tecnico_sel.strip().upper()
                
                if final_name == "":
                    st.error("❌ Error: Debe escribir un nombre o seleccionar uno de la lista.")
                elif not comentario:
                    st.error("❌ Error: El comentario es obligatorio.")
                else:
                    urls = []
                    if archivos:
                        with st.spinner("Subiendo evidencias..."):
                            for a in archivos:
                                try:
                                    res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                    if res.status_code == 200: urls.append(res.json()["image"]["url"])
                                    time.sleep(1)
                                except: pass
                    
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": final_name, # YA VA EN MAYÚSCULAS
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": ", ".join(urls),
                        "SUPERVISOR": supervisor_actual
                    }])
                    
                    try:
                        df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        st.cache_data.clear() # LIMPIEZA TOTAL DE MEMORIA
                        st.success(f"✅ ¡REGISTRADO EXITOSAMENTE!: {final_name}")
                        time.sleep(1.5)
                        st.rerun()
                    except:
                        st.error("❌ Error de conexión con Google Sheets.")

    st.markdown("---")
    st.subheader("📜 Historial Unificado")
    
    try:
        # LEEMOS Y UNIFICAMOS EL HISTORIAL PARA EL FILTRO
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0).dropna(subset=['TECNICO'], how='all')
        
        if not df_view.empty:
            # UNIFICACIÓN DE NOMBRES EN EL FILTRO
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.strip().str.upper()
            opciones_filtro = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar por Nombre (Unificado):", options=opciones_filtro)
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 5px solid #EF4444; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <h3 style="margin:0; color:white;">👨‍🔧 {row['TECNICO']}</h3>
                        <p style="margin:5px 0; color:#94A3B8;"><b>Falta:</b> {row['TIPO_FALTA']} | <b>Fecha:</b> {row['FECHA_INCIDENCIA']}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; margin:10px 0; color:white;">{row['COMENTARIO']}</div>
                        <p style="font-size:0.8rem; color:#64748B;">Registrado por {row.get('SUPERVISOR','N/D')} el {row['FECHA_REGISTRO']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c_pdf, c_del = st.columns([1, 1])
                    with c_pdf:
                        st.download_button("📄 PDF Memo", data=generar_pdf_memo(row), file_name=f"Memo_{idx}.pdf", key=f"pdf_{idx}", use_container_width=True)
                    with c_del:
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                                df_new = df_view.drop(idx)
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                                st.cache_data.clear()
                                st.rerun()
        else:
            st.info("No hay incidencias registradas.")
    except:
        st.warning("⚠️ Error al cargar historial.")
