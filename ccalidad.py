import streamlit as st
import pandas as pd
import re
import os
from tools import guardar_registro_calidad, generar_url_whatsapp_QA, get_honduras_time, normalizar_nombre_cruce

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Módulo de encuestas, satisfacción de clientes (CSAT) y auditoría técnica de órdenes cerradas.")
    
    # Filtrar órdenes cerradas (las evaluables)
    df_cerradas = df_base[df_base['ESTADO'].astype(str).str.upper() == 'CERRADA'].copy()
    
    if df_cerradas.empty:
        st.info("ℹ️ No hay órdenes cerradas en el sistema para evaluar en este momento.")
        return

    # Generar lista de selección para las órdenes cerradas
    df_cerradas['OPCION_SELECT'] = "ORD-" + df_cerradas['NUM'].astype(str) + " | " + df_cerradas['TECNICO'].astype(str) + " | " + df_cerradas['NOMBRE'].astype(str)
    opciones = df_cerradas['OPCION_SELECT'].tolist()
    
    col_sel1, col_sel2 = st.columns([2, 1])
    with col_sel1:
        opcion_seleccionada = st.selectbox("🔍 Seleccione la Orden a Evaluar:", opciones)
    
    # Extraer fila correspondiente
    row_sel = df_cerradas[df_cerradas['OPCION_SELECT'] == opcion_seleccionada].iloc[0]
    
    # Cargar variables de la orden
    num_orden = row_sel.get('NUM', 'N/D')
    cliente_id = row_sel.get('CLIENTE', 'N/D')
    nombre_cliente = row_sel.get('NOMBRE', 'N/D')
    colonia = row_sel.get('COLONIA', 'N/D')
    tecnico = row_sel.get('TECNICO', 'N/D')
    actividad = row_sel.get('ACTIVIDAD', 'N/D')
    comentario_cierre = row_sel.get('COMENTARIO', '')
    
    # Extraer OLT / Telemetría
    olt_val = ""
    for col in df_cerradas.columns:
        if any(k in str(col).upper() for k in ['FTTX', 'DISPOSITIVO', 'OLT', 'INFO']):
            olt_val = str(row_sel.get(col, ''))
            break

    st.markdown("---")
    st.subheader("📋 Información de la Orden de Servicio")
    
    col_inf1, col_inf2, col_inf3 = st.columns(3)
    with col_inf1:
        st.markdown(f"**Ticket:** ORD-{num_orden}")
        st.markdown(f"**Técnico:** {tecnico}")
    with col_inf2:
        st.markdown(f"**ID Cliente:** {cliente_id}")
        st.markdown(f"**Nombre:** {nombre_cliente}")
    with col_inf3:
        st.markdown(f"**Actividad:** {actividad}")
        st.markdown(f"**Localidad:** {colonia}")
        
    with st.expander("💬 Comentario de Cierre de Campo"):
        st.write(comentario_cierre if comentario_cierre else "Sin comentario registrado.")
        
    st.markdown("---")
    st.subheader("🏅 Formulario de Auditoría y Satisfacción (CSAT)")
    
    form_calidad = st.form(key="form_eval_calidad")
    with form_calidad:
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            csat_rating = st.slider("⭐ Satisfacción del Cliente (CSAT) - 1 a 5 Estrellas:", min_value=1, max_value=5, value=5)
            nps_rating = st.slider("📈 Probabilidad de Recomendación (NPS) - 0 a 10:", min_value=0, max_value=10, value=10)
            estetica_instalacion = st.selectbox(
                "📐 Calidad de la Instalación Física / Estética:",
                ["Excelente (Cables ordenados, grapado impecable)", "Aceptable (Pequeños detalles)", "Deficiente (Requiere corrección de campo)"]
            )
            limpieza_hogar = st.radio("🧹 ¿El técnico dejó limpio el hogar/área de trabajo?", ["Sí", "No"], horizontal=True)

        with col_f2:
            sen_optica = st.text_input("🔌 Potencia Óptica Final Reportada (dBm):", value="-18.5" if "UP" in olt_val else "")
            telefono_qa = st.text_input("📞 Teléfono del Cliente (WhatsApp):", value="", placeholder="Ej: 99887766")
            clasificacion_eval = st.selectbox("🚦 Tipo de Auditoría:", ["Llamada Post-Servicio", "Inspección Física de Campo", "Auditoría por Foto"])
            comentarios_qa = st.text_area("✍️ Observaciones de Calidad:", placeholder="Escriba los comentarios o detalles adicionales de la auditoría...")

        submit_eval = st.form_submit_button("💾 Guardar Evaluación y Registro de Calidad")
        
    if submit_eval:
        datos_eval = {
            "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
            "NUM_ORDEN": num_orden,
            "CLIENTE": cliente_id,
            "NOMBRE_CLIENTE": nombre_cliente,
            "TECNICO": tecnico,
            "ACTIVIDAD": actividad,
            "CSAT": csat_rating,
            "NPS": nps_rating,
            "ESTETICA": estetica_instalacion,
            "LIMPIEZA": limpieza_hogar,
            "POTENCIA_DBM": sen_optica,
            "TELEFONO": telefono_qa,
            "TIPO_AUDITORIA": clasificacion_eval,
            "COMENTARIOS": comentarios_qa
        }
        
        exito = guardar_registro_calidad(conn, datos_eval)
        if exito:
            st.success(f"✅ ¡Evaluación de Calidad para la ORD-{num_orden} guardada correctamente en el sistema!")
        else:
            st.error("❌ Ocurrió un error al guardar la evaluación. Por favor verifique el log de conexiones.")
            
    # WhatsApp click-to-chat generator
    st.markdown("### 💬 Canal de Comunicación WhatsApp")
    st.caption("Genere el mensaje de satisfacción automatizado pre-poblado y envíelo directamente al cliente por chat.")
    
    col_wa1, col_wa2 = st.columns([2, 1])
    with col_wa1:
        tel_input = st.text_input("📞 Confirme Teléfono para WhatsApp:", value=telefono_qa if telefono_qa else "", key="tel_wa_QA")
    with col_wa2:
        st.markdown("<br>", unsafe_allow_html=True)
        if tel_input.strip():
            url_wa = generar_url_whatsapp_QA(tel_input, num_orden, nombre_cliente, tecnico, csat_rating, comentarios_qa)
            st.link_button("💬 ENVIAR ENCUESTA POR WHATSAPP", url_wa, type="primary", use_container_width=True)
        else:
            st.info("Ingrese un teléfono para habilitar el envío.")
