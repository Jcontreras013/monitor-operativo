import pandas as pd
import streamlit as st

def procesar_biometrico(df_marcas, df_areas):
    st.subheader("📊 Reporte Biométrico Inteligente")
    
    # 1. Unir con las áreas (Aseguramos que los ID sean texto para evitar errores)
    df_marcas['ID'] = df_marcas['ID'].astype(str)
    df_areas['ID'] = df_areas['ID'].astype(str)
    df_completo = pd.merge(df_marcas, df_areas[['ID', 'Area']], on='ID', how='left')

    # 2. Formatear Fecha y Hora para ordenar cronológicamente
    # Usamos errors='coerce' por si alguna fila viene vacía
    df_completo['Datetime'] = pd.to_datetime(df_completo['Date'] + ' ' + df_completo['Time'], format='%d/%m/%Y %H:%M', errors='coerce')
    df_completo = df_completo.dropna(subset=['Datetime']).sort_values(['ID', 'Datetime'])

    # 3. Eliminar marcas dobles por error humano (menos de 15 min de diferencia)
    df_completo['Time_Diff'] = df_completo.groupby(['ID', 'Date'])['Datetime'].diff()
    df_limpio = df_completo[(df_completo['Time_Diff'].isna()) | (df_completo['Time_Diff'] > pd.Timedelta(minutes=15))].copy()

    # 4. Función de Inferencia Lógica según el Área
    def etiquetar_marcas(grupo):
        # Asegurarnos de no fallar si no hay área definida
        area = str(grupo['Area'].iloc[0]).strip().upper() if pd.notna(grupo['Area'].iloc[0]) else ""
        n = len(grupo)
        etiquetas = [''] * n
        
        # Aplicamos tus reglas estrictas de eventos
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
            # Comportamiento por defecto si el ID no tiene área
            if n >= 1: etiquetas[0] = "Entrada"
            if n >= 2: etiquetas[-1] = "Salida"
            
        grupo['Evento'] = etiquetas
        return grupo

    # Aplicar la lógica de etiquetas día por día, empleado por empleado
    df_final = df_limpio.groupby(['ID', 'Date'], group_keys=False).apply(etiquetar_marcas)
    
    # Limpiar lo que no es un evento principal (ej. una 6ta marca accidental)
    df_final = df_final[df_final['Evento'] != '']

    # 5. Formato innegociable HH:mm:ss
    df_final['Time'] = df_final['Datetime'].dt.strftime('%H:%M:%S')

    # 6. Mostrar Pestañas por Departamento
    st.write("### Resultados por Departamento")
    areas_presentes = [a for a in df_final['Area'].dropna().unique() if str(a).strip() != ""]
    
    if not areas_presentes:
        st.warning("⚠️ No se detectaron áreas. Mostrando todos los registros generales.")
        st.dataframe(df_final[['Full Name', 'Date', 'Time', 'Evento']], use_container_width=True)
        return

    tabs = st.tabs(areas_presentes)
    
    for i, area in enumerate(areas_presentes):
        with tabs[i]:
            df_area = df_final[df_final['Area'] == area].reset_index(drop=True)
            st.dataframe(df_area[['Full Name', 'Date', 'Time', 'Evento']], use_container_width=True)

def vista_biometrico():
    st.title("⏱️ Módulo de Depuración Biométrica Inteligente")
    st.markdown("Carga el archivo ZKTeco y tu plantilla de áreas. El sistema limpiará marcas dobles y asignará las entradas, almuerzos y salidas de forma autónoma.")
    
    col1, col2 = st.columns(2)
    with col1:
        arch_biometrico = st.file_uploader("1️⃣ Cargar Transaction.csv", type=['csv'])
    with col2:
        arch_areas = st.file_uploader("2️⃣ Cargar Plantilla_Areas.xlsx", type=['xlsx'])
        
    if arch_biometrico and arch_areas:
        try:
            # Saltamos las primeras 4 filas basura del ZKTeco
            df_marcas = pd.read_csv(arch_biometrico, skiprows=4)
            df_areas = pd.read_excel(arch_areas)
            procesar_biometrico(df_marcas, df_areas)
        except Exception as e:
            st.error(f"❌ Error procesando los archivos: {e}")
