import streamlit as st
import pandas as pd
from datetime import datetime
import re
import os
import io

# Importar las herramientas de PDF que ya existen en tu sistema
try:
    from tools import ReporteGenerencialPDF, finalizar_pdf, safestr
except ImportError:
    st.error("⚠️ No se pudo importar tools.py. Asegúrate de que esté en la misma carpeta.")

# ==============================================================================
# LECTOR BLINDADO DE ARCHIVOS (ANTI-ERRORES BINARIOS)
# ==============================================================================
def read_file_robust(uploaded_file):
    filename = uploaded_file.name.lower()
    
    if filename.endswith('.csv'):
        try:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='utf-8')
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding='latin1')
    else:
        try:
            uploaded_file.seek(0)
            motor = 'xlrd' if filename.endswith('.xls') else None
            return pd.read_excel(uploaded_file, engine=motor)
        except ImportError as e_import:
            if 'xlrd' in str(e_import):
                raise RuntimeError("FALTA LIBRERÍA: Necesitas instalar 'xlrd' para leer archivos .xls antiguos. Agrégalo a tu requirements.txt.")
            raise e_import
        except Exception as e_excel:
            try:
                uploaded_file.seek(0)
                html_str = uploaded_file.getvalue().decode('utf-8', errors='ignore')
                dfs = pd.read_html(io.StringIO(html_str))
                return max(dfs, key=len)
            except Exception:
                try:
                    uploaded_file.seek(0)
                    html_str = uploaded_file.getvalue().decode('latin1', errors='ignore')
                    dfs = pd.read_html(io.StringIO(html_str))
                    return max(dfs, key=len)
                except Exception:
                    raise ValueError(f"El archivo está corrupto o es un Excel antiguo (.xls). Asegúrate de tener instalado 'xlrd'. Detalle original: {e_excel}")

# ==============================================================================
# LÓGICA DE AUDITORÍA DE VEHÍCULOS (TIEMPOS)
# ==============================================================================
def procesar_auditoria_vehiculos(df):
    try:
        col_placa = next((c for c in df.columns if re.search(r'PLACA|ALIAS|VEHICULO', str(c), re.I)), None)
        col_ingreso = next((c for c in df.columns if re.search(r'INGRESO|ENTRADA', str(c), re.I)), None)
        col_salida = next((c for c in df.columns if re.search(r'SALIDA', str(c), re.I)), None)
        
        if not (col_placa and col_ingreso and col_salida):
            return None, "El archivo no tiene el formato esperado para medir tiempos."
            
        df = df.rename(columns={col_placa: 'Placa-Alias', col_ingreso: 'Hora Ingreso', col_salida: 'Hora Salida'})
        df['Placa-Alias'] = df['Placa-Alias'].astype(str).str.replace(r'\xa0', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
        df = df[~df['Placa-Alias'].isin(['nan', '--', 'None', ''])]
        
        df['Hora Ingreso'] = pd.to_datetime(df['Hora Ingreso'], errors='coerce')
        df['Hora Salida'] = pd.to_datetime(df['Hora Salida'], errors='coerce')
        
        resumen = df.groupby('Placa-Alias').agg(Primera_Salida=('Hora Salida', 'min'), Ultima_Entrada=('Hora Ingreso', 'max')).reset_index()
        
        def calc_tiempo(row):
            if pd.isnull(row['Primera_Salida']): return "Sin Salida"
            if pd.isnull(row['Ultima_Entrada']): return "Sin Ingreso"
            if row['Ultima_Entrada'] >= row['Primera_Salida']:
                diff = row['Ultima_Entrada'] - row['Primera_Salida']
                total_seconds = int(diff.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                return "Revisar"
                
        resumen['Tiempo Real en Calle'] = resumen.apply(calc_tiempo, axis=1)
        resumen['Primera Salida'] = resumen['Primera_Salida'].dt.strftime('%I:%M %p').fillna("---")
        resumen['Última Entrada'] = resumen['Ultima_Entrada'].dt.strftime('%I:%M %p').fillna("---")
        
        return resumen[['Vehículo / Placa', 'Primera Salida', 'Última Entrada', 'Tiempo Real en Calle']], "OK"
    except Exception as e:
        return None, str(e)

# ==============================================================================
# LÓGICA DE EXCESOS Y TELEMETRÍA (MATRIZ REPARADA)
# ==============================================================================
def procesar_matriz_telemetria(df_raw):
    try:
        header_idx = None
        for i in range(min(20, len(df_raw))):
            val = str(df_raw.iloc[i, 0]).upper()
            if 'PLACA' in val or 'ALIAS' in val or 'VEHICULO' in val:
                header_idx = i
                break
                
        if header_idx is None: return None, "No se encontró la fila de encabezados."

        df = df_raw.iloc[header_idx + 1:].copy()
        raw_columns = df_raw.iloc[header_idx].astype(str).str.strip().tolist()
        
        clean_columns = []
        for i, col in enumerate(raw_columns):
            if col.lower() == 'nan' or col == '':
                clean_columns.append(f"Dia_{i-1}" if i > 1 else f"Info_{i}")
            else:
                clean_columns.append(col)
                
        df.columns = clean_columns
        col_placa = df.columns[0]
        
        df = df.dropna(subset=[col_placa])
        df = df[~df[col_placa].astype(str).str.contains('La versión de este equipo', case=False, na=False)]
        df = df[df[col_placa].astype(str).str.strip() != '']
        df = df.fillna(0)

        return df, "OK"
    except Exception as e:
        return None, f"Error al limpiar la matriz: {str(e)}"

# ==============================================================================
# GENERADORES DE PDF (ACTUALIZADOS PARA PROMEDIO Y % EXCESO)
# ==============================================================================
def generar_pdf_auditoria_tiempos(df_resumen):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 10, safestr(f" Auditoria de Tiempos de Ruta (GPS) - {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Consolidado de Tiempos Reales en Calle")
    
    if not df_resumen.empty:
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        anchos = [85, 30, 30, 45]
        
        for i, col in enumerate(df_resumen.columns):
            pdf.cell(anchos[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 7)
        for _, fila in df_resumen.iterrows():
            for i, item in enumerate(fila):
                valstr = str(item)[:45]
                valclean = safestr(valstr)
                
                fillr, fillg, fillb = 255, 255, 255
                textr, textg, textb = 0, 0, 0
                
                if "Sin Salida" in valstr or "Sin Ingreso" in valstr or "Revisar" in valstr or "---" in valstr:
                    fillr, fillg, fillb = 253, 230, 230 
                    textr, textg, textb = 180, 0, 0     
                elif i == 3 and "Sin" not in valstr and "Revisar" not in valstr:
                    fillr, fillg, fillb = 230, 245, 230 
                    textr, textg, textb = 0, 100, 0     
                    
                pdf.set_fill_color(fillr, fillg, fillb)
                pdf.set_text_color(textr, textg, textb)
                pdf.cell(anchos[i], 5, valclean, border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos para mostrar.", ln=True)
        
    return finalizar_pdf(pdf)

def generar_pdf_telemetria_matriz(df_matriz, limite_vel):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page('L') 
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 10, safestr(f" Auditoria de Infracciones (> {limite_vel} km/h) - {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    if not df_matriz.empty:
        pdf.seccion_titulo("Matriz Mensual de Vehiculos Infractores")
        
        # Calcular anchos de columna dinámicamente
        has_prom = 'Promedio Vel. (km/h)' in df_matriz.columns
        has_pct = '% Exceso' in df_matriz.columns
        
        w_placa = 60
        w_opcion = 30
        w_prom = 25 if has_prom else 0
        w_pct = 20 if has_pct else 0
        
        espacio_restante = 275 - w_placa - w_opcion - w_prom - w_pct
        cols_extras = 2 + (1 if has_prom else 0) + (1 if has_pct else 0)
        cols_dias = len(df_matriz.columns) - cols_extras
        w_dia = espacio_restante / cols_dias if cols_dias > 0 else 0
        
        font_size = 6 if cols_dias <= 15 else 5
        pdf.set_font("Helvetica", "B", font_size)
        
        # ---------------- ENCABEZADOS ----------------
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        
        for i, col in enumerate(df_matriz.columns):
            if i == 0: w = w_placa
            elif i == 1: w = w_opcion
            elif col == 'Promedio Vel. (km/h)': w = w_prom
            elif col == '% Exceso': w = w_pct
            else: w = w_dia
            
            nom_col = str(col).replace('Dia_', '')
            pdf.cell(w, 6, safestr(nom_col[:15]), border=1, align="C", fill=True)
        pdf.ln()
        
        # ---------------- FILAS ----------------
        pdf.set_font("Helvetica", "", font_size)
        for _, fila in df_matriz.iterrows():
            for i, (col_name, item) in enumerate(fila.items()):
                if i == 0: w = w_placa
                elif i == 1: w = w_opcion
                elif col_name == 'Promedio Vel. (km/h)': w = w_prom
                elif col_name == '% Exceso': w = w_pct
                else: w = w_dia
                
                valstr = str(item).replace('.0', '').strip()
                
                pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(0, 0, 0)
                
                # Colores para Promedio
                if col_name == 'Promedio Vel. (km/h)':
                    if valstr != "-":
                        pdf.set_fill_color(230, 240, 255)
                        pdf.set_text_color(0, 50, 150)
                        valstr = f"{valstr} km/h"
                # Colores para % Exceso
                elif col_name == '% Exceso':
                    if valstr != "-":
                        pdf.set_fill_color(255, 235, 204) # Naranjita
                        pdf.set_text_color(150, 75, 0)
                # Colores para conteo de días
                elif i > 1: 
                    try:
                        num = float(valstr)
                        if num > 0:
                            pdf.set_fill_color(253, 230, 230) 
                            pdf.set_text_color(180, 0, 0)      
                            valstr = str(int(num))
                        else:
                            valstr = "-" 
                    except:
                        if valstr == '0': valstr = "-"
                
                max_chars = 40 if i == 0 else (20 if i == 1 else 15)
                pdf.cell(w, 5, safestr(valstr[:max_chars]), border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, f"No hay datos estructurados para mostrar.", ln=True)
        
    return finalizar_pdf(pdf)

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("") 
        st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")

    st.divider()

    tab_tiempos, tab_velocidad = st.tabs(["⏱️ Auditoría de Tiempos", "🚀 Telemetría (Eventos)"])

    # --------------------------------------------------------------------------
    # PESTAÑA 1: TIEMPOS
    # --------------------------------------------------------------------------
    with tab_tiempos:
        df_gps_crudo = None

        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando reporte desde la pestaña 'Auditoria'..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados de la nube correctamente.")
                        else:
                            st.warning("⚠️ La pestaña 'Auditoria' está vacía en la nube.")
                    except Exception as e:
                        st.error(f"❌ Error al conectar con la nube: {e}")
            else:
                st.error("❌ No se detectó la conexión a Google Sheets.")
                
        st.divider()

        if not es_movil:
            st.markdown("### 📥 Ingreso Manual (Modo PC)")
            archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas (Tiempos)", type=['csv', 'xlsx', 'xls'], key="up_tiempos")
            
            if archivo_gps_tiempos is not None:
                with st.spinner("🔍 Leyendo archivo y subiendo a la Nube..."):
                    try:
                        df_gps_crudo = read_file_robust(archivo_gps_tiempos)
                        if conn is not None:
                            st.toast("Subiendo datos a Google Sheets...")
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                            st.success("☁️ ¡Datos subidos a la Nube exitosamente!")
                        
                        if 'df_gps_memoria' in st.session_state: del st.session_state['df_gps_memoria']
                    except Exception as e:
                        st.error(f"❌ Error al leer o subir. Verifique que xlrd esté instalado. Detalle: {e}")
        else:
            st.info("📱 El ingreso de datos manual está deshabilitado en teléfonos.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state:
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            with st.spinner("⚙️ Procesando auditoría de tiempos..."):
                df_resumen_gps, mensaje_error = procesar_auditoria_vehiculos(df_gps_crudo)
            
            if df_resumen_gps is not None:
                st.success("✅ Análisis completado.")
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Vehículos Activos", len(df_resumen_gps))
                m2.metric("Vehículos en Calle / Sin Cierre", len(df_resumen_gps[df_resumen_gps['Última Entrada'] == "---"]))
                
                st.dataframe(df_resumen_gps, use_container_width=True, hide_index=True)
                
                pdf_bytes_tiempos = generar_pdf_auditoria_tiempos(df_resumen_gps)
                csv_gps = df_resumen_gps.to_csv(index=False).encode('utf-8')
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        label="🚀 Descargar Reporte (PDF)",
                        data=pdf_bytes_tiempos,
                        file_name=f"Auditoria_Tiempos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )
                with col_d2:
                    st.download_button(
                        label="📥 Descargar Reporte (CSV)",
                        data=csv_gps,
                        file_name=f"Auditoria_Tiempos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            else:
                st.error(f"❌ Error formato: {mensaje_error}")

    # --------------------------------------------------------------------------
    # PESTAÑA 2: TELEMETRÍA (Matriz del GPS + Promedios Detallados)
    # --------------------------------------------------------------------------
    with tab_velocidad:
        st.markdown("### 🚀 Depuración de Infractores Reales")
        st.caption("Sube TODOS los archivos a la vez: El 'Informe Estadístico' y los archivos 'Detallados' de cada técnico.")
        
        # Permitirle al usuario definir cuál es el límite para no quedar encerrado en 60
        limite_vel = st.number_input("Establecer límite de velocidad (km/h):", min_value=10, max_value=200, value=60, step=5)
        
        if not es_movil:
            archivos_telemetria = st.file_uploader(
                "Arrastra aquí todos los archivos Excel/CSV de un solo golpe", 
                type=['csv', 'xlsx', 'xls'], 
                accept_multiple_files=True,
                key="up_telemetria"
            )
            
            if archivos_telemetria:
                with st.spinner("Analizando, depurando y cruzando matrices..."):
                    archivo_principal = None
                    archivos_detallados = []
                    
                    for file in archivos_telemetria:
                        if 'estadistico' in file.name.lower() or 'informe' in file.name.lower():
                            archivo_principal = file
                        else:
                            archivos_detallados.append(file)
                            
                    if archivo_principal is None:
                        st.error("❌ No encontré el archivo principal. Asegúrate de subir el archivo llamado 'Informe_Estadistico'.")
                    else:
                        try:
                            df_raw_tel = read_file_robust(archivo_principal)
                            df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                            
                            if df_matriz is not None:
                                dict_promedios = {}
                                dict_pct = {}
                                
                                for file_det in archivos_detallados:
                                    try:
                                        df_d = read_file_robust(file_det)
                                        col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|SPEED|KM/H|KMH', str(c), re.I)), None)
                                        col_placa = next((c for c in df_d.columns if re.search(r'PLACA|ALIAS|VEHICULO|NOMBRE', str(c), re.I)), None)
                                        
                                        if col_vel and col_placa:
                                            placa_sucia = str(df_d[col_placa].iloc[0])
                                            placa_limpia = placa_sucia.split('-')[0].strip()
                                            
                                            df_d['Vel_Num'] = df_d[col_vel].astype(str).str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                            
                                            # DEPURA: Extrae solo los eventos que genuinamente superaron el límite
                                            df_excesos_reales = df_d[df_d['Vel_Num'] > limite_vel]
                                            
                                            if not df_excesos_reales.empty:
                                                promedio = df_excesos_reales['Vel_Num'].mean()
                                                pct_exceso = ((promedio - limite_vel) / limite_vel) * 100
                                                
                                                dict_promedios[placa_limpia] = round(promedio, 2)
                                                dict_pct[placa_limpia] = round(pct_exceso, 1)
                                    except Exception:
                                        pass
                                
                                if dict_promedios:
                                    col_placa_matriz = df_matriz.columns[0]
                                    df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip()
                                    
                                    df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios)
                                    df_matriz['% Exceso'] = df_matriz['Placa_Match'].map(dict_pct)
                                    
                                    # 🚨 DEPURA: Borra de la matriz a todo el que no tuvo excesos promediados (Se portaron bien)
                                    df_matriz = df_matriz.dropna(subset=['Promedio Vel. (km/h)'])
                                    
                                    df_matriz['% Exceso'] = df_matriz['% Exceso'].astype(str) + '%'
                                    df_matriz = df_matriz.drop(columns=['Placa_Match'])

                                    if df_matriz.empty:
                                        st.success(f"✅ ¡Excelente! Ningún vehículo superó la velocidad de {limite_vel} km/h en los archivos analizados.")
                                    else:
                                        st.warning(f"⚠️ Se detectaron {len(df_matriz)} vehículos con excesos confirmados (Promedio > {limite_vel} km/h).")
                                        
                                        cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)', '% Exceso']]
                                        def color_celdas(val):
                                            try:
                                                if float(val) > 0: return 'background-color: #ffcccc; color: #b30000; font-weight: bold'
                                            except: pass
                                            return ''
                                            
                                        styled_df = df_matriz.style.map(color_celdas, subset=cols_estilo)
                                        
                                        def color_pct(val):
                                            return 'background-color: #ffe6cc; color: #cc6600; font-weight: bold'
                                        styled_df = styled_df.map(color_pct, subset=['% Exceso'])
                                        
                                        st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                            
                                        pdf_matriz_bytes = generar_pdf_telemetria_matriz(df_matriz, limite_vel)
                                        st.download_button(
                                            label="📥 Descargar Reporte Final (PDF)",
                                            data=pdf_matriz_bytes,
                                            file_name=f"Auditoria_Velocidades_{datetime.now().strftime('%Y%m%d')}.pdf",
                                            mime="application/pdf",
                                            type="primary",
                                            use_container_width=True
                                        )
                                else:
                                    st.success(f"✅ No se encontraron excesos mayores a {limite_vel} km/h en los archivos detallados.")
                            else:
                                st.error(f"❌ Error al procesar matriz principal: {msg_tel}")
                        except Exception as main_e:
                            st.error(f"❌ Ocurrió un error al procesar. Detalle: {main_e}")
        else:
            st.info("📱 La carga masiva de archivos está reservada para uso en computadora (Modo PC).")
