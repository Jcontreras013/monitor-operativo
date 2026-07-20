import streamlit as st
import pandas as pd
import re
import os
from tools import (
    guardar_registro_calidad, 
    generar_url_whatsapp_QA, 
    get_honduras_time, 
    normalizar_nombre_cruce,
    disparar_encuesta_wati
)

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Gestión unificada de auditorías: Ingrese un número de orden para auto-rellenar los datos del servicio.")
    
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
    tab_llamada, tab_whatsapp = st.tabs(["📞 Registrar Gestión de Llamada", "💬 Enviar Encuesta WhatsApp"])

    # --------------------------------------------------------------------------
    # PESTAÑA 1: REGISTRO DE LLAMADA TELEFÓNICA (CONTESTADA O FALLIDA)
    # --------------------------------------------------------------------------
    with tab_llamada:
        st.subheader("📞 Registro de Llamada Telefónica Post-Servicio")
        st.caption("Complete este formulario durante o después de la llamada telefónica.")
        
        form_llamada = st.form(key="form_gestion_llamada")
        with form_llamada:
            contesto = st.radio("🚦 ¿El cliente contestó la llamada?", ["Sí, contestó", "No contestó / Buzón de voz", "Número apagado o fuera de servicio"], horizontal=True)
            
            st.markdown("#### 📊 Datos de la Encuesta (Solo si contestó)")
            csat_rating = st.slider("⭐ Satisfacción del Cliente (CSAT) - 1 a 5 Estrellas:", min_value=1, max_value=5, value=5)
            nps_rating = st.slider("📈 Probabilidad de Recomendación (NPS) - 0 a 10:", min_value=0, max_value=10, value=10)
            estetica_instalacion = st.selectbox(
                "📐 Calidad de la Instalación Física / Estética:",
                ["Excelente (Cables ordenados, grapado impecable)", "Aceptable (Pequeños detalles)", "Deficiente (Requiere corrección de campo)"]
            )
            limpieza_hogar = st.radio("🧹 ¿El técnico dejó limpio el hogar/área de trabajo?", ["Sí", "No"], horizontal=True)
            sen_optica = st.text_input("🔌 Potencia Óptica Final Reportada (dBm):", value="-18.5" if "UP" in olt_val else "")
            telefono_cliente = st.text_input("📞 Teléfono de Contacto del Cliente:", value="", placeholder="Ej: 99887766")
            observaciones_llamada = st.text_area("✍️ Observaciones de la Llamada / Gestión:")
            
            submit_llamada = st.form_submit_button("💾 Guardar Gestión de Llamada")
            
        if submit_llamada:
            if contesto != "Sí, contestó":
                datos_llamada = {
                    "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "NUM_ORDEN": num_orden,
                    "CLIENTE": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "COLONIA": colonia,
                    "CSAT": "N/A",
                    "NPS": "N/A",
                    "ESTETICA": "N/A",
                    "LIMPIEZA": "N/A",
                    "POTENCIA_DBM": "N/A",
                    "TELEFONO": telefono_cliente if telefono_cliente.strip() else "N/A",
                    "TIPO_AUDITORIA": f"Llamada - {contesto}",
                    "COMENTARIOS": f"Gestión telefónica fallida. Estado: {contesto}. Notas: {observaciones_llamada}"
                }
            else:
                datos_llamada = {
                    "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "NUM_ORDEN": num_orden,
                    "CLIENTE": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "COLONIA": colonia,
                    "CSAT": csat_rating,
                    "NPS": nps_rating,
                    "ESTETICA": estetica_instalacion,
                    "LIMPIEZA": limpieza_hogar,
                    "POTENCIA_DBM": sen_optica,
                    "TELEFONO": telefono_cliente,
                    "TIPO_AUDITORIA": "Llamada Telefónica Exitosa",
                    "COMENTARIOS": observaciones_llamada
                }
                
            exito = guardar_registro_calidad(conn, datos_llamada)
            if exito:
                st.success(f"✅ ¡Gestión de llamada registrada correctamente para la ORD-{num_orden}!")
            else:
                st.error("❌ Error al guardar el registro en la base de datos.")

    # --------------------------------------------------------------------------
    # PESTAÑA 2: ENVÍO AUTOMÁTICO DE ENCUESTA DIGITAL POR WHATSAPP (A PARTE CON WATI)
    # --------------------------------------------------------------------------
    with tab_whatsapp:
        st.subheader("💬 Envío Automático mediante WATI (WhatsApp Business API)")
        st.caption("Esta pestaña registra el envío en el historial del sistema y dispara de forma automatizada la plantilla de encuesta oficial de WATI.")
        
        telefono_wa = st.text_input("📞 Ingrese el número de WhatsApp del Cliente:", value=telefono_cliente if 'telefono_cliente' in locals() and telefono_cliente else "", placeholder="Ej: 99887766", key="tel_wa_QA_input")
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
                    "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                    "NUM_ORDEN": num_orden,
                    "CLIENTE": cliente_id,
                    "NOMBRE_CLIENTE": nombre_cliente,
                    "TECNICO": tecnico,
                    "ACTIVIDAD": actividad,
                    "COLONIA": colonia,
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
                    wati_ok = disparar_encuesta_wati(datos_envio)
                
                if saved:
                    st.success(f"💾 Registro de envío guardado correctamente en la base de datos de Calidad.")
                    
                if wati_ok:
                    st.success(f"🚀 ¡Envío Exitoso! La plantilla oficial fue autorizada por WATI y se enviará automáticamente al {telefono_wa}.")
                else:
                    st.info("ℹ️ Señal automática no enviada (Las credenciales de WATI o el nombre de la plantilla no están configuradas en st.secrets).")
                    
        # Backup manual generator
        st.markdown("---")
        st.markdown("#### 🔗 Respaldo: Envío Manual (WhatsApp Web)")
        st.caption("Utilice esta alternativa si la cuenta de WATI está desconectada o prefiere enviar el texto de forma manual.")
        if telefono_wa.strip():
            url_wa = generar_url_whatsapp_QA(telefono_wa, num_orden, nombre_cliente, tecnico, 5, "Por favor califique nuestro servicio")
            st.link_button("💬 ENVIAR RESPALDO MANUAL POR WHATSAPP ↗", url_wa, use_container_width=True)
        else:
            st.warning("Ingrese un teléfono para habilitar la plantilla manual.")
