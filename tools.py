import pandas as pd
import re
from fpdf import FPDF
from datetime import datetime, timedelta
import unicodedata
import tempfile
import os
import io

def safestr(texto):
    """Sanitizador CRÍTICO: Previene corrupción de PDFs eliminando caracteres especiales."""
    if pd.isna(texto):
        return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

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
        self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "", 7)
        self.cell(100, 5, safestr("Reporte Operativo Consolidado"), ln=False, align="L")
        self.cell(0, 5, safestr("Maxcom PRO - Modulo Gerencial"), ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

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
                
                if df.columns[i] in ['% LOGRO FINAL', '% LOGRO SEMANAL', '% LOGRO META', 'Participacion_%']:
                    try:
                        pct = float(str(valstr).replace('%', ''))
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

# ==============================================================================
# 3. MOTOR DE GENERACIÓN DE GRÁFICOS
# ==============================================================================
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
    except Exception as e:
        return {}

# ==============================================================================
# LÓGICA DE VALORIZACIÓN DE METAS (GAMIFICACIÓN INTELIGENTE)
# ==============================================================================
def calcular_aporte_meta(row):
    act = str(row.get('ACTIVIDAD', '')).upper()
    com = str(row.get('COMENTARIO', '')).upper()
    txt = act + " " + com
    
    if 'PEXTERNO' in act:
        return 100.0  
    elif re.search('ADIC|CAMBIO|MIGRACI|RECUP', txt):
        return 12.5   
    elif re.search('INS|NUEVA|PLEX|SPLITTEROPT', act):
        return 25.0   
    elif re.search('SOP|FALLA|MANT|RECON|TRASLADO', act):
        return 12.5   
    else:
        return 12.5   

# ==============================================================================
# 6. FUNCIONES PARA GENERAR PDF (EXISTENTES)
# ==============================================================================
def finalizar_pdf(pdfobj):
    fd, tmppath = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdfobj.output(tmppath)
        with open(tmppath, "rb") as f: return f.read()
    finally:
        try: os.remove(tmppath)
        except: pass

def generar_pdf_semanal(df_base, fecha_inicio, fecha_fin):
    df_sem = df_base[
        (df_base['HORA_LIQ'].dt.date >= fecha_inicio) & 
        (df_base['HORA_LIQ'].dt.date <= fecha_fin) &
        (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
    ].copy()
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(84, 98, 143)
    pdf.cell(0, 10, safestr(f" Reporte Analitico Semanal: {fecha_inicio} al {fecha_fin}"), border=1, ln=True, fill=True)
    if not df_sem.empty:
        df_sem['%_APORTE'] = df_sem.apply(calcular_aporte_meta, axis=1)
        df_tec = df_sem.groupby('TECNICO').agg(ORDENES=('NUM', 'count'), PORCENTAJE_META=('%_APORTE', 'sum')).reset_index()
        df_tec['% LOGRO SEMANAL'] = ((df_tec['PORCENTAJE_META'] / 600.0) * 100).round(1)
        df_tec_table = df_tec[['TECNICO', 'ORDENES', 'PORCENTAJE_META', '% LOGRO SEMANAL']].copy()
        df_tec_table.columns = ['TECNICO', 'ORDENES', 'PUNTOS ACUMULADOS', '% LOGRO SEMANAL']
        df_tec_table['% LOGRO SEMANAL'] = df_tec_table['% LOGRO SEMANAL'].astype(str) + '%'
        pdf.dibujar_tabla_rendimiento(df_tec_table, anchos=[80, 30, 40, 40])
    return finalizar_pdf(pdf)

def generar_pdf_mensual(df_base, mes, anio):
    df_mes = df_base[(df_base['HORA_LIQ'].dt.month == mes) & (df_base['HORA_LIQ'].dt.year == anio)].copy()
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.seccion_titulo(f"Reporte Mensual: {mes}/{anio}")
    pdf.dibujar_tabla_cerradas_ciudad(df_mes)
    return finalizar_pdf(pdf)

def generar_pdf_cierre_diario(dfbase, fechatarget):
    dfc = dfbase[dfbase['HORA_LIQ'].dt.date == fechatarget].copy()
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.seccion_titulo(f"Cierre Diario: {fechatarget}")
    if not dfc.empty:
        pdf.dibujar_tabla_tiempos_actividad(dfc)
    return finalizar_pdf(pdf)

def logica_generar_pdf(dfbase):
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.seccion_titulo("Reporte Dinamico")
    pdf.dibujar_tabla_cerradas_ciudad(dfbase)
    return finalizar_pdf(pdf)

# ==============================================================================
# FUNCIONES DE MOTOR (DEPURACIÓN Y PROCESAMIENTO)
# ==============================================================================
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

def es_alerta_administrativa(row):
    if not hasattr(row, 'get'): return False
    act = str(row.get('ACTIVIDAD', '')).upper(); com = str(row.get('COMENTARIO', '')).upper()
    if any(e in act for e in ['INACTIVO', 'CORTEMORA', 'NOINSTALADO']): return True
    if any(j in com for j in ['NO SE PUDO', 'CLIENTE NO QUISO', 'CANCELADA', 'NO PERMITE']): return True
    return False

# ==============================================================================
# ---> NUEVA FUNCIÓN: GENERADOR DE REPORTE TRIMESTRAL DETALLADO (GERENCIAL) <---
# ==============================================================================
def generar_pdf_trimestral_detallado(tabla_produccion, tabla_eficiencia, resumen_jornada):
    pdf = ReporteGenerencialPDF(); pdf.alias_nb_pages(); pdf.add_page()
    pdf.set_font("Helvetica", "B", 12); pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, safestr("REPORTE GERENCIAL: RENDIMIENTO Y JORNADA DE TECNICOS"), border=0, ln=True, align="C")
    pdf.set_font("Helvetica", "", 9); pdf.set_text_color(100, 100, 100)
    ahorastr = datetime.now().strftime('%d/%m/%Y %I:%M %p')
    pdf.cell(0, 6, safestr(f"Generado el: {ahorastr}"), ln=True, align="C"); pdf.ln(5)
    
    if resumen_jornada.empty:
        pdf.cell(0, 10, "No hay datos suficientes.", ln=True); return finalizar_pdf(pdf)

    lista_tecnicos = resumen_jornada['TECNICO'].dropna().unique()
    for tecnico in lista_tecnicos:
        if pdf.get_y() > 220: pdf.add_page()
        pdf.set_font("Helvetica", "B", 10); pdf.set_fill_color(230, 240, 255); pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, safestr(f" 👤 TECNICO: {tecnico}"), border=1, ln=True, fill=True)
        
        df_jor = resumen_jornada[resumen_jornada['TECNICO'] == tecnico]
        df_prod = tabla_produccion[tabla_produccion['TECNICO'] == tecnico]
        df_efi = tabla_eficiencia[tabla_eficiencia['TECNICO'] == tecnico]
        
        pdf.set_font("Helvetica", "B", 8); pdf.cell(0, 6, "   RESUMEN DE JORNADA LABORAL", ln=True)
        pdf.set_font("Helvetica", "", 8)
        prom_horas = df_jor['Promedio_Horas_Dia'].values[0]; dias_lab = df_jor['Dias_Laborados'].values[0]; max_horas = df_jor['Max_Horas_Dia'].values[0]
        pdf.cell(10, 5, ""); pdf.cell(50, 5, safestr(f"Dias Trabajados: {dias_lab}")); pdf.cell(60, 5, safestr(f"Promedio en Calle: {prom_horas:.2f} hrs/dia")); pdf.cell(50, 5, safestr(f"Dia mas largo: {max_horas:.2f} hrs"), ln=True); pdf.ln(2)
        
        pdf.set_font("Helvetica", "B", 8); pdf.cell(0, 6, "   DESGLOSE DE ACTIVIDAD Y TIEMPOS", ln=True)
        pdf.set_fill_color(245, 245, 245); pdf.cell(10, 5, "")
        pdf.cell(60, 5, "Tipo de Actividad", border=1, align="C", fill=True); pdf.cell(25, 5, "Volumen", border=1, align="C", fill=True); pdf.cell(25, 5, "% del Total", border=1, align="C", fill=True); pdf.cell(40, 5, "Promedio de Resolucion", border=1, align="C", fill=True); pdf.ln()
        
        pdf.set_font("Helvetica", "", 8); total_ordenes_tec = 0
        df_prod = df_prod.sort_values(by='Cantidad', ascending=False)
        for _, fila_p in df_prod.iterrows():
            actividad = str(fila_p['ACTIVIDAD']); cantidad = fila_p['Cantidad']; porcentaje = fila_p['Participacion_%']
            total_ordenes_tec += cantidad
            fila_efi = df_efi[df_efi['ACTIVIDAD'] == actividad]
            minutos_prom = fila_efi['Promedio_Minutos'].values[0] if not fila_efi.empty else 0
            pdf.cell(10, 5, ""); pdf.cell(60, 5, safestr(actividad[:35]), border=1); pdf.cell(25, 5, safestr(str(cantidad)), border=1, align="C"); pdf.cell(25, 5, safestr(f"{porcentaje}%"), border=1, align="C")
            if pd.notnull(minutos_prom) and minutos_prom > 120:
                pdf.set_text_color(200, 0, 0); pdf.cell(40, 5, safestr(f"{minutos_prom:.0f} min [!]"), border=1, align="C"); pdf.set_text_color(0, 0, 0)
            elif pd.notnull(minutos_prom):
                pdf.cell(40, 5, safestr(f"{minutos_prom:.0f} min"), border=1, align="C")
            else: pdf.cell(40, 5, "---", border=1, align="C")
            pdf.ln()
        pdf.set_font("Helvetica", "B", 8); pdf.set_fill_color(240, 240, 240); pdf.cell(10, 5, ""); pdf.cell(60, 5, "TOTAL ORDENES", border=1, align="R", fill=True); pdf.cell(25, 5, safestr(str(total_ordenes_tec)), border=1, align="C", fill=True); pdf.ln(8)
    return finalizar_pdf(pdf)
