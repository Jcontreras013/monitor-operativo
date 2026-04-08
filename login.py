import streamlit as st
from datetime import datetime, timedelta
import extra_streamlit_components as stx

# ==============================================================================
# INICIALIZAR EL ADMINISTRADOR DE COOKIES
# ==============================================================================
# 🚨 AQUÍ ESTABA EL ERROR: Se eliminó la instrucción obsoleta
@st.cache_resource
def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()

# ==============================================================================
# BASE DE DATOS DE USUARIOS (Modifica con tus contraseñas reales)
# ==============================================================================
USUARIOS = {
    "jaison": {"pwd": "123", "rol": "admin"},
    "jefe": {"pwd": "456", "rol": "jefe"},
    "tecnico": {"pwd": "789", "rol": "monitoreo"}
}

# ==============================================================================
# LÓGICA DE AUTENTICACIÓN Y TEMPORIZADOR BLINDADA
# ==============================================================================
def verificar_autenticacion():
    # Pausar el código hasta que el celular envíe las cookies
    if not cookie_manager.ready():
        st.stop()
        
    # 1. Leemos la cookie con seguridad
    ultimo_acceso_str = cookie_manager.get(cookie="token_maxcom")
    
    if ultimo_acceso_str:
        try:
            # Desarmamos el token (Formato: "2026-04-08T15:00:00|admin")
            partes = str(ultimo_acceso_str).split("|")
            fecha_str = partes[0]
            rol_guardado = partes[1] if len(partes) > 1 else "monitoreo"
            
            ultimo_acceso = datetime.fromisoformat(fecha_str)
            tiempo_inactivo = datetime.now() - ultimo_acceso
            
            # 2. Verificamos el temporizador de 5 Minutos
            if tiempo_inactivo < timedelta(minutes=5):
                # Como sigue activo, RENOVAMOS la cookie desde este momento
                nuevo_token = f"{datetime.now().isoformat()}|{rol_guardado}"
                cookie_manager.set("token_maxcom", nuevo_token, key="update_session")
                
                st.session_state['autenticado'] = True
                st.session_state['rol_actual'] = rol_guardado
                return True
            else:
                # 3. Si pasaron los 5 minutos, lo expulsamos
                cookie_manager.delete("token_maxcom", key="delete_timeout")
                st.session_state['autenticado'] = False
                return False
        except Exception:
            st.session_state['autenticado'] = False
            return False
    else:
        st.session_state['autenticado'] = False
        return False

# ==============================================================================
# PANTALLA VISUAL DE LOGIN
# ==============================================================================
def mostrar_pantalla_login():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<h2 style='text-align: center;'>🔒 Acceso Operativo</h2>", unsafe_allow_html=True)
        st.info("⏳ Por seguridad, tu sesión se cerrará tras 5 minutos de inactividad.")
        
        usuario = st.text_input("👤 Usuario", key="user_input").strip().lower()
        pwd = st.text_input("🔑 Contraseña", type="password", key="pwd_input")
        
        if st.button("🚀 Ingresar", use_container_width=True, type="primary"):
            if usuario in USUARIOS and pwd == USUARIOS[usuario]["pwd"]:
                rol = USUARIOS[usuario]["rol"]
                
                # Crear el token inicial con la hora y el rol
                token = f"{datetime.now().isoformat()}|{rol}"
                cookie_manager.set("token_maxcom", token, key="login_set")
                
                st.session_state['autenticado'] = True
                st.session_state['rol_actual'] = rol
                
                st.success("✅ Acceso concedido, cargando sistema...")
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos")

# ==============================================================================
# BOTÓN DE LOGOUT VOLUNTARIO
# ==============================================================================
def mostrar_boton_logout():
    if st.button("🚪 Cerrar Sesión", use_container_width=True, type="secondary"):
        cookie_manager.delete("token_maxcom", key="logout_del")
        st.session_state['autenticado'] = False
        st.session_state['rol_actual'] = None
        st.rerun()
