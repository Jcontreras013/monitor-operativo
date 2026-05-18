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
# CONFIGURACIÓN Y CARGA DE PERSONAL
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

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
@st.cache_data(show_spinner=False, max_entries=50) 
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
        pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "Desglose de Eventos Registrados:", ln=True)
        pdf.set_font("Helvetica", "B", 8); pdf.set_fill_color(240, 240, 240)
        pdf.cell(30, 8, " Fecha y Hora", border=1, fill=True, align="C")
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
                b_top = 'T' if i == 0 else ''
                b_bot = 'B' if i == len(lineas_com) - 1 else ''
                b_style = 'LR' + b_top + b_bot
                col1 = f" {f_reg}" if i == 0 else ""
                col2 = f" {tec}" if i == 0 else ""
                col3 = f" {mot}" if i == 0 else ""
                pdf.cell(30, 5, col1, border=b_style, align="C")
                pdf.cell(50, 5, col2, border=b_style)
                pdf.cell(35, 5, col3, border=b_style)
                pdf.cell(75, 5, f" {linea}", border=b_style, ln=True)
        
        tiene_anexos = False
        for _, row in df.iterrows():
            urls = str(row.get('URL_FOTO', '')).split(',')
            validas = [u.strip() for u in urls if u.strip().startswith('http')]
            if validas:
                tiene_anexos = True
                break
                
        if tiene_anexos:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(40, 50, 100)
            pdf.cell(0, 10, "ANEXOS - EVIDENCIA FOTOGRAFICA", ln=True, align="C")
            pdf.ln(5)
            for _, row in df.iterrows():
                urls = str(row.get('URL_FOTO', '')).split(',')
                validas = [u.strip() for u in urls if u.strip().startswith('http')]
                if validas:
                    tec_name = sanitizar(str(row.get('TECNICO','')))
                    f_inc = sanitizar(str(row.get('FECHA_INCIDENCIA','')))
                    motivo_falta = sanitizar(str(row.get('TIPO_FALTA','')))
                    for url in validas:
                        try:
                            r = requests.get(url, timeout=10)
                            if r.status_code == 200:
                                fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
                                try:
                                    with open(tp, 'wb') as f: f.write(r.content)
                                    if pdf.get_y() > 60: pdf.add_page() 
                                    pdf.set_font("Helvetica", "B", 9); pdf.set_text_color(0, 0, 0)
                                    pdf.set_fill_color(240, 240, 240)
                                    pdf.cell(0, 8, f" Evidencia: {tec_name} | {motivo_falta} | {f_inc}", ln=True, fill=True, border=1)
                                    pdf.ln(3)
                                    pdf.image(tp, x=20, w=150) 
                                    pdf.ln(10)
                                finally:
                                    if os.path.exists(tp):
                                        os.remove(tp)
                        except: pass
            
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

@st.cache_data(show_spinner=False, max_entries=50) 
def generar_pdf_memo(row_dict):
    pdf = MemoPDF(); pdf.alias_nb_pages(); pdf.add_page()
    es_medica = str(row_dict.get('TIPO_FALTA', '')).upper() in ["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"]
    if es_medica:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(0, 102, 204)
        titulo = "CONSTANCIA DE INCIDENCIA MEDICA"
    else:
        pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
        titulo = "MEMORANDUM: LLAMADO DE ATENCION"
    pdf.cell(0, 10, titulo, ln=True, align="C"); pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0); pdf.set_fill_color(240, 240, 240)
    pdf.cell(40, 8, " Colaborador:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TECNICO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Motivo/Falta:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('TIPO_FALTA'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Fecha Suceso:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('FECHA_INCIDENCIA'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Registro:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('FECHA_REGISTRO'))}", border=1, ln=True)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(40, 8, " Registrado por:", border=1, fill=True); pdf.set_font("Helvetica", "", 10); pdf.cell(150, 8, f" {sanitizar(row_dict.get('SUPERVISOR'))}", border=1, ln=True)
    pdf.ln(8); pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(40, 50, 100); pdf.cell(0, 8, "Detalle de los Hechos:", ln=True); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    for l in textwrap.wrap(str(row_dict.get('COMENTARIO','')), width=95): pdf.cell(0, 6, sanitizar(l), ln=True)
    urls = str(row_dict.get('URL_FOTO', '')).split(',')
    for u in [x.strip() for x in urls if x.strip().startswith('http')]:
        try:
            r = requests.get(u, timeout=10)
            if r.status_code == 200:
                fd, tp = tempfile.mkstemp(suffix=".png"); os.close(fd)
                try:
                    with open(tp, 'wb') as f: f.write(r.content)
                    if pdf.get_y() > 60: pdf.add_page()
                    pdf.image(tp, x=15, w=170); pdf.ln(5)
                finally:
                    if os.path.exists(tp):
                        os.remove(tp)
        except: pass
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: d = f.read()
    os.remove(path); return d

# ==============================================================================
# 🚨 FUNCIÓN AUXILIAR: ESCUDO ANTI-LAG (LLAVES UNIFICADAS Y CORRECTAS) 🚨
# ==============================================================================
def obtener_df_seguro(conn):
    st.cache_data.clear() # Destruye el caché falso de Streamlit
    df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    
    if not df_nube.empty:
        df_nube.columns = df_nube.columns.astype(str).str.strip().str.upper()
        if 'TECNICO' in df_nube.columns:
            df_nube['TECNICO_TEST'] = df_nube['TECNICO'].astype(str).str.strip().str.lower()
            df_nube = df_nube[~df_nube['TECNICO_TEST'].isin(['', 'nan', 'none', 'null', 'nat', 'undefined'])]
            df_nube = df_nube.drop(columns=['TECNICO_TEST'])
    else:
        df_nube = pd.DataFrame()

    # EL ESCUDO: Aquí estaba el error de nombre. Ahora coincide exactamente con la que guardamos.
    if 'MEMORIA_EXPEDIENTES_ACTUAL' in st.session_state:
        df_local = st.session_state['MEMORIA_EXPEDIENTES_ACTUAL']
        # Si Google nos da MENOS registros de los que nosotros sabemos que guardamos, ignoramos a Google
        if len(df_nube) < len(df_local):
            return df_local.copy()
            
    return df_nube

def limpiar_df_para_escritura(df):
    return (
        df.fillna("")
          .astype(str)
          .replace(["nan", "NaN", "None", "null", "NaT", "undefined"], "")
    )

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    columnas_oficiales = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA", "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]

    with st.expander("➕ Crear Nuevo Registro", expanded=True):
        st.info(f"✍️ Supervisor registrando: **{supervisor_actual}**")
        with st.form("form_incidencia_txt", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                lista_nombres = cargar_personal("personal_tecnico.txt")
                colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres)
                tipo_falta = st.selectbox("🚫 Motivo:", [
                    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                    "Mala Documentación", "Incidencia Médica", "Otro"
                ])
            with c2:
                fecha_inc = st.date_input("📅 Fecha:", value=get_honduras_time().date())
                archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            comentario = st.text_area("📝 Descripción de los hechos:")
            
            if st.form_submit_button("💾 GUARDAR EN EXPEDIENTE"):
                if colaborador_sel == "---" or not comentario:
                    st.error("⚠️ Complete el nombre y el comentario.")
                else:
                    try:
                        urls = []
                        if archivos:
                            for a in archivos:
                                res = requests.post(
                                    "https://freeimage.host/api/1/upload",
                                    data={
                                        "key": API_KEY_FREEIMAGE,
                                        "action": "upload",
                                        "source": base64.b64encode(a.getvalue()).decode('utf-8'),
                                        "format": "json"
                                    }
                                )
                                if res.status_code == 200:
                                    urls.append(res.json()["image"]["url"])
                        
                        nueva_fila = pd.DataFrame([{
                            "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO": colaborador_sel,
                            "TIPO_FALTA": tipo_falta,
                            "FECHA_INCIDENCIA": fecha_inc.strftime("%d/%m/%Y"),
                            "COMENTARIO": comentario,
                            "URL_FOTO": ", ".join(urls),
                            "SUPERVISOR": supervisor_actual
                        }])

                        # 1. LEER USANDO EL ESCUDO
                        df_db = obtener_df_seguro(conn)
                        
                        # 2. ASEGURAR COLUMNAS
                        for col in columnas_oficiales:
                            if col not in df_db.columns: 
                                df_db[col] = ""
                        df_db = df_db[columnas_oficiales]
                        
                        # 3. PEGAR LA NUEVA FILA (SIN DESTRUIR LO ANTERIOR)
                        df_final = pd.concat([df_db, nueva_fila], ignore_index=True)
                        
                        # 4. LIMPIEZA FINAL
                        df_final = df_final.drop_duplicates(subset=['FECHA_REGISTRO', 'TECNICO', 'TIPO_FALTA'], keep='last')
                        df_final = limpiar_df_para_escritura(df_final)
                        
                        # 5. SUBIR A GOOGLE SHEETS
                        conn.update(
                            spreadsheet=st.secrets["url_base_datos"],
                            worksheet="Expedientes",
                            data=df_final
                        )
                        
                        # 6. ACTIVAR ESCUDO: GUARDAR LA MEMORIA LOCAL CON LA LLAVE EXACTA PARA EL PRÓXIMO GUARDADO
                        st.session_state['MEMORIA_EXPEDIENTES_ACTUAL'] = df_final.copy()
                        
                        st.success(f"✅ ¡Guardado con éxito para {colaborador_sel}!")
                        time.sleep(1.5)
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    st.markdown("---")
    
    # --------------------------------------------------------------------------
    # HISTORIAL DE EXPEDIENTES Y FILTROS
    # --------------------------------------------------------------------------
    st.subheader("📜 Historial de Expedientes")
    try:
        # Se lee con el escudo por si Google sigue retrasado al cargar la tabla
        df_view = obtener_df_seguro(conn)
        
        if not df_view.empty and 'TECNICO' in df_view.columns:
            df_view['TECNICO'] = df_view['TECNICO'].astype(str).str.upper().str.strip()
            
            with st.container():
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    filtro_nombre = st.selectbox(
                        "🔍 Colaborador:",
                        options=["VER TODOS"] + sorted(df_view['TECNICO'].unique().tolist())
                    )
                
                with col2:
                    hoy = get_honduras_time().date()
                    hace_una_semana = hoy - timedelta(days=60) 
                    rango_fechas = st.date_input(
                        "📅 Rango de Fechas:",
                        value=(hace_una_semana, hoy)
                    )
                
                with col3:
                    filtro_tipo = st.selectbox(
                        "📋 Tipo de Registro:",
                        options=["Todos los Tipos", "Llamado de Atención", "Incidencia Médica"]
                    )

            df_mostrar = df_view.copy()
            
            if filtro_nombre != "VER TODOS":
                df_mostrar = df_mostrar[df_mostrar['TECNICO'] == filtro_nombre]
            
            if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
                fecha_inicio, fecha_fin = rango_fechas

                def parsear_fecha(fecha_str):
                    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                        try:
                            return datetime.strptime(str(fecha_str).strip(), fmt).date()
                        except ValueError:
                            continue
                    return None

                df_mostrar['FECHA_INCIDENCIA_DT'] = df_mostrar['FECHA_INCIDENCIA'].apply(parsear_fecha)
                
                df_mostrar = df_mostrar[
                    df_mostrar['FECHA_INCIDENCIA_DT'].notna() &
                    (df_mostrar['FECHA_INCIDENCIA_DT'] >= fecha_inicio) & 
                    (df_mostrar['FECHA_INCIDENCIA_DT'] <= fecha_fin)
                ]
            
            if filtro_tipo == "Incidencia Médica":
                df_mostrar = df_mostrar[df_mostrar['TIPO_FALTA'].str.upper().isin(["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"])]
            elif filtro_tipo == "Llamado de Atención":
                df_mostrar = df_mostrar[~df_mostrar['TIPO_FALTA'].str.upper().isin(["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"])]
            
            c_v, c_b = st.columns([3, 1])
            with c_b:
                if not df_mostrar.empty:
                    nombre_archivo = (
                        "Reporte_General.pdf" if filtro_nombre == "VER TODOS"
                        else f"Reporte_{filtro_nombre.replace(' ', '_')}.pdf"
                    )
                    etiqueta = (
                        "📊 Reporte Gerencial" if filtro_nombre == "VER TODOS"
                        else f"📊 Reporte de {filtro_nombre}"
                    )
                    st.download_button(
                        etiqueta,
                        data=generar_pdf_consolidado(df_mostrar),
                        file_name=nombre_archivo,
                        mime="application/pdf",
                        use_container_width=True
                    )

            if df_mostrar.empty:
                st.info("💡 No hay registros. (Verifica si necesitas ampliar el rango de fechas)")
            else:
                for idx, row in df_mostrar.iloc[::-1].iterrows():
                    es_m = str(row.get('TIPO_FALTA', '')).upper() in ["INCIDENCIA MÉDICA", "INCIDENCIA MEDICA"]
                    c_tag = "#3B82F6" if es_m else "#EF4444"
                    
                    with st.container():
                        st.markdown(f"""<div style="background-color: #1A1D24; padding: 15px; border-radius: 10px; border-left: 5px solid {c_tag}; margin-bottom: 10px; border: 1px solid #2D2F39;">
                            <h3 style="margin:0; color:white;">{row['TECNICO']}</h3>
                            <p style="color:#94A3B8;"><b>Motivo:</b> {row['TIPO_FALTA']} | <b>Fecha:</b> {row['FECHA_INCIDENCIA']}</p>
                            <p style="font-size:12px; color:#64748B;">Registrado por: {row.get('SUPERVISOR', 'N/D')}</p>
                            <div style="background:#0F1115; padding:10px; border-radius:5px; color:white;">{row['COMENTARIO']}</div>
                        </div>""", unsafe_allow_html=True)
                        
                        c_p, c_d = st.columns(2)
                        with c_p:
                            st.download_button(
                                f"📄 Descargar {'Constancia Medica' if es_m else 'Documento'}",
                                data=generar_pdf_memo(row.to_dict()),
                                file_name=f"Reporte_{idx}.pdf",
                                key=f"p_{idx}",
                                use_container_width=True
                            )
                        with c_d:
                            if es_admin:
                                if st.button("🗑️ Eliminar", key=f"del_{idx}", use_container_width=True):
                                    df_new = df_view.drop(idx)
                                    df_new = limpiar_df_para_escritura(df_new)
                                    conn.update(
                                        spreadsheet=st.secrets["url_base_datos"],
                                        worksheet="Expedientes",
                                        data=df_new
                                    )
                                    # SE ACTUALIZA EL ESCUDO LOCAL AL ELIMINAR PARA NO RESUCITAR LA FILA BORRADA
                                    st.session_state['MEMORIA_EXPEDIENTES_ACTUAL'] = df_new.copy()
                                    time.sleep(1)
                                    st.rerun()
        else:
            st.info("No hay registros válidos en la base de datos.")

    except Exception as e:
        st.warning(f"⚠️ Error al cargar el historial: {e}")
