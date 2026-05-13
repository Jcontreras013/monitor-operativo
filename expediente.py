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
import numpy as np

# ==============================================================================
# CONFIGURACIÓN Y CARGA DE PERSONAL
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def cargar_personal(filepath="personal_tecnico.txt"):
    """Carga los nombres desde el TXT ignorando roles y asegurando mayúsculas."""
    try:
        if not os.path.exists(filepath): return []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
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
# 2. GENERADOR DE PDF
# ==============================================================================
def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    es_medica = str(row_dict.get('TIPO_FALTA', '')).upper() == "INCIDENCIA MÉDICA"
    if es_medica:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0, 102, 204)
        titulo = "CONSTANCIA DE INCIDENCIA MÉDICA"
    else:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
        titulo = "MEMORANDUM: LLAMADO DE ATENCION"
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(40, 8, " Colaborador:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Clasificación:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Supervisor:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('SUPERVISOR'))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle del Registro:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES (SOLUCIÓN GUARDADO INFINITO)
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    # Nombre del supervisor automático
    supervisor_actual = st.session_state.get('usuario', 'SUPERVISOR CONTROL')
    es_admin = (str(st.session_state.get('rol_actual', 'monitoreo')).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    with st.expander("➕ Crear Nuevo Registro (Desde A8 en adelante)", expanded=True):
        with st.form("form_registro_continuo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_nombres = cargar_personal("personal_tecnico.txt")
                colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres)
                tipo_falta = st.selectbox("🚫 Motivo/Tipo:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Tiempos Muertos", "Mala Documentación", "Insubordinación", 
                    "Incidencia Médica", "Otro"
                ])
                st.info(f"✍️ Firma el registro: **{supervisor_actual}**")
            with c2:
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción detallada:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ Complete el nombre y el comentario.")
                else:
                    try:
                        urls = []
                        if archivos:
                            for a in archivos:
                                res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                if res.status_code == 200: urls.append(res.json()["image"]["url"])
                        
                        nueva_fila = pd.DataFrame([{
                            "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO": colaborador_sel,
                            "TIPO_FALTA": tipo_falta,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        # LÓGICA DE GUARDADO INFINITO (A8, A9, A10...)
                        df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        
                        # Limpiamos filas que Google Sheets manda como "vacías" pero Python detecta
                        if not df_db.empty:
                            # Reemplazamos celdas que son solo espacios por valores nulos reales
                            df_db = df_db.replace(r'^\s*$', np.nan, regex=True)
                            # Mantenemos solo las filas donde hay un técnico escrito
                            df_db = df_db.dropna(subset=['TECNICO'])
                        
                        cols = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
                        for c in cols:
                            if c not in df_db.columns: df_db[c] = ""
                        
                        # Al concatenar ahora, Python lo pone justo después del último dato real
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        df_final = df_final.fillna("").astype(str).replace(["nan", "NaN", "None", "null"], "")
                        
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        st.cache_data.clear()
                        st.success(f"✅ ¡Guardado con éxito! Se registró a {colaborador_sel} en la siguiente fila disponible.")
                        time.sleep(1.5); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        # Limpieza visual del historial
        if not df_view.empty:
            df_view = df_view.replace(r'^\s*$', np.nan, regex=True).dropna(subset=['TECNICO'])
            df_view['TECNICO'] = df_view['TECNICO'].str.upper().str.strip()
            filtro = st.selectbox("🔍 Buscar Colaborador:", options=["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist()))
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                es_m = str(row.get('TIPO_FALTA')).upper() == "INCIDENCIA MÉDICA"
                color_borde = "#3B82F6" if es_m else "#EF4444"
                with st.container():
                    st.markdown(f"""<div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {color_borde}; margin-bottom: 10px; border: 1px solid #2D2F39;"><h3 style="margin:0; color:white;">{row['TECNICO']} <span style="font-size:12px; background:{color_borde}; padding:2px 8px; border-radius:10px;">{row['TIPO_FALTA']}</span></h3><p style="color:#94A3B8;"><b>Registrado por:</b> {row.get('SUPERVISOR', 'N/D')} | <b>Fecha:</b> {row['FECHA_INCIDENCIA']}</p><div style="background:#0F1115; padding:10px; border-radius:5px; color:white;">{row['COMENTARIO']}</div></div>""", unsafe_allow_html=True)
                    st.download_button(f"📄 Descargar {'Constancia' if es_m else 'Memorandum'}", data=generar_pdf_memo(row.to_dict()), file_name=f"Reporte_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
        else: st.info("No hay registros aún.")
    except: st.warning("⚠️ Cargando historial...")
