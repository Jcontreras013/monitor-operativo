# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata
import re

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
        # 1. CARGA Y LIMPIEZA DE LA NUBE (BASE PRINCIPAL)
        df_nube_clean = limpiar_columnas(df_nube.copy())
        
        col_num_nube = next((c for c in df_nube_clean.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        col_est_nube = next((c for c in df_nube_clean.columns if 'ESTADO' in c), None)
        col_act_nube = next((c for c in df_nube_clean.columns if 'ACTIVIDAD' in c), None)
        col_tec_nube = next((c for c in df_nube_clean.columns if 'TECNICO' in c), None)
        cols_obs_nube = [c for c in df_nube_clean.columns if any(kw in c for kw in ['COMENTARIO', 'OBSERVACION', 'LIQUID'])]

        df_cerradas = df_nube_clean[df_nube_clean[col_est_nube].astype(str).str.upper() == 'CERRADA'].copy()
        df_cerradas[col_num_nube] = df_cerradas[col_num_nube].astype(str).str.replace(r'\D', '', regex=True)

        # 2. CARGA DEL REGISTRO (MOZART)
        if archivo_registro.name.endswith('.csv'):
            try: df_raw = pd.read_csv(archivo_registro, header=None, dtype=str)
            except: df_raw = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw = pd.read_excel(archivo_registro, header=None, dtype=str)

        header_idx = -1
        for i, row in df_raw.iterrows():
            fila_texto = " ".join(row.dropna().astype(str)).upper()
            if 'ORDEN' in fila_texto and 'ESTADO' in fila_texto:
                header_idx = i
                break
        
        if header_idx == -1:
            st.error("❌ No se detectaron las columnas en el Registro.")
            return None

        df_reg = df_raw.iloc[header_idx + 1:].copy()
        df_reg.columns = df_raw.iloc[header_idx]
        df_reg = limpiar_columnas(df_reg.reset_index(drop=True))
        
        col_num_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_est_reg = next((c for c in df_reg.columns if 'ESTADO' in c), None)
        
        df_reg[col_num_reg] = df_reg[col_num_reg].astype(str).str.replace(r'\D', '', regex=True)
        ordenes_aceptables = set(df_reg[df_reg[col_est_reg].astype(str).str.upper() == 'ACEPTABLE'][col_num_reg])

        # 3. LÓGICA DE ASIGNACIÓN Y CONTEO
        def clasificar_y_puntuar(row):
            actividad = str(row.get(col_act_nube, "")).upper()
            num_orden = str(row.get(col_num_nube, ""))
            comentario = " ".join([str(row[c]) for c in cols_obs_nube if pd.notna(row[c])]).lower()
            
            # Inicializamos categorías para el conteo
            tipo = "OTRO"
            puntos = 0.0

            if 'INSFIBRA' in actividad:
                return pd.Series(["INSFIBRA", 2.5])
            
            if 'SOP' in actividad:
                if num_orden in ordenes_aceptables:
                    # Traslado Externo
                    if any(kw in comentario for kw in ['traslado externo', 'traslado de equipo', 'traslado de linea']):
                        return pd.Series(["TRASLADO", 2.5])
                    # Cambio de Fibra
                    if any(kw in comentario for kw in ['cambia fibra', 'cambio de fibra', 'reemplazo drop', 'fibra nueva']):
                        return pd.Series(["CAMBIO FIBRA", 2.0])
                    # SOP Normal
                    return pd.Series(["SOP NORMAL", 1.0])
                else:
                    return pd.Series(["NO ACEPTABLE", 0.0])
            
            return pd.Series([tipo, puntos])

        # Aplicamos la clasificación
        df_cerradas[['TIPO_ORDEN', 'PUNTOS']] = df_cerradas.apply(clasificar_y_puntuar, axis=1)

        # 4. CONSOLIDACIÓN DETALLADA
        # Contamos cuántas hay de cada tipo por técnico
        reporte_conteo = df_cerradas.groupby([col_tec_nube, 'TIPO_ORDEN']).size().unstack(fill_value=0)
        
        # Aseguramos que existan todas las columnas aunque el conteo sea 0
        for col in ['INSFIBRA', 'CAMBIO FIBRA', 'SOP NORMAL', 'TRASLADO']:
            if col not in reporte_conteo.columns:
                reporte_conteo[col] = 0

        # Calculamos los puntos totales
        reporte_puntos = df_cerradas.groupby(col_tec_nube)['PUNTOS'].sum()

        # Unimos todo
        reporte_final = reporte_conteo.merge(reporte_puntos, left_index=True, right_index=True)
        reporte_final = reporte_final.reset_index()

        # Renombrar para que se vea profesional
        reporte_final = reporte_final.rename(columns={
            col_tec_nube: '👨‍🔧 Técnico',
            'INSFIBRA': '🏠 Instalaciones (2.5)',
            'CAMBIO FIBRA': '🧵 Cambio Fibra (2.0)',
            'SOP NORMAL': '🔧 SOP Normal (1.0)',
            'TRASLADO': '🚚 Traslados (2.5)',
            'PUNTOS': '⭐ TOTAL PUNTOS'
        })

        return reporte_final.sort_values(by='⭐ TOTAL PUNTOS', ascending=False)

    except Exception as e:
        st.error(f"Error procesando la evaluación: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Tablero de Rendimiento Detallado")
    st.caption("Desglose de órdenes por tipo y puntos acumulados.")
    
    df_nube = st.session_state.get('df_base', None)
    
    if df_nube is not None and not df_nube.empty:
        archivo_reg = st.file_uploader("📂 Sube archivo Mozart (Registro)", type=['csv', 'xlsx'])
        
        if archivo_reg and st.button("🚀 Generar Reporte de Producción", use_container_width=True, type="primary"):
            with st.spinner("Procesando datos..."):
                resultado = procesar_evaluacion_puntos(archivo_reg, df_nube)
                
                if resultado is not None:
                    st.markdown("---")
                    st.dataframe(resultado, use_container_width=True, hide_index=True)
                    
                    csv = resultado.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Descargar Reporte en Excel/CSV", 
                        data=csv, 
                        file_name="Produccion_Detallada_Tecnicos.csv", 
                        mime="text/csv", 
                        use_container_width=True
                    )
    else:
        st.warning("⚠️ Sincroniza los datos en el panel lateral antes de continuar.")
