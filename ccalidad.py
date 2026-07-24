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

    # ==============================================================================
    # CONTROL DE ACCESO BASADO EN ROLES Y USUARIOS
    # ==============================================================================
    usuario = str(st.session_state.get('usuario_actual', '')).strip().lower()

    # Definimos la lista de pestañas que se renderizarán según el perfil
    if usuario == "miguel":
        tabs_to_render = [
            "🚙 Auditoría de Campo (Operaciones)",
            "📋 Histórico y Reportes"
        ]
    elif usuario == "sac":
        tabs_to_render = [
            "📞 Registrar Gestión de Llamada", 
            "💬 Enviar Encuesta WhatsApp", 
            "📋 Histórico y Reportes"
        ]
    else:
        tabs_to_render = [
            "📞 Registrar Gestión de Llamada", 
            "💬 Enviar Encuesta WhatsApp", 
            "🚙 Auditoría de Campo (Operaciones)",
            "📋 Histórico y Reportes"
        ]

    rendered_tabs = st.tabs(tabs_to_render)

    # Iteramos dinámicamente sobre las pestañas generadas
    for tab, tab_name in zip(rendered_tabs, tabs_to_render):

        # --------------------------------------------------------------------------
        # FLUJO: REGISTRO DE LLAMADA TELEFÓNICA (CONTESTADA O FALLIDA)
        # --------------------------------------------------------------------------
        if "Llamada" in tab_name:
            with tab:
                st.subheader("📞 Registro de Llamada Telefónica Post-Servicio")
                st.caption("Complete la encuesta de satisfacción mientras gestiona la llamada telefónica con el cliente.")
                
                contesto = st.radio("🚦 ¿El cliente contestó la llamada?", ["Sí, contestó", "No contestó / Buzón de voz", "Número apagado o fuera de servicio"], horizontal=True, key="call_contesto_radio")
                
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
                        
                        st.markdown("### 2️⃣ Encuesta de Control de Calidad – Visita Técnica")
                        st.info("Califique cada aspecto de la visita técnica en una escala de 1 (Muy insatisfecho) a 5 (Muy satisfecho).")
                        
                        # Opciones visuales con estrellas para el operador
                        escala_estrellas = [
                            "1 ⭐ (Muy insatisfecho)", 
                            "2 ⭐⭐ (Insatisfecho)", 
                            "3 ⭐⭐⭐ (Regular)", 
                            "4 ⭐⭐⭐⭐ (Satisfecho)", 
                            "5 ⭐⭐⭐⭐⭐ (Muy satisfecho)"
                        ]
                        
                        p1_puntualidad = st.radio("1. Puntualidad del técnico", escala_estrellas, index=4, horizontal=True, key="p1_puntualidad_radio")
                        p2_presentacion = st.radio("2. Presentación y trato del técnico", escala_estrellas, index=4, horizontal=True, key="p2_presentacion_radio")
                        p3_claridad = st.radio("3. Claridad en la explicación del trabajo realizado", escala_estrellas, index=4, horizontal=True, key="p3_claridad_radio")
                        p4_tv_ccveo = st.radio("4. Explicación sobre el servicio de TV Cable y CCVEO", escala_estrellas, index=4, horizontal=True, key="p4_tv_ccveo_radio")
                        p5_calidad = st.radio("5. Calidad del servicio (instalación/mantenimiento)", escala_estrellas, index=4, horizontal=True, key="p5_calidad_radio")
                        p6_limpieza = st.radio("6. Estado en que dejó el área de trabajo", escala_estrellas, index=4, horizontal=True, key="p6_limpieza_radio")
                        p7_satisfaccion = st.radio("7. Nivel de satisfacción general con la visita", escala_estrellas, index=4, horizontal=True, key="p7_satisfaccion_radio")
                        
                        st.divider()
                        
                        st.markdown("### 3️⃣ Pregunta Opcional")
                        mejoras_opcional = st.text_area("¿Hay algo que podamos mejorar? (Respuesta corta):", key="mejoras_opcional_input")
                        
                        st.divider()
                        
                        st.markdown("### 4️⃣ Visto Bueno y Cierre de la Gestión")
                        nombre_firma = st.text_input("Nombre de la persona que brinda la aceptación digital (Cliente o Responsable):", value=nombre_cliente, key="firma_call_input")
                        hora_cierre = st.text_input("Hora de cierre del servicio:", value=get_honduras_time().strftime('%I:%M %p'), key="hora_c_call_input")
                        
                        st.divider()
                        
                        st.markdown("### 💼 Uso Operativo Interno (Exclusivo de Calidad)")
                        evaluacion_interna = st.selectbox(
                            "Estado de Aprobación del Servicio (Recomendación Operativa):",
                            ["Servicio aprobado", "Servicio con observaciones", "Servicio no aprobado – requiere seguimiento"],
                            key="eval_interna_select"
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
                            
                            # Extracción de valores numéricos de la escala (primer carácter)
                            "P1_PUNTUALIDAD": int(p1_puntualidad[0]),
                            "P2_PRESENTACION_TRATO": int(p2_presentacion[0]),
                            "P3_CLARIDAD_EXPLICACION": int(p3_claridad[0]),
                            "P4_EXPLICACION_TV_CCVEO": int(p4_tv_ccveo[0]),
                            "P5_CALIDAD_SERVICIO": int(p5_calidad[0]),
                            "P6_LIMPIEZA_TRABAJO": int(p6_limpieza[0]),
                            "P7_SATISFACCION_GENERAL": int(p7_satisfaccion[0]),
                            
                            "MEJORAS_OPCIONAL": mejoras_opcional if mejoras_opcional.strip() else "Ninguna",
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
                        observaciones_falla = st.text_area("Detalle de la gestión (Buzón, apagado, etc.):", value=f"Se llamó al cliente. Estado: {contesto}.", key="obs_falla_input")
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
                            
                            # Rellenamos con N/A en caso de que la llamada no se haya concretado
                            "P1_PUNTUALIDAD": "N/A",
                            "P2_PRESENTACION_TRATO": "N/A",
                            "P3_CLARIDAD_EXPLICACION": "N/A",
                            "P4_EXPLICACION_TV_CCVEO": "N/A",
                            "P5_CALIDAD_SERVICIO": "N/A",
                            "P6_LIMPIEZA_TRABAJO": "N/A",
                            "P7_SATISFACCION_GENERAL": "N/A",
                            
                            "MEJORAS_OPCIONAL": "Llamada no contestada",
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
        # FLUJO: ENVÍO AUTOMÁTICO DE ENCUESTA DIGITAL POR WHATSAPP (WATI)
        # --------------------------------------------------------------------------
        elif "WhatsApp" in tab_name:
            with tab:
                st.subheader("💬 Envío Automático mediante WATI (WhatsApp Business API)")
                st.caption("Esta pestaña registra el envío en el historial del sistema y dispara de forma automatizada la plantilla de encuesta oficial de WATI.")
                
                telefono_wa = st.text_input("📞 Ingrese el número de WhatsApp del Cliente:", value="", placeholder="Ej: 99887766", key="tel_wa_QA_input")
                comentarios_envio = st.text_area("📝 Comentarios o Notas de Envío (Opcional):", placeholder="Notas internas sobre el envío del WhatsApp...", key="comentarios_envio_wa_input")
                
                st.markdown("<br>", unsafe_allow_html=True)
                col_wa1, col_wa2 = st.columns(2)
                
                with col_wa1:
                    btn_disparar_bot = st.button("🚀 ENVIAR ENCUESTA OFICIAL POR WATI", use_container_width=True, type="primary", key="btn_disparar_wati_calidad")
                    
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
                            st.info("ℹ️ @WATI_OK: Señal automática no enviada (Las credenciales de WATI o el nombre de la plantilla no están configuradas en st.secrets).")

        # --------------------------------------------------------------------------
        # FLUJO: AUDITORÍA TÉCNICA DE CAMPO (OPERACIONES E INSTALACIONES)
        # --------------------------------------------------------------------------
        elif "Campo" in tab_name:
            with tab:
                st.subheader("🚙 Auditoría Técnica en Campo (Supervisión Presencial)")
                st.caption("Formularios técnicos de control de calidad para ser completados por supervisores en el sitio de trabajo.")
                
                # Sub-selector para separar Órdenes Varias de INSFIBRA sin tabs anidados
                key_subtab_campo = f"subtab_campo_selector_{num_orden}"
                opcion_subtab_campo = st.radio(
                    "Tipo de auditoría de campo:",
                    ["📋 Auditoría de Órdenes Varias", "🔌 Auditoría de Instalaciones (INSFIBRA)"],
                    horizontal=True,
                    key=key_subtab_campo
                )
                st.markdown("---")

                if opcion_subtab_campo == "📋 Auditoría de Órdenes Varias":
                    st.markdown("### 📋 Formulario para Órdenes Varias (Soporte, Mantenimiento, etc.)")
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
                            
                else:
                    st.markdown("### 🔌 Formulario de Auditoría para Instalaciones (INSFIBRA)")
                    
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
                            tiempo_invent_val = st.text_input("TIEMPO INVERTIDO:", value=tiempo_invent_str if tiempo_invent_str != "---" else "", key=f"time_ins_input_{num_orden}", placeholder="Ej: 45 minutos")
                        with col_i2:
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
                            "TIEMPO_INVERTIDO": tiempo_invent_val,
                            "TIPO_FO": tipo_fo,
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

        # --------------------------------------------------------------------------
        # FLUJO: HISTORIAL, REPORTE EN PDF Y ELIMINACIÓN DE REGISTROS
        # --------------------------------------------------------------------------
        elif "Histórico" in tab_name:
            with tab:
                st.subheader("📋 Histórico de Auditorías y Control de Calidad")
                
                tipo_consulta = st.selectbox(
                    "📋 Seleccione la Base de Datos a Consultar:", 
                    ["Satisfacción de Clientes (Llamadas / QA)", "Auditoría de Campo (Operaciones)", "Auditoría de Instalaciones (INSFIBRA)"],
                    key="tipo_consulta_calidad_selectbox"
                )
                
                hoja_target = "Calidad" if tipo_consulta == "Satisfacción de Clientes (Llamadas / QA)" else ("Operaciones" if "Campo" in tipo_consulta else "Instalaciones")
                archivo_respaldo = "calidad_maestro.csv" if hoja_target == "Calidad" else ("operaciones_maestro.csv" if hoja_target == "Operaciones" else "instalaciones_maestro.csv")
                
                try:
                    df_qa = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=hoja_target, ttl=0)
                except Exception:
                    df_qa = None
                    
                if df_qa is None or df_qa.empty:
                    df_qa = leer_espejo_gcs("jovial-trilogy-306216.appspot.com", archivo_respaldo)
                    
                if df_qa is None or df_qa.empty:
                    st.info(f"ℹ️ Aún no se han registrado auditorías en la pestaña '{hoja_target}' de Google Sheets.")
                else:
                    df_qa.columns = df_qa.columns.astype(str).str.upper().str.strip()
                    
                    st.markdown("#### 📅 Filtrar por Rango de Fechas")
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        hoy_hx = get_honduras_time().date()
                        rango_sel = st.date_input("Seleccione el periodo a consultar:", value=(hoy_hx - timedelta(days=7), hoy_hx), key="rango_calidad_picker")
                    
                    col_fecha_cruce = 'FECHA_GESTION' if 'FECHA_GESTION' in df_qa.columns else 'FECHA_AUDITORIA'
                    df_qa['FECHA_DT'] = pd.to_datetime(df_qa[col_fecha_cruce], errors='coerce')
                    df_qa = df_qa.dropna(subset=['FECHA_DT'])
                    
                    if len(rango_sel) == 2:
                        ini_d, fin_d = rango_sel
                        df_filtered = df_qa[(df_qa['FECHA_DT'].dt.date >= ini_d) & (df_qa['FECHA_DT'].dt.date <= fin_d)].copy()
                    else:
                        ini_d = rango_sel[0]
                        df_filtered = df_qa[df_qa['FECHA_DT'].dt.date == ini_d].copy()
                        
                    if df_filtered.empty:
                        st.warning(f"⚠️ No se encontraron auditorías en la pestaña '{hoja_target}' para el rango de fechas seleccionado.")
                    else:
                        cols_mostrar = [c for c in df_filtered.columns if c not in ['FECHA_DT']]
                        st.dataframe(df_filtered[cols_mostrar], use_container_width=True, hide_index=True)
                        
                        st.markdown("---")
                        
                        st.markdown("#### 📥 Exportación de Reporte en PDF")
                        col_pdf1, col_pdf2 = st.columns([1, 2])
                        with col_pdf1:
                            if st.button("📄 GENERAR REPORTE PDF DE CALIDAD", use_container_width=True, type="primary", key="btn_pdf_calidad_action"):
                                with st.spinner("Preparando archivo de reporte..."):
                                    from tools import generar_pdf_reporte_calidad, generar_pdf_reporte_campo
                                    if hoja_target == "Calidad":
                                        st.session_state['pdf_calidad_data_final'] = generar_pdf_reporte_calidad(
                                            df_filtered, 
                                            ini_d, 
                                            fin_d if 'fin_d' in locals() else ini_d
                                        )
                                    else:
                                        st.session_state['pdf_calidad_data_final'] = generar_pdf_reporte_campo(
                                            df_filtered, 
                                            ini_d, 
                                            fin_d if 'fin_d' in locals() else ini_d,
                                            tipo="operaciones" if hoja_target == "Operaciones" else "instalaciones"
                                        )
                                        
                            if 'pdf_calidad_data_final' in st.session_state and st.session_state['pdf_calidad_data_final'] is not None:
                                st.download_button(
                                    label="📥 DESCARGAR REPORTE EN PDF",
                                    data=st.session_state['pdf_calidad_data_final'],
                                    file_name=f"Reporte_{hoja_target}_{ini_d}.pdf",
                                    mime="application/pdf",
                                    use_container_width=True,
                                    key="btn_download_calidad_actual"
                                )
                        
                        st.markdown("---")
                        
                        st.markdown("#### 🗑️ Eliminación de Registros (Uso exclusivo Gerencia)")
                        st.caption(f"Seleccione un registro del histórico para eliminarlo permanentemente de Google Sheets y GCS de la pestaña '{hoja_target}'.")
                        
                        # --- DETERMINAR COLUMNAS DE REFERENCIA DE FORMA ULTRA-SEGURA ---
                        col_ticket_ref = 'TICKET' if 'TICKET' in df_filtered.columns else ('ORDEN_NUM' if 'ORDEN_NUM' in df_filtered.columns else df_filtered.columns[0])
                        
                        # Elegir un nombre o campo de referencia que exista para evitar KeyError en Operaciones
                        if 'NOMBRE_CLIENTE' in df_filtered.columns:
                            col_nombre_ref = 'NOMBRE_CLIENTE'
                        elif 'TECNICO' in df_filtered.columns:
                            col_nombre_ref = 'TECNICO'
                        elif 'CODIGO_CLIENTE' in df_filtered.columns:
                            col_nombre_ref = 'CODIGO_CLIENTE'
                        elif 'SUPERVISOR' in df_filtered.columns:
                            col_nombre_ref = 'SUPERVISOR'
                        else:
                            col_nombre_ref = None

                        # Sanitización segura de la columna de fecha cruzada
                        col_fecha_cruce_safe = col_fecha_cruce if col_fecha_cruce in df_filtered.columns else df_filtered.columns[0]
                        
                        ticket_part = df_filtered[col_ticket_ref].astype(str)
                        fecha_part = df_filtered[col_fecha_cruce_safe].astype(str)
                        
                        if col_nombre_ref is not None:
                            nombre_part = df_filtered[col_nombre_ref].astype(str)
                            df_filtered['OPCION_ELIMINAR'] = ticket_part + " - " + nombre_part + " (" + fecha_part + ")"
                        else:
                            df_filtered['OPCION_ELIMINAR'] = ticket_part + " (" + fecha_part + ")"

                        lista_eliminar_ops = ["---"] + df_filtered['OPCION_ELIMINAR'].tolist()
                        
                        registro_a_borrar = st.selectbox("Seleccione el registro que desea eliminar permanentemente:", lista_eliminar_ops, key="box_eliminar_QA_general")
                        
                        if registro_a_borrar != "---":
                            row_eliminar = df_filtered[df_filtered['OPCION_ELIMINAR'] == registro_a_borrar].iloc[0]
                            ticket_del = row_eliminar[col_ticket_ref]
                            fecha_del = row_eliminar[col_fecha_cruce_safe]
                            
                            col_del1, col_del2 = st.columns([1, 2])
                            with col_del1:
                                confirmar_del = st.button("🚨 ELIMINAR REGISTRO SELECCIONADO", use_container_width=True, type="primary", key="btn_eliminar_QA_confirm")
                                
                            if confirmar_del:
                                from tools import eliminar_registro_calidad, eliminar_registro_campo
                                with st.spinner("Eliminando el registro de las bases de datos..."):
                                    if hoja_target == "Calidad":
                                        exito_del = eliminar_registro_calidad(conn, ticket_del, fecha_del)
                                    else:
                                        exito_del = eliminar_registro_campo(conn, ticket_del, fecha_del, tipo="operaciones" if hoja_target == "Operaciones" else "instalaciones")
                                    
                                if exito_del:
                                    st.success(f"✅ ¡El registro correspondiente a la {ticket_del} ha sido eliminado con éxito de la pestaña '{hoja_target}'!")
                                    if 'pdf_calidad_data_final' in st.session_state:
                                        del st.session_state['pdf_calidad_data_final']
                                    import time
                                    time.sleep(1.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Error al intentar eliminar el registro de campo.")
