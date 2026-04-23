# tecnicos.py
import streamlit as st
import pandas as pd
import re

def procesar_evaluacion_puntos(archivo_registro, df_nube):
    """
    Realiza el cotejo entre el Registro manual y las Actividades de la nube (Google Sheets).
    Aplica las reglas de puntuación con protecciones contra columnas vacías o tipo float.
    """
    try:
        # 1. Cargar Registro Manual (Mozart)
        if archivo_registro.name.endswith('.csv'):
            df_reg = pd.read_csv(archivo_registro, skiprows=3)
        else:
            df_reg = pd.read_excel(archivo_registro, skiprows=3)
        
        # ESCUDO ANTI-FLOAT: Convertir explícitamente a texto antes de limpiar
        df_reg.columns = df_reg.columns.astype(str).str.strip().str.upper()
        
        # 2. Validar Datos de la Nube
        if df_nube is None or df_nube.empty:
            st.error("No hay datos cargados desde Google Sheets. Sincroniza el monitor primero.")
            return None
        
        df_sheets = df_nube.copy()
        df_sheets.columns = df_sheets.columns.astype(str).str.strip().str.upper()

        # 3. Búsqueda Dinámica de Columnas (buscando seguro dentro de strings)
        col_orden_reg  = next((c for c in df_reg.columns if 'ORDEN' in str(c)), None)
        col_region_reg = next((c for c in df_reg.columns if 'REGI' in str(c)), None)
        col_estado_reg = next((c for c in df_reg.columns if 'ESTADO' in str(c)), None)
        col_tec_reg    = next((c for c in df_reg.columns if 'TÉCNICO' in str(c) or 'TECNICO' in str(c)), None)
        col_act_reg    = next((c for c in df_reg.columns if 'ACTIVIDAD' in str(c)), None)
        col_eval_reg   = next((c for c in df_reg.columns if 'EVALUACI' in str(c) and 'COMENTARIO' in str(c)), None)
        col_mod_reg    = next((c for c in df_reg.columns if 'MODIFICA' in str(c) and 'COMENTARIO' in str(c)), None)

        if not col_orden_reg:
            st.error("❌ No se encontró la columna de Órdenes en el archivo. Asegúrate de subir la pestaña que dice 'Registro'.")
            return None

        # Búsqueda Dinámica en la Nube
        col_num_nube = 'NUM' if 'NUM' in df_sheets.columns else next((c for c in df_sheets.columns if 'ORDEN' in str(c)), None)
        if not col_num_nube:
            st.error("❌ No se encontró la columna de Número de Orden (NUM) en los datos de la nube.")
            return None

        # Limpiar y estandarizar los números de orden para el cruce exacto
        df_reg[col_orden_reg] = df_reg[col_orden_reg].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        df_sheets[col_num_nube] = df_sheets[col_num_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 4. Filtrado Inicial: Región ISLAS y Estado ACEPTABLE
        df_reg_islas = df_reg[
            (df_reg[col_region_reg].astype(str).str.strip().str.upper() == 'ISLAS') & 
            (df_reg[col_estado_reg].astype(str).str.strip().str.upper() == 'ACEPTABLE')
        ].copy()

        if df_reg_islas.empty:
            st.warning("⚠️ No se encontraron órdenes en estado 'ACEPTABLE' para la región 'ISLAS' en este reporte.")
            return pd.DataFrame()

        # 5. Cruce (Merge) para obtener comentarios líquidos de la nube
        df_final = pd.merge(
            df_reg_islas, 
            df_sheets, 
            left_on=col_orden_reg, 
            right_on=col_num_nube, 
            how='inner',
            suffixes=('_REG', '_NUBE')
        )

        # 6. Lógica de Puntuación Segura
        def calcular_puntos(row):
            # Extracción segura evitando valores float (NaN) de celdas vacías
            actividad = str(row[col_act_reg] if col_act_reg in row else row.get('ACTIVIDAD', '')).strip().upper()
            
            val_eval = str(row[col_eval_reg]) if col_eval_reg in row and pd.notna(row[col_eval_reg]) else ""
            val_mod = str(row[col_mod_reg]) if col_mod_reg in row and pd.notna(row[col_mod_reg]) else ""
            val_nube = str(row['COMENTARIO']) if 'COMENTARIO' in row and pd.notna(row['COMENTARIO']) else ""

            # Combinar comentarios
            todos_los_comentarios = f"{val_eval} {val_mod} {val_nube}".lower()

            # Directriz: Traslados e Instalaciones (2.5 puntos)
            if any(x in actividad for x in ['INSTALACION', 'TRASLADO']):
                return 2.5
            
            # Directriz: SOPFIBRAS
            if 'SOPFIBRA' in actividad:
                # Buscamos evidencias de cambio de fibra en cualquier comentario
                cambio_fibra_keywords = ['cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 'se cambio drop', 'fibra nueva']
                if any(kw in todos_los_comentarios for kw in cambio_fibra_keywords):
                    return 2.0 # Con cambio de fibra reportado
                return 1.0 # Soporte Normal (sin cambio)
            
            return 0.0 # Cualquier otra orden no contemplada

        # Aplicar los puntos
        df_final['PUNTOS'] = df_final.apply(calcular_puntos, axis=1)

        # 7. Consolidado por Técnico
        reporte = df_final.groupby(col_tec_reg).agg(
            Ordenes_Aceptables=(col_orden_reg, 'count'),
            Total_Puntos=('PUNTOS', 'sum')
        ).reset_index()
        
        # Renombrar para que se vea estético y ordenar de mayor a menor
        reporte = reporte.rename(columns={col_tec_reg: 'Técnico', 'Ordenes_Aceptables': 'Órdenes Aceptables', 'Total_Puntos': 'Total Puntos'})
        reporte = reporte.sort_values(by='Total Puntos', ascending=False)

        return reporte

    except Exception as e:
        st.error(f"Error procesando los puntos: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Rendimiento por Puntos")
    st.info("Esta sección cruza el **Registro de Calidad (Mozart)** con los **Comentarios de la Nube** para calcular la productividad en base a reglas operativas.")

    # Acceso automático a la base de Google Sheets ya cargada en app.py
    df_base_nube = st.session_state.get('df_base', None)

    if df_base_nube is not None and not df_base_nube.empty:
        st.success("🔗 **Conexión con Google Sheets activa y lista para cruzar.**")
        
        # Cargador para el Registro manual
        archivo_reg = st.file_uploader("📂 Sube el archivo de Registro de Calidad (Pestaña 'Registro')", type=['csv', 'xlsx'], key="reg_puntos")

        if archivo_reg:
            if st.button("🚀 Calcular Puntos de Técnicos", type="primary", use_container_width=True):
                with st.spinner("Analizando comentarios líquidos y directrices..."):
                    resultado = procesar_evaluacion_puntos(archivo_reg, df_base_nube)
                    
                    if resultado is not None and not resultado.empty:
                        st.divider()
                        st.subheader("📊 Resultados de Evaluación - Región ISLAS")
                        st.dataframe(resultado, use_container_width=True, hide_index=True)
                        
                        # Opción de descarga CSV
                        csv = resultado.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Descargar Reporte de Puntos", 
                            data=csv, 
                            file_name="Reporte_Puntos_Tecnicos_ISLAS.csv", 
                            mime="text/csv", 
                            use_container_width=True
                        )
    else:
        st.warning("⚠️ Los datos de la nube aún no están cargados. Por favor, asegúrate de que el Monitor principal se haya sincronizado.")
