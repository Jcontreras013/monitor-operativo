import streamlit as st
import pandas as pd
import re
import requests
import base64
import tempfile
import os
import io
from datetime import datetime, timedelta, timezone

from tools import (
    get_hn_time,
    read_file_robust,
    time_to_sec_robust,
    procesar_auditoria_vehiculos,
    procesar_auditoria_semanal,
    procesar_matriz_telemetria,
    generar_pdf_auditoria_tiempos,
    generar_pdf_semanal_tiempos,
    generar_pdf_telemetria_matriz,
    generar_pdf_mensual_tiempos
)

# --- IMPORTACIONES BLINDADAS ---
try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    DRIVE_DISPONIBLE = True
except ImportError:
    DRIVE_DISPONIBLE = False
    st.warning("⚠️ Faltan librerías de Google Drive. Ejecuta: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

# Configuración de Nube
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# =============================================================================
# FUNCIONES AUXILIARES PARA DRIVE (GUARDADO DE PDF)
# =============================================================================
@st.cache_resource(show_spinner=False)
def obtener_servicio_drive():
    try:
        credenciales = {
            "type": "service_account",
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"],
            "universe_domain": "googleapis.com"
        }
        scopes = ['https://www.googleapis.com/auth/drive.file']
        creds = service_account.Credentials.from_service_account_info(credenciales, scopes=scopes)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        return None

def subir_pdf_a_drive_auditoria(pdf_bytes, nombre_archivo):
    """
    Sube un archivo PDF a la carpeta de 'AUDITORIA Y REGISTRO FLOTA' (ID: 15j3nQeE6w31wJ2fB3V3R0LpZ3M_q5dO5).
    """
    servicio = obtener_servicio_drive()
    if not servicio: return None
    
    carpeta_id = "15j3nQeE6w31wJ2fB3V3R0LpZ3M_q5dO5"
    
    file_metadata = {
        'name': nombre_archivo,
        'parents': [carpeta_id]
    }
    
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
    
    try:
        archivo = servicio.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        # Otorgar permisos de lectura al archivo para que sea accesible vía link
        permiso = {
            'type': 'anyone',
            'role': 'reader',
        }
        servicio.permissions().create(fileId=archivo.get('id'), body=permiso).execute()
        
        return archivo.get('webViewLink')
    except Exception as e:
        return None

# ==============================================================================
# FUNCIONES PARA GOOGLE CLOUD STORAGE
# ==============================================================================
def forzar_actualizacion_flota(conn):
    try:
        df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
        if df is None or df.empty:
            df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
        st.session_state['df_flota_memoria'] = df
    except:
        pass

def obtener_datos_flota(conn):
    if 'df_flota_memoria' not in st.session_state:
        forzar_actualizacion_flota(conn)
    return st.session_state.get('df_flota_memoria', pd.DataFrame())

def subir_imagen_freeimage(image_bytes):
    try:
        res = requests.post(
            "https://freeimage.host/api/1/upload",
            data={
                "key": API_KEY_FREEIMAGE,
                "action": "upload",
                "source": base64.b64encode(image_bytes).decode('utf-8'),
                "format": "json"
            },
            timeout=10
        )
        if res.status_code == 200:
            return res.json()["image"]["url"]
    except: pass
    return ""

def procesar_imagenes_lote(archivos):
    urls = []
    if archivos:
        for a in archivos:
            url = subir_imagen_freeimage(a.getvalue())
            if url: urls.append(url)
    return ", ".join(urls)

# ==============================================================================
# MÓDULO PRINCIPAL: AUDITORÍA DE VEHÍCULOS
# ==============================================================================
def mostrar_auditoria(conn):
    st.markdown("<h2 style='text-align: center; color: #38BDF8;'>🚐 Auditoría y Gestión de Flota Vehicular</h2>", unsafe_allow_html=True)
    
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    tab1, tab2, tab3 = st.tabs(["⏱️ Auditoría Tiempos GPS", "🛠️ Matriz de Telemetría", "📸 Registro de Escáner y Fallas"])

    # ==========================================================================
    # PESTAÑA 1: AUDITORÍA DE TIEMPOS GPS (DIARIO / SEMANAL / MENSUAL)
    # ==========================================================================
    with tab1:
        st.markdown("### 📡 Carga de Reporte GPS Tiempos")
        st.info("Sube el archivo Excel generado por la plataforma GPS con el detalle de tiempos (Encendido, Ralentí, Movimiento, etc.).")
        
        c_gps1, c_gps2 = st.columns([3, 1])
        with c_gps1:
            file_gps = st.file_uploader("📂 Sube el Excel de Tiempos GPS", type=["xlsx", "xls"], key="up_gps_tiempos")
        with c_gps2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ Limpiar Archivo", use_container_width=True, key="clear_gps"):
                file_gps = None
                st.rerun()

        if file_gps is not None:
            with st.spinner("⏳ Analizando estructura del documento GPS..."):
                df_gps_crudo = read_file_robust(file_gps)
                
            if df_gps_crudo is None or df_gps_crudo.empty:
                st.error("❌ El archivo está vacío o no se pudo leer.")
                return

        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático", "🗓️ Reporte Mensual"], horizontal=True)
        if tipo_reporte == "📅 Reporte Semanal Automático":
            st.info("💡 El sistema detectará automáticamente los días en el archivo o historial de la Nube para generar el resumen de la semana.")
        elif tipo_reporte == "🗓️ Reporte Mensual":
            st.info("💡 El reporte mensual consolidará toda la data del mes para un informe ejecutivo, conciso y directo a los totales de flota.")
        
        if file_gps is not None:
            if tipo_reporte == "📊 Reporte Diario":
                with st.spinner("⚙️ Procesando tiempos diarios..."):
                    df_resumen, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                    
                    if df_resumen is not None:
                        st.success("✅ Análisis Diario completado.")
                        
                        col_k1, col_k2, col_k3 = st.columns(3)
                        with col_k1:
                            st.metric("👥 Técnicos Auditados", len(df_resumen))
                        with col_k2:
                            total_secs = 0
                            if 'Motor Encendido' in df_resumen.columns:
                                for val in df_resumen['Motor Encendido']:
                                    try: total_secs += time_to_sec_robust(val)
                                    except: pass
                            st.metric("⏱️ Total Horas Motor", f"{total_secs // 3600} hrs")
                        with col_k3:
                            total_sec_ral = 0
                            if 'Ralenti' in df_resumen.columns:
                                for val in df_resumen['Ralenti']:
                                    try: total_sec_ral += time_to_sec_robust(val)
                                    except: pass
                            st.metric("⛽ Total Horas Ralentí", f"{total_sec_ral // 3600} hrs")
                        
                        st.dataframe(df_resumen, use_container_width=True, hide_index=True)
                        
                        # --- Botones y Lógica de Guardado ---
                        col_pdf1, col_pdf2 = st.columns(2)
                        with col_pdf1:
                            if st.button("⚙️ Preparar PDF Oficial Diario", use_container_width=True):
                                with st.spinner("Generando documento..."):
                                    st.session_state['pdf_auditoria_diario'] = generar_pdf_auditoria_tiempos(df_resumen)
                            
                            if 'pdf_auditoria_diario' in st.session_state:
                                st.download_button(
                                    label="⬇️ Descargar Reporte PDF Diario",
                                    data=st.session_state['pdf_auditoria_diario'],
                                    file_name=f"Auditoria_Diaria_Tiempos_{get_hn_time().strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    use_container_width=True,
                                    type="primary"
                                )
                        
                        with col_pdf2:
                            if 'pdf_auditoria_diario' in st.session_state and DRIVE_DISPONIBLE:
                                if st.button("☁️ Respaldar Reporte en Nube Central", use_container_width=True, type="secondary"):
                                    with st.spinner("Subiendo reporte a carpeta central..."):
                                        nombre_file = f"Reporte_Tiempos_Diario_{get_hn_time().strftime('%Y%m%d_%H%M')}.pdf"
                                        link = subir_pdf_a_drive_auditoria(st.session_state['pdf_auditoria_diario'], nombre_file)
                                        if link:
                                            st.success("✅ Guardado en Nube.")
                                            st.markdown(f"[Ver en Drive]({link})")
                                        else:
                                            st.error("Error al subir a la nube.")
                                            
                    else:
                        st.warning(f"⚠️ {msg}")

            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y consolidando semana..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                    
                    if res_sem is not None:
                        st.success(f"✅ Análisis Semanal completado (Del {f_in.strftime('%d/%m/%Y')} al {f_out.strftime('%d/%m/%Y')}).")
                        
                        st.markdown("#### 📊 Consolidado Semanal por Técnico")
                        st.dataframe(res_sem, use_container_width=True, hide_index=True)
                        
                        try:
                            import plotly.express as px
                            if 'Distancia(km)' in res_sem.columns:
                                fig = px.bar(res_sem.sort_values('Distancia(km)', ascending=False), x='TECNICOS', y='Distancia(km)', title="Kilometraje Total Recorrido en la Semana")
                                st.plotly_chart(fig, use_container_width=True)
                        except: pass
                        
                        col_s1, col_s2 = st.columns(2)
                        with col_s1:
                            if st.button("⚙️ Preparar PDF Oficial Semanal", use_container_width=True):
                                with st.spinner("Estructurando resumen semanal..."):
                                    st.session_state['pdf_auditoria_semanal'] = generar_pdf_semanal_tiempos(res_sem, f_in, f_out)
                            
                            if 'pdf_auditoria_semanal' in st.session_state:
                                st.download_button(
                                    label="⬇️ Descargar Resumen Semanal PDF",
                                    data=st.session_state['pdf_auditoria_semanal'],
                                    file_name=f"Auditoria_Semanal_{f_in.strftime('%Y%m%d')}_al_{f_out.strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    use_container_width=True,
                                    type="primary"
                                )
                                
                        with col_s2:
                            if 'pdf_auditoria_semanal' in st.session_state and DRIVE_DISPONIBLE:
                                if st.button("☁️ Archivar Semana en Nube", use_container_width=True, type="secondary"):
                                    with st.spinner("Subiendo consolidado semanal a carpeta central..."):
                                        nombre_file = f"Resumen_Semanal_{f_in.strftime('%Y%m%d')}_{f_out.strftime('%Y%m%d')}.pdf"
                                        link = subir_pdf_a_drive_auditoria(st.session_state['pdf_auditoria_semanal'], nombre_file)
                                        if link:
                                            st.success("✅ Archivada semana en Nube.")
                                            st.markdown(f"[Ver Consolidado]({link})")
                                        else:
                                            st.error("Error al subir.")
                    else:
                        st.warning(f"⚠️ {msg_sem}")



            elif tipo_reporte == "🗓️ Reporte Mensual":
                with st.spinner("⚙️ Escaneando fechas y consolidando totales mensuales..."):
                    res_diario, res_men, msg_men, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                    
                    if res_men is not None:
                        st.success(f"✅ Análisis Mensual completado (Del {f_in.strftime('%d/%m/%Y')} al {f_out.strftime('%d/%m/%Y')}).")
                        
                        st.markdown("#### 📊 Consolidado Ejecutivo Mensual por Técnico")
                        
                        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                        with col_kpi1:
                            st.metric("👥 Técnicos Auditados", len(res_men))
                        with col_kpi2:
                            total_secs = 0
                            if 'Motor Encendido' in res_men.columns:
                                for val in res_men['Motor Encendido']:
                                    try: total_secs += time_to_sec_robust(val)
                                    except: pass
                            st.metric("⏱️ Total Horas Motor", f"{total_secs // 3600} hrs")
                        with col_kpi3:
                            total_sec_ral = 0
                            if 'Ralenti' in res_men.columns:
                                for val in res_men['Ralenti']:
                                    try: total_sec_ral += time_to_sec_robust(val)
                                    except: pass
                            st.metric("⛽ Total Horas Ralentí", f"{total_sec_ral // 3600} hrs")
                            
                        st.dataframe(res_men, use_container_width=True, hide_index=True)
                        
                        try:
                            import plotly.express as px
                            if 'Distancia(km)' in res_men.columns:
                                fig_men = px.bar(
                                    res_men.sort_values('Distancia(km)', ascending=False).head(15), 
                                    x='TECNICOS', 
                                    y='Distancia(km)', 
                                    title="Top 15 Técnicos con Mayor Distancia Recorrida en el Mes (km)", 
                                    template="plotly_dark", 
                                    color='Distancia(km)', 
                                    color_continuous_scale="Blues"
                                )
                                st.plotly_chart(fig_men, use_container_width=True)
                        except:
                            pass
                        
                        col_m1, col_m2 = st.columns(2)
                        with col_m1:
                            st.download_button(
                                label="🚀 Descargar Reporte Ejecutivo Mensual (PDF)", 
                                data=generar_pdf_mensual_tiempos(res_men, f_in, f_out), 
                                file_name=f"Auditoria_Mensual_{f_in.strftime('%Y%m')}.pdf", 
                                mime="application/pdf", 
                                use_container_width=True, 
                                type="primary"
                            )
                    else: 
                        st.warning(f"⚠️ {msg_men}")


    # ==========================================================================
    # PESTAÑA 2: MATRIZ DE TELEMETRÍA (EXCESOS Y KILOMETRAJE VIRTUAL)
    # ==========================================================================
    with tab2:
        st.markdown("### 🏎️ Evaluador de Telemetría (Excesos de Velocidad)")
        st.info("Sube el archivo Excel de Exceso de Velocidad.")
        
        c_tele1, c_tele2 = st.columns([3, 1])
        with c_tele1:
            file_tele = st.file_uploader("📂 Sube el Excel de Exceso Velocidad", type=["xlsx", "xls"], key="up_gps_tele")
        with c_tele2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ Limpiar Archivo", use_container_width=True, key="clear_tele"):
                file_tele = None
                st.rerun()

        if file_tele is not None:
            with st.spinner("⏳ Analizando infracciones y telemetría..."):
                df_tele_crudo = read_file_robust(file_tele)
            
            if df_tele_crudo is not None and not df_tele_crudo.empty:
                df_matriz, msg_tele = procesar_matriz_telemetria(df_tele_crudo)
                
                if df_matriz is not None:
                    st.success("✅ Matriz de Telemetría generada con éxito.")
                    
                    k1, k2 = st.columns(2)
                    with k1:
                        st.metric("🏎️ Total Infracciones Nivel Flota", df_matriz['Cantidad de Infracciones'].sum() if 'Cantidad de Infracciones' in df_matriz.columns else 0)
                    with k2:
                        top_inf = df_matriz.iloc[0]['TECNICOS'] if not df_matriz.empty else "N/A"
                        st.metric("🚨 Técnico Más Crítico", top_inf)
                        
                    st.dataframe(df_matriz, use_container_width=True, hide_index=True)
                    
                    try:
                        import plotly.express as px
                        if 'Cantidad de Infracciones' in df_matriz.columns:
                            fig2 = px.pie(df_matriz.head(10), names='TECNICOS', values='Cantidad de Infracciones', title="Top 10: Distribución de Excesos de Velocidad", hole=0.3)
                            st.plotly_chart(fig2, use_container_width=True)
                    except: pass
                    
                    col_pt1, col_pt2 = st.columns(2)
                    with col_pt1:
                        if st.button("⚙️ Preparar Matriz PDF", use_container_width=True):
                            with st.spinner("Construyendo matriz..."):
                                st.session_state['pdf_telemetria'] = generar_pdf_telemetria_matriz(df_matriz)
                                
                        if 'pdf_telemetria' in st.session_state:
                            st.download_button(
                                label="⬇️ Descargar Matriz PDF",
                                data=st.session_state['pdf_telemetria'],
                                file_name=f"Matriz_Telemetria_{get_hn_time().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                type="primary"
                            )
                            
                    with col_pt2:
                        if 'pdf_telemetria' in st.session_state and DRIVE_DISPONIBLE:
                            if st.button("☁️ Reportar Matriz a Nube", use_container_width=True, type="secondary", key="btn_nube_tele"):
                                with st.spinner("Subiendo matriz de seguridad vial a carpeta central..."):
                                    nombre_file = f"Telemetria_Excesos_{get_hn_time().strftime('%Y%m%d_%H%M')}.pdf"
                                    link = subir_pdf_a_drive_auditoria(st.session_state['pdf_telemetria'], nombre_file)
                                    if link:
                                        st.success("✅ Matriz respaldada.")
                                        st.markdown(f"[Ver Documento de Control]({link})")
                                    else:
                                        st.error("Error al subir la matriz.")
                                        
                else:
                    st.warning(f"⚠️ {msg_tele}")
            else:
                st.error("❌ Archivo de telemetría inválido o vacío.")


    # ==========================================================================
    # PESTAÑA 3: REGISTRO DE ESCÁNER Y GESTIÓN DE FALLAS
    # ==========================================================================
    with tab3:
        st.markdown("### 📸 Registro Manual de Escáner y Estado Vehicular")
        st.info("Utiliza este módulo para documentar revisiones físicas, escaneos OBD2 y evidencia fotográfica del estado del vehículo.")
        
        with st.expander("➕ CREAR NUEVO REGISTRO DE INSPECCIÓN", expanded=True):
            st.write(f"**Inspector / Supervisor responsable:** {supervisor_actual}")
            
            c_ins1, c_ins2 = st.columns(2)
            with c_ins1:
                try:
                    with open("personal_tecnico.txt", 'r', encoding='utf-8') as f:
                        lineas = f.readlines()
                    nombres = ["---"] + sorted(list(set([" ".join(linea.strip().split(',')[0].replace('\\t', ' ').split()).upper() for linea in lineas if linea.strip()])))
                except:
                    nombres = ["---", "TECNICO 1", "TECNICO 2"]
                    
                tecnico_sel = st.selectbox("👤 Conductor Asignado:", options=nombres, key="sel_cond_flota")
                
                placa = st.text_input("🔢 Número de Placa / Identificador del Vehículo:", placeholder="Ej: HAH 1234", key="txt_placa_flota").upper()
                kilometraje = st.number_input("📏 Kilometraje Actual:", min_value=0, step=100, key="num_km_flota")
                
                estado_general = st.selectbox("🚦 Estado General de Evaluación:", ["ÓPTIMO (Sin códigos)", "PRECAUCIÓN (Códigos menores)", "CRÍTICO (Requiere taller)", "EN TALLER / MANTENIMIENTO"], key="sel_estado_flota")
                
            with c_ins2:
                fecha_inspeccion = st.date_input("📅 Fecha de Inspección:", value=get_hn_time().date(), key="date_insp_flota")
                
                codigos_obd2 = st.text_input("💻 Códigos de Error (Si aplica):", placeholder="Ej: P0300, P0420 o N/A", key="txt_codigos_flota").upper()
                
                fotos_flota = st.file_uploader("🖼️ Adjuntar Evidencia (Fotos tablero, escáner, daños):", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="up_fotos_flota")
                
            notas_flota = st.text_area("📝 Notas o Recomendaciones del Inspector:", placeholder="Detalla los hallazgos de la revisión física y diagnóstica...", key="txt_notas_flota")
            
            if st.button("💾 REGISTRAR INSPECCIÓN EN LA NUBE", type="primary", use_container_width=True):
                if tecnico_sel == "---" or not placa or not notas_flota:
                    st.error("⚠️ El Conductor, la Placa y las Notas son campos obligatorios.")
                else:
                    with st.spinner("Subiendo evidencia y sincronizando base de datos..."):
                        urls_flota = procesar_imagenes_lote(fotos_flota)
                        
                        cols_flota = [
                            'FECHA_REGISTRO', 'FECHA_INSPECCION', 'CONDUCTOR', 'PLACA', 
                            'KILOMETRAJE', 'ESTADO_EVALUACION', 'CODIGOS_OBD2', 'NOTAS_INSPECTOR', 
                            'SUPERVISOR', 'EVIDENCIA_FOTOGRAFICA'
                        ]
                        
                        nueva_fila_flota = [
                            get_hn_time().strftime("%d/%m/%Y %H:%M:%S"),
                            fecha_inspeccion.strftime("%d/%m/%Y"),
                            tecnico_sel,
                            placa,
                            kilometraje,
                            estado_general,
                            codigos_obd2 if codigos_obd2 else "N/A",
                            notas_flota,
                            supervisor_actual,
                            urls_flota
                        ]
                        
                        df_actual = obtener_datos_flota(conn)
                        nuevo_df = pd.DataFrame([nueva_fila_flota], columns=cols_flota)
                        
                        if df_actual is not None and not df_actual.empty:
                            if len(df_actual.columns) > len(cols_flota):
                                df_actual = df_actual.iloc[:, :len(cols_flota)]
                            elif len(df_actual.columns) < len(cols_flota):
                                for i in range(len(cols_flota) - len(df_actual.columns)):
                                    df_actual[f"Extra_{i}"] = ""
                            df_actual.columns = cols_flota
                            df_final = pd.concat([df_actual, nuevo_df], ignore_index=True)
                        else:
                            df_final = nuevo_df
                            
                        # Guardar GCS y Sheets
                        sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                        try:
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_final)
                        except Exception as e:
                            st.warning(f"Guardado local/GCS exitoso, pero Sheets falló: {e}")
                            
                        st.success(f"✅ Inspección de {placa} registrada correctamente.")
                        forzar_actualizacion_flota(conn)
                        
                        # Limpiar inputs
                        claves_a_limpiar = ["sel_cond_flota", "txt_placa_flota", "num_km_flota", "sel_estado_flota", "txt_codigos_flota", "txt_notas_flota", "up_fotos_flota"]
                        for k in claves_a_limpiar:
                            if k in st.session_state: del st.session_state[k]
                            
                        st.rerun()

        st.markdown("---")
        st.subheader("📜 Historial de Inspecciones y Revisiones")
        
        try:
            df_view_insp = obtener_datos_flota(conn)
            if not df_view_insp.empty:
                df_view_insp = df_view_insp.iloc[::-1].reset_index(drop=True)
                
                c_fil1, c_fil2, c_fil3 = st.columns(3)
                with c_fil1:
                    filtro_placa = st.selectbox("🔍 Filtrar por Placa:", ["TODAS"] + sorted(list(set([str(p).upper() for p in df_view_insp['PLACA'] if pd.notna(p)]))))
                with c_fil2:
                    filtro_estado = st.selectbox("🚦 Filtrar por Estado:", ["TODOS"] + sorted(list(set([str(e) for e in df_view_insp['ESTADO_EVALUACION'] if pd.notna(e)]))))
                with c_fil3:
                    if st.button("🔄 Refrescar Historial", use_container_width=True):
                        forzar_actualizacion_flota(conn)
                        st.rerun()
                        
                df_mostrar = df_view_insp.copy()
                if filtro_placa != "TODAS":
                    df_mostrar = df_mostrar[df_mostrar['PLACA'].astype(str).str.upper() == filtro_placa]
                if filtro_estado != "TODOS":
                    df_mostrar = df_mostrar[df_mostrar['ESTADO_EVALUACION'].astype(str) == filtro_estado]
                    
                st.dataframe(df_mostrar[['FECHA_INSPECCION', 'CONDUCTOR', 'PLACA', 'ESTADO_EVALUACION', 'CODIGOS_OBD2']].head(50), use_container_width=True, hide_index=True)
                
                st.markdown("#### 🛠️ Gestión de Registros")
                opciones_gestion = ["--- Selecciona un registro para ver detalles ---"]
                dict_map = {}
                for idx, row in df_mostrar.iterrows():
                    lbl = f"{row.get('FECHA_INSPECCION','')} | {row.get('PLACA','')} | {row.get('CONDUCTOR','')} ({row.get('ESTADO_EVALUACION','')})"
                    opciones_gestion.append(lbl)
                    dict_map[lbl] = (idx, row)
                    
                registro_sel = st.selectbox("Seleccionar Inspección:", opciones_gestion, label_visibility="collapsed")
                
                if registro_sel != "--- Selecciona un registro para ver detalles ---":
                    idx, row = dict_map[registro_sel]
                    
                    color_alerta = "green"
                    if "CRÍTICO" in str(row.get('ESTADO_EVALUACION', '')): color_alerta = "red"
                    elif "PRECAUCIÓN" in str(row.get('ESTADO_EVALUACION', '')): color_alerta = "orange"
                    elif "TALLER" in str(row.get('ESTADO_EVALUACION', '')): color_alerta = "gray"
                    
                    st.markdown(f"<h3 style='color: {color_alerta};'>Inspección: {row.get('PLACA','')} - {row.get('CONDUCTOR','')}</h3>", unsafe_allow_html=True)
                    st.info(f"**📝 Notas del Inspector:**\n\n{row.get('NOTAS_INSPECTOR','')}")
                    
                    st.write(f"**🚦 Estado:** {row.get('ESTADO_EVALUACION','')} | **💻 Códigos OBD2:** {row.get('CODIGOS_OBD2','')}")
                    st.write(f"**📏 Kilometraje:** {row.get('KILOMETRAJE','')} km | **👤 Registrado por:** {row.get('SUPERVISOR','')} el {row.get('FECHA_REGISTRO','')}")
                    
                    fotos = str(row.get('EVIDENCIA_FOTOGRAFICA', '')).split(',')
                    validas = [u.strip() for u in fotos if u.strip().startswith('http')]
                    if validas:
                        st.markdown("#### 🖼️ Evidencias Adjuntas:")
                        cols_e = st.columns(len(validas))
                        for i, u in enumerate(validas):
                            with cols_e[i]:
                                st.image(u, use_container_width=True)
                                
                    if es_admin:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("🗑️ Eliminar esta inspección", type="primary"):
                            with st.spinner("Eliminando registro..."):
                                try:
                                    df_borrado = st.session_state.get('df_flota_memoria', None)
                                    if df_borrado is None or df_borrado.empty:
                                        df_borrado = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", ttl=0)
                                    
                                    if idx in df_borrado.index:
                                        df_borrado = df_borrado.drop(idx).reset_index(drop=True)
                                        sobrescribir_archivo_gcs(df_borrado, NOMBRE_BUCKET_SISTEMA, "registro_escaneres_flota.csv")
                                        if conn:
                                            try: conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Registro_Flota", data=df_borrado)
                                            except: pass
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                    
                    st.markdown("<hr style='margin: 0px; padding: 0px; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)
                    
                if len(df_view_insp) > 50:
                    st.caption("Mostrando los últimos 50 registros por motivos de rendimiento.")
                    
            else:
                st.info("Aún no hay escáneres vehiculares en la base de datos.")
        except Exception as e:
            st.warning("No se pudo cargar el registro en este momento.")
