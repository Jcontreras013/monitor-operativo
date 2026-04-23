# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata

def limpiar_columnas(df):
    """Normaliza encabezados: quita tildes, espacios y pasa a mayúsculas."""
    cols_limpias = []
    for col in df.columns:
        c = str(col).strip().upper()
        c = ''.join(char for char in unicodedata.normalize('NFKD', c) if unicodedata.category(char) != 'Mn')
        cols_limpias.append(c)
    df.columns = cols_limpias
    return df

def procesar_evaluacion_puntos(archivo_registro, df_nube):
    try:
        # 1. CARGA DEL REGISTRO (MOZART) - El Maestro de Órdenes
        if archivo_registro.name.endswith('.csv'):
            try:
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str)
            except UnicodeDecodeError:
                archivo_registro.seek(0)
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw = pd.read_excel(archivo_registro, header=None, dtype=str)
        
        # Localizador dinámico de encabezados en Mozart
        header_idx = -1
        for i, row in df_raw.iterrows():
            fila_texto = " ".join(row.dropna().astype(str)).upper()
            if 'ORDEN' in fila_texto and 'ACTIVIDAD' in fila_texto:
                header_idx = i
                break
        
        if header_idx == -1:
            st.error("❌ No se detectaron las columnas en el Registro. Sube la pestaña 'Registro'.")
            return None
            
        df_reg = df_raw.iloc[header_idx + 1:].copy()
        df_reg.columns = df_raw.iloc[header_idx]
        df_reg = limpiar_columnas(df_reg.reset_index(drop=True))
        
        # 2. PREPARAR DATOS DE LA NUBE (GOOGLE SHEETS)
        df_sheets = limpiar_columnas(df_nube.copy())

        # 3. IDENTIFICACIÓN DE COLUMNAS CLAVE
        col_orden_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_region_reg = next((c for c in df_reg.columns if 'REGI' in c), None)
        col_estado_reg = next((c for c in df_reg.columns if 'ESTADO' in c), None)
        col_tec_reg = next((c for c in df_reg.columns if 'TECNICO' in c), None)
        col_act_reg = next((c for c in df_reg.columns if 'ACTIVIDAD' in c), None)

        col_num_nube = next((c for c in df_sheets.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        
        # OJO: Solo tomamos columnas de comentarios de LA NUBE (Líquidos / Gestión)
        cols_comentarios_nube = [c for c in df_sheets.columns if any(kw in c for kw in ['COMENTARIO', 'NOTA', 'OBSERVACION', 'LIQUID'])]

        # 4. LIMPIEZA DE IDs (Asegurar cruce exacto solo por números)
        df_reg[col_orden_reg] = df_reg[col_orden_reg].astype(str).str.replace(r'\D', '', regex=True)
        df_sheets[col_num_nube] = df_sheets[col_num_nube].astype(str).str.replace(r'\D', '', regex=True)
        df_reg = df_reg[df_reg[col_orden_reg] != '']

        # 5. FILTRADO (ISLAS + ACEPTABLE)
        df_islas = df_reg[
            (df_reg[col_region_reg].astype(str).str.upper() == 'ISLAS') & 
            (df_reg[col_estado_reg].astype(str).str.upper() == 'ACEPTABLE')
        ].copy()

        if df_islas.empty:
            st.warning("⚠️ No se encontraron órdenes en estado 'ACEPTABLE' para la región 'ISLAS'.")
            return pd.DataFrame()

        # 6. CRUCE LEFT JOIN (Mantiene TODAS las órdenes del Registro)
        df_final = pd.merge(
            df_islas, 
            df_sheets, 
            left_on=col_orden_reg, 
            right_on=col_num_nube, 
            how='left',
            suffixes=('_REG', '_NUBE')
        )

        # 7. LÓGICA ESTRICTA DE PUNTOS
        def calcular_puntos(row):
            # Priorizamos la actividad del Registro
            actividad = str(row.get(f"{col_act_reg}_REG", row.get(col_act_reg, ""))).upper()
            
            # Buscamos justificación EXCLUSIVAMENTE en las columnas de la NUBE
            comentarios_nube_lista = []
            for col in cols_comentarios_nube:
                c_real = f"{col}_NUBE" if f"{col}_NUBE" in df_final.columns else col
                if c_real in row and pd.notna(row[c_real]):
                    comentarios_nube_lista.append(str(row[c_real]))
            
            texto_nube = " ".join(comentarios_nube_lista).lower()

            # --- DIRECTRICES ---
            # 1. Traslados e Instalaciones (Completados 100% por estar Aceptables) = 2.5 pts
            if any(x in actividad for x in ['INSTALACION', 'TRASLADO']):
                return 2.5
            
            # 2. SOPFIBRAS (Con cambio = 2 pts, Normal = 1 pt)
            if 'SOPFIBRA' in actividad:
                keywords_cambio = ['cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 'cambio drop', 'fibra nueva', 'se tiro fibra']
                if any(kw in texto_nube for kw in keywords_cambio):
                    return 2.0
                return 1.0
            
            # 3. Mantenimiento (Normal = 1 pt)
            if 'MANTENIMIENTO' in actividad:
                return 1.0
            
            return 0.0

        df_final['PUNTOS'] = df_final.apply(calcular_puntos, axis=1)

        # 8. CONSOLIDADO
        tec_final_col = f"{col_tec_reg}_REG" if f"{col_tec_reg}_REG" in df_final.columns else col_tec_reg
        orden_final_col = f"{col_orden_reg}_REG" if f"{col_orden_reg}_REG" in df_final.columns else col_orden_reg
        
        reporte = df_final.groupby(tec_final_col).agg(
            Ordenes_Aceptables=(orden_final_col, 'count'),
            Total_Puntos=('PUNTOS', 'sum')
        ).reset_index()

        reporte = reporte.rename(columns={
            tec_final_col: 'Técnico', 
            'Ordenes_Aceptables': 'Órdenes Aceptables', 
            'Total_Puntos': 'Puntos Totales'
        })
        
        return reporte.sort_values(by='Puntos Totales', ascending=False)

    except Exception as e:
        st.error(f"Error crítico procesando el archivo: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Puntos por Técnico")
    st.caption("Cruce estricto: Órdenes del Registro vs. Comentarios de Gestión (Nube)")
    
    df_nube = st.session_state.get('df_base', None)
    
    if df_nube is not None and not df_nube.empty:
        st.success("🔗 **Conexión con Google Sheets activa.**")
        
        archivo_reg = st.file_uploader("📂 Sube el archivo de Registro de Calidad (Mozart)", type=['csv', 'xlsx'])
        
        if archivo_reg and st.button("🚀 Calcular Puntos", use_container_width=True, type="primary"):
            with st.spinner("Analizando comentarios de la nube..."):
                resultado = procesar_evaluacion_puntos(archivo_reg, df_nube)
                
                if resultado is not None and not resultado.empty:
                    st.divider()
                    
                    # Renderizado nativo y estético de Streamlit
                    st.dataframe(
                        resultado,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Técnico": st.column_config.TextColumn(
                                "👨‍🔧 Nombre del Técnico", 
                                width="large"
                            ),
                            "Órdenes Aceptables": st.column_config.NumberColumn(
                                "📋 Órdenes 100% Completas", 
                                help="Cantidad de órdenes ACEPTABLES según Mozart"
                            ),
                            "Puntos Totales": st.column_config.NumberColumn(
                                "⭐ Puntos Ganados", 
                                format="%.1f",
                                help="Basado en directrices de Instalación, Traslado, SOPFibra y Mantenimiento"
                            )
                        }
                    )
                    
                    csv = resultado.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Descargar Consolidado CSV", 
                        data=csv, 
                        file_name="Reporte_Puntos_Tecnicos_ISLAS.csv", 
                        mime="text/csv", 
                        use_container_width=True
                    )
    else:
        st.warning("⚠️ Los datos de la nube aún no están cargados. Asegúrate de sincronizar en el panel lateral.")
