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
        
        # Identificar columnas clave en la nube
        col_num_nube = next((c for c in df_nube_clean.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        col_est_nube = next((c for c in df_nube_clean.columns if 'ESTADO' in c), None)
        col_act_nube = next((c for c in df_nube_clean.columns if 'ACTIVIDAD' in c), None)
        col_tec_nube = next((c for c in df_nube_clean.columns if 'TECNICO' in c), None)
        cols_obs_nube = [c for c in df_nube_clean.columns if any(kw in c for kw in ['COMENTARIO', 'OBSERVACION', 'LIQUID'])]

        # Filtrar solo órdenes CERRADAS en la nube
        df_cerradas = df_nube_clean[df_nube_clean[col_est_nube].astype(str).str.upper() == 'CERRADA'].copy()
        df_cerradas[col_num_nube] = df_cerradas[col_num_nube].astype(str).str.replace(r'\D', '', regex=True)

        # 2. CARGA DEL REGISTRO (MOZART) PARA COTEJAR CALIDAD
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
        
        # Identificar columnas en Registro
        col_num_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_est_reg = next((c for c in df_reg.columns if 'ESTADO' in c), None)
        
        # Limpiar IDs de Registro y filtrar solo ACEPTABLES
        df_reg[col_num_reg] = df_reg[col_num_reg].astype(str).str.replace(r'\D', '', regex=True)
        # Creamos un set de órdenes aceptables para búsqueda rápida
        ordenes_aceptables = set(df_reg[df_reg[col_est_reg].astype(str).str.upper() == 'ACEPTABLE'][col_num_reg])

        # 3. LÓGICA DE ASIGNACIÓN DE PUNTOS
        def calcular_puntos(row):
            actividad = str(row.get(col_act_nube, "")).upper()
            num_orden = str(row.get(col_num_nube, ""))
            
            # --- CASO 1: INSFIBRA (Instalación Fija) ---
            if 'INSFIBRA' in actividad:
                return 2.5
            
            # --- CASO 2: SOPFIBRA / SOP (Requieren cotejo con Registro) ---
            if 'SOP' in actividad:
                # Si NO está en el registro como aceptable, no gana puntos o solo base? 
                # Según tu instrucción: "cotejamos con las ordenes que hay en estado aceptable"
                if num_orden in ordenes_aceptables:
                    # Unimos todos los comentarios de la nube para buscar palabras clave
                    comentario = " ".join([str(row[c]) for c in cols_obs_nube if pd.notna(row[c])]).lower()
                    
                    # Traslado Externo = 2.5 pts
                    if any(kw in comentario for kw in ['traslado externo', 'traslado de equipo', 'traslado de linea']):
                        return 2.5
                    # Cambio de Fibra = 2.0 pts
                    if any(kw in comentario for kw in ['cambia fibra', 'cambio de fibra', 'reemplazo drop', 'fibra nueva']):
                        return 2.0
                    
                    # SOP Normal Aceptable = 1.0 pt
                    return 1.0
                else:
                    # Si es SOP pero no está aceptable en Mozart, 0 puntos
                    return 0.0
            
            return 0.0

        # Aplicar puntos
        df_cerradas['PUNTOS'] = df_cerradas.apply(calcular_puntos, axis=1)

        # 4. CONSOLIDACIÓN FINAL
        reporte = df_cerradas.groupby(col_tec_nube).agg(
            Total_Ordenes_Cerradas=(col_num_nube, 'count'),
            Puntos_Ganados=('PUNTOS', 'sum')
        ).reset_index()

        reporte = reporte.rename(columns={
            col_tec_nube: '👨‍🔧 Nombre del Técnico',
            'Total_Ordenes_Cerradas': '📦 Órdenes Cerradas',
            'Puntos_Ganados': '⭐ Puntos Totales'
        })

        return reporte.sort_values(by='⭐ Puntos Totales', ascending=False)

    except Exception as e:
        st.error(f"Error procesando la evaluación: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación Gerencial por Puntos")
    st.caption("Base: Órdenes Cerradas (Nube) vs. Calidad Aceptable (Mozart)")
    
    df_nube = st.session_state.get('df_base', None)
    
    if df_nube is not None and not df_nube.empty:
        st.info("📊 Analizando base de datos de la nube con estatus 'Cerrada'.")
        
        archivo_reg = st.file_uploader("📂 Sube el archivo Mozart (Pestaña Registro)", type=['csv', 'xlsx'])
        
        if archivo_reg and st.button("🚀 Ejecutar Auditoría de Puntos", use_container_width=True, type="primary"):
            with st.spinner("Cruzando datos y analizando comentarios..."):
                resultado = procesar_evaluacion_puntos(archivo_reg, df_nube)
                
                if resultado is not None:
                    st.divider()
                    st.dataframe(resultado, use_container_width=True, hide_index=True)
                    
                    csv = resultado.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Descargar Reporte de Puntos", 
                        data=csv, 
                        file_name="Evaluacion_Puntos_Tecnicos.csv", 
                        mime="text/csv", 
                        use_container_width=True
                    )
    else:
        st.warning("⚠️ Sincroniza los datos en el panel lateral antes de continuar.")
