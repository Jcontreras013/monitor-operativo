# tecnicos.py
import streamlit as st
import pandas as pd
import glob
import os
import re

def buscar_archivos_locales():
    """
    Busca dinámicamente los archivos en el directorio de trabajo.
    Ignora cualquier número entre paréntesis al final del nombre usando expresiones regulares.
    """
    # Patrón para identificar cualquier archivo que contenga "Registro" (Control de Calidad)
    archivos_registro = [f for f in glob.glob("*.csv") + glob.glob("*.xlsx") if re.search(r'Registro(?:\s*\(\d+\))?\.csv|\.xlsx', f, re.IGNORECASE)]
    
    # Patrón para identificar el archivo de la nube (ajusta 'actividades' según el prefijo que suelan usar al descargar)
    archivos_nube = [f for f in glob.glob("*.csv") + glob.glob("*.xlsx") if re.search(r'actividades(?:\s*\(\d+\))?\.csv|\.xlsx', f, re.IGNORECASE)]
    
    archivo_registro = max(archivos_registro, key=os.path.getmtime) if archivos_registro else None
    archivo_nube = max(archivos_nube, key=os.path.getmtime) if archivos_nube else None
    
    return archivo_registro, archivo_nube

def procesar_puntos(ruta_registro, ruta_nube, es_buffer=False):
    """
    Contiene toda la lógica de negocio para cruzar y evaluar las órdenes.
    El parámetro 'es_buffer' permite que Streamlit procese los archivos si se suben manualmente.
    """
    try:
        # 1. Cargar el archivo de Control de Calidad (Registro) saltando los títulos
        if (es_buffer and ruta_registro.name.endswith('.csv')) or (not es_buffer and str(ruta_registro).endswith('.csv')):
            df_registro = pd.read_csv(ruta_registro, skiprows=3)
        else:
            df_registro = pd.read_excel(ruta_registro, skiprows=3)
            
        # 2. Cargar el archivo de Actividades de la Nube
        if (es_buffer and ruta_nube.name.endswith('.csv')) or (not es_buffer and str(ruta_nube).endswith('.csv')):
            df_nube = pd.read_csv(ruta_nube)
        else:
            df_nube = pd.read_excel(ruta_nube)
    except Exception as e:
        st.error(f"Error al leer los archivos: {e}")
        return None

    # Limpieza de espacios en los nombres de las columnas
    df_registro.columns = df_registro.columns.str.strip()
    df_nube.columns = df_nube.columns.str.strip()

    # Detectar dinámicamente la columna de Número de Orden en la nube
    col_orden_nube = next((col for col in df_nube.columns if 'ORDEN' in str(col).upper()), None)
    if not col_orden_nube:
        st.error("No se pudo identificar la columna de Número de Orden en el archivo de Actividades.")
        return None

    # Detectar dinámicamente las columnas de comentarios líquidos en la nube
    cols_liquidos = [col for col in df_nube.columns if any(kw in str(col).upper() for kw in ['COMENTARIO', 'LIQUIDO', 'OBSERVACION', 'NOTA'])]

    # 3. Hacer la comparación/cruce exacto (Merge)
    df_merged = pd.merge(
        df_registro,
        df_nube,
        left_on='Número Orden',
        right_on=col_orden_nube,
        how='inner',
        suffixes=('_reg', '_nube')
    )

    # 4. Aislar la muestra de evaluación: Sólo Región ISLAS y Estado ACEPTABLE
    if 'Región' in df_merged.columns and 'Estado' in df_merged.columns:
        df_filtrado = df_merged[
            (df_merged['Región'].astype(str).str.strip().str.upper() == 'ISLAS') &
            (df_merged['Estado'].astype(str).str.strip().str.upper() == 'ACEPTABLE')
        ].copy()
    else:
        st.error("Las columnas 'Región' o 'Estado' no se encontraron en la estructura del Registro.")
        return None

    if df_filtrado.empty:
        st.warning("No hay órdenes cruzadas en estado ACEPTABLE para la región ISLAS en esta fecha.")
        return pd.DataFrame()

    # Consolidar columnas donde buscaremos las justificaciones
    columnas_evaluacion = ['Comentario Evaluación', 'Comentario Modificación'] + cols_liquidos

    # 5. Función de asignación de directrices
    def evaluar_orden_y_comentarios(row):
        actividad = str(row.get('Actividad', '')).strip().upper()
        
        # Concatenar todos los comentarios físicos de la orden y líquidos
        comentarios_totales = " ".join([str(row.get(col, '')) for col in columnas_evaluacion if pd.notna(row.get(col))]).lower()
        
        # Diccionario de terminología técnica para el cambio de material
        keywords_cambio = [
            'cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 
            'reemplazo fibra', 'se cambia fibra', 'se tiro fibra', 
            'cambio drop', 'se instalo fibra nueva'
        ]
        
        # Directriz: Traslados externos e Instalaciones (100% completas)
        if 'TRASLADO EXTERNO' in actividad or 'INSTALACION' in actividad or 'TRASLADO' in actividad:
            return 2.5
            
        # Directriz: SOPFIBRAS (Con o sin cambio)
        elif 'SOPFIBRA' in actividad:
            if any(kw in comentarios_totales for kw in keywords_cambio):
                return 2.0
            return 1.0
            
        return 0.0

    df_filtrado['Puntos_Obtenidos'] = df_filtrado.apply(evaluar_orden_y_comentarios, axis=1)
    
    # 6. Agrupación final por técnico
    reporte_final = df_filtrado.groupby('Técnico').agg(
        Órdenes_Aceptables=('Número Orden', 'count'),
        Puntos_Totales=('Puntos_Obtenidos', 'sum')
    ).reset_index()
    
    reporte_final = reporte_final.sort_values(by='Puntos_Totales', ascending=False)
    return reporte_final

def render_modulo_tecnicos():
    """
    Función que renderiza la vista en tu Monitor Operativo.
    Llámala desde tu app.py o controlador principal.
    """
    st.subheader("🛠️ Evaluación de Puntos por Técnico (Región ISLAS)")
    st.markdown("Comparativa automatizada: **Registro de Calidad vs Comentarios Líquidos (Nube)**")
    
    # Intento de carga automática desde el directorio
    archivo_registro_local, archivo_nube_local = buscar_archivos_locales()
    
    if archivo_registro_local and archivo_nube_local:
        st.success(f"Archivos detectados automáticamente:\n- {archivo_registro_local}\n- {archivo_nube_local}")
        if st.button("Generar Reporte (Archivos Locales)"):
            df_reporte = procesar_puntos(archivo_registro_local, archivo_nube_local, es_buffer=False)
            if df_reporte is not None and not df_reporte.empty:
                st.dataframe(df_reporte, use_container_width=True)
    else:
        st.info("No se detectaron los archivos en la carpeta de ejecución automáticamente. Por favor, cárgalos manualmente.")
        
    st.divider()
    
    # Opción de carga manual en caso de que los archivos estén en otra ruta
    st.write("**Carga Manual de Archivos**")
    col1, col2 = st.columns(2)
    with col1:
        archivo_registro_ui = st.file_uploader("1. Archivo de Registro (Calidad)", type=['csv', 'xlsx'])
    with col2:
        archivo_nube_ui = st.file_uploader("2. Archivo Actividades (Nube)", type=['csv', 'xlsx'])

    if archivo_registro_ui and archivo_nube_ui:
        if st.button("Procesar Comparativa Manual", type="primary"):
            with st.spinner("Leyendo cruces y comentarios líquidos..."):
                df_reporte = procesar_puntos(archivo_registro_ui, archivo_nube_ui, es_buffer=True)
                if df_reporte is not None and not df_reporte.empty:
                    st.dataframe(df_reporte, use_container_width=True)
                    
                    # Funcionalidad opcional para exportar el consolidado final
                    csv_export = df_reporte.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="Descargar Consolidado CSV",
                        data=csv_export,
                        file_name="Reporte_Puntos_Tecnicos_ISLAS.csv",
                        mime="text/csv",
                    )
