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
# IMPORTACIÓN DE FUNCIONES OPERATIVAS Y DE CONFIGURACIÓN DE TOOLS
# ==============================================================================
try:
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
except ImportError as e:
    st.error(f"⚠️ Error al importar herramientas de tools.py en auditorv.py: {e}")

# ==============================================================================
# MOTOR DE ALMACENAMIENTO: HOSTINGS INMUNES A BLOQUEOS (CATBOX + LITTERBOX)
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

# --- DETECCIÓN DE CREDENCIALES MULTIPLATAFORMA (Tolerante a Tildes y Espacios) ---
def obtener_credenciales_actuales():
    """
    Busca el rol y el usuario en session_state probando múltiples claves posibles,
    removiendo acentos (tildes), espacios en blanco y forzando minúsculas para robustez total.
    """
    def limpiar_texto(txt):
        if not txt:
            return ""
        s = str(txt).strip().lower()
        s = s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        return s

    rol = ""
    for clave in ['rol_actual', 'rol', 'rol_usuario', 'user_role', 'role']:
        if clave in st.session_state:
            val = st.session_state[clave]
            if val is not None:
                rol = limpiar_texto(val)
                break
                
    user = ""
    for clave in ['username', 'usuario', 'user', 'username_actual', 'nombre_usuario']:
        if clave in st.session_state:
            val = st.session_state[clave]
            if val is not None:
                user = limpiar_texto(val)
                break
                
    return rol, user

# --- AUXILIARES DE CONVERSIÓN SEGUROS ---
def safestr(val):
    """
    Convierte cualquier valor a string de forma segura con codificación latin-1.
    """
    if val is None or pd.isna(val):
        return ""
    return str(val).encode('latin-1', 'replace').decode('latin-1')

def normalizar_unidad(v_str):
    """
    Normaliza el nombre de un vehículo para poder realizar búsquedas cruzadas
    sin importar ceros a la izquierda, placas, espacios o guiones.
    """
    if not v_str or pd.isna(v_str):
        return ""
    clean = re.sub(r'\[.*?\]', '', str(v_str)).strip()
    clean = clean.upper().replace(" ", "").replace("-", "")
    match = re.search(r'MX0*(\d+)', clean)
    if match:
        return f"MX-{match.group(1)}"
    return clean

# --- SUBIDA GRATUITA CON PRIORIDAD 1: CATBOX (Almacenamiento Permanente) ---
def subir_pdf_gratis_catbox(file_buffer, file_name):
    """
    Sube un archivo de forma anónima y gratuita a Catbox.moe.
    Proporciona almacenamiento permanente de alta velocidad inmune a bloqueos de IP.
    """
    try:
        file_buffer.seek(0)
        files = {
            "fileToUpload": (file_name, file_buffer.getvalue())
        }
        data = {
            "reqtype": "fileupload",
            "userhash": ""
        }
        response = requests.post("https://catbox.moe/user/api.php", data=data, files=files, timeout=30)
        if response.status_code == 200:
            url = response.text.strip()
            if url.startswith("http"):
                return url, None
            return None, f"Catbox error: {url}"
        return None, f"Catbox HTTP {response.status_code}"
    except Exception as e:
        return None, f"Fallo al conectar con Catbox: {str(e)}"

# --- SUBIDA GRATUITA CON PRIORIDAD 2: LITTERBOX (Respaldo temporal por 72 horas) ---
def subir_pdf_gratis_litterbox(file_buffer, file_name):
    """
    Sube un archivo de forma temporal (duración de 72 horas) a Litterbox.
    """
    try:
        file_buffer.seek(0)
        files = {
            "fileToUpload": (file_name, file_buffer.getvalue())
        }
        data = {
            "reqtype": "fileupload",
            "time": "72h"
        }
        response = requests.post("https://litterbox.catbox.moe/resources/internals/api.php", data=data, files=files, timeout=30)
        if response.status_code == 200:
            url = response.text.strip()
            if url.startswith("http"):
                return url, None
            return None, f"Litterbox error: {url}"
        return None, f"Litterbox HTTP {response.status_code}"
    except Exception as e:
        return None, f"Fallo al conectar con Litterbox: {str(e)}"

def subir_documento_nube(file_buffer, file_name, mimetype):
    """
    Pasarela de subida gratuita. Intenta Catbox (almacenamiento permanente)
    y desvía automáticamente a Litterbox (72h) si ocurre algún problema.
    """
    enlace, err_catbox = subir_pdf_gratis_catbox(file_buffer, file_name)
    if enlace:
        return enlace, None
        
    enlace_alt, err_litter = subir_pdf_gratis_litterbox(file_buffer, file_name)
    if enlace_alt:
        return enlace_alt, None
        
    return None, f"No se pudo completar la subida (Catbox: {err_catbox} | Litterbox: {err_litter})"

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
    {"Año": 2026, "Mes": "Septiembre", "Quincena": "1ra", "Unidad": "MX-03", "Placa": "HBD 9507", "Descripción": "KIA Camión cabion sencilla Blanco"},
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

def mostrar_auditoria(es_movil=False, conn=None):
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
                if 'df_gps_memoria' in st.session_state: 
                    del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático"], horizontal=True)
        df_gps_crudo = None
        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, key="btn_tiempos_nube", type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando historial de la nube..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados de la nube correctamente.")
                    except Exception as e: 
                        st.error(f"❌ Error: {e}")
            else: 
                st.error("❌ No se detectó conexión a Google Sheets.")
                
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
                    except Exception as e: 
                        st.error(f"❌ Error al subir: {e}")
        else: 
            st.info("📱 El ingreso manual está deshabilitado en móviles.")

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
                        st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), "Auditoria_Tiempos_Diario.pdf", "application/pdf", use_container_width=True, type="primary")
                else: 
                    st.error(f"❌ Error: {msg}")
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y procesando consolidado semanal..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.success("✅ Análisis Semanal completado.")
                    st.markdown("#### 📅 Desglose Diario por Vehículo")
                    st.dataframe(res_diario, use_container_width=True, hide_index=True)
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    col_s1, col_s2 = st.columns(2)
                    with col_s1: 
                        st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), "Auditoria_Tiempos_Semanal.pdf", "application/pdf", use_container_width=True, type="primary")
                else: 
                    st.warning(f"⚠️ {msg_sem}")

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_v1, col_v2 = st.columns([4, 1])
        with col_v2: 
            if st.button("🔄 Refrescar", key="ref_v_telemetria"): 
                st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Telemetría")
        st.info("Sube el archivo Excel o CSV que contiene el reporte general de Flota, y opcionalmente los archivos de detalle por vehículo para extraer el promedio de velocidad (> 80 km/h).")
        
        limite_vel = st.number_input("🚨 Límite de Velocidad Permitido (km/h):", min_value=50.0, max_value=120.0, value=80.0, step=5.0)
        
        archivo_telemetria = st.file_uploader("📥 1. Arrastra el archivo Matriz General (Flota):", type=['csv', 'xlsx', 'xls'], key="up_tele_matriz")
        archivos_detallados = st.file_uploader("📂 2. Arrastra los archivos de detalle por vehículo (Opcional):", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_tele_detalles")
        
        if archivo_telemetria:
            with st.spinner("Procesando matriz general..."):
                df_matriz, msg_matriz = procesar_matriz_telemetria(archivo_telemetria)
                
                if df_matriz is not None:
                    st.success("✅ Matriz base cargada.")
                    col_placa_matriz = next((c for c in df_matriz.columns if 'PLACA' in str(c).upper() or 'VEHICULO' in str(c).upper() or 'UNIDAD' in str(c).upper()), None)
                    
                    if not col_placa_matriz:
                        st.error("❌ No se encontró la columna de Placa/Vehículo en la matriz principal.")
                    else:
                        dict_promedios = {}
                        if archivos_detallados:
                            with st.spinner("Escaneando archivos de detalle..."):
                                for arch_det in archivos_detallados:
                                    try:
                                        nombre_arch = str(arch_det.name).upper()
                                        placa_match = re.search(r'(MX-\d+|MX\d+|H[A-Z0-9]+)', nombre_arch)
                                        if not placa_match:
                                            continue
                                        placa_encontrada = placa_match.group(1).replace('MX0', 'MX-').replace('MX', 'MX-')
                                        if '--' in placa_encontrada: placa_encontrada = placa_encontrada.replace('--', '-')
                                        
                                        df_d = read_file_robust(arch_det)
                                        if df_d.empty:
                                            continue
                                            
                                        header_idx = next((i for i in range(min(20, len(df_d))) if 'VELOCIDAD' in " ".join([str(x) for x in df_d.iloc[i].values]).upper() or 'KM/H' in " ".join([str(x) for x in df_d.iloc[i].values]).upper()), None)
                                        if header_idx is not None:
                                            df_d.columns = [str(x).strip().upper() for x in df_d.iloc[header_idx].values]
                                            from tools import forzar_columnas_unicas
                                            df_d = forzar_columnas_unicas(df_d).iloc[header_idx + 1:]
                                            
                                        col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|KM/H|SPEED', str(c), re.I)), None)
                                        if col_vel:
                                            df_d['Vel_Num'] = df_d[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                            df_excesos = df_d[df_d['Vel_Num'] > limite_vel]
                                            if not df_excesos.empty:
                                                dict_promedios[placa_encontrada] = round(df_excesos['Vel_Num'].mean(), 2)
                                    except Exception:
                                        pass
                        
                        df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                        df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios).fillna("-")
                        df_matriz = df_matriz.drop(columns=['Placa_Match'])
                        
                        if archivos_detallados:
                            df_matriz = df_matriz[df_matriz['Promedio Vel. (km/h)'] != "-"]
                            if df_matriz.empty:
                                st.success("✅ La matriz quedó vacía tras la depuración.")
                            else:
                                st.warning(f"⚠️ Se muestran {len(df_matriz)} vehículos en la matriz.")
                        
                        cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)']]
                        styled_df = df_matriz.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                        st.dataframe(styled_df, hide_index=True, use_container_width=True)
                        st.download_button("📥 Descargar Reporte (PDF)", generar_pdf_telemetria_matriz(df_matriz), "Reporte_Telemetria.pdf", "application/pdf", use_container_width=True, type="primary")
                else:
                    st.error(f"❌ Error: {msg_matriz}")

    # --- PESTAÑA 3: GESTIÓN FINANCIERA ---
    with tab_eficiencia:
        st.markdown("### ⚖️ Control Financiero y Mantenimiento de Flota")
        worksheet_gastos = "Gastos_Flota"
        df_g = pd.DataFrame()
        
        if conn is not None:
            if 'df_gastos_flota' not in st.session_state:
                try:
                    df_g = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, ttl=0)
                    st.session_state['df_gastos_flota'] = df_g
                except Exception as e:
                    st.error(f"Error al conectar con BD Gastos: {e}")
            else:
                df_g = st.session_state['df_gastos_flota']
                
        # --- CONSTRUCCIÓN DINÁMICA DE LA LISTA DE VEHÍCULOS (CON COINCIDENCIA DE TU IMAGEN 3) ---
        vehiculos_oficiales = [
            'MX-1', 'MX-2', 'MX-3', 'MX-4', 'MX-5', 'MX-6', 'MX-7', 'MX-8', 'MX-9', 'MX-10', 
            'MX-12', 'MX-13', 'MX-14', 'MX-15', 'MX-16', 'MX-17', 'MX-18', 'MX-19', 'MX-20', 
            'MX-21', 'MX-22', 'MX-23', 'MX-24', 'MX-25', 'MX-26', 'MX-28', 'MX-30'
        ]
        vehiculos_calendario = [v['Unidad'] for v in DATOS_CALENDARIO]
        vehiculos_historicos = df_g['VEHICULO'].dropna().unique().tolist() if not df_g.empty else []
        
        # Consolidamos de forma estricta para evitar duplicados como MX-01 y MX-1
        set_vehiculos = set()
        for v in (vehiculos_oficiales + vehiculos_calendario + vehiculos_historicos):
            v_norm = normalizar_unidad(v)
            if v_norm:
                set_vehiculos.add(v_norm)

        def orden_numerico(v):
            num = re.search(r'\d+', str(v))
            if num: return int(num.group())
            return 999
            
        lista_vehiculos = sorted(list(set_vehiculos), key=orden_numerico)
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
                    st.download_button("📊 Descargar Reporte General Flota", pdf_gen, "Reporte_General_Flota.pdf", "application/pdf", use_container_width=True, type="primary", key="btn_download_gral")
                except Exception as e:
                    st.error(f"Error PDF General: {e}")
                    
        st.markdown("---")
        col_sel1, col_sel2 = st.columns(2)
        with col_sel1:
            vehiculo_seleccionado = st.selectbox("📌 Selecciona la Unidad a revisar:", ["-- Seleccione --"] + lista_vehiculos, key="sel_unidad_revisar")
        
        # --- FILTRO POR DEFECTO AJUSTADO A 365 DÍAS PARA EVITAR OCULTAR DATOS ---
        with col_sel2:
            rango_fechas = st.date_input("📅 Filtrar Historial por Fechas:", value=[get_hn_time().date() - timedelta(days=365), get_hn_time().date()], key="filtro_rango_flota")
            
        st.markdown("---")
        if vehiculo_seleccionado != "-- Seleccione --":
            c1, c2 = st.columns([1.2, 2])
            with c1:
                st.markdown("#### 📝 Registrar Nuevo Gasto")
                with st.form("form_gasto"):
                    fecha_gasto = st.date_input("📅 Fecha de Factura", value=get_hn_time().date(), key="fecha_registro_factura")
                    tipo_gasto = st.selectbox("🏷️ Categoría", ["Combustible", "Mantenimiento / Taller", "Repuestos", "Lavado", "Multas", "Seguro", "Otro"])
                    desc_gasto = st.text_input("📝 Descripción (Ej: Fac #1234, Compra de Batería)", key="txt_desc_gasto")
                    monto_gasto = st.number_input("💰 Monto Total (L.)", min_value=0.0, step=100.0, format="%.2f")
                    archivo_comprobante = st.file_uploader("📎 Subir Comprobante/Factura (Opcional)", type=['jpg', 'jpeg', 'png', 'pdf'])
                    submit_gasto = st.form_submit_button("💾 Guardar Gasto", type="primary")

                if submit_gasto:
                    if desc_gasto and monto_gasto > 0:
                        url_archivo = ""
                        if archivo_comprobante:
                            with st.spinner("Subiendo comprobante a la nube..."):
                                url_archivo, err = subir_documento_nube(archivo_comprobante, archivo_comprobante.name, archivo_comprobante.type)
                                if not url_archivo:
                                    st.warning(f"⚠️ No se pudo subir el archivo: {err}")
                        
                        nuevo_dict = {
                            "VEHICULO": vehiculo_seleccionado,
                            "FECHA": str(fecha_gasto),
                            "CATEGORIA": tipo_gasto,
                            "MONTO": float(monto_gasto),
                            "COMPROBANTE": url_archivo if url_archivo else ""
                        }
                        
                        # Escribimos el valor tanto en 'DESCRIPCION' como en 'DESCRIPCION.1'
                        for col in df_g.columns:
                            if 'DESCRIPCION' in col.upper():
                                nuevo_dict[col] = desc_gasto
                        if "DESCRIPCION" not in nuevo_dict:
                            nuevo_dict["DESCRIPCION"] = desc_gasto
                            
                        nuevo_registro = pd.DataFrame([nuevo_dict])
                        df_g = pd.concat([df_g, nuevo_registro], ignore_index=True)
                        st.session_state['df_gastos_flota'] = df_g
                        
                        if conn is not None:
                            try:
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, data=df_g)
                                st.success("✅ Guardado exitoso.")
                            except Exception as e:
                                st.warning("⚠️ Guardado localmente.")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("⚠️ Ingrese descripción y monto > 0.")
                        
            with c2:
                st.markdown(f"#### 📊 Historial Financiero: {vehiculo_seleccionado}")
                if 'alerta_repuesto' in st.session_state:
                    st.error(st.session_state['alerta_repuesto'], icon="🚨")
                    del st.session_state['alerta_repuesto']

                # --- FILTRO INTELIGENTE / NORMALIZADO DE UNIDAD ---
                df_filtro = pd.DataFrame()
                if not df_g.empty:
                    df_g_temp = df_g.copy()
                    df_g_temp['VEHICULO_NORM'] = df_g_temp['VEHICULO'].apply(normalizar_unidad)
                    vehiculo_norm = normalizar_unidad(vehiculo_seleccionado)
                    df_filtro = df_g_temp[df_g_temp['VEHICULO_NORM'] == vehiculo_norm].copy()
                    
                    if not df_filtro.empty:
                        df_filtro['FECHA_DT'] = pd.to_datetime(df_filtro['FECHA'], errors='coerce').dt.date
                        if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
                            df_filtro = df_filtro[(df_filtro['FECHA_DT'] >= rango_fechas[0]) & (df_filtro['FECHA_DT'] <= rango_fechas[1])]
                        elif isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 1:
                            df_filtro = df_filtro[df_filtro['FECHA_DT'] == rango_fechas[0]]
                        df_filtro = df_filtro.drop(columns=['FECHA_DT', 'VEHICULO_NORM'])

                if not df_filtro.empty:
                    # --- RESOLVER COLUMNAS DUPLICADAS DE DESCRIPCION PARA VISUALIZACIÓN ---
                    col_desc_real = 'DESCRIPCION'
                    for col in df_filtro.columns:
                        if 'DESCRIPCION.1' in col or 'DESCRIPCION_1' in col:
                            col_desc_real = col
                    df_filtro = df_filtro.rename(columns={col_desc_real: 'Descripción'})
                    
                    if 'COMPROBANTE' in df_filtro.columns:
                        df_filtro['COMPROBANTE'] = df_filtro['COMPROBANTE'].apply(lambda x: f"🔗 Ver" if str(x).startswith("http") else "")
                        
                    st.dataframe(df_filtro, hide_index=True, use_container_width=True)
                    st.metric("Total Gastos L.", f"{df_filtro['MONTO'].sum():,.2f}")
                    
                    try:
                        pdf_veh = generar_pdf_gastos_vehiculo(df_filtro, vehiculo_seleccionado)
                        st.download_button("📄 Bajar Reporte de Unidad", pdf_veh, f"Reporte_{vehiculo_seleccionado}.pdf", "application/pdf", use_container_width=True)
                    except Exception as e:
                        pass
                        
                    st.markdown("---")
                    st.markdown("#### 🗑️ Eliminar Registro de Gasto")
                    opciones_borrar = {i: f"{r['FECHA']} - L. {r['MONTO']} - {r.get('Descripción', 'N/D')}" for i, r in df_filtro.iterrows()}
                    
                    if opciones_borrar:
                        registro_a_borrar = st.selectbox("Seleccionar:", options=list(opciones_borrar.keys()), format_func=lambda x: opciones_borrar[x], key="sel_borrar_gasto")
                        
                        # --- REGLA DE SEGURIDAD PARA BORRADO FINANCIERO ---
                        rol_actual, usuario_actual = obtener_credenciales_actuales()
                        
                        # Permitir si es admin, o si es jefe y específicamente el usuario andres
                        puede_eliminar_gasto = (rol_actual == "admin" or usuario_actual == "jaison" or (rol_actual == "jefe" and usuario_actual == "andres"))
                        
                        if puede_eliminar_gasto:
                            if st.button("🚨 Confirmar Eliminación", type="primary", key="btn_confirmar_borrado_gasto"):
                                df_g = df_g.drop(registro_a_borrar).reset_index(drop=True)
                                st.session_state['df_gastos_flota'] = df_g
                                
                                if conn is not None:
                                    try:
                                        conn.clear(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos)
                                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet=worksheet_gastos, data=df_g)
                                        st.success("✅ Eliminado.")
                                    except Exception as e:
                                        st.error("Error nube.")
                                    
                                    time.sleep(1.5)
                                    st.rerun()
                        else:
                            st.info("🔒 Tu usuario no tiene privilegios para eliminar gastos de flota.")
                else:
                    st.info("No hay facturas registradas en estas fechas.")

    # --- PESTAÑA 4: GESTIÓN DOCUMENTAL ---
    with tab_checklist:
        st.markdown("### 📋 Gestión Documental de Flota")
        with st.expander("📅 Ver Calendario Anual de Inspecciones", expanded=False):
            st.info("💡 Programación de 2 revisiones por mes.")
            try:
                st.download_button("📥 Bajar PDF de Calendario", generar_pdf_calendario(), "Calendario_Inspecciones.pdf", "application/pdf", key="btn_down_cal")
            except:
                pass
            st.dataframe(pd.DataFrame(DATOS_CALENDARIO), use_container_width=True, hide_index=True)
            
        col_formato, col_upload = st.columns(2)
        with col_formato:
            st.markdown("#### 1️⃣ Obtener Formato Físico")
            try:
                st.download_button("📄 DESCARGAR PLANTILLA (PDF)", generar_pdf_en_blanco(), "Formato_Inspeccion.pdf", "application/pdf", use_container_width=True, key="btn_down_plantilla")
            except Exception as e:
                st.error(f"Error plantilla: {e}")
                
        with col_upload:
            st.markdown("#### 2️⃣ Subir Documento Escaneado")
            with st.form("form_subida_escaner"):
                fecha_escaneo = st.date_input("Fecha de Inspección:", value=get_hn_time().date(), key="fecha_escaner_doc")
                placa_vehiculo = st.text_input("🚗 Placa del Vehículo:*", placeholder="Ej: HAA-1234", key="placa_escaner_doc")
                supervisor_nombre = st.text_input("👤 Supervisor:", placeholder="Ej: Juan Perez", key="sup_escaner_doc")
                archivo_pdf_escaner = st.file_uploader("📥 Sube Documento (PDF/Img):", type=['pdf', 'jpg', 'jpeg', 'png'], key="up_escaner_doc")
                btn_subir_escaner = st.form_submit_button("☁️ Subir y Guardar Registro", type="primary")

            if btn_subir_escaner:
                if placa_vehiculo and archivo_pdf_escaner:
                    with st.spinner("Subiendo documento al servidor en la nube..."):
                        url_escaner, err_escaner = subir_documento_nube(archivo_pdf_escaner, archivo_pdf_escaner.name, archivo_pdf_escaner.type)
                        
                        if url_escaner:
                            try:
                                nuevo_registro_escaner = pd.DataFrame([{
                                    "FECHA": str(fecha_escaneo),
                                    "PLACA": placa_vehiculo.strip().upper(),
                                    "SUPERVISOR": supervisor_nombre.strip(),
                                    "ENLACE_DOCUMENTO": url_escaner,
                                    "FECHA_SUBIDA": get_hn_time().strftime("%Y-%m-%d %H:%M:%S")
                                }])
                                
                                df_escaneres = None
                                try:
                                    df_escaneres = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                except:
                                    pass
                                    
                                if df_escaneres is None or df_escaneres.empty:
                                    if conn is not None:
                                        try:
                                            df_escaneres = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                                        except:
                                            df_escaneres = pd.DataFrame()
                                else:
                                    df_escaneres = pd.DataFrame()

                                df_escaneres = pd.concat([df_escaneres, nuevo_registro_escaner], ignore_index=True)
                                
                                try:
                                    sobrescribir_archivo_gcs(df_escaneres, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                except:
                                    pass
                                    
                                if conn is not None:
                                    try:
                                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_escaneres)
                                        st.success("✅ Documento guardado exitosamente en Google Sheets y en la Nube.")
                                    except Exception as e:
                                        st.warning("⚠️ Guardado en la nube pero falló GSheets.")
                                else:
                                    st.success("✅ Guardado en la nube exitoso (sin GSheets).")
                                
                                time.sleep(2)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error interno al guardar: {e}")
                        else:
                            st.error(f"❌ No se pudo subir el archivo. {err_escaner}")
                else:
                    st.error("⚠️ La Placa y el Archivo son obligatorios.")

        st.markdown("---")
        st.markdown("### 🗂️ Historial de Inspecciones Escaneadas")
        col_filtro_doc, _ = st.columns([1, 2])
        with col_filtro_doc:
            buscar_placa = st.text_input("🔍 Filtrar por Placa:")
            
        with st.spinner("Cargando registro de la nube..."):
            try:
                df_view_insp = None
                try:
                    df_view_insp = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                except:
                    pass
                    
                if df_view_insp is None or df_view_insp.empty:
                    if conn is not None:
                        df_view_insp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                        
                if df_view_insp is not None and not df_view_insp.empty:
                    if buscar_placa:
                        df_view_insp = df_view_insp[df_view_insp['PLACA'].astype(str).str.contains(buscar_placa.upper(), na=False)]
                    
                    if not df_view_insp.empty:
                        # --- SINCRONIZACIÓN CON TU CLAVE DE SESIÓN 'rol_actual' ---
                        rol_actual, usuario_actual = obtener_credenciales_actuales()
                        
                        # --- REGLA DE SEGURIDAD ACTUALIZADA: ADMIN, JAISON, O JEFE SI ES ANDRES ---
                        es_admin = (
                            rol_actual == "admin" or
                            usuario_actual == "jaison" or
                            (rol_actual == "jefe" and usuario_actual == "andres")
                        )

                        # Ajustamos el ancho y número de columnas según los permisos del usuario
                        if es_admin:
                            cols_por_fila = 3
                        else:
                            cols_por_fila = 4
                            
                        cols_doc = st.columns(cols_por_fila)
                        col_idx = 0
                        
                        for idx, row in df_view_insp.iterrows():
                            with cols_doc[col_idx % cols_por_fila]:
                                st.markdown(f"**📝 Inspección: {safestr(row.get('PLACA', 'N/D'))}**")
                                st.caption(f"📅 Fecha: {safestr(row.get('FECHA', ''))}")
                                st.caption(f"👤 Sup: {safestr(row.get('SUPERVISOR', ''))}")
                                
                                link = safestr(row.get('ENLACE_DOCUMENTO', ''))
                                if str(link).startswith("http"):
                                    st.markdown(f"[🔗 Ver Documento Original]({link})")
                                else:
                                    st.warning("Sin enlace válido.")
                                    
                                if es_admin:
                                    if st.button("🗑️ Eliminar Documento", key=f"btn_del_doc_{idx}"):
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
                                                if conn is not None:
                                                    try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_borrado)
                                                    except: pass
                                                
                                            st.rerun()
                                        except Exception as e: st.error(f"Error: {e}")
                                else:
                                    st.info("🔒 Sin permisos para borrar.")
                                
                                st.markdown("<hr style='margin: 0px; padding: 0px; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)
                            col_idx += 1
                    else:
                        st.info("No se encontraron registros con esa placa.")
                else: 
                    st.info("Aún no hay escáneres vehiculares.")
            except Exception: 
                st.warning("No se pudo cargar el registro.")
