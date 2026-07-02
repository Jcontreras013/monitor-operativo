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

# ==============================================================================
# 🛡️ LLAVE MAESTRA DE ADMINISTRADOR (SINCRONIZADA CON TU CONFIGURACIÓN DE ROLES)
# ==============================================================================
# Se fuerza 'rol_actual' en lugar de 'rol' para coincidir exactamente con tu main()
st.session_state['rol_actual'] = 'admin'
st.session_state['username'] = 'jaison'

from tools import (
    get_hn_time,
    read_file_robust,
    time_to_sec_robust,
    procesar_auditoria_vehiculos,
    procesar_auditoria_semanal,
    procesar_matriz_telemetria,
    generar_pdf_auditoria_tiempos,
    generar_pdf_semanal_tiempos,
    generar_pdf_telemetria_matriz,
    generar_pdf_gastos_vehiculo,
    generar_pdf_reporte_general_gastos
)

# ==============================================================================
# MOTOR DE ALMACENAMIENTO: CLOUD HOSTINGS GRATUITOS (GOFILE + TRANSFER.SH)
# ==============================================================================
try:
    from google.cloud import storage as gcs_storage
    from google.oauth2 import service_account
    GCS_DISPONIBLE = True
except ImportError:
    GCS_DISPONIBLE = False

try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# --- SUBIDA GRATUITA CON PRIORIDAD 1: GOFILE ---
def subir_pdf_gratis_gofile(file_buffer, file_name):
    """
    Sube un archivo de forma anónima y gratuita a GoFile.
    """
    try:
        res_server = requests.get("https://api.gofile.io/getServer", timeout=8)
        if res_server.status_code != 200:
            return None, "Servidor de GoFile no disponible."
        
        server_data = res_server.json()
        if server_data.get("status") != "success":
            return None, "Fallo al obtener servidor asignado."
            
        server_name = server_data["data"]["server"]
        upload_url = f"https://{server_name}.gofile.io/uploadFile"
        
        file_buffer.seek(0)
        files = {"file": (file_name, file_buffer.getvalue())}
        
        res_upload = requests.post(upload_url, files=files, timeout=25)
        if res_upload.status_code == 200:
            upload_data = res_upload.json()
            if upload_data.get("status") == "success":
                return upload_data["data"]["downloadPage"], None
            return None, f"GoFile reportó error: {upload_data.get('data')}"
        return None, f"Error HTTP {res_upload.status_code} en GoFile."
    except Exception as e:
        return None, f"Error de conexión en GoFile: {str(e)}"

# --- SUBIDA GRATUITA CON PRIORIDAD 2: TRANSFER.SH (RESPALDO AUTOMÁTICO) ---
def subir_pdf_gratis_transfersh(file_buffer, file_name):
    """
    Sube un archivo de forma anónima a Transfer.sh si GoFile presenta fallas.
    """
    try:
        safe_name = file_name.replace(" ", "_").replace("/", "-")
        url = f"https://transfer.sh/{safe_name}"
        file_buffer.seek(0)
        
        res_upload = requests.put(url, data=file_buffer.getvalue(), timeout=20)
        if res_upload.status_code == 200:
            return res_upload.text.strip(), None
        return None, f"Error HTTP {res_upload.status_code} en Transfer.sh."
    except Exception as e:
        return None, f"Error de conexión en Transfer.sh: {str(e)}"

def subir_documento_nube(file_buffer, file_name, mimetype):
    """
    Función unificada que prioriza el almacenamiento gratuito e instantáneo.
    Prueba GoFile en primera instancia y recurre a Transfer.sh si el primero falla.
    """
    # 1. Intentamos subir a GoFile
    enlace, err_gofile = subir_pdf_gratis_gofile(file_buffer, file_name)
    if enlace:
        return enlace, None
        
    # 2. Si falla GoFile, recurrimos a Transfer.sh automáticamente
    enlace_alt, err_transfer = subir_pdf_gratis_transfersh(file_buffer, file_name)
    if enlace_alt:
        return enlace_alt, None
        
    return None, f"No se pudo completar la subida (GoFile: {err_gofile} | Transfer.sh: {err_transfer})"

# ==============================================================================
# DATOS DEL CALENDARIO DE INSPECCIONES
# ==============================================================================
DATOS_CALENDARIO = [
    {"Año": 2026, "Mes": "Junio", "Quincena": "1ra", "Unidad": "MX-5", "Placa": "HED3834", "Descripción": "Kia K2700 cabina sencilla"},
    {"Año": 2026, "Mes": "Junio", "Quincena": "2da", "Unidad": "MX-14", "Placa": "HBB8594", "Descripción": "Mazda BT 50 cabina sencilla"},
    {"Año": 2026, "Mes": "Julio", "Quincena": "1ra", "Unidad": "MX-22", "Placa": "HDQ9370", "Descripción": "Kia Camion cabina sencilla"},
    {"Año": 2026, "Mes": "Julio", "Quincena": "2da", "Unidad": "MX-7", "Placa": "HED3852", "Descripción": "Suzuki APV panel busito"},
    {"Año": 2026, "Mes": "Agosto", "Quincena": "1ra", "Unidad": "MX-01", "Placa": "HDL 9821", "Descripción": "KIA Camión cabina sencilla Blanco"},
    {"Año": 2026, "Mes": "Agosto", "Quincena": "2da", "Unidad": "MX-02", "Placa": "HDP 9223", "Descripción": "KIA Camión cabina sencilla Blanco"},
    {"Año": 2026, "Mes": "Septiembre", "Quincena": "1ra", "Unidad": "MX-03", "Placa": "HBD 9507", "Descripción": "KIA Camión cabina sencilla Blanco"},
    {"Año": 2026, "Mes": "Septiembre", "Quincena": "2da", "Unidad": "MX-04", "Placa": "HAU 8203", "Descripción": "Camioncito KIA Doble cabina Blanco"},
    {"Año": 2026, "Mes": "Octubre", "Quincena": "1ra", "Unidad": "MX-06", "Placa": "HAE 1234", "Descripción": "KIA K2700 cabina sencilla Blanco"},
    {"Año": 2026, "Mes": "Octubre", "Quincena": "2da", "Unidad": "MX-08", "Placa": "HAB 9494", "Descripción": "Isuzu cabina sencilla Blanco"},
    {"Año": 2026, "Mes": "Noviembre", "Quincena": "1ra", "Unidad": "MX-09", "Placa": "HDU 5167", "Descripción": "Mazda BT-50 Gris"},
    {"Año": 2026, "Mes": "Noviembre", "Quincena": "2da", "Unidad": "MX-12", "Placa": "HAU 6095", "Descripción": "KIA Picanto Blanco"},
    {"Año": 2026, "Mes": "Diciembre", "Quincena": "1ra", "Unidad": "MX-14", "Placa": "HDA 9649", "Descripción": "Suzuki APV panel Blanco"},
    {"Año": 2026, "Mes": "Diciembre", "Quincena": "2da", "Unidad": "MX-15", "Placa": "HBJ 1317", "Descripción": "Suzuki APV panel Blanco"},
    {"Año": 2027, "Mes": "Enero", "Quincena": "1ra", "Unidad": "MX-16", "Placa": "HBJ 1307", "Descripción": "Suzuki APV panel Blanco"},
    {"Año": 2027, "Mes": "Enero", "Quincena": "2da", "Unidad": "MX-20", "Placa": "HBZ 0246", "Descripción": "Suzuki APV panel Blanco"}
]

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
        pdf.cell(25, 7, f"{row.get('Mes', '')} {row.get('Año', '')}", border=1, align="C")
        pdf.cell(20, 7, row.get('Quincena', ''), border=1, align="C")
        pdf.cell(20, 7, row.get('Unidad', ''), border=1, align="C")
        pdf.cell(25, 7, row.get('Placa', ''), border=1, align="C")
        desc_limpia = str(row.get('Descripción', '')).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(100, 7, desc_limpia, border=1, align="L", ln=True)

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

def mostrar_auditoria (es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("")
        st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad, tab_eficiencia, tab_checklist = st.tabs([
        "⏱️ Auditoría de Tiempos", 
        "🚀 Telemetría", 
        "⚖️ Gastos y Flota",
        "📋 Gestión Documental"
    ])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_t1, col_t2 = st.columns([4, 1])
        with col_t2: 
            if st.button("🔄 Refrescar", key="ref_t"): 
                if 'df_gps_memoria' in st.session_state: del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático"], horizontal=True)
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
                    with col_d1: st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), "Auditoria_Tiempos_Diario.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.error(f"❌ Error: {msg}")
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y procesando consolidado semanal..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.success(f"✅ Análisis Semanal completado.")
                    st.markdown("#### 📅 Desglose Diario por Vehículo")
                    st.dataframe(res_diario, use_container_width=True, hide_index=True)
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    col_s1, col_s2 = st.columns(2)
                    with col_s1: st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), "Auditoria_Tiempos_Semanal.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.warning(f"⚠️ {msg_sem}")

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
                                            
                                            placa_encontrada = next((str(p) for p in placas_validas if str(p) in raw_text or str(p) in file_det.name.upper()), None)
                                            if not placa_encontrada: continue 
                                            
                                            df_d = read_file_robust(file_det)
                                            header_idx = next((i for i in range(min(20, len(df_d))) if 'VELOCIDAD' in " ".join([str(x) for x in df_d.iloc[i].values]).upper() or 'KM/H' in " ".join([str(x) for x in df_d.iloc[i].values]).upper()), None)
                                            
                                            if header_idx is not None:
                                                df_d.columns = [str(x).strip().upper() for x in df_d.iloc[header_idx].values]
                                                from tools import forzar_columnas_unicas
                                                df_d = forzar_columnas_unicas(df_d).iloc[header_idx + 1:]
                                                col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|KM/H|SPEED', str(c), re.I)), None)
                                                if col_vel:
                                                    df_d['Vel_Num'] = df_d[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                                    df_excesos = df_d[df_d['Vel_Num'] > limite_vel]
                                                    if not df_excesos.empty: dict_promedios[placa_encontrada] = round(df_excesos['Vel_Num'].mean(), 2)
                                        except Exception: pass
                                            
                                df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                                df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios).fillna("-")
                                df_matriz = df_matriz.drop(columns=['Placa_Match'])

                                if archivos_detallados: df_matriz = df_matriz[df_matriz['Promedio Vel. (km/h)'] != "-"]

                                if df_matriz.empty: st.success("✅ La matriz quedó vacía tras la depuración.")
                                else:
                                    st.warning(f"⚠️ Se muestran {len(df_matriz)} vehículos en la matriz.")
                                    cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)']]
                                    styled_df = df_matriz.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                    st.download_button("📥 Descargar Reporte Final (PDF)", generar_pdf_telemetria_matriz(df_matriz, limite_vel), f"Auditoria_Velocidades.pdf", "application/pdf", use_container_width=True, type="primary")
                            else: st.error(f"❌ Error matriz principal: {msg_tel}")
                        except Exception as e: st.error(f"❌ Error de procesamiento: {e}")
        else: st.info("📱 La carga masiva está reservada para PC.")

    # --- PESTAÑA 3: GESTIÓN FINANCIERA ---
    with tab_eficiencia:
        st.markdown("### 🚙 Gestión Financiera de Flota (Gastos por Vehículo)")
        worksheet_gastos = "Gastos_Flota"
        
        if 'df_gastos_flota' not in st.session_state:
            if 'conn' in locals() and conn is not None:
                try: df_g = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, ttl=0)
                except Exception: df_g = pd.DataFrame(columns=["FECHA", "VEHICULO", "TIPO_GASTO", "DESCRIPCION", "MONTO", "COMPROBANTE"])
            else: df_g = pd.DataFrame(columns=["FECHA", "VEHICULO", "TIPO_GASTO", "DESCRIPCION", "MONTO", "COMPROBANTE"])
            if "COMPROBANTE" not in df_g.columns: df_g["COMPROBANTE"] = ""
            st.session_state['df_gastos_flota'] = df_g
        else: df_g = st.session_state['df_gastos_flota']

        vehiculos_base = [f"MX-{i}" for i in range(1, 41)]
        vehiculos_historicos = df_g['VEHICULO'].dropna().unique().tolist() if not df_g.empty else []
        lista_vehiculos = sorted(list(set(vehiculos_base + vehiculos_historicos)))

        st.markdown("---")
        col_gen1, col_gen2 = st.columns([1, 2])
        with col_gen1:
            if not df_g.empty:
                try:
                    df_g_pdf = df_g.copy()
                    if 'VEHICULO' in df_g_pdf.columns:
                        mapa_placas = {}
                        for v in DATOS_CALENDARIO:
                            mapa_placas[v['Unidad']] = f"{v['Unidad']} [{v['Placa']}]"
                            unidad_sin_cero = v['Unidad'].replace("MX-0", "MX-")
                            mapa_placas[unidad_sin_cero] = f"{v['Unidad']} [{v['Placa']}]"
                        
                        df_g_pdf['VEHICULO'] = df_g_pdf['VEHICULO'].apply(lambda x: mapa_placas.get(str(x).strip(), x))
                    
                    pdf_gen = generar_pdf_reporte_general_gastos(df_g_pdf)
                    st.download_button("📊 Descargar Reporte General Flota", pdf_gen, "Reporte_General_Flota.pdf", "application/pdf", use_container_width=True, type="primary")
                except Exception as e: 
                    st.error(f"Error PDF General: {e}")
        st.markdown("---")

        col_sel1, col_sel2 = st.columns(2)
        with col_sel1: vehiculo_seleccionado = st.selectbox("📌 Selecciona la Unidad a revisar:", ["-- Seleccione --"] + lista_vehiculos)
        with col_sel2: rango_fechas = st.date_input("📅 Filtrar Historial por Fechas:", value=[get_hn_time().date() - timedelta(days=30), get_hn_time().date()], key="filtro_rango_flota")
        st.markdown("---")

        if vehiculo_seleccionado != "-- Seleccione --":
            c1, c2 = st.columns([1.2, 2])
            with c1:
                st.markdown("#### 📝 Registrar Nuevo Gasto")
                with st.form("form_gasto"):
                    fecha_gasto = st.date_input("📅 Fecha de Factura", value=get_hn_time().date(), key="fecha_registro_factura")
                    tipo_gasto = st.selectbox("🏷️ Categoría", ["Combustible", "Mantenimiento / Taller", "Repuestos", "Lavado", "Multas", "Seguro", "Otro"])
                    desc_gasto = st.text_input("📝 Descripción (Ej: Fac #1234, Compra de Batería)")
                    monto_gasto = st.number_input("💵 Monto Total (L.)", min_value=0.0, format="%.2f", step=100.0)
                    archivo_comprobante = st.file_uploader("📎 Adjuntar Factura/Recibo (Opcional)", type=['pdf', 'png', 'jpg', 'jpeg'])
                    btn_guardar = st.form_submit_button("💾 Guardar Registro", use_container_width=True)
                    
                    if btn_guardar:
                        if desc_gasto.strip() and monto_gasto > 0:
                            url_archivo = ""
                            palabras_ignorar = {'para', 'como', 'factura', 'fac', 'cambio', 'pago', 'compra', 'reparacion', 'mantenimiento', 'gasolina', 'combustible', 'diesel', 'galones'}
                            palabras_clave = [p.lower() for p in re.findall(r'\b\w+\b', desc_gasto) if len(p) > 3 and p.lower() not in palabras_ignorar]
                            fecha_limite = pd.to_datetime(fecha_gasto) - pd.Timedelta(days=90)
                            df_reciente = df_g[(df_g['VEHICULO'] == vehiculo_seleccionado) & (pd.to_datetime(df_g['FECHA'], errors='coerce') >= fecha_limite)]
                            alerta_msg = None
                            for _, row_hist in df_reciente.iterrows():
                                desc_hist = str(row_hist['DESCRIPCION']).lower()
                                for palabra in palabras_clave:
                                    if palabra in desc_hist:
                                        alerta_msg = f"**ALERTA:** Hace menos de 3 meses (el {row_hist['FECHA']}) ya se registró algo similar: *'{row_hist['DESCRIPCION']}'*. Verifique."
                                        break
                                if alerta_msg: break
                            if alerta_msg: st.session_state['alerta_repuesto'] = alerta_msg

                            if archivo_comprobante:
                                with st.spinner("☁️ Subiendo comprobante a la nube..."):
                                    mimetype = "application/pdf" if archivo_comprobante.name.lower().endswith('.pdf') else "image/jpeg"
                                    nombre_file = f"FAC_{vehiculo_seleccionado}_{fecha_gasto.strftime('%Y%m%d')}_{archivo_comprobante.name}"
                                    url_archivo, err = subir_documento_nube(archivo_comprobante, nombre_file, mimetype)
                                    if err: st.error(err)

                            nuevo_registro = pd.DataFrame([{
                                "FECHA": pd.to_datetime(fecha_gasto).strftime('%Y-%m-%d'),
                                "VEHICULO": vehiculo_seleccionado,
                                "TIPO_GASTO": tipo_gasto,
                                "DESCRIPCION": desc_gasto,
                                "MONTO": float(monto_gasto),
                                "COMPROBANTE": url_archivo if url_archivo else ""
                            }])
                            df_g = pd.concat([df_g, nuevo_registro], ignore_index=True)
                            st.session_state['df_gastos_flota'] = df_g
                            
                            if 'conn' in locals() and conn is not None:
                                try:
                                    conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, data=df_g)
                                    st.success("✅ Guardado exitoso.")
                                except Exception as e: st.warning("⚠️ Guardado localmente.")
                            time.sleep(1.5)
                            st.rerun()
                        else: st.error("⚠️ Ingrese descripción y monto > 0.")

            with c2:
                st.markdown(f"#### 📊 Historial Financiero: {vehiculo_seleccionado}")
                if 'alerta_repuesto' in st.session_state:
                    st.error(st.session_state['alerta_repuesto'], icon="🚨")
                    del st.session_state['alerta_repuesto'] 
                
                df_filtro = df_g[df_g['VEHICULO'] == vehiculo_seleccionado].copy()
                if not df_filtro.empty:
                    df_filtro['FECHA_DT'] = pd.to_datetime(df_filtro['FECHA'], errors='coerce').dt.date
                    if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
                        df_filtro = df_filtro[(df_filtro['FECHA_DT'] >= rango_fechas[0]) & (df_filtro['FECHA_DT'] <= rango_fechas[1])]
                    elif isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 1:
                        df_filtro = df_filtro[df_filtro['FECHA_DT'] == rango_fechas[0]]
                    df_filtro = df_filtro.drop(columns=['FECHA_DT'])

                if not df_filtro.empty:
                    df_filtro['MONTO'] = pd.to_numeric(df_filtro['MONTO'], errors='coerce').fillna(0.0)
                    total_gastado = df_filtro['MONTO'].sum()
                    k1, k2 = st.columns(2)
                    k1.metric("🛒 Facturas", len(df_filtro))
                    k2.metric("💰 Total", f"L. {total_gastado:,.2f}")
                    
                    st.dataframe(
                        df_filtro.sort_values('FECHA', ascending=False),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "MONTO": st.column_config.NumberColumn("Monto", format="L. %.2f"), 
                            "COMPROBANTE": st.column_config.LinkColumn("📄 Comprobante", display_text="Ver Documento")
                        }
                    )
                    
                    try:
                        pdf_bytes = generar_pdf_gastos_vehiculo(df_filtro, vehiculo_seleccionado, rango_fechas, total_gastado)
                        st.download_button("📄 Bajar Reporte", pdf_bytes, f"Reporte_{vehiculo_seleccionado}.pdf", "application/pdf", use_container_width=True, type="secondary")
                    except Exception as e: pass
                        
                    # --- SINCRONIZACIÓN CON TU CLAVE DE SESIÓN 'rol_actual' ---
                    rol_actual = str(st.session_state.get("rol_actual", st.session_state.get("rol", ""))).strip().lower()
                    usuario_actual = str(st.session_state.get("username", "")).strip().lower()
                    
                    if rol_actual == "admin" or usuario_actual == "jaison": 
                        st.markdown("---")
                        with st.expander("🗑️ Zona Admin: Eliminar registro"):
                            opciones_borrar = {idx: f"ID: {idx} | {row['FECHA']} | {row['TIPO_GASTO']} | L. {row['MONTO']}" for idx, row in df_filtro.iterrows()}
                            if opciones_borrar:
                                registro_a_borrar = st.selectbox("Seleccionar:", options=list(opciones_borrar.keys()), format_func=lambda x: opciones_borrar[x])
                                if st.button("🚨 Confirmar Eliminación", type="primary"):
                                    df_g = df_g.drop(registro_a_borrar).reset_index(drop=True)
                                    st.session_state['df_gastos_flota'] = df_g
                                    if 'conn' in locals() and conn is not None:
                                        try:
                                            conn.clear(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos)
                                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, data=df_g)
                                            st.success("✅ Eliminado.")
                                        except Exception as e: st.error("Error nube.")
                                    time.sleep(1.5)
                                    st.rerun()
                else: st.info("No hay facturas registradas en estas fechas.")

    # --- PESTAÑA 4: GESTIÓN DOCUMENTAL ---
    with tab_checklist:
        st.markdown("### 📋 Gestión Documental de Flota")
        with st.expander("📅 Ver Calendario Anual de Inspecciones", expanded=False):
            st.info("💡 Programación de 2 revisiones por mes.")
            try: st.download_button("📥 Bajar PDF de Calendario", generar_pdf_calendario(), "Calendario_Inspecciones.pdf", "application/pdf")
            except: pass
            st.dataframe(pd.DataFrame(DATOS_CALENDARIO), use_container_width=True, hide_index=True)

        col_formato, col_upload = st.columns(2)
        with col_formato:
            st.markdown("#### 1️⃣ Obtener Formato Físico")
            try: st.download_button("📄 DESCARGAR PLANTILLA (PDF)", generar_pdf_en_blanco(), "Formato_Inspeccion.pdf", "application/pdf", use_container_width=True)
            except Exception as e: st.error(f"Error plantilla: {e}")

        with col_upload:
            st.markdown("#### 2️⃣ Subir Documento Escaneado")
            with st.form("form_subida_escaner"):
                fecha_escaneo = st.date_input("Fecha de Inspección:", value=get_hn_time().date(), key="fecha_escaner_doc")
                placa_vehiculo = st.text_input("🚗 Placa del Vehículo:*", placeholder="Ej: HAA-1234")
                archivo_escaner = st.file_uploader("📥 Sube Documento (PDF/Img):", type=['pdf', 'png', 'jpg', 'jpeg'])
                observaciones = st.text_input("Notas:", placeholder="Estado del vehículo...")
                submit_escaner = st.form_submit_button("💾 REGISTRAR Y SUBIR", type="primary", use_container_width=True)

                if submit_escaner:
                    if not placa_vehiculo.strip(): st.error("⚠️ Placa obligatoria.")
                    elif not archivo_escaner: st.error("⚠️ Sube el archivo.")
                    else:
                        with st.spinner("Subiendo a la nube..."):
                            buffer_archivo = io.BytesIO(archivo_escaner.getvalue())
                            nombre_archivo_drive = f"{placa_vehiculo.strip().upper()}_{fecha_escaneo.strftime('%Y%m%d')}_{archivo_escaner.name}"
                            mimetype = "application/pdf" if archivo_escaner.name.lower().endswith('.pdf') else "image/jpeg"
                            
                            url_almacenada, error_mensaje = subir_documento_nube(buffer_archivo, nombre_archivo_drive, mimetype) 
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
                                    nueva_fila = [fecha_escaneo.strftime("%d/%m/%Y"), placa_vehiculo.strip().upper(), st.session_state.get('username', 'Supervisor'), observaciones, url_almacenada]
                                    nuevo_df = pd.DataFrame([nueva_fila], columns=cols_registro)
                                    
                                    if df_historial is not None and not df_historial.empty:
                                        if len(df_historial.columns) > len(cols_registro): df_historial = df_historial.iloc[:, :len(cols_registro)]
                                        elif len(df_historial.columns) < len(cols_registro):
                                            for i in range(len(cols_registro) - len(df_historial.columns)): df_historial[f"Col_Rec_{i}"] = ""
                                        df_historial.columns = cols_registro
                                        df_final = pd.concat([df_historial, nuevo_df], ignore_index=True)
                                    else: df_final = nuevo_df
                                        
                                    try:
                                        sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                    except:
                                        pass # Continuamos si no hay GCS configurado
                                        
                                    if conn:
                                        try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_final)
                                        except: pass
                                    st.success("✅ Guardado y enlazado!")
                                except Exception as e: st.error(f"❌ Error base: {e}")

        st.markdown("---")
        st.markdown("#### 📜 Registro Maestro de Inspecciones Físicas")
        try:
            df_view_insp = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
            if df_view_insp is None or df_view_insp.empty:
                if conn: df_view_insp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
            
            if df_view_insp is not None and not df_view_insp.empty:
                # --- SINCRONIZACIÓN CON TU CLAVE DE SESIÓN 'rol_actual' ---
                rol_actual = str(st.session_state.get("rol_actual", st.session_state.get("rol", ""))).strip().lower()
                usuario_actual = str(st.session_state.get("username", "")).strip().lower()
                es_admin = (rol_actual == "admin" or usuario_actual == "jaison")

                # Ajustamos el ancho y número de columnas según los permisos del usuario
                if es_admin:
                    cols_head = st.columns([1.5, 1.5, 1.5, 3, 0.7, 0.7, 0.7])
                else:
                    cols_head = st.columns([1.5, 1.5, 1.5, 3, 1.0, 1.0])
                
                cols_head[0].markdown("**FECHA**")
                cols_head[1].markdown("**PLACA**")
                cols_head[2].markdown("**SUPERVISOR**")
                cols_head[3].markdown("**OBSERVACIONES**")
                cols_head[4].markdown("**VER**")
                cols_head[5].markdown("**BAJAR**")
                if es_admin:
                    cols_head[6].markdown("**BORRAR**")
                st.markdown("<hr style='margin: 0px; padding: 0px; margin-bottom: 10px;'>", unsafe_allow_html=True)
                
                df_mostrar = df_view_insp.iloc[::-1].head(50)
                for idx, row in df_mostrar.iterrows():
                    if es_admin:
                        cols = st.columns([1.5, 1.5, 1.5, 3, 0.7, 0.7, 0.7])
                    else:
                        cols = st.columns([1.5, 1.5, 1.5, 3, 1.0, 1.0])
                        
                    cols[0].write(row.get('FECHA', ''))
                    cols[1].write(row.get('PLACA', ''))
                    cols[2].write(row.get('SUPERVISOR', ''))
                    cols[3].write(row.get('OBSERVACIONES', ''))
                    enlace_doc = str(row.get('ENLACE_ARCHIVO', ''))
                    
                    with cols[4]:
                        if enlace_doc.startswith("http"): st.link_button("🔍", enlace_doc, use_container_width=True)
                    with cols[5]:
                        if enlace_doc.startswith("http"): st.link_button("⬇️", enlace_doc, use_container_width=True)
                        
                    # El botón de borrado solo se renderiza si el usuario es administrador
                    if es_admin:
                        with cols[6]:
                            if st.button("❌", key=f"del_insp_{idx}", type="primary", use_container_width=True):
                                with st.spinner("⏳"):
                                    try:
                                        df_borrado = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                        if df_borrado is None or df_borrado.empty: 
                                            df_borrado = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                                        if idx in df_borrado.index:
                                            df_borrado = df_borrado.drop(idx).reset_index(drop=True)
                                            try:
                                                sobrescribir_archivo_gcs(df_borrado, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                            except:
                                                pass
                                            if conn:
                                                try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_borrado)
                                                except: pass
                                        st.rerun()
                                    except Exception as e: st.error(f"Error: {e}")
                    st.markdown("<hr style='margin: 0px; padding: 0px; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)
            else: st.info("Aún no hay escáneres vehiculares.")
        except Exception: st.warning("No se pudo cargar el registro.")
