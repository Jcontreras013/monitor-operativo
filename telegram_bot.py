# ==============================================================================
# BOT DE TELEGRAM: REGISTRO DE FALTAS/INCIDENCIAS DESDE UN GRUPO
# ==============================================================================
# Corre FUERA de Streamlit, en la misma PC que sync_job.py (C:\Maxcom), leyendo
# el mismo secrets.toml. Escucha un grupo de Telegram y guarda reportes de
# falta/incidencia directo en la pestaña 'Expedientes' de Google Sheets (+
# respaldo en GCS) -- sin depender de st.connection (no existe fuera de
# Streamlit).
#
# Dos formas de reportar:
#   1) Formulario guiado con botones: comando /falta (recomendada,
#      usa las mismas opciones que el formulario de Expedientes en la app).
#   2) Mensaje de texto libre con formato fijo (ver parse_mensaje_falta), para
#      quien prefiera escribirlo de un jalón.
#
# Uso: python telegram_bot.py   (queda corriendo en bucle; Ctrl+C para parar)
# ==============================================================================
import sys
import os
import time
import json
import toml
import requests
import difflib
import pandas as pd
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tools import (
    resolver_tecnico_por_similitud,
    normalizar_nombre_cruce,
    sobrescribir_archivo_gcs,
    leer_espejo_gcs,
    get_honduras_time,
    NOMBRE_BUCKET_SISTEMA as NOMBRE_BUCKET,
)
from expediente import (
    cargar_personal,
    cargar_personal_admin,
    subir_archivo_catbox,
)

RUTA_SECRETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
RUTA_OFFSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_offset.txt")

COLS_EXPEDIENTE = ['FECHA_REGISTRO', 'TECNICO', 'TIPO_FALTA', 'FECHA_INCIDENCIA', 'COMENTARIO', 'URL_FOTO', 'SUPERVISOR']

# Mismas opciones que ya usa el formulario manual de Expedientes en la app
# (expediente.py), para que el resultado sea idéntico sin importar por dónde
# se registre la falta.
MOTIVOS_OPERACIONES = [
    "Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta",
    "Mala Documentación", "Incidencia Médica", "Reco / Cambio de Postes",
    "Trabajo Deficiente (Auditoría de Fibra)", "Otro",
]
MOTIVOS_SAC = [
    "Llamado de Atención Verbal", "Amonestación Escrita", "Llegada Tardía",
    "Ausencia Laboral", "Incidencia Médica", "Felicitación / Mérito",
    "Curriculum / Contrato", "Otro",
]

# Sinónimos aceptados para el campo "Área" del mensaje de texto libre -- los
# jefes no siempre van a escribir exactamente "Operaciones" o "SAC".
SINONIMOS_AREA = {
    'OPERACIONES': 'OPERACIONES', 'OPERACION': 'OPERACIONES', 'TECNICOS': 'OPERACIONES',
    'TECNICO': 'OPERACIONES', 'CAMPO': 'OPERACIONES', 'INSTALACIONES': 'OPERACIONES',
    'SAC': 'SAC', 'ADMINISTRATIVO': 'SAC', 'ADMINISTRACION': 'SAC', 'ADMIN': 'SAC',
    'VENTAS': 'SAC', 'CALL CENTER': 'SAC', 'CALLCENTER': 'SAC', 'OFICINA': 'SAC',
}

# Estado de las conversaciones guiadas (/falta) EN MEMORIA, por
# (chat_id, user_id) -- así dos jefes pueden estar llenando su propio reporte
# al mismo tiempo en el mismo grupo sin cruzarse. Se pierde si el script se
# reinicia (aceptable: la persona solo tiene que volver a escribir el
# comando), a cambio de no complicar el script con persistencia a disco de
# conversaciones a medias.
ESTADOS_CONVERSACION = {}


def cargar_secrets():
    return toml.load(RUTA_SECRETS)


def conectar_hoja_expedientes(secrets_data):
    creds_dict = secrets_data["connections"]["gsheets"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(secrets_data["url_base_datos"])
    return spreadsheet.worksheet("Expedientes")


# ==============================================================================
# TELEGRAM: ENVÍO DE MENSAJES/BOTONES Y DESCARGA DE FOTOS
# ==============================================================================
def teclado_botones(opciones):
    """opciones: lista de (texto_boton, callback_data). Un botón por fila."""
    return {"inline_keyboard": [[{"text": texto, "callback_data": data}] for texto, data in opciones]}


def enviar_mensaje(token, chat_id, texto, botones=None, reply_to_message_id=None):
    try:
        payload = {"chat_id": chat_id, "text": texto}
        if botones:
            payload["reply_markup"] = json.dumps(botones)
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=15)
    except Exception as e:
        print(f"[-] Error al enviar mensaje de Telegram: {e}", flush=True)


def responder_telegram(token, chat_id, texto, reply_to_message_id=None):
    enviar_mensaje(token, chat_id, texto, reply_to_message_id=reply_to_message_id)


def responder_callback_query(token, callback_query_id):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                      json={"callback_query_id": callback_query_id}, timeout=10)
    except Exception:
        pass


def descargar_foto_telegram(token, file_id):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=30)
        file_path = r.json().get("result", {}).get("file_path")
        if not file_path:
            return None, None
        url_descarga = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r_foto = requests.get(url_descarga, timeout=30)
        if r_foto.status_code == 200:
            return r_foto.content, os.path.basename(file_path)
        return None, None
    except Exception as e:
        print(f"[-] Error al descargar foto de Telegram: {e}", flush=True)
        return None, None


# ==============================================================================
# RESOLUCIÓN DE ÁREA Y COLABORADOR (compartido por ambos flujos)
# ==============================================================================
def resolver_area(area_tecleada):
    """Devuelve 'OPERACIONES', 'SAC' o None si no se pudo determinar."""
    if not area_tecleada:
        return None
    norm = normalizar_nombre_cruce(area_tecleada)
    if norm in SINONIMOS_AREA:
        return SINONIMOS_AREA[norm]
    coincidencia = difflib.get_close_matches(norm, list(SINONIMOS_AREA.keys()), n=1, cutoff=0.75)
    if coincidencia:
        return SINONIMOS_AREA[coincidencia[0]]
    return None


def resolver_colaborador(nombre_tecleado, area_resuelta):
    """
    Devuelve (tecnico_para_guardar, encontrado_bool). Para 'OPERACIONES' busca
    en personal_tecnico.txt; para 'SAC' busca en personal_sac.txt (aplanado) y
    etiqueta el resultado con su departamento real, igual que ya hace el
    formulario manual de Expedientes ("NOMBRE (DEPARTAMENTO)").
    """
    if area_resuelta == 'OPERACIONES':
        lista_tecnicos = cargar_personal("personal_tecnico.txt")
        nombre_resuelto, _ = resolver_tecnico_por_similitud(nombre_tecleado, lista_tecnicos)
        encontrado = normalizar_nombre_cruce(nombre_resuelto) in {normalizar_nombre_cruce(n) for n in lista_tecnicos}
        return nombre_resuelto, encontrado

    dict_admin = cargar_personal_admin("personal_sac.txt")
    nombre_a_depto = {}
    todos_los_nombres = []
    for depto, empleados in dict_admin.items():
        for emp in empleados:
            nombre_a_depto[normalizar_nombre_cruce(emp)] = depto
            todos_los_nombres.append(emp)

    nombre_resuelto, _ = resolver_tecnico_por_similitud(nombre_tecleado, todos_los_nombres)
    norm_resuelto = normalizar_nombre_cruce(nombre_resuelto)
    if norm_resuelto in nombre_a_depto:
        depto_real = nombre_a_depto[norm_resuelto]
        return f"{nombre_resuelto} ({depto_real})", True
    return nombre_resuelto, False


def parse_fecha_libre(texto):
    """Intenta leer una fecha escrita a mano en DD/MM/YYYY, DD-MM-YYYY o YYYY-MM-DD."""
    texto = (texto or "").strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


# ==============================================================================
# GUARDADO EN EXPEDIENTES (Sheets + GCS) -- estilo gspread directo, sin
# depender de st.connection (no existe fuera de Streamlit).
# ==============================================================================
def guardar_falta(worksheet_exp, tecnico, tipo_falta, fecha_incidencia_str, comentario, supervisor, url_foto=""):
    try:
        nueva_fila = [
            get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
            tecnico,
            tipo_falta,
            fecha_incidencia_str,
            comentario,
            url_foto,
            supervisor,
        ]
        nuevo_df = pd.DataFrame([nueva_fila], columns=COLS_EXPEDIENTE)

        df_gcs = leer_espejo_gcs(NOMBRE_BUCKET, "expedientes_maestro.csv")
        if df_gcs is not None and not df_gcs.empty:
            if len(df_gcs.columns) == len(COLS_EXPEDIENTE):
                df_gcs.columns = COLS_EXPEDIENTE
            df_final_gcs = pd.concat([df_gcs, nuevo_df], ignore_index=True)
        else:
            df_final_gcs = nuevo_df
        sobrescribir_archivo_gcs(df_final_gcs, NOMBRE_BUCKET, "expedientes_maestro.csv")

        registros_actuales = worksheet_exp.get_all_values()
        if len(registros_actuales) <= 1:
            worksheet_exp.update(values=[COLS_EXPEDIENTE] + nuevo_df.values.tolist(), range_name='A1')
        else:
            worksheet_exp.append_row(nueva_fila, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"[-] Error al guardar falta en Expedientes: {e}", flush=True)
        return False


def texto_resumen(estado):
    return (
        f"📋 Resumen del reporte:\n"
        f"Área: {estado['area']}\n"
        f"Motivo: {estado['motivo']}\n"
        f"Colaborador: {estado['colaborador']}\n"
        f"Fecha: {estado['fecha']}\n"
        f"Descripción: {estado['descripcion']}\n"
        f"Foto: {'Sí' if estado.get('url_foto') else 'No'}\n\n"
        f"¿Guardar este reporte?"
    )


# ==============================================================================
# FORMULARIO GUIADO CON BOTONES (/falta)
# ==============================================================================
def iniciar_flujo(token, chat_id, user_id):
    ESTADOS_CONVERSACION[(chat_id, user_id)] = {"paso": "area"}
    enviar_mensaje(
        token, chat_id,
        "📝 Nuevo reporte de falta/incidencia.\n¿Cuál es el área del colaborador?",
        teclado_botones([("Operaciones (técnicos/campo)", "area|OPERACIONES"), ("SAC / Administrativo", "area|SAC")])
    )


def cancelar_flujo(token, chat_id, user_id):
    ESTADOS_CONVERSACION.pop((chat_id, user_id), None)
    enviar_mensaje(token, chat_id, "❌ Reporte cancelado.")


def procesar_callback(token, chat_id_esperado, worksheet_exp, callback_query):
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    user_id = callback_query.get("from", {}).get("id")
    data = callback_query.get("data", "")
    responder_callback_query(token, callback_query.get("id"))

    if str(chat_id) != str(chat_id_esperado):
        return

    clave = (chat_id, user_id)
    estado = ESTADOS_CONVERSACION.get(clave)
    if estado is None:
        return  # botón de un flujo viejo/expirado

    if "|" not in data:
        return
    tipo, valor = data.split("|", 1)

    if tipo == "area" and estado.get("paso") == "area":
        estado["area"] = valor
        estado["paso"] = "motivo"
        motivos = MOTIVOS_OPERACIONES if valor == "OPERACIONES" else MOTIVOS_SAC
        enviar_mensaje(
            token, chat_id, "¿Cuál es el motivo?",
            teclado_botones([(m, f"motivo|{i}") for i, m in enumerate(motivos)])
        )

    elif tipo == "motivo" and estado.get("paso") == "motivo":
        motivos = MOTIVOS_OPERACIONES if estado["area"] == "OPERACIONES" else MOTIVOS_SAC
        idx = int(valor)
        motivo_elegido = motivos[idx] if 0 <= idx < len(motivos) else "Otro"

        if motivo_elegido == "Otro":
            estado["paso"] = "motivo_otro"
            enviar_mensaje(token, chat_id, "Escribe el motivo específico:")
            return

        estado["motivo"] = motivo_elegido

        if motivo_elegido == "Reco / Cambio de Postes":
            # Igual que en el formulario manual: esta falta siempre queda a
            # nombre de "RECO", no se pide colaborador.
            estado["colaborador"] = "RECO"
            estado["paso"] = "fecha"
            _preguntar_fecha(token, chat_id)
        else:
            estado["paso"] = "colaborador"
            enviar_mensaje(token, chat_id, "¿Quién es el colaborador? Escribe su nombre.")

    elif tipo == "fecha" and estado.get("paso") == "fecha":
        hoy = get_honduras_time()
        if valor == "hoy":
            estado["fecha"] = hoy.strftime("%d/%m/%Y")
            estado["paso"] = "descripcion"
            enviar_mensaje(token, chat_id, "Describe lo sucedido:")
        elif valor == "ayer":
            estado["fecha"] = (hoy - timedelta(days=1)).strftime("%d/%m/%Y")
            estado["paso"] = "descripcion"
            enviar_mensaje(token, chat_id, "Describe lo sucedido:")
        else:  # otra
            estado["paso"] = "fecha_texto"
            enviar_mensaje(token, chat_id, "Escribe la fecha (DD/MM/AAAA):")

    elif tipo == "foto" and estado.get("paso") == "foto":
        if valor == "si":
            estado["paso"] = "foto_espera"
            enviar_mensaje(token, chat_id, "Envía la foto ahora.")
        else:
            estado["url_foto"] = ""
            estado["paso"] = "confirmar"
            enviar_mensaje(token, chat_id, texto_resumen(estado),
                            teclado_botones([("✅ Guardar", "confirmar|si"), ("❌ Cancelar", "confirmar|no")]))

    elif tipo == "confirmar" and estado.get("paso") == "confirmar":
        if valor == "si":
            remitente = callback_query.get("from", {})
            supervisor = f"{remitente.get('first_name', '')} {remitente.get('last_name', '')}".strip() or remitente.get('username', 'Telegram')
            exito = guardar_falta(
                worksheet_exp,
                tecnico=estado["colaborador"],
                tipo_falta=estado["motivo"].strip().upper(),
                fecha_incidencia_str=estado["fecha"],
                comentario=estado["descripcion"] or "Sin descripción",
                supervisor=supervisor,
                url_foto=estado.get("url_foto", ""),
            )
            if exito:
                enviar_mensaje(token, chat_id, f"✅ Falta registrada para {estado['colaborador']} ({estado['motivo']}).")
            else:
                enviar_mensaje(token, chat_id, "❌ Hubo un error guardando el reporte. Avisa a soporte.")
        else:
            enviar_mensaje(token, chat_id, "❌ Reporte cancelado, no se guardó nada.")
        ESTADOS_CONVERSACION.pop(clave, None)


def _preguntar_fecha(token, chat_id):
    enviar_mensaje(
        token, chat_id, "¿Cuándo ocurrió?",
        teclado_botones([("Hoy", "fecha|hoy"), ("Ayer", "fecha|ayer"), ("Otra fecha", "fecha|otra")])
    )


def procesar_respuesta_texto_flujo(token, chat_id, worksheet_exp, message, estado):
    """Atiende los pasos del formulario guiado que esperan texto libre (no botones)."""
    texto = (message.get("text") or "").strip()
    paso = estado.get("paso")

    if paso == "motivo_otro":
        estado["motivo"] = texto
        estado["paso"] = "colaborador"
        enviar_mensaje(token, chat_id, "¿Quién es el colaborador? Escribe su nombre.")
        return

    if paso == "colaborador":
        tecnico_final, encontrado = resolver_colaborador(texto, estado["area"])
        if not encontrado:
            enviar_mensaje(token, chat_id, f"⚠️ No encontré a \"{texto}\" en el listado de {estado['area']}. Escribe el nombre de nuevo (o /cancelar).")
            return
        estado["colaborador"] = tecnico_final
        estado["paso"] = "fecha"
        _preguntar_fecha(token, chat_id)
        return

    if paso == "fecha_texto":
        fecha_parseada = parse_fecha_libre(texto)
        if not fecha_parseada:
            enviar_mensaje(token, chat_id, "⚠️ No entendí esa fecha. Escríbela como DD/MM/AAAA (ej. 19/09/2026).")
            return
        estado["fecha"] = fecha_parseada.strftime("%d/%m/%Y")
        estado["paso"] = "descripcion"
        enviar_mensaje(token, chat_id, "Describe lo sucedido:")
        return

    if paso == "descripcion":
        estado["descripcion"] = texto or "Sin descripción"
        estado["paso"] = "foto"
        enviar_mensaje(
            token, chat_id, "¿Quieres adjuntar una foto?",
            teclado_botones([("Sí, la envío ahora", "foto|si"), ("No, continuar", "foto|no")])
        )
        return

    if paso == "foto_espera":
        fotos = message.get("photo")
        if not fotos:
            enviar_mensaje(token, chat_id, "Envía una foto (o escribe /cancelar).")
            return
        file_id = fotos[-1].get("file_id")
        contenido, nombre_archivo = descargar_foto_telegram(token, file_id)
        url_subida = subir_archivo_catbox(contenido, nombre_archivo or "foto_telegram.jpg") if contenido else None
        estado["url_foto"] = url_subida or ""
        if not url_subida:
            enviar_mensaje(token, chat_id, "⚠️ No se pudo subir la foto, se continúa sin ella.")
        estado["paso"] = "confirmar"
        enviar_mensaje(token, chat_id, texto_resumen(estado),
                        teclado_botones([("✅ Guardar", "confirmar|si"), ("❌ Cancelar", "confirmar|no")]))
        return


# ==============================================================================
# TEXTO LIBRE CON FORMATO FIJO (alternativa a /falta)
# ==============================================================================
def parse_mensaje_falta(texto):
    """
    Espera un formato de líneas "Etiqueta: valor". La primera línea debe ser
    la palabra "FALTA" (sin importar mayúsculas/acentos) para que el bot sepa
    que este mensaje SÍ es un reporte y no charla normal del grupo.
    Devuelve un dict con las claves colaborador/area/motivo/fecha/descripcion
    (cadena vacía si no vino), o None si el mensaje no es un reporte de falta.
    """
    if not texto:
        return None
    lineas = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    if not lineas:
        return None
    if normalizar_nombre_cruce(lineas[0]) != 'FALTA':
        return None

    campos = {'colaborador': '', 'area': '', 'motivo': '', 'fecha': '', 'descripcion': ''}
    mapa_etiquetas = {
        'COLABORADOR': 'colaborador', 'TECNICO': 'colaborador', 'NOMBRE': 'colaborador',
        'AREA': 'area', 'DEPARTAMENTO': 'area',
        'MOTIVO': 'motivo', 'TIPO': 'motivo',
        'FECHA': 'fecha',
        'DESCRIPCION': 'descripcion', 'DETALLE': 'descripcion', 'COMENTARIO': 'descripcion',
    }
    for linea in lineas[1:]:
        if ':' not in linea:
            continue
        etiqueta, valor = linea.split(':', 1)
        etiqueta_norm = normalizar_nombre_cruce(etiqueta)
        clave = mapa_etiquetas.get(etiqueta_norm)
        if clave:
            campos[clave] = valor.strip()
    return campos


def procesar_mensaje_libre(token, chat_id, worksheet_exp, message):
    texto = message.get("text") or message.get("caption") or ""
    campos = parse_mensaje_falta(texto)
    if campos is None:
        return  # no es un reporte de falta, es charla normal del grupo

    message_id = message.get("message_id")
    remitente = message.get("from", {})
    supervisor = f"{remitente.get('first_name', '')} {remitente.get('last_name', '')}".strip() or remitente.get('username', 'Telegram')

    faltantes = [campo for campo in ('colaborador', 'area', 'motivo') if not campos.get(campo)]
    if faltantes:
        responder_telegram(
            token, chat_id,
            f"⚠️ Faltan estos campos en el reporte: {', '.join(faltantes)}. No se guardó nada, corrígelo y vuelve a mandarlo completo.",
            message_id
        )
        return

    area_resuelta = resolver_area(campos['area'])
    if area_resuelta is None:
        responder_telegram(
            token, chat_id,
            f"⚠️ No reconozco el área \"{campos['area']}\". Usa \"Operaciones\" o \"SAC\". No se guardó nada.",
            message_id
        )
        return

    tecnico_final, encontrado = resolver_colaborador(campos['colaborador'], area_resuelta)
    if not encontrado:
        responder_telegram(
            token, chat_id,
            f"⚠️ No encontré a \"{campos['colaborador']}\" en el listado de {area_resuelta}. Revisa el nombre y vuelve a mandarlo. No se guardó nada.",
            message_id
        )
        return

    fecha_incidencia_str = campos['fecha'].strip()
    fecha_parseada = parse_fecha_libre(fecha_incidencia_str) if fecha_incidencia_str else None
    fecha_incidencia_str = fecha_parseada.strftime('%d/%m/%Y') if fecha_parseada else get_honduras_time().strftime('%d/%m/%Y')

    url_foto = ""
    fotos = message.get("photo")
    if fotos:
        file_id = fotos[-1].get("file_id")  # la última es la de mayor resolución
        contenido, nombre_archivo = descargar_foto_telegram(token, file_id)
        if contenido:
            url_subida = subir_archivo_catbox(contenido, nombre_archivo or "foto_telegram.jpg")
            if url_subida:
                url_foto = url_subida

    exito = guardar_falta(
        worksheet_exp,
        tecnico=tecnico_final,
        tipo_falta=campos['motivo'].strip().upper(),
        fecha_incidencia_str=fecha_incidencia_str,
        comentario=campos.get('descripcion', '').strip() or "Sin descripción",
        supervisor=supervisor,
        url_foto=url_foto,
    )

    if exito:
        responder_telegram(token, chat_id, f"✅ Falta registrada para {tecnico_final} ({campos['motivo']}).", message_id)
    else:
        responder_telegram(token, chat_id, "❌ Hubo un error guardando el reporte. Avisa a soporte.", message_id)


# ==============================================================================
# ENRUTADOR PRINCIPAL DE MENSAJES
# ==============================================================================
def procesar_mensaje(token, chat_id_esperado, worksheet_exp, message):
    chat_id = message.get("chat", {}).get("id")
    if str(chat_id) != str(chat_id_esperado):
        return  # mensaje de otro chat -- el bot podría estar en más de un grupo

    user_id = message.get("from", {}).get("id")
    texto = (message.get("text") or "").strip()
    comando = texto.split('@')[0].lower()  # quita el "@NombreDelBot" que Telegram agrega en grupos

    if comando == "/falta":
        iniciar_flujo(token, chat_id, user_id)
        return

    if comando == "/cancelar":
        if (chat_id, user_id) in ESTADOS_CONVERSACION:
            cancelar_flujo(token, chat_id, user_id)
        return

    estado = ESTADOS_CONVERSACION.get((chat_id, user_id))
    if estado is not None:
        procesar_respuesta_texto_flujo(token, chat_id, worksheet_exp, message, estado)
        return

    # Ninguna conversación guiada activa: probar el formato de texto libre.
    procesar_mensaje_libre(token, chat_id, worksheet_exp, message)


# ==============================================================================
# OFFSET (para no reprocesar mensajes ya atendidos si el script se reinicia)
# ==============================================================================
def leer_offset():
    try:
        with open(RUTA_OFFSET, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def guardar_offset(update_id):
    try:
        with open(RUTA_OFFSET, "w", encoding="utf-8") as f:
            f.write(str(update_id))
    except Exception:
        pass


# ==============================================================================
# BUCLE PRINCIPAL
# ==============================================================================
def main():
    if not HAS_GSPREAD:
        print("[-] Error: falta instalar 'gspread' y 'google-auth' (pip install gspread google-auth).", flush=True)
        return

    secrets_data = cargar_secrets()
    telegram_cfg = secrets_data.get("telegram", {})
    token = telegram_cfg.get("token")
    chat_id_esperado = telegram_cfg.get("chat_id")
    if not token or not chat_id_esperado:
        print("[-] Falta configurar [telegram] token/chat_id en .streamlit/secrets.toml", flush=True)
        return

    worksheet_exp = conectar_hoja_expedientes(secrets_data)

    offset = leer_offset()
    print("=" * 60, flush=True)
    print("🤖 BOT DE TELEGRAM DE FALTAS -- escuchando el grupo...", flush=True)
    print("   Formulario guiado: /falta", flush=True)
    print("=" * 60, flush=True)

    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset + 1
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params, timeout=40)
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"]
                mensaje = update.get("message")
                callback = update.get("callback_query")
                try:
                    if mensaje:
                        procesar_mensaje(token, chat_id_esperado, worksheet_exp, mensaje)
                    elif callback:
                        procesar_callback(token, chat_id_esperado, worksheet_exp, callback)
                except Exception as e_msg:
                    print(f"[-] Error procesando una actualización: {e_msg}", flush=True)
                guardar_offset(offset)
        except Exception as e_loop:
            print(f"[-] Error en el ciclo de escucha: {e_loop}", flush=True)
            time.sleep(10)


if __name__ == '__main__':
    main()
