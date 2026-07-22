# ==============================================================================
# SCRIPT DE SINCRONIZACIÓN AUTOMATIZADA EN SEGUNDO PLANO 
# Carga principal en Google Sheets y respaldo espejo en GCS
# ==============================================================================
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import time

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
    calcular_offline_y_alertas
)

PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
ACTIVIDADES_BASURA = ['ACTUALIZACIONDATOS', 'ACTUALIZACIOFW', 'ACTUALIZAINFOTECNICA', 'ACTUALIZARDATOSTECNICOS', 'ACTUALIZARSENSOR']
NOMBRE_BUCKET = "jovial-trilogy-306216.appspot.com"

def ejecutar_sincronizacion_background():
    if not HAS_GSPREAD:
        print("[-] Error: Las librerías 'gspread' o 'google-auth' no están instaladas.")
        return

    print(f"[{datetime.now()}] Iniciando descarga automática desde la API de Cepheus...")
    
    # 1. Definir rango de extracción (últimos 60 días, el máximo permitido por
    # IT). Con solo 7 días, las órdenes pendientes/sin asignar más antiguas
    # (que son justo las que suelen llevar más tiempo estancadas) quedaban
    # fuera del rango y nunca llegaban a descargarse ni a mostrarse.
    ahora_local = get_honduras_time()
    fecha_api = ahora_local - timedelta(days=55)
    fecha_dt_api = datetime.combine(fecha_api.date(), datetime.min.time())
    
    # 2. Descargar órdenes en vivo desde la API de Cepheus
    df_api_raw = consultar_api_ordenes(fecha_dt_api)
    if df_api_raw is None or df_api_raw.empty:
        print("[-] Fallo de descarga: La API de Cepheus no devolvió registros.")
        return
        
    # 3. CONEXIÓN DIRECTA A GOOGLE SHEETS (Base de datos principal)
    # Se conecta primero porque también sirve de respaldo para el catálogo FTTX
    # si GCS falla (timeouts, conexión reiniciada, etc.)
    try:
        # Extraer credenciales seguras de gsheets desde Streamlit Secrets
        creds_dict = st.secrets["connections"]["gsheets"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Abrir la hoja por URL
        spreadsheet = client.open_by_url(st.secrets["url_base_datos"])
        worksheet = spreadsheet.worksheet("Sheet1")
        
        # Leer los datos de Sheets para consolidación
        registros_crudos = worksheet.get_all_records()
        df_sheets_master = pd.DataFrame(registros_crudos)
    except Exception as e_sheets:
        print(f"[-] Fallo al conectar o leer desde Google Sheets: {e_sheets}")
        return

    # 4. Cruzar con el catálogo de dispositivos FTTX: la escritura a GCS del
    # archivo FTTX viene fallando de forma silenciosa desde app.py, así que
    # Google Sheets (pestaña "FTTX") es la fuente confiable y se intenta
    # primero. GCS queda como respaldo secundario por si algún día se
    # resuelve la escritura ahí (o hay timeout/caída puntual en Sheets).
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

    # Calcular ES_OFFLINE y ALERTA_TIEMPO con la misma lógica que usa la carga
    # manual, para que el flujo automático también detecte equipos caídos.
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
            # Descartar solo si indica explícitamente otra empresa (no vacía)
            empresa_upper_master = df_sheets_master['EMPRESA'].astype(str).str.strip().str.upper()
            mask_otra_empresa_master = (empresa_upper_master != '') & (empresa_upper_master != 'NAN') & (empresa_upper_master != 'NONE') & (~empresa_upper_master.str.contains('ISCA', na=False))
            df_sheets_master = df_sheets_master[~mask_otra_empresa_master].copy()
            
        # Unir historial cerrado con la nueva extracción
        mask_vivas_nube = df_sheets_master['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
        df_historial_cerrado = df_sheets_master[~mask_vivas_nube].copy()
        df_consolidado = pd.concat([df_historial_cerrado, df_depurado])
    else:
        df_consolidado = df_depurado
        
    # Eliminar duplicidades manteniendo el cambio más reciente
    if 'NUM' in df_consolidado.columns:
        df_consolidado['TIENE_LIQ'] = df_consolidado.get('HORA_LIQ').notna()
        df_consolidado = df_consolidado.sort_values(by=['TIENE_LIQ'], ascending=True)
        df_valid_num = df_consolidado[df_consolidado['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_nd = df_consolidado[df_consolidado['NUM'] == 'N/D']
        df_consolidado = pd.concat([df_valid_num, df_nd]).drop(columns=['TIENE_LIQ'], errors='ignore')
        
    # Formatear fechas antes de subir
    df_final = df_consolidado.copy()
    for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
        if c_date in df_final.columns:
            df_final[c_date] = pd.to_datetime(df_final[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')

    # Reemplazar valores nulos/NaN por strings vacíos para evitar incompatibilidades de serialización JSON en Sheets
    df_final = df_final.fillna("")

    # 7. CARGA EN GOOGLE SHEETS (Base de datos principal)
    try:
        # Convertir dataframe a lista de listas para gspread (incluye cabecera)
        valores_actualizar = [df_final.columns.values.tolist()] + df_final.values.tolist()
        
        # Limpiar y reescribir toda la hoja
        worksheet.clear()
        worksheet.update(values=valores_actualizar, range_name='A1')
        print("[+] Carga exitosa: Google Sheets actualizado correctamente.")
    except Exception as e_write:
        print(f"[-] Fallo al intentar escribir en Google Sheets: {e_write}")
        return

    # 8. RESPALDO ESPEJO EN GCS (Caché de alta velocidad para el monitor)
    try:
        gcs_ok = sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET, "historial_maestro.csv")
        if gcs_ok:
            print("[+] Respaldo exitoso: Copia de alta velocidad subida a GCS.")
        else:
            print("[-] Error menor al respaldar en GCS (Sheets se guardó bien; ver detalle de error impreso arriba).")
    except Exception as e_gcs:
        print(f"[-] Error menor al respaldar en GCS (Sheets se guardó bien): {e_gcs}")

if __name__ == '__main__':
    print("="*60)
    print("🚀 INICIANDO DEMONIO DE SINCRONIZACIÓN MAXCOM PRO")
    print("="*60)
    
    while True:
        try:
            # Ejecuta tu función principal intacta
            ejecutar_sincronizacion_background()
        except Exception as e_critico:
            # Evitamos que el programa se caiga permanentemente si un ciclo falla (ej: caída de internet)
            print(f"[-] Falla crítica en el ciclo actual. Se reintentará en la siguiente ventana. Detalle: {e_critico}")
        
        print("="*60)
        hora_prox = (datetime.now() + timedelta(minutes=15)).strftime("%H:%M:%S")
        print(f"⏳ Ciclo terminado. Esperando 15 minutos. Próxima ejecución a las: {hora_prox}")
        
        # 900 segundos = 15 minutos (límite de IT: 5 consultas/hora -> 15 min = 4/hora, con margen)
        time.sleep(900)
