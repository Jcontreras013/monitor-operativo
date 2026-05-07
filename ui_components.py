import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

def get_honduras_time():
    """Ajusta la hora a UTC-6 internamente para los componentes visuales."""
    return datetime.utcnow() - timedelta(hours=6)

def aplicar_estilos_nativos():
    """Inyecta CSS para hacer que Streamlit parezca una App Nativa en Móviles"""
    hide_st_style = """
        <style>
        #MainMenu {visibility: hidden;} 
        header {visibility: hidden;} 
        footer {visibility: hidden;} 
        
        .block-container {
            padding-top: 1rem !important; 
            padding-bottom: 6rem !important; 
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        
        html, body {
            max-width: 100%;
            overflow-x: hidden;
        }
        </style>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    """
    st.markdown(hide_st_style, unsafe_allow_html=True)

@st.dialog("Detalle de Gestión de la Orden")
def mostrar_comentario_cierre(fila):
    st.markdown(f"### 📋 Información Detallada: Orden N° {fila['NUM']}")
    
    col_modal_a, col_modal_b = st.columns(2)
    with col_modal_a:
        st.markdown("##### 👤 Datos del Cliente")
        st.write(f"**N° Cuenta:** {fila.get('CLIENTE', 'N/D')}")
        nombre_real = fila.get('NOMBRE', fila.get('SUSCRIPTOR', fila.get('NOMBRE CLIENTE', fila.get('NOMBRE_CLIENTE', 'N/D'))))
        if nombre_real != 'N/D': st.write(f"**Nombre:** {nombre_real}")
        st.write(f"**Ubicación (Colonia):** {fila.get('COLONIA', 'N/D')}")
    
    with col_modal_b:
        st.markdown("##### 🚦 Datos de Operación")
        st.write(f"**Estado Actual:** {fila['ESTADO']}")
        st.write(f"**Técnico:** {fila['TECNICO']}")
        if 'MX' in fila: st.write(f"**Vehículo:** {fila.get('MX', 'S/N')}")
        if 'GPS' in fila: st.write(f"**GPS:** {fila.get('GPS', 'S/N')}")

    st.markdown("---")

    st.markdown("##### ⏳ Tiempos Operativos")
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        try:
            h_ini = pd.to_datetime(fila.get('HORA_INI')).strftime('%H:%M') if pd.notnull(fila.get('HORA_INI')) else "N/D"
        except:
            h_ini = "N/D"
        st.write(f"**Hora de Inicio:** {h_ini}")
        
    with col_t2:
        try:
            if str(fila.get('ESTADO', '')).upper() == 'CERRADA' and pd.notnull(fila.get('HORA_LIQ')):
                h_liq = pd.to_datetime(fila.get('HORA_LIQ')).strftime('%H:%M')
                st.write(f"**Hora de Cierre:** {h_liq}")
                
                if pd.notnull(fila.get('HORA_INI')):
                    diff = pd.to_datetime(fila.get('HORA_LIQ')) - pd.to_datetime(fila.get('HORA_INI'))
                    mins = diff.total_seconds() / 60
                    hrs, rem_mins = divmod(max(0, mins), 60)
                    st.write(f"**Tiempo de Gestión:** {int(hrs)}h {int(rem_mins)}m")
            else:
                st.write("**Hora de Cierre:** En Proceso (Abierta)")
                
                if pd.notnull(fila.get('HORA_INI')):
                    ahora = get_honduras_time()
                    diff = ahora - pd.to_datetime(fila.get('HORA_INI'))
                    mins = diff.total_seconds() / 60
                    hrs, rem_mins = divmod(max(0, mins), 60)
                    st.write(f"**Tiempo Transcurrido:** {int(hrs)}h {int(rem_mins)}m ⏳")
        except:
            st.write("**Hora de Cierre:** N/D")

    st.markdown("---")
    
    estatus_final_check = str(fila.get('ESTADO','')).upper().strip()
    if estatus_final_check == 'CERRADA': 
        st.success("✅ **COMENTARIO DE LIQUIDACIÓN / CIERRE FINAL:**")
    else: 
        st.markdown("**📝 COMENTARIO DE SEGUIMIENTO (EN PROCESO):**")
        
    texto_comentario_registrado = fila.get('COMENTARIO', '')
    if pd.isnull(texto_comentario_registrado) or texto_comentario_registrado == "": 
        texto_comentario_registrado = "No existen observaciones registradas para esta gestión."
    st.info(texto_comentario_registrado)
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("📋 Copiar resumen (Clic en el ícono de las 2 páginas a la derecha):")
    
    try:
        h_ini_copy = pd.to_datetime(fila.get('HORA_INI')).strftime('%H:%M') if pd.notnull(fila.get('HORA_INI')) else "N/D"
    except:
        h_ini_copy = "N/D"
        
    texto_copia = f"TECNICO={fila.get('TECNICO', 'N/D')}\nNUM={fila.get('NUM', 'N/D')}\nCOLONIA={fila.get('COLONIA', 'N/D')}\nESTADO={fila.get('ESTADO', 'N/D')}\nInicio={h_ini_copy}"
    
    st.code(texto_copia, language="text")

    if st.button("Cerrar Detalles y Volver al Monitor", use_container_width=True): 
        st.rerun()

# =========================================================================================
# LÓGICA RECONSTRUIDA DE 6 COLUMNAS
# =========================================================================================
@st.dialog("Resumen de Operaciones", width="large")
def mostrar_detalle_avance(segmento, asignadas_df, cerradas_df, inicio_mora_df=None):
    st.subheader(f"📊 Desglose: {segmento}")

    hoy_date = get_honduras_time().date()

    # Validamos que tengamos la columna de fechas real para hacer cortes
    if not cerradas_df.empty and 'FECHA_APE_DT' not in cerradas_df.columns:
        cerradas_df['FECHA_APE_DT'] = pd.to_datetime(cerradas_df['FECHA_APE'], errors='coerce')

    # Separación de datos: Mora vs Día Actual
    if 'DIAS_RETRASO' in asignadas_df.columns:
        p_mora = asignadas_df[asignadas_df['DIAS_RETRASO'] > 0]
        p_hoy = asignadas_df[asignadas_df['DIAS_RETRASO'] <= 0]
    else:
        p_mora = asignadas_df
        p_hoy = pd.DataFrame(columns=asignadas_df.columns)

    if 'FECHA_APE_DT' in cerradas_df.columns:
        c_mora = cerradas_df[cerradas_df['FECHA_APE_DT'].dt.date < hoy_date]
        c_hoy = cerradas_df[cerradas_df['FECHA_APE_DT'].dt.date == hoy_date]
    else:
        c_mora = cerradas_df
        c_hoy = pd.DataFrame(columns=cerradas_df.columns)

    # Función rápida para agrupar y contar por actividad
    def agrupar(df, col_name):
        if df.empty: return pd.DataFrame(columns=['ACTIVIDAD', col_name])
        return df.groupby('ACTIVIDAD').size().reset_index(name=col_name)

    # 1. Armamos bloque de MORA
    if inicio_mora_df is not None:
        grp_mora_ini = agrupar(inicio_mora_df, 'Mora inicial')
    else:
        grp_mora_ini = agrupar(pd.concat([p_mora, c_mora]), 'Mora inicial')

    grp_c_mora = agrupar(c_mora, 'Cerradas')

    # 2. Armamos bloque de HOY
    grp_a_hoy = agrupar(pd.concat([p_hoy, c_hoy]), 'Asignadas hoy')
    grp_c_hoy = agrupar(c_hoy, 'Cerradas hoy')

    # Extraemos todas las actividades únicas para tener el cascarón de la tabla
    dfs = [grp_mora_ini, grp_c_mora, grp_a_hoy, grp_c_hoy]
    actividades = set()
    for df in dfs:
        if not df.empty: actividades.update(df['ACTIVIDAD'].unique())

    resumen = pd.DataFrame({'ACTIVIDAD': list(actividades)})

    # Unimos todo
    for df in dfs:
        if not df.empty: resumen = pd.merge(resumen, df, on='ACTIVIDAD', how='left')

    resumen = resumen.fillna(0)
    
    cols_calc = ['Mora inicial', 'Cerradas', 'Asignadas hoy', 'Cerradas hoy']
    for col in cols_calc:
        if col not in resumen.columns: resumen[col] = 0
        resumen[col] = resumen[col].astype(int)

    # Las dos restas mágicas
    resumen['Total_M'] = resumen['Mora inicial'] - resumen['Cerradas']
    resumen['Total_H'] = resumen['Asignadas hoy'] - resumen['Cerradas hoy']

    # Estética
    resumen.rename(columns={'ACTIVIDAD': 'Tipo'}, inplace=True)
    resumen = resumen.sort_values(by='Tipo').reset_index(drop=True)

    # Fila de Totales
    fila_total = {'Tipo': 'TOTAL GENERAL'}
    for col in ['Mora inicial', 'Cerradas', 'Total_M', 'Asignadas hoy', 'Cerradas hoy', 'Total_H']:
        fila_total[col] = resumen[col].sum()

    resumen = pd.concat([resumen, pd.DataFrame([fila_total])], ignore_index=True)

    # Nombres exactos que se mostrarán en pantalla
    col_config = {
        "Tipo": st.column_config.TextColumn("TIPO DE ORDEN", width="medium"),
        "Mora inicial": st.column_config.NumberColumn("Mora inicial", format="%d"),
        "Cerradas": st.column_config.NumberColumn("Cerradas", format="%d"),
        "Total_M": st.column_config.NumberColumn("Total", format="%d"),
        "Asignadas hoy": st.column_config.NumberColumn("Asignadas hoy", format="%d"),
        "Cerradas hoy": st.column_config.NumberColumn("Cerradas hoy", format="%d"),
        "Total_H": st.column_config.NumberColumn("Total", format="%d")
    }

    cols_orden = ['Tipo', 'Mora inicial', 'Cerradas', 'Total_M', 'Asignadas hoy', 'Cerradas hoy', 'Total_H']
    st.dataframe(resumen[cols_orden], use_container_width=True, hide_index=True, column_config=col_config)
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar Resumen", use_container_width=True): st.rerun()

def aplicar_estilos_df(df_original_para_estilo):
    df_visual_procesado = df_original_para_estilo.copy()
    def row_styler_logic(fila_v):
        estilos_fila = [''] * len(fila_v)
        if fila_v.get('ES_OFFLINE') == True:
            if 'NUM' in fila_v.index: estilos_fila[fila_v.index.get_loc('NUM')] = 'background-color: #9b111e; color: white; font-weight: bold'
        est_val = str(fila_v.get('ESTADO','')).upper().strip()
        if est_val == 'CERRADA':
            if 'TIEMPO_REAL' in fila_v.index:
                idx_tr = fila_v.index.get_loc('TIEMPO_REAL')
                minutos_trabajados = fila_v.get('MINUTOS_CALC', 0)
                if minutos_trabajados < 60: estilos_fila[idx_tr] = 'background-color: #4caf50; color: white; font-weight: bold'
                elif minutos_trabajados > 119: estilos_fila[idx_tr] = 'background-color: #d32f2f; color: white; font-weight: bold'
        if fila_v.get('ALERTA_TIEMPO') == True:
            if 'HORA_INI' in fila_v.index: estilos_fila[fila_v.index.get_loc('HORA_INI')] = 'background-color: #ff5722; color: white; font-weight: bold'
        if 'DIAS_RETRASO' in fila_v.index:
            idx_dias = fila_v.index.get_loc('DIAS_RETRASO')
            val_dias = fila_v['DIAS_RETRASO']
            if val_dias >= 7: estilos_fila[idx_dias] = 'background-color: #d32f2f; color: white; font-weight: bold' 
            elif 4 <= val_dias <= 6: estilos_fila[idx_dias] = 'background-color: #f57c00; color: white; font-weight: bold' 
            elif 1 <= val_dias <= 3: estilos_fila[idx_dias] = 'background-color: #fbc02d; color: black; font-weight: bold' 
            elif val_dias <= 0: estilos_fila[idx_dias] = 'background-color: #388e3c; color: white; font-weight: bold' 
        return estilos_fila

    if 'NUM' in df_visual_procesado.columns: df_visual_procesado['NUM'] = df_visual_procesado.apply(lambda r: f"⚠️ {r['NUM']}" if r.get('ALERTA_TIEMPO') else r['NUM'], axis=1)
    if 'HORA_INI' in df_visual_procesado.columns: df_visual_procesado['HORA_INI'] = pd.to_datetime(df_visual_procesado['HORA_INI'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    if 'HORA_LIQ' in df_visual_procesado.columns: df_visual_procesado['HORA_LIQ'] = pd.to_datetime(df_visual_procesado['HORA_LIQ'], errors='coerce').dt.strftime('%H:%M').fillna("---")
    cols_a_mostrar = ['DIAS_RETRASO', 'NUM', 'HORA_INI','HORA_LIQ', 'TIEMPO_REAL', 'ESTADO', 'TECNICO', 'ACTIVIDAD', 'MOTIVO', 'CLIENTE', 'NOMBRE', 'COLONIA', 'COMENTARIO', 'ES_OFFLINE', 'MINUTOS_CALC']
    columnas_finales = [c for c in cols_a_mostrar if c in df_visual_procesado.columns]
    return df_visual_procesado[columnas_finales], row_styler_logic
