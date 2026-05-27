import streamlit as st
import os
import tempfile
import unicodedata
import pandas as pd

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
# LÓGICA DE RENDERING DE PDF: ESTILO LIBRO DE TEXTO ILUSTRADO
# ==============================================================================
class ManualEscolarPDF(FPDF):
    def header(self):
        # Encabezado estilo libro educativo
        self.set_y(8)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(100, 116, 139)
        self.cell(95, 5, "MAXCOM PRO - MANUAL DIDACTICO", align="L")
        self.cell(95, 5, "DEPARTAMENTO DE CONTROL OPERATIVO", align="R", ln=True)
        self.set_draw_color(226, 232, 240)
        self.line(10, 14, 200, 14)
        self.ln(10)
        
    def footer(self):
        # Pie de página con número e indicador de módulo
        self.set_y(-15)
        self.set_draw_color(226, 232, 240)
        self.line(10, 282, 200, 282)
        self.set_text_color(148, 163, 184)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()} | Aseguramiento de Calidad MaxCom", align="C")

    def titulo_modulo(self, numero, titulo):
        """Dibuja un banner capitular grande y colorido estilo libro escolar."""
        self.set_fill_color(15, 23, 42) # Fondo oscuro elegante
        self.rect(10, self.get_y(), 190, 14, style='F')
        self.set_x(14)
        self.set_y(self.get_y() + 2)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(255, 255, 255)
        self.cell(10, 10, f"{numero}.", align="L")
        self.set_font("Helvetica", "B", 11)
        self.cell(170, 10, safestr(titulo).upper(), align="L", ln=True)
        self.ln(8)

    def cuadro_nota(self, titulo_nota, lineas_texto, tipo="info"):
        """Dibuja un recuadro destacado de 'Sabías que...' o 'Importante'."""
        # Configurar colores según el tipo de nota educativa
        if tipo == "alerta":
            r_bg, g_bg, b_bg = 254, 242, 242
            r_bd, g_bd, b_bd = 239, 68, 68
        elif tipo == "success":
            r_bg, g_bg, b_bg = 240, 253, 250
            r_bd, g_bd, b_bd = 16, 185, 129
        else:
            r_bg, g_bg, b_bg = 240, 246, 255
            r_bd, g_bd, b_bd = 59, 130, 246

        ancho_cuadro = 190
        # --- CORRECCIÓN DE LA VARIABLE: lineas_texto en lugar de un nombre inexistente ---
        alto_estimado = 8 + (len(lineas_texto) * 5)
        
        # Verificar si cabe en la página actual
        if self.get_y() + alto_estimado > 270:
            self.add_page()

        y_inicial = self.get_y()
        self.set_fill_color(r_bg, g_bg, b_bg)
        self.rect(10, y_inicial, ancho_cuadro, alto_estimado, style='F')
        
        # Borde izquierdo grueso característico de los libros modernos
        self.set_draw_color(r_bd, g_bd, b_bd)
        self.set_linewidth(1.5)
        self.line(10, y_inicial, 10, y_inicial + alto_estimado)
        self.set_linewidth(0.2) # Restaurar línea normal

        self.set_x(14)
        self.set_y(y_inicial + 2)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(r_bd, g_bd, b_bd)
        self.cell(0, 5, f"[!] {safestr(titulo_nota).upper()}", ln=True)
        
        self.set_font("Helvetica", "", 9)
        self.set_text_color(51, 65, 85)
        for lin in lineas_texto:
            self.set_x(14)
            self.multi_cell(182, 4.5, txt=safestr(lin))
        self.ln(6)

    # ==========================================================================
    # ILUSTRACIONES VECTORIALES (IMÁGENES PROGRAMÁTICAS)
    # ==========================================================================
    def dibujar_figura_seguridad(self):
        """FIGURA 1: Diagrama de flujo del ciclo de autenticación y cookies."""
        if self.get_y() + 25 > 270: self.add_page()
        y = self.get_y() + 2
        
        # Caja 1: Login
        self.set_fill_color(241, 245, 249); self.set_draw_color(148, 163, 184)
        self.rect(15, y, 45, 12, style='FD')
        self.set_font("Helvetica", "B", 8); self.set_text_color(15, 23, 42)
        self.text(20, y + 7, "1. Normaliza Login")
        
        # Flecha 1
        self.line(60, y + 6, 75, y + 6); self.line(72, y + 4, 75, y + 6); self.line(72, y + 8, 75, y + 6)
        
        # Caja 2: Cookie
        self.rect(75, y, 50, 12, style='FD')
        self.text(78, y + 7, "2. Inyecta Cookie Token")
        
        # Flecha 2
        self.line(125, y + 6, 140, y + 6); self.line(137, y + 4, 140, y + 6); self.line(137, y + 8, 140, y + 6)
        
        # Caja 3: Timer
        self.set_fill_color(254, 242, 242); self.set_draw_color(239, 68, 68)
        self.rect(140, y, 45, 12, style='FD')
        self.set_text_color(185, 28, 28)
        self.text(143, y + 7, "3. Alerta Regla 30 Min")
        
        # Epígrafe escolar
        self.set_y(y + 15)
        self.set_font("Helvetica", "I", 8); self.set_text_color(100, 116, 139)
        self.cell(190, 5, "Figura 1.1: Diagrama logico secuencial de la persistencia y proteccion de sesion activa.", align="C", ln=True)
        self.ln(4)

    def dibujar_figura_pipeline(self):
        """FIGURA 2: Pipeline de Ingeniería de Datos (Limpieza de crudos)."""
        if self.get_y() + 32 > 270: self.add_page()
        y = self.get_y() + 2
        
        # Caja de entrada
        self.set_fill_color(239, 246, 255); self.set_draw_color(59, 130, 246)
        self.rect(12, y, 32, 18, style='FD')
        self.set_font("Helvetica", "B", 8); self.set_text_color(29, 78, 216)
        self.text(14, y + 8, "Archivo Crudo")
        self.set_font("Helvetica", "", 7)
        self.text(14, y + 14, "(Excel o CSV)")
        
        # Filtro Central
        self.set_fill_color(241, 245, 249); self.set_draw_color(71, 85, 105)
        self.rect(55, y - 2, 90, 22, style='FD')
        self.set_font("Helvetica", "B", 8); self.set_text_color(15, 23, 42)
        self.text(58, y + 4, "PROCESAMIENTO TRANSPARENTE ENGINE:")
        self.set_font("Helvetica", "", 7.5); self.set_text_color(51, 65, 85)
        self.text(58, y + 10, "- Purga automatica de Actividades Basura (Lista Negra)")
        self.text(58, y + 14, "- Filtro anti-duplicados por columna [NUM] (keep='last')")
        self.text(58, y + 18, "- Conversion automatica a diferencias MINUTOS_CALC")
        
        # Conexiones
        self.line(44, y + 9, 55, y + 9)
        self.line(145, y + 9, 156, y + 9)
        
        # Caja de salida
        self.set_fill_color(240, 253, 250); self.set_draw_color(16, 185, 129)
        self.rect(156, y, 32, 18, style='FD')
        self.set_font("Helvetica", "B", 8); self.set_text_color(4, 120, 87)
        self.text(158, y + 8, "Estructura")
        self.set_font("Helvetica", "", 7)
        self.text(158, y + 14, "Listo en Memoria")
        
        self.set_y(y + 23)
        self.set_font("Helvetica", "I", 8); self.set_text_color(100, 116, 139)
        self.cell(190, 5, "Figura 2.1: Esquema de refinamiento y transformacion del Pipeline de Datos interno.", align="C", ln=True)
        self.ln(4)

    def dibujar_figura_balance(self):
        """FIGURA 3: Gráfica conceptual de la balanza de tiempos."""
        if self.get_y() + 25 > 270: self.add_page()
        y = self.get_y() + 2
        
        self.set_draw_color(148, 163, 184)
        self.line(40, y + 12, 160, y + 12) # Eje central
        self.line(100, y + 12, 100, y + 16) # Soporte
        
        # Plato Izquierdo (Verde)
        self.set_fill_color(209, 250, 229); self.set_draw_color(16, 185, 129)
        self.rect(40, y, 45, 8, style='FD')
        self.set_font("Helvetica", "B", 7); self.set_text_color(4, 120, 87)
        self.text(43, y + 5, "Signo (+): PAUSAS REALES")
        
        # Plato Derecho (Rojo)
        self.set_fill_color(254, 226, 226); self.set_draw_color(239, 68, 68)
        self.rect(115, y, 45, 8, style='FD')
        self.set_text_color(185, 28, 28)
        self.text(117, y + 5, "Signo (-): MINUTOS FANTASMA")
        
        self.set_y(y + 17)
        self.set_font("Helvetica", "I", 8); self.set_text_color(100, 116, 139)
        self.cell(190, 5, "Figura 3.1: Representacion de la Metrica Balance (Tiempo Muerto en PDF vs Pausas Manuales).", align="C", ln=True)
        self.ln(4)

    def dibujar_figura_dashboard(self):
        """FIGURA 4: Cuadrícula analítica 2x2 simulada."""
        if self.get_y() + 38 > 270: self.add_page()
        y = self.get_y() + 2
        
        self.set_draw_color(203, 213, 225)
        # Cuadrante 1
        self.set_fill_color(255, 255, 255); self.rect(15, y, 80, 14, style='FD')
        self.set_font("Helvetica", "B", 7); self.set_text_color(15, 23, 42)
        self.text(18, y + 5, "Cuadrante 1: REINCIDENTES CRITICOS")
        self.set_fill_color(239, 68, 68); self.rect(18, y + 8, 45, 3, style='F') # simulación barra
        
        # Cuadrante 2
        self.set_fill_color(255, 255, 255); self.rect(105, y, 80, 14, style='FD')
        self.text(108, y + 5, "Cuadrante 2: FRECUENCIA POR DIA")
        self.set_fill_color(245, 158, 11); self.rect(108, y + 8, 30, 3, style='F')
        
        # Cuadrante 3
        self.set_fill_color(255, 255, 255); self.rect(15, y + 18, 80, 14, style='FD')
        self.text(18, y + 23, "Cuadrante 3: CATEGORIAS (GPS, BIOM...)")
        self.set_fill_color(59, 130, 246); self.rect(18, y + 26, 60, 3, style='F')
        
        # Cuadrante 4
        self.set_fill_color(255, 255, 255); self.rect(105, y + 18, 80, 14, style='FD')
        self.text(108, y + 23, "Cuadrante 4: PORCENTAJES DE ACCION")
        self.set_fill_color(16, 185, 129); self.rect(108, y + 26, 20, 3, style='F')
        
        self.set_y(y + 34)
        self.set_font("Helvetica", "I", 8); self.set_text_color(100, 116, 139)
        self.cell(190, 5, "Figura 5.1: Mapeo y distribucion matricial del Panel de Analitica de Personal de campo.", align="C", ln=True)
        self.ln(4)

# ==============================================================================
# COMPILACIÓN GENERAL DEL CONTENIDO COMPLETO DEL MANUAL
# ==============================================================================
@st.cache_data(show_spinner=False)
def generar_manual_pdf():
    pdf = ManualEscolarPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- TÍTULO DE PORTADA ---
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(190, 10, "MANUAL DE USUARIO INTEGRAL (MAXCOM PRO)", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(190, 5, "Guia Visual de Operaciones, Modulos de Auditoria y Control Gerencial", ln=True, align="C")
    pdf.ln(8)
    
    # ==========================================================================
    # SECCIÓN 1: CONTROL DE ACCESO
    # ==========================================================================
    pdf.titulo_modulo("1", "Control de Acceso, Sesiones y Roles (login.py)")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(51, 65, 85)
    pdf.multi_cell(190, 5, txt=safestr("El acceso a la plataforma esta protegido por un motor de autenticacion descentralizado que aisla las variables de memoria por cada usuario para evitar cruces de informacion, apoyado en un sistema de persistencia por cookies locales (token_maxcom)."))
    pdf.ln(2)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "1.1 Ciclo de Autenticacion y Temporizador de Seguridad", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("- Validacion de Credenciales: Al ingresar al sistema, el software normaliza el nombre de usuario (remueve espacios y fuerza minusculas) y valida la contrasena frente a los registros de seguridad autorizados."))
    pdf.multi_cell(190, 5, txt=safestr("- Persistencia por Cookies: Si las credenciales son correctas, el sistema inyecta un token encriptado temporal en el navegador web del dispositivo (computadora o celular). Este almacena marca de tiempo, usuario y rol."))
    pdf.multi_cell(190, 5, txt=safestr("- Expiracion Automatica (Regla de los 30 Minutos): Por politicas de seguridad de datos, cada vez que interactuas con el sistema o recargas la pagina, el software mide la diferencia de tiempo frente a tu ultima accion. Si transcurren mas de 30 minutos de inactividad, la sesion se destruye automaticamente por seguridad."))
    pdf.multi_cell(190, 5, txt=safestr("- Cierre de Sesion: Ubicado en la parte inferior de la barra lateral, el boton Cerrar Sesion borra de inmediato el token del navegador y limpia el estado de ejecucion (st.session_state)."))
    pdf.ln(2)

    # Inyección de Imagen 1
    pdf.dibujar_figura_seguridad()

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "1.2 Matriz Operativa de Roles y Privilegios", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("- ADMIN: Posee control total sobre la plataforma. Puede visualizar pantallas criticas, procesar cargas maestras, configurar conexiones a bases de datos en Oracle y es el unico autorizado para ejecutar la eliminacion permanente de registros desde la nube."))
    pdf.multi_cell(190, 5, txt=safestr("- JEFE: Rol intermedio enfocado en la supervision de campo. Cuenta con permisos de escritura y carga de reportes diarios (Actividades/Mozart), generacion de memorandums en PDF y acceso al panel analitico, sin eliminacion historica."))
    pdf.multi_cell(190, 5, txt=safestr("- MONITOREO: Rol operativo de lectura y auditoria. Puede revisar la linea de tiempo en vivo, consultar el historial de expedientes y descargar reportes corporativos consolidacion en PDF. Cargas o borrados permanecen invisibles."))
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 2: MONITOR EN VIVO
    # ==========================================================================
    pdf.titulo_modulo("2", "Monitor en Vivo y Cronograma Operativo (app.py)")
    pdf.multi_cell(190, 5, txt=safestr("Este modulo procesa la actividad viva de la calle para estructurar las jornadas de los tecnicos y auxiliares, mapeando la efectividad del despacho diario."))
    pdf.ln(2)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "2.1 Flujo Correcto de Ingesta y Depuracion de Datos", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("1. Dirigete a la opcion Monitor en Vivo en la barra de navegacion lateral."))
    pdf.multi_cell(190, 5, txt=safestr("2. Si posees rol Admin o Jefe, se desplegara el contenedor de carga de archivos Excel (.xlsx) o CSV."))
    pdf.multi_cell(190, 5, txt=safestr("3. Procesamiento: El motor de limpieza realiza de forma transparente las siguientes acciones:"))
    
    pdf.cuadro_nota("Reglas de Depuracion en Carga", [
        "1. Filtrado de Actividades Basura: Remueve automaticamente todas las filas cuyas etiquetas pertenezcan a la lista negra interna del departamento (REVISION DE VEHICULO, CHECK IN, ALMUERZO, etc.).",
        "2. Unificacion por Clave Unica: Limpia ordenes duplicadas utilizando la columna NUM (Numero de Orden), preservando exclusivamente la ultima interacción registrada (keep='last') para reflejar el estado real de campo.",
        "3. Conversion de Tiempos: Traduce las horas crudas en diferencias de minutos exactos (MINUTOS_CALC) y genera la etiqueta visual TIEMPO_REAL."
    ], tipo="info")

    pdf.dibujar_figura_pipeline()

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "2.2 Visualizacion de la Linea de Tiempo de Gantt", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("- Interpretacion: La grafica de Gantt (Plotly Dark) grafica horizontalmente el inicio, progreso y finalizacion de cada trabajo asignado, agrupado por el nombre de cada tecnico."))
    pdf.multi_cell(190, 5, txt=safestr("- Detection de Anomalias: Permite identificar visualmente solapamientos (dos ordenes ejecutadas al mismo tiempo por la misma cuadrilla) o tiempos muertos excesivos entre liquidacion y aperturas."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "2.3 Uso de Ventanas Emergentes Interactivas (ui_components.py)", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("Al hacer clic sobre los registros de la tabla de control, la interfaz desplegara cuadros de dialogo flotantes (st.dialog):"))
    pdf.multi_cell(190, 5, txt=safestr("- Detalle de Gestion de la Orden: Muestra la informacion tecnica completa del cliente (Direccion, Telefono, Tipo de Tecnologia HFC/FTTH, Nodo) junto con el comentario exacto escrito por el tecnico."))
    pdf.multi_cell(190, 5, txt=safestr("- Seguimientos en Curso: Si la cuadrilla ha reportado avances intermedios sin liquidar, este panel listara cronologicamente cada comentario de progreso ingresado."))
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 3: EVALUACIÓN POR PUNTOS
    # ==========================================================================
    pdf.titulo_modulo("3", "Evaluación de Producción por Puntos (tecnicos.py)")
    pdf.multi_cell(190, 5, txt=safestr("Herramienta gerencial de auditoria orientada a medir si el volumen de trabajo ejecutado por cada colaborador cumple con los estandares minimos aceptables de produccion establecidos por MaxCom mediante el calculo de scores diarios."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "3.1 Carga del Reporte Maestro 'Mozart'", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("1. Selecciona la opcion de evaluacion de tecnicos."))
    pdf.multi_cell(190, 5, txt=safestr("2. Establece el rango de fechas que deseas auditar mediante el selector de calendario 'Periodo de evaluacion' (por defecto carga desde el primer dia del mes actual)."))
    pdf.multi_cell(190, 5, txt=safestr("3. En el cargador de archivos, sube el archivo maestro de registros extraido del sistema (denominado Mozart)."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "3.2 Procesamiento del Score de Rendimiento", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("Al presionar el boton Calcular Rendimiento, el algoritmo realiza un cruce de datos masivo: normaliza gramaticalmente los nombres de los tecnicos, cruza la base cargada contra la lista del personal en la nube (df_base), asignando pesos establecidos (1 pto Fibra Normal, 2 ptos Cambios de Fibra, 2.5 Inst.)."))
    pdf.multi_cell(190, 5, txt=safestr("- Resultados en Pantalla: Genera una tabla ejecutiva que detalla: Nombre del Colaborador, Cantidad de Ordenes Finalizadas, Puntos Acumulados Totales y el Porcentaje de Efectividad Operativa."))
    pdf.multi_cell(190, 5, txt=safestr("- Exportacion: Al final de la tabla dispones de botones para descargar el reporte en formato Excel o exportar un reporte PDF oficial para RRHH."))
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 4: AUDITORÍA DE TIEMPOS MUERTOS
    # ==========================================================================
    pdf.titulo_modulo("4", "Auditoría de Tiempos Muertos y Eficiencia (tiempot.py)")
    pdf.multi_cell(190, 5, txt=safestr("Este modulo gerencial avanzado tiene como proposito cruzar los tiempos de inactividad calculados por el sistema de despacho automatizado frente a las pausas que los tecnicos reportaron manualmente en sus hojas de ruta."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "4.1 Carga Combinada de Insumos", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("1. Reporte de Pausas (Excel/CSV): Listado extraido donde los tecnicos registran paradas justificadas (Ej: ponchadura de llanta, lluvia masiva, soporte de IT)."))
    pdf.multi_cell(190, 5, txt=safestr("2. PDF de Eficiencia: Archivo oficial de metricas. El sistema utiliza la libreria PyMuPDF (fitz) para leer el texto crudo del PDF internamente en memoria RAM, extrayendo las tablas mediante reconocimiento de patrones."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "4.2 Interpretacion del 'Balance de Tiempos'", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("El software empareja los nombres normalizados de ambas fuentes y calcula la formula: Balance = Tiempo Muerto (Calculado en PDF) - Pausas Reportadas manualmente."))
    
    pdf.cuadro_nota("Reglas de Evaluacion de Balances", [
        "Balance Positivo Verde (Signo +): Indica que los tiempos de inactividad del tecnico en la calle se encuentran completamente justificados y respaldados por las pausas reportadas.",
        "Balance Negativo Rojo (Signo -): Alerta critica para supervision. Significa que el tecnico tiene horas o minutos 'fantasma' de inactividad en la calle que no fueron reportados ni justificados."
    ], tipo="alerta")

    pdf.dibujar_figura_balance()
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 5: AUDITORÍA BIOMÉTRICA
    # ==========================================================================
    pdf.titulo_modulo("5", "Auditoría de Asistencia Biométrica (biometrico.py)")
    pdf.multi_cell(190, 5, txt=safestr("Modulo disenado para fiscalizar la puntualidad, asistencias, faltas injustificadas y control de horarios de alimentacion (almuerzos) mediante la lectura del reloj biometrico de la empresa."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "5.1 Carga del Archivo de Transacciones", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("- Sube el archivo CSV o PDF generado directamente por el reloj biometrico de asistencia de la oficina."))
    pdf.multi_cell(190, 5, txt=safestr("- El sistema ejecutara la funcion limpiar_nombre, removiendo metadatos irrelevantes del archivo log (punch, state, location, remarks) para aislar los nombres y cruzarlos contra personal_tecnico.txt."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "5.2 Estructura del Tablero de Asistencia por Areas", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("El sistema procesa la informacion y segmenta al personal automaticamente en tres tablas independientes: 1. Tablero Area HFC, 2. Tablero Area FTTH, 3. Tablero Otras Areas (Supervision, IT, Logistica)."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "5.3 Indicadores de Asistencia", ln=True)
    pdf.multi_cell(190, 5, txt=safestr("- ASISTENCIA (Verde): Marcaje correcto de entrada dentro de las tolerancias de la empresa."))
    pdf.multi_cell(190, 5, txt=safestr("- RETARDO (Amarillo): El marcaje de entrada supera la hora limite establecida para el inicio del turno."))
    pdf.multi_cell(190, 5, txt=safestr("- AUSENTE (Rojo): El colaborador no registra ningun marcaje de huella o rostro durante todo el dia."))
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 6: GESTIÓN DE EXPEDIENTES
    # ==========================================================================
    pdf.titulo_modulo("6", "Gestión de Expedientes Disciplinarios (expediente.py)")
    pdf.multi_cell(190, 5, txt=safestr("Modulo critico para el registro administrativo de incidencias, amonestaciones y justificaciones medicas de MaxCom, conectado a un cluster de almacenamiento dual GCS/Sheets de alta velocidad."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "6.1 Registro Paso a Paso de una Incidencia", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("1. Abre el expander Crear Nuevo Registro en el panel."))
    pdf.multi_cell(190, 5, txt=safestr("2. Seleccion de Colaborador: Elige el nombre. El motor anti-duplicados estandarizara la escritura."))
    pdf.multi_cell(190, 5, txt=safestr("3. Motivo: Selecciona la categoria. Si eliges 'Otro', se abrira un text_input obligatorio reactivo."))
    pdf.multi_cell(190, 5, txt=safestr("4. Evidencias: Arrastra imagenes. El sistema se comunica con la API de FreeImage e integra los enlaces resultantes de forma automatizada."))
    pdf.multi_cell(190, 5, txt=safestr("5. Comentario: Describe detalladamente las observaciones del suceso en campo."))
    pdf.multi_cell(190, 5, txt=safestr("6. Guardado: Al hacer clic en GUARDAR, la informacion se inyecta en milisegundos en el bucket de Google Cloud Storage (expedientes_maestro.csv) y Sheets espejo, limpiando la memoria temporal."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "6.2 Interpretacion de la Cuadrícula Analítica de KPIs (2x2)", ln=True)
    pdf.dibujar_figura_dashboard()
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "6.3 Descarga de Memorandums en PDF y Eliminacion", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("- Memos Inteligentes: Al seleccionar un caso, podras descargar su PDF oficial. Si es 'Incidencia Medica', cambiara a tonos azules bajo el titulo Constancia Medica. Si es amonestacion, adoptara titulos en color rojo bajo la estructura de Memorandum: Llamado de Atencion."))
    pdf.multi_cell(190, 5, txt=safestr("- Eliminacion (Admin): Si eres administrador, podras borrar el registro fisico. El sistema borrara las celdas en GCS y en Sheets (gspread) sincronizando la cache al instante."))
    pdf.ln(4)

    # ==========================================================================
    # SECCIÓN 7: SETTINGS
    # ==========================================================================
    pdf.titulo_modulo("7", "Preferencias de Interfaz y Configuración (settings.py)")
    pdf.multi_cell(190, 5, txt=safestr("Espacio disenado para personalizar la experiencia de usuario y gestionar el comportamiento visual de la pantalla de monitoreo operativo."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "7.1 Personalización de la Interfaz (Toggles)", ln=True)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(190, 5, txt=safestr("A traves de interruptores interactivos (st.toggle), puedes encender o apagar los componentes visuales de la pantalla principal para concentrarte en una sola tarea: Filtros Rapidos, Tablero de Carga Actual (Pendientes), Consolidado Diario, Linea de Tiempo Operativa (Gantt) y Panel de Analitica General."))
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, "7.2 Manual de Usuario Integrado", ln=True)
    pdf.multi_cell(190, 5, txt=safestr("Despliega acordeones informativos (st.expander) y un boton central de descarga para obtener este manual estructurado en formato PDF listo para auditorias de calidad corporativas."))

    # Guardar en memoria y retornar bytes
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# CONFIGURACIÓN DE LA INTERFAZ DE STREAMLIT
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
        st.markdown("### 📖 Documentación Didáctica Ilustrada")
        st.write("Presione el botón inferior para compilar y descargar el **Manual Técnico de Operación (Estilo Libro Escolar)**. Este documento incluye todas las reglas de negocio de MaxCom, diagramas de flujo secuenciales de datos, la lógica analítica de mora y guías de auditoría interactiva.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_espacio, col_boton, col_espacio2 = st.columns([1, 2, 1])
        with col_boton:
            try:
                pdf_manual = generar_manual_pdf()
                st.download_button(
                    label="📥 DESCARGAR MANUAL DIDÁCTICO ILUSTRADO (PDF)",
                    data=pdf_manual,
                    file_name="Manual_Ilustrado_MaxcomPRO.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error al compilar el manual ilustrado: {e}")
