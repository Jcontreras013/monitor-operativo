import streamlit as st
import pandas as pd
from datetime import timedelta
from tools import (
    guardar_registro_calidad,
    get_honduras_time,
    leer_espejo_gcs,
    guardar_auditoria_campo,
    normalizar_nombre_cruce,
    NOMBRE_BUCKET_SISTEMA
)

# Mapea el nombre de la pestaña de Google Sheets al "tipo" que esperan
# generar_pdf_reporte_campo()/eliminar_registro_campo() en tools.py.
_TIPO_CAMPO_POR_HOJA = {
    "Operaciones": "operaciones",
    "Instalaciones": "instalaciones",
    "Auditoria_Fibra": "fibra",
}

# subir_archivo_catbox vive en expediente.py (ya usa CATBOX_USERHASH desde
# st.secrets ahí) -- se reutiliza en vez de duplicar la integración con
# Catbox. expediente.py no importa nada de este módulo, así que no hay
# import circular.
from expediente import subir_archivo_catbox

def mostrar_modulo_calidad(conn, df_base):
    st.title("🏅 Control de Calidad y Auditoría de Servicios")
    st.caption("Módulo de encuestas, auditorías en campo (Operaciones / Instalaciones) y control de calidad en Google Sheets.")

    # Se necesita saber el usuario ANTES de armar el universo de órdenes
    # evaluables, porque SAC (el personal que llama al cliente) solo debe
    # ver INSFIBRA cerradas de los últimos 15 días -- las órdenes que tiene
    # sentido llamar para encuestar -- y no todo el universo de órdenes.
    usuario = str(st.session_state.get('usuario_actual', '')).strip().lower()

    # === SOLUCIÓN: Buscar órdenes tanto pendientes como cerradas (excluyendo anuladas) ===
    df_evaluables = df_base[~df_base['ESTADO'].astype(str).str.upper().str.contains('ANULADA', na=False)].copy()

    # Universo COMPLETO de INSFIBRA cerradas (sin el límite de 15 días que
    # sí aplica para la búsqueda individual de SAC), para el reporte de
    # "Cierres INSFIBRA por Rango de Fechas" -- ahí sí interesa poder
    # consultar rangos más viejos, no solo lo último.
    df_insfibra_cerradas_todas = df_evaluables[
        (df_evaluables['ACTIVIDAD'].astype(str).str.upper().str.strip() == 'INSFIBRA') &
        (df_evaluables['ESTADO'].astype(str).str.upper().str.strip() == 'CERRADA')
    ].copy()

    if usuario == "sac":
        hoy_sac = get_honduras_time().date()
        limite_sac = hoy_sac - timedelta(days=15)
        mask_insfibra_sac = df_evaluables['ACTIVIDAD'].astype(str).str.upper().str.strip() == 'INSFIBRA'
        mask_cerrada_sac = df_evaluables['ESTADO'].astype(str).str.upper().str.strip() == 'CERRADA'
        fechas_liq_sac = pd.to_datetime(df_evaluables['HORA_LIQ'], errors='coerce').dt.date
        mask_15dias_sac = (fechas_liq_sac >= limite_sac) & (fechas_liq_sac <= hoy_sac)
        df_evaluables = df_evaluables[mask_insfibra_sac & mask_cerrada_sac & mask_15dias_sac].copy()

    if df_evaluables.empty:
        if usuario == "sac":
            st.info("ℹ️ No hay órdenes INSFIBRA cerradas en los últimos 15 días para encuestar por el momento.")
        else:
            st.info("ℹ️ No hay órdenes registradas en el sistema para evaluar en este momento.")
        return

    # ==============================================================================
    # UN SOLO BUSCADOR, POR TEXTO LIBRE (NUM, CLIENTE o NOMBRE, en cualquier orden)
    # ==============================================================================
    # El cuadro de búsqueda NATIVO de un st.selectbox de Streamlit solo filtra
    # desde el INICIO del texto de cada opción -- por eso combinar NUM/cliente/
    # nombre en una sola etiqueta siempre dejaba a alguno de los tres sin poder
    # buscarse según cuál quedara primero (ya se probaron ambos órdenes). Para
    # buscar por cualquiera de los tres datos desde una sola barra hay que
    # dejar de depender de ese filtro nativo: aquí se usa un st.text_input y el
    # filtrado se hace a mano con .str.contains(), que sí encuentra el texto
    # en cualquier posición (número de orden, número de cliente o nombre).
    row_sel = None

    busqueda_libre = st.text_input(
        "🔍 Buscar por Número de Orden, Número de Cliente o Nombre:",
        placeholder="Escriba cualquiera de los tres...",
        key="calidad_busqueda_libre"
    )

    if busqueda_libre and busqueda_libre.strip():
        q = busqueda_libre.strip().upper()
        mask_num_cli = (
            df_evaluables['NUM'].astype(str).str.upper().str.contains(q, na=False, regex=False) |
            df_evaluables['CLIENTE'].astype(str).str.upper().str.contains(q, na=False, regex=False)
        )

        # Para el nombre no basta con "contains" del texto completo: si se
        # escribe solo nombre y apellido ("JUAN PEREZ") pero el nombre
        # guardado tiene más partes en medio ("JUAN CARLOS PEREZ LOPEZ"), el
        # texto "JUAN PEREZ" nunca aparece pegado tal cual y no encontraba
        # nada. Se normaliza (sin acentos, mayúsculas, espacios de más -- lo
        # mismo que ya usa el cruce de técnicos) y se exige que CADA palabra
        # escrita esté presente en el nombre, sin importar el orden ni si hay
        # otras palabras en medio.
        q_tokens = normalizar_nombre_cruce(q).split()
        nombre_norm = df_evaluables['NOMBRE'].fillna('').apply(normalizar_nombre_cruce)
        mask_nombre = nombre_norm.apply(lambda n: all(tok in n for tok in q_tokens)) if q_tokens else pd.Series(False, index=df_evaluables.index)

        mask_busqueda = mask_num_cli | mask_nombre
        df_resultados = df_evaluables[mask_busqueda].copy()

        if df_resultados.empty:
            st.warning(f"⚠️ No se encontró ninguna orden, cliente o nombre que coincida con \"{busqueda_libre}\".")
        else:
            df_resultados['OPCION_BUSQUEDA'] = (
                "ORD-" + df_resultados['NUM'].astype(str) + " | " +
                df_resultados['CLIENTE'].astype(str) + " - " +
                df_resultados['NOMBRE'].fillna('N/D').astype(str)
            )
            opciones_resultado = sorted(df_resultados['OPCION_BUSQUEDA'].unique().tolist())

            if len(opciones_resultado) == 1:
                opcion_elegida = opciones_resultado[0]
                st.caption(f"✅ Coincidencia única: {opcion_elegida}")
            else:
                opcion_elegida = st.selectbox(
                    f"Se encontraron {len(opciones_resultado)} coincidencias, elige una:",
                    options=opciones_resultado,
                    index=None,
                    key="calidad_busqueda_resultado"
                )

            if opcion_elegida is not None:
                row_sel = df_resultados[df_resultados['OPCION_BUSQUEDA'] == opcion_elegida].iloc[0]

    # Si no se ha realizado ninguna selección todavía, NO cortamos la
    # ejecución aquí: hay pestañas (como "Cierres INSFIBRA por Rango de
    # Fechas" e "Histórico y Reportes") que no dependen de tener una orden
    # puntual seleccionada -- son reportes/listados, no una auditoría de UNA
    # orden. Las pestañas que sí necesitan una orden puntual (Llamada,
    # WhatsApp, Campo) revisan `row_sel is None` cada una por su cuenta y
    # muestran su propio aviso de "seleccione una orden" en vez de romperse
    # por variables indefinidas.
    if row_sel is not None:
        # Cargar variables de la orden una vez seleccionada
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
    else:
        # Valores de relleno para que las pestañas que sí requieren una
        # orden puntual (y que revisan row_sel por su cuenta) tengan algo
        # definido si llegaran a referenciarlos por error; no se muestran.
        num_orden = cliente_id = nombre_cliente = colonia = tecnico = actividad = 'N/D'
        comentario_cierre = ''
        olt_val = ''
        fecha_visita_str = get_honduras_time().strftime('%d/%m/%Y')

    # ==============================================================================
    # CONTROL DE ACCESO BASADO EN ROLES Y USUARIOS
    # ==============================================================================
    # (usuario ya se calculó arriba, antes de armar df_evaluables)

    # Definimos la lista de pestañas que se renderizarán según el perfil
    if usuario == "miguel":
        tabs_to_render = [
            "🚙 Auditoría de Campo (Operaciones)",
            "📋 Histórico y Reportes"
        ]
    elif usuario == "sac":
        # La encuesta por WhatsApp (WATI) se omite: es un servicio de paga.
        tabs_to_render = [
            "📞 Registrar Gestión de Llamada",
            "📅 Cierres INSFIBRA por Rango de Fechas",
            "📋 Histórico y Reportes"
        ]
    else:
        # La encuesta por WhatsApp (WATI) se omite: es un servicio de paga.
        tabs_to_render = [
            "📞 Registrar Gestión de Llamada",
            "📅 Cierres INSFIBRA por Rango de Fechas",
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
                if row_sel is None:
                    st.info("💡 Busque y seleccione una orden arriba para gestionar su llamada.")
                else:
                    st.subheader("📞 Registro de Llamada Telefónica Post-Servicio")
                    st.caption("Complete la encuesta de satisfacción mientras gestiona la llamada telefónica con el cliente.")

                    # ----------------------------------------------------------------
                    # HISTORIAL DE NOTAS DE SEGUIMIENTO / PROMESA PARA ESTA ORDEN
                    # ----------------------------------------------------------------
                    # Antes de volver a llamar, quien gestiona necesita saber si en
                    # una gestión anterior ya se dejó una nota de seguimiento o de
                    # promesa para este mismo ticket, para no perder contexto de lo
                    # ya acordado con el cliente.
                    try:
                        df_notas_prev = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Calidad", ttl=0)
                    except Exception:
                        df_notas_prev = None
                    if df_notas_prev is None or df_notas_prev.empty:
                        df_notas_prev = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "calidad_maestro.csv")

                    if df_notas_prev is not None and not df_notas_prev.empty and 'TICKET' in df_notas_prev.columns:
                        df_notas_prev.columns = df_notas_prev.columns.astype(str).str.upper().str.strip()
                        df_notas_ticket = df_notas_prev[df_notas_prev['TICKET'].astype(str) == f"ORD-{num_orden}"].copy()
                        if 'TIPO_NOTA' in df_notas_ticket.columns:
                            df_notas_ticket = df_notas_ticket[df_notas_ticket['TIPO_NOTA'].astype(str).isin(['Seguimiento', 'Promesa'])]
                        else:
                            df_notas_ticket = df_notas_ticket.iloc[0:0]

                        if not df_notas_ticket.empty:
                            st.warning(f"📌 Esta orden YA tiene {len(df_notas_ticket)} nota(s) de seguimiento/promesa de gestiones anteriores:")
                            cols_notas = [c for c in ['FECHA_GESTION', 'TIPO_NOTA', 'DETALLE_NOTA'] if c in df_notas_ticket.columns]
                            st.dataframe(df_notas_ticket[cols_notas], hide_index=True, use_container_width=True)

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
                            p4_tv_ccveo = st.radio("4. Explicación sobre el servicio de TV Cable y CCVEO", escala_estrellas + ["No aplica"], index=4, horizontal=True, key="p4_tv_ccveo_radio")
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

                            st.markdown("### 5️⃣ Nota de Seguimiento / Promesa (opcional)")
                            st.caption("Si le prometiste algo al cliente o esta gestión necesita seguimiento posterior, déjalo anotado aquí -- se mostrará automáticamente la próxima vez que alguien abra esta orden.")
                            tipo_nota_llamada = st.selectbox("🏷️ Tipo de nota:", ["Ninguna", "Seguimiento", "Promesa"], key="tipo_nota_llamada_select")
                            detalle_nota_llamada = st.text_area("📝 Detalle de la nota:", key="detalle_nota_llamada_input")

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
                                "P4_EXPLICACION_TV_CCVEO": ("N/A" if p4_tv_ccveo == "No aplica" else int(p4_tv_ccveo[0])),
                                "P5_CALIDAD_SERVICIO": int(p5_calidad[0]),
                                "P6_LIMPIEZA_TRABAJO": int(p6_limpieza[0]),
                                "P7_SATISFACCION_GENERAL": int(p7_satisfaccion[0]),
                            
                                "MEJORAS_OPCIONAL": mejoras_opcional if mejoras_opcional.strip() else "Ninguna",
                                "ACEPTACION_DIGITAL": nombre_firma,
                                "HORA_CIERRE_SERVICIO": hora_cierre,
                                "APROBACION_INTERNA": evaluacion_interna,
                                "METODO_AUDITORIA": "Llamada Telefónica Completada",
                                "TIPO_NOTA": tipo_nota_llamada,
                                "DETALLE_NOTA": (detalle_nota_llamada.strip() if tipo_nota_llamada != "Ninguna" and detalle_nota_llamada.strip() else "N/A"),
                            }

                            exito = guardar_registro_calidad(conn, datos_completos)
                            if exito:
                                # Promedio de ESTA encuesta (las 7 preguntas, o 6 si el
                                # cliente no tiene TV Cable/CCVEO y P4 quedó "No aplica"),
                                # en una escala de 1 a 5 -- para verlo de inmediato al
                                # calificar, no solo en el CSAT agregado del Histórico.
                                valores_estrellas_orden = [
                                    datos_completos["P1_PUNTUALIDAD"], datos_completos["P2_PRESENTACION_TRATO"],
                                    datos_completos["P3_CLARIDAD_EXPLICACION"], datos_completos["P5_CALIDAD_SERVICIO"],
                                    datos_completos["P6_LIMPIEZA_TRABAJO"], datos_completos["P7_SATISFACCION_GENERAL"],
                                ]
                                if datos_completos["P4_EXPLICACION_TV_CCVEO"] != "N/A":
                                    valores_estrellas_orden.append(datos_completos["P4_EXPLICACION_TV_CCVEO"])
                                promedio_orden = sum(valores_estrellas_orden) / len(valores_estrellas_orden)

                                st.success(f"✅ ¡Encuesta de Satisfacción guardada exitosamente en la base de datos de Google Sheets para la ORD-{num_orden}!")
                                st.metric("⭐ Promedio de esta orden", f"{promedio_orden:.1f} / 5.0")
                            else:
                                st.error("❌ Error al guardar el registro en Google Sheets. Por favor, asegúrese de crear la pestaña 'Calidad' en su hoja de cálculo.")
                            
                    else:
                        # Flujo de llamada fallida (No contestó)
                        form_falla = st.form(key="form_falla_llamada_erronea")
                        with form_falla:
                            st.markdown("### ⚠️ Registro de Gestión sin Encuesta Completada")
                            st.info(f"Se registrará una constancia de gestión para la orden ORD-{num_orden} asignada a {tecnico}.")

                            resultado_gestion = st.selectbox(
                                "Resultado de la gestión:",
                                [
                                    "Cliente no desea participar",
                                    "Responsable no disponible",
                                    "Llamada reprogramada",
                                    "Número equivocado",
                                    "Sin respuesta después de dos intentos",
                                    "Requiere seguimiento",
                                ],
                                key="resultado_gestion_select"
                            )
                            observaciones_falla = st.text_area("Detalle de la gestión (Buzón, apagado, etc.):", value=f"Se llamó al cliente. Estado: {contesto}.", key="obs_falla_input")

                            st.markdown("#### 🔁 Datos de Seguimiento (si aplica)")
                            ticket_seguimiento = st.text_input("Número de ticket o gestión asociada:", key="ticket_seg_input")
                            responsable_seguimiento = st.text_input("Responsable del seguimiento:", key="resp_seg_input")
                            fecha_limite_seguimiento = st.date_input("Fecha límite del seguimiento:", value=get_honduras_time().date() + timedelta(days=2), key="fecha_lim_seg_input")

                            st.markdown("#### 🏷️ Nota de Seguimiento / Promesa (opcional)")
                            tipo_nota_falla = st.selectbox("Tipo de nota:", ["Ninguna", "Seguimiento", "Promesa"], key="tipo_nota_falla_select")
                            detalle_nota_falla = st.text_area("Detalle de la nota:", key="detalle_nota_falla_input")

                            submit_falla = st.form_submit_button("💾 Registrar Gestión")
                        
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
                            
                                "MEJORAS_OPCIONAL": observaciones_falla if observaciones_falla.strip() else "Sin detalle",
                                "ACEPTACION_DIGITAL": "N/A",
                                "HORA_CIERRE_SERVICIO": "N/A",
                                "RESULTADO_GESTION": resultado_gestion,
                                "TICKET_SEGUIMIENTO": ticket_seguimiento if ticket_seguimiento.strip() else "N/A",
                                "RESPONSABLE_SEGUIMIENTO": responsable_seguimiento if responsable_seguimiento.strip() else "N/A",
                                "FECHA_LIMITE_SEGUIMIENTO": fecha_limite_seguimiento.strftime('%Y-%m-%d'),
                                "APROBACION_INTERNA": ("Servicio no aprobado – requiere seguimiento" if resultado_gestion == "Requiere seguimiento" else "Sin encuesta completada"),
                                "METODO_AUDITORIA": f"Gestión sin encuesta - {resultado_gestion}",
                                "TIPO_NOTA": tipo_nota_falla,
                                "DETALLE_NOTA": (detalle_nota_falla.strip() if tipo_nota_falla != "Ninguna" and detalle_nota_falla.strip() else "N/A"),
                            }
                        
                            exito = guardar_registro_calidad(conn, datos_falla)
                            if exito:
                                st.success(f"📝 ¡Intento fallido registrado correctamente en Google Sheets para la ORD-{num_orden}!")
                            else:
                                st.error("❌ Error al guardar el registro del intento en la base de datos.")

        # --------------------------------------------------------------------------
        # FLUJO: CIERRES INSFIBRA POR RANGO DE FECHAS (con auto-marcado de llamada)
        # --------------------------------------------------------------------------
        elif "Cierres INSFIBRA" in tab_name:
            with tab:
                st.subheader("📅 Cierres de INSFIBRA por Rango de Fechas")
                st.caption("Lista las órdenes INSFIBRA cerradas en el rango elegido y marca automáticamente cuáles ya tienen una llamada registrada en Control de Calidad (contestada o no), para saber a cuáles todavía falta llamar.")

                hoy_rango_ins = get_honduras_time().date()
                rango_ins = st.date_input(
                    "Rango de fechas de cierre a consultar:",
                    value=(hoy_rango_ins - timedelta(days=7), hoy_rango_ins),
                    key="rango_insfibra_cierres_picker"
                )
                if isinstance(rango_ins, tuple) and len(rango_ins) == 2:
                    ini_rango_ins, fin_rango_ins = rango_ins
                else:
                    ini_rango_ins = fin_rango_ins = rango_ins[0] if isinstance(rango_ins, tuple) else rango_ins

                fechas_cierre_ins = pd.to_datetime(df_insfibra_cerradas_todas['HORA_LIQ'], errors='coerce').dt.date
                mask_rango_ins = (fechas_cierre_ins >= ini_rango_ins) & (fechas_cierre_ins <= fin_rango_ins)
                df_rango_ins = df_insfibra_cerradas_todas[mask_rango_ins].copy()

                if df_rango_ins.empty:
                    st.info(f"ℹ️ No hay INSFIBRA cerradas entre {ini_rango_ins.strftime('%d/%m/%Y')} y {fin_rango_ins.strftime('%d/%m/%Y')}.")
                else:
                    # --- Cargar el histórico de Calidad para saber a quién ya se le llamó ---
                    # Cualquier registro guardado en la pestaña "Calidad" -- ya sea la
                    # encuesta completa (cliente contestó) o la constancia de gestión
                    # (no contestó, número equivocado, etc.) -- cuenta como "ya se
                    # gestionó la llamada", que es lo que importa para no volver a
                    # marcarla como pendiente.
                    try:
                        df_llamadas_hechas = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet="Calidad", ttl=0)
                    except Exception:
                        df_llamadas_hechas = None
                    if df_llamadas_hechas is None or df_llamadas_hechas.empty:
                        df_llamadas_hechas = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, "calidad_maestro.csv")

                    if df_llamadas_hechas is not None and not df_llamadas_hechas.empty:
                        df_llamadas_hechas.columns = df_llamadas_hechas.columns.astype(str).str.upper().str.strip()
                    if df_llamadas_hechas is not None and not df_llamadas_hechas.empty and 'TICKET' in df_llamadas_hechas.columns:
                        tickets_ya_llamados = set(df_llamadas_hechas['TICKET'].astype(str).str.upper().str.strip())
                    else:
                        tickets_ya_llamados = set()

                    df_rango_ins['TICKET'] = "ORD-" + df_rango_ins['NUM'].astype(str)
                    df_rango_ins['¿SE LLAMÓ?'] = df_rango_ins['TICKET'].str.upper().str.strip().apply(
                        lambda t: "✅ Sí" if t in tickets_ya_llamados else "❌ Pendiente"
                    )
                    df_rango_ins['FECHA DE CIERRE'] = pd.to_datetime(df_rango_ins['HORA_LIQ'], errors='coerce').dt.strftime('%d/%m/%Y')

                    total_cerradas_ins = len(df_rango_ins)
                    total_llamadas_ins = int((df_rango_ins['¿SE LLAMÓ?'] == "✅ Sí").sum())
                    total_pendientes_ins = total_cerradas_ins - total_llamadas_ins

                    col_ins1, col_ins2, col_ins3 = st.columns(3)
                    col_ins1.metric("Total INSFIBRA cerradas", total_cerradas_ins)
                    col_ins2.metric("Ya con llamada registrada", total_llamadas_ins)
                    col_ins3.metric("Pendientes de llamar", total_pendientes_ins)

                    solo_pendientes_ins = st.checkbox("Mostrar solo las pendientes de llamar", key="chk_solo_pendientes_insfibra")
                    df_mostrar_ins = df_rango_ins[df_rango_ins['¿SE LLAMÓ?'] == "❌ Pendiente"] if solo_pendientes_ins else df_rango_ins

                    cols_ins_mostrar = [c for c in ['NUM', 'CLIENTE', 'NOMBRE', 'TECNICO', 'FECHA DE CIERRE', '¿SE LLAMÓ?'] if c in df_mostrar_ins.columns]
                    st.dataframe(
                        df_mostrar_ins[cols_ins_mostrar].sort_values('FECHA DE CIERRE'),
                        use_container_width=True,
                        hide_index=True
                    )

        # --------------------------------------------------------------------------
        # FLUJO: ENVÍO AUTOMÁTICO DE ENCUESTA DIGITAL POR WHATSAPP (WATI)
        # --------------------------------------------------------------------------
        elif "WhatsApp" in tab_name:
            with tab:
                if row_sel is None:
                    st.info("💡 Busque y seleccione una orden arriba para enviar la encuesta por WhatsApp.")
                else:
                    st.subheader("💬 Envío Automático mediante WATI (WhatsApp Business API)")
                    st.caption("Esta pestaña registra el envío en el historial del sistema y dispara de forma automatizada la plantilla de encuesta oficial de WATI.")
                
                    # Encapsulamos la sección de WhatsApp en un formulario para eliminar la autorecarga molesta al escribir
                    form_whatsapp = st.form(key=f"form_whatsapp_envio_{num_orden}")
                    with form_whatsapp:
                        telefono_wa = st.text_input("📞 Ingrese el número de WhatsApp del Cliente:", value="", placeholder="Ej: 99887766", key="tel_wa_QA_input")
                        comentarios_envio = st.text_area("📝 Comentarios o Notas de Envío (Opcional):", placeholder="Notas internas sobre el envío del WhatsApp...", key="comentarios_envio_wa_input")
                        btn_disparar_bot = st.form_submit_button("🚀 ENVIAR ENCUESTA OFICIAL POR WATI")
                    
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
                if row_sel is None:
                    st.info("💡 Busque y seleccione una orden arriba para auditar.")
                else:
                    st.subheader("🚙 Auditoría Técnica en Campo (Supervisión Presencial)")
                    st.caption("Formularios técnicos de control de calidad para ser completados por supervisores en el sitio de trabajo.")
                
                    # Sub-selector para separar Órdenes Varias / INSFIBRA / Fibra sin tabs anidados
                    key_subtab_campo = f"subtab_campo_selector_{num_orden}"
                    opcion_subtab_campo = st.radio(
                        "Tipo de auditoría de campo:",
                        ["📋 Auditoría de Órdenes Varias", "🔌 Auditoría de Instalaciones (INSFIBRA)", "🧵 Auditoría de Fibra en Campo"],
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
                            
                    elif opcion_subtab_campo == "🔌 Auditoría de Instalaciones (INSFIBRA)":
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

                    else:
                        st.markdown("### 🧵 Formulario de Auditoría de Fibra en Campo")
                        st.caption("Se guarda en su propia pestaña 'Auditoria_Fibra'. Si marcas el trabajo como deficiente, queda disponible en Expedientes para registrar el llamado de atención correspondiente.")

                        form_fibra = st.form(key=f"form_auditoria_fibra_{num_orden}")
                        with form_fibra:
                            col_f1, col_f2 = st.columns(2)
                            with col_f1:
                                st.text_input("Cliente:", value=nombre_cliente, disabled=True, key=f"cli_fibra_disabled_{num_orden}")
                                st.text_input("# Orden:", value=num_orden, disabled=True, key=f"ord_fibra_disabled_{num_orden}")
                                st.text_input("Técnico:", value=tecnico, disabled=True, key=f"tec_fibra_disabled_{num_orden}")
                            with col_f2:
                                # Texto libre (no number_input): metraje y viñeta a veces
                                # traen letras además de números (ej. "45M", "V-12A").
                                ruta_fibra = st.text_input("Ruta de acometida:", placeholder="Ej: Poste 3 a Caja NAP", key=f"ruta_fibra_input_{num_orden}")
                                metraje_fibra = st.text_input("Metraje:", placeholder="Ej: 45 o 45M", key=f"metraje_fibra_input_{num_orden}")
                                vineta_fibra = st.text_input("Viñeta:", placeholder="Ej: V-12345 o V-12A", key=f"vineta_fibra_input_{num_orden}")

                            comentarios_fibra = st.text_area("Comentarios:", key=f"comentarios_fibra_input_{num_orden}")
                            evaluacion_fibra = st.selectbox(
                                "🔎 Evaluación del trabajo realizado:",
                                ["Correcto", "Con observaciones", "Deficiente / Mal trabajo"],
                                key=f"evaluacion_fibra_select_{num_orden}"
                            )
                            st.caption("Si eliges \"Deficiente / Mal trabajo\", esta auditoría queda visible en el expediente del técnico con un botón para registrar el llamado de atención.")
                            fotos_fibra = st.file_uploader(
                                "📷 Imágenes (se guardan en Catbox):", type=['png', 'jpg', 'jpeg'],
                                accept_multiple_files=True, key=f"fotos_fibra_uploader_{num_orden}"
                            )
                            submit_fibra = st.form_submit_button("💾 Guardar Auditoría de Fibra")

                        if submit_fibra:
                            urls_fibra = []
                            if fotos_fibra:
                                with st.spinner("Subiendo imágenes a Catbox..."):
                                    for foto in fotos_fibra:
                                        url_foto = subir_archivo_catbox(foto.getvalue(), foto.name)
                                        if url_foto:
                                            urls_fibra.append(url_foto)

                            datos_fibra = {
                                "FECHA_AUDITORIA": get_honduras_time().strftime('%Y-%m-%d %H:%M:%S'),
                                "ORDEN_NUM": num_orden,
                                "CODIGO_CLIENTE": cliente_id,
                                "NOMBRE_CLIENTE": nombre_cliente,
                                "TECNICO": tecnico,
                                "RUTA_ACOMETIDA": ruta_fibra,
                                "METRAJE": metraje_fibra,
                                "VINETA": vineta_fibra,
                                "COMENTARIOS": comentarios_fibra,
                                "EVALUACION_TRABAJO": evaluacion_fibra,
                                "IMAGENES_URLS": ", ".join(urls_fibra) if urls_fibra else "",
                                "SUPERVISOR": st.session_state.get('username', 'N/D'),
                                "CONVERTIDO_A_FALTA": "",
                            }
                            exito_f = guardar_auditoria_campo(conn, datos_fibra, "fibra")
                            if exito_f:
                                st.success("✅ ¡Auditoría de Fibra guardada con éxito en la pestaña 'Auditoria_Fibra' de Google Sheets!")
                                if fotos_fibra and not urls_fibra:
                                    st.warning("⚠️ No se pudo subir ninguna imagen a Catbox; la auditoría se guardó sin fotos.")
                            else:
                                st.error("❌ Error al guardar en Google Sheets. Por favor, asegúrese de crear la pestaña 'Auditoria_Fibra'.")

        # --------------------------------------------------------------------------
        # FLUJO: HISTORIAL, REPORTE EN PDF Y ELIMINACIÓN DE REGISTROS
        # --------------------------------------------------------------------------
        elif "Histórico" in tab_name:
            with tab:
                st.subheader("📋 Histórico de Auditorías y Control de Calidad")
                
                tipo_consulta = st.selectbox(
                    "📋 Seleccione la Base de Datos a Consultar:",
                    ["Satisfacción de Clientes (Llamadas / QA)", "Auditoría de Campo (Operaciones)", "Auditoría de Instalaciones (INSFIBRA)", "Auditoría de Fibra en Campo"],
                    key="tipo_consulta_calidad_selectbox"
                )

                _mapa_hoja_consulta = {
                    "Satisfacción de Clientes (Llamadas / QA)": ("Calidad", "calidad_maestro.csv"),
                    "Auditoría de Campo (Operaciones)": ("Operaciones", "operaciones_maestro.csv"),
                    "Auditoría de Instalaciones (INSFIBRA)": ("Instalaciones", "instalaciones_maestro.csv"),
                    "Auditoría de Fibra en Campo": ("Auditoria_Fibra", "auditoria_fibra_maestro.csv"),
                }
                hoja_target, archivo_respaldo = _mapa_hoja_consulta[tipo_consulta]
                
                try:
                    df_qa = conn.read(spreadsheet=st.secrets["url_base_datos"], worksheet=hoja_target, ttl=0)
                except Exception:
                    df_qa = None
                    
                if df_qa is None or df_qa.empty:
                    df_qa = leer_espejo_gcs(NOMBRE_BUCKET_SISTEMA, archivo_respaldo)
                    
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

                        # --- INDICADOR OFICIAL CSAT (solo encuesta de satisfacción) ---
                        # CSAT = clientes que calificaron 4 o 5 en la pregunta 7 (satisfacción
                        # general) / total de respuestas válidas * 100. Las otras 6 preguntas
                        # se usan como diagnóstico para ver qué parte de la visita mejorar.
                        if hoja_target == "Calidad" and 'P7_SATISFACCION_GENERAL' in df_filtered.columns:
                            p7 = pd.to_numeric(df_filtered['P7_SATISFACCION_GENERAL'], errors='coerce').dropna()
                            validas = int(len(p7))
                            top = int((p7 >= 4).sum())
                            csat = (top / validas * 100) if validas > 0 else 0.0

                            st.markdown("#### 📊 Indicador Oficial de Satisfacción (CSAT)")
                            cE1, cE2, cE3 = st.columns(3)
                            cE1.metric("CSAT (P7: 4 o 5)", f"{csat:.0f}%")
                            cE2.metric("Respuestas válidas", validas)
                            cE3.metric("Calificaron 4 o 5", top)
                            st.caption("CSAT = clientes que calificaron 4 o 5 en la pregunta 7 (satisfacción general) ÷ total de respuestas válidas × 100. Solo cuentan las encuestas contestadas.")

                            diag = {
                                'P1_PUNTUALIDAD': '1. Puntualidad',
                                'P2_PRESENTACION_TRATO': '2. Presentación / Trato',
                                'P3_CLARIDAD_EXPLICACION': '3. Claridad de explicación',
                                'P4_EXPLICACION_TV_CCVEO': '4. TV Cable / CCVEO',
                                'P5_CALIDAD_SERVICIO': '5. Calidad del servicio',
                                'P6_LIMPIEZA_TRABAJO': '6. Limpieza del área',
                            }
                            filas_diag = []
                            for col_p, etiqueta in diag.items():
                                if col_p in df_filtered.columns:
                                    serie = pd.to_numeric(df_filtered[col_p], errors='coerce').dropna()
                                    if len(serie) > 0:
                                        filas_diag.append({
                                            'Indicador de diagnóstico': etiqueta,
                                            'Promedio (1-5)': round(float(serie.mean()), 2),
                                            'Respuestas': int(len(serie)),
                                        })
                            if filas_diag:
                                st.markdown("**Indicadores de diagnóstico** (para identificar qué parte de la visita mejorar):")
                                st.dataframe(pd.DataFrame(filas_diag), hide_index=True, use_container_width=True)

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
                                            tipo=_TIPO_CAMPO_POR_HOJA.get(hoja_target, "instalaciones")
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
                                        exito_del = eliminar_registro_campo(conn, ticket_del, fecha_del, tipo=_TIPO_CAMPO_POR_HOJA.get(hoja_target, "instalaciones"))
                                    
                                if exito_del:
                                    st.success(f"✅ ¡El registro correspondiente a la {ticket_del} ha sido eliminado con éxito de la pestaña '{hoja_target}'!")
                                    if 'pdf_calidad_data_final' in st.session_state:
                                        del st.session_state['pdf_calidad_data_final']
                                    import time
                                    time.sleep(1.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Error al intentar eliminar el registro de campo.")
