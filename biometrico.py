import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta, time
import io
import os
import tempfile
import unicodedata
from fpdf import FPDF
import pdfplumber

# =========================================================
# FUNCIONES ORIGINALES (CONSOLIDADO RRHH - NO TOCADAS)
# =========================================================

def limpiar_nombre(raw):
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def extraer_tabla_limpia_pdf(archivo_pdf):
    import pdfplumber
    todas_las_filas = []
    
    with pdfplumber.open(archivo_pdf) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas:
                tabla_limpia = [[str(celda).replace('\n', ' ').strip() if celda else '' for celda in fila] for fila in tabla]
                todas_las_filas.extend(tabla_limpia)
                
    if not todas_las_filas:
        return pd.DataFrame()
        
    df = pd.DataFrame(todas_las_filas)
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    df = df.replace(r'^\s*$', pd.NA, regex=True)
    df = df.replace('None', pd.NA)
    df = df.replace('--', pd.NA) 
    
    df = df.dropna(how='all', axis=1) 
    df = df.dropna(how='all', axis=0) 
    df = df.fillna('---')
    
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique(): 
        cols[cols[cols == dup].index.values.tolist()] = [f"{dup}_{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df.columns = cols
    return df

def generar_pdf_unificado_rrhh(df_ausencias, df_tardanzas):
    from fpdf import FPDF
    import tempfile
    import os
    import unicodedata
    
    def safestr(texto):
        if pd.isna(texto): return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
        
    pdf = FPDF('L', 'mm', 'A4') 
    pdf.add_page()
    
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
            
        cols_deseadas = ['Nombre completo', 'Departamento', 'Fecha', 'Horario', 'Hora de inicio del trabajo', 'Hora final del trabajo']
        cols_finales = [c for c in cols_deseadas if c in df.columns]
        if not cols_finales: cols_finales = list(df.columns)[:6]
            
        df_sub = df[cols_finales]
        pdf_obj.set_font("Helvetica", "B", 8)
        pdf_obj.set_fill_color(230, 235, 245)
        pdf_obj.set_text_color(0, 0, 0)
        
        ancho_total = 275 
        w = ancho_total / len(cols_finales)
        
        for col in cols_finales:
            pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
        pdf_obj.ln()
        
        pdf_obj.set_font("Helvetica", "", 7)
        for _, row in df_sub.iterrows():
            if pdf_obj.get_y() > 185:
                pdf_obj.add_page()
                pdf_obj.set_font("Helvetica", "B", 8)
                pdf_obj.set_fill_color(230, 235, 245)
                for col in cols_finales:
                    pdf_obj.cell(w, 8, safestr(str(col))[:25], border=1, align="C", fill=True)
                pdf_obj.ln()
                pdf_obj.set_font("Helvetica", "", 7)
                
            for col in cols_finales:
                pdf_obj.cell(w, 6, safestr(str(row[col]))[:40], border=1, align="C")
            pdf_obj.ln()
        pdf_obj.ln(12)
        
    dibujar_tabla(pdf, df_ausencias, "1. DETALLE DE AUSENCIAS")
    dibujar_tabla(pdf, df_tardanzas, "2. DETALLE DE LLEGADAS TARDE")
    
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdf.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

# =========================================================
# NUEVAS FUNCIONES PARA EL CSV BIOMÉTRICO (DEPURADO)
# =========================================================

def procesar_biometrico_mejorado(df_csv):
    """Filtra y procesa usando SOLO: Full Name, ID, Date, Time, Weekday"""
    df_csv.columns = df_csv.columns.str.strip()
    
    cols_requeridas = ['ID', 'Full Name', 'Weekday', 'Date', 'Time']
    cols_presentes = [c for c in cols_requeridas if c in df_csv.columns]
    df_csv = df_csv[cols_presentes].copy()

    df_csv['Date'] = pd.to_datetime(df_csv['Date'], dayfirst=True, errors='coerce').dt.date
    df_csv['Time'] = pd.to_datetime(df_csv['Time'], format='%H:%M', errors='coerce').dt.time
    
    df_csv = df_csv.dropna(subset=['Date', 'Time'])
    df_csv = df_csv.sort_values(by=['Full Name', 'Date', 'Time'])

    resultados = []
    
    for (emp_id, nombre, dia_semana, fecha), grupo in df_csv.groupby(['ID', 'Full Name', 'Weekday', 'Date']):
        marcas = grupo['Time'].tolist()
        num_marcas = len(marcas)
        if num_marcas == 0: continue

        entrada = marcas[0]
        dt_entrada = datetime.combine(datetime.today(), entrada)

        # NUEVA REGLA: Si llega del minuto 15 en adelante, pertenece a la siguiente hora.
        if dt_entrada.minute >= 15: 
            hora_base = (dt_entrada + timedelta(hours=1)).replace(minute=0, second=0)
        else: 
            hora_base = dt_entrada.replace(minute=0, second=0)

        # El límite de tardanza es siempre el minuto 06 de su hora base
        limite_tardia = (hora_base + timedelta(minutes=6)).time()
        dt_limite = datetime.combine(datetime.today(), limite_tardia)
        
        es_tardia = "Sí" if entrada >= limite_tardia else "No"
        
        # CÁLCULO EXACTO DE MINUTOS TARDE
        exceso_tardanza = 0
        if es_tardia == "Sí":
            exceso_tardanza = int((dt_entrada - dt_limite).total_seconds() / 60)
            if exceso_tardanza < 0: exceso_tardanza = 0
        
        salida_alm = marcas[1] if num_marcas > 1 else None
        regreso_alm = marcas[2] if num_marcas > 2 else None
        inicio_break = marcas[3] if num_marcas > 3 else None
        fin_break = marcas[4] if num_marcas > 4 else None
        salida_final = marcas[5] if num_marcas > 5 else None

        def min_dif(t1, t2):
            if not t1 or not t2: return 0
            return int((datetime.combine(fecha, t2) - datetime.combine(fecha, t1)).total_seconds() / 60)

        alm_min = min_dif(salida_alm, regreso_alm)
        exceso_alm = alm_min - 60 if alm_min > 60 else 0
        
        brk_min = min_dif(inicio_break, fin_break)
        exceso_brk = brk_min - 15 if brk_min > 15 else 0

        resultados.append({
            "ID": emp_id,
            "Empleado": nombre,
            "Día": dia_semana,
            "Fecha": fecha.strftime('%d/%m/%Y'),
            "Entrada": entrada.strftime('%H:%M'),
            "Tardanza": es_tardia,
            "Exceso_Tardanza_min": exceso_tardanza, # Columna oculta para matemática
            "Almuerzo (min)": alm_min,
            "Exceso_Alm_min": exceso_alm,           # Columna oculta para matemática
            "Break (min)": brk_min,
            "Exceso_Brk_min": exceso_brk,           # Columna oculta para matemática
            "Salida": salida_final.strftime('%H:%M') if salida_final else "-",
            "Marcaciones": num_marcas
        })
    
    return pd.DataFrame(resultados)

def generar_pdf_infracciones(df_res):
    """Crea un reporte PDF RESUMIDO por empleado con 3 nuevas columnas."""
    from fpdf import FPDF
    pdf = FPDF('L', 'mm', 'A4') # Formato Horizontal para que quepa todo
    pdf.add_page()
    
    # Título
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(277, 10, "Resumen Consolidado de Infracciones", ln=True, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(277, 6, f"Generado el: {datetime.now().strftime('%d/%m/%Y')}", ln=True, align='C')
    pdf.ln(10)

    # 1. Preparar los datos consolidados matemáticamente
    df_res['Es_Tarde'] = df_res['Tardanza'] == 'Sí'
    df_res['Tiene_Exc_Alm'] = df_res['Almuerzo (min)'] > 60
    df_res['Tiene_Exc_Brk'] = df_res['Break (min)'] > 15

    # Agrupar por ID y Empleado
    resumen = df_res.groupby(['ID', 'Empleado']).agg(
        Tardanzas=('Es_Tarde', 'sum'),
        Suma_Tar=('Exceso_Tardanza_min', 'sum'),
        Almuerzos=('Tiene_Exc_Alm', 'sum'),
        Suma_Alm=('Exceso_Alm_min', 'sum'),
        Breaks=('Tiene_Exc_Brk', 'sum'),
        Suma_Brk=('Exceso_Brk_min', 'sum')
    ).reset_index()

    # Sumar el total de faltas y filtrar a los que se portaron bien
    resumen['Total_Faltas'] = resumen['Tardanzas'] + resumen['Almuerzos'] + resumen['Breaks']
    infractores = resumen[resumen['Total_Faltas'] > 0].sort_values(by='Total_Faltas', ascending=False)

    if infractores.empty:
        pdf.set_font("Arial", '', 12)
        pdf.cell(277, 10, "Excelente: No se registraron infracciones en este periodo.", ln=True, align='C')
        return pdf.output(dest='S').encode('latin-1')

    # 2. Dibujar la Tabla
    pdf.set_font("Arial", 'B', 8)
    pdf.set_fill_color(220, 230, 241) 
    
    # Anchos de columna optimizados (Total = ~266mm)
    w_id, w_emp, w_tar, w_ptar, w_alm, w_palm, w_brk, w_pbrk, w_tot = 15, 60, 22, 28, 25, 33, 25, 33, 25
    
    # Encabezados
    pdf.cell(w_id, 8, "ID", border=1, fill=True, align='C')
    pdf.cell(w_emp, 8, "Empleado", border=1, fill=True, align='C')
    pdf.cell(w_tar, 8, "Tardanzas", border=1, fill=True, align='C')
    pdf.cell(w_ptar, 8, "Prom. Tardanza", border=1, fill=True, align='C')
    pdf.cell(w_alm, 8, "Exc. Almuerzo", border=1, fill=True, align='C')
    pdf.cell(w_palm, 8, "Prom. Exc. Alm.", border=1, fill=True, align='C')
    pdf.cell(w_brk, 8, "Exc. Break", border=1, fill=True, align='C')
    pdf.cell(w_pbrk, 8, "Prom. Exc. Brk.", border=1, fill=True, align='C')
    pdf.cell(w_tot, 8, "TOTAL FALTAS", border=1, fill=True, align='C')
    pdf.ln()

    # Filas de datos
    pdf.set_font("Arial", '', 8)
    for _, row in infractores.iterrows():
        # Truncar el nombre si es muy largo
        nombre_corto = str(row['Empleado'])[:35]
        
        # Matemáticas para evitar divisiones entre cero
        p_tar = f"{int(row['Suma_Tar'] / row['Tardanzas'])} min" if row['Tardanzas'] > 0 else "---"
        p_alm = f"{int(row['Suma_Alm'] / row['Almuerzos'])} min" if row['Almuerzos'] > 0 else "---"
        p_brk = f"{int(row['Suma_Brk'] / row['Breaks'])} min" if row['Breaks'] > 0 else "---"
        
        pdf.cell(w_id, 8, str(row['ID']), border=1, align='C')
        pdf.cell(w_emp, 8, f" {nombre_corto}", border=1)
        pdf.cell(w_tar, 8, str(int(row['Tardanzas'])), border=1, align='C')
        pdf.cell(w_ptar, 8, p_tar, border=1, align='C')
        pdf.cell(w_alm, 8, str(int(row['Almuerzos'])), border=1, align='C')
        pdf.cell(w_palm, 8, p_alm, border=1, align='C')
        pdf.cell(w_brk, 8, str(int(row['Breaks'])), border=1, align='C')
        pdf.cell(w_pbrk, 8, p_brk, border=1, align='C')
        
        # Resaltar el total en negrita
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(w_tot, 8, str(int(row['Total_Faltas'])), border=1, align='C')
        pdf.set_font("Arial", '', 8)
        pdf.ln()

    return pdf.output(dest='S').encode('latin-1')

# =========================================================
# INTERFAZ PRINCIPAL STREAMLIT
# =========================================================

def vista_biometrico():
    st.title("🚨 Centro de Control Biométrico y RRHH")
    tab_transacciones, tab_rrhh = st.tabs(["⏱️ Auditoría Diaria (CSV)", "📊 Consolidado RRHH (PDFs)"])
    
    with tab_transacciones:
        st.subheader("Análisis de Marcaciones Biométricas")
        st.write("Sube el archivo CSV exportado desde el sistema MaxCom.")
        
        file_bio = st.file_uploader("Cargar archivo de Transacciones", type=["csv"], key="bio_upload")

        if file_bio:
            try:
                content = file_bio.getvalue().decode('utf-8-sig', errors='ignore')
                lineas = content.splitlines()
                skip_lines = 0
                
                for i, linea in enumerate(lineas[:10]): 
                    if 'Full Name' in linea and 'Date' in linea and 'Time' in linea:
                        skip_lines = i
                        break
                
                file_bio.seek(0)
                df_raw = pd.read_csv(file_bio, sep=';', encoding='utf-8-sig', skiprows=skip_lines)
                
                if len(df_raw.columns) == 1:
                    file_bio.seek(0)
                    df_raw = pd.read_csv(file_bio, sep=',', encoding='utf-8-sig', skiprows=skip_lines)

                df_p = procesar_biometrico_mejorado(df_raw)
                
                st.success(f"Archivo procesado correctamente. ¡Tabla limpiada y depurada!")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Tardanzas Detectadas", len(df_p[df_p["Tardanza"] == "Sí"]))
                c2.metric("Excesos Almuerzo", len(df_p[df_p["Almuerzo (min)"] > 60]))
                c3.metric("Excesos Break", len(df_p[df_p["Break (min)"] > 15]))

                st.markdown("---")
                
                # === CREAMOS LA VISTA CONSOLIDADA (CON LOS PROMEDIOS INCLUIDOS) ===
                df_p['Es_Tarde'] = df_p['Tardanza'] == 'Sí'
                df_p['Tiene_Exc_Alm'] = df_p['Almuerzo (min)'] > 60
                df_p['Tiene_Exc_Brk'] = df_p['Break (min)'] > 15

                agrupado = df_p.groupby(['ID', 'Empleado']).agg(
                    Tardanzas=('Es_Tarde', 'sum'),
                    Suma_Tardanza=('Exceso_Tardanza_min', 'sum'),
                    Exc_Almuerzo=('Tiene_Exc_Alm', 'sum'),
                    Suma_Alm=('Exceso_Alm_min', 'sum'),
                    Exc_Break=('Tiene_Exc_Brk', 'sum'),
                    Suma_Brk=('Exceso_Brk_min', 'sum')
                ).reset_index()

                agrupado['TOTAL FALTAS'] = agrupado['Tardanzas'] + agrupado['Exc_Almuerzo'] + agrupado['Exc_Break']
                agrupado = agrupado[agrupado['TOTAL FALTAS'] > 0].copy()

                if not agrupado.empty:
                    # Aplicando los promedios
                    agrupado['Prom. Tardanza'] = agrupado.apply(lambda x: f"{int(x['Suma_Tardanza']/x['Tardanzas'])} min" if x['Tardanzas'] > 0 else "---", axis=1)
                    agrupado['Prom. Exc. Almuerzo'] = agrupado.apply(lambda x: f"{int(x['Suma_Alm']/x['Exc_Almuerzo'])} min" if x['Exc_Almuerzo'] > 0 else "---", axis=1)
                    agrupado['Prom. Exc. Break'] = agrupado.apply(lambda x: f"{int(x['Suma_Brk']/x['Exc_Break'])} min" if x['Exc_Break'] > 0 else "---", axis=1)

                    agrupado = agrupado.sort_values(by='TOTAL FALTAS', ascending=False)
                    df_mostrar = agrupado[['ID', 'Empleado', 'Tardanzas', 'Prom. Tardanza', 'Exc_Almuerzo', 'Prom. Exc. Almuerzo', 'Exc_Break', 'Prom. Exc. Break', 'TOTAL FALTAS']]
                    df_mostrar.columns = ['ID', 'Empleado', 'Tardanzas', 'Prom. Tardanza', 'Exc. Almuerzo', 'Prom. Exc. Almuerzo', 'Exc. Break', 'Prom. Exc. Break', 'TOTAL FALTAS']
                else:
                    df_mostrar = pd.DataFrame()

                # Generar el nuevo PDF Horizontal
                pdf_data = generar_pdf_infracciones(df_p)
                st.download_button(
                    label="📥 Descargar Resumen de Infracciones (PDF)",
                    data=pdf_data,
                    file_name=f"Resumen_Infracciones_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

                # Mostramos las dos vistas usando Pestañas (Tabs)
                t_consolidado, t_detalle = st.tabs(["📊 Tabla Consolidada", "📝 Detalle Diario"])
                
                with t_consolidado:
                    if not df_mostrar.empty:
                        st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ Excelente. Nadie llegó tarde ni se pasó del almuerzo o break.")
                        
                with t_detalle:
                    # Ocultamos de la vista las columnas de suma basura para que se vea limpio
                    columnas_a_esconder = ['Exceso_Tardanza_min', 'Exceso_Alm_min', 'Exceso_Brk_min', 'Es_Tarde', 'Tiene_Exc_Alm', 'Tiene_Exc_Brk']
                    st.dataframe(df_p.drop(columns=columnas_a_esconder, errors='ignore'), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error al procesar el archivo. Asegúrate de subir el reporte correcto. Detalles: {e}")

    with tab_rrhh:
        st.subheader("📑 Generador de Reporte Unificado")
        st.markdown("Cargue los reportes oficiales para limpiar columnas vacías y unificar la información.")
        
        col_u1, col_u2 = st.columns(2)
        with col_u1: f_aus = st.file_uploader("📂 PDF de Ausencias", type=['pdf'], key="up_aus")
        with col_u2: f_tar = st.file_uploader("📂 PDF de Llegadas Tarde", type=['pdf'], key="up_tar")
            
        if st.button("🚀 ANALIZAR ARCHIVOS", type="primary", use_container_width=True):
            if f_aus or f_tar:
                with st.spinner("Procesando tablas y eliminando basura..."):
                    try:
                        df_a = extraer_tabla_limpia_pdf(f_aus) if f_aus else pd.DataFrame()
                        df_t = extraer_tabla_limpia_pdf(f_tar) if f_tar else pd.DataFrame()
                        
                        pdf_data = generar_pdf_unificado_rrhh(df_a, df_t)
                        
                        if pdf_data:
                            st.session_state['pdf_final_rrhh'] = pdf_data
                            st.session_state['df_a_prev'] = df_a
                            st.session_state['df_t_prev'] = df_t
                            st.success("✅ ¡Análisis completado con éxito!")
                            st.balloons()
                    except Exception as e:
                        st.error(f"Error en el análisis. Detalles: {e}")
            else:
                st.warning("Debe subir al menos un archivo para proceder.")

        if 'pdf_final_rrhh' in st.session_state:
            st.markdown("---")
            st.markdown("### 🎉 Tu Reporte está listo")
            st.download_button(
                label="📥 DESCARGAR REPORTE UNIFICADO (PDF)",
                data=st.session_state['pdf_final_rrhh'],
                file_name=f"Consolidado_RRHH_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
            
            with st.expander("Ver vista previa de datos extraídos"):
                if not st.session_state.get('df_a_prev', pd.DataFrame()).empty:
                    st.write("**Ausencias:**")
                    st.dataframe(st.session_state['df_a_prev'].head(5), use_container_width=True)
                if not st.session_state.get('df_t_prev', pd.DataFrame()).empty:
                    st.write("**Tardanzas:**")
                    st.dataframe(st.session_state['df_t_prev'].head(5), use_container_width=True)

if __name__ == "__main__":
    try:
        st.set_page_config(page_title="Control Operativo - MaxCom", layout="wide")
    except:
        pass
    vista_biometrico()
