import pandas as pd
import streamlit as st

def procesar_marcas(df_marcas, df_areas):
    try:
        # 1. Asegurar que los nombres de columnas no tengan espacios ocultos y sean consistentes
        df_marcas.columns = df_marcas.columns.str.strip()
        df_areas.columns = df_areas.columns.str.strip()
        
        # Convertir IDs a string para que el cruce sea exacto
        df_marcas['ID'] = df_marcas['ID'].astype(str)
        df_areas['ID'] = df_areas['ID'].astype(str)

        # 2. Unir las marcas con las áreas asignadas
        df_completo = pd.merge(df_marcas, df_areas, on=['ID', 'Full Name'], how='left')

        # 3. Formatear y ordenar cronológicamente
        df_completo['Datetime'] = pd.to_datetime(df_completo['Date'] + ' ' + df_completo['Time'], format='%d/%m/%Y %H:%M', errors='coerce')
        df_completo = df_completo.dropna(subset=['Datetime']).sort_values(['ID', 'Datetime'])

        # 4. Eliminar marcas dobles (menos de 15 min de diferencia)
        df_completo['Time_Diff'] = df_completo.groupby(['ID', 'Date'])['Datetime'].diff()
        df_limpio = df_completo[(df_completo['Time_Diff'].isna()) | (df_completo['Time_Diff'] > pd.Timedelta(minutes=15))].copy()

        # 5. Función de Inferencia Lógica según el Área
        def etiquetar_marcas(grupo):
            area = str(grupo['Area'].iloc[0]).strip().upper() if pd.notna(grupo['Area'].iloc[0]) else "ADMINISTRACION"
            n = len(grupo)
            etiquetas = [''] * n
            
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
            else:
                if n >= 1: etiquetas[0] = "Entrada"
                if n >= 2: etiquetas[-1] = "Salida"
                
            grupo['Evento'] = etiquetas
            return grupo

        # Aplicar etiquetas
        df_final = df_limpio.groupby(['ID', 'Date'], group_keys=False).apply(etiquetar_marcas)
        df_final = df_final[df_final['Evento'] != '']
        df_final['Time'] = df_final['Datetime'].dt.strftime('%H:%M:%S')

        # 6. Pivotar la tabla (Formato Horizontal)
        df_pivot = df_final.pivot(index=['ID', 'Full Name', 'Date', 'Area'], columns='Evento', values='Time').reset_index()
        
        # Orden de columnas
        orden_base = ['ID', 'Full Name', 'Date']
        eventos_posibles = ['Entrada', 'Salida Almuerzo', 'Entrada Almuerzo', 'Break', 'Salida']
        columnas_finales = orden_base + [e for e in eventos_posibles if e in df_pivot.columns]
        
        df_pivot = df_pivot[columnas_finales].rename(columns={'Full Name': 'Nombre Completo', 'Date': 'Fecha'})

        st.write("---")
        st.write("### 2️⃣ Reporte de Asistencia Formateado")
        
        areas_presentes = df_pivot['Area'].unique()
        tabs = st.tabs([str(a) for a in areas_presentes])
        
        for i, area in enumerate(areas_presentes):
            with tabs[i]:
                df_area = df_pivot[df_pivot['Area'] == area].drop(columns=['Area', 'ID'])
                st.dataframe(df_area.fillna("-"), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"❌ Error en el procesamiento: {e}")

def vista_biometrico():
    st.title("⏱️ Módulo de Depuración Biométrica")
    archivo = st.file_uploader("📥 Cargar Transaction.csv", type=['csv'])
    
    if archivo:
        try:
            # Lectura del archivo original
            df_marcas = pd.read_csv(archivo, skiprows=4)
            df_marcas.columns = df_marcas.columns.str.strip() # Limpiar encabezados
            
            # Extraer empleados únicos para la tabla de edición
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            empleados_unicos['ID'] = empleados_unicos['ID'].astype(str)

            if 'mapeo_areas' not in st.session_state:
                empleados_unicos['Area'] = "ADMINISTRACION"
                st.session_state['mapeo_areas'] = empleados_unicos
            
            st.write("### 1️⃣ Asignación de Áreas")
            areas_editadas = st.data_editor(
                st.session_state['mapeo_areas'],
                column_config={
                    "Area": st.column_config.SelectboxColumn(
                        "Área", options=["AREA TECNICA", "SAC", "ADMINISTRACION"], required=True
                    )
                },
                disabled=["ID", "Full Name"],
                hide_index=True,
                use_container_width=True,
                key="editor_biometrico"
            )
            
            if st.button("🚀 Generar Reporte Depurado", type="primary"):
                procesar_marcas(df_marcas, areas_editadas)
                
        except Exception as e:
            st.error(f"❌ Error al cargar archivo: {e}")
