import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta
import io

def limpiar_nombre(raw):
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def extraer_tabla_limpia_pdf(archivo_pdf):
    """Extrae datos, asigna la primera fila como header y elimina lo vacío"""
    import pdfplumber
    todas_las_filas = []
    
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas:
                tabla_limpia = [[str(celda).replace('\n', ' ').strip() if celda else '' for celda in fila] for fila in tabla]
                todas_las_filas.extend(tabla_limpia)
                
    if not todas_las_filas:
        return pd.DataFrame()
        
    df = pd.DataFrame(todas_las_filas)
    
    # La fila 0 contiene los nombres reales de las columnas
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # Limpieza estricta de vacíos
    df = df.replace(r'^\s*$', pd.NA, regex=True)
    df = df.replace('None', pd.NA)
    df = df.replace('--', pd.NA) # Los guiones de tu PDF de ausencias
    
    df = df.dropna(how='all', axis=1) # Elimina columnas 100% vacías
    df = df.dropna(how='all', axis=0) # Elimina filas 100% vacías
    
    df = df.fillna('---')
    
    # Arreglar columnas duplicadas
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique(): 
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}_{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df.columns = cols
    
    return df

def generar_pdf_unificado_rrhh(df_ausencias, df_tardanzas):
    from fpdf import FPDF
    import tempfile
    import os
    import unicodedata
    
    def safestr(texto):
        if pd.isna(texto): return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
        
    pdf = FPDF('L', 'mm', 'A4') # Horizontal para que quepan tus columnas
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 12, "REPORTE UNIFICADO RRHH: CONTROL DE ASISTENCIA", ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Fecha de emision: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}", ln=True, align="C")
    pdf.ln(10)
    
    def dibujar_tabla(pdf_obj, df, titulo):
        pdf_obj.set_font("Helvetica", "B", 12)
        pdf_obj.set_text_color(40, 50, 100)
        pdf_obj.cell(0, 10, safestr(titulo), ln=True)
        
        if df.empty:
            pdf_obj.set_font("Helvetica", "I", 10)
            pdf_obj.set_text_color(150, 0, 0)
            pdf_obj.cell(0, 8, "No se registraron datos en esta categoria.", ln=True)
            pdf_obj.ln(5)
            return
            
        # Seleccionamos las columnas más importantes para que no se salga de la hoja
        cols_deseadas = ['Nombre completo', 'Departamento', 'Fecha', 'Horario', 'Hora de inicio del trabajo', 'Hora final del trabajo']
        cols_finales = [c for c in cols_deseadas if c in df.columns]
        
        # Si por alguna razón el PDF cambió, agarramos las primeras 6 disponibles
        if not cols_finales:
            cols_finales = list(df.columns)[:6]
            
        df_sub = df[cols_finales]
        
        pdf_obj.set_font("Helvetica", "B", 8)
        pdf_obj.set_fill_color(230, 235, 245)
        pdf_obj.set_text_color(0, 0, 0)
        
        ancho_total = 275 
        w = ancho_total / len(cols_finales)
        
        # Encabezados
        for col in cols_finales:
            pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
        pdf_obj.ln()
        
        # Filas
        pdf_obj.set_font("Helvetica", "", 7)
        for _, row in df_sub.iterrows():
            if pdf_obj.get_y() > 185:
                pdf_obj.add_page()
                pdf_obj.set_font("Helvetica", "B", 8)
                pdf_obj.set_fill_color(230, 235, 245)
                for col in cols_finales:
                    pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
                pdf_obj.ln()
                pdf_obj.set_font("Helvetica", "", 7)
                
            for col in cols_finales:
                pdf_obj.cell(w, 6, safestr(str(row[col]))[:40], border=1, align="C")
            pdf_obj.ln()
        pdf_obj.ln(12)
        
    dibujar_tabla(pdf, df_ausencias, "1. DETALLE DE AUSENCIAS")
    dibujar_tabla(pdf, df_tardanzas, "2. DETALLE DE LLEGADAS TARDE")
    
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdf.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

def vista_biometrico():
    st.title("🚨 Centro de Control Biométrico y RRHH")
    
    tab_transacciones, tab_rrhh = st.tabs(["⏱️ Auditoría Diaria (Transacciones)", "📊 Consolidado RRHH (PDFs)"])
    
    # =========================================================
    # PESTAÑA 1: AUDITORÍA ORIGINAL
    # =========================================================
    with tab_transacciones:
        st.caption("Detecta llegadas tarde (ej. a partir de las 08:06 AM exactas), almuerzos mayores a 1 hora y breaks mayores a 15 min.")
        if st.button("🔄 Reiniciar Turnos"):
            if 'memoria_turnos' in st.session_state:
                del st.session_state['memoria_turnos']
            st.success("Memoria borrada.")

        archivo = st.file_uploader("📥 Subir Archivo Transaction.pdf", type=['pdf'])
        if archivo:
            try:
                from PyPDF2 import PdfReader
                with st.spinner("🕵️‍♂️ Escaneando PDF y extrayendo marcas..."):
                    reader = PdfReader(archivo)
                    texto_completo = ""
                    for page in reader.pages:
                        texto_completo += page.extract_text() + "\n"
                        
                    patron = re.compile(r'([A-Za-z\sñÑáéíóúÁÉÍÓÚ\.]+)(\d{1,10})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})')
                    matches = patron.findall(texto_completo)
                    
                    if not matches:
                        st.error("❌ No se encontraron marcas válidas.")
                        return
                        
                    df = pd.DataFrame(matches, columns=['Name_Raw', 'ID', 'Date', 'Time'])
                    df['Name_Clean'] = df['Name_Raw'].apply(limpiar_nombre)
                    id_to_name = df.groupby('ID')['Name_Clean'].agg(lambda x: x.mode()[0] if not x.empty else 'Unknown').to_dict()
                    df['Full Name'] = df['ID'].map(id_to_name)
                    df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%d/%m/%Y %H:%M')
                    df = df.sort_values(['ID', 'Datetime'])
                    df['Time_Diff'] = df.groupby(['ID', 'Date'])['Datetime'].diff()
                    df = df[(df['Time_Diff'].isna()) | (df['Time_Diff'] > pd.Timedelta(minutes=15))].copy()
                    df['FECHA_SOLA'] = df['Datetime'].dt.date

                usuarios_unicos = df[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
                usuarios_unicos['Turno'] = "08:00 AM" 
                
                if 'memoria_turnos' in st.session_state:
                    previos = st.session_state['memoria_turnos']
                    usuarios_unicos = pd.merge(usuarios_unicos, previos[['ID', 'Turno']], on='ID', how='left', suffixes=('', '_y'))
                    usuarios_unicos['Turno'] = usuarios_unicos['Turno_y'].fillna("08:00 AM")
                    usuarios_unicos = usuarios_unicos.drop(columns=['Turno_y'], errors='ignore')
                    
                st.session_state['memoria_turnos'] = usuarios_unicos
                
                st.write("### 1️⃣ Asignar Turno de Entrada")
                opciones_turnos = ["07:00 AM", "08:00 AM", "09:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"]
                turnos_editados = st.data_editor(
                    st.session_state['memoria_turnos'],
                    column_config={"Turno": st.column_config.SelectboxColumn(options=opciones_turnos, required=True)},
                    disabled=['ID', 'Full Name'],
                    hide_index=True,
                    use_container_width=True
                )
                st.session_state['memoria_turnos'] = turnos_editados
                dict_turnos = dict(zip(turnos_editados['ID'], turnos_editados['Turno']))

                if st.button("🚀 Extraer Infractores", type="primary"):
                    resultados = []
                    for (uid, fecha), grupo in df.groupby(['ID', 'FECHA_SOLA']):
                        punches = grupo['Datetime'].tolist()
                        if not punches: continue
                        nombre = grupo['Full Name'].iloc[0]
                        turno_str = dict_turnos.get(uid, "08:00 AM")
                        
                        entrada = punches[0]
                        llegada_tarde = False
                        try:
                            dt_turno = datetime.strptime(turno_str, "%I:%M %p").time()
                            limite = datetime.combine(fecha, dt_turno) + timedelta(minutes=5, seconds=59)
                            if entrada > limite: llegada_tarde = True
                        except: pass
                            
                        almuerzo_exc, almuerzo_str = False, ""
                        break_exc, break_str = False, ""
                        
                        if len(punches) >= 3:
                            if punches[1].hour < 17 and punches[2].hour < 17:
                                mins_almuerzo = (punches[2] - punches[1]).total_seconds() / 60
                                if mins_almuerzo > 60:
                                    almuerzo_exc = True
                                    almuerzo_str = f"{int(mins_almuerzo)} min"
                                    
                        if len(punches) >= 5:
                            if punches[3].hour < 17 and punches[4].hour < 17:
                                mins_break = (punches[4] - punches[3]).total_seconds() / 60
                                if mins_break > 15:
                                    break_exc = True
                                    break_str = f"{int(mins_break)} min"
                                    
                        if llegada_tarde or almuerzo_exc or break_exc:
                            motivos = []
                            if llegada_tarde: motivos.append(f"Llegada a las {entrada.strftime('%I:%M %p')} (Tarde)")
                            if almuerzo_exc: motivos.append(f"Almuerzo: {almuerzo_str}")
                            if break_exc: motivos.append(f"Break: {break_str}")
                            resultados.append({
                                'Nombre': nombre, 'Fecha': fecha.strftime('%d/%m/%Y'), 'Infracción Detectada': " | ".join(motivos)
                            })
                            
                    st.write("---")
                    if resultados:
                        st.error(f"🚨 Se detectaron {len(resultados)} infracciones.")
                        st.dataframe(pd.DataFrame(resultados), use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ Excelente. Nadie llegó tarde ni se pasó del almuerzo o break.")
            except Exception as e:
                st.error(f"❌ Ocurrió un error leyendo los datos: {e}")

    # =========================================================
    # PESTAÑA 2: CONSOLIDADO RRHH
    # =========================================================
    with tab_rrhh:
        st.subheader("📑 Generador de Reporte Unificado")
        st.markdown("Cargue los reportes oficiales para limpiar columnas vacías y unificar la información.")
        
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            f_aus = st.file_uploader("📂 PDF de Ausencias", type=['pdf'], key="up_aus")
        with col_u2:
            f_tar = st.file_uploader("📂 PDF de Llegadas Tarde", type=['pdf'], key="up_tar")
            
        # BOTÓN PARA PROCESAR LOS ARCHIVOS
        if st.button("🚀 ANALIZAR ARCHIVOS", type="primary", use_container_width=True):
            if f_aus or f_tar:
                with st.spinner("Procesando tablas y eliminando basura..."):
                    try:
                        df_a = extraer_tabla_limpia_pdf(f_aus) if f_aus else pd.DataFrame()
                        df_t = extraer_tabla_limpia_pdf(f_tar) if f_tar else pd.DataFrame()
                        
                        pdf_data = generar_pdf_unificado_rrhh(df_a, df_t)
                        
                        if pdf_data:
                            # Guardamos en la memoria para que el botón de descarga aparezca abajo
                            st.session_state['pdf_final_rrhh'] = pdf_data
                            st.session_state['df_a_prev'] = df_a
                            st.session_state['df_t_prev'] = df_t
                            st.success("✅ ¡Análisis completado con éxito!")
                            st.balloons()
                    except Exception as e:
                        st.error(f"Error en el análisis. Detalles: {e}")
            else:
                st.warning("Debe subir al menos un archivo para proceder.")

        # --- SECCIÓN QUE DIBUJA EL BOTÓN DE DESCARGA (Se queda fijo) ---
        if 'pdf_final_rrhh' in st.session_state:
            st.divider()
            st.markdown("### 🎉 Tu Reporte está listo")
            st.download_button(
                label="📥 DESCARGAR REPORTE UNIFICADO (PDF)",
                data=st.session_state['pdf_final_rrhh'],
                file_name=f"Consolidado_RRHH_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
            
            with st.expander("Ver vista previa de datos extraídos"):
                if not st.session_state.get('df_a_prev', pd.DataFrame()).empty:
                    st.write("**Ausencias:**")
                    st.dataframe(st.session_state['df_a_prev'].head(5), use_container_width=True)
                if not st.session_state.get('df_t_prev', pd.DataFrame()).empty:
                    st.write("**Tardanzas:**")
                    st.dataframe(st.session_state['df_t_prev'].head(5), use_container_width=True)
