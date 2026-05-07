import streamlit as st

def inicializar_configuracion():
    """Define los valores por defecto si no existen en la sesión."""
    if 'config_mostrar_filtros' not in st.session_state:
        st.session_state.config_mostrar_filtros = True
    if 'config_mostrar_gantt' not in st.session_state:
        st.session_state.config_mostrar_gantt = True
    if 'config_mostrar_kpis' not in st.session_state:
        st.session_state.config_mostrar_kpis = True

def mostrar_configuracion():
    st.title("⚙️ Configuración")
    
    tab_conf, tab_doc = st.tabs(["Preferencias de Interfaz", "📚 Manual de Usuario"])
    
    with tab_conf:
        st.subheader("Personalización del Monitor")
        st.write("Ajusta qué elementos deseas ver en la pantalla principal.")
        
        st.session_state.config_mostrar_filtros = st.toggle(
            "Mostrar Panel de Filtros", 
            value=st.session_state.config_mostrar_filtros
        )
        
        st.session_state.config_mostrar_gantt = st.toggle(
            "Mostrar Gráfica de Gantt", 
            value=st.session_state.config_mostrar_gantt
        )
        
        st.session_state.config_mostrar_kpis = st.toggle(
            "Mostrar Resumen de KPIs (Cerradas/Asignadas)", 
            value=st.session_state.config_mostrar_kpis
        )
        
        if st.button("Guardar y Aplicar Cambios"):
            st.success("Configuración aplicada correctamente.")
            st.rerun()

    with tab_doc:
        st.subheader("📚 Guía Rápida del Sistema")
        
        with st.expander("🚀 Cómo cargar datos"):
            st.markdown("""
            1. Ve a la barra lateral izquierda.
            2. En la sección **Carga de Archivos**, sube el reporte de actividades.
            3. Haz clic en **PROCESAR ARCHIVOS**. 
            *Nota: El sistema detectará automáticamente si faltan datos de vehículos y los bajará de la nube.*
            """)
            
        with st.expander("📊 Interpretación de Tablas"):
            st.markdown("""
            - **Celdas Rojas:** Indican retrasos mayores a 7 días o técnicos offline.
            - **Icono ⚠️:** Aparece en órdenes que han excedido el tiempo estándar de gestión.
            - **Clic en Fila:** Al seleccionar una fila, se abrirá un detalle completo con los comentarios de liquidación.
            """)
            
        with st.expander("🔌 Conexión a Oracle (Beta)"):
            st.info("Esta función extrae datos directamente del sistema principal sin necesidad de subir Excels manuales.")
