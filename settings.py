import streamlit as st
import os
import tempfile

# --- IMPORTACIÓN BLINDADA PARA FPDF2 ---
try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

# ==============================================================================
# LÓGICA DE PDF PARA EL MANUAL TÉCNICO
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
        self.set_text_color(0, 51, 102) # Azul Corporativo
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 9)
        self.set_x(50)
        self.cell(0, 5, "Manual Técnico de Usuario - Monitor Operativo PRO", ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, 25, 200, 25)
        self.ln(15)
        
    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    def capitulo(self, titulo, texto_lineas):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(40, 50, 100)
        self.cell(0, 8, titulo, ln=True)
        self.ln(2)
        
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        for linea in texto_lineas:
            linea = linea.replace("* ", "- ") 
            self.multi_cell(0, 6, txt=linea)
        self.ln(6)

@st.cache_data(show_spinner=False)
def generar_manual_pdf():
    pdf = ManualPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # Título Principal
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, "MANUAL DE USUARIO: MONITOR OPERATIVO", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, "Este sistema ha sido diseñado para la supervisión en tiempo real de la operación técnica, la gestión de indicadores y la auditoría del personal de campo.")
    pdf.ln(8)
    
    # Capítulo 1
    pdf.capitulo("1. Acceso y Seguridad", [
        "Inicio de Sesión: Ingrese sus credenciales asignadas en la pantalla principal.",
        "Temporizador: Por seguridad, la sesión caduca tras 5 minutos de inactividad.",
        "Cierre de Sesión: Use el botón 'Cerrar Sesión' al final de la barra lateral para salir de forma segura y borrar sus cookies locales."
    ])
    
    # Capítulo 2
    pdf.capitulo("2. Monitor en Vivo", [
        "A. Indicadores (KPIs):",
        "- Pendientes Asignadas: Órdenes activas con técnico en ruta o sitio.",
        "- Cerradas Hoy: Total de liquidaciones exitosas del día.",
        "- Caídas (Offline): Equipos detectados con pérdida de señal en la red.",
        "",
        "B. Línea de Tiempo (Gantt):",
        "Muestra la secuencia de trabajo por técnico. Al pasar el cursor verá:",
        "- Actividad y Estado actual.",
        "- Horas exactas de inicio y cierre.",
        "- Tiempo Total de duración exacta de la gestión.",
        "",
        "C. Panel de Control (Alertas Visuales):",
        "- Fondo Rojo: Retrasos mayores o iguales a 7 días.",
        "- Fondo Naranja: Retraso de 4 a 6 días.",
        "- Icono de Alerta: Órdenes que exceden el tiempo estándar (ej. SOP > 2h)."
    ])
    
    # Capítulo 3
    pdf.capitulo("3. Centro de Reportes", [
        "Cierre Diario:",
        "Seleccione una fecha para generar el PDF con métricas de efectividad de mora.",
        "",
        "Resumen de Operaciones (6 Columnas):",
        "Este cuadro separa el avance real para un análisis profundo:",
        "1. Mora inicial: Pendientes arrastradas de días anteriores.",
        "2. Cerradas (Mora): Avance logrado sobre el arrastre.",
        "3. Total (Mora): Saldo pendiente antiguo que no se logró liquidar.",
        "4. Asignadas hoy: Nuevas entradas inyectadas durante el día.",
        "5. Cerradas hoy: Órdenes nuevas que fueron liquidadas el mismo día.",
        "6. Total (Hoy): Saldo total consolidado para el día siguiente."
    ])
    
    pdf.add_page()
    
    # Capítulo 4
    pdf.capitulo("4. Configuración y Conectividad", [
        "- Preferencias: Use los interruptores en la pestaña de configuración para limpiar su pantalla y ocultar los módulos que no necesita ver constantemente.",
        "- Sincronización: El botón 'Descargar Datos Ahora' asegura que está viendo la información más reciente desde la Nube (Google Cloud Storage).",
        "- Oracle (Beta): Módulo de conexión directa a la base de datos central en desarrollo."
    ])
    
    # Capítulo 5
    pdf.capitulo("5. Módulos de Auditoría", [
        "- Auditoría Vehicular: Compara la primera salida y la última llegada para calcular el tiempo real de los vehículos en la calle.",
        "- Biométrico: Analiza el archivo CSV de transacciones de recursos humanos para detectar tardanzas o excesos en tiempos de comida.",
        "- Tiempos Técnicos: Contrasta el tiempo pagado en calle vs el tiempo facturado en órdenes.",
        "- Expedientes: Gestor en la nube para registrar llamados de atención, incidencias médicas y adjuntar evidencia fotográfica."
    ])

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
        st.markdown("### 📖 Documentación Oficial del Sistema")
        st.write("El manual técnico de usuario detalla el funcionamiento de todos los módulos del sistema Maxcom PRO, incluyendo la interpretación de KPIs, el centro de reportes y las herramientas de auditoría.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_espacio, col_boton, col_espacio2 = st.columns([1, 2, 1])
        with col_boton:
            try:
                pdf_manual = generar_manual_pdf()
                st.download_button(
                    label="📥 DESCARGAR MANUAL TÉCNICO DE USUARIO (PDF)",
                    data=pdf_manual,
                    file_name="Manual_Usuario_MaxcomPRO.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error al generar el manual: {e}")
