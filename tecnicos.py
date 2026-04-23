# tecnicos.py
import streamlit as st
import pandas as pd
import re
import unicodedata

def limpiar_columnas(df):
    """
    Búsqueda Pesada: Normaliza los nombres de las columnas quitando tildes, 
    espacios extra y pasándolas a mayúsculas para que la búsqueda nunca falle.
    """
    cols_limpias = []
    for col in df.columns:
        # Convertir a texto, mayúsculas y quitar espacios en los bordes
        c = str(col).strip().upper()
        # Quitar tildes y caracteres especiales (ej. TÉCNICO -> TECNICO)
        c = ''.join(char for char in unicodedata.normalize('NFKD', c) if unicodedata.category(char) != 'Mn')
        cols_limpias.append(c)
    df.columns = cols_limpias
    return df

def procesar_evaluacion_puntos(archivo_registro, df_nube):
    """
    Coteja Registro manual y Actividades de la nube usando búsqueda profunda de columnas.
    """
    try:
        # 1. CARGA SEGURA DEL REGISTRO LOCAL
        if archivo_registro.name.endswith('.csv'):
            try:
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str)
            except UnicodeDecodeError:
                archivo_registro.seek(0)
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw = pd.read_excel(archivo_registro, header=None, dtype=str)
        
        # Cazador de Encabezados (ignora las filas vacías de arriba)
        header_idx = -1
        for i, row in df_raw.iterrows():
            fila_texto = " ".join(row.dropna().astype(str)).upper()
            if 'ORDEN' in fila_texto and 'ACTIVIDAD' in fila_texto:
                header_idx = i
                break
                
        if header_idx == -1:
            st.error("❌ No se detectaron las columnas de Órdenes. Asegúrate de subir la pestaña 'Registro'.")
            return None
            
        df_reg = df_raw.iloc[header_idx + 1:].copy()
        df_reg.columns = df_raw.iloc[header_idx]
        df_reg = df_reg.reset_index(drop=True)
        
        # Limpieza Pesada de columnas locales
        df_reg = limpiar_columnas(df_reg)
        
        # 2. CARGA Y LIMPIEZA DE LA NUBE
        if df_nube is None or df_nube.empty:
            st.error("No hay datos en la nube. Sincroniza el monitor primero.")
            return None
        
        df_sheets = df_nube.copy()
        df_sheets = limpiar_columnas(df_sheets)

        # 3. BÚSQUEDA PESADA DE COLUMNAS (LOCAL)
        col_orden_reg  = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_region_reg = next((c for c in df_reg.columns if 'REGI' in c), None)
        col_estado_reg = next((c for c in df_reg.columns if 'ESTADO' in c or 'STATUS' in c), None)
        col_tec_reg    = next((c for c in df_reg.columns if 'TECNICO' in c or 'ASIGNADO' in c), None)
        col_act_reg    = next((c for c in df_reg.columns if 'ACTIVIDAD' in c or 'TIPO' in c), None)
        col_eval_reg   = next((c for c in df_reg.columns if 'EVALUAC' in c), None)
        col_mod_reg    = next((c for c in df_reg.columns if 'MODIFICAC' in c), None)

        # BÚSQUEDA PESADA DE COLUMNAS (NUBE)
        # Buscar Número de Orden en la nube
        col_num_nube = next((c for c in df_sheets.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        
        # Buscar TODAS las columnas de comentarios en la nube (puede haber más de una)
        cols_comentarios_nube = [c for c in df_sheets.columns if any(kw in c for kw in ['COMENTARIO', 'NOTA', 'OBSERVACION', 'LIQUID', 'DETALLE'])]

        if not col_num_nube:
            st.error("❌ No se encontró la columna de Número de Orden en la base de datos de la nube.")
            return None

        # 4. ESTANDARIZACIÓN PARA EL CRUCE
        df_reg[col_orden_reg] = df_reg[col_orden_reg].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        df_sheets[col_num_nube] = df_sheets[col_num_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        # 5. FILTRADO (ISLAS Y ACEPTABLE)
        df_reg_islas = df_reg[
            (df_reg[col_region_reg].astype(str).str.strip().str.upper() == 'ISLAS') & 
            (df_reg[col_estado_reg].astype(str).str.strip().str.upper() == 'ACEPTABLE')
        ].copy()

        if df_reg_islas.empty:
            st.warning("⚠️ No se encontraron órdenes en estado 'ACEPTABLE' para la región 'ISLAS'.")
            return pd.DataFrame()

        # 6. CRUCE MAESTRO (MERGE)
        df_final = pd.merge(
            df_reg_islas, 
            df_sheets, 
            left_on=col_orden_reg, 
            right_on=col_num_nube, 
            how='inner',
            suffixes=('_REG', '_NUBE')
        )

        # 7. LÓGICA DE DIRECTRICES (PUNTUACIÓN)
        def calcular_puntos(row):
            actividad = str(row[col_act_reg] if col_act_reg in row else row.get('ACTIVIDAD', '')).strip().upper()
            
            # Extraer y concatenar TODOS los comentarios (Registro + Nube)
            val_eval = str(row[col_eval_reg]) if col_eval_reg in row and pd.notna(row[col_eval_reg]) else ""
            val_mod = str(row[col_mod_reg]) if col_mod_reg in row and pd.notna(row[col_mod_reg]) else ""
            
            vals_nube = []
            for col_com in cols_comentarios_nube:
                if col_com in row and pd.notna(row[col_com]):
                    vals_nube.append(str(row[col_com]))
            
            # Unir todo el texto en minúsculas
            todos_los_comentarios = f"{val_eval} {val_mod} {' '.join(vals_nube)}".lower()

            # --- DIRECTRICES ---
            
            # 1. Traslados e Instalaciones (2.5 puntos)
            if any(x in actividad for x in ['INSTALACION', 'TRASLADO']):
                return 2.5
            
            # 2. SOPFIBRAS
            if 'SOPFIBRA' in actividad:
                cambio_fibra_keywords = ['cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 'se cambio drop', 'fibra nueva']
                if any(kw in todos_los_comentarios for kw in cambio_fibra_keywords):
                    return 2.0 # Con cambio de fibra reportado
                return 1.0 # Normal (sin cambio)
            
            return 0.0

        df_final['PUNTOS'] = df_final.apply(calcular_puntos, axis=1)

        # 8. CONSOLIDADO
        reporte = df_final.groupby(col_tec_reg).agg(
            Ordenes_Aceptables=(col_orden_reg, 'count'),
            Total_Puntos=('PUNTOS', 'sum')
        ).reset_index()
        
        reporte = reporte.rename(columns={col_tec_reg: 'Técnico', 'Ordenes_Aceptables': 'Órdenes Aceptables', 'Total_Puntos': 'Total Puntos'})
        reporte = reporte.sort_values(by='Total Puntos', ascending=False)

        return reporte

    except Exception as e:
        st.error(f"Error crítico procesando el archivo: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Rendimiento por Puntos")
    st.info("Cruce de **Registro de Calidad** con **Comentarios de Google Sheets**.")

    df_base_nube = st.session_state.get('df_base', None)

    if df_base_nube is not None and not df_base_nube.empty:
        st.success("🔗 **Base de datos de Google Sheets sincronizada y lista para cruce.**")
        
        archivo_reg = st.file_uploader("📂 Sube el archivo de Registro de Calidad", type=['csv', 'xlsx'], key="reg_puntos")

        if archivo_reg:
            if st.button("🚀 Calcular Puntos de Técnicos", type="primary", use_container_width=True):
                with st.spinner("Realizando búsqueda pesada y analizando directrices..."):
                    resultado = procesar_evaluacion_puntos(archivo_reg, df_base_nube)
                    
                    if resultado is not None and not resultado.empty:
                        st.divider()
                        st.subheader("📊 Resultados - Región ISLAS")
                        st.dataframe(resultado, use_container_width=True, hide_index=True)
                        
                        csv = resultado.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Descargar Reporte CSV", 
                            data=csv, 
                            file_name="Reporte_Puntos_Tecnicos_ISLAS.csv", 
                            mime="text/csv", 
                            use_container_width=True
                        )
    else:
        st.warning("⚠️ Los datos de la nube aún no están cargados. Asegúrate de sincronizar en el panel lateral.")
