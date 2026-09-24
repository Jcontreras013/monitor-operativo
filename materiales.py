import io
import pandas as pd
import streamlit as st

from tools import read_file_robust, procesar_dataframe_base

# ==============================================================================
# AUDITORÍA DE MATERIALES: CEPHEUS vs. MOVIMIENTOS DE BODEGA (ODOO)
# ==============================================================================
# El problema que resuelve este módulo: la razón de cierre que el técnico
# elige en Cepheus (ej. "Corte de Acometida") no siempre refleja lo que
# realmente hizo -- a veces solo corrió reserva o no tenía material y aun así
# cierra con una razón que implica un cambio de cable. La única forma
# objetiva de confirmarlo es cruzar contra lo que de verdad salió de bodega
# (el reporte de movimientos de stock que exporta Odoo).

ACTIVIDADES_FIBRA_DEFAULT = ['SOPFIBRA', 'SOPFIBRACORP']
RAZONES_EXIGEN_METRAJE_DEFAULT = "CORTE DE ACOMETIDA"

# Nombres posibles de la columna de cantidad realmente entregada en el
# reporte stock.move.line de Odoo, en orden de preferencia. "Reservado" NO
# sirve: es lo apartado, no lo que salió.
COLUMNAS_METROS_ODOO = ['HECHO', 'CANTIDAD HECHA', 'CANTIDAD REALIZADA', 'QUANTITY DONE', 'DONE', 'CANTIDAD']
UNIDADES_METRO = {'m', 'mt', 'mts', 'metro', 'metros'}

SIN_ORDEN_CEPHEUS = 'N/D (orden no encontrada en Cepheus)'
ACTIVIDAD_SIN_ORDEN = 'SIN ORDEN EN CEPHEUS'

# Subirlo cada vez que cambie la forma del dict de resultados: así una
# sesión que cruzó con una versión anterior pide volver a cruzar en vez de
# mostrar datos incompletos o fallar por una llave que no existe.
VERSION_RESULTADO = 2
# Igual, pero para el formato del PDF (un PDF ya preparado en la sesión se
# regenera si cambió su diseño).
VERSION_PDF = 2


def _normalizar_num(serie):
    return serie.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()


def extraer_fibra_odoo(df_odoo):
    """
    Deja solo los movimientos de fibra medidos en metros, con columnas
    normalizadas ORDEN_NORM / PRODUCTO / METROS. Conectores, patch cords,
    fajillas, etc. no sirven para confirmar si hubo un lanzamiento real.
    Devuelve (df_fibra, nombre_columna_metros_usada).
    """
    cols_por_nombre = {str(c).strip().upper(): c for c in df_odoo.columns}
    col_producto = next((c for c in df_odoo.columns if 'PRODUCTO' in str(c).upper()), None)
    col_unidad = next((c for c in df_odoo.columns if 'UNIDAD' in str(c).upper()), None)
    col_origen = next((c for c in df_odoo.columns if 'ORIGEN' in str(c).upper()), None)
    col_metros = next((cols_por_nombre[n] for n in COLUMNAS_METROS_ODOO if n in cols_por_nombre), None)

    faltantes = [nombre for nombre, col in [
        ('Producto', col_producto), ('Unidad de medida', col_unidad),
        ('Origen', col_origen), ('Hecho (cantidad entregada)', col_metros),
    ] if col is None]
    if faltantes:
        raise ValueError(
            "El archivo de Odoo no tiene las columnas esperadas: " + ", ".join(faltantes)
            + f". Columnas encontradas: {', '.join(map(str, df_odoo.columns))}"
        )

    es_fibra = df_odoo[col_producto].astype(str).str.upper().str.contains('FIBRA', na=False)
    es_metro = df_odoo[col_unidad].astype(str).str.strip().str.lower().isin(UNIDADES_METRO)
    mask = es_fibra & es_metro

    df_fibra = pd.DataFrame({
        'ORDEN_NORM': _normalizar_num(df_odoo.loc[mask, col_origen]),
        'PRODUCTO': df_odoo.loc[mask, col_producto].astype(str),
        'METROS': pd.to_numeric(df_odoo.loc[mask, col_metros], errors='coerce').fillna(0),
    })
    return df_fibra, str(col_metros)


def cruzar_cepheus_odoo(df_cep, metraje_por_orden, actividades, razones_exigen_metraje):
    """
    Regla aplicada: entre las órdenes CERRADAS de las actividades indicadas,
    las que se cerraron con una razón de la lista `razones_exigen_metraje`
    deben tener metraje de fibra en Odoo. Las que no lo tienen quedan
    marcadas como SIN_METRAJE; si además el comentario de cierre menciona
    "reserva", se marca MENCIONA_RESERVA -- es la prueba más clara de que el
    propio técnico admite que no hizo el cambio.
    Devuelve (df_detalle, df_resumen_por_tecnico).
    """
    act_upper = df_cep['ACTIVIDAD'].astype(str).str.upper().str.strip()
    est_upper = df_cep['ESTADO'].astype(str).str.upper().str.strip()
    actividades_upper = [a.upper().strip() for a in actividades]
    df_sel = df_cep[act_upper.isin(actividades_upper) & (est_upper == 'CERRADA')].copy()

    df_sel = df_sel.merge(metraje_por_orden, left_on='NUM_NORM', right_index=True, how='left')
    df_sel['METRAJE_ODOO'] = df_sel['METRAJE_ODOO'].fillna(0)

    razones_upper = [r.upper().strip() for r in razones_exigen_metraje]
    razon_orden_upper = df_sel['RAZON_CIERRE_SOP'].astype(str).str.upper().str.strip()
    df_sel = df_sel[razon_orden_upper.isin(razones_upper)].copy()

    df_sel['SIN_METRAJE'] = df_sel['METRAJE_ODOO'] <= 0
    com_upper = df_sel['COMENTARIO_CIERRE'].astype(str).str.upper()
    df_sel['MENCIONA_RESERVA'] = df_sel['SIN_METRAJE'] & com_upper.str.contains('RESERVA', na=False)

    columnas_detalle = [
        'NUM_NORM', 'TECNICO', 'ACTIVIDAD', 'RAZON_CIERRE_SOP', 'COMENTARIO_CIERRE',
        'CLIENTE', 'HORA_LIQ', 'METRAJE_ODOO', 'SIN_METRAJE', 'MENCIONA_RESERVA',
    ]
    df_detalle = df_sel[[c for c in columnas_detalle if c in df_sel.columns]].rename(columns={
        'NUM_NORM': 'ORDEN',
        'RAZON_CIERRE_SOP': 'RAZON_CIERRE',
        'COMENTARIO_CIERRE': 'COMENTARIO',
        'HORA_LIQ': 'FECHA_CIERRE',
    })

    resumen = df_sel.groupby('TECNICO').agg(
        TOTAL_ORDENES=('NUM_NORM', 'count'),
        SIN_METRAJE=('SIN_METRAJE', 'sum'),
        MENCIONAN_RESERVA=('MENCIONA_RESERVA', 'sum'),
        METROS_ODOO=('METRAJE_ODOO', 'sum'),
    ).reset_index()
    resumen['CON_METRAJE'] = resumen['TOTAL_ORDENES'] - resumen['SIN_METRAJE']
    resumen['PCT_SIN_METRAJE'] = (resumen['SIN_METRAJE'] / resumen['TOTAL_ORDENES'] * 100).round(1)
    resumen = resumen[[
        'TECNICO', 'TOTAL_ORDENES', 'CON_METRAJE', 'SIN_METRAJE', 'PCT_SIN_METRAJE',
        'MENCIONAN_RESERVA', 'METROS_ODOO',
    ]].sort_values('SIN_METRAJE', ascending=False).reset_index(drop=True)

    return df_detalle, resumen


def _agrupar_metros(df_ordenes, columnas):
    grupo = df_ordenes.groupby(columnas).agg(
        ORDENES=('ORDEN_NORM', 'nunique'),
        METROS=('METROS', 'sum'),
    ).reset_index()
    grupo['PROMEDIO_M_X_ORDEN'] = (grupo['METROS'] / grupo['ORDENES']).round(1)
    return grupo


def calcular_metraje_real_usado(df_cep, df_fibra):
    """
    Metraje REAL de fibra retirado de bodega en todo el periodo del archivo
    de Odoo, sin filtrar por razón de cierre. Técnico y actividad se toman
    de Cepheus cruzando por número de orden (más confiable que parsear el
    nombre desde el campo "Desde" de Odoo); lo que no aparece en Cepheus
    queda en una fila aparte para que se note, no se pierde.

    El desglose por técnico va SIEMPRE separado por actividad: un PEXTERNO
    o una INSFIBRA consumen mucho más cable que un SOPFIBRA, así que
    sumarlos juntos hace que el promedio por técnico no sea comparable.
    Devuelve (df_por_orden, por_producto, por_actividad, por_tecnico).
    """
    por_producto = df_fibra.groupby('PRODUCTO').agg(
        MOVIMIENTOS=('METROS', 'count'),
        METROS=('METROS', 'sum'),
    ).reset_index().sort_values('METROS', ascending=False).reset_index(drop=True)

    df_por_orden = df_fibra.groupby('ORDEN_NORM')['METROS'].sum().reset_index()
    datos_orden = df_cep.drop_duplicates('NUM_NORM').set_index('NUM_NORM')
    df_por_orden['TECNICO'] = df_por_orden['ORDEN_NORM'].map(datos_orden['TECNICO']).fillna(SIN_ORDEN_CEPHEUS)
    df_por_orden['ACTIVIDAD'] = (
        df_por_orden['ORDEN_NORM'].map(datos_orden['ACTIVIDAD'])
        .astype(str).str.upper().str.strip()
        .where(df_por_orden['ORDEN_NORM'].isin(datos_orden.index), ACTIVIDAD_SIN_ORDEN)
    )

    por_actividad = _agrupar_metros(df_por_orden, ['ACTIVIDAD']) \
        .sort_values('METROS', ascending=False).reset_index(drop=True)
    por_tecnico = _agrupar_metros(df_por_orden, ['ACTIVIDAD', 'TECNICO'])
    orden_actividad = {a: i for i, a in enumerate(por_actividad['ACTIVIDAD'])}
    por_tecnico = por_tecnico.assign(_o=por_tecnico['ACTIVIDAD'].map(orden_actividad)) \
        .sort_values(['_o', 'METROS'], ascending=[True, False]) \
        .drop(columns='_o').reset_index(drop=True)

    return df_por_orden, por_producto, por_actividad, por_tecnico


def procesar_auditoria_materiales(df_cepheus_crudo, df_odoo_crudo, actividades, razones):
    """Corre todo el análisis y devuelve un solo dict con los resultados."""
    df_cep = procesar_dataframe_base(df_cepheus_crudo.copy())
    df_cep['NUM_NORM'] = _normalizar_num(df_cep['NUM'])

    df_fibra, col_metros = extraer_fibra_odoo(df_odoo_crudo)
    metraje_por_orden = df_fibra.groupby('ORDEN_NORM')['METROS'].sum().rename('METRAJE_ODOO')

    df_detalle, resumen = cruzar_cepheus_odoo(df_cep, metraje_por_orden, actividades, razones)
    df_por_orden, por_producto, por_actividad, por_tecnico = calcular_metraje_real_usado(df_cep, df_fibra)

    total_metros = float(df_fibra['METROS'].sum())
    en_cepheus = df_por_orden['ACTIVIDAD'] != ACTIVIDAD_SIN_ORDEN
    en_actividades = df_por_orden['ACTIVIDAD'].isin([a.upper().strip() for a in actividades])

    return {
        'version': VERSION_RESULTADO,
        'detalle': df_detalle,
        'resumen': resumen,
        'metraje_por_producto': por_producto,
        'metraje_por_actividad': por_actividad,
        'metraje_por_tecnico': por_tecnico,
        'total_metros': total_metros,
        'metros_con_orden_cepheus': float(df_por_orden.loc[en_cepheus, 'METROS'].sum()),
        'metros_sin_orden_cepheus': float(df_por_orden.loc[~en_cepheus, 'METROS'].sum()),
        'metros_actividades_evaluadas': float(df_por_orden.loc[en_actividades, 'METROS'].sum()),
        'metros_ordenes_evaluadas': float(df_detalle['METRAJE_ODOO'].sum()),
        'col_metros': col_metros,
        'actividades': list(actividades),
        'razones': [r.strip().upper() for r in razones],
    }


# ==============================================================================
# INTERFAZ STREAMLIT
# ==============================================================================
def mostrar_auditoria_materiales(*args, **kwargs):
    st.title("🔍 Auditoría de Materiales SOPFIBRA")
    st.caption(
        "Cruza las órdenes de Cepheus contra los materiales realmente retirados de bodega "
        "(reporte de movimientos de stock de Odoo), para detectar cierres que no tienen un "
        "lanzamiento de fibra real detrás."
    )
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        archivo_cepheus = st.file_uploader(
            "1. rep_actividades (Cepheus)", type=['xlsx', 'csv'], key="up_mat_cepheus"
        )
    with col2:
        archivo_odoo = st.file_uploader(
            "2. Movimientos de Stock (Odoo)", type=['xlsx', 'csv'], key="up_mat_odoo"
        )

    col_a, col_r = st.columns(2)
    with col_a:
        actividades_sel = st.multiselect(
            "Actividades a evaluar:",
            options=['SOPFIBRA', 'SOPFIBRACORP', 'SOP', 'SOPCORP'],
            default=ACTIVIDADES_FIBRA_DEFAULT,
            key="mat_actividades_sel",
        )
    with col_r:
        razones_txt = st.text_input(
            "Razón(es) de cierre que deben llevar metraje (separadas por coma):",
            value=RAZONES_EXIGEN_METRAJE_DEFAULT,
            key="mat_razones_sel",
        )

    if st.button("🚀 Cruzar Información", type="primary", use_container_width=True):
        if archivo_cepheus is None or archivo_odoo is None:
            st.warning("⚠️ Sube ambos archivos para poder cruzar la información.")
        elif not actividades_sel:
            st.warning("⚠️ Selecciona al menos una actividad.")
        else:
            with st.spinner("Cruzando Cepheus contra los movimientos de bodega..."):
                try:
                    razones = [r for r in razones_txt.split(',') if r.strip()]
                    st.session_state['mat_resultado'] = procesar_auditoria_materiales(
                        read_file_robust(archivo_cepheus), read_file_robust(archivo_odoo),
                        actividades_sel, razones,
                    )
                except Exception as e:
                    st.error(f"❌ Error al cruzar la información: {e}")

    # Todo el resultado vive en UNA sola llave: así nunca se muestra un
    # análisis a medias (ej. detalle de un cruce viejo con metraje en 0).
    res = st.session_state.get('mat_resultado')
    if res is None:
        return
    if res.get('version') != VERSION_RESULTADO:
        st.info("🔄 El módulo se actualizó. Presiona **Cruzar Información** de nuevo para ver los resultados.")
        return

    df_detalle = res['detalle']
    resumen = res['resumen']

    st.divider()

    # --- METRAJE REAL (no depende del filtro de actividad/razón) ---
    st.markdown("#### 📏 Metraje Real de Fibra Usado en el Periodo")
    st.caption(
        f"Metros de fibra realmente entregados según Odoo (columna **{res['col_metros']}**, unidad en metros), "
        "en TODO el periodo del archivo — sin filtrar por actividad ni razón de cierre."
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total metros de fibra usados", f"{res['total_metros']:,.0f} m")
    m2.metric(f"En {' + '.join(res['actividades'])}", f"{res['metros_actividades_evaluadas']:,.0f} m")
    m3.metric(f"En órdenes {', '.join(res['razones']).title()}", f"{res['metros_ordenes_evaluadas']:,.0f} m")
    m4.metric("Sin orden en Cepheus", f"{res['metros_sin_orden_cepheus']:,.0f} m")
    if res['metros_sin_orden_cepheus'] > 0:
        st.caption(
            "ℹ️ \"Sin orden en Cepheus\" son movimientos de bodega cuyo número de orden no aparece en el "
            "rep_actividades subido — normalmente porque los dos archivos no cubren exactamente las mismas fechas."
        )
    col_mp1, col_mp2 = st.columns(2)
    with col_mp1:
        st.markdown("**Por tipo de fibra**")
        st.dataframe(res['metraje_por_producto'], use_container_width=True, hide_index=True)
    with col_mp2:
        st.markdown("**Por actividad**")
        st.dataframe(res['metraje_por_actividad'], use_container_width=True, hide_index=True)

    st.markdown("**Por técnico y actividad**")
    st.caption("Separado por actividad para que el promedio por orden sea comparable: un PEXTERNO o una INSFIBRA llevan mucho más cable que un SOPFIBRA.")
    por_tecnico = res['metraje_por_tecnico']
    actividades_metraje = st.multiselect(
        "Ver actividades:",
        options=list(res['metraje_por_actividad']['ACTIVIDAD']),
        default=list(res['metraje_por_actividad']['ACTIVIDAD']),
        key="mat_filtro_actividad_metraje",
    )
    st.dataframe(
        por_tecnico[por_tecnico['ACTIVIDAD'].isin(actividades_metraje)],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # --- AUDITORÍA DE LA RAZÓN DE CIERRE ---
    st.markdown(f"#### 🧾 Órdenes cerradas como: {', '.join(res['razones'])}")
    total = len(df_detalle)
    if total == 0:
        st.info("No se encontraron órdenes que coincidan con las actividades y razones de cierre seleccionadas.")
        return

    sin_metraje = int(df_detalle['SIN_METRAJE'].sum())
    con_metraje = total - sin_metraje
    mencionan_reserva = int(df_detalle['MENCIONA_RESERVA'].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Órdenes evaluadas", total)
    c2.metric("Con metraje real", con_metraje)
    c3.metric("Sin metraje (mal depuradas)", sin_metraje, delta=f"{sin_metraje / total * 100:.0f}%", delta_color="inverse")
    c4.metric("Mencionan 'reserva' sin metraje", mencionan_reserva)

    st.markdown("#### 📋 Resumen por Técnico")
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    st.markdown("#### 🔎 Detalle de Órdenes")
    solo_sospechosas = st.checkbox(
        "Mostrar solo órdenes sin metraje (sospechosas)", value=True, key="mat_solo_sospechosas"
    )
    df_mostrar = df_detalle[df_detalle['SIN_METRAJE']] if solo_sospechosas else df_detalle
    st.dataframe(
        df_mostrar.sort_values('MENCIONA_RESERVA', ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            resumen.to_excel(writer, sheet_name='Resumen por Tecnico', index=False)
            df_detalle.to_excel(writer, sheet_name='Detalle Ordenes', index=False)
            res['metraje_por_producto'].to_excel(writer, sheet_name='Metraje Real x Producto', index=False)
            res['metraje_por_actividad'].to_excel(writer, sheet_name='Metraje Real x Actividad', index=False)
            res['metraje_por_tecnico'].to_excel(writer, sheet_name='Metraje Real x Tecnico', index=False)
        st.download_button(
            "⬇️ Descargar Excel (Resumen + Detalle)",
            data=buffer.getvalue(),
            file_name="auditoria_materiales_sopfibra.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_mat_excel",
            use_container_width=True,
        )
    with col_dl2:
        id_estado_pdf = f"mat_pdf_v{VERSION_RESULTADO}.{VERSION_PDF}_{total}_{sin_metraje}_{mencionan_reserva}_{res['total_metros']:.0f}"
        if st.session_state.get('mat_estado_pdf') != id_estado_pdf:
            if st.button("📥 Preparar Reporte PDF", key="btn_mat_pdf", use_container_width=True):
                with st.spinner("Generando PDF..."):
                    from tools import generar_pdf_auditoria_materiales
                    st.session_state['mat_pdf_bytes'] = generar_pdf_auditoria_materiales(res)
                    st.session_state['mat_estado_pdf'] = id_estado_pdf
                st.rerun()
        else:
            st.download_button(
                "⬇️ Descargar Reporte PDF",
                data=st.session_state['mat_pdf_bytes'],
                file_name="auditoria_materiales_sopfibra.pdf",
                mime="application/pdf",
                key="dl_mat_pdf",
                use_container_width=True,
            )
