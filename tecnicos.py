# tecnicos.py
import streamlit as st
import pandas as pd
import re

def procesar_puntos(archivo_registro, df_nube):
    """
    Contiene toda la lógica de negocio para cruzar el archivo local de Registro subido manualmente
    con el DataFrame de Actividades que ya viene automáticamente de Google Sheets.
    """
    try:
        # 1. Cargar el archivo de Control de Calidad (Registro) saltando los títulos
        if archivo_registro.name.endswith('.csv'):
            df_registro = pd.read_csv(archivo_registro, skiprows=3)
        else:
            df_registro = pd.read_excel(archivo_registro, skiprows=3)
    except Exception as e:
        st.error(f"Error al leer el archivo de Registro: {e}")
        return None

    if df_nube is None or df_nube.empty:
        st.error("El DataFrame de Google Sheets está vacío o no se ha cargado en memoria.")
        return None

    # Limpieza de espacios en los nombres de las columnas
    df_registro.columns = df_registro.columns.str.strip()
    df_nube_temp = df_nube.copy()
    df_nube_temp.columns = df_nube_temp.columns.str.strip()

    # Detectar dinámicamente la columna de Número de Orden en la nube (generalmente 'NUM')
    col_orden_nube = 'NUM' if 'NUM' in df_nube_temp.columns else next((col for col in df_nube_temp.columns if 'ORDEN' in str(col).upper()), None)
    
    if not col_orden_nube:
        st.error("No se pudo identificar la columna de Número de Orden en los datos de Google Sheets.")
        return None

    if 'Número Orden' not in df_registro.columns:
        st.error("El archivo subido no parece ser el Registro de Calidad correcto (Falta columna 'Número Orden').")
        return None

    # Estandarizar columnas de cruce para evitar fallos por decimales o espacios
    df_registro['Número Orden'] = df_registro['Número Orden'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df_nube_temp[col_orden_nube] = df_nube_temp[col_orden_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    # Detectar dinámicamente las columnas de comentarios líquidos en la nube
    cols_liquidos = [col for col in df_nube_temp.columns if any(kw in str(col).upper() for kw in ['COMENTARIO', 'LIQUIDO', 'OBSERVACION', 'NOTA'])]

    # 3. Hacer la comparación/cruce exacto (Merge)
    df_merged = pd.merge(
        df_registro,
        df_nube_temp,
        left_on='Número Orden',
        right_on=col_orden_nube,
        how='inner',
        suffixes=('_reg', '_nube')
    )

    # Buscar el nombre de la columna Estado de calidad (evitando colisiones con la nube)
    col_estado_calidad = 'Estado_reg' if 'Estado_reg' in df_merged.columns else ('Estado' if 'Estado' in df_registro.columns else None)

    # 4. Aislar la muestra de evaluación: Sólo Región ISLAS y Estado ACEPTABLE
    if 'Región' in df_merged.columns and col_estado_calidad:
        df_filtrado = df_merged[
            (df_merged['Región'].astype(str).str.strip().str.upper() == 'ISLAS') &
            (df_merged[col_estado_calidad].astype(str).str.strip().str.upper() == 'ACEPTABLE')
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
        actividad = str(row.get('Actividad_reg', row.get('Actividad', row.get('ACTIVIDAD', '')))).strip().upper()
        
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
    col_tecnico = 'Técnico_reg' if 'Técnico_reg' in df_filtrado.columns else ('Técnico' if 'Técnico' in df_registro.columns else 'TECNICO')
    
    reporte_final = df_filtrado.groupby(col_tecnico).agg(
        Órdenes_Aceptables=('Número Orden', 'count'),
        Puntos_Totales=('Puntos_Obtenidos', 'sum')
    ).reset_index()
    
    reporte_final = reporte_final.rename(columns={col_tecnico: 'Técnico'})
    reporte_final = reporte_final.sort_values(by='Puntos_Totales', ascending=False)
    return reporte_final

def render_modulo_tecnicos():
    """
    Renderiza la vista en el Monitor Operativo.
    Carga manual del Registro y cruce automático con df_base.
    """
    st.subheader("🏆 Evaluación de Puntos por Técnico (Región ISLAS)")
    st.markdown("Comparativa híbrida: **Registro de Calidad (Manual) vs Actividades (Google Sheets Automático)**")
    
    # Extraer los datos de la nube que ya están en la sesión de la app
    df_nube_session = st.session_state.get('df_base', None)
    
    if df_nube_session is None or df_nube_session.empty:
        st.warning("⚠️ Los datos de Actividades aún no están cargados. Asegúrate de que el Monitor Operativo se haya sincronizado en el panel lateral.")
        return

    st.success(f"✅ **Base de Datos conectada:** Datos de Google Sheets cargados en memoria listos para cruzar.")
    st.divider()
    
    # Subida de archivo SOLO para el Registro de Calidad
    archivo_registro_ui = st.file_uploader("📂 Sube el archivo de Registro de Calidad (.csv o .xlsx)", type=['csv', 'xlsx'])
    
    if archivo_registro_ui:
        if st.button("🚀 Procesar y Generar Reporte", type="primary", use_container_width=True):
            with st.spinner("Cruzando calidad con comentarios líquidos de Google Sheets..."):
                df_reporte = procesar_puntos(archivo_registro_ui, df_nube_session)
                
                if df_reporte is not None and not df_reporte.empty:
                    st.dataframe(df_reporte, use_container_width=True)
                    
                    csv_export = df_reporte.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Descargar Consolidado CSV",
                        data=csv_export,
                        file_name="Reporte_Puntos_Tecnicos_ISLAS.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
