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
        
        # Limpiar AM/PM
        df['_I'] = df['_I'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        df['_S'] = df['_S'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        
        # Forzar Datetime
        df['_I'] = pd.to_datetime(df['_I'], format='mixed', dayfirst=True, errors='coerce')
        df['_S'] = pd.to_datetime(df['_S'], format='mixed', dayfirst=True, errors='coerce')
        
        df['Fecha'] = df['_I'].dt.date.fillna(df['_S'].dt.date)
        df = df.dropna(subset=['Fecha'])
        
        if df.empty: return None, None, "No hay fechas válidas en el archivo.", None, None
        
        # 🚨 ESCUDO ANTI-FECHAS ANTIGUAS (Corrige el rango 05/01/2026)
        fecha_maxima = df['Fecha'].max()
        if pd.notnull(fecha_maxima):
            fecha_minima_valida = fecha_maxima - timedelta(days=7)
            df = df[df['Fecha'] > fecha_minima_valida].copy()

        f_inicio = df['Fecha'].min()
        f_fin = df['Fecha'].max()

        diario = df.groupby(['_P', 'Fecha']).agg(P_S=('_S', 'min'), U_E=('_I', 'max')).reset_index()
        
        # 🚨 CÁLCULO DE TIEMPOS SEGURO (Corrige el error de los 00:00:00)
        def calc_segs(row):
            ps = row['P_S']
            ue = row['U_E']
            if pd.isnull(ps) or pd.isnull(ue): return 0
            
            fecha_base = row['Fecha']
            try:
                ps_full = datetime.combine(fecha_base, ps.time())
                ue_full = datetime.combine(fecha_base, ue.time())
            except:
                return 0
            
            limite_inf = ps_full.replace(hour=6, minute=30, second=0, microsecond=0)
            limite_sup = ps_full.replace(hour=23, minute=59, second=59, microsecond=0)
            
            if ps_full < limite_inf: ps_full = limite_inf
            if ue_full > limite_sup: ue_full = limite_sup
            
            if ue_full > ps_full:
                diff = (ue_full - ps_full).total_seconds()
                if diff > 3600: return diff - 3600 # Descuenta almuerzo
                return diff
            return 0

        diario['segundos'] = diario.apply(calc_segs, axis=1)
        
        semanal = diario.groupby('_P').agg(
            Dias_Laborados=('Fecha', 'nunique'),
            Total_Segundos=('segundos', 'sum')
        ).reset_index()

        # Promedio basado SOLO en días realmente trabajados (que generaron segundos válidos)
        dias_reales = diario[diario['segundos'] > 0].groupby('_P').size().reset_index(name='Dias_Efectivos')
        semanal = pd.merge(semanal, dias_reales, on='_P', how='left')
        semanal['Dias_Efectivos'] = semanal['Dias_Efectivos'].fillna(semanal['Dias_Laborados'])
        
        semanal['Prom_Segundos'] = 0
        mask_efectivos = semanal['Dias_Efectivos'] > 0
        semanal.loc[mask_efectivos, 'Prom_Segundos'] = semanal.loc[mask_efectivos, 'Total_Segundos'] / semanal.loc[mask_efectivos, 'Dias_Efectivos']

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
    # Usar hoja A4 en formato Apaisado (Landscape 'L')
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(84, 98, 143)
    
    inicio_str = f_inicio.strftime('%d/%m/%Y') if hasattr(f_inicio, 'strftime') else str(f_inicio)
    fin_str = f_fin.strftime('%d/%m/%Y') if hasattr(f_fin, 'strftime') else str(f_fin)
    
    titulo = f" Auditoria Semanal Consolidada ({inicio_str} al {fin_str})"
    pdf.cell(0, 10, safestr(titulo), border=1, ln=True, fill=True, align="C")
    pdf.ln(5)
    
    if df_diario is not None and not df_diario.empty and df_semanal is not None and not df_semanal.empty:
        df_full = pd.merge(df_diario, df_semanal, on='Vehículo / Placa', how='left')
        
        # Anchos ajustados para cubrir el total horizontal (275mm)
        w = [75, 25, 25, 25, 30, 25, 35, 35] 
        
        pdf.set_fill_color(210, 210, 215)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 8)
        
        headers = ['VEHICULO / PLACA', 'FECHA', '1RA SALIDA', 'ULT ENTRADA', 'TIEMPO DIARIO', 'DIAS TRAB.', 'TIEMPO SEMANAL', 'PROMEDIO DIARIO']
        for i, h in enumerate(headers):
            pdf.cell(w[i], 8, safestr(h), border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 8)
        last_tec = None
        
        for idx, row in df_full.iterrows():
            tec = row['Vehículo / Placa']
            fecha_str = row['Fecha'].strftime('%d/%m/%Y') if hasattr(row['Fecha'], 'strftime') else str(row['Fecha'])
            
            if tec != last_tec:
                tec_display = safestr(tec)[:40]
                dias = str(row['Días Trabajados'])
                t_sem = safestr(row['Tiempo Total Semana'])
                p_dia = safestr(row['Promedio Diario'])
                pdf.set_fill_color(240, 248, 255) 
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
            
            if tec_display != "": pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w[0], 6, tec_display, border=1, align="L", fill=fill)
            pdf.set_font("Helvetica", "", 8)
            
            pdf.cell(w[1], 6, fecha_str, border=1, align="C", fill=fill)
            pdf.cell(w[2], 6, safestr(row['Primera Salida']), border=1, align="C", fill=fill)
            pdf.cell(w[3], 6, safestr(row['Última Entrada']), border=1, align="C", fill=fill)
            
            # Si un día no trabajó bien, ponerlo en color gris
            if row['Tiempo Diario'] == "00:00:00": pdf.set_text_color(180, 180, 180)
            pdf.cell(w[4], 6, safestr(row['Tiempo Diario']), border=1, align="C", fill=fill)
            pdf.set_text_color(0, 0, 0)
            
            if tec_display != "": pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w[5], 6, dias, border=1, align="C", fill=fill)
            pdf.cell(w[6], 6, t_sem, border=1, align="C", fill=fill)
            
            # Color verde para el Promedio
            if tec_display != "": pdf.set_text_color(0, 100, 0) 
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

# ==============================================================================
# PANTALLA VISUAL PRINCIPAL
# ==============================================================================
def mostrar_auditoria(es_movil=False, conn=None):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write(""); st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Vehículos (GPS)")
        st.caption("Control gerencial de Tiempos en Ruta y Análisis de Telemetría.")
    st.divider()

    tab_tiempos, tab_velocidad, tab_eficiencia = st.tabs(["⏱️ Auditoría de Tiempos", "🚀 Telemetría", "⚖️ Eficiencia Total"])

    # --- PESTAÑA 1: TIEMPOS ---
    with tab_tiempos:
        col_t1, col_t2 = st.columns([4, 1])
        with col_t2: 
            if st.button("🔄 Refrescar", key="ref_t"): 
                if 'df_gps_memoria' in st.session_state:
                    del st.session_state['df_gps_memoria']
                st.rerun()
                
        tipo_reporte = st.radio("📌 Selecciona el Tipo de Análisis:", ["📊 Reporte Diario", "📅 Reporte Semanal Automático"], horizontal=True)
        if tipo_reporte == "📅 Reporte Semanal Automático":
            st.info("💡 El sistema detectará automáticamente los días en el archivo o historial de la Nube para generar el resumen de la semana.")

        df_gps_crudo = None
        st.markdown("### ☁️ Sincronización de Tiempos")
        if st.button("☁️ Cargar desde la Nube (Tiempos)", use_container_width=True, type="primary"):
            if conn is not None:
                with st.spinner("📥 Descargando historial de la nube..."):
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
            archivo_gps_tiempos = st.file_uploader("Arrastra el archivo de Zonas/Rutas (Tiempos)", type=['csv', 'xlsx', 'xls'], key="up_tiempos")
            if archivo_gps_tiempos:
                with st.spinner("Subiendo a la Nube..."):
                    try:
                        df_gps_crudo = read_file_robust(archivo_gps_tiempos)
                        if conn:
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Auditoria", data=df_gps_crudo)
                            st.success("☁️ ¡Datos subidos exitosamente!")
                    except Exception as e: st.error(f"❌ Error al subir: {e}")
        else: st.info("📱 El ingreso manual está deshabilitado en móviles.")

        if df_gps_crudo is None and 'df_gps_memoria' in st.session_state: 
            df_gps_crudo = st.session_state['df_gps_memoria']

        if df_gps_crudo is not None:
            if tipo_reporte == "📊 Reporte Diario":
                with st.spinner("⚙️ Procesando tiempos diarios..."):
                    res_t, msg = procesar_auditoria_vehiculos(df_gps_crudo)
                if res_t is not None:
                    st.success("✅ Análisis Diario completado.")
                    st.dataframe(res_t, use_container_width=True, hide_index=True)
                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.download_button("🚀 Descargar Reporte Diario (PDF)", generar_pdf_auditoria_tiempos(res_t), f"Auditoria_Tiempos_Diario.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.error(f"❌ Error: {msg}")
                
            elif tipo_reporte == "📅 Reporte Semanal Automático":
                with st.spinner("⚙️ Escaneando fechas y procesando consolidado semanal..."):
                    res_diario, res_sem, msg_sem, f_in, f_out = procesar_auditoria_semanal(df_gps_crudo)
                if res_sem is not None:
                    st.success(f"✅ Análisis Semanal completado (Del {f_in.strftime('%d/%m/%Y')} al {f_out.strftime('%d/%m/%Y')}).")
                    
                    st.markdown("#### 📅 Desglose Diario por Vehículo")
                    st.dataframe(res_diario, use_container_width=True, hide_index=True)
                    
                    st.markdown("#### 📈 Promedios y Consolidado")
                    st.dataframe(res_sem, use_container_width=True, hide_index=True)
                    
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.download_button("🚀 Descargar Reporte Semanal (PDF)", generar_pdf_semanal_tiempos(res_diario, res_sem, f_in, f_out), f"Auditoria_Tiempos_Semanal.pdf", "application/pdf", use_container_width=True, type="primary")
                else: st.warning(f"⚠️ {msg_sem}")

    # --- PESTAÑA 2: TELEMETRÍA ---
    with tab_velocidad:
        col_v1, col_v2 = st.columns([4, 1])
        with col_v2: 
            if st.button("🔄 Refrescar", key="ref_v"): st.rerun()
            
        st.markdown("### 🚀 Matriz de Excesos y Velocidad Promedio")
        st.caption("El sistema creará la columna Promedio y depurará a quienes no tengan incidencias reales.")
        limite_vel = st.number_input("Promediar solo velocidades mayores a (km/h):", min_value=10, max_value=200, value=60, step=5)
        
        if not es_movil:
            archivos_telemetria = st.file_uploader("Arrastra aquí TODOS los archivos Excel/CSV juntos", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_telemetria")
            
            if archivos_telemetria:
                with st.spinner("Analizando y cruzando matrices con escáner profundo..."):
                    archivo_principal = next((f for f in archivos_telemetria if 'estadistico' in f.name.lower() or 'informe' in f.name.lower()), None)
                    archivos_detallados = [f for f in archivos_telemetria if f != archivo_principal]
                            
                    if not archivo_principal:
                        st.error("❌ Sube el archivo 'Informe_Estadistico'.")
                    else:
                        try:
                            df_raw_tel = read_file_robust(archivo_principal)
                            df_matriz, msg_tel = procesar_matriz_telemetria(df_raw_tel)
                            
                            if df_matriz is not None:
                                dict_promedios = {}
                                col_placa_matriz = df_matriz.columns[0]
                                placas_validas = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper().unique()
                                
                                if archivos_detallados:
                                    for file_det in archivos_detallados:
                                        try:
                                            file_det.seek(0)
                                            raw_text = file_det.getvalue().decode('utf-8', errors='ignore').upper()
                                            if len(raw_text) < 100: raw_text = file_det.getvalue().decode('latin1', errors='ignore').upper()
                                            
                                            placa_encontrada = None
                                            for p in placas_validas:
                                                if str(p) in raw_text or str(p) in file_det.name.upper():
                                                    placa_encontrada = str(p); break
                                            
                                            if not placa_encontrada: continue 
                                            
                                            df_d = read_file_robust(file_det)
                                            header_idx = None
                                            for i in range(min(20, len(df_d))):
                                                row_str = " ".join([str(x) for x in df_d.iloc[i].values]).upper()
                                                if 'VELOCIDAD' in row_str or 'KM/H' in row_str:
                                                    header_idx = i; break
                                            
                                            if header_idx is not None:
                                                df_d.columns = [str(x).strip().upper() for x in df_d.iloc[header_idx].values]
                                                df_d = forzar_columnas_unicas(df_d) 
                                                df_d = df_d.iloc[header_idx + 1:]
                                                
                                                col_vel = next((c for c in df_d.columns if re.search(r'VELOCIDAD|KM/H|SPEED', str(c), re.I)), None)
                                                if col_vel:
                                                    df_d['Vel_Num'] = df_d[col_vel].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
                                                    df_excesos = df_d[df_d['Vel_Num'] > limite_vel]
                                                    if not df_excesos.empty:
                                                        dict_promedios[placa_encontrada] = round(df_excesos['Vel_Num'].mean(), 2)
                                        except Exception: pass
                                            
                                df_matriz['Placa_Match'] = df_matriz[col_placa_matriz].astype(str).str.split('-').str[0].str.strip().str.upper()
                                df_matriz['Promedio Vel. (km/h)'] = df_matriz['Placa_Match'].map(dict_promedios).fillna("-")
                                df_matriz = df_matriz.drop(columns=['Placa_Match'])

                                if archivos_detallados:
                                    df_matriz = df_matriz[df_matriz['Promedio Vel. (km/h)'] != "-"]

                                if df_matriz.empty: 
                                    st.success("✅ La matriz quedó vacía tras la depuración. Ningún vehículo infractor cruzó datos con los archivos detallados.")
                                else:
                                    st.warning(f"⚠️ Se muestran {len(df_matriz)} vehículos en la matriz de infractores.")
                                    
                                    cols_estilo = [c for c in df_matriz.columns if c not in [df_matriz.columns[0], df_matriz.columns[1], 'Promedio Vel. (km/h)']]
                                    styled_df = df_matriz.style.map(lambda x: 'background-color: #ffcccc; color: #b30000; font-weight: bold' if (str(x).replace('.0','').isdigit() and float(x)>0) else '', subset=cols_estilo)
                                    st.dataframe(styled_df, hide_index=True, use_container_width=True)
                                        
                                    st.download_button(
                                        label="📥 Descargar Reporte Final (PDF)", 
                                        data=generar_pdf_telemetria_matriz(df_matriz, limite_vel), 
                                        file_name=f"Auditoria_Velocidades_{get_hn_time().strftime('%Y%m%d')}.pdf", 
                                        mime="application/pdf", 
                                        use_container_width=True, 
                                        type="primary"
                                    )
                            else: st.error(f"❌ Error matriz principal: {msg_tel}")
                        except Exception as e: st.error(f"❌ Error de procesamiento: {e}")
        else: st.info("📱 La carga masiva está reservada para PC.")

    # --- PESTAÑA 3: MÉTRICA DE EFICIENCIA TOTAL ---
    with tab_eficiencia:
        col_e1, col_e2 = st.columns([4, 1])
        with col_e2: 
            if st.button("🔄 Refrescar", key="ref_e"): st.rerun()
            
        st.markdown("### ⚖️ Cruce de Productividad vs Tiempos GPS")
        st.caption("Calcula el porcentaje real de tiempo que el técnico estuvo produciendo mientras estaba en la calle.")
        st.info("💡 Sube tu archivo de Actividades y tus reportes de GPS para cruzarlos instantáneamente.")
        
        col_up1, col_up2 = st.columns(2)
        with col_up1:
            archivo_act = st.file_uploader("1️⃣ Sube 'rep_actividades' (Órdenes)", type=['csv', 'xlsx', 'xls'], key="up_act_efi")
        with col_up2:
            archivos_detallados = st.file_uploader("2️⃣ Sube 'DetencionDetallado' (GPS)", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="up_detallado")
            
        if st.button("🚀 Calcular Eficiencia", use_container_width=True, type="primary"):
            
            df_base_local = None
            if archivo_act:
                df_base_local = read_file_robust(archivo_act)
                if df_base_local is not None:
                    cols_upper = {c: str(c).upper() for c in df_base_local.columns}
                    col_liq = next((c for c, up in cols_upper.items() if 'LIQUIDADO' in up or 'CIERRE' in up), None)
                    col_ini = next((c for c, up in cols_upper.items() if 'INICIO' in up or 'ENTRADA' in up), None)
                    col_tec = next((c for c, up in cols_upper.items() if 'TECNICO' in up or 'TÉCNICO' in up or 'USER' in up), None)
                    col_est = next((c for c, up in cols_upper.items() if 'ESTADO' in up or 'STATUS' in up), None)
                    col_num = next((c for c, up in cols_upper.items() if 'NUM' in up or 'ORDEN' in up or 'ID' in up), None)

                    if col_liq and col_ini and col_tec and col_est and col_num:
                        df_base_local = df_base_local.rename(columns={col_liq: 'HORA_LIQ', col_ini: 'HORA_INI', col_tec: 'TECNICO', col_est: 'ESTADO', col_num: 'NUM'})
            elif 'df_base' in st.session_state and st.session_state.df_base is not None:
                df_base_local = st.session_state.df_base

            if df_base_local is None: 
                st.error("❌ Faltan los datos de Actividades. Sube el archivo 'rep_actividades' en la caja 1.")
            elif not archivos_detallados:
                st.warning("⚠️ Sube al menos un archivo 'DetencionDetallado' del GPS en la caja 2.")
            else:
                with st.spinner("🧠 Procesando Inteligencia..."):
                    try:
                        df_gps_list = []
                        dict_ralenti_secs = {}
                        for file_det in archivos_detallados:
                            df_temp = read_file_robust(file_det)
                            if df_temp is not None and not df_temp.empty:
                                col_placa_temp = next((c for c in df_temp.columns if re.search(r'(?i)PLACA|ALIAS|VEHICULO', str(c))), None)
                                if not col_placa_temp:
                                    for i in range(min(15, len(df_temp))):
                                        row_str = " ".join([str(x) for x in df_temp.iloc[i].values]).upper()
                                        if 'PLACA' in row_str or 'VEHICULO' in row_str or 'ALIAS' in row_str:
                                            df_temp.columns = [str(x).strip() for x in df_temp.iloc[i].values]
                                            df_temp = df_temp.iloc[i+1:].reset_index(drop=True)
                                            df_temp = forzar_columnas_unicas(df_temp)
                                            break
                                df_gps_list.append(df_temp)
                                
                            file_det.seek(0)
                            lineas = file_det.getvalue().decode('utf-8', errors='ignore').splitlines()
                            if len(lineas) < 5: 
                                file_det.seek(0)
                                lineas = file_det.getvalue().decode('latin1', errors='ignore').splitlines()
                            for linea in lineas:
                                if "Tiempo de detencion con motor encendido" in linea:
                                    m = re.search(r'Placa:?\s*(.*?)(?:",|$)', linea)
                                    if m:
                                        p = m.group(1).replace('"', '').strip()
                                        t = linea.split(',')[-1].strip()
                                        if not t: t = linea.split(',')[-2].strip()
                                        dict_ralenti_secs[p] = dict_ralenti_secs.get(p, 0) + time_to_sec_robust(t)
                        
                        if df_gps_list:
                            res_diario, res_gps, msg_gps, f_in, f_out = procesar_auditoria_semanal(pd.concat(df_gps_list, ignore_index=True))
                            if res_gps is not None:
                                df_act = df_base_local.copy()
                                df_act['HORA_LIQ'] = pd.to_datetime(df_act['HORA_LIQ'], errors='coerce')
                                df_act['HORA_INI'] = pd.to_datetime(df_act['HORA_INI'], errors='coerce')
                                
                                df_act['Fecha_Ord'] = df_act['HORA_LIQ'].dt.date
                                df_act = df_act.dropna(subset=['Fecha_Ord'])
                                df_act = df_act[df_act['ESTADO'].astype(str).str.upper().str.contains('CERRADA', na=False)]
                                
                                df_act['Segundos_Prod'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds().clip(lower=0)
                                resumen_prod = df_act.groupby('TECNICO').agg(Ordenes=('NUM', 'count'), Seg_Prod=('Segundos_Prod', 'sum')).reset_index()
                                
                                def time_to_sec(t):
                                    parts = str(t).split(':')
                                    return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2]) if len(parts)==3 else 0
                                
                                res_gps['Seg_Calle'] = res_gps['Tiempo Total Semana'].apply(time_to_sec)
                                res_gps['Motor_Encendido_Secs'] = res_gps['Vehículo / Placa'].map(dict_ralenti_secs).fillna(0)
                                
                                def finding_placa(tec):
                                    if pd.isnull(tec): return None
                                    pt = str(tec).upper().replace(',', '').replace('.', '').split()
                                    required_matches = 2 if len(pt) >= 2 else 1
                                    
                                    for pl in res_gps['Vehículo / Placa']:
                                        pl_up = str(pl).upper()
                                        coincidencias = sum(1 for p in pt if len(p) > 2 and p in pl_up)
                                        if coincidencias >= required_matches: return pl
                                    return None
                                
                                resumen_prod['Placa_Match'] = resumen_prod['TECNICO'].apply(finding_placa)
                                df_final = pd.merge(resumen_prod, res_gps, left_on='Placa_Match', right_on='Vehículo / Placa', how='inner')
                                
                                if not df_final.empty:
                                    df_final['% Eficiencia'] = (df_final['Seg_Prod'] / df_final['Seg_Calle'] * 100).fillna(0).clip(upper=100)
                                    
                                    def sec_to_human(s):
                                        h, r = divmod(int(s), 3600); m, _ = divmod(r, 60)
                                        return f"{h:02d}h {m:02d}m"

                                    df_final['Trabajo (Órdenes)'] = df_final['Seg_Prod'].apply(sec_to_human)
                                    df_final['En Calle (GPS)'] = df_final['Seg_Calle'].apply(sec_to_human)
                                    df_final['Motor Encendido'] = df_final['Motor_Encendido_Secs'].apply(sec_to_human)
                                    
                                    st.success(f"✅ Cruce completado. Mostrando eficiencia para {len(df_final)} técnicos.")
                                    st.dataframe(df_final[['TECNICO', 'Ordenes', 'Trabajo (Órdenes)', 'En Calle (GPS)', '% Eficiencia', 'Motor Encendido']].style.format({'% Eficiencia': "{:.1f}%"}).map(
                                        lambda x: 'background-color: #2ea043; color: white' if x >= 65 else ('background-color: #d32f2f; color: white' if x < 40 else ''), subset=['% Eficiencia']
                                    ), use_container_width=True, hide_index=True)
                                else:
                                    st.warning("⚠️ No se encontraron técnicos que coincidan entre el archivo de Actividades y las placas del GPS.")
                            else:
                                st.error(f"❌ Error al procesar datos del GPS: {msg_gps}")
                        else:
                            st.error("❌ No se detectaron datos válidos en los archivos GPS subidos.")
                    except Exception as e: st.error(f"❌ Error interno en el cruce: {e}")
