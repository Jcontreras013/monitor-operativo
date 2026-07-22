import streamlit as st
import pandas as pd
import re
import os
from datetime import timedelta
from tools import (
    guardar_registro_calidad, 
    get_honduras_time, 
    normalizar_nombre_cruce,
    leer_espejo_gcs,
    guardar_auditoria_campo
)

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Módulo de encuestas, auditorías en campo (Operaciones / Instalaciones) y control de calidad en Google Sheets.")
    
    # === SOLUCIÓN: Buscar órdenes tanto pendientes como cerradas (excluyendo anuladas) ===
    df_evaluables = df_base[~df_base['ESTADO'].astype(str).str.upper().str.contains('ANULADA', na=False)].copy()
    
    if df_evaluables.empty:
        st.info("ℹ️ No hay órdenes registradas en el sistema para evaluar en este momento.")
        return

    # 1. BUSCADOR SIMPLE DE NÚMEROS DE ORDEN (Searchable por defecto)
    lista_ordenes = sorted(df_evaluables['NUM'].dropna().astype(str).unique().tolist())
    
    col_sel1, col_sel2 = st.columns([1, 2])
    with col_sel1:
        num_seleccionado = st.selectbox("🔍 Busque el Número de Orden (NUM):", lista_ordenes)
    
    # Extraer fila correspondiente a la orden seleccionada
    row_sel = df_evaluables[df_evaluables['NUM'].astype(str) == num_seleccionado].iloc[0]
    
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
    for col in df_evaluables.columns:
        if any(k in str(col).upper() for k in ['FTTX', 'DISPOSITIVO', 'OLT', 'INFO']):
            olt_val = str(row_sel.get(col, ''))
            break

    # Intentar obtener fecha de visita limpia
    fecha_liq_dt = pd.to_datetime(row_sel.get('HORA_LIQ', pd.NaT))
    fecha_visita_str = fecha_liq_dt.strftime('%d/%m/%Y') if pd.notnull(fecha_liq_dt) else get_honduras_time().strftime('%d/%m/%Y')

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

    # === SEPARACIÓN DE FLUJOS MEDIANTE CUATRO PESTAÑAS ===
    tab_llamada, tab_whatsapp, tab_campo, tab_historico = st.tabs([
        "📞 Registrar Gestión de Llamada", 
        "💬 Enviar Encuesta WhatsApp", 
        "🚙 Auditoría de Campo (Operaciones)",
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
                    st.text_input("Nombre del Cliente (Auto-rellenado):", value=nombre_cliente, disabled=True, key="call_cli_dis")
                    st.text_input("Número de Orden / Servicio:", value=f"ORD-{num_orden}", disabled=True, key="call_ord_dis")
                with col_gen2:
                    fecha_visita_input = st.text_input("Fecha de la Visita (DD/MM/AAAA):", value=fecha_visita_str, key="fv_input")
                    st.text_input("Nombre del Técnico (Auto-rellenado):", value=tecnico, disabled=True, key="call_tec_dis")
                
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
                observaciones_cliente = st.text_area("Comentarios u observaciones adicionales del cliente:", key="obs_cliente_call")
                
                st.divider()
                
                st.markdown("### 8️⃣ Visto Bueno y Cierre del Servicio")
                p11_visto_bueno = st.radio("11. ¿Autoriza usted que el técnico continúe con su siguiente instalación o visita, confirmando que el servicio quedó conforme?", ["Sí, otorgo mi visto bueno", "No"], horizontal=True)
                nombre_firma = st.text_input("Nombre de la persona que brinda la aceptación digital (Cliente o Responsable):", value=nombre_cliente, key="firma_call_input")
                hora_cierre = st.text_input("Hora de cierre del servicio:", value=get_honduras_time().strftime('%I:%M %p'), key="hora_c_call_input")
                
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
            form_falla = st.form(key="form_falla_llamada_erronea")
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
                
                saved = guardar_registro_calidad(conn, datos_envio)
                
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
    # PESTAÑA 3: AUDITORÍA TÉCNICA DE CAMPO (OPERACIONES E INSTALACIONES)
    # --------------------------------------------------------------------------
    with tab_campo:
        st.subheader("🚙 Auditoría Técnica en Campo (Supervisión Presencial)")
        st.caption("Formularios técnicos de control de calidad para ser completados por supervisores en el sitio de trabajo.")
        
        # Sub-pestañas para diferenciar Órdenes Varias de INSFIBRA
        subtab_varias, subtab_insfibra = st.tabs(["📋 Auditoría de Órdenes Varias", "🔌 Auditoría de Instalaciones (INSFIBRA)"])
        
        with subtab_varias:
            st.markdown("### 📋 Formulario para Órdenes Varias (Soporte, Mantenimiento, etc.)")
            # Vinculamos la llave del formulario al ID de la orden seleccionada para reiniciar el estado
            form_varias = st.form(key=f"form_auditoria_varias_{num_orden}")
            with form_varias:
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    st.text_input("Orden #:", value=num_orden, disabled=True, key=f"ord_varias_disabled_{num_orden}")
                    st.text_input("Código (Cliente ID):", value=cliente_id, disabled=True, key=f"cod_varias_disabled_{num_orden}")
                    st.text_input("Código Servicio (Actividad):", value=actividad, disabled=True, key=f"cs_varias_disabled_{num_orden}")
                    vineta_v = st.text_input("Viñeta:", placeholder="Ej: V-12345", key=f"vineta_varias_{num_orden}")
                with col_v2:
                    mufa_v = st.text_input("Mufa:", placeholder="Ej: MUFA-A", key=f"mufa_varias_{num_orden}")
                    metraje_v = st.number_input("Metraje (Meters):", min_value=0.0, value=0.0, step=1.0, key=f"metraje_varias_{num_orden}")
                    estetica_v = st.selectbox("Estética:", ["Excelente", "Aceptable", "Deficiente"], key=f"estetica_varias_{num_orden}")
                    ruta_v = st.text_input("Ruta de acometida:", placeholder="Ej: Poste 3 a Fachada", key=f"ruta_varias_{num_orden}")
                
                comentario_auditor_v = st.text_area("Comentario del auditor:", key=f"comentario_varias_{num_orden}")
                submit_varias = st.form_submit_button("💾 Guardar Auditoría (Órdenes Varias)")
                
            if submit_varias:
                datos_varias = {
                    "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "ORDEN_NUM": num_orden,
                    "CODIGO_CLIENTE": cliente_id,
                    "CODIGO_SERVICIO": actividad,
                    "VINETA": vineta_v,
                    "MUFA": mufa_v,
                    "METRAJE": metraje_v,
                    "ESTETICA": estetica_v,
                    "RUTA_ACOMETIDA": ruta_v,
                    "COMENTARIO_AUDITOR": comentario_auditor_v,
                    "SUPERVISOR": st.session_state.get('username', 'N/D')
                }
                exito_v = guardar_auditoria_campo(conn, datos_varias, "operaciones")
                if exito_v:
                    st.success("✅ ¡Auditoría de Órdenes Varias guardada con éxito en la pestaña 'Operaciones' de Google Sheets!")
                else:
                    st.error("❌ Error al guardar en Google Sheets. Por favor, asegúrese de crear la pestaña 'Operaciones'.")
                    
with subtab_insfibra:
            st.markdown("### 🔌 Formulario de Auditoría para Instalaciones (INSFIBRA)")
            
            # === CÁLCULO DE TIEMPO SUGERIDO (OPCIONAL COMO BASE, PERO TOTALMENTE EDITABLE) ===
            tiempo_invent_str = "---"
            if pd.notnull(row_sel.get('HORA_INI')):
                ini_naive = row_sel['HORA_INI'].replace(tzinfo=None) if hasattr(row_sel['HORA_INI'], 'tzinfo') and row_sel['HORA_INI'].tzinfo is not None else row_sel['HORA_INI']
                
                if pd.notnull(row_sel.get('HORA_LIQ')):
                    liq_naive = row_sel['HORA_LIQ'].replace(tzinfo=None) if hasattr(row_sel['HORA_LIQ'], 'tzinfo') and row_sel['HORA_LIQ'].tzinfo is not None else row_sel['HORA_LIQ']
                    mins_inv = int((liq_naive - ini_naive).total_seconds() / 60)
                    tiempo_invent_str = f"{mins_inv} minutos"
                else:
                    ahora_naive = get_honduras_time().replace(tzinfo=None)
                    mins_trans = int((ahora_naive - ini_naive).total_seconds() / 60)
                    tiempo_invent_str = f"{mins_trans} minutos"
            elif row_sel.get('TIEMPO_REAL') != "---":
                tiempo_invent_str = str(row_sel.get('TIEMPO_REAL'))
                
            form_insfibra = st.form(key=f"form_auditoria_insfibra_{num_orden}")
            with form_insfibra:
                col_i1, col_i2 = st.columns(2)
                with col_i1:
                    st.text_input("TÉCNICO:", value=tecnico, disabled=True, key=f"tec_ins_disabled_{num_orden}")
                    st.text_input("# ORDEN:", value=num_orden, disabled=True, key=f"ord_ins_disabled_{num_orden}")
                    st.text_input("CÓDIGO (Cliente ID):", value=cliente_id, disabled=True, key=f"cod_ins_disabled_{num_orden}")
                    st.text_input("CS (Actividad):", value=actividad, disabled=True, key=f"cs_ins_disabled_{num_orden}")
                    
                    # SE QUITÓ 'disabled=True' PARA PERMITIR LA EDICIÓN MANUAL
                    tiempo_invent_val = st.text_input("TIEMPO INVERTIDO:", value=tiempo_invent_str if tiempo_invent_str != "---" else "", key=f"time_ins_input_{num_orden}", placeholder="Ej: 45 minutos")
                with col_i2:
                    # SE CAMBIÓ DE selectbox A text_input PARA ESCRITURA MANUAL
                    tipo_fo = st.text_input("TIPO F.O.:", placeholder="Ej: Drop Flat 1 Hilo, ADSS 6 Hilos", key=f"tipo_fo_ins_{num_orden}")
                    
                    metros_fo = st.number_input("METROS F.O.:", min_value=0.0, value=0.0, step=1.0, key=f"metros_fo_ins_{num_orden}")
                    vineta_ins = st.text_input("VIÑETA:", placeholder="Ej: V-INS-99", key=f"vineta_ins_input_{num_orden}")
                    ruta_ins = st.text_input("RUTA ACOMETIDA:", placeholder="Ej: Caja de Distribución a ONT", key=f"ruta_ins_input_{num_orden}")
                    mufa_ins = st.text_input("MUFA:", placeholder="Ej: MUFA-INS", key=f"mufa_ins_input_{num_orden}")
                    
                comentario_auditor_ins = st.text_area("COMENTARIO DEL AUDITOR:", key=f"comentario_ins_input_{num_orden}")
                submit_ins = st.form_submit_button("💾 Guardar Auditoría de Instalación (INSFIBRA)")
                
            if submit_ins:
                datos_ins = {
                    "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "TECNICO": tecnico,
                    "ORDEN_NUM": num_orden,
                    "CODIGO_CLIENTE": cliente_id,
                    "CODIGO_SERVICIO": actividad,
                    "TIEMPO_INVERTIDO": tiempo_invent_val, # Almacena el valor escrito manualmente por el supervisor
                    "TIPO_FO": tipo_fo,                     # Almacena el tipo de fibra escrito manualmente
                    "METROS_FO": metros_fo,
                    "VINETA": vineta_ins,
                    "RUTA_ACOMETIDA": ruta_ins,
                    "MUFA": mufa_ins,
                    "COMENTARIO_AUDITOR": comentario_auditor_ins,
                    "SUPERVISOR": st.session_state.get('username', 'N/D')
                }
                exito_i = guardar_auditoria_campo(conn, datos_ins, "instalaciones")
                if exito_i:
                    st.success("✅ ¡Auditoría de Instalación guardada con éxito en la pestaña 'Instalaciones' de Google Sheets!")
                else:
                    st.error("❌ Error al guardar en Google Sheets. Por favor, asegúrese de crear la pestaña 'Instalaciones'.")
