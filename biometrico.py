import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta
import io

def limpiar_nombre(raw):
    """Quita la basura que el PDF mezcla con los nombres"""
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def extraer_tabla_limpia_pdf(archivo_pdf):
    """Extrae datos con pdfplumber y elimina columnas/filas vacías"""
    import pdfplumber
    todas_las_filas = []
    
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas:
                # Limpiar saltos de línea extraños dentro de las celdas
                tabla_limpia = [[str(celda).replace('\n', ' ').strip() if celda else '' for celda in fila] for fila in tabla]
                todas_las_filas.extend(tabla_limpia)
                
    if not todas_las_filas:
        return pd.DataFrame()
        
    # Convertir a DataFrame
    df = pd.DataFrame(todas_las_filas)
    
    # Asignar la primera fila como encabezado
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # === ELIMINAR COLUMNAS Y FILAS VACÍAS (Requisito) ===
    # Reemplazar strings vacíos o "None" por valores nulos reales de Pandas
    df = df.replace(r'^\s*$', pd.NA, regex=True)
    df = df.replace('None', pd.NA)
    
    # Borrar columnas donde TODOS los datos sean nulos
    df = df.dropna(how='all', axis=1)
    # Borrar filas donde TODOS los datos sean nulos
    df = df.dropna(how='all', axis=0)
    
    # Rellenar lo que quede vacío con un guión para que el PDF no falle
    df = df.fillna('---')
    
    # Arreglar nombres de columnas duplicados (por si el PDF venía mal formateado)
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique(): 
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}_{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df.columns = cols
    
    return df

def generar_pdf_unificado_rrhh(df_ausencias, df_tardanzas):
    """Genera un PDF corporativo con ambas tablas limpias"""
    from fpdf import FPDF
    import tempfile
    import os
    import unicodedata
    
    def safestr(texto):
        if pd.isna(texto): return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
        
    pdf = FPDF('L', 'mm', 'A4') # Formato Horizontal (Landscape) para que quepan más columnas
    pdf.add_page()
    
    # Encabezado
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE UNIFICADO DE RRHH: AUSENCIAS Y LLEGADAS TARDE", ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Generado el: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}", ln=True, align="C")
    pdf.ln(5)
    
    def dibujar_tabla(pdf_obj, df, titulo):
        pdf_obj.set_font("Helvetica", "B", 11)
        pdf_obj.set_text_color(40, 50, 100)
        pdf_obj.cell(0, 8, safestr(titulo), ln=True)
        pdf_obj.set_text_color(0, 0, 0)
        
        if df.empty:
            pdf_obj.set_font("Helvetica", "", 9)
            pdf_obj.cell(0, 6, "No se encontraron registros para esta categoria.", ln=True)
            pdf_obj.ln(5)
            return
            
        # Tomar máximo 8 columnas para que no se salga de la hoja
        cols = list(df.columns)[:8]
        df = df[cols]
        
        pdf_obj.set_font("Helvetica", "B", 7)
        pdf_obj.set_fill_color(220, 230, 245)
        
        # Calcular ancho dinámico
        w = 270 / len(cols) # 270mm es aprox el ancho usable en formato horizontal
        
        # Dibujar Encabezados
        for col in cols:
            pdf_obj.cell(w, 6, safestr(str(col))[:25], border=1, align="C", fill=True)
        pdf_obj.ln()
        
        # Dibujar Filas
        pdf_obj.set_font("Helvetica", "", 7)
        pdf_obj.set_fill_color(255, 255, 255)
        for _, row in df.iterrows():
            # Si llegamos al final de la página, crear una nueva
            if pdf_obj.get_y() > 180:
                pdf_obj.add_page()
                pdf_obj.set_font("Helvetica", "B", 7)
                pdf_obj.set_fill_color(220, 230, 245)
                for col in cols:
                    pdf_obj.cell(w, 6, safestr(str(col))[:25], border=1, align="C", fill=True)
                pdf_obj.ln()
                pdf_obj.set_font("Helvetica", "", 7)
                
            for col in cols:
                val = safestr(str(row[col]))[:30] # Cortar textos ultra largos
                pdf_obj.cell(w, 5, val, border=1, align="C")
            pdf_obj.ln()
        pdf_obj.ln(10)
        
    # Dibujar las dos tablas en el PDF
    dibujar_tabla(pdf, df_ausencias, "1. DETALLE DE AUSENCIAS")
    dibujar_tabla(pdf, df_tardanzas, "2. DETALLE DE LLEGADAS TARDE")
    
    # Exportar a Bytes
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
    
    tab_transacciones, tab_rrhh = st.tabs(["⏱️ Auditoría Diaria (Transacciones)", "📊 Consolidado RRHH (Ausencias/Tardanzas)"])
    
    # =========================================================
    # PESTAÑA 1: AUDITORÍA DE TRANSACCIONES ORIGINAL
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
                import importlib
                if importlib.util.find_spec("PyPDF2") is None:
                    st.error("⚠️ Falta la librería. Ejecuta: pip install PyPDF2")
                    return
                    
                from PyPDF2 import PdfReader
                
                with st.spinner("🕵️‍♂️ Escaneando PDF y extrayendo marcas..."):
                    reader = PdfReader(archivo)
                    texto_completo = ""
                    for page in reader.pages:
                        texto_completo += page.extract_text() + "\n"
                        
                    patron = re.compile(r'([A-Za-z\sñÑáéíóúÁÉÍÓÚ\.]+)(\d{1,10})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})')
                    matches = patron.findall(texto_completo)
                    
                    if not matches:
                        st.error("❌ No se encontraron marcas válidas en el PDF.")
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
                        st.success("✅ Excelente. Nadie llegó tarde ni se pasó del almuerzo o break en este reporte.")
                        
            except Exception as e:
                st.error(f"❌ Ocurrió un error leyendo los datos: {e}")

    # =========================================================
    # PESTAÑA 2: CONSOLIDADO UNIFICADO DE RRHH
    # =========================================================
    with tab_rrhh:
        st.markdown("### 📑 Reporte Unificado de RRHH (Extractor Inteligente)")
        st.caption("Sube los PDFs. El sistema borrará columnas vacías y te armará un PDF limpio.")
        
        col_a, col_b = st.columns(2)
        with col_a:
            file_ausencias = st.file_uploader("📥 Subir PDF de Ausencias", type=['pdf'], key="aus")
        with col_b:
            file_tardanzas = st.file_uploader("📥 Subir PDF de Llegadas Tarde", type=['pdf'], key="tar")
            
        if st.button("🚀 Procesar y Generar Reporte Unificado", type="primary", use_container_width=True):
            if file_ausencias or file_tardanzas:
                with st.spinner("Extrayendo, limpiando columnas vacías y dibujando el PDF..."):
                    try:
                        import importlib
                        if importlib.util.find_spec("pdfplumber") is None:
                            st.warning("⚠️ Asegúrate de que tu archivo 'requirements.txt' en GitHub tenga la palabra 'pdfplumber' para que funcione.")
                            st.stop()
                            
                        # Extraer y limpiar
                        df_aus = extraer_tabla_limpia_pdf(file_ausencias) if file_ausencias else pd.DataFrame()
                        df_tar = extraer_tabla_limpia_pdf(file_tardanzas) if file_tardanzas else pd.DataFrame()
                        
                        # Mostrar vistas previas en pantalla
                        if not df_aus.empty:
                            st.success("✅ Ausencias extraídas y limpiadas:")
                            st.dataframe(df_aus.head(10), use_container_width=True, hide_index=True)
                        if not df_tar.empty:
                            st.success("✅ Tardanzas extraídas y limpiadas:")
                            st.dataframe(df_tar.head(10), use_container_width=True, hide_index=True)
                            
                        # Generar el PDF Final
                        pdf_bytes = generar_pdf_unificado_rrhh(df_aus, df_tar)
                        
                        if pdf_bytes:
                            st.session_state['pdf_rrhh'] = pdf_bytes
                            st.balloons()
                            
                    except Exception as e:
                        st.error(f"Ocurrió un error procesando las tablas: {e}")
            else:
                st.warning("Sube al menos un PDF para poder generar el reporte.")
                
        # Botón de descarga
        if 'pdf_rrhh' in st.session_state:
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                label="📥 DESCARGAR REPORTE UNIFICADO (PDF)",
                data=st.session_state['pdf_rrhh'],
                file_name=f"Consolidado_RRHH_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
