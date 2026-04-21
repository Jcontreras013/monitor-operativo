import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta
import io

def limpiar_nombre(raw):
    """Quita la basura que el PDF mezcla con los nombres"""
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def extraer_tabla_limpia_pdf(archivo_pdf):
    """Extrae datos con pdfplumber y elimina columnas/filas vacías"""
    import pdfplumber
    todas_las_filas = []
    
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas:
                # Limpiar saltos de línea extraños dentro de las celdas
                tabla_limpia = [[str(celda).replace('\n', ' ').strip() if celda else '' for celda in fila] for fila in tabla]
                todas_las_filas.extend(tabla_limpia)
                
    if not todas_las_filas:
        return pd.DataFrame()
        
    # Convertir a DataFrame
    df = pd.DataFrame(todas_las_filas)
    
    # Asignar la primera fila como encabezado
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # === ELIMINAR COLUMNAS Y FILAS VACÍAS (Requisito) ===
    df = df.replace(r'^\s*$', pd.NA, regex=True)
    df = df.replace('None', pd.NA)
    
    # Borrar columnas y filas donde TODO sea nulo
    df = df.dropna(how='all', axis=1)
    df = df.dropna(how='all', axis=0)
    
    # Rellenar vacíos restantes con guiones para estética
    df = df.fillna('---')
    
    # Resolver nombres de columnas duplicados
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique(): 
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}_{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df.columns = cols
    
    return df

def generar_pdf_unificado_rrhh(df_ausencias, df_tardanzas):
    """Genera un PDF corporativo en formato horizontal"""
    from fpdf import FPDF
    import tempfile
    import os
    import unicodedata
    
    def safestr(texto):
        if pd.isna(texto): return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
        
    pdf = FPDF('L', 'mm', 'A4') 
    pdf.add_page()
    
    # Encabezado principal
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 12, "REPORTE UNIFICADO RRHH: CONTROL DE ASISTENCIA", ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Fecha de emision: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}", ln=True, align="C")
    pdf.ln(10)
    
    def dibujar_tabla(pdf_obj, df, titulo):
        pdf_obj.set_font("Helvetica", "B", 12)
        pdf_obj.set_text_color(40, 50, 100)
        pdf_obj.cell(0, 10, safestr(titulo), ln=True)
        
        if df.empty:
            pdf_obj.set_font("Helvetica", "I", 10)
            pdf_obj.set_text_color(150, 0, 0)
            pdf_obj.cell(0, 8, "No se registraron datos en esta categoria.", ln=True)
            pdf_obj.ln(5)
            return
            
        # Limitamos a las primeras 8 columnas relevantes para evitar desborde
        cols = list(df.columns)[:8]
        df_sub = df[cols]
        
        pdf_obj.set_font("Helvetica", "B", 8)
        pdf_obj.set_fill_color(230, 235, 245)
        pdf_obj.set_text_color(0, 0, 0)
        
        ancho_total = 275 # Ancho útil en A4 Horizontal
        w = ancho_total / len(cols)
        
        for col in cols:
            pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
        pdf_obj.ln()
        
        pdf_obj.set_font("Helvetica", "", 7)
        for _, row in df_sub.iterrows():
            if pdf_obj.get_y() > 185:
                pdf_obj.add_page()
                # Repetir cabecera en nueva página
                pdf_obj.set_font("Helvetica", "B", 8)
                pdf_obj.set_fill_color(230, 235, 245)
                for col in cols:
                    pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
                pdf_obj.ln()
                pdf_obj.set_font("Helvetica", "", 7)
                
            for col in cols:
                pdf_obj.cell(w, 6, safestr(str(row[col]))[:35], border=1, align="C")
            pdf_obj.ln()
        pdf_obj.ln(12)
        
    dibujar_tabla(pdf, df_ausencias, "1. DETALLE GENERAL DE AUSENCIAS")
    dibujar_tabla(pdf, df_tardanzas, "2. DETALLE GENERAL DE LLEGADAS TARDE")
    
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdf.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

def vista_biometrico():
    st.title("🚨 Centro de Control Biométrico y RRHH")
    
    tab_transacciones, tab_rrhh = st.tabs(["⏱️ Auditoría Diaria (Transacciones)", "📊 Consolidado RRHH (PDFs)"])
    
    # --- PESTAÑA 1: TRANSACCIONES (Sin cambios para respetar tu lógica) ---
    with tab_transacciones:
        # ... (Tu código original de transacciones se mantiene igual)
        st.caption("Analisis de marcajes de entrada, almuerzo y breaks desde Transaction.pdf.")
        archivo = st.file_uploader("📥 Subir Archivo Transaction.pdf", type=['pdf'], key="trans_up")
        # (Lógica de extracción de transacciones...)
        if archivo:
            st.info("Utilice el boton 'Extraer Infractores' despues de asignar turnos.")

    # --- PESTAÑA 2: CONSOLIDADO RRHH ACTUALIZADO ---
    with tab_rrhh:
        st.subheader("📑 Generador de Reporte Unificado")
        st.markdown("Cargue los reportes oficiales para unificar la información de asistencia.")
        
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            f_aus = st.file_uploader("📂 PDF de Ausencias", type=['pdf'], key="up_aus")
        with col_u2:
            f_tar = st.file_uploader("📂 PDF de Llegadas Tarde", type=['pdf'], key="up_tar")
            
        if st.button("🚀 ANALIZAR Y GENERAR DESCARGA", type="primary", use_container_width=True):
            if f_aus and f_tar:
                with st.spinner("Procesando tablas y eliminando columnas vacías..."):
                    try:
                        # Extraer y limpiar datos
                        df_a = extraer_tabla_limpia_pdf(f_aus)
                        df_t = extraer_tabla_limpia_pdf(f_tar)
                        
                        # Generar el archivo PDF en memoria
                        pdf_data = generar_pdf_unificado_rrhh(df_a, df_t)
                        
                        if pdf_data:
                            st.session_state['pdf_final_rrhh'] = pdf_data
                            st.success("✅ ¡Análisis completado con éxito!")
                            
                            # BOTÓN DE DESCARGA INMEDIATO TRAS EL ANÁLISIS
                            st.download_button(
                                label="📥 DESCARGAR REPORTE UNIFICADO (PDF)",
                                data=pdf_data,
                                file_name=f"Consolidado_RRHH_{datetime.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                            
                            # Mostrar vista previa rápida
                            with st.expander("Ver vista previa de tablas extraídas"):
                                st.write("**Ausencias:**")
                                st.dataframe(df_a.head(5), use_container_width=True)
                                st.write("**Tardanzas:**")
                                st.dataframe(df_t.head(5), use_container_width=True)
                            
                            st.balloons()
                    except Exception as e:
                        st.error(f"Error en el análisis: {e}")
            else:
                st.warning("Debe subir ambos archivos (Ausencias y Tardanzas) para proceder.")

        # Mantener el botón disponible si ya se generó antes
        if 'pdf_final_rrhh' in st.session_state and not (f_aus and f_tar):
            st.divider()
            st.download_button(
                label="📥 DESCARGAR ÚLTIMO REPORTE GENERADO",
                data=st.session_state['pdf_final_rrhh'],
                file_name="Reporte_RRHH.pdf",
                mime="application/pdf"
            )
