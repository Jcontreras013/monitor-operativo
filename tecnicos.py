# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata
from datetime import date
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

def procesar_evaluacion_puntos(archivo_registro, df_nube, fecha_inicio, fecha_fin):
    try:
        # =======================================================
        # 1. PREPARACIÓN DE LA NUBE (LA BASE MAESTRA AHORA)
        # =======================================================
        df_nube_clean = limpiar_columnas(df_nube.copy())
        
        # Identificadores de columnas en la nube
        col_num_nube = 'NUM' if 'NUM' in df_nube_clean.columns else next((c for c in df_nube_clean.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        col_est_nube = next((c for c in df_nube_clean.columns if 'ESTADO' in c), None)
        col_act_nube = next((c for c in df_nube_clean.columns if 'ACTIVIDAD' in c), None)
        col_tec_nube = next((c for c in df_nube_clean.columns if 'TECNICO' in c), None)
        col_fecha_nube = next((c for c in df_nube_clean.columns if 'HORA_LIQ' in c or 'FECHA' in c), None)
        cols_obs_nube = [c for c in df_nube_clean.columns if any(kw in c for kw in ['COMENTARIO', 'OBSERVACION', 'LIQUID', 'NOTA'])]

        # Filtrar SOLO Órdenes CERRADAS de la Nube
        df_cerradas = df_nube_clean[df_nube_clean[col_est_nube].astype(str).str.upper() == 'CERRADA'].copy()
        
        # --- FILTRO MAESTRO DE FECHAS (MES A EVALUAR) ---
        if col_fecha_nube:
            df_cerradas['FECHA_FILTRO'] = pd.to_datetime(df_cerradas[col_fecha_nube], errors='coerce').dt.date
            df_cerradas = df_cerradas[
                (df_cerradas['FECHA_FILTRO'] >= fecha_inicio) & 
                (df_cerradas['FECHA_FILTRO'] <= fecha_fin)
            ]

        if df_cerradas.empty:
            st.warning(f"⚠️ No hay órdenes cerradas en la nube entre el {fecha_inicio.strftime('%d/%m/%Y')} y el {fecha_fin.strftime('%d/%m/%Y')}.")
            return None

        # Limpiar los IDs Nube de forma segura (Quitamos el .0 antes de quitar todo lo que no sea número)
        df_cerradas[col_num_nube] = df_cerradas[col_num_nube].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '', regex=True).str.strip()

        # =======================================================
        # 2. CARGA DEL REGISTRO (MOZART) PARA AUDITORÍA
        # =======================================================
        if archivo_registro.name.endswith('.csv'):
            try: 
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str)
            except: 
                archivo_registro.seek(0)
                df_raw = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw = pd.read_excel(archivo_registro, header=None, dtype=str)

        # Buscar dónde empiezan los encabezados reales
        header_idx = -1
        for i, row in df_raw.iterrows():
            fila_texto = " ".join(row.dropna().astype(str)).upper()
            if ('ORDEN' in fila_texto or 'NUMERO' in fila_texto) and 'ESTADO' in fila_texto:
                header_idx = i
                break
        
        if header_idx == -1:
            st.error("❌ No se detectaron las columnas en el Registro Mozart. Sube la pestaña 'Registro'.")
            return None

        df_reg = df_raw.iloc[header_idx + 1:].copy()
        df_reg.columns = df_raw.iloc[header_idx]
        df_reg = limpiar_columnas(df_reg.reset_index(drop=True))
        
        col_num_reg = next((c for c in df_reg.columns if c in ['NUMERO ORDEN', 'ORDEN', 'NUM']), None)
        if not col_num_reg:
            col_num_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
            
        col_est_reg = next((c for c in df_reg.columns if c in ['ESTADO', 'ESTATUS']), None)
        col_region_reg = next((c for c in df_reg.columns if 'REGI' in c), None)
        
        # --- FILTRO: SOLO REGIÓN ISLAS ---
        if col_region_reg:
            df_reg = df_reg[df_reg[col_region_reg].astype(str).str.upper().str.contains('ISLAS', na=False)]

        # Limpiar IDs de Mozart de forma segura
        df_reg[col_num_reg] = df_reg[col_num_reg].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '', regex=True).str.strip()
        
        # Guardamos en un set todas las órdenes de ISLAS que estén como ACEPTABLE
        ordenes_aceptables = set(df_reg[df_reg[col_est_reg].astype(str).str.upper() == 'ACEPTABLE'][col_num_reg])

        # =======================================================
        # 3. LÓGICA DE CLASIFICACIÓN Y PUNTUACIÓN
        # =======================================================
        def clasificar_y_puntuar(row):
            actividad = str(row.get(col_act_nube, "")).upper()
            num_orden = str(row.get(col_num_nube, ""))
            comentario = " ".join([str(row[c]) for c in cols_obs_nube if pd.notna(row[c])]).lower()
            
            # --- 1. INSFIBRA (Instalaciones fijas, 2.5 puntos) ---
            if 'INSFIBRA' in actividad:
                return pd.Series(['🏠 INSFIBRA (2.5)', 2.5])
            
            # --- 2. SOP y SOPFIBRA (Cotejo con Mozart) ---
            if 'SOP' in actividad:
                if num_orden in ordenes_aceptables:
                    # Buscamos Traslado Externo (2.5)
                    if any(kw in comentario for kw in ['traslado externo', 'traslado de equipo', 'traslado de linea', 'traslado']):
                        return pd.Series(['🚚 Traslado Externo (2.5)', 2.5])
                    
                    # Buscamos Cambio de Fibra (2.0)
                    if any(kw in comentario for kw in ['cambia fibra', 'cambio de fibra', 'reemplazo drop', 'fibra nueva', 'se tiro fibra', 'cambio fibra']):
                        return pd.Series(['🧵 Cambio de Fibra (2.0)', 2.0])
                    
                    # SOP Normal (1.0)
                    return pd.Series(['🔧 SOP Normal Aceptable (1.0)', 1.0])
                else:
                    return pd.Series(['❌ SOP Rechazado/Mora (0.0)', 0.0])
            
            # --- 3. Otras actividades ---
            return pd.Series(['📂 Otra Actividad (0.0)', 0.0])

        df_cerradas[['TIPO_ORDEN', 'PUNTOS']] = df_cerradas.apply(clasificar_y_puntuar, axis=1)

        # =======================================================
        # 4. CONSOLIDACIÓN DE RESULTADOS
        # =======================================================
        conteo_tipos = df_cerradas.groupby([col_tec_nube, 'TIPO_ORDEN']).size().unstack(fill_value=0)
        
        columnas_esperadas = [
            '🏠 INSFIBRA (2.5)', 
            '🚚 Traslado Externo (2.5)', 
            '🧵 Cambio de Fibra (2.0)', 
            '🔧 SOP Normal Aceptable (1.0)', 
            '❌ SOP Rechazado/Mora (0.0)',
            '📂 Otra Actividad (0.0)'
        ]
        
        for col in columnas_esperadas:
            if col not in conteo_tipos.columns:
                conteo_tipos[col] = 0

        conteo_tipos = conteo_tipos[columnas_esperadas]

        suma_puntos = df_cerradas.groupby(col_tec_nube)['PUNTOS'].sum().reset_index()
        suma_puntos.rename(columns={col_tec_nube: '👨‍🔧 Técnico', 'PUNTOS': '⭐ TOTAL PUNTOS'}, inplace=True)

        reporte_final = pd.merge(suma_puntos, conteo_tipos, left_on='👨‍🔧 Técnico', right_index=True)
        reporte_final = reporte_final.sort_values(by='⭐ TOTAL PUNTOS', ascending=False).reset_index(drop=True)

        return reporte_final

    except Exception as e:
        st.error(f"Error crítico procesando la evaluación: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Tablero de Producción y Calidad (Puntos)")
    st.caption("Base Maestra: Nube (Cerradas) | Auditoría de SOPs: Mozart (Región ISLAS - Aceptables)")
    
    df_nube = st.session_state.get('df_base', None)
    
    if df_nube is not None and not df_nube.empty:
        # --- SELECTOR DE RANGO DE FECHAS ---
        hoy = date.today()
        primer_dia_mes = hoy.replace(day=1)
        
        st.markdown("##### 📅 Parámetros de Evaluación")
        rango_fechas = st.date_input(
            "Selecciona el periodo a evaluar (Por defecto: Mes Actual):",
            value=[primer_dia_mes, hoy],
            max_value=hoy
        )
        st.markdown("<br>", unsafe_allow_html=True)
        # -----------------------------------

        archivo_reg = st.file_uploader("📂 Sube el archivo Mozart (Pestaña de Registro)", type=['csv', 'xlsx'])
        
        if archivo_reg and st.button("🚀 Ejecutar Cálculo de Puntos", use_container_width=True, type="primary"):
            if len(rango_fechas) != 2:
                st.warning("⚠️ Por favor, selecciona una fecha de inicio y una de fin en el calendario.")
            else:
                fecha_inicio, fecha_fin = rango_fechas
                
                with st.spinner(f"Evaluando producción del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}..."):
                    resultado = procesar_evaluacion_puntos(archivo_reg, df_nube, fecha_inicio, fecha_fin)
                    
                    if resultado is not None and not resultado.empty:
                        st.divider()
                        
                        st.dataframe(
                            resultado,
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        csv = resultado.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Descargar Desglose Completo (CSV)", 
                            data=csv, 
                            file_name=f"Evaluacion_Tecnicos_ISLAS_{fecha_inicio.strftime('%b')}.csv", 
                            mime="text/csv", 
                            use_container_width=True
                        )
    else:
        st.warning("⚠️ Los datos de la nube aún no están cargados. Asegúrate de sincronizar en el panel lateral.")
