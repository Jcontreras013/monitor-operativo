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
        self.cell(80, 5, safestr("Reporte Integral de Eficiencia y Atrasos"), ln=False, align="L")
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
        return pd.DataFrame(datos_extraidos)
    except Exception as e:
        st.error(f"Error al procesar el PDF: {e}")
        return pd.DataFrame()

def extraer_fecha_y_hora(val):
    if pd.isnull(val): return None, None
    val_str = str(val).strip()
    
    fecha_dt = None
    if hasattr(val, 'date'):
        fecha_dt = val.date()
        val_str = f"{val.hour:02d}:{val.minute:02d}:{val.second:02d}"
    elif ' ' in val_str:
        partes_espacio = val_str.split(' ')
        try: fecha_dt = pd.to_datetime(partes_espacio[0]).date()
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
    if archivo_excel.name.lower().endswith('.csv'): df_pausas_bruto = pd.read_csv(archivo_excel, header=None)
    else: df_pausas_bruto = pd.read_excel(archivo_excel, header=None)
    
    idx_header = -1
    for idx, row in df_pausas_bruto.iterrows():
        fila_str = ' '.join([str(val).upper() for val in row.tolist()])
        if 'FECHA_INICIO' in fila_str or 'FECHA INICIO' in fila_str:
            idx_header = idx; break
    
    if idx_header == -1: return None, "No se encontraron las columnas FECHA_INICIO y FECHA_FIN en el archivo."
    
    df_pausas = df_pausas_bruto.iloc[idx_header+1:].reset_index(drop=True)
    df_pausas.columns = [str(c).upper().strip() for c in df_pausas_bruto.iloc[idx_header]]
    df_pausas = df_pausas.dropna(axis=1, how='all')
    
    col_tec = next((col for col in df_pausas.columns if 'TEC' in col or 'TÉC' in col), None)
    if not col_tec: return None, "No se encontró la columna de Técnicos en el archivo de pausas."
    
    df_pausas['TECNICO_LIMPIO'] = df_pausas[col_tec].astype(str).str.strip().str.upper()
    
    fechas_ini, horas_ini = zip(*df_pausas['FECHA_INICIO'].apply(extraer_fecha_y_hora))
    fechas_fin, horas_fin = zip(*df_pausas['FECHA_FIN'].apply(extraer_fecha_y_hora))
    
    df_pausas['D_INICIO'], df_pausas['T_INICIO'] = fechas_ini, horas_ini
    df_pausas['D_FIN'], df_pausas['T_FIN'] = fechas_fin, horas_fin
    
    return df_pausas.dropna(subset=['T_INICIO', 'T_FIN']).copy(), None

# ==============================================================================
# 3. GENERADOR DEL SUPER PDF UNIFICADO
# ==============================================================================
def generar_pdf_unificado_tiempos(df_comp, df_detalles, f_ini, f_fin):
    pdf = ReporteEficienciaPDF(orientation='P', unit='mm', format='A4') 
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE INTEGRAL DE EFICIENCIA Y ATRASOS"), ln=True, align='C')
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    rango_str = f"{f_ini.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')}" if f_ini != f_fin else f"{f_ini.strftime('%d/%m/%Y')}"
    pdf.cell(0, 6, safestr(f"Periodo Evaluado: {rango_str}"), ln=True, align='C')
    pdf.ln(8)
    
    # ---------------------------------------------------------
    # SECCIÓN 1: BALANCE COMPARATIVO
    # ---------------------------------------------------------
    if df_comp is not None and not df_comp.empty:
        pdf.seccion_titulo("1. Balance General: Sistema vs Pausas Reportadas")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(225, 225, 225)
        pdf.set_draw_color(200, 200, 200)
        
        w_tec, w_muerto, w_pausa, w_bal = 70, 40, 40, 40
        pdf.cell(w_tec, 8, "COLABORADOR", border=1, align='C', fill=True)
        pdf.cell(w_muerto, 8, "T. MUERTO (SISTEMA)", border=1, align='C', fill=True)
        pdf.cell(w_pausa, 8, "PAUSAS (REPORTADAS)", border=1, align='C', fill=True)
        pdf.cell(w_bal, 8, "BALANCE", border=1, align='C', fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 8)
        for _, row in df_comp.iterrows():
            if pdf.get_y() > 270:
                pdf.add_page()
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_fill_color(225, 225, 225)
                pdf.cell(w_tec, 8, "COLABORADOR", border=1, align='C', fill=True)
                pdf.cell(w_muerto, 8, "T. MUERTO (SISTEMA)", border=1, align='C', fill=True)
                pdf.cell(w_pausa, 8, "PAUSAS (REPORTADAS)", border=1, align='C', fill=True)
                pdf.cell(w_bal, 8, "BALANCE", border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font("Helvetica", "", 8)
                
            tec = safestr(str(row['TECNICO']))[:35]
            muerto = safestr(str(row.get('Tiempo Muerto (PDF)', '0h 0m')))
            pausa = safestr(str(row.get('Pausas Reportadas', '0h 0m')))
            balance = safestr(str(row.get('Balance', '0h 0m')))
            
            pdf.set_text_color(0, 0, 0)
            pdf.cell(w_tec, 7, tec, border=1)
            pdf.cell(w_muerto, 7, muerto, border=1, align='C')
            pdf.cell(w_pausa, 7, pausa, border=1, align='C')
            
            if "+" in balance:
                pdf.set_text_color(0, 128, 0); pdf.set_font("Helvetica", "B", 8)
            elif "-" in balance:
                pdf.set_text_color(200, 0, 0); pdf.set_font("Helvetica", "B", 8)
            else:
                pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 8)
                
            pdf.cell(w_bal, 7, balance, border=1, align='C')
            pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 8)
            pdf.ln()
        
        pdf.ln(5)
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 4, "* Balance Positivo (+ Verde): Las pausas reportadas justifican el tiempo muerto del sistema.", ln=True)
        pdf.cell(0, 4, "* Balance Negativo (- Rojo): El colaborador tiene tiempo muerto en sistema que NO justifico.", ln=True)
        pdf.ln(10)

    # ---------------------------------------------------------
    # SECCIÓN 2: DESGLOSE DETALLADO DE PAUSAS
    # ---------------------------------------------------------
    if df_detalles is not None and not df_detalles.empty:
        pdf.add_page()
        pdf.seccion_titulo("2. Desglose Detallado de Pausas Registradas")
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(0,0,0)
        
        w_d = [50, 50, 25, 20, 20, 25] # Total 190
        pdf.cell(w_d[0], 8, "COLABORADOR", border=1, align='C', fill=True)
        pdf.cell(w_d[1], 8, "MOTIVO / RAZON", border=1, align='C', fill=True)
        pdf.cell(w_d[2], 8, "FECHA", border=1, align='C', fill=True)
        pdf.cell(w_d[3], 8, "INICIO", border=1, align='C', fill=True)
        pdf.cell(w_d[4], 8, "FIN", border=1, align='C', fill=True)
        pdf.cell(w_d[5], 8, "DURACION", border=1, align='C', fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 7)
        df_detalles = df_detalles.sort_values(by=['TECNICO_LIMPIO', 'D_INICIO', 'T_INICIO'])
        
        for _, row in df_detalles.iterrows():
            if pdf.get_y() > 270:
                pdf.add_page()
                pdf.set_font("Helvetica", "B", 7)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(w_d[0], 8, "COLABORADOR", border=1, align='C', fill=True)
                pdf.cell(w_d[1], 8, "MOTIVO / RAZON", border=1, align='C', fill=True)
                pdf.cell(w_d[2], 8, "FECHA", border=1, align='C', fill=True)
                pdf.cell(w_d[3], 8, "INICIO", border=1, align='C', fill=True)
                pdf.cell(w_d[4], 8, "FIN", border=1, align='C', fill=True)
                pdf.cell(w_d[5], 8, "DURACION", border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font("Helvetica", "", 7)
                
            tec = safestr(str(row['TECNICO_LIMPIO']))[:30]
            motivo_raw = str(row.get('RAZON PAUSA', row.get('MOTIVO', 'N/D')))
            if motivo_raw.upper() == 'NAN' or motivo_raw == '': motivo_raw = str(row.get('MOTIVO', 'N/D'))
            motivo = safestr(motivo_raw)[:30]
            
            fecha_str = row['D_INICIO'].strftime("%d/%m/%y") if pd.notnull(row['D_INICIO']) else "N/D"
            ini_val = str(row.get('FECHA_INICIO', '')).split()[-1][:8] if pd.notnull(row.get('FECHA_INICIO')) else "---"
            fin_val = str(row.get('FECHA_FIN', '')).split()[-1][:8] if pd.notnull(row.get('FECHA_FIN')) else "---"
            
            dur_num = row.get('DURACION_HORAS', 0)
            hrs, mins = divmod(dur_num * 60, 60)
            dur_str = f"{int(hrs)}h {int(round(mins))}m"
            
            pdf.cell(w_d[0], 6, tec, border=1)
            pdf.cell(w_d[1], 6, motivo, border=1)
            pdf.cell(w_d[2], 6, fecha_str, border=1, align='C')
            pdf.cell(w_d[3], 6, ini_val, border=1, align='C')
            pdf.cell(w_d[4], 6, fin_val, border=1, align='C')
            pdf.cell(w_d[5], 6, dur_str, border=1, align='C')
            pdf.ln()

    return finalizar_pdf(pdf)

# ==============================================================================
# 4. APLICACIÓN PRINCIPAL (VISTA STREAMLIT)
# ==============================================================================
def mostrar_tiempos_tecnicos():
    st.subheader("Análisis Integral de Eficiencia y Atrasos")
    st.markdown("Genera un PDF unificado cruzando el tiempo muerto del sistema con las pausas justificadas por los técnicos.")
    st.markdown("---")
    
    # 1. Selectores de Fechas
    col_d1, col_d2 = st.columns(2)
    with col_d1: fecha_ini = st.date_input("📅 Fecha de Inicio:", value=datetime.now().date())
    with col_d2: fecha_fin = st.date_input("📅 Fecha de Fin:", value=datetime.now().date())
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 2. Carga de Archivos
    col_f1, col_f2 = st.columns(2)
    with col_f1: archivo_excel = st.file_uploader("1️⃣ Sube el Excel/CSV de Pausas (Obligatorio)", type=['xlsx', 'xls', 'csv'])
    with col_f2: archivo_pdf = st.file_uploader("2️⃣ Sube el PDF de Eficiencia (Opcional)", type=['pdf'])
    
    if archivo_excel:
        with st.spinner("Procesando y unificando reportes..."):
            try:
                # A. Procesar y Filtrar Excel
                df_valido_pausas, error_msg = procesar_excel_pausas_blindado(archivo_excel)
                
                if error_msg:
                    st.error(error_msg)
                else:
                    def checar_rango(d):
                        if pd.isnull(d): return True
                        return fecha_ini <= d <= fecha_fin
                        
                    df_detalles = df_valido_pausas[df_valido_pausas['D_INICIO'].apply(checar_rango)].copy()
                    
                    if df_detalles.empty:
                        st.warning("⚠️ No se encontraron pausas registradas en el rango de fechas seleccionado.")
                    else:
                        df_detalles['DURACION_HORAS'] = df_detalles.apply(calcular_duracion_pausa, axis=1)
                        pausas_agrupadas = df_detalles.groupby('TECNICO_LIMPIO')['DURACION_HORAS'].sum().reset_index()
                        pausas_agrupadas.rename(columns={'TECNICO_LIMPIO': 'TECNICO'}, inplace=True)
                        
                        # B. Procesar PDF si existe
                        if archivo_pdf:
                            df_muerto = extraer_tiempos_muertos_pdf(archivo_pdf)
                            if not df_muerto.empty:
                                df_muerto['MUERTO_HORAS'] = df_muerto['TIEMPO_MUERTO'].apply(extraer_horas_pdf)
                                df_final = pd.merge(df_muerto, pausas_agrupadas, on='TECNICO', how='outer').fillna(0)
                            else:
                                df_final = pausas_agrupadas.copy()
                                df_final['MUERTO_HORAS'] = 0
                                df_final['TIEMPO_MUERTO'] = "0h 0m"
                        else:
                            df_final = pausas_agrupadas.copy()
                            df_final['MUERTO_HORAS'] = 0
                            df_final['TIEMPO_MUERTO'] = "0h 0m"
                        
                        if 'DURACION_HORAS' in df_final.columns:
                            df_final.rename(columns={'DURACION_HORAS': 'PAUSAS_HORAS'}, inplace=True)
                        else:
                            df_final['PAUSAS_HORAS'] = 0
                            
                        # C. Calcular Balances y Textos para la UI
                        df_mostrar = df_final.copy()
                        df_mostrar['Tiempo Muerto (PDF)'] = df_mostrar['MUERTO_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                        df_mostrar['Pausas Reportadas'] = df_mostrar['PAUSAS_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                        df_mostrar['Diferencia_Num'] = df_mostrar['PAUSAS_HORAS'] - df_mostrar['MUERTO_HORAS']
                        
                        def formato_diferencia(val):
                            signo = "+" if val >= 0 else "-"
                            return f"{signo} {int(abs(val))}h {int(round((abs(val)%1)*60))}m"
                            
                        df_mostrar['Balance'] = df_mostrar['Diferencia_Num'].apply(formato_diferencia)
                        
                        # D. Botón de Descarga Unificado
                        pdf_bytes = generar_pdf_unificado_tiempos(df_mostrar, df_detalles, fecha_ini, fecha_fin)
                        st.download_button(
                            label="🚀 GENERAR Y DESCARGAR REPORTE UNIFICADO (PDF)", 
                            data=pdf_bytes, 
                            file_name=f"Reporte_Integral_Eficiencia_{fecha_ini.strftime('%Y%m%d')}.pdf", 
                            mime="application/pdf", 
                            type="primary", 
                            use_container_width=True
                        )
                        st.markdown("---")

                        # E. Vistas en Pantalla (Pestañas)
                        t1, t2, t3 = st.tabs(["📈 Gráfica Comparativa", "⚖️ Balance General", "📋 Detalle de Pausas"])
                        
                        with t1:
                            if archivo_pdf:
                                fig = go.Figure()
                                fig.add_trace(go.Bar(x=df_final['TECNICO'], y=df_final['MUERTO_HORAS'], name='Tiempo Muerto (Sistema)', marker_color='#ef4444'))
                                fig.add_trace(go.Bar(x=df_final['TECNICO'], y=df_final['PAUSAS_HORAS'], name='Pausas Reportadas (< 5 PM)', marker_color='#3b82f6'))
                                fig.update_layout(barmode='group', xaxis_tickangle=-45, height=500, margin=dict(b=150))
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sube el PDF de Eficiencia para poder generar la gráfica comparativa.")
                                
                        with t2:
                            def color_balance(val): return f"color: {'#388e3c' if '+' in val else '#d32f2f'}; font-weight: bold"
                            st.dataframe(df_mostrar[['TECNICO', 'Tiempo Muerto (PDF)', 'Pausas Reportadas', 'Balance']].style.map(color_balance, subset=['Balance']), use_container_width=True, hide_index=True)
                            
                        with t3:
                            df_prev_detalles = df_detalles.copy()
                            df_prev_detalles['Duración Exacta'] = df_prev_detalles['DURACION_HORAS'].apply(lambda x: f"{int(x)}h {int(round((x%1)*60))}m")
                            col_motivo = 'RAZON PAUSA' if 'RAZON PAUSA' in df_prev_detalles.columns else 'MOTIVO'
                            st.dataframe(df_prev_detalles[['TECNICO_LIMPIO', col_motivo, 'FECHA_INICIO', 'FECHA_FIN', 'Duración Exacta']], use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error crítico al procesar los archivos: {e}")
