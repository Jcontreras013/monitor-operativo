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
    if pd.isna(texto): 
        return "N/D"
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
        # TABLA DE RESUMEN
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "1. Resumen Estadistico:", ln=True)
        
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(140, 8, " Tipo de Falta", border=1, fill=True)
        pdf.cell(50, 8, " Total", border=1, ln=True, align="C", fill=True)
        
        for falta, total in df['TIPO_FALTA'].value_counts().items():
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(140, 7, f" {sanitizar(falta)}", border=1)
            pdf.cell(50, 7, str(total), border=1, ln=True, align="C")
            
        pdf.ln(10)
        
        # DETALLE DE INCIDENCIAS
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "2. Detalle de Incidencias:", ln=True)
        
        for tipo in sorted(df['TIPO_FALTA'].unique()):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_text_color(180, 0, 0)
            pdf.cell(0, 8, f" CATEGORIA: {sanitizar(tipo).upper()}", border="B", ln=True, fill=True)
            
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
            
            subset = df[df['TIPO_FALTA'] == tipo]
            for _, row in subset.iterrows():
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, sanitizar(f"[{row['FECHA_INCIDENCIA']}] - {row['TECNICO']}"), ln=True)
                
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(100, 100, 100)
                lineas = textwrap.wrap(f"Nota: {row['COMENTARIO']}", width=120)
                for l in lineas: 
                    pdf.cell(0, 4, f"   {sanitizar(l)}", ln=True)
                pdf.ln(2)
                
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    
    with open(path, "rb") as f: 
        data = f.read()
    os.remove(path)
    
    return data

# ==============================================================================
# 3. GENERADOR DE MEMO INDIVIDUAL
# ==============================================================================
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
    lineas = textwrap.wrap(str(row.get('COMENTARIO')), width=95)
    for l in lineas: 
        pdf.cell(0, 6, sanitizar(l), ln=True)
        
    urls = str(row.get('URL_FOTO', '')).split(',')
    urls_validas = [x.strip() for x in urls if x.strip().startswith('http')]
    
    for u in urls_validas:
        try:
            req = requests.get(u, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if req.status_code == 200:
                fd, tmppath = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                with open(tmppath, 'wb') as f: 
                    f.write(req.content)
                    
                if pdf.get_y() > 140: 
                    pdf.add_page()
                    
                pdf.image(tmppath, x=15, w=170)
                pdf.ln(5)
                os.remove(tmppath)
        except: 
            pass
            
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    
    with open(path, "rb") as f: 
        data = f.read()
    os.remove(path)
    
    return data

# ==============================================================================
# 4. INTERFAZ DE EXPEDIENTES EN STREAMLIT
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', 'Supervisor')

    st.title("📁 Gestión de Expedientes Disciplinarios")
    
    # --- FORMULARIO DE REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=True):
        st.info(f"✍️ Reporte firmado oficialmente por: **{supervisor_actual}**")
        
        with st.form("form_incidencia_unificado", clear_on_submit=True):
            c1, c2 = st.columns(2)
            
            with c1:
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                tecnico_sel = st.selectbox("👤 Seleccionar Técnico de la lista:", options=["---"] + lista_tecs)
                
                nombre_ayudante = st.text_input("👷 Escriba nombre del AYUDANTE (Prioridad):", help="Si escribe aquí, se ignorará el selector de arriba.")
                
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Otro"
                ])
                
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Detalle de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True):
                
                # UNIFICACIÓN DE NOMBRE Y PRIORIDAD DEL AYUDANTE
                final_name = ""
                if nombre_ayudante.strip() != "":
                    final_name = f"{nombre_ayudante.strip().upper()} (AYUDANTE)"
                elif tecnico_sel != "---":
                    final_name = tecnico_sel.strip().upper()
                
                # VALIDACIÓN
                if final_name == "":
                    st.error("❌ Error: Debe escribir un nombre de ayudante o seleccionar un técnico.")
                elif not comentario:
                    st.error("❌ Error: El comentario detallado es obligatorio.")
                else:
                    urls_imagenes = []
                    if archivos:
                        with st.spinner("Subiendo evidencias visuales..."):
                            for archivo in archivos:
                                try:
                                    img_bytes = archivo.getvalue()
                                    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                    payload = {"key": API_KEY_FREEIMAGE, "action": "upload", "source": img_base64, "format": "json"}
                                    res = requests.post("https://freeimage.host/api/1/upload", data=payload)
                                    
                                    if res.status_code == 200: 
                                        urls_imagenes.append(res.json()["image"]["url"])
                                    time.sleep(1) # Pausa para no saturar la API
                                except Exception as e: 
                                    st.warning(f"No se pudo subir una imagen: {e}")
                    
                    # CREAR NUEVA FILA
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": final_name, 
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": ", ".join(urls_imagenes),
                        "SUPERVISOR": supervisor_actual
                    }])
                    
                    try:
                        with st.spinner("Guardando en la base de datos..."):
                            df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            
                            df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                            
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            
                            # LIMPIEZA DE CACHÉ PARA ACTUALIZACIÓN INMEDIATA
                            st.cache_data.clear() 
                            
                            st.success(f"✅ ¡REGISTRADO EXITOSAMENTE PARA: {final_name}!")
                            time.sleep(1.5)
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error de conexión con Google Sheets: {e}")

    st.markdown("---")
    st.subheader("📜 Historial Unificado de Incidencias")
    
    try:
        # LECTURA DEL HISTORIAL
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0).dropna(subset=['TECNICO'], how='all')
        
        if not df_view.empty:
            # UNIFICACIÓN DE NOMBRES PARA EL FILTRO DE BÚSQUEDA
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.strip().str.upper()
            
            # BOTÓN GERENCIAL
            col_vacia, col_boton = st.columns([3, 1]) 
            with col_boton:
                pdf_gerencial = generar_pdf_consolidado(df_view)
                st.download_button(
                    label="📊 Reporte Gerencial", 
                    data=pdf_gerencial, 
                    file_name=f"Consolidado_Faltas_{get_honduras_time().strftime('%d%m%Y')}.pdf", 
                    mime="application/pdf", 
                    use_container_width=True, 
                    type="primary"
                )

            # FILTRO
            opciones_filtro = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar por Nombre (Unificado):", options=opciones_filtro)
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            # RENDERIZADO DE LAS TARJETAS DE INCIDENCIA
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 5px solid #EF4444; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <h3 style="margin:0; color:white;">👨‍🔧 {row['TECNICO']}</h3>
                        <p style="margin:5px 0; color:#94A3B8;"><b>Falta:</b> {row['TIPO_FALTA']} | <b>Fecha Suceso:</b> {row['FECHA_INCIDENCIA']}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; margin:10px 0; color:white;">{row['COMENTARIO']}</div>
                        <p style="font-size:0.8rem; color:#64748B;">Registrado por {row.get('SUPERVISOR','N/D')} el {row['FECHA_REGISTRO']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col_pdf, col_del = st.columns([1, 1])
                    
                    with col_pdf:
                        pdf_individual = generar_pdf_memo(row)
                        st.download_button(
                            label="📄 Descargar Memo Individual", 
                            data=pdf_individual, 
                            file_name=f"Memo_{row['TECNICO']}.pdf", 
                            key=f"pdf_{idx}", 
                            use_container_width=True
                        )
                        
                    with col_del:
                        if es_admin:
                            if st.button("🗑️ Eliminar Registro", key=f"del_{idx}", use_container_width=True):
                                df_nuevo = df_view.drop(idx)
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_nuevo)
                                st.cache_data.clear()
                                st.rerun()
        else:
            st.info("No hay incidencias registradas en la base de datos.")
    except Exception as e:
        st.warning(f"⚠️ Error al cargar historial: {e}")
