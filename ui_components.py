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

@st.dialog("Resumen de Operaciones", width="large")
def mostrar_detalle_avance(segmento, asignadas_df, cerradas_df, inicio_mora_df=None):
    st.subheader(f"📊 Desglose: {segmento}")
    
    hoy = get_honduras_time().date()
    p_df = asignadas_df.copy()
    c_df = cerradas_df.copy()
    
    # 1. Separar Mora y Hoy para Asignadas (Pendientes en ruta)
    if 'DIAS_RETRASO' in p_df.columns:
        p_mora = p_df[p_df['DIAS_RETRASO'] > 0]
        p_hoy = p_df[p_df['DIAS_RETRASO'] == 0]
    else:
        p_df['FECHA_APE_DT'] = pd.to_datetime(p_df['FECHA_APE'], errors='coerce')
        p_mora = p_df[p_df['FECHA_APE_DT'].dt.date < hoy]
        p_hoy = p_df[p_df['FECHA_APE_DT'].dt.date == hoy]
        
    # 2. Separar Mora y Hoy para Cerradas
    c_df['FECHA_APE_DT'] = pd.to_datetime(c_df['FECHA_APE'], errors='coerce')
    c_mora = c_df[c_df['FECHA_APE_DT'].dt.date < hoy]
    c_hoy = c_df[c_df['FECHA_APE_DT'].dt.date == hoy]

    # 3. Agrupar por TIPO DE ACTIVIDAD
    def get_counts(df, col_name):
        if df.empty: return pd.DataFrame(columns=['ACTIVIDAD', col_name])
        return df.groupby('ACTIVIDAD').size().reset_index(name=col_name)

    pm = get_counts(p_mora, 'MORA_Asig')
    cm = get_counts(c_mora, 'MORA_Cerr')
    ph = get_counts(p_hoy, 'HOY_Asig')
    ch = get_counts(c_hoy, 'HOY_Cerr')

    # Unir todas las tablas
    resumen = pd.DataFrame(columns=['ACTIVIDAD'])
    for df_parcial in [pm, cm, ph, ch]:
        if not df_parcial.empty:
            resumen = pd.merge(resumen, df_parcial, on='ACTIVIDAD', how='outer')

    if resumen.empty or len(resumen.columns) == 1:
        st.info("No hay datos de operaciones para este segmento.")
        if st.button("Cerrar Resumen", use_container_width=True): st.rerun()
        return

    resumen = resumen.fillna(0)
    
    # Asegurar que existan las columnas por si alguna categoría estaba en 0
    for col in ['MORA_Asig', 'MORA_Cerr', 'HOY_Asig', 'HOY_Cerr']:
        if col not in resumen.columns:
            resumen[col] = 0

    # 4. Calcular Totales Verticales y Horizontales
    resumen['MORA_Total'] = resumen['MORA_Asig'] + resumen['MORA_Cerr']
    resumen['HOY_Total'] = resumen['HOY_Asig'] + resumen['HOY_Cerr']
    resumen['GRAN_TOTAL'] = resumen['MORA_Total'] + resumen['HOY_Total']
    
    for col in resumen.columns:
        if col != 'ACTIVIDAD': resumen[col] = resumen[col].astype(int)
        
    resumen.rename(columns={'ACTIVIDAD': 'Tipo'}, inplace=True)
    resumen = resumen.sort_values(by='Tipo').reset_index(drop=True)
    
    # Fila de Total General al final de la tabla
    fila_total = {'Tipo': 'TOTAL GENERAL'}
    for col in resumen.columns:
        if col != 'Tipo': fila_total[col] = resumen[col].sum()
    resumen = pd.concat([resumen, pd.DataFrame([fila_total])], ignore_index=True)

    # 5. Configuración visual para Streamlit
    col_config = {
        "Tipo": st.column_config.TextColumn("TIPO DE ORDEN", width="medium"),
        "MORA_Asig": st.column_config.NumberColumn("🔴 Mora (Asig)", format="%d"),
        "MORA_Cerr": st.column_config.NumberColumn("🔴 Mora (Cerr)", format="%d"),
        "MORA_Total": st.column_config.NumberColumn("🔴 Mora (Total)", format="%d"),
        "HOY_Asig": st.column_config.NumberColumn("🔵 Hoy (Asig)", format="%d"),
        "HOY_Cerr": st.column_config.NumberColumn("🔵 Hoy (Cerr)", format="%d"),
        "HOY_Total": st.column_config.NumberColumn("🔵 Hoy (Total)", format="%d"),
        "GRAN_TOTAL": st.column_config.NumberColumn("📦 GRAN TOTAL", format="%d")
    }

    # Ordenar las columnas para mostrar
    columnas_orden = ['Tipo', 'MORA_Asig', 'MORA_Cerr', 'MORA_Total', 'HOY_Asig', 'HOY_Cerr', 'HOY_Total', 'GRAN_TOTAL']
    
    # Colorear la fila de Totales
    def highlight_total(row):
        if row['Tipo'] == 'TOTAL GENERAL':
            return ['background-color: #2D3748; color: white; font-weight: bold'] * len(row)
        return [''] * len(row)

    st.dataframe(resumen[columnas_orden].style.apply(highlight_total, axis=1), 
                 use_container_width=True, hide_index=True, column_config=col_config)
                 
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Cerrar Resumen", use_container_width=True): st.rerun()
