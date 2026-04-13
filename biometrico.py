import pandas as pd
import streamlit as st

def procesar_marcas(df_marcas, df_areas):
    # 1. Unir las marcas con las áreas asignadas en la pantalla
    df_completo = pd.merge(df_marcas, df_areas, on=['ID', 'Full Name'], how='left')

    # 2. Formatear y ordenar cronológicamente
    df_completo['Datetime'] = pd.to_datetime(df_completo['Date'] + ' ' + df_completo['Time'], format='%d/%m/%Y %H:%M', errors='coerce')
    df_completo = df_completo.dropna(subset=['Datetime']).sort_values(['ID', 'Datetime'])

    # 3. Eliminar marcas dobles por error humano (menos de 15 min de diferencia)
    df_completo['Time_Diff'] = df_completo.groupby(['ID', 'Date'])['Datetime'].diff()
    df_limpio = df_completo[(df_completo['Time_Diff'].isna()) | (df_completo['Time_Diff'] > pd.Timedelta(minutes=15))].copy()

    # 4. Función de Inferencia Lógica según el Área
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

    # 5. Formato innegociable HH:mm:ss sin fecha
    df_final['Time'] = df_final['Datetime'].dt.strftime('%H:%M:%S')

    # 6. PIVOTAR LA TABLA (Formato Horizontal estilo Excel)
    df_pivot = df_final.pivot(index=['ID', 'Full Name', 'Date', 'Area'], columns='Evento', values='Time').reset_index()
    
    # Definir el orden lógico de las columnas de izquierda a derecha
    orden_columnas = ['ID', 'Full Name', 'Date']
    eventos_logicos = ['Entrada', 'Salida Almuerzo', 'Entrada Almuerzo', 'Break', 'Salida']
    
    # Agregar solo las columnas de eventos que existan en los datos procesados
    for evento in eventos_logicos:
        if evento in df_pivot.columns:
            orden_columnas.append(evento)
            
    df_pivot = df_pivot[orden_columnas]
    
    # Renombrar para que se vea estético en la pantalla
    df_pivot = df_pivot.rename(columns={'Full Name': 'Nombre Completo', 'Date': 'Fecha'})

    # 7. Renderizar en Streamlit
    st.write("---")
    st.write("### 2️⃣ Reporte de Asistencia Formateado")
    
    # Crear pestañas automáticas según las áreas detectadas
    areas_presentes = [a for a in df_pivot['Area'].unique() if str(a).strip() != ""]
    
    if areas_presentes:
        tabs = st.tabs(areas_presentes)
        for i, area in enumerate(areas_presentes):
            with tabs[i]:
                # Filtramos por área, quitamos columnas redundantes (ID y Area)
                df_area = df_pivot[df_pivot['Area'] == area].drop(columns=['Area', 'ID'])
                
                # Rellenar espacios vacíos con guiones y mostrar la tabla sin números de índice
                st.dataframe(df_area.fillna("-"), use_container_width=True, hide_index=True)
    else:
        st.dataframe(df_pivot.drop(columns=['Area', 'ID']).fillna("-"), use_container_width=True, hide_index=True)


def vista_biometrico():
    st.title("⏱️ Módulo de Depuración Biométrica")
    st.markdown("Sube tu archivo `Transaction.csv`. Asigna el área a cada empleado en la tabla y presiona procesar.")
    
    archivo = st.file_uploader("📥 Cargar Transaction.csv", type=['csv'])
    
    if archivo:
        try:
            # 1. BÚSQUEDA DINÁMICA DE LOS ENCABEZADOS (A prueba de fallos)
            content = archivo.getvalue().decode('utf-8', errors='ignore')
            lineas = content.splitlines()
            
            inicio_datos = 0
            for i, linea in enumerate(lineas):
                # Busca automáticamente la fila que contiene las columnas clave
                if "ID" in linea and "Full Name" in linea:
                    inicio_datos = i
                    break
            
            # Regresamos el puntero al inicio para que pandas lo lea desde la línea correcta
            archivo.seek(0)
            df_marcas = pd.read_csv(archivo, skiprows=inicio_datos)
            
            # 2. Limpiar espacios invisibles en las columnas (ej: " ID " a "ID")
            df_marcas.columns = df_marcas.columns.str.strip()
            
            # Asegurarnos de que la columna ID exista y sea texto limpio
            if 'ID' not in df_marcas.columns:
                st.error("El archivo no tiene una columna llamada 'ID'. Verifica que sea el export original.")
                return
                
            df_marcas['ID'] = df_marcas['ID'].astype(str).str.strip()
            
            # Extraer lista única de empleados
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            
            # Guardar en la memoria temporal de la app (Mejorado para guardar tus cambios si subes otro reporte)
            if 'mapeo_areas' not in st.session_state:
                empleados_unicos['Area'] = "ADMINISTRACION" # Asignación por defecto
                st.session_state['mapeo_areas'] = empleados_unicos
            else:
                # Mezclar empleados nuevos con los que ya tenías clasificados
                empleados_previos = st.session_state['mapeo_areas']
                combinado = pd.merge(empleados_unicos, empleados_previos[['ID', 'Area']], on='ID', how='left')
                combinado['Area'] = combinado['Area'].fillna("ADMINISTRACION")
                st.session_state['mapeo_areas'] = combinado
                
            st.write("### 1️⃣ Asignación Rápida de Áreas")
            st.info("Selecciona el área correspondiente. Puedes cambiarla dando doble clic en la columna 'Area'.")
            
            # Editor interactivo de Streamlit (st.data_editor)
            areas_editadas = st.data_editor(
                st.session_state['mapeo_areas'],
                column_config={
                    "Area": st.column_config.SelectboxColumn(
                        "Área del Empleado",
                        options=["AREA TECNICA", "SAC", "ADMINISTRACION"],
                        required=True
                    )
                },
                disabled=["ID", "Full Name"], # Proteger nombre e ID
                hide_index=True,
                use_container_width=True
            )
            
            st.session_state['mapeo_areas'] = areas_editadas

            # Botón de ejecución
            if st.button("🚀 Generar Reporte Depurado", type="primary"):
                procesar_marcas(df_marcas, areas_editadas)
                
        except Exception as e:
            st.error(f"❌ Error procesando el archivo. Detalle técnico: {e}")
