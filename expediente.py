import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta, timezone
import os
import tempfile
import textwrap
import time
from fpdf import FPDF
import plotly.express as px
import re
import io

# --- ARRANQUE BLINDADO SÚPER AVANZADO: CAPTURA IMPORT-ERROR Y KEY-ERROR ---
try:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    HAS_DOCX = True
except (ImportError, KeyError, Exception):
    # Captura cualquier fallo interno de python-docx para evitar caídas en el inicio
    HAS_DOCX = False

# --- IMPORTACIÓN DE HERRAMIENTAS GCS ---
try:
    from tools import leer_espejo_gcs, sobrescribir_archivo_gcs
except ImportError:
    pass

# ==============================================================================
# CONFIGURACIÓN Y CARGA DE PERSONAL
# ==============================================================================
API_KEY_FREEIMAGE = st.secrets.get("api_freeimage", "6d207e02198a847aa98d0a2a901485a5")
NOMBRE_BUCKET_SISTEMA = "jovial-trilogy-306216.appspot.com"

def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

@st.cache_data(show_spinner=False)
def cargar_personal(filepath="personal_tecnico.txt"):
    try:
        if not os.path.exists(filepath): return []
        with open(filepath, 'r', encoding='utf-8') as f:
            lineas = f.readlines()
        nombres = []
        for linea in lineas:
            linea = linea.strip()
            if linea:
                nombre_crudo = linea.split(',')[0]
                nombre_limpio = " ".join(nombre_crudo.replace('\t', ' ').split()).upper()
                if nombre_limpio: nombres.append(nombre_limpio)
        return sorted(list(set(nombres)))
    except: return []

@st.cache_data(show_spinner=False)
def cargar_personal_admin(filepath="personal_sac.txt"):
    personal = {}
    try:
        if not os.path.exists(filepath): return personal
        with open(filepath, 'r', encoding='utf-8') as f:
            contenido = f.read().replace('\n', ' ')
        
        bloques_departamentos = contenido.split('.')
        
        for bloque in bloques_departamentos:
            bloque = bloque.strip()
            if not bloque: continue
            
            partes = bloque.split(',', 1)
            
            if len(partes) > 0:
                departamento = partes[0].strip().upper()
                
                if len(partes) > 1:
                    empleados = [e.strip().upper() for e in partes[1].split(';') if e.strip()]
                else:
                    empleados = []
                
                if departamento not in personal:
                    personal[departamento] = []
                personal[departamento].extend(empleados)
                
        return personal
    except:
        return {}

# ==============================================================================
# MOTOR DE CLASIFICACIÓN INTELIGENTE DE INCIDENCIAS (EXCLUSIÓN DE ÓRDENES)
# ==============================================================================
def es_llegada_tarde(motivo, comentario):
    motivo_u = str(motivo).upper().strip()
    com_u = str(comentario).upper().strip()
    
    EXCL = [
        'ALMUERZO', 'BREAK', 'DESCANSO', 'ORDEN', 'ÓRDEN', 'CIERRE', 
        'CERRADA', 'APERTURA', 'APERTURADA', 'LIQUIDADA', 'LIQUIDACION', 
        'LIQUIDACIÓN', 'CEQUI', 'SOP'
    ]
    KWS  = ['LLEGADA TARDE', 'LLEGADA TARDIA', 'LLEGADA TARDÍA', 'TARDANZA', 'TARDE', 'RETRASO', 'LLEGADA TARDÍA / AUSENCIA']
    
    texto_completo = motivo_u + " " + com_u
    if any(ex in texto_completo for ex in EXCL):
        return False
        
    for kw in KWS:
        if kw in motivo_u:
            return True
    for kw in KWS:
        if kw in com_u:
            return True
    return False

def clasificiar_grave_o_leve(motivo, comentario, n_tardes=0):
    return clasificar_grave_o_leve(motivo, comentario, n_tardes)

def clasificar_grave_o_leve(motivo, comentario, n_tardes=0):
    motivo_u = str(motivo).upper().strip()
    com_u = str(comentario).upper().strip()
    texto = motivo_u + " " + com_u

    # 1. VEHÍCULO / MAL CUIDADO O DESCUIDO - SIEMPRE GRAVE
    palabras_vehiculo_neglect = [
        "MAL CUIDADO", "CUIDADO VEHICULO", "CUIDADO DEL VEHICULO", "CUIDADO DE VEHICULO",
        "CUIDADO VEHÍCULO", "CUIDADO DEL VEHÍCULO", "CUIDADO DE VEHÍCULO",
        "MALTRATO VEHICULO", "MALTRATO DE VEHICULO", "MALTRATO DEL VEHICULO",
        "DESCUIDO VEHICULO", "DESCUIDO DE VEHICULO", "DESCUIDO DEL VEHICULO",
        "DESCUIDO VEHÍCULO", "DESCUIDO DE VEHÍCULO", "DESCUIDO DEL VEHÍCULO",
        "DAÑO VEHICULO", "DAÑO AL VEHICULO", "DAÑO DE VEHICULO",
        "DAÑO VEHÍCULO", "DAÑO AL VEHÍCULO", "DAÑO DE VEHÍCULO",
        "GOLPE VEHICULO", "GOLPE AL VEHICULO", "GOLPE DE VEHICULO",
        "ABUSO VEHICULO", "ABUSO DEL VEHICULO", "ABUSO DE VEHICULO",
        "DAÑO CARRO", "DAÑO AL CARRO", "DAÑO UNIDAD", "DAÑO A UNIDAD"
    ]
    if any(x in texto for x in palabras_vehiculo_neglect):
        return 'GRAVE'

    # 2. EVALUACIÓN DE SLA & MANEJO DE ÓRDENES (REGLA ASOCIATIVA INTELIGENTE)
    roots_objeto = ["ORDEN", "ÓRDEN", "RUTA"]
    roots_accion = ["APERTUR", "CERR", "CIERR", "INIC", "LIQUID", "FINALIZ"]
    roots_anomalia = ["TARDE", "TARDÍ", "TARDI", "DESFAS", "DESFAC", "RETRAS", "INCUMPLI"]

    has_objeto = any(obj in texto for obj in roots_objeto)
    has_accion = any(acc in texto for acc in roots_accion)
    has_anomalia = any(anom in texto for anom in roots_anomalia)

    if (has_objeto and has_accion and has_anomalia):
        return 'GRAVE'

    # 3. ACCIONES GRAVES DIRECTAS (Seguridad y Faltas de Respeto)
    palabras_graves_directas = [
        "FALTA DE RESPETO", "FALTA DE RESPET", "FALTAS DE RESPETO",
        "IRRESPETO", "INSULTO", "INSULTOS", "GOLPE", "PELEA",
        "AGRESION", "AGRESIÓN", "AMENAZA", "HOSTIGAMIENTO",
        "FALTA AL RESPETO", "OFENSA", "OFENSAS", "FALTA RESPETO",
        "APERTURADA TARDE", "CERRADA TARDE", "APERTURADAS TARDES", "CERRADAS TARDES",
        "MAL USO", "MAL MANEJO", "MALA MANIPULACIÓN", "MALA MANIPULACION",
        "CHOQUE", "ACCIDENTE", "ALCOHOL", "EBRIEDAD", "EBRIO", "DROGA", 
        "ROBO", "HURTO", "ABANDONO DE RUTA", "ABANDONO RUTA", "ABANDONO", 
        "INJUSTIFICADA", "DAÑO", "PÉRDIDA", "PERDIDA", "FRAUDE", "NEGLIGENCIA", 
        "REINCIDENCIA", "DORMIDO", "GRAVE", "IRRESPONSABILIDAD"
    ]
    if any(kw in texto for kw in palabras_graves_directas):
        return 'GRAVE'

    graves_combos = [
        ('ABANDONO', 'RUTA'),
        ('DAÑO', 'EQUIPO'), ('DAÑO', 'VEHICULO'),
        ('DAÑO', 'VEHÍCULO'), ('DAÑO', 'CARRO'), ('DAÑO', 'UNIDAD'),
        ('FALTA', 'RESPETO'),
        ('RESPETO', 'COMPAÑERO'), ('RESPETO', 'SUPERVISOR'),
        ('ORDENES', 'PENDIENTES'), ('ÓRDENES', 'PENDIENTES'),
        ('AUSENCIA', 'AVISO'), ('AUSENCIA', 'JUSTIF'),
        ('INASISTENCIA', 'AVISO'), ('INASISTENCIA', 'JUSTIF'),
        ('IRRESPETO', 'COMPAÑERO'), ('IRRESPETO', 'SUPERVISOR'),
    ]
    for w1, w2 in graves_combos:
        if w1 in texto and w2 in texto:
            return 'GRAVE'

    # 4. PROMOCIÓN AUTOMÁTICA POR REINCIDENCIA (3 o más llegadas tarde = GRAVE)
    if es_llegada_tarde(motivo, comentario):
        if n_tardes >= 3:
            return 'GRAVE'
        return 'LEVE'

    # 5. ACCIONES LEVES
    palabras_leves = [
        'ALMUERZO EXCEDIDO', 'HORA ALMUERZO', 'HORA DE ALMUERZO',
        'EXCEDIÓ ALMUERZO', 'EXCEDIO ALMUERZO',
        'TIEMPO DE ALMUERZO', 'TIEMPO ALMUERZO', 'EXCESO ALMUERZO',
        'BREAK EXCEDIDO', 'HORA BREAK', 'HORA DE BREAK',
        'EXCEDIÓ BREAK', 'EXCEDIO BREAK',
        'TIEMPO DE BREAK', 'TIEMPO BREAK', 'EXCESO BREAK',
        'DESCANSO EXCEDIDO',
        'NO MARCÓ', 'NO MARCO', 'SIN MARCAJE', 'MARCAJE FALTANTE',
        'NO MARCÓ ENTRADA', 'NO MARCÓ SALIDA',
        'NO MARCO ENTRADA', 'NO MARCO SALIDA',
        'NO REGISTRO ENTRADA', 'NO REGISTRO SALIDA',
        'OLVIDO MARCAJE', 'FALTA DE MARCAJE', 'OLVIDO DE MARCAJE',
        'MALA DOCUMENTACION', 'MALA DOCUMENTACIÓN',
        "TARDE", "RETRASO", "TRÁFICO", "TRAFICO", "LLANTA", "UNIFORME",
        "GAFETE", "SUCIO", "DESORDEN", "OLVIDO", "MINUTOS", "LEVE"
    ]
    if any(p in texto for p in palabras_leves):
        return 'LEVE'

    leves_combos = [
        ('HORA', 'ALMUERZO'), ('HORA', 'BREAK'),
        ('EXCEDIÓ', 'ALMUERZO'), ('EXCEDIÓ', 'BREAK'),
        ('NO', 'MARCÓ'), ('NO', 'MARCO'),
        ('SIN', 'MARCAJE'), ('SIN', 'MARCA'),
        ('MALA', 'DOCUMENTACION'), ('MALA', 'DOCUMENTACIÓN'),
    ]
    for w1, w2 in leves_combos:
        if w1 in texto and w2 in texto:
            return 'LEVE'

    return 'OTRO'

def asignar_rubro_automatico(motivo, comentario, n_tardes=0):
    motivo_str = str(motivo).upper().strip()
    clasificacion = clasificar_grave_o_leve(motivo, comentario, n_tardes)
    etiqueta = f"[{clasificacion}]"
    motivo_limpio = motivo_str.replace("[GRAVE]", "").replace("[LEVE]", "").replace("[OTRO]", "").strip()
    return f"{etiqueta} {motivo_limpio}"

# ==============================================================================
# 1. LÓGICA DE PDF (Clase Base)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        logo_path = 'logo_monitor.png' if os.path.exists('logo_monitor.png') else 'logo.png' [3]
        if os.path.exists(logo_path):
            try: self.image(logo_path, 10, 6, 35)
            except: pass
        self.set_y(10); self.set_x(50); self.set_text_color(0, 0, 0)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - DEPARTAMENTO DE CONTROL OPERATIVO", ln=True, align="R")
        self.set_font("Helvetica", "", 8); self.set_x(50)
        self.cell(0, 5, "Reporte Oficial de Gestion de Personal", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
        
    def footer(self):
        self.set_y(-15); self.set_text_color(150, 150, 150); self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto) or texto is None: return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

# ==============================================================================
# 2. GENERADORES DE DOCUMENTOS DE REPORTES (PDF Y WORD)
# ==============================================================================
def generar_pdf_consolidado(df):
    df_work = pd.DataFrame()
    df_leves = df_graves = df_otros = pd.DataFrame()
    conteo_tardes = {}

    if not df.empty:
        df_work = df.copy()

        # Contar llegadas tarde filtradas para la promoción por reincidencia
        mask_tarde = df_work.apply(
            lambda r: es_llegada_tarde(
                str(r.get('TIPO_FALTA', '')).upper(),
                str(r.get('COMENTARIO', '')).upper()
            ), axis=1
        )
        conteo_tardes = (
            df_work[mask_tarde]['TECNICO']
            .astype(str).str.upper().str.strip()
            .value_counts().to_dict()
        )

        df_work['_CLASIF'] = df_work.apply(
            lambda r: clasificar_grave_o_leve(
                str(r.get('TIPO_FALTA', '')),
                str(r.get('COMENTARIO', '')),
                conteo_tardes.get(str(r.get('TECNICO', '')).upper().strip(), 0)
            ), axis=1
        )
        df_leves  = df_work[df_work['_CLASIF'] == 'LEVE'].copy()
        df_graves = df_work[df_work['_CLASIF'] == 'GRAVE'].copy()
        df_otros  = df_work[df_work['_CLASIF'] == 'OTRO'].copy()

    n_leves  = len(df_leves)
    n_graves = len(df_graves)
    n_otros  = len(df_otros)

    def _dibujar_tabla_clasif(pdf_obj, df_t, etiqueta, desc_corta,
                               hr, hg, hb,
                               rr, rg, rb,
                               thr=255, thg=255, thb=255):
        if df_t.empty:
            return

        n = len(df_t)

        pdf_obj.set_font("Helvetica", "B", 11)
        pdf_obj.set_fill_color(hr, hg, hb)
        pdf_obj.set_text_color(thr, thg, thb)
        pdf_obj.cell(0, 8,
                     f"  {etiqueta}  ({n} incidencia{'s' if n != 1 else ''})",
                     border=1, fill=True, ln=True)
        pdf_obj.set_font("Helvetica", "I", 7)
        pdf_obj.set_text_color(100, 100, 100)
        pdf_obj.cell(0, 5, f"  {desc_corta}", ln=True)
        pdf_obj.ln(2)

        W    = [25, 48, 42, 55, 20]
        HDRS = ["FECHA", "COLABORADOR", "TIPO DE FALTA", "DESCRIPCION", "SUPERVISOR"]

        pdf_obj.set_fill_color(hr, hg, hb)
        pdf_obj.set_text_color(thr, thg, thb)
        pdf_obj.set_font("Helvetica", "B", 7)
        for i, h in enumerate(HDRS):
            pdf_obj.cell(W[i], 6, h, border=1, fill=True, align="C")
        pdf_obj.ln()

        pdf_obj.set_text_color(40, 40, 40)
        for idx_fila, (_, row) in enumerate(df_t.iterrows()):
            f_inc = sanitizar(str(row.get('FECHA_INCIDENCIA', ''))[:16])
            tec   = sanitizar(str(row.get('TECNICO', ''))[:40])
            mot   = sanitizar(str(row.get('TIPO_FALTA', ''))[:35])
            com   = sanitizar(str(row.get('COMENTARIO', '')))
            sup   = sanitizar(str(row.get('SUPERVISOR', ''))[:18])

            lineas = textwrap.wrap(com, width=40)
            if not lineas:
                lineas = [""]

            if idx_fila % 2 == 0:
                pdf_obj.set_fill_color(rr, rg, rb)
            else:
                pdf_obj.set_fill_color(255, 255, 255)

            pdf_obj.set_font("Helvetica", "", 7)
            for i_l, linea in enumerate(lineas):
                b_t = 'T' if i_l == 0 else ''
                b_b = 'B' if i_l == len(lineas) - 1 else ''
                bs  = 'LR' + b_t + b_b

                pdf_obj.cell(W[0], 5, f_inc if i_l == 0 else "", border=bs, fill=True)
                pdf_obj.cell(W[1], 5, tec   if i_l == 0 else "", border=bs, fill=True)
                pdf_obj.cell(W[2], 5, mot   if i_l == 0 else "", border=bs, fill=True)
                pdf_obj.cell(W[3], 5, f" {linea}",               border=bs, fill=True)
                pdf_obj.cell(W[4], 5, sup   if i_l == 0 else "", border=bs, fill=True, ln=True)

        pdf_obj.ln(6)

    pdf = MemoPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(40, 50, 100)
    pdf.cell(0, 10, "REPORTE CONSOLIDADO DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, f"Generado el: {get_honduras_time().strftime('%d/%m/%Y a las %H:%M:%S')}", ln=True, align="C")
    pdf.ln(8)

    if df.empty:
        pdf.set_font("Helvetica", "I", 12)
        pdf.cell(0, 10, "No hay registros disponibles.", ln=True, align="C")
    else:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 6, "RESUMEN DE INCIDENCIAS POR NIVEL DE GRAVEDAD", ln=True)
        pdf.ln(2)

        W_KPI = 63
        KPI_DATA = [
            ("  FALTAS LEVES",        n_leves,  200, 140,  20, 255, 248, 220, 100, 50,  0),
            ("  FALTAS GRAVES",       n_graves, 180,  30,  30, 255, 235, 235, 255, 255, 255),
            ("  OTRAS INCIDENCIAS",   n_otros,   80,  95, 115, 235, 238, 245, 255, 255, 255),
        ]
        for (label, _, hr, hg, hb, rr, rg, rb, thr, thg, thb) in KPI_DATA:
            pdf.set_fill_color(hr, hg, hb)
            pdf.set_text_color(thr, thg, thb)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(W_KPI, 7, label, border=1, fill=True)
        pdf.ln()
        for (_, count, hr, hg, hb, rr, rg, rb, thr, thg, thb) in KPI_DATA:
            pdf.set_fill_color(rr, rg, rb)
            pdf.set_text_color(hr, hg, hb)
            pdf.set_font("Helvetica", "B", 18)
            pdf.cell(W_KPI, 12, f"  {count}", border=1, fill=True)
        pdf.ln()
        pdf.ln(10)

        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5,
                 "Nota: Las llegadas tardes se clasifican como LEVE hasta 2 ocurrencias por colaborador. "
                 "A partir de la 3a se promueven automaticamente a GRAVE.",
                 ln=True)
        pdf.ln(5)

        if n_leves > 0:
            _dibujar_tabla_clasif(
                pdf, df_leves,
                etiqueta   = "FALTAS LEVES",
                desc_corta = "Llegadas tardes (<3), almuerzo/break excedido, no marco entrada/salida, mala documentacion",
                hr=200, hg=140, hb=20,
                rr=255, rg=248, rb=220,
                thr=255, thg=255, thb=255,
            )

        if n_graves > 0:
            if pdf.get_y() > 200:
                pdf.add_page()
            _dibujar_tabla_clasif(
                pdf, df_graves,
                etiqueta   = "FALTAS GRAVES",
                desc_corta = "Mal cuidado de vehiculos, no apertura/cierre, ordenes pendientes, insultos/irrespeto, o >=3 llegadas tarde",
                hr=180, hg=30, hb=30,
                rr=255, rg=235, rb=235,
                thr=255, thg=255, thb=255,
            )

        if n_otros > 0:
            if pdf.get_y() > 200:
                pdf.add_page()
            _dibujar_tabla_clasif(
                pdf, df_otros,
                etiqueta   = "OTRAS INCIDENCIAS",
                desc_corta = "Incidencias medicas, meritos, documentos administrativos y registros sin clasificacion definida",
                hr=80, hg=95, hb=115,
                rr=235, rg=238, rb=245,
                thr=255, thg=255, thb=255,
            )

    tiene_anexos = False
    for _, row in df.iterrows():
        urls = str(row.get('URL_FOTO', '')).split(',')
        if any(u.strip().startswith('http') for u in urls):
            tiene_anexos = True
            break

    if tiene_anexos:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(40, 50, 100)
        pdf.cell(0, 10, "ANEXOS - EVIDENCIA FOTOGRÁFICA", ln=True, align="C")
        pdf.ln(5)
        for _, row in df.iterrows():
            urls    = str(row.get('URL_FOTO', '')).split(',')
            validas = [u.strip() for u in urls if u.strip().startswith('http')]
            if validas:
                tec_name     = sanitizar(str(row.get('TECNICO', '')))
                f_inc        = sanitizar(str(row.get('FECHA_INCIDENCIA', '')))
                motivo_falta = sanitizar(str(row.get('TIPO_FALTA', '')))
                for url in validas:
                    try:
                        r = requests.get(url, timeout=5)
                        if r.status_code == 200:
                            fd, tp = tempfile.mkstemp(suffix=".png")
                            os.close(fd)
                            try:
                                with open(tp, 'wb') as f: f.write(r.content)
                                if pdf.get_y() > 60:
                                    pdf.add_page()
                                pdf.set_font("Helvetica", "B", 9)
                                pdf.set_text_color(0, 0, 0)
                                pdf.set_fill_color(240, 240, 240)
                                pdf.cell(0, 8, f" Evidencia: {tec_name} | {motivo_falta} | {f_inc}",
                                         ln=True, fill=True, border=1)
                                pdf.ln(3)
                                pdf.image(tp, x=20, w=150)
                                pdf.ln(10)
                            finally:
                                if os.path.exists(tp):
                                    os.remove(tp)
                    except:
                        pass

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data


# ==============================================================================
# MOTOR AUXILIAR DE DETECCIÓN INTELIGENTE DE HORA DE FALTA
# ==============================================================================
def extraer_hora_falta(comentario, fecha_registro):
    """
    Escanea la descripción del supervisor buscando patrones de hora (ej: 08:06 am, 2:47pm).
    Si no localiza ninguna hora explícita, extrae la hora del registro del sistema.
    """
    match = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)', str(comentario))
    if match:
        return match.group(1).strip()
    
    # Intenta extraer de la fecha de registro (ej: 11/07/2026 10:10:00)
    reg_str = str(fecha_registro).strip()
    if " " in reg_str:
        return reg_str.split(" ")[1][:5] # Obtiene el hh:mm
    return "N/D"


def generar_docx_consolidado(df):
    """
    Genera un documento estructurado de Word (.docx) que simula de forma exacta el 
    formato oficial corporativo de "REPORTE DE FALTAS".
    
    Si el DataFrame contiene múltiples incidencias, se agrupan de manera cronológica
    en renglones distintos dentro del cuadro "Detalle de la Falta" para optimizar espacio [3],
    y la sección de firmas inferior se mantiene 100% en color blanco para firma manuscrita [3].
    """
    if not HAS_DOCX:
        return b""
        
    doc = Document()
    
    # --- Estilo de Página Compacto (Márgenes de 0.5 pulg para asegurar que quepa en una página) ---
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
        
    # --- Configurar tipografía estándar ---
    style_normal = doc.styles['Normal']
    font_normal = style_normal.font
    font_normal.name = 'Arial'
    font_normal.size = Pt(8.5)

    def set_cell_background(cell, hex_color):
        shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
        cell._tc.get_or_add_tcPr().append(shading_elm)

    def aplicar_espaciado_celda(cell):
        for p in cell.paragraphs:
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.0

    # Extraemos información base del primer elemento para las cabeceras principales [3]
    primer_registro = df.iloc[0]
    nombre_completo = str(primer_registro.get('TECNICO', ''))
    nombre_limpio_emp = re.sub(r'\s*\(.*\)$', '', nombre_completo).strip()
    
    fecha_falta_val = str(primer_registro.get('FECHA_INCIDENCIA', ''))
    hora_falta_val = extraer_hora_falta(str(primer_registro.get('COMENTARIO', '')), str(primer_registro.get('FECHA_REGISTRO', '')))

    # ==========================================================================
    # 1. TABLA ENCABEZADO (Logo | Título | Metadatos) - Imagen 1
    # ==========================================================================
    header_table = doc.add_table(rows=1, cols=3)
    header_table.style = 'Table Grid'
    header_table.autofit = False
    
    header_table.columns[0].width = Inches(1.3)
    header_table.columns[1].width = Inches(3.7)
    header_table.columns[2].width = Inches(2.5)

    # Columna 1: Logotipo (Utiliza logo_monitor.png con fallback a logo.png) [3]
    cell_logo = header_table.cell(0, 0)
    p_logo = cell_logo.paragraphs[0]
    logo_path = 'logo_monitor.png' if os.path.exists('logo_monitor.png') else 'logo.png' [3]
    if os.path.exists(logo_path):
        try: p_logo.add_run().add_picture(logo_path, width=Inches(1.1))
        except: p_logo.text = "MAXCOM"
    else:
        p_logo.text = "MAXCOM"
        p_logo.runs[0].font.bold = True
        p_logo.runs[0].font.size = Pt(12)
    p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Columna 2: Título Central de la tabla de cabecera
    cell_title = header_table.cell(0, 1)
    p_title = cell_title.paragraphs[0]
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = p_title.add_run("\nREPORTE DE FALTAS")
    run_title.font.size = Pt(10)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(128, 128, 128) # Gris opaco

    # Columna 3: Cuadro de Metadatos
    cell_meta = header_table.cell(0, 2)
    meta_table = cell_meta.add_table(rows=4, cols=2)
    meta_table.style = 'Table Grid'
    meta_table.autofit = True
    
    meta_fields = [
        ("CÓDIGO", "HN-GG-RH-FR-09"),
        ("VERSIÓN", "1.0"),
        ("FECHA", "12/05/2026"),
        ("CLASIFICACIÓN", "INTERNO")
    ]
    for r_idx, (k, v) in enumerate(meta_fields):
        m_cells = meta_table.rows[r_idx].cells
        m_cells[0].text = k
        m_cells[0].paragraphs[0].runs[0].font.bold = True
        m_cells[0].paragraphs[0].runs[0].font.size = Pt(7)
        m_cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(100, 116, 139)
        
        m_cells[1].text = v
        m_cells[1].paragraphs[0].runs[0].font.size = Pt(7)
        m_cells[1].paragraphs[0].runs[0].font.color.rgb = RGBColor(100, 116, 139)
        
        aplicar_espaciado_celda(m_cells[0])
        aplicar_espaciado_celda(m_cells[1])

    for cell in header_table.rows[0].cells:
        aplicar_espaciado_celda(cell)

    # --- TÍTULO INDEPENDIENTE DEBAJO DE LA CABECERA (Imagen 1) --- [3]
    p_title_below = doc.add_paragraph()
    p_title_below.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title_below.paragraph_format.space_before = Pt(12)
    p_title_below.paragraph_format.space_after = Pt(12)
    run_title_below = p_title_below.add_run("REPORTE DE FALTAS") # [3]
    run_title_below.font.name = 'Arial'
    run_title_below.font.size = Pt(11)
    run_title_below.font.bold = True
    run_title_below.font.color.rgb = RGBColor(0, 0, 0)

    # ==========================================================================
    # 2. TABLA: DATOS DEL JEFE SOLICITANTE
    # ==========================================================================
    table_jefe = doc.add_table(rows=6, cols=2)
    table_jefe.style = 'Table Grid'
    table_jefe.columns[0].width = Inches(2.5)
    table_jefe.columns[1].width = Inches(5.0)

    # Cabecera azul
    hdr_cell_j = table_jefe.rows[0].cells[0].merge(table_jefe.rows[0].cells[1])
    hdr_cell_j.text = "Datos del Jefe del Departamento Solicitante"
    set_cell_background(hdr_cell_j, "1E1B4B") # Navy oscuro institucional
    p_hdr_j = hdr_cell_j.paragraphs[0]
    p_hdr_j.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_hdr_j = p_hdr_j.runs[0]
    run_hdr_j.font.bold = True
    run_hdr_j.font.size = Pt(9)
    run_hdr_j.font.color.rgb = RGBColor(255, 255, 255)

    jefe_labels = [
        "Nombre del Jefe del Departamento",
        "Puesto",
        "Departamento",
        "Ciudad",
        "Fecha de Ingreso"
    ]
    for f_idx, label in enumerate(jefe_labels):
        cells = table_jefe.rows[f_idx + 1].cells
        cells[0].text = label
        cells[0].paragraphs[0].runs[0].font.bold = True
        cells[0].paragraphs[0].runs[0].font.size = Pt(8.5)
        cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(30, 41, 59)
        
        cells[1].text = "" # Editable manual
        
        aplicar_espaciado_celda(cells[0])
        aplicar_espaciado_celda(cells[1])

    aplicar_espaciado_celda(hdr_cell_j)
    doc.add_paragraph()

    # ==========================================================================
    # 3. TABLA: DATOS DEL EMPLEADO REPORTADO (AUTO-COMPLETADOS)
    # ==========================================================================
    table_emp = doc.add_table(rows=7, cols=2)
    table_emp.style = 'Table Grid'
    table_emp.columns[0].width = Inches(2.5)
    table_emp.columns[1].width = Inches(5.0)

    # Cabecera azul
    hdr_cell_e = table_emp.rows[0].cells[0].merge(table_emp.rows[0].cells[1])
    hdr_cell_e.text = "Datos de Empleado Reportado"
    set_cell_background(hdr_cell_e, "1E1B4B")
    p_hdr_e = hdr_cell_e.paragraphs[0]
    p_hdr_e.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_hdr_e = p_hdr_e.runs[0]
    run_hdr_e.font.bold = True
    run_hdr_e.font.size = Pt(9)
    run_hdr_e.font.color.rgb = RGBColor(255, 255, 255)

    emp_fields = [
        ("Nombre del Empleado", nombre_limpio_emp), # Autocompletado [3]
        ("Código de Empleado", ""),
        ("Puesto", ""),
        ("Horario de Trabajo", ""),
        ("Fecha de la Falta Ocurrida", fecha_falta_val), # Autocompletado [3]
        ("Hora de la Falta Ocurrida", hora_falta_val)   # Autocompletado [3]
    ]

    for f_idx, (label, val) in enumerate(emp_fields):
        cells = table_emp.rows[f_idx + 1].cells
        cells[0].text = label
        cells[0].paragraphs[0].runs[0].font.bold = True
        cells[0].paragraphs[0].runs[0].font.size = Pt(8.5)
        cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(30, 41, 59)
        
        cells[1].text = val
        if val:
            cells[1].paragraphs[0].runs[0].font.size = Pt(8.5)
            
        aplicar_espaciado_celda(cells[0])
        aplicar_espaciado_celda(cells[1])

    aplicar_espaciado_celda(hdr_cell_e)
    doc.add_paragraph()

    # ==========================================================================
    # 4. TABLA: DETALLE DE LA FALTA (CON CONSOLIDACIÓN EN RENGLONES DISTINTOS)
    # ==========================================================================
    table_det = doc.add_table(rows=12, cols=1)
    table_det.style = 'Table Grid'

    # Cabecera azul
    hdr_cell_d = table_det.rows[0].cells[0]
    hdr_cell_d.text = "Detalle de la Falta"
    set_cell_background(hdr_cell_d, "1E1B4B")
    p_hdr_d = hdr_cell_d.paragraphs[0]
    p_hdr_d.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_hdr_d = p_hdr_d.runs[0]
    run_hdr_d.font.bold = True
    run_hdr_d.font.size = Pt(9)
    run_hdr_d.font.color.rgb = RGBColor(255, 255, 255)
    aplicar_espaciado_celda(hdr_cell_d)

    # --- AUTOCOMPLETADO DE CADA INCIDENCIA EN RENGLONES DISTINTOS --- [3]
    idx_renglon = 1
    for _, row_inc in df.iterrows():
        if idx_renglon >= 12: # Límite para evitar que salte de página
            break
        fecha_p = str(row_inc.get('FECHA_INCIDENCIA', ''))
        tipo_p = str(row_inc.get('TIPO_FALTA', ''))
        desc_p = str(row_inc.get('COMENTARIO', ''))
        
        cell_renglon = table_det.rows[idx_renglon].cells[0]
        cell_renglon.text = f"• [{fecha_p}] {tipo_p}: {desc_p}" # [3]
        cell_renglon.paragraphs[0].runs[0].font.size = Pt(8.5)
        aplicar_espaciado_celda(cell_renglon)
        idx_renglon += 1

    # Renglones restantes en blanco con altura para simular diseño impreso original [3]
    for r_idx in range(idx_renglon, 12):
        cell_vacia = table_det.rows[r_idx].cells[0]
        cell_vacia.text = ""
        table_det.rows[r_idx].height = Inches(0.18)
        aplicar_espaciado_celda(cell_vacia)

    doc.add_paragraph()

    # Texto Legal intermedio
    p_legal = doc.add_paragraph()
    run_legal = p_legal.add_run("Firmo en señal de solicitud/autorización/aprobación lo de arriba detallado.")
    run_legal.font.size = Pt(8.5)
    run_legal.italic = True
    p_legal.paragraph_format.space_before = Pt(4)
    p_legal.paragraph_format.space_after = Pt(4)

    # ==========================================================================
    # 5. TABLA INFERIOR DE FIRMAS Y ELABORACIÓN - Imagen 2 [3]
    # ==========================================================================
    table_bottom = doc.add_table(rows=2, cols=2)
    table_bottom.style = 'Table Grid'
    table_bottom.columns[0].width = Inches(4.5)
    table_bottom.columns[1].width = Inches(3.0)

    # --- FILA 0: ENCABEZADOS AZULES ---
    # Celda izquierda: Totalmente azul oscuro sin texto (Imagen 2) [3]
    cell_elab_hdr = table_bottom.cell(0, 0)
    cell_elab_hdr.text = "" 
    set_cell_background(cell_elab_hdr, "1E1B4B")

    # Celda derecha: Azul oscuro con texto de Firma [3]
    cell_firma_hdr = table_bottom.cell(0, 1)
    cell_firma_hdr.text = "" 
    set_cell_background(cell_firma_hdr, "1E1B4B")
    p_firma_hdr = cell_firma_hdr.paragraphs[0]
    p_firma_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_firma_hdr = p_firma_hdr.add_run("Firma de Jefe de\nDepartamento Solicitante") [3]
    run_firma_hdr.font.bold = True
    run_firma_hdr.font.size = Pt(8.5)
    run_firma_hdr.font.color.rgb = RGBColor(255, 255, 255)

    # --- FILA 1: CONTENIDO ---
    cell_elab_cont = table_bottom.cell(1, 0)
    left_subtable = cell_elab_cont.add_table(rows=2, cols=2)
    left_subtable.style = 'Table Grid'

    # Fecha y hora actual del sistema en Honduras [3]
    ahora_hn = get_honduras_time()
    fecha_elab = ahora_hn.strftime("%d/%m/%Y") [3]
    hora_elab = ahora_hn.strftime("%I:%M%p").lower() # Formato compacto como 10:10am [3]

    elab_fields = [
        ("Fecha de elaboración de reporte", fecha_elab),
        ("Hora de elaboración de reporte", hora_elab)
    ]
    for f_idx, (k, v) in enumerate(elab_fields):
        l_cells = left_subtable.rows[f_idx].cells
        l_cells[0].text = k
        l_cells[0].paragraphs[0].runs[0].font.bold = True
        l_cells[0].paragraphs[0].runs[0].font.size = Pt(8)
        
        l_cells[1].text = v
        if v:
            l_cells[1].paragraphs[0].runs[0].font.size = Pt(8)
            
        aplicar_espaciado_celda(l_cells[0])
        aplicar_espaciado_celda(l_cells[1])

    # Columna Derecha de Firma: SE MANTIENE TOTALMENTE COLOR BLANCO PARA LA PLUMA [3]
    cell_firma_cont = table_bottom.cell(1, 1)
    cell_firma_cont.text = "" # Fondo blanco liso [3]
    cell_firma_cont.add_paragraph("\n\n\n")

    # Aplicar sangría final a las celdas de la tabla inferior
    for r_idx in range(2):
        for c_idx in range(2):
            aplicar_espaciado_celda(table_bottom.cell(r_idx, c_idx))

    # Retornar como Bytes seguros en memoria
    b_io = io.BytesIO()
    doc.save(b_io)
    return b_io.getvalue()


# ==============================================================================
# MOTOR DE MEMORIA
# ==============================================================================
def forzar_actualizacion_memoria(conn):
    df = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "expedientes_maestro.csv")
    if df is None or df.empty:
        df = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
    st.session_state['df_exp_memoria'] = df

def obtener_datos_memoria(conn):
    if 'df_exp_memoria' not in st.session_state:
        forzar_actualizacion_memoria(conn)
    return st.session_state['df_exp_memoria']

# ==============================================================================
# 3. INTERFAZ DE EXPEDIENTES Y VISTAS AISLADAS
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base):
    supervisor_actual = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    rol_usuario = st.session_state.get('rol_actual', 'monitoreo')
    es_admin = (str(rol_usuario).strip().lower() == 'admin')

    st.title("📁 Gestión de Expedientes y Reportes")
    
    def generar_vista_historial(df_mostrar, titulo_seccion, tab_id):
        try:
            col_tit, col_ref = st.columns([4, 1])
            with col_tit:
                st.subheader(f"📜 Historial de Expedientes ({titulo_seccion})")
            with col_ref:
                if st.button("🔄 Refrescar Datos", key=f"btn_refrescar_{tab_id}", use_container_width=True):
                    forzar_actualizacion_memoria(conn)
                    st.rerun()
            
            if not df_mostrar.empty:
                with st.container():
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        filtro_nombre = st.selectbox("🔍 Colaborador:", options=["VER TODOS"] + sorted(df_mostrar['TECNICO'].unique().tolist()), key=f"filtro_nom_{tab_id}")
                    with col2:
