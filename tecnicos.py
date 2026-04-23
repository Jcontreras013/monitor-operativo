# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata

def limpiar_columnas(df):
    """
    Normaliza los nombres de las columnas quitando tildes, 
    espacios extra y pasándolas a mayúsculas.
    """
    cols_limpias = []
    for col in df.columns:
        c = str(col).strip().upper()
        c = ''.join(char for char in unicodedata.normalize('NFKD', c) if unicodedata.category(char) != 'Mn')
        cols_limpias.append(c)
    df.columns = cols_limpias
    return df

def procesar_evaluacion_puntos(archivo_registro, df_nube):
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
        
        # Cazador de Encabezados
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
        
        # Limpieza Pesada
        df_reg = limpiar_columnas(df_reg)
        
        # 2. CARGA DE LA NUBE
        if df_nube is None or df_nube.empty:
            st.error("No hay datos en la nube. Sincroniza el monitor primero.")
            return None
        
        df_sheets = df_nube.copy()
        df_sheets = limpiar_columnas(df_sheets)

        # 3. BÚSQUEDA PESADA DE COLUMNAS
        col_orden_reg  = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_region_reg = next((c for c in df_reg.columns if 'REGI' in c), None)
        col_estado_reg = next((c for c in df_reg.columns if 'ESTADO' in c or 'STATUS' in c), None)
        col_tec_reg    = next((c for c in df_reg.columns if 'TECNICO' in c or 'ASIGNADO' in c), None)
        col_act_reg    = next((c for c in df_reg.columns if 'ACTIVIDAD' in c or 'TIPO' in c), None)
        col_eval_reg   = next((c for c in df_reg.columns if 'EVALUAC' in c), None)
        col_mod_reg    = next((c for c in df_reg.columns if 'MODIFICAC' in c), None)

        col_num_nube = next((c for c in df_sheets.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        cols_comentarios_nube = [c for c in df_sheets.columns if any(kw in c for kw in ['COMENTARIO', 'NOTA', 'OBSERVACION', 'LIQUID', 'DETALLE'])]

        if not col_num_nube:
            st.error("❌ No se encontró la columna de Número de Orden en la base de datos de la nube.")
            return None

        # 4. ESTANDARIZACIÓN AGRESIVA (Solo números)
        df_reg[col_orden_reg] = df_reg[col_orden_reg].astype(str).str.replace(r'\D', '', regex=True)
        df_sheets[col_num_nube] = df_sheets[col_num_nube].astype(str).str.replace(r'\D', '', regex=True)

        df_reg = df_reg[df_reg[col_orden_reg] != '']

        # 5. FILTRADO (Solo ISLAS y ACEPTABLES)
        df_reg_islas = df_reg[
            (df_reg[col_region_reg].astype(str).str.strip().str.upper() == 'ISLAS') & 
            (df_reg[col_estado_reg].astype(str).str.strip().str.upper() == 'ACEPTABLE')
        ].copy()

        if df_reg_islas.empty:
            st.warning("⚠️ No se encontraron órdenes en estado 'ACEPTABLE' para la región 'ISLAS'.")
            return pd.DataFrame()

        # 6. CRUCE MAESTRO (LEFT JOIN para conservar el 100% de órdenes del Registro)
        df_final = pd.merge(
            df_reg_islas, 
            df_sheets, 
            left_on=col_orden_reg, 
            right_on=col_num_nube, 
            how='left',
            suffixes=('_REG', '_NUBE')
        )

        # Escudo de Colisiones
        final_tec_col   = f"{col_tec_reg}_REG"   if f"{col_tec_reg}_REG"   in df_final.columns else col_tec_reg
        final_orden_col = f"{col_orden_reg}_REG" if f"{col_orden_reg}_REG" in df_final.columns else col_orden_reg
        final_act_col   = f"{col_act_reg}_REG"   if f"{col_act_reg}_REG"   in df_final.columns else col_act_reg
        final_eval_col  = f"{col_eval_reg}_REG"  if f"{col_eval_reg}_REG"  in df_final.columns else col_eval_reg
        final_mod_col   = f"{col_mod_reg}_REG"   if f"{col_mod_reg}_REG"   in df_final.columns else col_mod_reg

        # 7. LÓGICA DE DIRECTRICES (Puntos)
        def calcular_puntos(row):
            actividad = str(row.get(final_act_col, '')).strip().upper()
            
            val_eval = str(row.get(final_eval_col, '')) if pd.notna(row.get(final_eval_col)) else ""
            val_mod  = str(row.get(final_mod_col, ''))  if pd.notna(row.get(final_mod_col)) else ""
            
            vals_nube = []
            for col_com in cols_comentarios_nube:
                col_nube_real = f"{col_com}_NUBE" if f"{col_com}_NUBE" in df_final.columns else col_com
                if col_nube_real in row and pd.notna(row[col_nube_real]):
                    vals_nube.append(str(row[col_nube_real]))
            
            todos_los_comentarios = f"{val_eval} {val_mod} {' '.join(vals_nube)}".lower()

            # REGLA 1: Traslados e Instalaciones = 2.5
            if any(x in actividad for x in ['INSTALACION', 'TRASLADO']):
                return 2.5
            
            # REGLA 2: SOPFIBRAS (Cambio = 2, Normal = 1)
            if 'SOPFIBRA' in actividad:
                cambio_fibra_keywords = [
                    'cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 
                    'se cambio drop', 'fibra nueva', 'cambio drop'
                ]
                if any(kw in todos_los_comentarios for kw in cambio_fibra_keywords):
                    return 2.0 
                return 1.0 
            
            return 0.0

        df_final['PUNTOS'] = df_final.apply(calcular_puntos, axis=1)

        # 8. CONSOLIDADO
        reporte = df_final.groupby(final_tec_col).agg(
            Ordenes_Aceptables=(final_orden_col, 'count'),
            Total_Puntos=('PUNTOS', 'sum')
        ).reset_index()
        
        reporte = reporte.rename(columns={final_tec_col: 'Técnico', 'Ordenes_Aceptables': 'Órdenes Aceptables', 'Total_Puntos': 'Total Puntos'})
        reporte = reporte.sort_values(by='Total Puntos', ascending=False)

        return reporte

    except Exception as e:
        st.error(f"Error crítico procesando el archivo: {e}")
        return None

def render_tabla_estilizada(df):
    """
    Renderiza la tabla con CSS nativo para que luzca exactamente como el diseño solicitado.
    """
    html = """
    <style>
    .tabla-puntos {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        margin-top: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        border-radius: 8px;
        overflow: hidden;
    }
    .tabla-puntos thead tr {
        background-color: #1e3a8a; /* Azul corporativo */
        color: #ffffff;
        text-align: center;
        font-size: 14px;
        letter-spacing: 0.5px;
    }
    .tabla-puntos th, .tabla-puntos td {
        padding: 12px 15px;
    }
    .tabla-puntos tbody tr {
        border-bottom: 1px solid #dddddd;
        background-color: #ffffff;
        color: #333333;
    }
    .tabla-puntos tbody tr:nth-of-type(even) {
        background-color: #f8fafc; /* Gris/Azul muy claro para filas alternas */
    }
    .tabla-puntos tbody tr:hover {
        background-color: #e2e8f0;
    }
    .texto-tecnico {
        text-align: left;
        font-weight: 600;
        color: #0f172a;
    }
    .texto-centro {
        text-align: center;
        font-size: 15px;
    }
    .texto-puntos {
        text-align: center;
        font-size: 16px;
        font-weight: bold;
        color: #1d4ed8;
    }
    </style>
    <table class="tabla-puntos">
        <thead>
            <tr>
                <th style="text-align: left; padding-left: 20px;">TÉCNICO</th>
                <th>ÓRDENES ACEPTABLES</th>
                <th>PUNTOS TOTALES</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for _, row in df.iterrows():
        html += f"""
            <tr>
                <td class="texto-tecnico" style="padding-left: 20px;">{row['Técnico']}</td>
                <td class="texto-centro">{int(row['Órdenes Aceptables'])}</td>
                <td class="texto-puntos">{row['Total Puntos']:.1f}</td>
            </tr>
        """
        
    html += """
        </tbody>
    </table>
    <br>
    """
    st.markdown(html, unsafe_allow_html=True)

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Rendimiento por Puntos")
    st.info("Cruce de **Registro de Calidad** con **Comentarios de Google Sheets**. Se conservan todas las órdenes aceptables del registro.")

    df_base_nube = st.session_state.get('df_base', None)

    if df_base_nube is not None and not df_base_nube.empty:
        st.success("🔗 **Base de datos de Google Sheets sincronizada y lista para cruce.**")
        
        archivo_reg = st.file_uploader("📂 Sube el archivo de Registro de Calidad", type=['csv', 'xlsx'], key="reg_puntos")

        if archivo_reg:
            if st.button("🚀 Calcular Puntos de Técnicos", type="primary", use_container_width=True):
                with st.spinner("Realizando cruce y calculando directrices..."):
                    resultado = procesar_evaluacion_puntos(archivo_reg, df_base_nube)
                    
                    if resultado is not None and not resultado.empty:
                        st.divider()
                        
                        # Renderizar la tabla con diseño personalizado
                        render_tabla_estilizada(resultado)
                        
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
