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
# CONFIGURACIÓN
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

# ==============================================================================
# LECTOR DEL ARCHIVO DE PERSONAL (NUEVO)
# ==============================================================================
def cargar_nombres_personal():
    """Lee el archivo personal_tecnico.txt y extrae SOLO los nombres limpios"""
    nombres = []
    try:
        with open("personal_tecnico.txt", "r", encoding="utf-8") as file:
            for linea in file:
                if linea.strip():
                    # Separar por la coma y tomar solo la primera parte (el nombre)
                    nombre_crudo = linea.split(",")[0]
                    # Cambiar tabulaciones por espacios y limpiar extremos
                    nombre_limpio = nombre_crudo.replace("\t", " ").strip().upper()
                    # Quitar espacios dobles por si acaso
                    nombre_limpio = " ".join(nombre_limpio.split())
                    nombres.append(nombre_limpio)
    except Exception as e:
        st.error(f"⚠️ No se pudo leer el archivo 'personal_tecnico.txt'. Verifica que esté en la misma carpeta. Error: {e}")
    
    # Devolver la lista ordenada alfabéticamente y sin duplicados
    return sorted(list(set(nombres)))

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
    if pd.isna(texto) or texto is None: return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# 2. GENERADORES DE PDF (Con Caché para que sea rápido)
# ==============================================================================
@st.cache_data(show_spinner=False)
def generar_pdf_consolidado_general(df_dict_list):
    df = pd.DataFrame(df_dict_list)
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO GENERAL", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10); pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C"); pdf.ln(10)
    
    if df.empty:
        pdf.set_font("Helvetica", "I", 12); pdf.cell(0, 10, "No hay registros en el sistema.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen Estadistico:", ln=True)
        pdf.set_fill_color(230, 230, 230); pdf.set_font("Helvetica", "B", 10)
        pdf.cell(140, 8, " Tipo de Falta", border=1, fill=True); pdf.cell(50, 8, " Total", border=1, ln=True, align="C", fill=True)
        for f, t in df['TIPO_FALTA'].value_counts().items():
            pdf.set_font("Helvetica", "", 10); pdf.cell(140, 7, f" {sanitizar(f)}", border=1); pdf.cell(50, 7, str(t), border=1, ln=True, align="C")
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

@st.cache_data(show_spinner=False)
def generar_pdf_consolidado_tecnico(df_dict_list, nombre_tecnico):
    df = pd.DataFrame(df_dict_list)
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, f"HISTORIAL CONSOLIDADO: {sanitizar(nombre_tecnico)}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align="C"); pdf.ln(5)
    
    pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen de Faltas:", ln=True)
    for f, t in df['TIPO_FALTA'].value_counts().items():
        pdf.set_font("Helvetica", "", 10); pdf.cell(0, 6, f"- {sanitizar(f)}: {t} reportes", ln=True)
        
    pdf.ln(5); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Desglose Detallado:", ln=True)
    for _, row in df.iterrows():
        pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 6, f"[{row.get('FECHA_INCIDENCIA')}] {row.get('TIPO_FALTA')}", ln=True)
        pdf.set_font("Helvetica", "", 9); pdf.set_text_color(0, 0, 0)
        for l in textwrap.wrap(str(row.get('COMENTARIO', '')), width=95): 
            pdf.cell(0, 5, sanitizar(l), ln=True)
        pdf.ln(3)
        
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

@st.cache_data(show_spinner=False)
def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0); pdf.cell(0, 10, "MEMORANDUM: LLAMADO DE ATENCION", ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 8, " Implicado:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row_dict.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(35, 8, " Tipo Falta:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row_dict.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
    urls = str(row_dict.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=8); 
            if r.status_code == 200:
                fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
                with open(tp, 'wb') as f: f.write(r.content)
                if pdf.get_y() > 140: pdf.add_page()
                pdf.image(tp, x=15, w=170); pdf.ln(5); os.remove(tp)
        except: pass

    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES
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
                # AQUÍ USAMOS LA FUNCIÓN PARA CARGAR LA LISTA DESDE EL .TXT
                lista_personal = cargar_nombres_personal()
                
                # UN SOLO SELECTOR PARA TODO EL PERSONAL (Técnicos, Supervisores, Ayudantes, etc.)
                tecnico_sel = st.selectbox("👤 Seleccionar Colaborador:", options=["---"] + lista_personal)
                
                # Eliminé el campo de texto de 'Ayudante' para simplificar todo a este menú desplegable.
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Otro"])
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Detalle detallado de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                if tecnico_sel == "---":
                    st.error("❌ Error: Debe seleccionar un colaborador de la lista.")
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
                    
                    # CÓDIGO EXACTO DE GUARDADO A GOOGLE SHEETS
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": tecnico_sel, # Ya viene limpio y en mayúsculas del txt
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": ", ".join(urls),
                        "SUPERVISOR": supervisor_actual
                    }])
                    
                    try:
                        with st.spinner("Guardando en la Base de Datos..."):
                            df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            
                            cols = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
                            if df_db.empty or len(df_db.columns) == 0:
                                df_db = pd.DataFrame(columns=cols)
                            else:
                                for c in cols:
                                    if c not in df_db.columns: df_db[c] = ""
                            
                            df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                            df_final = df_final[cols]
                            
                            df_final = df_final.fillna("").astype(str).replace(["nan", "NaN", "None", "null"], "")
                            
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            
                            st.cache_data.clear() # LIMPIEZA TOTAL DE MEMORIA
                            st.success(f"✅ ¡REGISTRADO EXITOSAMENTE!: {tecnico_sel}")
                            time.sleep(1.5)
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error de conexión con Google Sheets: {e}")

    st.markdown("---")
    st.subheader("📜 Historial Unificado y Reportes")
    
    try:
        # CÓDIGO DE HISTORIAL QUE MANDASTE (Funcional y Unificado)
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        
        if not df_view.empty and 'TECNICO' in df_view.columns:
            df_view = df_view.dropna(subset=['TECNICO'])
            df_view = df_view[df_view['TECNICO'].astype(str).str.strip() != '']
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.strip().str.upper()
            
            if df_view.empty:
                st.info("No hay incidencias registradas.")
                return

            opciones_filtro = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar por Nombre (Unificado automáticamente):", options=opciones_filtro)
            
            c_v, c_b = st.columns([3, 1])
            with c_b:
                if filtro == "VER TODOS":
                    pdf_gen = generar_pdf_consolidado_general(df_view.to_dict(orient="records"))
                    st.download_button("📊 Reporte General Empresa", data=pdf_gen, file_name="Reporte_General_Faltas.pdf", mime="application/pdf", use_container_width=True, type="primary")
                else:
                    df_tec = df_view[df_view['TECNICO'] == filtro]
                    pdf_tec = generar_pdf_consolidado_tecnico(df_tec.to_dict(orient="records"), filtro)
                    st.download_button(f"📊 Reporte de {filtro}", data=pdf_tec, file_name=f"Historial_{filtro.replace(' ','_')}.pdf", mime="application/pdf", use_container_width=True, type="primary")
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 5px solid #EF4444; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <h3 style="margin:0; color:white;">👨‍🔧 {row['TECNICO']}</h3>
                        <p style="margin:5px 0; color:#94A3B8;"><b>Falta:</b> {row.get('TIPO_FALTA', 'N/D')} | <b>Fecha:</b> {row.get('FECHA_INCIDENCIA', 'N/D')}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; margin:10px 0; color:white;">{row.get('COMENTARIO', '')}</div>
                        <p style="font-size:0.8rem; color:#64748B;">Registrado por {row.get('SUPERVISOR','N/D')} el {row.get('FECHA_REGISTRO', 'N/D')}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c_pdf, c_del = st.columns([1, 1])
                    with c_pdf:
                        st.download_button("📄 PDF Memo Individual", data=generar_pdf_memo(row.to_dict()), file_name=f"Memo_{idx}.pdf", key=f"pdf_{idx}", use_container_width=True)
                    with c_del:
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                                df_new = df_view.drop(idx)
                                df_new = df_new.fillna("").astype(str).replace(["nan", "NaN", "None", "null"], "")
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                                st.cache_data.clear()
                                st.rerun()
        else:
            st.info("No hay incidencias registradas.")
    except Exception as e:
        st.warning(f"⚠️ Error al cargar historial: {e}")
