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
    """Crea un PDF resumen agrupando por tipo de falta"""
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE INCIDENCIAS", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)
    
    # --- TABLA DE RESUMEN (CONTEO) ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "1. Resumen Estadistico:", ln=True)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(140, 8, " Tipo de Falta", border=1, fill=True)
    pdf.cell(50, 8, " Total Reportes", border=1, ln=True, align="C", fill=True)
    
    pdf.set_font("Helvetica", "", 10)
    conteo_faltas = df['TIPO_FALTA'].value_counts()
    for falta, total in conteo_faltas.items():
        pdf.cell(140, 7, f" {sanitizar(falta)}", border=1)
        pdf.cell(50, 7, str(total), border=1, ln=True, align="C")
    
    pdf.ln(10)
    
    # --- DESGLOSE DETALLADO GRUPAL ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "2. Detalle de Incidencias por Categoria:", ln=True)
    
    tipos_ordenados = sorted(df['TIPO_FALTA'].unique())
    
    for tipo in tipos_ordenados:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(245, 245, 245)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 8, f" CATEGORIA: {sanitizar(tipo).upper()}", border="B", ln=True, fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
        
        subset = df[df['TIPO_FALTA'] == tipo].sort_values(by='FECHA_INCIDENCIA', ascending=False)
        
        for _, row in subset.iterrows():
            pdf.set_font("Helvetica", "B", 9)
            header_txt = f"[{row['FECHA_INCIDENCIA']}] - {row['TECNICO']}"
            pdf.cell(0, 5, sanitizar(header_txt), ln=True)
            
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(100, 100, 100)
            comentario = f"Nota: {row['COMENTARIO']}"
            lineas = textwrap.wrap(comentario, width=120)
            for l in lineas:
                pdf.cell(0, 4, f"   {sanitizar(l)}", ln=True)
            pdf.ln(2)
        pdf.ln(5)

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(pdf_path)
    with open(pdf_path, "rb") as f:
        data = f.read()
    os.remove(pdf_path)
    return data

# ==============================================================================
# 3. GENERADOR DE MEMO INDIVIDUAL
# ==============================================================================
def generar_pdf_memo(row):
    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, "MEMORANDUM: LLAMADO DE ATENCION", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 8, " Implicado:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('TECNICO', ''))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, " Tipo de Falta:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('TIPO_FALTA', ''))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, " Fecha Suceso:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('FECHA_INCIDENCIA', ''))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, " Registrado Por:", border=1, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(155, 8, f" {sanitizar(row.get('SUPERVISOR', 'Sistema'))} el {sanitizar(row.get('FECHA_REGISTRO', ''))}", border=1, ln=True)
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    lineas = textwrap.wrap(str(row.get('COMENTARIO', '')), width=95)
    for linea in lineas: pdf.cell(0, 6, sanitizar(linea), ln=True)
    pdf.ln(8)
    urls_crudo = str(row.get('URL_FOTO', '')).split(',')
    urls_validas = [u.strip() for u in urls_crudo if u.strip().startswith('http')]
    if urls_validas:
        pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 8, "Evidencia Fotografica / Capturas del Sistema:", ln=True)
        pdf.set_text_color(0, 0, 0)
        for url_foto in urls_validas:
            try:
                req = requests.get(url_foto, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                if req.status_code == 200:
                    fd, tmppath = tempfile.mkstemp(suffix=".png"); os.close(fd)
                    with open(tmppath, 'wb') as f: f.write(req.content)
                    if pdf.get_y() > 140: pdf.add_page()
                    pdf.image(tmppath, x=15, w=170); pdf.ln(5); os.remove(tmppath)
            except: pass
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
    pdf.output(pdf_path)
    with open(pdf_path, "rb") as f: data = f.read()
    os.remove(pdf_path)
    return data

# ==============================================================================
# 4. INTERFAZ STREAMLIT
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', st.session_state.get('username', st.session_state.get('usuario_actual', 'Supervisor')))

    st.title("📁 Gestión de Expedientes Disciplinarios")
    
    # --- FORMULARIO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=False):
        st.info(f"✍️ Reporte firmado por: **{supervisor_actual}**")
        with st.form("form_incidencia", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                lista_tecs.insert(0, "Seleccionar...")
                tecnico_sel = st.selectbox("👤 Técnico:", options=lista_tecs)
                ayudante_manual = st.text_input("👷 O nombre del Ayudante:")
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Pérdida de Herramientas", "Sin Datos Móviles", "Otro"])
            with c2:
                fecha_inc = st.date_input("📅 Fecha:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            comentario = st.text_area("📝 Detalle:")
            
            if st.form_submit_button("💾 Guardar Registro", use_container_width=True):
                
                # --- LA MAGIA ESTÁ AQUÍ ---
                # Si escribieron un nombre en la casilla del ayudante, forzamos la etiqueta (AYUDANTE)
                if ayudante_manual.strip() != "":
                    nombre_final = f"{ayudante_manual.strip().upper()} (AYUDANTE)"
                else:
                    nombre_final = tecnico_sel.upper()
                # --------------------------

                if nombre_final in ["SELECCIONAR...", ""]: 
                    st.warning("⚠️ Seleccione un técnico o escriba el nombre del ayudante.")
                elif not comentario: 
                    st.warning("⚠️ El detalle de los hechos es obligatorio.")
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
                        "TECNICO": nombre_final, # Aquí se guarda el nombre ya procesado con la etiqueta
                        "TIPO_FALTA": tipo_falta, 
                        "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"), 
                        "COMENTARIO": comentario, 
                        "URL_FOTO": ", ".join(urls), 
                        "SUPERVISOR": supervisor_actual
                    }])
                    
                    try:
                        with st.spinner("Guardando en la base central..."):
                            df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                            
                            # Forzar el orden correcto
                            cols_ideales = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
                            for col in cols_ideales:
                                if col not in df_final.columns: df_final[col] = "" 
                            df_final = df_final[cols_ideales]
                            
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            st.success(f"✅ ¡Guardado con éxito el reporte para {nombre_final}!")
                            time.sleep(1.5)
                            st.rerun()
                    except Exception as e: 
                        st.error(f"Error: {e}")

    st.markdown("---")
    
    # --- HISTORIAL Y REPORTE GERENCIAL ---
    st.subheader("📜 Historial y Reportes para Gerencia")
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0).dropna(subset=['TECNICO'], how='all')
        
        if not df_view.empty:
            col_vacia, col_boton = st.columns([3, 1]) 
            with col_boton:
                pdf_cons = generar_pdf_consolidado(df_view)
                st.download_button("📊 Reporte Gerencial", data=pdf_cons, file_name=f"Consolidado_Faltas_{get_honduras_time().strftime('%d%m%Y')}.pdf", mime="application/pdf", use_container_width=True, type="primary")
            
            filtro = st.selectbox("🔍 Filtrar Historial:", options=["Ver Todos"] + sorted(df_view['TECNICO'].unique().tolist()))
            df_mostrar = df_view if filtro == "Ver Todos" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                with st.container():
                    st.markdown("""<div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 4px solid #EF4444; margin-bottom: 10px;">""", unsafe_allow_html=True)
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        # Si es ayudante, el nombre destacará automáticamente aquí
                        st.markdown(f"### 👨‍🔧 {row['TECNICO']}")
                        st.markdown(f"**🚫 Falta:** {row['TIPO_FALTA']} | **📅 Fecha:** {row['FECHA_INCIDENCIA']}")
                        st.caption(f"**✍️ Por:** {row.get('SUPERVISOR', 'N/D')} | **⏳ Reg:** {row['FECHA_REGISTRO']}")
                        st.info(row['COMENTARIO'])
                    with c2:
                        urls = str(row.get('URL_FOTO', '')).split(',')
                        for i, u in enumerate([u.strip() for u in urls if u.strip().startswith('http')]):
                            st.image(u, use_container_width=True, caption=f"Evidencia {i+1}")
                        st.download_button("📄 PDF Individual", data=generar_pdf_memo(row), file_name=f"Memo_{str(row['TECNICO']).replace(' ', '_')}.pdf", key=f"memo_{idx}", use_container_width=True)
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                                df_upd = df_view[~((df_view['FECHA_REGISTRO'] == row['FECHA_REGISTRO']) & (df_view['TECNICO'] == row['TECNICO']))]
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_upd)
                                st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
        else: st.info("No hay registros disciplinarios creados.")
    except Exception as e: 
        st.warning("Cree la pestaña 'Expedientes' en Google Sheets para poder almacenar la información.")
