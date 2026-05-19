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
# CONFIGURACIÓN Y UTILIDADES
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

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
# CLASE PDF
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
        self.cell(0, 5, "Reporte Oficial de Gestion de Personal", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
        
    def footer(self):
        self.set_y(-15); self.set_text_color(150, 150, 150); self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

# ==============================================================================
# GENERADORES DE PDF
# ==============================================================================
def generar_pdf_consolidado(df):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y a las %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)
    
    if df.empty:
        pdf.set_font("Helvetica", "I", 12); pdf.cell(0, 10, "No hay registros disponibles.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen por Tipo de Falta:", ln=True)
        pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(240, 240, 240)
        pdf.cell(140, 8, " Motivo / Falta", border=1, fill=True)
        pdf.cell(50, 8, " Cantidad Total", border=1, ln=True, align="C", fill=True)
        pdf.set_font("Helvetica", "", 10)
        for cat, total in df['TIPO_FALTA'].value_counts().items():
            pdf.cell(140, 7, f" {sanitizar(cat)}", border=1)
            pdf.cell(50, 7, str(total), border=1, ln=True, align="C")
        pdf.ln(10)
        
        pdf.set_font("Helvetica", "B", 8); pdf.set_fill_color(240, 240, 240)
        pdf.cell(30, 8, " Fecha Reg.", border=1, fill=True, align="C")
        pdf.cell(50, 8, " Colaborador", border=1, fill=True)
        pdf.cell(35, 8, " Motivo", border=1, fill=True)
        pdf.cell(75, 8, " Observaciones", border=1, ln=True, fill=True)
        
        pdf.set_font("Helvetica", "", 7)
        for _, row in df.iterrows():
            f_reg = sanitizar(str(row.get('FECHA_REGISTRO',''))[:16]) 
            tec = sanitizar(str(row.get('TECNICO',''))[:35])
            mot = sanitizar(str(row.get('TIPO_FALTA',''))[:30])
            com = sanitizar(str(row.get('COMENTARIO','')))
            lineas_com = textwrap.wrap(com, width=55) 
            if not lineas_com: lineas_com = [""]
            for i, linea in enumerate(lineas_com):
                b_style = 'LR' + ('T' if i == 0 else '') + ('B' if i == len(lineas_com)-1 else '')
                col1 = f" {f_reg}" if i == 0 else ""
                col2 = f" {tec}" if i == 0 else ""
                col3 = f" {mot}" if i == 0 else ""
                pdf.cell(30, 5, col1, border=b_style, align="C")
                pdf.cell(50, 5, col2, border=b_style)
                pdf.cell(35, 5, col3, border=b_style)
                pdf.cell(75, 5, f" {linea}", border=b_style, ln=True)
            
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    es_medica = str(row_dict.get('TIPO_FALTA', '')).upper() in ["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"]
    titulo = "CONSTANCIA DE INCIDENCIA MEDICA" if es_medica else "MEMORANDUM: LLAMADO DE ATENCION"
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0, 102, 204) if es_medica else pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    
    for label, key in [("Colaborador:", "TECNICO"), ("Motivo:", "TIPO_FALTA"), ("Fecha:", "FECHA_INCIDENCIA"), ("Registro:", "FECHA_REGISTRO"), ("Supervisor:", "SUPERVISOR")]:
        pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, f" {label}", border=1, fill=True)
        pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get(key))}", border=1, ln=True)
    
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
    urls = str(row_dict.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=10)
            if r.status_code == 200:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(r.content); tmp_path = tmp.name
                if pdf.get_y() > 180: pdf.add_page()
                pdf.ln(5); pdf.image(tmp_path, x=20, w=160); os.remove(tmp_path)
        except: pass

    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# LÓGICA DE DATOS
# ==============================================================================
def leer_expedientes_limpio(conn):
    st.cache_data.clear()
    df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    columnas_oficiales = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
    if df.empty: return pd.DataFrame(columns=columnas_oficiales)
    df.columns = df.columns.astype(str).str.strip().str.upper()
    for col in columnas_oficiales:
        if col not in df.columns: df[col] = ""
    df = df[df['TECNICO'].astype(str).str.strip() != ""]
    return df[columnas_oficiales]

# ==============================================================================
# FUNCIÓN PRINCIPAL (LA QUE LLAMA TU APP.PY)
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    # Obtener info de sesión
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    # --- FORMULARIO ---
    with st.expander("➕ Crear Nuevo Registro", expanded=True):
        with st.form("form_incidencia_new", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_nombres = cargar_personal()
                colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres)
                tipo_falta = st.selectbox("🚫 Motivo:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Mala Documentación", "Incidencia Médica", "Otro"])
            with c2:
                fecha_inc = st.date_input("📅 Fecha:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción:")
            
            if st.form_submit_button("💾 GUARDAR"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ Falta información.")
                else:
                    try:
                        urls = []
                        if archivos:
                            for a in archivos:
                                res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                if res.status_code == 200: urls.append(res.json()["image"]["url"])
                        
                        nueva_fila = [get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"), colaborador_sel, tipo_falta, fecha_inc.strftime("%d/%m/%Y"), comentario, ", ".join(urls), supervisor_actual]
                        
                        # Guardado directo
                        doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                        hoja = doc.worksheet("Expedientes")
                        hoja.append_row(nueva_fila)
                        
                        st.cache_data.clear()
                        st.success("✅ Guardado.")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # --- HISTORIAL ---
    st.markdown("---")
    try:
        df_view = leer_expedientes_limpio(conn)
        if not df_view.empty:
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.upper()
            
            c1, c2, c3 = st.columns(3)
            with c1: filtro_nombre = st.selectbox("🔍 Colaborador:", ["TODOS"] + sorted(df_view['TECNICO'].unique().tolist()))
            with c2: rango = st.date_input("📅 Rango:", value=(get_honduras_time().date()-timedelta(days=60), get_honduras_time().date()))
            with c3: filtro_tipo = st.selectbox("📋 Filtro:", ["Todos", "Llamado Atención", "Incidencia Médica"])

            df_mostrar = df_view.copy()
            if filtro_nombre != "TODOS": df_mostrar = df_mostrar[df_mostrar['TECNICO'] == filtro_nombre]
            
            if filtro_tipo == "Incidencia Médica":
                df_mostrar = df_mostrar[df_mostrar['TIPO_FALTA'].str.upper().str.contains("MEDICA|MÉDICA")]
            elif filtro_tipo == "Llamado Atención":
                df_mostrar = df_mostrar[~df_mostrar['TIPO_FALTA'].str.upper().str.contains("MEDICA|MÉDICA")]

            if not df_mostrar.empty:
                st.download_button("📊 Reporte PDF", data=generar_pdf_consolidado(df_mostrar), file_name="Reporte.pdf")

            for idx, row in df_mostrar.iloc[::-1].iterrows():
                color = "#3B82F6" if "MEDICA" in str(row['TIPO_FALTA']).upper() or "MÉDICA" in str(row['TIPO_FALTA']).upper() else "#EF4444"
                with st.container():
                    st.markdown(f'<div style="border-left:5px solid {color}; background:#1A1D24; padding:15px; border-radius:5px; margin-bottom:10px;">'
                                f'<h4 style="margin:0;">{row["TECNICO"]}</h4>'
                                f'<p style="color:#94A3B8; margin:0;">{row["TIPO_FALTA"]} | {row["FECHA_INCIDENCIA"]}</p>'
                                f'<p>{row["COMENTARIO"]}</p></div>', unsafe_allow_html=True)
                    
                    cb1, cb2 = st.columns([1, 4])
                    with cb1: st.download_button("📄 PDF", data=generar_pdf_memo(row.to_dict()), file_name=f"Doc_{idx}.pdf", key=f"d_{idx}")
                    with cb2:
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}"):
                                doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                                hoja = doc.worksheet("Expedientes")
                                hoja.delete_rows(idx + 2)
                                st.cache_data.clear()
                                st.rerun()
        else: st.info("Sin registros.")
    except Exception as e: st.error(f"Error carga: {e}")
