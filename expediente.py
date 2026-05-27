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
import numpy as np

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
# LÓGICA DE ASIGNACIÓN DE RUBROS AUTOMÁTICOS (INCLUYE NUEVA ASIGNACIÓN RECO)
# ==============================================================================
def asignar_rubro_automatico(motivo, comentario):
    motivo_str = str(motivo).upper().strip()
    comentario_str = str(comentario).upper().strip()
    
    claves_gps = ['VEHICULO', 'CARRO', 'MOTO', 'CONDUCIR', 'LLANTA', 'COLISION', 'CHOQUE', 'VELOCIDAD', 'RUTA', 'GPS', 'GASOLINA', 'KILOMETRAJE']
    claves_biometrico = ['TARDE', 'LLEGADA', 'TARDANZA', 'BIOMETRICO', 'MARCAJE', 'HORARIO', 'ASISTENCIA']
    claves_cepheus = ['CEPHEUS', 'DOCUMENTA', 'CERRAR', 'ABRIR', 'ORDEN', 'RETRASO ORDEN', 'LIQUIDAC']
    claves_reco = ['RECO', 'POSTE', 'POSTES', 'CAMBIO DE POSTE', 'CAMBIO DE POSTES']
    
    if "RECO" in motivo_str or "POSTE" in motivo_str:
        return "RECO"
    if any(clv in motivo_str or clv in comentario_str for clv in claves_reco):
        return "RECO"
        
    if "EXCESO DE VELOCIDAD" in motivo_str or "ABANDONO DE RUTA" in motivo_str:
        return "GPS"
    if any(clv in motivo_str or clv in comentario_str for clv in claves_gps):
        return "GPS"
        
    if "LLEGADA TARDE" in motivo_str:
        return "BIOMÉTRICO"
    if any(clv in motivo_str or clv in comentario_str for clv in claves_biometrico):
        return "BIOMÉTRICO"
        
    if "MALA DOCUMENTACIÓN" in motivo_str or "MALA DOCUMENTACION" in motivo_str:
        return "CEPHEUS"
    if any(clv in motivo_str or clv in comentario_str for clv in claves_cepheus):
        return "CEPHEUS"
        
    return "OTROS"

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
            
            pdf.cell(30, 6, f" {f_reg}", border=1, align="C")
            pdf.cell(50, 6, f" {tec}", border=1)
            pdf.cell(35, 6, f" {mot}", border=1)
            pdf.cell(75, 6, f" {com[:45]}...", border=1, ln=True)
    return pdf.output(dest='S')

def subir_imagen_freeimage(image_bytes):
    try:
        url = "https://freeimage.host/api/1/upload"
        payload = {
            "key": API_KEY_FREEIMAGE,
            "action": "upload",
            "source": base64.b64encode(image_bytes).decode('utf-8')
        }
        res = requests.post(url, data=payload, timeout=15)
        if res.status_code == 200:
            return res.json().get('image', {}).get('url', None)
    except: pass
    return None

# ==============================================================================
# MÓDULO PRINCIPAL DE INTERFAZ
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_nube_base=None):
    st.title("🗂️ Sistema de Expedientes Operativos")
    
    # SOLUCIÓN DE RAÍZ AL NameError: Cargar la lista del personal técnico desde el catálogo estructurado
    lista_personal = cargar_personal()
    
    with st.spinner("☁️ Cargando bitácora de incidencias desde la base de datos..."):
        try:
            df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
            if df is None or df.empty:
                df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        except Exception as e:
            st.error(f"Error al conectar con la base de datos: {e}")
            return

    if df is not None and not df.empty:
        df.columns = df.columns.str.upper().str.strip()
        if 'FECHA_REGISTRO' in df.columns:
            df['FECHA_REGISTRO_DT'] = pd.to_datetime(df['FECHA_REGISTRO'], errors='coerce')
        else:
            df['FECHA_REGISTRO_DT'] = pd.NaT
    else:
        df = pd.DataFrame(columns=['FECHA_REGISTRO', 'TECNICO', 'TIPO_FALTA', 'COMENTARIO', 'URL_EVIDENCIA', 'RUBRO_AUTO', 'AUTOR', 'FECHA_REGISTRO_DT'])

    menu_exp = st.tabs(["📊 Reporte General", "➕ Registrar Incidencia", "📜 Historial Completo"])
    
    # --------------------------------------------------------------------------
    # PESTAÑA 1: REPORTE GENERAL
    # --------------------------------------------------------------------------
    with menu_exp[0]:
        st.subheader("Análisis y Métricas de Rendimiento")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            todos_tecs = ["VER TODOS"] + sorted(list(df['TECNICO'].dropna().unique())) if not df.empty else ["VER TODOS"]
            filtro_nombre = st.selectbox("👤 Filtrar por Colaborador:", options=todos_tecs, key="f_nom_exp")
        with col2:
            hoy = get_honduras_time().date()
            rango_fechas = st.date_input("📅 Rango de Fechas:", value=(hoy - timedelta(days=60), hoy), key="f_fec_exp")
        with col3:
            filtro_tipo = st.selectbox("📋 Tipo de Registro:", options=["Todos los Tipos", "Llamado de Atención", "Incidencia Médica"], key="f_tip_exp")
            
        df_mostrar = df.copy()
        if filtro_nombre != "VER TODOS":
            df_mostrar = df_mostrar[df_mostrar['TECNICO'] == filtro_nombre]
            
        if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
            f_ini, f_fin = pd.to_datetime(rango_fechas[0]), pd.to_datetime(rango_fechas[1]) + timedelta(days=1)
            df_mostrar = df_mostrar[(df_mostrar['FECHA_REGISTRO_DT'] >= f_ini) & (df_mostrar['FECHA_REGISTRO_DT'] < f_fin)]
            
        if filtro_tipo != "Todos los Tipos":
            df_mostrar = df_mostrar[df_mostrar['TIPO_FALTA'].str.contains(filtro_tipo, case=False, na=False)]
            
        if not df_mostrar.empty:
            m1, m2, m3 = st.columns(3)
            with m1: st.metric("📋 Total Eventos", len(df_mostrar))
            with m2: st.metric("👥 Colaboradores Afectados", df_mostrar['TECNICO'].nunique())
            with m3:
                rubro_top = df_mostrar['RUBRO_AUTO'].mode()[0] if 'RUBRO_AUTO' in df_mostrar.columns and not df_mostrar['RUBRO_AUTO'].dropna().empty else "N/D"
                st.metric("🔥 Rubro Más Crítico", rubro_top)
                
            c_top1, c_top2 = st.columns(2)
            with c_top1:
                st.markdown("<h5 style='color:#10B981; font-size:13px; font-weight:bold;'>🍩 Distribución por Rubros Automatizados</h5>", unsafe_allow_html=True)
                fig_p = px.pie(df_mostrar, names='RUBRO_AUTO', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_p.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=260, showlegend=True)
                st.plotly_chart(fig_p, use_container_width=True)
            with c_top2:
                st.markdown("<h5 style='color:#F59E0B; font-size:13px; font-weight:bold;'>📅 Faltas por Día</h5>", unsafe_allow_html=True)
                df_mostrar['DIA_NOM'] = df_mostrar['FECHA_REGISTRO_DT'].dt.day_name()
                orden_dias = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                map_dias = {'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles', 'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'}
                df_dias = df_mostrar['DIA_NOM'].value_counts().reindex(orden_dias, fill_value=0).reset_index()
                df_dias['index'] = df_dias['index'].map(map_dias)
                fig_b = px.bar(df_dias, x='index', y='DIA_NOM', labels={'index': 'Día', 'DIA_NOM': 'Cantidad'}, color_discrete_sequence=['#3B82F6'])
                fig_b.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=260)
                st.plotly_chart(fig_b, use_container_width=True)
                
            # ---> NUEVA TABLA SOLICITADA: DESGLOSE COMPLETO POR RUBROS Y CANTIDADES
            st.markdown("<h4 style='color:#10B981; font-size:15px; font-weight:bold; margin-top:20px;'>📊 Resumen General de Incidencias por Rubro</h4>", unsafe_allow_html=True)
            df_resumen_rubros = df_mostrar['RUBRO_AUTO'].value_counts().reset_index()
            df_resumen_rubros.columns = ['Rubro / Tipo de Falta', 'Cantidad de Incidencias']
            st.dataframe(df_resumen_rubros, use_container_width=True, hide_index=True)
            
            st.divider()
            try:
                pdf_b = generar_pdf_consolidado(df_mostrar)
                st.download_button("📥 DESCARGAR REPORTE CONSOLIDADO (PDF)", data=pdf_b, file_name="Reporte_Expedientes.pdf", mime="application/pdf", use_container_width=True)
            except Exception as e_pdf:
                st.warning(f"El generador de PDF está sincronizando componentes: {e_pdf}")
        else:
            st.info("No hay registros en el rango seleccionado.")

    # --------------------------------------------------------------------------
    # PESTAÑA 2: REGISTRAR INCIDENCIA (NUEVO RUBRO RECO COMPARTIDO)
    # --------------------------------------------------------------------------
    with menu_exp[1]:
        st.subheader("Formulario de Captura")
        
        tipo_falta_base = st.selectbox(
            "⚠️ Seleccione el Rubro de la Falta/Incidencia:",
            options=[
                "Exceso de Velocidad",
                "Llegada Tarde",
                "Abandono de Ruta",
                "Mala Documentación",
                "Incidencia Médica",
                "Reco / Cambio de Postes",
                "Otro"
            ], key="sel_falta"
        )
        
        # LÓGICA SOLICITADA: Interceptar si es RECO para bloquear el formulario forzando a técnico RECO
        if tipo_falta_base == "Reco / Cambio de Postes":
            tipo_falta = "RECO / CAMBIO DE POSTES"
            opciones_tecnicos = ["RECO"]
            index_defecto = 0
            disabled_tec = True
        else:
            tipo_falta = tipo_falta_base
            if tipo_falta_base == "Otro":
                motivo_especifico = st.text_input("📝 Especifique el motivo de la falta:", key="txt_motivo_otro")
                tipo_falta = motivo_especifico.strip().upper() if motivo_especifico else "OTRO"
            opciones_tecnicos = lista_personal if lista_personal else ["SIN CATÁLOGO"]
            index_defecto = 0
            disabled_tec = False

        c1, c2 = st.columns(2)
        with c1:
            tec_name = st.selectbox("👤 Colaborador Asociado:", options=opciones_tecnicos, index=index_defecto, disabled=disabled_tec, key="sel_tec_exp")
        with c2:
            fecha_inc = st.date_input("📅 Fecha:", value=get_honduras_time().date(), key="date_inc")
            
        archivos = st.file_uploader("📸 Captura de Evidencia (Imagen PNG/JPG):", type=['png', 'jpg', 'jpeg'], key="file_evidencia")
        comentario = st.text_area("💬 Notas u Observaciones del Supervisor:", placeholder="Detalle lo sucedido...", key="txt_com_exp")
        
        if st.button("💾 GUARDAR INCIDENCIA EN EXPEDIENTE", type="primary", use_container_width=True):
            if not tec_name or tec_name == "SIN CATÁLOGO":
                st.error("Por favor configure un colaborador válido.")
                return
            if not comentario.strip():
                st.error("Las observaciones no pueden quedar vacías.")
                return
                
            with st.spinner("☁️ Procesando y subiendo registros..."):
                url_url = ""
                if archivos is not None:
                    url_url = subir_imagen_freeimage(archivos.getvalue())
                    if not url_url:
                        url_url = "Evidencia subida localmente"
                
                # Asignar automáticamente el rubro analítico
                rubro_calculado = asignar_rubro_automatico(tipo_falta, comentario)
                
                nuevo_reg = {
                    'FECHA_REGISTRO': get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    'TECNICO': tec_name,
                    'TIPO_FALTA': tipo_falta.upper(),
                    'COMENTARIO': comentario.strip(),
                    'URL_EVIDENCIA': url_url if url_url else "SIN EVIDENCIA",
                    'RUBRO_AUTO': rubro_calculado,
                    'AUTOR': st.session_state.get('usuario_actual', 'Supervisor').upper()
                }
                
                df_nuevo_row = pd.DataFrame([nuevo_reg])
                df_total = pd.concat([df, df_nuevo_row], ignore_index=True)
                if 'FECHA_REGISTRO_DT' in df_total.columns:
                    df_total = df_total.drop(columns=['FECHA_REGISTRO_DT'], errors='ignore')
                
                try:
                    sobrescribir_archivo_gcs(df_total, NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
                    conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_total)
                    st.success("✅ Incidencia guardada en el expediente correctamente.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Fallo en la comunicación con el servidor: {e}")

    # --------------------------------------------------------------------------
    # PESTAÑA 3: HISTORIAL COMPLETO
    # --------------------------------------------------------------------------
    with menu_exp[2]:
        st.subheader("Historial Maestro del Personal")
        if not df.empty:
            df_vista = df.copy()
            if 'FECHA_REGISTRO_DT' in df_vista.columns:
                df_vista = df_vista.drop(columns=['FECHA_REGISTRO_DT'], errors='ignore')
            st.dataframe(df_vista.sort_values(by='FECHA_REGISTRO', ascending=False), use_container_width=True)
            
            # Módulo de borrado exclusivo para administradores
            if st.session_state.get('rol_actual', '').upper() == 'ADMINISTRADOR':
                st.markdown("---")
                st.markdown("<h5 style='color:#EF4444; font-size:13px;'>🗑️ Zona de Eliminación Administrativa</h5>", unsafe_allow_html=True)
                idx_sel = st.number_input("Ingrese el ID del índice a eliminar:", min_value=0, max_value=len(df)-1, step=1)
                if st.button("🔥 ELIMINAR REGISTRO SELECCIONADO", type="secondary", use_container_width=True):
                    with st.spinner("Modificando GCS y Sheets..."):
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
