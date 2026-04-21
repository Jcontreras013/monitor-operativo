import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta

def limpiar_nombre(raw):
    """Quita la basura que el PDF mezcla con los nombres"""
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def vista_biometrico():
    st.title("🚨 Centro de Control Biométrico y RRHH")
    
    tab_transacciones, tab_rrhh = st.tabs(["⏱️ Auditoría Diaria (Transacciones)", "📊 Consolidado RRHH (PDFs)"])
    
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
                        
                    # Extraer marcas con Regex
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

                # --- GESTIÓN DE TURNOS ---
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
    # PESTAÑA 2: NUEVO CONSOLIDADO DE RRHH
    # =========================================================
    with tab_rrhh:
        st.markdown("### 📑 Reporte Unificado de RRHH")
        st.caption("Cruza los PDFs de Ausencias y Llegadas Tarde para generar un consolidado general.")
        
        col_a, col_b = st.columns(2)
        with col_a:
            file_ausencias = st.file_uploader("📥 Subir PDF de Ausencias", type=['pdf'], key="aus")
        with col_b:
            file_tardanzas = st.file_uploader("📥 Subir PDF de Llegadas Tarde", type=['pdf'], key="tar")
            
        if st.button("🔍 Analizar Estructura de PDFs", type="primary", use_container_width=True):
            if file_ausencias and file_tardanzas:
                st.info("Analizando cómo está armada la tabla dentro de los PDFs...")
                try:
                    import importlib
                    if importlib.util.find_spec("pdfplumber") is None:
                        st.warning("⚠️ Necesitamos instalar la librería avanzada. Abre tu terminal y ejecuta: `pip install pdfplumber`")
                        st.stop()
                        
                    import pdfplumber
                    
                    # INTENTO DE LECTURA PDF 1 (AUSENCIAS)
                    st.write("#### 📄 Extracción de PDF Ausencias:")
                    with pdfplumber.open(file_ausencias) as pdf_a:
                        # Leemos la primera página para ver el esqueleto
                        page = pdf_a.pages[0]
                        tablas = page.extract_tables()
                        if tablas:
                            st.write(f"✅ Tabla detectada. Columnas encontradas:")
                            df_test_a = pd.DataFrame(tablas[0])
                            st.dataframe(df_test_a.head(10)) # Mostramos solo las primeras 10 filas
                        else:
                            st.error("No se detectó una tabla estructurada. Extrayendo texto bruto:")
                            st.text(page.extract_text()[:1000])
                            
                    # INTENTO DE LECTURA PDF 2 (TARDANZAS)
                    st.write("#### 📄 Extracción de PDF Llegadas Tarde:")
                    with pdfplumber.open(file_tardanzas) as pdf_t:
                        page2 = pdf_t.pages[0]
                        tablas2 = page2.extract_tables()
                        if tablas2:
                            st.write(f"✅ Tabla detectada. Columnas encontradas:")
                            df_test_t = pd.DataFrame(tablas2[0])
                            st.dataframe(df_test_t.head(10))
                        else:
                            st.error("No se detectó una tabla estructurada. Extrayendo texto bruto:")
                            st.text(page2.extract_text()[:1000])
                            
                    st.success("👆 **¡Pásame una captura de los datos que salieron aquí arriba!** Con eso escribiré el código final que une todo el reporte de RRHH en un solo clic.")
                    
                except Exception as e:
                    st.error(f"Error procesando PDFs: {e}")
            else:
                st.warning("Por favor sube ambos PDFs para hacer el análisis.")
