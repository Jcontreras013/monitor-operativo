import streamlit as st

def inicializar_configuracion():
    """Define los valores por defecto en la memoria de la sesión."""
    if 'config_mostrar_tablero' not in st.session_state:
        st.session_state.config_mostrar_tablero = True
    if 'config_mostrar_consolidado' not in st.session_state:
        st.session_state.config_mostrar_consolidado = True
    if 'config_mostrar_panel' not in st.session_state:
        st.session_state.config_mostrar_panel = True

def mostrar_configuracion():
    st.title("⚙️ Configuración y Documentación")
    
    tab_conf, tab_doc = st.tabs(["🎛️ Preferencias de Interfaz", "📚 Manual de Usuario"])
    
    with tab_conf:
        st.subheader("Personalización del Monitor en Vivo")
        st.write("Apaga o enciende las secciones que deseas ver en tu pantalla principal. Los cambios se guardan automáticamente.")
        
        # Toggles conectados a la memoria para ocultar los expanders
        st.session_state.config_mostrar_tablero = st.toggle(
            "📊 Mostrar: Tablero de Carga Actual (Pendientes)", 
            value=st.session_state.config_mostrar_tablero
        )
        
        st.session_state.config_mostrar_consolidado = st.toggle(
            "📊 Mostrar: Consolidado por Segmento (Mora vs Al Día)", 
            value=st.session_state.config_mostrar_consolidado
        )
        
        st.session_state.config_mostrar_panel = st.toggle(
            "🎛️ Mostrar: Panel de Control y Análisis Detallado", 
            value=st.session_state.config_mostrar_panel
        )

    with tab_doc:
        st.subheader("📚 Guía Rápida del Sistema MaxCom")
        
        with st.expander("🚀 1. Cómo cargar y actualizar datos"):
            st.markdown("""
            * **Si eres Admin:** Debes subir los archivos `rep_actividades` y `FttxActiveDevice` en la barra lateral y presionar **PROCESAR ARCHIVOS**.
            * **Si eres Monitoreo:** Solo verás el botón de actualización en la nube.
            * **Nota:** El sistema bajará automáticamente el FTTX de la nube si no lo subes (para ahorrar tiempo).
            """)
            
        with st.expander("📊 2. Interpretación de la Tabla y Colores"):
            st.markdown("""
            * 🔴 **Rojo oscuro:** Retraso grave (>= 7 días).
            * 🟠 **Naranja:** Retraso medio (4 a 6 días).
            * 🟡 **Amarillo:** Retraso leve (1 a 3 días).
            * 🟢 **Verde:** Al día (0 días).
            * ⚠️ **Icono de Alerta:** Aparece cuando una orden ha superado el tiempo máximo establecido (ej. SOP > 2 hrs).
            * 👆 **Interacción:** Si haces clic en fila de la tabla, se abrirá un cuadro flotante con detalles de la liquidación.
            """)
            
        with st.expander("🔌 3. Conexión a Oracle (Beta)"):
            st.info("Esta función extrae datos directamente del sistema principal sin necesidad de subir Excels manuales.")
