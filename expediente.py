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
            try: self.image('logo.png', 10, 6, 35)
            except: pass
        self.set_y(10)
        self.set_x(50)
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 8)
        self.set_x(50)
        self.cell(0, 5, "Reporte Disciplinario Oficial", ln=True, align="R")
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
    if pd.isna(texto): return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# 2. GENERADOR DE REPORTE CONSOLIDADO (GERENCIA)
# ==============================================================================
def generar_pdf_consolidado(df):
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE INCIDENCIAS", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)
    
    if df.empty:
        pdf.set_font("Helvetica", "I", 12)
        pdf.cell(0, 10, "No hay registros en el sistema.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "1. Resumen Estadistico:", ln=True)
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(140, 8, " Tipo de Falta", border=1, fill=True)
        pdf.cell(50, 8, " Total", border=1, ln=True, align="C", fill=True)
        
        for f, t in df['TIPO_FALTA'].value_counts().items():
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(140, 7, f" {sanitizar(f)}", border=1)
            pdf.cell(50, 7, str(t), border=1, ln=True, align="C")
            
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "2. Detalle de Incidencias:", ln=True)
        
        for tipo in sorted(df['TIPO_FALTA'].unique()):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_text_color(180, 0, 0)
            pdf.cell(0, 8, f" CATEGORIA: {sanitizar(tipo).upper()}", border="B", ln=True, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
            
            for _, row in df[df['TIPO_FALTA'] == tipo].iterrows():
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, sanitizar(f"[{row['FECHA_INCIDENCIA']}] - {row['TECNICO']}"), ln=True)
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(100, 100, 100)
                for l in textwrap.wrap(f"Nota: {row['COMENTARIO']}", width=120): 
                    pdf.cell(0, 4, f"   {sanitizar(l)}", ln=True)
                pdf.ln(2)
                
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: 
        d = f.read()
    os.remove(path)
    return d

def generar_pdf_memo(row):
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, "MEMORANDUM: LLAMADO DE ATENCION", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 8, " Implicado:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, " Tipo Falta:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row.get('COMENTARIO')), width=95): 
        pdf.cell(0, 6, sanitizar(l), ln=True)
        
    urls = str(row.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if r.status_code == 200:
                fd, tp = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                with open(tp, 'wb') as f: f.write(r.content)
                if pdf.get_y() > 140: pdf.add_page()
                pdf.image(tp, x=15, w=170)
                pdf.ln(5)
                os.remove(tp)
        except: pass
        
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: 
        d = f.read()
    os.remove(path)
    return d

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', st.session_state.get('username', 'Supervisor'))

    st.title("📁 Gestión de Expedientes Disciplinarios")
    
    # --- REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=False):
        st.info(f"✍️ Reporte firmado por: **{supervisor_actual}**")
        with st.form("form_incidencia", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                lista_tecs.insert(0, "--- Seleccionar Técnico del Reporte ---")
                tecnico_sel = st.selectbox("👤 Técnico de la lista:", options=lista_tecs)
                
                nombre_manual = st.text_input("👷 O escriba nombre de AYUDANTE:", placeholder="Escriba aquí si no aparece en la lista")
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Pérdida de Herramientas", "Otro"])
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Detalle de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True):
                # Validar de quién es la falta
                final_name = ""
                if nombre_manual.strip() != "":
                    final_name = f"{nombre_manual.strip().upper()} (AYUDANTE)"
                elif tecnico_sel != "--- Seleccionar Técnico del Reporte ---":
                    final_name = tecnico_sel.upper()
                
                if final_name == "":
                    st.error("❌ ERROR: Debe seleccionar un técnico o escribir el nombre del ayudante.")
                elif not comentario:
                    st.error("❌ ERROR: El detalle de los hechos es obligatorio.")
                else:
                    urls = []
                    if archivos:
                        with st.spinner("Subiendo fotos a la nube..."):
                            for a in archivos:
                                try:
                                    res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                    if res.status_code == 200: urls.append(res.json()["image"]["url"])
                                    time.sleep(1)
                                except: pass
                    
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": final_name,
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": ", ".join(urls),
                        "SUPERVISOR": supervisor_actual
                    }])
                    
                    try:
                        with st.spinner("Guardando en la base de datos..."):
                            df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            
                            # Alineación estricta de columnas para evitar que se pierdan datos en GSheets
                            cols_ideales = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
                            for col in cols_ideales:
                                if col not in df_db.columns: df_db[col] = "" 
                            
                            df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                            df_final = df_final[cols_ideales]
                            
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            
                            # BORRAMOS CACHÉ Y FORZAMOS ACTUALIZACIÓN
                            st.cache_data.clear()
                            
                            st.success(f"✅ ¡Se guardó exitosamente el acta para: {final_name}!")
                            time.sleep(2)
                            st.rerun()
                    except Exception as e: 
                        st.error(f"❌ Error al conectar con la base de datos: {e}")

    st.markdown("---")
    st.subheader("📜 Historial y Reportes para Gerencia")
    
    try:
        # Aquí también nos aseguramos de que siempre baje la última versión
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0).dropna(subset=['TECNICO'], how='all')
    except:
        df_view = pd.DataFrame()

    cv, cb = st.columns([3, 1]) 
    with cb:
        st.download_button("📊 Reporte Gerencial", data=generar_pdf_consolidado(df_view), file_name=f"Reporte_Faltas_{get_honduras_time().strftime('%d%m%Y')}.pdf", mime="application/pdf", use_container_width=True, type="primary")

    if not df_view.empty:
        filtro = st.selectbox("🔍 Filtrar Historial por Nombre:", options=["Ver Todos"] + sorted(df_view['TECNICO'].unique().tolist()))
        df_mostrar = df_view if filtro == "Ver Todos" else df_view[df_view['TECNICO'] == filtro]
        
        for idx, row in df_mostrar.iloc[::-1].iterrows():
            with st.container():
                st.markdown("""<div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 4px solid #EF4444; margin-bottom: 10px;">""", unsafe_allow_html=True)
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"### 👨‍🔧 {row['TECNICO']}")
                    st.markdown(f"**🚫 Falta:** {row['TIPO_FALTA']} | **📅 Sucedió:** {row['FECHA_INCIDENCIA']}")
                    st.caption(f"**✍️ Por:** {row.get('SUPERVISOR', 'N/D')} | **⏳ Reg:** {row['FECHA_REGISTRO']}")
                    st.info(row['COMENTARIO'])
                with c2:
                    urls = str(row.get('URL_FOTO', '')).split(',')
                    for u in [x.strip() for x in urls if x.strip().startswith('http')][:1]: st.image(u, use_container_width=True)
                    st.download_button("📄 PDF Memo", data=generar_pdf_memo(row), file_name=f"Memo_{row['TECNICO']}.pdf", key=f"m_{idx}", use_container_width=True)
                    if es_admin:
                        if st.button("🗑️ Eliminar", key=f"d_{idx}", use_container_width=True):
                            df_upd = df_view[~((df_view['FECHA_REGISTRO'] == row['FECHA_REGISTRO']) & (df_view['TECNICO'] == row['TECNICO']))]
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_upd)
                            st.cache_data.clear() # Limpiamos caché al eliminar también
                            st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
    else: 
        st.info("No hay registros disciplinarios registrados aún.")
