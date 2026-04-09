import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import re
import os
import io

# Importar las herramientas de PDF
try:
    from tools import ReporteGenerencialPDF, finalizar_pdf, safestr
except ImportError:
    st.error("⚠️ No se pudo importar tools.py. Asegúrate de que esté en la misma carpeta.")

# ==============================================================================
# HORA LOCAL HONDURAS (UTC-6)
# ==============================================================================
def get_hn_time():
    """Ajusta la hora del servidor en la nube a la zona horaria de Honduras"""
    return datetime.utcnow() - timedelta(hours=6)

# ==============================================================================
# ESCUDO ANTI-DUPLICADOS (Evita el crash de PyArrow)
# ==============================================================================
def forzar_columnas_unicas(df):
    if df is None or df.empty: return df
    cols = pd.Series(df.columns).astype(str).str.strip()
    new_cols = []
    counts = {}
    for col in cols:
        nombre = col if col not in ["", "nan"] and "Unnamed" not in col else "Columna"
        if nombre in counts:
            counts[nombre] += 1
            new_cols.append(f"{nombre}_{counts[nombre]}")
        else:
            counts[nombre] = 0
            new_cols.append(nombre)
    df.columns = new_cols
    return df

# ==============================================================================
# LECTOR BLINDADO DE ARCHIVOS
# ==============================================================================
def read_file_robust(uploaded_file):
    filename = uploaded_file.name.lower()
    content = uploaded_file.getvalue()
    df = None
    
    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file, engine='xlrd')
        except:
            st.error("Error leyendo Excel antiguo (.xls)")
    elif b'<table' in content.lower() or b'<html' in content.lower():
        try:
            dfs = pd.read_html(io.StringIO(content.decode('utf-8', errors='ignore')))
            df = max(dfs, key=len)
        except:
            dfs = pd.read_html(io.StringIO(content.decode('latin1', errors='ignore')))
            df = max(dfs, key=len)
    else:
        uploaded_file.seek(0)
        if filename.endswith('.xlsx'): 
            df = pd.read_excel(uploaded_file, engine='openpyxl')
        else:
            try: 
                df = pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip')
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding='latin1', on_bad_lines='skip')

    return forzar_columnas_unicas(df)

# ==============================================================================
# LÓGICA DE AUDITORÍA DE VEHÍCULOS (TIEMPOS)
# ==============================================================================
def procesar_auditoria_vehiculos(df_input):
    try:
        df = df_input.copy()
        col_placa = next((c for c in df.columns if re.search(r'PLACA|ALIAS|VEHICULO', str(c), re.I)), None)
        col_ingreso = next((c for c in df.columns if re.search(r'INGRESO|ENTRADA', str(c), re.I)), None)
        col_salida = next((c for c in df.columns if re.search(r'SALIDA', str(c), re.I)), None)
        
        if not (col_placa and col_ingreso and col_salida): 
            return None, "Columnas no detectadas."
            
        df = df.rename(columns={col_placa: '_P', col_ingreso: '_I', col_salida: '_S'})
        df['_P'] = df['_P'].astype(str).str.strip()
        df = df[~df['_P'].isin(['nan', '--', 'None', '', 'Columna'])]
        
        # 🚨 PARSEO ULTRA-SEGURO DE FECHAS
        df['_I'] = pd.to_datetime(df['_I'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_I'], dayfirst=False, errors='coerce'))
        df['_S'] = pd.to_datetime(df['_S'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_S'], dayfirst=False, errors='coerce'))
        
        resumen = df.groupby('_P').agg(P_S=('_S', 'min'), U_E=('_I', 'max')).reset_index()
        
        def calc_tiempo(row):
            if pd.isnull(row['P_S']): return "Sin Salida"
            if pd.isnull(row['U_E']): return "Sin Ingreso"
            if row['U_E'] >= row['P_S']:
                diff = row['U_E'] - row['P_S']
                h, r = divmod(int(diff.total_seconds()), 3600); m, s = divmod(r, 60)
                return f"{h:02d}:{m:02d}:{s:02d}"
            return "Revisar"
                
        resumen['Tiempo Real en Calle'] = resumen.apply(calc_tiempo, axis=1)
        resumen['Primera Salida'] = resumen['P_S'].dt.strftime('%I:%M %p').fillna("---")
        resumen['Última Entrada'] = resumen['U_E'].dt.strftime('%I:%M %p').fillna("---")
        
        resumen = resumen.rename(columns={'_P': 'Vehículo / Placa'})
        final_df = resumen[['Vehículo / Placa', 'Primera Salida', 'Última Entrada', 'Tiempo Real en Calle']].copy()
        
        return forzar_columnas_unicas(final_df), "OK"
    except Exception as e: return None, str(e)

# ==============================================================================
# LÓGICA DE TELEMETRÍA (MATRIZ REPARADA)
# ==============================================================================
def procesar_matriz_telemetria(df_raw):
    try:
        header_idx = None
        for i in range(min(20, len(df_raw))):
            if any(k in str(df_raw.iloc[i, 0]).upper() for k in ['PLACA', 'ALIAS', 'VEHICULO']):
                header_idx = i; break
        if header_idx is None: return None, "Formato no reconocido."

        df = df_raw.iloc[header_idx + 1:].copy()
        raw_columns = df_raw.iloc[header_idx].astype(str).str.strip().tolist()
        df.columns = [f"Dia_{i-1}" if i > 1 else f"Info_{i}" if col.lower() in ['nan', ''] else col for i, col in enumerate(raw_columns)]
        df = forzar_columnas_unicas(df)
        
        col_placa = df.columns[0]
        col_opcion = df.columns[1] if len(df.columns) > 1 else None
        
        df = df.dropna(subset=[col_placa])
        df = df[~df[col_placa].astype(str).str.contains('La versión de este equipo', case=False, na=False)]
        
        if col_opcion:
            df = df[~df[col_opcion].astype(str).str.contains('Tiempo', case=False, na=False)]
            
        df = df[df[col_placa].astype(str).str.strip() != ''].fillna(0)
        
        col_total = next((c for c in df.columns if 'TOTAL' in str(c).upper()), None)
        if col_total:
            df[col_total] = pd.to_numeric(df[col_total], errors='coerce').fillna(0)
            df = df[df[col_total] > 0].copy()

        return df, "OK"
    except Exception as e: return None, str(e)

def extraer_promedios_detallados(df_raw, limite_vel, file_name, placas_validas):
    try:
        header_idx = None
        for i in range(min(20, len(df_raw))):
            row_str = " ".join(df_raw.iloc[i].astype(str)).upper()
            if 'VELOCIDAD' in row_str or 'KM/H' in row_str:
                header_idx = i; break
        
        if header_idx is None: df = df_raw.copy()
        else:
            df = df_raw.iloc[header_idx + 1:].copy()
            df.columns = df_raw.iloc[header_idx].astype(str).str.strip().str.upper()
            df = forzar_columnas_unicas(df)
        
        col_vel = next((c for c in df.columns if re.search(r'VELOCIDAD|KM/H', str(c), re.I)), None)
        if not col_vel: return {}
        
        df['V_N'] = df[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
        df_ex = df[df['V_N'] > limite_vel]
        if df_ex.empty: return {}
        
        col_placa = next((c for c in df.columns if re.search(r'PLACA|ALIAS', str(c), re.I)), None)
        if col_placa:
            res = {}
            for p in df_ex[col_placa].dropna().unique():
                if 'VERSIÓN' in str(p).upper(): continue
                res[str(p).split('-')[0].strip().upper()] = round(df_ex[df_ex[col_placa] == p]['V_N'].mean(), 2)
            return res
            
        # Respaldo si no encuentra columna de placa
        full_text = df_raw.astype(str).to_string().upper()
        promedio = round(df_ex['V_N'].mean(), 2)
        for p in placas_validas:
            if str(p).upper() in full_text or str(p).upper() in file_name.upper(): 
                return {str(p).upper(): promedio}
        return {}
    except: return {}

# ==============================================================================
# GENERADORES DE PDF 
# ==============================================================================
def generar_pdf_auditoria_tiempos(df_resumen):
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(84, 98, 143)
    pdf.cell(0, 10, safestr(f" Auditoria de Tiempos - {get_hn_time().strftime('%d/%m/%Y %I:%M %p')}"), border=1, ln=True, fill=True)
    pdf.ln(5); pdf.seccion_titulo("Consolidado de Tiempos Reales")
    
    if not df_resumen.empty:
        pdf.set_fill_color(225, 225, 225); pdf.set_text_color(50, 50, 50); pdf.set_font("Helvetica", "B", 7)
        anchos = [85, 30, 30, 45]
        for i, col in enumerate(df_resumen.columns): pdf.cell(anchos[i], 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        pdf.ln(); pdf.set_font("Helvetica", "", 7)
        for _, fila in df_resumen.iterrows():
            for i, item in enumerate(fila):
                pdf.set_fill_color(255, 255, 255); pdf.set_text_color(0, 0, 0)
                if "Sin Salida" in str(item) or "Sin Ingreso" in str(item): pdf.set_fill_color(253, 230, 230); pdf.set_text_color(180, 0, 0)
                pdf.cell(anchos[i], 5, safestr(str(item)[:45]), border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    return finalizar_pdf(pdf)

def generar_pdf_telemetria_matriz(df_matriz, limite_vel):
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page('L') 
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(84, 98, 143); pdf.set_fill_color(252, 252, 252)
    pdf.cell(0, 10, safestr(f" Matriz de Infracciones y Velocidad Promedio (> {limite_vel} km/h) - {get_hn_time().strftime('%d/%m/%Y %I:%M %p')}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    if not df_matriz.empty:
        pdf.seccion_titulo("Vehiculos con Excesos Confirmados")
        has_prom = 'Promedio Vel. (km/h)' in df_matriz.columns
        col_total = next((c for c in df_matriz.columns if 'TOTAL' in str(c).upper()), None)
        
        w_placa = 95; w_opcion = 20; w_prom = 25 if has_prom else 0; w_total = 12 if col_total else 0
        espacio_restante = 275 - w_placa - w_opcion - w_prom - w_total
        cols_dias = len(df_matriz.columns) - 2 - (1 if has_prom else 0) - (1 if col_total else 0)
        w_dia = espacio_restante / cols_dias if cols_dias > 0 else 10
        
        font_size = 5.5 if cols_dias <= 15 else 4.5
        pdf.set_font("Helvetica", "B", font_size); pdf.set_fill_color(225, 225, 225); pdf.set_text_color(50, 50, 50)
        
        for i, col in enumerate(df_matriz.columns):
            if i == 0: w = w_placa
            elif i == 1: w = w_opcion
            elif col == 'Promedio Vel. (km/h)': w = w_prom
            elif str(col).upper() == 'TOTAL': w = w_total
            else: w = w_dia
            pdf.cell(w, 6, safestr(str(col).replace('Dia_', '')[:20]), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", font_size)
        for _, fila in df_matriz.iterrows():
            for i, (col_name, item) in enumerate(fila.items()):
                if i == 0: w = w_placa
                elif i == 1: w = w_opcion
                elif col_name == 'Promedio Vel. (km/h)': w = w_prom
                elif str(col_name).upper() == 'TOTAL': w = w_total
                else: w = w_dia
                
                valstr = str(item).replace('.0', '').strip()
                pdf.set_fill_color(255, 255, 255); pdf.set_text_color(0, 0, 0)
                
                if col_name == 'Promedio Vel. (km/h)':
                    if valstr != "-" and valstr != "":
                        pdf.set_fill_color(230, 240, 255); pdf.set_text_color(0, 50, 150)
                        valstr = f"{valstr} km/h"
                    else: valstr = "-"
                elif i > 1 and str(col_name).upper() != 'TOTAL': 
                    try:
                        num = float(valstr)
                        if num > 0:
                            pdf.set_fill_color(253, 230, 230); pdf.set_text_color(180, 0, 0)
                            valstr = str(int(num))
                        else: valstr = "-" 
                    except:
                        if valstr == '0': valstr = "-"
                
                max_chars = 80 if i == 0 else (20 if i == 1 else 15)
                pdf.cell(w, 5, safestr(valstr[:max_chars]), border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, f"Operacion Segura: Nadie supero los {limite_vel} km/h.", ln=True)
    return finalizar_pdf(pdf)

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    st.title("🚙 Auditoría de Vehículos (GPS)")
    st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad = st.tabs(["⏱️ Auditoría de Tiempos", "🚀 Telemetría"])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_a1, col_a2 = st.columns([4, 1])
        with col_a2: 
            if st.button("🔄 Refrescar", key="ref_t"): st.rerun()
            
        df_gps_crudo = None
        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando..."):
                    try:
                        df_descarga = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", ttl=0)
                        if not df_descarga.empty:
                            st.session_state['df_gps_memoria'] = df_descarga
                            st.success("✅ Datos descargados de la nube correctamente.")
                    except Exception as e: st.error(f"❌ Error: {e}")
            else: st.error("❌ No se detectó conexión a Google Sheets.")
                
        st.divider()
        if not es_movil:
            st.markdown("### 📥 Ingreso Manual (Modo PC)")
            archivo_t = st.file_uploader("Subir Zonas/Rutas", type=['csv', 'xlsx', 'xls'], key="u_t")
            
            if archivo_t:
                with st.spinner("Procesando y Subiendo..."):
                    try:
                        df_gps_crudo = read_file_robust(archivo_t)
                        if conn:
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                            st.success("☁️ ¡Datos subidos exitosamente!")
                    except Exception as e: st.error(f"❌ Error al subir: {e}")
        else: st.info("📱 El ingreso manual está deshabilitado en móviles.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state: 
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            with st.spinner("⚙️ Analizando tiempos..."):
                res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
            if res_t is not None:
                st.success("✅ Análisis completado.")
                st.dataframe(res_t, use_container_width=True, hide_index=True)
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button("🚀 Descargar Reporte (PDF)", generar_pdf_auditoria_tiempos(res_t), f"Auditoria_Tiempos.pdf", "application/pdf", use_container_width=True, type="primary")
            else: st.error(f"❌ Error: {msg}")

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_b1, col_b2 = st.columns([4, 1])
        with col_b2: 
            if st.button("🔄 Refrescar", key="ref_v"): st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        limite = st.number_input("Límite Vel. (km/h):", value=60, step=5)
        
        if not es_movil:
            archivos_v = st.file_uploader("Subir Estadístico + Detallados", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="u_v")
            
            if archivos_v:
                with st.spinner("Cruzando datos..."):
                    main_f = next((f for f in archivos_v if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    archivos_detallados = [f for f in archivos_v if f != main_f]
                    
                    if main_f:
                        try:
                            df_m = read_file_robust(main_f)
                            res_m, msg = procesar_matriz_telemetria(df_m)
                            
                            if res_m is not None:
                                dict_promedios = {}
                                col_placa_matriz = res_m.columns[0]
                                placas_validas = res_m[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper().unique()
                                
                                if archivos_detallados:
                                    for file_det in archivos_detallados:
                                        try:
                                            df_d = read_file_robust(file_det)
                                            res_indiv = extraer_promedios_detallados(df_d, limite, file_det.name, placas_validas)
                                            dict_promedios.update(res_indiv)
                                        except Exception: pass
                                            
                                res_m['Placa_Match'] = res_m[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                                res_m['Promedio Vel. (km/h)'] = res_m['Placa_Match'].map(dict_promedios).fillna("-")
                                res_m = res_m.drop(columns=['Placa_Match'])

                                if archivos_detallados:
                                    res_m = res_m[res_m['Promedio Vel. (km/h)'] != "-"]

                                if res_m.empty: 
                                    st.success("✅ La matriz quedó vacía tras la depuración.")
                                else:
                                    st.warning(f"⚠️ Se muestran {len(res_m)} vehículos infractores.")
                                    cols_estilo = [c for c in res_m.columns if c not in [res_m.columns[0], res_m.columns[1], 'Promedio Vel. (km/h)']]
                                    styled_df = res_m.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                    st.download_button("📥 Descargar Reporte Final (PDF)", generar_pdf_telemetria_matriz(res_m, limite), f"Auditoria_Velocidades.pdf", "application/pdf", use_container_width=True, type="primary")
                            else: st.error(f"❌ Error matriz principal: {msg}")
                        except Exception as e: st.error(f"❌ Error: {e}")
                    else: st.warning("Falta archivo 'Estadístico'")
        else: st.info("📱 La carga masiva está reservada para PC.")
