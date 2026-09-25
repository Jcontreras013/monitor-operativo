# ==============================================================================
# AVISOS POR CORREO (SMTP)
# ==============================================================================
# Lo usan la app (Auditoría de Materiales) y sync_job.py (órdenes VIP), que
# corre fuera de Streamlit y lee secrets.toml con toml. Por eso la
# configuración entra como dict y este módulo no depende de Streamlit.
#
# Secretos (sección [correo]):
#   servidor = "smtp.us-east.atmailcloud.com"
#   puerto = 587                       # 587 = STARTTLS (por defecto, cifrado TLS); 465 = SSL/TLS
#   usuario = "cuenta@dominio"
#   contrasena = "..."                 # en Gmail: "contraseña de aplicación"
#   remitente = "cuenta@dominio"       # opcional; por defecto, el usuario
#   destinatarios = ["a@...", "b@..."]
#   destinatarios_vip = ["a@..."]      # opcional; por defecto, destinatarios
import html
import smtplib
import ssl
from email.message import EmailMessage

import pandas as pd


def config_correo_streamlit():
    """Sección [correo] de st.secrets como dict ({} si no está)."""
    try:
        import streamlit as st
        return dict(st.secrets["correo"])
    except Exception:
        return {}


def lista_destinatarios(config, clave="destinatarios"):
    valor = config.get(clave) or (config.get("destinatarios") if clave != "destinatarios" else None) or []
    if isinstance(valor, str):
        valor = valor.replace(";", ",").split(",")
    return [str(d).strip() for d in valor if str(d).strip()]


def falta_configuracion(config, clave_destinatarios="destinatarios"):
    """Qué falta para poder enviar, o None si está completo."""
    faltantes = [c for c in ("servidor", "usuario", "contrasena") if not str(config.get(c, "")).strip()]
    if not lista_destinatarios(config, clave_destinatarios):
        faltantes.append(clave_destinatarios)
    return ", ".join(faltantes) if faltantes else None


def tabla_html(df):
    """Tabla HTML con estilos en línea (los clientes de correo ignoran <style>)."""
    celda = "border:1px solid #d0d7e2;padding:4px 8px;font-size:12px;vertical-align:top;"
    encabezado = "".join(
        f'<th style="{celda}background:#e6ebf5;text-align:left;">{html.escape(str(c))}</th>' for c in df.columns
    )
    filas = "".join(
        "<tr>" + "".join(f'<td style="{celda}">{html.escape("" if pd.isna(v) else str(v))}</td>' for v in fila) + "</tr>"
        for fila in df.itertuples(index=False)
    )
    return f'<table style="border-collapse:collapse;font-family:Arial,sans-serif;"><tr>{encabezado}</tr>{filas}</table>'


def enviar_correo(config, asunto, texto, html_cuerpo=None, clave_destinatarios="destinatarios"):
    """Envía un correo. Devuelve (True, None) o (False, motivo)."""
    faltante = falta_configuracion(config, clave_destinatarios)
    if faltante:
        return False, f"falta configurar en los secretos [correo]: {faltante}"

    destinatarios = lista_destinatarios(config, clave_destinatarios)
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = str(config.get("remitente") or config["usuario"]).strip()
    mensaje["To"] = ", ".join(destinatarios)
    mensaje.set_content(texto)
    if html_cuerpo:
        mensaje.add_alternative(html_cuerpo, subtype="html")

    servidor = str(config["servidor"]).strip()
    puerto = int(config.get("puerto", 587))
    # Si el puerto configurado no conecta, se prueban los puertos cifrados
    # estándar (587 = STARTTLS, 465 = SSL/TLS), también si el configurado no
    # es de correo (ej. un 447 mal escrito). Solo ante fallas de CONEXIÓN: una
    # contraseña o un destinatario rechazado no se arreglan cambiando de puerto.
    puertos = [puerto] + [p for p in (587, 465) if p != puerto]
    fallas_conexion = []
    for p in puertos:
        try:
            _enviar_por_puerto(servidor, p, config, mensaje)
            if p != puerto:
                return True, (f"se envió por el puerto {p} ({_modo(p)}) porque el {puerto} no conectó; "
                              f"conviene poner puerto = {p} en los secretos [correo]")
            return True, None
        # El orden importa: los errores SMTP y de certificado también son OSError.
        except smtplib.SMTPAuthenticationError:
            return False, "el servidor de correo rechazó el usuario o la contraseña"
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
            # Algo contestó en ese puerto pero no es el servicio de correo esperado.
            fallas_conexion.append(f"{p} ({_modo(p)}): {e}")
        except smtplib.SMTPException as e:
            return False, f"el servidor de correo respondió con un error: {e}"
        except ssl.SSLCertVerificationError:
            return False, (f"el certificado de seguridad del servidor no corresponde a '{servidor}'. "
                           "Usa el nombre del servidor del proveedor de correo (en MAXCOM: smtp.us-east.atmailcloud.com)")
        except OSError as e:
            fallas_conexion.append(f"{p} ({_modo(p)}): {e}")
        except Exception as e:
            return False, str(e)
    return False, (f"no se pudo conectar a {servidor} por ningún puerto [{'; '.join(fallas_conexion)}]. "
                   "Revisa el nombre del servidor; si es desde la PC del robot, que el firewall de la red "
                   "permita salir por los puertos 465 o 587")


def _modo(puerto):
    return "SSL/TLS" if puerto == 465 else "STARTTLS (TLS)"


def _enviar_por_puerto(servidor, puerto, config, mensaje):
    contexto = ssl.create_default_context()
    if puerto == 465:
        with smtplib.SMTP_SSL(servidor, puerto, context=contexto, timeout=30) as smtp:
            smtp.login(str(config["usuario"]).strip(), str(config["contrasena"]))
            smtp.send_message(mensaje)
    else:
        with smtplib.SMTP(servidor, puerto, timeout=30) as smtp:
            smtp.starttls(context=contexto)
            smtp.login(str(config["usuario"]).strip(), str(config["contrasena"]))
            smtp.send_message(mensaje)


def enviar_correo_prueba(config, clave_destinatarios="destinatarios", origen="la app"):
    """Correo de prueba para confirmar que la configuración [correo] funciona."""
    texto = (
        f"Este es un correo de prueba enviado desde {origen} del Monitor Operativo MAXCOM.\n\n"
        "Si lo recibiste, las alertas por correo (cajas molex en soporte y órdenes de clientes VIP) "
        "van a llegar a esta misma lista de destinatarios."
    )
    return enviar_correo(config, "✅ Prueba de alertas por correo - Monitor Operativo", texto,
                         clave_destinatarios=clave_destinatarios)


ARCHIVO_ESTADO_ALERTAS = "estado_alertas_robot.csv"
MINUTOS_ROBOT_DETENIDO = 35   # el ciclo es de 15 min; más de dos ciclos sin reportar = algo pasa


def mostrar_estado_robot():
    """Resultado del último ciclo de alertas que reportó sync_job.py (lo guarda en GCS)."""
    import streamlit as st
    from tools import leer_espejo_gcs, get_honduras_time, NOMBRE_BUCKET_SISTEMA

    st.markdown("##### 🤖 Último ciclo de alertas del robot")
    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, ARCHIVO_ESTADO_ALERTAS)
    except Exception:
        df = None
    if df is None or df.empty:
        st.warning(
            "El robot todavía no reporta el estado de las alertas. Eso significa que en la PC del robot sigue "
            "corriendo una versión anterior del código, o que no se ha reiniciado desde que se actualizó. "
            "Actualiza el código en esa PC y reinicia el robot; después de un ciclo (15 min) aparece aquí."
        )
        return
    ultimo = pd.to_datetime(df["ULTIMO_CICLO"].iloc[0], errors="coerce")
    if pd.notna(ultimo):
        minutos = (pd.Timestamp(get_honduras_time()) - ultimo).total_seconds() / 60
        texto = f"Último ciclo: **{ultimo:%d/%m/%Y %H:%M}** (hace {max(minutos, 0):.0f} min)."
        (st.warning if minutos > MINUTOS_ROBOT_DETENIDO else st.caption)(
            texto + (" El robot parece detenido: no reporta desde hace más de dos ciclos." if minutos > MINUTOS_ROBOT_DETENIDO else "")
        )
    iconos = {"enviado": "✅", "sin novedades": "➖", "desactivado": "⛔", "sin lista VIP": "⚠️",
              "error al enviar": "❌", "error": "❌"}
    for _, fila in df.iterrows():
        st.markdown(f"{iconos.get(fila['RESULTADO'], '•')} **{fila['ALERTA']}:** {fila['RESULTADO']} — {fila['DETALLE']}")


def mostrar_config_correo():
    """Pestaña de Configuración: estado de [correo] y botón de prueba (sin mostrar la contraseña)."""
    import streamlit as st

    st.subheader("📧 Correo de alertas")
    mostrar_estado_robot()
    st.divider()

    st.markdown("##### Configuración de la app (botón de prueba)")
    st.caption(
        "Las alertas las envía el robot con el [correo] de su propio secrets.toml. Esta sección usa el [correo] "
        "de Settings → Secrets de la app, solo para el correo de prueba."
    )
    config = config_correo_streamlit()
    if not config:
        st.warning("No hay sección [correo] en los secretos de la app, así que no se puede mandar el correo de prueba desde aquí.")
        return

    c1, c2 = st.columns(2)
    c1.markdown(f"**Servidor:** `{config.get('servidor', '—')}:{config.get('puerto', 587)}` ({_modo(int(config.get('puerto', 587)))})")
    c1.markdown(f"**Envía:** `{config.get('remitente') or config.get('usuario', '—')}`")
    c1.markdown(f"**Contraseña:** {'configurada' if str(config.get('contrasena', '')).strip() else '❌ falta'}")
    c2.markdown("**Alertas de cajas molex a:**<br>" + ("<br>".join(map(html.escape, lista_destinatarios(config))) or "—"),
                unsafe_allow_html=True)
    c2.markdown("**Avisos VIP a:**<br>" + ("<br>".join(map(html.escape, lista_destinatarios(config, "destinatarios_vip"))) or "—"),
                unsafe_allow_html=True)

    faltante = falta_configuracion(config)
    if faltante:
        st.warning(f"Falta configurar: {faltante}.")
        return
    if st.button("📨 Enviar correo de prueba", key="btn_correo_prueba"):
        with st.spinner("Enviando..."):
            ok, error = enviar_correo_prueba(config)
        if ok:
            st.success(f"✅ Correo de prueba enviado a {len(lista_destinatarios(config))} destinatario(s). Revisen la bandeja (y el spam).")
            if error:
                st.warning(f"⚠️ Nota: {error}.")
        else:
            st.error(f"❌ No se pudo enviar: {error}")
