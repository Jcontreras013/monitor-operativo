import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import re
import fitz  # PyMuPDF para extraer texto del PDF
from fpdf import FPDF
from datetime import datetime

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
        doc = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
        texto_completo = ""
        for pagina in doc:
            texto_completo += pagina.get_text()
        
        datos_extraidos = []
        patron_tecnico = re.compile(r'TECNICO:\s*(.+)')
        patron_muerto = re.compile(r'TIEMPO PERDIDO\s*/\s*MUERTO\s*\(Base 8 Horas\):\s*(\d+h\s*\d+m)', re.IGNORECASE)
        
        tecnicos_encontrados = patron_tecnico.findall(texto_completo)
        tiempos_encontrados = patron_muerto.findall(texto_completo)
        
        for i in range(min(len(tecnicos_encontrados), len(tiempos_encontrados))):
            datos_extraidos.append({
                'TECNICO': tecnicos_encontrados[i].strip().upper(),
                'TIEMPO_MUERTO': tiempos_encontrados[i].strip()
            })
            
        return pd.DataFrame(datos_extraidos)
    except Exception as e:
        st.error(f"Error al procesar el PDF: {e}")
        return pd.DataFrame()

# === NUEVA FUNCIÓN DE EXPORTACIÓN A PDF ===
def generar_pdf_comparativo(df_mostrar):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Título
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(40, 50, 100)
    hoy_str = datetime.now().strftime("%d/%m/%Y")
    pdf.cell(0, 10, f"REPORTE COMPARATIVO DE TIEMPOS MUERTOS VS PAUSAS - {hoy_str}", ln=True, align='C')
    pdf.ln(5)
    
    # Encabezados de tabla
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(220, 230, 250)
    pdf.cell(90, 8, "TECNICO", border=1, align='C', fill=True)
    pdf.cell(50, 8, "TIEMPO MUERTO (PDF)", border=1, align='C', fill=True)
    pdf.cell(50, 8, "PAUSAS (EXCEL/CSV)", border=1, align='C', fill=True)
    pdf.cell(50, 8, "BALANCE", border=1, align='C', fill=True)
    pdf.ln()
    
    # Filas de datos
    pdf.set_font("Arial", '', 9)
    for _, row in df_mostrar.iterrows():
        tec = str(row['TECNICO']).encode('latin-1', 'ignore').decode('latin-1')[:45]
        muerto = str(row['Tiempo Muerto (PDF)'])
        pausa = str(row['Pausas Justificadas (Excel/CSV)'])
        balance = str(row['Balance (Justificado - Muerto)'])
        
        pdf.cell(90, 8, tec, border=1)
        pdf.cell(50, 8, muerto, border=1, align='C')
        pdf.cell(50, 8, pausa, border=1, align='C')
        
        # Colorear solo la celda de balance
        if "+" in balance:
            pdf.set_text_color(0, 128, 0) # Verde
        elif "-" in balance:
            pdf.set_text_color(200, 0, 0) # Rojo
        else:
            pdf.set_text_color(0, 0, 0)
            
        pdf.cell(50, 8, balance, border=1, align='C')
        pdf.set_text_color(0, 0, 0) # Resetear a negro para la siguiente fila
        pdf.ln()

    # Retorna los bytes listos para descargar
    return pdf.output(dest='S').encode('latin-1')

def mostrar_tiempos_tecnicos():
    st.subheader("Análisis de Eficiencia: Tiempo Muerto vs Pausas Reportadas")
    st.markdown("Sube los reportes del día para comparar la eficiencia de la cuadrilla.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        archivo_excel = st.file_uploader("1. Sube el Excel/CSV de Pausas (Atrasos)", type=['xlsx', 'xls', 'csv'])
    
    with col2:
        archivo_pdf = st.file_uploader("2. Sube el PDF de Eficiencia (Tiempos Muertos)", type=['pdf'])
        
    if archivo_excel and archivo_pdf:
        with st.spinner("Procesando y cruzando reportes..."):
            try:
                # 1. Procesar Excel/CSV de Pausas
                if archivo_excel.name.lower().endswith('.csv'):
                    df_pausas = pd.read_csv(archivo_excel)
                    if 'TECNICO5' not in df_pausas.columns and 'TECNICO' not in df_pausas.columns:
                        archivo_excel.seek(0)
                        df_pausas = pd.read_csv(archivo_excel, header=2)
                else:
                    try:
                        df_pausas = pd.read_excel(archivo_excel, sheet_name='Hoja1', header=2)
                    except:
                        archivo_excel.seek(0)
                        df_pausas = pd.read_excel(archivo_excel) 
                        
                df_pausas = df_pausas.dropna(axis=1, how='all')
                
                if 'TECNICO5' in df_pausas.columns:
                    df_pausas['TECNICO'] = df_pausas['TECNICO5'].str.strip().str.upper()
                elif 'TECNICO' in df_pausas.columns:
                    df_pausas['TECNICO'] = df_pausas['TECNICO'].str.strip().str.upper()
                else:
                    st.error("No se encontró la columna de técnicos ('TECNICO' o 'TECNICO5') en el archivo. Verifica el formato.")
                    return
                
                df_pausas['FECHA_INICIO'] = pd.to_datetime(df_pausas['FECHA_INICIO'], errors='coerce')
                df_pausas['FECHA_FIN'] = pd.to_datetime(df_pausas['FECHA_FIN'], errors='coerce')
                
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
                
                # 5. Tabla Comparativa y Botón de Descarga
                st.markdown("### 📋 Cuadro Comparativo Detallado")
                
                # === BOTÓN DE DESCARGA PDF ===
                col_down1, col_down2 = st.columns([1, 2])
                with col_down1:
                    pdf_bytes = generar_pdf_comparativo(df_mostrar)
                    st.download_button(
                        label="📥 Descargar Reporte en PDF",
                        data=pdf_bytes,
                        file_name=f"Comparativo_Tiempos_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                with col_down2:
                    st.caption("ℹ️ El PDF incluirá la tabla detallada de auditoría para su revisión formal.")
                
                st.markdown("<br>", unsafe_allow_html=True)
                
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
