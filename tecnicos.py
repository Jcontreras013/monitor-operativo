# tecnicos.py
import streamlit as st
import pandas as pd
import re

def procesar_evaluacion_puntos(archivo_registro, df_nube):
    """
    Realiza el cotejo entre el Registro manual y las Actividades de la nube (Google Sheets).
    Aplica las reglas de puntuación: 1, 2 o 2.5 puntos.
    """
    try:
        # 1. Cargar Registro Manual ( Mozart )
        if archivo_registro.name.endswith('.csv'):
            df_reg = pd.read_csv(archivo_registro, skiprows=3)
        else:
            df_reg = pd.read_excel(archivo_registro, skiprows=3)
        
        df_reg.columns = df_reg.columns.str.strip()
        
        # 2. Validar Datos de la Nube
        if df_nube is None or df_nube.empty:
            st.error("No hay datos cargados desde Google Sheets. Sincroniza el monitor primero.")
            return None
        
        df_sheets = df_nube.copy()
        df_sheets.columns = df_sheets.columns.str.strip().str.upper()

        # 3. Limpieza y Preparación para el Cruce
        # Aseguramos que el Número de Orden sea string y esté limpio
        df_reg['Número Orden'] = df_reg['Número Orden'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        
        col_num_nube = 'NUM' if 'NUM' in df_sheets.columns else next((c for c in df_sheets.columns if 'ORDEN' in c), None)
        if not col_num_nube:
            st.error("No se encontró la columna de Número de Orden (NUM) en los datos de la nube.")
            return None
        
        df_sheets[col_num_nube] = df_sheets[col_num_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 4. Filtrado Inicial: Región ISLAS y Estado ACEPTABLE
        df_reg_islas = df_reg[
            (df_reg['Región'].astype(str).str.upper() == 'ISLAS') & 
            (df_reg['Estado'].astype(str).str.upper() == 'ACEPTABLE')
        ].copy()

        if df_reg_islas.empty:
            st.warning("No se encontraron órdenes 'ACEPTABLE' para la región 'ISLAS' en el archivo de registro.")
            return None

        # 5. Cruce (Merge) para obtener comentarios líquidos
        df_final = pd.merge(
            df_reg_islas, 
            df_sheets, 
            left_on='Número Orden', 
            right_on=col_num_nube, 
            how='inner'
        )

        # 6. Lógica de Puntuación
        def calcular_puntos(row):
            actividad = str(row.get('Actividad', '')).upper()
            # Combinamos todos los campos de comentarios disponibles para la búsqueda
            comentarios_reg = (str(row.get('Comentario Evaluación', '')) + " " + str(row.get('Comentario Modificación', ''))).lower()
            comentario_nube = str(row.get('COMENTARIO', '')).lower()
            todos_los_comentarios = comentarios_reg + " " + comentario_nube

            # Directriz: Traslados e Instalaciones (2.5 puntos)
            if any(x in actividad for x in ['INSTALACION', 'TRASLADO']):
                return 2.5
            
            # Directriz: SOPFIBRAS
            if 'SOPFIBRA' in actividad:
                # Buscamos evidencias de cambio de fibra en cualquier comentario
                cambio_fibra_keywords = ['cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 'se cambio drop', 'fibra nueva']
                if any(kw in todos_los_comentarios for kw in cambio_fibra_keywords):
                    return 2.0 # Con cambio de fibra
                return 1.0 # Normal (sin cambio)
            
            return 0.0

        df_final['PUNTOS'] = df_final.apply(calcular_puntos, axis=1)

        # 7. Consolidado por Técnico
        reporte = df_final.groupby('Técnico').agg(
            Ordenes_Aceptables=('Número Orden', 'count'),
            Total_Puntos=('PUNTOS', 'sum')
        ).reset_index().sort_values(by='Total_Puntos', ascending=False)

        return reporte

    except Exception as e:
        st.error(f"Error procesando los puntos: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Rendimiento por Puntos")
    st.info("Esta sección cruza el **Registro de Calidad** con los comentarios de la nube para calcular la productividad.")

    # Acceso automático a la base de Google Sheets ya cargada en app.py
    df_base_nube = st.session_state.get('df_base', None)

    if df_base_nube is not None:
        st.success("🔗 Conexión con Google Sheets activa.")
        
        # Cargador para el Registro manual
        archivo_reg = st.file_uploader("Subir archivo de Registro (Mozart)", type=['csv', 'xlsx'], key="reg_puntos")

        if archivo_reg:
            if st.button("Calcular Puntos de Técnicos", type="primary", use_container_width=True):
                resultado = procesar_evaluacion_puntos(archivo_reg, df_base_nube)
                
                if resultado is not None:
                    st.divider()
                    st.subheader("📊 Resultados de Evaluación - Región ISLAS")
                    st.dataframe(resultado, use_container_width=True, hide_index=True)
                    
                    # Opción de descarga
                    csv = resultado.to_csv(index=False).encode('utf-8')
                    st.download_button("Descargar Reporte de Puntos", csv, "puntos_tecnicos_islas.csv", "text/csv", use_container_width=True)
    else:
        st.warning("⚠️ Los datos de la nube no están sincronizados. Por favor, ve al Monitor y presiona 'Actualizar desde la nube'.")
