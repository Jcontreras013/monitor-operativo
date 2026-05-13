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
    if pd.isna(texto): return "N/D"
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
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen Estadístico:", ln=True)
        # Resumen por categoría (Falta o Incidencia)
        col_resumen = 'CATEGORIA' if 'CATEGORIA' in df.columns else 'TIPO_FALTA'
        for f, t in df[col_resumen].value_counts().items():
            pdf.set_font("Helvetica", "", 10); pdf.cell(140, 7, f" {sanitizar(f)}", border=1); pdf.cell(50, 7, str(t), border=1, ln=True, align="C")
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

def generar_pdf_memo(row):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
    
    # Título dinámico según la nueva clasificación
    es_falta = str(row.get('CATEGORIA', '')).upper() == "FALTA DISCIPLINARIA"
    titulo = "MEMORANDUM: LLAMADO DE ATENCION" if es_falta else "REPORTE DE INCIDENCIA OPERATIVA"
    
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 8, " Implicado:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row.get('TECNICO',''))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(35, 8, " Clasificación:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row.get('CATEGORIA', 'Falta Disciplinaria'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(35, 8, " Motivo:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(155, 8, f" {sanitizar(row.get('TIPO_FALTA',''))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
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
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

# ==============================================================================
# 3. INTERFAZ PRINCIPAL
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    supervisor_actual = st.session_state.get('usuario', 'Supervisor')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    with st.expander("➕ Crear Nuevo Registro (SAC / Técnico / Ayudante / Otros)", expanded=True):
        with st.form("form_expediente_base", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_tecs = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                tecnico_sel = st.selectbox("👤 Seleccionar Técnico de la lista:", options=["---"] + lista_tecs)
                
                # CAMPO PARA AYUDANTES / SAC / OTROS
                nombre_manual = st.text_input("👷 O nombre de Colaborador (SAC, Ayudante, etc):", placeholder="Prioridad si escribe aquí")
                
                # NUEVO CAMPO DE CLASIFICACIÓN
                categoria_reg = st.radio("🏷️ Tipo de Registro:", ["Falta Disciplinaria", "Incidencia Operativa"], horizontal=True)
                
            with c2:
                tipo_evento = st.selectbox("🚫 Motivo:", ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", "Mala Atención", "Falla de Proceso", "Otro"])
                fecha_inc = st.date_input("📅 Fecha del suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                # UNIFICACIÓN DE NOMBRE (Mayúsculas)
                nombre_final = nombre_manual.strip().upper() if nombre_manual.strip() != "" else (tecnico_sel.upper() if tecnico_sel != "---" else "")
                
                if not nombre_final:
                    st.error("⚠️ Debe indicar el nombre del implicado.")
                elif not comentario:
                    st.error("⚠️ El detalle es obligatorio.")
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
                            "TECNICO": nombre_final,
                            "CATEGORIA": categoria_reg,
                            "TIPO_FALTA": tipo_evento,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        # LÓGICA DE GUARDADO BASE (Como te funcionaba)
                        df_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        
                        # Concatenar y asegurar que la columna CATEGORIA no genere errores
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        
                        # IMPORTANTE: Rellenar vacíos con texto para que GSheets no rechace la tabla
                        df_final = df_final.fillna("").astype(str)
                        
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        
                        st.cache_data.clear()
                        st.success(f"✅ ¡Guardado para {nombre_final}!")
                        time.sleep(1.5); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        df_view = df_view.fillna("").astype(str)
        df_view = df_view[df_view['TECNICO'] != ""]
        
        if not df_view.empty:
            df_view['TECNICO'] = df_view['TECNICO'].str.upper().str.strip()
            
            c_v, c_b = st.columns([3, 1])
            with c_b:
                st.download_button("📊 Reporte Gerencial", data=generar_pdf_consolidado(df_view), file_name="Reporte_General.pdf", mime="application/pdf", use_container_width=True)

            nombres = ["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("🔍 Buscar Colaborador:", options=nombres)
            
            df_mostrar = df_view if filtro == "VER TODOS" else df_view[df_view['TECNICO'] == filtro]
            
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                # Color según si es Falta o Incidencia
                c_tag = "#EF4444" if row.get('CATEGORIA') == "Falta Disciplinaria" else "#3B82F6"
                
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {c_tag}; margin-bottom: 10px; border: 1px solid #2D2F39;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin:0; color:white;">{row['TECNICO']}</h3>
                            <span style="background:{c_tag}; color:white; padding:3px 12px; border-radius:15px; font-size:11px; font-weight:bold;">{str(row.get('CATEGORIA', 'FALTA')).upper()}</span>
                        </div>
                        <p style="margin:5px 0; color:#94A3B8;"><b>Motivo:</b> {row['TIPO_FALTA']} | <b>Fecha:</b> {row['FECHA_INCIDENCIA']}</p>
                        <div style="background:#0F1115; padding:10px; border-radius:5px; margin:10px 0; color:white;">{row['COMENTARIO']}</div>
                        <p style="font-size:0.8rem; color:#64748B;">Registrado por {row.get('SUPERVISOR','N/D')} el {row['FECHA_REGISTRO']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c_p, c_d = st.columns(2)
                    with c_p:
                        doc_name = "Memo" if row.get('CATEGORIA') == "Falta Disciplinaria" else "Reporte"
                        st.download_button(f"📄 Descargar {doc_name}", data=generar_pdf_memo(row.to_dict()), file_name=f"{doc_name}_{idx}.pdf", key=f"p_{idx}", use_container_width=True)
                    with c_d:
                        if es_admin and st.button("🗑️ Eliminar", key=f"d_{idx}", use_container_width=True):
                            df_new = df_view.drop(idx)
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_new)
                            st.cache_data.clear(); st.rerun()
        else:
            st.info("No hay registros en el expediente.")
    except Exception as e:
        st.warning(f"⚠️ El historial se está actualizando...")
