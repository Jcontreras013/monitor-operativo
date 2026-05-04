import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from tools import get_honduras_time

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

@st.dialog("Resumen de Operaciones", width="large")
def mostrar_detalle_avance(segmento, asignadas_df, cerradas_df, inicio_mora_df=None):
    st.subheader(f"📊 Desglose: {segmento}")
    if not asignadas_df.empty: p = asignadas_df.groupby('ACTIVIDAD').size().reset_index(name='Pendientes (Hoy)')
    else: p = pd.DataFrame(columns=['ACTIVIDAD', 'Pendientes (Hoy)'])
    if not cerradas_df.empty: c = cerradas_df.groupby('ACTIVIDAD').size().reset_index(name='Cerradas')
    else: c = pd.DataFrame(columns=['ACTIVIDAD', 'Cerradas'])
    resumen = pd.merge(p, c, on='ACTIVIDAD', how='outer').fillna(0)
    if inicio_mora_df is not None:
        if not inicio_mora_df.empty: m = inicio_mora_df.groupby('ACTIVIDAD').size().reset_index(name='Inicio (Mora)')
        else: m = pd.DataFrame(columns=['ACTIVIDAD', 'Inicio (Mora)'])
        resumen = pd.merge(m, resumen, on='ACTIVIDAD', how='outer').fillna(0)
    else: resumen.rename(columns={'Pendientes (Hoy)': 'Asignadas'}, inplace=True)

    if not resumen.empty:
        for col in resumen.columns:
            if col != 'ACTIVIDAD': resumen[col] = resumen[col].astype(int)
        resumen.rename(columns={'ACTIVIDAD': 'Tipo'}, inplace=True)
        resumen = resumen.sort_values(by='Tipo').reset_index(drop=True)
        fila_total = {'Tipo': 'TOTAL GENERAL'}
        for col in resumen.columns:
            if col != 'Tipo': fila_total[col] = resumen[col].sum()
        resumen = pd.concat([resumen, pd.DataFrame([fila_total])], ignore_index=True)
        col_config = {"Tipo": st.column_config.TextColumn("TIPO DE ORDEN", width="medium")}
        if 'Inicio (Mora)' in resumen.columns:
            col_config["Inicio (Mora)"] = st.column_config.NumberColumn("INICIO (MORA)", format="%d", width="small")
            col_config["Pendientes (Hoy)"] = st.column_config.NumberColumn("PENDIENTES", format="%d", width="small")
        else:
            col_config["Asignadas"] = st.column_config.NumberColumn("ASIGNADAS (Total)", format="%d", width="small")
        col_config["Cerradas"] = st.column_config.NumberColumn("CERRADAS", format="%d", width="small")
        st.dataframe(resumen, use_container_width=True, hide_index=True, column_config=col_config)
    else: st.info("No hay datos de operaciones para este segmento.")
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
