import streamlit as st
import os
import tempfile
import unicodedata
import pandas as pd  # <--- ¡ESTA ERA LA IMPORTACIÓN QUE HACÍA FALTA!

# --- IMPORTACIÓN BLINDADA PARA FPDF2 ---
try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

def safestr(texto):
    """Sanitiza el texto eliminando caracteres especiales que confunden a FPDF2."""
    if pd.isna(texto) or texto is None: 
        return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# LÓGICA DE PDF PARA EL MANUAL TÉCNICO ESTRUCTURADO
# ==============================================================================
class ManualPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try:
                self.image('logo.png', 10, 8, 33)
            except:
                pass
        self.set_y(10)
        self.set_x(50)
        self.set_text_color(0, 51, 102) # Azul Corporativo Maxcom
        self.set_font("Helvetica", "B", 12)
        self.cell(150, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 9)
        self.set_x(50)
        self.cell(150, 5, "Manual Tecnico Estructurado - Monitor Operativo PRO", ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, 25, 200, 25)
        self.ln(15)
        
    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

    def capitulo(self, titulo, subsecciones):
        """
        Escribe un bloque capitular estructurado.
        subsecciones: Diccionario de { Subtitulo: [Lineas de parrafo] }
        """
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(0, 51, 102)
        self.cell(190, 8, titulo, ln=True)
        self.ln(4)
        
        for sub_tit, lineas in subsecciones.items():
            if sub_tit:
                self.set_font("Helvetica", "B", 10)
                self.set_text_color(51, 65, 85)
                self.cell(190, 6, sub_tit, ln=True)
                self.ln(1)
            
            self.set_font("Helvetica", "", 9.5)
            self.set_text_color(40, 40, 40)
            for linea in lineas:
                linea_limpia = str(linea).replace("* ", "- ").replace("\t", " ").strip()
                self.multi_cell(190, 5.5, txt=linea_limpia)
            self.ln(3)
        self.ln(4)

@st.cache_data(show_spinner=False)
def generar_manual_pdf():
    pdf = ManualPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- PORTADA / TITULO ---
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(190, 10, "MANUAL TECNICO DE OPERACION Y SISTEMAS", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(190, 6, "Plataforma Centralizada Monitor Operativo Maxcom PRO", ln=True, align="C")
    pdf.ln(10)
    
    # --- CAPÍTULO 1 ---
    pdf.capitulo("1. PROTOCOLO DE ACCESO, SEGURIDAD Y SESION", {
        "A. Control de Autenticacion": [
            "* Acceso Restringido: El ingreso al sistema exige credenciales unicas validadas contra la lista de usuarios autorizados.",
            "* Roles de Usuario: Los perfiles se dividen en Administrador (Acceso total, edicion y eliminacion) y Monitoreo (Carga y visualizacion analitica)."
        ],
        "B. Politicas de Seguridad del Servidor": [
            "* Temporizador Inactivo: Como contingencia ante descuidos en estaciones de trabajo, la sesion expira automaticamente tras 5 minutos de inactividad detectada.",
            "* Cierre Seguro: El boton 'Cerrar Sesion' purga los tokens de seguridad y elimina las cookies activas en el navegador (token_maxcom) para evitar secuestros de sesion."
        ]
    })
    
    # --- CAPÍTULO 2 ---
    pdf.capitulo("2. ARQUITECTURA DEL MONITOR EN VIVO Y PANELES", {
        "A. Indicadores Operativos Clave (KPIs)": [
            "* Pendientes Asignadas: Cuantifica las ordenes en estado activo que ya cuentan con un tecnico asignado, en ruta o en sitio.",
            "* Cerradas Hoy: Despliega el total de ordenes que han sido liquidadas exitosamente en el transcurso del dia actual.",
            "* Caidas (Offline): Alertas criticas que muestran equipos con perdida total de potencia o enlace en la red."
        ],
        "B. Linea de Tiempo Dinamica (Gantt)": [
            "* Mapeo de Flujo Técnico: Grafica de forma cronologica la secuencia de actividades ejecutadas por cada tecnico de campo.",
            "* Interaccion Tooltip: Al pasar el cursor sobre los bloques de tiempo, el sistema extrae e imprime el estado de la orden, hora de apertura, hora de liquidacion y la duracion exacta calculada de la gestion."
        ],
        "C. Panel de Control y Semaforizacion de Alertas": [
            "* Alerta Critica (Fondo Rojo): Identifica ordenes con retraso acumulado igual o superior a 7 dias en la malla operativa.",
            "* Alerta Preventiva (Fondo Naranja): Destaca ordenes en el limbo con retrasos de 4 a 6 dias.",
            "* Exceso de Tiempo Estandar (Icono Alerta): Se activa dinamicamente si una tarea excede el tiempo promedio establecido para su rubro (Ej: Soporte de fibra > 2 horas)."
        ]
    })
    
    pdf.add_page()

    # --- CAPÍTULO 3 ---
    pdf.capitulo("3. ESTRUCTURA ANALITICA DEL CENTRO DE REPORTES", {
        "A. Cierre Diario de Efectividad": [
            "* Filtrado por Fecha: Permite seleccionar un dia especifico del calendario para empaquetar un archivo PDF exportable con las metricas completas de resolucion de mora."
        ],
        "B. Logica de la Matriz Operativa de 6 Columnas": [
            "Este cuadro desglosa matematicamente el balance diario para evitar duplicaciones:",
            "1. Mora Inicial: Saldo de ordenes pendientes que fueron arrastradas de dias anteriores.",
            "2. Cerradas (Mora): Cantidad de ordenes antiguas logradas liquidar durante la jornada.",
            "3. Total (Mora): Saldo real remanente de mora que pasara al siguiente dia.",
            "4. Asignadas Hoy: Ordenes nuevas capturadas e inyectadas en las ultimas 24 horas.",
            "5. Cerradas Hoy: Ordenes nuevas creadas hoy que se resolvieron el mismo dia.",
            "6. Total (Hoy): Balance final de ordenes del dia que quedan pendientes para manana."
        ]
    })
    
    # --- CAPÍTULO 4 ---
    pdf.capitulo("4. PREFERENCIAS, PERSISTENCIA Y ADAPTADORES DE BASE DE DATOS", {
        "A. Filtros Rápidos de Interfaz": [
            "* Control de Secciones: Permite al supervisor usar interruptores logicos para ocultar o mostrar bloques (Gantt, Graficas, Tablas) con el fin de optimizar el rendimiento en pantallas moviles."
        ],
        "B. Sincronizacion de Datos": [
            "* Boton 'Descargar Datos Ahora': Fuerza un llamado de lectura directo a la persistencia en la nube (Google Cloud Storage) sincronizando las ultimas modificaciones brutas procesadas."
        ],
        "C. Capa de Datos (GCS Principal & Sheets Contingencia)": [
            "* Persistencia Central (GCS): El motor lee y sobrescribe archivos compactados (.csv) en el Bucket del sistema para operaciones de alta velocidad.",
            "* Contingencia (Google Sheets): Actua como un espejo visual y respaldo. Si la conexion principal falla, el sistema se acopla a Sheets de inmediato para no detener la supervision.",
            "* Conector Oracle (Beta): Modulo de transicion directa para conectarse directamente al core de la base de datos central sin dependencias manuales."
        ]
    })

    # --- CAPÍTULO 5 ---
    pdf.capitulo("5. SINOPSIS DE MODULOS DE AUDITORIA", {
        "A. Auditoria Vehicular y Tiempos en Calle": [
            "* Cruza la primera lectura de salida GPS con la ultima entrada registrada del vehiculo para certificar el total de horas productivas en ruta."
        ],
        "B. Auditoria Biometrica (RRHH)": [
            "* Procesa las tramas de marcajes de los archivos de asistencia para contrastarlos con el catalogo oficial, detectando llegadas tarde, ausencias y tiempos de comida excedidos."
        ],
        "C. Control de Expedientes e Incidencias": [
            "* Modulo integrado para registrar llamados de atencion oficiales, faltas operativas e incidencias medicas de forma persistente en la nube, permitiendo adjuntar evidencias fotograficas y generar memorandums individuales en PDF.",
            "* Rubro Automatico RECO: Detecta palabras clave relacionadas con postes en las notas e inyecta de forma automatica y bloqueada el personal 'RECO' para simplificar los reportes generales."
        ]
    })

    # Guardar en memoria y retornar bytes
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# CONFIGURACIÓN DE LA INTERFAZ
# ==============================================================================
def inicializar_configuracion():
    """Inicializa los valores por defecto en la sesión si no existen."""
    if 'config_ver_filtros' not in st.session_state:
        st.session_state.config_ver_filtros = True
    if 'config_ver_tablero' not in st.session_state:
        st.session_state.config_ver_tablero = True
    if 'config_ver_consolidado' not in st.session_state:
        st.session_state.config_ver_consolidado = True
    if 'config_ver_gantt' not in st.session_state:
        st.session_state.config_ver_gantt = True
    if 'config_ver_panel' not in st.session_state:
        st.session_state.config_ver_panel = True

def mostrar_configuracion():
    st.title("⚙️ Configuración y Documentación")
    
    tab_conf, tab_doc = st.tabs(["🎛️ Preferencias de Interfaz", "📚 Manual de Usuario"])
    
    with tab_conf:
        st.subheader("Personalización del Monitor en Vivo")
        st.write("Apaga o enciende las secciones que deseas ver en tu pantalla principal.")
        
        st.session_state.config_ver_filtros = st.toggle("🔍 Mostrar: Filtros Rápidos", value=st.session_state.config_ver_filtros)
        st.session_state.config_ver_tablero = st.toggle("📊 Mostrar: Tablero de Carga Actual (Pendientes)", value=st.session_state.config_ver_tablero)
        st.session_state.config_ver_consolidado = st.toggle("📊 Mostrar: Consolidado por Segmento (Mora vs Al Día)", value=st.session_state.config_ver_consolidado)
        st.session_state.config_ver_gantt = st.toggle("⏳ Mostrar: Línea de Tiempo Operativa (Gantt)", value=st.session_state.config_ver_gantt)
        st.session_state.config_ver_panel = st.toggle("🎛️ Mostrar: Panel de Control y Análisis Detallado", value=st.session_state.config_ver_panel)

    with tab_doc:
        st.markdown("### 📖 Documentación Estructurada del Sistema")
        st.write("Presione el botón inferior para compilar y descargar el Manual Técnico Oficial. Este documento detalla todos los lineamientos operativos, la lógica del balance de 6 columnas de mora, la configuración de bases de datos y los módulos de auditoría integral.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_espacio, col_boton, col_espacio2 = st.columns([1, 2, 1])
        with col_boton:
            try:
                pdf_manual = generar_manual_pdf()
                st.download_button(
                    label="📥 DESCARGAR MANUAL TECNICO DE USUARIO (PDF)",
                    data=pdf_manual,
                    file_name="Manual_Tecnico_MaxcomPRO.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error al generar el manual estructurado: {e}")
