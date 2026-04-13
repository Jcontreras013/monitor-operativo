import pandas as pd
import streamlit as st
import io

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

    # ---------------------------------------------------------
    # LA ÚNICA ADICIÓN: PIVOTAR LA TABLA (Formato Horizontal)
    # ---------------------------------------------------------
    df_pivot = df_final.pivot(index=['ID', 'Full Name', 'Date', 'Area'], columns='Evento', values='Time').reset_index()
    
    # Definir el orden lógico de las columnas
    orden_columnas = ['ID', 'Full Name', 'Date']
    eventos_logicos = ['Entrada', 'Salida Almuerzo', 'Entrada Almuerzo', 'Break', 'Salida']
    
    for evento in eventos_logicos:
        if evento in df_pivot.columns:
            orden_columnas.append(evento)
            
    df_pivot = df_pivot[orden_columnas]
    df_pivot = df_pivot.rename(columns={'Full Name': 'Nombre Completo', 'Date': 'Fecha'})
    # ---------------------------------------------------------

    st.write("---")
    st.write("### 2️⃣ Reporte de Asistencia Formateado")
    
    # Crear pestañas automáticas según las áreas detectadas
    areas_presentes = [a for a in df_pivot['Area'].unique() if str(a).strip() != ""]
    
    if areas_presentes:
        tabs = st.tabs(areas_presentes)
        for i, area in enumerate(areas_presentes):
            with tabs[i]:
                # Filtramos por área, quitamos columnas redundantes y mostramos
                df_area = df_pivot[df_pivot['Area'] == area].drop(columns=['Area', 'ID'])
                st.dataframe(df_area.fillna("-"), use_container_width=True, hide_index=True)
    else:
        st.dataframe(df_pivot.drop(columns=['Area', 'ID']).fillna("-"), use_container_width=True, hide_index=True)


def vista_biometrico():
    st.title("⏱️ Módulo de Depuración Biométrica")
    st.markdown("Sube tu archivo `Transaction.csv`. Asigna el área a cada empleado en la tabla y presiona procesar.")
    
    # Única protección extra añadida: Botón de reset por si te equivocas asignando un área
    if st.button("🔄 Reiniciar Asignación de Áreas"):
        if 'mapeo_areas' in st.session_state:
            del st.session_state['mapeo_areas']
        st.success("Memoria reiniciada. Ya puedes subir el archivo de nuevo.")

    archivo = st.file_uploader("📥 Cargar Transaction.csv", type=['csv'])
    
    if archivo:
        try:
            # 1. Leemos el archivo con io.StringIO y utf-8-sig para eliminar cualquier error de "ID" invisible desde la raíz
            content = archivo.getvalue().decode('utf-8-sig', errors='ignore')
            lineas = content.splitlines()
            
            # Buscar dónde empiezan realmente los datos saltando la basura de arriba
            inicio_datos = 0
            for i, linea in enumerate(lineas):
                if "ID" in linea and "Full Name" in linea:
                    inicio_datos = i
                    break
                    
            csv_valido = "\n".join(lineas[inicio_datos:])
            df_marcas = pd.read_csv(io.StringIO(csv_valido))
            
            # Limpiamos los nombres de columnas por si vienen con espacios
            df_marcas.columns = [str(col).strip() for col in df_marcas.columns]
            
            df_marcas['ID'] = df_marcas['ID'].astype(str)
            
            # Extraer lista única de empleados
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            
            # Guardar en la memoria temporal de la app para que no tengas que clasificar cada vez
            if 'mapeo_areas' not in st.session_state:
                empleados_unicos['Area'] = "ADMINISTRACION" # Asignación por defecto
                st.session_state['mapeo_areas'] = empleados_unicos
                
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
                disabled=["ID", "Full Name"], # Proteger nombre e ID para no borrarlos por accidente
                hide_index=True,
                use_container_width=True
            )
            
            st.session_state['mapeo_areas'] = areas_editadas

            # Botón de ejecución
            if st.button("🚀 Generar Reporte Depurado", type="primary"):
                procesar_marcas(df_marcas, areas_editadas)
                
        except Exception as e:
            st.error(f"❌ Error leyendo el archivo. Detalle: {e}")
