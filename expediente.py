import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta, timezone
import os
import tempfile
import time
from fpdf import FPDF
from streamlit_gsheets import GSheetsConnection

# ==============================================================================
# 1. UTILIDADES Y CONFIGURACIÓN
# ==============================================================================
def get_honduras_time():
    return datetime.now(timezone.utc) - timedelta(hours=6)

def sanitizar(texto):
    import unicodedata
    if pd.isna(texto) or texto is None:
        return "N/D"
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')

@st.cache_data(show_spinner=False, ttl=300)
def cargar_personal(filepath="personal_tecnico.txt"):
    try:
        if not os.path.exists(filepath):
            return []
        with open(filepath, 'r', encoding='utf-8') as f:
            nombres = [l.split(',')[0].strip().upper() for l in f if l.strip()]
        return sorted(list(set(nombres)))
    except:
        return []

# ==============================================================================
# 2. ESTILOS CSS PREMIUM
# ==============================================================================
def aplicar_estilos_premium():
    st.markdown("""
        <style>
        .metric-card {
            background: rgba(255,255,255,0.05);
            padding: 15px; border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.1); text-align: center;
        }
        .expediente-card {
            background-color: #1A1D24; padding: 15px; border-radius: 10px;
            border: 1px solid #2D2F39; margin-bottom: 10px;
        }
        .badge {
            padding: 2px 10px; border-radius: 20px;
            font-size: 10px; font-weight: bold; text-transform: uppercase;
        }
        .badge-rojo    { background-color: #9b111e; color: white; }
        .badge-azul    { background-color: #3b82f6; color: white; }
        .badge-naranja { background-color: #f57c00; color: white; }
        </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# 3. ACCESO A GOOGLE SHEETS (CORREGIDO Y SEGURO)
# ==============================================================================

COLUMNAS = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA",
            "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]

def _get_hoja(conn):
    """
    Obtiene la hoja de cálculo. Corregido para acceder al cliente
    de gspread correctamente según la versión actual de GSheetsConnection.
    """
    # Intentar obtener el cliente de gspread de forma robusta
    try:
        # En versiones recientes es conn._instance.client o directamente accesible vía session
        client = conn.client 
        doc = client.open_by_url(st.secrets["url_base_datos"])
        return doc.worksheet("Expedientes")
    except AttributeError:
        # Fallback para algunas versiones específicas de la librería
        doc = conn._connect().open_by_url(st.secrets["url_base_datos"])
        return doc.worksheet("Expedientes")

def leer_datos_frescos(conn):
    try:
        hoja = _get_hoja(conn)
        registros = hoja.get_all_records(default_blank="")
        
        if not registros:
            return pd.DataFrame(columns=COLUMNAS)

        df = pd.DataFrame(registros)
        # Limpieza de nombres de columnas a mayúsculas
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # Asegurar que las columnas existan
        for col in COLUMNAS:
            if col not in df.columns:
                df[col] = ""

        # Filtrar solo si el Técnico tiene datos y descartar filas vacías
        df = df[df['TECNICO'].astype(str).str.strip() != ""]
        return df.reset_index(drop=True)

    except Exception as e:
        st.error(f"❌ Error al leer Google Sheets: {e}")
        return pd.DataFrame(columns=COLUMNAS)

def guardar_registro(conn, nuevo_reg: dict):
    """
    Guarda el registro buscando la primera fila vacía pero
    asegurando que NUNCA sea antes de la fila 18.
    """
    hoja = _get_hoja(conn)
    fila_datos = [nuevo_reg.get(c, "") for c in COLUMNAS]
    
    # Obtener todos los valores de la columna A para contar filas ocupadas
    valores_col_a = hoja.col_values(1)
    primera_fila_libre = len(valores_col_a) + 1
    
    # REGLA: Si la fila libre es menor a 18, forzamos que sea la 18
    fila_destino = max(18, primera_fila_libre)
    
    # Usamos update para insertar en la fila específica o insert_row
    hoja.insert_row(fila_datos, index=fila_destino, value_input_option='USER_ENTERED')

def eliminar_registro(conn, fecha_registro_id: str) -> bool:
    """
    Elimina registros pero PROTEGE las filas 1 a 17.
    """
    try:
        hoja = _get_hoja(conn)
        todas_las_filas = hoja.get_all_values()
        
        fila_a_borrar = None
        # Empezamos a buscar desde la fila 18 (índice 17 en la lista)
        for i, fila in enumerate(todas_las_filas[17:], start=18):
            # Asumimos que Fecha_Registro es la columna 1 (A)
            if str(fila[0]).strip() == str(fecha_registro_id).strip():
                fila_a_borrar = i
                break # Borramos la primera coincidencia que encontremos de la 18 en adelante
        
        if fila_a_borrar:
            hoja.delete_rows(fila_a_borrar)
            return True
        return False
    except Exception as e:
        st.error(f"❌ Error al eliminar: {e}")
        return False

# ==============================================================================
# 4. GENERACIÓN DE PDF (MANTIENE TU CLASE)
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try: self.image('logo.png', 10, 6, 35)
            except: pass
        self.set_y(10); self.set_x(50); self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - CONTROL OPERATIVO", ln=True, align="R")
        self.set_draw_color(200, 200, 200); self.line(10, 22, 200, 22); self.ln(10)
    def footer(self):
        self.set_y(-15); self.set_font("Helvetica", "I", 8); self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def generar_pdf_memo(row) -> bytes:
    pdf = MemoPDF(); pdf.add_page()
    es_m = "MEDICA" in str(row.get('TIPO_FALTA', '')).upper()
    pdf.set_font("Helvetica", "B", 14); pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, "MEMORANDUM" if not es_m else "CONSTANCIA MEDICA", ln=True, align="C")
    pdf.ln(5); pdf.set_font("Helvetica", "B", 10); pdf.set_text_color(0, 0, 0)
    for k, v in [("Tecnico", row.get('TECNICO', '')), ("Motivo", row.get('TIPO_FALTA', '')), ("Fecha", row.get('FECHA_INCIDENCIA', ''))]:
        pdf.cell(40, 8, f" {k}:", border=1, fill=True); pdf.cell(150, 8, f" {sanitizar(v)}", border=1, ln=True)
    pdf.ln(5); pdf.multi_cell(0, 6, f"Comentario: {sanitizar(row.get('COMENTARIO', ''))}", border=1)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name); tmp.seek(0); data = tmp.read()
    os.unlink(tmp.name); return data

# ==============================================================================
# 5. MÓDULO PRINCIPAL
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base=None):
    aplicar_estilos_premium()
    supervisor = st.session_state.get('usuario_actual', st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'

    st.title("📁 Expedientes y Personal")

    # ── LECTURA DE DATOS ──────────────────
    df_full = leer_datos_frescos(conn)

    # ── MÉTRICAS ──────────────────────────
    m1, m2, m3 = st.columns(3)
    medicos_n = df_full['TIPO_FALTA'].astype(str).str.contains("MEDICA|MÉDICA", case=False).sum() if not df_full.empty else 0
    with m1: st.markdown(f'<div class="metric-card"><small>TOTAL</small><br><b>{len(df_full)}</b></div>', unsafe_allow_html=True)
    with m2: st.markdown(f'<div class="metric-card"><small>MÉDICOS</small><br><b>{medicos_n}</b></div>', unsafe_allow_html=True)
    with m3: st.markdown(f'<div class="metric-card"><small>FALTAS</small><br><b>{len(df_full)-medicos_n}</b></div>', unsafe_allow_html=True)

    # ── FORMULARIO ────────────────────────
    with st.expander("➕ REGISTRAR NUEVA INCIDENCIA", expanded=False):
        with st.form("f_nuevo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                tecnico = st.selectbox("Técnico *", options=["---"] + cargar_personal())
                motivo  = st.selectbox("Motivo *", ["Llegada Tarde", "Exceso de Velocidad", "Abandono de Ruta", "Incidencia Médica", "Otro"])
            with c2:
                fecha = st.date_input("Fecha Suceso *", value=get_honduras_time().date())
                fotos = st.file_uploader("Fotos", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)
            obs = st.text_area("Descripción de los hechos *")
            if st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True):
                if tecnico == "---" or not obs.strip():
                    st.error("⚠️ Complete campos obligatorios.")
                else:
                    try:
                        urls = []
                        if fotos:
                            for f in fotos:
                                resp = requests.post("https://freeimage.host/api/1/upload", data={"key": "6d207e02198a847aa98d0a2a901485a5", "action": "upload", "source": base64.b64encode(f.getvalue()).decode('utf-8'), "format": "json"})
                                if resp.status_code == 200: urls.append(resp.json()["image"]["url"])
                        
                        nuevo_reg = {
                            "FECHA_REGISTRO": get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO": tecnico, "TIPO_FALTA": motivo, "FECHA_INCIDENCIA": fecha.strftime("%d/%m/%Y"),
                            "COMENTARIO": obs.strip(), "URL_FOTO": ", ".join(urls), "SUPERVISOR": supervisor
                        }
                        guardar_registro(conn, nuevo_reg)
                        st.success("✅ Guardado en fila 18+ correctamente.")
                        time.sleep(1); st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

    # ── LISTADO Y FILTROS ─────────────────
    if not df_full.empty:
        st.markdown("---")
        # (Aquí puedes añadir tus selectbox de filtros f_tec, f_date, etc. tal cual los tenías)
        
        for _, row in df_full.iloc[::-1].iterrows():
            es_m = "MEDICA" in str(row.get('TIPO_FALTA')).upper()
            badge_class = "badge-azul" if es_m else "badge-naranja"
            
            st.markdown(f"""
            <div class="expediente-card">
                <span class="badge {badge_class}">{row.get('TIPO_FALTA','')}</span>
                <div style="display:flex; justify-content:space-between; margin-top:5px;">
                    <b>{row.get('TECNICO','')}</b> <small>{row.get('FECHA_INCIDENCIA','')}</small>
                </div>
                <p style="font-size:13px; color:#CBD5E1; margin-top:5px;">{row.get('COMENTARIO','')}</p>
                <small style="color:#64748B;">ID Registro: {row.get('FECHA_REGISTRO','')}</small>
            </div>
            """, unsafe_allow_html=True)
            
            c_p, c_f, c_e = st.columns(3)
            with c_p:
                st.download_button("📄 PDF", data=generar_pdf_memo(row), file_name=f"Exp_{row.get('TECNICO')}.pdf", key=f"pdf_{row.get('FECHA_REGISTRO')}")
            with c_f:
                if row.get('URL_FOTO'):
                    with st.popover("🖼️ Fotos"):
                        for u in str(row['URL_FOTO']).split(','): st.image(u.strip())
            with c_e:
                if es_admin:
                    if st.button("🗑️ Eliminar", key=f"del_{row.get('FECHA_REGISTRO')}"):
                        if eliminar_registro(conn, row.get('FECHA_REGISTRO')):
                            st.success("Eliminado")
                            time.sleep(0.5); st.rerun()
