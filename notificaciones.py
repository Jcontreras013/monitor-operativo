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
    except smtplib.SMTPAuthenticationError:
        return False, "el servidor de correo rechazó el usuario o la contraseña"
    except Exception as e:
        return False, str(e)
