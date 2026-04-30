import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import re
import fitz  # PyMuPDF para extraer texto del PDF de manera robusta

# REGLA DE DIAMANTE: No tocar la lógica de la app principal, solo se agrega este módulo.

def extraer_horas(tiempo_str):
    if not isinstance(tiempo_str, str): return 0
    m = re.match(r'(?i)(\d+)h\s*(\d+)m', tiempo_str.strip().replace('O','0'))
    if m:
        return int(m.group(1)) + round(int(m.group(2))/60, 2)
    return 0

def extraer_tiempos_muertos_pdf(archivo_pdf):
    """Extrae los nombres de los técnicos y su tiempo perdido desde el PDF subido."""
    try:
        # Usamos PyMuPDF (fitz) que es más robusto para leer PDFs complejos
        doc = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
        texto_completo = ""
        for pagina in doc:
            texto_completo += pagina.get_text()
        
        datos_extraidos = []
        
        # Buscar el nombre del técnico
        patron_tecnico = re.compile(r'TECNICO:\s*(.+)')
        # Buscar el tiempo muerto base 8 horas
        patron_muerto = re.compile(r'TIEMPO PERDIDO\s*/\s*MUERTO\s*\(Base 8 Horas\):\s*(\d+h\s*\d+m)', re.IGNORECASE)
        
        tecnicos_encontrados = patron_tecnico.findall(texto_completo)
        tiempos_encontrados = patron_muerto.findall(texto_completo)
        
        # Emparejar cada técnico con su tiempo muerto
        for i in range(min(len(tecnicos_encontrados), len(tiempos_encontrados))):
            datos_extraidos.append({
                'TECNICO': tecnicos_encontrados[i].strip().upper(),
                'TIEMPO_MUERTO': tiempos_encontrados[i].strip()
            })
            
        return pd.DataFrame(datos_extraidos)
    except Exception as e:
        st.error(f"Error al procesar el PDF: {e}")
        return pd.DataFrame()

def mostrar_tiempos_tecnicos():
    st.subheader("Análisis de Eficiencia: Tiempo Muerto vs Pausas Reportadas")
    st.markdown("Sube los reportes del día para comparar la eficiencia de la cuadrilla.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # AHORA ACEPTA CSV TAMBIÉN
        archivo_excel = st.file_uploader("1. Sube el Excel/CSV de Pausas (Atrasos)", type=['xlsx', 'xls', 'csv'])
    
    with col2:
        archivo_pdf = st.file_uploader("2. Sube el PDF de Eficiencia (Tiempos Muertos)", type=['pdf'])
        
    if archivo_excel and archivo_pdf:
        with st.spinner("Procesando y cruzando reportes..."):
            try:
                # 1. Procesar Excel/CSV de Pausas
                if archivo_excel.name.lower().endswith('.csv'):
                    # Intento de lectura para CSV
                    df_pausas = pd.read_csv(archivo_excel)
                    # Si el CSV se exportó con las 2 filas vacías arriba (como el Excel), lo ajustamos
                    if 'TECNICO5' not in df_pausas.columns and 'TECNICO' not in df_pausas.columns:
                        archivo_excel.seek(0)
                        df_pausas = pd.read_csv(archivo_excel, header=2)
                else:
                    # Intento de lectura normal para Excel
                    try:
                        df_pausas = pd.read_excel(archivo_excel, sheet_name='Hoja1', header=2)
                    except:
                        archivo_excel.seek(0)
                        df_pausas = pd.read_excel(archivo_excel) # Fallback si no tiene 'Hoja1'
                        
                df_pausas = df_pausas.dropna(axis=1, how='all')
                
                # Normalización del nombre de la columna de técnico
                if 'TECNICO5' in df_pausas.columns:
                    df_pausas['TECNICO'] = df_pausas['TECNICO5'].str.strip().str.upper()
                elif 'TECNICO' in df_pausas.columns:
                    df_pausas['TECNICO'] = df_pausas['TECNICO'].str.strip().str.upper()
                else:
                    st.error("No se encontró la columna de técnicos ('TECNICO' o 'TECNICO5') en el archivo. Verifica el formato.")
                    return
                
                df_pausas['FECHA_INICIO'] = pd.to_datetime(df_pausas['FECHA_INICIO'], errors='coerce')
                df_pausas['FECHA_FIN'] = pd.to_datetime(df_pausas['FECHA_FIN'], errors='coerce')
                
                # Calcular pausas totales en horas
                df_valido_pausas = df_pausas.dropna(subset=['FECHA_INICIO', 'FECHA_FIN']).copy()
                df_valido_pausas['DURACION_HORAS'] = (df_valido_pausas['FECHA_FIN'] - df_valido_pausas['FECHA_INICIO']).dt.total_seconds() / 3600
                pausas_agrupadas = df_valido_pausas.groupby('TECNICO')['DURACION_HORAS'].sum().reset_index()
                
                # 2. Procesar PDF de Tiempos Muertos
                df_muerto = extraer_tiempos_muertos_pdf(archivo_pdf)
                
                if df_muerto.empty:
                    st.warning("No se pudieron extraer los tiempos muertos del PDF. Revisa el formato.")
                    return
                
                df_muerto['MUERTO_HORAS'] = df_muerto['TIEMPO_MUERTO'].apply(extraer_horas)

                # 3. Unir y calcular diferencias
                df_final = pd.merge(df_muerto, pausas_agrupadas, on='TECNICO', how='left').fillna(0)
                df_final.rename(columns={'DURACION_HORAS': 'PAUSAS_HORAS'}, inplace=True)
                
                # Formateo visual del cuadro
                df_mostrar = df_final.copy()
                df_mostrar['Tiempo Muerto (PDF)'] = df_mostrar['MUERTO_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                df_mostrar['Pausas Justificadas (Excel/CSV)'] = df_mostrar['PAUSAS_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                
                df_mostrar['Diferencia_Num'] = df_mostrar['PAUSAS_HORAS'] - df_mostrar['MUERTO_HORAS']
                
                def formato_diferencia(val):
                    signo = "+" if val >= 0 else "-"
                    val_abs = abs(val)
                    return f"{signo} {int(val_abs)}h {int(round((val_abs%1)*60))}m"
                
                df_mostrar['Balance (Justificado - Muerto)'] = df_mostrar['Diferencia_Num'].apply(formato_diferencia)

                # 4. Visualización Gráfica
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_final['TECNICO'], 
                    y=df_final['MUERTO_HORAS'],
                    name='Tiempo Muerto (Órdenes)',
                    marker_color='#ef4444' # Rojo indicador
                ))
                fig.add_trace(go.Bar(
                    x=df_final['TECNICO'], 
                    y=df_final['PAUSAS_HORAS'],
                    name='Pausas (Reportadas a Supervisor)',
                    marker_color='#3b82f6' # Azul justificado
                ))
                fig.update_layout(
                    barmode='group',
                    title="Contraste Operativo por Técnico",
                    xaxis_tickangle=-45,
                    height=550,
                    margin=dict(b=150)
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # 5. Tabla Comparativa
                st.markdown("### 📋 Cuadro Comparativo Detallado")
                
                def color_balance(val):
                    color = '#388e3c' if '+' in val else '#d32f2f'
                    return f'color: {color}; font-weight: bold'
                
                st.dataframe(
                    df_mostrar[['TECNICO', 'Tiempo Muerto (PDF)', 'Pausas Justificadas (Excel/CSV)', 'Balance (Justificado - Muerto)']].style.map(color_balance, subset=['Balance (Justificado - Muerto)']),
                    use_container_width=True,
                    hide_index=True
                )
                
            except Exception as e:
                st.error(f"Error procesando los archivos: {e}")
    else:
        st.info("👆 Por favor sube ambos archivos para generar el cruce de información.")
