# tecnicos.py
import streamlit as st
import pandas as pd
import unicodedata
import re
from weasyprint import HTML
import base64

def normalizar_columnas(df):
    """Limpia encabezados: quita tildes, espacios y pasa a mayúsculas."""
    cols_limpias = []
    for col in df.columns:
        c = str(col).strip().upper()
        c = ''.join(char for char in unicodedata.normalize('NFKD', c) if unicodedata.category(char) != 'Mn')
        cols_limpias.append(c)
    df.columns = cols_limpias
    return df

def generar_pdf_puntos(df_reporte):
    """
    Crea un archivo PDF estilizado a partir del DataFrame de resultados.
    """
    fecha_actual = pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')
    
    # Construcción de las filas de la tabla en HTML
    filas_html = ""
    for _, row in df_reporte.iterrows():
        filas_html += f"""
        <tr>
            <td style="text-align: left;">{row['👨‍🔧 Nombre del Técnico']}</td>
            <td>{int(row['📋 Total Órdenes Cerradas'])}</td>
            <td style="font-weight: bold; color: #1d4ed8;">{row['⭐ Puntos Totales']:.1f}</td>
        </tr>
        """

    # Template HTML con CSS embebido para el PDF
    html_template = f"""
    <html>
    <head>
        <style>
            @page {{ size: A4; margin: 20mm; }}
            body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #333; }}
            .header {{ text-align: center; border-bottom: 2px solid #1e3a8a; padding-bottom: 10px; margin-bottom: 20px; }}
            h1 {{ color: #1e3a8a; margin: 0; font-size: 24px; }}
            .info {{ text-align: right; font-size: 10px; color: #666; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th {{ background-color: #1e3a8a; color: white; padding: 12px; font-size: 12px; text-transform: uppercase; }}
            td {{ padding: 10px; border-bottom: 1px solid #eee; font-size: 11px; text-align: center; }}
            tr:nth-child(even) {{ background-color: #f8fafc; }}
            .footer {{ position: fixed; bottom: 0; width: 100%; text-align: center; font-size: 9px; color: #999; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>REPORTE DE EVALUACIÓN POR PUNTOS</h1>
            <p>Región: ISLAS | Maxcom PRO</p>
        </div>
        <div class="info">Generado el: {fecha_actual}</div>
        <table>
            <thead>
                <tr>
                    <th style="text-align: left;">Técnico</th>
                    <th>Órdenes Cerradas</th>
                    <th>Puntos Totales</th>
                </tr>
            </thead>
            <tbody>
                {filas_html}
            </tbody>
        </table>
        <div class="footer">Este documento es un reporte automático generado por el Monitor Operativo Maxcom PRO.</div>
    </body>
    </html>
    """
    
    # Convertir HTML a PDF en memoria (Bytes)
    pdf_bytes = HTML(string=html_template).write_pdf()
    return pdf_bytes

def procesar_evaluacion_inversa(archivo_registro, df_nube):
    try:
        # 1. MAESTRO: Datos de la Nube (Solo Cerradas)
        df_sheets = normalizar_columnas(df_nube.copy())
        
        col_num_nube = next((c for c in df_sheets.columns if any(kw in c for kw in ['NUM', 'ORDEN', 'ID'])), None)
        col_est_nube = next((c for c in df_sheets.columns if 'ESTADO' in c or 'STATUS' in c), None)
        col_act_nube = next((c for c in df_sheets.columns if 'ACTIVIDAD' in c), None)
        col_tec_nube = next((c for c in df_sheets.columns if 'TECNICO' in c), None)
        cols_comentarios = [c for c in df_sheets.columns if any(kw in c for kw in ['COMENTARIO', 'NOTA', 'OBSERVACION', 'LIQUID'])]

        df_maestro = df_sheets[df_sheets[col_est_nube].astype(str).str.upper() == 'CERRADA'].copy()
        df_maestro[col_num_nube] = df_maestro[col_num_nube].astype(str).str.replace(r'\D', '', regex=True)

        # 2. VALIDACIÓN: Mozart (Aceptables)
        if archivo_registro.name.endswith('.csv'):
            try:
                df_raw_reg = pd.read_csv(archivo_registro, header=None, dtype=str)
            except:
                archivo_registro.seek(0)
                df_raw_reg = pd.read_csv(archivo_registro, header=None, dtype=str, encoding='latin1')
        else:
            df_raw_reg = pd.read_excel(archivo_registro, header=None, dtype=str)

        header_idx = -1
        for i, row in df_raw_reg.iterrows():
            txt = " ".join(row.dropna().astype(str)).upper()
            if 'ORDEN' in txt and 'ACTIVIDAD' in txt:
                header_idx = i
                break
        
        df_reg = df_raw_reg.iloc[header_idx + 1:].copy()
        df_reg.columns = df_raw_reg.iloc[header_idx]
        df_reg = normalizar_columnas(df_reg.reset_index(drop=True))

        col_num_reg = next((c for c in df_reg.columns if 'ORDEN' in c or 'NUM' in c), None)
        col_est_reg = next((c for c in df_reg.columns if 'ESTADO' in c), None)
        
        df_reg[col_num_reg] = df_reg[col_num_reg].astype(str).str.replace(r'\D', '', regex=True)
        ordenes_aceptables = set(df_reg[df_reg[col_est_reg].astype(str).str.upper() == 'ACEPTABLE'][col_num_reg].tolist())

        # 3. ASIGNACIÓN DE PUNTOS
        def evaluar_puntos(row):
            actividad = str(row.get(col_act_nube, "")).upper()
            orden_id = str(row.get(col_num_nube, ""))
            texto_coment = " ".join([str(row[c]) for c in cols_comentarios if pd.notna(row[c])]).lower()

            # REGLA: Instalaciones (2.5 pts)
            if any(x in actividad for x in ['INSFIBRA', 'INSTALACION']):
                return 2.5
            
            # REGLA: Traslado Externo en comentario (2.5 pts)
            if 'TRASLADO EXTERNO' in texto_coment or 'TRASLADO' in actividad:
                return 2.5

            # REGLA: SOP / SOPFIBRA (Debe ser aceptable en Mozart)
            if 'SOP' in actividad:
                if orden_id in ordenes_aceptables:
                    keywords_cambio = ['cambio de fibra', 'cambio fibra', 'reemplazo de fibra', 'cambio drop', 'fibra nueva', 'se tiro fibra']
                    if any(kw in texto_coment for kw in keywords_cambio):
                        return 2.0
                    return 1.0
            
            # REGLA: Mantenimiento (1 pt si es aceptable)
            if 'MANTENIMIENTO' in actividad and orden_id in ordenes_aceptables:
                return 1.0

            return 0.0

        df_maestro['PUNTOS'] = df_maestro.apply(evaluar_puntos, axis=1)

        # 4. AGRUPACIÓN
        reporte = df_maestro.groupby(col_tec_nube).agg(
            Ordenes_Cerradas=(col_num_nube, 'count'),
            Puntos_Ganados=('PUNTOS', 'sum')
        ).reset_index()

        reporte = reporte.rename(columns={
            col_tec_nube: '👨‍🔧 Nombre del Técnico',
            'Ordenes_Cerradas': '📋 Total Órdenes Cerradas',
            'Puntos_Ganados': '⭐ Puntos Totales'
        })

        return reporte.sort_values(by='⭐ Puntos Totales', ascending=False)

    except Exception as e:
        st.error(f"Error en el procesamiento: {e}")
        return None

def render_modulo_tecnicos():
    st.markdown("### 🏆 Evaluación de Rendimiento (Puntos)")
    st.caption("Base: Nube (Cerradas) | Validación: Registro Mozart (Aceptables)")

    df_nube = st.session_state.get('df_base', None)

    if df_nube is not None and not df_nube.empty:
        st.success("🔗 **Conexión con Google Sheets activa.**")
        
        archivo_reg = st.file_uploader("📂 Sube el Registro de Calidad", type=['csv', 'xlsx'])
        
        if archivo_reg:
            if st.button("🚀 Calcular y Mostrar Resultados", use_container_width=True, type="primary"):
                resultado = procesar_evaluacion_inversa(archivo_reg, df_nube)
                
                if resultado is not None and not resultado.empty:
                    st.divider()
                    
                    # Tabla Nativa (Cero HTML en pantalla)
                    st.dataframe(resultado, use_container_width=True, hide_index=True)
                    
                    st.markdown("### 📥 Descargar Reportes")
                    col_dl1, col_dl2 = st.columns(2)
                    
                    with col_dl1:
                        # Descarga PDF
                        with st.spinner("Generando PDF..."):
                            pdf_file = generar_pdf_puntos(resultado)
                            st.download_button(
                                label="📄 Descargar Reporte en PDF",
                                data=pdf_file,
                                file_name=f"Reporte_Puntos_{pd.Timestamp.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                            
                    with col_dl2:
                        # Descarga CSV
                        csv = resultado.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="📥 Descargar Reporte en CSV",
                            data=csv,
                            file_name="Reporte_Puntos_Tecnicos.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
    else:
        st.warning("⚠️ Los datos de la nube no están sincronizados. Actualiza desde el panel lateral.")
