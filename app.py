import streamlit as st
import pandas as pd
import numpy as np
import os
import io
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as dt_time
import re
from streamlit_gsheets import GSheetsConnection
import matplotlib.pyplot as plt
from streamlit_js_eval import streamlit_js_eval
from streamlit.runtime.uploaded_file_manager import UploadedFile
import sys
import time
import unicodedata

# ==============================================================================
# CONFIGURACIÓN DE RUTAS DEL SISTEMA (VITAL)
# ==============================================================================
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ==============================================================================
# IMPORTACIÓN DE MÓDULOS Y HERRAMIENTAS
# ==============================================================================
import expediente
from login import verificar_autenticacion, mostrar_pantalla_login, mostrar_boton_logout
from ui_components import (
    aplicar_estilos_nativos, 
    mostrar_comentario_cierre, 
    mostrar_detalle_avance, 
    aplicar_estilos_df,
    mostrar_seguimientos_tecnico
)

import settings 

try:
    from streamlit_option_menu import option_menu
except ImportError:
    st.error("⚠️ Falta la librería. Asegúrate de agregar 'streamlit-option-menu' a tu requirements.txt")
    option_menu = None

try:
    from auditorv import mostrar_auditoria
except ImportError:
    st.error("⚠️ Falta el archivo 'auditorv.py'. Asegúrate de crearlo en la misma carpeta para ver la Auditoría de Vehículos.")

try:
    import biometrico
except ImportError:
    st.error("⚠️ Falta el archivo 'biometrico.py'. Asegúrate de crearlo en la misma carpeta para ver el reporte Biométrico.")

try:
    import ccalidad
except ImportError:
    st.error("⚠️ Falta el archivo 'ccalidad.py'. Asegúrate de crearlo en la misma carpeta para ver el módulo de Control de Calidad.")


try:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from tools import (
        COLUMNS_MAPPING, 
        es_offline_preciso, 
        procesar_dataframe_base, 
        depurar_archivos_en_crudo,
        depurar_api_con_dispositivos,
        consultar_api_ordenes,
        logica_generar_pdf,
        generar_pdf_cierre_diario,
        generar_pdf_semanal,
        generar_pdf_mensual,
        generar_pdf_trimestral_detallado,
        generar_pdf_primera_orden,
        generar_pdf_pendientes_dispatch,
        get_honduras_time,
        parse_date_ultra_safe,
        procesar_fechas_seguro,
        generar_pdf_tiempos_muertos,
        generar_pdf_promedio_arranque,
        generar_tablas_gerenciales,
        cargar_y_limpiar_crudos_diamante_monitor,
        extraer_seguimientos_tecnico_unificado,
        generar_pdf_ordenes_totales,
        sobrescribir_archivo_gcs,
        leer_espejo_gcs,
        clasificar_materiales,               
        generar_pdf_materiales_mensual,
        normalizar_nombre_cruce,
        guardar_almuerzo,
        cargar_almuerzos,
        cargar_catalogo_tecnicos,
        guardar_orden_manual,
        cargar_ordenes_manuales
    )
except ImportError as e:
    st.error(f"⚠️ Error Crítico de Sistema: No se pudo localizar el archivo 'tools.py'. Detalle: {e}")
    
# ==============================================================================
# CONSTANTES DE NEGOCIO Y CONFIGURACIÓN GLOBAL
# ==============================================================================
# ==============================================================================
# LISTA MAESTRA DE ACTIVIDADES
# ==============================================================================
# Esta es la ÚNICA fuente de verdad sobre qué actividades son visitas técnicas
# reales y por lo tanto pueden mostrarse en la aplicación (Gantt, reportes,
# asignadas, pendientes, PDFs, KPIs). Se aplica como filtro global sobre df_base,
# así que cualquier actividad que NO esté aquí queda descartada desde la raíz del
# pipeline y no puede reaparecer en ninguna vista.
# Para agregar o quitar una actividad, se edita SOLO esta lista.
ACTIVIDADES_PERMITIDAS = [
    'CEQUI', 'INSEQUIPO', 'INSFIBRA', 'INSFIBRACORP', 'INSHFC', 'INS-WA',
    'PEXTERNO', 'PLEXISCA', 'SOP', 'SOPCORP', 'SOPFIBRA', 'SOPFIBRACORP',
    'SOPRECONCORP', 'SOPRECONFIBRA', 'SOPRECONHFC', 'SPLITTEROPT',
    'TRASLADOEXTFIBRA', 'TRASLADOEXTFIBRACORP', 'TRASLADOINTERNOFIBRA',
    'TRASLADOINTFIBRACORP', 'TVADICIONAL'
]

# Las constantes de abajo se mantienen por compatibilidad con el resto del
# código, pero ya NO son listas independientes: todas apuntan a la lista maestra
# para que sea imposible que se vuelvan a desincronizar entre sí.
ACTIVIDADES_VALIDAS_NO_ASIGNADAS = ACTIVIDADES_PERMITIDAS
ACTIVIDADES_GANTT_PERMITIDAS = ACTIVIDADES_PERMITIDAS

PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA|ABIERTA|EJECUCION|ATENDIENDO|TRABAJANDO'

# Estados que dan por TERMINADA una orden. Se usan como lista negra en el Gantt:
# cualquier estado que no sea terminal y tenga hora de inicio real se considera
# trabajo vivo. Esto evita que una orden desaparezca solo porque su estado no
# figuraba en la lista blanca de arriba (fue justo lo que pasaba con 'ABIERTA').
ESTADOS_TERMINALES = ['CERRADA', 'ANULADA', 'CANCELADA', 'LIQUIDADA', 'FINALIZADA', 'RECHAZADA']
ACTIVIDADES_BASURA = ['ACTUALIZACIONDATOS', 'ACTUALIZACIOFW', 'ACTUALIZAINFOTECNICA', 'ACTUALIZARDATOSTECNICOS', 'ACTUALIZARSENSOR', 'ACTIVARRES', 'DESTEFO']
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# FUNCIONES AUXILIARES DE SOPORTE GLOBAL
# ==============================================================================
def normalizar_nombre_cruce(texto):
    """
    Normaliza texto eliminando acentos, caracteres invisibles (como el Zero-Width Non-Joiner)
    y espacios extra para asegurar un cruce de nombres óptimo.
    """
    if pd.isnull(texto): 
        return ""
    t = str(texto).upper().strip()
    t = t.replace('\u200c', '').replace('\u200b', '')
    t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    t = ' '.join(t.split())
    
    alias_map = {
        "JOSUE MIGUEL SAUCEDA": "JOSE MIGUEL SAUCEDA",
        "JERMY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "JEREMY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "JERMY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JEREMY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JERNY MODESTO PADILLA CARDONA": "JERMI MODESTO PADILLA CARDONA",
        "JERNY MODESTO PADILLA": "JERMI MODESTO PADILLA",
        "ELIAS MIZAEL SABILLON": "ELIAS MISAEL ALONZO SABILLON",
        "ELIAS MISAEL SABILLON": "ELIAS MISAEL ALONZO SABILLON",
        "ELIAS MISAEL ALONZO": "ELIAS MISAEL ALONZO SABILLON",
        "DANIEL EZEQUIEL PONCE GUZMAN": "DANIEL EZEQUIEL GUZMAN PONCE",
        "NELAON RAMON FERRUFINO LEON": "NELSON RAMON FERRUFINO LEON"
    }
    
    if t in alias_map:
        return alias_map[t]
    return t

def mascara_tecnico_asignado(serie_tecnicos):
    """
    Retorna una serie booleana con True para técnicos asignados válidos
    y False para técnicos nulos, vacíos o no asignados.
    """
    s = serie_tecnicos.fillna('').astype(str).str.strip().str.upper()
    valores_invalidos = {'', 'NONE', 'NAN', 'N/D', 'NULL', '0'}
    return ~s.isin(valores_invalidos)

# ==============================================================================
# 1. CONFIGURACIÓN INICIAL DE LA INTERFAZ
# ==============================================================================
st.set_page_config(
    layout="wide", 
    page_title="Monitor Operativo Maxcom PRO", 
    page_icon="⚡",
    initial_sidebar_state="collapsed" 
)

st.markdown("""
    <style>
    .js-plotly-plot .plotly text {
        user-select: text !important;
        pointer-events: auto !important;
        cursor: text !important;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# SINCROFONIZACIÓN DE DATOS CON LA NUBE
# ==============================================================================
def sincronizar_datos_nube(conn):
    try:
        with st.spinner("☁️ Descargando historial desde GCS (Alta Velocidad)..."):
            df_nube = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
            
            if df_nube is None or df_nube.empty:
                df_nube = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                
            if df_nube is not None and not df_nube.empty:
                df_nube = df_nube.dropna(how='all')
                df_nube.columns = df_nube.columns.str.upper().str.strip()

                if 'SUSCRIPTOR' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)
                elif 'NOMBRE_CLIENTE' in df_nube.columns and 'NOMBRE' not in df_nube.columns: df_nube.rename(columns={'NOMBRE_CLIENTE': 'NOMBRE'}, inplace=True)

                if 'ACTIVIDAD' in df_nube.columns:
                    mask_basura_sync = df_nube['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
                    df_nube = df_nube[~mask_basura_sync].copy()

            if 'EMPRESA' in df_nube.columns:
                empresa_upper_sync = df_nube['EMPRESA'].astype(str).str.strip().str.upper()
                mask_otra_empresa_sync = (empresa_upper_sync != '') & (empresa_upper_sync != 'NAN') & (empresa_upper_sync != 'NONE') & (~empresa_upper_sync.str.contains('ISCA', na=False))
                df_nube = df_nube[~mask_otra_empresa_sync].copy()

                df_nube = procesar_fechas_seguro(df_nube, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'], columnas_sin_asumir_hoy=['HORA_LIQ', 'FECHA_APE'])
                
                if 'HORA_INI' in df_nube.columns and 'HORA_LIQ' in df_nube.columns:
                    df_nube['MINUTOS_CALC'] = (df_nube['HORA_LIQ'] - df_nube['HORA_INI']).dt.total_seconds() / 60
                    df_nube['MINUTOS_CALC'] = df_nube['MINUTOS_CALC'].fillna(0.0)
                    
                    diff_nube = df_nube['HORA_LIQ'] - df_nube['HORA_INI']
                    df_nube['TIEMPO_REAL'] = np.where(
                        df_nube['HORA_INI'].isnull() | df_nube['HORA_LIQ'].isnull(),
                        "---",
                        (diff_nube.dt.total_seconds() // 3600).fillna(0).astype(int).astype(str) + "h " +
                        ((diff_nube.dt.total_seconds() % 3600) // 60).fillna(0).astype(int).astype(str) + "m"
                    )

                for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
                    if col_b in df_nube.columns: df_nube[col_b] = df_nube[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])

                if 'ACTIVIDAD' in df_nube.columns:
                    act_upper = df_nube['ACTIVIDAD'].astype(str).str.upper()
                    mask_falsos = act_upper.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
                    mask_solo_sop = act_upper.str.contains('SOPFIBRA', na=False)
                    if 'ES_OFFLINE' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ES_OFFLINE'] = False
                        df_nube.loc[~mask_solo_sop, 'ES_OFFLINE'] = False
                    if 'ALERTA_TIEMPO' in df_nube.columns:
                        df_nube.loc[mask_falsos, 'ALERTA_TIEMPO'] = False
                        df_nube.loc[~mask_solo_sop, 'ALERTA_TIEMPO'] = False
                
                for col_txt in ['NUM', 'CLIENTE']:
                    if col_txt in df_nube.columns:
                        df_nube[col_txt] = pd.to_numeric(df_nube[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
                        df_nube[col_txt] = df_nube[col_txt].replace('0', 'N/D')
                        
                if 'NUM' in df_nube.columns:
                    df_nube['NUM'] = df_nube['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    
                    df_nube['SORT_DATE'] = pd.to_datetime(df_nube['HORA_LIQ'], errors='coerce')
                    df_nube['SORT_DATE'] = df_nube['SORT_DATE'].fillna(pd.to_datetime(df_nube['FECHA_APE'], errors='coerce'))
                    df_nube['SORT_DATE'] = df_nube['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
                    
                    PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                    df_nube['ES_VIVA'] = df_nube['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
                    df_nube = df_nube.sort_values(by=['ES_VIVA', 'SORT_DATE'], ascending=[False, True])
                    
                    df_validos = df_nube[df_nube['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                    df_invalidos = df_nube[df_nube['NUM'] == 'N/D']
                    df_nube = pd.concat([df_validos, df_invalidos]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')
                            
                if 'DIAS_RETRASO' in df_nube.columns: df_nube['DIAS_RETRASO'] = pd.to_numeric(df_nube['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
                if 'ESTADO' in df_nube.columns: df_nube['ESTADO'] = df_nube['ESTADO'].astype(str).str.upper().str.strip()

                if 'TECNICO' in df_nube.columns:
                    mask_josue = df_nube['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
                    if 'DIAS_RETRASO' in df_nube.columns: df_nube.loc[mask_josue, 'DIAS_RETRASO'] = 0
                    if 'ES_OFFLINE' in df_nube.columns: df_nube.loc[mask_josue, 'ES_OFFLINE'] = False

                ahora_momento_ts = pd.Timestamp(get_honduras_time())
                if df_nube['HORA_LIQ'].dt.tz is None:
                    ahora_naive = ahora_momento_ts.tz_localize(None)
                else:
                    ahora_naive = ahora_momento_ts
                fecha_limite_7d = ahora_naive - timedelta(days=7) 
                
                if 'HORA_LIQ' in df_nube.columns and 'FECHA_APE' in df_nube.columns and 'ESTADO' in df_nube.columns:
                    mask_vivas = df_nube['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                    df_nube = df_nube[(df_nube['HORA_LIQ'] >= fecha_limite_7d) | (df_nube['FECHA_APE'] >= fecha_limite_7d) | (df_nube['HORA_LIQ'].isna()) | mask_vivas].copy()

                cols_orden_ideal = ['DIAS_RETRASO', 'NUM', 'ACTIVIDAD', 'CLIENTE', 'NOMBRE', 'COLONIA', 'TECNICO', 'HORA_INI', 'HORA_LIQ', 'TIEMPO_REAL', 'ESTADO', 'COMENTARIO', 'ES_OFFLINE', 'SOP', 'RAZON_CIERRE_SOP', 'SEGMENTO', 'ALERTA_TIEMPO']
                cols_presentes = [c for c in cols_orden_ideal if c in df_nube.columns]
                cols_restantes = [c for c in df_nube.columns if c not in cols_presentes]
                df_nube = df_nube[cols_presentes + cols_restantes]

                st.session_state.df_base = df_nube
                
                st.success(f"✅ Sincronización Exitosa. Se cargaron {len(df_nube)} órdenes de la nube.")
                import time
                time.sleep(1.5)
                st.rerun()
            else: 
                st.warning("⚠️ La base de datos en la nube está completamente vacía. Sube archivos como Admin primero.")
                import time
                time.sleep(3)
    except Exception as e: 
        st.error(f"❌ Error crítico al conectar con la nube: {e}")
        import time
        time.sleep(3)

# ==============================================================================
# INTERFAZ PRINCIPAL (MAIN)
# ==============================================================================
def mostrar_analisis_red(df_base_activa, hoy_date_valor, conn=None):
    """
    Analiza dónde se concentran las fallas dentro de la red FTTH usando las
    columnas OLT y PON que ahora entrega Cepheus.

    La idea de fondo: varios reportes de clientes distintos en el MISMO puerto
    PON y en una ventana corta de tiempo casi nunca son fallas independientes;
    normalmente son un solo daño físico (una fibra cortada, un poste movido, un
    splitter dañado) visto desde muchos clientes. Detectarlo permite atender la
    causa en vez de despachar un técnico por cada llamada.
    """
    st.subheader("🛰️ Análisis de Red por OLT / PON")

    if 'OLT' not in df_base_activa.columns and 'PON' not in df_base_activa.columns:
        st.warning(
            "No se encontraron las columnas **OLT** ni **PON** en los datos cargados.\n\n"
            "Verifica que el reporte de Cepheus las incluya. El sistema busca los encabezados "
            "`OLT`, `NOMBRE OLT`, `PON`, `PUERTO PON`, `SPLITTER`, entre otros. "
            "Si en tu reporte se llaman distinto, dime el nombre exacto para agregarlo al mapeo."
        )
        return

    df_red = df_base_activa.copy()
    for c in ['OLT', 'PON']:
        if c not in df_red.columns:
            df_red[c] = ""
        df_red[c] = df_red[c].fillna("").astype(str).str.strip().str.upper()

    # Solo incidencias de red: soportes/averías de fibra. Las instalaciones no
    # indican falla, así que incluirlas distorsionaría el diagnóstico.
    act = df_red['ACTIVIDAD'].astype(str).str.upper()
    mask_falla = act.str.contains('SOP|PEXTERNO|SPLITTEROPT|RECON', na=False)
    df_fallas = df_red[mask_falla].copy()

    if df_fallas.empty:
        st.info("No hay incidencias de red (soportes/averías) en el rango de datos cargado.")
        return

    # ---------------- Filtros ----------------
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        dias_rango = st.selectbox("Periodo a analizar:", [7, 15, 30, 60, 90], index=2, key="red_dias")
    with col_f2:
        solo_offline = st.checkbox(
            "Solo caídas totales (ONT/ONU Offline)",
            value=False,
            key="red_solo_off",
            help="Filtra únicamente clientes sin señal. Útil para separar cortes de fibra de problemas de atenuación o TV."
        )

    fecha_corte = pd.Timestamp(hoy_date_valor) - pd.Timedelta(days=dias_rango)
    ref_fecha = pd.to_datetime(df_fallas['FECHA_APE'], errors='coerce')
    ref_fecha = ref_fecha.fillna(pd.to_datetime(df_fallas['HORA_INI'], errors='coerce'))
    df_fallas = df_fallas[ref_fecha >= fecha_corte].copy()
    df_fallas['FECHA_REF'] = ref_fecha[ref_fecha >= fecha_corte]

    if solo_offline and 'ES_OFFLINE' in df_fallas.columns:
        df_fallas = df_fallas[df_fallas['ES_OFFLINE'].fillna(False).astype(bool)]

    if df_fallas.empty:
        st.info("No hay incidencias en el periodo seleccionado.")
        return

    con_olt = (df_fallas['OLT'].str.len() > 0).sum()
    st.caption(
        f"Analizando **{len(df_fallas)}** incidencias de los últimos **{dias_rango}** días · "
        f"{con_olt} con OLT identificada ({100*con_olt/len(df_fallas):.0f}%)"
    )
    if con_olt < len(df_fallas) * 0.5:
        st.warning(
            "⚠️ Más de la mitad de las incidencias no traen OLT. El análisis sigue siendo válido "
            "para las que sí la tienen, pero el ranking puede no reflejar la realidad completa."
        )

    sub_olt, sub_eventos, sub_cruce, sub_avisos = st.tabs([
        "📊 Desglose OLT / PON",
        "🚨 Eventos Masivos",
        "🗺️ Cruce con Sector",
        "📢 Avisos RECO"
    ])

    # ============================================================
    # 1) RANKING
    # ============================================================
    with sub_olt:
        df_con_olt = df_fallas[df_fallas['OLT'].str.len() > 0].copy()
        if df_con_olt.empty:
            st.info("Ninguna incidencia del periodo tiene OLT registrada.")
        else:
            df_con_olt['MES'] = df_con_olt['FECHA_REF'].dt.strftime('%Y-%m')
            df_con_olt['MES_ETIQUETA'] = df_con_olt['FECHA_REF'].dt.strftime('%b').str.lower()
            df_con_olt['PON_LABEL'] = df_con_olt['PON'].replace('', '(sin PON)')

            meses_orden = sorted(df_con_olt['MES'].dropna().unique())
            mapa_mes = (
                df_con_olt.drop_duplicates('MES')
                .set_index('MES')['MES_ETIQUETA']
                .to_dict()
            )

            # Tabla dinámica: OLT (grupo) -> PON (detalle), una columna por mes.
            tabla = pd.pivot_table(
                df_con_olt, index=['OLT', 'PON_LABEL'], columns='MES',
                values='NUM', aggfunc='count', fill_value=0
            )
            tabla = tabla.reindex(columns=meses_orden, fill_value=0)
            tabla.columns = [mapa_mes.get(m, m) for m in tabla.columns]
            tabla['Total'] = tabla.sum(axis=1)

            totales_olt = tabla.groupby(level=0).sum().sort_values('Total', ascending=False)

            st.markdown("**Resumen por OLT**")
            st.caption("Total de incidencias por equipo, desglosado por mes. Expande cada OLT para ver sus puertos PON.")
            st.dataframe(
                totales_olt.style.background_gradient(cmap='Reds', subset=['Total']).format('{:.0f}'),
                use_container_width=True
            )

            st.divider()
            st.markdown("**Desglose por puerto PON**")

            for olt in totales_olt.index:
                sub = tabla.loc[olt].sort_values('Total', ascending=False)
                total_olt = int(totales_olt.loc[olt, 'Total'])
                n_pon = len(sub)
                # El PON más golpeado se muestra en el título: es el dato que
                # normalmente se busca al abrir el desglose.
                peor_pon, peor_val = sub.index[0], int(sub.iloc[0]['Total'])

                with st.expander(f"📡 **{olt}** — {total_olt} incidencias en {n_pon} puerto(s) · más afectado: PON {peor_pon} ({peor_val})"):
                    st.dataframe(
                        sub.style.background_gradient(cmap='Oranges', subset=['Total']).format('{:.0f}'),
                        use_container_width=True
                    )

                    detalle = df_con_olt[df_con_olt['OLT'] == olt]
                    colonias = (
                        detalle.groupby(detalle['COLONIA'].astype(str).str.upper())['NUM']
                        .count().sort_values(ascending=False).head(5)
                    )
                    if not colonias.empty:
                        st.caption("Colonias con más incidencias en esta OLT: " +
                                   " · ".join(f"**{c}** ({v})" for c, v in colonias.items()))

            csv_pivot = tabla.reset_index().to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Descargar desglose (CSV)",
                data=csv_pivot,
                file_name=f"desglose_olt_pon_{hoy_date_valor.strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="red_dl_pivot"
            )

    # ============================================================
    # 2) EVENTOS MASIVOS  (el corazón del análisis)
    # ============================================================
    with sub_eventos:
        st.markdown("**Detección de fallas con causa común**")
        st.caption(
            "Agrupa incidencias de un mismo puerto PON ocurridas en una ventana corta de tiempo. "
            "Varios clientes distintos fallando a la vez en el mismo ramal apunta a un único daño físico."
        )

        col_e1, col_e2 = st.columns(2)
        with col_e1:
            ventana_horas = st.slider("Ventana de tiempo (horas):", 1, 48, 6, key="red_ventana")
        with col_e2:
            minimo_clientes = st.slider("Mínimo de clientes afectados:", 2, 10, 3, key="red_minimo")

        df_ev = df_fallas[(df_fallas['PON'].str.len() > 0) & df_fallas['FECHA_REF'].notna()].copy()

        if df_ev.empty:
            st.info("No hay incidencias con PON y fecha válidas para agrupar.")
        else:
            df_ev['NODO'] = df_ev['OLT'] + " / PON " + df_ev['PON']
            df_ev = df_ev.sort_values(['NODO', 'FECHA_REF'])

            eventos = []
            for nodo, grupo in df_ev.groupby('NODO'):
                grupo = grupo.sort_values('FECHA_REF')
                bloque = []
                for _, fila in grupo.iterrows():
                    if bloque and (fila['FECHA_REF'] - bloque[0]['FECHA_REF']) > pd.Timedelta(hours=ventana_horas):
                        if len(bloque) >= minimo_clientes:
                            eventos.append((nodo, bloque))
                        bloque = []
                    bloque.append(fila)
                if len(bloque) >= minimo_clientes:
                    eventos.append((nodo, bloque))

            if not eventos:
                st.success(
                    f"✅ No se detectaron eventos masivos con los criterios actuales "
                    f"({minimo_clientes}+ clientes en {ventana_horas}h en el mismo PON)."
                )
            else:
                eventos.sort(key=lambda e: len(e[1]), reverse=True)
                st.error(f"🚨 Se detectaron **{len(eventos)}** evento(s) con posible causa común.")

                for i, (nodo, bloque) in enumerate(eventos[:20]):
                    df_bloque = pd.DataFrame(bloque)
                    inicio = df_bloque['FECHA_REF'].min()
                    fin = df_bloque['FECHA_REF'].max()
                    colonias = ", ".join(sorted(set(df_bloque['COLONIA'].astype(str))))[:70]
                    n_cli = df_bloque['CLIENTE'].nunique()

                    with st.expander(f"🔴 {nodo} — {n_cli} clientes · {inicio.strftime('%d/%m %H:%M')} → {fin.strftime('%d/%m %H:%M')}"):
                        st.markdown(f"**Colonias afectadas:** {colonias}")
                        st.caption(
                            f"Duración del evento: {(fin - inicio).total_seconds()/3600:.1f} horas · "
                            f"{len(df_bloque)} órdenes"
                        )
                        st.info(
                            "💡 Revisa si hubo trabajos programados (cambio de postes, poda, obra vial) "
                            f"en **{colonias.split(',')[0]}** en esas fechas. Si coincide, el origen está identificado."
                        )
                        cols_ev = [c for c in ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'FECHA_REF', 'ESTADO', 'TECNICO', 'COMENTARIO'] if c in df_bloque.columns]
                        st.dataframe(df_bloque[cols_ev], use_container_width=True, hide_index=True)

    # ============================================================
    # 3) CRUCE CON SECTOR
    # ============================================================
    with sub_cruce:
        st.markdown("**Concentración geográfica de fallas**")
        st.caption("Cruza la infraestructura con la ubicación: si una colonia concentra fallas de un solo PON, el problema es de red; si son de varios PON, apunta a algo externo (obra, clima, energía).")

        df_c = df_fallas[df_fallas['COLONIA'].astype(str).str.len() > 0].copy()
        if df_c.empty:
            st.info("Sin datos de colonia en el periodo.")
        else:
            resumen_col = (
                df_c.groupby(df_c['COLONIA'].astype(str).str.upper())
                .agg(INCIDENCIAS=('NUM', 'count'),
                     CLIENTES=('CLIENTE', 'nunique'),
                     PON_DISTINTOS=('PON', lambda s: s[s.str.len() > 0].nunique()),
                     OLT_DISTINTAS=('OLT', lambda s: s[s.str.len() > 0].nunique()))
                .reset_index()
                .rename(columns={'COLONIA': 'COLONIA'})
                .sort_values('INCIDENCIAS', ascending=False)
                .head(30)
            )

            def _diagnostico(fila):
                if fila['PON_DISTINTOS'] == 1 and fila['INCIDENCIAS'] >= 3:
                    return "🔴 Un solo PON: probable daño en el ramal"
                if fila['PON_DISTINTOS'] >= 3 and fila['INCIDENCIAS'] >= 5:
                    return "🟠 Varios PON: posible causa externa (obra, clima, energía)"
                return "🟢 Disperso"

            resumen_col['DIAGNOSTICO'] = resumen_col.apply(_diagnostico, axis=1)
            st.dataframe(resumen_col, use_container_width=True, hide_index=True)


    # ============================================================
    # 4) AVISOS RECO
    # ============================================================
    with sub_avisos:
        st.markdown("**Registro de avisos de RECO / trabajos programados**")
        st.caption(
            "Pega aquí el texto del comunicado. El sistema extrae las colonias y fechas, "
            "y las cruza con las incidencias para identificar el origen de las fallas."
        )

        with st.expander("ℹ️ ¿Por qué no se conecta solo al Facebook de RECO?"):
            st.markdown(
                "Meta cerró el acceso a páginas de terceros: leer publicaciones de una página "
                "que **no administras** requiere *Page Public Content Access*, que exige revisión "
                "de app y verificación de negocio ante Meta, y aun así no garantiza la aprobación. "
                "Los servicios que lo hacen por fuera operan con raspado web, que **viola los "
                "términos de Meta** y se rompe cada vez que cambian la página.\n\n"
                "Por eso este módulo funciona con copiar y pegar: toma 15 segundos, no depende de "
                "terceros y no expone a la empresa. Todo lo demás (extraer colonias, fechas y "
                "cruzarlas con las fallas) sí es automático."
            )

        # Catálogo de colonias reales, para detectarlas dentro del texto del aviso.
        colonias_conocidas = sorted({
            str(c).strip().upper()
            for c in df_base_activa.get('COLONIA', pd.Series(dtype=str)).dropna().unique()
            if len(str(c).strip()) > 3
        })

        HOJA_AVISOS = "AvisosReco"

        def _normalizar_txt(t):
            """Quita acentos y normaliza para comparar nombres de colonias."""
            t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode('ascii')
            return re.sub(r'\s+', ' ', t).strip().upper()

        # Vocabulario real de campo. Cuando RECO trabaja en los postes, la fibra
        # se corta y el técnico lo escribe en el comentario de cierre.
        #
        # OJO: aquí van SOLO indicadores fuertes. Palabras sueltas como "CORTADO",
        # "CORTADA" o "ACOMETIDA" se quitaron a propósito porque aparecen en
        # averías que nada tienen que ver con RECO ("servicio cortado por mora",
        # "se cambia acometida por deterioro") e inflaban el conteo del evento.
        CLAVES_CORTE_EXTERNO = [
            # Mención directa al responsable del trabajo externo
            'RECO', 'ENEE', 'ELECTRICA', 'ELECTRICIDAD',
            # El daño físico, siempre en frase (no palabra suelta)
            'CORTE DE ACOMETIDA', 'ACOMETIDA CORTADA', 'ACOMETIDA ROTA',
            'ACOMETIDA DANADA', 'ACOMETIDA REVENTADA', 'ACOMETIDA REVENTO',
            'CORTARON LA ACOMETIDA', 'CORTO LA ACOMETIDA',
            'CABLE CORTADO', 'CORTARON EL CABLE', 'CABLE REVENTADO',
            'FIBRA CORTADA', 'CORTARON LA FIBRA', 'CORTO LA FIBRA',
            'DROP CORTADO', 'DROP REVENTADO',
            # Causa/contexto inequívoco del corte
            'CAMBIO DE POSTE', 'CAMBIARON EL POSTE', 'POSTE NUEVO',
            'PODA', 'PODARON', 'CAIDA DE ARBOL', 'RAMA CAIDA',
            'LINEA TRONCAL', 'TRONCAL',
        ]

        # Se compila una sola vez. \b exige palabra completa: así "RECO" no
        # coincide dentro de "RECONFIGURA" ni "PODA" dentro de "PODADORA".
        _PATRON_CORTE_EXTERNO = re.compile(
            r'\b(' + '|'.join(re.escape(k) for k in CLAVES_CORTE_EXTERNO) + r')\b'
        )

        def _claves_detectadas(row):
            """
            Devuelve las palabras clave que hicieron coincidir una orden.
            Se muestra como columna EVIDENCIA para que el criterio sea auditable:
            si una orden aparece sin razón aparente, aquí se ve exactamente qué
            término la activó y se puede corregir el vocabulario.
            """
            texto = _normalizar_txt(str(row.get('COMENTARIO', '')) + " " + str(row.get('RAZON_CIERRE_SOP', '')))
            if not texto:
                return ""
            return ", ".join(sorted(set(_PATRON_CORTE_EXTERNO.findall(texto))))

        def _es_corte_externo(row):
            """
            Identifica si una orden corresponde a un corte causado por trabajo
            externo (RECO, poda, cambio de poste) y no a una falla del cliente.

            Se exige DOBLE condición: que la actividad sea SOP/SOPFIBRA -- una
            avería, no una instalación -- Y que el comentario contenga vocabulario
            de corte físico. Sin la segunda condición entrarían todas las SOP de
            la zona (routers, lentitud, TV), que no tienen relación con el corte
            y desvirtuarían el conteo de impacto.

            La búsqueda es por PALABRA COMPLETA, no por subcadena: buscar "RECO"
            suelto daba falsos positivos dentro de "RECOnfigura", "RECOnexion" o
            "RECOrrido", metiendo averías comunes al conteo del evento.
            """
            act = _normalizar_txt(row.get('ACTIVIDAD', ''))
            if 'SOP' not in act:
                return False
            texto = _normalizar_txt(str(row.get('COMENTARIO', '')) + " " + str(row.get('RAZON_CIERRE_SOP', '')))
            if not texto:
                return False
            return bool(_PATRON_CORTE_EXTERNO.search(texto))

        def _extraer_colonias(texto, catalogo):
            """
            Busca las colonias del catálogo dentro del comunicado.

            Los avisos de RECO escriben "Col. Bella Vista" y usan acentos
            ("Los Ángeles"), mientras que en Cepheus están sin prefijo ni tildes.
            Por eso se compara sobre texto normalizado y se recorta el "Col.".
            """
            txt = _normalizar_txt(texto)
            # "COL. BELLA VISTA" -> "BELLA VISTA" para que empate con el catálogo
            txt = re.sub(r'\bCOL\.?\s+', '', txt)
            encontradas = []
            for c in catalogo:
                cn = _normalizar_txt(c)
                if len(cn) > 3 and cn in txt:
                    encontradas.append(c)
            # Descarta nombres contenidos en otro más largo (BAY dentro de SANDY BAY)
            return [c for c in encontradas
                    if not any(c != o and _normalizar_txt(c) in _normalizar_txt(o) for o in encontradas)]

        def _extraer_fechas(texto, anio_ref):
            """
            Extrae fechas del comunicado evitando dos trampas reales:

            1) Los avisos vienen en español e inglés, y la misma fecha aparece
               como 07/08/2026 y 08/07/2026. Tomar ambas produciría una fecha
               falsa, así que se prioriza la que sigue a la etiqueta "Fecha:"
               (versión en español, formato día/mes).
            2) Los teléfonos y extensiones ("2405-1130/99", "1108 / 1110")
               parecen fechas; se exigen números de 1-2 dígitos y se validan.
            """
            candidatas = []

            # Prioridad: lo que viene justo después de "Fecha:" (español)
            m_es = re.search(r'FECHA\s*:?\s*(?:[A-ZÁÉÍÓÚÑ]+\s+)?(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',
                             texto, re.IGNORECASE)
            if m_es:
                d_, m_, a_ = m_es.groups()
                candidatas.append((int(d_), int(m_), a_))

            if not candidatas:
                for d_, m_, a_ in re.findall(r'(?<![\d/-])(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})(?![\d/-])', texto):
                    candidatas.append((int(d_), int(m_), a_))

            fechas = []
            for d_, m_, a_ in candidatas:
                if len(a_) == 2:
                    a_ = "20" + a_
                # Si el "día" supera 12 es inequívocamente día/mes; si el mes
                # supera 12, venía en formato inglés y se invierte.
                if m_ > 12 and d_ <= 12:
                    d_, m_ = m_, d_
                try:
                    fechas.append(pd.Timestamp(int(a_), m_, d_))
                except Exception:
                    pass
            return sorted(set(fechas))

        def _ocr_imagen(archivo_img):
            """
            Extrae el texto de una captura del comunicado.

            Las capturas de Facebook son texto digital nítido, así que el OCR
            funciona bien; los afiches con letra estilizada o fondo de color son
            más difíciles. Por eso la imagen se preprocesa (escala de grises,
            aumento de tamaño y contraste) antes de leerla, y el resultado SIEMPRE
            queda editable: el OCR se equivoca y corregir debe ser trivial.
            """
            try:
                import pytesseract
                from PIL import Image, ImageOps, ImageEnhance
            except ImportError:
                return None, "falta_libreria"

            try:
                img = Image.open(archivo_img)
                img = ImageOps.exif_transpose(img).convert("L")

                # Modo oscuro: si el fondo predomina oscuro, se invierte. Sin esto
                # el OCR falla casi por completo con las capturas de Facebook en
                # tema oscuro (texto blanco sobre negro), que son muy comunes.
                if np.array(img).mean() < 110:
                    img = ImageOps.invert(img)

                # Ampliar mejora bastante el OCR en capturas de celular.
                if img.width < 1200:
                    factor = 1200 / img.width
                    img = img.resize((int(img.width * factor), int(img.height * factor)), Image.LANCZOS)

                img = ImageOps.autocontrast(img)
                img = ImageEnhance.Sharpness(img).enhance(1.5)

                texto = ""
                for cfg in ("--psm 6", "--psm 4", "--psm 3"):
                    try:
                        t = pytesseract.image_to_string(img, lang="spa+eng", config=cfg)
                    except Exception:
                        t = pytesseract.image_to_string(img, config=cfg)
                    if len(t.strip()) > len(texto.strip()):
                        texto = t
                return texto.strip(), None
            except Exception as e:
                return None, str(e)

        def _detectar_tipo_trabajo(texto):
            """Deduce el tipo de trabajo por palabras clave del comunicado."""
            t = _normalizar_txt(texto)
            reglas = [
                ("Cambio de postes", ['CAMBIO DE POSTE', 'POSTES', 'SUSTITUCION DE POSTE']),
                ("Poda de árboles", ['PODA', 'ARBOL', 'DESPEJE DE ARBOL', 'RAMAS']),
                ("Obra vial", ['OBRA VIAL', 'CARRETERA', 'PAVIMENT', 'EXCAVA']),
                ("Corte programado de energía", ['INTERRUPCION', 'SUSPENSION', 'CORTE DE ENERGIA',
                                                 'SCHEDULED OUTAGE', 'OUTAGE', 'DESPEJE', 'LINEA TRONCAL']),
                ("Mantenimiento de red eléctrica", ['MANTENIMIENTO', 'MEJORAS EN LA RED',
                                                    'RED DE DISTRIBUCION', 'DISTRIBUTION SYSTEM']),
            ]
            for etiqueta, claves in reglas:
                if any(k in t for k in claves):
                    return etiqueta
            return "Otro"

        modo_entrada = st.radio(
            "¿Cómo quieres cargar el comunicado?",
            ["📷 Subir captura de pantalla", "⌨️ Escribir o pegar texto"],
            horizontal=True,
            key="reco_modo"
        )

        if modo_entrada == "📷 Subir captura de pantalla":
            img_aviso = st.file_uploader(
                "Captura del comunicado:",
                type=["png", "jpg", "jpeg", "webp"],
                key="reco_img"
            )

            if img_aviso is not None:
                # La imagen se procesa UNA sola vez por archivo. Se identifica por
                # nombre+tamaño para no releerla en cada recarga de la página, que
                # además borraría las correcciones que el usuario ya hizo a mano.
                firma_img = f"{img_aviso.name}_{img_aviso.size}"

                if st.session_state.get('reco_firma_img') != firma_img:
                    with st.spinner("Leyendo el comunicado y completando los campos..."):
                        texto_leido, err_ocr = _ocr_imagen(img_aviso)

                    st.session_state['reco_firma_img'] = firma_img
                    st.session_state['reco_error_ocr'] = err_ocr

                    if texto_leido:
                        # Se escriben los valores en session_state ANTES de crear los
                        # widgets. Pasarlos como value= no funciona: una vez que el
                        # widget existe, session_state tiene prioridad y el campo
                        # quedaría vacío aunque el texto sí se hubiera leído.
                        st.session_state['reco_texto'] = texto_leido

                        cols_det = _extraer_colonias(texto_leido, colonias_conocidas)
                        st.session_state['reco_colonias'] = ", ".join(cols_det)

                        fechas_det = _extraer_fechas(texto_leido, hoy_date_valor.year)
                        if fechas_det:
                            st.session_state['reco_fecha'] = fechas_det[0].date()

                        st.session_state['reco_tipo'] = _detectar_tipo_trabajo(texto_leido)
                        st.session_state['reco_autocompletado'] = {
                            'colonias': len(cols_det),
                            'fecha': fechas_det[0].strftime('%d/%m/%Y') if fechas_det else None,
                            'tipo': st.session_state['reco_tipo'],
                        }
                    st.rerun()

                col_img1, col_img2 = st.columns([1, 2])
                with col_img1:
                    st.image(img_aviso, caption="Captura cargada", use_container_width=True)
                with col_img2:
                    err_ocr = st.session_state.get('reco_error_ocr')
                    resumen = st.session_state.get('reco_autocompletado')

                    if err_ocr == "falta_libreria":
                        st.error(
                            "El servidor aún no tiene instalado el lector de imágenes.\n\n"
                            "Agrega al repositorio un archivo **packages.txt** con `tesseract-ocr` y "
                            "`tesseract-ocr-spa`, y **pytesseract** en `requirements.txt`. "
                            "Mientras tanto, usa la opción de escribir el texto."
                        )
                    elif err_ocr:
                        st.error(f"No se pudo leer la imagen: {err_ocr}")
                    elif resumen:
                        st.success("✅ Campos completados automáticamente:")
                        st.markdown(
                            f"- 📍 **{resumen['colonias']}** colonia(s) detectada(s)\n"
                            f"- 📅 Fecha: **{resumen['fecha'] or 'no detectada'}**\n"
                            f"- 🛠️ Tipo: **{resumen['tipo']}**"
                        )
                        if resumen['colonias'] == 0:
                            st.warning("No se reconoció ninguna colonia. Escríbelas abajo.")
                        if not resumen['fecha']:
                            st.warning("No se detectó la fecha. Selecciónala abajo.")
                        st.caption("Revisa los campos y corrige si algo quedó mal antes de registrar.")

        texto_aviso = st.text_area(
            "Texto del comunicado:",
            height=130,
            key="reco_texto",
            placeholder="Ej: RECO informa que el día 08/08/2026 se realizarán trabajos de cambio de postes en Gravel Bay y Sandy Bay, de 8:00 am a 4:00 pm."
        )

        def _mapear_infraestructura_afectada(lista_colonias, df_universo):
            """
            CRUCE MASIVO: traduce las colonias de un comunicado a la infraestructura
            real que las atiende, y al universo de clientes que dependen de ella.

            Esto es lo que permite anticipar en vez de reaccionar: cuando RECO
            anuncia un corte en ciertas colonias, aquí se resuelve de inmediato
            QUÉ OLT y QUÉ puertos PON alimentan ese sector y CUÁNTOS clientes hay
            detrás. Así, cuando después entren SOP/SOPFIBRA de esa zona, ya se
            sabe que pertenecen al mismo evento y no son fallas independientes.

            El mapa se construye con el histórico real de órdenes: si un cliente
            de esa colonia fue atendido alguna vez y quedó registrado su OLT/PON,
            esa relación colonia->infraestructura es un hecho, no una suposición.
            """
            if not lista_colonias or df_universo is None or df_universo.empty:
                return {}

            df_u = df_universo.copy()
            for c in ['OLT', 'PON', 'COLONIA']:
                if c not in df_u.columns:
                    df_u[c] = ""
                df_u[c] = df_u[c].fillna("").astype(str).str.strip().str.upper()

            cols_norm = [_normalizar_txt(c) for c in lista_colonias if str(c).strip()]
            colonia_norm_serie = df_u['COLONIA'].apply(_normalizar_txt)

            mask_zona = colonia_norm_serie.apply(
                lambda x: any(cn and (cn in x or x in cn) for cn in cols_norm)
            )
            df_zona = df_u[mask_zona]

            if df_zona.empty:
                return {'colonias_encontradas': [], 'olts': [], 'pones': [],
                        'clientes': 0, 'df_zona': df_zona, 'detalle_olt': pd.DataFrame()}

            olts = sorted([o for o in df_zona['OLT'].unique() if o])
            pones = sorted([f"{r['OLT']}/{r['PON']}" for _, r in
                            df_zona[df_zona['PON'].str.len() > 0].drop_duplicates(subset=['OLT', 'PON']).iterrows()])

            detalle_olt = pd.DataFrame()
            if olts:
                detalle_olt = (
                    df_zona[df_zona['OLT'].str.len() > 0]
                    .groupby('OLT')
                    .agg(CLIENTES=('CLIENTE', 'nunique'),
                         PUERTOS_PON=('PON', lambda s: s[s.str.len() > 0].nunique()),
                         COLONIAS=('COLONIA', lambda s: ", ".join(sorted(set(s))[:4])))
                    .reset_index()
                    .sort_values('CLIENTES', ascending=False)
                )

            return {
                'colonias_encontradas': sorted(df_zona['COLONIA'].unique().tolist()),
                'olts': olts,
                'pones': pones,
                'clientes': int(df_zona['CLIENTE'].nunique()),
                'df_zona': df_zona,
                'detalle_olt': detalle_olt,
            }

        def _cargar_avisos():
            # OLTS/PONES/CLIENTES_RIESGO guardan la infraestructura mapeada al
            # momento de registrar el aviso: así el cruce con órdenes futuras se
            # puede hacer por PUERTO PON (preciso) y no solo por nombre de colonia.
            cols = ["FECHA_REGISTRO", "FECHA_TRABAJO", "COLONIAS", "TIPO", "PROGRAMADA",
                    "OLTS", "PONES", "CLIENTES_RIESGO", "TEXTO", "REGISTRADO_POR"]
            if conn is None:
                return pd.DataFrame(columns=cols)
            try:
                d = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=HOJA_AVISOS, ttl=0)
                d = d.dropna(how="all")
                for c in cols:
                    if c not in d.columns:
                        d[c] = ""
                return d
            except Exception:
                # La hoja aún no existe: es normal antes del primer registro y no
                # se trata como error, pero tampoco se oculta.
                st.session_state['reco_hoja_faltante'] = True
                return pd.DataFrame(columns=cols)

        def _guardar_avisos(d):
            """
            Guarda el índice de avisos en Google Sheets.

            La hoja 'AvisosReco' normalmente no existe la primera vez, y
            conn.update() falla con WorksheetNotFound. Se intentan varias
            estrategias porque distintas versiones de st-gsheets-connection
            manejan create() de forma diferente. Si todas fallan se muestra el
            error REAL: un mensaje genérico no permite diagnosticar nada.
            """
            if conn is None:
                st.error("Sin conexión a la base de datos (conn no disponible).")
                return False

            url_hoja = st.secrets["url_base_datos"]
            errores = []

            # 1) Actualizar la hoja (funciona si ya existe)
            try:
                conn.update(spreadsheet=url_hoja, worksheet=HOJA_AVISOS, data=d)
                return True
            except Exception as e:
                errores.append(f"update: {type(e).__name__}: {e}")

            # 2) Crear la pestaña directamente con gspread. conn.create() de
            # st-gsheets-connection tiene un bug conocido: ignora
            # el spreadsheet= que se le pasa por parámetro y solo usa el que esté
            # configurado como default en secrets.toml, así que siempre falla con
            # "Spreadsheet must be specified" aunque el valor sí se haya pasado.
            # Se evita el problema autenticando gspread directo con las mismas
            # credenciales de servicio que ya usa el sistema para GCS.
            try:
                import gspread
                from google.oauth2.service_account import Credentials as _GSCredentials

                creds_dict = st.secrets["connections"]["gsheets"]
                scopes = ["https://www.googleapis.com/auth/spreadsheets",
                          "https://www.googleapis.com/auth/drive"]
                creds = _GSCredentials.from_service_account_info(creds_dict, scopes=scopes)
                gc = gspread.authorize(creds)
                sh = gc.open_by_url(url_hoja)
                sh.add_worksheet(title=HOJA_AVISOS, rows=200, cols=10)

                conn.update(spreadsheet=url_hoja, worksheet=HOJA_AVISOS, data=d)
                return True
            except Exception as e:
                errores.append(f"gspread directo: {type(e).__name__}: {e}")

            st.error(
                f"No se pudo guardar en la hoja **{HOJA_AVISOS}**. Detalle de los intentos:\n\n- "
                + "\n- ".join(errores)
            )
            st.info(
                f"💡 Solución más rápida: abre tu Google Sheet y crea manualmente una pestaña "
                f"llamada exactamente **{HOJA_AVISOS}**. Luego vuelve a registrar el aviso."
            )
            # El aviso no se pierde: se ofrece descargarlo para no rehacer el trabajo.
            try:
                st.download_button(
                    "📥 Descargar este aviso (CSV)",
                    data=d.tail(1).to_csv(index=False).encode('utf-8'),
                    file_name=f"aviso_reco_{get_honduras_time().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    key=f"aviso_rescate_{get_honduras_time().strftime('%H%M%S')}"
                )
            except Exception:
                pass
            return False

        df_avisos = _cargar_avisos()

        if st.session_state.get('reco_hoja_faltante') and df_avisos.empty:
            st.info(
                f"ℹ️ La hoja **{HOJA_AVISOS}** aún no existe en tu Google Sheet. "
                "El sistema intentará crearla al registrar el primer aviso; si no lo logra, "
                "créala manualmente con ese nombre exacto."
            )

        detectadas, fechas_detectadas = [], []
        if texto_aviso.strip():
            detectadas = _extraer_colonias(texto_aviso, colonias_conocidas)
            fechas_detectadas = _extraer_fechas(texto_aviso, hoy_date_valor.year)

            c1, c2 = st.columns(2)
            with c1:
                if detectadas:
                    st.success(f"📍 Colonias detectadas: **{', '.join(detectadas)}**")
                else:
                    st.warning("No se reconoció ninguna colonia. Puedes escribirlas manualmente abajo.")
            with c2:
                if fechas_detectadas:
                    st.info("📅 Fechas: " + ", ".join(f.strftime('%d/%m/%Y') for f in fechas_detectadas))

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            # Sin value=: el contenido viene de session_state, que es donde el
            # lector de la imagen deja las colonias detectadas.
            if 'reco_colonias' not in st.session_state:
                st.session_state['reco_colonias'] = ", ".join(detectadas)
            colonias_final = st.text_input(
                "Colonias afectadas (separadas por coma):",
                key="reco_colonias"
            ).strip().upper()
        with col_a2:
            if 'reco_fecha' not in st.session_state:
                st.session_state['reco_fecha'] = (fechas_detectadas[0].date() if fechas_detectadas else hoy_date_valor)
            fecha_trabajo = st.date_input("Fecha del trabajo:", key="reco_fecha")

        OPCIONES_TIPO = ["Cambio de postes", "Mantenimiento de red eléctrica", "Poda de árboles",
                         "Obra vial", "Corte programado de energía", "Otro"]
        if 'reco_tipo' not in st.session_state:
            st.session_state['reco_tipo'] = OPCIONES_TIPO[0]
        tipo_aviso = st.selectbox("Tipo de trabajo:", OPCIONES_TIPO, key="reco_tipo")

        col_mg1, col_mg2 = st.columns([1, 1])
        with col_mg1:
            margen_dias_registro = st.slider(
                "Ventana de impacto (días a monitorear después del trabajo):",
                1, 15, 5, key="reco_margen_registro"
            )
        with col_mg2:
            solo_cortes = st.checkbox(
                "🎯 Solo cortes de acometida / menciones a RECO",
                value=True,
                key="reco_solo_cortes",
                help="Filtra únicamente SOP/SOPFIBRA cuyo comentario indique corte de acometida, fibra cortada, poste, poda o mención directa a RECO. Desactívalo para ver todas las averías de la zona."
            )

        # Universo de órdenes a considerar. El filtro por comentario es lo que
        # separa un corte real causado por el trabajo externo de una avería
        # cualquiera del cliente que coincidió en fecha y colonia.
        if solo_cortes:
            df_fallas_reco = df_fallas[df_fallas.apply(_es_corte_externo, axis=1)].copy()
            # Se registra QUÉ término activó cada coincidencia, para poder auditar
            # el criterio en pantalla en vez de confiar a ciegas en el filtro.
            if not df_fallas_reco.empty:
                df_fallas_reco['EVIDENCIA'] = df_fallas_reco.apply(_claves_detectadas, axis=1)
        else:
            df_fallas_reco = df_fallas.copy()
            df_fallas_reco['EVIDENCIA'] = ""

        if solo_cortes:
            st.caption(
                f"Analizando **{len(df_fallas_reco)}** órdenes de corte "
                f"(de {len(df_fallas)} averías totales en el periodo)."
            )
        else:
            st.warning(
                "⚠️ **Filtro desactivado.** Se están incluyendo TODAS las averías de la zona "
                "(routers, lentitud, niveles de fibra, TV), no solo los cortes por trabajo externo. "
                "Actívalo para que el conteo refleje únicamente el impacto de RECO."
            )

        # ==========================================================
        # CRUCE MASIVO EN VIVO: colonias -> OLT/PON -> clientes
        # ==========================================================
        # Se ejecuta apenas hay colonias detectadas, ANTES de registrar nada,
        # para que se vea el alcance real del corte de inmediato.
        if colonias_final:
            lista_cols_actual = [c.strip() for c in colonias_final.split(',') if c.strip()]
            mapa = _mapear_infraestructura_afectada(lista_cols_actual, df_base_activa)

            st.markdown("#### 🎯 Cruce masivo: infraestructura y clientes en riesgo")

            if not mapa or not mapa.get('colonias_encontradas'):
                st.warning(
                    "No se encontró ninguna colonia del comunicado en el histórico del sistema. "
                    "Verifica los nombres: deben coincidir con los que usa Cepheus."
                )
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("📍 Colonias", len(mapa['colonias_encontradas']))
                m2.metric("🛰️ OLT afectadas", len(mapa['olts']))
                m3.metric("🔌 Puertos PON", len(mapa['pones']))
                m4.metric("👥 Clientes en riesgo", mapa['clientes'])

                if mapa['olts']:
                    st.caption("**OLT que alimentan este sector:** " + " · ".join(mapa['olts']))
                    with st.expander(f"Ver desglose por OLT ({len(mapa['olts'])})"):
                        st.dataframe(mapa['detalle_olt'], use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "Las colonias existen en el sistema pero sus órdenes no traen OLT registrada. "
                        "El monitoreo funcionará por colonia, sin el detalle de infraestructura."
                    )

        if st.button("💾 Registrar incidencia y activar monitoreo", type="primary", use_container_width=True, key="reco_guardar"):
            if not colonias_final:
                st.error("Indica al menos una colonia.")
            else:
                lista_cols_g = [c.strip() for c in colonias_final.split(',') if c.strip()]
                mapa_g = _mapear_infraestructura_afectada(lista_cols_g, df_base_activa)

                es_programada = "SI" if "PROGRAM" in _normalizar_txt(texto_aviso + " " + tipo_aviso) else "NO"

                nuevo = pd.DataFrame([{
                    "FECHA_REGISTRO": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "FECHA_TRABAJO": fecha_trabajo.strftime('%Y-%m-%d'),
                    "COLONIAS": colonias_final,
                    "TIPO": tipo_aviso,
                    "PROGRAMADA": es_programada,
                    "OLTS": ", ".join(mapa_g.get('olts', [])),
                    "PONES": ", ".join(mapa_g.get('pones', [])),
                    "CLIENTES_RIESGO": mapa_g.get('clientes', 0),
                    "TEXTO": texto_aviso.strip()[:500],
                    "REGISTRADO_POR": st.session_state.get('usuario_actual', ''),
                }])

                # --- IMPACTO REAL: órdenes ya generadas por esta incidencia ---
                st.divider()
                st.markdown("### 📊 Impacto de esta incidencia")

                cols_aviso_nuevo = [c.strip().upper() for c in colonias_final.split(',') if c.strip()]
                f_trab_nuevo = pd.to_datetime(fecha_trabajo)

                col_serie_n = df_fallas_reco['COLONIA'].astype(str).str.upper()
                mask_col_n = col_serie_n.apply(lambda x: any(ca in x or x in ca for ca in cols_aviso_nuevo))

                # Además de la colonia, se cruza por PUERTO PON: si el corte tocó
                # un ramal concreto, cualquier orden de ese PON pertenece al mismo
                # evento aunque el nombre de la colonia esté escrito distinto.
                pones_afectados = set(mapa_g.get('pones', []))
                if pones_afectados:
                    nodo_serie = df_fallas_reco['OLT'].astype(str) + "/" + df_fallas_reco['PON'].astype(str)
                    mask_pon_n = nodo_serie.isin(pones_afectados)
                else:
                    mask_pon_n = pd.Series(False, index=df_fallas_reco.index)

                mask_fec_n = (df_fallas_reco['FECHA_REF'] >= f_trab_nuevo) & (df_fallas_reco['FECHA_REF'] <= f_trab_nuevo + pd.Timedelta(days=margen_dias_registro))
                coincid_nuevo = df_fallas_reco[(mask_col_n | mask_pon_n) & mask_fec_n].copy()

                clientes_riesgo = mapa_g.get('clientes', 0)

                if coincid_nuevo.empty:
                    st.success(
                        f"✅ Todavía **no se han generado órdenes** por esta incidencia "
                        f"(ventana del {fecha_trabajo.strftime('%d/%m/%Y')} + {margen_dias_registro} días)."
                    )
                    if clientes_riesgo:
                        st.info(f"👥 Hay **{clientes_riesgo} clientes** en la zona. Si empiezan a reportar, las órdenes aparecerán aquí.")
                else:
                    n_ord = len(coincid_nuevo)
                    n_cli = coincid_nuevo['CLIENTE'].nunique()
                    pct = (n_cli / clientes_riesgo * 100) if clientes_riesgo else 0

                    k1, k2, k3 = st.columns(3)
                    k1.metric("📋 Órdenes generadas", n_ord)
                    k2.metric("👤 Clientes que reportaron", n_cli)
                    k3.metric("📉 % de la zona afectada", f"{pct:.1f}%" if clientes_riesgo else "N/D")

                    pon_afectados_n = coincid_nuevo[coincid_nuevo['PON'].str.len() > 0]['PON'].nunique()
                    if pon_afectados_n == 1:
                        st.error("🔴 Todas las órdenes provienen de **un solo PON**: daño físico concentrado en ese ramal.")
                    elif pon_afectados_n > 1:
                        st.warning(f"🟠 Órdenes repartidas en **{pon_afectados_n} puertos PON**: el evento afectó varios ramales.")

                    resumen_por_colonia = (
                        coincid_nuevo.groupby(coincid_nuevo['COLONIA'].astype(str).str.upper())
                        .size().sort_values(ascending=False)
                    )
                    st.markdown("**Órdenes por colonia:** " + " · ".join(
                        f"{c}: **{n}**" for c, n in resumen_por_colonia.items()
                    ))

                    cols_m_n = [c for c in ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'OLT', 'PON', 'FECHA_REF', 'ESTADO', 'TECNICO', 'EVIDENCIA', 'COMENTARIO'] if c in coincid_nuevo.columns]
                    st.dataframe(coincid_nuevo[cols_m_n].sort_values('FECHA_REF'), use_container_width=True, hide_index=True)

                    st.download_button(
                        "📥 Descargar clientes afectados (CSV)",
                        data=coincid_nuevo[cols_m_n].to_csv(index=False).encode('utf-8'),
                        file_name=f"impacto_{fecha_trabajo.strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        key="dl_impacto_nuevo"
                    )

                # --- Guardado (no bloquea lo mostrado arriba) ---
                if _guardar_avisos(pd.concat([df_avisos, nuevo], ignore_index=True)):
                    st.success("✅ Incidencia registrada. El monitoreo queda activo para futuras órdenes.")
                    for k in ['reco_texto', 'reco_colonias', 'reco_firma_img',
                              'reco_autocompletado', 'reco_error_ocr']:
                        st.session_state.pop(k, None)

        st.divider()

        # ---------- CRUCE: avisos vs incidencias ----------
        if df_avisos.empty:
            st.info("Aún no hay avisos registrados. Al registrar el primero, aquí verás el cruce con las fallas.")
        else:
            st.markdown("**Correlación entre avisos y fallas**")
            margen_dias = st.slider("Ventana de correlación (días después del trabajo):", 1, 15, 5, key="reco_margen")

            resultados = []
            for _, av in df_avisos.iterrows():
                try:
                    f_trab = pd.to_datetime(av['FECHA_TRABAJO'], errors='coerce')
                    if pd.isna(f_trab):
                        continue
                except Exception:
                    continue

                cols_aviso = [c.strip().upper() for c in str(av['COLONIAS']).split(',') if c.strip()]
                if not cols_aviso:
                    continue

                col_serie = df_fallas_reco['COLONIA'].astype(str).str.upper()
                mask_col = col_serie.apply(lambda x: any(ca in x or x in ca for ca in cols_aviso))

                # Cruce adicional por PUERTO PON usando la infraestructura que se
                # mapeó al registrar la incidencia. Es más preciso que el nombre de
                # la colonia: si el corte tocó un ramal, toda orden de ese PON
                # pertenece al evento aunque la colonia venga escrita distinto.
                pones_guardados = {p.strip() for p in str(av.get('PONES', '')).split(',') if p.strip()}
                if pones_guardados:
                    nodo_serie_av = df_fallas_reco['OLT'].astype(str) + "/" + df_fallas_reco['PON'].astype(str)
                    mask_pon_av = nodo_serie_av.isin(pones_guardados)
                else:
                    mask_pon_av = pd.Series(False, index=df_fallas_reco.index)

                mask_fec = (df_fallas_reco['FECHA_REF'] >= f_trab) & (df_fallas_reco['FECHA_REF'] <= f_trab + pd.Timedelta(days=margen_dias))
                coincidencias = df_fallas_reco[(mask_col | mask_pon_av) & mask_fec]

                if not coincidencias.empty:
                    pon_afectados = coincidencias[coincidencias['PON'].str.len() > 0]['PON'].nunique()
                    try:
                        cli_riesgo_av = int(float(av.get('CLIENTES_RIESGO', 0) or 0))
                    except Exception:
                        cli_riesgo_av = 0
                    resultados.append({
                        'aviso': av, 'f_trab': f_trab, 'df': coincidencias,
                        'n': len(coincidencias), 'pon': pon_afectados,
                        'riesgo': cli_riesgo_av
                    })

            if not resultados:
                st.success("✅ Ningún aviso registrado coincide con fallas en el periodo analizado.")
            else:
                resultados.sort(key=lambda r: r['n'], reverse=True)
                st.error(f"🔗 **{len(resultados)}** aviso(s) coinciden con fallas posteriores.")

                for r in resultados:
                    av, coincid = r['aviso'], r['df']
                    n_cli_r = coincid['CLIENTE'].nunique()
                    marca_prog = "📅" if str(av.get('PROGRAMADA', '')).upper() == "SI" else "⚠️"
                    titulo = f"{marca_prog} {av['TIPO']} · {av['COLONIAS']} ({r['f_trab'].strftime('%d/%m/%Y')}) → {r['n']} orden(es)"
                    with st.expander(titulo):
                        k1, k2, k3 = st.columns(3)
                        k1.metric("📋 Órdenes", r['n'])
                        k2.metric("👤 Clientes que reportaron", n_cli_r)
                        if r.get('riesgo'):
                            k3.metric("📉 % de la zona", f"{n_cli_r / r['riesgo'] * 100:.1f}%")
                        else:
                            k3.metric("👥 Clientes en zona", "N/D")

                        if str(av.get('OLTS', '')).strip():
                            st.caption(f"🛰️ **OLT del sector:** {av['OLTS']}")

                        if r['pon'] == 1:
                            st.error("🔴 Todas las órdenes provienen de **un solo PON**: daño físico concentrado en ese ramal.")
                        elif r['pon'] > 1:
                            st.warning(f"🟠 Órdenes repartidas en **{r['pon']} puertos PON**: el evento afectó varios ramales.")

                        resumen_col_r = coincid.groupby(coincid['COLONIA'].astype(str).str.upper()).size().sort_values(ascending=False)
                        st.markdown("**Órdenes por colonia:** " + " · ".join(f"{c}: **{n}**" for c, n in resumen_col_r.items()))

                        st.caption(f"Comunicado: {str(av['TEXTO'])[:250]}")
                        cols_m = [c for c in ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'OLT', 'PON', 'FECHA_REF', 'ESTADO', 'TECNICO', 'EVIDENCIA', 'COMENTARIO'] if c in coincid.columns]
                        st.dataframe(coincid[cols_m].sort_values('FECHA_REF'), use_container_width=True, hide_index=True)

                        st.download_button(
                            "📥 Descargar clientes afectados (CSV)",
                            data=coincid[cols_m].to_csv(index=False).encode('utf-8'),
                            file_name=f"impacto_{r['f_trab'].strftime('%Y%m%d')}_{str(av['COLONIAS'])[:20]}.csv",
                            mime="text/csv",
                            key=f"dl_imp_{r['f_trab'].strftime('%Y%m%d')}_{r['n']}_{n_cli_r}"
                        )

            with st.expander(f"📋 Incidencias registradas ({len(df_avisos)})"):
                cols_hist = [c for c in ['FECHA_TRABAJO', 'TIPO', 'PROGRAMADA', 'COLONIAS', 'OLTS', 'CLIENTES_RIESGO', 'REGISTRADO_POR'] if c in df_avisos.columns]
                st.dataframe(
                    df_avisos[cols_hist].sort_values('FECHA_TRABAJO', ascending=False),
                    use_container_width=True, hide_index=True
                )


def main():
    settings.inicializar_configuracion() 

    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')
    es_admin_o_supervisor = str(rol_usuario).strip().lower() in ['admin', 'jefe']
    
    # Se fuerza es_movil a False para unificar la interfaz de escritorio en todos los roles
    es_movil = False

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error("Error al inicializar la conexión con Google Sheets.")
        conn = None

    if str(rol_usuario).strip().lower() == 'llamados':
        expediente.mostrar_modulo_expedientes(conn, pd.DataFrame())
        mostrar_boton_logout() 
        st.stop() 

    sidebar_top = st.sidebar.container()
    sidebar_bottom = st.sidebar.container()
    
    # === SISTEMA DE NAVEGACIÓN RESISTENTE A REINICIOS ===
    if 'nav_menu_diamante' not in st.session_state:
        st.session_state['nav_menu_diamante'] = "⚡ Monitor en Vivo"

    if es_movil and option_menu is not None:
        st.markdown("""
            <style>
            [data-testid="collapsedControl"] { display: none; }
            .bottom-menu-container {
                position: fixed; bottom: 0; left: 0; width: 100%; z-index: 9999;
                background-color: #1A1D24; padding-bottom: 10px; padding-top: 5px;
                border-top: 1px solid #2D2F39; box-shadow: 0px -2px 10px rgba(0,0,0,0.5);
            }
            </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="bottom-menu-container">', unsafe_allow_html=True)
        
        if rol_usuario in ['admin', 'jefe']:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor", "Reportes", "Vehículos", "Más"],
                icons=["lightning", "bar-chart", "car-front", "list"],
                default_index=0,
                orientation="horizontal",
                key="mobile_nav_menu_opt",
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#94A3B8", "font-size": "20px"}, 
                    "nav-link": {"font-size": "11px", "text-align": "center", "margin":"0px", "--hover-color": "#2D2F39", "padding": "5px"},
                    "nav-link-selected": {"background-color": "transparent", "color": "#3B82F6", "font-weight": "bold"},
                }
            )
            if selected_nav == "Monitor": nav_menu_diamante = "⚡ Monitor en Vivo"
            elif selected_nav == "Reportes": nav_menu_diamante = "📊 Centro de Reportes"
            elif selected_nav == "Vehículos": nav_menu_diamante = "🚙 Auditoría Vehículos"   
            else: 
                nav_menu_diamante = st.selectbox("Seleccione un módulo extra:", ["🏅 Control Calidad", "📅 Reprog / No Inst", "⚙️ Configuración", "📁 Expedientes"], key="mobile_extra_sel_opt")    
        else:
            selected_nav = option_menu(
                menu_title=None,
                options=["Monitor", "Calidad"],
                icons=["lightning", "award"],
                default_index=0,
                orientation="horizontal",
                key="mobile_nav_menu_opt",
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#94A3B8", "font-size": "20px"}, 
                    "nav-link": {"font-size": "11px", "text-align": "center", "margin":"0px", "--hover-color": "#2D2F39", "padding": "5px"},
                    "nav-link-selected": {"background-color": "transparent", "color": "#3B82F6", "font-weight": "bold"},
                }
            )
            if selected_nav == "Monitor": 
                nav_menu_diamante = "⚡ Monitor en Vivo"
            else: 
                nav_menu_diamante = "🏅 Control Calidad"
            
        st.markdown('</div>', unsafe_allow_html=True)
        if nav_menu_diamante != "⚡ Monitor en Vivo": st.divider()
        st.session_state['nav_menu_diamante'] = nav_menu_diamante
    else:
        # Definición segura de las opciones según el rol
        if rol_usuario in ['admin', 'jefe']:
            opciones_menu = ["⚡ Monitor en Vivo", "📊 Centro de Reportes", "🏅 Control Calidad", "📅 Reprog / No Inst", "🚙 Auditoría Vehículos", "⚙️ Configuración", "📁 Expedientes"]
        else:
            opciones_menu = ["⚡ Monitor en Vivo", "🏅 Control Calidad"]

        # Buscar el índice del valor actual de sesión para que nunca se pierda la selección
        default_val = st.session_state.get('nav_menu_diamante', "⚡ Monitor en Vivo")
        if default_val in opciones_menu:
            default_index = opciones_menu.index(default_val)
        else:
            default_index = 0

        with sidebar_top:
            if rol_usuario in ['admin', 'jefe']: 
                nav_menu_diamante = st.radio(
                    "MENÚ DE CONTROL:", 
                    opciones_menu, 
                    index=default_index, 
                    key="nav_menu_radio_admin"
                )
            else:
                st.markdown("### 🖥️ Menú de Control")
                nav_menu_diamante = st.radio(
                    "SELECCIONE EL MÓDULO:", 
                    opciones_menu, 
                    index=default_index, 
                    key="nav_menu_radio_user"
                )
            # Sincronizamos la variable de sesión persistente
            st.session_state['nav_menu_diamante'] = nav_menu_diamante

    with sidebar_top:
        mostrar_boton_logout()
        st.divider()

    with sidebar_bottom:
        btn_api_procesar = False
        file_act_ptr = None
        file_disp_ptr = None

        if not es_movil: st.markdown("<br><br>", unsafe_allow_html=True)
        st.divider()

        if es_admin_o_supervisor:
            st.markdown("### 📝 Ingresar Orden Manual")
            with st.expander("Ingresar una orden que no se refleja en el sistema", expanded=False):
                st.caption("Úsalo cuando la API falle y una orden real de un técnico no aparezca en el monitor.")

                num_orden_manual = st.text_input("Número de orden", key="input_num_orden_manual")

                actividades_orden_manual = sorted(ACTIVIDADES_GANTT_PERMITIDAS)
                actividad_manual_sel = st.selectbox("Actividad", options=actividades_orden_manual, key="sel_actividad_orden_manual")

                lista_tecs_principales_manual = []
                try:
                    df_cat_tecs_manual = cargar_catalogo_tecnicos()
                    if df_cat_tecs_manual is not None and not df_cat_tecs_manual.empty:
                        lista_tecs_principales_manual = sorted(
                            df_cat_tecs_manual[df_cat_tecs_manual['Clasificación'] == 'TÉCNICO PRINCIPAL']['Nombre'].dropna().unique().tolist()
                        )
                except Exception:
                    pass

                if lista_tecs_principales_manual:
                    tec_orden_manual_sel = st.selectbox("Técnico", options=lista_tecs_principales_manual, key="sel_tec_orden_manual")
                else:
                    tec_orden_manual_sel = st.text_input("Técnico (nombre exacto)", key="input_tec_orden_manual")

                fecha_orden_manual_sel = st.date_input("Fecha", value=get_honduras_time().date(), key="fecha_orden_manual_sel")
                col_omi, col_oml = st.columns(2)
                with col_omi:
                    hora_ini_orden_manual_txt = st.text_input("Hora inicio (HH:MM)", value="", placeholder="08:00", key="hora_ini_orden_manual", max_chars=5)
                with col_oml:
                    hora_liq_orden_manual_txt = st.text_input("Hora liquidada (HH:MM)", value="", placeholder="Dejar vacío si sigue abierta", key="hora_liq_orden_manual", max_chars=5)

                if st.button("💾 Guardar Orden Manual", use_container_width=True, key="btn_guardar_orden_manual"):
                    hora_ini_om_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_ini_orden_manual_txt.strip())
                    hora_liq_om_valida = (hora_liq_orden_manual_txt.strip() == "") or re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_liq_orden_manual_txt.strip())
                    if not num_orden_manual.strip():
                        st.warning("Ingresa el número de orden.")
                    elif not tec_orden_manual_sel:
                        st.warning("Selecciona o escribe un técnico.")
                    elif not hora_ini_om_valida:
                        st.warning("La hora de inicio debe tener formato HH:MM en 24 horas (ej. 08:00).")
                    elif not hora_liq_om_valida:
                        st.warning("La hora liquidada debe tener formato HH:MM en 24 horas (ej. 14:30), o dejarse vacía si la orden sigue abierta.")
                    else:
                        ok_orden_manual = guardar_orden_manual(
                            num_orden=num_orden_manual.strip(),
                            actividad=actividad_manual_sel,
                            tecnico=tec_orden_manual_sel,
                            fecha=fecha_orden_manual_sel.strftime('%Y-%m-%d'),
                            hora_inicio=hora_ini_orden_manual_txt.strip(),
                            hora_liq=hora_liq_orden_manual_txt.strip(),
                            registrado_por=st.session_state.get('usuario_actual', rol_usuario)
                        )
                        if ok_orden_manual:
                            st.success(f"✅ Orden {num_orden_manual.strip()} guardada manualmente para {tec_orden_manual_sel}.")
                            st.cache_data.clear()
                        else:
                            st.error("No se pudo guardar la orden manual.")
        st.divider()

        if es_admin_o_supervisor:
            st.markdown("### 🍽️ Registrar Almuerzo")
            with st.expander("Ingresar hora de almuerzo de un técnico", expanded=False):
                lista_tecs_almuerzo = []
                df_base_for_tecs = st.session_state.get('df_base')
                
                if df_base_for_tecs is not None and not df_base_for_tecs.empty and 'TECNICO' in df_base_for_tecs.columns:
                    lista_tecs_almuerzo = sorted(df_base_for_tecs['TECNICO'].dropna().unique().tolist())
                
                if not lista_tecs_almuerzo:
                    try:
                        df_cat_tecs = cargar_catalogo_tecnicos()
                        if df_cat_tecs is not None and not df_cat_tecs.empty:
                            lista_tecs_almuerzo = sorted(df_cat_tecs['Nombre'].dropna().unique().tolist())
                    except Exception:
                        pass
                
                if not lista_tecs_almuerzo and os.path.exists("gps.txt"):
                    try:
                        with open("gps.txt", "r", encoding="utf-8") as f:
                            for line in f:
                                parts = line.strip().split(",")
                                if len(parts) >= 3:
                                    lista_tecs_almuerzo.append(parts[2].strip().rstrip("."))
                        lista_tecs_almuerzo = sorted(list(set(lista_tecs_almuerzo)))
                    except Exception:
                        pass

                if lista_tecs_almuerzo:
                    tec_almuerzo_sel = st.selectbox("Técnico", options=lista_tecs_almuerzo, key="sel_tec_almuerzo")
                else:
                    tec_almuerzo_sel = st.text_input("Técnico (nombre exacto)", key="input_tec_almuerzo")

                fecha_almuerzo_sel = st.date_input("Fecha", value=get_honduras_time().date(), key="fecha_almuerzo_sel")
                col_hi, col_hf = st.columns(2)
                with col_hi:
                    hora_ini_almuerzo_txt = st.text_input("Hora inicio (HH:MM)", value="12:00", key="hora_ini_almuerzo", max_chars=5)
                with col_hf:
                    hora_fin_almuerzo_txt = st.text_input("Hora fin (HH:MM)", value="13:00", key="hora_fin_almuerzo", max_chars=5)

                if st.button("💾 Guardar Almuerzo", use_container_width=True, key="btn_guardar_almuerzo"):
                    hora_ini_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_ini_almuerzo_txt.strip())
                    hora_fin_valida = re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora_fin_almuerzo_txt.strip())
                    if not tec_almuerzo_sel:
                        st.warning("Selecciona o escribe un técnico.")
                    elif not hora_ini_valida or not hora_fin_valida:
                        st.warning("La hora debe tener formato HH:MM en 24 horas (ej. 12:00, 13:30).")
                    else:
                        ok_almuerzo = guardar_almuerzo(
                            conn,
                            tecnico=tec_almuerzo_sel,
                            fecha=fecha_almuerzo_sel.strftime('%Y-%m-%d'),
                            hora_inicio=hora_ini_almuerzo_txt.strip(),
                            hora_fin=hora_fin_almuerzo_txt.strip(),
                            registrado_por=st.session_state.get('usuario_actual', rol_usuario)
                        )
                        if ok_almuerzo:
                            st.success(f"✅ Almuerzo de {tec_almuerzo_sel} guardado para el {fecha_almuerzo_sel.strftime('%d/%m/%Y')}.")
                        else:
                            st.error("No se pudo guardar el almuerzo. Revisa la conexión con Sheets.")
        st.divider()

        st.markdown("### ☁️ Sincronización")
        if st.button("☁️ ACTUALIZAR DESDE LA NUBE", use_container_width=True, key="btn_nube_sidebar"):
            if conn is not None:
                sincronizar_datos_nube(conn)
            else:
                st.error("Conexión no disponible.")

        st.divider()
        st.markdown("### 📥 Carga de Archivos")

        # Indicador de antigüedad de los datos en memoria. Los datos NO se
        # refrescan solos: quedan congelados en la sesión desde que se cargaron.
        # Sin este aviso, una sesión abierta hace horas muestra información vieja
        # sin ninguna señal, y parece que "faltan órdenes" cuando en realidad lo
        # que falta es actualizar.
        _cargado_en = st.session_state.get('df_base_cargado_en')
        if _cargado_en is not None:
            try:
                _minutos_datos = int((get_honduras_time() - _cargado_en).total_seconds() // 60)
                _hora_datos = _cargado_en.strftime('%H:%M')
                if _minutos_datos >= 60:
                    st.warning(f"⚠️ Datos cargados a las {_hora_datos} (hace {_minutos_datos // 60}h {_minutos_datos % 60}min). Actualiza para ver las órdenes más recientes.")
                elif _minutos_datos >= 20:
                    st.info(f"🕒 Datos cargados a las {_hora_datos} (hace {_minutos_datos} min).")
                else:
                    st.caption(f"🟢 Datos actualizados a las {_hora_datos}.")
            except Exception:
                pass
        
        if es_admin:
            st.markdown("#### ⚡ Actualización Inmediata")
            btn_api_procesar = st.button("🔄 FORZAR ACTUALIZACIÓN INMEDIATA", use_container_width=True, type="primary", key="btn_forzar_act_admin")
            
            st.divider()
            st.markdown("#### 📄 Actividades (rep_actividades)")
            st.caption("Solo necesitas subir las actividades. El catálogo FTTX se toma automáticamente de la nube (pestaña FTTX / GCS).")
            archivo_actividades = st.file_uploader("Sube rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_actividades_admin")
            if archivo_actividades: file_act_ptr = archivo_actividades
            btn_reprocesar = st.button("🔄 PROCESAR ACTIVIDADES", use_container_width=True, key="btn_proc_act_admin")

            st.divider()
            st.markdown("#### 🚙 Catálogo FTTX")
            st.caption("Sube esto SOLO cuando necesites actualizar el catálogo de dispositivos en la nube. No requiere subir actividades a la vez.")
            archivo_fttx = st.file_uploader("Sube FttxActiveDevice", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_fttx_admin")
            btn_actualizar_fttx = st.button("🔄 ACTUALIZAR SOLO CATÁLOGO FTTX", use_container_width=True, key="btn_act_fttx_admin")

            if archivo_fttx:
                try:
                    with open("cache_fttx.tmp", "wb") as f: f.write(archivo_fttx.getvalue())
                except: pass

            if btn_actualizar_fttx:
                if archivo_fttx is None:
                    st.warning("Primero selecciona un archivo FttxActiveDevice para subir.")
                elif conn is None:
                    st.error("Conexión no disponible.")
                else:
                    with st.spinner("⏳ Subiendo catálogo FTTX a la nube..."):
                        try:
                            archivo_fttx.seek(0)
                            if archivo_fttx.name.lower().endswith('.csv'):
                                df_fttx_subir = pd.read_csv(archivo_fttx, sep=None, engine='python')
                            else:
                                df_fttx_subir = pd.read_excel(archivo_fttx, engine='openpyxl')

                            if df_fttx_subir is None or df_fttx_subir.empty:
                                st.error("El archivo se leyó pero está vacío.")
                            else:
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", data=df_fttx_subir)
                                st.success(f"✅ Catálogo FTTX actualizado en la nube ({len(df_fttx_subir)} registros).")

                                try:
                                    sobrescribir_archivo_gcs(df_fttx_subir, NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                                except Exception:
                                    pass
                        except Exception as e_fttx_up:
                            st.error(f"No se pudo procesar/subir el archivo FTTX: {e_fttx_up}")
        else:
            st.caption("Solo necesitas subir las actividades. FTTX se bajará de la nube.")
            archivo_unico = st.file_uploader("Sube únicamente el rep_actividades", type=["xlsx", "csv"], accept_multiple_files=False, key="uploader_unico_user")
            if archivo_unico: file_act_ptr = archivo_unico
            btn_reprocesar = st.button("🔄 PROCESAR ARCHIVO SUBIDO", use_container_width=True, key="btn_proc_act_user")
            btn_actualizar_fttx = False

        ahora_hx = get_honduras_time()
        es_horario_tarde = ahora_hx.hour >= 17
        es_fin_de_semana = (ahora_hx.weekday() == 5 and ahora_hx.hour >= 13) or (ahora_hx.weekday() == 6)
        condicion_usar_cache = es_horario_tarde or es_fin_de_semana
        
        if condicion_usar_cache and file_act_ptr is not None and file_disp_ptr is None and es_admin:
            if os.path.exists("cache_fttx.tmp"):
                try:
                    with open("cache_fttx.tmp", "rb") as f: file_disp_ptr = f.read()
                    st.info("🕒 **Modo Caché Activo:** Se cargó automáticamente el último archivo FTTX guardado.")
                except: pass

    # ==============================================================================
    # 2. CARGA Y PROCESAMIENTO DE DATOS (MIGRADO A GCS CON API INTEGRADA)
    # ==============================================================================
    if 'df_base' not in st.session_state or btn_reprocesar or btn_api_procesar:
        if btn_api_procesar:
            if conn is not None:
                sincronizar_datos_nube(conn)
            else:
                st.error("Conexión no disponible.")

        elif btn_reprocesar:
            if file_act_ptr is not None and file_disp_ptr is None:
                with st.spinner("⏳ Descargando base de Vehículos/Dispositivos..."):
                    try:
                        df_fttx_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", ttl=600)
                        if df_fttx_cloud is None or df_fttx_cloud.empty:
                            df_fttx_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                        
                        if df_fttx_cloud is not None and not df_fttx_cloud.empty:
                            b_io = io.BytesIO()
                            with pd.ExcelWriter(b_io, engine='openpyxl') as writer:
                                df_fttx_cloud.to_excel(writer, index=False)
                            file_disp_ptr = b_io.getvalue()
                        else: raise ValueError("La pestaña FTTX está vacía.")
                    except Exception as e:
                        b_io = io.BytesIO()
                        with pd.ExcelWriter(b_io, engine='openpyxl') as writer:
                            pd.DataFrame(columns=['ID']).to_excel(writer, index=False)
                        file_disp_ptr = b_io.getvalue()

            if file_act_ptr is None or file_disp_ptr is None:
                if st.session_state.get('df_base') is None:
                    if os.path.exists("Logotipo monitor.png"):
                        col1_img, col2_img, col3_img = st.columns([1, 2, 1])
                        with col2_img:
                            st.image("Logotipo monitor.png", use_container_width=True)
                    else:
                        st.title("⚡ Monitor Operativo Maxcom PRO")
                    
                    st.info("💡 Sesión iniciada correctamente. Los datos de la operación no están cargados en memoria.")
                    st.markdown("<br><br>", unsafe_allow_html=True)
                    
                    col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
                    with col_c2:
                        if st.button("📥 DESCARGAR DATOS AHORA", type="primary", use_container_width=True, key="btn_nube_central"):
                            if conn is not None: 
                                sincronizar_datos_nube(conn)
                            else: 
                                st.error("Conexión no disponible.")
                    return
            else:
                res_p_diamante, res_h_diamante = cargar_y_limpiar_crudos_diamante_monitor(file_act_ptr, file_disp_ptr)
                if res_p_diamante is not None:
                    st.session_state.df_hist = res_h_diamante
                    if conn is not None:
                        with st.spinner("⏳ Sincronizando y uniendo con histórico en GCS..."):
                            try:
                                df_new = res_p_diamante.copy()
                                if 'NUM' in df_new.columns:
                                    df_new['NUM'] = df_new['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    df_new.loc[df_new['NUM'] == 'nan', 'NUM'] = 'N/D'
                                    
                                df_cloud = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                                if df_cloud is None or df_cloud.empty:
                                    df_cloud = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                                    
                                if df_cloud is not None and not df_cloud.empty:
                                    df_cloud.columns = df_cloud.columns.str.upper().str.strip()
                                    if 'NUM' in df_cloud.columns:
                                        df_cloud['NUM'] = df_cloud['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                        df_cloud.loc[df_cloud['NUM'] == 'nan', 'NUM'] = 'N/D'
                                    if 'ACTIVIDAD' in df_cloud.columns:
                                        mask_basura_cloud = df_cloud['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_BASURA)
                                        df_cloud = df_cloud[~mask_basura_cloud].copy()
                                    
                                    if 'EMPRESA' in df_cloud.columns:
                                        empresa_upper_cloud = df_cloud['EMPRESA'].astype(str).str.strip().str.upper()
                                        mask_otra_empresa_cloud = (empresa_upper_cloud != '') & (empresa_upper_cloud != 'NAN') & (empresa_upper_cloud != 'NONE') & (~empresa_upper_cloud.str.contains('ISCA', na=False))
                                        df_cloud = df_cloud[~mask_otra_empresa_cloud].copy()

                                    PATRON_VIVAS_NUBE = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                    mask_vivas_nube = df_cloud['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS_NUBE, na=False)
                                    df_historial_puro = df_cloud[~mask_vivas_nube].copy()
                                    df_combined = pd.concat([df_historial_puro, df_new])
                                else: df_combined = df_new
                                    
                                if 'NUM' in df_combined.columns:
                                    df_combined['NUM'] = df_combined['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    
                                    df_combined['SORT_DATE'] = pd.to_datetime(df_combined['HORA_LIQ'], errors='coerce')
                                    df_combined['SORT_DATE'] = df_combined['SORT_DATE'].fillna(pd.to_datetime(df_combined['FECHA_APE'], errors='coerce'))
                                    df_combined['SORT_DATE'] = df_combined['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
                                    
                                    PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
                                    df_combined['ES_VIVA'] = df_combined['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)
                                    
                                    df_combined = df_combined.sort_values(by=['ES_VIVA', 'SORT_DATE'], ascending=[False, True])
                                    
                                    df_validos = df_combined[df_combined['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
                                    df_nd = df_combined[df_combined['NUM'] == 'N/D']
                                    df_combined = pd.concat([df_validos, df_nd]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')

                                df_to_upload = df_combined.copy()
                                for c_date in ['HORA_INI', 'HORA_LIQ', 'FECHA_APE']:
                                    if c_date in df_to_upload.columns:
                                        df_to_upload[c_date] = pd.to_datetime(df_to_upload[c_date], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
                                        
                                sobrescribir_archivo_gcs(df_to_upload, NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                                conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", data=df_to_upload)
                                st.session_state.df_base = df_combined
                                
                                if es_admin and file_disp_ptr is not None and not isinstance(file_disp_ptr, bytes):
                                    try:
                                        if hasattr(file_disp_ptr, 'read'): 
                                            file_disp_ptr.seek(0)
                                            bytes_fttx = file_disp_ptr.read()
                                            sobrescribir_archivo_gcs(bytes_fttx, NOMBRE_BUCKET_SISTEMA, "fttx_activo.csv")
                                            file_disp_ptr.seek(0)

                                        if getattr(file_disp_ptr, 'name', '').lower().endswith('.csv'): 
                                            df_fttx_up = pd.read_csv(file_disp_ptr, sep=None, engine='python')
                                        else: 
                                            df_fttx_up = pd.read_excel(file_disp_ptr, engine='openpyxl')
                                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="FTTX", data=df_fttx_up)
                                    except Exception as e_fttx: pass
                                
                                st.success("✅ Datos sincronizados en GCS y unidos al historial correctamente.")
                                import time
                                time.sleep(1)
                                st.rerun()
                            except Exception as e: 
                                st.warning(f"Se procesó localmente, pero falló la sincronización con la nube: {e}")
                                st.session_state.df_base = res_p_diamante
                    else: 
                        st.session_state.df_base = res_p_diamante
                        st.success("✅ Datos procesados localmente.")
                else: return

        if 'df_base' not in st.session_state:
            df_gcs_init = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
            if df_gcs_init is not None and not df_gcs_init.empty:
                st.session_state.df_base = df_gcs_init
            else:
                if os.path.exists("Logotipo monitor.png"):
                    col1_img, col2_img, col3_img = st.columns([1, 2, 1])
                    with col2_img:
                        st.image("Logotipo monitor.png", use_container_width=True)
                else:
                    st.title("⚡ Monitor Operativo Maxcom PRO")

                st.info("💡 Sesión iniciada correctamente. Los datos de la operación no están cargados en memoria.")
                st.markdown("<br><br>", unsafe_allow_html=True)

                col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
                with col_c2:
                    if st.button("📥 DESCARGAR DATOS AHORA", type="primary", use_container_width=True, key="btn_nube_fallback_inicial"):
                        if conn is not None:
                            sincronizar_datos_nube(conn)
                        else:
                            st.error("Conexión no disponible.")
                return

    # Marca de tiempo del "snapshot" de datos que vive en memoria de ESTA sesión.
    # df_base se guarda en st.session_state y NO se refresca solo: cada sesión
    # conserva la foto de los datos del momento en que se cargó. Por eso dos
    # usuarios distintos pueden ver información diferente al mismo tiempo si uno
    # abrió su sesión antes que el otro. Guardar la hora permite avisarlo.
    if btn_reprocesar or btn_api_procesar or st.session_state.get('df_base_cargado_en') is None:
        st.session_state['df_base_cargado_en'] = get_honduras_time()

    df_base = st.session_state.df_base.copy()

    # ==============================================================================
    # EXTRACCIÓN Y MAPEO DINÁMICO DEL ARCHIVO GPS.TXT
    # ==============================================================================
    gps_map = {}
    if os.path.exists("gps.txt"):
        try:
            with open("gps.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) >= 3:
                        g_url = parts[0].strip()
                        g_name = parts[2].strip().rstrip(".")
                        gps_map[normalizar_nombre_cruce(g_name)] = g_url
        except Exception as e:
            pass
    
    if not df_base.empty:
        if 'TECNICO' in df_base.columns:
            df_base['TECNICO'] = df_base['TECNICO'].astype(str).str.strip().str.upper()
            df_base['TECNICO_NORM'] = df_base['TECNICO'].apply(normalizar_nombre_cruce)
            
            def buscar_enlace_gps(tecnico_norm):
                if not tecnico_norm:
                    return ""
                if tecnico_norm in gps_map:
                    return gps_map[tecnico_norm]
                for gps_name, url in gps_map.items():
                    words_gps = set(gps_name.split())
                    words_tec = set(tecnico_norm.split())
                    if words_gps.issubset(words_tec) and len(words_gps) >= 2:
                        return url
                    if words_tec.issubset(words_gps) and len(words_tec) >= 2:
                        return url
                return ""
                
            df_base['GPS'] = df_base['TECNICO_NORM'].apply(buscar_enlace_gps)
            df_base.drop(columns=['TECNICO_NORM'], errors='ignore', inplace=True)
        else:
            df_base['GPS'] = ""
            
        if 'ACTIVIDAD' in df_base.columns:
            df_base['ACTIVIDAD'] = df_base['ACTIVIDAD'].astype(str).str.strip().str.upper()
            df_base = df_base[(df_base['ACTIVIDAD'] != '') & (df_base['ACTIVIDAD'] != 'NAN') & df_base['ACTIVIDAD'].notna()]

        df_base = df_base.drop_duplicates()
        
        if 'HORA_LIQ' in df_base.columns:
            df_base['HORA_LIQ'] = pd.to_datetime(df_base['HORA_LIQ'], dayfirst=True, errors='coerce')
    
    # Copia previa al filtro de actividad. Se define siempre (aunque no exista la
    # columna ACTIVIDAD) para que las vistas que dependen de ella nunca fallen.
    df_base_sin_filtro_actividad = df_base.copy()

    if 'ACTIVIDAD' in df_base.columns:
        # FILTRO GLOBAL POR LISTA BLANCA. Antes se usaba una lista negra
        # (ACTIVIDADES_BASURA), lo que obligaba a ir agregando cada actividad
        # indeseada una por una conforme aparecía. Ahora se invierte el criterio:
        # SOLO sobreviven las actividades de la lista maestra. Como este filtro se
        # aplica sobre df_base -- la raíz de la que derivan el Monitor, el Gantt,
        # asignadas, pendientes, reportes y PDFs -- cualquier otra actividad queda
        # descartada de toda la aplicación y no puede reaparecer en ninguna vista.
        mask_actividad_permitida = df_base['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_PERMITIDAS)
        df_base = df_base[mask_actividad_permitida].copy()

    if 'NUM' in df_base.columns:
        df_base['NUM'] = df_base['NUM'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        
        df_base['SORT_DATE'] = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce')
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.to_datetime(df_base['FECHA_APE'], errors='coerce'))
        df_base['SORT_DATE'] = df_base['SORT_DATE'].fillna(pd.Timestamp('1970-01-01'))
        
        PATRON_VIVAS = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
        df_base['ES_VIVA'] = df_base['ESTADO'].astype(str).str.upper().str.contains(PATRON_VIVAS, na=False)

        # DEDUPLICACIÓN POR NUM: debe sobrevivir el registro MÁS RECIENTE.
        #
        # Antes se ordenaba por ES_VIVA primero (descendente) y se conservaba el
        # último, lo que hacía que CUALQUIER registro no-vivo le ganara siempre a
        # la versión viva, sin importar las fechas. Si una orden traía un registro
        # viejo CERRADA/ANULADA además del registro vivo actual, se conservaba el
        # viejo y la orden real desaparecía del Monitor, del Gantt y de pendientes.
        #
        # Ahora manda SORT_DATE (recencia). Esto sigue funcionando bien para las
        # órdenes genuinamente cerradas, porque su HORA_LIQ siempre es posterior a
        # su propia FECHA_APE, así que el registro cerrado gana por sí solo.
        # ES_VIVA queda únicamente como desempate: si dos registros tienen la misma
        # fecha, prevalece el estado final (no vivo).
        df_base = df_base.sort_values(by=['SORT_DATE', 'ES_VIVA'], ascending=[True, False])

        df_validos = df_base[df_base['NUM'] != 'N/D'].drop_duplicates(subset=['NUM'], keep='last')
        df_invalidos = df_base[df_base['NUM'] == 'N/D']
        df_base = pd.concat([df_validos, df_invalidos]).drop(columns=['SORT_DATE', 'ES_VIVA'], errors='ignore')

    df_base = procesar_fechas_seguro(df_base, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'], columnas_sin_asumir_hoy=['HORA_LIQ', 'FECHA_APE'])

    # === INTEGRACIÓN DE ÓRDENES MANUALES ===
    # Se agregan las órdenes cargadas manualmente (para cuando la API falla y
    # una orden real no se refleja). Si la orden real ya llegó después por la
    # API/Sheets (mismo NUM), se descarta la versión manual para no duplicar.
    try:
        df_ordenes_manuales = cargar_ordenes_manuales()
        if df_ordenes_manuales is not None and not df_ordenes_manuales.empty:
            if 'NUM' in df_base.columns:
                nums_ya_reales = set(df_base['NUM'].astype(str).str.strip())
                df_ordenes_manuales = df_ordenes_manuales[~df_ordenes_manuales['NUM'].astype(str).str.strip().isin(nums_ya_reales)]
            if not df_ordenes_manuales.empty:
                df_base = pd.concat([df_base, df_ordenes_manuales], ignore_index=True)
    except Exception:
        pass
    
    # === FILTRADO AVANZADO DE FALSOS OFFLINE USANDO TELEMETRÍA REAL FTTX ===
    col_olt_info = None
    for col in df_base.columns:
        sample_vals = df_base[col].dropna().astype(str)
        if sample_vals.str.contains("onustatus|statusText|adminState|rxPower", case=False, regex=True).any():
            col_olt_info = col
            break
            
    if col_olt_info:
        def determinar_si_esta_online(val):
            if pd.isnull(val):
                return False
            t = str(val).lower().strip()
            if not t:
                return False
            if "onustatus: down" in t or "onustatus:down" in t or "status: offline" in t or "status_text: offline" in t or "statustext: offline" in t or "statustext:offline" in t:
                return False
            is_up = "onustatus: up" in t or "onustatus:up" in t or "statustext: online" in t or "status_text: online" in t or "statustext:online" in t
            if is_up:
                dbm_real = None
                rx_match = re.search(r'\brx:\s*(-?\d+\.?\d*)', t)
                if rx_match:
                    try: dbm_real = float(rx_match.group(1)) / 100.0
                    except: pass
                rxpower_match = re.search(r'rxpower:\s*(-?\d+\.?\d*)', t)
                if rxpower_match:
                    try: dbm_real = float(rxpower_match.group(1)) / 1000.0
                    except: pass
                if dbm_real is not None:
                    if dbm_real <= -30:
                        return False
                return True
            return False
            
        mask_realmente_online = df_base[col_olt_info].apply(determinar_si_esta_online)
        df_base.loc[mask_realmente_online, 'ES_OFFLINE'] = False

    if 'SUSCRIPTOR' in df_base.columns and 'NOMBRE' not in df_base.columns: df_base.rename(columns={'SUSCRIPTOR': 'NOMBRE'}, inplace=True)
    elif 'NOMBRE CLIENTE' in df_base.columns and 'NOMBRE' not in df_base.columns: df_base.rename(columns={'NOMBRE CLIENTE': 'NOMBRE'}, inplace=True)

    for col_b in ['ES_OFFLINE', 'ALERTA_TIEMPO']:
        if col_b in df_base.columns: df_base[col_b] = df_base[col_b].astype(str).str.upper().str.strip().isin(['TRUE', 'VERDADERO', '1', '1.0'])
            
    if 'ACTIVIDAD' in df_base.columns:
        act_upper_global = df_base['ACTIVIDAD'].fillna('').astype(str).str.upper()
        mask_no_criticas_g = act_upper_global.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)
        mask_solo_sop_g = act_upper_global.str.contains('SOPFIBRA', regex=True)
        
        if 'ES_OFFLINE' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ES_OFFLINE'] = False
            df_base.loc[~mask_solo_sop_g, 'ES_OFFLINE'] = False
        if 'ALERTA_TIEMPO' in df_base.columns:
            df_base.loc[mask_no_criticas_g, 'ALERTA_TIEMPO'] = False
            df_base.loc[~mask_solo_sop_g, 'ALERTA_TIEMPO'] = False
            
        def extraer_motivo_falla(row): return "🔧 Mantenimiento General"
        def extraer_segmento_global(row): return "RESIDENCIAL"

        com_up_g = df_base['COMENTARIO'].fillna('').astype(str).str.upper()
        cli_up_g = df_base['CLIENTE'].fillna('').astype(str).str.upper()
        texto_g = act_upper_global + " " + com_up_g

        cond_off = df_base.get('ES_OFFLINE', pd.Series([False]*len(df_base))) == True
        cond_ins = texto_g.str.contains("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", regex=True)
        cond_niv = texto_g.str.contains("NIVEL|DB|POTENCIA|ATENU", regex=True)
        cond_tv  = texto_g.str.contains("TV|CABLE|SEÑAL", regex=True)
        cond_nav = texto_g.str.contains("NAV|INTERNET|LENT", regex=True)

        df_base['MOTIVO'] = np.select(
            [cond_off, cond_ins, cond_niv, cond_tv, cond_nav],
            ["🔴 Offline / Caída", "📦 Instalación / Cambio", "⚡ Niveles Alterados", "📺 Falla de TV", "🌐 Lentitud / Navegación"],
            default="🔧 Mantenimiento General"
        )

        texto_seg_g = act_upper_global + " " + cli_up_g + " " + com_up_g
        df_base['SEGMENTO'] = np.where(texto_seg_g.str.contains('PLEX|PEXTERNO|SPLITTEROPT', regex=True), 'PLEX', 'RESIDENCIAL')

    for col_n in ['DIAS_RETRASO', 'MINUTOS_CALC']:
        if col_n in df_base.columns: df_base[col_n] = pd.to_numeric(df_base[col_n], errors='coerce').fillna(0)
    for col_txt in ['NUM', 'CLIENTE']:
        if col_txt in df_base.columns:
            df_base[col_txt] = pd.to_numeric(df_base[col_txt], errors='coerce').fillna(0).astype(int).astype(str)
            df_base[col_txt] = df_base[col_txt].replace('0', 'N/D')
    
    ahora_local = get_honduras_time()
    hoy_date_valor = ahora_local.date()
    df_base_activa = df_base.copy()

    # === CORRECCIÓN DE ESPACIOS EN SOP FIBRA PARA ES_OFFLINE (RESUELVE CAÍDAS 0) ===
    if 'ACTIVIDAD' in df_base_activa.columns and 'COMENTARIO' in df_base_activa.columns:
        act_upper_c = df_base_activa['ACTIVIDAD'].fillna('').astype(str).str.upper().str.strip()
        est_upper_c = df_base_activa['ESTADO'].fillna('').astype(str).str.upper().str.strip()
        com_upper_c = df_base_activa['COMENTARIO'].fillna('').astype(str).str.upper().str.strip()
        
        mask_sop_c = act_upper_c.str.contains(r'SOP\s*FIBRA|SOP_FIBRA', regex=True)
        mask_falsos_c = act_upper_c.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)
        mask_est_abierto_c = est_upper_c != 'CERRADA'
        mask_com_off_c = com_upper_c.str.contains("ONU OFFLINE|OFF LINE|OFFLINE|LOS EN ROJO|PON ROJO", regex=True)
        mask_precisa_c = com_upper_c.apply(es_offline_preciso)
        
        df_base_activa['ES_OFFLINE'] = (mask_est_abierto_c & mask_sop_c & ~mask_falsos_c & (mask_com_off_c | mask_precisa_c))
        
        if 'TECNICO' in df_base_activa.columns:
            mask_josue_c = df_base_activa['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
            df_base_activa.loc[mask_josue_c, 'ES_OFFLINE'] = False

    # ==============================================================================
    # 3. RENDERIZADO DE PANTALLAS Y CONFIGURACIÓN
    # ==============================================================================
    if nav_menu_diamante == "⚙️ Configuración":
        settings.mostrar_configuracion()
        return

    if nav_menu_diamante == "📁 Expedientes":
        expediente.mostrar_modulo_expedientes(conn, df_base)
        return
        
    if nav_menu_diamante == "🏅 Control Calidad":
        ccalidad.mostrar_modulo_calidad(conn, df_base)
        return

    if nav_menu_diamante == "🚙 Auditoría Vehículos":
        tab1, tab2 = st.tabs(["🚙 Auditoría Vehículos", "⏱️ Tiempo Tecnicos"])
        
        with tab1:
            try: mostrar_auditoria(es_movil, conn)
            except Exception as e: st.error(f"Ocurrió un error al cargar el módulo de Auditoría: {e}")
            
        with tab2:
            try:
                import tiempot
                tiempot.mostrar_tiempos_tecnicos()
            except ImportError:
                st.warning("⚠️ Falta el archivo 'tiempot.py'. Asegúrate de crearlo en la misma carpeta.")
            except Exception as e:
                st.error(f"Ocurrió un error al cargar el módulo de Tiempo Técnicos: {e}")
                
        return

    if nav_menu_diamante == "📅 Reprog / No Inst":
        st.title("📅 Reprogramadas y No Instalados")
        tab_reprog, tab_noinst = st.tabs(["📅 Reprogramadas (Futuras)", "🚫 NOINSTALADO (Hoy)"])
        
        with tab_reprog:
            st.subheader("📅 Órdenes Agendadas a Futuro")
            df_base['DIAS_RETRASO_REAL'] = (pd.Timestamp(ahora_local).normalize() - pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).astype(int)
            mask_reprog = (df_base['DIAS_RETRASO_REAL'] < 0) & (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False))
            df_reprog = df_base[mask_reprog].copy()
            st.metric("Total Agendadas a Futuro", len(df_reprog))
            if not df_reprog.empty:
                cols_visibles = ['DIAS_RETRASO_REAL', 'NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'TECNICO', 'ESTADO', 'COMENTARIO', 'FECHA_APE']
                cols_finales = [c for c in cols_visibles if c in df_reprog.columns]
                def highlight_reprog(row): return ['background-color: #1a2a3a; color: #58a6ff; font-weight: bold' if col == 'DIAS_RETRASO_REAL' else '' for col in row.index]
                st.dataframe(df_reprog[cols_finales].style.apply(highlight_reprog, axis=1), use_container_width=True, height=600, hide_index=True)
            else: st.success("✅ No hay órdenes reprogramadas para fechas futuras en este momento.")

        with tab_noinst:
            st.subheader("🚫 Órdenes Cerradas como NOINSTALADO Hoy")
            st.caption("Órdenes asignadas que el técnico cerró como NO INSTALADAS durante el día de hoy.")
            # Se lee de la copia PREVIA al filtro global de actividad, porque
            # NOINSTALADO no está en la lista maestra y de otro modo esta vista
            # quedaría vacía. OJO: eso NO significa traer historial -- abajo se
            # sigue acotando estrictamente al día de hoy.
            df_fuente_noinst = df_base_sin_filtro_actividad

            # HORA_LIQ viene en UTC, así que se le restan 6h para obtener la fecha
            # real en hora de Honduras. Sin este ajuste, las órdenes cerradas ayer
            # entre las 6:00pm y medianoche caen en la misma fecha UTC que hoy y
            # se colaban en esta vista como si fueran del día actual.
            hora_liq_local_noinst = pd.to_datetime(df_fuente_noinst['HORA_LIQ'], errors='coerce') - pd.Timedelta(hours=6)

            mask_noinst_hoy = (
                df_fuente_noinst['ACTIVIDAD'].astype(str).str.upper().str.contains('NOINSTALADO', na=False)
                & (hora_liq_local_noinst.dt.date == hoy_date_valor)
                & mascara_tecnico_asignado(df_fuente_noinst['TECNICO'])
            )

            df_noinst_hoy = df_fuente_noinst[mask_noinst_hoy].copy()
            if df_noinst_hoy.empty:
                st.success("✅ No hay órdenes cerradas como NOINSTALADO en el día de hoy.")
            else:
                st.metric("Total NOINSTALADO hoy", len(df_noinst_hoy))
                st.dataframe(df_noinst_hoy[['NUM','CLIENTE','TECNICO','HORA_LIQ','COMENTARIO']].sort_values(by='HORA_LIQ'), use_container_width=True, height=600, hide_index=True)
            
        return

    # ==============================================================================
    # 4. FILTROS Y LÓGICA COMPARTIDA PARA MONITOR Y REPORTES
    # ==============================================================================
    filtro_actividad = []
    filtro_estado = []
    filtro_motivo = []
    check_criticos_diamante = False
    check_no_asignadas = False 
    tec_filtro_monitor = "Todos"

    if nav_menu_diamante == "⚡ Monitor en Vivo":
        filtro_container = st.expander("🎛️ Filtros Rápidos y Búsqueda", expanded=False) if es_movil else sidebar_top
        with filtro_container:
            if not es_movil: st.markdown("---")
            st.markdown("### 🎛️ Filtros Múltiples")
            
            lista_actividades = sorted(df_base_activa['ACTIVIDAD'].dropna().unique().tolist())
            lista_estados = sorted(df_base_activa['ESTADO'].dropna().unique().tolist())
            lista_motivos = sorted(df_base_activa['MOTIVO'].dropna().unique().tolist()) if 'MOTIVO' in df_base_activa.columns else []
            
            filtro_actividad = st.multiselect("🛠️ Tipo de Actividad:", options=lista_actividades, default=[], placeholder="Todas las actividades", key="filtro_actividad_multiselect")
            filtro_estado = st.multiselect("🚦 Estado de Orden:", options=lista_estados, default=[], placeholder="Todos los estados", key="filtro_estado_multiselect")
            filtro_motivo = st.multiselect("⚠️ Motivo / Diagnóstico:", options=lista_motivos, default=[], placeholder="Todos los motivos", key="filtro_motivo_multiselect")
            
            st.divider() 
            st.markdown("### 🔍 Filtros en Vivo")
            
            m_viva_count = df_base_activa['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
            
            if 'ES_OFFLINE' not in df_base_activa.columns:
                df_base_activa['ES_OFFLINE'] = False
            mascara_offline_segura = df_base_activa['ES_OFFLINE'] == True
            
            total_off_count_viva = int((mascara_offline_segura & m_viva_count).sum())
            
            # --- MODIFICACIÓN DE "NO ASIGNADAS": SE VALIDA QUE LA ACTIVIDAD ESTÉ EN LA LISTA PERMITIDA ---
            mask_no_asig_act_base = df_base_activa['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
            mascara_no_asignadas = (~mascara_tecnico_asignado(df_base_activa['TECNICO'])) & mask_no_asig_act_base
            total_no_asignadas_viva = int((mascara_no_asignadas & m_viva_count).sum())
            
            check_criticos_diamante = st.toggle(f"🚨 Ver solo Críticas ({total_off_count_viva})", key="toggle_criticos")
            check_no_asignadas = st.toggle(f"🚨 Ver NO Asignadas ({total_no_asignadas_viva})", key="toggle_no_asignadas")
         
            total_vivas = int(m_viva_count.sum()) 
            check_ordenes_totales = st.toggle(f"📋 Órdenes Totales Pendientes ({total_vivas})", key="toggle_totales")
            
            if check_ordenes_totales:
                if st.button("📄 GENERAR PDF DE ÓRDENES TOTALES", use_container_width=True, key="btn_generar_pdf_totales"):
                    with st.spinner("Generando documento PDF..."):
                        df_vivas_export = df_base_activa[m_viva_count].copy()
                        st.session_state['pdf_totales_gen'] = generar_pdf_ordenes_totales(df_vivas_export, hoy_date_valor)
                if 'pdf_totales_gen' in st.session_state and st.session_state['pdf_totales_gen']:
                    st.download_button("📥 DESCARGAR PDF TOTAL", data=st.session_state['pdf_totales_gen'], file_name=f"Ordenes_Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_download_pdf_totales")
            
            try:
                from tools import cargar_catalogo_tecnicos
                
                df_cat_tecs = cargar_catalogo_tecnicos()
                if not df_cat_tecs.empty:
                    df_principales = df_cat_tecs[
                        (df_cat_tecs['Clasificación'] == "TÉCNICO PRINCIPAL") & 
                        (df_cat_tecs['Estatus'] == "ACTIVO")
                    ]
                    tecs_validos_set = {normalizar_nombre_cruce(n) for n in df_principales['Nombre'].dropna()}
                    
                    tecs_en_base = df_base_activa['TECNICO'].dropna().unique().tolist()
                    tecs_filtrados = [t for t in tecs_en_base if normalizar_nombre_cruce(t) in tecs_validos_set]
                    lista_tecs_monitor = ["Todos"] + sorted(tecs_filtrados)
                else:
                    lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
            except Exception:
                lista_tecs_monitor = ["Todos"] + sorted(df_base_activa['TECNICO'].dropna().unique().tolist())
                
            tec_filtro_monitor = st.selectbox("👤 Técnico:", lista_tecs_monitor, key="sel_tecnico_monitor")

        df_monitor_filtrado = df_base_activa.copy()
        if len(filtro_actividad) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ACTIVIDAD'].isin(filtro_actividad)]
        if len(filtro_estado) > 0: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].isin(filtro_estado)]
        if len(filtro_motivo) > 0 and 'MOTIVO' in df_monitor_filtrado.columns: df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['MOTIVO'].isin(filtro_motivo)]
        if check_criticos_diamante:
            mask_critica = df_monitor_filtrado['ES_OFFLINE'] | df_monitor_filtrado.get('ALERTA_TIEMPO', False)
            mask_sop_fibra = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('SOP', na=False)
            mask_falsos = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.upper().str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', na=False)
            df_monitor_filtrado = df_monitor_filtrado[mask_critica & mask_sop_fibra & ~mask_falsos]
        if check_no_asignadas:
            # --- SE APLICA EL FILTRO DE ACTIVIDAD AL FILTRAR EN VIVO LAS NO ASIGNADAS ---
            mask_no_asig_act_filtro = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
            mask_no_asignadas_filtro = (~mascara_tecnico_asignado(df_monitor_filtrado['TECNICO'])) & mask_no_asig_act_filtro
            df_monitor_filtrado = df_monitor_filtrado[mask_no_asignadas_filtro]
        if tec_filtro_monitor != "Todos": 
            df_monitor_filtrado = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec_filtro_monitor]

        # AVISO DE FILTROS ACTIVOS. Algunos filtros del panel lateral eliminan
        # categorías COMPLETAS de la vista -- por ejemplo, "Ver solo Críticas"
        # descarta todas las PLEXISCA, PEXTERNO, SPLITTEROPT e instalaciones --
        # y sin este aviso parecía que faltaban órdenes o que un técnico no
        # había trabajado, cuando en realidad estaban ocultas por un filtro.
        _filtros_activos = []
        if check_criticos_diamante:
            _filtros_activos.append("🚨 **Ver solo Críticas** — oculta TODAS las PLEX, PEXTERNO, SPLITTEROPT e instalaciones")
        if check_no_asignadas:
            _filtros_activos.append("🚨 **Ver NO Asignadas** — oculta todas las órdenes que ya tienen técnico")
        if len(filtro_actividad) > 0:
            _filtros_activos.append(f"🛠️ **Actividad**: {', '.join(map(str, filtro_actividad))}")
        if len(filtro_estado) > 0:
            _filtros_activos.append(f"🚦 **Estado**: {', '.join(map(str, filtro_estado))}")
        if len(filtro_motivo) > 0:
            _filtros_activos.append(f"⚠️ **Motivo**: {', '.join(map(str, filtro_motivo))}")
        if tec_filtro_monitor != "Todos":
            _filtros_activos.append(f"👤 **Técnico**: {tec_filtro_monitor}")

        if _filtros_activos:
            st.warning(
                "**Hay filtros activos ocultando información:**\n\n- "
                + "\n- ".join(_filtros_activos)
                + f"\n\nSe están mostrando **{len(df_monitor_filtrado)}** de **{len(df_base_activa)}** órdenes. "
                "Desactívalos en el panel lateral para ver todo."
            )
    else: 
        df_monitor_filtrado = df_base_activa.copy()

    # ==============================================================================
    # 5. PANTALLA: CENTRO DE REPORTES
    # ==============================================================================
    if nav_menu_diamante == "📊 Centro de Reportes":
        st.title("📊 Centro Único de Reportes Operativos")
        st.caption("Central de exportación gerencial de métricas y rendimiento.")
        
        # MENSAJE DE AYUDA DE NAVEGADOR PARA DESCARGAS DE REPORTES
        st.info("💡 **Para Supervisores de Campo (Móvil):** Si estás descargando un reporte en PDF o Excel desde tu celular, asegúrate de haber abierto el monitor operativo en tu navegador nativo (**Chrome o Safari**). Si abres este monitor directamente dentro de un chat de WhatsApp o WATI, las descargas serán bloqueadas por seguridad del dispositivo móvil.")

        tab_diario, tab_pendientes, tab_gerencial, tab_red, tab_biometrico, tab_materiales = st.tabs([
            "📦 Cierre Diario", 
            "📋 Pendientes Generales", 
            "💼 Gerencial (Trimestral)", 
            "🛰️ Análisis de Red (OLT/PON)",
            "⏱️ Biométrico",
            "🔌 Control de Materiales"
        ])

        with tab_red:
            mostrar_analisis_red(df_base_activa, hoy_date_valor, conn)

        with tab_pendientes:
            st.subheader("📋 Resumen de Pendientes Generales")
            df_todas_vivas = df_monitor_filtrado[df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)].copy()
            if not df_todas_vivas.empty:
                # --- AQUÍ TAMBIÉN SE FILTRAN LAS NO ASIGNADAS BAJO LA REGLA DE ACTIVIDAD ---
                mask_sin_tec_act = df_todas_vivas['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
                mask_sin_tec = (~mascara_tecnico_asignado(df_todas_vivas['TECNICO'])) & mask_sin_tec_act
                df_asig = df_todas_vivas[mascara_tecnico_asignado(df_todas_vivas['TECNICO'])].copy()
                df_no_asig = df_todas_vivas[mask_sin_tec].copy()
                
                def clasificas_dispatch(row):
                    act = str(row.get('ACTIVIDAD', '')).upper(); com = str(row.get('COMENTARIO', '')).upper(); txt = act + " " + com
                    if re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act): return "INSTALACIONES"
                    elif re.search("SOP|FALLA|MANT", act): return "MANTENIMIENTOS"
                    elif re.search("PLEX|PEXTERNO|SPLITTEROPT", txt): return "PLEX"
                    else: return "OTRAS"
                    
                if not df_asig.empty:
                    df_asig['CATEGORIA'] = df_asig.apply(clasificas_dispatch, axis=1)
                    res_a = df_asig['CATEGORIA'].value_counts().reset_index()
                    res_a.columns = ['Categoría', 'Asignadas (En Ruta)']
                else: res_a = pd.DataFrame(columns=['Categoría', 'Asignadas (En Ruta)'])
                if not df_no_asig.empty:
                    df_no_asig['CATEGORIA'] = df_no_asig.apply(clasificas_dispatch, axis=1)
                    res_n = df_no_asig['CATEGORIA'].value_counts().reset_index()
                    res_n.columns = ['Categoría', 'Nuevas (Sin Asignar)']
                else: res_n = pd.DataFrame(columns=['Categoría', 'Nuevas (Sin Asignar)'])
                
                df_dispatch = pd.merge(res_a, res_n, on='Categoría', how='outer').fillna(0)
                df_dispatch['Asignadas (En Ruta)'] = df_dispatch['Asignadas (En Ruta)'].astype(int)
                df_dispatch['Nuevas (Sin Asignar)'] = df_dispatch['Nuevas (Sin Asignar)'].astype(int)
                df_dispatch['TOTAL GENERAL'] = df_dispatch['Asignadas (En Ruta)'] + df_dispatch['Nuevas (Sin Asignar)']
                tot_a = df_dispatch['Asignadas (En Ruta)'].sum()
                tot_n = df_dispatch['Nuevas (Sin Asignar)'].sum()
                tot_g = df_dispatch['TOTAL GENERAL'].sum()
                df_totales = pd.DataFrame([{'Categoría': 'TOTAL PENDIENTES', 'Asignadas (En Ruta)': tot_a, 'Nuevas (Sin Asignar)': tot_n, 'TOTAL GENERAL': tot_g}])
                df_dispatch_final = pd.concat([df_dispatch, df_totales], ignore_index=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil: col_kpi1, col_kpi2 = st.columns(2)
                else: col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                with col_kpi1: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #3B82F6; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">ASIGNADAS</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_a}</div></div>""", unsafe_allow_html=True)
                with col_kpi2: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #F59E0B; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">SIN ASIGNAR</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_n}</div></div>""", unsafe_allow_html=True)
                if not es_movil:
                    with col_kpi3: st.markdown(f"""<div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 8px; border-left: 5px solid #10B981; text-align: center;"><div style="color: #94A3B8; font-size: 0.8rem; font-weight: bold;">TOTAL</div><div style="color: #FFFFFF; font-size: 2rem; font-weight: bold;">{tot_g}</div></div>""", unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil:
                    def highlight_total(row): return ['background-color: #2D3748; color: white; font-weight: bold' if row['Categoría'] == 'TOTAL PENDIENTES' else '' for _ in row.index]
                    st.dataframe(df_dispatch_final.style.apply(highlight_total, axis=1), use_container_width=True, hide_index=True)
                    st.info("Genera reportes para Dispatch.")
                    buffer = io.BytesIO()
                    df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificas_dispatch, axis=1)
                    cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                    df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Manana')
                    st.download_button(label="📥 Exportar EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="btn_descargar_excel_pendientes")
                    if st.button("📄 Generar PDF", use_container_width=True, type="primary", key="btn_generar_pdf_dispatch_mobile"):
                        with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                    if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_dispatch_mobile")
                else:
                    col_d1, col_d2 = st.columns([2, 1])
                    with col_d1:
                        def highlight_total(row): return ['background-color: #2D3748; color: white; font-weight: bold' if row['Categoría'] == 'TOTAL PENDIENTES' else '' for _ in row.index]
                        st.dataframe(df_dispatch_final.style.apply(highlight_total, axis=1), use_container_width=True, hide_index=True, column_config={"Categoría": st.column_config.TextColumn("CLASIFICACIÓN"), "Asignadas (En Ruta)": st.column_config.NumberColumn("🚗 ASIGNADAS", format="%d"), "Nuevas (Sin Asignar)": st.column_config.NumberColumn("📥 SIN ASIGNAR", format="%d"), "TOTAL GENERAL": st.column_config.NumberColumn("📦 TOTAL", format="%d")})
                    with col_d2:
                        st.info("Genera los reportes para enviar al departamento de Dispatch.")
                        buffer = io.BytesIO()
                        df_todas_vivas['CLASIFICACION_DISPATCH'] = df_todas_vivas.apply(clasificas_dispatch, axis=1)
                        cols_export = ['NUM', 'CLIENTE', 'NOMBRE', 'COLONIA', 'ACTIVIDAD', 'COMENTARIO', 'ESTADO', 'TECNICO', 'CLASIFICACION_DISPATCH', 'FECHA_APE']
                        df_export = df_todas_vivas[[c for c in cols_export if c in df_todas_vivas.columns]]
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_export.to_excel(writer, index=False, sheet_name='Pendientes_Dispatch_Hoy')
                        st.download_button(label="📥 Exportar Resumen a EXCEL", data=buffer.getvalue(), file_name=f"Pendientes_Dispatch_{hoy_date_valor}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="btn_descargar_excel_dispatch")
                        if st.button("📄 Generar PDF (Dispatch)", use_container_width=True, type="primary", key="btn_generar_pdf_dispatch_desktop"):
                            with st.spinner("Generando PDF..."): st.session_state['pdf_dispatch'] = generar_pdf_pendientes_dispatch(df_dispatch_final, df_todas_vivas, hoy_date_valor.strftime('%d/%m/%Y'))
                        if 'pdf_dispatch' in st.session_state and st.session_state['pdf_dispatch'] is not None: st.download_button(label="📥 Descargar PDF Generado", data=st.session_state['pdf_dispatch'], file_name=f"Pendientes_Dispatch_{hoy_date_valor}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_dispatch_desktop")
            else: st.success("🎉 No hay órdenes pendientes registradas. ¡Operación limpia!")

        with tab_biometrico:
            try: biometrico.vista_biometrico()
            except Exception as e: st.error(f"Error al cargar la vista del biométrico: {e}")

        with tab_gerencial:
            st.subheader("📊 Reporte Gerencial Unificado")
            archivo_gerencial = st.file_uploader("📂 Subir Reporte de Actividades (Excel/CSV)", type=['xlsx', 'csv'], key="uploader_gerencial")
            if archivo_gerencial:
                with st.spinner("⏳ Analizando datos, cruzando tablas y calculando jornadas..."):
                    try:
                        if archivo_gerencial.name.endswith('.csv'): df_raw = pd.read_csv(archivo_gerencial)
                        else: df_raw = pd.read_excel(archivo_gerencial)
                        df_limpio = procesar_dataframe_base(df_raw)
                        tabla_prod, tabla_efi, res_jornada = generar_tablas_gerenciales(df_limpio)
                        df_merge_1 = pd.merge(tabla_prod, tabla_efi, on=['TECNICO', 'ACTIVIDAD'], how='left')
                        df_maestra = pd.merge(df_merge_1, res_jornada, on='TECNICO', how='left')
                        df_maestra = df_maestra.rename(columns={'TECNICO': 'Técnico', 'Dias_Laborados': 'Días Trabajados', 'Promedio_Horas_Dia': 'Hrs / Día', 'ACTIVIDAD': 'Actividad', 'Cantidad': 'Volumen', 'Participacion_%': '% del Total', 'Promedio_Minutos': 'Min. Promedio'})
                        df_maestra = df_maestra[['Técnico', 'Días Trabajados', 'Hrs / Día', 'Actividad', 'Volumen', '% del Total', 'Min. Promedio']]
                        st.success("✅ Datos processed y unificados correctamente.")
                        ordenes_con_error = df_maestra['Min. Promedio'].isna().sum()
                        if ordenes_con_error > 0: st.warning(f"⚠️ Se detectaron {ordenes_con_error} órdenes con errores de tiempo.")
                        st.dataframe(df_maestra, use_container_width=True, hide_index=True)
                        st.markdown("---")
                        if st.button("🚀 GENERAR PDF GERENCIAL COMPLETO", use_container_width=True, type="primary", key="btn_generar_pdf_gerencial"):
                            with st.spinner("Dibujando secciones por técnico..."): st.session_state['pdf_gerencial'] = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                        if 'pdf_gerencial' in st.session_state: st.download_button(label="📥 Descargar Reporte PDF", data=st.session_state['pdf_gerencial'], file_name=f"Reporte_Gerencial_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_gerencial")
                    except Exception as e: st.error(f"❌ Ocurrió un error procesando el reporte: {e}")
        
        with tab_diario:
            st.subheader("📦 Archivo de Cierre de Jornada")
            fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor, key="fecha_archivar_diario")
            
            mask_ini_dia = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == fecha_cal_sel
            mask_liq_dia = pd.to_datetime(df_base['HORA_LIQ'], errors='coerce').dt.date == fecha_cal_sel
            mask_ape_dia = (df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)) & (pd.to_datetime(df_base['FECHA_APE'], errors='coerce').dt.date == fecha_cal_sel)
            
            df_para_gantt_diario = df_base[mask_ini_dia | mask_liq_dia | mask_ape_dia].copy()
            
            mask_sin_ini_c = df_para_gantt_diario['HORA_INI'].isna() & df_para_gantt_diario['HORA_LIQ'].notnull()
            df_para_gantt_diario.loc[mask_sin_ini_c, 'HORA_INI'] = df_para_gantt_diario.loc[mask_sin_ini_c, 'HORA_LIQ'] - pd.Timedelta(minutes=30)
            
            df_para_gantt_diario = df_para_gantt_diario[df_para_gantt_diario['HORA_INI'].notnull()].copy()
            
            df_cerradas_espejo = df_para_gantt_diario[(df_para_gantt_diario['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_para_gantt_diario['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))].copy()
            df_asignadas_espejo = df_para_gantt_diario[df_para_gantt_diario['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)].copy()

            st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cerradas_espejo))
            st.markdown("### 📊 Indicadores de Avance Operativo (Mora)")
            df_asignadas_espejo['FECHA_APE_DT'] = pd.to_datetime(df_asignadas_espejo['FECHA_APE'], errors='coerce')
            df_cerradas_espejo['FECHA_APE_DT'] = pd.to_datetime(df_cerradas_espejo['FECHA_APE'], errors='coerce')
            df_mora_pend_rep = df_asignadas_espejo[df_asignadas_espejo['FECHA_APE_DT'].dt.date < fecha_cal_sel].copy()
            df_mora_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['FECHA_APE_DT'].dt.date < fecha_cal_sel].copy()
            df_inicio_mora_rep = pd.concat([df_mora_pend_rep, df_mora_cerr_rep]).drop_duplicates(subset=['NUM'])
            
            df_plex_m_pend_rep = df_mora_pend_rep[df_mora_pend_rep['SEGMENTO'] == 'PLEX']
            df_plex_m_cerr_rep = df_mora_cerr_rep[df_mora_cerr_rep['SEGMENTO'] == 'PLEX']
            df_plex_m_inicio_rep = df_inicio_mora_rep[df_inicio_mora_rep['SEGMENTO'] == 'PLEX']
            
            df_resi_m_pend_rep = df_mora_pend_rep[df_mora_pend_rep['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_cerr_rep = df_mora_cerr_rep[df_mora_cerr_rep['SEGMENTO'] == 'RESIDENCIAL']
            df_resi_m_inicio_rep = df_inicio_mora_rep[df_inicio_mora_rep['SEGMENTO'] == 'RESIDENCIAL']
            
            tot_mora_plex_rep = len(df_plex_m_inicio_rep)
            avance_mora_plex_rep = (len(df_plex_m_cerr_rep) / tot_mora_plex_rep * 100) if tot_mora_plex_rep > 0 else 0
            
            tot_mora_resi_rep = len(df_resi_m_inicio_rep)
            avance_mora_resi_rep = (len(df_resi_m_cerr_rep) / tot_mora_resi_rep * 100) if tot_mora_resi_rep > 0 else 0
            
            tot_mora_global_rep = len(df_inicio_mora_rep)
            avance_mora_global_rep = (len(df_mora_cerr_rep) / tot_mora_global_rep * 100) if tot_mora_global_rep > 0 else 0
            
            def crear_velocimetro_rep(valor, titulo, total_ordenes=0):
                color_v = "#EF4444" if valor < 60 else ("#F59E0B" if valor < 90 else "#10B981") 
                if total_ordenes == 0: color_v = "#4B5563"
                fig = go.Figure(go.Pie(values=[valor, max(0, 100 - valor)] if total_ordenes > 0 else [0, 100], labels=['Completado', 'Pendiente'], hole=0.8, marker=dict(colors=[color_v, '#2D2F39']), textinfo='none', hoverinfo='none', direction='clockwise', sort=False))
                fig.update_layout(showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}}, annotations=[dict(text=f"{valor:.0f}%" if total_ordenes > 0 else "N/A", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")])
                return fig

            if es_movil:
                st.plotly_chart(crear_velocimetro_rep(avance_mora_resi_rep, "🏠 Mora Residencial", len(df_resi_m_inicio_rep)), use_container_width=True)
                st.plotly_chart(crear_velocimetro_rep(avance_mora_plex_rep, "🏢 Mora PLEX", len(df_plex_m_inicio_rep)), use_container_width=True)
                st.plotly_chart(crear_velocimetro_rep(avance_mora_global_rep, "🌍 Mora Global", len(df_inicio_mora_rep)), use_container_width=True)
            else:
                col_gr1, col_gr2, col_gr3 = st.columns(3)
                with col_gr1: st.plotly_chart(crear_velocimetro_rep(avance_mora_resi_rep, "🏠 Mora Residencial", len(df_resi_m_inicio_rep)), use_container_width=True)
                with col_gr2: st.plotly_chart(crear_velocimetro_rep(avance_mora_plex_rep, "🏢 Mora PLEX", len(df_plex_m_inicio_rep)), use_container_width=True)
                with col_gr3: st.plotly_chart(crear_velocimetro_rep(avance_mora_global_rep, "🌍 Mora Global", len(df_inicio_mora_rep)), use_container_width=True)
            
            st.markdown("---")

            if not es_movil:
                st.markdown("<h4 style='text-align: center; color: #1F2937;'>⏳ Eficiencia y Tiempos Operativos (Gantt Histórico)</h4><br>", unsafe_allow_html=True)
                
                with st.expander("⏳ LÍNEA DE TIEMPO OPERATIVA (GANTT)", expanded=False):
                    # Solo entran órdenes con hora de inicio real (HORA_INI) en el día
                    # seleccionado. Una orden sin HORA_INI está apenas asignada, no trabajada.
                    mask_ini_dia = pd.to_datetime(df_base['HORA_INI'], errors='coerce').dt.date == fecha_cal_sel
                    df_para_gantt_diario = df_base[mask_ini_dia].copy()
                    # Mismo motivo que en el Gantt en vivo: índice único para que las
                    # asignaciones por máscara del recorte de barras no se crucen.
                    df_para_gantt_diario = df_para_gantt_diario.reset_index(drop=True)
                    
                    if not df_para_gantt_diario.empty:
                        ahora_hx_d = get_honduras_time()
                        
                        df_para_gantt_diario['GANTT_START'] = df_para_gantt_diario['HORA_INI']
                        hora_cierre_proyectada = ahora_hx_d if fecha_cal_sel == ahora_hx_d.date() else datetime.combine(fecha_cal_sel, dt_time(22, 0))
                        
                        # Mismo criterio que en el Gantt en vivo: se confía en el ESTADO por
                        # encima de HORA_LIQ para decidir si sigue realmente abierta, ya que
                        # a veces queda un timestamp provisional en HORA_LIQ antes del cierre
                        # confirmado (ver comentario detallado en el bloque del Gantt en vivo).
                        mask_estado_vivo_d = df_para_gantt_diario['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                        mask_abierta_d = mask_estado_vivo_d

                        df_para_gantt_diario['GANTT_END'] = df_para_gantt_diario['HORA_LIQ']
                        df_para_gantt_diario.loc[mask_abierta_d, 'GANTT_END'] = hora_cierre_proyectada

                        # Cerrada (o estado no vivo) sin HORA_LIQ utilizable: bloque acotado,
                        # no se proyecta un cierre inventado.
                        mask_cierre_desc_d = df_para_gantt_diario['GANTT_END'].isna()
                        df_para_gantt_diario.loc[mask_cierre_desc_d, 'GANTT_END'] = df_para_gantt_diario.loc[mask_cierre_desc_d, 'GANTT_START'] + pd.Timedelta(minutes=30)

                        # Ninguna barra puede extenderse más allá del inicio de la siguiente
                        # orden del mismo técnico: así se conservan los huecos reales entre
                        # una orden y la siguiente, y nada queda montado.
                        df_para_gantt_diario = df_para_gantt_diario.sort_values(by=['TECNICO', 'GANTT_START'])
                        siguiente_inicio_d = df_para_gantt_diario.groupby('TECNICO')['GANTT_START'].shift(-1)

                        mask_invade_d = siguiente_inicio_d.notna() & (df_para_gantt_diario['GANTT_END'] > siguiente_inicio_d) & (siguiente_inicio_d > df_para_gantt_diario['GANTT_START'])
                        df_para_gantt_diario.loc[mask_invade_d, 'GANTT_END'] = siguiente_inicio_d[mask_invade_d]

                        ancho_min_barra_d = pd.Timedelta(minutes=10)
                        fin_objetivo_d = df_para_gantt_diario['GANTT_START'] + ancho_min_barra_d
                        tope_permitido_d = siguiente_inicio_d.where(siguiente_inicio_d > df_para_gantt_diario['GANTT_START'], fin_objetivo_d).fillna(fin_objetivo_d)
                        fin_ajustado_d = pd.concat([fin_objetivo_d, tope_permitido_d], axis=1).min(axis=1)

                        mask_barra_corta_d = (df_para_gantt_diario['GANTT_END'] - df_para_gantt_diario['GANTT_START']) < ancho_min_barra_d
                        df_para_gantt_diario.loc[mask_barra_corta_d, 'GANTT_END'] = fin_ajustado_d[mask_barra_corta_d]

                        mask_inv = df_para_gantt_diario['GANTT_END'] < df_para_gantt_diario['GANTT_START']
                        df_para_gantt_diario.loc[mask_inv, 'GANTT_END'] = df_para_gantt_diario.loc[mask_inv, 'GANTT_START'] + ancho_min_barra_d
                        
                        df_para_gantt_diario['Inicio'] = df_para_gantt_diario['HORA_INI'].dt.strftime('%H:%M')
                        df_para_gantt_diario['Cierre'] = df_para_gantt_diario['HORA_LIQ'].apply(
                            lambda x: x.strftime('%H:%M') if pd.notnull(x) else "En curso (Abierta)"
                        )
                        
                        df_para_gantt_diario['TECNICO'] = df_para_gantt_diario['TECNICO'].apply(normalizar_nombre_cruce)
                        df_para_gantt_diario = df_para_gantt_diario.dropna(subset=['GANTT_START', 'GANTT_END']).sort_values(by=['TECNICO', 'GANTT_START'])

                        actividades_permitidas = ACTIVIDADES_GANTT_PERMITIDAS
                        
                        df_para_gantt_diario = df_para_gantt_diario[
                            df_para_gantt_diario['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_permitidas)
                        ]

                        try:
                            df_almuerzos_hist = cargar_almuerzos(conn, fecha=fecha_cal_sel.strftime('%Y-%m-%d'))
                        except Exception:
                            df_almuerzos_hist = pd.DataFrame()

                        if df_almuerzos_hist is not None and not df_almuerzos_hist.empty:
                            filas_almuerzo_h = []
                            for _, fila_alm_h in df_almuerzos_hist.iterrows():
                                try:
                                    tec_alm_h = normalizar_nombre_cruce(fila_alm_h['TECNICO'])
                                    hi_alm_h = datetime.combine(fecha_cal_sel, datetime.strptime(str(fila_alm_h['HORA_INICIO']), '%H:%M').time())
                                    hf_alm_h = datetime.combine(fecha_cal_sel, datetime.strptime(str(fila_alm_h['HORA_FIN']), '%H:%M').time())
                                    
                                    # Cálculo dinámico de la duración total del almuerzo
                                    duracion_alm_m_h = int((hf_alm_h - hi_alm_h).total_seconds() / 60)
                                    h_h, m_h = divmod(duracion_alm_m_h, 60)
                                    tiempo_real_alm_h = f"{h_h}h {m_h}m" if h_h > 0 else f"{m_h}m"
                                    
                                    filas_almuerzo_h.append({
                                        'TECNICO': tec_alm_h,
                                        'ACTIVIDAD': 'ALMUERZO',
                                        'NUM': '-',
                                        'CLIENTE': '-',
                                        'COLONIA': '-',
                                        'ESTADO': 'ALMUERZO',
                                        'GANTT_START': hi_alm_h,
                                        'GANTT_END': hf_alm_h,
                                        'Inicio': hi_alm_h.strftime('%H:%M'),
                                        'Cierre': hf_alm_h.strftime('%H:%M'),
                                        'TIEMPO_REAL': tiempo_real_alm_h
                                    })
                                except Exception:
                                    continue
                            if filas_almuerzo_h:
                                df_para_gantt_diario = pd.concat([df_para_gantt_diario, pd.DataFrame(filas_almuerzo_h)], ignore_index=True)
                                df_para_gantt_diario = df_para_gantt_diario.sort_values(by=['TECNICO', 'GANTT_START'])
                        
                        cli_series_d = df_para_gantt_diario['CLIENTE'].fillna('-').astype(str) if 'CLIENTE' in df_para_gantt_diario.columns else pd.Series(['-'] * len(df_para_gantt_diario), index=df_para_gantt_diario.index).astype(str)
                        
                        df_para_gantt_diario['INFO_HOVER'] = (
                            "ACTIVIDAD=" + df_para_gantt_diario['ACTIVIDAD'].astype(str) + "<br>" +
                            "NUM=" + df_para_gantt_diario['NUM'].astype(str) + "<br>" +
                            "CLIENTE=" + cli_series_d + "<br>" +
                            "COLONIA=" + df_para_gantt_diario['COLONIA'].astype(str) + "<br>" +
                            "ESTADO=" + df_para_gantt_diario['ESTADO'].astype(str) + "<br>" +
                            "Inicio=" + df_para_gantt_diario['Inicio'].astype(str) + "<br>" +
                            "Cierre=" + df_para_gantt_diario['Cierre'].astype(str) + "<br>" +
                            "Tiempo Total=" + df_para_gantt_diario['TIEMPO_REAL'].astype(str)
                        )

                        colores_solidos = {
                            "SOPFIBRA": "#d32f2f",         
                            "SOP": "#d32f2f",                
                            "INSFIBRA": "#1976d2",         
                            "INSFIBRACORP": "#0d47a1",     
                            "PEXTERNO": "#f57c00",         
                            "PLEXISCA": "#e65100",         
                            "TRASLADOEXTFIBRA": "#8e24aa",  
                            "SOPRECONCORP": "#c2185b",       
                            "SOPRECONHFC": "#c2185b",       
                            "SOPRECONFIBRA": "#c2185b",
                            "TVADICIONAL": "#00897b",
                            "ALMUERZO": "#78909c"
                        }

                        fig_gantt_d = px.timeline(
                            df_para_gantt_diario, 
                            x_start="GANTT_START", 
                            x_end="GANTT_END", 
                            y="TECNICO", 
                            color="ACTIVIDAD", 
                            text="ACTIVIDAD",  
                            custom_data=["INFO_HOVER"], 
                            color_discrete_map=colores_solidos,
                            height=max(400, len(df_para_gantt_diario['TECNICO'].unique()) * 45)
                        )
                        
                        fig_gantt_d.update_yaxes(autorange="reversed", title_text="", type="category")
                        margen_eje_d = pd.Timedelta(minutes=30)
                        if df_para_gantt_diario.empty or df_para_gantt_diario['GANTT_START'].isna().all() or df_para_gantt_diario['GANTT_END'].isna().all():
                            # Sin datos para ese día -- respaldo fijo (06:00-22:00 del día
                            # seleccionado) en vez de tronar con NaT.strftime().
                            hora_inicio_pantalla_d = datetime.combine(fecha_cal_sel, dt_time(6, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            hora_fin_pantalla_d = datetime.combine(fecha_cal_sel, dt_time(22, 0)).strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            hora_inicio_pantalla_d = (df_para_gantt_diario['GANTT_START'].min() - margen_eje_d).strftime('%Y-%m-%d %H:%M:%S')
                            hora_fin_pantalla_d = (df_para_gantt_diario['GANTT_END'].max() + margen_eje_d).strftime('%Y-%m-%d %H:%M:%S')
                        
                        fig_gantt_d.update_xaxes(range=[hora_inicio_pantalla_d, hora_fin_pantalla_d], tickformat="%H:%M", title_text=f"Cronograma Operativo - {fecha_cal_sel.strftime('%d/%m/%Y')}")
                        fig_gantt_d.update_traces(textposition='inside', insidetextanchor='middle', marker_line_color='white', marker_line_width=1.5, opacity=1.0, hovertemplate="%{customdata[0]}<extra></extra>")
                        fig_gantt_d.update_layout(showlegend=True, legend_title_text='Identificador', legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02), margin=dict(t=10, b=20, l=0, r=150), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.02)")
                        
                        st.plotly_chart(fig_gantt_d, use_container_width=True)

                        col_bpdf1, col_bpdf2 = st.columns([1, 2])
                        with col_bpdf1:
                            if st.button("📄 GENERAR PDF TIEMPOS Y TIEMPO PERDIDO", use_container_width=True, key="btn_generar_pdf_tiempos_muertos"):
                                with st.spinner("Calculando rendimientos de 8 horas..."):
                                    st.session_state['pdf_tiempos_muertos'] = generar_pdf_tiempos_muertos(df_para_gantt_diario, fecha_cal_sel)
                                    
                            if 'pdf_tiempos_muertos' in st.session_state and st.session_state['pdf_tiempos_muertos']:
                                st.download_button(
                                    label=f"📥 Descargar PDF (Eficiencia {fecha_cal_sel.strftime('%d-%m')})", 
                                    data=st.session_state['pdf_tiempos_muertos'], 
                                    file_name=f"Eficiencia_Tiempos_{fecha_cal_sel}.pdf", 
                                    mime="application/pdf", 
                                    type="primary", 
                                    use_container_width=True,
                                    key="btn_descargar_pdf_tiempos_muertos"
                                )
                        st.markdown("---")
                    else:
                        st.info("No hay actividades registradas en esta fecha para generar el Gantt.")

            if not df_cerradas_espejo.empty:
                st.markdown("### 📊 Desglose de Producción")
                if es_movil: cs_col, ci_col = st.columns(2)
                else: cs_col, ci_col, cp_col, co_col = st.columns(4)
                
                with cs_col:
                    st.write("**SOP**")
                    df_sop = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_sop, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_sop['Cant'].sum()}**")
                with ci_col:
                    st.write("**Instalaciones**")
                    txt_ins_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_ins_general = txt_ins_c.str.contains('INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_ins_cierre = df_cerradas_espejo[mask_ins_general].copy()
                    if not df_ins_cierre.empty:
                        def clasificas_ins_cierre(row):
                            txt = (str(row.get('ACTIVIDAD','')) + " " + str(row.get('COMENTARIO',''))).upper()
                            if re.search('ADIC', txt): return 'Adición'
                            if re.search('CAMBIO|MIGRACI', txt): return 'Cambio / Migración'
                            if re.search('RECUP', txt): return 'Recuperado'
                            return 'Nueva'
                        df_ins_cierre['SUBTIPO'] = df_ins_cierre.apply(clasificas_ins_cierre, axis=1)
                        df_ins_grouped = df_ins_cierre['SUBTIPO'].value_counts().reset_index()
                        df_ins_grouped.columns = ['Instalaciones', 'Cant']
                        st.dataframe(df_ins_grouped, hide_index=True, use_container_width=True)
                        st.write(f"**Total: {df_ins_grouped['Cant'].sum()}**")
                    else: st.write("Sin datos")
                
                if es_movil: cp_col, co_col = st.columns(2)

                with cp_col:
                    st.write("**Plex**")
                    df_plex = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('PLEX|PEXTERNO|SPLITTEROPT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_plex, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_plex['Cant'].sum()}**")
                with co_col:
                    st.write("**Otros**")
                    txt_otr_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                    mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|PEXTERNO|SPLITTEROPT|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                    df_otros = df_cerradas_espejo[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                    st.dataframe(df_otros, hide_index=True, use_container_width=True)
                    st.write(f"**Total: {df_otros['Cant'].sum()}**")

            st.markdown("---")
            st.markdown("### 🌅 Primera Orden del Día por Técnico")
            df_universo_diario = pd.concat([df_asignadas_espejo, df_cerradas_espejo]).drop_duplicates(subset=['NUM'])
            if 'HORA_INI' in df_universo_diario.columns:
                df_universo_diario['HORA_INI_DT'] = pd.to_datetime(df_universo_diario['HORA_INI'], errors='coerce')
                df_universo_diario = df_universo_diario.dropna(subset=['HORA_INI_DT'])
                mask_fecha_ini = df_universo_diario['HORA_INI_DT'].dt.date == pd.to_datetime(fecha_cal_sel).date()
                df_primera = df_universo_diario[mask_fecha_ini].sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO'], keep='first')
                
                if not df_primera.empty:
                    df_primera_mostrar = df_primera[['TECNICO', 'HORA_INI_DT', 'COLONIA', 'NUM']].copy()
                    df_primera_mostrar = df_primera_mostrar.sort_values(by='HORA_INI_DT')
                    df_primera_mostrar['HORA_INI'] = df_primera_mostrar['HORA_INI_DT'].dt.strftime('%H:%M:%S')
                    df_primera_mostrar = df_primera_mostrar.drop(columns=['HORA_INI_DT'])
                    df_primera_mostrar = df_primera_mostrar[['TECNICO', 'HORA_INI', 'COLONIA', 'NUM']]
                    st.dataframe(df_primera_mostrar, use_container_width=True, hide_index=True)

                    st.markdown("<br>", unsafe_allow_html=True)
                    if es_movil: col_btn1, col_btn2 = st.columns(2)
                    else: col_btn1, col_btn2 = st.columns([1, 2])
                    with col_btn1:
                        if st.button("📄 GENERAR PDF PRIMERA ORDEN", use_container_width=True, key="btn_generar_pdf_primera_orden"):
                            try:
                                with st.spinner("Generando PDF..."): st.session_state['pdf_primera'] = generar_pdf_primera_orden(df_base, fecha_cal_sel)
                            except Exception as e: st.error(f"Error generando PDF: {e}")
                        if 'pdf_primera' in st.session_state and st.session_state['pdf_primera']: st.download_button("📥 Descargar PDF (Inicio Jornada)", data=st.session_state['pdf_primera'], file_name=f"Primeras_Ordenes_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_primera_orden")
                else: st.info("No hay registros de inicio de órdenes para esta fecha.")
            else: st.info("No hay registros de inicio de órdenes para esta fecha.")

            st.markdown("---")
            st.markdown("### 📅 Promedio Semanal: Primera Orden del Día")
            st.caption("Calcula el promedio de la hora en la que cada técnico inicia su primera orden dentro del rango seleccionado.")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                f_inicio_primera = st.date_input("Fecha Inicio:", value=hoy_date_valor - timedelta(days=6), key="f_ini_arranque")
            with col_sel2:
                f_fin_primera = st.date_input("Fecha Fin:", value=hoy_date_valor, key="f_fin_arranque")
                
            if st.button("⚙️ Calcular Promedio de Inicio", use_container_width=True, key="btn_calcular_promedio_inicio"):
                if f_inicio_primera > f_fin_primera:
                    st.warning("⚠️ La Fecha de Inicio no puede ser mayor que la Fecha Fin.")
                else:
                    df_base_prom = df_base.copy()
                    if 'HORA_INI' in df_base_prom.columns:
                        df_base_prom['HORA_INI_DT'] = pd.to_datetime(df_base_prom['HORA_INI'], errors='coerce')
                        df_base_prom = df_base_prom.dropna(subset=['HORA_INI_DT'])
                        
                        mask_rango = (df_base_prom['HORA_INI_DT'].dt.date >= f_inicio_primera) & (df_base_prom['HORA_INI_DT'].dt.date <= f_fin_primera)
                        df_rango = df_base_prom[mask_rango].copy()
                        
                        if not df_rango.empty:
                            df_rango['Fecha_Sola'] = df_rango['HORA_INI_DT'].dt.date
                            primeras_ordenes_rango = df_rango.sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO', 'Fecha_Sola'], keep='first')
                            
                            primeras_ordenes_rango['Segundos_Inicio'] = primeras_ordenes_rango['HORA_INI_DT'].dt.hour * 3600 + \
                                                                        primeras_ordenes_rango['HORA_INI_DT'].dt.minute * 60 + \
                                                                        primeras_ordenes_rango['HORA_INI_DT'].dt.second
                                                                        
                            promedios_inicio = primeras_ordenes_rango.groupby('TECNICO').agg(
                                Dias_Computados=('Fecha_Sola', 'nunique'),
                                Promedio_Segundos=('Segundos_Inicio', 'mean')
                            ).reset_index()
                            
                            def secs_to_time_str(s):
                                if pd.isnull(s): return "N/D"
                                hash_h, r = divmod(int(s), 3600)
                                m, sec = divmod(r, 60)
                                return f"{hash_h:02d}:{m:02d}:{sec:02d}"
                                
                            promedios_inicio['Hora_Promedio_Inicio'] = promedios_inicio['Promedio_Segundos'].apply(secs_to_time_str)
                            promedios_inicio = promedios_inicio.sort_values('Promedio_Segundos')
                            
                            mask_tecnicos_validos = (promedios_inicio['TECNICO'].notna()) & (promedios_inicio['TECNICO'].str.strip() != '')
                            promedios_inicio = promedios_inicio[mask_tecnicos_validos]

                            st.session_state['df_promedios_inicio'] = promedios_inicio
                        else:
                            st.session_state['df_promedios_inicio'] = pd.DataFrame()
                            st.warning("⚠️ No se encontraron órdenes iniciadas en este rango de fechas.")
                            
            if 'df_promedios_inicio' in st.session_state and not st.session_state['df_promedios_inicio'].empty:
                promedios_mostrar = st.session_state['df_promedios_inicio']
                
                st.dataframe(
                    promedios_mostrar[['TECNICO', 'Dias_Computados', 'Hora_Promedio_Inicio']], 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TECNICO": st.column_config.TextColumn("👨‍🔧 Técnico"),
                        "Dias_Computados": st.column_config.NumberColumn("📅 Días Evaluados", format="%d"),
                        "Hora_Promedio_Inicio": st.column_config.TextColumn("⏰ Hora Promedio de Arranque")
                    }
                )
                
                st.markdown("<br>", unsafe_allow_html=True)
                if es_movil: col_btn_p1, col_btn_p2 = st.columns(2)
                else: col_btn_p1, col_btn_p2 = st.columns([1, 2])
                
                with col_btn_p1:
                    if st.button("📄 GENERAR PDF PROMEDIO SEMANAL", use_container_width=True, key="btn_generar_pdf_promedio_arranque"):
                        try:
                            with st.spinner("Generando PDF..."):
                                st.session_state['pdf_promedio_arranque'] = generar_pdf_promedio_arranque(promedios_mostrar, f_inicio_primera, f_fin_primera)
                        except Exception as e:
                            st.error(f"Error generando PDF: {e}")
                            
                    if 'pdf_promedio_arranque' in st.session_state and st.session_state['pdf_promedio_arranque']:
                        st.download_button(
                            "📥 Descargar PDF (Promedio Semanal)", 
                            data=st.session_state['pdf_promedio_arranque'], 
                            file_name=f"Promedio_Arranque_{f_inicio_primera}.pdf", 
                            mime="application/pdf", 
                            type="primary", 
                            use_container_width=True,
                            key="btn_descargar_pdf_prom_arranque"
                        )

            st.markdown("---")
            st.markdown("### 📥 Exportación")
            if st.button("🚀 GENERAR PDF DE CIERRE DIARIO", use_container_width=True, type="primary", key="btn_generar_pdf_cierre_diario"):
                with st.spinner("Preparando archivo de cierre..."): st.session_state['pdf_cierre'] = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
            if 'pdf_cierre' in st.session_state: st.download_button("📥 Descargar Archivo (PDF)", data=st.session_state['pdf_cierre'], file_name=f"Cierre_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True, key="btn_descargar_pdf_cierre")
            st.markdown("---")
            with st.expander("Ver Lista Detallada"): st.dataframe(df_cerradas_espejo[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)

        with tab_materiales:
            st.subheader("🔌 Control de Materiales e Inventario (Equipos y Acometidas)")
            st.caption("Reporte histórico completo de cambios de equipos terminales (ONT/ONU/CPE) y reemplazos de cable acometida (Drop).")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                meses_nombres = [
                    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
                ]
                mes_seleccionado = st.selectbox("📅 Seleccione el Mes:", meses_nombres, index=get_honduras_time().month - 1, key="materiales_mes_sel")
                numero_mes = meses_nombres.index(mes_seleccionado) + 1
            with col_sel2:
                anio_seleccionado = st.selectbox("📅 Seleccione el Año:", [2025, 2026, 2027], index=1, key="materiales_anio_sel")

            if 'df_materiales_master' not in st.session_state:
                with st.spinner("📥 Cargando base histórica completa para inventario..."):
                    try:
                        df_m_master = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "historial_maestro.csv")
                        if df_m_master is None or df_m_master.empty:
                            if conn is not None:
                                df_m_master = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Sheet1", ttl=0)
                        
                        if df_m_master is not None and not df_m_master.empty:
                            df_m_master.columns = df_m_master.columns.str.upper().str.strip()
                            st.session_state['df_materiales_master'] = df_m_master
                        else:
                            st.session_state['df_materiales_master'] = df_base.copy()
                    except Exception as e:
                        st.session_state['df_materiales_master'] = df_base.copy()

            df_m = st.session_state.get('df_materiales_master', df_base).copy()

            df_m['FECHA_REPORTE'] = pd.to_datetime(df_m['HORA_LIQ'], dayfirst=True, errors='coerce')
            df_m['FECHA_REPORTE'] = df_m['FECHA_REPORTE'].fillna(pd.to_datetime(df_m['FECHA_APE'], dayfirst=True, errors='coerce'))
            df_m = df_m[df_m['FECHA_REPORTE'].notna()]
            
            df_m_filtrado = df_m[
                (df_m['FECHA_REPORTE'].dt.month == numero_mes) & 
                (df_m['FECHA_REPORTE'].dt.year == anio_seleccionado)
            ].copy()
            
            if not df_m_filtrado.empty:
                act_upper = df_m_filtrado['ACTIVIDAD'].astype(str).str.upper().str.strip()
                mask_actividades_sop = act_upper.str.contains("SOP", na=False) | (act_upper == "CEQUI")
                df_m_filtrado = df_m_filtrado[mask_actividades_sop].copy()
            
            if not df_m_filtrado.empty:
                mask_validos = ~df_m_filtrado['TECNICO'].astype(str).str.upper().str.contains("LILIAN|WILFREDO", na=False)
                df_m_filtrado = df_m_filtrado[mask_validos].copy()
            
            if not df_m_filtrado.empty:
                df_m_filtrado['CLASIF_MATERIAL'] = df_m_filtrado.apply(clasificar_materiales, axis=1)
                
                df_equipos = df_m_filtrado[df_m_filtrado['CLASIF_MATERIAL'] == 'CAMBIO_EQUIPO']
                df_acometidas = df_m_filtrado[df_m_filtrado['CLASIF_MATERIAL'] == 'CAMBIO_ACOMETIDA']
                
                total_equipos = len(df_equipos)
                total_acometidas = len(df_acometidas)
                
                col_k1, col_k2 = st.columns(2)
                with col_k1:
                    st.markdown(f"""
                    <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #3B82F6; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #2D2F39;">
                        <div style="color: #94A3B8; font-size: 0.85rem; font-weight: bold; text-transform: uppercase;">🔌 CAMBIOS DE EQUIPO (ONT/ONU/CPE)</div>
                        <div style="color: #3B82F6; font-size: 2.5rem; font-weight: bold; margin-top: 5px;">{total_equipos}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col_k2:
                    st.markdown(f"""
                    <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #F59E0B; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #2D2F39;">
                        <div style="color: #94A3B8; font-size: 0.85rem; font-weight: bold; text-transform: uppercase;">🎗️ REEMPLAZOS DE ACOMETIDA (DROP)</div>
                        <div style="color: #F59E0B; font-size: 2.5rem; font-weight: bold; margin-top: 5px;">{total_acometidas}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("### 📊 Desglose de Cambios por Técnico")
                
                if total_equipos > 0:
                    eq_tech = df_equipos.groupby('TECNICO').size().reset_index(name='Equipos Cambiados')
                else:
                    eq_tech = pd.DataFrame(columns=['TECNICO', 'Equipos Cambiados'])
                    
                if total_acometidas > 0:
                    ac_tech = df_acometidas.groupby('TECNICO').size().reset_index(name='Acometidas Cambiadas')
                else:
                    ac_tech = pd.DataFrame(columns=['TECNICO', 'Acometidas Cambiadas'])
                    
                tech_summary = pd.merge(eq_tech, ac_tech, on='TECNICO', how='outer').fillna(0)
                tech_summary['Equipos Cambiados'] = tech_summary['Equipos Cambiados'].astype(int)
                tech_summary['Acometidas Cambiadas'] = tech_summary['Acometidas Cambiadas'].astype(int)
                tech_summary['Total Intervenciones'] = tech_summary['Equipos Cambiados'] + tech_summary['Acometidas Cambiadas']
                
                tech_summary = tech_summary[tech_summary['Total Intervenciones'] > 0]
                tech_summary = tech_summary.sort_values(by='Total Intervenciones', ascending=False)
                
                st.dataframe(
                    tech_summary, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TECNICO": st.column_config.TextColumn("👨‍🔧 Técnico"),
                        "Equipos Cambiados": st.column_config.NumberColumn("🔌 Equipos Cambiados", format="%d"),
                        "Acometidas Cambiadas": st.column_config.NumberColumn("🎗️ Acometidas Cambiadas", format="%d"),
                        "Total Intervenciones": st.column_config.NumberColumn("📦 Total General", format="%d")
                    }
                )
                
                st.markdown("### 📥 Descargar Reporte en Formato PDF")
                
                if st.button(f"📄 GENERAR REPORTE PDF ({mes_seleccionado} {anio_seleccionado})", use_container_width=True, type="primary", key="btn_generar_pdf_materiales"):
                    with st.spinner("Dibujando celdas y empaquetando reporte..."):
                        st.session_state['pdf_materiales_cargado'] = generar_pdf_materiales_mensual(
                            df_equipos, 
                            df_acometidas, 
                            tech_summary, 
                            mes_seleccionado, 
                            anio_seleccionado
                        )
                
                if 'pdf_materiales_cargado' in st.session_state and st.session_state['pdf_materiales_cargado'] is not None:
                    st.download_button(
                        label=f"📥 Descargar Reporte en PDF",
                        data=st.session_state['pdf_materiales_cargado'],
                        file_name=f"Reporte_Materiales_{mes_seleccionado}_{anio_seleccionado}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key="btn_descargar_pdf_materiales"
                    )
                
                with st.expander("🔍 Ver Vista Previa del Detalle de Transacciones"):
                    df_view_table = pd.concat([df_equipos, df_acometidas]).sort_values(by='FECHA_REPORTE')
                    if not df_view_table.empty:
                        df_view_table['FECHA_REPORTE'] = df_view_table['FECHA_REPORTE'].dt.strftime('%d/%m/%Y %H:%M')
                        df_view_table = df_view_table[['NUM', 'CLIENTE', 'TECNICO', 'COMENTARIO', 'FECHA_REPORTE']]
                        df_view_table.columns = ['Orden', 'Cliente', 'Técnico', 'Comentario de Cierre', 'Fecha']
                    st.dataframe(df_view_table, use_container_width=True, hide_index=True)
            else:
                st.warning(f"⚠️ No se encontraron transacciones u órdenes procesadas para el mes de {mes_seleccionado} {anio_seleccionado}.")

    # ==============================================================================
    # 6. MONITOR OPERATIVO EN VIVO 
    # ==============================================================================        
    if nav_menu_diamante == "⚡ Monitor en Vivo":
        
      # === FILTRADO SEGURO DE FECHAS PARA INDICADORES ===
        # Aseguramos la conversión a Datetime64 para evitar falsos positivos de fecha.
        # OJO: HORA_LIQ llega en UTC, así que hay que restarle 6h para obtener la
        # fecha real en hora de Honduras. Sin este ajuste, cualquier orden cerrada
        # entre las 6:00pm y medianoche (hora Honduras) del día ANTERIOR cae en la
        # misma fecha UTC que la madrugada/mañana de HOY, y se cuenta como
        # "cerrada hoy" sin serlo.
        df_monitor_filtrado['HORA_LIQ_CLEAN'] = pd.to_datetime(df_monitor_filtrado['HORA_LIQ'], errors='coerce') - pd.Timedelta(hours=6)

        mask_vivas_monitor = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        df_todas_pendientes_monitor = df_monitor_filtrado[mask_vivas_monitor].copy()

        # --- APLICACIÓN DEL REQUERIMIENTO: SOLO PASAN A NO ASIGNADAS LAS ACTIVIDADES DEL DETALLE CARGADO ---
        mask_has_tec_mon = mascara_tecnico_asignado(df_todas_pendientes_monitor['TECNICO'])
        mask_valid_no_asig_act = df_todas_pendientes_monitor['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_VALIDAS_NO_ASIGNADAS)
        # Filtramos df_todas_pendientes_monitor para que mantenga las asignadas y solo las unassigned que pertenezcan a las actividades permitidas
        df_todas_pendientes_monitor = df_todas_pendientes_monitor[mask_has_tec_mon | (~mask_has_tec_mon & mask_valid_no_asig_act)].copy()

        # Se eliminó la asignación antigua redundante que no filtraba por técnico

        df_todas_pendientes_monitor['DIAS_RETRASO'] = (pd.Timestamp(ahora_local).normalize() - pd.to_datetime(df_todas_pendientes_monitor['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).astype(int)
        
        if 'TECNICO' in df_todas_pendientes_monitor.columns:
            mask_josue_kpi = df_todas_pendientes_monitor['TECNICO'].astype(str).str.upper().str.contains("JOSUE MIGUEL SAUCEDA", na=False)
            df_todas_pendientes_monitor.loc[mask_josue_kpi, 'DIAS_RETRASO'] = 0
            
        df_todas_pendientes_monitor.loc[df_todas_pendientes_monitor['DIAS_RETRASO'] < 0, 'DIAS_RETRASO'] = 0

        df_todas_pendientes_monitor['CatD'] = df_todas_pendientes_monitor['DIAS_RETRASO'].apply(
            lambda d: ">= 7 Dia" if d >= 7 else ("= 4 a 6 Dias" if d >= 4 else ("= 1 a 3 Dias" if d >= 1 else "= 0 Dia"))
        )

        if os.path.exists("Logotipo monitor.png"):
            st.image("Logotipo monitor.png", width=400) 
        else:
            st.title("⚡ Monitor Operativo Maxcom")

        mask_tec_valido_mon = mascara_tecnico_asignado(df_todas_pendientes_monitor['TECNICO'])
        
        if check_no_asignadas:
            df_solo_asignadas_monitor = df_todas_pendientes_monitor[~mask_tec_valido_mon].copy()
        else:
            df_solo_asignadas_monitor = df_todas_pendientes_monitor[mask_tec_valido_mon].copy()
            
        vivas_count_asignadas = len(df_todas_pendientes_monitor[mask_tec_valido_mon])
        
        # Conteo depurado de cerradas de HOY (compara la fecha de cierre con hoy_date_valor)
        # Solo se cuentan actividades de la lista oficial (ACTIVIDADES_GANTT_PERMITIDAS);
        # actividades internas como ACTEFO/ACTIVARRES (que no son visitas técnicas
        # reales al cliente) no deben mostrarse ni inflar el contador de "Cerradas Hoy".
        mask_actividad_valida_cerr = df_monitor_filtrado['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_GANTT_PERMITIDAS)
        mask_cerradas_hoy = (df_monitor_filtrado['HORA_LIQ_CLEAN'].dt.date == hoy_date_valor) & (df_monitor_filtrado['ESTADO'].astype(str).str.upper() == 'CERRADA') & mask_actividad_valida_cerr
        df_cerradas_hoy_monitor = df_monitor_filtrado[mask_cerradas_hoy & mascara_tecnico_asignado(df_monitor_filtrado['TECNICO'])].copy()
        cerradas_hoy = len(df_cerradas_hoy_monitor)
    
        tecs_activos = df_solo_asignadas_monitor['TECNICO'].nunique() if not check_no_asignadas else 0
        offline_criticos_asignadas = int((df_todas_pendientes_monitor.get('ES_OFFLINE', pd.Series([False]*len(df_todas_pendientes_monitor))) == True).sum())
        total_pendientes_general = len(df_todas_pendientes_monitor)

        if es_movil:
            st.markdown(f"""
            <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; margin-top: 10px;">
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #3B82F6; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">ASIGNADAS</div>
                    <div style="color: #FFFFFF; font-size: 1.8rem; font-weight: bold;">{vivas_count_asignadas}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #10B981; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">CERRADAS</div>
                    <div style="color: #10B981; font-size: 1.8rem; font-weight: bold;">{cerradas_hoy}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #F59E0B; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">EN RUTA</div>
                    <div style="color: #FFFFFF; font-size: 1.8rem; font-weight: bold;">{tecs_activos}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 15px; border-radius: 12px; border-left: 4px solid #EF4444; flex: 1 1 45%; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                    <div style="color: #94A3B8; font-size: 0.7rem; font-weight: bold;">CAÍDAS</div>
                    <div style="color: #EF4444; font-size: 1.8rem; font-weight: bold;">{offline_criticos_asignadas}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            html_kpis = f"""
            <div style="display: flex; justify-content: space-between; gap: 15px; margin-bottom: 20px; margin-top: 10px;">
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #3B82F6; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                    <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">PENDIENTES ASIGNADAS</div>
                    <div style="color: #FFFFFF; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{vivas_count_asignadas}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #10B981; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                    <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">CERRADAS HOY</div>
                    <div style="color: #10B981; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{cerradas_hoy}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #F59E0B; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                    <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">TÉCNICOS EN RUTA</div>
                    <div style="color: #FFFFFF; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{tecs_activos}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #EF4444; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                    <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">CAÍDAS (OFFLINE)</div>
                    <div style="color: #EF4444; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{offline_criticos_asignadas}</div>
                </div>
                <div style="background: linear-gradient(145deg, #1A1D24 0%, #15171C 100%); padding: 20px; border-radius: 12px; border-left: 5px solid #A855F7; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); border-top: 1px solid #2D2F39; border-right: 1px solid #2D2F39; border-bottom: 1px solid #2D2F39;">
                    <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 600; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px;">TOTAL (ASIGNADAS + NO ASIGNADAS)</div>
                    <div style="color: #FFFFFF; font-size: 2.2rem; font-weight: 700; margin: 0; line-height: 1.2;">{total_pendientes_general}</div>
                </div>
            </div>
            """
            st.markdown(html_kpis, unsafe_allow_html=True)

        if st.session_state.get('config_ver_tablero', True):
            with st.expander("📊 TABLERO DE CARGA ACTUAL (TODAS LAS PENDIENTES)", expanded=not es_movil):
                if es_movil:
                    st.caption("📅 Resumen de Retraso")
                    res_retraso_v = df_todas_pendientes_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 a 6 Dias","= 1 a 3 Dias","= 0 Dia"], fill_value=0).reset_index()
                    res_retraso_v.columns = ['Dias', 'Cant']
                    sum_total_asignadas_v = res_retraso_v['Cant'].sum()
                    res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_asignadas_v*100):.0f}%" if sum_total_asignadas_v > 0 else "0%")
                    def style_dias_apply(row):
                        v = row['Dias']
                        bg_color, font_color = '', 'white'
                        if v == ">= 7 Dia": bg_color = '#d32f2f'
                        elif v == "= 4 a 6 Dias": bg_color = '#f57c00'
                        elif v == "= 1 a 3 Dias": bg_color, font_color = '#fbc02d', 'black'
                        elif v == "= 0 Dia": bg_color = '#388e3c'
                        return [f'background-color: {bg_color}; color: {font_color}; font-weight: bold' if i == 0 else '' for i in range(len(row))]
                    st.dataframe(res_retraso_v.style.apply(style_dias_apply, axis=1), hide_index=True, use_container_width=True)
                    st.write(f"**Total General Retraso: {sum_total_asignadas_v}**")
               
                else:
                    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
                    with col_t1:
                        st.caption("📅 Resumen de Retraso")
                        res_retraso_v = df_todas_pendientes_monitor['CatD'].value_counts().reindex([">= 7 Dia","= 4 a 6 Dias","= 1 a 3 Dias","= 0 Dia"], fill_value=0).reset_index()
                        res_retraso_v.columns = ['Dias', 'Cant']
                        sum_total_asignadas_v = res_retraso_v['Cant'].sum()
                        res_retraso_v['%'] = res_retraso_v['Cant'].apply(lambda x: f"{(x/sum_total_asignadas_v*100):.0f}%" if sum_total_asignadas_v > 0 else "0%")
                        def style_dias_apply(row):
                            v = row['Dias']
                            bg_color, font_color = '', 'white'
                            if v == ">= 7 Dia": bg_color = '#d32f2f'
                            elif v == "= 4 a 6 Dias": bg_color = '#f57c00'
                            elif v == "= 1 a 3 Dias": bg_color, font_color = '#fbc02d', 'black'
                            elif v == "= 0 Dia": bg_color = '#388e3c'
                            return [f'background-color: {bg_color}; color: {font_color}; font-weight: bold' if i == 0 else '' for i in range(len(row))]
                        st.dataframe(res_retraso_v.style.apply(style_dias_apply, axis=1), hide_index=True, use_container_width=True, height=178)
                        st.write(f"**Total: {sum_total_asignadas_v}**")

                g_tab_list = []
                sub_tab_list = []
                for idx, r in df_todas_pendientes_monitor.iterrows():
                    act = str(r.get('ACTIVIDAD', '')).upper()
                    com = str(r.get('COMENTARIO', '')).upper()
                    txt = act + " " + com
                    is_off = r.get('ES_OFFLINE', False)
                    if not re.search("SOP|FALLA|MANT|INS|ADIC|CAMBIO|MIGRACI|NUEVA|RECUP", txt):
                        g_tab_list.append("OTROS"); sub_tab_list.append(act if act != "" else "N/A")
                    elif re.search("INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP", txt) and not re.search("SOP|FALLA|MANT", act):
                        g_tab_list.append("INS")
                        if re.search("ADIC", txt): sub_tab_list.append("Adición")
                        elif re.search("CAMBIO|MIGRACI", txt): sub_tab_list.append("Cambio / Migración")
                        elif re.search("RECUP", txt): sub_tab_list.append("Recuperado")
                        else: sub_tab_list.append("Nueva")
                    else:
                        g_tab_list.append("SOP")
                        if is_off: sub_tab_list.append("ONT/ONU Offline")
                        elif re.search("NIVEL|DB", com): sub_tab_list.append("Niveles alterados")
                        elif re.search("FIBRA|FTTH", act): sub_tab_list.append("FTTH / FIBRA")
                        elif re.search("NAV|INTERNET", act): sub_tab_list.append("Navegación / Internet")
                        elif re.search("TV|CABLE", act): sub_tab_list.append("Sin señal de TV")
                        else: sub_tab_list.append("SOP General")
                        
                df_tablero = df_todas_pendientes_monitor.copy()
                df_tablero['G_TAB'] = g_tab_list
                df_tablero['SUB_TAB'] = sub_tab_list
                
                if es_movil:
                    st.caption("🛠️ SOP / Mantenimiento")
                    df_sop = df_tablero[df_tablero['G_TAB'] == 'SOP']
                    res_sop = df_sop['SUB_TAB'].value_counts().reset_index()
                    res_sop.columns = ['SOP', 'Cant']
                    st.dataframe(res_sop, hide_index=True, use_container_width=True)
                    
                    st.caption("📦 Compartido / Tipo")
                    df_ins = df_tablero[df_tablero['G_TAB'] == 'INS']
                    res_ins = df_ins['SUB_TAB'].value_counts().reset_index()
                    res_ins.columns = ['Instalaciones', 'Cant']
                    cats_ins = ['Nueva', 'Adición', 'Cambio / Migración', 'Recuperado']
                    for c in cats_ins:
                        if c not in res_ins['Instalaciones'].values: 
                            res_ins = pd.concat([res_ins, pd.DataFrame([{'Instalaciones': c, 'Cant': 0}])], ignore_index=True)
                    st.dataframe(res_ins, hide_index=True, use_container_width=True)
                else:
                    with col_t2:
                        st.caption("🛠️ SOP / Mantenimiento")
                        df_sop = df_tablero[df_tablero['G_TAB'] == 'SOP']
                        res_sop = df_sop['SUB_TAB'].value_counts().reset_index()
                        res_sop.columns = ['SOP', 'Cant']
                        st.dataframe(res_sop, hide_index=True, use_container_width=True, height=140)
                        st.write(f"**Total: {df_sop.shape[0]}**")
                        st.metric("Exceden 2h ⚠️", int((df_sop['ALERTA_TIEMPO'] == True).sum()))

                    with col_t3:
                        st.caption("📦 Instalaciones")
                        df_ins = df_tablero[df_tablero['G_TAB'] == 'INS']
                        res_ins = df_ins['SUB_TAB'].value_counts().reset_index()
                        res_ins.columns = ['Instalaciones', 'Cant']
                        cats_ins = ['Nueva', 'Adición', 'Cambio / Migración', 'Recuperado']
                        for c in cats_ins:
                            if c not in res_ins['Instalaciones'].values: 
                                res_ins = pd.concat([res_ins, pd.DataFrame([{'Instalaciones': c, 'Cant': 0}])], ignore_index=True)
                        st.dataframe(res_ins, hide_index=True, use_container_width=True, height=178)
                        st.write(f"**Total: {df_ins.shape[0]}**")

                    with col_t4:
                        st.caption("⚙️ Otros")
                        df_otros = df_tablero[df_tablero['G_TAB'] == 'OTROS']
                        res_otr = df_otros['SUB_TAB'].value_counts().reset_index()
                        res_otr.columns = ['Otros', 'Cant']
                        st.dataframe(res_otr.head(8), hide_index=True, use_container_width=True, height=178)
                        st.write(f"**Total: {df_otros.shape[0]}**")
                        
        if st.session_state.get('config_ver_consolidado', True):
            with st.expander("📊 CONSOLIDADO POR SEGMENTO (MORA VS AL DÍA)", expanded=True):
                st.markdown("<h4 style='text-align: center; color: #1F2937;'>Avance Operativo Detallado</h4><br>", unsafe_allow_html=True)
                
                df_cerradas_hoy_monitor['FECHA_APE_DT'] = pd.to_datetime(df_cerradas_hoy_monitor['FECHA_APE'], errors='coerce')
                
                def calcular_metricas(segmento):
                    if segmento == 'GLOBAL':
                        p = df_solo_asignadas_monitor
                        c = df_cerradas_hoy_monitor
                    else:
                        p = df_solo_asignadas_monitor[df_solo_asignadas_monitor['SEGMENTO'] == segmento]
                        c = df_cerradas_hoy_monitor[df_cerradas_hoy_monitor['SEGMENTO'] == segmento]

                    p_mora = len(p[p['DIAS_RETRASO'] > 0])
                    p_hoy = len(p[p['DIAS_RETRASO'] == 0])
                    c_mora = len(c[c['FECHA_APE_DT'].dt.date < hoy_date_valor])
                    c_hoy = len(c[c['FECHA_APE_DT'].dt.date == hoy_date_valor])

                    tot_mora, tot_hoy = p_mora + c_mora, p_hoy + c_hoy
                    tot_global = tot_mora + tot_hoy
                    cerr_global = c_mora + c_hoy

                    pct_mora = (c_mora / tot_mora * 100) if tot_mora > 0 else 0
                    pct_hoy = (c_hoy / tot_hoy * 100) if tot_hoy > 0 else 0
                    pct_global = (cerr_global / tot_global * 100) if tot_global > 0 else 0

                    return {
                        'tot_g': tot_global, 'cerr_g': cerr_global, 'pct_g': pct_global,
                        'tot_m': tot_mora, 'cerr_m': c_mora, 'pct_m': pct_mora,
                        'tot_h': tot_hoy, 'cerr_h': c_hoy, 'pct_h': pct_hoy,
                        'df_p': p, 'df_c': c
                    }

                stats_resi = calcular_metricas('RESIDENCIAL')
                stats_plex = calcular_metricas('PLEX')
                stats_global = calcular_metricas('GLOBAL')

                def renderizar_metrica(col_ui, stats, titulo, color_hex, key_btn):
                    with col_ui:
                        fig = go.Figure(go.Pie(
                            values=[stats['pct_g'], max(0, 100 - stats['pct_g'])] if stats['tot_g'] > 0 else [0, 100],
                            labels=['Completado', 'Pendiente'], hole=0.8,
                            marker=dict(colors=[color_hex, '#2D2F39']),
                            textinfo='none', hoverinfo='none', direction='clockwise', sort=False
                        ))
                        
                        texto_central = f"{stats['pct_g']:.0f}%" if stats['tot_g'] > 0 else "N/A"
                        subtexto = f"Total: {stats['cerr_g']} de {stats['tot_g']}" if stats['tot_g'] > 0 else "Sin asignaciones"
                        
                        fig.update_layout(
                            showlegend=False, height=150, margin=dict(l=5, r=5, t=30, b=5),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#1F2937', 'size': 14, 'weight': 'bold'}},
                            annotations=[
                                dict(text=texto_central, x=0.5, y=0.42, font_size=26, font_color=color_hex, showarrow=False, font_weight="bold"),
                                dict(text=subtexto, x=0.5, y=0.68, font_size=11, font_color="#6B7280", showarrow=False)
                            ]
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"pie_{key_btn}")

                        html_badges = f"""
                        <div style="display:flex; justify-content:center; gap:8px; font-size:11px; margin-top:-15px; margin-bottom:10px;">
                            <div style="background-color:#fee2e2; color:#b91c1c; padding:3px 8px; border-radius:10px; font-weight:bold; border:1px solid #fca5a5;">
                                🔴 Mora: {stats['cerr_m']}/{stats['tot_m']} ({stats['pct_m']:.0f}%)
                            </div>
                            <div style="background-color:#dbeafe; color:#1d4ed8; padding:3px 8px; border-radius:10px; font-weight:bold; border:1px solid #93c5fd;">
                                🔵 Hoy: {stats['cerr_h']}/{stats['tot_h']} ({stats['pct_h']:.0f}%)
                            </div>
                        </div>
                        """
                        st.markdown(html_badges, unsafe_allow_html=True)

                        if st.button("🔍 Ver Desglose", use_container_width=True, key=f"btn_{key_btn}"):
                            mostrar_detalle_avance(titulo.upper(), stats['df_p'], stats['df_c'])

                if es_movil:
                    renderizar_metrica(st.container(), stats_resi, "🏠 Residencial", "#EF4444", "resi_m")
                    renderizar_metrica(st.container(), stats_plex, "🏢 PLEX", "#F59E0B", "plex_m")
                    renderizar_metrica(st.container(), stats_global, "🌍 Global", "#10B981", "glob_m")
                else:
                    col1, col2, col3 = st.columns(3)
                    renderizar_metrica(col1, stats_resi, "🏠 Residencial", "#EF4444", "resi")
                    renderizar_metrica(col2, stats_plex, "🏢 PLEX", "#F59E0B", "plex")
                    renderizar_metrica(col3, stats_global, "🌍 Global", "#10B981", "glob")

                st.markdown("---")
        
        if st.session_state.get('config_mostrar_panel', True):
            if not es_movil:
                if st.session_state.get('config_ver_gantt', True):
                    with st.expander("⏳ LÍNEA DE TIEMPO OPERATIVA (GANTT)", expanded=False):

                        # Una orden que se inició AYER y sigue abierta hoy desaparecía por
                        # completo del Gantt, aunque el técnico la siga trabajando: el filtro
                        # solo aceptaba HORA_INI de hoy. Esta opción permite arrastrarlas.
                        incluir_arrastradas = st.checkbox(
                            "➕ Incluir órdenes que siguen abiertas de días anteriores",
                            value=True,
                            key="chk_gantt_arrastradas",
                            help="Órdenes iniciadas en días previos que aún no se cierran. Su barra empieza al inicio de la jornada de hoy, porque el trabajo real de días anteriores no cabe en esta línea de tiempo."
                        )

                        mask_cerradas_gantt = (df_monitor_filtrado['ESTADO'].astype(str).str.upper() == 'CERRADA') & (df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor)

                        # El Gantt representa TRABAJO REALIZADO en la línea de tiempo, así que
                        # una orden solo entra si tiene una hora de inicio real (HORA_INI). Una
                        # orden sin HORA_INI todavía no fue iniciada en campo -- está únicamente
                        # asignada -- y dibujarla implicaría inventar un horario que nunca ocurrió.
                        # Una orden cuenta como VIVA si su estado no es terminal.
                        #
                        # Antes se exigía que el estado coincidiera con una lista blanca
                        # (PENDIENTE, EN PROCESO, ASIGNADA...). Cualquier estado que no
                        # estuviera ahí -- por ejemplo 'ABIERTA' -- no calificaba ni como viva
                        # ni como cerrada, y la orden desaparecía del Gantt aunque tuviera
                        # hora de inicio real. Invertir el criterio elimina esa clase de fallo
                        # para siempre: no hay que adivinar todos los nombres de estado, solo
                        # los pocos que significan "terminada".
                        _estado_up = df_monitor_filtrado['ESTADO'].astype(str).str.upper().str.strip()
                        mask_viva_gantt = ~_estado_up.str.contains('|'.join(ESTADOS_TERMINALES), na=False, regex=True)

                        # La serie de fechas se calcula UNA vez y como objeto. Si toda la
                        # columna HORA_INI viene vacía (madrugada, o filtros muy restrictivos),
                        # comparar con "<" sobre datetime lanza TypeError y tumbaría todo el
                        # Gantt; con dtype object la comparación se resuelve fila por fila.
                        _fechas_ini = pd.to_datetime(df_monitor_filtrado['HORA_INI'], errors='coerce')
                        _solo_fecha_ini = _fechas_ini.dt.date.astype(object)

                        mask_hora_ini_hoy = _solo_fecha_ini == hoy_date_valor
                        mask_abiertas_gantt = mask_viva_gantt & mask_hora_ini_hoy

                        # Abiertas iniciadas en días anteriores que siguen vivas.
                        #
                        # NO se exige HORA_LIQ vacío a propósito: el sistema a veces deja un
                        # timestamp provisional en HORA_LIQ antes de que el técnico confirme el
                        # cierre real. Más abajo, para DIBUJAR la barra, ya se confía en el
                        # ESTADO por encima de HORA_LIQ; exigirlo aquí creaba una incoherencia
                        # que dejaba fuera del Gantt órdenes vivas de días anteriores (no
                        # entraban por "abiertas hoy" ni por "cerradas hoy" ni por "arrastradas").
                        mask_ini_anterior = _solo_fecha_ini.apply(
                            lambda d: bool(d is not None and not pd.isna(d) and d < hoy_date_valor)
                        )
                        mask_arrastradas = mask_viva_gantt & _fechas_ini.notna() & mask_ini_anterior
                        if not incluir_arrastradas:
                            mask_arrastradas = mask_arrastradas & False

                        df_para_gantt_final = df_monitor_filtrado[mask_cerradas_gantt | mask_abiertas_gantt | mask_arrastradas].copy()

                        # Índice limpio y único. Al concatenar orígenes de datos el índice
                        # queda con etiquetas repetidas, y eso rompe tanto reindex() como
                        # las asignaciones por máscara del recorte de barras (pandas alinea
                        # por etiqueta y con duplicados asigna valores cruzados).
                        df_para_gantt_final = df_para_gantt_final.reset_index(drop=True)

                        # La marca se recalcula sobre el propio DataFrame en lugar de
                        # reindexar la máscara original. Cuando el índice trae etiquetas
                        # repetidas -- cosa que ocurre al concatenar orígenes de datos --
                        # reindex() falla con "cannot reindex on an axis with duplicate
                        # labels" y tumbaba el Gantt.
                        if incluir_arrastradas and not df_para_gantt_final.empty:
                            df_para_gantt_final['ES_ARRASTRADA'] = (
                                df_para_gantt_final['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                                & df_para_gantt_final['HORA_INI'].notna()
                                & (df_para_gantt_final['HORA_INI'].dt.date < hoy_date_valor)
                            )
                        else:
                            df_para_gantt_final['ES_ARRASTRADA'] = False

                        n_arrastradas = int(df_para_gantt_final['ES_ARRASTRADA'].sum())
                        if n_arrastradas:
                            st.caption(f"🔁 {n_arrastradas} orden(es) vienen abiertas de días anteriores. Su barra arranca al inicio de la jornada.")

                        try:
                            df_almuerzos_hoy = cargar_almuerzos(conn, fecha=hoy_date_valor.strftime('%Y-%m-%d'))
                        except Exception:
                            df_almuerzos_hoy = pd.DataFrame()

                        def _obtener_almuerzo_tec(tec_nombre):
                            if df_almuerzos_hoy is None or df_almuerzos_hoy.empty:
                                return None, None
                            tec_norm_b = str(tec_nombre).strip().upper()
                            fila = df_almuerzos_hoy[df_almuerzos_hoy['TECNICO'].astype(str).str.upper() == tec_norm_b]
                            if fila.empty:
                                return None, None
                            try:
                                hi = datetime.combine(hoy_date_valor, datetime.strptime(str(fila.iloc[0]['HORA_INICIO']), '%H:%M').time())
                                hf = datetime.combine(hoy_date_valor, datetime.strptime(str(fila.iloc[0]['HORA_FIN']), '%H:%M').time())
                                return hi, hf
                            except Exception:
                                return None, None
                        
                        # ==============================================================================
                        # CONTINUACIÓN: PROCESAMIENTO Y DIBUJADO DEL GANTT
                        # ==============================================================================
                        mask_sin_inicio = df_para_gantt_final['HORA_INI'].isna() & df_para_gantt_final['HORA_LIQ'].notnull()
                        df_para_gantt_final.loc[mask_sin_inicio, 'HORA_INI'] = df_para_gantt_final.loc[mask_sin_inicio, 'HORA_LIQ'] - pd.Timedelta(minutes=30)

                        df_para_gantt_final = df_para_gantt_final[df_para_gantt_final['HORA_INI'].notnull()].copy()


                        # Se resetea aquí; si el Gantt termina vacío, ningún técnico debe
                        # figurar en las tablas de abajo.
                        tecnicos_en_gantt_hoy = set()
                        
                        if not df_para_gantt_final.empty:
                            ahora_hx = get_honduras_time()
                            
                            df_para_gantt_final['GANTT_START'] = df_para_gantt_final['HORA_INI']

                            # Las órdenes arrastradas de días anteriores se recortan al inicio
                            # de la jornada de hoy. Si se dejara su HORA_INI real, el eje se
                            # estiraría días hacia atrás y comprimiría todo el trabajo de hoy
                            # hasta volverlo ilegible.
                            if 'ES_ARRASTRADA' in df_para_gantt_final.columns:
                                mask_arr = df_para_gantt_final['ES_ARRASTRADA'].fillna(False).astype(bool)
                                if mask_arr.any():
                                    inicio_jornada = datetime.combine(hoy_date_valor, dt_time(6, 0))
                                    df_para_gantt_final.loc[mask_arr, 'GANTT_START'] = inicio_jornada

                            # Solo se estira la barra hasta la hora actual si la orden está
                            # GENUINAMENTE abierta. El criterio único es el ESTADO: si dice que
                            # sigue en un estado vivo (PENDIENTE/INICIADA/EN RUTA/etc.), se
                            # confía en eso por encima de HORA_LIQ -- a veces el sistema deja un
                            # timestamp provisional en HORA_LIQ antes de que el técnico confirme
                            # el cierre real, y exigir HORA_LIQ vacío además del ESTADO vivo
                            # cortaba esas barras antes de tiempo, haciendo que técnicos que
                            # siguen trabajando ahora mismo se vieran "terminados" en horas
                            # distintas en vez de todos llegar hasta el mismo punto (ahora).
                            mask_estado_vivo_barra = df_para_gantt_final['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
                            mask_realmente_abierta = mask_estado_vivo_barra

                            df_para_gantt_final['GANTT_END'] = df_para_gantt_final['HORA_LIQ']
                            df_para_gantt_final.loc[mask_realmente_abierta, 'GANTT_END'] = ahora_hx

                            # Orden ya cerrada (o en cualquier estado no vivo) pero sin HORA_LIQ
                            # utilizable: no se inventa una duración hasta "ahora"; se le da un
                            # bloque acotado para que no domine ni distorsione la gráfica.
                            mask_cierre_desconocido = df_para_gantt_final['GANTT_END'].isna()
                            df_para_gantt_final.loc[mask_cierre_desconocido, 'GANTT_END'] = df_para_gantt_final.loc[mask_cierre_desconocido, 'GANTT_START'] + pd.Timedelta(minutes=30)

                            df_para_gantt_final['Inicio'] = df_para_gantt_final['HORA_INI'].dt.strftime('%H:%M')
                            df_para_gantt_final['Cierre'] = df_para_gantt_final['HORA_LIQ'].apply(
                                lambda x: x.strftime('%H:%M') if pd.notnull(x) else "En curso (Abierta)"
                            )
                            
                            df_para_gantt_final['TECNICO'] = df_para_gantt_final['TECNICO'].apply(normalizar_nombre_cruce)
                            df_para_gantt_final = df_para_gantt_final.sort_values(by=['TECNICO', 'GANTT_START'])

                            actividades_permitidas = ACTIVIDADES_GANTT_PERMITIDAS
                            
                            df_para_gantt_final = df_para_gantt_final[
                                df_para_gantt_final['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_permitidas)
                            ]

                            # Agregar barras de ALMUERZO registradas manualmente para el día
                            if df_almuerzos_hoy is not None and not df_almuerzos_hoy.empty:
                                filas_almuerzo = []
                                for _, fila_alm in df_almuerzos_hoy.iterrows():
                                    try:
                                        tec_alm = normalizar_nombre_cruce(fila_alm['TECNICO'])
                                        hi_alm = datetime.combine(hoy_date_valor, datetime.strptime(str(fila_alm['HORA_INICIO']), '%H:%M').time())
                                        hf_alm = datetime.combine(hoy_date_valor, datetime.strptime(str(fila_alm['HORA_FIN']), '%H:%M').time())
                                        
                                        # Cálculo dinámico del tiempo total del almuerzo
                                        duracion_alm_m = int((hf_alm - hi_alm).total_seconds() / 60)
                                        h_v, m_v = divmod(duracion_alm_m, 60)
                                        tiempo_real_alm_v = f"{h_v}h {m_v}m" if h_v > 0 else f"{m_v}m"
                                        
                                        filas_almuerzo.append({
                                            'TECNICO': tec_alm,
                                            'ACTIVIDAD': 'ALMUERZO',
                                            'NUM': '-',
                                            'CLIENTE': '-',
                                            'COLONIA': '-',
                                            'ESTADO': 'ALMUERZO',
                                            'GANTT_START': hi_alm,
                                            'GANTT_END': hf_alm,
                                            'Inicio': hi_alm.strftime('%H:%M'),
                                            'Cierre': hf_alm.strftime('%H:%M'),
                                            'TIEMPO_REAL': tiempo_real_alm_v
                                        })
                                    except Exception:
                                        continue
                                if filas_almuerzo:
                                    df_para_gantt_final = pd.concat([df_para_gantt_final, pd.DataFrame(filas_almuerzo)], ignore_index=True)
                                    df_para_gantt_final = df_para_gantt_final.sort_values(by=['TECNICO', 'GANTT_START'])

                            # NOTA DE ORDEN: el control de solapes se ejecuta AQUÍ, después de
                            # insertar los almuerzos, y no antes. El bloque de almuerzo es una
                            # barra más en la fila del técnico; si se agregara después del
                            # control, entraría sin pasar por él y podría montarse encima de una
                            # orden que empezó dentro de ese horario, ocultándola por completo.
                            # --- CAPAS: la orden abierta sigue corriendo por debajo ---
                            # Una orden que sigue abierta NO se recorta al iniciar la siguiente:
                            # su barra continúa hasta la hora actual, porque el trabajo sigue
                            # vigente. Para que las órdenes nuevas no queden escondidas debajo,
                            # se dibujan en una capa superior (ver construcción del gráfico).
                            #
                            # Las órdenes YA CERRADAS sí se recortan entre sí: ahí el traslape
                            # no representa nada real y solo taparía información.
                            df_para_gantt_final = df_para_gantt_final.sort_values(by=['TECNICO', 'GANTT_START'])
                            siguiente_inicio = df_para_gantt_final.groupby('TECNICO')['GANTT_START'].shift(-1)

                            _sigue_abierta = df_para_gantt_final['ESTADO'].astype(str).str.upper().str.strip().apply(
                                lambda e: not any(t in e for t in ESTADOS_TERMINALES)
                            ) & (df_para_gantt_final['ACTIVIDAD'].astype(str) != 'ALMUERZO')

                            mask_invade = (
                                siguiente_inicio.notna()
                                & (df_para_gantt_final['GANTT_END'] > siguiente_inicio)
                                & (siguiente_inicio > df_para_gantt_final['GANTT_START'])
                                & ~_sigue_abierta
                            )
                            df_para_gantt_final.loc[mask_invade, 'GANTT_END'] = siguiente_inicio[mask_invade]

                            # Ancho mínimo visible (10 min), expandiendo hacia adelante pero
                            # SIN pasar del inicio de la siguiente orden.
                            ancho_min_barra = pd.Timedelta(minutes=10)
                            fin_objetivo = df_para_gantt_final['GANTT_START'] + ancho_min_barra
                            tope_permitido = siguiente_inicio.where(siguiente_inicio > df_para_gantt_final['GANTT_START'], fin_objetivo).fillna(fin_objetivo)
                            fin_ajustado = pd.concat([fin_objetivo, tope_permitido], axis=1).min(axis=1)

                            mask_barra_corta = (df_para_gantt_final['GANTT_END'] - df_para_gantt_final['GANTT_START']) < ancho_min_barra
                            df_para_gantt_final.loc[mask_barra_corta, 'GANTT_END'] = fin_ajustado[mask_barra_corta]

                            mask_inv_m = df_para_gantt_final['GANTT_END'] < df_para_gantt_final['GANTT_START']
                            df_para_gantt_final.loc[mask_inv_m, 'GANTT_END'] = df_para_gantt_final.loc[mask_inv_m, 'GANTT_START'] + ancho_min_barra

                            # CAPA DE FONDO: órdenes abiertas cuya barra se traslapa con otra
                            # posterior del mismo técnico. Van abajo para que las demás se vean.
                            _fin_por_fila = df_para_gantt_final['GANTT_END']
                            _hay_posterior = siguiente_inicio.notna() & (_fin_por_fila > siguiente_inicio)
                            df_para_gantt_final['ES_FONDO'] = (_sigue_abierta & _hay_posterior).fillna(False)

                            cli_series_f = df_para_gantt_final['CLIENTE'].fillna('-').astype(str) if 'CLIENTE' in df_para_gantt_final.columns else pd.Series(['-'] * len(df_para_gantt_final), index=df_para_gantt_final.index).astype(str)

                            # Salvaguarda: si por cualquier motivo TIEMPO_REAL no viene ya
                            # calculado en alguna fila (ej. orígenes de datos distintos),
                            # se calcula aquí mismo para que nunca falte en la nota flotante.
                            if 'TIEMPO_REAL' not in df_para_gantt_final.columns:
                                df_para_gantt_final['TIEMPO_REAL'] = pd.NA
                            mask_tiempo_real_faltante = df_para_gantt_final['TIEMPO_REAL'].isna()
                            if mask_tiempo_real_faltante.any():
                                diff_fill = df_para_gantt_final.loc[mask_tiempo_real_faltante, 'HORA_LIQ'] - df_para_gantt_final.loc[mask_tiempo_real_faltante, 'HORA_INI']
                                df_para_gantt_final.loc[mask_tiempo_real_faltante, 'TIEMPO_REAL'] = np.where(
                                    df_para_gantt_final.loc[mask_tiempo_real_faltante, 'HORA_LIQ'].isnull(),
                                    "En curso (Abierta)",
                                    (diff_fill.dt.total_seconds() // 3600).fillna(0).astype(int).astype(str) + "h " +
                                    ((diff_fill.dt.total_seconds() % 3600) // 60).fillna(0).astype(int).astype(str) + "m"
                                )
                            
                            # Para las arrastradas se aclara su fecha real de inicio, porque
                            # su barra aparece recortada al inicio de la jornada de hoy.
                            if 'ES_ARRASTRADA' in df_para_gantt_final.columns:
                                nota_arrastre = df_para_gantt_final.apply(
                                    lambda r: f"<br>⚠️ Abierta desde {r['HORA_INI'].strftime('%d/%m %H:%M')}"
                                    if bool(r.get('ES_ARRASTRADA')) and pd.notnull(r.get('HORA_INI')) else "",
                                    axis=1
                                )
                            else:
                                nota_arrastre = ""

                            df_para_gantt_final['INFO_HOVER'] = (
                                "ACTIVIDAD=" + df_para_gantt_final['ACTIVIDAD'].astype(str) + "<br>" +
                                "NUM=" + df_para_gantt_final['NUM'].astype(str) + "<br>" +
                                "CLIENTE=" + cli_series_f + "<br>" +
                                "COLONIA=" + df_para_gantt_final['COLONIA'].astype(str) + "<br>" +
                                "ESTADO=" + df_para_gantt_final['ESTADO'].astype(str) + "<br>" +
                                "Inicio=" + df_para_gantt_final['Inicio'].astype(str) + "<br>" +
                                "Cierre=" + df_para_gantt_final['Cierre'].astype(str) + "<br>" +
                                "Tiempo Total=" + df_para_gantt_final['TIEMPO_REAL'].astype(str)
                                + nota_arrastre
                            )

                            st.markdown("<h5 style='text-align: left; color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px;'>👨‍🔧 Productividad Diaria (Actividades Aperturadas Hoy)</h5>", unsafe_allow_html=True)
                            
                            colores_solidos = {
                                "SOPFIBRA": "#d32f2f",         
                                "SOP": "#d32f2f",                
                                "INSFIBRA": "#1976d2",         
                                "INSFIBRACORP": "#0d47a1",     
                                "PEXTERNO": "#f57c00",         
                                "PLEXISCA": "#e65100",         
                                "TRASLADOEXTFIBRA": "#8e24aa",  
                                "SOPRECONCORP": "#c2185b",       
                                "SOPRECONHFC": "#c2185b",       
                                "SOPRECONFIBRA": "#c2185b",
                                "TVADICIONAL": "#00897b",
                                "ALMUERZO": "#78909c"
                            }

                            # --- GRÁFICO EN DOS CAPAS ---
                            # Plotly dibuja los trazos en el orden en que se agregan, así que
                            # el orden de fig.data define qué queda encima. Se arman dos
                            # figuras y se combinan: primero las órdenes abiertas que siguen
                            # corriendo (fondo), luego todo lo demás (frente). Así la barra de
                            # una orden abierta continúa hasta la hora actual, pero las órdenes
                            # que el técnico inició después se dibujan por encima y quedan
                            # visibles en vez de perderse debajo.
                            _alto_fig = max(400, len(df_para_gantt_final['TECNICO'].unique()) * 45)
                            _cats_y = sorted(df_para_gantt_final['TECNICO'].dropna().unique().tolist())

                            _df_fondo = df_para_gantt_final[df_para_gantt_final['ES_FONDO'] == True]
                            _df_frente = df_para_gantt_final[df_para_gantt_final['ES_FONDO'] != True]

                            def _crear_timeline(_df):
                                return px.timeline(
                                    _df,
                                    x_start="GANTT_START",
                                    x_end="GANTT_END",
                                    y="TECNICO",
                                    color="ACTIVIDAD",
                                    text="ACTIVIDAD",
                                    custom_data=["INFO_HOVER"],
                                    color_discrete_map=colores_solidos,
                                    height=_alto_fig
                                )

                            if not _df_fondo.empty and not _df_frente.empty:
                                _fig_fondo = _crear_timeline(_df_fondo)
                                _fig_frente = _crear_timeline(_df_frente)

                                # Las del fondo se atenúan un poco y no repiten leyenda, para
                                # que se lean como "sigue en curso" sin competir con las de arriba.
                                for _tr in _fig_fondo.data:
                                    _tr.showlegend = False
                                    _tr.opacity = 0.55

                                fig_gantt = go.Figure(
                                    data=list(_fig_fondo.data) + list(_fig_frente.data),
                                    layout=_fig_frente.layout
                                )
                                fig_gantt.update_yaxes(categoryorder='array', categoryarray=_cats_y)
                                fig_gantt.update_layout(barmode='overlay', height=_alto_fig)
                                st.caption(
                                    f"🔁 {len(_df_fondo)} orden(es) siguen abiertas: su barra continúa atenuada por "
                                    "debajo, y las órdenes iniciadas después se muestran encima."
                                )
                            else:
                                fig_gantt = _crear_timeline(df_para_gantt_final)
                            
                            fig_gantt.update_yaxes(autorange="reversed", title_text="", type="category")

                            # El eje se ajusta al horario real de actividad del día (con 30 min
                            # de margen) en vez de un fijo 06:00-22:00. Antes, si el trabajo
                            # terminaba a las 15:00, casi la mitad del ancho quedaba vacía y
                            # comprimía todas las barras, haciendo que los huecos reales entre
                            # una orden y otra fueran casi imperceptibles.
                            margen_eje = pd.Timedelta(minutes=30)
                            if df_para_gantt_final.empty or df_para_gantt_final['GANTT_START'].isna().all() or df_para_gantt_final['GANTT_END'].isna().all():
                                # Sin datos (aún) para calcular un rango real -- se usa el
                                # respaldo fijo de siempre (06:00 a las 22:00 de hoy) en vez de
                                # tronar con NaT.strftime(). Esto pasa típicamente muy temprano
                                # en el día, cuando todavía no hay ninguna orden abierta/cerrada.
                                hora_inicio_pantalla = datetime.combine(hoy_date_valor, dt_time(6, 0)).strftime('%Y-%m-%d %H:%M:%S')
                                hora_fin_pantalla = datetime.combine(hoy_date_valor, dt_time(22, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                inicio_real_dia = df_para_gantt_final['GANTT_START'].min() - margen_eje
                                fin_real_dia = df_para_gantt_final['GANTT_END'].max() + margen_eje
                                hora_inicio_pantalla = inicio_real_dia.strftime('%Y-%m-%d %H:%M:%S')
                                hora_fin_pantalla = fin_real_dia.strftime('%Y-%m-%d %H:%M:%S')
                            
                            fig_gantt.update_xaxes(range=[hora_inicio_pantalla, hora_fin_pantalla], tickformat="%H:%M", title_text="Cronograma de Actividades")
                            # opacity=1.0: las barras deben ser SÓLIDAS. Con opacidad menor,
                            # las órdenes abiertas (que se extienden hasta la hora actual) se
                            # encimaban unas con otras y se transparentaban entre sí, lo que
                            # producía un efecto de "rayado" en vez de bloques limpios.
                            # Se aplica a todos MENOS la opacidad, que se fija después para no
                            # borrar la atenuación de las barras de fondo (órdenes en curso).
                            fig_gantt.update_traces(textposition='inside', insidetextanchor='middle', marker_line_color='white', marker_line_width=1.5, hovertemplate="%{customdata[0]}<extra></extra>")
                            for _tr in fig_gantt.data:
                                if _tr.opacity is None:
                                    _tr.opacity = 1.0
                            fig_gantt.update_layout(showlegend=True, legend_title_text='Identificador de Actividades', legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02), margin=dict(t=10, b=20, l=0, r=150), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.02)")
                            
                            st.plotly_chart(fig_gantt, use_container_width=True)

                            # Se recalcula aquí (y no antes) porque df_para_gantt_final ya
                            # pasó por TODOS los filtros de dibujado (actividades permitidas,
                            # bloques de almuerzo, etc.). Este es el set real de técnicos que
                            # el usuario ve en la gráfica.
                            tecnicos_en_gantt_hoy = set(df_para_gantt_final['TECNICO'].dropna().unique())

                        # ==============================================================================
                        # CÁLCULO DE ALERTAS OPERATIVAS EN TIEMPO REAL
                        # ==============================================================================
                        alertas_9am = []
                        alertas_tiempo_muerto = []
                        
                        tecnicos_validos_alertas = set()
                        file_to_load = "personal_tecnico.txt" if os.path.exists("personal_tecnico.txt") else ("gps.txt" if os.path.exists("gps.txt") else None)
                        if file_to_load:
                            try:
                                with open(file_to_load, "r", encoding="utf-8") as f:
                                    for line in f:
                                        line = line.strip()
                                        if line:
                                            parts = line.split(",")
                                            if len(parts) >= 3:
                                                name = parts[2].strip().rstrip(".")
                                            else:
                                                name = parts[-1].strip().rstrip(".")
                                            tecnicos_validos_alertas.add(normalizar_nombre_cruce(name))
                            except Exception as e:
                                pass
                        
                        ahora_local = get_honduras_time()
                        limite_9am = datetime.combine(hoy_date_valor, dt_time(9, 0))

                        # tecnicos_en_gantt_hoy ya fue calculado justo arriba, usando el
                        # dataframe final del Gantt (después de todos sus filtros).

                        # Salvaguarda anti-desfase de nombres: si el archivo de técnicos
                        # válidos no coincide con NINGUNO de los técnicos que sí tienen
                        # actividad hoy en el Gantt, es señal de que los nombres no calzan
                        # (tildes, orden de apellidos, etc.). En ese caso se desactiva el
                        # filtro para no dejar las tablas vacías por error.
                        if tecnicos_validos_alertas and not (tecnicos_validos_alertas & tecnicos_en_gantt_hoy):
                            tecnicos_validos_alertas = set()

                        # 1. Validación de Inicio Tardío (Pasadas las 9:00 AM)
                        primera_orden_por_tec = {}
                        if ahora_local > limite_9am:
                            tecs_con_asignacion = df_monitor_filtrado[
                                mascara_tecnico_asignado(df_monitor_filtrado['TECNICO'])
                            ]['TECNICO'].unique()
                            
                            for tec in tecs_con_asignacion:
                                tec_norm = normalizar_nombre_cruce(tec)
                                if tec_norm not in tecnicos_en_gantt_hoy:
                                    continue
                                if tecnicos_validos_alertas and tec_norm not in tecnicos_validos_alertas:
                                    continue
                                    
                                df_tec_hoy = df_monitor_filtrado[df_monitor_filtrado['TECNICO'] == tec]
                                ordenes_iniciadas_hoy = df_tec_hoy[
                                    df_tec_hoy['HORA_INI'].notna() & 
                                    (df_tec_hoy['HORA_INI'].dt.date == hoy_date_valor)
                                ]
                                if ordenes_iniciadas_hoy.empty:
                                    alertas_9am.append(tec)
                                    primera_orden_por_tec[tec] = None
                                else:
                                    primera_ini_tec = ordenes_iniciadas_hoy['HORA_INI'].min()
                                    primera_ini_tec_naive = primera_ini_tec.replace(tzinfo=None) if hasattr(primera_ini_tec, 'tzinfo') and primera_ini_tec.tzinfo is not None else primera_ini_tec
                                    if primera_ini_tec_naive > limite_9am:
                                        alertas_9am.append(tec)
                                        primera_orden_por_tec[tec] = primera_ini_tec_naive
                                    

                        # 2. Validación de Tiempos Muertos e Inactividad (> 30 Minutos)
                        df_jornada_hoy = df_monitor_filtrado[
                            ((df_monitor_filtrado['HORA_INI'].dt.date == hoy_date_valor) | 
                             (df_monitor_filtrado['HORA_LIQ'].dt.date == hoy_date_valor)) &
                            (df_monitor_filtrado['TECNICO'].notna()) &
                            (df_monitor_filtrado['TECNICO'].astype(str).str.strip() != '')
                        ].copy()
                        
                        if not df_jornada_hoy.empty:
                            for tec, group in df_jornada_hoy.groupby('TECNICO'):
                                tec_norm = normalizar_nombre_cruce(tec)
                                if tec_norm not in tecnicos_en_gantt_hoy:
                                    continue
                                if tecnicos_validos_alertas and tec_norm not in tecnicos_validos_alertas:
                                    continue
                                    
                                group_sorted = group.sort_values(by='HORA_INI')
                                
                                for i in range(len(group_sorted) - 1):
                                    task_actual = group_sorted.iloc[i]
                                    task_siguiente = group_sorted.iloc[i+1]
                                    
                                    liq_actual = task_actual.get('HORA_LIQ')
                                    ini_siguiente = task_siguiente.get('HORA_INI')
                                    
                                    if pd.notnull(liq_actual) and pd.notnull(ini_siguiente):
                                        liq_actual_naive = liq_actual.replace(tzinfo=None) if hasattr(liq_actual, 'tzinfo') and liq_actual.tzinfo is not None else liq_actual
                                        ini_siguiente_naive = ini_siguiente.replace(tzinfo=None) if hasattr(ini_siguiente, 'tzinfo') and ini_siguiente.tzinfo is not None else ini_siguiente
                                        
                                        gap_mins = (ini_siguiente_naive - liq_actual_naive).total_seconds() / 60

                                        alm_ini, alm_fin = _obtener_almuerzo_tec(tec)
                                        if alm_ini is not None and alm_fin is not None:
                                            solape_ini = max(liq_actual_naive, alm_ini)
                                            solape_fin = min(ini_siguiente_naive, alm_fin)
                                            if solape_fin > solape_ini:
                                                solape_mins = (solape_fin - solape_ini).total_seconds() / 60
                                                gap_mins = max(0, gap_mins - solape_mins)

                                        if gap_mins > 30:
                                            alertas_tiempo_muerto.append({
                                                "tipo": "historico",
                                                "tecnico": tec,
                                                "gap": int(gap_mins),
                                                "orden_prev": task_actual.get('NUM', 'N/D'),
                                                "orden_next": task_siguiente.get('NUM', 'N/D'),
                                                "hora_fin": liq_actual_naive.strftime('%H:%M')
                                            })
                                
                                tiene_orden_activa = not group[group['HORA_INI'].notnull() & group['HORA_LIQ'].isnull()].empty
                                if not tiene_orden_activa:
                                    ordenes_cerradas = group[group['HORA_LIQ'].notnull() & (group['HORA_LIQ'].dt.date == hoy_date_valor)]
                                    if not ordenes_cerradas.empty:
                                        ultima_cerrada = ordenes_cerradas.sort_values(by='HORA_LIQ').iloc[-1]
                                        liq_last = ultima_cerrada.get('HORA_LIQ')
                                        liq_last_naive = liq_last.replace(tzinfo=None) if hasattr(liq_last, 'tzinfo') and liq_last.tzinfo is not None else liq_last
                                        
                                        gap_vivo_mins = (ahora_local - liq_last_naive).total_seconds() / 60

                                        alm_ini_v, alm_fin_v = _obtener_almuerzo_tec(tec)
                                        if alm_ini_v is not None and alm_fin_v is not None:
                                            solape_ini_v = max(liq_last_naive, alm_ini_v)
                                            solape_fin_v = min(ahora_local, alm_fin_v)
                                            if solape_fin_v > solape_ini_v:
                                                solape_mins_v = (solape_fin_v - solape_ini_v).total_seconds() / 60
                                                gap_vivo_mins = max(0, gap_vivo_mins - solape_mins_v)

                                        if gap_vivo_mins > 30:
                                            alertas_tiempo_muerto.append({
                                                "tipo": "vivo",
                                                "tecnico": tec,
                                                "gap": int(gap_vivo_mins),
                                                "orden_prev": ultima_cerrada.get('NUM', 'N/D'),
                                                "hora_fin": liq_last_naive.strftime('%H:%M')
                                            })


                        with st.expander("📋 Detalle de Apertura Tardía", expanded=False):
                            # Solo técnicos que SÍ iniciaron su orden (pasadas las 9:00 AM).
                            # Se excluyen los que aún no tienen ninguna orden iniciada hoy.
                            filas_apertura = []
                            for tec in alertas_9am:
                                primera_ini = primera_orden_por_tec.get(tec)
                                if primera_ini is None:
                                    continue

                                atraso_min = max(0, int((primera_ini - limite_9am).total_seconds() / 60))
                                filas_apertura.append({
                                    "TÉCNICO": tec,
                                    "HORA DE INICIO": primera_ini.strftime('%H:%M'),
                                    "_atraso_min": atraso_min
                                })

                            if not filas_apertura:
                                st.success("🎉 Sin retrasos de apertura registrados hoy.")
                            else:
                                filas_apertura.sort(key=lambda f: f["_atraso_min"], reverse=True)
                                df_tabla_apertura = pd.DataFrame(filas_apertura).drop(columns=["_atraso_min"])
                                st.dataframe(
                                    df_tabla_apertura,
                                    use_container_width=True,
                                    hide_index=True
                                )

                        with st.expander("🕳️ Detalle de Tiempo Muerto Total de la Jornada", expanded=False):
                            filas_muerto = []
                            if not df_jornada_hoy.empty:
                                for tec, group in df_jornada_hoy.groupby('TECNICO'):
                                    tec_norm = normalizar_nombre_cruce(tec)
                                    if tec_norm not in tecnicos_en_gantt_hoy:
                                        continue
                                    if tecnicos_validos_alertas and tec_norm not in tecnicos_validos_alertas:
                                        continue

                                    group_sorted = group.sort_values(by='HORA_INI')
                                    ordenes_ini_hoy = group_sorted[
                                        group_sorted['HORA_INI'].notna() &
                                        (group_sorted['HORA_INI'].dt.date == hoy_date_valor)
                                    ]
                                    if ordenes_ini_hoy.empty:
                                        continue

                                    primera_orden_ini = ordenes_ini_hoy['HORA_INI'].min()
                                    primera_orden_ini_naive = primera_orden_ini.replace(tzinfo=None) if hasattr(primera_orden_ini, 'tzinfo') and primera_orden_ini.tzinfo is not None else primera_orden_ini

                                    tiene_orden_activa_tm = not ordenes_ini_hoy[
                                        ordenes_ini_hoy['HORA_INI'].notnull() & ordenes_ini_hoy['HORA_LIQ'].isnull()
                                    ].empty

                                    cerradas_hoy_tec = ordenes_ini_hoy[ordenes_ini_hoy['HORA_LIQ'].notnull()]
                                    ultima_actividad = cerradas_hoy_tec['HORA_LIQ'].max() if not cerradas_hoy_tec.empty else None

                                    # Punto de referencia para contar tiempo muerto: si el
                                    # técnico abrió su primera orden después de las 9:00 AM,
                                    # el tiempo muerto debe contar desde las 9:00 (no desde la
                                    # hora en que por fin abrió la orden). Si abrió a tiempo,
                                    # se sigue usando su hora real de inicio.
                                    referencia_inicio = min(primera_orden_ini_naive, limite_9am)

                                    referencia_fin = ahora_local
                                    tiempo_transcurrido_min = max(0.0, (referencia_fin - referencia_inicio).total_seconds() / 60)

                                    # Se fusionan los intervalos de trabajo antes de sumarlos.
                                    # Si dos órdenes se traslapan en el tiempo (ej. un bloque
                                    # corto de reasignación "INSEQUIPO" que cae dentro de otra
                                    # orden más larga), sumarlas por separado duplicaba minutos
                                    # que en realidad no eran tiempo muerto, pero tampoco eran
                                    # minutos de trabajo "nuevos".
                                    intervalos_trabajo = []
                                    for _, r_ord in ordenes_ini_hoy.iterrows():
                                        ini_r = r_ord.get('HORA_INI')
                                        liq_r = r_ord.get('HORA_LIQ')
                                        if pd.isnull(ini_r):
                                            continue

                                        ini_r_naive = ini_r.replace(tzinfo=None) if hasattr(ini_r, 'tzinfo') and ini_r.tzinfo is not None else ini_r

                                        if pd.notnull(liq_r):
                                            liq_r_naive = liq_r.replace(tzinfo=None) if hasattr(liq_r, 'tzinfo') and liq_r.tzinfo is not None else liq_r
                                        else:
                                            liq_r_naive = ahora_local

                                        if liq_r_naive > ini_r_naive:
                                            intervalos_trabajo.append((ini_r_naive, liq_r_naive))

                                    tiempo_trabajado_min = 0.0
                                    if intervalos_trabajo:
                                        intervalos_trabajo.sort(key=lambda x: x[0])
                                        cur_ini, cur_fin = intervalos_trabajo[0]
                                        for ini_i, fin_i in intervalos_trabajo[1:]:
                                            if ini_i <= cur_fin:
                                                cur_fin = max(cur_fin, fin_i)
                                            else:
                                                tiempo_trabajado_min += (cur_fin - cur_ini).total_seconds() / 60
                                                cur_ini, cur_fin = ini_i, fin_i
                                        tiempo_trabajado_min += (cur_fin - cur_ini).total_seconds() / 60

                                    tiempo_muerto_bruto = int(round(max(0.0, tiempo_transcurrido_min - tiempo_trabajado_min)))

                                    # Ya no se descuenta el almuerzo aquí: el técnico reporta su
                                    # hora de almuerzo y esta se agrega manualmente a la gráfica.
                                    # Si un técnico NO reporta su almuerzo, ese tramo debe
                                    # contar como tiempo muerto (no se le da el beneficio de la
                                    # duda). Se deja la variable en 0 para no tocar el resto del
                                    # cálculo ni la tabla de diagnóstico.
                                    descuento_almuerzo = 0

                                    tiempo_muerto_neto = max(0, tiempo_muerto_bruto - descuento_almuerzo)



                                    if tiene_orden_activa_tm:
                                        estado_actual = "🔧 En orden activa"
                                    elif ultima_actividad is not None:
                                        ultima_act_naive = ultima_actividad.replace(tzinfo=None) if hasattr(ultima_actividad, 'tzinfo') and ultima_actividad.tzinfo is not None else ultima_actividad
                                        estado_actual = f"💤 Libre desde {ultima_act_naive.strftime('%H:%M')}"
                                    else:
                                        estado_actual = "💤 Libre (sin cierres hoy)"

                                    filas_muerto.append({
                                        "TÉCNICO": tec,
                                        "TIEMPO MUERTO TOTAL": tiempo_muerto_neto,
                                        "_1RA ORDEN REAL": primera_orden_ini_naive.strftime('%H:%M'),
                                        "_REFERENCIA INICIO": referencia_inicio.strftime('%H:%M'),
                                        "_MIN TRANSCURRIDOS": int(round(tiempo_transcurrido_min)),
                                        "_MIN TRABAJADOS": int(round(tiempo_trabajado_min)),
                                        "_BRUTO": tiempo_muerto_bruto,
                                        "_DESCUENTO ALMUERZO": descuento_almuerzo
                                    })

                            if not filas_muerto:
                                st.success("🎉 Sin tiempo muerto registrado hoy.")
                            else:
                                filas_muerto.sort(key=lambda f: f["TIEMPO MUERTO TOTAL"], reverse=True)
                                total_equipo_muerto = sum(f["TIEMPO MUERTO TOTAL"] for f in filas_muerto)

                                df_tabla_muerto = pd.DataFrame(filas_muerto)[["TÉCNICO", "TIEMPO MUERTO TOTAL"]]
                                df_tabla_muerto["TIEMPO MUERTO TOTAL"] = df_tabla_muerto["TIEMPO MUERTO TOTAL"].apply(
                                    lambda m: f"{int(m) // 60}h {int(m) % 60}m"
                                )
                                st.dataframe(
                                    df_tabla_muerto,
                                    use_container_width=True,
                                    hide_index=True
                                )

                                horas_t, mins_t = divmod(total_equipo_muerto, 60)
                                st.metric("⏱️ Tiempo Muerto Neto Total del Equipo Hoy", f"{horas_t}h {mins_t}m")

                                # --- TABLA TEMPORAL DE DIAGNÓSTICO ---
                                # Muestra el desglose completo del cálculo para poder
                                # verificar cada número contra la gráfica. Se puede quitar
                                # una vez que confirmemos que los cálculos cuadran.
                                with st.expander("🔧 Diagnóstico (desglose del cálculo)", expanded=False):
                                    df_diag = pd.DataFrame(filas_muerto)
                                    df_diag = df_diag.rename(columns={
                                        "_1RA ORDEN REAL": "1ra Orden Real",
                                        "_REFERENCIA INICIO": "Referencia Inicio",
                                        "_MIN TRANSCURRIDOS": "Min. Transcurridos",
                                        "_MIN TRABAJADOS": "Min. Trabajados",
                                        "_BRUTO": "Bruto",
                                        "_DESCUENTO ALMUERZO": "Descuento Almuerzo"
                                    })
                                    st.dataframe(
                                        df_diag[["TÉCNICO", "1ra Orden Real", "Referencia Inicio", "Min. Transcurridos", "Min. Trabajados", "Bruto", "Descuento Almuerzo", "TIEMPO MUERTO TOTAL"]],
                                        use_container_width=True,
                                        hide_index=True
                                    )

            st.markdown("---")
            if st.session_state.get('config_ver_checkpoint', True):
                with st.expander("🎛️ PANEL DE CONTROL Y ANÁLISIS DETALLADO", expanded=True):
                    if 'st_btn_v_active' not in st.session_state or st.session_state.st_btn_v_active == "CONSOL": 
                        st.session_state.st_btn_v_active = "PENDIENTE"
                        
                    if es_movil:
                        st.write("Filtros:")
                        if st.button("⏳ ASIGNADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary", key="btn_panel_v_pend_mob"): 
                            st.session_state.st_btn_v_active = "PENDIENTE"; st.rerun()
                        col_m1, col_m2 = st.columns(2)
                        if col_m1.button("✅ CERRADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "C_HOY" else "secondary", key="btn_panel_v_cerr_mob"): 
                            st.session_state.st_btn_v_active = "C_HOY"; st.rerun()
                        if col_m2.button("❌ ANULADAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "A_HOY" else "secondary", key="btn_panel_v_anul_mob"): 
                            st.session_state.st_btn_v_active = "A_HOY"; st.rerun()
                    else:
                        col_bt1_v, col_bt2_v, col_bt3_v = st.columns(3)
                        if col_bt1_v.button("⏳ ASIGNADAS ACTIVAS", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "PENDIENTE" else "secondary", key="btn_panel_v_pend_desk"): 
                            st.session_state.st_btn_v_active = "PENDIENTE"; st.rerun()
                        if col_bt2_v.button("✅ CERRADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "C_HOY" else "secondary", key="btn_panel_v_cerr_desk"): 
                            st.session_state.st_btn_v_active = "C_HOY"; st.rerun()
                        if col_bt3_v.button("❌ ANULADAS HOY", use_container_width=True, type="primary" if st.session_state.st_btn_v_active == "A_HOY" else "secondary", key="btn_panel_v_anul_desk"): 
                            st.session_state.st_btn_v_active = "A_HOY"; st.rerun()

                    status_final_btn = st.session_state.st_btn_v_active

                    if check_ordenes_totales:
                        df_v_tabla_monitor = df_todas_pendientes_monitor 
                    else:
                        if status_final_btn == "PENDIENTE": 
                            if check_criticos_diamante:
                                df_v_tabla_monitor = df_todas_pendientes_monitor[df_todas_pendientes_monitor['ES_OFFLINE'] == True]
                            else:
                                df_v_tabla_monitor = df_solo_asignadas_monitor
                        elif status_final_btn == "C_HOY": 
                            df_v_tabla_monitor = df_cerradas_hoy_monitor
                        else: 
                            df_v_tabla_monitor = df_monitor_filtrado[(df_monitor_filtrado['ESTADO'].astype(str).str.contains('ANULADA', na=False, case=False)) & ((df_monitor_filtrado['HORA_LIQ'] - pd.Timedelta(hours=6)).dt.date == hoy_date_valor) & (df_monitor_filtrado['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(ACTIVIDADES_GANTT_PERMITIDAS))]
                        

                    t_panel_v, t_graphs_v, t_analitica_v = st.tabs(["📋 PANEL OPERATIVO", "📊 PRODUCTIVIDAD", "📈 ANALÍTICA"])
            
                    with t_panel_v:
                        if not df_v_tabla_monitor.empty:
                            if es_movil:
                                st.markdown("<br>", unsafe_allow_html=True)
                                for idx, row in df_v_tabla_monitor.iterrows():
                                    color_borde = "#EF4444" if row.get('ES_OFFLINE') else ("#F59E0B" if row.get('ALERTA_TIEMPO') else "#3B82F6")
                                    estado_txt = str(row.get('ESTADO', 'N/D')).upper()
                                    bg_estado = "#10B981" if estado_txt == "CERRADA" else ("#d32f2f" if estado_txt == "ANULADA" else "#2D3748")
                            
                                    # El link de ubicación GPS solo debe mostrarse cuando el
                                    # técnico YA abrió (inició) la orden, es decir, cuando
                                    # HORA_INI tiene un valor real. Antes de eso no hay una
                                    # ubicación GPS asociada a un trabajo en curso.
                                    # Se utiliza target="_self" para forzar la apertura directa en la app de mapas (Google Maps, Waze, etc.)
                                    # evitando los bloqueos de ventanas emergentes en navegadores de celular.
                                    hora_ini_row_gps = row.get('HORA_INI')
                                    orden_ya_abierta_gps = pd.notnull(hora_ini_row_gps) and str(hora_ini_row_gps).strip() not in ("", "---", "NaT", "None")
                                    show_gps_mobile = row.get('GPS') if orden_ya_abierta_gps else None
                                    gps_link_html = f'<br>📍 <a href="{row.get("GPS")}" target="_self" style="color: #3B82F6; font-weight: bold; text-decoration: none;">UBICACIÓN GPS ↗</a>' if show_gps_mobile else ""
                            
                                    st.markdown(f"""
                                    <div style="background-color: #1A1D24; padding: 15px; border-radius: 12px; margin-bottom: 12px; border-left: 5px solid {color_borde}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                            <span style="color: white; font-weight: bold; font-size: 16px;">ORD-{row.get('NUM', 'N/D')}</span>
                                            <span style="background: {bg_estado}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: bold;">{estado_txt}</span>
                                        </div>
                                        <div style="color: #94A3B8; font-size: 13px; margin-bottom: 8px; line-height: 1.4;">
                                            👤 <b>{str(row.get('NOMBRE', 'N/D'))[:25]}</b> <br>
                                            📍 {str(row.get('COLONIA', 'N/D'))[:30]}
                                            {gps_link_html}
                                        </div>
                                        <div style="color: #E2E8F0; font-size: 12px; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                                            🛠️ {str(row.get('ACTIVIDAD', ''))} <br>
                                            👨‍🔧 {str(row.get('TECNICO', ''))[:20]}
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                            
                                    if st.button(f"👁️ Ver Detalle de Orden {row.get('NUM')}", key=f"btn_mobile_{row.get('NUM')}_{idx}", use_container_width=True):
                                        mostrar_comentario_cierre(row)
                                    st.markdown("<hr style='margin-top: 5px; margin-bottom: 15px; border-color: #2D2F39;'>", unsafe_allow_html=True)
                            else:
                                df_estilo_v, row_styler = aplicar_estilos_df(df_v_tabla_monitor)
                        
                                # === CONTROL DE COLUMNA GPS ===
                                # El link de ubicación GPS solo debe mostrarse cuando el
                                # técnico YA abrió (inició) la orden, es decir, cuando
                                # HORA_INI tiene un valor real (no "---"/vacío). Antes de
                                # eso no existe una ubicación asociada a un trabajo en curso.
                                if "GPS" in df_v_tabla_monitor.columns:
                                    if "HORA_INI" in df_v_tabla_monitor.columns:
                                        mask_orden_abierta_gps = df_v_tabla_monitor["HORA_INI"].notna()
                                        df_estilo_v["GPS"] = df_v_tabla_monitor["GPS"].where(mask_orden_abierta_gps, "").fillna("")
                                    else:
                                        df_estilo_v["GPS"] = df_v_tabla_monitor["GPS"].fillna("")
                            
                                    cols = list(df_estilo_v.columns)
                                    if "GPS" in cols:
                                        cols.remove("GPS")
                                    if "COLONIA" in cols:
                                        idx_colonia = cols.index("COLONIA")
                                        cols.insert(idx_colonia, "GPS")
                                    else:
                                        cols.append("GPS")
                                    df_estilo_v = df_estilo_v[cols]
                        
                                evento_monitor_diam = st.dataframe(
                                    df_estilo_v.style.apply(row_styler, axis=1),
                                    column_config={
                                        "GPS": st.column_config.LinkColumn("UBICACIÓN GPS", display_text="🔍 Ver"),
                                        "NOMBRE": st.column_config.TextColumn("NOMBRE", width="medium"),
                                        "COLONIA": st.column_config.TextColumn("COLONIA", width="medium"),
                                        "COMENTARIO": st.column_config.TextColumn("COMENTARIO", width="large"),
                                        "ES_OFFLINE": st.column_config.CheckboxColumn("🔴 OFFLINE"),
                                        "MINUTOS_CALC": None
                                    }, 
                                    use_container_width=True, 
                                    height=600, 
                                    hide_index=True, 
                                    on_select="rerun", 
                                    key="table_visual_monitor_desktop"
                                )
                        
                                if evento_monitor_diam.selection.rows:
                                    mostrar_comentario_cierre(df_v_tabla_monitor.iloc[evento_monitor_diam.selection.rows[0]])
                        else:
                            st.warning("No hay registros disponibles para mostrar.")

                    with t_graphs_v:
                        st.subheader("📈 Órdenes Cerradas por Hora (Hoy)")
            
                        df_graficas = df_base.copy()
                        df_graficas['HORA_LIQ_LOCAL'] = df_graficas['HORA_LIQ'] - pd.Timedelta(hours=6)
            
                        df_productividad_v = df_graficas[df_graficas['HORA_LIQ_LOCAL'].dt.date == hoy_date_valor].copy()
            
                        if not df_productividad_v.empty:
                            df_productividad_v['Hr_C'] = df_productividad_v['HORA_LIQ_LOCAL'].dt.hour
                            conteo_horario_v = df_productividad_v.groupby('Hr_C').size().reset_index(name='Ord')
                    
                            conteo_horario_v['Hora_Format'] = conteo_horario_v['Hr_C'].apply(lambda x: f"{int(x):02d}:00")
                    
                            fig_barras_v = px.bar(
                                conteo_horario_v, x='Hora_Format', y='Ord', 
                                labels={'Hora_Format':'Hora del Día (Honduras)','Ord':'Cant. Cerradas'}, 
                                template="plotly_dark", height=300
                            )
                            st.plotly_chart(fig_barras_v, use_container_width=True)
                        else:
                            st.info("Sin datos de cierres para generar gráfico horario.")

                    with t_analitica_v:
                        st.markdown("### 📈 Análisis de Rendimiento Operativo")
                
                        if df_v_tabla_monitor.empty:
                            st.info("ℹ️ No hay datos disponibles para mostrar el análisis gráfico en este momento.")
                        else:
                            plt.style.use('dark_background')
                    
                            segmentos_conteo = df_v_tabla_monitor['SEGMENTO'].value_counts()
                            motivos_conteo = df_v_tabla_monitor['MOTIVO'].value_counts() if 'MOTIVO' in df_v_tabla_monitor.columns else pd.Series()
                    
                            if es_movil:
                                if not segmentos_conteo.empty:
                                    fig, ax = plt.subplots(figsize=(6, 4))
                                    segmentos_conteo.plot(kind='bar', ax=ax, color=['#3B82F6', '#10B981'])
                                    ax.set_title("Órdenes por Segmento")
                                    st.pyplot(fig)
                                else:
                                    st.caption("Sin datos de segmentos.")
                            else:
                                col_an1, col_an2 = st.columns(2)
                                with col_an1:
                                    if not segmentos_conteo.empty:
                                        fig, ax = plt.subplots(figsize=(6, 4))
                                        segmentos_conteo.plot(kind='bar', ax=ax, color=['#3B82F6', '#10B981'])
                                        ax.set_title("Órdenes por Segmento")
                                        st.pyplot(fig)
                                    else:
                                        st.caption("Sin datos de segmentos para graficar.")
                                
                                with col_an2:
                                    if not motivos_conteo.empty:
                                        fig, ax = plt.subplots(figsize=(6, 4))
                                        motivos_conteo.plot(kind='pie', autopct='%1.1f%%', ax=ax, cmap='viridis')
                                        ax.set_ylabel('')
                                        ax.set_title("Motivo / Diagnóstico")
                                        st.pyplot(fig)
                                    else:
                                        st.caption("Sin datos de diagnósticos para graficar.")

if __name__ == '__main__':
    if verificar_autenticacion():
        main()
    else:
        mostrar_pantalla_login()
