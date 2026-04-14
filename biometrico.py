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
    st.title("🚨 Auditoría Biométrica por Excepción (PDF)")
    st.caption("Detecta llegadas tarde (ej. a partir de las 08:06 AM exactas), almuerzos mayores a 1 hora (2do y 3er marcaje) y breaks mayores a 15 min (4to y 5to marcaje). Los marcajes después de las 5:00 PM se consideran salida.")
    
    if st.button("🔄 Reiniciar Turnos"):
        if 'memoria_turnos' in st.session_state:
            del st.session_state['memoria_turnos']
        st.success("Memoria borrada.")

    archivo = st.file_uploader("📥 Subir Archivo Transaction.pdf", type=['pdf'])
    
    if archivo:
        try:
            # 1. Validar librería PDF
            import importlib
            if importlib.util.find_spec("PyPDF2") is None:
                st.error("⚠️ Falta la librería para leer PDFs. Abre tu terminal y ejecuta: `pip install PyPDF2`")
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
                
                # Limpiar Nombres y Formatear
                df['Name_Clean'] = df['Name_Raw'].apply(limpiar_nombre)
                id_to_name = df.groupby('ID')['Name_Clean'].agg(lambda x: x.mode()[0] if not x.empty else 'Unknown').to_dict()
                df['Full Name'] = df['ID'].map(id_to_name)
                
                df['Datetime'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%d/%m/%Y %H:%M')
                df = df.sort_values(['ID', 'Datetime'])
                
                # Eliminar dedazos (marcas con menos de 15 min de diferencia)
                df['Time_Diff'] = df.groupby(['ID', 'Date'])['Datetime'].diff()
                df = df[(df['Time_Diff'].isna()) | (df['Time_Diff'] > pd.Timedelta(minutes=15))].copy()
                df['FECHA_SOLA'] = df['Datetime'].dt.date

            # --- GESTIÓN DE TURNOS ---
            usuarios_unicos = df[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            usuarios_unicos['Turno'] = "08:00 AM" # Turno por defecto
            
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

            # --- ANALIZAR EXCEPCIONES ---
            if st.button("🚀 Extraer Infractores", type="primary"):
                resultados = []
                
                for (uid, fecha), grupo in df.groupby(['ID', 'FECHA_SOLA']):
                    punches = grupo['Datetime'].tolist()
                    if not punches: continue
                    
                    nombre = grupo['Full Name'].iloc[0]
                    turno_str = dict_turnos.get(uid, "08:00 AM")
                    
                    # 1. Llegada Tarde (1er marcaje)
                    entrada = punches[0]
                    llegada_tarde = False
                    try:
                        dt_turno = datetime.strptime(turno_str, "%I:%M %p").time()
                        # Ajuste exacto: El empleado tiene 5 minutos y 59 segundos a favor. 
                        # Si entra a las 08:06:00, es tarde.
                        limite = datetime.combine(fecha, dt_turno) + timedelta(minutes=5, seconds=59)
                        if entrada > limite:
                            llegada_tarde = True
                    except: pass
                        
                    almuerzo_exc = False
                    almuerzo_str = ""
                    break_exc = False
                    break_str = ""
                    
                    # 2. Almuerzo (>60 min entre el 2do y 3er marcaje)
                    if len(punches) >= 3:
                        # Aseguramos que ninguno de estos marcajes sea la salida (>= 17:00)
                        if punches[1].hour < 17 and punches[2].hour < 17:
                            mins_almuerzo = (punches[2] - punches[1]).total_seconds() / 60
                            if mins_almuerzo > 60:
                                almuerzo_exc = True
                                almuerzo_str = f"{int(mins_almuerzo)} min"
                                
                    # 3. Break (>15 min entre el 4to y 5to marcaje)
                    if len(punches) >= 5:
                        # Aseguramos que ninguno de estos marcajes sea la salida (>= 17:00)
                        if punches[3].hour < 17 and punches[4].hour < 17:
                            mins_break = (punches[4] - punches[3]).total_seconds() / 60
                            if mins_break > 15:
                                break_exc = True
                                break_str = f"{int(mins_break)} min"
                                
                    # Si tiene al menos una infracción, lo agregamos al reporte
                    if llegada_tarde or almuerzo_exc or break_exc:
                        motivos = []
                        if llegada_tarde: motivos.append(f"Llegada a las {entrada.strftime('%I:%M %p')} (Tarde)")
                        if almuerzo_exc: motivos.append(f"Almuerzo: {almuerzo_str}")
                        if break_exc: motivos.append(f"Break: {break_str}")
                        
                        resultados.append({
                            'Nombre': nombre,
                            'Fecha': fecha.strftime('%d/%m/%Y'),
                            'Infracción Detectada': " | ".join(motivos)
                        })
                        
                # --- MOSTRAR RESULTADOS ---
                st.write("---")
                if resultados:
                    st.error(f"🚨 Se detectaron {len(resultados)} infracciones.")
                    st.dataframe(pd.DataFrame(resultados), use_container_width=True, hide_index=True)
                else:
                    st.success("✅ Excelente. Nadie llegó tarde ni se pasó del almuerzo o break en este reporte.")
                    
        except Exception as e:
            st.error(f"❌ Ocurrió un error leyendo los datos del PDF: {e}")
