# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata
from datetime import date
import re

def normalizar_texto(texto):
    """Limpia el texto: quita tildes, espacios extras y pasa a mayúsculas."""
    if pd.isnull(texto): return ""
    t = str(texto).strip().upper()
    t = ''.join(char for char in unicodedata.normalize('NFKD', t) if unicodedata.category(char) != 'Mn')
    return " ".join(t.split())

def procesar_evaluacion_puntos(archivo_registro, df_nube, fecha_inicio, fecha_fin):
    try:
        # =======================================================
        # 1. PREPARACIÓN DE LA NUBE (MAESTRA)
        # =======================================================
        df_nube_clean = df_nube.copy()
        df_nube_clean.columns = [normalizar_texto(c) for c in df_nube_clean.columns]
        
        col_num_nube = 'NUM' if 'NUM' in df_nube_clean.columns else next((c for c in df_nube_clean.columns if 'ORDEN' in c), None)
        col_est_nube = next((c for c in df_nube_clean.columns if 'ESTADO' in c), None)
        col_act_nube = next((c for c in df_nube_clean.columns if 'ACTIVIDAD' in c), None)
        col_tec_nube = next((c for c in df_nube_clean.columns if 'TECNICO' in c), None)
        col_fecha_nube = next((c for c in df_nube_clean.columns if 'HORA_LIQ' in c or 'FECHA' in c), None)
        cols_obs_nube = [c for c in df_nube_clean.columns if any(kw in c for kw in ['COMENTARIO', 'OBSERVACION', 'LIQUID', 'NOTA'])]

        # Filtro: CERRADAS + RANGO DE FECHAS
        df_cerradas = df_nube_clean[df_nube_clean[col_est_nube].astype(str).str.upper() == 'CERRADA'].copy()
        if col_fecha_nube:
            df_cerradas['FECHA_FILTRO'] = pd.to_datetime(df_cerradas[col_fecha_nube], errors='coerce').dt.date
            df_cerradas = df_cerradas[(df_cerradas['FECHA_FILTRO'] >= fecha_inicio) & (df_cerradas['FECHA_FILTRO'] <= fecha_fin)]

        if df_cerradas.empty:
            st.warning("⚠️ No se encontraron órdenes cerradas en la Nube para el periodo seleccionado.")
            return None

        # Limpiar IDs en Nube
        df_cerradas['NUM_LIMPIO'] = df_cerradas[col_num_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '', regex=True).str.lstrip('0')

        # =======================================================
        # 2. CARGA Y FILTRADO DE MOZART (CALIDAD)
        # =======================================================
        if archivo_registro.name.endswith('.csv'):
            try: df_raw = pd.read_csv(archivo_registro, header=None, dtype=str)
            except: df_raw = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw = pd.read_excel(archivo_registro, header=None, dtype=str)

        h_idx = -1
        for i, row in df_raw.iterrows():
            txt = " ".join(row.dropna().astype(str)).upper()
            if 'ORDEN' in txt and 'ESTADO' in txt:
                h_idx = i; break
        
        if h_idx == -1: return None

        df_reg = df_raw.iloc[h_idx + 1:].copy()
        df_reg.columns = [normalizar_texto(c) for c in df_raw.iloc[h_idx]]
        
        col_num_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_est_reg = next((c for c in df_reg.columns if 'ESTADO' in c or 'ESTATUS' in c), None)
        col_reg_reg = next((c for c in df_reg.columns if 'REGION' in c or 'REGI' in c), None)

        # Filtro Mozart: ISLAS + ACEPTABLE
        mask_region = df_reg[col_reg_reg].astype(str).str.upper().str.contains('ISLAS', na=False) if col_reg_reg else True
        mask_estado = df_reg[col_est_reg].astype(str).str.upper().str.contains('ACEPTABLE', na=False) if col_est_reg else False
        
        ordenes_aceptables = set(df_reg[mask_region & mask_estado][col_num_reg].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '', regex=True).str.lstrip('0'))

        # =======================================================
        # 3. LÓGICA DE CLASIFICACIÓN (SOLO SUMA SI ES ACEPTABLE)
        # =======================================================
        def evaluar_orden(row):
            act = str(row.get(col_act_nube, "")).upper()
            num = row['NUM_LIMPIO']
            coment = " ".join([str(row[c]) for c in cols_obs_nube if pd.notna(row[c])]).lower()

            # 🏠 INSFIBRA: Siempre suma (2.5)
            if 'INSFIBRA' in act:
                return pd.Series(['🏠 INSFIBRA (2.5)', 2.5])

            # 🛠️ SOP: Solo suma si está en el set de ACEPTABLES de Mozart
            if 'SOP' in act:
                if num in ordenes_aceptables:
                    if any(k in coment for k in ['traslado externo', 'traslado de equipo', 'traslado de linea', 'traslado']):
                        return pd.Series(['🚚 TRASLADOS (2.5)', 2.5])
                    if any(k in coment for k in ['cambia fibra', 'cambio de fibra', 'reemplazo drop', 'fibra nueva', 'se tiro fibra', 'cambio fibra']):
                        return pd.Series(['🧵 CAMBIO FIBRA (2.0)', 2.0])
                    return pd.Series(['🔧 SOP NORMAL (1.0)', 1.0])
            
            return pd.Series(['OCULTO', 0.0])

        df_cerradas[['CATEGORIA', 'PUNTOS']] = df_cerradas.apply(evaluar_orden, axis=1)

        # =======================================================
        # 4. CONSOLIDACIÓN FINAL (TABLA LIMPIA)
        # =======================================================
        resumen_conteo = df_cerradas.groupby([col_tec_nube, 'CATEGORIA']).size().unstack(fill_value=0)
        
        # Solo definimos las columnas que queremos mostrar
        columnas_finales = [
            '🏠 INSFIBRA (2.5)', 
            '🚚 TRASLADOS (2.5)', 
            '🧵 CAMBIO FIBRA (2.0)', 
            '🔧 SOP NORMAL (1.0)'
        ]
        
        for col in columnas_finales:
            if col not in resumen_conteo.columns: resumen_conteo[col] = 0
        
        resumen_conteo = resumen_conteo[columnas_finales]
        resumen_puntos = df_cerradas.groupby(col_tec_nube)['PUNTOS'].sum().reset_index()
        resumen_puntos.rename(columns={col_tec_nube: '👨‍🔧 Técnico', 'PUNTOS': '⭐ TOTAL PUNTOS'}, inplace=True)

        final = pd.merge(resumen_puntos, resumen_conteo, left_on='👨‍🔧 Técnico', right_index=True)
        return final.sort_values(by='⭐ TOTAL PUNTOS', ascending=False).reset_index(drop=True)

    except Exception as e:
        st.error(f"Error: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Puntos: Producción Aceptable")
    st.caption("Cruce: Nube (Cerradas) vs Mozart (Aceptables Islas)")
    
    df_nube = st.session_state.get('df_base', None)
    if df_nube is not None:
        hoy = date.today()
        rango = st.date_input("Periodo de evaluación:", value=[hoy.replace(day=1), hoy])
        archivo_reg = st.file_uploader("📂 Sube el Mozart (Registro)", type=['csv', 'xlsx'])
        
        if archivo_reg and st.button("🚀 Calcular Rendimiento", use_container_width=True, type="primary"):
            if len(rango) == 2:
                res = procesar_evaluacion_puntos(archivo_reg, df_nube, rango[0], rango[1])
                if res is not None:
                    st.divider()
                    st.dataframe(res, use_container_width=True, hide_index=True)
                    st.download_button("📥 Descargar Reporte", res.to_csv(index=False).encode('utf-8'), "Puntos_Tecnicos.csv", "text/csv", use_container_width=True)
