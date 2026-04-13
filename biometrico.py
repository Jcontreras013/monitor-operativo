import pandas as pd
import streamlit as st
import io

def procesar_marcas(df_marcas, df_areas):
    # Aseguramos que ambas tablas tengan ID como texto limpio para evitar errores de cruce
    df_marcas['ID'] = df_marcas['ID'].astype(str).str.strip()
    df_areas['ID'] = df_areas['ID'].astype(str).str.strip()
    
    df_completo = pd.merge(df_marcas, df_areas, on=['ID', 'Full Name'], how='left')

    # Validar que existan las columnas de tiempo
    if 'Date' not in df_completo.columns or 'Time' not in df_completo.columns:
        st.error(f"Faltan columnas de fecha/hora. Columnas actuales: {df_completo.columns.tolist()}")
        return

    # Formatear y ordenar cronológicamente
    df_completo['Datetime'] = pd.to_datetime(df_completo['Date'].astype(str).str.strip() + ' ' + df_completo['Time'].astype(str).str.strip(), format='%d/%m/%Y %H:%M', errors='coerce')
    df_completo = df_completo.dropna(subset=['Datetime']).sort_values(['ID', 'Datetime'])

    if df_completo.empty:
        st.warning("No hay registros válidos después de procesar las fechas y horas.")
        return

    # Eliminar marcas dobles por error humano (menos de 15 min de diferencia)
    df_completo['Time_Diff'] = df_completo.groupby(['ID', 'Date'])['Datetime'].diff()
    df_limpio = df_completo[(df_completo['Time_Diff'].isna()) | (df_completo['Time_Diff'] > pd.Timedelta(minutes=15))].copy()

    # Función de Inferencia Lógica según el Área
    def etiquetar_marcas(grupo):
        area = str(grupo['Area'].iloc[0]).strip().upper() if pd.notna(grupo['Area'].iloc[0]) else "ADMINISTRACION"
        n = len(grupo)
        etiquetas = [''] * n
        
        # Reglas de eventos por área
        if area == "AREA TECNICA":
            if n >= 1: etiquetas[0] = "Entrada"
            if n >= 2: etiquetas[-1] = "Salida"
        elif area == "ADMINISTRACION":
            if n >= 1: etiquetas[0] = "Entrada"
            if n >= 2: etiquetas[1] = "Salida Almuerzo"
            if n >= 3: etiquetas[2] = "Entrada Almuerzo"
            if n >= 4: etiquetas[-1] = "Salida"
        elif area == "SAC":
            if n >= 1: etiquetas[0] = "Entrada"
            if n >= 2: etiquetas[1] = "Salida Almuerzo"
            if n >= 3: etiquetas[2] = "Entrada Almuerzo"
            if n >= 4: etiquetas[3] = "Break"
            if n >= 5: etiquetas[-1] = "Salida"
            
        grupo['Evento'] = etiquetas
        return grupo

    # Aplicar las etiquetas y limpiar registros sobrantes
    df_final = df_limpio.groupby(['ID', 'Date'], group_keys=False).apply(etiquetar_marcas)
    df_final = df_final[df_final['Evento'] != '']

    # Formato innegociable HH:mm:ss
    df_final['Time'] = df_final['Datetime'].dt.strftime('%H:%M:%S')

    # PIVOTAR LA TABLA (Formato Horizontal)
    df_pivot = df_final.pivot(index=['ID', 'Full Name', 'Date', 'Area'], columns='Evento', values='Time').reset_index()
    
    # Definir el orden lógico de las columnas de izquierda a derecha
    orden_columnas = ['ID', 'Full Name', 'Date']
    eventos_logicos = ['Entrada', 'Salida Almuerzo', 'Entrada Almuerzo', 'Break', 'Salida']
    
    for evento in eventos_logicos:
        if evento in df_pivot.columns:
            orden_columnas.append(evento)
            
    df_pivot = df_pivot[orden_columnas]
    df_pivot = df_pivot.rename(columns={'Full Name': 'Nombre Completo', 'Date': 'Fecha'})

    # Renderizar en Streamlit
    st.write("---")
    st.write("### 2️⃣ Reporte de Asistencia Formateado")
    
    areas_presentes = [a for a in df_pivot['Area'].unique() if str(a).strip() != ""]
    
    if areas_presentes:
        tabs = st.tabs(areas_presentes)
        for i, area in enumerate(areas_presentes):
            with tabs[i]:
                # El errors='ignore' protege contra fallos si la columna no existe
                df_area = df_pivot[df_pivot['Area'] == area].drop(columns=['Area', 'ID'], errors='ignore')
                st.dataframe(df_area.fillna("-"), use_container_width=True, hide_index=True)
    else:
        st.dataframe(df_pivot.drop(columns=['Area', 'ID'], errors='ignore').fillna("-"), use_container_width=True, hide_index=True)


def vista_biometrico():
    st.title("⏱️ Módulo de Depuración Biométrica")
    st.markdown("Sube tu archivo. Asigna el área a cada empleado en la tabla y presiona procesar.")
    
    # Botón de emergencia para resetear la memoria por si se trabó con el error anterior
    if st.button("🔄 Reiniciar Memoria de Áreas (Clic si tienes errores)"):
        if 'mapeo_areas' in st.session_state:
            del st.session_state['mapeo_areas']
        st.success("Memoria reiniciada correctamente. Ya puedes subir el archivo.")

    archivo = st.file_uploader("📥 Cargar Reporte Biométrico", type=['csv'])
    
    if archivo:
        try:
            # 1. utf-8-sig ELIMINA caracteres basura de Windows/ZKTeco (BOM)
            content = archivo.getvalue().decode('utf-8-sig', errors='replace')
            lineas = content.splitlines()
            
            # 2. Búsqueda ultra-flexible de encabezados (Soporta Inglés y Español)
            inicio_datos = -1
            for i, linea in enumerate(lineas):
                linea_up = linea.upper()
                if ("ID" in linea_up and "FULL NAME" in linea_up) or \
                   ("NO." in linea_up and "NOMBRE" in linea_up) or \
                   ("DEPARTAMENTO" in linea_up and "NOMBRE" in linea_up):
                    inicio_datos = i
                    break
                    
            if inicio_datos == -1:
                # Si no encuentra encabezado basura, asumimos que arranca en la fila 0
                inicio_datos = 0
                
            # 3. Leer el CSV permitiendo separadores dinámicos (, o ;)
            csv_valido = "\n".join(lineas[inicio_datos:])
            df_marcas = pd.read_csv(io.StringIO(csv_valido), sep=None, engine='python')
            
            # 4. Limpieza agresiva de columnas (quita espacios invisibles)
            df_marcas.columns = [str(col).strip() for col in df_marcas.columns]
            
            # 5. TRADUCTOR DINÁMICO: Convierte el formato en español al estándar que usa tu lógica
            columnas_actuales = list(df_marcas.columns)
            for col in columnas_actuales:
                col_up = col.upper()
                if col_up in ['ID', 'NO.', 'NO', 'NÚMERO']:
                    df_marcas.rename(columns={col: 'ID'}, inplace=True)
                elif col_up in ['FULL NAME', 'NOMBRE', 'NOMBRES']:
                    df_marcas.rename(columns={col: 'Full Name'}, inplace=True)
                elif col_up in ['DATE', 'FECHA']:
                    df_marcas.rename(columns={col: 'Date'}, inplace=True)
                elif col_up in ['TIME', 'HORA']:
                    df_marcas.rename(columns={col: 'Time'}, inplace=True)
                elif col_up in ['FECHA/HORA', 'FECHA Y HORA']:
                    # Separar la columna combinada en Date y Time
                    dt_temp = pd.to_datetime(df_marcas[col], errors='coerce')
                    df_marcas['Date'] = dt_temp.dt.strftime('%d/%m/%Y')
                    df_marcas['Time'] = dt_temp.dt.strftime('%H:%M:%S')

            # Comprobación de diagnóstico
            if 'ID' not in df_marcas.columns or 'Full Name' not in df_marcas.columns:
                st.error("❌ Aún con el traductor, no encuentro las columnas clave.")
                st.write("Las columnas exactas detectadas son:", df_marcas.columns.tolist())
                return
                
            df_marcas['ID'] = df_marcas['ID'].astype(str).str.strip()
            df_marcas['Full Name'] = df_marcas['Full Name'].astype(str).str.strip()
            
            # 6. Lógica de Memoria de Empleados
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            empleados_unicos['Area'] = "ADMINISTRACION" 
            
            if 'mapeo_areas' in st.session_state:
                empleados_previos = st.session_state['mapeo_areas']
                if 'ID' in empleados_previos.columns and 'Area' in empleados_previos.columns:
                    dict_areas = dict(zip(empleados_previos['ID'], empleados_previos['Area']))
                    empleados_unicos['Area'] = empleados_unicos['ID'].map(dict_areas).fillna("ADMINISTRACION")
                    
            st.session_state['mapeo_areas'] = empleados_unicos
                
            st.write("### 1️⃣ Asignación Rápida de Áreas")
            st.info("Selecciona el área correspondiente. Puedes cambiarla dando doble clic en la columna 'Area'.")
            
            areas_editadas = st.data_editor(
                st.session_state['mapeo_areas'],
                column_config={
                    "Area": st.column_config.SelectboxColumn(
                        "Área del Empleado",
                        options=["AREA TECNICA", "SAC", "ADMINISTRACION"],
                        required=True
                    )
                },
                disabled=["ID", "Full Name"], 
                hide_index=True,
                use_container_width=True
            )
            
            st.session_state['mapeo_areas'] = areas_editadas

            if st.button("🚀 Generar Reporte Depurado", type="primary"):
                procesar_marcas(df_marcas, areas_editadas)
                
        except Exception as e:
            st.error(f"❌ Error crítico procesando el archivo. Detalle: {e}")
