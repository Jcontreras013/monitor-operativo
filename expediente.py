import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime
import os
import tempfile
import textwrap
from fpdf import FPDF

# ==============================================================================
# CONFIGURACIÓN: API KEY PARA GUARDAR FOTOS EN LA NUBE GRATUITA
# ==============================================================================
API_KEY_FREEIMAGE = "6d207e02198a847aa98d0a2a901485a5"

# ==============================================================================
# 1. LÓGICA DE PDF INDEPENDIENTE (Soporte Multi-Imagen)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try:
                self.image('logo.png', 10, 6, 35)
            except: pass
            
        self.set_y(10)
        self.set_x(50)
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 8)
        self.set_x(50)
        self.cell(0, 5, "Reporte Oficial de Incidencias en Ruta", ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, 22, 200, 22)
        self.ln(10)
        
    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def sanitizar(texto):
    """Limpia tildes y caracteres raros para que el PDF no explote"""
    import unicodedata
    if pd.isna(texto): return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

def generar_pdf_memo(row):
    """Genera el PDF del memorándum soportando múltiples imágenes"""
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
    pdf.cell(35, 8, " Tecnico:", border=1, fill=True)
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
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    
    lineas = textwrap.wrap(str(row.get('COMENTARIO', '')), width=95)
    for linea in lineas:
        pdf.cell(0, 6, sanitizar(linea), ln=True)
        
    pdf.ln(8)
    
    # Procesar múltiples URLs separadas por coma
    urls_crudo = str(row.get('URL_FOTO', '')).split(',')
    urls_validas = [u.strip() for u in urls_crudo if u.strip().startswith('http')]
    
    if urls_validas:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 8, "Evidencia Fotografica / Capturas del Sistema:", ln=True)
        pdf.set_text_color(0, 0, 0)
        
        for index, url_foto in enumerate(urls_validas):
            try:
                req = requests.get(url_foto, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
                if req.status_code == 200:
                    fd, tmppath = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    with open(tmppath, 'wb') as f:
                        f.write(req.content)
                    
                    # Si ya estamos muy abajo en la hoja, saltamos a la siguiente antes de pegar la foto
                    if pdf.get_y() > 140:
                        pdf.add_page()
                        pdf.set_font("Helvetica", "I", 9)
                        pdf.cell(0, 6, f"(Continuacion de evidencias - Pag. {pdf.page_no()})", ln=True)
                    
                    pdf.image(tmppath, x=15, w=170)
                    pdf.ln(5) # Añadir un pequeño margen debajo de la imagen
                    os.remove(tmppath)
                else:
                    pdf.set_font("Helvetica", "I", 9)
                    pdf.cell(0, 6, f"(No se pudo descargar la evidencia {index+1}. Error {req.status_code})", ln=True)
            except:
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 6, f"(Error de red al leer la evidencia grafica {index+1}.)", ln=True)
            
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdf.output(pdf_path)
        with open(pdf_path, "rb") as f:
            return f.read()
    finally:
        try: os.remove(pdf_path)
        except: pass


# ==============================================================================
# 2. INTERFAZ GRÁFICA EN STREAMLIT
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes Disciplinarios")
    st.markdown("---")
    
    # --- FORMULARIO DE REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=True):
        with st.form("form_incidencia", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                lista_tecnicos = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                if "Todos" in lista_tecnicos:
                    lista_tecnicos.remove("Todos")
                    
                tecnico_sel = st.selectbox("👤 Seleccione al Técnico:", options=lista_tecnicos, help="Aparecerán los técnicos de la base actual.")
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", 
                                        ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                                         "Tiempos Muertos", "Mala Documentación", "Insubordinación", 
                                         "Pérdida de Herramientas", "Sin Datos Móviles", "Falla de Protocolo de Seguridad", "Otro"])
            
            with col2:
                fecha_incidencia = st.date_input("📅 Fecha del Suceso:", value=datetime.now())
                
                # MODIFICACIÓN: Aceptar múltiples archivos
                archivos_evidencia = st.file_uploader("🖼️ Capturas de Pantalla (Evidencias):", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, help="Puedes seleccionar varias imágenes a la vez.")

            comentario = st.text_area("📝 Comentario Detallado:", placeholder="Describa con precisión lo sucedido (horas, ubicaciones, etc.)...")
            btn_guardar = st.form_submit_button("💾 Guardar en Expediente Oficial", use_container_width=True)
            
            if btn_guardar:
                if tecnico_sel and comentario:
                    urls_imagenes_subidas = []
                    
                    if archivos_evidencia:
                        with st.spinner(f"☁️ Subiendo {len(archivos_evidencia)} evidencia(s) a la nube..."):
                            for archivo in archivos_evidencia:
                                try:
                                    img_bytes = archivo.getvalue()
                                    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                    payload = {"key": API_KEY_FREEIMAGE, "action": "upload", "source": img_base64, "format": "json"}
                                    res = requests.post("https://freeimage.host/api/1/upload", data=payload)
                                    if res.status_code == 200:
                                        urls_imagenes_subidas.append(res.json()["image"]["url"])
                                    else:
                                        st.warning(f"No se pudo subir una foto (Error {res.status_code}).")
                                except Exception as e:
                                    st.error(f"Error al subir imagen: {e}")

                    # Convertir la lista de URLs en un solo texto separado por comas
                    string_urls_final = ", ".join(urls_imagenes_subidas)
                    supervisor_actual = st.session_state.get('usuario', 'Sistema')
                    
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": tecnico_sel,
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_incidencia.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": string_urls_final, # Guardamos todas las URLs juntas
                        "SUPERVISOR": supervisor_actual 
                    }])
                    
                    with st.spinner("💾 Guardando en la base de datos central..."):
                        try:
                            df_exp_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            df_final = pd.concat([df_exp_db, nueva_fila], ignore_index=True)
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            st.success(f"✅ ¡Incidencia registrada exitosamente para {tecnico_sel} con {len(urls_imagenes_subidas)} foto(s)!")
                        except Exception as e:
                            st.error(f"❌ Error al conectar con Google Sheets. Detalle: {e}")
                else:
                    st.warning("⚠️ El nombre del técnico y el comentario son obligatorios.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- HISTORIAL Y VISOR ---
    st.subheader("📜 Historial Disciplinario Activo")
    try:
        with st.spinner("Cargando expedientes..."):
            df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            
        if not df_view.empty:
            df_view = df_view.dropna(subset=['TECNICO', 'TIPO_FALTA'], how='all')
            lista_tecs_hist = ["Ver Todos"] + sorted(df_view['TECNICO'].astype(str).unique().tolist())
            filtro = st.selectbox("🔍 Buscar Expediente de Técnico:", options=lista_tecs_hist)
            
            df_mostrar = df_view if filtro == "Ver Todos" else df_view[df_view['TECNICO'] == filtro]
            
            if df_mostrar.empty:
                 st.info(f"No hay incidencias registradas para {filtro}.")
            else:
                for idx, row in df_mostrar.iloc[::-1].iterrows():
                    with st.container():
                        st.markdown("""<div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 4px solid #EF4444; margin-bottom: 10px;">""", unsafe_allow_html=True)
                        c1, c2 = st.columns([3, 1])
                        
                        with c1:
                            st.markdown(f"### 👨‍🔧 {row['TECNICO']}")
                            st.markdown(f"**🚫 Falta Reportada:** {row['TIPO_FALTA']}")
                            st.caption(f"**📅 Sucedió el:** {row['FECHA_INCIDENCIA']} | **⏳ Registrado:** {row['FECHA_REGISTRO']} | **✍️ Por:** {row.get('SUPERVISOR', 'N/D')}")
                            st.info(f"**Detalle del Reporte:**\n\n{row['COMENTARIO']}")
                            
                        with c2:
                            # Procesamos las múltiples URLs para mostrarlas en la web
                            urls_crudo = str(row.get('URL_FOTO', '')).split(',')
                            urls_validas = [u.strip() for u in urls_crudo if u.strip().startswith('http')]
                            
                            if urls_validas:
                                for i, url in enumerate(urls_validas):
                                    st.image(url, use_container_width=True, caption=f"Evidencia {i+1}")
                                    st.markdown(f"[🔍 Ver Original {i+1}]({url})")
                            else:
                                st.markdown("<br><br>", unsafe_allow_html=True)
                                st.caption("📸 *No hay evidencia visual.*")
                                
                            try:
                                pdf_bytes = generar_pdf_memo(row)
                                nombre_archivo = f"Memo_{str(row.get('TECNICO', ''))[:10]}_{str(row.get('FECHA_INCIDENCIA', '')).replace('/', '')}.pdf".replace(" ", "_")
                                
                                st.download_button(
                                    label="📄 Descargar Memo",
                                    data=pdf_bytes,
                                    file_name=nombre_archivo,
                                    mime="application/pdf",
                                    key=f"btn_pdf_{idx}",
                                    use_container_width=True,
                                    type="primary"
                                )
                            except Exception as e:
                                st.error(f"❌ Error al crear PDF: {e}")
                                
                            if es_admin:
                                if st.button("🗑️ Eliminar", key=f"btn_del_{idx}", help="Acción exclusiva de Administrador"):
                                    with st.spinner("Eliminando..."):
                                        try:
                                            df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                                            mask_borrar = (df_db['FECHA_REGISTRO'] == row['FECHA_REGISTRO']) & (df_db['TECNICO'] == row['TECNICO'])
                                            df_actualizado = df_db[~mask_borrar]
                                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_actualizado)
                                            st.success("Eliminado correctamente.")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error al eliminar: {e}")
                                        
                        st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("La base de datos de expedientes está limpia.")
    except Exception as e:
        st.warning(f"⚠️ Error al cargar los expedientes: Asegúrese de tener la pestaña 'Expedientes' creada en Google Sheets.")
