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
    st.markdown("Sube tu archivo `Transaction.csv`. Asigna el área a cada empleado en la tabla y presiona procesar.")
    
    archivo = st.file_uploader("📥 Cargar Transaction.csv", type=['csv'])
    
    if archivo:
        try:
            # === LECTURA 100% SEGURA EN MEMORIA (Evita el KeyError) ===
            content = archivo.getvalue().decode('utf-8', errors='replace')
            lineas = content.splitlines()
            
            # Buscar dónde empiezan realmente los datos
            inicio_datos = -1
            for i, linea in enumerate(lineas):
                if "ID" in linea and "Full Name" in linea:
                    inicio_datos = i
                    break
                    
            if inicio_datos == -1:
                st.error("❌ El archivo no es válido o no tiene las columnas 'Full Name' e 'ID'.")
                return
                
            # Extraer solo desde la línea correcta y convertir a DataFrame
            csv_valido = "\n".join(lineas[inicio_datos:])
            df_marcas = pd.read_csv(io.StringIO(csv_valido))
            
            # Limpieza extrema de nombres de columnas (Quita espacios fantasmas)
            df_marcas.columns = [str(col).strip() for col in df_marcas.columns]
            
            # Verificación de diagnóstico: si vuelve a fallar te dirá exactamente qué vio el sistema
            if 'ID' not in df_marcas.columns:
                st.error(f"❌ Las columnas detectadas son: {df_marcas.columns.tolist()}. No se encontró 'ID'.")
                return
                
            df_marcas['ID'] = df_marcas['ID'].astype(str).str.strip()
            df_marcas['Full Name'] = df_marcas['Full Name'].astype(str).str.strip()
            
            # Lista única de empleados
            empleados_unicos = df_marcas[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
            empleados_unicos['Area'] = "ADMINISTRACION" # Valor por defecto
            
            # Restaurar áreas si ya se habían editado en la sesión para evitar perder tu trabajo
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
