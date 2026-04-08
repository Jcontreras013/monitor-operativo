import streamlit as st
import pandas as pd
from datetime import datetime
import re
import os

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
# LÓGICA DE EXCESOS Y TELEMETRÍA (ADAPTADO AL FORMATO MATRIZ DEL GPS)
# ==============================================================================
def procesar_matriz_telemetria(df_raw):
    try:
        # 1. Buscar dinámicamente la fila donde están los verdaderos encabezados (Ej: "Placas - Alias")
        header_idx = None
        for i in range(min(20, len(df_raw))): # Buscar en las primeras 20 filas
            val = str(df_raw.iloc[i, 0]).upper()
            if 'PLACA' in val or 'ALIAS' in val or 'VEHICULO' in val:
                header_idx = i
                break
                
        if header_idx is None:
            return None, "No se encontró la fila de encabezados (Placas - Alias) en el archivo."

        # 2. Reconstruir el DataFrame desde esa fila
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = df_raw.iloc[header_idx].astype(str).str.strip()
        
        col_placa = df.columns[0]
        
        # 3. Limpieza de basura del GPS
        df = df.dropna(subset=[col_placa])
        df = df[~df[col_placa].astype(str).str.contains('La versión de este equipo', case=False, na=False)]
        df = df[df[col_placa].astype(str).str.strip() != '']
        
        # 4. Rellenar nulos con 0 para la matriz numérica
        df = df.fillna(0)
        
        # Limpiar un poco los nombres de las placas por estética
        df[col_placa] = df[col_placa].astype(str).str.split('-').str[0].str.strip()

        return df, "OK"
    except Exception as e:
        return None, f"Error al limpiar la matriz: {str(e)}"

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

def generar_pdf_telemetria_matriz(df_matriz):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page('L') # PÁGINA EN HORIZONTAL PARA QUE QUEPAN LOS DÍAS
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 10, safestr(f" Auditoria de Telemetria e Infracciones Diarias - Generado: {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    if not df_matriz.empty:
        pdf.seccion_titulo("Matriz de Eventos por Vehiculo y Fecha")
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        
        num_cols = len(df_matriz.columns)
        # Calcular anchos: Col 1 y 2 más grandes, el resto (días) pequeños
        w_placa = 45
        w_opcion = 45
        w_restante = 270 - w_placa - w_opcion # 270mm aprox de ancho usable en Landscape
        w_dia = w_restante / (num_cols - 2) if num_cols > 2 else 0
        
        pdf.set_font("Helvetica", "B", 6)
        
        # Dibujar Encabezados
        for i, col in enumerate(df_matriz.columns):
            w = w_placa if i == 0 else (w_opcion if i == 1 else w_dia)
            pdf.cell(w, 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        # Dibujar Filas
        pdf.set_font("Helvetica", "", 6)
        for _, fila in df_matriz.iterrows():
            pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)
            
            for i, item in enumerate(fila):
                w = w_placa if i == 0 else (w_opcion if i == 1 else w_dia)
                valstr = str(item)
                
                # Si es número mayor a 0 en las columnas de días, poner en rojito
                if i > 1:
                    try:
                        num = float(valstr)
                        if num > 0:
                            pdf.set_fill_color(253, 230, 230)
                            pdf.set_text_color(180, 0, 0)
                        else:
                            pdf.set_fill_color(255, 255, 255)
                            pdf.set_text_color(0, 0, 0)
                            valstr = "-" # Más limpio a la vista que un cero
                    except:
                        pass
                
                pdf.cell(w, 5, safestr(valstr[:35]), border=1, align="C" if i > 1 else "L", fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, f"No hay datos estructurados para mostrar.", ln=True)
        
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

    tab_tiempos, tab_velocidad = st.tabs(["⏱️ Auditoría de Tiempos", "🚀 Telemetría (Eventos)"])

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
            archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas (Tiempos)", type=['csv', 'xlsx', 'xls'], key="up_tiempos")
            
            if archivo_gps_tiempos is not None:
                with st.spinner("🔍 Leyendo archivo y subiendo a la Nube..."):
                    try:
                        if archivo_gps_tiempos.name.endswith('.csv'): 
                            try:
                                df_gps_crudo = pd.read_csv(archivo_gps_tiempos, encoding='utf-8')
                            except UnicodeDecodeError:
                                archivo_gps_tiempos.seek(0)
                                df_gps_crudo = pd.read_csv(archivo_gps_tiempos, encoding='latin1')
                        elif archivo_gps_tiempos.name.endswith('.xls'):
                            df_gps_crudo = pd.read_excel(archivo_gps_tiempos) # Soporte .xls activado
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
    # PESTAÑA 2: TELEMETRÍA EVENTOS (El reporte tipo Matriz del GPS)
    # --------------------------------------------------------------------------
    with tab_velocidad:
        st.markdown("### 🚀 Análisis de Eventos (Matriz)")
        st.caption("Sube el archivo Excel que contiene el conteo de eventos por día (Aceleración, Frenado, Excesos).")
        
        if not es_movil:
            archivo_telemetria = st.file_uploader("Arrastra el reporte matriz de Eventos (.xls, .xlsx, .csv)", type=['csv', 'xlsx', 'xls'], key="up_telemetria")
            
            if archivo_telemetria is not None:
                with st.spinner("Analizando y limpiando matriz..."):
                    # Leer archivo evitando errores de formato
                    if archivo_telemetria.name.endswith('.csv'): 
                        try:
                            df_raw_tel = pd.read_csv(archivo_telemetria, encoding='utf-8', header=None)
                        except UnicodeDecodeError:
                            archivo_telemetria.seek(0)
                            df_raw_tel = pd.read_csv(archivo_telemetria, encoding='latin1', header=None)
                    else: 
                        df_raw_tel = pd.read_excel(archivo_telemetria, header=None)
                    
                    df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                
                if df_matriz is not None:
                    st.success("✅ Matriz depurada y estructurada correctamente.")
                    st.dataframe(df_matriz, hide_index=True, use_container_width=True)
                        
                    pdf_matriz_bytes = generar_pdf_telemetria_matriz(df_matriz)
                    st.download_button(
                        label="📥 Descargar Reporte Detallado (PDF)",
                        data=pdf_matriz_bytes,
                        file_name=f"Telemetria_Matriz_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                else:
                    st.error(f"❌ Error al procesar matriz: {msg_tel}")
        else:
            st.info("📱 La carga de archivos de telemetría está reservada para uso en computadora (Modo PC).")
