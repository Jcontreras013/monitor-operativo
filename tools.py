import pandas as pd
import re
from fpdf import FPDF
from datetime import datetime, timedelta, time as dt_time
import unicodedata
import tempfile
import os
import numpy as np
import streamlit as st
import io
from typing import Any, List, Optional, Tuple, Union, Dict

# ==============================================================================
# MOTOR SEGURO DE FECHAS, ZONA HORARIA Y UTILIDADES BASE
# ==============================================================================
def safestr(texto: Any) -> str:
    """Sanitizador CRÍTICO: Previene corrupción de PDFs eliminando caracteres especiales."""
    if pd.isna(texto):
        return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

def get_honduras_time() -> datetime:
    """Ajusta la hora a UTC-6 internamente."""
    return datetime.utcnow() - timedelta(hours=6)

# Alias para mantener compatibilidad con las funciones de auditoría
get_hn_time = get_honduras_time

def parse_date_ultra_safe(val: Any) -> pd.Timestamp:
    """Motor blindado de conversión de fechas a partir de múltiples formatos entrantes."""
    if pd.isnull(val) or str(val).strip() == "" or str(val).upper() in ["NONE", "NAN", "NAT", "NULL"]:
        return pd.NaT
    
    hoy = pd.Timestamp(get_honduras_time()).normalize()

    if isinstance(val, dt_time):
        return pd.Timestamp.combine(hoy.date(), val)
    if isinstance(val, datetime):
        if val.year <= 1970:
            return hoy + pd.Timedelta(hours=val.hour, minutes=val.minute, seconds=val.second)
        return pd.Timestamp(val)
    if isinstance(val, (int, float)):
        if val == 0 or val == 0.0: return pd.NaT
        if val > 10000: return pd.to_datetime(val, unit='D', origin='1899-12-30')
        elif 0 < val < 1: return hoy + pd.to_timedelta(val, unit='D')
        else: return pd.NaT

    # === LA CURA: Limpieza de formatos MaxCom (AM/PM) ===
    str_val = str(val).strip()
    str_val = re.sub(r'(?i)a\.?\s*m\.?', 'AM', str_val)
    str_val = re.sub(r'(?i)p\.?\s*m\.?', 'PM', str_val)

    try:
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?$', str_val, re.I):
            parsed_time = pd.to_datetime(str_val).time()
            return pd.Timestamp.combine(hoy.date(), parsed_time)

        if re.match(r'^\d{4}-\d{2}-\d{2}', str_val):
            parsed = pd.to_datetime(str_val, errors='coerce')
        else:
            parsed = pd.to_datetime(str_val, dayfirst=True, errors='coerce')

        if pd.notnull(parsed):
            if parsed.year <= 1970:
                return hoy + pd.Timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
            return parsed
        return pd.NaT
    except:
        return pd.NaT

def procesar_fechas_seguro(df_input: pd.DataFrame, columnas: list) -> pd.DataFrame:
    df = df_input.copy()
    for col in columnas:
        if col in df.columns:
            df[col] = df[col].apply(parse_date_ultra_safe)
            # CRÍTICO: Forzar formato de pandas para evitar errores de ploteo en el Gantt
            df[col] = pd.to_datetime(df[col], errors='coerce')
    return df

# ==============================================================================
# 1. MAPEO UNIVERSAL DE COLUMNAS
# ==============================================================================
COLUMNS_MAPPING = {
    'HORA_INI': ['HORA ENTRADA', 'HORA INICIO', 'HORAINICIOORDEN', 'HORA INICIO ORDEN', 'FECHA ENTRADA', 'INICIO'],
    'HORA_LIQ': ['HORA LIQUIDADO', 'HORA CIERRE', 'HORACIERREORDEN', 'HORA CIERRE ORDEN', 'FECHA LIQUIDADO', 'LIQUIDADO'],
    'TECNICO': ['TÉCNICO', 'TECNICO', 'OPERADOR', 'USER NAME'],
    'ACTIVIDAD': ['NOMBRE ACTIVIDAD', 'TIPO ORDEN', 'ACTIVIDAD'],
    'FECHA_APE': ['FECHA APERTURA', 'APERTURA', 'DIASASIGNADA', 'Días'],
    'ESTADO': ['ESTADO', 'STATUS'],
    'SECTOR': ['SECTOR', 'Sect', 'Sector', 'CIUDAD', 'Ciudad', 'Zona'],
    'COLONIA': ['COLONIA', 'BARRIO', 'DIRECCION', 'LOCALIDAD'],
    'NUM': ['NUM', 'IDORDEN', 'NÚMERO'],
    'CLIENTE': ['CLIENTE', 'CUENTA', 'NO. CLIENTE'], 
    'NOMBRE': ['NOMBRE CLIENTE', 'SUSCRIPTOR', 'NOMBRE'], 
    'COMENTARIO': ['COMENTARIO', 'OBSERVACIONES'],
    'MX': ['MX', 'VEHICULO', 'UNIDAD'],
    'GPS': ['GPS', 'UBICACION', 'LINK', 'COORDENADAS']
}

COLUMNAS_VITALES_SISTEMA = [
    'HORA_INI', 'HORA_LIQ', 'TECNICO', 'ACTIVIDAD', 'FECHA_APE',
    'ESTADO', 'SECTOR', 'COLONIA', 'NUM', 'CLIENTE', 'NOMBRE', 'COMENTARIO', 'MX', 'GPS'
]

PATRON_ASIGNADAS_VIVA_STR = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'

# ==============================================================================
# 2. CLASE PARA PDF (REPORTING AVANZADO Y TABLAS COMPLEJAS)
# ==============================================================================
class ReporteGenerencialPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            self.image('logo.png', 10, 6, 35) 
        
        self.set_x(50) 
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "", 7)
        self.cell(80, 5, safestr("Reporte Operativo Consolidado"), ln=False, align="L")
        self.cell(0, 5, safestr("Maxcom PRO - Modulo Gerencial"), ln=True, align="R")
        
        self.set_draw_color(200, 200, 200)
        y_line = max(self.get_y(), 18) 
        self.line(10, y_line, 200, y_line)
        self.set_y(y_line + 5)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "", 7)
        self.cell(0, 10, f"{self.page_no()} / {{nb}}", align="R")

    def seccion_titulo(self, titulo):
        self.set_text_color(84, 98, 143)
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 6, safestr(titulo), ln=True, align="L")
        self.ln(1)

    def dibujar_tabla_rendimiento(self, df, anchos=None, alineaciones=None):
        if df.empty: return
        self.set_fill_color(225, 225, 225)
        self.set_text_color(50, 50, 50)
        self.set_draw_color(230, 230, 230)
        self.set_font("Helvetica", "B", 7)
        numcols = len(df.columns)
        w = anchos if anchos else 190 / numcols
        aligns = alineaciones if (alineaciones and len(alineaciones) == numcols) else ["C"] * numcols
        for i, col in enumerate(df.columns):
            widthcell = w if isinstance(w, (int, float)) else w[i]
            self.cell(widthcell, 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        self.ln()
        self.set_font("Helvetica", "", 7)
        for _, fila in df.iterrows():
            for i, item in enumerate(fila):
                widthcell = w if isinstance(w, (int, float)) else w[i]
                valstr = str(item)[:40]
                valclean = safestr(valstr)
                fillr, fillg, fillb = 255, 255, 255
                textr, textg, textb = 0, 0, 0
                
                if df.columns[i] in ['% LOGRO FINAL', '% LOGRO SEMANAL', '% LOGRO META']:
                    try:
                        pct = float(valstr.replace('%', ''))
                        if pct >= 100: fillr, fillg, fillb = 146, 208, 80 
                        elif pct >= 80: fillr, fillg, fillb = 169, 208, 142 
                        elif pct >= 50: fillr, fillg, fillb = 255, 230, 153 
                        elif pct >= 0: fillr, fillg, fillb = 244, 176, 132 
                    except: pass
                    
                if df.columns[i] == 'BONO MIXTO':
                    if valstr != '+0.0%':
                        fillr, fillg, fillb = 220, 235, 255 

                self.set_fill_color(fillr, fillg, fillb)
                self.set_text_color(textr, textg, textb)
                self.cell(widthcell, 5, valclean, border=1, align=aligns[i], fill=True)
            self.ln()
        self.ln(4)

    def dibujar_tabla(self, df, anchos=None, alineaciones=None):
        if df.empty: return
        self.set_fill_color(225, 225, 225)
        self.set_text_color(50, 50, 50)
        self.set_draw_color(230, 230, 230)
        self.set_font("Helvetica", "B", 7)
        numcols = len(df.columns)
        w = anchos if anchos else 190 / numcols
        aligns = alineaciones if (alineaciones and len(alineaciones) == numcols) else ["C"] * numcols
        for i, col in enumerate(df.columns):
            widthcell = w if isinstance(w, (int, float)) else w[i]
            self.cell(widthcell, 6, safestr(str(col).upper()), border=1, align="C", fill=True)
        self.ln()
        self.set_font("Helvetica", "", 7)
        for _, fila in df.iterrows():
            for i, item in enumerate(fila):
                widthcell = w if isinstance(w, (int, float)) else w[i]
                valstr = str(item)[:40]
                self.cell(widthcell, 5, safestr(valstr), border=1, align=aligns[i], fill=False)
            self.ln()
        self.ln(4)

    def dibujar_tabla_tiempos_rangos(self, titulo, headercolname, dfsubset, pivotcol, showtotalcol=False):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(84, 98, 143)
        self.cell(0, 6, safestr(titulo), ln=True, align="L")
        if dfsubset.empty:
            self.set_text_color(0, 0, 0); self.set_font("Helvetica", "", 7)
            self.cell(0, 6, "Sin datos disponibles.", ln=True); self.ln(2)
            return
        rangosorden = ['0. Anulada', '1. Menos de 1 Día', '2. De 1 a 3 Días', '3. De 3 a 6 Días', '4. Más de 6 Días', '6. Pendiente']
        pivotvals = dfsubset[pivotcol].value_counts().index.tolist()
        if showtotalcol: pivotvals.append('Total')
        wcol1 = 35
        wsub = 18
        self.set_fill_color(210, 210, 215)
        self.set_text_color(50, 50, 50)
        self.set_font("Helvetica", "B", 7)
        self.set_draw_color(220, 220, 220)
        self.cell(wcol1, 6, safestr(headercolname), border=1, align="C", fill=True)
        for pval in pivotvals:
            self.cell(wsub * 2, 6, safestr(pval), border=1, align="C", fill=True)
        self.ln()
        self.cell(wcol1, 6, "Rango Dias a Visita", border=1, align="C", fill=True)
        for pval in pivotvals:
            self.cell(wsub, 6, "Cantidad", border=1, align="C", fill=True)
            self.cell(wsub, 6, "%", border=1, align="C", fill=True)
        self.ln()
        datos = {}
        for pval in pivotvals:
            dfp = dfsubset if pval == 'Total' else dfsubset[dfsubset[pivotcol] == pval]
            datos[pval] = {'total': len(dfp), 'counts': dfp['RANGOTIEMPO'].value_counts()}
        self.set_font("Helvetica", "", 7)
        self.set_text_color(0, 0, 0)
        for rango in rangosorden:
            self.set_fill_color(255, 255, 255)
            self.cell(wcol1, 5, safestr(rango), border=1, align="L", fill=True)
            for pval in pivotvals:
                count = datos[pval]['counts'].get(rango, 0)
                tot = datos[pval]['total']
                pct = (count / tot * 100) if tot > 0 else 0
                cntstr = str(count) if count > 0 else ""
                pctstr = f"{pct:.0f}%" if count > 0 else ""
                fr, fg, fb = 255, 255, 255
                if count > 0 and 'Menos' in rango: 
                    if pct >= 75: fr, fg, fb = 146, 208, 80 
                    elif pct >= 40: fr, fg, fb = 255, 230, 153 
                    elif pct >= 25: fr, fg, fb = 244, 176, 132 
                    else: fr, fg, fb = 234, 153, 153 
                elif count > 0: 
                    if pct >= 75: fr, fg, fb = 146, 208, 80
                    elif pct >= 40: fr, fg, fb = 255, 230, 153
                    elif pct >= 25: fr, fg, fb = 244, 176, 132
                    else: fr, fg, fb = 234, 153, 153 
                self.set_fill_color(255, 255, 255)
                self.cell(wsub, 5, cntstr, border=1, align="C", fill=True)
                self.set_fill_color(fr, fg, fb)
                self.cell(wsub, 5, pctstr, border=1, align="C", fill=True)
            self.ln()
        self.set_font("Helvetica", "B", 7)
        self.set_fill_color(240, 240, 240)
        self.cell(wcol1, 5, "Total", border=1, align="L", fill=True)
        for pval in pivotvals:
            tot = datos[pval]['total']
            self.cell(wsub, 5, str(tot) if tot>0 else "0", border=1, align="C", fill=True)
            self.cell(wsub, 5, "100%" if tot>0 else "0%", border=1, align="C", fill=True)
        self.ln(6)

    def dibujar_tabla_cerradas_ciudad(self, dfbase):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(84, 98, 143)
        self.cell(0, 6, safestr("Ordenes Cerradas y Tiempo Promedio de Atencion por Ciudad"), ln=True, align="L")
        dfcerradas = dfbase[dfbase['ESTADO'].astype(str).str.upper() == 'CERRADA'].copy()
        if dfcerradas.empty:
            self.set_text_color(0, 0, 0); self.set_font("Helvetica", "", 7)
            self.cell(0, 6, "Sin datos de ordenes cerradas.", ln=True); self.ln(2)
            return
        dfgrp = dfcerradas.groupby(['SECTOR', 'TIPOACTDETALLE']).agg(
            CANTIDAD=('NUM', 'count'), MINUTOSPROMEDIO=('MINUTOS_CALC', 'mean')
        ).reset_index()
        dfgrp['MINUTOSPROMEDIO'] = dfgrp['MINUTOSPROMEDIO'].round(0).fillna(0).astype(int)
        wcity, wact, wcant, wmin = 40, 60, 30, 40
        self.set_fill_color(210, 210, 215); self.set_text_color(50, 50, 50); self.set_font("Helvetica", "B", 7)
        self.cell(wcity, 6, "Ciudad", border=1, align="C", fill=True)
        self.cell(wact, 6, "Tipo Actividad", border=1, align="C", fill=True)
        self.cell(wcant, 6, "Cantidad", border=1, align="C", fill=True)
        self.cell(wmin, 6, "Minutos Promedio", border=1, align="C", fill=True)
        self.ln()
        self.set_font("Helvetica", "", 7); self.set_text_color(0, 0, 0)
        sectores = sorted(dfgrp['SECTOR'].unique())
        grandtotcant = grandtotminsum = 0
        for sec in sectores:
            dfsec = dfgrp[dfgrp['SECTOR'] == sec].sort_values(by='CANTIDAD', ascending=False)
            first = True; sectotcant = sectotminsum = 0
            for _, row in dfsec.iterrows():
                self.set_fill_color(255, 255, 255)
                bordercity = "LTR" if first else "LR"
                self.cell(wcity, 5, safestr(sec) if first else "", border=bordercity, align="L", fill=True)
                self.cell(wact, 5, safestr(row['TIPOACTDETALLE']), border=1, align="L", fill=True)
                self.cell(wcant, 5, str(row['CANTIDAD']), border=1, align="C", fill=True)
                self.cell(wmin, 5, str(row['MINUTOSPROMEDIO']), border=1, align="C", fill=True)
                self.ln()
                first = False
                sectotcant += row['CANTIDAD']
                sectotminsum += row['MINUTOSPROMEDIO'] * row['CANTIDAD']
            secprom = int(sectotminsum / sectotcant) if sectotcant > 0 else 0
            self.set_font("Helvetica", "B", 7); self.set_fill_color(248, 248, 248)
            self.cell(wcity, 5, "", border="LRB", align="L", fill=True) 
            self.cell(wact, 5, "Total", border=1, align="L", fill=True)
            self.cell(wcant, 5, str(sectotcant), border=1, align="C", fill=True)
            self.cell(wmin, 5, str(secprom), border=1, align="C", fill=True)
            self.ln()
            self.set_font("Helvetica", "", 7)
            grandtotcant += sectotcant
            grandtotminsum += sectotminsum
        grandprom = int(grandtotminsum / grandtotcant) if grandtotcant > 0 else 0
        self.set_font("Helvetica", "B", 7); self.set_fill_color(240, 240, 240)
        self.cell(wcity + wact, 6, "Total General", border=1, align="L", fill=True)
        self.cell(wcant, 6, str(grandtotcant), border=1, align="C", fill=True)
        self.cell(wmin, 6, str(grandprom), border=1, align="C", fill=True)
        self.ln(6)

    def dibujar_tabla_tiempos_actividad(self, dfbase):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(84, 98, 143)
        self.cell(0, 6, safestr("Tiempos de Atencion Promedio por Colaborador y Actividad"), ln=True, align="L")
        
        if dfbase.empty:
            self.set_text_color(0, 0, 0); self.set_font("Helvetica", "", 7)
            self.cell(0, 6, "Sin datos disponibles.", ln=True); self.ln(2)
            return
            
        dfgrp = dfbase.groupby(['TECNICO', 'ACTIVIDAD']).agg(
            CANTIDAD=('NUM', 'count'), MINUTOSPROMEDIO=('MINUTOS_CALC', 'mean')
        ).reset_index()
        dfgrp['MINUTOSPROMEDIO'] = dfgrp['MINUTOSPROMEDIO'].round(1)
        
        wtec, wact, wcant, wmin = 55, 65, 30, 40
        
        self.set_fill_color(210, 210, 215); self.set_text_color(50, 50, 50); self.set_font("Helvetica", "B", 7)
        self.cell(wtec, 6, "Colaborador", border=1, align="C", fill=True)
        self.cell(wact, 6, "Actividad", border=1, align="C", fill=True)
        self.cell(wcant, 6, "Ordenes Atendidas", border=1, align="C", fill=True)
        self.cell(wmin, 6, "Prom. Duracion (Min)", border=1, align="C", fill=True)
        self.ln()
        
        self.set_font("Helvetica", "", 7); self.set_text_color(0, 0, 0)
        tecnicos = sorted(dfgrp['TECNICO'].unique())
        
        for tec in tecnicos:
            dftec = dfgrp[dfgrp['TECNICO'] == tec].sort_values(by='CANTIDAD', ascending=False)
            first = True
            tectotcant = 0
            tectotminsum = 0
            
            for _, row in dftec.iterrows():
                self.set_fill_color(255, 255, 255)
                bordertec = "LTR" if first else "LR"
                self.cell(wtec, 5, safestr(tec)[:32] if first else "", border=bordertec, align="L", fill=True)
                self.cell(wact, 5, safestr(row['ACTIVIDAD'])[:35], border=1, align="L", fill=True)
                self.cell(wcant, 5, str(row['CANTIDAD']), border=1, align="C", fill=True)
                self.cell(wmin, 5, str(row['MINUTOSPROMEDIO']), border=1, align="C", fill=True)
                self.ln()
                first = False
                tectotcant += row['CANTIDAD']
                tectotminsum += row['MINUTOSPROMEDIO'] * row['CANTIDAD']
                
            tecprom = round((tectotminsum / tectotcant), 1) if tectotcant > 0 else 0
            self.set_font("Helvetica", "B", 7); self.set_fill_color(248, 248, 248)
            self.cell(wtec, 5, "", border="LRB", align="L", fill=True) 
            self.cell(wact, 5, "Total", border=1, align="R", fill=True)
            self.cell(wcant, 5, str(tectotcant), border=1, align="C", fill=True)
            self.cell(wmin, 5, str(tecprom), border=1, align="C", fill=True)
            self.ln()
            self.set_font("Helvetica", "", 7)
        self.ln(6)

def finalizar_pdf(pdfobj):
    """Guarda y retorna el archivo PDF de manera segura."""
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdfobj.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

def generar_graficos_temporales(dfbase):
    paths = {}
    try:
        import matplotlib
        matplotlib.use('Agg') 
        import matplotlib.pyplot as plt
        actstr = dfbase['ACTIVIDAD'].astype(str).str.upper()
        maskins = actstr.str.contains('INS|NUEVA|ADIC|CAMBIO|PLEX')
        masksop = actstr.str.contains('SOP|FALLA|MANT')
        totins = len(dfbase[maskins])
        totsop = len(dfbase[masksop])
        tototros = len(dfbase[~(maskins | masksop)])
        labels, sizes, colors = [], [], []
        if totins > 0: labels.append('Instalaciones'); sizes.append(totins); colors.append('#5C82A6')
        if totsop > 0: labels.append('Mantenimientos'); sizes.append(totsop); colors.append('#A5B1C2')
        if tototros > 0: labels.append('Otros'); sizes.append(tototros); colors.append('#D1D8E0')
        if sizes:
            fig1, ax1 = plt.subplots(figsize=(4, 3))
            ax1.pie(sizes, labels=labels, autopct='%1.0f%%', startangle=90, colors=colors,
                    textprops={'fontsize': 8, 'color': '#333333'}, wedgeprops={'edgecolor': 'white'})
            ax1.axis('equal')
            plt.title('Instalaciones vs Mantenimientos', fontsize=9, color='#4A628A', fontweight='bold', pad=10)
            fdpie, pathpie = tempfile.mkstemp(suffix=".png")
            os.close(fdpie)
            plt.savefig(pathpie, bbox_inches='tight', dpi=150, transparent=True)
            plt.close(fig1)
            paths['pie'] = pathpie
            
        dffechas = dfbase.copy()
        dffechas['FECHAAPEDT'] = pd.to_datetime(dffechas['FECHA_APE'], errors='coerce')
        dffechas = dffechas.dropna(subset=['FECHAAPEDT'])
        if not dffechas.empty:
            conteofechas = dffechas.groupby(dffechas['FECHAAPEDT'].dt.date).size().tail(7)
            if not conteofechas.empty:
                fig2, ax2 = plt.subplots(figsize=(5, 3))
                etiquetasx = [d.strftime('%d/%m') for d in conteofechas.index]
                bars = ax2.bar(etiquetasx, conteofechas.values, color='#8FA1B3')
                ax2.set_title('Creacion de Ordenes por Fecha (Ultimos 7 dias)', fontsize=9, color='#4A628A', fontweight='bold', pad=10)
                ax2.tick_params(axis='x', rotation=30, labelsize=7, colors='#555555')
                ax2.tick_params(axis='y', labelsize=7, colors='#555555')
                ax2.spines['top'].set_visible(False)
                ax2.spines['right'].set_visible(False)
                ax2.spines['left'].set_color('#DDDDDD')
                ax2.spines['bottom'].set_color('#DDDDDD')
                for bar in bars:
                    yval = bar.get_height()
                    ax2.text(bar.get_x() + bar.get_width()/2, yval + (yval*0.02), int(yval),
                             ha='center', va='bottom', fontsize=7, color='#333333')
                fdbar, pathbar = tempfile.mkstemp(suffix=".png")
                os.close(fdbar)
                plt.tight_layout()
                plt.savefig(pathbar, bbox_inches='tight', dpi=150, transparent=True)
                plt.close(fig2)
                paths['bar'] = pathbar
        return paths
    except ImportError:
        return {}
    except Exception as e:
        return {}

def _generar_dona_png(pct, titulo):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        color = "#EF4444" if pct < 50 else ("#F59E0B" if pct < 80 else "#10B981")
        fig, ax = plt.subplots(figsize=(2.5, 2.5))
        ax.pie([pct, max(0, 100-pct)], colors=[color, '#E5E7EB'], startangle=90, counterclock=False, wedgeprops=dict(width=0.3, edgecolor='w'))
        ax.text(0, 0, f"{pct:.0f}%", ha='center', va='center', fontsize=20, fontweight='bold', color=color)
        plt.title(titulo, fontsize=10, color='#333333', fontweight='bold', pad=5)
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        plt.savefig(path, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)
        return path
    except:
        return None

def calcular_aporte_meta(row):
    act = str(row.get('ACTIVIDAD', '')).upper()
    com = str(row.get('COMENTARIO', '')).upper()
    txt = act + " " + com
    if 'PEXTERNO' in act: return 100.0  
    elif re.search('ADIC|CAMBIO|MIGRACI|RECUP', txt): return 12.5   
    elif re.search('INS|NUEVA|PLEX|SPLITTEROPT', act): return 25.0   
    elif re.search('SOP|FALLA|MANT|RECON|TRASLADO', act): return 12.5   
    else: return 12.5   

# ==============================================================================
# REPORTES DE GERENCIA ORIGINALES
# ==============================================================================
def generar_pdf_semanal(df_base, fecha_inicio, fecha_fin):
    df_sem = df_base[
        (df_base['HORA_LIQ'].dt.date >= fecha_inicio) & 
        (df_base['HORA_LIQ'].dt.date <= fecha_fin) &
        (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
    ].copy()
    
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    pdf.cell(0, 10, safestr(f" Reporte Analitico Semanal: {fecha_inicio} al {fecha_fin}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Rendimiento Operativo Semanal (Basado en Metas de Cuota)")
    if not df_sem.empty:
        df_sem['%_APORTE'] = df_sem.apply(calcular_aporte_meta, axis=1)
        df_tec = df_sem.groupby('TECNICO').agg(ORDENES=('NUM', 'count'), PORCENTAJE_META=('%_APORTE', 'sum')).reset_index()
        df_tec['% LOGRO SEMANAL'] = ((df_tec['PORCENTAJE_META'] / 600.0) * 100).round(1)
        df_tec = df_tec.sort_values(by='% LOGRO SEMANAL', ascending=False)
        df_tec_table = df_tec[['TECNICO', 'ORDENES', 'PORCENTAJE_META', '% LOGRO SEMANAL']].copy()
        df_tec_table.columns = ['TECNICO', 'ORDENES', 'PUNTOS ACUMULADOS', '% LOGRO SEMANAL']
        df_tec_table['% LOGRO SEMANAL'] = df_tec_table['% LOGRO SEMANAL'].astype(str) + '%'
        pdf.dibujar_tabla_rendimiento(df_tec_table, anchos=[80, 30, 40, 40], alineaciones=["L", "C", "C", "C"])
        
        imagenes = generar_graficos_temporales(df_sem)
        if imagenes and 'pie' in imagenes:
            pdf.add_page()
            pdf.seccion_titulo("Distribucion Grafica Semanal")
            pdf.image(imagenes['pie'], x=60, y=pdf.get_y() + 5, w=90)
            for path in imagenes.values():
                try: os.remove(path)
                except: pass
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos de ordenes cerradas en este rango de fechas.", ln=True)
        
    return finalizar_pdf(pdf)

def generar_pdf_mensual(df_base, mes, anio):
    df_mes = df_base[
        (df_base['HORA_LIQ'].dt.month == mes) & 
        (df_base['HORA_LIQ'].dt.year == anio) &
        (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
    ].copy()
    
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    meses_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    nombre_mes = meses_nombres[mes - 1]
    pdf.cell(0, 10, safestr(f" Reporte Consolidado Mensual: {nombre_mes} {anio}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Vision Macro Gerencial - Consolidado por Ciudades")
    if not df_mes.empty:
        pdf.dibujar_tabla_cerradas_ciudad(df_mes)
        imagenes = generar_graficos_temporales(df_mes)
        if imagenes and 'pie' in imagenes:
            pdf.add_page()
            pdf.seccion_titulo("Distribucion Grafica Mensual")
            pdf.image(imagenes['pie'], x=60, y=pdf.get_y() + 5, w=90)
            for path in imagenes.values():
                try: os.remove(path)
                except: pass
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos de ordenes cerradas registradas para este mes.", ln=True)
        
    return finalizar_pdf(pdf)

def generar_pdf_cierre_diario(dfbase, fechatarget):
    dfc = dfbase[
        (dfbase['HORA_LIQ'].dt.date == fechatarget) & 
        (dfbase['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
    ].copy()
    
    def get_tipo_detalle(row):
        txt = (str(row.get('ACTIVIDAD', '')) + " " + str(row.get('COMENTARIO', ''))).upper()
        if 'RECON' in txt: return 'RECONEXIONES'
        if 'TRASLADO' in txt: return 'TRASLADOS'
        if re.search('INS|NUEVA|ADIC|CAMBIO|PLEX|MIGRACI|RECUP', txt): return 'INSTALACION'
        if re.search('SOP|FALLA|MANT', txt): return 'MANTENIMIENTO'
        return 'OTROS'
        
    def get_tipo_orden(row):
        txt = (str(row.get('ACTIVIDAD', '')) + " " + str(row.get('COMENTARIO', ''))).upper()
        if re.search('INS|NUEVA|ADIC|CAMBIO|PLEX|MIGRACI|RECUP', txt): return 'INSTALACION'
        if re.search('SOP|FALLA|MANT', txt): return 'MANTENIMIENTO'
        return 'OTROS'

    def get_rango(row):
        est = str(row.get('ESTADO', '')).upper()
        dias = row.get('DIAS_RETRASO', 0)
        if 'ANULADA' in est: return '0. Anulada'
        if 'CERRADA' not in est: return '6. Pendiente'
        if dias < 1: return '1. Menos de 1 Día'
        if 1 <= dias <= 3: return '2. De 1 a 3 Días'
        if 4 <= dias <= 6: return '3. De 3 a 6 Días'
        return '4. Más de 6 Días'

    if not dfc.empty:
        dfc['TIPOACTDETALLE'] = dfc.apply(get_tipo_detalle, axis=1)
        dfc['TIPOORDEN'] = dfc.apply(get_tipo_orden, axis=1)
        if 'DIAS_RETRASO' not in dfc.columns:
            ahora = pd.Timestamp(datetime.now())
            dfc['DIAS_RETRASO'] = (ahora.normalize() - pd.to_datetime(dfc['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).clip(lower=0).astype(int)
        dfc['RANGOTIEMPO'] = dfc.apply(get_rango, axis=1)

    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    pdf.cell(0, 10, safestr(f" Reporte Analitico de Cierre Diario: {fechatarget}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Analisis de Eficiencia (Puntos por Meta + 10% Bono por Ruta Mixta)")
    if not dfc.empty:
        dfc['CANT_INS'] = (dfc['TIPOORDEN'] == 'INSTALACION').astype(int)
        dfc['CANT_SOP'] = (dfc['TIPOORDEN'] == 'MANTENIMIENTO').astype(int)
        dfc['CANT_OTR'] = (dfc['TIPOORDEN'] == 'OTROS').astype(int)
        dfc['%_APORTE'] = dfc.apply(calcular_aporte_meta, axis=1)
        
        df_tec = dfc.groupby('TECNICO').agg(
            CANT_INS=('CANT_INS', 'sum'),
            CANT_SOP=('CANT_SOP', 'sum'),
            CANT_OTR=('CANT_OTR', 'sum'),
            PUNTOS_BASE=('%_APORTE', 'sum')
        ).reset_index()
        
        def calcular_bono(row):
            tipos = sum([1 for x in [row['CANT_INS'], row['CANT_SOP'], row['CANT_OTR']] if x > 0])
            if tipos > 1: return 10.0 
            return 0.0
            
        df_tec['BONO_MIXTO'] = df_tec.apply(calcular_bono, axis=1)
        df_tec['LOGRO_FINAL'] = df_tec['PUNTOS_BASE'] + df_tec['BONO_MIXTO']
        df_tec = df_tec.sort_values(by='LOGRO_FINAL', ascending=False)
        
        df_tec_table = df_tec[['TECNICO', 'CANT_INS', 'CANT_SOP', 'CANT_OTR', 'PUNTOS_BASE', 'BONO_MIXTO', 'LOGRO_FINAL']].copy()
        df_tec_table.columns = ['TECNICO', 'INS', 'SOP', 'OTR', 'PUNTOS BASE', 'BONO MIXTO', '% LOGRO FINAL']
        df_tec_table['PUNTOS BASE'] = df_tec_table['PUNTOS BASE'].round(1).astype(str) + '%'
        df_tec_table['BONO MIXTO'] = '+' + df_tec_table['BONO MIXTO'].round(1).astype(str) + '%'
        df_tec_table['% LOGRO FINAL'] = df_tec_table['% LOGRO FINAL'].round(1).astype(str) + '%'
        pdf.dibujar_tabla_rendimiento(df_tec_table, anchos=[55, 15, 15, 15, 30, 30, 30], alineaciones=["L", "C", "C", "C", "C", "C", "C"])
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos de productividad para hoy.", ln=True)

    if not dfc.empty:
        pdf.add_page()
        pdf.seccion_titulo("Indicadores de Avance Operativo (Completado vs Pendiente)")
        
        mask_tec = (dfbase['TECNICO'].notna() & (dfbase['TECNICO'].astype(str).str.strip() != '') & (~dfbase['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL'])))
        dfv = dfbase[mask_tec].copy()
        df_vivas = dfv[dfv['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)]
        
        resi_pend = len(df_vivas[df_vivas['SEGMENTO'] == 'RESIDENCIAL'])
        resi_cerr = len(dfc[dfc['SEGMENTO'] == 'RESIDENCIAL'])
        t_resi = resi_pend + resi_cerr
        pct_resi = (resi_cerr / t_resi * 100) if t_resi > 0 else 0
        
        plex_pend = len(df_vivas[df_vivas['SEGMENTO'] == 'PLEX'])
        plex_cerr = len(dfc[dfc['SEGMENTO'] == 'PLEX'])
        t_plex = plex_pend + plex_cerr
        pct_plex = (plex_cerr / t_plex * 100) if t_plex > 0 else 0
        
        t_global = len(df_vivas) + len(dfc)
        pct_global = (len(dfc) / t_global * 100) if t_global > 0 else 0

        path_resi = _generar_dona_png(pct_resi, "Residencial")
        path_plex = _generar_dona_png(pct_plex, "PLEX")
        path_global = _generar_dona_png(pct_global, "Global")

        current_y = pdf.get_y()
        if path_resi: pdf.image(path_resi, x=20, y=current_y, w=50)
        if path_plex: pdf.image(path_plex, x=80, y=current_y, w=50)
        if path_global: pdf.image(path_global, x=140, y=current_y, w=50)
        
        pdf.ln(60) 
        
        for path in [path_resi, path_plex, path_global]:
            if path:
                try: os.remove(path)
                except: pass
        
        pdf.add_page()
        pdf.seccion_titulo("Tiempos de Atencion (Antiguedad de Ordenes Liquidadas)")
        pdf.ln(2)
        dfins = dfc[dfc['TIPOORDEN'] == 'INSTALACION']
        pdf.dibujar_tabla_tiempos_rangos("Instalaciones Liquidadas por Rango", "Ciudad", dfins, 'SECTOR', showtotalcol=False)
        dfmant = dfc[dfc['TIPOORDEN'] == 'MANTENIMIENTO']
        pdf.dibujar_tabla_tiempos_rangos("Mantenimientos Liquidados por Rango", "Ciudad", dfmant, 'SECTOR', showtotalcol=False)
        
        pdf.add_page()
        pdf.dibujar_tabla_cerradas_ciudad(dfc)

        pdf.add_page()
        pdf.seccion_titulo("Resumen Consolidado por Tipo de Actividad")
        df_act_summary = dfc['ACTIVIDAD'].value_counts().reset_index()
        df_act_summary.columns = ['Actividad Realizada', 'Total de Ordenes']
        pdf.dibujar_tabla(df_act_summary, anchos=[120, 40], alineaciones=["L", "C"])

        pdf.add_page()
        pdf.dibujar_tabla_tiempos_actividad(dfc)

    pdf.add_page()
    pdf.seccion_titulo("Consolidado General de Ordenes Liquidadas")
    if not dfc.empty:
        pdf.dibujar_tabla(dfc[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL']], anchos=[30, 60, 60, 40], alineaciones=["C", "L", "L", "C"])

    if not dfc.empty:
        imagenes = generar_graficos_temporales(dfc)
        if imagenes and 'pie' in imagenes:
            pdf.add_page()
            pdf.seccion_titulo("Distribucion Grafica de la Jornada")
            pdf.image(imagenes['pie'], x=60, y=pdf.get_y() + 5, w=90)
            for path in imagenes.values():
                try: os.remove(path)
                except: pass
                
    return finalizar_pdf(pdf)

def logica_generar_pdf(dfbase):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    if 'DIAS_RETRASO' not in dfbase.columns:
        ahora = pd.Timestamp(datetime.now())
        dfbase['DIAS_RETRASO'] = (ahora.normalize() - pd.to_datetime(dfbase['FECHA_APE'], errors='coerce').dt.normalize()).dt.days.fillna(0).clip(lower=0).astype(int)
        
    def getrango(row):
        est = str(row.get('ESTADO', '')).upper()
        dias = row.get('DIAS_RETRASO', 0)
        if 'ANULADA' in est: return '0. Anulada'
        if 'CERRADA' not in est: return '6. Pendiente'
        if dias < 1: return '1. Menos de 1 Día'
        if 1 <= dias <= 3: return '2. De 1 a 3 Días'
        if 4 <= dias <= 6: return '3. De 3 a 6 Días'
        return '4. Más de 6 Días'
        
    dfbase['RANGOTIEMPO'] = dfbase.apply(getrango, axis=1)
    
    def gettipoorden(row):
        txt = (str(row.get('ACTIVIDAD', '')) + " " + str(row.get('COMENTARIO', ''))).upper()
        if re.search('INS|NUEVA|ADIC|CAMBIO|PLEX|MIGRACI|RECUP', txt): return 'INSTALACION'
        if re.search('SOP|FALLA|MANT', txt): return 'MANTENIMIENTO'
        return 'OTROS'
        
    dfbase['TIPOORDEN'] = dfbase.apply(gettipoorden, axis=1)
    
    def gettipodetalle(row):
        txt = (str(row.get('ACTIVIDAD', '')) + " " + str(row.get('COMENTARIO', ''))).upper()
        if 'RECON' in txt: return 'RECONEXIONES'
        if 'TRASLADO' in txt: return 'TRASLADOS'
        if re.search('INS|NUEVA|ADIC|CAMBIO|PLEX|MIGRACI|RECUP', txt): return 'INSTALACION'
        if re.search('SOP|FALLA|MANT', txt): return 'MANTENIMIENTO'
        return 'OTROS'
        
    dfbase['TIPOACTDETALLE'] = dfbase.apply(gettipodetalle, axis=1)
    
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(84, 98, 143)
    ahorastr = datetime.now().strftime('%d/%m/%Y')
    pdf.set_draw_color(220, 220, 220)
    pdf.set_fill_color(252, 252, 252)
    pdf.cell(0, 10, safestr(f" Reporte Dinamico de Rendimiento de Instalacion y Mantenimiento: {ahorastr}"), border=1, ln=True, fill=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Rendimiento Operativo (Basado en Metas de Cuota y Complejidad)")
    if not dfbase.empty:
        dfbase['%_APORTE'] = dfbase.apply(calcular_aporte_meta, axis=1)
        df_tec = dfbase.groupby('TECNICO').agg(ORDENES=('NUM', 'count'), PORCENTAJE_META=('%_APORTE', 'sum')).reset_index()
        
        df_tec['% LOGRO META'] = df_tec['PORCENTAJE_META'].round(1)
        df_tec = df_tec.sort_values(by='% LOGRO META', ascending=False)
        
        df_tec_table = df_tec[['TECNICO', 'ORDENES', 'PORCENTAJE_META', '% LOGRO META']].copy()
        df_tec_table.columns = ['TECNICO', 'ORDENES', 'PUNTOS ACUMULADOS', '% LOGRO META']
        df_tec_table['% LOGRO META'] = df_tec_table['% LOGRO META'].astype(str) + '%'
        
        pdf.dibujar_tabla_rendimiento(df_tec_table, anchos=[80, 30, 40, 40], alineaciones=["L", "C", "C", "C"])
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, "Sin datos disponibles.", ln=True)

    pdf.add_page()
    pdf.seccion_titulo("Capitulo I - Rangos de Tiempo de Atencion")
    pdf.ln(2)
    dfins = dfbase[dfbase['TIPOORDEN'] == 'INSTALACION']
    pdf.dibujar_tabla_tiempos_rangos("Instalaciones por Rango de Tiempo", "Ciudad", dfins, 'SECTOR', showtotalcol=False)
    dfmant = dfbase[dfbase['TIPOORDEN'] == 'MANTENIMIENTO']
    pdf.dibujar_tabla_tiempos_rangos("Mantenimientos por Rango de Tiempo", "Ciudad", dfmant, 'SECTOR', showtotalcol=False)
    pdf.dibujar_tabla_tiempos_rangos("Rango de Tiempo de Atencion por Tipo de Orden", "Tipo Orden", dfbase, 'TIPOORDEN', showtotalcol=True)
    
    pdf.add_page()
    pdf.dibujar_tabla_cerradas_ciudad(dfbase)
    
    imagenes = generar_graficos_temporales(dfbase)
    if imagenes:
        pdf.ln(5)
        pdf.seccion_titulo("Analisis Grafico Operativo")
        pdf.ln(5)
        currenty = pdf.get_y()
        if 'pie' in imagenes:
            pdf.image(imagenes['pie'], x=15, y=currenty, w=85)
        if 'bar' in imagenes:
            pdf.image(imagenes['bar'], x=110, y=currenty, w=90)
        for path in imagenes.values():
            try: os.remove(path)
            except: pass
            
    return finalizar_pdf(pdf)

def generar_pdf_trimestral_detallado(tabla_produccion, tabla_eficiencia, resumen_jornada):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE GERENCIAL: RENDIMIENTO Y JORNADA DE TECNICOS"), border=0, ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 6, safestr(f"Generado el: {ahorastr}"), ln=True, align="C")
    pdf.ln(5)
    
    if resumen_jornada.empty:
        pdf.cell(0, 10, "No hay datos suficientes para generar el reporte.", ln=True)
        return finalizar_pdf(pdf)

    lista_tecnicos = resumen_jornada['TECNICO'].dropna().unique()
    
    for tecnico in lista_tecnicos:
        if pdf.get_y() > 220:
            pdf.add_page()
            
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 240, 255)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, safestr(f"   TECNICO: {tecnico}"), border=1, ln=True, fill=True)
        
        df_jor = resumen_jornada[resumen_jornada['TECNICO'] == tecnico]
        df_prod = tabla_produccion[tabla_produccion['TECNICO'] == tecnico]
        df_efi = tabla_eficiencia[tabla_eficiencia['TECNICO'] == tecnico]
        
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 6, "   RESUMEN DE JORNADA LABORAL", ln=True)
        
        pdf.set_font("Helvetica", "", 8)
        prom_horas = df_jor['Promedio_Horas_Dia'].values[0] if not df_jor.empty else 0
        dias_lab = df_jor['Dias_Laborados'].values[0] if not df_jor.empty else 0
        max_horas = df_jor['Max_Horas_Dia'].values[0] if not df_jor.empty else 0
        
        pdf.cell(10, 5, "", border=0)
        pdf.cell(50, 5, safestr(f"Dias Trabajados: {dias_lab}"), border=0)
        pdf.cell(60, 5, safestr(f"Promedio en Calle: {prom_horas:.2f} hrs/dia"), border=0)
        pdf.cell(50, 5, safestr(f"Dia mas largo: {max_horas:.2f} hrs"), border=0, ln=True)
        pdf.ln(2)
        
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 6, "   DESGLOSE DE ACTIVIDAD Y TIEMPOS", ln=True)
        
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(10, 5, "", border=0)
        pdf.cell(60, 5, "Tipo de Actividad", border=1, align="C", fill=True)
        pdf.cell(25, 5, "Volumen", border=1, align="C", fill=True)
        pdf.cell(25, 5, "% del Total", border=1, align="C", fill=True)
        pdf.cell(40, 5, "Promedio de Resolucion", border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 8)
        total_ordenes_tec = 0
        
        df_prod = df_prod.sort_values(by='Cantidad', ascending=False)
        
        for _, fila_p in df_prod.iterrows():
            actividad = str(fila_p['ACTIVIDAD'])
            cantidad = fila_p['Cantidad']
            porcentaje = fila_p['Participacion_%']
            total_ordenes_tec += cantidad
            
            fila_efi = df_efi[df_efi['ACTIVIDAD'] == actividad]
            minutos_prom = fila_efi['Promedio_Minutos'].values[0] if not fila_efi.empty else 0
            
            pdf.cell(10, 5, "", border=0)
            pdf.cell(60, 5, safestr(actividad[:35]), border=1)
            pdf.cell(25, 5, safestr(str(cantidad)), border=1, align="C")
            pdf.cell(25, 5, safestr(f"{porcentaje}%"), border=1, align="C")
            
            if pd.notnull(minutos_prom) and minutos_prom > 120:
                pdf.set_text_color(200, 0, 0)
                pdf.cell(40, 5, safestr(f"{minutos_prom:.0f} min [!]"), border=1, align="C")
                pdf.set_text_color(0, 0, 0)
            elif pd.notnull(minutos_prom):
                pdf.cell(40, 5, safestr(f"{minutos_prom:.0f} min"), border=1, align="C")
            else:
                pdf.cell(40, 5, "---", border=1, align="C")
            
            pdf.ln()
            
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(10, 5, "", border=0)
        pdf.cell(60, 5, "TOTAL ORDENES", border=1, align="R", fill=True)
        pdf.cell(25, 5, safestr(str(total_ordenes_tec)), border=1, align="C", fill=True)
        pdf.cell(65, 5, "", border=0, ln=True)
        
        pdf.ln(8)
        
    return finalizar_pdf(pdf)

def generar_pdf_primera_orden(df_base, fecha_cierre):
    try:
        mask_vivas = df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        mask_cerradas = (pd.to_datetime(df_base['HORA_LIQ'], errors='coerce').dt.date == fecha_cierre) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
        
        df_universo = pd.concat([df_base[mask_vivas], df_base[mask_cerradas]]).drop_duplicates(subset=['NUM'])
        
        if 'HORA_INI' in df_universo.columns:
            df_universo['HORA_INI_DT'] = pd.to_datetime(df_universo['HORA_INI'], errors='coerce')
            df_universo = df_universo.dropna(subset=['HORA_INI_DT'])
            
            mask_fecha_ini = df_universo['HORA_INI_DT'].dt.date == pd.to_datetime(fecha_cierre).date()
            df_primera = df_universo[mask_fecha_ini].sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO'], keep='first')
            df_primera = df_primera.sort_values(by='HORA_INI_DT')
        else:
            return None 

        pdf = ReporteGenerencialPDF()
        pdf.alias_nb_pages()
        pdf.add_page()
        
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 10, safestr(f"REPORTE: PRIMERA ORDEN DEL DIA ({fecha_cierre})"), border=0, ln=True, align="C")
        pdf.ln(5)

        if not df_primera.empty:
            df_mostrar = df_primera[['TECNICO', 'HORA_INI_DT', 'COLONIA', 'NUM']].copy()
            df_mostrar['HORA_INI'] = df_mostrar['HORA_INI_DT'].dt.strftime('%H:%M:%S')
            df_mostrar = df_mostrar.drop(columns=['HORA_INI_DT'])
            df_mostrar = df_mostrar[['TECNICO', 'HORA_INI', 'COLONIA', 'NUM']]
            
            pdf.dibujar_tabla(df_mostrar, anchos=[70, 30, 60, 30], alineaciones=["L", "C", "L", "C"])
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 10, "No hay registros de primera orden para esta fecha.", ln=True, align="C")

        return finalizar_pdf(pdf)
    except Exception as e:
        print(f"Error al generar PDF de Primera Orden: {e}")
        return None

def generar_pdf_pendientes_dispatch(df_totales, df_detalle, hoy_str):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE DE PENDIENTES GENERALES (DISPATCH)"), border=0, ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Corte Operativo del Día: {hoy_str}"), ln=True, align="C")
    pdf.ln(10)
    
    pdf.seccion_titulo("RESUMEN DE CARGA PARA EL SIGUIENTE TURNO")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(60, 8, "Clasificacion", border=1, fill=True)
    pdf.cell(40, 8, "Asignadas (Ruta)", border=1, align="C", fill=True)
    pdf.cell(40, 8, "Sin Asignar", border=1, align="C", fill=True)
    pdf.cell(40, 8, "Total General", border=1, align="C", fill=True)
    pdf.ln()
    
    for _, row in df_totales.iterrows():
        if row['Categoría'] == 'TOTAL PENDIENTES':
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(220, 230, 245)
            fill = True
        else:
            pdf.set_font("Helvetica", "", 8) 
            fill = False
            
        pdf.cell(60, 7, safestr(row['Categoría'])[:35], border=1, fill=fill)
        pdf.cell(40, 7, str(row['Asignadas (En Ruta)']), border=1, align="C", fill=fill)
        pdf.cell(40, 7, str(row['Nuevas (Sin Asignar)']), border=1, align="C", fill=fill)
        pdf.cell(40, 7, str(row['TOTAL GENERAL']), border=1, align="C", fill=fill)
        pdf.ln()

    pdf.ln(10)
    
    mask_sin_tec = (df_detalle['TECNICO'].isna()) | (df_detalle['TECNICO'].astype(str).str.strip() == '') | (df_detalle['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
    df_no_asig = df_detalle[mask_sin_tec].copy()

    if not df_no_asig.empty:
        pdf.seccion_titulo("LISTADO PRIORITARIO: ORDENES NUEVAS (SIN ASIGNAR)")
        
        pdf.set_fill_color(255, 235, 235) 
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(20, 6, "Orden", border=1, align="C", fill=True)
        pdf.cell(30, 6, "Cliente", border=1, align="C", fill=True)
        pdf.cell(60, 6, "Actividad", border=1, align="C", fill=True)
        pdf.cell(70, 6, "Colonia", border=1, align="C", fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(0, 0, 0)
        
        for _, row in df_no_asig.iterrows():
            pdf.cell(20, 5, safestr(str(row['NUM'])), border=1, align="C")
            pdf.cell(30, 5, safestr(str(row['CLIENTE'])), border=1, align="C")
            pdf.cell(60, 5, safestr(str(row['ACTIVIDAD']))[:35], border=1, align="L")
            pdf.cell(70, 5, safestr(str(row.get('COLONIA', '')))[:40], border=1, align="L")
            pdf.ln()
    else:
        pdf.seccion_titulo("LISTADO PRIORITARIO: ORDENES NUEVAS (SIN ASIGNAR)")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(0, 100, 0)
        pdf.cell(0, 6, "Excelente. Todas las ordenes se encuentran asignadas a tecnicos.", ln=True)

    df_asig = df_detalle[~mask_sin_tec].copy()

    if not df_asig.empty:
        pdf.add_page() 
        pdf.seccion_titulo("LISTADO GENERAL DETALLADO: ORDENES EN RUTA (ASIGNADAS)")
        
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        
        pdf.cell(15, 6, "Orden", border=1, align="C", fill=True)
        pdf.cell(20, 6, "Cliente", border=1, align="C", fill=True)
        pdf.cell(50, 6, "Actividad", border=1, align="C", fill=True)
        pdf.cell(55, 6, "Colonia", border=1, align="C", fill=True)
        pdf.cell(40, 6, "Tecnico", border=1, align="C", fill=True)
        pdf.cell(10, 6, "Dias", border=1, align="C", fill=True)
        pdf.ln()
        
        if 'DIAS_RETRASO' not in df_asig.columns:
            df_asig['DIAS_RETRASO'] = 0
        df_asig['DIAS_RETRASO'] = pd.to_numeric(df_asig['DIAS_RETRASO'], errors='coerce').fillna(0).astype(int)
        df_asig = df_asig.sort_values(by=['DIAS_RETRASO', 'TECNICO'], ascending=[False, True])
        
        for _, row in df_asig.iterrows():
            if pdf.get_y() > 270:
                pdf.add_page()
                pdf.set_font("Helvetica", "B", 7)
                pdf.set_text_color(50, 50, 50)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(15, 6, "Orden", border=1, align="C", fill=True)
                pdf.cell(20, 6, "Cliente", border=1, align="C", fill=True)
                pdf.cell(50, 6, "Actividad", border=1, align="C", fill=True)
                pdf.cell(55, 6, "Colonia", border=1, align="C", fill=True)
                pdf.cell(40, 6, "Tecnico", border=1, align="C", fill=True)
                pdf.cell(10, 6, "Dias", border=1, align="C", fill=True)
                pdf.ln()
            
            dias_retraso_val = row['DIAS_RETRASO']
            dias_retraso_str = str(dias_retraso_val)
            
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(0, 0, 0)
            
            pdf.cell(15, 5, safestr(str(row.get('NUM', ''))), border=1, align="C")
            pdf.cell(20, 5, safestr(str(row.get('CLIENTE', ''))), border=1, align="C")
            pdf.cell(50, 5, safestr(str(row.get('ACTIVIDAD', '')))[:35], border=1, align="L")
            pdf.cell(55, 5, safestr(str(row.get('COLONIA', '')))[:40], border=1, align="L")
            pdf.cell(40, 5, safestr(str(row.get('TECNICO', '')))[:25], border=1, align="L")
            
            if dias_retraso_val >= 7:
                pdf.set_fill_color(211, 47, 47) 
                pdf.set_text_color(255, 255, 255)
            elif dias_retraso_val >= 4:
                pdf.set_fill_color(245, 124, 0) 
                pdf.set_text_color(255, 255, 255)
            elif dias_retraso_val >= 1:
                pdf.set_fill_color(251, 192, 45) 
                pdf.set_text_color(0, 0, 0)
            else:
                pdf.set_fill_color(56, 142, 60) 
                pdf.set_text_color(255, 255, 255)
                
            pdf.cell(10, 5, safestr(dias_retraso_str), border=1, align="C", fill=True)
            pdf.ln()
            
        pdf.set_text_color(0, 0, 0)

    return finalizar_pdf(pdf)

def generar_pdf_tiempos_muertos(df_dia, fecha_sel):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr(f"REPORTE DE EFICIENCIA OPERATIVA Y TIEMPO PERDIDO - {fecha_sel.strftime('%d/%m/%Y')}"), ln=True, align='C')
    pdf.ln(5)
    
    df_valido = df_dia.dropna(subset=['HORA_INI', 'TECNICO']).copy()
    
    if df_valido.empty:
        pdf.set_font("Helvetica", '', 12)
        pdf.cell(0, 10, "No hay datos operativos para calcular tiempos.", ln=True, align='C')
        return finalizar_pdf(pdf)

    df_valido['HORA_INI'] = pd.to_datetime(df_valido['HORA_INI'])
    df_valido['HORA_LIQ'] = pd.to_datetime(df_valido['HORA_LIQ'])
    tecnicos = sorted(df_valido['TECNICO'].astype(str).unique())
    
    ahora_hx = get_honduras_time()
    inicio_jornada = pd.Timestamp.combine(fecha_sel, dt_time(8, 0))
    fin_jornada = pd.Timestamp.combine(fecha_sel, dt_time(17, 0))
    limite_evaluacion = min(ahora_hx, fin_jornada) if fecha_sel == ahora_hx.date() else fin_jornada
    
    for tec in tecnicos:
        df_tec = df_valido[df_valido['TECNICO'] == tec].sort_values(by='HORA_INI')
        
        pdf.set_font("Helvetica", 'B', 10)
        pdf.set_fill_color(220, 230, 250)
        pdf.cell(0, 8, safestr(f" TECNICO: {tec}"), border=1, ln=True, fill=True)
        
        pdf.set_font("Helvetica", 'B', 8)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(25, 6, "ORDEN", border=1, align='C', fill=True)
        pdf.cell(100, 6, "ACTIVIDAD", border=1, align='C', fill=True)
        pdf.cell(25, 6, "INICIO", border=1, align='C', fill=True)
        pdf.cell(25, 6, "FIN", border=1, align='C', fill=True)
        pdf.cell(25, 6, "DURACION", border=1, align='C', fill=True)
        pdf.ln()
        
        total_minutos_trabajados = 0
        tiempo_muerto_acumulado = 0
        cursor_tiempo = inicio_jornada 
        
        pdf.set_font("Helvetica", '', 8)
        for _, row in df_tec.iterrows():
            num = str(row.get('NUM', 'N/D'))
            act = str(row.get('ACTIVIDAD', ''))[:55]
            
            h_ini_dt = row['HORA_INI']
            h_liq_dt = row['HORA_LIQ']
            
            h_ini_str = h_ini_dt.strftime('%H:%M') if pd.notnull(h_ini_dt) else "N/D"
            h_fin_str = h_liq_dt.strftime('%H:%M') if pd.notnull(h_liq_dt) else "En curso"
            
            duracion_str = "---"
            if pd.notnull(h_ini_dt):
                if pd.notnull(h_liq_dt): fin_real = h_liq_dt
                else: fin_real = ahora_hx if h_ini_dt.date() == ahora_hx.date() else fin_jornada
                    
                if fin_real > h_ini_dt:
                    mins_reales = (fin_real - h_ini_dt).total_seconds() / 60
                    if mins_reales > 0:
                        total_minutos_trabajados += mins_reales
                        hrs_d, mins_d = divmod(mins_reales, 60)
                        duracion_str = f"{int(hrs_d)}h {int(mins_d)}m"

                if h_ini_dt > cursor_tiempo and cursor_tiempo < limite_evaluacion:
                    gap_end = min(h_ini_dt, limite_evaluacion)
                    gap_mins = (gap_end - cursor_tiempo).total_seconds() / 60
                    if gap_mins > 0: tiempo_muerto_acumulado += gap_mins
                
                fin_orden_gap = h_liq_dt if pd.notnull(h_liq_dt) else ahora_hx
                if pd.notnull(fin_orden_gap): cursor_tiempo = max(cursor_tiempo, fin_orden_gap)

            pdf.cell(25, 6, safestr(num), border=1, align='C')
            pdf.cell(100, 6, safestr(act), border=1)
            pdf.cell(25, 6, safestr(h_ini_str), border=1, align='C')
            pdf.cell(25, 6, safestr(h_fin_str), border=1, align='C')
            pdf.cell(25, 6, safestr(duracion_str), border=1, align='C')
            pdf.ln()
            
        if cursor_tiempo < limite_evaluacion:
            gap_mins = (limite_evaluacion - cursor_tiempo).total_seconds() / 60
            if gap_mins > 0: tiempo_muerto_acumulado += gap_mins
        
        tiempo_perdido_mins = max(0, tiempo_muerto_acumulado - 60)
        hrs_t, mins_t = divmod(total_minutos_trabajados, 60)
        hrs_p, mins_p = divmod(tiempo_perdido_mins, 60)
        
        pdf.set_font("Helvetica", 'B', 8)
        pdf.cell(175, 6, "TOTAL TIEMPO TRABAJADO EN ORDENES (Incluye Extras):", border=1, align='R')
        pdf.set_text_color(0, 100, 0)
        pdf.cell(25, 6, safestr(f"{int(hrs_t)}h {int(mins_t)}m"), border=1, align='C')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()
        
        pdf.cell(175, 6, "TIEMPO PERDIDO / MUERTO (Base Brechas 8am-5pm - Almuerzo):", border=1, align='R')
        if tiempo_perdido_mins > 0: pdf.set_text_color(200, 0, 0)
        pdf.cell(25, 6, safestr(f"{int(hrs_p)}h {int(mins_p)}m"), border=1, align='C')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()
        pdf.ln(5)

    return finalizar_pdf(pdf)

def generar_pdf_promedio_arranque(df_promedios, f_inicio, f_fin):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("PROMEDIO DE ARRANQUE DE JORNADA"), ln=True, align='C')
    
    pdf.set_font("Helvetica", '', 10)
    pdf.set_text_color(100, 100, 100)
    inicio_str = f_inicio.strftime('%d/%m/%Y') if hasattr(f_inicio, 'strftime') else str(f_inicio)
    fin_str = f_fin.strftime('%d/%m/%Y') if hasattr(f_fin, 'strftime') else str(f_fin)
    pdf.cell(0, 6, safestr(f"Periodo: {inicio_str} al {fin_str}"), ln=True, align='C')
    pdf.ln(10)
    
    if not df_promedios.empty:
        pdf.set_x(15)
        pdf.set_fill_color(220, 230, 250)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", 'B', 9)
        pdf.cell(90, 8, "TECNICO", border=1, align='C', fill=True)
        pdf.cell(40, 8, "DIAS EVALUADOS", border=1, align='C', fill=True)
        pdf.cell(50, 8, "HORA PROMEDIO", border=1, align='C', fill=True)
        pdf.ln()
        
        pdf.set_font("Helvetica", '', 9)
        for _, row in df_promedios.iterrows():
            pdf.set_x(15)
            tec = str(row['TECNICO'])[:45]
            dias = str(row['Dias_Computados'])
            hora = str(row['Hora_Promedio_Inicio'])
            
            pdf.cell(90, 7, safestr(tec), border=1, align='L')
            pdf.cell(40, 7, safestr(dias), border=1, align='C')
            pdf.cell(50, 7, safestr(hora), border=1, align='C')
            pdf.ln()
            
    return finalizar_pdf(pdf)

def generar_pdf_evaluacion(df, fecha_inicio, fecha_fin):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", 'B', 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE DE PRODUCCION Y PUNTOS POR TECNICO"), ln=True, align='C')
    
    pdf.set_font("Helvetica", '', 10)
    pdf.set_text_color(100, 100, 100)
    f_ini = fecha_inicio.strftime('%d/%m/%Y') if hasattr(fecha_inicio, 'strftime') else str(fecha_inicio)
    f_fin = fecha_fin.strftime('%d/%m/%Y') if hasattr(fecha_fin, 'strftime') else str(fecha_fin)
    f_emision = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 6, safestr(f"Periodo de Evaluacion: {f_ini} al {f_fin}"), ln=True, align='C')
    pdf.cell(0, 6, safestr(f"Fecha de Emision: {f_emision}"), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Helvetica", 'B', 9)
    pdf.set_fill_color(230, 235, 245)
    pdf.set_text_color(0, 0, 0)
    
    w = [65, 30, 35, 40, 40, 40]
    headers = ['Nombre del Tecnico', 'TOTAL PUNTOS', 'INSFIBRA (2.5)', 'Traslados (2.5)', 'Cambio Fibra (2.0)', 'SOP Normal (1.0)']
    
    for i in range(len(headers)):
        pdf.cell(w[i], 8, safestr(headers[i]), border=1, align='C', fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 8)
    for _, row in df.iterrows():
        tec = str(row['👨‍🔧 Técnico'])
        pdf.cell(w[0], 6, safestr(f" {tec[:35]}"), border=1)
        pdf.set_font("Helvetica", 'B', 9)
        pdf.cell(w[1], 6, safestr(row['⭐ TOTAL PUNTOS']), border=1, align='C')
        pdf.set_font("Helvetica", '', 8)
        pdf.cell(w[2], 6, safestr(row['🏠 INSFIBRA (2.5)']), border=1, align='C')
        pdf.cell(w[3], 6, safestr(row['🚚 TRASLADOS (2.5)']), border=1, align='C')
        pdf.cell(w[4], 6, safestr(row['🧵 CAMBIO FIBRA (2.0)']), border=1, align='C')
        pdf.cell(w[5], 6, safestr(row['🔧 SOP NORMAL (1.0)']), border=1, align='C')
        pdf.ln()

    return finalizar_pdf(pdf)

def generar_pdf_unificado_rrhh(df_ausencias, df_tardanzas):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 12, safestr("REPORTE UNIFICADO RRHH: CONTROL DE ASISTENCIA"), ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Fecha de emision: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}"), ln=True, align="C")
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
    
    return finalizar_pdf(pdf)

def generar_pdf_infracciones(df_res):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(277, 10, safestr("Resumen Consolidado de Infracciones Biometricas"), ln=True, align='C')
    pdf.set_font("Helvetica", 'I', 10)
    pdf.cell(277, 6, safestr(f"Generado el: {datetime.now().strftime('%d/%m/%Y')}"), ln=True, align='C')
    pdf.ln(10)

    df_res['Es_Tarde'] = df_res['Tardanza'] == 'Sí'
    df_res['Tiene_Exc_Alm'] = df_res['Almuerzo (min)'] > 60
    df_res['Tiene_Exc_Brk'] = df_res['Break (min)'] > 15

    resumen = df_res.groupby(['ID', 'Empleado']).agg(
        Tardanzas=('Es_Tarde', 'sum'),
        Suma_Tar=('Exceso_Tardanza_min', 'sum'),
        Almuerzos=('Tiene_Exc_Alm', 'sum'),
        Suma_Alm=('Exceso_Alm_min', 'sum'),
        Breaks=('Tiene_Exc_Brk', 'sum'),
        Suma_Brk=('Exceso_Brk_min', 'sum')
    ).reset_index()

    resumen['Total_Faltas'] = resumen['Tardanzas'] + resumen['Almuerzos'] + resumen['Breaks']
    infractores = resumen[resumen['Total_Faltas'] > 0].sort_values(by='Total_Faltas', ascending=False)

    if infractores.empty:
        pdf.set_font("Helvetica", '', 12)
        pdf.cell(277, 10, safestr("Excelente: No se registraron infracciones en este periodo."), ln=True, align='C')
        return finalizar_pdf(pdf)

    pdf.set_font("Helvetica", 'B', 8)
    pdf.set_fill_color(220, 230, 241) 
    
    w_id, w_emp, w_tar, w_ptar, w_alm, w_palm, w_brk, w_pbrk, w_tot = 15, 60, 22, 28, 25, 33, 25, 33, 25
    
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

    pdf.set_font("Helvetica", '', 8)
    for _, row in infractores.iterrows():
        nombre_corto = str(row['Empleado'])[:35]
        p_tar = f"{int(row['Suma_Tar'] / row['Tardanzas'])} min" if row['Tardanzas'] > 0 else "---"
        p_alm = f"{int(row['Suma_Alm'] / row['Almuerzos'])} min" if row['Almuerzos'] > 0 else "---"
        p_brk = f"{int(row['Suma_Brk'] / row['Breaks'])} min" if row['Breaks'] > 0 else "---"
        
        pdf.cell(w_id, 8, safestr(row['ID']), border=1, align='C')
        pdf.cell(w_emp, 8, safestr(f" {nombre_corto}"), border=1)
        pdf.cell(w_tar, 8, str(int(row['Tardanzas'])), border=1, align='C')
        pdf.cell(w_ptar, 8, safestr(p_tar), border=1, align='C')
        pdf.cell(w_alm, 8, str(int(row['Almuerzos'])), border=1, align='C')
        pdf.cell(w_palm, 8, safestr(p_alm), border=1, align='C')
        pdf.cell(w_brk, 8, str(int(row['Breaks'])), border=1, align='C')
        pdf.cell(w_pbrk, 8, safestr(p_brk), border=1, align='C')
        
        pdf.set_font("Helvetica", 'B', 9)
        pdf.cell(w_tot, 8, str(int(row['Total_Faltas'])), border=1, align='C')
        pdf.set_font("Helvetica", '', 8)
        pdf.ln()

    return finalizar_pdf(pdf)

# ==============================================================================
# 5. UTILIDADES Y PROCESAMIENTO GENERAL
# ==============================================================================
def es_offline_preciso(comentario):
    txt = str(comentario).upper().strip()
    if not txt or txt == 'NAN': return False
    jergasolucion = ['OK', 'LISTO', 'RECUPERADO', 'SOLUCIONADO', 'NAVEGA', 'YA QUEDO', 'ARRIBA', 'FUNCIONAL', 'ONLINE']
    if any(word in txt for word in jergasolucion): return False
    # CORRECCIÓN: Dejamos estrictamente términos de equipo caído
    keywordsfalla = ['OFFLINE', 'OFF LINE', 'LOS RED', 'PON ROJO', 'LOS EN ROJO', 'EQUIPO OFFLINE', 'ONU OFFLINE', 'ONT OFFLINE']
    return any(word in txt for word in keywordsfalla)

def depurar_archivos_en_crudo(fileactividades, filedispositivos):
    try:
        xlact = pd.ExcelFile(fileactividades, engine='openpyxl')
        sheetp = 'Prueba' if 'Prueba' in xlact.sheet_names else xlact.sheet_names[0]
        dfpraw = pd.read_excel(xlact, sheet_name=sheetp)
        sheethnom = 'HistoricoNoInstaladas' if 'HistoricoNoInstaladas' in xlact.sheet_names else None
        dfhraw = pd.read_excel(xlact, sheet_name=sheethnom) if sheethnom else pd.DataFrame()
        if filedispositivos.name.lower().endswith('.csv'):
            dfdispfull = pd.read_csv(filedispositivos, sep=None, engine='python')
        else:
            dfdispfull = pd.read_excel(filedispositivos, engine='openpyxl')
        dfdispref = pd.DataFrame()
        coltec = [c for c in dfdispfull.columns if any(x in str(c).upper() for x in['TECNICO', 'USER', 'OPERADOR'])]
        colmx = [c for c in dfdispfull.columns if any(x in str(c).upper() for x in['MX', 'VEHICULO', 'PLACA'])]
        dfdispref['TECREF'] = dfdispfull[coltec[0]].astype(str).str.strip().str.upper() if coltec else "N/D"
        dfdispref['MXREF'] = dfdispfull[colmx[0]].astype(str).str.strip() if colmx else "N/D"
        dfp = procesar_dataframe_base(dfpraw)
        dfp['TECKEY'] = dfp['TECNICO'].astype(str).str.strip().str.upper()
        dffinal = dfp.merge(dfdispref.drop_duplicates('TECREF'), left_on='TECKEY', right_on='TECREF', how='left')
        if 'MXREF' in dffinal.columns:
            dffinal['MX'] = dffinal['MXREF'].combine_first(dffinal.get('MX', pd.Series(dtype=str)))
        return dffinal.drop(columns=['TECKEY', 'TECREF', 'MXREF'], errors='ignore'), procesar_dataframe_base(dfhraw)
    except Exception as e:
        raise Exception(f"Error en cruce: {str(e)}")

def procesar_dataframe_base(df):
    df.columns = df.columns.astype(str).str.strip()
    mapeocolumnas = {}
    for nombreinterno, listaopciones in COLUMNS_MAPPING.items():
        for opcion in listaopciones:
            if opcion.upper() in [str(c).upper() for c in df.columns]:
                realname = next(c for c in df.columns if str(c).upper() == opcion.upper())
                mapeocolumnas[realname] = nombreinterno
                break
    df = df.rename(columns=mapeocolumnas)
    for colv in COLUMNAS_VITALES_SISTEMA:
        if colv not in df.columns: df[colv] = "N/D"
    for cstr in ['ESTADO', 'ACTIVIDAD', 'COMENTARIO', 'CLIENTE', 'TECNICO']:
        df[cstr] = df[cstr].astype(str).replace(['nan', 'None'], 'N/D')
    return df

def generar_tablas_gerenciales(df_crudo):
    df = df_crudo.copy()
    df['HORA_INI'] = df['HORA_INI'].apply(parse_date_ultra_safe)
    df['HORA_LIQ'] = df['HORA_LIQ'].apply(parse_date_ultra_safe)
    df = df.dropna(subset=['HORA_INI', 'HORA_LIQ'])
    df['FECHA'] = df['HORA_LIQ'].dt.date
    totales_tec = df.groupby('TECNICO').size().reset_index(name='Total_Tecnico')
    conteo_act = df.groupby(['TECNICO', 'ACTIVIDAD']).size().reset_index(name='Cantidad')
    tabla_produccion = pd.merge(conteo_act, totales_tec, on='TECNICO')
    tabla_produccion['Participacion_%'] = (tabla_produccion['Cantidad'] / tabla_produccion['Total_Tecnico'] * 100).round(1)

    df['MINUTOS'] = (df['HORA_LIQ'] - df['HORA_INI']).dt.total_seconds() / 60
    df.loc[df['MINUTOS'] <= 0, 'MINUTOS'] = None 
    tabla_eficiencia = df.groupby(['TECNICO', 'ACTIVIDAD'])['MINUTOS'].mean().reset_index()
    tabla_eficiencia.columns = ['TECNICO', 'ACTIVIDAD', 'Promedio_Minutos']
    tabla_eficiencia['Promedio_Minutos'] = tabla_eficiencia['Promedio_Minutos'].round(1)

    jornada = df.groupby(['TECNICO', 'FECHA']).agg(Hora_Apertura=('HORA_INI', 'min'), Hora_Cierre=('HORA_LIQ', 'max'), Total_Ordenes=('NUM', 'count')).reset_index()
    jornada['Horas_En_Calle'] = (jornada['Hora_Cierre'] - jornada['Hora_Apertura']).dt.total_seconds() / 3600
    jornada.loc[jornada['Horas_En_Calle'] <= 0, 'Horas_En_Calle'] = None

    resumen_jornada = jornada.groupby('TECNICO').agg(Promedio_Horas_Dia=('Horas_En_Calle', 'mean'), Dias_Laborados=('FECHA', 'nunique'), Max_Horas_Dia=('Horas_En_Calle', 'max')).reset_index()
    resumen_jornada['Promedio_Horas_Dia'] = resumen_jornada['Promedio_Horas_Dia'].round(2)
    resumen_jornada['Max_Horas_Dia'] = resumen_jornada['Max_Horas_Dia'].round(2)

    return tabla_produccion, tabla_eficiencia, resumen_jornada

def cargar_y_limpiar_crudos_diamante_monitor(file_activ, file_dispos):
    try:
        if isinstance(file_dispos, bytes):
            file_dispos_obj = io.BytesIO(file_dispos)
            file_dispos_obj.name = "FttxActiveDevice_cached.xlsx"
        elif hasattr(file_dispos, 'read'): file_dispos.seek(0); file_dispos_obj = file_dispos
        else: file_dispos_obj = file_dispos

        if hasattr(file_activ, 'read'): file_activ.seek(0)
        df_act, df_hst = depurar_archivos_en_crudo(file_activ, file_dispos_obj)
        df_act = procesar_fechas_seguro(df_act, ['HORA_INI', 'HORA_LIQ', 'FECHA_APE'])
        ahora_momento_ts = pd.Timestamp(get_honduras_time())
        fecha_limite_7d_ventana = ahora_momento_ts - timedelta(days=7) 
        mask_vivas_loc = df_act['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        df_act = df_act[(df_act['HORA_LIQ'] >= fecha_limite_7d_ventana) | (df_act['FECHA_APE'] >= fecha_limite_7d_ventana) | (df_act['HORA_LIQ'].isna()) | mask_vivas_loc].copy()
        
        df_act['DIAS_RETRASO'] = (ahora_momento_ts.normalize() - df_act['FECHA_APE'].dt.normalize()).dt.days.fillna(0).astype(int)
        df_act.loc[df_act['TECNICO'].str.strip().str.upper() == 'JOSUE MIGUEL SAUCEDA', 'DIAS_RETRASO'] = 0

        act_upper = df_act['ACTIVIDAD'].fillna('').astype(str).str.upper()
        est_upper = df_act['ESTADO'].fillna('').astype(str).str.upper().str.strip()
        tec_upper = df_act['TECNICO'].fillna('').astype(str).str.upper().str.strip()
        com_upper = df_act['COMENTARIO'].fillna('').astype(str).str.upper()
        cli_upper = df_act['CLIENTE'].fillna('').astype(str).str.upper()
        
        mins_diff = (ahora_momento_ts - df_act['HORA_INI']).dt.total_seconds() / 60
        mask_sop = act_upper.str.contains('SOPFIBRA', regex=True)
        mask_falsos = act_upper.str.contains('PLEXISCA|PEXTERNO|SPLITTEROPT|PLEX|INS|NUEVA|ADIC|CAMBIO|RECU|TVADICIONAL|MIGRACI', regex=True)

        df_act['ALERTA_TIEMPO'] = (
            (df_act['HORA_INI'].notnull()) & (df_act['HORA_LIQ'].isnull()) & 
            (mins_diff > 120) & (est_upper != 'CERRADA') & mask_sop & ~mask_falsos
        )
        
        mask_tec_valido = tec_upper != 'JOSUE MIGUEL SAUCEDA'
        mask_est_abierto = est_upper != 'CERRADA'
        mask_com_off = com_upper.str.contains("ONU OFFLINE|OFF LINE|OFFLINE|LOS EN ROJO|PON ROJO", regex=True)
        mask_precisa = com_upper.apply(es_offline_preciso) 
        
        df_act['ES_OFFLINE'] = (mask_tec_valido & mask_est_abierto & mask_sop & ~mask_falsos & (mask_com_off | mask_precisa))
        df_act['MINUTOS_CALC'] = (df_act['HORA_LIQ'] - df_act['HORA_INI']).dt.total_seconds() / 60
        
        texto_seg = act_upper + " " + cli_upper + " " + com_upper
        df_act['SEGMENTO'] = np.where(texto_seg.str.contains('PLEX|PEXTERNO|SPLITTEROPT', regex=True), 'PLEX', 'RESIDENCIAL')
        
        diff_temp = df_act['HORA_LIQ'] - df_act['HORA_INI']
        df_act['TIEMPO_REAL'] = np.where(
            df_act['HORA_INI'].isnull() | df_act['HORA_LIQ'].isnull(),
            "---",
            (diff_temp.dt.total_seconds() // 3600).fillna(0).astype(int).astype(str) + "h " +
            ((diff_temp.dt.total_seconds() % 3600) // 60).fillna(0).astype(int).astype(str) + "m"
        )
        
        return df_act, df_hst
    except Exception as e:
        if st: st.error(f"❌ Error fatal en el motor de depuración: {e}")
        return None, None

# ==============================================================================
# 6. UTILIDADES Y PROCESAMIENTO: AUDITORIA DE VEHICULOS
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
            if st: st.error("Falta librería xlrd para Excel antiguo.")
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
        
        df['_I'] = df['_I'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        df['_S'] = df['_S'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        
        df['_I'] = pd.to_datetime(df['_I'], format='mixed', dayfirst=True, errors='coerce')
        df['_S'] = pd.to_datetime(df['_S'], format='mixed', dayfirst=True, errors='coerce')
        
        df['Fecha'] = df['_I'].dt.date.fillna(df['_S'].dt.date)
        df = df.dropna(subset=['Fecha'])
        
        if df.empty: return None, None, "No hay fechas válidas en el archivo.", None, None
        
        fecha_maxima = df['Fecha'].max()
        if pd.notnull(fecha_maxima):
            fecha_minima_valida = fecha_maxima - timedelta(days=7)
            df = df[df['Fecha'] > fecha_minima_valida].copy()

        f_inicio = df['Fecha'].min()
        f_fin = df['Fecha'].max()

        diario = df.groupby(['_P', 'Fecha']).agg(P_S=('_S', 'min'), U_E=('_I', 'max')).reset_index()
        
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
                if diff > 3600: return int(diff - 3600)
                return int(diff)
            return 0

        diario['segundos'] = diario.apply(calc_segs, axis=1)
        
        semanal = diario.groupby('_P').agg(
            Dias_Laborados=('Fecha', 'nunique'),
            Total_Segundos=('segundos', 'sum')
        ).reset_index()

        semanal['Total_Segundos'] = semanal['Total_Segundos'].fillna(0).astype(int)

        dias_reales = diario[diario['segundos'] > 0].groupby('_P').size().reset_index(name='Dias_Efectivos')
        semanal = pd.merge(semanal, dias_reales, on='_P', how='left')
        semanal['Dias_Efectivos'] = semanal['Dias_Efectivos'].fillna(semanal['Dias_Laborados'])
        
        semanal['Prom_Segundos'] = 0
        mask_efectivos = semanal['Dias_Efectivos'] > 0
        
        semanal.loc[mask_efectivos, 'Prom_Segundos'] = (semanal.loc[mask_efectivos, 'Total_Segundos'] / semanal.loc[mask_efectivos, 'Dias_Efectivos']).astype(int)
        semanal['Prom_Segundos'] = semanal['Prom_Segundos'].fillna(0).astype(int)

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
            
            if row['Tiempo Diario'] == "00:00:00": pdf.set_text_color(180, 180, 180)
            pdf.cell(w[4], 6, safestr(row['Tiempo Diario']), border=1, align="C", fill=fill)
            pdf.set_text_color(0, 0, 0)
            
            if tec_display != "": pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w[5], 6, dias, border=1, align="C", fill=fill)
            pdf.cell(w[6], 6, t_sem, border=1, align="C", fill=fill)
            
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
def cargar_catalogo_tecnicos():
    """Lee y clasifica el archivo personal_tecnico.txt según reglas de MaxCom."""
    path = "personal_tecnico.txt"
    datos = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for linea in f:
                linea = linea.strip()
                if not linea: continue
                
                # Separar por coma
                partes = linea.split(',')
                
                # El nombre está en la primera parte, reemplazamos tabs por espacios y limpiamos dobles espacios
                nombre_bruto = partes[0].replace('\t', ' ')
                nombre = ' '.join(nombre_bruto.split()).upper()
                
                if len(partes) > 1:
                    cargo_area = partes[1].strip().upper()
                else:
                    cargo_area = "N/D"
                    
                estatus = "ACTIVO"
                if len(partes) > 2 and "VACACIONES" in partes[2].upper():
                    estatus = "VACACIONES"
                
                # Regla del usuario: Clasificación de Técnico Principal
                if cargo_area in ['PLEX', 'HFC', 'FTTH']:
                    clasificacion = "TÉCNICO PRINCIPAL"
                elif 'AYUDANTE' in cargo_area:
                    clasificacion = "AYUDANTE"
                elif 'SUPERVISOR' in cargo_area:
                    clasificacion = "SUPERVISOR"
                else:
                    clasificacion = "OTRAS ÁREAS / SOPORTE"
                    
                datos.append({
                    'Nombre': nombre,
                    'Cargo/Área': cargo_area,
                    'Clasificación': clasificacion,
                    'Estatus': estatus
                })
    return pd.DataFrame(datos)

def procesar_asistencia_vs_catalogo(df_biometrico, df_catalogo):
    """Cruza marcaciones biométricas contra el catálogo maestro de personal agrupando por áreas."""
    import unicodedata

    def limpiar_para_cruce(texto):
        """Quita tildes, dobles espacios y pasa a mayúsculas para un cruce perfecto."""
        if pd.isnull(texto): return ""
        t = str(texto).upper()
        t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
        return ' '.join(t.split())

    if df_catalogo.empty:
        return pd.DataFrame()
        
    df_cat = df_catalogo.copy()
    
    # Clasificador automático de Áreas (Plex, Residencial, Otras)
    def categorizar_grupo(area):
        a = str(area).upper()
        if 'PLEX' in a: return 'PLEX'
        elif 'FTTH' in a or 'HFC' in a: return 'RESIDENCIAL'
        else: return 'OTRAS ÁREAS'
        
    df_cat['Grupo_Tabla'] = df_cat['Cargo/Área'].apply(categorizar_grupo)
    
    # Si no hay biométrico cargado aún
    if df_biometrico.empty:
        df_cat['Asistencia'] = df_cat['Estatus'].apply(lambda x: '🌴 VACACIONES' if x == 'VACACIONES' else '❌ NO MARCÓ')
        df_cat['Entrada'] = "---"
        return df_cat[['Nombre', 'Clasificación', 'Cargo/Área', 'Asistencia', 'Entrada', 'Grupo_Tabla']]

    df_bio = df_biometrico.copy()
    
    df_cat['KEY_CRUCE'] = df_cat['Nombre'].apply(limpiar_para_cruce)
    df_bio['KEY_CRUCE'] = df_bio['Empleado'].apply(limpiar_para_cruce)
    
    resultado = pd.merge(df_cat, df_bio, on='KEY_CRUCE', how='left')
    
    def determinar_asistencia(row):
        if row['Estatus'] == 'VACACIONES': return '🌴 VACACIONES'
        if pd.notnull(row.get('Entrada')) and row['Entrada'] != "---" and str(row['Entrada']).strip() != "": 
            return '✅ MARCÓ'
        return '❌ NO MARCÓ'
        
    resultado['Asistencia'] = resultado.apply(determinar_asistencia, axis=1)
    resultado['Entrada'] = resultado['Entrada'].fillna("---")
    
    # Retornamos solo Entrada, Clasificación y el Grupo_Tabla invisible
    return resultado[['Nombre', 'Clasificación', 'Cargo/Área', 'Asistencia', 'Entrada', 'Grupo_Tabla']]
