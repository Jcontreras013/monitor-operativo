# ==============================================================================
# CLIENTES VIP
# ==============================================================================
# La lista vive en la hoja "VIP" de la base de datos (Google Sheets) y se carga desde
# Configuración. NUNCA en el repositorio (es público): el Excel original trae
# correos y teléfonos de clientes. De ese archivo solo se guardan código,
# nombre y clase, que es lo único que hace falta para marcar las órdenes.
#
# La usan: el Monitor en Vivo (panel de órdenes abiertas VIP) y sync_job.py
# (aviso por correo cuando se abre una orden nueva de un cliente VIP).
import io

import pandas as pd
import streamlit as st

HOJA_VIP = "VIP"
COLUMNAS_VIP = ["CLIENTE", "NOMBRE", "CLASE"]


def normalizar_codigos(serie):
    """Código de cliente como texto sin '.0' (Sheets/Excel lo devuelven como número)."""
    return serie.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def leer_archivo_vip(archivo):
    """
    Lee el Excel/CSV de clientes VIP y devuelve solo CLIENTE, NOMBRE, CLASE.
    Busca la hoja que tenga una columna CLIENTE (el archivo puede traer hojas
    vacías o con otro nombre).
    """
    nombre = str(getattr(archivo, "name", "")).lower()
    datos = archivo.getvalue()
    if nombre.endswith(".csv"):
        try:
            hojas = {"csv": pd.read_csv(io.BytesIO(datos), dtype=str)}
        except UnicodeDecodeError:
            hojas = {"csv": pd.read_csv(io.BytesIO(datos), dtype=str, encoding="latin1")}
    else:
        hojas = pd.read_excel(io.BytesIO(datos), sheet_name=None, dtype=str)

    for df in hojas.values():
        columnas = {str(c).strip().upper(): c for c in df.columns}
        if "CLIENTE" not in columnas:
            continue
        col_nombre = next((columnas[c] for c in ("NOMBRE", "NOMBRE CLIENTE", "RAZON SOCIAL") if c in columnas), None)
        col_clase = next((columnas[c] for c in ("CLASE CLIENTE", "CLASE") if c in columnas), None)
        vip = pd.DataFrame({
            "CLIENTE": normalizar_codigos(df[columnas["CLIENTE"]]),
            "NOMBRE": df[col_nombre].astype(str).str.strip() if col_nombre else "",
            "CLASE": df[col_clase].astype(str).str.strip() if col_clase else "",
        }).replace({"nan": "", "None": ""})
        vip = vip[vip["CLIENTE"].str.fullmatch(r"\d+")]
        return vip.drop_duplicates("CLIENTE").reset_index(drop=True)
    raise ValueError("El archivo no tiene una columna llamada CLIENTE con los códigos de cliente.")


@st.cache_data(ttl=600, show_spinner=False)
def _cargar_vip_cache(_conn):
    try:
        url = st.secrets["url_base_datos"]
        df = _conn.read(spreadsheet=url, worksheet=HOJA_VIP, ttl=0)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_VIP)
    if df is None or df.empty or "CLIENTE" not in df.columns:
        return pd.DataFrame(columns=COLUMNAS_VIP)
    df = df.dropna(how="all")
    for c in COLUMNAS_VIP:
        if c not in df.columns:
            df[c] = ""
    df["CLIENTE"] = normalizar_codigos(df["CLIENTE"])
    return df[COLUMNAS_VIP].fillna("")


def cargar_clientes_vip(conn):
    if conn is None:
        return pd.DataFrame(columns=COLUMNAS_VIP)
    return _cargar_vip_cache(conn)


def guardar_clientes_vip(conn, df):
    """Reemplaza la lista completa en la hoja VIP (la crea si no existe)."""
    url = st.secrets["url_base_datos"]
    df = df[COLUMNAS_VIP].astype(str)
    try:
        conn.update(spreadsheet=url, worksheet=HOJA_VIP, data=df)
    except Exception:
        conn.create(spreadsheet=url, worksheet=HOJA_VIP, data=df)
    _cargar_vip_cache.clear()


def marcar_ordenes_vip(df_ordenes, df_vip):
    """Órdenes de df_ordenes cuyo CLIENTE está en la lista VIP, con NOMBRE_VIP y CLASE_VIP."""
    if df_ordenes is None or df_ordenes.empty or df_vip.empty or "CLIENTE" not in df_ordenes.columns:
        return pd.DataFrame()
    vip = df_vip.drop_duplicates("CLIENTE").set_index("CLIENTE")
    df = df_ordenes[normalizar_codigos(df_ordenes["CLIENTE"]).isin(vip.index).values].copy()
    codigos = normalizar_codigos(df["CLIENTE"])
    df["NOMBRE_VIP"] = codigos.map(vip["NOMBRE"]).values
    df["CLASE_VIP"] = codigos.map(vip["CLASE"]).values
    return df


# ==============================================================================
# AVISO DE ÓRDENES NUEVAS (lo usa sync_job.py en cada ciclo)
# ==============================================================================
def seleccionar_ordenes_vip_nuevas(df_ordenes, df_vip, ya_avisadas, ahora, horas=24):
    """
    Órdenes VIP abiertas en las últimas `horas` que no se hayan avisado.
    La ventana evita que, al activar el aviso, lleguen de golpe todas las
    órdenes viejas de clientes VIP que siguen en la consulta de 55 días.
    """
    df = marcar_ordenes_vip(df_ordenes, df_vip)
    if df.empty or "NUM" not in df.columns or "FECHA_APE" not in df.columns:
        return pd.DataFrame()
    df["NUM"] = normalizar_codigos(df["NUM"])
    apertura = pd.to_datetime(df["FECHA_APE"], errors="coerce")
    recientes = apertura >= pd.Timestamp(ahora) - pd.Timedelta(hours=horas)
    nuevas = df[recientes & ~df["NUM"].isin(set(ya_avisadas)) & (df["NUM"] != "N/D")]
    return nuevas.drop_duplicates("NUM")


def armar_correo_vip(df_nuevas):
    """Devuelve (asunto, texto, html) del aviso de órdenes nuevas VIP."""
    from notificaciones import tabla_html

    if len(df_nuevas) == 1:
        asunto = f"⭐ Orden nueva de cliente VIP: {df_nuevas['NOMBRE_VIP'].iloc[0]}"
    else:
        asunto = f"⭐ {len(df_nuevas)} órdenes nuevas de clientes VIP"
    columnas = {
        "NUM": "Orden", "CLIENTE": "Cliente", "NOMBRE_VIP": "Nombre", "CLASE_VIP": "Clase",
        "ACTIVIDAD": "Actividad", "ESTADO": "Estado", "TECNICO": "Técnico",
        "FECHA_APE": "Apertura", "COLONIA": "Colonia", "COMENTARIO": "Comentario de apertura",
    }
    tabla = df_nuevas[[c for c in columnas if c in df_nuevas.columns]].rename(columns=columnas)
    if "Apertura" in tabla.columns:
        tabla["Apertura"] = pd.to_datetime(tabla["Apertura"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
    texto = "Se abrieron órdenes para clientes VIP:\n\n" + "\n".join(
        " | ".join(f"{k}: {v}" for k, v in fila.items()) for fila in tabla.fillna("").to_dict("records")
    ) + "\n\nMonitor Operativo MAXCOM - aviso automático de clientes VIP"
    cuerpo_html = (
        '<div style="font-family:Arial,sans-serif;font-size:13px;">'
        "<p>Se abrieron órdenes para <b>clientes VIP</b>:</p>"
        f"{tabla_html(tabla)}"
        '<p style="color:#666;font-size:11px;">Monitor Operativo MAXCOM · aviso automático. '
        "Cada orden se avisa una sola vez.</p></div>"
    )
    return asunto, texto, cuerpo_html


# ==============================================================================
# INTERFAZ
# ==============================================================================
def mostrar_panel_vip_monitor(conn, df_vivas):
    """Aviso arriba del Monitor en Vivo con las órdenes abiertas de clientes VIP."""
    df_vip_abiertas = marcar_ordenes_vip(df_vivas, cargar_clientes_vip(conn))
    if df_vip_abiertas.empty:
        return
    columnas = [c for c in ["NUM", "CLIENTE", "NOMBRE_VIP", "CLASE_VIP", "ACTIVIDAD", "ESTADO",
                            "TECNICO", "FECHA_APE", "DIAS_RETRASO", "COLONIA"] if c in df_vip_abiertas.columns]
    if "FECHA_APE" in df_vip_abiertas.columns:
        df_vip_abiertas = df_vip_abiertas.sort_values("FECHA_APE", ascending=False)
    with st.container(border=True):
        st.warning(f"⭐ **{len(df_vip_abiertas)} orden(es) abierta(s) de clientes VIP** "
                   f"({df_vip_abiertas['CLIENTE'].nunique()} cliente(s)).")
        st.dataframe(df_vip_abiertas[columnas], use_container_width=True, hide_index=True)


def mostrar_admin_clientes_vip(conn):
    """Pestaña de Configuración para cargar o reemplazar la lista VIP."""
    st.subheader("⭐ Clientes VIP")
    st.caption(
        "Las órdenes abiertas de estos clientes se marcan arriba del Monitor en Vivo y, si el correo "
        "está configurado, el robot de sincronización avisa por correo cuando se abre una orden nueva. "
        "Se guarda en la hoja VIP de la base de datos, solo con código, nombre y clase: los correos y teléfonos de contacto no se guardan."
    )
    if conn is None:
        st.error("No hay conexión con Google Sheets.")
        return

    df_actual = cargar_clientes_vip(conn)
    st.metric("Clientes VIP cargados", len(df_actual))
    if not df_actual.empty:
        with st.expander("Ver lista actual"):
            st.dataframe(df_actual, use_container_width=True, hide_index=True)

    archivo = st.file_uploader(
        "Subir lista de clientes VIP (Excel o CSV con una columna CLIENTE)",
        type=["xlsx", "xls", "csv"], key="up_clientes_vip",
    )
    if archivo is None:
        return
    try:
        df_nuevo = leer_archivo_vip(archivo)
    except Exception as e:
        st.error(f"❌ No se pudo leer el archivo: {e}")
        return

    antes, despues = set(df_actual["CLIENTE"]), set(df_nuevo["CLIENTE"])
    st.info(
        f"El archivo trae **{len(df_nuevo)}** clientes: {len(despues - antes)} nuevo(s) y "
        f"{len(antes - despues)} que salen de la lista. La lista actual se reemplaza completa."
    )
    st.dataframe(df_nuevo, use_container_width=True, hide_index=True)
    if st.button("💾 Reemplazar lista VIP", type="primary", key="btn_guardar_vip"):
        try:
            guardar_clientes_vip(conn, df_nuevo)
            st.success(f"✅ Lista VIP guardada: {len(df_nuevo)} clientes.")
        except Exception as e:
            st.error(f"❌ No se pudo guardar en Google Sheets: {e}")
