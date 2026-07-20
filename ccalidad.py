import streamlit as st
import pandas as pd
import re
import os
from datetime import timedelta
from tools import (
    guardar_registro_calidad, 
    get_honduras_time, 
    normalizar_nombre_cruce,
    leer_espejo_gcs
)

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Módulo de encuestas, satisfacción de clientes (CSAT) y auditoría técnica de órdenes cerradas.")
    
    # Filtrar órdenes cerradas (las evaluables)
    df_cerradas = df_base[df_base['ESTADO'].astype(str).str.upper() == 'CERRADA'].copy()
    
    if df_cerradas.empty:
        st.info("ℹ️ No hay órdenes cerradas en el sistema para evaluar en este momento.")
        return

    # 1. BUSCADOR SIMPLE DE NÚMEROS DE ORDEN (Searchable por defecto)
    lista_ordenes = sorted(df_cerradas['NUM'].dropna().astype(str).unique().tolist())
    
    col_sel1, col_sel2 = st.columns([1, 2])
    with col_sel1:
        num_seleccionado = st.selectbox("🔍 Busque el Número de Orden (NUM):", lista_ordenes)
    
    # Extraer fila correspondiente a la orden seleccionada
    row_sel = df_cerradas[df_cerradas['NUM'].astype(str) == num_seleccionado].iloc[0]
    
    # Cargar variables de la orden
    num_orden = row_sel.get('NUM', 'N/D')
    cliente_id = row_sel.get('CLIENTE', 'N/D')
    nombre_cliente = row_sel.get('NOMBRE', 'N/D')
    colonia = row_sel.get('COLONIA', 'N/D')
    tecnico = row_sel.get('TECNICO', 'N/D')
    actividad = row_sel.get('ACTIVIDAD', 'N/D')
    comentario_cierre = row_sel.get('COMENTARIO', '')
    
    # Extraer OLT / Telemetría si existe
    olt_val = ""
    for col in df_cerradas.columns:
        if any(k in str(col).upper() for k in ['FTTX', 'DISPOSITIVO', 'OLT', 'INFO']):
            olt_val = str(row_sel.get(col, ''))
            break

    st.markdown("---")
    
    # 2. CAMPOS AUTO-RELLENADOS AUTOMÁTICAMENTE
    st.subheader("📋 Datos del Servicio (Auto-rellenados)")
    
    col_auto1, col_auto2 = st.columns(2)
    with col_auto1:
        st.text_input("👤 Nombre del Cliente:", value=nombre_cliente, disabled=True)
        st.text_input("👨‍🔧 Técnico Responsable:", value=tecnico, disabled=True)
    with col_auto2:
        st.text_input("🛠️ Actividad Realizada:", value=actividad, disabled=True)
        st.text_input("📍 Localidad / Colonia:", value=colonia, disabled=True)
        
    with st.expander("💬 Ver Comentario de Cierre en Campo"):
        st.write(comentario_cierre if comentario_cierre else "Sin comentario registrado.")
        
    st.markdown("---")

    # === SEPARACIÓN DE FLUJOS MEDIANTE PESTAÑAS ===
    tab_llamada, tab_whatsapp, tab_historico = st.tabs([
        "📞 Registrar Gestión de Llamada", 
        "💬 Enviar Encuesta WhatsApp", 
        "📋 Histórico y Reportes"
    ])

    # --------------------------------------------------------------------------
    # PESTAÑA 1: REGISTRO DE LLAMADA TELEFÓNICA (CONTESTADA O FALLIDA)
    # --------------------------------------------------------------------------
    with tab_llamada:
        st.subheader("📞 Registro de Llamada Telefónica Post-Servicio")
        st.caption("Complete la encuesta de satisfacción mientras gestiona la llamada telefónica con el cliente.")
        
        contesto = st.radio("🚦 ¿El cliente contestó la llamada?", ["Sí, contestó", "No contestó / Buzón de voz", "Número apagado o fuera de servicio"], horizontal=True)
        
        if contesto == "Sí, contestó":
            form_llamada = st.form(key="form_encuesta_completa")
            with form_llamada:
                st.markdown("### 1️⃣ Datos Generales del Servicio")
                col_gen1, col_gen2 = st.columns(2)
                with col_gen1:
                    st.text_input("Nombre del Cliente:", value=nombre_cliente, disabled=True)
                    st.text_input("Número de Orden / Servicio:", value=f"ORD-{num_orden}", disabled=True)
                with col_gen2:
                    fecha_visita_input = st.text_input("Fecha de la Visita (DD/MM/AAAA):", value=row_sel.get('HORA_LIQ', get_honduras_time()).strftime('%d/%m/%Y') if pd.notnull(row_sel.get('HORA_LIQ')) else get_honduras_time().strftime('%d/%m/%Y'))
                    st.text_input("Nombre del Técnico:", value=tecnico, disabled=True)
                
                st.divider()
                
                st.markdown("### 2️⃣ Puntualidad y Presentación")
                p1_puntualidad = st.radio("1. ¿El técnico llegó dentro del horario acordado?", ["Sí", "No"], horizontal=True)
                p2_presentacion = st.radio("2. ¿El técnico se presentó de forma adecuada (uniforme, identificación y trato respetuoso)?", ["Excelente", "Bueno", "Regular", "Deficiente"], horizontal=True)
                
                st.divider()
                
                st.markdown("### 3️⃣ Ejecución del Trabajo")
                p3_explicacion = st.radio("3. ¿El técnico le explicó claramente el trabajo que iba a realizar?", ["Sí", "Parcialmente", "No"], horizontal=True)
                p4_corresponde = st.radio("4. ¿El trabajo realizado corresponde al servicio solicitado?", ["Sí", "No"], horizontal=True)
                p5_funcionando = st.radio("5. ¿El servicio quedó funcionando correctamente al momento de la entrega?", ["Sí", "No"], horizontal=True)
                motivo_no_funciona = st.text_input("Si respondió 'No' en la pregunta anterior, indique brevemente el motivo:", value="", placeholder="Escriba el motivo aquí...")
                
                st.divider()
                
                st.markdown("### 4️⃣ Orden, Limpieza y Cuidado")
                p6_limpieza = st.radio("6. ¿El área de trabajo quedó limpia y ordenada al finalizar?", ["Sí", "No"], horizontal=True)
                p7_cuidado = st.radio("7. ¿El técnico cuidó adecuadamente su propiedad y equipos?", ["Sí", "No"], horizontal=True)
                
                st.divider()
                
                st.markdown("### 5️⃣ Atención y Trato")
                p8_atencion = st.radio("8. ¿Cómo califica el trato y la atención brindada por el técnico?", ["Excelente", "Bueno", "Regular", "Deficiente"], horizontal=True)
                
                st.divider()
                
                st.markdown("### 6️⃣ Satisfacción General")
                p9_satisfaccion = st.radio("9. En general, ¿qué tan satisfecho(a) está con el servicio recibido?", ["Muy satisfecho", "Satisfecho", "Poco satisfecho", "Insatisfecho"], horizontal=True)
                p10_recomienda = st.radio("10. ¿En base al servicio recibido, recomendaría el servicio de MAXCOM a otras personas?", ["Sí", "No"], horizontal=True)
                
                st.divider()
                
                st.markdown("### 7️⃣ Observaciones del Cliente (Opcional)")
                observaciones_cliente = st.text_area("Comentarios u observaciones adicionales del cliente:")
                
                st.divider()
                
                st.markdown("### 8️⃣ Visto Bueno y Cierre del Servicio")
                p11_visto_bueno = st.radio("11. ¿Autoriza usted que el técnico continúe con su siguiente instalación o visita, confirmando que el servicio quedó conforme?", ["Sí, otorgo mi visto bueno", "No"], horizontal=True)
                nombre_firma = st.text_input("Nombre de la persona que brinda la aceptación digital (Cliente o Responsable):", value=nombre_cliente)
                hora_cierre = st.text_input("Hora de cierre del servicio:", value=get_honduras_time().strftime('%I:%M %p'))
                
                st.divider()
                
                st.markdown("### 💼 Uso Operativo Interno (Exclusivo de Calidad)")
                evaluacion_interna = st.selectbox(
                    "Estado de Aprobación del Servicio (Recomendación Operativa):",
                    ["Servicio aprobado", "Servicio con observaciones", "Servicio no aprobado – requiere seguimiento"]
                )
                
                submit_encuesta = st.form_submit_button("💾 Guardar Registro de Encuesta Completa")
                
            if submit_encuesta:
                datos_completos = {
                    "FECHA_GESTION": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "TICKET": f"ORD-{num_orden}",
                    "CLIENTE_ID": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "FECHA_VISITA": fecha_visita_input,
                    "PUNTUALIDAD_HORARIO": p1_puntualidad,
                    "PRESENTACION_TRATO": p2_presentacion,
                    "EXPLICACION_TRABAJO": p3_explicacion,
                    "CORRESPONDE_SERVICIO": p4_corresponde,
                    "FUNCIONANDO_CORRECTAMENTE": p5_funcionando,
                    "MOTIVO_FALLA_SERVICIO": motivo_no_funciona if p5_funcionando == "No" else "N/A",
                    "ORDEN_LIMPIEZA": p6_limpieza,
                    "CUIDADO_PROPIEDAD": p7_cuidado,
                    "CALIFICACION_ATENCION": p8_atencion,
                    "SATISFACCION_GENERAL": p9_satisfaccion,
                    "RECOMENDARIA_MAXCOM": p10_recomienda,
                    "OBSERVACIONES_CLIENTE": observaciones_cliente if observaciones_cliente.strip() else "Ninguna",
                    "AUTORIZA_SIGUIENTE_VISITA": p11_visto_bueno,
                    "ACEPTACION_DIGITAL": nombre_firma,
                    "HORA_CIERRE_SERVICIO": hora_cierre,
                    "APROBACION_INTERNA": evaluacion_interna,
                    "METODO_AUDITORIA": "Llamada Telefónica Completada"
                }
                
                exito = guardar_registro_calidad(conn, datos_completos)
                if exito:
                    st.success(f"✅ ¡Encuesta de Satisfacción guardada exitosamente en la base de datos de Google Sheets para la ORD-{num_orden}!")
                else:
                    st.error("❌ Error al guardar el registro en Google Sheets. Por favor, asegúrese de crear la pestaña 'Calidad' en su hoja de cálculo.")
                    
        else:
            # Flujo de llamada fallida (No contestó)
            form_falla = st.form(key="form_llamada_fallida")
            with form_falla:
                st.markdown("### ⚠️ Registro de Intento de Llamada Fallida")
                st.info(f"Se registrará una constancia de llamada fallida para la orden ORD-{num_orden} asignada a {tecnico}.")
                observaciones_falla = st.text_area("Detalle de la gestión (Buzón, apagado, etc.):", value=f"Se llamó al cliente. Estado: {contesto}.")
                submit_falla = st.form_submit_button("💾 Registrar Intento Fallido")
                
            if submit_falla:
                datos_falla = {
                    "FECHA_GESTION": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "TICKET": f"ORD-{num_orden}",
                    "CLIENTE_ID": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "FECHA_VISITA": fecha_visita_str,
                    "PUNTUALIDAD_HORARIO": "N/A",
                    "PRESENTACION_TRATO": "N/A",
                    "EXPLICACION_TRABAJO": "N/A",
                    "CORRESPONDE_SERVICIO": "N/A",
                    "FUNCIONANDO_CORRECTAMENTE": "N/A",
                    "MOTIVO_FALLA_SERVICIO": "N/A",
                    "ORDEN_LIMPIEZA": "N/A",
                    "CUIDADO_PROPIEDAD": "N/A",
                    "CALIFICACION_ATENCION": "N/A",
                    "SATISFACCION_GENERAL": "N/A",
                    "RECOMENDARIA_MAXCOM": "N/A",
                    "OBSERVACIONES_CLIENTE": "Llamada no contestada",
                    "AUTORIZA_SIGUIENTE_VISITA": "N/A",
                    "ACEPTACION_DIGITAL": "N/A",
                    "HORA_CIERRE_SERVICIO": "N/A",
                    "APROBACION_INTERNA": "Servicio no aprobado – requiere seguimiento",
                    "METODO_AUDITORIA": f"Intento Fallido - {contesto}"
                }
                
                exito = guardar_registro_calidad(conn, datos_falla)
                if exito:
                    st.success(f"📝 ¡Intento fallido registrado correctamente en Google Sheets para la ORD-{num_orden}!")
                else:
                    st.error("❌ Error al guardar el registro del intento en la base de datos.")

    # --------------------------------------------------------------------------
    # PESTAÑA 2: ENVÍO AUTOMÁTICO DE ENCUESTA DIGITAL POR WHATSAPP (WATI)
    # --------------------------------------------------------------------------
    with tab_whatsapp:
        st.subheader("💬 Envío Automático mediante WATI (WhatsApp Business API)")
        st.caption("Esta pestaña registra el envío en el historial del sistema y dispara de forma automatizada la plantilla de encuesta oficial de WATI.")
        
        telefono_wa = st.text_input("📞 Ingrese el número de WhatsApp del Cliente:", value="", placeholder="Ej: 99887766", key="tel_wa_QA_input")
        comentarios_envio = st.text_area("📝 Comentarios o Notas de Envío (Opcional):", placeholder="Notas internas sobre el envío del WhatsApp...")
        
        st.markdown("<br>", unsafe_allow_html=True)
        col_wa1, col_wa2 = st.columns(2)
        
        with col_wa1:
            btn_disparar_bot = st.button("🚀 ENVIAR ENCUESTA OFICIAL POR WATI", use_container_width=True, type="primary")
            
        if btn_disparar_bot:
            if not telefono_wa.strip():
                st.error("❌ Ingrese el número de teléfono para disparar la encuesta.")
            else:
                datos_envio = {
                    "FECHA_GESTION": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "TICKET": f"ORD-{num_orden}",
                    "CLIENTE_ID": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "CSAT": "Pendiente",
                    "NPS": "Pendiente",
                    "ESTETICA": "Pendiente",
                    "LIMPIEZA": "Pendiente",
                    "POTENCIA_DBM": "N/D",
                    "TELEFONO": telefono_wa,
                    "TIPO_AUDITORIA": "Encuesta Digital Enviada (WATI)",
                    "COMENTARIOS": f"Se envió la encuesta por WhatsApp de forma automática usando WATI. Notas internas: {comentarios_envio}"
                }
                
                # 1. Guardar en base de datos (GSheets / GCS)
                saved = guardar_registro_calidad(conn, datos_envio)
                
                # 2. Disparar señal a WATI vía API REST
                with st.spinner("🚀 Conectando con los servidores de WATI..."):
                    from tools import disparar_encuesta_wati
                    wati_ok = disparar_encuesta_wati(datos_envio)
                
                if saved:
                    st.success(f"💾 Registro de envío guardado correctamente en la base de datos de Calidad.")
                    
                if wati_ok:
                    st.success(f"🚀 ¡Envío Exitoso! La plantilla oficial fue autorizada por WATI y se enviará automáticamente al {telefono_wa}.")
                else:
                    st.info("ℹ️ Señal automática no enviada (Las credenciales de WATI o el nombre de la plantilla no están configuradas en st.secrets).")

    # --------------------------------------------------------------------------
    # PESTAÑA 3: HISTORIAL, REPORTE EN PDF Y ELIMINACIÓN DE REGISTROS
    # --------------------------------------------------------------------------
    with tab_historico:
        st.subheader("📋 Histórico de Auditorías de Calidad y Satisfacción")
        st.caption("Consulte todas las encuestas y gestiones guardadas en su base de datos.")
        
        # Intentar leer desde Google Sheets (Worksheet='Calidad')
        try:
            df_qa = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Calidad", ttl=0)
        except Exception:
            df_qa = None
            
        if df_qa is None or df_qa.empty:
            # Fallback en caso de que esté vacía la pestaña o falle la conexión, intentar leer de GCS
            df_qa = leer_espejo_gcs("jovial-trilogy-306216.appspot.com", "calidad_maestro.csv")
            
        if df_qa is None or df_qa.empty:
            st.info("ℹ️ Aún no se han registrado encuestas de calidad o gestiones telefónicas en el sistema.")
        else:
            # Normalizar columnas a mayúsculas
            df_qa.columns = df_qa.columns.astype(str).str.upper().str.strip()
            
            # 1. FILTRADO POR RANGO DE FECHAS
            st.markdown("#### 📅 Filtrar por Rango de Fechas")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                hoy_hx = get_honduras_time().date()
                rango_sel = st.date_input("Seleccione el periodo a consultar:", value=(hoy_hx - timedelta(days=7), hoy_hx), key="rango_calidad_picker")
            
            # Convertir fechas de forma segura para realizar el filtro
            df_qa['FECHA_DT'] = pd.to_datetime(df_qa['FECHA_GESTION'], errors='coerce')
            df_qa = df_qa.dropna(subset=['FECHA_DT'])
            
            if len(rango_sel) == 2:
                ini_d, fin_d = rango_sel
                df_filtered = df_qa[(df_qa['FECHA_DT'].dt.date >= ini_d) & (df_qa['FECHA_DT'].dt.date <= fin_d)].copy()
            else:
                ini_d = rango_sel[0]
                df_filtered = df_qa[df_qa['FECHA_DT'].dt.date == ini_d].copy()
                
            if df_filtered.empty:
                st.warning("⚠️ No se encontraron registros de calidad para el rango de fechas seleccionado.")
            else:
                # Mostrar el DataFrame de forma ejecutiva omitiendo la columna datetime interna
                cols_mostrar = [c for c in df_filtered.columns if c not in ['FECHA_DT']]
                st.dataframe(df_filtered[cols_mostrar], use_container_width=True, hide_index=True)
                
                st.markdown("---")
                
                # 2. GENERACIÓN DE REPORTE EN FORMATO PDF
                st.markdown("#### 📥 Exportación de Reporte en PDF")
                col_pdf1, col_pdf2 = st.columns([1, 2])
                with col_pdf1:
                    if st.button("📄 GENERAR REPORTE PDF DE CALIDAD", use_container_width=True, type="primary"):
                        with st.spinner("Preparando archivo de reporte..."):
                            from tools import generar_pdf_reporte_calidad
                            # Generar los bytes del PDF invocando la lógica en tools.py
                            st.session_state['pdf_calidad_data'] = generar_pdf_reporte_calidad(
                                df_filtered, 
                                ini_d, 
                                fin_d if 'fin_d' in locals() else ini_d
                            )
                            
                    if 'pdf_calidad_data' in st.session_state and st.session_state['pdf_calidad_data'] is not None:
                        st.download_button(
                            label="📥 DESCARGAR REPORTE EN PDF",
                            data=st.session_state['pdf_calidad_data'],
                            file_name=f"Reporte_Calidad_{ini_d}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                        
                st.markdown("---")
                
                # 3. SECCIÓN DE ELIMINACIÓN DE REGISTROS (Poder eliminarlos)
                st.markdown("#### 🗑️ Eliminación de Registros (Uso exclusivo Gerencia)")
                st.caption("Seleccione un registro del histórico para eliminarlo de forma permanente tanto de Google Sheets como de GCS.")
                
                # Crear columna descriptiva para que el usuario elija con precisión
                df_filtered['OPCION_ELIMINAR'] = df_filtered['TICKET'].astype(str) + " - " + df_filtered['NOMBRE_CLIENTE'].astype(str) + " (" + df_filtered['FECHA_GESTION'].astype(str) + ")"
                lista_eliminar_ops = ["---"] + df_filtered['OPCION_ELIMINAR'].tolist()
                
                registro_a_borrar = st.selectbox("Seleccione el registro que desea eliminar permanentemente:", lista_eliminar_ops)
                
                if registro_a_borrar != "---":
                    row_eliminar = df_filtered[df_filtered['OPCION_ELIMINAR'] == registro_a_borrar].iloc[0]
                    ticket_del = row_eliminar['TICKET']
                    fecha_del = row_eliminar['FECHA_GESTION']
                    
                    col_del1, col_del2 = st.columns([1, 2])
                    with col_del1:
                        confirmar_del = st.button("🚨 ELIMINAR REGISTRO SELECCIONADO", use_container_width=True, type="primary")
                        
                    if confirmar_del:
                        from tools import eliminar_registro_calidad
                        with st.spinner("Eliminando el registro de las bases de datos..."):
                            exito_del = eliminar_registro_calidad(conn, ticket_del, fecha_del)
                            
                        if exito_del:
                            st.success(f"✅ ¡El registro correspondiente a la {ticket_del} ha sido eliminado con éxito de Google Sheets y GCS!")
                            # Limpiar estados de descarga y recargar
                            if 'pdf_calidad_data' in st.session_state:
                                del st.session_state['pdf_calidad_data']
                            import time
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error("❌ Error al intentar eliminar el registro.")
