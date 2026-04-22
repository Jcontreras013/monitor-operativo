import pandas as pd
import re
from fpdf import FPDF
from datetime import datetime, timedelta
import unicodedata
import tempfile
import os
import numpy as np

def safestr(texto):
    """Sanitizador CRÍTICO: Previene corrupción de PDFs eliminando caracteres especiales."""
    if pd.isna(texto):
        return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

from datetime import datetime, timedelta

def get_honduras_time():
    """Calcula y devuelve la hora exacta de Honduras (UTC-6)"""
    return datetime.utcnow() - timedelta(hours=6)

# ==============================================================================
# 1. MAPEO UNIVERSAL DE COLUMNAS
# ==============================================================================
COLUMNS_MAPPING = {
    'HORA_INI': ['HORA ENTRADA', 'HORA INICIO', 'HORAINICIOORDEN', 'FECHA ENTRADA'],
    'HORA_LIQ': ['HORA LIQUIDADO', 'HORA CIERRE', 'HORACIERREORDEN', 'FECHA LIQUIDADO'],
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
        PATRON_VIVA = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
        df_vivas = dfv[dfv['ESTADO'].astype(str).str.contains(PATRON_VIVA, na=False, case=False)]
        
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

def finalizar_pdf(pdfobj):
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdfobj.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

def es_offline_preciso(comentario):
    txt = str(comentario).upper().strip()
    if not txt or txt == 'NAN': return False
    jergasolucion = ['OK', 'LISTO', 'RECUPERADO', 'SOLUCIONADO', 'NAVEGA', 'YA QUEDO', 'ARRIBA', 'FUNCIONAL', 'ONLINE']
    if any(word in txt for word in jergasolucion): return False
    keywordsfalla = ['OFFLINE', 'OFF LINE', 'SIN INTERNET', 'LOS RED', 'PON ROJO', 'LOS EN ROJO', 'EQUIPO OFFLINE', 'ONU OFFLINE', 'ONT OFFLINE', 'FUERA DE SERVICIO', 'SIN SEÑAL']
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

# ==============================================================================
# ---> FUNCIÓN: GENERADOR DE REPORTE TRIMESTRAL DETALLADO (GERENCIAL) <---
# ==============================================================================
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
        patron_vivas = 'PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|VIAJANDO|CAMINO|LLEGADA'
        mask_vivas = df_base['ESTADO'].astype(str).str.contains(patron_vivas, na=False, case=False)
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

# ==============================================================================
# FUNCIÓN PARA GENERAR PDF DE PENDIENTES GENERALES (DISPATCH)
# ==============================================================================
def generar_pdf_pendientes_dispatch(df_totales, df_detalle, hoy_str):
    pdf = ReporteGenerencialPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # --- ENCABEZADO DEL REPORTE ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE DE PENDIENTES GENERALES (DISPATCH)"), border=0, ln=True, align="C")
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, safestr(f"Corte Operativo del Día: {hoy_str}"), ln=True, align="C")
    pdf.ln(10)
    
    # --- SECCIÓN: RESUMEN DE CARGA ---
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
    
    # --- SECCIÓN: DESGLOSE DE NUEVAS SIN ASIGNAR ---
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

    # --- SECCIÓN 3: LA TABLA GRANDE (TODAS LAS ASIGNADAS CON KPI) ---
    df_asig = df_detalle[~mask_sin_tec].copy()

    if not df_asig.empty:
        pdf.add_page() 
        pdf.seccion_titulo("LISTADO GENERAL DETALLADO: ORDENES EN RUTA (ASIGNADAS)")
        
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(50, 50, 50)
        pdf.set_font("Helvetica", "B", 7)
        
        # Ajuste de anchos para sumar ~190mm
        pdf.cell(15, 6, "Orden", border=1, align="C", fill=True)
        pdf.cell(20, 6, "Cliente", border=1, align="C", fill=True)
        pdf.cell(50, 6, "Actividad", border=1, align="C", fill=True)
        pdf.cell(55, 6, "Colonia", border=1, align="C", fill=True)
        pdf.cell(40, 6, "Tecnico", border=1, align="C", fill=True)
        pdf.cell(10, 6, "Dias", border=1, align="C", fill=True)
        pdf.ln()
        
        # ORDENAR POR DÍAS (MAYOR A MENOR) Y LUEGO POR TÉCNICO
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
            
            # KPI COLORES SEMÁFORO
            if dias_retraso_val >= 7:
                pdf.set_fill_color(211, 47, 47) # Rojo
                pdf.set_text_color(255, 255, 255)
            elif dias_retraso_val >= 4:
                pdf.set_fill_color(245, 124, 0) # Naranja
                pdf.set_text_color(255, 255, 255)
            elif dias_retraso_val >= 1:
                pdf.set_fill_color(251, 192, 45) # Amarillo
                pdf.set_text_color(0, 0, 0)
            else:
                pdf.set_fill_color(56, 142, 60) # Verde
                pdf.set_text_color(255, 255, 255)
                
            pdf.cell(10, 5, safestr(dias_retraso_str), border=1, align="C", fill=True)
            pdf.ln()
            
        pdf.set_text_color(0, 0, 0)

    return finalizar_pdf(pdf)

#--------------------------------------------------------------#
#Proseso Gerencial    
#--------------------------------------------------------------#
def parse_date_ultra_safe(val):
    if pd.isnull(val) or str(val).strip() == "" or str(val).upper() in ["NONE", "NAN", "NAT", "NULL"]:
        return pd.NaT
    str_val = str(val).strip()
    if str_val in ["0", "0.0", "1899-12-30 00:00:00"]:
        return pd.NaT

    hoy = pd.Timestamp(get_honduras_time()).normalize()

    try:
        if isinstance(val, dt_time): return pd.Timestamp.combine(hoy.date(), val)
        if isinstance(val, datetime):
            if val.year <= 1970: return hoy + pd.Timedelta(hours=val.hour, minutes=val.minute, seconds=val.second)
            return pd.Timestamp(val)
        if isinstance(val, (int, float)):
            if val == 0 or val == 0.0: return pd.NaT
            if val > 10000: return pd.to_datetime(val, unit='D', origin='1899-12-30')
            elif 0 < val < 1: return hoy + pd.to_timedelta(val, unit='D')
            else: return pd.NaT
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', str_val):
            parsed_time = pd.to_datetime(str_val).time()
            return pd.Timestamp.combine(hoy.date(), parsed_time)
        if re.match(r'^\d{4}-\d{2}-\d{2}', str_val): parsed = pd.to_datetime(str_val, errors='coerce')
        else: parsed = pd.to_datetime(str_val, dayfirst=True, errors='coerce')

        if pd.notnull(parsed):
            if parsed.year <= 1970: return hoy + pd.Timedelta(hours=parsed.hour, minutes=parsed.minute, seconds=parsed.second)
            return parsed
        return pd.NaT
    except: return pd.NaT

def procesar_fechas_seguro(df_input, columnas):
    df = df_input.copy()
    for col in columnas:
        if col in df.columns: df[col] = df[col].apply(parse_date_ultra_safe)
    return df

# ==============================================================================
# FUNCIÓN DE PROCESAMIENTO GERENCIAL
# ==============================================================================
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

