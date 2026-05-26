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
import plotly.express as px

# --- IMPORTACIÓN DE HERRAMIENTAS GCS ---
try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

# ==============================================================================
# CONFIGURACIÓN Y CARGA DE PERSONAL
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

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
# 3. INTERFAZ DE EXPEDIENTES
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    with st.expander("➕ Crear Nuevo Registro", expanded=True):
        st.info(f"✍️ Supervisor registrando: **{supervisor_actual}**")
        
        c1, c2 = st.columns(2)
        with c1:
            lista_nombres = cargar_personal("personal_tecnico.txt")
            colaborador_sel = st.selectbox("👤 Colaborador:", options=["---"] + lista_nombres, key="sel_colab")
            tipo_falta = st.selectbox("🚫 Motivo:", [
                "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                "Mala Documentación", "Incidencia Médica", "Otro"
            ], key="sel_falta")
        with c2:
            fecha_inc = st.date_input("📅 Fecha:", value=get_honduras_time().date(), key="date_inc")
            archivos = st.file_uploader("🖼️ Evidencias:", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="up_archivos")
        
        comentario = st.text_area("📝 Descripción de los hechos:", key="txt_comentario")
        
        if st.button("💾 GUARDAR EN EXPEDIENTE", type="primary", use_container_width=True):
            if colaborador_sel == "---" or not comentario:
                st.error("⚠️ Complete el nombre y el comentario.")
            else:
                try:
                    urls = []
                    if archivos:
                        with st.spinner("Subiendo imágenes al servidor..."):
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
                    
                    with st.spinner("Guardando en la Nube y en Sheets..."):
                        df_actual = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        if df_actual is None or df_actual.empty:
                            df_actual = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            
                        cols_exp = ['FECHA_REGISTRO', 'TECNICO', 'TIPO_FALTA', 'FECHA_INCIDENCIA', 'COMENTARIO', 'URL_FOTO', 'SUPERVISOR']
                        
                        nueva_fila = [
                            get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            colaborador_sel,
                            tipo_falta,
                            fecha_inc.strftime("%d/%m/%Y"),
                            comentario,
                            ", ".join(urls),
                            supervisor_actual
                        ]
                        nuevo_df = pd.DataFrame([nueva_fila], columns=cols_exp)
                        
                        if df_actual is not None and not df_actual.empty:
                            df_actual.columns = cols_exp
                            df_final = pd.concat([df_actual, nuevo_df], ignore_index=True)
                        else:
                            df_final = nuevo_df
                            
                        sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)

                    st.success(f"✅ ¡Guardado exitosamente! {colaborador_sel} registrado en la base de datos.")
                    time.sleep(1.5)
                    
                    llaves_a_borrar = ["sel_colab", "sel_falta", "date_inc", "up_archivos", "txt_comentario"]
                    for llave in llaves_a_borrar:
                        if llave in st.session_state:
                            del st.session_state[llave]
                    
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error al intentar escribir en la base de datos: {e}")

    st.markdown("---")
    
    # ==========================================================================
    # 📊 DASHBOARD DE KPIs AVANZADO: RENDIMIENTO, REINCIDENCIA Y TIEMPOS
    # ==========================================================================
    with st.expander("📊 PANEL DE KPIs: ANALÍTICA DE PERSONAL", expanded=False):
        try:
            df_kpi = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
            if df_kpi is None or df_kpi.empty:
                df_kpi = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)

            if df_kpi is not None and not df_kpi.empty and 'TECNICO' in df_kpi.columns:
                df_kpi['TECNICO'] = df_kpi['TECNICO'].astype(str).str.upper().str.strip()
                df_kpi = df_kpi[~df_kpi['TECNICO'].isin(['NAN', 'NONE', 'N/D', ''])]
                
                df_kpi['FECHA_DT'] = pd.to_datetime(df_kpi['FECHA_INCIDENCIA'], format='%d/%m/%Y', errors='coerce')
                df_kpi['Día Semana'] = df_kpi['FECHA_DT'].dt.day_name()
                
                dias_es = {
                    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
                    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
                }
                df_kpi['Día Semana'] = df_kpi['Día Semana'].map(dias_es)

                tot_registros = len(df_kpi)
                colab_unicos = df_kpi['TECNICO'].nunique()
                motivo_comun = df_kpi['TIPO_FALTA'].value_counts().index[0] if not df_kpi['TIPO_FALTA'].empty else "N/D"
                
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("📦 Total Incidencias", f"{tot_registros} Casos")
                with m2:
                    st.metric("👤 Colaboradores Implicados", f"{colab_unicos} Personas")
                with m3:
                    st.metric("🚨 Mayor Problema", str(motivo_comun).title())
                
                st.markdown("<hr style='margin: 10px 0; border-color: #2D2F39;'>", unsafe_allow_html=True)

                col_k1, col_k2, col_k3 = st.columns(3)
                
                with col_k1:
                    st.markdown("<h5 style='color:#EF4444; font-size:14px;'>🚨 Alerta: Reincidentes Críticos</h5>", unsafe_allow_html=True)
                    df_reinc = df_kpi.groupby(['TECNICO', 'TIPO_FALTA']).size().reset_index(name='Veces Repetido')
                    df_reinc = df_reinc[df_reinc['Veces Repetido'] > 1].sort_values(by='Veces Repetido', ascending=False)
                    df_reinc.columns = ['Colaborador', 'Falta Repetida', 'Cantidad']
                    
                    if not df_reinc.empty:
                        st.dataframe(df_reinc.head(5), hide_index=True, use_container_width=True)
                    else:
                        st.success("✅ Excelente: No hay reincidentes.")

                with col_k2:
                    st.markdown("<h5 style='color:#F59E0B; font-size:14px;'>📅 ¿Qué días ocurren más faltas?</h5>", unsafe_allow_html=True)
                    orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                    df_dias = df_kpi['Día Semana'].value_counts().reindex(orden_dias, fill_value=0).reset_index()
                    df_dias.columns = ['Día', 'Cantidad']
                    
                    fig_barras_dias = px.bar(
                        df_dias, x='Día', y='Cantidad',
                        template="plotly_dark", height=200,
                        color='Cantidad', color_continuous_scale='Reds'
                    )
                    fig_barras_dias.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False, coloraxis_showscale=False, xaxis_title="", yaxis_title="")
                    st.plotly_chart(fig_barras_dias, use_container_width=True)

                with col_k3:
                    st.markdown("<h5 style='color:#10B981; font-size:14px;'>🚫 Distribución por Motivo</h5>", unsafe_allow_html=True)
                    df_motivos = df_kpi['TIPO_FALTA'].value_counts().reset_index()
                    df_motivos.columns = ['Motivo', 'Cantidad']
                    
                    fig_pie = px.pie(df_motivos, names='Motivo', values='Cantidad', hole=0.5, template="plotly_dark", height=200)
                    fig_pie.update_traces(textposition='inside', textinfo='percent+value')
                    fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
                    st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("📊 Aún no hay suficientes registros en la base de datos para calcular KPIs.")
        except Exception as e:
            st.warning(f"Error al procesar gráficas de KPIs: {e}")

    st.markdown("---")
    
    # --------------------------------------------------------------------------
    # HISTORIAL Y HISTÓRICO VISUAL
    # --------------------------------------------------------------------------
    st.subheader("📜 Historial de Expedientes")
    try:
        df_view = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
        
        if df_view is None or df_view.empty:
            df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        
        if 'TECNICO' in df_view.columns:
            df_view['TECNICO_TEST'] = df_view['TECNICO'].astype(str).str.strip().str.lower()
            df_mostrar = df_view[~df_view['TECNICO_TEST'].isin(['', 'nan', 'none', 'null', 'nat', 'undefined'])].copy()
            df_mostrar = df_mostrar.drop(columns=['TECNICO_TEST'])
        else:
            df_mostrar = pd.DataFrame()
            
        if not df_mostrar.empty:
            df_mostrar['TECNICO'] = df_mostrar['TECNICO'].astype(str).str.upper().str.strip()
            
            with st.container():
                col1, col2, col3 = st.columns(3)
                with col1:
                    filtro_nombre = st.selectbox("🔍 Colaborador:", options=["VER TODOS"] + sorted(df_mostrar['TECNICO'].unique().tolist()))
                with col2:
                    hoy = get_honduras_time().date()
                    rango_fechas = st.date_input("📅 Rango de Fechas:", value=(hoy - timedelta(days=60), hoy))
                with col3:
                    filtro_tipo = st.selectbox("📋 Tipo de Registro:", options=["Todos los Tipos", "Llamado de Atención", "Incidencia Médica"])

            if filtro_nombre != "VER TODOS":
                df_mostrar = df_mostrar[df_mostrar['TECNICO'] == filtro_nombre]
            
            if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
                fecha_inicio, fecha_fin = rango_fechas
                def parsear_fecha(f_str):
                    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                        try: return datetime.strptime(str(f_str).strip(), fmt).date()
                        except: continue
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
                    st.download_button(
                        "📊 Reporte Gerencial",
                        data=generar_pdf_consolidado(df_mostrar),
                        file_name="Reporte.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

            if df_mostrar.empty:
                st.info("💡 No hay registros para los filtros seleccionados.")
            else:
                # 1. PREPARAMOS Y MOSTRAMOS LA TABLA LIMPIA COMPACTA
                df_tabla = df_mostrar[['FECHA_INCIDENCIA', 'TECNICO', 'TIPO_FALTA', 'COMENTARIO', 'SUPERVISOR']].copy()
                df_tabla.columns = ['Fecha', 'Colaborador', 'Motivo', 'Descripción', 'Registrado por']
                
                st.dataframe(
                    df_tabla.iloc[::-1],
                    hide_index=True, 
                    use_container_width=True,
                    height=250
                )
                
                st.markdown("<br>", unsafe_allow_html=True)

                # 2. PANEL DE ACCIONES COMPACTO
                with st.expander("🛠️ ACCIONES: Descargar PDF o Eliminar Registro", expanded=False):
                    st.write("Seleccione un registro de la lista para gestionarlo:")
                    
                    dict_acciones = {}
                    lista_opciones = ["--- Seleccione un registro ---"]
                    
                    for idx, row in df_mostrar.iloc[::-1].iterrows():
                        label = f"{row['FECHA_INCIDENCIA']} | {row['TECNICO']} | {row['TIPO_FALTA']}"
                        lista_opciones.append(label)
                        dict_acciones[label] = (idx, row)
                        
                    registro_sel = st.selectbox("Registro a gestionar:", options=lista_opciones, label_visibility="collapsed")
                    
                    if registro_sel != "--- Seleccione un registro ---":
                        idx_sel, row_sel = dict_acciones[registro_sel]
                        st.info(f"**Detalle del reporte:** {row_sel['COMENTARIO']}")
                        
                        c_p, c_d = st.columns(2)
                        with c_p:
                            st.download_button(
                                "📄 Descargar Memo (PDF)",
                                data=generar_pdf_memo(row_sel.to_dict()),
                                file_name=f"Memo_{row_sel['TECNICO'].replace(' ', '_')}.pdf",
                                key=f"pdf_btn_{idx_sel}",
                                use_container_width=True
                            )
                        with c_d:
                            if es_admin:
                                if st.button("🗑️ Eliminar Registro", key=f"del_btn_{idx_sel}", type="primary", use_container_width=True):
                                    with st.spinner("Eliminando de GCS y Sheets..."):
                                        try:
                                            df_borrado = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                                            if df_borrado is None or df_borrado.empty:
                                                df_borrado = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                                            
                                            if idx_sel in df_borrado.index:
                                                df_borrado = df_borrado.drop(idx_sel).reset_index(drop=True)
                                                sobrescribir_archivo_gcs(df_borrado, NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_borrado)
                                                
                                            st.success("✅ Registro eliminado correctamente.")
                                            time.sleep(1.5)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error al eliminar: {e}")
        else:
            st.info("No hay registros en la base de datos.")

    except Exception as e:
        st.warning(f"⚠️ Error al cargar el historial: {e}")
