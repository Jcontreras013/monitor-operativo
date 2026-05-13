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
# CONFIGURACIÓN Y CARGA DE PERSONAL (TXT)
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def cargar_personal(filepath="personal_tecnico.txt"):
    """Carga los nombres desde el TXT sin bloqueos de caché."""
    try:
        if not os.path.exists(filepath): return []
        try:
            with open(filepath, 'r', encoding='utf-8') as f: lineas = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f: lineas = f.readlines()
        nombres = []
        for linea in lineas:
            linea = linea.strip()
            if linea:
                # Cortamos en la coma y limpiamos espacios
                nombre_limpio = " ".join(linea.split(',')[0].replace('\t', ' ').split()).upper()
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
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen General:", ln=True)
        col_cat = 'CATEGORIA' if 'CATEGORIA' in df.columns else 'TIPO_FALTA'
        for cat, total in df[col_cat].value_counts().items():
            pdf.set_font("Helvetica", "", 11); pdf.cell(0, 7, f"- {cat}: {total}", ln=True)
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Desglose Detallado:", ln=True)
        for _, row in df.iterrows():
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, sanitizar(f"[{row.get('FECHA_INCIDENCIA','')}] {row.get('TECNICO','')} - {row.get('TIPO_FALTA','')}"), ln=True)
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(0, 4, f"   Detalle: {sanitizar(str(row.get('COMENTARIO',''))[:100])}...", ln=True); pdf.ln(2)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    
    # Lógica especial para PDF Médico
    es_medica = str(row_dict.get('TIPO_FALTA', '')).upper() == "INCIDENCIA MÉDICA"
    if es_medica:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0, 102, 204)
        titulo = "CONSTANCIA DE INCIDENCIA MEDICA"
    else:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
        titulo = "MEMORANDUM: LLAMADO DE ATENCION"
        
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(40, 8, " Colaborador:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Tipo de Evento:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Supervisor:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('SUPERVISOR'))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle del Registro:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
    urls = str(row_dict.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=8)
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
# 3. INTERFAZ Y MOTOR DE MEMORIA INFINITA
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    supervisor_actual = st.session_state.get('usuario', 'SUPERVISOR CONTROL')
    es_admin = (str(st.session_state.get('rol_actual', 'monitoreo')).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")

    # --- INICIALIZAR MEMORIA RAM DEL SISTEMA ---
    # Esto salva a la app del retraso de lectura de Google Sheets
    if "memoria_expedientes" not in st.session_state:
        try:
            st.cache_data.clear()
            df_init = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            if not df_init.empty:
                df_init = df_init.fillna("").astype(str)
                if 'TECNICO' in df_init.columns:
                    # Borramos las 1000 filas vacías de Google para empezar limpio
                    df_init = df_init[df_init['TECNICO'].str.strip() != ""]
                    df_init = df_init[~df_init['TECNICO'].str.upper().isin(["NAN", "NONE", "NULL"])]
            st.session_state.memoria_expedientes = df_init
        except:
            st.session_state.memoria_expedientes = pd.DataFrame()
    
    with st.expander("➕ Crear Nuevo Registro (Múltiple y Continuo)", expanded=True):
        with st.form("form_registro_continuo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_nombres = cargar_personal("personal_tecnico.txt")
                colaborador_sel = st.selectbox("👤 Colaborador (De Lista General):", options=["---"] + lista_nombres)
                categoria_reg = st.radio("🏷️ Tipo de Registro:", ["Falta Disciplinaria", "Incidencia Operativa"], horizontal=True)
                
            with c2:
                tipo_falta = st.selectbox("🚫 Motivo/Categoría:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Tiempos Muertos", "Mala Documentación", "Insubordinación", 
                    "Incidencia Médica", "Otro"
                ])
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias Visuales:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            st.info(f"✍️ Supervisor a cargo del registro: **{supervisor_actual}**")
            comentario = st.text_area("📝 Descripción detallada de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ Complete obligatoriamente el nombre y la descripción.")
                else:
                    try:
                        urls = []
                        if archivos:
                            with st.spinner("Subiendo archivos de evidencia..."):
                                for a in archivos:
                                    res = requests.post("https://freeimage.host/api/1/upload", data={"key": API_KEY_FREEIMAGE, "action": "upload", "source": base64.b64encode(a.getvalue()).decode('utf-8'), "format": "json"})
                                    if res.status_code == 200: urls.append(res.json()["image"]["url"])
                                    time.sleep(1)
                        
                        nueva_fila = pd.DataFrame([{
                            "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO": colaborador_sel,
                            "CATEGORIA": categoria_reg,
                            "TIPO_FALTA": tipo_falta,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        # USAMOS NUESTRA MEMORIA PARA EVITAR REESCRIBIR
                        df_local = st.session_state.memoria_expedientes
                        
                        cols = ["FECHA_REGISTRO", "TECNICO", "CATEGORIA", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
                        for c in cols:
                            if c not in df_local.columns: df_local[c] = ""
                            if c not in nueva_fila.columns: nueva_fila[c] = ""
                        
                        # Pegamos la fila al final (Fila 8, 9, 10...)
                        df_final = pd.concat([df_local, nueva_fila], ignore_index=True)
                        df_final = df_final[cols] # Aseguramos orden perfecto
                        df_final = df_final.fillna("").astype(str).replace(["nan", "NaN", "None", "null"], "")
                        
                        # 1. ACTUALIZAMOS GOOGLE SHEETS
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        # 2. ACTUALIZAMOS NUESTRA MEMORIA PARA EL SIGUIENTE REGISTRO INMEDIATO
                        st.session_state.memoria_expedientes = df_final
                        st.cache_data.clear()
                        
                        st.success(f"✅ ¡Guardado automático! Se agregó a {colaborador_sel} al expediente general.")
                        time.sleep(1.5); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error crítico de guardado: {e}")

    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    try:
        # Mostramos los datos directamente desde nuestra memoria ultrarrápida
        df_view = st.session_state.get('memoria_expedientes', pd.DataFrame())
        
        if not df_view.empty:
            df_view['TECNICO'] = df_view['TECNICO'].str.upper().str.strip()
            
            c_v, c_b = st.columns([3, 1])
            with c_b:
                st.download_button("📊 Reporte Gerencial", data=generar_pdf_consolidado(df_view), file_name="Reporte_General.pdf", mime="application/pdf", use_container_width=True, type="primary")

            nombres = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar Colaborador:", options=nombres)
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                es_m = str(row.get('TIPO_FALTA')).upper() == "INCIDENCIA MÉDICA"
                color_borde = "#3B82F6" if es_m else "#EF4444"
                
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {color_borde}; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin:0; color:white;">{row['TECNICO']}</h3>
                            <span style="font-size:11px; font-weight:bold; background:{color_borde}; color:white; padding:3px 12px; border-radius:15px;">{row['TIPO_FALTA']}</span>
                        </div>
                        <p style="color:#94A3B8; margin:5px 0;"><b>Registrado por:</b> {row.get('SUPERVISOR', 'N/D')} | <b>Fecha Evento:</b> {row['FECHA_INCIDENCIA']}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; color:white; margin:10px 0;">{row['COMENTARIO']}</div>
                        <p style="font-size:0.8rem; color:#64748B;">{row['FECHA_REGISTRO']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c_p, c_d = st.columns(2)
                    with c_p:
                        doc_name = "Constancia Médica" if es_m else "Memorandum"
                        st.download_button(f"📄 Descargar {doc_name}", data=generar_pdf_memo(row.to_dict()), file_name=f"Reporte_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
                    with c_d:
                        if es_admin and st.button("🗑️ Eliminar", key=f"d_{idx}", use_container_width=True):
                            df_new = df_view.drop(idx)
                            # Eliminamos de GSheets y de la Memoria Local simultáneamente
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                            st.session_state.memoria_expedientes = df_new
                            st.cache_data.clear(); st.rerun()
        else:
            st.info("No hay registros en el expediente o la base de datos está vacía.")
    except Exception as e: 
        st.warning(f"⚠️ Actualizando historial interno... ({e})")
