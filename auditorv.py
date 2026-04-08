import streamlit as st
import pandas as pd
from datetime import datetime
import re

# Importar las herramientas de PDF que ya existen en tu sistema
try:
    from tools import ReporteGenerencialPDF, finalizar_pdf, safestr
except ImportError:
    st.error("⚠️ No se pudo importar tools.py. Asegúrate de que esté en la misma carpeta.")

# ==============================================================================
# LÓGICA DE AUDITORÍA DE VEHÍCULOS (TIEMPOS)
# ==============================================================================
def procesar_auditoria_vehiculos(df):
    try:
        cols_necesarias = ['Placa-Alias', 'Hora Ingreso', 'Hora Salida']
        if not all(col in df.columns for col in cols_necesarias):
            col_placa = next((c for c in df.columns if 'PLACA' in str(c).upper() or 'ALIAS' in str(c).upper() or 'VEHICULO' in str(c).upper()), None)
            col_ingreso = next((c for c in df.columns if 'INGRESO' in str(c).upper() or 'ENTRADA' in str(c).upper()), None)
            col_salida = next((c for c in df.columns if 'SALIDA' in str(c).upper()), None)
            
            if not (col_placa and col_ingreso and col_salida):
                return None, "El archivo no tiene el formato esperado. Faltan columnas de Placa, Ingreso o Salida."
            df = df.rename(columns={col_placa: 'Placa-Alias', col_ingreso: 'Hora Ingreso', col_salida: 'Hora Salida'})
        
        df['Placa-Alias'] = df['Placa-Alias'].astype(str).str.replace(r'\xa0', ' ', regex=True)
        df['Placa-Alias'] = df['Placa-Alias'].str.replace(r'\s+', ' ', regex=True).str.strip()
        df = df[~df['Placa-Alias'].isin(['nan', '--', 'Placa-Alias', 'None', ''])]
        
        df['Hora Ingreso'] = pd.to_datetime(df['Hora Ingreso'], errors='coerce')
        df['Hora Salida'] = pd.to_datetime(df['Hora Salida'], errors='coerce')
        
        resumen = df.groupby('Placa-Alias').agg(
            Primera_Salida=('Hora Salida', 'min'),
            Ultima_Entrada=('Hora Ingreso', 'max')
        ).reset_index()
        
        def calc_tiempo(row):
            if pd.isnull(row['Primera_Salida']): return "Sin Salida (No arrancó)"
            if pd.isnull(row['Ultima_Entrada']): return "Sin Ingreso (Falta cierre)"
            
            if row['Ultima_Entrada'] >= row['Primera_Salida']:
                diff = row['Ultima_Entrada'] - row['Primera_Salida']
                total_seconds = int(diff.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                return "Revisar (Entró antes de salir)"
                
        resumen['Tiempo Total Fuera'] = resumen.apply(calc_tiempo, axis=1)
        resumen['Primera_Salida'] = resumen['Primera_Salida'].dt.strftime('%I:%M:%S %p').fillna("---")
        resumen['Ultima_Entrada'] = resumen['Ultima_Entrada'].dt.strftime('%I:%M:%S %p').fillna("---")
        resumen.columns = ['Vehículo / Placa', 'Primera Salida', 'Última Entrada', 'Tiempo Real en Calle']
        
        return resumen, "OK"
    except Exception as e:
        return None, str(e)

# ==============================================================================
# LÓGICA DE EXCESOS DE VELOCIDAD
# ==============================================================================
def procesar_excesos_velocidad(df, limite_vel):
    try:
        # Búsqueda inteligente de columnas
        col_placa = next((c for c in df.columns if re.search(r'PLACA|ALIAS|VEHICULO|UNIDAD|NOMBRE', str(c), re.I)), None)
        col_vel = next((c for c in df.columns if re.search(r'VELOCIDAD|SPEED|KM/H|KMH', str(c), re.I)), None)
        col_fecha = next((c for c in df.columns if re.search(r'FECHA|HORA|TIME|DATE', str(c), re.I)), None)
        col_ubi = next((c for c in df.columns if re.search(r'UBICACION|DIRECCION|COORDENADA|POSICION', str(c), re.I)), None)

        if not col_placa or not col_vel:
            return None, None, "El archivo no contiene las columnas necesarias (Placa/Vehículo y Velocidad)."

        df = df.copy()
        
        # Limpieza de nombres
        df[col_placa] = df[col_placa].astype(str).str.replace(r'\xa0', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
        df = df[~df[col_placa].isin(['nan', '--', 'None', '', 'N/D'])]

        # Extracción de la velocidad pura
        df['Vel_Numerica'] = df[col_vel].astype(str).str.extract(r'(\d+\.?\d*)')[0].astype(float)

        # Filtrar excesos
        df_excesos = df[df['Vel_Numerica'] > limite_vel].copy()

        if df_excesos.empty:
            return pd.DataFrame(), pd.DataFrame(), "OK"

        # Formatear detalle
        df_excesos['Vehículo / Placa'] = df_excesos[col_placa]
        df_excesos['Velocidad (km/h)'] = df_excesos['Vel_Numerica']
        df_excesos['Fecha y Hora'] = df_excesos[col_fecha].astype(str) if col_fecha else "N/D"
        df_excesos['Ubicación'] = df_excesos[col_ubi].astype(str) if col_ubi else "N/D"

        detalle = df_excesos[['Vehículo / Placa', 'Velocidad (km/h)', 'Fecha y Hora', 'Ubicación']].sort_values(by='Velocidad (km/h)', ascending=False)

        # Crear resumen Top Infractores
        resumen = df_excesos.groupby('Vehículo / Placa').agg(
            Total_Excesos=('Vehículo / Placa', 'count'),
            Vel_Maxima=('Velocidad (km/h)', 'max')
        ).reset_index().sort_values(by='Total_Excesos', ascending=False)
        resumen.columns = ['Vehículo / Placa', 'Total de Infracciones', 'Velocidad Máxima Alcanzada']

        return resumen, detalle, "OK"
    except Exception as e:
        return None, None, str(e)

# ==============================================================================
# GENERADORES DE PDF
# ==============================================================================
def generar_pdf_auditoria_tiempos(df_resumen):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 10, safestr(f" Auditoria de Tiempos de Ruta (GPS) - Generado: {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Consolidado de Tiempos Reales en Calle")
    
    if not df_resumen.empty:
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        anchos = [85, 30, 30, 45]
        aligns = ["L", "C", "C", "C"]
        
        for i, col in enumerate(df_resumen.columns):
            pdf.cell(anchos[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 7)
        for _, fila in df_resumen.iterrows():
            for i, item in enumerate(fila):
                valstr = str(item)[:45]
                valclean = safestr(valstr)
                
                fillr, fillg, fillb = 255, 255, 255
                textr, textg, textb = 0, 0, 0
                
                if "Sin Salida" in valstr or "Sin Ingreso" in valstr or "Revisar" in valstr or "---" in valstr:
                    fillr, fillg, fillb = 253, 230, 230 
                    textr, textg, textb = 180, 0, 0     
                elif i == 3 and "Sin" not in valstr and "Revisar" not in valstr:
                    fillr, fillg, fillb = 230, 245, 230 
                    textr, textg, textb = 0, 100, 0     
                    
                pdf.set_fill_color(fillr, fillg, fillb)
                pdf.set_text_color(textr, textg, textb)
                pdf.cell(anchos[i], 5, valclean, border=1, align=aligns[i], fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos para mostrar.", ln=True)
        
    return finalizar_pdf(pdf)

def generar_pdf_velocidad(df_resumen, df_detalle, limite):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 10, safestr(f" Auditoria de Excesos de Velocidad (> {limite} km/h) - {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    if not df_resumen.empty:
        # Tabla Top Infractores
        pdf.seccion_titulo("Resumen: Top Vehiculos con Infracciones")
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        anchos_res = [80, 45, 45]
        
        for i, col in enumerate(df_resumen.columns):
            pdf.cell(anchos_res[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 7)
        for _, fila in df_resumen.iterrows():
            pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)
            
            # Resaltar en rojo si supera el límite por mucho (+20km/h)
            if fila['Velocidad Máxima Alcanzada'] >= limite + 20:
                pdf.set_text_color(200, 0, 0)
                
            pdf.cell(anchos_res[0], 5, safestr(str(fila[0])[:45]), border=1, align="L", fill=True)
            pdf.cell(anchos_res[1], 5, safestr(str(fila[1])), border=1, align="C", fill=True)
            pdf.cell(anchos_res[2], 5, safestr(f"{fila[2]:.1f} km/h"), border=1, align="C", fill=True)
            pdf.ln()
            
        pdf.ln(5)
        
        # Tabla Detalle
        pdf.seccion_titulo("Detalle Completo de Eventos de Exceso")
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        anchos_det = [50, 25, 35, 80]
        
        for i, col in enumerate(df_detalle.columns):
            pdf.cell(anchos_det[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(0, 0, 0)
        for _, fila in df_detalle.iterrows():
            pdf.cell(anchos_det[0], 5, safestr(str(fila[0])[:35]), border=1, align="L")
            pdf.cell(anchos_det[1], 5, safestr(f"{fila[1]:.1f}"), border=1, align="C")
            pdf.cell(anchos_det[2], 5, safestr(str(fila[2])[:20]), border=1, align="C")
            pdf.cell(anchos_det[3], 5, safestr(str(fila[3])[:65]), border=1, align="L")
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, f"Operacion Segura. No se detectaron velocidades mayores a {limite} km/h.", ln=True)
        
    return finalizar_pdf(pdf)

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("") 
        st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Excesos de Velocidad.")

    st.divider()

    # ==========================================================================
    # SEPARACIÓN EN DOS PESTAÑAS INDEPENDIENTES
    # ==========================================================================
    tab_tiempos, tab_velocidad = st.tabs(["⏱️ Auditoría de Tiempos", "🚀 Control de Velocidad"])

    # --------------------------------------------------------------------------
    # PESTAÑA 1: TIEMPOS (Conectado a la Nube)
    # --------------------------------------------------------------------------
    with tab_tiempos:
        df_gps_crudo = None

        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando reporte desde la pestaña 'Auditoria'..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados de la nube correctamente.")
                        else:
                            st.warning("⚠️ La pestaña 'Auditoria' está vacía en la nube.")
                    except Exception as e:
                        st.error(f"❌ Error al conectar con la pestaña 'Auditoria' en la nube: {e}")
            else:
                st.error("❌ No se detectó la conexión a Google Sheets.")
                
        st.divider()

        if not es_movil:
            st.markdown("### 📥 Ingreso Manual (Modo PC)")
            archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas", type=['csv', 'xlsx'], key="up_tiempos")
            
            if archivo_gps_tiempos is not None:
                with st.spinner("🔍 Leyendo archivo y subiendo a la Nube..."):
                    try:
                        # 🛡️ PROTECCIÓN DE CODIFICACIÓN (Evita el error utf-8 en CSVs con tildes/ñ)
                        if archivo_gps_tiempos.name.endswith('.csv'): 
                            try:
                                df_gps_crudo = pd.read_csv(archivo_gps_tiempos, encoding='utf-8')
                            except UnicodeDecodeError:
                                archivo_gps_tiempos.seek(0)
                                df_gps_crudo = pd.read_csv(archivo_gps_tiempos, encoding='latin1')
                        else: 
                            df_gps_crudo = pd.read_excel(archivo_gps_tiempos)
                        
                        if conn is not None:
                            st.toast("Subiendo datos a Google Sheets...")
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                            st.success("☁️ ¡Datos subidos a la Nube exitosamente!")
                        
                        if 'df_gps_memoria' in st.session_state:
                            del st.session_state['df_gps_memoria']
                            
                    except Exception as e:
                        st.error(f"❌ Error crítico al leer o subir: {e}")
        else:
            st.info("📱 El ingreso de datos manual está deshabilitado en teléfonos. Usa el botón de la nube.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state:
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            with st.spinner("⚙️ Procesando auditoría de tiempos..."):
                df_resumen_gps, mensaje_error = procesar_auditoria_vehiculos(df_gps_crudo)
            
            if df_resumen_gps is not None:
                st.success("✅ Análisis completado.")
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Vehículos Activos", len(df_resumen_gps))
                m2.metric("Vehículos en Calle / Sin Cierre", len(df_resumen_gps[df_resumen_gps['Última Entrada'] == "---"]))
                
                st.dataframe(df_resumen_gps, use_container_width=True, hide_index=True)
                
                pdf_bytes_tiempos = generar_pdf_auditoria_tiempos(df_resumen_gps)
                csv_gps = df_resumen_gps.to_csv(index=False).encode('utf-8')
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        label="🚀 Descargar Reporte (PDF)",
                        data=pdf_bytes_tiempos,
                        file_name=f"Auditoria_Tiempos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                with col_d2:
                    st.download_button(
                        label="📥 Descargar Reporte (CSV)",
                        data=csv_gps,
                        file_name=f"Auditoria_Tiempos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            else:
                st.error(f"❌ Error formato: {mensaje_error}")


    # --------------------------------------------------------------------------
    # PESTAÑA 2: EXCESOS DE VELOCIDAD (Independiente)
    # --------------------------------------------------------------------------
    with tab_velocidad:
        st.markdown("### 🚀 Análisis de Telemetría y Excesos")
        st.caption("Sube el archivo general del GPS. El sistema filtrará a los infractores.")
        
        limite_vel = st.number_input("Establecer límite de velocidad (km/h):", min_value=10, max_value=200, value=80, step=5)
        
        if not es_movil:
            archivo_vel = st.file_uploader("Arrastra el reporte de Velocidad/Telemetría", type=['csv', 'xlsx'], key="up_vel")
            
            if archivo_vel is not None:
                with st.spinner("Analizando velocidades..."):
                    # 🛡️ PROTECCIÓN DE CODIFICACIÓN PARA VELOCIDAD TAMBIÉN
                    if archivo_vel.name.endswith('.csv'): 
                        try:
                            df_vel_crudo = pd.read_csv(archivo_vel, encoding='utf-8')
                        except UnicodeDecodeError:
                            archivo_vel.seek(0)
                            df_vel_crudo = pd.read_csv(archivo_vel, encoding='latin1')
                    else: 
                        df_vel_crudo = pd.read_excel(archivo_vel)
                    
                    df_res_vel, df_det_vel, msg_vel = procesar_excesos_velocidad(df_vel_crudo, limite_vel)
                
                if df_res_vel is not None:
                    if df_res_vel.empty:
                        st.success(f"✅ **¡Excelente!** Operación Segura. No se registraron velocidades superiores a {limite_vel} km/h.")
                    else:
                        st.error(f"⚠️ Se detectaron {len(df_det_vel)} infracciones distribuidas en {len(df_res_vel)} vehículos.")
                        
                        col_v1, col_v2 = st.columns([1, 1.5])
                        with col_v1:
                            st.markdown("**🏆 Top Infractores**")
                            st.dataframe(df_res_vel, hide_index=True, use_container_width=True)
                        with col_v2:
                            st.markdown("**📍 Detalle de Eventos**")
                            st.dataframe(df_det_vel, hide_index=True, use_container_width=True)
                            
                        pdf_vel_bytes = generar_pdf_velocidad(df_res_vel, df_det_vel, limite_vel)
                        st.download_button(
                            label="📥 Descargar Reporte de Infracciones (PDF)",
                            data=pdf_vel_bytes,
                            file_name=f"Infracciones_Velocidad_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                else:
                    st.error(f"❌ Error al procesar velocidades: {msg_vel}")
        else:
            st.info("📱 La carga de archivos de telemetría está reservada para uso en computadora (Modo PC).")
