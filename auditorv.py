import streamlit as st
import pandas as pd
import re
import requests
import base64
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
    generar_pdf_telemetria_matriz
)

# --- IMPORTACIÓN DE HERRAMIENTAS GCS ---
try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write(""); st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad, tab_eficiencia, tab_checklist = st.tabs([
        "⏱️ Auditoría de Tiempos", 
        "🚀 Telemetría", 
        "⚖️ Eficiencia Total",
        "📝 Checklist Inspección" # NUEVA PESTAÑA AÑADIDA
    ])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_t1, col_t2 = st.columns([4, 1])
        with col_t2: 
            if st.button("🔄 Refrescar", key="ref_t"): 
                if 'df_gps_memoria' in st.session_state:
                    del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático"], horizontal=True)
        if tipo_reporte == "📅 Reporte Semanal Automático":
            st.info("💡 El sistema detectará automáticamente los días en el archivo o historial de la Nube para generar el resumen de la semana.")

        df_gps_crudo = None
        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando historial de la nube..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados de la nube correctamente.")
                    except Exception as e: st.error(f"❌ Error: {e}")
            else: st.error("❌ No se detectó conexión a Google Sheets.")
                
        st.divider()
        if not es_movil:
            st.markdown("### 📥 Ingreso Manual (Modo PC)")
            archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas (Tiempos)", type=['csv', 'xlsx', 'xls'], key="up_tiempos")
            if archivo_gps_tiempos:
                with st.spinner("Subiendo a la Nube..."):
                    try:
                        df_gps_crudo = read_file_robust(archivo_gps_tiempos)
                        if conn:
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                            st.success("☁️ ¡Datos subidos exitosamente!")
                    except Exception as e: st.error(f"❌ Error al subir: {e}")
        else: st.info("📱 El ingreso manual está deshabilitado en móviles.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state: 
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            if tipo_reporte == "📊 Reporte Diario":
                with st.spinner("⚙️ Procesando tiempos diarios..."):
                    res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                if res_t is not None:
                    st.success("✅ Análisis Diario completado.")
                    st.dataframe(res_t, use_container_width=True, hide_index=True)
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), f"Auditoria_Tiempos_Diario.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.error(f"❌ Error: {msg}")
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y procesando consolidado semanal..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.success(f"✅ Análisis Semanal completado (Del {f_in.strftime('%d/%m/%Y')} al {f_out.strftime('%d/%m/%Y')}).")
                    
                    st.markdown("#### 📅 Desglose Diario por Vehículo")
                    st.dataframe(res_diario, use_container_width=True, hide_index=True)
                    
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), f"Auditoria_Tiempos_Semanal.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.warning(f"⚠️ {msg_sem}")

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_v1, col_v2 = st.columns([4, 1])
        with col_v2: 
            if st.button("🔄 Refrescar", key="ref_v"): st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        st.caption("El sistema creará la columna Promedio y depurará a quienes no tengan incidencias reales.")
        limite_vel = st.number_input("Promediar solo velocidades mayores a (km/h):", min_value=10, max_value=200, value=60, step=5)
        
        if not es_movil:
            archivos_telemetria = st.file_uploader("Arrastra aquí TODOS los archivos Excel/CSV juntos", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_telemetria")
            
            if archivos_telemetria:
                with st.spinner("Analizando y cruzando matrices con escáner profundo..."):
                    archivo_principal = next((f for f in archivos_telemetria if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    archivos_detallados = [f for f in archivos_telemetria if f != archivo_principal]
                            
                    if not archivo_principal:
                        st.error("❌ Sube el archivo 'Informe_Estadistico'.")
                    else:
                        try:
                            df_raw_tel = read_file_robust(archivo_principal)
                            df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                            
                            if df_matriz is not None:
                                dict_promedios = {}
                                col_placa_matriz = df_matriz.columns[0]
                                placas_validas = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper().unique()
                                
                                if archivos_detallados:
                                    for file_det in archivos_detallados:
                                        try:
                                            file_det.seek(0)
                                            raw_text = file_det.getvalue().decode('utf-8', errors='ignore').upper()
                                            if len(raw_text) < 100: raw_text = file_det.getvalue().decode('latin1', errors='ignore').upper()
                                            
                                            placa_encontrada = None
                                            for p in placas_validas:
                                                if str(p) in raw_text or str(p) in file_det.name.upper():
                                                    placa_encontrada = str(p); break
                                            
                                            if not placa_encontrada: continue 
                                            
                                            df_d = read_file_robust(file_det)
                                            header_idx = None
                                            for i in range(min(20, len(df_d))):
                                                row_str = " ".join([str(x) for x in df_d.iloc[i].values]).upper()
                                                if 'VELOCIDAD' in row_str or 'KM/H' in row_str:
                                                    header_idx = i; break
                                            
                                            if header_idx is not None:
                                                df_d.columns = [str(x).strip().upper() for x in df_d.iloc[header_idx].values]
                                                from tools import forzar_columnas_unicas
                                                df_d = forzar_columnas_unicas(df_d) 
                                                df_d = df_d.iloc[header_idx + 1:]
                                                
                                                col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|KM/H|SPEED', str(c), re.I)), None)
                                                if col_vel:
                                                    df_d['Vel_Num'] = df_d[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                                    df_excesos = df_d[df_d['Vel_Num'] > limite_vel]
                                                    if not df_excesos.empty:
                                                        dict_promedios[placa_encontrada] = round(df_excesos['Vel_Num'].mean(), 2)
                                        except Exception: pass
                                            
                                df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                                df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios).fillna("-")
                                df_matriz = df_matriz.drop(columns=['Placa_Match'])

                                if archivos_detallados:
                                    df_matriz = df_matriz[df_matriz['Promedio Vel. (km/h)'] != "-"]

                                if df_matriz.empty: 
                                    st.success("✅ La matriz quedó vacía tras la depuración. Ningún vehículo infractor cruzó datos con los archivos detallados.")
                                else:
                                    st.warning(f"⚠️ Se muestran {len(df_matriz)} vehículos en la matriz de infractores.")
                                    
                                    cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)']]
                                    styled_df = df_matriz.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                        
                                    st.download_button(
                                        label="📥 Descargar Reporte Final (PDF)", 
                                        data=generar_pdf_telemetria_matriz(df_matriz, limite_vel), 
                                        file_name=f"Auditoria_Velocidades_{get_hn_time().strftime('%Y%m%d')}.pdf", 
                                        mime="application/pdf", 
                                        use_container_width=True, 
                                        type="primary"
                                    )
                            else: st.error(f"❌ Error matriz principal: {msg_tel}")
                        except Exception as e: st.error(f"❌ Error de procesamiento: {e}")
        else: st.info("📱 La carga masiva está reservada para PC.")

    # --- PESTAÑA 3: MÉTRICA DE EFICIENCIA TOTAL ---
    with tab_eficiencia:
        col_e1, col_e2 = st.columns([4, 1])
        with col_e2: 
            if st.button("🔄 Refrescar", key="ref_e"): st.rerun()
            
        st.markdown("### ⚖️ Cruce de Productividad vs Tiempos GPS")
        st.caption("Calcula el porcentaje real de tiempo que el técnico estuvo produciendo mientras estaba en la calle.")
        st.info("💡 Sube tu archivo de Actividades y tus reportes de GPS para cruzarlos instantáneamente.")
        
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            archivo_act = st.file_uploader("1️⃣ Sube 'rep_actividades' (Órdenes)", type=['csv', 'xlsx', 'xls'], key="up_act_efi")
        with col_up2:
            archivos_detallados = st.file_uploader("2️⃣ Sube 'DetencionDetallado' (GPS)", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_detallado")
            
        if st.button("🚀 Calcular Eficiencia", use_container_width=True, type="primary"):
            
            df_base_local = None
            if archivo_act:
                df_base_local = read_file_robust(archivo_act)
                if df_base_local is not None:
                    cols_upper = {c: str(c).upper() for c in df_base_local.columns}
                    col_liq = next((c for c, up in cols_upper.items() if 'LIQUIDADO' in up or 'CIERRE' in up), None)
                    col_ini = next((c for c, up in cols_upper.items() if 'INICIO' in up or 'ENTRADA' in up), None)
                    col_tec = next((c for c, up in cols_upper.items() if 'TECNICO' in up or 'TÉCNICO' in up or 'USER' in up), None)
                    col_est = next((c for c, up in cols_upper.items() if 'ESTADO' in up or 'STATUS' in up), None)
                    col_num = next((c for c, up in cols_upper.items() if 'NUM' in up or 'ORDEN' in up or 'ID' in up), None)

                    if col_liq and col_ini and col_tec and col_est and col_num:
                        df_base_local = df_base_local.rename(columns={col_liq: 'HORA_LIQ', col_ini: 'HORA_INI', col_tec: 'TECNICO', col_est: 'ESTADO', col_num: 'NUM'})
            elif 'df_base' in st.session_state and st.session_state.df_base is not None:
                df_base_local = st.session_state.df_base

            if df_base_local is None: 
                st.error("❌ Faltan los datos de Actividades. Sube el archivo 'rep_actividades' en la caja 1.")
            elif not archivos_detallados:
                st.warning("⚠️ Sube al menos un archivo 'DetencionDetallado' del GPS en la caja 2.")
            else:
                with st.spinner("🧠 Procesando Inteligencia..."):
                    try:
                        df_gps_list = []
                        dict_ralenti_secs = {}
                        for file_det in archivos_detallados:
                            df_temp = read_file_robust(file_det)
                            if df_temp is not None and not df_temp.empty:
                                col_placa_temp = next((c for c in df_temp.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
                                if not col_placa_temp:
                                    for i in range(min(15, len(df_temp))):
                                        row_str = " ".join([str(x) for x in df_temp.iloc[i].values]).upper()
                                        if 'PLACA' in row_str or 'VEHICULO' in row_str or 'ALIAS' in row_str:
                                            df_temp.columns = [str(x).strip() for x in df_temp.iloc[i].values]
                                            from tools import forzar_columnas_unicas
                                            df_temp = forzar_columnas_unicas(df_temp)
                                            df_temp = df_temp.iloc[i+1:].reset_index(drop=True)
                                            break
                                df_gps_list.append(df_temp)
                                
                            file_det.seek(0)
                            lineas = file_det.getvalue().decode('utf-8', errors='ignore').splitlines()
                            if len(lineas) < 5: 
                                file_det.seek(0)
                                lineas = file_det.getvalue().decode('latin1', errors='ignore').splitlines()
                            for linea in lineas:
                                if "Tiempo de detencion con motor encendido" in linea:
                                    m = re.search(r'Placa:?\s*(.*?)(?:",|$)', linea)
                                    if m:
                                        p = m.group(1).replace('"', '').strip()
                                        t = linea.split(',')[-1].strip()
                                        if not t: t = linea.split(',')[-2].strip()
                                        dict_ralenti_secs[p] = dict_ralenti_secs.get(p, 0) + time_to_sec_robust(t)
                        
                        if df_gps_list:
                            res_diario, res_gps, msg_gps, f_in, f_out = procesar_auditoria_semanal(pd.concat(df_gps_list, ignore_index=True))
                            if res_gps is not None:
                                df_act = df_base_local.copy()
                                df_act['HORA_LIQ'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
                                df_act['HORA_INI'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
                                
                                df_act['Fecha_Ord'] = df_act['HORA_LIQ'].dt.date
                                df_act = df_act.dropna(subset=['Fecha_Ord'])
                                df_act = df_act[df_act['ESTADO'].astype(str).str.upper().str.contains('CERRADA', na=False)]
                                
                                df_act['Segundos_Prod'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds().clip(lower=0)
                                resumen_prod = df_act.groupby('TECNICO').agg(Ordenes=('NUM', 'count'), Seg_Prod=('Segundos_Prod', 'sum')).reset_index()
                                
                                def time_to_sec(t):
                                    parts = str(t).split(':')
                                    return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) if len(parts)==3 else 0
                                
                                res_gps['Seg_Calle'] = res_gps['Tiempo Total Semana'].apply(time_to_sec)
                                res_gps['Motor_Encendido_Secs'] = res_gps['Vehículo / Placa'].map(dict_ralenti_secs).fillna(0)
                                
                                def finding_placa(tec):
                                    if pd.isnull(tec): return None
                                    pt = str(tec).upper().replace(',', '').replace('.', '').split()
                                    required_matches = 2 if len(pt) >= 2 else 1
                                    
                                    for pl in res_gps['Vehículo / Placa']:
                                        pl_up = str(pl).upper()
                                        coincidencias = sum(1 for p in pt if len(p) > 2 and p in pl_up)
                                        if coincidencias >= required_matches: return pl
                                    return None
                                
                                resumen_prod['Placa_Match'] = resumen_prod['TECNICO'].apply(finding_placa)
                                df_final = pd.merge(resumen_prod, res_gps, left_on='Placa_Match', right_on='Vehículo / Placa', how='inner')
                                
                                if not df_final.empty:
                                    df_final['% Eficiencia'] = (df_final['Seg_Prod'] / df_final['Seg_Calle'] * 100).fillna(0).clip(upper=100)
                                    
                                    def sec_to_human(s):
                                        h, r = divmod(int(s), 3600); m, _ = divmod(r, 60)
                                        return f"{h:02d}h {m:02d}m"

                                    df_final['Trabajo (Órdenes)'] = df_final['Seg_Prod'].apply(sec_to_human)
                                    df_final['En Calle (GPS)'] = df_final['Seg_Calle'].apply(sec_to_human)
                                    df_final['Motor Encendido'] = df_final['Motor_Encendido_Secs'].apply(sec_to_human)
                                    
                                    st.success(f"✅ Cruce completado. Mostrando eficiencia para {len(df_final)} técnicos.")
                                    st.dataframe(df_final[['TECNICO', 'Ordenes', 'Trabajo (Órdenes)', 'En Calle (GPS)', '% Eficiencia', 'Motor Encendido']].style.format({'% Eficiencia': "{:.1f}%"}).map(
                                        lambda x: 'background-color: #2ea043; color: white' if x >= 65 else ('background-color: #d32f2f; color: white' if x < 40 else ''), subset=['% Eficiencia']
                                    ), use_container_width=True, hide_index=True)
                                else:
                                    st.warning("⚠️ No se encontraron técnicos que coincidan entre el archivo de Actividades y las placas del GPS.")
                            else:
                                st.error(f"❌ Error al procesar datos del GPS: {msg_gps}")
                        else:
                            st.error("❌ No se detectaron datos válidos en los archivos GPS subidos.")
                    except Exception as e: st.error(f"❌ Error interno en el cruce: {e}")

    # ==========================================================================
    # --- PESTAÑA 4: CHECKLIST INSPECCIÓN VEHICULAR ---
    # ==========================================================================
    with tab_checklist:
        st.markdown("### 📋 Formulario de Inspección y Control de Flota")
        st.caption("Complete la evaluación física del vehículo para mantener el historial preventivo actualizado.")
        
        # Opciones estándar de evaluación
        opciones_eval = ["✅ Buen Estado", "⚠️ Requiere Atención", "❌ Dañado/Falta"]
        
        # Categorías estructuradas
        categorias_checklist = {
            "💧 1. Fluidos y Motor": [
                "Nivel de aceite de motor", "Nivel de aceite de transmisión",
                "Nivel de aceite diferencial", "Nivel de aceite hidráulico (Dirección)",
                "Líquido de frenos", "Nivel de refrigerante / agua", "Fugas visibles en motor"
            ],
            "⚙️ 2. Suspensión y Mecánica": [
                "Sistema de Dirección", "Suspensión general", "Bujes de tijera",
                "Hojas de resorte", "Frenos delanteros (fricciones/pastillas)", "Frenos traseros (zapatas/tambor)"
            ],
            "🚗 3. Exteriores y Llantas": [
                "Estado de llantas en uso (desgaste y presión)", "Llanta de repuesto",
                "Luces (Faros delanteros, traseros y vías)", "Estado de carrocería y espejos"
            ],
            "🧰 4. Equipamiento de Seguridad": [
                "Extintor de incendios", "Conos y mica/triángulo reflectivo", "Gata hidráulica y llave de rueda"
            ]
        }

        with st.form("form_inspeccion_vehicular"):
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                placa_vehiculo = st.text_input("🚗 Placa / Código del Vehículo:*", placeholder="Ej: HAA-1234")
            with col_info2:
                conductor = st.text_input("👤 Nombre del Conductor:*", placeholder="Nombre del técnico responsable")
            with col_info3:
                kilometraje = st.number_input("🛣️ Kilometraje Actual:", min_value=0, value=0, step=100)

            st.divider()
            
            # Generación dinámica de la matriz de checklist
            resultados_checklist = {}
            for cat, items in categorias_checklist.items():
                st.markdown(f"<h5 style='color:#1E3A8A;'>{cat}</h5>", unsafe_allow_html=True)
                for item in items:
                    resultados_checklist[item] = st.radio(f"**{item}**", opciones_eval, horizontal=True, key=f"chk_{item}")
                st.write("") # Espaciador
                
            st.divider()
            st.markdown("#### 📝 Observaciones y Evidencia")
            observaciones = st.text_area("Detalle aquí si encontró daños, rayones o piezas faltantes:", placeholder="Ej: Fricciones delanteras desgastadas, solicitar cambio pronto.")
            archivos_evidencia = st.file_uploader("📸 Subir Evidencia Fotográfica (Opcional):", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
            
            supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
            
            submit_inspeccion = st.form_submit_button("💾 GUARDAR INSPECCIÓN EN LA NUBE", type="primary", use_container_width=True)

            if submit_inspeccion:
                if not placa_vehiculo.strip() or not conductor.strip():
                    st.error("⚠️ Los campos de Placa y Conductor son obligatorios.")
                else:
                    try:
                        urls_fotos = []
                        if archivos_evidencia:
                            with st.spinner("Subiendo evidencia fotográfica al servidor..."):
                                for a in archivos_evidencia:
                                    res = requests.post(
                                        "https://freeimage.host/api/1/upload",
                                        data={
                                            "key": API_KEY_FREEIMAGE,
                                            "action": "upload",
                                            "source": base64.b64encode(a.getvalue()).decode('utf-8'),
                                            "format": "json"
                                        }
                                    )
                                    if res.status_code == 200:
                                        urls_fotos.append(res.json()["image"]["url"])
                        
                        with st.spinner("Compilando reporte y guardando en la Nube..."):
                            # Analizar resultados para generar un resumen rápido
                            conteo_alertas = sum(1 for v in resultados_checklist.values() if "Requiere Atención" in v)
                            conteo_danos = sum(1 for v in resultados_checklist.values() if "Dañado/Falta" in v)
                            
                            # Formatear el detalle completo como un JSON en string para no crear 20 columnas en el CSV
                            detalle_completo = " | ".join([f"{k}: {v.split(' ')[1]}" for k, v in resultados_checklist.items() if "Buen Estado" not in v])
                            if not detalle_completo: detalle_completo = "Todo en orden."

                            estado_general = "✅ ÓPTIMO"
                            if conteo_alertas > 0: estado_general = "⚠️ CON OBSERVACIONES"
                            if conteo_danos > 0: estado_general = "❌ CRÍTICO"

                            # Intentar leer historial existente
                            df_historial = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "inspecciones_flota.csv")
                            if df_historial is None or df_historial.empty:
                                try:
                                    df_historial = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Inspecciones_Flota", ttl=0)
                                except:
                                    df_historial = pd.DataFrame()
                                    
                            cols_inspeccion = ['FECHA_INSPECCION', 'PLACA', 'CONDUCTOR', 'KILOMETRAJE', 'ESTADO_GENERAL', 'ALERTAS', 'DANOS', 'DETALLES_FALLAS', 'OBSERVACIONES', 'URL_FOTOS', 'SUPERVISOR']
                            
                            nueva_fila = [
                                get_hn_time().strftime("%d/%m/%Y %H:%M:%S"),
                                placa_vehiculo.strip().upper(),
                                conductor.strip().upper(),
                                kilometraje,
                                estado_general,
                                conteo_alertas,
                                conteo_danos,
                                detalle_completo,
                                observaciones,
                                ", ".join(urls_fotos),
                                supervisor_actual
                            ]
                            nuevo_df = pd.DataFrame([nueva_fila], columns=cols_inspeccion)
                            
                            if df_historial is not None and not df_historial.empty:
                                if len(df_historial.columns) == len(cols_inspeccion):
                                    df_historial.columns = cols_inspeccion
                                else:
                                    # Forzar alineación si las columnas no coinciden por versiones viejas
                                    for c in cols_inspeccion:
                                        if c not in df_historial.columns: df_historial[c] = ""
                                    df_historial = df_historial[cols_inspeccion]
                                df_final = pd.concat([df_historial, nuevo_df], ignore_index=True)
                            else:
                                df_final = nuevo_df
                                
                            # Sobrescribir en GCS
                            sobrescribir_archivo_gcs(df_final, NOMBRE_BUCKET_SISTEMA, "inspecciones_flota.csv")
                            
                            # Actualizar en Sheets si hay conexión
                            if conn:
                                try:
                                    conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Inspecciones_Flota", data=df_final)
                                except Exception as e:
                                    st.warning(f"Guardado en GCS exitoso, pero falló el espejo en Sheets: {e}")

                        st.success(f"✅ ¡Inspección de {placa_vehiculo.upper()} guardada correctamente!")
                    except Exception as e:
                        st.error(f"❌ Error al intentar guardar la inspección: {e}")

        # --- TABLA DE HISTORIAL DE INSPECCIONES ---
        st.markdown("---")
        st.markdown("#### 📜 Historial Reciente de Flota")
        try:
            df_view_insp = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "inspecciones_flota.csv")
            if df_view_insp is None or df_view_insp.empty:
                if conn: df_view_insp = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Inspecciones_Flota", ttl=0)
            
            if df_view_insp is not None and not df_view_insp.empty:
                # Mostrar solo las columnas más relevantes para no saturar la vista
                df_mostrar_insp = df_view_insp[['FECHA_INSPECCION', 'PLACA', 'CONDUCTOR', 'ESTADO_GENERAL', 'DETALLES_FALLAS', 'OBSERVACIONES']].copy()
                st.dataframe(df_mostrar_insp.iloc[::-1], use_container_width=True, hide_index=True, height=250)
            else:
                st.info("Aún no hay inspecciones vehiculares registradas en la base de datos.")
        except Exception as e:
            st.warning("No se pudo cargar el historial de inspecciones en este momento.")
