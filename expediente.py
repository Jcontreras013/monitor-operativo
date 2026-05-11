import streamlit as st
import pandas as pd
import requests
import base64
from datetime import datetime
import os
from tools import generar_pdf_memorandum # <--- AQUÍ IMPORTAMOS LA LÓGICA DE TOOLS

# ==============================================================================
# CONFIGURACIÓN: API KEY PARA GUARDAR FOTOS EN LA NUBE GRATUITA
# ==============================================================================
API_KEY_FREEIMAGE = "AQUI_TU_API_KEY_DE_FREEIMAGE"

def mostrar_modulo_expedientes(conn, df_base):
    st.title("📁 Gestión de Expedientes Disciplinarios")
    st.markdown("---")
    
    # --- 1. FORMULARIO DE REGISTRO ---
    with st.expander("➕ Registrar Nueva Incidencia / Falta", expanded=True):
        with st.form("form_incidencia", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                lista_tecnicos = sorted(df_base['TECNICO'].dropna().unique().tolist()) if 'TECNICO' in df_base.columns else []
                if "Todos" in lista_tecnicos:
                    lista_tecnicos.remove("Todos")
                    
                tecnico_sel = st.selectbox("👤 Seleccione al Técnico:", options=lista_tecnicos, help="Solo aparecerán los técnicos cargados en la base operativa del día.")
                tipo_falta = st.selectbox("🚫 Tipo de Falta:", 
                                        ["Exceso de Velocidad", "Llegada Tarde", "Abandono de Ruta", 
                                         "Tiempos Muertos", "Mala Documentación", "Insubordinación", 
                                         "Pérdida de Herramientas", "Sin Datos Móviles", "Falla de Protocolo de Seguridad", "Otro"])
            
            with col2:
                fecha_incidencia = st.date_input("📅 Fecha del Suceso:", value=datetime.now())
                archivo_evidencia = st.file_uploader("🖼️ Captura de Pantalla (Evidencia):", type=['png', 'jpg', 'jpeg'], help="Sube el pantallazo del GPS o Cepheus. Pesa cero en tu GitHub.")

            comentario = st.text_area("📝 Comentario Detallado:", placeholder="Describa con precisión lo sucedido (horas, ubicaciones, instrucciones ignoradas, etc.)...")
            
            btn_guardar = st.form_submit_button("💾 Guardar en Expediente Oficial", use_container_width=True)
            
            if btn_guardar:
                if tecnico_sel and comentario:
                    url_imagen_subida = ""
                    
                    if archivo_evidencia is not None:
                        with st.spinner("☁️ Subiendo evidencia a la nube segura..."):
                            try:
                                img_bytes = archivo_evidencia.getvalue()
                                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                                payload = {"key": API_KEY_FREEIMAGE, "action": "upload", "source": img_base64, "format": "json"}
                                res = requests.post("https://freeimage.host/api/1/upload", data=payload)
                                if res.status_code == 200:
                                    url_imagen_subida = res.json()["image"]["url"]
                                else:
                                    st.warning(f"No se pudo subir la imagen. Código de error: {res.status_code}. Revisa tu API Key. El registro se guardará solo con texto.")
                            except Exception as e:
                                st.error(f"Error técnico al subir imagen: {e}. Se guardará sin foto.")

                    # Agregamos automáticamente quién hizo el registro
                    supervisor_actual = st.session_state.get('usuario', 'Sistema')
                    
                    nueva_fila = pd.DataFrame([{
                        "FECHA_REGISTRO": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "TECNICO": tecnico_sel,
                        "TIPO_FALTA": tipo_falta,
                        "FECHA_INCIDENCIA": fecha_incidencia.strftime("%d/%m/%Y"),
                        "COMENTARIO": comentario,
                        "URL_FOTO": url_imagen_subida,
                        "SUPERVISOR": supervisor_actual 
                    }])
                    
                    with st.spinner("💾 Guardando en la base de datos central..."):
                        try:
                            df_exp_db = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
                            df_final = pd.concat([df_exp_db, nueva_fila], ignore_index=True)
                            conn.update(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", data=df_final)
                            st.success(f"✅ ¡Incidencia registrada exitosamente para el expediente de {tecnico_sel}!")
                        except Exception as e:
                            st.error(f"❌ Error al conectar con Google Sheets. Detalle: {e}")
                else:
                    st.warning("⚠️ El nombre del técnico y el comentario detallado son obligatorios para abrir un expediente.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- 2. VISOR DE EXPEDIENTES (HISTORIAL) ---
    st.subheader("📜 Historial Disciplinario Activo")
    st.caption("Filtre por técnico para ver su bitácora de faltas y evidencias. Use esto para fundamentar llamados de atención.")
    
    try:
        with st.spinner("Cargando expedientes..."):
            df_view = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Expedientes", ttl=0)
            
        if not df_view.empty:
            df_view = df_view.dropna(subset=['TECNICO', 'TIPO_FALTA'], how='all')
            lista_tecs_hist = ["Ver Todos"] + sorted(df_view['TECNICO'].astype(str).unique().tolist())
            filtro = st.selectbox("🔍 Buscar Expediente de Técnico:", options=lista_tecs_hist)
            
            df_mostrar = df_view if filtro == "Ver Todos" else df_view[df_view['TECNICO'] == filtro]
            
            if df_mostrar.empty:
                 st.info(f"No hay incidencias registradas en el historial de {filtro}.")
            else:
                for idx, row in df_mostrar.iloc[::-1].iterrows():
                    with st.container():
                        st.markdown("""<div style="background-color: #1A1D24; padding: 15px; border-radius: 8px; border-left: 4px solid #EF4444; margin-bottom: 10px;">""", unsafe_allow_html=True)
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(f"### 👨‍🔧 {row['TECNICO']}")
                            st.markdown(f"**🚫 Falta Reportada:** {row['TIPO_FALTA']}")
                            st.caption(f"**📅 Sucedió el:** {row['FECHA_INCIDENCIA']} | **⏳ Registrado en Sistema:** {row['FECHA_REGISTRO']} | **✍️ Por:** {row.get('SUPERVISOR', 'N/D')}")
                            st.info(f"**Detalle del Reporte:**\n\n{row['COMENTARIO']}")
                        with c2:
                            url = str(row.get('URL_FOTO', ''))
                            if url.startswith('http'):
                                st.image(url, use_container_width=True, caption="Evidencia Adjunta")
                                st.markdown(f"[🔍 Abrir Imagen Completa en Pestaña Nueva]({url})")
                            else:
                                st.markdown("<br><br>", unsafe_allow_html=True)
                                st.caption("📸 *No se adjuntó captura de pantalla para este incidente.*")
                                
                            # --- EL BOTÓN PARA GENERAR EL PDF USANDO TOOLS.PY ---
                            pdf_bytes = generar_pdf_memorandum(row)
                            nombre_archivo = f"Memorandum_{str(row.get('TECNICO', ''))[:10]}_{str(row.get('FECHA_INCIDENCIA', '')).replace('/', '')}.pdf".replace(" ", "_")
                            
                            st.download_button(
                                label="📄 Descargar Memo",
                                data=pdf_bytes,
                                file_name=nombre_archivo,
                                mime="application/pdf",
                                key=f"btn_pdf_{idx}",
                                use_container_width=True,
                                type="primary"
                            )
                        st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("La base de datos de expedientes está limpia. No hay registros previos.")
    except Exception as e:
        st.warning(f"⚠️ Error al cargar los expedientes: {e}")
