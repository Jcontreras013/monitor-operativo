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
from streamlit_gsheets import GSheetsConnection

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
        # Resumen
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Resumen por Tipo de Falta:", ln=True)
        pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(240, 240, 240)
        pdf.cell(140, 8, " Motivo / Falta", border=1, fill=True)
        pdf.cell(50, 8, " Cantidad Total", border=1, ln=True, align="C", fill=True)
        pdf.set_font("Helvetica", "", 10)
        for cat, total in df['TIPO_FALTA'].value_counts().items():
            pdf.cell(140, 7, f" {sanitizar(cat)}", border=1)
            pdf.cell(50, 7, str(total), border=1, ln=True, align="C")
            
        pdf.ln(10)
        # Desglose
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
    campos = [
        ("Colaborador:", "TECNICO"), ("Motivo/Falta:", "TIPO_FALTA"),
        ("Fecha Suceso:", "FECHA_INCIDENCIA"), ("Registro:", "FECHA_REGISTRO"),
        ("Registrado por:", "SUPERVISOR")
    ]
    for label, key in campos:
        pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, f" {label}", border=1, fill=True)
        pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get(key))}", border=1, ln=True)
    
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    
    # Imágenes
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
# LÓGICA DE DATOS (ANTI-LAG)
# ==============================================================================
def leer_expedientes_limpio(conn):
    st.cache_data.clear() # Forzar refresco
    df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    
    columnas_oficiales = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]
    
    if df.empty:
        return pd.DataFrame(columns=columnas_oficiales)
    
    df.columns = df.columns.astype(str).str.strip().str.upper()
    for col in columnas_oficiales:
        if col not in df.columns: df[col] = ""
    
    # Filtrar solo filas con técnico válido (ignorar vacías al final)
    df = df[df['TECNICO'].astype(str).str.strip() != ""]
    return df[columnas_oficiales]

# ==============================================================================
# INTERFAZ PRINCIPAL
# ==============================================================================
def main():
    st.set_page_config(page_title="Gestión de Expedientes", layout="wide")
    
    # Inicializar Conexión
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return

    # Credenciales simuladas (Ajusta según tu sistema de login)
    supervisor_actual = st.session_state.get('usuario_actual', "SUPERVISOR PRUEBA")
    es_admin = st.session_state.get('rol_actual', 'admin') == 'admin'

    st.title("📁 Gestión de Expedientes y Reportes")

    # --- FORMULARIO DE INGRESO ---
    with st.expander("➕ Crear Nuevo Registro", expanded=True):
        with st.form("form_incidencia", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                lista_nombres = cargar_personal()
                colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres)
                tipo_falta = st.selectbox("🚫 Motivo:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Mala Documentación", "Incidencia Médica", "Otro"
                ])
            with col2:
                fecha_inc = st.date_input("📅 Fecha del Suceso:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción detallada:")
            
            if st.form_submit_button("💾 GUARDAR REGISTRO"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ El colaborador y el comentario son obligatorios.")
                else:
                    with st.spinner("Subiendo datos..."):
                        try:
                            # Subir fotos
                            urls = []
                            if archivos:
                                for a in archivos:
                                    res = requests.post("https://freeimage.host/api/1/upload",
                                        data={"key": API_KEY_FREEIMAGE, "action": "upload",
                                              "source": base64.b64encode(a.getvalue()).decode('utf-8'),
                                              "format": "json"})
                                    if res.status_code == 200: urls.append(res.json()["image"]["url"])

                            # Preparar fila
                            nueva_fila = [
                                get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                                colaborador_sel,
                                tipo_falta,
                                fecha_inc.strftime("%d/%m/%Y"),
                                comentario,
                                ", ".join(urls),
                                supervisor_actual
                            ]

                            # Escritura directa a Google Sheets (Bypass cache)
                            doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                            hoja = doc.worksheet("Expedientes")
                            hoja.append_row(nueva_fila)
                            
                            st.cache_data.clear()
                            st.success("✅ Guardado con éxito.")
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar: {e}")

    # --- HISTORIAL ---
    st.markdown("---")
    st.subheader("📜 Historial de Expedientes")
    
    try:
        df_view = leer_expedientes_limpio(conn)
        
        if not df_view.empty:
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.upper()
            
            # Filtros
            c1, c2, c3 = st.columns(3)
            with c1:
                filtro_nombre = st.selectbox("🔍 Buscar por Nombre:", ["TODOS"] + sorted(df_view['TECNICO'].unique().tolist()))
            with c2:
                rango = st.date_input("📅 Rango:", value=(get_honduras_time().date()-timedelta(days=30), get_honduras_time().date()))
            with c3:
                filtro_tipo = st.selectbox("📋 Filtro Tipo:", ["Todos", "Llamado Atención", "Incidencia Médica"])

            # Aplicar filtros
            df_mostrar = df_view.copy()
            if filtro_nombre != "TODOS":
                df_mostrar = df_mostrar[df_mostrar['TECNICO'] == filtro_nombre]
            
            if filtro_tipo == "Incidencia Médica":
                df_mostrar = df_mostrar[df_mostrar['TIPO_FALTA'].str.upper().str.contains("MÉDICA|MEDICA")]
            elif filtro_tipo == "Llamado Atención":
                df_mostrar = df_mostrar[~df_mostrar['TIPO_FALTA'].str.upper().str.contains("MÉDICA|MEDICA")]

            # Botón Reporte General
            if not df_mostrar.empty:
                st.download_button("📊 Descargar Reporte PDF de esta vista",
                                  data=generar_pdf_consolidado(df_mostrar),
                                  file_name="Reporte_Consolidado.pdf",
                                  mime="application/pdf")

            # Mostrar tarjetas
            for idx, row in df_mostrar.iloc[::-1].iterrows():
                es_m = "MEDICA" in str(row['TIPO_FALTA']).upper() or "MÉDICA" in str(row['TIPO_FALTA']).upper()
                color = "#3B82F6" if es_m else "#EF4444"
                
                with st.container():
                    st.markdown(f"""
                    <div style="border-left: 5px solid {color}; background-color: #1A1D24; padding: 15px; border-radius: 5px; margin-bottom: 10px; border-top: 1px solid #333; border-right: 1px solid #333; border-bottom: 1px solid #333;">
                        <h4 style="margin:0; color:white;">{row['TECNICO']}</h4>
                        <p style="margin:0; color:#94A3B8; font-size:14px;">{row['TIPO_FALTA']} | Suceso: {row['FECHA_INCIDENCIA']}</p>
                        <p style="margin:5px 0; color:#CBD5E1;">{row['COMENTARIO']}</p>
                        <small style="color:#64748B;">Reg: {row['FECHA_REGISTRO']} por {row['SUPERVISOR']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    col_btn1, col_btn2 = st.columns([1, 4])
                    with col_btn1:
                        st.download_button(f"📄 PDF", data=generar_pdf_memo(row.to_dict()), 
                                         file_name=f"Expediente_{idx}.pdf", key=f"btn_{idx}")
                    with col_btn2:
                        if es_admin:
                            if st.button("🗑️ Eliminar", key=f"del_{idx}"):
                                # Lógica para eliminar fila
                                doc = conn.client.open_by_url(st.secrets["url_base_datos"])
                                hoja = doc.worksheet("Expedientes")
                                # +2 porque Sheets empieza en 1 y tiene encabezado
                                hoja.delete_rows(idx + 2)
                                st.cache_data.clear()
                                st.rerun()
        else:
            st.info("No hay registros en la base de datos.")
            
    except Exception as e:
        st.error(f"Error cargando historial: {e}")

if __name__ == "__main__":
    main()
