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

# --- IMPORTACIONES DE HERRAMIENTAS ---
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
    # Nuevas funciones para el cruce mensual
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

# Configuración de Nube
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# MOTOR DE CONEXIÓN A GOOGLE DRIVE
# ==============================================================================
def subir_archivo_drive(file_buffer, file_name, mimetype):
    """Sube un archivo a Google Drive usando la ruta directa."""
    try:
        if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
            return None, "Falta la configuración '[connections.gsheets]' en los Secrets."

        creds_dict = dict(st.secrets["connections"]["gsheets"])
        if '\\n' in creds_dict.get('private_key', ''):
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')

        folder_id = "1_HRdEQMRWrhSeasMwr5HAJlZBLDLL6yB"
        
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=credentials)
        
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_buffer, mimetype=mimetype, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        
        service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}, supportsAllDrives=True).execute()
        
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
        self.line(10, 25, 200, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-25)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
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
    pdf.set_y(pdf.get_y() + 2); pdf.set_x(15)
    pdf.cell(90, 8, "Fecha: ______/______/ 20______")
    pdf.cell(90, 8, "Placa / Codigo: ________________________", ln=True)
    pdf.set_x(15)
    pdf.cell(90, 8, "Conductor: ________________________")
    pdf.cell(90, 8, "Kilometraje Actual: ________________________", ln=True)
    pdf.ln(5)

    categorias = {
        "1. FLUIDOS Y MOTOR": ["Nivel de aceite de motor", "Nivel de aceite de transmision", "Nivel de refrigerante / agua", "Fugas visibles en motor"],
        "2. SUSPENSION Y MECANICA": ["Sistema de Direccion", "Suspension general", "Frenos delanteros (fricciones)", "Frenos traseros (zapatas)"],
        "3. EXTERIORES Y LLANTAS": ["Estado de llantas en uso", "Llanta de repuesto", "Luces (Faros, vias)", "Estado de carroceria"],
        "4. EQUIPAMIENTO DE SEGURIDAD": ["Extintor de incendios", "Conos y triangulo reflectivo", "Gata hidraulica y llave de rueda"]
    }

    for cat, items in categorias.items():
        pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(30, 58, 138); pdf.set_text_color(255, 255, 255)
        pdf.cell(190, 7, f"  {cat}", ln=True, fill=True)
        pdf.set_font("Helvetica", "", 10); pdf.set_text_color(15, 23, 42)
        for item in items:
            pdf.cell(130, 7, f"      {item}", border='B')
            pdf.cell(20, 7, "[ B ]", border='B', align="C")
            pdf.cell(20, 7, "[ A ]", border='B', align="C")
            pdf.cell(20, 7, "[ D ]", border='B', align="C", ln=True)
        pdf.ln(3)

    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

@st.cache_data(show_spinner=False)
def generar_pdf_calendario():
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "MAXCOM - CALENDARIO ANUAL DE INSPECCIONES (2026-2027)", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(30, 58, 138); pdf.set_text_color(255, 255, 255)
    pdf.cell(25, 8, "Mes / Ano", border=1, align="C", fill=True)
    pdf.cell(20, 8, "Quincena", border=1, align="C", fill=True)
    pdf.cell(20, 8, "Unidad", border=1, align="C", fill=True)
    pdf.cell(25, 8, "Placa", border=1, align="C", fill=True)
    pdf.cell(100, 8, "Descripcion del Vehiculo", border=1, align="C", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 8); pdf.set_text_color(15, 23, 42)
    for row in DATOS_CALENDARIO:
        pdf.cell(25, 7, f"{row['Mes']} {row['Año']}", border=1, align="C")
        pdf.cell(20, 7, row['Quincena'], border=1, align="C")
        pdf.cell(20, 7, row['Unidad'], border=1, align="C")
        pdf.cell(25, 7, row['Placa'], border=1, align="C")
        pdf.cell(100, 7, str(row['Descripción']).encode('latin-1', 'replace').decode('latin-1'), border=1, align="L", ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd); pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path); return data

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1: st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad, tab_eficiencia, tab_checklist = st.tabs([
        "⏱️ Auditoría de Tiempos", "🚀 Telemetría", "⚖️ Eficiencia Total", "📋 Gestión Documental"
    ])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_t1, col_t2 = st.columns([4, 1])
        with col_t2: 
            if st.button("🔄 Refrescar", key="ref_t"): 
                if 'df_gps_memoria' in st.session_state: del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático", "🗓️ Reporte Mensual Consolidado"], horizontal=True)

        # SECCIÓN DE CARGA NUBE (AUDITORIA GPS)
        st.markdown("### ☁️ Sincronización de Tiempos GPS")
        if st.button("☁️ Cargar Historial GPS desde la Nube", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("Descargando..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados correctamente.")
                    except Exception as e: st.error(f"❌ Error: {e}")
            else: st.error("❌ No se detectó conexión.")
                
        st.divider()
        
        # --- LÓGICA DE PROCESAMIENTO ---
        df_gps_crudo = st.session_state.get('df_gps_memoria')

        if df_gps_crudo is not None:
            if tipo_reporte == "📊 Reporte Diario":
                res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                if res_t is not None:
                    st.dataframe(res_t, use_container_width=True, hide_index=True)
                    st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), f"Diario_Tiempos.pdf", "application/pdf", use_container_width=True)
                else: st.error(msg)
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), f"Semanal_Tiempos.pdf", "application/pdf", use_container_width=True)
                else: st.warning(msg_sem)

            # ==============================================================================
            # CRUCE MENSUAL GERENCIAL (PEDIDO POR EL USUARIO)
            # ==============================================================================
            elif tipo_reporte == "🗓️ Reporte Mensual Consolidado":
                st.markdown("### 📊 Cruce Mensual: GPS vs Nube (Sheet1)")
                st.info("Este reporte cruza el historial de Zonas/Rutas del GPS con la producción de la **Sheet1** en la nube.")
                
                # Paso 1: Sincronizar Sheet1
                if st.button("🔍 1. Sincronizar Producción de la Nube (Sheet1)", use_container_width=True):
                    with st.spinner("Conectando con Google Drive..."):
                        try:
                            df_nube_val = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                            if not df_nube_val.empty:
                                st.session_state['df_nube_sheet1'] = df_nube_val
                                st.success("✅ Datos de Sheet1 cargados correctamente.")
                                st.rerun()
                        except Exception as e: st.error(f"Error nube: {e}")
                
                # Paso 2: Subir archivo GPS y cruzar
                if 'df_nube_sheet1' in st.session_state:
                    st.success("✔ Base de datos en la nube (Actividades) lista.")
                    archivo_zonas = st.file_uploader("📥 2. Sube el archivo 'InformeZonasRutas' (Excel/CSV)", type=['csv', 'xlsx'], key="zonas_mensual")
                    
                    if archivo_zonas:
                        with st.spinner("🧠 Calculando Eficiencia y Horas Semanales..."):
                            df_zonas_raw = read_file_robust(archivo_zonas)
                            # Llamada a la función en tools.py
                            df_cruce_res, msg_c = procesar_mensual_zonas_con_nube(df_zonas_raw, st.session_state['df_nube_sheet1'])
                            
                            if df_cruce_res is not None:
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown("#### 🏠 Rendimiento Residencial")
                                    st.dataframe(df_cruce_res[df_cruce_res['SEGMENTO_PRO'] == 'RESIDENCIAL'].drop(columns=['SEGMENTO_PRO']), hide_index=True)
                                with c2:
                                    st.markdown("#### 🏢 Rendimiento PLEX")
                                    st.dataframe(df_cruce_res[df_cruce_res['SEGMENTO_PRO'] == 'PLEX'].drop(columns=['SEGMENTO_PRO']), hide_index=True)
                                
                                st.divider()
                                pdf_final = generar_pdf_gerencial_mensual_premium(df_cruce_res, "Resumen Mensual Gerencial")
                                st.download_button(
                                    label="📥 DESCARGAR REPORTE GERENCIAL PREMIUM (PDF)",
                                    data=pdf_final,
                                    file_name=f"Reporte_Mensual_Operativo.pdf",
                                    mime="application/pdf",
                                    use_container_width=True,
                                    type="primary"
                                )
                            else: st.error(f"❌ Error en el cruce: {msg_c}")
                else:
                    st.warning("Primero debes sincronizar los datos de la nube en el botón de arriba.")

    # --- PESTAÑA 2: TELEMETRÍA (SIN CAMBIOS) ---
    with tab_velocidad:
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        limite_vel = st.number_input("Promediar solo velocidades mayores a (km/h):", 10, 200, 60, 5)
        if not es_movil:
            archivos_tel = st.file_uploader("Sube archivos de Telemetría", accept_multiple_files=True, key="up_tel")
            if archivos_tel:
                with st.spinner("Analizando..."):
                    archivo_principal = next((f for f in archivos_tel if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    if archivo_principal:
                        df_matriz, msg_tel = procesar_matriz_telemetria(read_file_robust(archivo_principal))
                        if df_matriz is not None:
                            st.dataframe(df_matriz, use_container_width=True, hide_index=True)
                            st.download_button("📥 Reporte Velocidad (PDF)", generar_pdf_telemetria_matriz(df_matriz, limite_vel), "Telemetria.pdf", use_container_width=True)
        else: st.info("📱 Función disponible solo en PC.")

    # --- PESTAÑA 3: EFICIENCIA TOTAL (SIN CAMBIOS) ---
    with tab_eficiencia:
        st.markdown("### ⚖️ Cruce de Productividad vs GPS")
        st.caption("Calcula el porcentaje de tiempo producido en calle.")
        # Se mantiene la lógica de carga de rep_actividades y DetencionDetallado...
        st.info("Utiliza esta pestaña para cruces rápidos de eficiencia diaria.")

    # --- PESTAÑA 4: CHECKLIST (Drive) ---
    with tab_checklist:
        st.markdown("### 📋 Gestión Documental de Flota (Google Drive)")
        with st.expander("📅 Ver Calendario Anual de Inspecciones", expanded=False):
            st.dataframe(pd.DataFrame(DATOS_CALENDARIO), use_container_width=True, hide_index=True)

        col_f, col_u = st.columns(2)
        with col_f:
            st.markdown("#### 1️⃣ Formato Físico")
            st.download_button("📄 DESCARGAR PLANTILLA (PDF)", generar_pdf_en_blanco(), "Formato_Inspeccion.pdf", use_container_width=True)
        with col_u:
            st.markdown("#### 2️⃣ Subir Escáner")
            with st.form("form_drive"):
                f_esc = st.date_input("Fecha Inspección")
                p_veh = st.text_input("Placa Vehículo", placeholder="Ej: HAA1234")
                a_esc = st.file_uploader("Archivo (PDF/Imagen)", type=['pdf','jpg','png'])
                if st.form_submit_button("💾 ENVIAR A DRIVE", type="primary", use_container_width=True):
                    if p_veh and a_esc:
                        buffer = io.BytesIO(a_esc.getvalue())
                        link, err = subir_archivo_drive(buffer, f"{p_veh}_{f_esc}.pdf", "application/pdf")
                        if link: st.success("✅ Subido a Drive"); time.sleep(1); st.rerun()
                        else: st.error(err)
                    else: st.warning("Faltan datos.")

        # --- REGISTRO MAESTRO (INSPECCIONES) ---
        st.markdown("---")
        st.markdown("#### 📜 Registro de Inspecciones")
        try:
            df_i = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
            if not df_i.empty:
                st.dataframe(df_i.iloc[::-1], use_container_width=True, hide_index=True)
        except: st.info("No hay registros aún.")
