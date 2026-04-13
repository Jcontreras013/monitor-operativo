import pandas as pd
import streamlit as st
import io
from datetime import datetime, timedelta

def procesar_excepciones(df_marcas, df_configuracion):
    st.write("---")
    st.write("### 🚨 Reporte de Infracciones y Llegadas Tardes")
    
    # Unir las marcas con la configuración de turnos asignada en pantalla
    df_completo = pd.merge(df_marcas, df_configuracion, on=['ID', 'Full Name'], how='left')
    
    # Formatear y ordenar cronológicamente
    df_completo['Datetime'] = pd.to_datetime(df_completo['Date'].astype(str).str.strip() + ' ' + df_completo['Time'].astype(str).str.strip(), format='%d/%m/%Y %H:%M', errors='coerce')
    df_completo = df_completo.dropna(subset=['Datetime']).sort_values(['ID', 'Datetime'])

    if df_completo.empty:
        st.warning("No hay registros válidos después de procesar las fechas y horas.")
        return

    # Eliminar marcas dobles por error humano (menos de 15 min de diferencia)
    df_completo['Time_Diff'] = df_completo.groupby(['ID', 'Date'])['Datetime'].diff()
    df_limpio = df_completo[(df_completo['Time_Diff'].isna()) | (df_completo['Time_Diff'] > pd.Timedelta(minutes=15))].copy()

    # Función principal para evaluar cada día de cada empleado
    def evaluar_dia(grupo):
        punches = grupo['Datetime'].tolist()
        if not punches: return None
        
        nombre = grupo['Full Name'].iloc[0]
        fecha = grupo['Date'].iloc[0]
        area = grupo['Area'].iloc[0] if 'Area' in grupo.columns else "SAC"
        turno_str = str(grupo['Hora Entrada Esperada'].iloc[0]).strip() if 'Hora Entrada Esperada' in grupo.columns else "08:00 AM"
        
        # 1. Evaluación de Llegada (Primera Marca) vs Turno Asignado
        entrada = punches[0]
        hora_entrada = entrada.strftime('%H:%M:%S') # Formato estricto HH:mm:ss
        
        # Calcular el límite de entrada dándole 5 minutos de gracia
        try:
            h_turno, m_turno = map(int, turno_str.replace(' AM', '').replace(' PM', '').split(':'))
            if 'PM' in turno_str and h_turno != 12:
                h_turno += 12
            hora_esperada_dt = datetime(2000, 1, 1, h_turno, m_turno)
            limite_entrada = (hora_esperada_dt + timedelta(minutes=5)).time()
            tarde = entrada.time() > limite_entrada
        except:
            tarde = False # Si hay error en el formato del turno, ignorar la llegada tarde
            
        # 2. Evaluación Dinámica de Almuerzos y Breaks (Independiente de la hora del día)
        almuerzo_excedido = False
        break_excedido = False
        tiempos_fuera = []
        
        # Revisamos los pares de marcas intermedias (salida -> entrada)
        for i in range(1, len(punches) - 1, 2):
            if i + 1 < len(punches):
                duracion = (punches[i+1] - punches[i]).total_seconds() / 60
                
                # Más de 60 minutos = Almuerzo excedido
                if duracion > 60:
                    almuerzo_excedido = True
                    h, m = divmod(int(duracion), 60)
                    tiempos_fuera.append(f"Almuerzo: {h}h {m}m")
                    
                # Entre 15 y 60 minutos = Break excedido
                elif duracion > 15 and duracion <= 60:
                    break_excedido = True
                    tiempos_fuera.append(f"Break: {int(duracion)}m")

        # Generar la alerta solo si hay infracción
        if tarde or almuerzo_excedido or break_excedido:
            infracciones = []
            if tarde: infracciones.append(f"Llegada Tarde (Turno {turno_str})")
            if almuerzo_excedido: infracciones.append("Almuerzo Excedido (>1h)")
            if break_excedido: infracciones.append("Break Excedido (>15m)")
            
            return pd.Series({
                'Nombre Completo': nombre,
                'Área': area,
                'Fecha': fecha,
                'Hora Entrada Real': hora_entrada,
                'Tiempos Excedidos': " | ".join(tiempos_fuera) if tiempos_fuera else "-",
                'Motivo de Alerta': " | ".join(infracciones)
            })
        return None

    # Procesar la evaluación
    with st.spinner("🕵️‍♂️ Analizando turnos y buscando excepciones..."):
        df_excepciones = df_limpio.groupby(['ID', 'Date'], group_keys=False).apply(evaluar_dia).dropna()
        
    if df_excepciones.empty:
        st.success("✅ ¡Excelente semana! Ningún empleado llegó tarde ni excedió sus tiempos de comida/break.")
    else:
        st.error(f"⚠️ Se detectaron {len(df_excepciones)} faltas en el reporte.")
        
        # Resaltar visualmente dónde está la falla
        def resaltar_infractor(row):
            styles = [''] * len(row)
            motivo = str(row['Motivo de Alerta'])
            if 'Llegada Tarde' in motivo:
                styles[df_excepciones.columns.get_loc('Hora Entrada Real')] = 'background-color: #ffcccc; color: #b30000; font-weight: bold'
            if 'Almuerzo Excedido' in motivo or 'Break Excedido' in motivo:
                styles[df_excepciones.columns.get_loc('Tiempos Excedidos')] = 'background-color: #ffcccc; color: #b30000; font-weight: bold'
            return styles

        df_styled = df_excepciones.style.apply(resaltar_infractor, axis=1)
        st.dataframe(df_styled, use_container_width=True, hide_index=True)


def vista_biometrico():
    st.title("⏱️ Auditoría Biométrica por Excepción (Turnos Flexibles)")
    st.caption("Asigna el turno a cada persona. El sistema detectará automáticamente si llegaron tarde o si excedieron su tiempo de almuerzo/break, **sin importar a qué hora lo tomaron**.")
    
    # Botón de seguridad
    if st.button("🔄 Reiniciar Asignación de Turnos"):
        if 'mapeo_turnos' in st.session_state:
            del st.session_state['mapeo_turnos']
        st.success("Memoria de turnos reiniciada.")

    archivo = st.file_uploader("📥 Cargar Transaction.csv (Original en Inglés)", type=['csv'])
    
    if archivo:
        try:
            # Lectura a prueba de errores de ZKTeco
            content = archivo.getvalue().decode('utf-8-sig', errors='replace')
            lineas = content.splitlines()
            
            # Buscar el inicio real de los datos
            inicio_datos = -1
            for i, linea in enumerate(lineas):
                if "ID" in linea.upper() and "FULL NAME" in linea.upper():
                    inicio_datos = i
                    break
                    
            if inicio_datos == -1:
                st.error("❌ El archivo no contiene las columnas necesarias (ID y Full Name). Asegúrate de subir el Transaction.csv original.")
                return
                
            # Extraer y leer el CSV limpio
            csv_valido = "\n".join(lineas[inicio_datos:])
            df_marcas = pd.read_csv(io.StringIO(csv_valido), sep=',', skipinitialspace=True, on_bad_lines='skip')
            df_marcas.columns = [str(col).strip() for col in df_marcas.columns]
            
            # Validación de diagnóstico
            if 'ID' not in df_marcas.columns or 'Full Name' not in df_marcas.columns:
                st.error("❌ Ocurrió un error leyendo las columnas.")
                return
                
            df_marcas['ID'] = df_marcas['ID'].astype(str).str.strip()
            df_marcas['Full Name'] = df_marcas['Full Name'].astype(str).str.strip()

            # --- LÓGICA DE MEMORIA PARA TURNOS ---
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            empleados_unicos['Area'] = "SAC" 
            empleados_unicos['Hora Entrada Esperada'] = "08:00 AM" # Turno por defecto
            
            opciones_turnos = [
                "07:00 AM", "07:30 AM", "08:00 AM", "08:30 AM", 
                "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", 
                "11:00 AM", "01:00 PM", "02:00 PM"
            ]
            
            # Recuperar asignaciones previas si existen
            if 'mapeo_turnos' in st.session_state:
                previos = st.session_state['mapeo_turnos']
                if 'ID' in previos.columns:
                    empleados_unicos = pd.merge(empleados_unicos[['ID', 'Full Name']], previos[['ID', 'Area', 'Hora Entrada Esperada']], on='ID', how='left')
                    empleados_unicos['Area'] = empleados_unicos['Area'].fillna("SAC")
                    empleados_unicos['Hora Entrada Esperada'] = empleados_unicos['Hora Entrada Esperada'].fillna("08:00 AM")
                    
            st.session_state['mapeo_turnos'] = empleados_unicos
            
            st.write("### 1️⃣ Asignación de Turnos por Empleado")
            st.info("💡 Asigna a qué hora debe entrar el empleado. El sistema le dará 5 minutos de gracia automáticamente.")
            
            # Editor interactivo
            turnos_editados = st.data_editor(
                st.session_state['mapeo_turnos'],
                column_config={
                    "Area": st.column_config.SelectboxColumn("Área", options=["AREA TECNICA", "SAC", "ADMINISTRACION"], required=True),
                    "Hora Entrada Esperada": st.column_config.SelectboxColumn("Turno (Entrada)", options=opciones_turnos, required=True)
                },
                disabled=["ID", "Full Name"], 
                hide_index=True,
                use_container_width=True
            )
            
            st.session_state['mapeo_turnos'] = turnos_editados

            # Ejecución
            if st.button("🚀 Procesar Infracciones", type="primary"):
                procesar_excepciones(df_marcas, turnos_editados)
                
        except Exception as e:
            st.error(f"❌ Error crítico procesando el archivo. Detalle: {e}")
