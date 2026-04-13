import pandas as pd
import streamlit as st

def procesar_biometrico(df):
    st.subheader("📊 Reporte Biométrico Depurado")
    
    # Estandarizar nombres de columnas a minúsculas temporalmente para evitar errores de lectura
    df.columns = df.columns.str.strip().str.lower()
    
    # Identificar las columnas reales del Excel (soporta variaciones comunes)
    col_name = 'name' if 'name' in df.columns else 'nombre'
    col_time = 'time' if 'time' in df.columns else 'hora'
    col_evento = 'evento' if 'evento' in df.columns else 'estado'
    col_area = 'area' if 'area' in df.columns else 'departamento'

    # Validar que vengan las columnas obligatorias
    if col_name not in df.columns or col_time not in df.columns:
        st.error(f"❌ El reporte debe contener obligatoriamente las columnas '{col_name}' y '{col_time}'.")
        return

    # Aplicar formato de tiempo estricto HH:mm:ss
    try:
        df[col_time] = pd.to_datetime(df[col_time]).dt.strftime('%H:%M:%S')
    except Exception as e:
        st.warning(f"⚠️ No se pudo formatear la columna de tiempo. Verifica que los datos sean horas válidas. Error: {e}")

    # Diccionario de eventos permitidos por área según tu especificación
    reglas = {
        "AREA TECNICA": ["Entrada", "Salida"],
        "SAC": ["Entrada", "Salida Almuerzo", "Entrada Almuerzo", "Break", "Salida"],
        "ADMINISTRACION": ["Entrada", "Salida Almuerzo", "Entrada Almuerzo", "Salida"]
    }

    # Si el reporte no trae columna de área, permitimos seleccionarla manualmente
    if col_area not in df.columns:
        st.info("ℹ️ El reporte no tiene columna de 'Área'. Selecciona a qué departamento pertenece este archivo:")
        area_seleccionada = st.selectbox("Filtrar por Área:", ["AREA TECNICA", "SAC", "ADMINISTRACION"])
        
        eventos_permitidos = reglas[area_seleccionada]
        
        if col_evento in df.columns:
            # Depurar solo los eventos válidos para el área seleccionada
            df_depurado = df[df[col_evento].isin(eventos_permitidos)]
            st.success(f"Mostrando registros depurados para: {area_seleccionada}")
            st.dataframe(df_depurado[[col_name, col_time, col_evento]], use_container_width=True)
        else:
            st.warning("No se encontró una columna de 'evento' o 'estado'. Mostrando datos sin depurar eventos:")
            st.dataframe(df[[col_name, col_time]], use_container_width=True)
            
    else:
        # Si el Excel trae las áreas de todos los empleados, separamos por pestañas
        st.write("### Resultados por Departamento")
        areas_presentes = df[col_area].dropna().unique()
        
        # Crear pestañas en Streamlit para cada área detectada
        tabs = st.tabs([str(a).upper() for a in areas_presentes if str(a).upper() in reglas])
        
        for i, area in enumerate([a for a in areas_presentes if str(a).upper() in reglas]):
            area_upper = str(area).upper().strip()
            eventos_permitidos = reglas[area_upper]
            
            with tabs[i]:
                if col_evento in df.columns:
                    df_filtrado = df[(df[col_area].str.upper().str.strip() == area_upper) & 
                                     (df[col_evento].isin(eventos_permitidos))]
                    # Reiniciar el índice para que la tabla se vea limpia
                    df_filtrado = df_filtrado.reset_index(drop=True)
                    st.dataframe(df_filtrado[[col_name, col_time, col_evento, col_area]], use_container_width=True)
                else:
                    st.warning("Falta columna de 'evento' para poder depurar. Mostrando marcas generales.")
                    df_filtrado = df[df[col_area].str.upper().str.strip() == area_upper]
                    st.dataframe(df_filtrado[[col_name, col_time, col_area]], use_container_width=True)


def vista_biometrico():
    """
    Función principal que se llama desde app.py
    """
    st.title("⏱️ Módulo de Depuración Biométrica")
    st.markdown("Carga el archivo del reloj biométrico. El sistema limpiará las marcas dependiendo de si el personal es de **Área Técnica**, **SAC** o **Administración**.")
    
    archivo = st.file_uploader("📥 Cargar reporte (Excel o CSV)", type=['xlsx', 'csv'])
    
    if archivo:
        try:
            if archivo.name.endswith('.xlsx'):
                df = pd.read_excel(archivo)
            else:
                df = pd.read_csv(archivo)
            procesar_biometrico(df)
        except Exception as e:
            st.error(f"❌ Error al leer el archivo: {e}")
