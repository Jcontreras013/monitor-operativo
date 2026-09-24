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


def _normalizar_num(serie):
    return serie.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()


def calcular_metraje_por_orden(df_odoo):
    """
    Suma, por número de orden (columna 'Origen' del reporte de Odoo), el
    metraje de fibra realmente retirado de bodega. Solo cuenta productos de
    fibra medidos en metros -- conectores, patch cords, fajillas, etc. no
    sirven para confirmar si hubo o no un lanzamiento real de cable.
    """
    col_producto = next((c for c in df_odoo.columns if 'PRODUCTO' in str(c).upper()), None)
    col_unidad = next((c for c in df_odoo.columns if 'UNIDAD' in str(c).upper()), None)
    col_origen = next((c for c in df_odoo.columns if 'ORIGEN' in str(c).upper()), None)
    col_hecho = next((c for c in df_odoo.columns if str(c).strip().upper() == 'HECHO'), None)

    faltantes = [nombre for nombre, col in [
        ('Producto', col_producto), ('Unidad de medida', col_unidad),
        ('Origen', col_origen), ('Hecho', col_hecho),
    ] if col is None]
    if faltantes:
        raise ValueError(
            "El archivo de Odoo no tiene las columnas esperadas: " + ", ".join(faltantes)
        )

    df = df_odoo.copy()
    es_fibra = df[col_producto].astype(str).str.upper().str.contains('FIBRA', na=False)
    es_metro = df[col_unidad].astype(str).str.strip().str.lower() == 'm'
    df_fibra = df[es_fibra & es_metro].copy()
    df_fibra['ORDEN_NORM'] = _normalizar_num(df_fibra[col_origen])
    return df_fibra.groupby('ORDEN_NORM')[col_hecho].sum().rename('METRAJE_ODOO')


def cruzar_cepheus_odoo(df_cepheus_crudo, df_odoo_crudo, actividades, razones_exigen_metraje):
    """
    Cruza el reporte de Cepheus (rep_actividades) con los movimientos de
    material de Odoo. Devuelve (df_detalle, df_resumen_por_tecnico).

    Regla aplicada: entre las órdenes CERRADAS de las actividades indicadas,
    las que se cerraron con una razón de la lista `razones_exigen_metraje`
    deben tener metraje de fibra en Odoo. Las que no lo tienen quedan
    marcadas como SIN_METRAJE; si además el comentario de cierre menciona
    "reserva", se marca MENCIONA_RESERVA -- es la prueba más clara de que el
    propio técnico admite que no hizo el cambio.
    """
    df_cep = procesar_dataframe_base(df_cepheus_crudo.copy())
    df_cep['NUM_NORM'] = _normalizar_num(df_cep['NUM'])

    metraje_por_orden = calcular_metraje_por_orden(df_odoo_crudo)

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
    ).reset_index()
    resumen['CON_METRAJE'] = resumen['TOTAL_ORDENES'] - resumen['SIN_METRAJE']
    resumen['PCT_SIN_METRAJE'] = (resumen['SIN_METRAJE'] / resumen['TOTAL_ORDENES'] * 100).round(1)
    resumen = resumen.sort_values('SIN_METRAJE', ascending=False).reset_index(drop=True)

    return df_detalle, resumen


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
                    df_cepheus_crudo = read_file_robust(archivo_cepheus)
                    df_odoo_crudo = read_file_robust(archivo_odoo)
                    razones = [r for r in razones_txt.split(',') if r.strip()]
                    df_detalle, resumen = cruzar_cepheus_odoo(
                        df_cepheus_crudo, df_odoo_crudo, actividades_sel, razones
                    )
                    st.session_state['mat_detalle'] = df_detalle
                    st.session_state['mat_resumen'] = resumen
                except Exception as e:
                    st.error(f"❌ Error al cruzar la información: {e}")

    if 'mat_detalle' not in st.session_state:
        return

    df_detalle = st.session_state['mat_detalle']
    resumen = st.session_state['mat_resumen']

    st.divider()

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

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        resumen.to_excel(writer, sheet_name='Resumen por Tecnico', index=False)
        df_detalle.to_excel(writer, sheet_name='Detalle Ordenes', index=False)
    st.download_button(
        "⬇️ Descargar Excel (Resumen + Detalle)",
        data=buffer.getvalue(),
        file_name="auditoria_materiales_sopfibra.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_mat_excel",
    )
