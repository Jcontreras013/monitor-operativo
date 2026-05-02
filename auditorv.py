import streamlit as st
import pandas as pd
import re
import os
import io
from datetime import datetime, timedelta, time as dt_time

# Importar las herramientas de PDF y utilidades
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
# ESCUDO ANTI-DUPLICADOS Y LECTOR DE ARCHIVOS
# ==============================================================================
def forzar_columnas_unicas(df):
    if df is None or df.empty: return df
    df.columns = df.columns.astype(str).str.strip()
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        dup_indices = cols[cols == dup].index.tolist()
        for i, idx in enumerate(dup_indices):
            if i != 0:
                cols.iat[idx] = f"{dup}_{i}"
    df.columns = cols
    return df

def read_file_robust(uploaded_file):
    filename = uploaded_file.name.lower()
    content = uploaded_file.getvalue()
    df = None
    
    if content.startswith(b'\xd0\xcf\x11\xe0'):
        try:
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file, engine='xlrd')
        except ImportError:
            st.error("Falta librería xlrd para Excel antiguo.")
    elif b'<table' in content.lower() or b'<html' in content.lower():
        try:
            dfs = pd.read_html(io.StringIO(content.decode('utf-8', errors='ignore')))
            df = max(dfs, key=len)
        except Exception:
            dfs = pd.read_html(io.StringIO(content.decode('latin1', errors='ignore')))
            df = max(dfs, key=len)
    else:
        uploaded_file.seek(0)
        if filename.endswith('.xlsx'): 
            df = pd.read_excel(uploaded_file, engine='openpyxl')
        else:
            try: 
                df = pd.read_csv(uploaded_file, encoding='utf-8', on_bad_lines='skip')
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding='latin1', on_bad_lines='skip')

    return forzar_columnas_unicas(df)

def time_to_sec_robust(t_str):
    if pd.isnull(t_str) or not str(t_str).strip(): return 0
    t_str = str(t_str).strip().lower()
    days = 0
    if 'dia' in t_str or 'día' in t_str:
        parts = re.split(r'dias?|días?', t_str)
        try: days = int(parts[0].strip())
        except: pass
        t_str = parts[1].strip() if len(parts) > 1 else "00:00:00"
    try:
        h_str, m_str, s_str = t_str.split(':')
        return days * 86400 + int(h_str) * 3600 + int(m_str) * 60 + int(s_str)
    except: return 0

# ==============================================================================
# 1. LÓGICA DE AUDITORÍA DE VEHÍCULOS (TIEMPOS DIARIOS)
# ==============================================================================
def procesar_auditoria_vehiculos(df_input):
    try:
        df = df_input.copy()
        col_placa = next((c for c in df.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
        if not col_placa:
            for i in range(min(15, len(df))):
                row_str = " ".join([str(x) for x in df.iloc[i].values]).upper()
                if 'PLACA' in row_str or 'VEHICULO' in row_str or 'ALIAS' in row_str:
                    df.columns = [str(x).strip() for x in df.iloc[i].values]
                    df = df.iloc[i+1:].reset_index(drop=True)
                    df = forzar_columnas_unicas(df)
                    break
                    
        col_placa = next((c for c in df.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
        col_ingreso = next((c for c in df.columns if re.search(r'(?i)HORA.*INGRESO|HORA.*ENTRADA', str(c))), None)
        if not col_ingreso:
            col_ingreso = next((c for c in df.columns if re.search(r'(?i)INGRESO|ENTRADA', str(c)) and not re.search(r'(?i)LAT|LON', str(c))), None)
            
        col_salida = next((c for c in df.columns if re.search(r'(?i)HORA.*SALIDA', str(c))), None)
        if not col_salida:
            col_salida = next((c for c in df.columns if re.search(r'(?i)SALIDA', str(c)) and not re.search(r'(?i)LAT|LON', str(c))), None)
        
        if not (col_placa and col_ingreso and col_salida): 
            return None, "Columnas de Hora o Placa no detectadas correctamente."
            
        df = df.rename(columns={col_placa: '_P', col_ingreso: '_I', col_salida: '_S'})
        df['_P'] = df['_P'].astype(str).str.strip()
        df = df[~df['_P'].isin(['nan', '--', 'None', '', 'Columna'])]
        
        df['_I'] = df['_I'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I)
        df['_S'] = df['_S'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I)
        
        df['_I'] = pd.to_datetime(df['_I'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_I'], dayfirst=False, errors='coerce'))
        df['_S'] = pd.to_datetime(df['_S'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_S'], dayfirst=False, errors='coerce'))
        
        resumen = df.groupby('_P').agg(P_S=('_S', 'min'), U_E=('_I', 'max')).reset_index()
        
        def calc_tiempo(row):
            ps = row['P_S']
            ue = row['U_E']
            if pd.isnull(ps): return "Sin Salida"
            if pd.isnull(ue): return "Sin Ingreso"
            
            limite_inf = ps.replace(hour=6, minute=30, second=0, microsecond=0)
            limite_sup = ps.replace(hour=23, minute=59, second=59, microsecond=0)
            
            if ps < limite_inf: ps = limite_inf
            if ue > limite_sup: ue = limite_sup
            
            if ue >= ps:
                diff_secs = (ue - ps).total_seconds()
                if diff_secs > 3600: diff_secs -= 3600
                else: diff_secs = 0
                h, r = divmod(int(diff_secs), 3600); m, s = divmod(r, 60)
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
# 2. AUDITORÍA SEMANAL AUTOMÁTICA
# ==============================================================================
def procesar_auditoria_semanal(df_input):
    try:
        df = df_input.copy()
        
        col_placa = next((c for c in df.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
        if not col_placa:
            for i in range(min(15, len(df))):
                row_str = " ".join([str(x) for x in df.iloc[i].values]).upper()
                if 'PLACA' in row_str or 'VEHICULO' in row_str or 'ALIAS' in row_str:
                    df.columns = [str(x).strip() for x in df.iloc[i].values]
                    df = df.iloc[i+1:].reset_index(drop=True)
                    df = forzar_columnas_unicas(df)
                    break
                    
        col_placa = next((c for c in df.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
        col_ingreso = next((c for c in df.columns if re.search(r'(?i)HORA.*INGRESO|HORA.*ENTRADA', str(c))), None)
        if not col_ingreso:
            col_ingreso = next((c for c in df.columns if re.search(r'(?i)INGRESO|ENTRADA', str(c)) and not re.search(r'(?i)LAT|LON', str(c))), None)
            
        col_salida = next((c for c in df.columns if re.search(r'(?i)HORA.*SALIDA', str(c))), None)
        if not col_salida:
            col_salida = next((c for c in df.columns if re.search(r'(?i)SALIDA', str(c)) and not re.search(r'(?i)LAT|LON', str(c))), None)
        
        if not (col_placa and col_ingreso and col_salida): return None, None, "Columnas no detectadas.", None, None
            
        df = df.rename(columns={col_placa: '_P', col_ingreso: '_I', col_salida: '_S'})
        df['_P'] = df['_P'].astype(str).str.strip()
        df = df[~df['_P'].isin(['nan', '--', 'None', '', 'Columna'])]
        
        df['_I'] = df['_I'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I)
        df['_S'] = df['_S'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I)
        
        df['_I'] = pd.to_datetime(df['_I'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_I'], dayfirst=False, errors='coerce'))
        df['_S'] = pd.to_datetime(df['_S'], dayfirst=True, errors='coerce').fillna(pd.to_datetime(df['_S'], dayfirst=False, errors='coerce'))
        
        df['Fecha'] = df['_I'].dt.date.fillna(df['_S'].dt.date)
        df = df.dropna(subset=['Fecha'])
        
        if df.empty: return None, None, "No hay fechas válidas en el archivo.", None, None
        
        f_inicio = df['Fecha'].min()
        f_fin = df['Fecha'].max()

        diario = df.groupby(['_P', 'Fecha']).agg(P_S=('_S', 'min'), U_E=('_I', 'max')).reset_index()
        
        def calc_segs(row):
            ps = row['P_S']
            ue = row['U_E']
            if pd.isnull(ps) or pd.isnull(ue): return 0
            
            limite_inf = ps.replace(hour=6, minute=30, second=0, microsecond=0)
            limite_sup = ps.replace(hour=23, minute=59, second=59, microsecond=0)
            
            if ps < limite_inf: ps = limite_inf
            if ue > limite_sup: ue = limite_sup
            
            if ue > ps:
                diff = (ue - ps).total_seconds()
                if diff > 3600: return diff - 3600 # Descuenta almuerzo
                return 0
            return 0

        diario['segundos'] = diario.apply(calc_segs, axis=1)
        
        semanal = diario.groupby('_P').agg(
            Dias_Laborados=('Fecha', 'nunique'),
            Total_Segundos=('segundos', 'sum'),
            Prom_Segundos=('segundos', 'mean')
        ).reset_index()

        def format_segs(secs):
            if pd.isnull(secs) or secs <= 0: return "00:00:00"
            h, r = divmod(int(secs), 3600); m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        diario['Primera Salida'] = diario['P_S'].dt.strftime('%I:%M %p').fillna("---")
        diario['Última Entrada'] = diario['U_E'].dt.strftime('%I:%M %p').fillna("---")
        diario['Tiempo Diario'] = diario['segundos'].apply(format_segs)
        diario = diario.rename(columns={'_P': 'Vehículo / Placa'})
        final_diario = diario[['Vehículo / Placa', 'Fecha', 'Primera Salida', 'Última Entrada', 'Tiempo Diario']].copy()

        semanal['Tiempo Total Semana'] = semanal['Total_Segundos'].apply(format_segs)
        semanal['Promedio Diario'] = semanal['Prom_Segundos'].apply(format_segs)
        semanal = semanal.rename(columns={'_P': 'Vehículo / Placa', 'Dias_Laborados': 'Días Trabajados'})
        final_semanal = semanal[['Vehículo / Placa', 'Días Trabajados', 'Tiempo Total Semana', 'Promedio Diario']].copy()
        
        return forzar_columnas_unicas(final_diario), forzar_columnas_unicas(final_semanal), "OK", f_inicio, f_fin
    except Exception as e: return None, None, str(e), None, None


# ==============================================================================
# 3. LÓGICA DE TELEMETRÍA 
# ==============================================================================
def procesar_matriz_telemetria(df_raw):
    try:
        header_idx = None
        for i in range(min(20, len(df_raw))):
            if any(k in str(df_raw.iloc[i, 0]).upper() for k in ['PLACA', 'ALIAS', 'VEHICULO']):
                header_idx = i; break
        if header_idx is None: return None, "No se encontró encabezado en Estadístico."

        df = df_raw.iloc[header_idx + 1:].copy()
        raw_columns = df_raw.iloc[header_idx].astype(str).str.strip().tolist()
        
        clean_columns = []
        for i, col in enumerate(raw_columns):
            col_str = str(col).strip()
            if col_str.lower() in ['nan', '', 'none']:
                clean_columns.append(f"Info_{i}")
            elif i == 0:
                clean_columns.append(col_str if col_str else "Placa")
            elif i == 1:
                clean_columns.append(col_str if col_str else "Opcion")
            elif 'TOTAL' in col_str.upper():
                clean_columns.append(col_str)
            else:
                try:
                    fecha_obj = pd.to_datetime(col_str, errors='coerce')
                    if pd.notna(fecha_obj):
                        dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
                        nombre_dia = dias_semana[fecha_obj.weekday()]
                        clean_columns.append(f"{nombre_dia} {fecha_obj.strftime('%d/%m')}")
                    else:
                        clean_columns.append(col_str if col_str else f"Dia_{i-1}")
                except:
                    clean_columns.append(col_str if col_str else f"Dia_{i-1}")
        
        df.columns = clean_columns
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


# ==============================================================================
# GENERADORES DE PDF 
# ==============================================================================
def generar_pdf_auditoria_tiempos(df_resumen):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.cell(0, 10, safestr(f" Auditoria de Tiempos Diario - {get_hn_time().strftime('%d/%m/%Y %I:%M %p')}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    pdf.seccion_titulo("Consolidado Diario de Tiempos Reales")
    
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
                pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(0, 0, 0)
                if "Sin Salida" in str(item) or "Sin Ingreso" in str(item): 
                    pdf.set_fill_color(253, 230, 230)
                    pdf.set_text_color(180, 0, 0)
                pdf.cell(anchos[i], 5, safestr(str(item)[:45]), border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    return finalizar_pdf(pdf)

def generar_pdf_semanal_tiempos(df_diario, df_semanal, f_inicio, f_fin):
    # Usar hoja A4 en formato Apaisado (Landscape) para la Mega-Tabla
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(84, 98, 143)
    titulo = f" Auditoría Semanal Consolidada ({f_inicio.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')})"
    pdf.cell(0, 10, safestr(titulo), border=1, ln=True, fill=True, align="C")
    pdf.ln(5)
    
    if df_diario is not None and not df_diario.empty and df_semanal is not None and not df_semanal.empty:
        # Unir los dos dataframes en uno solo basado en el Vehículo
        df_full = pd.merge(df_diario, df_semanal, on='Vehículo / Placa', how='left')
        
        # Anchos de columna optimizados para el ancho total de un A4 Horizontal (275mm usables)
        w = [75, 22, 25, 25, 30, 25, 35, 38] 
        
        # Configurar colores del encabezado
        pdf.set_fill_color(210, 210, 215)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 8)
        
        headers = ['VEHÍCULO / PLACA', 'FECHA', '1RA SALIDA', 'ÚLT ENTRADA', 'TIEMPO DIARIO', 'DÍAS TRAB.', 'TIEMPO SEMANAL', 'PROMEDIO DIARIO']
        for i, h in enumerate(headers):
            pdf.cell(w[i], 8, safestr(h), border=1, align="C", fill=True)
        pdf.ln()
        
        # Iterar sobre las filas combinadas
        pdf.set_font("Helvetica", "", 8)
        last_tec = None
        
        for idx, row in df_full.iterrows():
            tec = row['Vehículo / Placa']
            fecha_str = row['Fecha'].strftime('%d/%m/%Y') if hasattr(row['Fecha'], 'strftime') else str(row['Fecha'])
            
            # Solo mostrar el resumen total en la primera fila de cada técnico
            if tec != last_tec:
                tec_display = safestr(tec)[:40]
                dias = str(row['Días Trabajados'])
                t_sem = safestr(row['Tiempo Total Semana'])
                p_dia = safestr(row['Promedio Diario'])
                pdf.set_fill_color(240, 248, 255) # Fondo azul súper claro para resaltar el inicio
                fill = True
                last_tec = tec
            else:
                tec_display = "" 
                dias = ""
                t_sem = ""
                p_dia = ""
                pdf.set_fill_color(255, 255, 255)
                fill = False
                
            pdf.set_text_color(0, 0, 0)
            
            # Celda 1: Placa (Negrita si es la primera fila)
            if tec_display != "": pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w[0], 6, tec_display, border=1, align="L", fill=fill)
            pdf.set_font("Helvetica", "", 8)
            
            # Celdas Diarias
            pdf.cell(w[1], 6, fecha_str, border=1, align="C", fill=fill)
            pdf.cell(w[2], 6, safestr(row['Primera Salida']), border=1, align="C", fill=fill)
            pdf.cell(w[3], 6, safestr(row['Última Entrada']), border=1, align="C", fill=fill)
            pdf.cell(w[4], 6, safestr(row['Tiempo Diario']), border=1, align="C", fill=fill)
            
            # Celdas de Totales (Negrita y color verde en el promedio)
            if tec_display != "": pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w[5], 6, dias, border=1, align="C", fill=fill)
            pdf.cell(w[6], 6, t_sem, border=1, align="C", fill=fill)
            
            if tec_display != "": pdf.set_text_color(0, 100, 0) # Texto verde para el promedio
            pdf.cell(w[7], 6, p_dia, border=1, align="C", fill=fill)
            
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 0, 0)
            pdf.ln()
            
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 10, "Sin datos disponibles.", border=0, ln=True)
        
    return finalizar_pdf(pdf)

def generar_pdf_telemetria_matriz(df_matriz, limite_vel):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4') 
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_fill_color(252, 252, 252)
    pdf.cell(0, 10, safestr(f" Matriz de Infracciones y Velocidad Promedio (> {limite_vel} km/h) - {get_hn_time().strftime('%d/%m/%Y %I:%M %p')}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    if not df_matriz.empty:
        pdf.seccion_titulo("Vehiculos con Excesos Confirmados")
        
        has_prom = 'Promedio Vel. (km/h)' in df_matriz.columns
        col_total = next((c for c in df_matriz.columns if 'TOTAL' in str(c).upper()), None)
        
        w_placa = 95  
        w_opcion = 20 
        w_prom = 25 if has_prom else 0  
        w_total = 12 if col_total else 0
        
        espacio_restante = 275 - w_placa - w_opcion - w_prom - w_total
        cols_dias = len(df_matriz.columns) - 2 - (1 if has_prom else 0) - (1 if col_total else 0)
        w_dia = espacio_restante / cols_dias if cols_dias > 0 else 10
        
        font_size = 5.5 if cols_dias <= 15 else 4.5 
        pdf.set_font("Helvetica", "B", font_size)
        pdf.set_fill_color(225, 225, 225)
        pdf.set_text_color(50, 50, 50)
        
        for i, col in enumerate(df_matriz.columns):
            if i == 0: w = w_placa
            elif i == 1: w = w_opcion
            elif col == 'Promedio Vel. (km/h)': w = w_prom
            elif str(col).upper() == 'TOTAL': w = w_total
            else: w = w_dia
            pdf.cell(w, 6, safestr(str(col)[:20]), border=1, align="C", fill=True)
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
                pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(0, 0, 0)
                
                if col_name == 'Promedio Vel. (km/h)':
                    if valstr != "-" and valstr != "":
                        pdf.set_fill_color(230, 240, 255)
                        pdf.set_text_color(0, 50, 150)
                        valstr = f"{valstr} km/h"
                    else:
                        valstr = "-"
                elif i > 1 and str(col_name).upper() != 'TOTAL': 
                    try:
                        num = float(valstr)
                        if num > 0:
                            pdf.set_fill_color(253, 230, 230)
                            pdf.set_text_color(180, 0, 0)
                            valstr = str(int(num))
                        else: valstr = "-" 
                    except:
                        if valstr == '0': valstr = "-"
                
                max_chars = 80 if i == 0 else (20 if i == 1 else 15)
                pdf.cell(w, 5, safestr(valstr[:max_chars]), border=1, align="C" if i > 0 else "L", fill=True)
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, f"Operacion Segura: Nadie supero los {limite_vel} km/h.", ln=True)
        
    return finalizar_pdf(pdf)
