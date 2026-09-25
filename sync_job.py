# ==============================================================================
# SCRIPT DE SINCRONIZACIÓN AUTOMATIZADA EN SEGUNDO PLANO
# Carga principal en Google Sheets y respaldo espejo en GCS
# ==============================================================================
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import time
import json
import toml # Añadido para leer los secretos sin usar Streamlit

# ==============================================================================
# Forzar UTF-8 en la salida estándar. En Windows, cuando este script corre vía
# un .bat con la salida redirigida a un archivo (>> log_sync.txt), la consola
# usa por defecto una codificación vieja (cp1252) que no soporta emojis (🚀,
# ✅, etc.) y el script se cae con UnicodeEncodeError. Esto lo evita sin
# depender de configuraciones externas (chcp, variables de entorno, etc.)
# ==============================================================================
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Importar gspread y credenciales nativas de Google
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

# Asegura la visibilidad de tools.py en el entorno de ejecución
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tools import (
    consultar_api_ordenes,
    depurar_api_con_dispositivos,
    sobrescribir_archivo_gcs,
    leer_espejo_gcs,
    get_honduras_time,
    procesar_fechas_seguro,
    calcular_offline_y_alertas,
    PATRON_ASIGNADAS_VIVA_STR as PATRON_VIVAS,
    ACTIVIDADES_BASURA,
    NOMBRE_BUCKET_SISTEMA as NOMBRE_BUCKET
)

def ejecutar_sincronizacion_background(dias_atras=55):
    if not HAS_GSPREAD:
        print("[-] Error: Las librerías 'gspread' o 'google-auth' no están instaladas.")
        return

    print(f"[{datetime.now()}] Iniciando descarga automática desde la API de Cepheus ({dias_atras} días atrás)...")

    # 1. Definir rango de extracción
    #
    # dias_atras=55 es la ventana normal del ciclo cada 15 min. Un valor mayor
    # se usa SOLO para el relleno manual de historial (ver --backfill al final
    # de este archivo): las órdenes CERRADAS que Cepheus nunca llegó a
    # devolver dentro de esos 55 días (porque cerraron antes de esa ventana, o
    # el robot estuvo caído en ese momento) nunca entran al historial
    # acumulado -- una vez que una orden cerrada SÍ queda en Sheet1 una vez,
    # el resto del ciclo (más abajo) la conserva para siempre sin volver a
    # pedirla, pero si nunca se capturó no hay forma de que reaparezca sola.
    ahora_local = get_honduras_time()
    fecha_api = ahora_local - timedelta(days=dias_atras)
    fecha_dt_api = datetime.combine(fecha_api.date(), datetime.min.time())

    # 2. Descargar órdenes en vivo desde la API de Cepheus
    df_api_raw = consultar_api_ordenes(fecha_dt_api)
    if df_api_raw is None or df_api_raw.empty:
        print("[-] Fallo de descarga: La API de Cepheus no devolvió registros.")
        return

    # 3. CONEXIÓN DIRECTA A GOOGLE SHEETS SIN STREAMLIT
    try:
        # Leemos el archivo secrets.toml directamente
        ruta_secrets = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
        secrets_data = toml.load(ruta_secrets)
        
        creds_dict = secrets_data["connections"]["gsheets"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        # Abrir la hoja por URL
        url_bd = secrets_data["url_base_datos"]
        spreadsheet = client.open_by_url(url_bd)
        worksheet = spreadsheet.worksheet("Sheet1")

        # Leer los datos de Sheets para consolidación
        registros_crudos = worksheet.get_all_records()
        df_sheets_master = pd.DataFrame(registros_crudos)
    except Exception as e_sheets:
        print(f"[-] Fallo al conectar o leer desde Google Sheets: {e_sheets}")
        return

    # 4. Cruzar con el catálogo de dispositivos FTTX
    df_fttx_cloud = pd.DataFrame()
    try:
        worksheet_fttx = spreadsheet.worksheet("FTTX")
        registros_fttx = worksheet_fttx.get_all_records()
        df_fttx_cloud = pd.DataFrame(registros_fttx)
    except Exception as e_fttx_sheets:
        print(f"[!] No se pudo leer el catálogo FTTX desde Google Sheets: {e_fttx_sheets}. Intentando respaldo en GCS...")

    if df_fttx_cloud is None or df_fttx_cloud.empty:
        df_fttx_cloud = leer_espejo_gcs(NOMBRE_BUCKET, "fttx_activo.csv")

    if df_fttx_cloud is None or df_fttx_cloud.empty:
        print("[-] Fallo: No se pudo localizar el catálogo FTTX ni en Google Sheets ni en GCS. Se aborta este ciclo.")
        return
    else:
        print(f"  -> [+] Catálogo FTTX cargado con {len(df_fttx_cloud)} registros.")

    df_depurado = depurar_api_con_dispositivos(df_api_raw, df_fttx_cloud)
    df_depurado = procesar_fechas_seguro(df_depurado, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])

    # 5. Calcular campos técnicos básicos
    ahora_ts = pd.Timestamp(ahora_local)
    df_depurado['DIAS_RETRASO'] = (ahora_ts.normalize() - df_depurado['FECHA_APE'].dt.normalize()).dt.days.fillna(0).astype(int)

    if 'TECNICO' in df_depurado.columns:
        mask_josue = df_depurado['TECNICO'].astype(str).str.strip().str.upper() == 'JOSUE MIGUEL SAUCEDA'
        df_depurado.loc[mask_josue, 'DIAS_RETRASO'] = 0

    df_depurado['MINUTOS_CALC'] = (df_depurado['HORA_LIQ'] - df_depurado['HORA_INI']).dt.total_seconds() / 60
    df_depurado = calcular_offline_y_alertas(df_depurado)

    # 6. CONSOLIDACIÓN DE DATOS (Filtros y uniones)
    if df_sheets_master is not None and not df_sheets_master.empty:
        df_sheets_master.columns = df_sheets_master.columns.str.upper().str.strip()

        if 'NUM' in df_sheets_master.columns:
            df_sheets_master['NUM'] = df_sheets_master['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            df_sheets_master.loc[df_sheets_master['NUM'] == 'nan', 'NUM'] = 'N/D'

        if 'ACTIVIDAD' in df_sheets_master.columns:
            mask_basura = df_sheets_master['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
            df_sheets_master = df_sheets_master[~mask_basura].copy()

        if 'EMPRESA' in df_sheets_master.columns:
            empresa_upper_master = df_sheets_master['EMPRESA'].astype(str).str.strip().str.upper()
            mask_otra_empresa_master = (empresa_upper_master != '') & (empresa_upper_master != 'NAN') & (empresa_upper_master != 'NONE') & (~empresa_upper_master.str.contains('ISCA', na=False))
            df_sheets_master = df_sheets_master[~mask_otra_empresa_master].copy()

        mask_vivas_nube = df_sheets_master['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
        df_historial_cerrado = df_sheets_master[~mask_vivas_nube].copy()
        df_consolidado = pd.concat([df_historial_cerrado, df_depurado])
    else:
        df_consolidado = df_depurado

    if 'NUM' in df_consolidado.columns:
        df_consolidado['TIENE_LIQ'] = df_consolidado.get('HORA_LIQ').notna()
        df_consolidado = df_consolidado.sort_values(by=['TIENE_LIQ'], ascending=True)
        df_valid_num = df_consolidado[df_consolidado['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_nd = df_consolidado[df_consolidado['NUM'] == 'N/D']
        df_consolidado = pd.concat([df_valid_num, df_nd]).drop(columns=['TIENE_LIQ'], errors='ignore')

    df_final = df_consolidado.copy()
    for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
        if c_date in df_final.columns:
            df_final[c_date] = pd.to_datetime(df_final[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')

    df_final = df_final.fillna("")

    # 7. CARGA EN GOOGLE SHEETS
    try:
        valores_actualizar = [df_final.columns.values.tolist()] + df_final.values.tolist()
        filas_nuevas = len(valores_actualizar)
        columnas_nuevas = len(df_final.columns)

        # Dimensiones de la hoja ANTES de escribir, para poder recortar el
        # sobrante DESPUES de que los datos nuevos ya quedaron confirmados.
        filas_previas = worksheet.row_count
        columnas_previas = worksheet.col_count

        # ORDEN CRITICO: se escribe primero, se recorta el sobrante despues --
        # NUNCA al reves. Antes se hacia worksheet.clear() ANTES de escribir los
        # datos nuevos: si update() fallaba por cualquier motivo despues del
        # clear() (cuota excedida, timeout de red, dato invalido), Sheet1
        # quedaba COMPLETAMENTE VACIA hasta el siguiente ciclo exitoso -- que es
        # exactamente el sintoma detectado en produccion (hoja en blanco, sin
        # encabezados ni datos). Escribiendo primero, un fallo aqui deja los
        # datos del ciclo ANTERIOR intactos en vez de borrarlos a ciegas.
        worksheet.update(values=valores_actualizar, range_name='A1')

        # Se recorta solo el sobrante de la version anterior (si tenia mas
        # filas o columnas que la nueva), para que no queden filas viejas
        # colgando debajo de los datos frescos. Si esto llega a fallar, los
        # datos nuevos YA quedaron escritos -- no se pierde nada.
        try:
            if filas_previas > filas_nuevas or columnas_previas > columnas_nuevas:
                worksheet.resize(rows=filas_nuevas, cols=columnas_nuevas)
        except Exception as e_recorte:
            print(f"[!] Aviso: no se pudo recortar el sobrante de la hoja anterior (los datos nuevos ya quedaron escritos): {e_recorte}")

        print("[+] Carga exitosa: Google Sheets actualizado correctamente.")
    except Exception as e_write:
        print(f"[-] Fallo al intentar escribir en Google Sheets: {e_write}")
        return

    # 8. RESPALDO ESPEJO EN GCS
    try:
        gcs_ok = sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET, "historial_maestro.csv")
        if gcs_ok:
            print("[+] Respaldo exitoso: Copia de alta velocidad subida a GCS.")
        else:
            print("[-] Error menor al respaldar en GCS (Sheets se guardó bien).")
    except Exception as e_gcs:
        print(f"[-] Error menor al respaldar en GCS: {e_gcs}")

    # 9. ALERTAS POR CORREO: órdenes nuevas de clientes VIP y molex en
    # comentarios de cierre de soporte. Solo se envía correo si hay algo nuevo.
    _procesar_alertas(spreadsheet, df_depurado, secrets_data, ahora_local)


def _procesar_alertas(spreadsheet, df_depurado, secrets_data, ahora_local):
    """
    Corre las alertas y guarda el resultado de cada una en GCS, para verlo
    desde la app (Configuración -> Correo de alertas) sin abrir el log de esta PC.
    """
    from notificaciones import falta_configuracion
    marca_ciclo = pd.Timestamp(ahora_local).strftime('%Y-%m-%d %H:%M:%S')
    estados = []
    _faltante_correo = falta_configuracion(secrets_data.get("correo", {}))
    if _faltante_correo:
        print(f"  -> [!] Alertas por correo desactivadas: falta en secrets.toml [correo]: {_faltante_correo}")
        estados.append(("Correo", "desactivado", f"falta en secrets.toml de la PC del robot [correo]: {_faltante_correo}"))
    for nombre_alerta, funcion_alerta in (("Clientes VIP", _avisar_ordenes_vip_nuevas),
                                           ("Molex en cierres", _avisar_molex_en_comentarios)):
        try:
            resultado, detalle = funcion_alerta(spreadsheet, df_depurado, secrets_data, ahora_local)
        except Exception as e_alerta:
            resultado, detalle = "error", str(e_alerta)
            print(f"[-] Error en la alerta de {nombre_alerta} (la sincronización sí se completó): {e_alerta}")
        estados.append((nombre_alerta, resultado, detalle))
    try:
        df_estado = pd.DataFrame(
            [{"ALERTA": a, "RESULTADO": r, "DETALLE": d, "ULTIMO_CICLO": marca_ciclo} for a, r, d in estados]
        )
        sobrescribir_archivo_gcs(df_estado, NOMBRE_BUCKET, ARCHIVO_ESTADO_ALERTAS)
    except Exception as e_estado:
        print(f"[-] No se pudo guardar el estado de las alertas en GCS: {e_estado}")


# Resultado del último ciclo de alertas, que la app muestra en Configuración.
ARCHIVO_ESTADO_ALERTAS = "estado_alertas_robot.csv"

# Órdenes ya avisadas por correo (NUM -> fecha del aviso), una por alerta,
# para no repetir el correo en cada ciclo de 15 minutos. Viven junto al
# script, en la PC del robot.
_DIR_SCRIPT = os.path.dirname(os.path.abspath(__file__))
RUTA_VIP_AVISADAS = os.path.join(_DIR_SCRIPT, "vip_avisadas.json")
RUTA_MOLEX_AVISADAS = os.path.join(_DIR_SCRIPT, "molex_avisadas.json")


def _leer_avisadas(ruta):
    """Devuelve el dict de avisadas, {} si aún no existe, o None si no se puede leer."""
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  -> [!] No se pudo leer {ruta} ({e}). No se envía esta alerta para no repetirla; "
              "si el archivo está dañado, bórralo.")
        return None


def _registrar_avisadas(ruta, avisadas, nums, ahora_local):
    marca = pd.Timestamp(ahora_local).strftime('%Y-%m-%d %H:%M:%S')
    avisadas.update({str(num): marca for num in nums})
    # Pasados 30 días una orden ya no entra en la ventana de 24 h, así que se puede olvidar.
    limite = pd.Timestamp(ahora_local) - pd.Timedelta(days=30)
    avisadas = {num: f for num, f in avisadas.items() if pd.to_datetime(f, errors='coerce') >= limite}
    # Se escribe a un temporal y se reemplaza, para que un corte a medias no deje el archivo dañado.
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(avisadas, f, ensure_ascii=False, indent=0)
    os.replace(temporal, ruta)


def _enviar_y_registrar(nombre, nuevas, correo, ruta, avisadas, secrets_data, ahora_local, clave_destinatarios):
    from notificaciones import enviar_correo

    asunto, texto, cuerpo_html = correo
    ok, error = enviar_correo(secrets_data.get("correo", {}), asunto, texto, cuerpo_html,
                              clave_destinatarios=clave_destinatarios)
    ordenes = ", ".join(map(str, nuevas['NUM']))
    if not ok:
        print(f"  -> [!] {len(nuevas)} orden(es) de {nombre} sin avisar por correo: {error}")
        return "error al enviar", f"{len(nuevas)} orden(es) sin avisar ({ordenes}): {error}"
    _registrar_avisadas(ruta, avisadas, nuevas['NUM'], ahora_local)
    print(f"  -> [+] Alerta de {nombre} enviada por correo: {len(nuevas)} orden(es)." + (f" Nota: {error}" if error else ""))
    return "enviado", f"{len(nuevas)} orden(es): {ordenes}" + (f". Nota: {error}" if error else "")


def _avisar_ordenes_vip_nuevas(spreadsheet, df_ordenes, secrets_data, ahora_local):
    from clientes_vip import HOJA_VIP, normalizar_codigos, seleccionar_ordenes_vip_nuevas, armar_correo_vip, diagnostico_vip

    try:
        df_vip = pd.DataFrame(spreadsheet.worksheet(HOJA_VIP).get_all_records())
    except Exception as e:
        print(f"  -> [i] Sin hoja '{HOJA_VIP}' de clientes VIP en Sheets ({e}); no se revisan órdenes VIP.")
        return "sin lista VIP", f"no se encontró la hoja '{HOJA_VIP}' en la base de datos ({e})"
    if df_vip.empty or 'CLIENTE' not in df_vip.columns:
        return "sin lista VIP", f"la hoja '{HOJA_VIP}' está vacía o no tiene la columna CLIENTE"
    df_vip['CLIENTE'] = normalizar_codigos(df_vip['CLIENTE'])
    for columna in ('NOMBRE', 'CLASE'):
        if columna not in df_vip.columns:
            df_vip[columna] = ''

    avisadas = _leer_avisadas(RUTA_VIP_AVISADAS)
    if avisadas is None:
        return "error", f"no se pudo leer {RUTA_VIP_AVISADAS}"
    nuevas = seleccionar_ordenes_vip_nuevas(df_ordenes, df_vip, avisadas.keys(), ahora_local)
    if nuevas.empty:
        detalle = diagnostico_vip(df_ordenes, df_vip, avisadas.keys(), ahora_local)
        print(f"  -> [i] Alerta de clientes VIP: nada nuevo que avisar. {detalle}")
        return "sin novedades", detalle
    return _enviar_y_registrar("clientes VIP", nuevas, armar_correo_vip(nuevas), RUTA_VIP_AVISADAS,
                               avisadas, secrets_data, ahora_local, "destinatarios_vip")


def _avisar_molex_en_comentarios(spreadsheet, df_ordenes, secrets_data, ahora_local):
    from materiales import seleccionar_molex_en_comentarios, armar_correo_molex

    avisadas = _leer_avisadas(RUTA_MOLEX_AVISADAS)
    if avisadas is None:
        return "error", f"no se pudo leer {RUTA_MOLEX_AVISADAS}"
    nuevas = seleccionar_molex_en_comentarios(df_ordenes, avisadas.keys(), ahora_local)
    if nuevas.empty:
        print("  -> [i] Alerta de molex en cierres: sin cierres nuevos que mencionen molex.")
        return "sin novedades", "ningún cierre de soporte nuevo (últimas 24 h) menciona molex"
    return _enviar_y_registrar("molex en cierres", nuevas, armar_correo_molex(nuevas), RUTA_MOLEX_AVISADAS,
                               avisadas, secrets_data, ahora_local, "destinatarios")


def _ejecutar_backfill_una_vez(dias_atras):
    """
    Relleno de historial de UNA SOLA VEZ: pide a Cepheus una ventana más
    amplia que los 55 días normales, para traer órdenes CERRADAS viejas que el
    ciclo regular nunca llegó a capturar (porque cerraron antes de esos 55
    días, o el robot estuvo caído justo en ese momento). Reutiliza el mismo
    ejecutar_sincronizacion_background(): lee lo que ya hay en Sheet1,
    conserva las cerradas existentes y las combina con lo que traiga esta
    consulta más amplia -- así que es seguro correrlo aunque ya haya datos.
    Se corre UNA vez y termina (no entra al bucle de 15 minutos), para no
    quedarse pidiendo esa ventana ancha repetidamente y gastar de más el
    cupo de 5 consultas/hora que impone Cepheus.

    LÍMITE DURO DE CEPHEUS: confirmado en producción que su API rechaza
    cualquier fechaInicio de más de ~2 meses atrás (responde 400 con
    "La fecha no puede ser anterior a 2 meses"). No es un límite nuestro y no
    se puede evitar desde este script -- una orden cerrada hace más de ~2
    meses que el robot nunca haya capturado en su momento ya NO se puede
    recuperar por esta vía, para nadie. Por eso dias_atras se topa a 60 más
    abajo: pedir más solo hace que Cepheus rechace la consulta entera.
    """
    if dias_atras > 60:
        print(f"[!] Cepheus no acepta fechaInicio de más de ~60 días atrás (pediste {dias_atras}). Se ajusta a 60.", flush=True)
        dias_atras = 60
    print("="*60, flush=True)
    print(f"🔧 RELLENO DE HISTÓRICO (una sola vez): últimos {dias_atras} días", flush=True)
    print("="*60, flush=True)
    try:
        ejecutar_sincronizacion_background(dias_atras=dias_atras)
    except Exception as e_backfill:
        print(f"[-] Falla durante el relleno de histórico: {e_backfill}", flush=True)
    print("="*60, flush=True)
    print("✅ Relleno terminado. Revisa arriba cuántas órdenes se descargaron.", flush=True)
    print("="*60, flush=True)


if __name__ == '__main__':
    # Uso: python sync_job.py --backfill 60
    # Trae los últimos N días (máximo 60 -- límite impuesto por Cepheus, ver
    # _ejecutar_backfill_una_vez) en vez de los 55 de siempre, UNA sola vez, y
    # termina -- no reemplaza al ciclo normal de 15 minutos.
    # Uso: python sync_job.py --probar-correo
    # Manda un correo de prueba a destinatarios_vip con la sección [correo]
    # del secrets.toml de esta PC, y termina.
    if len(sys.argv) >= 2 and sys.argv[1] == '--probar-correo':
        from notificaciones import enviar_correo_prueba, lista_destinatarios
        _config = toml.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")).get("correo", {})
        _ok, _error = enviar_correo_prueba(_config, clave_destinatarios="destinatarios_vip", origen="el robot de sincronización")
        if _ok:
            print(f"✅ Correo de prueba enviado a: {', '.join(lista_destinatarios(_config, 'destinatarios_vip'))}", flush=True)
            if _error:
                print(f"   Nota: {_error}", flush=True)
        else:
            print(f"❌ No se pudo enviar: {_error}", flush=True)
        sys.exit(0 if _ok else 1)

    if len(sys.argv) >= 2 and sys.argv[1] == '--backfill':
        _dias_backfill = int(sys.argv[2]) if len(sys.argv) >= 3 else 60
        _ejecutar_backfill_una_vez(_dias_backfill)
        sys.exit(0)

    print("="*60, flush=True)
    print("🚀 INICIANDO DEMONIO DE SINCRONIZACIÓN MAXCOM PRO", flush=True)
    print("="*60, flush=True)

    ruta_heartbeat = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.txt")

    while True:
        # ======================================================================
        # TODO el cuerpo del ciclo va dentro de este try/except (no solo la
        # sincronización). Antes, los print() de cierre de ciclo quedaban
        # fuera de cualquier protección: si uno de ellos fallaba (por ejemplo,
        # el archivo de log bloqueado un instante por el antivirus o por
        # tenerlo abierto en Notepad), la excepción mataba el proceso completo
        # sin dejar rastro, aunque la PC siguiera encendida.
        # ======================================================================
        try:
            ejecutar_sincronizacion_background()
        except Exception as e_critico:
            try:
                print(f"[-] Falla crítica en el ciclo actual. Se reintentará en la siguiente ventana. Detalle: {e_critico}", flush=True)
            except Exception:
                pass

        try:
            print("="*60, flush=True)
            hora_prox = (datetime.now() + timedelta(minutes=15)).strftime("%H:%M:%S")
            print(f"⏳ Ciclo terminado. Esperando 15 minutos. Próxima ejecución a las: {hora_prox}", flush=True)
        except Exception:
            # Si hasta el print de cierre de ciclo falla (log bloqueado, disco
            # lleno, etc.), no se debe dejar morir el demonio por esto.
            pass

        # Heartbeat: se sobrescribe en cada vuelta del ciclo. Si esta hora deja
        # de avanzar mientras la PC sigue encendida, es la prueba de que el
        # proceso murió (o quedó colgado) justo después de la última escritura.
        try:
            with open(ruta_heartbeat, "w", encoding="utf-8") as f_hb:
                f_hb.write(f"Último ciclo completado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        except Exception:
            pass

        time.sleep(900)
