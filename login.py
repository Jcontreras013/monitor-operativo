import hashlib
import hmac
import secrets as _secretos
import streamlit as st
from datetime import datetime, timedelta
import extra_streamlit_components as stx

# ==============================================================================
# CONTRASEÑAS CAMBIADAS DESDE LA APP
# ==============================================================================
# Los usuarios y roles viven en st.secrets["credenciales"], pero la app NO
# puede escribir en los secretos de Streamlit Cloud (solo se editan a mano en
# su panel). Por eso, cuando un admin o jefe cambia su contraseña, se guarda
# cifrada (PBKDF2-SHA256 con sal: no se puede leer, solo comprobar) en la hoja
# Usuarios_Claves de la base de datos, y tiene prioridad sobre la de secrets.
HOJA_CLAVES = "Usuarios_Claves"
ROLES_CAMBIAN_CLAVE = ("admin", "jefe")
LARGO_MINIMO_CLAVE = 8
_ITERACIONES = 200_000


def _cifrar_clave(clave, sal=None):
    sal = sal or _secretos.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(clave).encode("utf-8"), bytes.fromhex(sal), _ITERACIONES).hex()
    return f"pbkdf2_sha256${_ITERACIONES}${sal}${digest}"


def _clave_coincide(clave, cifrada):
    try:
        _, iteraciones, sal, digest = str(cifrada).split("$")
        calculado = hashlib.pbkdf2_hmac("sha256", str(clave).encode("utf-8"), bytes.fromhex(sal), int(iteraciones)).hex()
        return hmac.compare_digest(calculado, digest)
    except Exception:
        return False


def _conexion_sheets():
    from streamlit_gsheets import GSheetsConnection
    return st.connection("gsheets", type=GSheetsConnection)


def _leer_claves_cambiadas():
    """{usuario: clave_cifrada} de la hoja Usuarios_Claves ({} si no existe o no responde)."""
    try:
        df = _conexion_sheets().read(spreadsheet=st.secrets["url_base_datos"], worksheet=HOJA_CLAVES, ttl=0)
        df = df.dropna(how="all")
        return {str(u).strip().lower(): str(c) for u, c in zip(df["USUARIO"], df["CLAVE_CIFRADA"]) if str(c).strip()}
    except Exception:
        return {}


def _guardar_clave_cambiada(usuario, nueva_clave):
    """Guarda (o reemplaza) la clave cifrada del usuario. Devuelve (True, None) o (False, motivo)."""
    import pandas as pd
    from tools import escribir_hoja_sheets
    try:
        conn = _conexion_sheets()
        try:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=HOJA_CLAVES, ttl=0).dropna(how="all")
        except Exception:
            df = pd.DataFrame(columns=["USUARIO", "CLAVE_CIFRADA", "ACTUALIZADO_EN"])
        df = df[df["USUARIO"].astype(str).str.strip().str.lower() != usuario] if not df.empty else df
        df = pd.concat([df, pd.DataFrame([{
            "USUARIO": usuario,
            "CLAVE_CIFRADA": _cifrar_clave(nueva_clave),
            "ACTUALIZADO_EN": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }])], ignore_index=True)
        escribir_hoja_sheets(conn, st.secrets["url_base_datos"], HOJA_CLAVES, df[["USUARIO", "CLAVE_CIFRADA", "ACTUALIZADO_EN"]])
        return True, None
    except Exception as e:
        return False, str(e)


def clave_valida(usuario, clave):
    """
    Comprueba la contraseña: la cambiada desde la app (hoja Usuarios_Claves)
    si existe; si no, la de secrets. Si la hoja no responde se usa secrets,
    para que nadie quede fuera por una falla de Google.
    """
    cambiada = _leer_claves_cambiadas().get(usuario)
    if cambiada:
        return _clave_coincide(clave, cambiada)
    return str(st.secrets["credenciales"][usuario]["clave"]) == str(clave)

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
                    if clave_valida(user_clean, clave):
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
        if str(st.session_state.get('rol_actual', '')).strip().lower() in ROLES_CAMBIAN_CLAVE:
            mostrar_cambio_clave()
        
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            cookie_manager.delete("token_maxcom")
            st.session_state['autenticado'] = False
            st.session_state['rol_actual'] = None
            st.session_state['usuario_actual'] = None
            st.rerun()


def mostrar_cambio_clave():
    """Formulario para que un admin o jefe cambie SU propia contraseña."""
    usuario = str(st.session_state.get('usuario_actual', '')).strip().lower()
    with st.expander("🔑 Cambiar contraseña"):
        with st.form("form_cambio_clave", clear_on_submit=True):
            actual = st.text_input("Contraseña actual", type="password")
            nueva = st.text_input(f"Nueva contraseña (mínimo {LARGO_MINIMO_CLAVE} caracteres)", type="password")
            confirmar = st.text_input("Repite la nueva contraseña", type="password")
            enviar = st.form_submit_button("Guardar nueva contraseña", use_container_width=True)
        if not enviar:
            return
        if not usuario or "credenciales" not in st.secrets or usuario not in st.secrets["credenciales"]:
            st.error("❌ No se encontró tu usuario.")
        elif not clave_valida(usuario, actual):
            st.error("❌ La contraseña actual no es correcta.")
        elif len(nueva) < LARGO_MINIMO_CLAVE:
            st.error(f"❌ La nueva contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.")
        elif nueva != confirmar:
            st.error("❌ Las dos contraseñas nuevas no coinciden.")
        elif nueva == actual:
            st.error("❌ La nueva contraseña debe ser distinta de la actual.")
        else:
            ok, motivo = _guardar_clave_cambiada(usuario, nueva)
            if ok:
                st.success("✅ Contraseña actualizada. Úsala desde tu próximo inicio de sesión.")
            else:
                st.error(f"❌ No se pudo guardar: {motivo}")
