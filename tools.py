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
import io
from google.cloud import storage
from google.oauth2 import service_account

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

    # =========================================================================
    # 🏢 FILTRO POR EMPRESA: Solo procesar registros de ISCA
    # Descarta cualquier registro de otra empresa (ej. Cable Color) que venga
    # mezclado en el archivo crudo o en el histórico de GCS.
    # =========================================================================
    if 'EMPRESA' in df.columns:
        mask_isca = df['EMPRESA'].astype(str).str.strip().str.upper().str.contains('ISCA', na=False)
        df = df[mask_isca].copy()

    for colv in COLUMNAS_VITALES_SISTEMA:
        if colv not in df.columns: df[colv] = "N/D"
        
    for cstr in ['ESTADO', 'ACTIVIDAD', 'COMENTARIO', 'CLIENTE', 'TECNICO']:
        df[cstr] = df[cstr].astype(str).replace(['nan', 'None'], 'N/D')
        
    # =========================================================================
    # 🧹 NUEVO: DEPURACIÓN RADICAL DESDE LA LECTURA DEL EXCEL
    # Elimina ACTUALIZARDATOSTECNICOS y otras basuras antes de que toquen la nube
    # =========================================================================
    if 'ACTIVIDAD' in df.columns:
        actividades_basura = [
            'ACTUALIZARDATOSTECNICOS', 
            'ACTUALIZACIONDATOS', 
            'ACTUALIZACIOFW', 
            'ACTUALIZAINFOTECNICA', 
            'ACTUALIZARSENSOR'
        ]
        # Filtramos buscando coincidencias exactas o parciales para mayor seguridad
        mask_basura = df['ACTIVIDAD'].astype(str).str.strip().str.upper().isin(actividades_basura)
        df = df[~mask_basura].copy()
        
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
        
        # 1. Búsqueda inteligente de columnas
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
        
        col_fecha = next((c for c in df.columns if re.search(r'(?i)^FECHA', str(c).strip())), None)
        
        if not (col_placa and col_ingreso and col_salida): 
            return None, None, "Columnas no detectadas.", None, None
            
        df = df.rename(columns={col_placa: '_P', col_ingreso: '_I', col_salida: '_S'})
        df['_P'] = df['_P'].astype(str).str.strip()
        df = df[~df['_P'].isin(['nan', '--', 'None', '', 'Columna'])]
        
        # 2. Limpieza de strings AM/PM
        raw_I = df['_I'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        raw_S = df['_S'].astype(str).str.replace(r'a\.?\s*m\.?', 'AM', flags=re.I).str.replace(r'p\.?\s*m\.?', 'PM', flags=re.I).str.strip()
        
        # 3. PARSEO INTELIGENTE DE FECHAS (La cura al bug de los meses/días invertidos)
        dt_I_eu = pd.to_datetime(raw_I, format='mixed', dayfirst=True, errors='coerce')
        dt_I_us = pd.to_datetime(raw_I, format='mixed', dayfirst=False, errors='coerce')
        
        # Si el parseo Europeo (DD/MM) distribuye las fechas en meses distintos (> 20 días)
        # pero el US (MM/DD) las mantiene juntitas en la misma semana, entonces el GPS usó formato US.
        if pd.notnull(dt_I_eu.max()) and pd.notnull(dt_I_us.max()):
            if (dt_I_eu.max() - dt_I_eu.min()).days > 20 and (dt_I_us.max() - dt_I_us.min()).days <= 20:
                df['_I'] = dt_I_us
                df['_S'] = pd.to_datetime(raw_S, format='mixed', dayfirst=False, errors='coerce')
            else:
                df['_I'] = dt_I_eu
                df['_S'] = pd.to_datetime(raw_S, format='mixed', dayfirst=True, errors='coerce')
        else:
            df['_I'] = dt_I_eu
            df['_S'] = pd.to_datetime(raw_S, format='mixed', dayfirst=True, errors='coerce')

        # Si existe una columna FECHA explícita, la usamos para sobrescribir y proteger
        if col_fecha:
            dt_F_eu = pd.to_datetime(df[col_fecha], format='mixed', dayfirst=True, errors='coerce')
            dt_F_us = pd.to_datetime(df[col_fecha], format='mixed', dayfirst=False, errors='coerce')
            if pd.notnull(dt_F_eu.max()) and pd.notnull(dt_F_us.max()):
                if (dt_F_eu.max() - dt_F_eu.min()).days > 20 and (dt_F_us.max() - dt_F_us.min()).days <= 20:
                    df['_F_real'] = dt_F_us.dt.date
                else:
                    df['_F_real'] = dt_F_eu.dt.date
            else:
                df['_F_real'] = dt_F_eu.dt.date

            def fusionar_fecha_hora(f_real, dt_time_parsed):
                if pd.isnull(dt_time_parsed): return pd.NaT
                if pd.notnull(f_real): return pd.Timestamp.combine(f_real, dt_time_parsed.time())
                return dt_time_parsed

            df['_I'] = df.apply(lambda row: fusionar_fecha_hora(row.get('_F_real'), row['_I']), axis=1)
            df['_S'] = df.apply(lambda row: fusionar_fecha_hora(row.get('_F_real'), row['_S']), axis=1)
            df['Fecha'] = df.get('_F_real', df['_I'].dt.date).fillna(df['_I'].dt.date).fillna(df['_S'].dt.date)
        else:
            df['Fecha'] = df['_I'].dt.date.fillna(df['_S'].dt.date)
        
        df = df.dropna(subset=['Fecha'])
        if df.empty: return None, None, "No hay fechas válidas en el archivo.", None, None
        
        # --- ELIMINADO EL FILTRO ESTRICTO DE 7 DÍAS QUE BORRABA LA DATA ---
        f_inicio = df['Fecha'].min()
        f_fin = df['Fecha'].max()

        # 4. Agrupación por Vehículo Y Fecha
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

def procesar_auditoria_mensual(df_input):
    """
    Reutiliza el motor de 'procesar_auditoria_semanal' para obtener el desglose
    diario por vehículo, y luego consolida los resultados por MES (Año-Mes)
    en lugar de por semana. Devuelve:
      - final_diario: desglose diario por vehículo (con columna 'Mes')
      - final_mensual: consolidado por Mes y Vehículo (Días Trabajados, Tiempo Total, Promedio Diario)
      - msg, f_inicio, f_fin
    """
    try:
        final_diario, _final_semanal, msg, f_inicio, f_fin = procesar_auditoria_semanal(df_input)
        if final_diario is None:
            return None, None, msg, None, None

        diario = final_diario.copy()
        diario['Fecha'] = pd.to_datetime(diario['Fecha'], errors='coerce')
        diario = diario.dropna(subset=['Fecha'])
        if diario.empty:
            return None, None, "No hay fechas válidas para consolidar el mes.", None, None

        diario['Mes_Periodo'] = diario['Fecha'].dt.to_period('M')
        diario['Mes'] = diario['Fecha'].dt.strftime('%B %Y')

        diario['segundos'] = diario['Tiempo Diario'].apply(time_to_sec_robust)

        mensual = diario.groupby(['Vehículo / Placa', 'Mes_Periodo', 'Mes']).agg(
            Dias_Laborados=('Fecha', 'nunique'),
            Total_Segundos=('segundos', 'sum')
        ).reset_index()

        dias_reales = diario[diario['segundos'] > 0].groupby(['Vehículo / Placa', 'Mes_Periodo']).size().reset_index(name='Dias_Efectivos')
        mensual = pd.merge(mensual, dias_reales, on=['Vehículo / Placa', 'Mes_Periodo'], how='left')
        mensual['Dias_Efectivos'] = mensual['Dias_Efectivos'].fillna(mensual['Dias_Laborados'])

        mensual['Prom_Segundos'] = 0
        mask_efectivos = mensual['Dias_Efectivos'] > 0
        mensual.loc[mask_efectivos, 'Prom_Segundos'] = (
            mensual.loc[mask_efectivos, 'Total_Segundos'] / mensual.loc[mask_efectivos, 'Dias_Efectivos']
        ).astype(int)
        mensual['Prom_Segundos'] = mensual['Prom_Segundos'].fillna(0).astype(int)

        def format_segs(secs):
            if pd.isnull(secs) or secs <= 0: return "00:00:00"
            h, r = divmod(int(secs), 3600); m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        mensual['Tiempo Total Mes'] = mensual['Total_Segundos'].apply(format_segs)
        mensual['Promedio Diario'] = mensual['Prom_Segundos'].apply(format_segs)
        mensual = mensual.rename(columns={'Dias_Laborados': 'Días Trabajados'})
        mensual = mensual.sort_values(['Mes_Periodo', 'Vehículo / Placa'])

        final_mensual = mensual[['Mes', 'Vehículo / Placa', 'Días Trabajados', 'Tiempo Total Mes', 'Promedio Diario']].copy()
        final_diario_out = diario.sort_values(['Mes_Periodo', 'Vehículo / Placa', 'Fecha'])[
            ['Vehículo / Placa', 'Fecha', 'Primera Salida', 'Última Entrada', 'Tiempo Diario', 'Mes']
        ].copy()

        return forzar_columnas_unicas(final_diario_out), forzar_columnas_unicas(final_mensual), "OK", f_inicio, f_fin
    except Exception as e:
        return None, None, str(e), None, None

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

def generar_pdf_mensual_tiempos(df_diario, df_mensual, f_inicio, f_fin):
    pdf = ReporteGenerencialPDF(orientation='L', unit='mm', format='A4')
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(84, 98, 143)

    inicio_str = f_inicio.strftime('%d/%m/%Y') if hasattr(f_inicio, 'strftime') else str(f_inicio)
    fin_str = f_fin.strftime('%d/%m/%Y') if hasattr(f_fin, 'strftime') else str(f_fin)

    titulo = f" Auditoria Mensual Consolidada ({inicio_str} al {fin_str})"
    pdf.cell(0, 10, safestr(titulo), border=1, ln=True, fill=True, align="C")
    pdf.ln(5)

    if df_mensual is not None and not df_mensual.empty:
        # --- TABLA 1: RESUMEN CONSOLIDADO POR MES Y VEHICULO ---
        pdf.seccion_titulo("Resumen Consolidado por Mes y Vehiculo")

        w_res = [40, 95, 30, 45, 45]
        pdf.set_fill_color(210, 210, 215)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 8)

        headers_res = ['MES', 'VEHICULO / PLACA', 'DIAS TRAB.', 'TIEMPO TOTAL MES', 'PROMEDIO DIARIO']
        for i, h in enumerate(headers_res):
            pdf.cell(w_res[i], 8, safestr(h), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        last_mes = None
        for _, row in df_mensual.iterrows():
            mes_actual = row['Mes']
            mes_display = safestr(mes_actual) if mes_actual != last_mes else ""
            if mes_display: last_mes = mes_actual

            fill = mes_display != ""
            pdf.set_fill_color(240, 248, 255) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)

            if mes_display: pdf.set_font("Helvetica", "B", 8)
            pdf.cell(w_res[0], 6, mes_display.upper(), border=1, align="L", fill=fill)
            pdf.set_font("Helvetica", "", 8)

            pdf.cell(w_res[1], 6, safestr(row['Vehículo / Placa'])[:55], border=1, align="L", fill=fill)
            pdf.cell(w_res[2], 6, str(row['Días Trabajados']), border=1, align="C", fill=fill)
            pdf.cell(w_res[3], 6, safestr(row['Tiempo Total Mes']), border=1, align="C", fill=fill)

            pdf.set_text_color(0, 100, 0)
            pdf.cell(w_res[4], 6, safestr(row['Promedio Diario']), border=1, align="C", fill=fill)
            pdf.set_text_color(0, 0, 0)
            pdf.ln()

        # --- TABLA 2: DESGLOSE DIARIO COMPLETO ---
        if df_diario is not None and not df_diario.empty:
            pdf.add_page()
            pdf.seccion_titulo("Desglose Diario Detallado del Periodo")

            w_dia = [40, 70, 30, 28, 28, 30]
            pdf.set_fill_color(210, 210, 215)
            pdf.set_text_color(50, 50, 50)
            pdf.set_font("Helvetica", "B", 8)

            headers_dia = ['MES', 'VEHICULO / PLACA', 'FECHA', '1RA SALIDA', 'ULT ENTRADA', 'TIEMPO DIARIO']
            for i, h in enumerate(headers_dia):
                pdf.cell(w_dia[i], 8, safestr(h), border=1, align="C", fill=True)
            pdf.ln()

            pdf.set_font("Helvetica", "", 8)
            last_mes_d = None
            for _, row in df_diario.iterrows():
                mes_actual = row.get('Mes', '')
                mes_display = safestr(mes_actual) if mes_actual != last_mes_d else ""
                if mes_display: last_mes_d = mes_actual

                fecha_str = row['Fecha'].strftime('%d/%m/%Y') if hasattr(row['Fecha'], 'strftime') else str(row['Fecha'])

                fill = mes_display != ""
                pdf.set_fill_color(240, 248, 255) if fill else pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(0, 0, 0)

                if mes_display: pdf.set_font("Helvetica", "B", 8)
                pdf.cell(w_dia[0], 6, mes_display.upper(), border=1, align="L", fill=fill)
                pdf.set_font("Helvetica", "", 8)

                pdf.cell(w_dia[1], 6, safestr(row['Vehículo / Placa'])[:40], border=1, align="L", fill=fill)
                pdf.cell(w_dia[2], 6, fecha_str, border=1, align="C", fill=fill)
                pdf.cell(w_dia[3], 6, safestr(row['Primera Salida']), border=1, align="C", fill=fill)
                pdf.cell(w_dia[4], 6, safestr(row['Última Entrada']), border=1, align="C", fill=fill)

                if row['Tiempo Diario'] == "00:00:00": pdf.set_text_color(180, 180, 180)
                pdf.cell(w_dia[5], 6, safestr(row['Tiempo Diario']), border=1, align="C", fill=fill)
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

def generar_pdf_memorandum(row):
    import textwrap
    import requests
    import tempfile
    import os
    
    # --- DICCIONARIO INTERNO DE GRAVEDAD ---
    def clasificar_gravedad(motivo):
        m = str(motivo).upper().strip()
        faltas_graves = ["ABANDONO DE RUTA", "DAÑO A EQUIPO", "FUSIONADORA", "DAÑO AL VEH", "ÓRDENES PENDIENTES", "AUSENCIAS LABORALES"]
        if "LLEGADAS TARDES" in m and "GRAVE" not in m: return "LEVE"
        if any(g in m for g in faltas_graves) or "GRAVE" in m: return "GRAVE"
        return "OTRO"
    
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("MEMORANDUM: LLAMADO DE ATENCION"), border=0, ln=True, align="C")
    pdf.ln(5)
    
    motivo_original = str(row.get('TIPO_FALTA', ''))
    nivel_gravedad = clasificar_gravedad(motivo_original)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, "Para: Recursos Humanos / Gerencia", ln=True)
    pdf.cell(0, 6, safestr(f"Tecnico Implicado: {row.get('TECNICO', '')}"), ln=True)
    pdf.cell(0, 6, safestr(f"Fecha de Incidencia: {row.get('FECHA_INCIDENCIA', '')}"), ln=True)
    
    # --- AQUÍ INYECTAMOS LA GRAVEDAD VISUAL EN EL PDF INDIVIDUAL ---
    pdf.cell(0, 6, safestr(f"Tipo de Falta: {motivo_original} [{nivel_gravedad}]"), ln=True)
    pdf.ln(5)
    
    pdf.seccion_titulo("Detalle de los hechos:")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    
    comentario = str(row.get('COMENTARIO', ''))
    comentario_lineas = textwrap.wrap(comentario, width=100)
    for linea in comentario_lineas:
        pdf.cell(0, 5, safestr(linea), ln=True)
        
    pdf.ln(10)
    
    url_foto = str(row.get('URL_FOTO', ''))
    if url_foto.startswith('http'):
        pdf.seccion_titulo("Evidencia Fotografica / Captura de Pantalla:")
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url_foto, headers=headers, timeout=5)
            if response.status_code == 200:
                fd, tmppath = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                with open(tmppath, 'wb') as f:
                    f.write(response.content)
                
                if pdf.get_y() > 170:
                    pdf.add_page()
                    
                pdf.image(tmppath, x=15, w=180)
                os.remove(tmppath)
            else:
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 5, "(Nota: No se pudo descargar la evidencia grafica desde el servidor).", ln=True)
        except Exception as e:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, safestr(f"(Error al procesar imagen: {e})"), ln=True)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 5, "(No se adjunto evidencia grafica en este reporte).", ln=True)
        
    return finalizar_pdf(pdf)


def extraer_seguimientos_tecnico_unificado(df_base, tecnico_nombre):
    import re
    import pandas as pd
    from datetime import datetime, timedelta
    
    # 1. Obtener fecha actual en Honduras
    hoy_date = (datetime.utcnow() - timedelta(hours=6)).date()
    
    df_limpio = df_base.copy()
    col_tec = 'TÉCNICO' if 'TÉCNICO' in df_limpio.columns else 'TECNICO'
    if col_tec not in df_limpio.columns:
        return pd.DataFrame()
        
    tecnico_upper = str(tecnico_nombre).strip().upper()
    df_limpio[col_tec] = df_limpio[col_tec].fillna('').astype(str).str.strip().str.upper()
    
    # --- 2. FILTRAR LA BANDEJA DEL TÉCNICO (Abiertas + Cerradas Hoy) ---
    patron_vivas = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
    mask_vivas = df_limpio['ESTADO'].astype(str).str.contains(patron_vivas, na=False, case=False)
    
    col_liq = 'HORA_LIQ' if 'HORA_LIQ' in df_limpio.columns else 'FECHA LIQUIDADO'
    if col_liq in df_limpio.columns:
        df_limpio['_TEMP_LIQ'] = pd.to_datetime(df_limpio[col_liq], format='mixed', dayfirst=True, errors='coerce').dt.date
    else:
        df_limpio['_TEMP_LIQ'] = pd.NaT
        
    mask_cerradas_hoy = (df_limpio['ESTADO'].astype(str).str.upper() == 'CERRADA') & (df_limpio['_TEMP_LIQ'] == hoy_date)
    
    mask_tec = df_limpio[col_tec] == tecnico_upper
    
    df_bandeja = df_limpio[mask_tec & (mask_vivas | mask_cerradas_hoy)]
    ordenes_bandeja = set(df_bandeja['NUM'].dropna().astype(str).unique())
    mapa_estados = dict(zip(df_bandeja['NUM'].astype(str), df_bandeja['ESTADO'].astype(str).str.upper()))
    
    if not ordenes_bandeja:
        return pd.DataFrame()
        
    seguimientos = []
    patron = r'\*\s*(\d{2}[/-]\d{2}[/-]\d{4}\s+\d{2}:\d{2}:\d{2})\s+(.*?)\s+(agrego el comentario|agrego archivo):\s+(.*?)(?=\* \d{2}[/-]\d{2}[/-]\d{4}|$)'
    
    # Pre-calculamos las palabras del nombre del técnico (Ignorando DE, LA)
    tecnico_words = set(tecnico_upper.split())
    tecnico_words = {w for w in tecnico_words if len(w) > 2} 
    
    for _, row in df_base.iterrows():
        num_celda = str(row.get('NUM', '')).strip()
        
        texto_celda = str(row.get('COMENTARIO', '')) + " " + str(row.get('CONTRATO FÍSICO', row.get('CONTRATO_FISICO', '')))
        texto_celda = texto_celda.replace('\n', ' ').replace('\r', ' ')
        
        id_orden = "".join(filter(str.isdigit, num_celda)) if "SEGUIMIENTO" in num_celda.upper() else num_celda
        
        if id_orden in ordenes_bandeja:
            matches = re.findall(patron, texto_celda, re.IGNORECASE)
            for match in matches:
                fecha_hora = match[0].strip()
                autor = match[1].strip()
                tipo_accion = match[2].strip().lower()
                texto_crudo = match[3].strip()
                
                # --- NUEVO FILTRO DE IDENTIDAD (Bloqueo a Dispatch) ---
                autor_limpio = autor.upper().replace('.', ' ')
                autor_words = set(autor_limpio.split())
                autor_words = {w for w in autor_words if len(w) > 2}
                
                # Exigimos que al menos una palabra del usuario exista en el nombre oficial
                if len(tecnico_words.intersection(autor_words)) >= 1:
                    
                    if "archivo" in tipo_accion:
                        texto_final = f"📸 Archivo adjunto: {texto_crudo}"
                    else:
                        texto_final = texto_crudo

                    seguimientos.append({
                        'ORDEN': id_orden, 
                        'ESTADO_ACTUAL': mapa_estados.get(id_orden, 'DESCONOCIDO'),
                        'FECHA_HORA': fecha_hora, 
                        'AUTOR': autor, 
                        'COMENTARIO': texto_final
                    })

    df_seg = pd.DataFrame(seguimientos)
    
    if not df_seg.empty:
        df_seg = df_seg.drop_duplicates(subset=['FECHA_HORA', 'COMENTARIO'])
        df_seg['FECHA_DT'] = pd.to_datetime(df_seg['FECHA_HORA'], format='mixed', dayfirst=True, errors='coerce')
        
        ordenes_recientes = df_seg.groupby('ORDEN')['FECHA_DT'].max().sort_values(ascending=False)
        top_3_ordenes = ordenes_recientes.head(3).index.tolist()
        df_seg = df_seg[df_seg['ORDEN'].isin(top_3_ordenes)]
        
        df_final = df_seg.sort_values(by='FECHA_DT', ascending=False).drop(columns=['FECHA_DT'])
        return df_final
            
    return pd.DataFrame()

def verificar_y_alertar_vips(df_diario, lista_vips):
    """Cruza la base operativa con la lista VIP y dispara alertas SOLO si es Crítica u Offline."""
    if not lista_vips or df_diario.empty:
        return False, 0
        
    # Aseguramos que la columna CLIENTE sea texto limpio para comparar
    df_diario['CLIENTE_STR'] = df_diario['CLIENTE'].astype(str).str.strip()
    
    # 1. Filtrar primero los que pertenecen a la lista VIP
    vips_afectados = df_diario[df_diario['CLIENTE_STR'].isin(lista_vips)].copy()
    
    if vips_afectados.empty:
        return False, 0

    # 2. NUEVO FILTRO: Dejamos SOLO los que son Offline o tienen Alerta de Tiempo (Críticos)
    condicion_offline = vips_afectados.get('ES_OFFLINE', pd.Series([False]*len(vips_afectados))) == True
    condicion_tiempo = vips_afectados.get('ALERTA_TIEMPO', pd.Series([False]*len(vips_afectados))) == True
    
    vips_criticos = vips_afectados[condicion_offline | condicion_tiempo]
    
    if not vips_criticos.empty:
        if 'alertas_enviadas' not in st.session_state:
            st.session_state['alertas_enviadas'] = set()
            
        nuevas_alertas = 0
        for index, row in vips_criticos.iterrows():
            id_cliente = row['CLIENTE_STR']
            nombre = str(row.get('NOMBRE', 'VIP Desconocido'))
            actividad = str(row.get('ACTIVIDAD', 'ACTIVIDAD DESCONOCIDA'))
            ticket = str(row.get('NUM', 'Sin Ticket'))
            estado = str(row.get('ESTADO', 'N/D'))
            
            # Identificamos visualmente por qué se disparó la alerta
            tipo_alerta = "🔴 EQUIPO OFFLINE (CAÍDO)" if row.get('ES_OFFLINE') else "⚠️ ALERTA DE TIEMPO (>2 HORAS)"
            
            # Evitamos enviar alertas por órdenes que ya fueron cerradas o anuladas
            if estado.upper() in ['CERRADA', 'ANULADA']:
                continue
            
            # Llave única para no bombardear el WhatsApp si la página se recarga (incluye etiqueta de critico)
            llave_alerta = f"{ticket}_{id_cliente}_{estado}_critico"
            
            if llave_alerta not in st.session_state['alertas_enviadas']:
                mensaje = f"🚨 *EMERGENCIA VIP MAXCOM* 🚨\n\n"
                mensaje += f"⚠️ *URGENCIA:* {tipo_alerta}\n"
                mensaje += f"👤 *Cliente:* {nombre}\n"
                mensaje += f"🆔 *ID:* {id_cliente}\n"
                mensaje += f"🛠️ *Actividad:* {actividad}\n"
                mensaje += f"🎫 *Ticket:* {ticket}\n"
                mensaje += f"🚦 *Estado Actual:* {estado}\n\n"
                mensaje += f"Prioridad Máxima. Favor escalar de inmediato."
                
                enviar_whatsapp(mensaje)
                st.session_state['alertas_enviadas'].add(llave_alerta)
                nuevas_alertas += 1
                
        return (nuevas_alertas > 0), nuevas_alertas
    return False, 0


def generar_pdf_ordenes_totales(df_base, fecha_corte):
    """Genera un PDF con el listado de todas las órdenes PENDIENTES, ordenadas por retraso y con columna Colonia."""
    
    # --- 1. ORDENAMIENTO ---
    df_base['DIAS_RETRASO'] = pd.to_numeric(df_base['DIAS_RETRASO'], errors='coerce').fillna(0)
    df_base = df_base.sort_values(by='DIAS_RETRASO', ascending=False)
    
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE DE ORDENES TOTALES PENDIENTES"), border=0, ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Corte Operativo del Día: {fecha_corte.strftime('%d/%m/%Y')}"), ln=True, align="C")
    pdf.ln(5)
    
    pdf.seccion_titulo(f"Listado Total ({len(df_base)} Órdenes en Ruta / Sin Asignar)")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(50, 50, 50)
    pdf.set_font("Helvetica", "B", 7)
    
    # Anchos ajustados: Días(12), Orden(18), Cliente(20), Tecnico(40), Actividad(50), Colonia(50) = 190mm
    w = [12, 18, 20, 40, 50, 50] 
    
    # Encabezado
    pdf.cell(w[0], 6, "Días", border=1, align="C", fill=True)
    pdf.cell(w[1], 6, "Orden", border=1, align="C", fill=True)
    pdf.cell(w[2], 6, "Cliente", border=1, align="C", fill=True)
    pdf.cell(w[3], 6, "Tecnico", border=1, align="C", fill=True)
    pdf.cell(w[4], 6, "Actividad", border=1, align="C", fill=True)
    pdf.cell(w[5], 6, "Colonia", border=1, align="C", fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 6)
    
    for _, row in df_base.iterrows():
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(240, 240, 240)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(w[0], 6, "Días", border=1, align="C", fill=True)
            pdf.cell(w[1], 6, "Orden", border=1, align="C", fill=True)
            pdf.cell(w[2], 6, "Cliente", border=1, align="C", fill=True)
            pdf.cell(w[3], 6, "Tecnico", border=1, align="C", fill=True)
            pdf.cell(w[4], 6, "Actividad", border=1, align="C", fill=True)
            pdf.cell(w[5], 6, "Colonia", border=1, align="C", fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 6)

        # 1. Semáforo de Días
        dias_val = int(row.get('DIAS_RETRASO', 0))
        if dias_val >= 7:
            pdf.set_fill_color(211, 47, 47)   # Rojo
            pdf.set_text_color(255, 255, 255)
        elif 4 <= dias_val <= 6:
            pdf.set_fill_color(245, 124, 0)   # Naranja
            pdf.set_text_color(255, 255, 255)
        elif 1 <= dias_val <= 3:
            pdf.set_fill_color(251, 192, 45)  # Amarillo
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.set_fill_color(56, 142, 60)   # Verde
            pdf.set_text_color(255, 255, 255)

        pdf.set_font("Helvetica", "B", 6)
        pdf.cell(w[0], 5, str(dias_val), border=1, align="C", fill=True)

        # 2. Reset para el resto de la fila
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 6)
        
        # Datos
        num = safestr(str(row.get('NUM', 'N/D')))
        cliente = safestr(str(row.get('CLIENTE', 'N/D')))
        
        tec_raw = str(row.get('TECNICO', ''))
        tec = "SIN ASIGNAR" if pd.isna(tec_raw) or tec_raw.strip().upper() in ['NONE', 'NAN', 'N/D', 'NULL', ''] else safestr(tec_raw)[:25]
        
        act = safestr(str(row.get('ACTIVIDAD', 'N/D')))[:32]
        colonia = safestr(str(row.get('COLONIA', 'N/D')))[:35] # Obtenemos Colonia
        
        pdf.cell(w[1], 5, num, border=1, align="C")
        pdf.cell(w[2], 5, cliente, border=1, align="C")
        pdf.cell(w[3], 5, tec, border=1, align="L")
        pdf.cell(w[4], 5, act, border=1, align="L")
        pdf.cell(w[5], 5, colonia, border=1, align="L") # Imprimimos Colonia
        pdf.ln()
        
    return finalizar_pdf(pdf)


# ==============================================================================
# 7. MÓDULO DE PERSISTENCIA EN GOOGLE CLOUD STORAGE (NUEVO)
# ==============================================================================

def obtener_cliente_gcs_nativo():
    """Inicializa el cliente de GCS reciclando las credenciales de gsheets de Streamlit."""
    import streamlit as st
    creds_dict = st.secrets["connections"]["gsheets"]
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return storage.Client(credentials=creds, project=creds.project_id)

def sobrescribir_archivo_gcs(dataframe_o_bytes, nombre_bucket, nombre_archivo_destino):
    """
    Sube un DataFrame (como CSV) o un archivo binario directo a GCS.
    Si el archivo ya existe, GCS lo borra/sobrescribe automáticamente en el acto.
    """
    try:
        cliente = obtener_cliente_gcs_nativo()
        bucket = cliente.bucket(nombre_bucket)
        blob = bucket.blob(nombre_archivo_destino)
        
        # Detectar si es un DataFrame de Pandas (para el Historial Maestro)
        if isinstance(dataframe_o_bytes, pd.DataFrame):
            csv_en_ram = dataframe_o_bytes.to_csv(index=False)
            blob.upload_from_string(csv_en_ram, content_type="text/csv")
        # Detectar si son bytes puros (para guardar el archivo FTTX tal cual)
        elif isinstance(dataframe_o_bytes, bytes):
            blob.upload_from_string(dataframe_o_bytes, content_type="application/octet-stream")
        else:
            # Si es un objeto de archivo subido de Streamlit (UploadedFile)
            dataframe_o_bytes.seek(0)
            blob.upload_from_file(dataframe_o_bytes)
            
        return True
    except Exception as e:
        print(f"Error de persistencia en GCS: {e}")
        return False
        

def leer_espejo_gcs(nombre_bucket, nombre_archivo_destino):
    """
    Descarga el archivo desde GCS en memoria RAM y lo devuelve como un DataFrame de Pandas.
    """
    import io
    try:
        cliente = obtener_cliente_gcs_nativo()
        bucket = cliente.bucket(nombre_bucket)
        blob = bucket.blob(nombre_archivo_destino)
        
        if blob.exists():
            contenido = blob.download_as_bytes()
            return pd.read_csv(io.BytesIO(contenido))
        else:
            print(f"El archivo {nombre_archivo_destino} no existe en GCS.")
            return None
    except Exception as e:
        print(f"Error al leer desde GCS: {e}")
        return None
        
# ==============================================================================
# PROCESAMIENTO DE RENDIMIENTO INTEGRAL (ÓRDENES, GPS, EXPEDIENTES)
# ==============================================================================
def procesar_rendimiento_integral(df_act, df_gps, df_exp):
    import pandas as pd
    import re

    try:
        # 1. Procesar Actividades (Órdenes)
        col_tec = next((c for c in df_act.columns if 'TECNICO' in str(c).upper() or 'TÉCNICO' in str(c).upper()), None)
        col_ent = next((c for c in df_act.columns if 'ENTRADA' in str(c).upper() or 'INICIO' in str(c).upper()), None)
        col_liq = next((c for c in df_act.columns if 'LIQUIDADO' in str(c).upper() or 'CIERRE' in str(c).upper()), None)
        col_num = next((c for c in df_act.columns if 'NUM' in str(c).upper() or 'ORDEN' in str(c).upper()), None)

        if not col_tec or not col_ent or not col_liq:
            return None, "El archivo 'rep_actividades' no tiene las columnas requeridas (Técnico, Entrada, Liquidado)."

        df_act['TEC_KEY'] = df_act[col_tec].astype(str).str.upper().str.strip()
        df_act['FECHA_ENTRADA'] = pd.to_datetime(df_act[col_ent], errors='coerce', dayfirst=True)
        df_act['FECHA_LIQUIDADO'] = pd.to_datetime(df_act[col_liq], errors='coerce', dayfirst=True)
        
        # Calcular el tiempo invertido en cada orden en minutos
        df_act['Minutos_Orden'] = (df_act['FECHA_LIQUIDADO'] - df_act['FECHA_ENTRADA']).dt.total_seconds() / 60
        df_act['Minutos_Orden'] = df_act['Minutos_Orden'].apply(lambda x: x if x > 0 else 0)

        # Agrupar datos de productividad pura
        resumen_act = df_act.groupby('TEC_KEY').agg(
            Cantidad_Ordenes=(col_num, 'count'),
            Tiempo_Prom_Minutos=('Minutos_Orden', 'mean'),
            Primera_Orden=('FECHA_ENTRADA', 'min')
        ).reset_index()

        resumen_act['Primera_Orden'] = resumen_act['Primera_Orden'].dt.strftime('%H:%M:%S').fillna('--')
        resumen_act['Tiempo_Prom_Minutos'] = resumen_act['Tiempo_Prom_Minutos'].round(1)

        # 2. Procesar GPS (Zonas y Rutas para extraer salidas/entradas)
        if df_gps is not None and not df_gps.empty:
            col_placa = next((c for c in df_gps.columns if 'PLACA' in str(c).upper() or 'ALIAS' in str(c).upper()), None)
            col_h_in = next((c for c in df_gps.columns if 'HORA INGRESO' in str(c).upper() or 'LLEGADA' in str(c).upper()), None)
            col_h_out = next((c for c in df_gps.columns if 'HORA SALIDA' in str(c).upper() or 'SALIDA' in str(c).upper()), None)

            if col_placa and col_h_in and col_h_out:
                df_gps['Hora Ingreso'] = pd.to_datetime(df_gps[col_h_in], errors='coerce')
                df_gps['Hora Salida'] = pd.to_datetime(df_gps[col_h_out], errors='coerce')

                # Tomamos la primera hora de salida y la última hora de ingreso reportada en el día
                gps_res = df_gps.groupby(col_placa).agg(
                    Salida_Plantel=('Hora Salida', 'min'),
                    Entrada_Plantel=('Hora Ingreso', 'max')
                ).reset_index()

                # Función inteligente para cruzar el Alias del GPS con el nombre del Técnico
                def match_tec(placa_alias, tecnicos_list):
                    placa_alias = str(placa_alias).upper().replace(',', '').replace('.', '')
                    placa_alias = re.sub(r'MX-\d+', '', placa_alias) # Limpiar el MX-
                    best_match = None
                    max_coincidencias = 0
                    for tec in tecnicos_list:
                        partes_tec = str(tec).upper().split()
                        coincidencias = sum(1 for p in partes_tec if len(p) > 2 and p in placa_alias)
                        if coincidencias > max_coincidencias:
                            max_coincidencias = coincidencias
                            best_match = tec
                    return best_match if max_coincidencias >= 1 else None

                tecnicos_act = resumen_act['TEC_KEY'].unique()
                gps_res['TEC_KEY'] = gps_res[col_placa].apply(lambda x: match_tec(x, tecnicos_act))
                
                gps_res = gps_res.dropna(subset=['TEC_KEY'])
                gps_res = gps_res.groupby('TEC_KEY').agg({'Salida_Plantel':'min', 'Entrada_Plantel':'max'}).reset_index()
                
                gps_res['Salida_Plantel'] = gps_res['Salida_Plantel'].dt.strftime('%H:%M:%S').fillna('--')
                gps_res['Entrada_Plantel'] = gps_res['Entrada_Plantel'].dt.strftime('%H:%M:%S').fillna('--')

                resumen_final = pd.merge(resumen_act, gps_res, on='TEC_KEY', how='left')
            else:
                resumen_final = resumen_act.copy()
                resumen_final['Salida_Plantel'] = '--'
                resumen_final['Entrada_Plantel'] = '--'
        else:
            resumen_final = resumen_act.copy()
            resumen_final['Salida_Plantel'] = '--'
            resumen_final['Entrada_Plantel'] = '--'

        resumen_final.fillna({'Salida_Plantel': '--', 'Entrada_Plantel': '--'}, inplace=True)

        # 3. Procesar Expedientes (Faltas y Llamados de Atención en la Nube)
        if df_exp is not None and not df_exp.empty:
            col_tec_exp = next((c for c in df_exp.columns if 'TECNICO' in str(c).upper()), None)
            col_tipo = next((c for c in df_exp.columns if 'TIPO_FALTA' in str(c).upper() or 'FALTA' in str(c).upper()), None)
            
            if col_tec_exp and col_tipo:
                df_exp['TEC_KEY'] = df_exp[col_tec_exp].astype(str).str.upper().str.strip()
                
                # Separar Ausencias de Llamados de Atención
                def categorizar(falta):
                    f = str(falta).upper()
                    if any(k in f for k in ['FALTA', 'AUSENCIA', 'INASISTENCIA', 'DIA', 'DÍA']): return 'Dias_Faltados'
                    return 'Llamados_Atencion'
                
                df_exp['Cat'] = df_exp[col_tipo].apply(categorizar)
                exp_res = df_exp.pivot_table(index='TEC_KEY', columns='Cat', aggfunc='size', fill_value=0).reset_index()
                
                if 'Dias_Faltados' not in exp_res.columns: exp_res['Dias_Faltados'] = 0
                if 'Llamados_Atencion' not in exp_res.columns: exp_res['Llamados_Atencion'] = 0
                
                resumen_final = pd.merge(resumen_final, exp_res[['TEC_KEY', 'Dias_Faltados', 'Llamados_Atencion']], on='TEC_KEY', how='left')
            else:
                resumen_final['Dias_Faltados'] = 0
                resumen_final['Llamados_Atencion'] = 0
        else:
            resumen_final['Dias_Faltados'] = 0
            resumen_final['Llamados_Atencion'] = 0

        resumen_final.fillna({'Dias_Faltados': 0, 'Llamados_Atencion': 0}, inplace=True)
        resumen_final['Dias_Faltados'] = resumen_final['Dias_Faltados'].astype(int)
        resumen_final['Llamados_Atencion'] = resumen_final['Llamados_Atencion'].astype(int)

        # Dar formato ejecutivo a la tabla resultante
        resumen_final.rename(columns={
            'TEC_KEY': 'TÉCNICO',
            'Cantidad_Ordenes': 'ÓRDENES EJECUTADAS',
            'Tiempo_Prom_Minutos': 'TIEMPO PROM. (Min)',
            'Primera_Orden': 'HORA 1ra ORDEN',
            'Salida_Plantel': 'SALIDA PLANTEL (GPS)',
            'Entrada_Plantel': 'RETORNO PLANTEL (GPS)',
            'Dias_Faltados': 'DÍAS FALTADOS',
            'Llamados_Atencion': 'LLAMADOS DE ATENCIÓN'
        }, inplace=True)

        return resumen_final, "Cruce exitoso"

    except Exception as e:
        return None, f"Error en el cruce integral: {e}"

def generar_pdf_rendimiento_integral(df_resumen):
    try:
        from fpdf import FPDF
    except ImportError:
        return b""
        
    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 14)
            self.cell(0, 10, "REPORTE INTEGRAL DE RENDIMIENTO DE TECNICOS", ln=True, align="C")
            self.set_font("Helvetica", "", 10)
            from datetime import datetime
            fecha_str = f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            self.cell(0, 6, fecha_str, ln=True, align="C")
            self.ln(5)

    pdf = PDF(orientation="L") # Orientación horizontal para que quepan las columnas
    pdf.add_page()
    
    if df_resumen is None or df_resumen.empty:
        pdf.cell(0, 10, "No hay datos para mostrar.", ln=True)
    else:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        
        valid_cols = df_resumen.columns.tolist()
        col_width = 275 / len(valid_cols)
        
        for c in valid_cols:
            pdf.cell(col_width, 8, str(c)[:18], border=1, fill=True, align="C")
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 8)
        for _, row in df_resumen.iterrows():
            for c in valid_cols:
                val = str(row.get(c, ''))
                pdf.cell(col_width, 7, val[:22], border=1, align="C")
            pdf.ln()

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# REPORTE INTEGRAL 360 (PRODUCTIVIDAD, GPS Y RRHH)
# ==============================================================================
class ReporteIntegral360PDF(FPDF):
    def header(self):
        # Logo corporativo
        if os.path.exists('logo.png'):
            self.image('logo.png', 10, 8, 33)
        self.set_y(12)
        self.set_x(50)
        self.set_text_color(40, 40, 40)
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 6, safestr("REPORTE INTEGRAL 360° - OPERACIONES Y RRHH"), ln=True, align="R")
        self.set_x(50)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, safestr("Maxcom PRO - Módulo Gerencial Avanzado"), ln=True, align="R")
        
        self.set_draw_color(200, 200, 200)
        self.line(10, 25, 287, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

def generar_pdf_rendimiento_integral_360(df_m, df_tipo_ord, df_exp_det):
    pdf = ReporteIntegral360PDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # --- MÓDULO 1: RESUMEN GERENCIAL (KPIs) ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(16, 185, 129) # Verde
    pdf.cell(0, 8, safestr("1. RESUMEN GERENCIAL (Indicadores Clave)"), ln=True)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    total_tecs = len(df_m)
    total_ords = int(df_m['ÓRDENES CANTIDAD'].sum()) if 'ÓRDENES CANTIDAD' in df_m else 0
    prom_gral = round(df_m['TIEMPO PROM. EN ORDEN (Min)'].mean(), 1) if not df_m.empty else 0
    tot_inc = int(df_m['DÍAS FALTADOS'].sum() + df_m['LLAMADOS ATENCIÓN'].sum() + df_m['DÍAS NO PRESENTADO'].sum())
    
    kpi_text = (f"Técnicos Analizados: {total_tecs}   |   "
                f"Total Órdenes Ejecutadas: {total_ords}   |   "
                f"Tiempo Promedio Global: {prom_gral} min   |   "
                f"Total Incidencias y Faltas: {tot_inc}")
    pdf.cell(0, 6, safestr(kpi_text), ln=True)
    pdf.ln(5)
    
    # --- MÓDULO 2: PRODUCTIVIDAD EN CAMPO ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(59, 130, 246) # Azul
    pdf.cell(0, 8, safestr("2. EJECUCIÓN OPERATIVA (Productividad y Tiempos de Cierre)"), ln=True)
    
    pdf.set_fill_color(240, 245, 250)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 8)
    
    w1 = [60, 20, 20, 20, 25, 30, 30] 
    h1 = ["TÉCNICO", "TOTAL", "PLEX", "RESID.", "PROM(Min)", "1ra ORDEN", "ÚLT. ORDEN"]
    
    for i, h in enumerate(h1):
        pdf.cell(w1[i], 7, safestr(h), border=1, fill=True, align="C")
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 8)
    for _, row in df_m.iterrows():
        pdf.cell(w1[0], 6, safestr(row.get('TÉCNICO', ''))[:35], border=1)
        pdf.cell(w1[1], 6, safestr(row.get('ÓRDENES CANTIDAD', 0)), border=1, align="C")
        pdf.cell(w1[2], 6, safestr(row.get('ÓRDENES PLEX', 0)), border=1, align="C")
        pdf.cell(w1[3], 6, safestr(row.get('ÓRDENES RESIDENCIAL', 0)), border=1, align="C")
        
        t_prom = row.get('TIEMPO PROM. EN ORDEN (Min)', 0)
        pdf.set_text_color(220, 38, 38) if t_prom > 90 else pdf.set_text_color(0, 0, 0)
        pdf.cell(w1[4], 6, safestr(t_prom), border=1, align="C")
        pdf.set_text_color(0, 0, 0)
        
        pdf.cell(w1[5], 6, safestr(row.get('HORA 1ra ORDEN', '--')), border=1, align="C")
        pdf.cell(w1[6], 6, safestr(row.get('HORA ÚLT. ORDEN', '--')), border=1, align="C")
        pdf.ln()

    # --- MÓDULO 3: LOGÍSTICA Y RRHH (GPS y Disciplina) ---
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(245, 158, 11) # Naranja/Ambar
    pdf.cell(0, 8, safestr("3. LOGÍSTICA Y RRHH (Control de Flotilla y Asistencia)"), ln=True)
    
    pdf.set_fill_color(254, 243, 199)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 8)
    
    w2 = [60, 35, 35, 35, 40]
    h2 = ["TÉCNICO", "SALIDA GPS", "ENTRADA GPS", "DÍAS FALTADOS", "LLAMADOS ATENCIÓN"]
    
    for i, h in enumerate(h2):
        pdf.cell(w2[i], 7, safestr(h), border=1, fill=True, align="C")
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 8)
    for _, row in df_m.iterrows():
        # Solo mostrar técnicos que tengan algún dato logístico o incidencia (opcional, o mostrar todos)
        faltas_tot = row.get('DÍAS FALTADOS', 0) + row.get('DÍAS NO PRESENTADO', 0)
        llamados = row.get('LLAMADOS ATENCIÓN', 0)
        gps_s = row.get('SALIDA PLANTEL (GPS)', '--')
        gps_e = row.get('ENTRADA PLANTEL (GPS)', '--')
        
        pdf.cell(w2[0], 6, safestr(row.get('TÉCNICO', ''))[:35], border=1)
        pdf.cell(w2[1], 6, safestr(gps_s), border=1, align="C")
        pdf.cell(w2[2], 6, safestr(gps_e), border=1, align="C")
        
        pdf.set_text_color(220, 38, 38) if faltas_tot > 0 else pdf.set_text_color(0, 0, 0)
        pdf.cell(w2[3], 6, safestr(faltas_tot), border=1, align="C")
        
        pdf.set_text_color(217, 119, 6) if llamados > 0 else pdf.set_text_color(0, 0, 0)
        pdf.cell(w2[4], 6, safestr(llamados), border=1, align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

    # --- MÓDULO 4: DESGLOSE POR ACTIVIDAD ---
    if df_tipo_ord is not None and not df_tipo_ord.empty:
        pdf.add_page() # Nueva página para evitar cortes abruptos
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(139, 92, 246) # Morado
        pdf.cell(0, 8, safestr("4. MATRIZ DE RENDIMIENTO POR TIPO DE ACTIVIDAD"), ln=True)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, safestr("Detalle de volumen y tiempo de ejecución por categoría técnica."), ln=True)
        pdf.ln(3)

        pdf.set_fill_color(243, 232, 255)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 8)
        
        w3 = [80, 75, 25, 25]
        h3 = ["TÉCNICO", "TIPO DE ACTIVIDAD", "CANTIDAD", "PROM(Min)"]
        
        for i, h in enumerate(h3):
            pdf.cell(w3[i], 7, safestr(h), border=1, fill=True, align="C")
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 8)
        df_listado = df_tipo_ord.sort_values(['TECNICO', 'Ordenes'], ascending=[True, False])
        
        tec_actual = ""
        for _, row_t in df_listado.iterrows():
            # Limpiar nombre del técnico para no repetirlo visualmente si es el mismo
            tec_print = safestr(row_t['TECNICO'])[:45] if row_t['TECNICO'] != tec_actual else ""
            tec_actual = row_t['TECNICO']
            
            pdf.cell(w3[0], 6, tec_print, border='L' if tec_print == "" else 1)
            pdf.cell(w3[1], 6, safestr(row_t['TipoOrden'])[:40], border=1)
            pdf.cell(w3[2], 6, safestr(row_t['Ordenes']), border=1, align="C")
            
            t_min = round(row_t['MinProm'], 1)
            pdf.set_text_color(220, 38, 38) if t_min > 90 else (pdf.set_text_color(16, 185, 129) if t_min < 45 else pdf.set_text_color(0, 0, 0))
            pdf.cell(w3[3], 6, safestr(t_min), border=1, align="C")
            pdf.set_text_color(0, 0, 0)
            pdf.ln()

    return finalizar_pdf(pdf) # Asegúrate de que esta función exista en tools.py
    
# ==============================================================================
# BLINDAJE CORE - USO EXCLUSIVO PARA APP.PY (CEREBRO PRINCIPAL)
# ==============================================================================
def sanitizar_core_monitor(df):
    """
    Filtro de Cero Fricción + Reparador Automático de Fechas (Formato MaxCom)
    Garantiza que toda orden trabajada hoy, sin importar la actividad, aparezca.
    """
    import pandas as pd
    import unicodedata
    import re
    from datetime import datetime, date, timezone, timedelta
    
    if df is None or df.empty:
        return df
        
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.upper()
    
    # 1. DESTRUIR DUPLICADOS (Sin borrar órdenes del mismo técnico)
    df = df.drop_duplicates()
        
    def quitar_tildes(texto):
        if pd.isna(texto): return ""
        return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii').upper()

    # --- 2. REGLA DEL TÉCNICO (A prueba de balas) ---
    col_tec = next((c for c in df.columns if any(k in c for k in ['TECNICO', 'EMPLEADO', 'ASIGNADO', 'RECURSO', 'OPERADOR', 'USER'])), None)
    if col_tec:
        df = df[df[col_tec].notna()]
        df = df[df[col_tec].astype(str).str.strip() != '']
        df = df[~df[col_tec].astype(str).str.upper().isin(['NAN', 'NONE', 'NULL', 'NO ASIGNADO', 'SIN ASIGNAR'])]

    # --- 3. ESTADOS VÁLIDOS (Súper Ampliado) ---
    col_est = next((c for c in df.columns if 'ESTADO' in c or 'STATUS' in c), None)
    if col_est:
        # Añadidos: RESUELT, ENTREGAD, OK
        raices_validas = ['FINALIZAD', 'CERRAD', 'LIQUIDAD', 'ATENDID', 'COMPLETAD', 'SOLUCIONAD', 'REALIZAD', 'EJECUTAD', 'TERMINAD', 'OK', 'RESUELT', 'ENTREGAD']
        def estado_valido(est):
            est_str = quitar_tildes(est)
            # Si el sistema dejó el estado en blanco, la dejamos pasar para no perderla
            if not est_str or est_str in ['NAN', 'NONE', '']: return True
            return any(raiz in est_str for raiz in raices_validas)
        df = df[df[col_est].apply(estado_valido)]

    # --- 4. EL ASESINO DE ÓRDENES: FORMATO "a.m. / p.m." ---
    col_liq = next((c for c in df.columns if 'LIQ' in c or 'CIERRE' in c or 'SALIDA' in c or 'FIN' in c), None)
    if not col_liq:
        col_liq = next((c for c in df.columns if 'FECHA' in c), None)
        
    if col_liq:
        try:
            from tools import get_honduras_time
            fecha_hoy = get_honduras_time().date()
        except ImportError:
            fecha_hoy = (datetime.now(timezone.utc) - timedelta(hours=6)).date()
            
        def limpiar_fecha_maxcom(val):
            if pd.isna(val): return pd.NaT
            # Si ya es un formato de tiempo nativo, lo respetamos
            if isinstance(val, (pd.Timestamp, datetime, date)): return val
            
            str_val = str(val).strip()
            # MAGIA: Curamos el "a.m." y "p.m." que hacía que Pandas borrara las filas
            str_val = re.sub(r'(?i)a\.?\s*m\.?', 'AM', str_val)
            str_val = re.sub(r'(?i)p\.?\s*m\.?', 'PM', str_val)
            return str_val

        df['FECHA_CURADA'] = df[col_liq].apply(limpiar_fecha_maxcom)
        df['FECHA_TMP'] = pd.to_datetime(df['FECHA_CURADA'], format='mixed', dayfirst=True, errors='coerce').dt.date
        
        # Nos quedamos estrictamente con las cerradas el día de HOY
        df = df[df['FECHA_TMP'] == fecha_hoy]
        df = df.drop(columns=['FECHA_TMP', 'FECHA_CURADA'])
        
    return df
# ==============================================================================
# MOTOR PDF: REPORTE DE GASTOS Y MANTENIMIENTO DE FLOTA (auditorv.py)
# ==============================================================================
class ReporteGastosPDF(FPDF):
    def header(self):
        # Logo corporativo
        if os.path.exists('logo.png'):
            self.image('logo.png', 10, 8, 33)
        self.set_y(12)
        self.set_x(50)
        self.set_text_color(40, 40, 40)
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 6, safestr("REPORTE DE GASTOS Y MANTENIMIENTO VEHICULAR"), ln=True, align="R")
        self.set_x(50)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, safestr("Control Operativo Financiero de Flota"), ln=True, align="R")
        
        self.set_draw_color(200, 200, 200)
        self.line(10, 25, 200, 25)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, safestr(f"Página {self.page_no()}"), align="C")

def generar_pdf_gastos_vehiculo(df_gastos, vehiculo, rango_fechas, total):
    pdf = ReporteGastosPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    # Info de cabecera
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(16, 185, 129) # Verde
    pdf.cell(0, 8, safestr(f"1. RESUMEN DE GASTOS - UNIDAD: {vehiculo}"), ln=True)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    
    if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
        fecha_txt = f"{rango_fechas[0].strftime('%d/%m/%Y')} al {rango_fechas[1].strftime('%d/%m/%Y')}"
    elif isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 1:
        fecha_txt = f"{rango_fechas[0].strftime('%d/%m/%Y')}"
    else:
        fecha_txt = "Todas las fechas"

    kpi_text = f"Periodo: {fecha_txt}   |   Total Facturas: {len(df_gastos)}   |   Monto Invertido: L. {total:,.2f}"
    pdf.cell(0, 6, safestr(kpi_text), ln=True)
    pdf.ln(5)
    
    # Tabla de detalle
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(59, 130, 246) # Azul
    pdf.cell(0, 8, safestr("2. HISTORIAL DETALLADO DE FACTURAS Y SERVICIOS"), ln=True)
    
    pdf.set_fill_color(240, 245, 250)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 9)
    
    w = [25, 45, 90, 30] 
    h = ["FECHA", "CATEGORÍA", "DESCRIPCIÓN / FACTURA", "MONTO (L)"]
    
    for i, head in enumerate(h):
        pdf.cell(w[i], 7, safestr(head), border=1, fill=True, align="C")
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 9)
    for _, row in df_gastos.iterrows():
        desc = safestr(row.get('DESCRIPCION', ''))[:55]
        cat = safestr(row.get('TIPO_GASTO', ''))[:20]
        
        pdf.cell(w[0], 6, safestr(row.get('FECHA', '')), border=1, align="C")
        pdf.cell(w[1], 6, cat, border=1, align="C")
        pdf.cell(w[2], 6, desc, border=1)
        pdf.cell(w[3], 6, safestr(f"{float(row.get('MONTO', 0)):,.2f}"), border=1, align="R")
        pdf.ln()
        
    # Totales finales en la tabla
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 230, 240)
    pdf.cell(w[0] + w[1] + w[2], 7, safestr("TOTAL GASTOS DEL PERIODO:"), border=1, align="R", fill=True)
    pdf.cell(w[3], 7, safestr(f"L. {total:,.2f}"), border=1, align="R", fill=True)
    
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data

def generar_pdf_reporte_general_gastos(df_gastos):
    pdf = ReporteGastosPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(16, 185, 129)
    pdf.cell(0, 8, safestr("REPORTE GENERAL: GASTOS POR VEHÍCULO Y CATEGORÍA"), ln=True, align="C")
    pdf.ln(5)

    if df_gastos.empty:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, "No hay gastos registrados en el sistema.", ln=True)
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        pdf.output(path)
        with open(path, "rb") as f: data = f.read()
        os.remove(path)
        return data

    # Asegurar que los montos sean números para poder sumarlos
    df_gastos['MONTO'] = pd.to_numeric(df_gastos['MONTO'], errors='coerce').fillna(0)
    
    # Agrupar matemáticamente por Vehículo y luego por Categoría
    resumen = df_gastos.groupby(['VEHICULO', 'TIPO_GASTO']).agg(
        Cantidad=('TIPO_GASTO', 'count'),
        Total=('MONTO', 'sum')
    ).reset_index()

    # Ordenar por Vehículo y luego por los gastos más caros
    resumen = resumen.sort_values(by=['VEHICULO', 'Total'], ascending=[True, False])

    for vehiculo, df_vehiculo in resumen.groupby('VEHICULO'):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(59, 130, 246) # Azul
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 7, safestr(f" UNIDAD: {vehiculo}"), border=1, ln=True, fill=True)
        
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 245, 250)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(80, 6, "CATEGORÍA", border=1, fill=True, align="C")
        pdf.cell(40, 6, "FRECUENCIA", border=1, fill=True, align="C")
        pdf.cell(70, 6, "TOTAL INVERTIDO (L.)", border=1, fill=True, align="C")
        pdf.ln()

        subtotal_vehiculo = 0
        pdf.set_font("Helvetica", "", 9)
        for _, row in df_vehiculo.iterrows():
            cat = safestr(row['TIPO_GASTO'])[:35]
            cant = str(row['Cantidad'])
            tot = float(row['Total'])
            subtotal_vehiculo += tot
            
            pdf.cell(80, 6, cat, border=1)
            pdf.cell(40, 6, cant, border=1, align="C")
            pdf.cell(70, 6, safestr(f"{tot:,.2f}"), border=1, align="R")
            pdf.ln()
        
        # Fila de Subtotal por Vehículo
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(220, 230, 240)
        pdf.cell(120, 6, "SUBTOTAL VEHÍCULO:", border=1, align="R", fill=True)
        pdf.cell(70, 6, safestr(f"L. {subtotal_vehiculo:,.2f}"), border=1, align="R", fill=True)
        pdf.ln(5)
        
    # Gran Total al final del documento
    gran_total = resumen['Total'].sum()
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(16, 185, 129)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(120, 8, "GRAN TOTAL INVERTIDO EN FLOTA:", border=1, align="R", fill=True)
    pdf.cell(70, 8, safestr(f"L. {gran_total:,.2f}"), border=1, align="R", fill=True)

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f: data = f.read()
    os.remove(path)
    return data
