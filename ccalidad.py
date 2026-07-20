import streamlit as st
import pandas as pd
import re
import os
from tools import guardar_registro_calidad, get_honduras_time, normalizar_nombre_cruce

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Encuesta oficial de satisfacción y control de calidad de instalaciones y soporte técnico en Google Sheets.")
    
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
    
    # Intentar obtener fecha de visita limpia
    fecha_liq_dt = pd.to_datetime(row_sel.get('HORA_LIQ', pd.NaT))
    fecha_visita_str = fecha_liq_dt.strftime('%d/%m/%Y') if pd.notnull(fecha_liq_dt) else get_honduras_time().strftime('%d/%m/%Y')

    st.markdown("---")
    
    st.subheader("📞 Registro de Gestión de Llamada Post-Servicio")
    st.caption("Complete la encuesta de satisfacción mientras gestiona la llamada telefónica con el cliente.")
    
    contesto = st.radio("🚦 ¿El cliente contestó la llamada?", ["Sí, contestó", "No contestó / Buzón de voz", "Número apagado o fuera de servicio"], horizontal=True)
    
    if contesto == "Sí, contestó":
        form_llamada = st.form(key="form_encuesta_completa")
        with form_llamada:
            # ----------------------------------------------------------------------
            # SECCIÓN 1: DATOS GENERALES (Pre-poblados de forma automática)
            # ----------------------------------------------------------------------
            st.markdown("### 1️⃣ Datos Generales del Servicio")
            col_gen1, col_gen2 = st.columns(2)
            with col_gen1:
                st.text_input("Nombre del Cliente (Auto-rellenado):", value=nombre_cliente, disabled=True)
                st.text_input("Número de Orden / Servicio:", value=f"ORD-{num_orden}", disabled=True)
            with col_gen2:
                fecha_visita_input = st.text_input("Fecha de la Visita (DD/MM/AAAA):", value=fecha_visita_str)
                st.text_input("Nombre del Técnico (Auto-rellenado):", value=tecnico, disabled=True)
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 2: PUNTUALIDAD Y PRESENTACIÓN
            # ----------------------------------------------------------------------
            st.markdown("### 2️⃣ Puntualidad y Presentación")
            p1_puntualidad = st.radio("1. ¿El técnico llegó dentro del horario acordado?", ["Sí", "No"], horizontal=True)
            p2_presentacion = st.radio("2. ¿El técnico se presentó de forma adecuada (uniforme, identificación y trato respetuoso)?", ["Excelente", "Bueno", "Regular", "Deficiente"], horizontal=True)
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 3: EJECUCIÓN DEL TRABAJO
            # ----------------------------------------------------------------------
            st.markdown("### 3️⃣ Ejecución del Trabajo")
            p3_explicacion = st.radio("3. ¿El técnico le explicó claramente el trabajo que iba a realizar?", ["Sí", "Parcialmente", "No"], horizontal=True)
            p4_corresponde = st.radio("4. ¿El trabajo realizado corresponde al servicio solicitado?", ["Sí", "No"], horizontal=True)
            p5_funcionando = st.radio("5. ¿El servicio quedó funcionando correctamente al momento de la entrega?", ["Sí", "No"], horizontal=True)
            motivo_no_funciona = st.text_input("Si respondió 'No' en la pregunta anterior, indique brevemente el motivo:", value="", placeholder="Escriba el motivo aquí...")
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 4: ORDEN, LIMPIEZA Y CUIDADO
            # ----------------------------------------------------------------------
            st.markdown("### 4️⃣ Orden, Limpieza y Cuidado")
            p6_limpieza = st.radio("6. ¿El área de trabajo quedó limpia y ordenada al finalizar?", ["Sí", "No"], horizontal=True)
            p7_cuidado = st.radio("7. ¿El técnico cuidó adecuadamente su propiedad y equipos?", ["Sí", "No"], horizontal=True)
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 5: ATENCIÓN Y TRATO
            # ----------------------------------------------------------------------
            st.markdown("### 5️⃣ Atención y Trato")
            p8_atencion = st.radio("8. ¿Cómo califica el trato y la atención brindada por el técnico?", ["Excelente", "Bueno", "Regular", "Deficiente"], horizontal=True)
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 6: SATISFACCIÓN GENERAL
            # ----------------------------------------------------------------------
            st.markdown("### 6️⃣ Satisfacción General")
            p9_satisfaccion = st.radio("9. En general, ¿qué tan satisfecho(a) está con el servicio recibido?", ["Muy satisfecho", "Satisfecho", "Poco satisfecho", "Insatisfecho"], horizontal=True)
            p10_recomienda = st.radio("10. ¿En base al servicio recibido, recomendaría el servicio de MAXCOM a otras personas?", ["Sí", "No"], horizontal=True)
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 7: OBSERVACIONES DEL CLIENTE (Opcional)
            # ----------------------------------------------------------------------
            st.markdown("### 7️⃣ Observaciones del Cliente (Opcional)")
            observaciones_cliente = st.text_area("Comentarios u observaciones adicionales del cliente:")
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 8: VISTO BUENO Y CIERRE
            # ----------------------------------------------------------------------
            st.markdown("### 8️⃣ Visto Bueno y Cierre del Servicio")
            p11_visto_bueno = st.radio("11. ¿Autoriza usted que el técnico continúe con su siguiente instalación o visita, confirmando que el servicio quedó conforme?", ["Sí, otorgo mi visto bueno", "No"], horizontal=True)
            nombre_firma = st.text_input("Nombre de la persona que brinda la aceptación digital (Cliente o Responsable):", value=nombre_cliente)
            hora_cierre = st.text_input("Hora de cierre del servicio:", value=get_honduras_time().strftime('%I:%M %p'))
            
            st.divider()
            
            # ----------------------------------------------------------------------
            # SECCIÓN 9: USO OPERATIVO INTERNO (NO VISIBLE AL CLIENTE)
            # ----------------------------------------------------------------------
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
