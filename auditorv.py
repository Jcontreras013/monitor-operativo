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
# LÓGICA DE AUDITORÍA DE VEHÍCULOS
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
# GENERADOR DE PDF DINÁMICO
# ==============================================================================
def generar_pdf_auditoria(df_resumen):
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
        # Encabezados
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        anchos = [85, 30, 30, 45]
        aligns = ["L", "C", "C", "C"]
        
        for i, col in enumerate(df_resumen.columns):
            pdf.cell(anchos[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        # Filas dinámicas
        pdf.set_font("Helvetica", "", 7)
        for _, fila in df_resumen.iterrows():
            for i, item in enumerate(fila):
                valstr = str(item)[:45]
                valclean = safestr(valstr)
                
                # Colores por defecto (blanco y negro)
                fillr, fillg, fillb = 255, 255, 255
                textr, textg, textb = 0, 0, 0
                
                # Reglas de colores dinámicos
                if "Sin Salida" in valstr or "Sin Ingreso" in valstr or "Revisar" in valstr or "---" in valstr:
                    fillr, fillg, fillb = 253, 230, 230 # Fondo rojizo
                    textr, textg, textb = 180, 0, 0     # Texto rojo
                elif i == 3 and "Sin" not in valstr and "Revisar" not in valstr:
                    fillr, fillg, fillb = 230, 245, 230 # Fondo verdoso
                    textr, textg, textb = 0, 100, 0     # Texto verde
                    
                pdf.set_fill_color(fillr, fillg, fillb)
                pdf.set_text_color(textr, textg, textb)
                pdf.cell(anchos[i], 5, valclean, border=1, align=aligns[i], fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos para mostrar.", ln=True)
        
    return finalizar_pdf(pdf)

# ==============================================================================
# PANTALLA VISUAL QUE SE LLAMARÁ DESDE APP.PY
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("") 
        st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Tiempos de Ruta (GPS)")
        st.caption("Consolida el tiempo real en calle de cada vehículo a partir del reporte crudo de Zonas/Rutas.")

    st.divider()

    # Variable para almacenar los datos crudos antes de procesarlos
    df_gps_crudo = None

    # --- 1. BOTÓN DE LA NUBE (Siempre visible para Móvil y PC) ---
    st.markdown("### ☁️ Sincronización")
    if st.button("☁️ Cargar desde la Nube (Auditoría)", use_container_width=True, type="primary"):
        if conn is not None:
            with st.spinner("📥 Descargando reporte de rutas desde Google Sheets..."):
                try:
                    # ATENCIÓN: worksheet="GPS" es el nombre de la pestaña en tu Excel. Cámbialo si se llama distinto.
                    df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="GPS", ttl=0)
                    if not df_descarga.empty:
                        st.session_state['df_gps_memoria'] = df_descarga
                        st.success("✅ Datos del GPS descargados de la nube correctamente.")
                    else:
                        st.warning("⚠️ La pestaña de GPS está vacía en la nube.")
                except Exception as e:
                    st.error(f"❌ Error al conectar con la pestaña del GPS en la nube: {e}")
        else:
            st.error("❌ No se detectó la conexión a Google Sheets.")
            
    st.divider()

    # --- 2. LÓGICA DE RESTRICCIÓN: MÓVIL vs PC ---
    if not es_movil:
        # ===== MODO PC: MUESTRA EL CARGADOR =====
        st.markdown("### 📥 Ingreso Manual (Modo PC)")
        archivo_gps = st.file_uploader("Arrastra aquí el archivo Excel o CSV generado por la plataforma de GPS", type=['csv', 'xlsx'])
        
        if archivo_gps is not None:
            with st.spinner("🔍 Leyendo archivo local..."):
                try:
                    if archivo_gps.name.endswith('.csv'): df_gps_crudo = pd.read_csv(archivo_gps)
                    else: df_gps_crudo = pd.read_excel(archivo_gps)
                    
                    # Limpiamos la memoria de la nube si el usuario decide subir un archivo manual
                    if 'df_gps_memoria' in st.session_state:
                        del st.session_state['df_gps_memoria']
                except Exception as e:
                    st.error(f"❌ Error crítico al leer el archivo local: {e}")
    else:
        # ===== MODO MÓVIL: OCULTA EL CARGADOR Y MUESTRA MENSAJE =====
        st.info("📱 **Modo Móvil Detectado:** El ingreso de datos manual en crudo está deshabilitado en teléfonos. Usa el botón de carga desde la nube superior.")

    # --- RECUPERAR DATOS DE LA NUBE SI EXISTEN Y NO SE SUBIÓ ARCHIVO MANUAL ---
    if df_gps_crudo is None and 'df_gps_memoria' in st.session_state:
        df_gps_crudo = st.session_state['df_gps_memoria']

    # --- 3. PROCESAMIENTO Y RESULTADOS ---
    if df_gps_crudo is not None:
        with st.spinner("⚙️ Procesando auditoría y calculando tiempos..."):
            df_resumen_gps, mensaje_error = procesar_auditoria_vehiculos(df_gps_crudo)
        
        if df_resumen_gps is not None:
            st.success("✅ ¡Análisis completado! Vehículos unificados y tiempos consolidados correctamente.")
            
            st.markdown("### 📊 Resultados de la Auditoría")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Vehículos Activos", len(df_resumen_gps))
            vehiculos_calle = len(df_resumen_gps[df_resumen_gps['Última Entrada'] == "---"])
            m2.metric("Vehículos Aún en Calle / Sin Cierre", vehiculos_calle)
            
            st.dataframe(df_resumen_gps, use_container_width=True, hide_index=True)
            
            csv_gps = df_resumen_gps.to_csv(index=False).encode('utf-8')
            pdf_bytes = generar_pdf_auditoria(df_resumen_gps)
            
            st.divider()
            st.markdown("### 📥 Exportar Información")
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.download_button(
                    label="🚀 Descargar Reporte (PDF)",
                    data=pdf_bytes,
                    file_name=f"Auditoria_Vehiculos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            with col_d2:
                st.download_button(
                    label="📥 Descargar Reporte (CSV)",
                    data=csv_gps,
                    file_name=f"Auditoria_Vehiculos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        else:
            st.error(f"❌ Ocurrió un error al procesar el formato: {mensaje_error}")
