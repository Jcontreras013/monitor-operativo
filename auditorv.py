import streamlit as st
import pandas as pd
import re
import requests
import base64
import tempfile
import os
import io
from datetime import datetime, timedelta, timezone

from tools import (
    get_hn_time,
    read_file_robust,
    time_to_sec_robust,
    procesar_auditoria_vehiculos,
    procesar_auditoria_semanal,
    procesar_matriz_telemetria,
    generar_pdf_auditoria_tiempos,
    generar_pdf_semanal_tiempos,
    generar_pdf_telemetria_matriz
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

# Configuración de Nube (CON TU BUCKET REAL)
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "monitor_maxcom_bd"

# ==============================================================================
# MOTOR DE CONEXIÓN A GOOGLE CLOUD STORAGE (EL PLAN MAESTRO SIN ERRORES DE CUOTA)
# ==============================================================================
def subir_archivo_gcs_pdf(file_buffer, file_name, mimetype):
    """Sube un archivo directamente a tu Bucket de GCS sin límites de cuota."""
    try:
        from google.oauth2 import service_account
        from google.cloud import storage

        if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
            return None, "Falta la configuración '[connections.gsheets]' en los Secrets."

        creds_dict = dict(st.secrets["connections"]["gsheets"])
        if '\\n' in creds_dict.get('private_key', ''):
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')

        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        client = storage.Client(credentials=credentials, project=creds_dict.get('project_id'))
        
        # Inyectamos el nombre real de tu bucket de forma directa para evitar el error 404
        bucket = client.bucket("monitor_maxcom_bd")
        blob = bucket.blob(f"Inspecciones_PDF/{file_name}")
        
        file_buffer.seek(0)
        blob.upload_from_file(file_buffer, content_type=mimetype)
        
        # Generamos una URL pública para poder ver el PDF en la tabla
        try:
            blob.make_public()
        except:
            pass
            
        return blob.public_url, None
    except Exception as e:
        return None, f"Error de GCS: {str(e)}"

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
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático"], horizontal=True)
        if tipo_reporte == "📅 Reporte Semanal Automático":
            st.info("💡 El sistema detectará automáticamente los días en el archivo o historial de la Nube para generar el resumen de la semana.")

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
        else: st.info("📱 El ingreso manual está deshabilitado en móviles.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state: 
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            if tipo_reporte == "📊 Reporte Diario":
                with st.spinner("⚙️ Procesando tiempos diarios..."):
                    res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                if res_t is not None:
                    st.success("✅ Análisis Diario completado.")
                    st.dataframe(res_t, use_container_width=True, hide_index=True)
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), f"Auditoria_Tiempos_Diario.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.error(f"❌ Error: {msg}")
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y procesando consolidado semanal..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.success(f"✅ Análisis Semanal completado (Del {f_in.strftime('%d/%m/%Y')} al {f_out.strftime('%d/%m/%Y')}).")
                    
                    st.markdown("#### 📅 Desglose Diario por Vehículo")
                    st.dataframe(res_diario, use_container_width=True, hide_index=True)
                    
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), f"Auditoria_Tiempos_Semanal.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.warning(f"⚠️ {msg_sem}")

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_v1, col_v2 = st.columns([4, 1])
        with col_v2: 
            if st.button("🔄 Refrescar", key="ref_v"): st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        st.caption("El sistema creará la columna Promedio y depurará a quienes no tengan incidencias reales.")
        limite_vel = st.number_input("Promediar solo velocidades mayores a (km/h):", min_value=10, max_value=200, value=60, step=5)
        
        if not es_movil:
            archivos_telemetria = st.file_uploader("Arrastra aquí TODOS los archivos Excel/CSV juntos", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_telemetria")
            
            if archivos_telemetria:
                with st.spinner("Analizando y cruzando matrices con escáner profundo..."):
                    archivo_principal = next((f for f in archivos_telemetria if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    archivos_detallados = [f for f in archivos_telemetria if f != archivo_principal]
                            
                    if not archivo_principal:
                        st.error("❌ Sube el archivo 'Informe_Estadistico'.")
                    else:
                        try:
                            df_raw_tel = read_file_robust(archivo_principal)
                            df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                            
                            if df_matriz is not None:
                                dict_promedios = {}
                                col_placa_matriz = df_matriz.columns[0]
                                placas_validas = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper().unique()
                                
                                if archivos_detallados:
                                    for file_det in archivos_detallados:
                                        try:
                                            file_det.seek(0)
                                            raw_text = file_det.getvalue().decode('utf-8', errors='ignore').upper()
                                            if len(raw_text) < 100: raw_text = file_det.getvalue().decode('latin1', errors='ignore').upper()
                                            
                                            placa_encontrada = None
                                            for p in placas_validas:
                                                if str(p) in raw_text or str(p) in file_det.name.upper():
                                                    placa_encontrada = str(p); break
                                            
                                            if not placa_encontrada: continue 
                                            
                                            df_d = read_file_robust(file_det)
                                            header_idx = None
                                            for i in range(min(20, len(df_d))):
                                                row_str = " ".join([str(x) for x in df_d.iloc[i].values]).upper()
                                                if 'VELOCIDAD' in row_str or 'KM/H' in row_str:
                                                    header_idx = i; break
                                            
                                            if header_idx is not None:
                                                df_d.columns = [str(x).strip().upper() for x in df_d.iloc[header_idx].values]
                                                from tools import forzar_columnas_unicas
                                                df_d = forzar_columnas_unicas(df_d) 
                                                df_d = df_d.iloc[header_idx + 1:]
                                                
                                                col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|KM/H|SPEED', str(c), re.I)), None)
                                                if col_vel:
                                                    df_d['Vel_Num'] = df_d[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                                    df_excesos = df_d[df_d['Vel_Num'] > limite_vel]
                                                    if not df_excesos.empty:
                                                        dict_promedios[placa_encontrada] = round(df_excesos['Vel_Num'].mean(), 2)
                                        except Exception: pass
                                            
                                df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                                df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios).fillna("-")
                                df_matriz = df_matriz.drop(columns=['Placa_Match'])

                                if archivos_detallados:
                                    df_matriz = df_matriz[df_matriz['Promedio Vel. (km/h)'] != "-"]

                                if df_matriz.empty: 
                                    st.success("✅ La matriz quedó vacía tras la depuración. Ningún vehículo infractor cruzó datos con los archivos detallados.")
                                else:
                                    st.warning(f"⚠️ Se muestran {len(df_matriz)} vehículos en la matriz de infractores.")
                                    
                                    cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)']]
                                    styled_df = df_matriz.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                        
                                    st.download_button(
                                        label="📥 Descargar Reporte Final (PDF)", 
                                        data=generar_pdf_telemetria_matriz(df_matriz, limite_vel), 
                                        file_name=f"Auditoria_Velocidades_{get_hn_time().strftime('%Y%m%d')}.pdf", 
                                        mime="application/pdf", 
                                        use_container_width=True, 
                                        type="primary"
                                    )
                            else: st.error(f"❌ Error matriz principal: {msg_tel}")
                        except Exception as e: st.error(f"❌ Error de procesamiento: {e}")
        else: st.info("📱 La carga masiva está reservada para PC.")

    # --- PESTAÑA 3: MÉTRICA DE EFICIENCIA TOTAL ---
    with tab_eficiencia:
        col_e1, col_e2 = st.columns([4, 1])
        with col_e2: 
            if st.button("🔄 Refrescar", key="ref_e"): st.rerun()
            
        st.markdown("### ⚖️ Cruce de Productividad vs Tiempos GPS")
        st.caption("Calcula el porcentaje real de tiempo que el técnico estuvo produciendo mientras estaba en la calle.")
        st.info("💡 Sube tu archivo de Actividades y tus reportes de GPS para cruzarlos instantáneamente.")
        
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            archivo_act = st.file_uploader("1️⃣ Sube 'rep_actividades' (Órdenes)", type=['csv', 'xlsx', 'xls'], key="up_act_efi")
        with col_up2:
            archivos_detallados = st.file_uploader("2️⃣ Sube 'DetencionDetallado' (GPS)", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_detallado")
            
        if st.button("🚀 Calcular Eficiencia", use_container_width=True, type="primary"):
            
            df_base_local = None
            if archivo_act:
                df_base_local = read_file_robust(archivo_act)
                if df_base_local is not None:
                    cols_upper = {c: str(c).upper() for c in df_base_local.columns}
                    col_liq = next((c for c, up in cols_upper.items() if 'LIQUIDADO' in up or 'CIERRE' in up), None)
                    col_ini = next((c for c, up in cols_upper.items() if 'INICIO' in up or 'ENTRADA' in up), None)
                    col_tec = next((c for c, up in cols_upper.items() if 'TECNICO' in up or 'TÉCNICO' in up or 'USER' in up), None)
                    col_est = next((c for c, up in cols_upper.items() if 'ESTADO' in up or 'STATUS' in up), None)
                    col_num = next((c for c, up in cols_upper.items() if 'NUM' in up or 'ORDEN' in up or 'ID' in up), None)

                    if col_liq and col_ini and col_tec and col_est and col_num:
                        df_base_local = df_base_local.rename(columns={col_liq: 'HORA_LIQ', col_ini: 'HORA_INI', col_tec: 'TECNICO', col_est: 'ESTADO', col_num: 'NUM'})
            elif 'df_base' in st.session_state and st.session_state.df_base is not None:
                df_base_local = st.session_state.df_base

            if df_base_local is None: 
                st.error("❌ Faltan los datos de Actividades. Sube el archivo 'rep_actividades' en la caja 1.")
            elif not archivos_detallados:
                st.warning("⚠️ Sube al menos un archivo 'DetencionDetallado' del GPS en la caja 2.")
            else:
                with st.spinner("🧠 Procesando Inteligencia..."):
                    try:
                        df_gps_list = []
                        dict_ralenti_secs = {}
                        for file_det in archivos_detallados:
                            df_temp = read_file_robust(file_det)
                            if df_temp is not None and not df_temp.empty:
                                col_placa_temp = next((c for c in df_temp.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
                                if not col_placa_temp:
                                    for i in range(min(15, len(df_temp))):
                                        row_str = " ".join([str(x) for x in df_temp.iloc[i].values]).upper()
                                        if 'PLACA' in row_str or 'VEHICULO' in row_str or 'ALIAS' in row_str:
                                            df_temp.columns = [str(x).strip() for x in df_temp.iloc[i].values]
                                            from tools import forzar_columnas_unicas
                                            df_temp = forzar_columnas_unicas(df_temp)
                                            df_temp = df_temp.iloc[i+1:].reset_index(drop=True)
                                            break
                                df_gps_list.append(df_temp)
                                
                            file_det.seek(0)
                            lineas = file_det.getvalue().decode('utf-8', errors='ignore').splitlines()
                            if len(lineas) < 5: 
                                file_det.seek(0)
                                lineas = file_det.getvalue().decode('latin1', errors='ignore').splitlines()
                            for linea in lineas:
                                if "Tiempo de detencion con motor encendido" in linea:
                                    m = re.search(r'Placa:?\s*(.*?)(?:",|$)', linea)
                                    if m:
                                        p = m.group(1).replace('"', '').strip()
                                        t = linea.split(',')[-1].strip()
                                        if not t: t = linea.split(',')[-2].strip()
                                        dict_ralenti_secs[p] = dict_ralenti_secs.get(p, 0) + time_to_sec_robust(t)
                        
                        if df_gps_list:
                            res_diario, res_gps, msg_gps, f_in, f_out = procesar_auditoria_semanal(pd.concat(df_gps_list, ignore_index=True))
                            if res_gps is not None:
                                df_act = df_base_local.copy()
                                df_act['HORA_LIQ'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
                                df_act['HORA_INI'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
                                
                                df_act['Fecha_Ord'] = df_act['HORA_LIQ'].dt.date
                                df_act = df_act.dropna(subset=['Fecha_Ord'])
                                df_act = df_act[df_act['ESTADO'].astype(str).str.upper().str.contains('CERRADA', na=False)]
                                
                                df_act['Segundos_Prod'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds().clip(lower=0)
                                resumen_prod = df_act.groupby('TECNICO').agg(Ordenes=('NUM', 'count'), Seg_Prod=('Segundos_Prod', 'sum')).reset_index()
                                
                                def time_to_sec(t):
                                    parts = str(t).split(':')
                                    return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) if len(parts)==3 else 0
                                
                                res_gps['Seg_Calle'] = res_gps['Tiempo Total Semana'].apply(time_to_sec)
                                res_gps['Motor_Encendido_Secs'] = res_gps['Vehículo / Placa'].map(dict_ralenti_secs).fillna(0)
                                
                                def finding_placa(tec):
                                    if pd.isnull(tec): return None
                                    pt = str(tec).upper().replace(',', '').replace('.', '').split()
                                    required_matches = 2 if len(pt) >= 2 else 1
                                    
                                    for pl in res_gps['Vehículo / Placa']:
                                        pl_up = str(pl).upper()
                                        coincidencias = sum(1 for p in pt if len(p) > 2 and p in pl_up)
                                        if coincidencias >= required_matches: return pl
                                    return None
                                
                                resumen_prod['Placa_Match'] = resumen_prod['TECNICO'].apply(finding_placa)
                                df_final = pd.merge(resumen_prod, res_gps, left_on='Placa_Match', right_on='Vehículo / Placa', how='inner')
                                
                                if not df_final.empty:
                                    df_final['% Eficiencia'] = (df_final['Seg_Prod'] / df_final['Seg_Calle'] * 100).fillna(0).clip(upper=100)
                                    
                                    def sec_to_human(s):
                                        h, r = divmod(int(s), 3600); m, _ = divmod(r, 60)
                                        return f"{h:02d}h {m:02d}m"

                                    df_final['Trabajo (Órdenes)'] = df_final['Seg_Prod'].apply(sec_to_human)
                                    df_final['En Calle (GPS)'] = df_final['Seg_Calle'].apply(sec_to_human)
                                    df_final['Motor Encendido'] = df_final['Motor_Encendido_Secs'].apply(sec_to_human)
                                    
                                    st.success(f"✅ Cruce completado. Mostrando eficiencia para {len(df_final)} técnicos.")
                                    st.dataframe(df_final[['TECNICO', 'Ordenes', 'Trabajo (Órdenes)', 'En Calle (GPS)', '% Eficiencia', 'Motor Encendido']].style.format({'% Eficiencia': "{:.1f}%"}).map(
                                        lambda x: 'background-color: #2ea043; color: white' if x >= 65 else ('background-color: #d32f2f; color: white' if x < 40 else ''), subset=['% Eficiencia']
                                    ), use_container_width=True, hide_index=True)
                                else:
                                    st.warning("⚠️ No se encontraron técnicos que coincidan entre el archivo de Actividades y las placas del GPS.")
                            else:
                                st.error(f"❌ Error al procesar datos del GPS: {msg_gps}")
                        else:
                            st.error("❌ No se detectaron datos válidos en los archivos GPS subidos.")
                    except Exception as e: st.error(f"❌ Error interno en el cruce: {e}")

    # ==========================================================================
    # --- PESTAÑA 4: CHECKLIST INSPECCIÓN VEHICULAR ---
    # ==========================================================================
    with tab_checklist:
        st.markdown("### 📋 Gestión Documental de Flota (Google Cloud Storage)")
        st.caption("Descarga el formato físico, complétalo en campo y sube aquí el escáner firmado en PDF o Imagen.")
        
        # --- CALENDARIO ANUAL CON BOTÓN PEQUEÑO ---
        with st.expander("📅 Ver Calendario Anual de Inspecciones (2026-2027)", expanded=False):
            col_info, col_btn = st.columns([5, 1])
            with col_info:
                st.info("💡 Programación establecida a un ritmo de 2 revisiones por mes para mantener la operatividad.")
            with col_btn:
                try:
                    pdf_cal = generar_pdf_calendario()
                    st.download_button(
                        label="📥 Bajar PDF",
                        data=pdf_cal,
                        file_name="Calendario_Inspecciones_2026-2027.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                except Exception as e:
                    pass
            
            df_cal = pd.DataFrame(DATOS_CALENDARIO)
            st.dataframe(df_cal, use_container_width=True, hide_index=True)

        col_formato, col_upload = st.columns(2)
        
        with col_formato:
            st.markdown("#### 1️⃣ Obtener Formato Físico")
            st.info("Formato oficial de inspección vehicular con áreas de firma y lista de revisión corporativa.")
            try:
                pdf_blanco = generar_pdf_en_blanco()
                st.download_button(
                    label="📄 DESCARGAR PLANTILLA (PDF)",
                    data=pdf_blanco,
                    file_name="Formato_Inspeccion_MaxCom.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error generando plantilla: {e}")

        with col_upload:
            st.markdown("#### 2️⃣ Subir Documento Escaneado")
            with st.form("form_subida_escaner"):
                fecha_escaneo = st.date_input("Fecha de Inspección:", value=get_hn_time().date())
                placa_vehiculo = st.text_input("🚗 Placa del Vehículo:*", placeholder="Ej: HAA-1234")
                archivo_escaner = st.file_uploader("📥 Sube el Documento Escaneado (PDF o Imagen):", type=['pdf', 'png', 'jpg', 'jpeg'])
                observaciones = st.text_input("Notas / Hallazgos principales:", placeholder="Breve descripción del estado del vehículo...")
                
                supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
                submit_escaner = st.form_submit_button("💾 REGISTRAR Y ENVIAR AL BUCKET (GCS)", type="primary", use_container_width=True)

                if submit_escaner:
                    if not placa_vehiculo.strip():
                        st.error("⚠️ La placa es obligatoria para el registro.")
                    elif not archivo_escaner:
                        st.error("⚠️ Debes adjuntar el archivo escaneado (PDF o Imagen).")
                    else:
                        with st.spinner("Subiendo al almacenamiento seguro en la Nube (GCS)..."):
                            url_almacenada = None
                            error_mensaje = None
                            
                            buffer_archivo = io.BytesIO(archivo_escaner.getvalue())
                            nombre_archivo_gcs = f"{placa_vehiculo.strip().upper()}_{fecha_escaneo.strftime('%Y%m%d')}_{archivo_escaner.name}"
                            mimetype = "application/pdf" if archivo_escaner.name.lower().endswith('.pdf') else "image/jpeg"
                            
                            url_almacenada, error_mensaje = subir_archivo_gcs_pdf(buffer_archivo, nombre_archivo_gcs, mimetype)

                            if error_mensaje:
                                st.error(f"❌ FALLO DE SUBIDA: {error_mensaje}")
                                st.stop()

                            if url_almacenada:
                                try:
                                    df_historial = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                    if df_historial is None or df_historial.empty:
                                        try: df_historial = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                                        except: df_historial = pd.DataFrame()
                                            
                                    cols_registro = ['FECHA', 'PLACA', 'SUPERVISOR', 'OBSERVACIONES', 'ENLACE_ARCHIVO']
                                    nueva_fila = [
                                        fecha_escaneo.strftime("%d/%m/%Y"),
                                        placa_vehiculo.strip().upper(),
                                        supervisor_actual,
                                        observaciones,
                                        url_almacenada
                                    ]
                                    nuevo_df = pd.DataFrame([nueva_fila], columns=cols_registro)
                                    
                                    if df_historial is not None and not df_historial.empty:
                                        if len(df_historial.columns) > len(cols_registro):
                                            df_historial = df_historial.iloc[:, :len(cols_registro)]
                                        elif len(df_historial.columns) < len(cols_registro):
                                            for i in range(len(cols_registro) - len(df_historial.columns)):
                                                df_historial[f"Columna_Recuperada_{i}"] = ""
                                                
                                        df_historial.columns = cols_registro
                                        df_final = pd.concat([df_historial, nuevo_df], ignore_index=True)
                                    else:
                                        df_final = nuevo_df
                                        
                                    sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                    
                                    if conn:
                                        try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_final)
                                        except: pass
                                    
                                    st.success(f"✅ ¡Inspección de {placa_vehiculo.upper()} guardada y enlazada correctamente!")
                                except Exception as e:
                                    st.error(f"❌ Error al registrar en la matriz: {e}")

     st.markdown("---")
        st.markdown("#### 📜 Registro Maestro de Inspecciones Físicas")
        try:
            df_view_insp = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
            if df_view_insp is None or df_view_insp.empty:
                if conn: df_view_insp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
            
            if df_view_insp is not None and not df_view_insp.empty:
                
                # 1. DIBUJAR LOS ENCABEZADOS DE LA TABLA MANUAL
                cols_head = st.columns([1.5, 1.5, 1.5, 3, 0.7, 0.7, 0.7])
                cols_head[0].markdown("**FECHA**")
                cols_head[1].markdown("**PLACA**")
                cols_head[2].markdown("**SUPERVISOR**")
                cols_head[3].markdown("**OBSERVACIONES**")
                cols_head[4].markdown("**VER**")
                cols_head[5].markdown("**BAJAR**")
                cols_head[6].markdown("**BORRAR**")
                st.markdown("<hr style='margin: 0px; padding: 0px; margin-bottom: 10px;'>", unsafe_allow_html=True)
                
                # Invertimos para ver los más nuevos y limitamos a 50 para que la app no se vuelva lenta
                df_mostrar = df_view_insp.iloc[::-1].head(50)
                
                # 2. CONSTRUIR CADA FILA CON SUS PROPIOS BOTONES
                for idx, row in df_mostrar.iterrows():
                    cols = st.columns([1.5, 1.5, 1.5, 3, 0.7, 0.7, 0.7])
                    
                    cols[0].write(row.get('FECHA', ''))
                    cols[1].write(row.get('PLACA', ''))
                    cols[2].write(row.get('SUPERVISOR', ''))
                    cols[3].write(row.get('OBSERVACIONES', ''))
                    
                    enlace_doc = str(row.get('ENLACE_ARCHIVO', ''))
                    
                    # Botón Lupa (Abre el PDF en el navegador para verlo)
                    with cols[4]:
                        if enlace_doc.startswith("http"):
                            st.link_button("🔍", url=enlace_doc, use_container_width=True)
                            
                    # Botón Flecha (Abre el mismo enlace para guardarlo)
                    with cols[5]:
                        if enlace_doc.startswith("http"):
                            st.link_button("⬇️", url=enlace_doc, use_container_width=True)
                            
                    # Botón X (Elimina la fila directamente y recarga)
                    with cols[6]:
                        if st.button("❌", key=f"del_{idx}", type="primary", use_container_width=True):
                            with st.spinner("⏳"):
                                try:
                                    df_borrado = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                    if df_borrado is None or df_borrado.empty:
                                        df_borrado = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                                    
                                    # Si el índice existe, lo eliminamos
                                    if idx in df_borrado.index:
                                        df_borrado = df_borrado.drop(idx).reset_index(drop=True)
                                        
                                        # Guardamos la nueva tabla en la Nube
                                        sobrescribir_archivo_gcs(df_borrado, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                        
                                        # Guardamos el respaldo en Sheets
                                        if conn:
                                            try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_borrado)
                                            except: pass
                                            
                                    st.rerun() # Refrescamos la pantalla para que desaparezca
                                except Exception as e:
                                    st.error(f"Error: {e}")
                    
                    # Separador sutil entre filas
                    st.markdown("<hr style='margin: 0px; padding: 0px; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)
                    
                if len(df_view_insp) > 50:
                    st.caption("Mostrando los últimos 50 registros por motivos de rendimiento.")
                    
            else:
                st.info("Aún no hay escáneres vehiculares en la base de datos.")
        except Exception as e:
            st.warning("No se pudo cargar el registro en este momento.")
