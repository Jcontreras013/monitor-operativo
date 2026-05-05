import pandas as pd
import streamlit as st
import re
from datetime import datetime, timedelta, time
import io
import os
import tempfile
import unicodedata
import pdfplumber

# IMPORTANTE: Hemos agregado las nuevas funciones de tools aquí.
from tools import (
    generar_pdf_unificado_rrhh, 
    generar_pdf_infracciones,
    cargar_catalogo_tecnicos,
    procesar_asistencia_vs_catalogo,
    ReporteGenerencialPDF,
    finalizar_pdf,
    safestr
)

# =========================================================
# FUNCIONES ORIGINALES (CONSOLIDADO RRHH - NO TOCADAS)
# =========================================================

def limpiar_nombre(raw):
    palabras = raw.replace('\n', ' ').strip().split()
    basura = ['punch', 'state', 'location', 'remarks', 'am', 'pm', 'device', 'mobile', 'app', 'oficina', 'santaelena', 'deviceoficina', 'statelocation', 'entrada', 'salida']
    limpias = [p for p in palabras if p.lower() not in basura]
    return " ".join(limpias[-4:])

def extraer_tabla_limpia_pdf(archivo_pdf):
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

# =========================================================
# NUEVAS FUNCIONES PARA EL CSV BIOMÉTRICO (DEPURADO)
# =========================================================

def procesar_biometrico_mejorado(df_csv, dict_turnos):
    """Filtra y procesa aplicando reglas estrictas y detectando personal de campo (Santa Elena)"""
    df_csv.columns = df_csv.columns.str.strip()
    
    # Capturamos toda la fila como texto para buscar fácilmente "Santa Elena"
    df_csv['Raw_Text'] = df_csv.apply(lambda row: ' '.join(row.values.astype(str)).upper(), axis=1)
    
    cols_requeridas = ['ID', 'Full Name', 'Weekday', 'Date', 'Time', 'Raw_Text']
    cols_presentes = [c for c in cols_requeridas if c in df_csv.columns]
    df_csv = df_csv[cols_presentes].copy()

    df_csv['Date'] = pd.to_datetime(df_csv['Date'], dayfirst=True, errors='coerce').dt.date
    df_csv['Time'] = pd.to_datetime(df_csv['Time'], format='%H:%M', errors='coerce').dt.time
    
    df_csv = df_csv.dropna(subset=['Date', 'Time'])
    df_csv = df_csv.sort_values(by=['Full Name', 'Date', 'Time'])

    resultados = []
    
    for (emp_id, nombre, dia_semana, fecha), grupo in df_csv.groupby(['ID', 'Full Name', 'Weekday', 'Date']):
        marcas_crudas = grupo['Time'].tolist()
        if not marcas_crudas: continue

        # --- FILTRO ANTI DOUBLE-PUNCH (IGNORA MARCAS CON < 2 MIN DE DIFERENCIA) ---
        marcas = [marcas_crudas[0]]
        for m in marcas_crudas[1:]:
            t1 = datetime.combine(fecha, marcas[-1])
            t2 = datetime.combine(fecha, m)
            if (t2 - t1).total_seconds() / 60 >= 2:
                marcas.append(m)

        # --- DETECCIÓN DE PERSONAL DE CAMPO (SANTA ELENA) Y FILTRO DE HORARIO ---
        es_campo = grupo['Raw_Text'].str.contains('SANTA ELENA|SANTAELENA', regex=True).any()

        if es_campo:
            marcas_filtradas = []
            for m in marcas:
                if fecha.weekday() == 5: # Sábado
                    if m.hour <= 12: 
                        marcas_filtradas.append(m)
                else: # Lunes a Viernes
                    if m.hour <= 17: 
                        marcas_filtradas.append(m)
            
            if marcas_filtradas:
                marcas = marcas_filtradas

        num_marcas = len(marcas)
        if num_marcas == 0: continue

        # 1. EVALUAR ENTRADA Y TARDANZA REAL
        entrada = marcas[0]
        dt_entrada = datetime.combine(fecha, entrada)
        
        turno_str = dict_turnos.get(emp_id, "08:00 AM")
        try:
            dt_turno = datetime.strptime(turno_str, "%I:%M %p").time()
        except:
            dt_turno = datetime.strptime("08:00 AM", "%I:%M %p").time()
            
        dt_base = datetime.combine(fecha, dt_turno)
        limite_tardia = (dt_base + timedelta(minutes=5, seconds=59)).time()
        dt_limite = datetime.combine(fecha, limite_tardia)
        
        es_tardia = "Sí" if entrada >= limite_tardia else "No"
        
        exceso_tardanza = 0
        if es_tardia == "Sí":
            exceso_tardanza = int((dt_entrada - dt_limite).total_seconds() / 60)
            if exceso_tardanza < 0: exceso_tardanza = 0
        
        def min_dif(t1, t2):
            if not t1 or not t2: return 0
            return int((datetime.combine(fecha, t2) - datetime.combine(fecha, t1)).total_seconds() / 60)

        alm_min = 0
        exceso_alm = 0
        brk_min = 0
        exceso_brk = 0
        
        # 2. REGLA DE NEGOCIO: PERSONAL DE CAMPO (SANTA ELENA)
        if es_campo:
            salida_final = marcas[-1] if num_marcas > 1 else None
        else:
            # 3. REGLAS NORMALES DE OFICINA
            if num_marcas >= 3:
                if marcas[1].hour < 17 and marcas[2].hour < 17:
                    alm_min = min_dif(marcas[1], marcas[2])
                    if alm_min > 60:
                        exceso_alm = alm_min - 60
                        
            if num_marcas >= 5:
                if marcas[3].hour < 17 and marcas[4].hour < 17:
                    brk_min = min_dif(marcas[3], marcas[4])
                    if brk_min > 15:
                        exceso_brk = brk_min - 15

            salida_final = marcas[-1] if num_marcas > 1 else None

        if "CYNIA" in str(nombre).upper():
            brk_min = 0
            exceso_brk = 0

        resultados.append({
            "ID": emp_id,
            "Empleado": nombre,
            "Día": dia_semana,
            "Fecha": fecha.strftime('%d/%m/%Y'),
            "Entrada": entrada.strftime('%H:%M'),
            "Tardanza": es_tardia,
            "Exceso_Tardanza_min": exceso_tardanza, 
            "Almuerzo (min)": alm_min,
            "Exceso_Alm_min": exceso_alm,           
            "Break (min)": brk_min,
            "Exceso_Brk_min": exceso_brk,           
            "Salida": salida_final.strftime('%H:%M') if salida_final else "-",
            "Marcaciones": num_marcas,
            "Es_Campo": "Sí" if es_campo else "No" 
        })
    
    return pd.DataFrame(resultados)


# =========================================================
# LÓGICA DE PDF PARA LAS AUSENCIAS
# =========================================================
def generar_pdf_ausencias(df_resultado):
    """Genera el PDF visual de los técnicos que no marcaron o están de vacaciones"""
    pdf = ReporteGenerencialPDF(orientation='P', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE DE ASISTENCIA DIARIA (Cruce Biometrico vs Catalogo)"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Generado el: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}"), ln=True, align="C")
    pdf.ln(5)

    # Filtrar para el PDF solo los que NO MARCARON o están de VACACIONES
    df_faltas = df_resultado[df_resultado['Asistencia'].isin(['❌ NO MARCÓ', '🌴 VACACIONES'])]

    if df_faltas.empty:
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 10, safestr("Excelente: Todos los tecnicos registrados marcaron asistencia hoy."), ln=True, align="C")
        return finalizar_pdf(pdf)

    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 8)

    w = [75, 40, 45, 30]
    headers = ['Nombre del Tecnico', 'Clasificacion', 'Area / Asignacion', 'Estado']

    for i, col in enumerate(headers):
        pdf.cell(w[i], 8, safestr(col), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for _, row in df_faltas.iterrows():
        pdf.cell(w[0], 6, safestr(str(row['Nombre']))[:45], border=1, align="L")
        pdf.cell(w[1], 6, safestr(str(row['Clasificación']))[:20], border=1, align="C")
        pdf.cell(w[2], 6, safestr(str(row['Cargo/Área']))[:25], border=1, align="C")

        # Color según estado
        if 'VACACIONES' in str(row['Asistencia']):
            pdf.set_text_color(0, 100, 0) # Verde
        else:
            pdf.set_text_color(200, 0, 0) # Rojo

        pdf.cell(w[3], 6, safestr(str(row['Asistencia'])), border=1, align="C")
        pdf.set_text_color(0, 0, 0) # Restaurar negro
        pdf.ln()

    return finalizar_pdf(pdf)


# =========================================================
# INTERFAZ PRINCIPAL STREAMLIT
# =========================================================

def vista_biometrico():
    st.title("🚨 Centro de Control Biométrico y RRHH")
    
    # 📌 SE AGREGA LA TERCERA PESTAÑA AQUÍ
    tab_transacciones, tab_rrhh, tab_asistencia = st.tabs([
        "⏱️ Auditoría Diaria (CSV)", 
        "📊 Consolidado RRHH (PDFs)", 
        "👥 Asistencia Técnicos"
    ])
    
    # ---------------------------------------------------------
    # PESTAÑA 1: TRANSACCIONES DIARIAS
    # ---------------------------------------------------------
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

                df_raw.columns = df_raw.columns.str.strip()
                df_raw['Full Name'] = df_raw['Full Name'].fillna("Desconocido")
                usuarios_unicos = df_raw[['ID', 'Full Name']].drop_duplicates().reset_index(drop=True)
                
                def preasignar_turno(nombre):
                    nom = str(nombre).upper()
                    if "BARIKA" in nom or "JAIR" in nom: return "09:00 AM"
                    if "RAMON" in nom and "CACERES" in nom: return "07:00 AM"
                    if "DARIO" in nom: return "10:00 AM"
                    return "08:00 AM"
                    
                usuarios_unicos['Turno'] = usuarios_unicos['Full Name'].apply(preasignar_turno)
                
                if 'memoria_turnos' in st.session_state:
                    previos = st.session_state['memoria_turnos']
                    usuarios_unicos = pd.merge(usuarios_unicos, previos[['ID', 'Turno']], on='ID', how='left', suffixes=('', '_y'))
                    usuarios_unicos['Turno'] = usuarios_unicos['Turno_y'].fillna(usuarios_unicos['Turno'])
                    usuarios_unicos = usuarios_unicos.drop(columns=['Turno_y'], errors='ignore')
                    
                st.session_state['memoria_turnos'] = usuarios_unicos
                
                st.write("### 1️⃣ Asignar Turno de Entrada")
                opciones_turnos = ["07:00 AM", "08:00 AM", "09:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"]
                turnos_editados = st.data_editor(
                    st.session_state['memoria_turnos'],
                    column_config={"Turno": st.column_config.SelectboxColumn(options=opciones_turnos, required=True)},
                    disabled=['ID', 'Full Name'],
                    hide_index=True,
                    use_container_width=True
                )
                st.session_state['memoria_turnos'] = turnos_editados
                dict_turnos = dict(zip(turnos_editados['ID'], turnos_editados['Turno']))

                if st.button("🚀 Extraer Infractores", type="primary"):
                    df_p = procesar_biometrico_mejorado(df_raw, dict_turnos)
                    
                    st.success(f"Archivo procesado correctamente. ¡Tabla limpiada y depurada!")
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Tardanzas Detectadas", len(df_p[df_p["Tardanza"] == "Sí"]))
                    c2.metric("Excesos Almuerzo", len(df_p[df_p["Almuerzo (min)"] > 60]))
                    c3.metric("Excesos Break", len(df_p[df_p["Break (min)"] > 15]))

                    st.markdown("---")
                    
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
                        agrupado['Prom. Tardanza'] = agrupado.apply(lambda x: f"{int(x['Suma_Tardanza']/x['Tardanzas'])} min" if x['Tardanzas'] > 0 else "---", axis=1)
                        agrupado['Prom. Exc. Almuerzo'] = agrupado.apply(lambda x: f"{int(x['Suma_Alm']/x['Exc_Almuerzo'])} min" if x['Exc_Almuerzo'] > 0 else "---", axis=1)
                        agrupado['Prom. Exc. Break'] = agrupado.apply(lambda x: f"{int(x['Suma_Brk']/x['Exc_Break'])} min" if x['Exc_Break'] > 0 else "---", axis=1)

                        agrupado = agrupado.sort_values(by='TOTAL FALTAS', ascending=False)
                        df_mostrar = agrupado[['ID', 'Empleado', 'Tardanzas', 'Prom. Tardanza', 'Exc_Almuerzo', 'Prom. Exc. Almuerzo', 'Exc_Break', 'Prom. Exc. Break', 'TOTAL FALTAS']]
                        df_mostrar.columns = ['ID', 'Empleado', 'Tardanzas', 'Prom. Tardanza', 'Exc. Almuerzo', 'Prom. Exc. Almuerzo', 'Exc. Break', 'Prom. Exc. Break', 'TOTAL FALTAS']
                    else:
                        df_mostrar = pd.DataFrame()

                    pdf_data = generar_pdf_infracciones(df_p)
                    st.download_button(
                        label="📥 Descargar Resumen de Infracciones (PDF)",
                        data=pdf_data,
                        file_name=f"Resumen_Infracciones_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

                    t_consolidado, t_detalle = st.tabs(["📊 Tabla Consolidada", "📝 Detalle Diario"])
                    
                    with t_consolidado:
                        if not df_mostrar.empty:
                            st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                        else:
                            st.success("✅ Excelente. Nadie llegó tarde ni se pasó del almuerzo o break.")
                            
                    with t_detalle:
                        columnas_a_esconder = ['Exceso_Tardanza_min', 'Exceso_Alm_min', 'Exceso_Brk_min', 'Es_Tarde', 'Tiene_Exc_Alm', 'Tiene_Exc_Brk', 'Es_Campo']
                        df_limpio_detalle = df_p.drop(columns=columnas_a_esconder, errors='ignore')
                        df_solo_infracciones = df_limpio_detalle[(df_limpio_detalle['Tardanza'] == 'Sí') | (df_limpio_detalle['Almuerzo (min)'] > 60) | (df_limpio_detalle['Break (min)'] > 15)]
                        st.dataframe(df_solo_infracciones, use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error al procesar el archivo. Asegúrate de subir el reporte correcto. Detalles: {e}")

    # ---------------------------------------------------------
    # PESTAÑA 2: RRHH PDF CONSOLIDADOS
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # PESTAÑA 3: ASISTENCIA TÉCNICOS (.TXT VS BIOMÉTRICO)
    # ---------------------------------------------------------
    with tab_asistencia:
        st.subheader("📋 Control de Asistencia y Ausencias")
        st.markdown("Arrastra el archivo exportado del biométrico (CSV) para cruzarlo con tu archivo maestro `personal_tecnico.txt`.")
        
        # 1. Cargar el catálogo
        df_catalogo = cargar_catalogo_tecnicos()
        
        if df_catalogo.empty:
            st.error("⚠️ No se pudo encontrar o leer el archivo `personal_tecnico.txt`. Asegúrate de que esté en la misma carpeta.")
        else:
            st.success(f"✅ Catálogo de personal cargado: **{len(df_catalogo)}** técnicos y supervisores registrados.")
            
            # 2. Subir biométrico
            file_bio_asistencia = st.file_uploader("Arrastrar Biométrico del Día (CSV)", type=["csv", "txt"], key="bio_asis")

            if file_bio_asistencia:
                try:
                    # Leer CSV igual que en la primera pestaña
                    content = file_bio_asistencia.getvalue().decode('utf-8-sig', errors='ignore')
                    lineas = content.splitlines()
                    skip_lines = 0
                    for i, linea in enumerate(lineas[:10]): 
                        if 'Full Name' in linea or 'Empleado' in linea:
                            skip_lines = i
                            break
                    
                    file_bio_asistencia.seek(0)
                    df_bio = pd.read_csv(file_bio_asistencia, sep=';', encoding='utf-8-sig', skiprows=skip_lines)
                    if len(df_bio.columns) == 1:
                        file_bio_asistencia.seek(0)
                        df_bio = pd.read_csv(file_bio_asistencia, sep=',', encoding='utf-8-sig', skiprows=skip_lines)

                    # Estandarizar nombre de columna para el backend
                    if 'Full Name' in df_bio.columns:
                        df_bio = df_bio.rename(columns={'Full Name': 'Empleado'})
                        
                    # Extraer primera y última marca si existen las horas
                    if 'Time' in df_bio.columns and 'Empleado' in df_bio.columns:
                        df_bio_agrupado = df_bio.groupby('Empleado').agg(
                            Entrada=('Time', 'min'),
                            Salida=('Time', 'max')
                        ).reset_index()
                    else:
                        df_bio_agrupado = df_bio

                    # 3. Cruzar con el TXT de Técnicos
                    with st.spinner("Cruzando datos con el maestro de técnicos..."):
                        df_resultado = procesar_asistencia_vs_catalogo(df_bio_agrupado, df_catalogo)
                    
                    # 4. Mostrar Resultados (Filtro por faltas)
                    df_faltas = df_resultado[df_resultado['Asistencia'].isin(['❌ NO MARCÓ', '🌴 VACACIONES'])]
                    
                    st.markdown("### 🚨 Personal Técnico Faltante hoy:")
                    
                    if not df_faltas.empty:
                        # Estilos para colorear las columnas en la interfaz
                        def style_asistencia(val):
                            color = '#d32f2f' if 'NO MARCÓ' in str(val) else ('#388e3c' if 'VACACIONES' in str(val) else '')
                            return f'color: {color}; font-weight: bold'

                        st.dataframe(df_faltas.style.map(style_asistencia, subset=['Asistencia']), use_container_width=True, hide_index=True)
                        
                        # 5. Generar y Descargar PDF
                        pdf_bytes = generar_pdf_ausencias(df_resultado)
                        st.download_button(
                            label="📥 DESCARGAR REPORTE DE AUSENCIAS (PDF)",
                            data=pdf_bytes,
                            file_name=f"Ausencias_Tecnicos_{datetime.now().strftime('%d_%m_%Y')}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                    else:
                        st.success("🎉 ¡Excelente! Todos los técnicos programados marcaron asistencia el día de hoy.")
                        
                    # Mostrar tabla completa opcional
                    with st.expander("Ver lista completa (Incluye los que sí asistieron)"):
                        st.dataframe(df_resultado.style.map(style_asistencia, subset=['Asistencia']), use_container_width=True, hide_index=True)
                        
                except Exception as e:
                    st.error(f"Error al cruzar los archivos: {e}")

if __name__ == "__main__":
    try:
        st.set_page_config(page_title="Control Operativo - MaxCom", layout="wide")
    except:
        pass
    vista_biometrico()
