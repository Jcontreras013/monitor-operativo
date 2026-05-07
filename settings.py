import streamlit as st

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
        st.markdown("# 📖 Manual de Usuario: Monitor Operativo Maxcom PRO")
        st.write("Este sistema ha sido diseñado para la supervisión en tiempo real de la operación técnica y la gestión de indicadores.")

        with st.expander("🔐 1. Acceso y Seguridad", expanded=True):
            st.markdown("""
            * **Inicio de Sesión**: Ingrese sus credenciales asignadas en la pantalla principal.
            * **Temporizador**: Por seguridad, la sesión caduca tras **5 minutos de inactividad**.
            * **Cierre de Sesión**: Use el botón **'Cerrar Sesión'** al final de la barra lateral para salir de forma segura.
            """)

        with st.expander("⚡ 2. Monitor en Vivo"):
            st.markdown("""
            ### A. Indicadores (KPIs)
            * **Pendientes Asignadas**: Órdenes activas con técnico en ruta o sitio.
            * **Cerradas Hoy**: Total de liquidaciones exitosas del día.
            * **Caídas (Offline)**: Equipos detectados con pérdida de señal.

            ### B. Línea de Tiempo (Gantt)
            Muestra la secuencia de trabajo por técnico. Al pasar el mouse verá:
            * **Actividad y Estado**.
            * **Horas exactas** de inicio y cierre.
            * **Tiempo Total**: Duración exacta de la gestión.

            ### C. Panel de Control
            * 🔴 **Fondo Rojo**: Retrasos >= 7 días.
            * 🟠 **Faranja**: Retraso de 4 a 6 días.
            * ⚠️ **Icono Alerta**: Órdenes que exceden el tiempo estándar (ej. SOP > 2h).
            """)

        with st.expander("📊 3. Centro de Reportes"):
            st.markdown("""
            ### Cierre Diario
            Seleccione una fecha para generar el PDF con métricas de efectividad de mora.

            ### Resumen de Operaciones (6 Columnas)
            Este cuadro separa el avance real:
            1. **Mora inicial**: Pendientes de días anteriores.
            2. **Cerradas (Mora)**: Avance sobre el arrastre.
            3. **Total (Mora)**: Saldo pendiente antiguo.
            4. **Asignadas hoy**: Nuevas entradas del día.
            5. **Cerradas hoy**: Órdenes nuevas liquidadas.
            6. **Total (Hoy)**: Saldo para el día siguiente.
            """)

        with st.expander("⚙️ 4. Configuración y Oracle"):
            st.markdown("""
            * **Preferencias**: Use los interruptores para limpiar su pantalla y ver solo lo que necesita.
            * **Sincronización**: El botón 'Actualizar desde la nube' trae los datos frescos de Sheets.
            * **🔌 Oracle (Beta)**: Conexión directa a la base de datos central para evitar cargas manuales de Excel.
            """)

        with st.expander("🚙 5. Módulos de Auditoría"):
            st.markdown("""
            * **Auditoría Vehicular**: Compara la primera salida y última entrada para calcular el tiempo real en calle.
            * **Biométrico**: Analiza el archivo CSV de transacciones para detectar tardanzas o excesos en tiempos de comida.
            """)
