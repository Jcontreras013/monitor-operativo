import streamlit as st
import pandas as pd
import re
import requests
import base64
import tempfile
import os
import io
import time
from datetime import datetime, timedelta, timezone

from tools import (
    get_hn_time,
    read_file_robust,
    time_to_sec_robust,
    procesar_auditoria_vehiculos,
    procesar_auditoria_semanal,
    procesar_auditoria_mensual,
    procesar_matriz_telemetria,
    generar_pdf_auditoria_tiempos,
    generar_pdf_semanal_tiempos,
    generar_pdf_mensual_tiempos,
    generar_pdf_telemetria_matriz,
    # --- NUEVAS IMPORTACIONES PARA EL CRUCE ---
    procesar_mensual_zonas_con_nube,
    generar_pdf_gerencial_mensual_premium
)

# --- IMPORTACIONES BLINDADAS ---
try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    DRIVE_DISPONIBLE = True
except ImportError:
    DRIVE_DISPONIBLE = False
    st.warning("⚠️ Faltan librerías de Google Drive. Ejecuta: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

# Configuración de Nube
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# MOTOR DE CONEXIÓN A GOOGLE DRIVE (RESTAURADO)
# ==============================================================================
def subir_archivo_drive(file_buffer, file_name, mimetype):
    """Sube un archivo a Google Drive usando la ruta directa."""
    try:
        if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
            return None, "Falta la configuración '[connections.gsheets]' en los Secrets."

        creds_dict = dict(st.secrets["connections"]["gsheets"])
        if '\\n' in creds_dict.get('private_key', ''):
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')

        # TU CARPETA ORIGINAL DE DRIVE
        folder_id = "1_HRdEQMRWrhSeasMwr5HAJlZBLDLL6yB"
        
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=credentials)
        
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(file_buffer, mimetype=mimetype, resumable=True)
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink'), None
    except Exception as e:
        return None, str(e)

# ==============================================================================
# DATOS DEL CALENDARIO DE INSPECCIONES
# ==============================================================================
DATOS_CALENDARIO = [
    {"Año": 2026, "Mes": "Junio", "Quincena": "1ra", "Unidad": "MX-5", "Placa": "HED3834", "Descripción": "Kia K2700 cabina sensilla"},
    {"Año": 2026, "Mes": "Junio", "Quincena": "2da", "Unidad": "MX-14", "Placa": "HBB8594", "Descripción": "Mazda BT 50 cabina sencilla"},
    {"Año": 2026, "Mes": "Julio", "Quincena": "1ra", "Unidad": "MX-22", "Placa": "HDQ9370", "Descripción": "Kia Camion cabina sencilla"},
    {"Año": 2026, "Mes": "Julio", "Quincena": "2da", "Unidad": "MX-7", "Placa": "HED3852", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Agosto", "Quincena": "1ra", "Unidad": "MX-1", "Placa": "HDL9821", "Descripción": "Kia Camion grande cabina sensilla"},
    {"Año": 2026, "Mes": "Agosto", "Quincena": "2da", "Unidad": "MX-20", "Placa": "HDA9649", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Septiembre", "Quincena": "1ra", "Unidad": "MX-12", "Placa": "HAU6095", "Descripción": "Kia picanto"},
    {"Año": 2026, "Mes": "Septiembre", "Quincena": "2da", "Unidad": "MX-4", "Placa": "HAU8203", "Descripción": "Camionsito kia Doble cabina"},
    {"Año": 2026, "Mes": "Octubre", "Quincena": "1ra", "Unidad": "MX-16", "Placa": "HBJ1307", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Octubre", "Quincena": "2da", "Unidad": "MX-26", "Placa": "HDU5167", "Descripción": "Mazda BT-50 Doble Gris"},
    {"Año": 2026, "Mes": "Noviembre", "Quincena": "1ra", "Unidad": "MX-9", "Placa": "HAB9494", "Descripción": "Izusu cabina sencilla"},
    {"Año": 2026, "Mes": "Noviembre", "Quincena": "2da", "Unidad": "MX-15", "Placa": "HBJ1317", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Diciembre", "Quincena": "1ra", "Unidad": "MX-25", "Placa": "HBZ0246", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Diciembre", "Quincena": "2da", "Unidad": "MX-2", "Placa": "HDP9223", "Descripción": "Kia Camion Cabina cabina sensilla"},
    {"Año": 2027, "Mes": "Enero", "Quincena": "1ra", "Unidad": "MX-18", "Placa": "HDZ2561", "Descripción": "Isuzu Cabina Sencilla"},
    {"Año": 2027, "Mes": "Enero", "Quincena": "2da", "Unidad": "MX-23", "Placa": "HDV2997", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2027, "Mes": "Febrero", "Quincena": "1ra", "Unidad": "MX-10", "Placa": "HAC9763", "Descripción": "Izusu cabina sencilla"},
    {"Año": 2027, "Mes": "Febrero", "Quincena": "2da", "Unidad": "MX-13", "Placa": "HBA2557", "Descripción": "Camioncito Kia cabina sencilla"},
    {"Año": 2027, "Mes": "Marzo", "Quincena": "1ra", "Unidad": "MX-3", "Placa": "HED3833", "Descripción": "Mazda BT-50 Doble"},
    {"Año": 2027, "Mes": "Marzo", "Quincena": "2da", "Unidad": "MX-30", "Placa": "JH12534", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2027, "Mes": "Abril", "Quincena": "1ra", "Unidad": "MX-19", "Placa": "HED6941", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2027, "Mes": "Abril", "Quincena": "2da", "Unidad": "MX-6", "Placa": "HED3832", "Descripción": "Camionsito kia Doble cabina"},
    {"Año": 2027, "Mes": "Mayo", "Quincena": "1ra", "Unidad": "MX-24", "Placa": "HBZ0243", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2027, "Mes": "Mayo", "Quincena": "2da", "Unidad": "MX-28", "Placa": "JAC5756", "Descripción": "Kia picanto"},
    {"Año": 2027, "Mes": "Junio", "Quincena": "1ra", "Unidad": "MX-17", "Placa": "HDA4311", "Descripción": "Izusu Pick Up cabina sencilla"},
    {"Año": 2027, "Mes": "Junio", "Quincena": "2da", "Unidad": "MX-21", "Placa": "HDV2994", "Descripción": "Suzuki Carry camion cabina sencilla"}
]

# ==============================================================================
# GENERADORES DE PDF (FORMATO BLANCO Y CALENDARIO)
# ==============================================================================
class FormatoInspeccionPDF(FPDF):
    def header(self):
        self.set_y(10)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(15, 23, 42)
        self.cell(0, 8, "MAXCOM - FORMATO DE INSPECCION VEHICULAR EN CAMPO", ln=True, align="C")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 116, 139)
        self.cell(0, 5, "Departamento de Control Operativo | Aseguramiento de Calidad", ln=True, align="C")
        self.set_draw_color(200, 200, 200)
        self.line(10, 25, 200, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-25)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(15, 23, 42)
        self.cell(90, 8, "Firma del Conductor: ___________________", align="C")
        self.cell(90, 8, "Firma del Supervisor: ___________________", ln=True, align="C")
        self.ln(2)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, "Este documento debe ser escaneado y subido a la plataforma MaxCom PRO.", align="C")

@st.cache_data(show_spinner=False)
def generar_pdf_en_blanco():
    pdf = FormatoInspeccionPDF()
    pdf.add_page()
    
    pdf.set_fill_color(241, 245, 249)
    pdf.rect(10, pdf.get_y(), 190, 20, style='F')
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)
    pdf.set_y(pdf.get_y() + 2)
    pdf.set_x(15)
    pdf.cell(90, 8, "Fecha: ______/______/ 20______")
    pdf.cell(90, 8, "Placa / Codigo: ________________________", ln=True)
    pdf.set_x(15)
    pdf.cell(90, 8, "Conductor: ________________________")
    pdf.cell(90, 8, "Kilometraje Actual: ________________________", ln=True)
    pdf.ln(5)

    categorias_checklist = {
        "1. FLUIDOS Y MOTOR": [
            "Nivel de aceite de motor", "Nivel de aceite de transmision",
            "Nivel de aceite diferencial", "Nivel de aceite hidraulico (Direccion)",
            "Liquido de frenos", "Nivel de refrigerante / agua", "Fugas visibles en motor"
        ],
        "2. SUSPENSION Y MECANICA": [
            "Sistema de Direccion", "Suspension general", "Bujes de tijera",
            "Hojas de resorte", "Frenos delanteros (fricciones)", "Frenos traseros (zapatas)"
        ],
        "3. EXTERIORES Y LLANTAS": [
            "Estado de llantas en uso (desgaste/presion)", "Llanta de repuesto",
            "Luces (Faros delanteros, traseros, vias)", "Estado de carroceria y espejos"
        ],
        "4. EQUIPAMIENTO DE SEGURIDAD": [
            "Extintor de incendios", "Conos y mica/triangulo reflectivo", "Gata hidraulica y llave de rueda"
        ]
    }

    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 8, "Marque con una 'X' segun corresponda:   [ B ] Buen Estado    [ A ] Requiere Atencion    [ D ] Danado o Falta", ln=True, align="C")
    pdf.ln(2)

    for cat, items in categorias_checklist.items():
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(255, 255, 255)
        pdf.set_fill_color(30, 58, 138)
        pdf.cell(190, 7, f"  {cat}", ln=True, fill=True)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(15, 23, 42)
        for item in items:
            pdf.cell(130, 7, f"      {item}", border='B')
            pdf.cell(20, 7, "[ B ]", border='B', align="C")
            pdf.cell(20, 7, "[ A ]", border='B', align="C")
            pdf.cell(20, 7, "[ D ]", border='B', align="C", ln=True)
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, "Observaciones de la Inspeccion:", ln=True)
    pdf.set_draw_color(150, 150, 150)
    for _ in range(3):
        pdf.line(10, pdf.get_y() + 6, 200, pdf.get_y() + 6)
        pdf.ln(8)

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

@st.cache_data(show_spinner=False)
def generar_pdf_calendario():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_y(10)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, "MAXCOM - CALENDARIO ANUAL DE INSPECCIONES (2026-2027)", ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, "Programacion Operativa: 2 Revisiones Mensuales por Unidad", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(30, 58, 138)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(25, 8, "Mes / Ano", border=1, align="C", fill=True)
    pdf.cell(20, 8, "Quincena", border=1, align="C", fill=True)
    pdf.cell(20, 8, "Unidad", border=1, align="C", fill=True)
    pdf.cell(25, 8, "Placa", border=1, align="C", fill=True)
    pdf.cell(100, 8, "Descripcion del Vehiculo", border=1, align="C", ln=True, fill=True)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(15, 23, 42)
    
    for row in DATOS_CALENDARIO:
        pdf.cell(25, 7, f"{row['Mes']} {row['Año']}", border=1, align="C")
        pdf.cell(20, 7, row['Quincena'], border=1, align="C")
        pdf.cell(20, 7, row['Unidad'], border=1, align="C")
        pdf.cell(25, 7, row['Placa'], border=1, align="C")
        
        desc_limpia = str(row['Descripción']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(100, 7, desc_limpia, border=1, align="L", ln=True)

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write(""); st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad, tab_eficiencia, tab_checklist = st.tabs([
        "⏱️ Auditoría de Tiempos", 
        "🚀 Telemetría", 
        "⚖️ Eficiencia Total",
        "📋 Gestión Documental"
    ])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_t1, col_t2 = st.columns([4, 1])
        with col_t2: 
            if st.button("🔄 Refrescar", key="ref_t"): 
                if 'df_gps_memoria' in st.session_state:
                    del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático", "🗓️ Reporte Mensual Consolidado"], horizontal=True)

elif tipo_reporte == "🗓️ Reporte Mensual Consolidado":
                st.markdown("### 📊 DASHBOARD GERENCIAL: CRUCE DE ARCHIVOS")
                st.warning("Este proceso ignora la nube y usa archivos cargados directamente para mayor precisión.")
                
                c_up1, c_up2 = st.columns(2)
                with c_up1:
                    archivo_zonas = st.file_uploader("1️⃣ Sube 'InformeZonasRutas' (GPS)", type=['csv', 'xlsx'], key="u_z")
                with c_up2:
                    archivo_act = st.file_uploader("2️⃣ Sube 'rep_actividades' (Excel)", type=['xlsx'], key="u_a")
                
                if archivo_zonas and archivo_act:
                    if st.button("🚀 GENERAR CRUCE DE RENDIMIENTO MENSUAL", use_container_width=True, type="primary"):
                        with st.spinner("🧠 Analizando miles de registros..."):
                            df_z_raw = read_file_robust(archivo_zonas)
                            df_a_raw = read_file_robust(archivo_act)
                            
                            # LLAMADA AL NUEVO MOTOR DE CRUCE DIRECTO
                            df_res, kpis, msg = procesar_mensual_cruce_directo(df_z_raw, df_a_raw)
                            
                            if df_res is not None and not df_res.empty:
                                # --- VISTA DE KPIs ---
                                st.markdown("#### 📈 Indicadores Clave de Desempeño")
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Eficiencia RES", f"{kpis['ef_res']} pts/hr")
                                m2.metric("Eficiencia PLEX", f"{kpis['ef_plex']} pts/hr")
                                m3.metric("Órdenes Totales", kpis['total_ord'])
                                m4.metric("Horas Calle", f"{kpis['total_hrs']}h")

                                # --- TABLAS ---
                                t_res, t_plex = st.tabs(["🏠 TÉCNICOS RESIDENCIAL", "🏢 TÉCNICOS PLEX"])
                                with t_res:
                                    st.dataframe(df_res[df_res['SEGMENTO_PRO'] == 'RESIDENCIAL'].drop(columns=['SEGMENTO_PRO']), use_container_width=True, hide_index=True)
                                with t_plex:
                                    st.dataframe(df_res[df_res['SEGMENTO_PRO'] == 'PLEX'].drop(columns=['SEGMENTO_PRO']), use_container_width=True, hide_index=True)

                                # --- PDF ---
                                st.divider()
                                pdf_data = generar_pdf_gerencial_mensual_premium(df_res, kpis, "Resumen Operativo Mensual")
                                st.download_button("📥 DESCARGAR INFORME GERENCIAL (PDF)", data=pdf_data, file_name="Reporte_Gerencial.pdf", mime="application/pdf", use_container_width=True)
                            
                            elif df_res is not None and df_res.empty:
                                st.error("❌ Los archivos cargaron bien, pero no se encontró ningún código 'MX' en común para cruzarlos. Revisa que la columna MX o los nombres tengan el formato MX-00.")
                            else:
                                st.error(f"❌ Error en el proceso: {msg}")
                else:
                    st.info("Por favor sube ambos archivos para habilitar el botón de procesamiento.")
        
        else:
            # Lógica para Diario y Semanal Automático
            df_gps_crudo = None
            st.markdown("### ☁️ Sincronización de Tiempos")
            if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
                if conn is not None:
                    with st.spinner("📥 Descargando historial de la nube..."):
                        try:
                            df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                            if not df_descarga.empty:
                                st.session_state['df_gps_memoria'] = df_descarga
                                st.success("✅ Datos descargados de la nube correctamente.")
                        except Exception as e: st.error(f"❌ Error: {e}")
                else: st.error("❌ No se detectó conexión a Google Sheets.")
                    
            st.divider()
            if not es_movil:
                st.markdown("### 📥 Ingreso Manual (Modo PC)")
                archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas (Tiempos)", type=['csv', 'xlsx', 'xls'], key="up_tiempos")
                if archivo_gps_tiempos:
                    with st.spinner("Subiendo a la Nube..."):
                        try:
                            df_gps_crudo = read_file_robust(archivo_gps_tiempos)
                            if conn:
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                                st.success("☁️ ¡Datos subidos exitosamente!")
                        except Exception as e: st.error(f"❌ Error al subir: {e}")
            
            if df_gps_crudo is None and 'df_gps_memoria' in st.session_state: 
                df_gps_crudo = st.session_state['df_gps_memoria']

            if df_gps_crudo is not None:
                if tipo_reporte == "📊 Reporte Diario":
                    res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                    if res_t is not None:
                        st.dataframe(res_t, use_container_width=True, hide_index=True)
                        st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), "Diario.pdf", use_container_width=True)
                elif tipo_reporte == "📅 Reporte Semanal Automático":
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                    if res_sem is not None:
                        st.dataframe(res_sem, use_container_width=True, hide_index=True)
                        st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), "Semanal.pdf", use_container_width=True)

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_v1, col_v2 = st.columns([4, 1])
        with col_v2: 
            if st.button("🔄 Refrescar", key="ref_v"): st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        limite_vel = st.number_input("Promediar solo velocidades mayores a (km/h):", min_value=10, max_value=200, value=60, step=5)
        
        if not es_movil:
            archivos_telemetria = st.file_uploader("Arrastra aquí TODOS los archivos Excel/CSV juntos", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_telemetria")
            
            if archivos_telemetria:
                with st.spinner("Analizando y cruzando matrices..."):
                    archivo_principal = next((f for f in archivos_telemetria if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    if archivo_principal:
                        df_raw_tel = read_file_robust(archivo_principal)
                        df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                        if df_matriz is not None:
                            st.dataframe(df_matriz, use_container_width=True, hide_index=True)
                            st.download_button("📥 Descargar Reporte Velocidad (PDF)", generar_pdf_telemetria_matriz(df_matriz, limite_vel), "Velocidad.pdf", use_container_width=True)

    # --- PESTAÑA 3: EFICIENCIA TOTAL ---
    with tab_eficiencia:
        st.markdown("### ⚖️ Cruce de Productividad vs Tiempos GPS")
        st.info("Utiliza esta pestaña para cruces diarios de eficiencia de motor.")
        # Se mantiene la lógica que tenías...

    # --- PESTAÑA 4: CHECKLIST INSPECCIÓN VEHICULAR ---
    with tab_checklist:
        st.markdown("### 📋 Gestión Documental de Flota (Google Drive)")
        with st.expander("📅 Ver Calendario Anual de Inspecciones (2026-2027)", expanded=False):
            df_cal = pd.DataFrame(DATOS_CALENDARIO)
            st.dataframe(df_cal, use_container_width=True, hide_index=True)

        col_formato, col_upload = st.columns(2)
        with col_formato:
            st.markdown("#### 1️⃣ Obtener Formato Físico")
            st.download_button("📄 DESCARGAR PLANTILLA (PDF)", generar_pdf_en_blanco(), "Formato_Inspeccion.pdf", use_container_width=True)

        with col_upload:
            st.markdown("#### 2️⃣ Subir Documento Escaneado")
            with st.form("form_subida_escaner"):
                fecha_escaneo = st.date_input("Fecha de Inspección:", value=get_hn_time().date())
                placa_vehiculo = st.text_input("🚗 Placa del Vehículo:*")
                archivo_escaner = st.file_uploader("📥 Sube el PDF o Imagen:", type=['pdf', 'png', 'jpg', 'jpeg'])
                if st.form_submit_button("💾 ENVIAR A GOOGLE DRIVE", type="primary", use_container_width=True):
                    if placa_vehiculo and archivo_escaner:
                        buffer = io.BytesIO(archivo_escaner.getvalue())
                        link, err = subir_archivo_drive(buffer, f"{placa_vehiculo}_{fecha_escaneo}.pdf", "application/pdf")
                        if link: st.success("✅ Subido correctamente"); time.sleep(1); st.rerun()
                        else: st.error(err)

        # Registro Maestro
        st.markdown("---")
        st.markdown("#### 📜 Registro Maestro de Inspecciones Físicas")
        try:
            df_view_insp = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
            if df_view_insp is not None and not df_view_insp.empty:
                st.dataframe(df_view_insp.iloc[::-1], use_container_width=True, hide_index=True)
        except: st.info("Aún no hay escáneres vehiculares.")
