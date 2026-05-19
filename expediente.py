import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime, timedelta, timezone
import os
import tempfile
import time
from fpdf import FPDF

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
# 2. ESTILOS CSS
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
# 3. ACCESO DIRECTO A GOOGLE SHEETS (SIN CACHÉ CONFLICTIVO)
# ==============================================================================

COLUMNAS = ["FECHA_REGISTRO", "TECNICO", "TIPO_FALTA",
            "FECHA_INCIDENCIA", "COMENTARIO", "URL_FOTO", "SUPERVISOR"]

def _get_hoja(conn):
    """Abre la hoja de Google Sheets sin caché, siempre fresca."""
    doc = conn.client.open_by_url(st.secrets["url_base_datos"])
    return doc.worksheet("Expedientes")

def leer_datos_frescos(conn):
    """
    Lee los datos directamente de Google Sheets usando get_all_records().
    Sin caché para que siempre refleje el estado real de la hoja.
    """
    try:
        hoja = _get_hoja(conn)
        registros = hoja.get_all_records(
            expected_headers=COLUMNAS,
            default_blank=""
        )
        if not registros:
            return pd.DataFrame(columns=COLUMNAS)

        df = pd.DataFrame(registros)
        df.columns = df.columns.astype(str).str.strip().str.upper()

        # Guardar el índice real en la hoja (fila 1 = cabecera → datos desde fila 2)
        # El orden de get_all_records() es igual al de la hoja, así que:
        df['_ROW_SHEET'] = range(2, len(df) + 2)

        # Filtrar filas vacías
        df = df[df['TECNICO'].astype(str).str.strip() != ""]
        return df.reset_index(drop=True)

    except Exception as e:
        st.error(f"❌ Error al leer Google Sheets: {e}")
        return pd.DataFrame(columns=COLUMNAS + ['_ROW_SHEET'])

def guardar_registro(conn, nuevo_reg: dict):
    """
    Agrega una fila al final de la hoja.
    Usa value_input_option='USER_ENTERED' para respetar fechas y formatos.
    """
    hoja = _get_hoja(conn)
    fila = [nuevo_reg.get(c, "") for c in COLUMNAS]
    hoja.append_row(fila, value_input_option='USER_ENTERED')

def eliminar_registro(conn, fecha_registro: str) -> bool:
    """
    Elimina la fila cuyo FECHA_REGISTRO coincida exactamente.
    Busca de abajo hacia arriba para mayor seguridad con duplicados.
    Devuelve True si encontró y eliminó la fila.
    """
    try:
        hoja = _get_hoja(conn)
        # Obtener solo la columna FECHA_REGISTRO (columna A asumiendo orden estándar)
        todas = hoja.get_all_records(expected_headers=COLUMNAS, default_blank="")
        fila_a_borrar = None
        for i, reg in enumerate(todas, start=2):  # fila 1 = cabecera
            if str(reg.get('FECHA_REGISTRO', '')).strip() == str(fecha_registro).strip():
                fila_a_borrar = i  # Sigue buscando por si hay duplicados; usa el último
        if fila_a_borrar:
            hoja.delete_rows(fila_a_borrar)
            return True
        return False
    except Exception as e:
        st.error(f"❌ Error al eliminar: {e}")
        return False

# ==============================================================================
# 4. LÓGICA DE PDF
# ==============================================================================
class MemoPDF(FPDF):
    def header(self):
        if os.path.exists('logo.png'):
            try:
                self.image('logo.png', 10, 6, 35)
            except:
                pass
        self.set_y(10)
        self.set_x(50)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "MAXCOM - CONTROL OPERATIVO", ln=True, align="R")
        self.set_draw_color(200, 200, 200)
        self.line(10, 22, 200, 22)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

def generar_pdf_memo(row) -> bytes:
    pdf = MemoPDF()
    pdf.add_page()
    es_m = "MEDICA" in str(row.get('TIPO_FALTA', '')).upper()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, "MEMORANDUM" if not es_m else "CONSTANCIA MEDICA", ln=True, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(0, 0, 0)
    for k, v in [("Tecnico", row.get('TECNICO', '')),
                 ("Motivo", row.get('TIPO_FALTA', '')),
                 ("Fecha", row.get('FECHA_INCIDENCIA', ''))]:
        pdf.cell(40, 8, f" {k}:", border=1, fill=True)
        pdf.cell(150, 8, f" {sanitizar(v)}", border=1, ln=True)
    pdf.ln(5)
    pdf.multi_cell(0, 6, f"Comentario: {sanitizar(row.get('COMENTARIO', ''))}", border=1)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

def generar_pdf_consolidado(df: pd.DataFrame) -> bytes:
    pdf = MemoPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "REPORTE DE EXPEDIENTES", ln=True, align="C")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(30, 8, " Fecha", border=1, fill=True)
    pdf.cell(50, 8, " Tecnico", border=1, fill=True)
    pdf.cell(110, 8, " Motivo", border=1, ln=True, fill=True)
    pdf.set_font("Helvetica", "", 8)
    for _, r in df.iterrows():
        pdf.cell(30, 7, sanitizar(r.get('FECHA_INCIDENCIA', '')), border=1)
        pdf.cell(50, 7, sanitizar(r.get('TECNICO', '')), border=1)
        pdf.cell(110, 7, sanitizar(r.get('TIPO_FALTA', '')), border=1, ln=True)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

# ==============================================================================
# 5. MÓDULO PRINCIPAL
# ==============================================================================
def mostrar_modulo_expedientes(conn, df_base=None):
    aplicar_estilos_premium()
    supervisor = st.session_state.get('usuario_actual',
                  st.session_state.get('username', 'Supervisor'))
    es_admin = st.session_state.get('rol_actual', '').lower() == 'admin'

    st.title("📁 Expedientes y Personal")

    # ── Forzar recarga si se pidió (post-guardar / post-eliminar) ──────────────
    if st.session_state.get('_recargar_expedientes', False):
        st.session_state['_recargar_expedientes'] = False
        # No hacemos nada más; el rerun ya ocurrió antes de llegar aquí.

    # ── LECTURA DE DATOS ───────────────────────────────────────────────────────
    with st.spinner("Cargando expedientes..."):
        df_full = leer_datos_frescos(conn)

    # ── MÉTRICAS ───────────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    mascara_medicos = df_full['TIPO_FALTA'].astype(str).str.contains(
        "MEDICA|MÉDICA", case=False, na=False)
    medicos_n = mascara_medicos.sum()
    with m1:
        st.markdown(f'<div class="metric-card"><small>TOTAL</small><br><b>{len(df_full)}</b></div>',
                    unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><small>MÉDICOS</small><br><b>{medicos_n}</b></div>',
                    unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric-card"><small>FALTAS</small><br><b>{len(df_full) - medicos_n}</b></div>',
                    unsafe_allow_html=True)

    # ── FORMULARIO DE REGISTRO ─────────────────────────────────────────────────
    with st.expander("➕ REGISTRAR NUEVA INCIDENCIA", expanded=False):
        with st.form("f_nuevo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                tecnico = st.selectbox("Técnico *", options=["---"] + cargar_personal())
                motivo  = st.selectbox("Motivo *", [
                    "Llegada Tarde", "Exceso de Velocidad",
                    "Abandono de Ruta", "Incidencia Médica", "Otro"
                ])
            with c2:
                fecha = st.date_input("Fecha Suceso *", value=get_honduras_time().date())
                fotos = st.file_uploader(
                    "Fotos (opcional)", type=['jpg', 'png', 'jpeg'],
                    accept_multiple_files=True
                )
            obs = st.text_area("Descripción de los hechos *")
            guardar = st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True)

        if guardar:
            if tecnico == "---" or not obs.strip():
                st.error("⚠️ Complete los campos obligatorios (Técnico y Descripción).")
            else:
                try:
                    with st.spinner("Subiendo fotos y guardando..."):
                        # Subir fotos
                        urls = []
                        for f in (fotos or []):
                            try:
                                resp = requests.post(
                                    "https://freeimage.host/api/1/upload",
                                    data={
                                        "key": "6d207e02198a847aa98d0a2a901485a5",
                                        "action": "upload",
                                        "source": base64.b64encode(f.getvalue()).decode('utf-8'),
                                        "format": "json"
                                    },
                                    timeout=15
                                )
                                if resp.status_code == 200:
                                    urls.append(resp.json()["image"]["url"])
                            except Exception as fe:
                                st.warning(f"No se pudo subir una foto: {fe}")

                        nuevo_reg = {
                            "FECHA_REGISTRO":    get_honduras_time().strftime("%d/%m/%Y %H:%M:%S"),
                            "TECNICO":           tecnico,
                            "TIPO_FALTA":        motivo,
                            "FECHA_INCIDENCIA":  fecha.strftime("%d/%m/%Y"),
                            "COMENTARIO":        obs.strip(),
                            "URL_FOTO":          ", ".join(urls),
                            "SUPERVISOR":        supervisor,
                        }

                        guardar_registro(conn, nuevo_reg)

                    st.success("✅ Registro guardado correctamente.")
                    time.sleep(0.8)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error al guardar en Google Sheets: {e}")

    # ── FILTROS ────────────────────────────────────────────────────────────────
    st.markdown("---")
    f1, f2 = st.columns(2)

    tecnicos_disponibles = sorted(df_full['TECNICO'].dropna().unique().tolist()) if not df_full.empty else []
    with f1:
        f_tec  = st.selectbox("🔍 Buscar Técnico", ["TODOS"] + tecnicos_disponibles)
        f_date = st.date_input(
            "📅 Rango de fechas",
            value=(
                get_honduras_time().date() - timedelta(days=60),
                get_honduras_time().date()
            )
        )
    with f2:
        f_tipo = st.selectbox("📋 Filtrar Tipo", ["Todos", "Llamado Atención", "Incidencia Médica"])
        if not df_full.empty:
            st.download_button(
                "📊 Reporte General PDF",
                data=generar_pdf_consolidado(df_full),
                file_name="Reporte_Expedientes.pdf",
                mime="application/pdf",
                use_container_width=True
            )

    # ── APLICAR FILTROS ────────────────────────────────────────────────────────
    df_f = df_full.copy()

    if f_tec != "TODOS":
        df_f = df_f[df_f['TECNICO'] == f_tec]

    if f_tipo == "Incidencia Médica":
        df_f = df_f[df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False, na=False)]
    elif f_tipo == "Llamado Atención":
        df_f = df_f[~df_f['TIPO_FALTA'].str.contains("MEDICA|MÉDICA", case=False, na=False)]

    if isinstance(f_date, (list, tuple)) and len(f_date) == 2:
        df_f['_DT'] = pd.to_datetime(
            df_f['FECHA_INCIDENCIA'], format='%d/%m/%Y', errors='coerce'
        ).dt.date
        df_f = df_f[
            (df_f['_DT'] >= f_date[0]) &
            (df_f['_DT'] <= f_date[1])
        ]

    # ── LISTADO ────────────────────────────────────────────────────────────────
    st.markdown(f"**{len(df_f)} registro(s) encontrado(s)**")

    if df_f.empty:
        st.info("ℹ️ No se encontraron registros con los filtros aplicados.")
    else:
        # Mostrar del más reciente al más antiguo
        for _, row in df_f.iloc[::-1].iterrows():
            es_m = "MEDICA" in str(row.get('TIPO_FALTA', '')).upper()
            badge_class = "badge-azul" if es_m else "badge-naranja"

            # Usar FECHA_REGISTRO como llave única para operaciones
            fecha_reg_key = str(row.get('FECHA_REGISTRO', ''))
            # Clave única para widgets de Streamlit
            widget_key = fecha_reg_key.replace("/", "").replace(":", "").replace(" ", "_")

            st.markdown(f"""
            <div class="expediente-card">
                <span class="badge {badge_class}">{row.get('TIPO_FALTA','')}</span>
                <div style="display:flex; justify-content:space-between; margin-top:5px;">
                    <b>{row.get('TECNICO','')}</b>
                    <small>{row.get('FECHA_INCIDENCIA','')}</small>
                </div>
                <p style="font-size:13px; color:#CBD5E1; margin-top:5px;">
                    {row.get('COMENTARIO','')}
                </p>
                <small style="color:#64748B;">Registrado: {fecha_reg_key} — Supervisor: {row.get('SUPERVISOR','')}</small>
            </div>
            """, unsafe_allow_html=True)

            c_b1, c_b2, c_b3 = st.columns(3)

            with c_b1:
                st.download_button(
                    "📄 Descargar PDF",
                    data=generar_pdf_memo(row),
                    file_name=f"Exp_{widget_key}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{widget_key}"
                )

            with c_b2:
                with st.popover("🖼️ Ver Fotos"):
                    url_foto = str(row.get('URL_FOTO', '')).strip()
                    if url_foto:
                        for u in url_foto.split(','):
                            u = u.strip()
                            if u:
                                st.image(u)
                    else:
                        st.write("Sin fotos adjuntas.")

            with c_b3:
                if es_admin:
                    # Confirmación en dos pasos para evitar borrados accidentales
                    confirm_key = f"confirm_del_{widget_key}"
                    if st.session_state.get(confirm_key, False):
                        col_si, col_no = st.columns(2)
                        with col_si:
                            if st.button("✅ Sí", key=f"si_{widget_key}", use_container_width=True):
                                with st.spinner("Eliminando..."):
                                    ok = eliminar_registro(conn, fecha_reg_key)
                                st.session_state[confirm_key] = False
                                if ok:
                                    st.success("Eliminado.")
                                else:
                                    st.error("No se encontró la fila.")
                                time.sleep(0.8)
                                st.rerun()
                        with col_no:
                            if st.button("❌ No", key=f"no_{widget_key}", use_container_width=True):
                                st.session_state[confirm_key] = False
                                st.rerun()
                    else:
                        if st.button("🗑️ Eliminar", key=f"del_{widget_key}", use_container_width=True):
                            st.session_state[confirm_key] = True
                            st.rerun()
