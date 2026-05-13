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
    """Retorna la hora exacta de Honduras (UTC-6)"""
    return datetime.utcnow() - timedelta(hours=6)

# ==============================================================================
# 1. LÓGICA DE PDF (Clase Base)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try: 
                self.image('logo.png', 10, 6, 35)
            except: 
                pass
        self.set_y(10)
        self.set_x(50)
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 8)
        self.set_x(50)
        self.cell(0, 5, "Reporte Oficial de Gestión de Personal", ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, 22, 200, 22)
        self.ln(10)
        
    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto): 
        return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# 2. GENERADORES DE DOCUMENTOS PDF
# ==============================================================================
def generar_pdf_consolidado(df):
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)
    
    if df.empty:
        pdf.set_font("Helvetica", "I", 12)
        pdf.cell(0, 10, "No hay registros disponibles.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "Resumen por Clasificación:", ln=True)
        for cat, total in df['CATEGORIA'].value_counts().items():
            pdf.set_font("Helvetica", "", 11)
            pdf.cell(0, 7, f"- {cat}: {total}", ln=True)
        pdf.ln(10)
        # Detalle simple para gerencia
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "Desglose de Eventos:", ln=True)
        for _, row in df.iterrows():
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, sanitizar(f"[{row['FECHA_INCIDENCIA']}] {row['TECNICO']} - {row['CATEGORIA']}"), ln=True)
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(0, 4, f"   {sanitizar(row['TIPO_FALTA'])}: {sanitizar(row['COMENTARIO'][:100])}...", ln=True)
            pdf.ln(2)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

def generar_pdf_memo(row):
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(180, 0, 0)
    
    titulo = "MEMORANDUM: LLAMADO DE ATENCION" if row['CATEGORIA'] == "Falta Disciplinaria" else "REPORTE DE INCIDENCIA OPERATIVA"
    pdf.cell(0, 10, titulo, ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(40, 8, " Colaborador:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(150, 8, f" {sanitizar(row['TECNICO'])}", border=1, ln=True)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(40, 8, " Clasificacion:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(150, 8, f" {sanitizar(row['CATEGORIA'])}", border=1, ln=True)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(40, 8, " Motivo:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(150, 8, f" {sanitizar(row['TIPO_FALTA'])}", border=1, ln=True)
    
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 8, "Descripción de los Hechos:", ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row['COMENTARIO']), width=95): 
        pdf.cell(0, 6, sanitizar(l), ln=True)
        
    urls = str(row.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=10)
            if r.status_code == 200:
                fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
                with open(tp, 'wb') as f: f.write(r.content)
                if pdf.get_y() > 140: pdf.add_page()
                pdf.image(tp, x=15, w=170); pdf.ln(5); os.remove(tp)
        except: pass
        
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', 'Supervisor')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    # --- REGISTRO ---
    with st.expander("➕ Crear Nuevo Registro (Falta o Incidencia)", expanded=True):
        with st.form("form_expediente_final", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                tecnico_sel = st.selectbox("👤 Seleccionar Técnico de la lista:", options=["---"] + lista_tecs)
                nombre_manual = st.text_input("👷 O escribir nombre (AYUDANTE / OTRO):", placeholder="Si escribe aquí, se ignora la lista")
                
                # NUEVO CAMPO SOLICITADO
                categoria_reg = st.radio("🏷️ Clasificación del Registro:", ["Falta Disciplinaria", "Incidencia Operativa"], horizontal=True)
                
            with c2:
                tipo_evento = st.selectbox("🚫 Motivo:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Tiempos Muertos", "Mala Documentación", "Falla de Protocolo", "Otro"])
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias Visuales:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción detallada:")
            
            if st.form_submit_button("💾 GUARDAR EN EXPEDIENTE"):
                # UNIFICACIÓN Y PRIORIDAD
                final_name = nombre_manual.strip().upper() if nombre_manual.strip() != "" else (tecnico_sel.upper() if tecnico_sel != "---" else "")
                
                if not final_name:
                    st.error("❌ ERROR: Debe indicar un nombre (seleccionando de la lista o escribiéndolo).")
                elif not comentario:
                    st.error("❌ ERROR: La descripción es obligatoria.")
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
                            "TECNICO": final_name,
                            "CATEGORIA": categoria_reg, # NUEVA COLUMNA
                            "TIPO_FALTA": tipo_evento,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        
                        # Aseguramos que la columna nueva exista en la base actual
                        if "CATEGORIA" not in df_db.columns: 
                            df_db["CATEGORIA"] = "Falta Disciplinaria"
                        
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        st.cache_data.clear()
                        st.success(f"✅ ¡Registro guardado para {final_name}!")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0).dropna(subset=['TECNICO'], how='all')
        
        if not df_view.empty:
            # UNIFICAR NOMBRES PARA EL FILTRO
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.upper().str.strip()
            
            c_v, c_b = st.columns([3, 1])
            with c_b:
                st.download_button("📊 Reporte Gerencial", data=generar_pdf_consolidado(df_view), file_name="Reporte_Gerencial_Expedientes.pdf", mime="application/pdf", use_container_width=True)

            opciones = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar por Nombre:", options=opciones)
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                # Color según categoría
                color = "#EF4444" if row.get('CATEGORIA') == "Falta Disciplinaria" else "#3B82F6"
                
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {color}; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <div style="display: flex; justify-content: space-between;">
                            <h3 style="margin:0; color:white;">{row['TECNICO']}</h3>
                            <span style="background:{color}; color:white; padding:2px 10px; border-radius:15px; font-size:12px; font-weight:bold;">{row.get('CATEGORIA', 'FALTA')}</span>
                        </div>
                        <p style="margin:5px 0; color:#94A3B8;"><b>Motivo:</b> {row['TIPO_FALTA']} | <b>Fecha:</b> {row['FECHA_INCIDENCIA']}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; margin:10px 0; color:white; border: 1px solid #2D2F39;">{row['COMENTARIO']}</div>
                        <p style="font-size:0.8rem; color:#64748B;">Registrado por {row.get('SUPERVISOR','N/D')} el {row['FECHA_REGISTRO']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c_p, c_d = st.columns(2)
                    with c_p:
                        st.download_button(f"📄 Descargar {('Memo' if row.get('CATEGORIA') == 'Falta Disciplinaria' else 'Reporte')}", data=generar_pdf_memo(row), file_name=f"Documento_{idx}.pdf", key=f"pdf_{idx}", use_container_width=True)
                    with c_d:
                        if es_admin and st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                            df_new = df_view.drop(idx)
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                            st.cache_data.clear(); st.rerun()
        else:
            st.info("No hay registros disciplinarios aún.")
    except:
        st.warning("⚠️ Error al cargar historial. Verifique la pestaña 'Expedientes'.")
