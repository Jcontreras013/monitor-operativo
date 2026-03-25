import streamlit as st

def verificar_autenticacion():
    """Inicializa la memoria de sesión de Streamlit si es la primera vez que entra."""
    if 'autenticado' not in st.session_state:
        st.session_state['autenticado'] = False
        st.session_state['rol_actual'] = None

def mostrar_pantalla_login():
    """Dibuja la tarjeta de login centrada en la pantalla."""
    st.markdown("<br><br><br>", unsafe_allow_html=True) 
    
    col1, col_login, col3 = st.columns([1, 1.2, 1])
    
    with col_login:
        st.markdown("<h2 style='text-align: center;'>🔐 Acceso al Sistema</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Monitor Operativo Maxcom PRO</p>", unsafe_allow_html=True)
        st.divider()
        
        with st.form("formulario_login"):
            usuario = st.text_input("👤 Usuario")
            clave = st.text_input("🔑 Contraseña", type="password")
            btn_ingresar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
            
            if btn_ingresar:
                user_clean = usuario.strip().lower()
                
                # Vamos a la caja fuerte (secrets) a revisar si el usuario existe y si la clave coincide
                if user_clean in st.secrets["credenciales"] and st.secrets["credenciales"][user_clean]["clave"] == clave:
                    st.session_state['autenticado'] = True
                    st.session_state['usuario_actual'] = user_clean
                    st.session_state['rol_actual'] = st.secrets["credenciales"][user_clean]["rol"]
                    st.success(f"✅ Acceso concedido. Bienvenido {user_clean.capitalize()}...")
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos. Intente de nuevo.")

def mostrar_boton_logout():
    """Agrega la etiqueta del usuario, su rol y el botón de salida al final del lateral."""
    with st.sidebar:
        st.divider()
        rol_mostrar = st.session_state.get('rol_actual', '').upper()
        st.caption(f"👤 Usuario: **{st.session_state.get('usuario_actual', '').upper()}** | Rol: {rol_mostrar}")
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state['autenticado'] = False
            st.session_state['rol_actual'] = None
            st.rerun()
