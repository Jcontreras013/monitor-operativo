import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import re
import fitz  # PyMuPDF para extraer texto del PDF
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import tempfile
import unicodedata

# ==============================================================================
# 1. CLASE PARA PDF Y UTILIDADES GERENCIALES
# ==============================================================================
def safestr(texto):
    if pd.isna(texto): return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

class ReporteEficienciaPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            self.image('logo.png', 10, 8, 33) 
        self.set_y(10)
        self.set_x(50) 
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "", 8)
        self.cell(80, 5, safestr("Reporte Comparativo de Tiempos Muertos y Pausas"), ln=False, align="L")
        self.cell(0, 5, safestr("Maxcom PRO - Modulo Gerencial"), ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        y_line = max(self.get_y(), 20) 
        self.line(10, y_line, 200, y_line)
        self.set_y(y_line + 5)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 10, f"Pagina {self.page_no()} / {{nb}}", align="R")

    def seccion_titulo(self, titulo):
        self.set_text_color(84, 98, 143)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, safestr(titulo), ln=True, align="L")
        self.ln(2)

def finalizar_pdf(pdfobj):
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdfobj.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

# ==============================================================================
# 2. FUNCIONES DE EXTRACCIÓN DE DATOS Y TIEMPO
# ==============================================================================
def extraer_horas_pdf(tiempo_str):
    if not isinstance(tiempo_str, str): return 0
    m = re.match(r'(?i)(\d+)h\s*(\d+)m', tiempo_str.strip().replace('O','0'))
    if m: return int(m.group(1)) + round(int(m.group(2))/60, 2)
    return 0

def extraer_tiempos_muertos_pdf(archivo_pdf):
    try:
        doc = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
        texto_completo = ""
        for pagina in doc: texto_completo += pagina.get_text()
        
        patron_fecha = re.search(r'REPORTE.*?-.*?(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE)
        fecha_reporte = None
        if patron_fecha:
            try:
                fecha_reporte = pd.to_datetime(patron_fecha.group(1), format='%d/%m/%Y').date()
            except: pass

        datos_extraidos = []
        patron_tecnico = re.compile(r'TECNICO:\s*(.+)')
        patron_muerto = re.compile(r'TIEMPO PERDIDO\s*/\s*MUERTO\s*\(Base.*?\):\s*(\d+h\s*\d+m)', re.IGNORECASE)
        
        tecnicos_encontrados = patron_tecnico.findall(texto_completo)
        tiempos_encontrados = patron_muerto.findall(texto_completo)
        
        for i in range(min(len(tecnicos_encontrados), len(tiempos_encontrados))):
            datos_extraidos.append({
                'TECNICO': tecnicos_encontrados[i].strip().upper(),
                'TIEMPO_MUERTO': tiempos_encontrados[i].strip()
            })
        return pd.DataFrame(datos_extraidos), fecha_reporte
    except Exception as e:
        st.error(f"Error al procesar el PDF: {e}")
        return pd.DataFrame(), None

def extraer_fecha_y_hora(val):
    if pd.isnull(val): return None, None
    val_str = str(val).strip()
    
    fecha_dt = None
    if hasattr(val, 'date'):
        fecha_dt = val.date()
        val_str = f"{val.hour:02d}:{val.minute:02d}:{val.second:02d}"
    elif ' ' in val_str:
        partes_espacio = val_str.split(' ')
        try:
            fecha_dt = pd.to_datetime(partes_espacio[0]).date()
        except: pass
        val_str = partes_espacio[-1]
        
    partes = val_str.split(':')
    try:
        h = int(partes[0])
        m = int(partes[1])
        s = int(float(partes[2])) if len(partes) > 2 else 0
        return fecha_dt, timedelta(hours=h, minutes=m, seconds=s)
    except: return None, None

def calcular_duracion_pausa(row):
    ini = row['T_INICIO']
    fin = row['T_FIN']
    if ini is None or fin is None: return 0.0
    
    limite_17h = timedelta(hours=17)
    
    if ini >= limite_17h: return 0.0
        
    if fin < ini or fin > limite_17h: fin_efectivo = limite_17h
    else: fin_efectivo = fin
        
    diff = fin_efectivo - ini
    return max(0.0, diff.total_seconds() / 3600)

def procesar_excel_pausas_blindado(archivo_excel):
    """Encapsula el motor de lectura de Excel para reutilizarlo en ambas pestañas."""
    if archivo_excel.name.lower().endswith('.csv'):
        df_pausas_bruto = pd.read_csv(archivo_excel, header=None)
    else:
        df_pausas_bruto = pd.read_excel(archivo_excel, header=None)
    
    idx_header = -1
    for idx, row in df_pausas_bruto.iterrows():
        fila_str = ' '.join([str(val).upper() for val in row.tolist()])
        if 'FECHA_INICIO' in fila_str or 'FECHA INICIO' in fila_str:
            idx_header = idx
            break
    
    if idx_header == -1: return None, "No se encontraron las columnas FECHA_INICIO y FECHA_FIN en el archivo."
    
    df_pausas = df_pausas_bruto.iloc[idx_header+1:].reset_index(drop=True)
    df_pausas.columns = [str(c).upper().strip() for c in df_pausas_bruto.iloc[idx_header]]
    df_pausas = df_pausas.dropna(axis=1, how='all')
    
    col_tec = next((col for col in df_pausas.columns if 'TEC' in col or 'TÉC' in col), None)
    if not col_tec: return None, "No se encontró la columna de Técnicos en el archivo de pausas."
    
    df_pausas['TECNICO_LIMPIO'] = df_pausas[col_tec].astype(str).str.strip().str.upper()
    
    fechas_ini, horas_ini = zip(*df_pausas['FECHA_INICIO'].apply(extraer_fecha_y_hora))
    fechas_fin, horas_fin = zip(*df_pausas['FECHA_FIN'].apply(extraer_fecha_y_hora))
    
    df_pausas['D_INICIO'] = fechas_ini
    df_pausas['T_INICIO'] = horas_ini
    df_pausas['D_FIN'] = fechas_fin
    df_pausas['T_FIN'] = horas_fin
    
    df_valido_pausas = df_pausas.dropna(subset=['T_INICIO', 'T_FIN']).copy()
    
    return df_valido_pausas, None

# ==============================================================================
# 3. CONSTRUCTORES DE REPORTE PDF FINAL
# ==============================================================================
def generar_pdf_comparativo(df_mostrar, fecha_str):
    pdf = ReporteEficienciaPDF(orientation='P', unit='mm', format='A4') 
    pdf.alias_nb_pages()
    pdf.add_page()
    hoy_str = datetime.now().strftime("%d/%m/%Y")
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE COMPARATIVO DE TIEMPOS MUERTOS"), ln=True, align='C')
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    
    fecha_titulo = fecha_str if fecha_str else hoy_str
    pdf.cell(0, 6, safestr(f"Corte Evaluativo: {fecha_titulo}"), ln=True, align='C')
    pdf.ln(8)
    
    pdf.seccion_titulo("Analisis de Diferencia: Sistema vs Pausas Reportadas")
    
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(225, 225, 225)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_text_color(50, 50, 50)
    
    w_tec, w_muerto, w_pausa, w_bal = 70, 40, 40, 40
    pdf.cell(w_tec, 8, "COLABORADOR", border=1, align='C', fill=True)
    pdf.cell(w_muerto, 8, "T. MUERTO (SISTEMA)", border=1, align='C', fill=True)
    pdf.cell(w_pausa, 8, "PAUSAS (REPORTADAS)", border=1, align='C', fill=True)
    pdf.cell(w_bal, 8, "BALANCE", border=1, align='C', fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 8)
    for _, row in df_mostrar.iterrows():
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(225, 225, 225)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(w_tec, 8, "COLABORADOR", border=1, align='C', fill=True)
            pdf.cell(w_muerto, 8, "T. MUERTO (SISTEMA)", border=1, align='C', fill=True)
            pdf.cell(w_pausa, 8, "PAUSAS (REPORTADAS)", border=1, align='C', fill=True)
            pdf.cell(w_bal, 8, "BALANCE", border=1, align='C', fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            
        tec = safestr(str(row['TECNICO']))[:35]
        muerto = safestr(str(row['Tiempo Muerto (PDF)']))
        pausa = safestr(str(row['Pausas Reportadas']))
        balance = safestr(str(row['Balance (Pausas - T. Muerto)']))
        
        pdf.set_text_color(0, 0, 0)
        pdf.cell(w_tec, 7, tec, border=1)
        pdf.cell(w_muerto, 7, muerto, border=1, align='C')
        pdf.cell(w_pausa, 7, pausa, border=1, align='C')
        
        if "+" in balance:
            pdf.set_text_color(0, 128, 0) 
            pdf.set_font("Helvetica", "B", 8)
        elif "-" in balance:
            pdf.set_text_color(200, 0, 0) 
            pdf.set_font("Helvetica", "B", 8)
        else:
            pdf.set_text_color(0, 0, 0) 
            pdf.set_font("Helvetica", "", 8)
            
        pdf.cell(w_bal, 7, balance, border=1, align='C')
        pdf.set_text_color(0, 0, 0) 
        pdf.set_font("Helvetica", "", 8)
        pdf.ln()
        
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, "* Notas de lectura (Corte a las 17:00 hrs):", ln=True)
    pdf.cell(0, 5, "- Balance Positivo (+ Verde): Las pausas reportadas justifican y exceden el tiempo muerto registrado en sistema.", ln=True)
    pdf.cell(0, 5, "- Balance Negativo (- Rojo): El colaborador tiene tiempo muerto en sistema que no justifico con pausas.", ln=True)

    return finalizar_pdf(pdf)

def generar_pdf_solo_pausas(df_detalles, pausas_agrupadas, archivo_nombre):
    pdf = ReporteEficienciaPDF(orientation='P', unit='mm', format='A4') 
    # Sustituimos el título en el header nativo solo para esta instancia
    class ReportePausas(ReporteEficienciaPDF):
        def header(self):
            if os.path.exists('logo.png'):
                self.image('logo.png', 10, 8, 33) 
            self.set_y(10)
            self.set_x(50) 
            self.set_text_color(0, 0, 0)
            self.set_font("Helvetica", "", 8)
            self.cell(80, 5, safestr("Reporte Gerencial Analitico de Pausas (Atrasos)"), ln=False, align="L")
            self.cell(0, 5, safestr("Maxcom PRO - Modulo Gerencial"), ln=True, align="R")
            self.set_draw_color(200, 200, 200)
            y_line = max(self.get_y(), 20) 
            self.line(10, y_line, 200, y_line)
            self.set_y(y_line + 5)

    pdf = ReportePausas(orientation='P', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    hoy_str = datetime.now().strftime("%d/%m/%Y")
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE GERENCIAL DE PAUSAS Y ATRASOS"), ln=True, align='C')
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Corte Evaluativo: {hoy_str} | Archivo: {archivo_nombre}"), ln=True, align='C')
    pdf.ln(8)
    
    # 1. TABLA RESUMEN
    pdf.seccion_titulo("Resumen Consolidado por Colaborador")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(225, 225, 225)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_text_color(50, 50, 50)
    
    pdf.cell(120, 8, "COLABORADOR", border=1, align='C', fill=True)
    pdf.cell(70, 8, "TIEMPO TOTAL EN PAUSA", border=1, align='C', fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(0, 0, 0)
    for _, row in pausas_agrupadas.iterrows():
        tec = safestr(row['TECNICO'])[:60]
        dur_num = row['DURACION_HORAS']
        hrs, mins = divmod(dur_num * 60, 60)
        dur_str = f"{int(hrs)}h {int(round(mins))}m"
        
        pdf.cell(120, 7, tec, border=1, align='L')
        pdf.cell(70, 7, dur_str, border=1, align='C')
        pdf.ln()
        
    pdf.ln(10)
    
    # 2. TABLA DETALLADA DE PAUSAS
    pdf.seccion_titulo("Detalle Integral de Pausas Registradas")
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(60, 8, "COLABORADOR", border=1, align='C', fill=True)
    pdf.cell(60, 8, "MOTIVO / RAZON", border=1, align='C', fill=True)
    pdf.cell(20, 8, "INICIO", border=1, align='C', fill=True)
    pdf.cell(20, 8, "FIN", border=1, align='C', fill=True)
    pdf.cell(30, 8, "DURACION", border=1, align='C', fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 7)
    
    # Ordenar para que el detalle se vea bonito por técnico
    df_detalles = df_detalles.sort_values(by=['TECNICO_LIMPIO', 'T_INICIO'])
    
    for _, row in df_detalles.iterrows():
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(60, 8, "COLABORADOR", border=1, align='C', fill=True)
            pdf.cell(60, 8, "MOTIVO / RAZON", border=1, align='C', fill=True)
            pdf.cell(20, 8, "INICIO", border=1, align='C', fill=True)
            pdf.cell(20, 8, "FIN", border=1, align='C', fill=True)
            pdf.cell(30, 8, "DURACION", border=1, align='C', fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 7)
            
        tec = safestr(str(row['TECNICO_LIMPIO']))[:35]
        
        # Buscar el motivo o la razón dependiendo de cómo venga la columna
        motivo_raw = str(row.get('RAZON PAUSA', row.get('MOTIVO', 'N/D')))
        if motivo_raw.upper() == 'NAN' or motivo_raw == '':
            motivo_raw = str(row.get('MOTIVO', 'N/D'))
        motivo = safestr(motivo_raw)[:35]
        
        ini_val = str(row.get('FECHA_INICIO', '')).split()[-1][:8] if pd.notnull(row.get('FECHA_INICIO')) else "N/D"
        fin_val = str(row.get('FECHA_FIN', '')).split()[-1][:8] if pd.notnull(row.get('FECHA_FIN')) else "N/D"
        
        dur_num = row['DURACION_HORAS']
        hrs, mins = divmod(dur_num * 60, 60)
        dur_str = f"{int(hrs)}h {int(round(mins))}m"
        
        pdf.cell(60, 6, tec, border=1)
        pdf.cell(60, 6, motivo, border=1)
        pdf.cell(20, 6, ini_val, border=1, align='C')
        pdf.cell(20, 6, fin_val, border=1, align='C')
        pdf.cell(30, 6, dur_str, border=1, align='C')
        pdf.ln()

    return finalizar_pdf(pdf)

# ==============================================================================
# 4. APLICACIÓN PRINCIPAL (VISTA STREAMLIT)
# ==============================================================================
def mostrar_tiempos_tecnicos():
    st.subheader("Análisis de Eficiencia y Atrasos")
    
    tab_comp, tab_rep = st.tabs(["⚖️ Comparativa (PDF vs Excel)", "📋 Reporte Atrasos (Solo Excel)"])
    
    # -------------------------------------------------------------------------
    # PESTAÑA 1: COMPARATIVA
    # -------------------------------------------------------------------------
    with tab_comp:
        st.markdown("Sube los reportes del día para auditar la eficiencia topada a las 5:00 PM.")
        col1, col2 = st.columns(2)
        with col1:
            archivo_excel = st.file_uploader("1. Sube el Excel/CSV de Pausas", type=['xlsx', 'xls', 'csv'])
        with col2:
            archivo_pdf = st.file_uploader("2. Sube el PDF de Eficiencia", type=['pdf'])
            
        if archivo_excel and archivo_pdf:
            with st.spinner("Procesando y cruzando reportes..."):
                try:
                    df_muerto, fecha_pdf = extraer_tiempos_muertos_pdf(archivo_pdf)
                    if df_muerto.empty:
                        st.warning("No se pudieron extraer los tiempos muertos del PDF.")
                    else:
                        df_muerto['MUERTO_HORAS'] = df_muerto['TIEMPO_MUERTO'].apply(extraer_horas_pdf)

                        df_valido_pausas, error_msg = procesar_excel_pausas_blindado(archivo_excel)
                        if error_msg:
                            st.error(error_msg)
                        else:
                            # Filtro estricto por la fecha del PDF
                            if fecha_pdf:
                                mask_fecha = (df_valido_pausas['D_INICIO'] == fecha_pdf) | (df_valido_pausas['D_FIN'] == fecha_pdf) | (df_valido_pausas['D_INICIO'].isnull())
                                df_valido_pausas = df_valido_pausas[mask_fecha]
                            else:
                                st.warning("No se pudo detectar la fecha del PDF. Se sumarán todas las pausas disponibles.")
                            
                            if not df_valido_pausas.empty:
                                df_valido_pausas['DURACION_HORAS'] = df_valido_pausas.apply(calcular_duracion_pausa, axis=1)
                                pausas_agrupadas = df_valido_pausas.groupby('TECNICO_LIMPIO')['DURACION_HORAS'].sum().reset_index()
                                pausas_agrupadas.rename(columns={'TECNICO_LIMPIO': 'TECNICO'}, inplace=True)
                            else:
                                pausas_agrupadas = pd.DataFrame(columns=['TECNICO', 'DURACION_HORAS'])
                            
                            df_final = pd.merge(df_muerto, pausas_agrupadas, on='TECNICO', how='left').fillna(0)
                            df_final.rename(columns={'DURACION_HORAS': 'PAUSAS_HORAS'}, inplace=True)
                            
                            df_mostrar = df_final.copy()
                            df_mostrar['Tiempo Muerto (PDF)'] = df_mostrar['MUERTO_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                            df_mostrar['Pausas Reportadas'] = df_mostrar['PAUSAS_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                            
                            df_mostrar['Diferencia_Num'] = df_mostrar['PAUSAS_HORAS'] - df_mostrar['MUERTO_HORAS']
                            def formato_diferencia(val):
                                signo = "+" if val >= 0 else "-"
                                return f"{signo} {int(abs(val))}h {int(round((abs(val)%1)*60))}m"
                            df_mostrar['Balance (Pausas - T. Muerto)'] = df_mostrar['Diferencia_Num'].apply(formato_diferencia)

                            fig = go.Figure()
                            fig.add_trace(go.Bar(x=df_final['TECNICO'], y=df_final['MUERTO_HORAS'], name='Tiempo Muerto (Sistema)', marker_color='#ef4444'))
                            fig.add_trace(go.Bar(x=df_final['TECNICO'], y=df_final['PAUSAS_HORAS'], name='Pausas Reportadas (< 5 PM)', marker_color='#3b82f6'))
                            fig.update_layout(barmode='group', title=f"Contraste Operativo por Técnico - {fecha_pdf.strftime('%d/%m/%Y') if fecha_pdf else ''}", xaxis_tickangle=-45, height=550, margin=dict(b=150))
                            st.plotly_chart(fig, use_container_width=True)
                            
                            st.markdown("### 📋 Cuadro Comparativo Detallado")
                            col_down1, col_down2 = st.columns([1, 2])
                            with col_down1:
                                fecha_pdf_str = fecha_pdf.strftime("%d/%m/%Y") if fecha_pdf else None
                                pdf_bytes = generar_pdf_comparativo(df_mostrar, fecha_pdf_str)
                                st.download_button("📄 Descargar Reporte Gerencial en PDF", data=pdf_bytes, file_name=f"Comparativo_Eficiencia_{fecha_pdf.strftime('%Y%m%d') if fecha_pdf else datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                            with col_down2:
                                st.caption("ℹ️ El PDF incluye la tabla auditora con balances en semáforo. Las pausas reportadas se topan automáticamente a las 5:00 PM.")
                            
                            st.markdown("<br>", unsafe_allow_html=True)
                            def color_balance(val): return f"color: {'#388e3c' if '+' in val else '#d32f2f'}; font-weight: bold"
                            st.dataframe(df_mostrar[['TECNICO', 'Tiempo Muerto (PDF)', 'Pausas Reportadas', 'Balance (Pausas - T. Muerto)']].style.map(color_balance, subset=['Balance (Pausas - T. Muerto)']), use_container_width=True, hide_index=True)
                            
                except Exception as e:
                    st.error(f"Error crítico al procesar los archivos: {e}")
        else:
            st.info("👆 Por favor sube ambos archivos en esta pestaña para cruzar la información.")

    # -------------------------------------------------------------------------
    # PESTAÑA 2: REPORTE GERENCIAL DE SOLO PAUSAS
    # -------------------------------------------------------------------------
    with tab_rep:
        st.markdown("Sube el archivo Excel o CSV de atrasos para generar un PDF formal (Se procesarán todas las filas válidas del archivo).")
        archivo_solo_excel = st.file_uploader("Sube el Excel/CSV de Pausas", type=['xlsx', 'xls', 'csv'], key="solo_excel")
        
        if archivo_solo_excel:
            with st.spinner("Procesando desglose de pausas..."):
                try:
                    df_valido_pausas, error_msg = procesar_excel_pausas_blindado(archivo_solo_excel)
                    if error_msg:
                        st.error(error_msg)
                    else:
                        if not df_valido_pausas.empty:
                            df_valido_pausas['DURACION_HORAS'] = df_valido_pausas.apply(calcular_duracion_pausa, axis=1)
                            pausas_agrupadas = df_valido_pausas.groupby('TECNICO_LIMPIO')['DURACION_HORAS'].sum().reset_index()
                            pausas_agrupadas.rename(columns={'TECNICO_LIMPIO': 'TECNICO'}, inplace=True)
                            
                            col_down_p1, col_down_p2 = st.columns([1, 2])
                            with col_down_p1:
                                pdf_bytes_pausas = generar_pdf_solo_pausas(df_valido_pausas, pausas_agrupadas, archivo_solo_excel.name)
                                st.download_button(
                                    label="📄 Generar y Descargar PDF de Atrasos",
                                    data=pdf_bytes_pausas,
                                    file_name=f"Reporte_Atrasos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                    mime="application/pdf",
                                    type="primary",
                                    use_container_width=True
                                )
                            with col_down_p2:
                                st.success("✅ Datos analizados correctamente. Haz clic en el botón para descargar el reporte.")
                            
                            st.markdown("---")
                            st.markdown("**Vista previa del consolidado:**")
                            
                            df_preview = pausas_agrupadas.copy()
                            df_preview['Duracion Exacta'] = df_preview['DURACION_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                            st.dataframe(df_preview[['TECNICO', 'Duracion Exacta']], use_container_width=True, hide_index=True)
                        else:
                            st.warning("El archivo no contiene registros de horas válidos.")
                except Exception as e:
                    st.error(f"Error crítico al procesar el archivo: {e}")
