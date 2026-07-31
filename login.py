import streamlit as st
from datetime import datetime, timedelta
import extra_streamlit_components as stx

# ==============================================================================
# INICIALIZAR EL ADMINISTRADOR DE COOKIES (AISLADO POR USUARIO)
# ==============================================================================
# 🚨 SE ELIMINÓ @st.cache_resource PARA EVITAR QUE SE CRUCEN LAS SESIONES 🚨
def get_cookie_manager():
    if 'cookie_manager' not in st.session_state:
        # Se guarda en el estado de sesión INDIVIDUAL de cada usuario
        st.session_state['cookie_manager'] = stx.CookieManager(key="galletas_sesion")
    return st.session_state['cookie_manager']

# 🚨 IMPORTANTE: NUNCA asignar get_cookie_manager() a una variable de módulo aquí.
# login.py solo se importa UNA VEZ por proceso; una variable global quedaría
# fija al session_state de la primera persona que abrió la app, y TODOS los
# usuarios siguientes terminarían leyendo/escribiendo su cookie a través del
# CookieManager de esa primera sesión ("falso usuario"). Por eso cada función
# de abajo llama a get_cookie_manager() en su propio cuerpo, en cada ejecución.

def verificar_autenticacion():
    """Verifica la sesión activa usando cookies y un temporizador de 30 minutos."""
    cookie_manager = get_cookie_manager()

    # Inicializar variables de sesión si no existen
    if 'autenticado' not in st.session_state:
        st.session_state['autenticado'] = False
        st.session_state['rol_actual'] = None
        st.session_state['usuario_actual'] = None

    # 1. Leemos la cookie del celular/PC de ESTE usuario en específico
    ultimo_acceso_str = cookie_manager.get(cookie="token_maxcom")
    
    if ultimo_acceso_str:
        try:
            # Desarmamos el token (Formato: "2026-04-08T15:00:00|jaison|admin")
            partes = str(ultimo_acceso_str).split("|")
            fecha_str = partes[0]
            user_guardado = partes[1] if len(partes) > 1 else "desconocido"
            rol_guardado = partes[2] if len(partes) > 2 else "monitoreo"
            
            ultimo_acceso = datetime.fromisoformat(fecha_str)
            tiempo_inactivo = datetime.now() - ultimo_acceso
            
            # 2. Verificamos el temporizador de 30 Minutos
            if tiempo_inactivo < timedelta(minutes=30):
                # ANTI-BUCLES: Solo renovamos la cookie si ha pasado más de 1 minuto
                if tiempo_inactivo > timedelta(minutes=1):
                    nuevo_token = f"{datetime.now().isoformat()}|{user_guardado}|{rol_guardado}"
                    cookie_manager.set("token_maxcom", nuevo_token)
                
                st.session_state['autenticado'] = True
                st.session_state['usuario_actual'] = user_guardado
                st.session_state['rol_actual'] = rol_guardado
                return True
            else:
                # 3. Si se pasó de los 30 minutos de inactividad, destruimos la sesión
                cookie_manager.delete("token_maxcom")
                st.session_state['autenticado'] = False
                return False
        except Exception:
            st.session_state['autenticado'] = False
            return False
    else:
        st.session_state['autenticado'] = False
        return False

def mostrar_pantalla_login():
    """Dibuja la tarjeta de login centrada en la pantalla."""
    st.markdown("<br><br><br>", unsafe_allow_html=True) 
    
    col1, col_login, col3 = st.columns([1, 1.2, 1])
    
    with col_login:
        st.markdown("<h2 style='text-align: center;'>🔐 Acceso al Sistema</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>Monitor Operativo Maxcom PRO</p>", unsafe_allow_html=True)
        st.info("⏳ Por seguridad, tu sesión se cerrará tras 30 minutos de inactividad.")
        st.divider()
        
        with st.form("formulario_login"):
            usuario = st.text_input("👤 Usuario")
            clave = st.text_input("🔑 Contraseña", type="password")
            btn_ingresar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
            
            if btn_ingresar:
                cookie_manager = get_cookie_manager()
                user_clean = usuario.strip().lower()
                
                # Vamos a la caja fuerte (secrets) a revisar si el usuario existe y si la clave coincide
                if "credenciales" in st.secrets and user_clean in st.secrets["credenciales"]:
                    # Se usa str() para evitar errores si la contraseña tiene números
                    if str(st.secrets["credenciales"][user_clean]["clave"]) == str(clave):
                        rol = st.secrets["credenciales"][user_clean]["rol"]
                        
                        # Crear el token inicial con la hora, el usuario y el rol
                        token = f"{datetime.now().isoformat()}|{user_clean}|{rol}"
                        cookie_manager.set("token_maxcom", token)
                        
                        st.session_state['autenticado'] = True
                        st.session_state['usuario_actual'] = user_clean
                        st.session_state['rol_actual'] = rol
                        
                        st.success(f"✅ Acceso concedido. Bienvenido {user_clean.capitalize()}...")
                        st.rerun()
                    else:
                        st.error("❌ Contraseña incorrecta. Intente de nuevo.")
                else:
                    st.error("❌ Usuario no encontrado en los registros.")

def mostrar_boton_logout():
    """Agrega la etiqueta del usuario, su rol y el botón de salida al final del lateral."""
    cookie_manager = get_cookie_manager()
    with st.sidebar:
        st.divider()
        rol_mostrar = st.session_state.get('rol_actual', '').upper()
        usuario_mostrar = st.session_state.get('usuario_actual', '').upper()
        
        st.caption(f"👤 Usuario: **{usuario_mostrar}** | Rol: {rol_mostrar}")
        
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            cookie_manager.delete("token_maxcom")
            st.session_state['autenticado'] = False
            st.session_state['rol_actual'] = None
            st.session_state['usuario_actual'] = None
            st.rerun()
