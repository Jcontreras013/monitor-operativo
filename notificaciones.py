# ==============================================================================
# AVISOS POR CORREO (SMTP)
# ==============================================================================
# Lo usan la app (Auditoría de Materiales) y sync_job.py (órdenes VIP), que
# corre fuera de Streamlit y lee secrets.toml con toml. Por eso la
# configuración entra como dict y este módulo no depende de Streamlit.
#
# Secretos (sección [correo]):
#   servidor = "smtp.gmail.com"        # o "smtp.office365.com"
#   puerto = 587                       # 587 (STARTTLS) o 465 (SSL)
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
    try:
        if puerto == 465:
            with smtplib.SMTP_SSL(servidor, puerto, context=ssl.create_default_context(), timeout=30) as smtp:
                smtp.login(str(config["usuario"]).strip(), str(config["contrasena"]))
                smtp.send_message(mensaje)
        else:
            with smtplib.SMTP(servidor, puerto, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(str(config["usuario"]).strip(), str(config["contrasena"]))
                smtp.send_message(mensaje)
        return True, None
    # El orden importa: los errores SMTP y de certificado también son OSError.
    except smtplib.SMTPAuthenticationError:
        return False, "el servidor de correo rechazó el usuario o la contraseña"
    except smtplib.SMTPException as e:
        return False, f"el servidor de correo respondió con un error: {e}"
    except ssl.SSLCertVerificationError:
        return False, (f"el certificado de seguridad del servidor no corresponde a '{servidor}'. "
                       "Usa el nombre del servidor del proveedor de correo (en MAXCOM: smtp.us-east.atmailcloud.com)")
    except OSError as e:
        return False, (f"no se pudo conectar a {servidor}:{puerto} ({e}). Revisa el servidor y el puerto; "
                       "si es desde la PC del robot, que el firewall de la red permita salir por ese puerto")
    except Exception as e:
        return False, str(e)


def enviar_correo_prueba(config, clave_destinatarios="destinatarios", origen="la app"):
    """Correo de prueba para confirmar que la configuración [correo] funciona."""
    texto = (
        f"Este es un correo de prueba enviado desde {origen} del Monitor Operativo MAXCOM.\n\n"
        "Si lo recibiste, las alertas por correo (cajas molex en soporte y órdenes de clientes VIP) "
        "van a llegar a esta misma lista de destinatarios."
    )
    return enviar_correo(config, "✅ Prueba de alertas por correo - Monitor Operativo", texto,
                         clave_destinatarios=clave_destinatarios)


def mostrar_config_correo():
    """Pestaña de Configuración: estado de [correo] y botón de prueba (sin mostrar la contraseña)."""
    import streamlit as st

    st.subheader("📧 Correo de alertas")
    st.caption(
        "Cuenta y destinatarios de las alertas por correo (cajas molex en soporte y órdenes nuevas de "
        "clientes VIP). Se configuran en Settings → Secrets de la app, sección [correo]."
    )
    config = config_correo_streamlit()
    if not config:
        st.warning("No hay sección [correo] en los secretos de la app. Hasta configurarla no se envía ninguna alerta.")
        return

    c1, c2 = st.columns(2)
    c1.markdown(f"**Servidor:** `{config.get('servidor', '—')}:{config.get('puerto', 587)}`")
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
        else:
            st.error(f"❌ No se pudo enviar: {error}")
