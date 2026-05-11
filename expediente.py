import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime

# CONFIGURACIÓN DE TU API KEY (Sustitúyela por la tuya de freeimage.host)
API_KEY_FREEIMAGE = "AQUI_TU_API_KEY_DE_FREEIMAGE"

def mostrar_modulo_expedientes(conn, df_base):
    st.title("📁 Expedientes Disciplinarios")
    st.markdown("---")
    
    # --- 1. FORMULARIO DE REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=True):
        with st.form("form_incidencia", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                # Obtenemos técnicos de tu DF principal
                lista_tecnicos = sorted(df_base['TECNICO'].unique().tolist()) if 'TECNICO' in df_base.columns else []
                tecnico_sel = st.selectbox("👤 Seleccione al Técnico:", options=lista_tecnicos)
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", 
                                        ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                                         "Tiempos Muertos", "Mala Documentación", "Insubordinación", "Otro"])
            
            with col2:
                fecha_incidencia = st.date_input("📅 Fecha del Suceso:", value=datetime.now())
                archivo_evidencia = st.file_uploader("🖼️ Captura de Pantalla (Evidencia):", type=['png', 'jpg', 'jpeg'])

            comentario = st.text_area("📝 Comentario Detallado:", placeholder="Describa lo sucedido (horas, lugar, etc.)...")
            
            btn_guardar = st.form_submit_button("💾 Guardar en Expediente", use_container_width=True)
            
            if btn_guardar:
                if tecnico_sel and comentario:
                    url_imagen_subida = ""
                    
                    # Proceso de subida a la nube (Freeimage)
                    if archivo_evidencia is not None:
                        with st.spinner("Subiendo evidencia a la nube..."):
                            try:
                                img_bytes = archivo_evidencia.getvalue()
                                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                payload = {"key": API_KEY_FREEIMAGE, "action": "upload", "source": img_base64, "format": "json"}
                                res = requests.post("https://freeimage.host/api/1/upload", data=payload)
                                if res.status_code == 200:
                                    url_imagen_subida = res.json()["image"]["url"]
                            except Exception as e:
                                st.error(f"Error al subir imagen: {e}")

                    # Preparar fila para Google Sheets
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": tecnico_sel,
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_incidencia.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": url_imagen_subida
                    }])
                    
                    # Guardar en la pestaña 'Expedientes'
                    try:
                        df_exp_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                        df_final = pd.concat([df_exp_db, nueva_fila], ignore_index=True)
                        conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                        st.success(f"✅ Incidencia registrada para {tecnico_sel}")
                    except Exception as e:
                        st.error(f"Error al conectar con Google Sheets: {e}")
                else:
                    st.warning("⚠️ El técnico y el comentario son obligatorios.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- 2. VISOR DE EXPEDIENTES ---
    st.subheader("📜 Historial Disciplinario")
    try:
        df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
        if not df_view.empty:
            lista_tecs_hist = ["Ver Todos"] + sorted(df_view['TECNICO'].unique().tolist())
            filtro = st.selectbox("Filtrar por Técnico:", options=lista_tecs_hist)
            
            df_mostrar = df_view if filtro == "Ver Todos" else df_view[df_view['TECNICO'] == filtro]
            
            for _, row in df_mostrar.iloc[::-1].iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{row['TECNICO']}** - *{row['TIPO_FALTA']}*")
                        st.caption(f"Sucedió el: {row['FECHA_INCIDENCIA']} | Registrado: {row['FECHA_REGISTRO']}")
                        st.info(row['COMENTARIO'])
                    with c2:
                        url = str(row.get('URL_FOTO', ''))
                        if url.startswith('http'):
                            st.image(url, use_container_width=True)
                            st.markdown(f"[🔗 Link]({url})")
                        else:
                            st.caption("Sin evidencia")
                    st.divider()
        else:
            st.info("No hay registros previos.")
    except:
        st.warning("⚠️ Verifique que la pestaña 'Expedientes' exista en su archivo de Drive.")
