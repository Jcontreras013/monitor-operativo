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
        logo_path = 'logo_monitor.png' if os.path.exists('logo_monitor.png') else 'logo.png'
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
    pdf.set
