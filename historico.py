import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
from datetime import datetime, timedelta
import io

def main_historico(df_hist_memoria):
    st.title("📚 Centro de Inteligencia Histórica")
    st.caption("Auditoría de operaciones pasadas mediante carga de archivos independientes.")

    # ==============================================================================
    # 0. CARGADOR EN CRUDO INDEPENDIENTE
    # ==============================================================================
    st.markdown("### 📥 Cargar Base de Datos Histórica")
    archivo_historico = st.file_uploader(
        "Sube aquí el archivo Excel o CSV crudo (ignora los datos del monitor en vivo)", 
        type=['xlsx', 'csv']
    )

    df_trabajo = None

    if archivo_historico is not None:
        with st.spinner("Procesando archivo histórico crudo..."):
            try:
                if archivo_historico.name.lower().endswith('.csv'):
                    df_trabajo = pd.read_csv(archivo_historico, low_memory=False)
                else:
                    df_trabajo = pd.read_excel(archivo_historico)
                
                # Normalizar columnas
                df_trabajo.columns = df_trabajo.columns.str.upper().str.strip()
                st.success(f"✅ Archivo cargado correctamente: {len(df_trabajo)} registros detectados.")
            except Exception as e:
                st.error(f"❌ Error al leer el archivo: {e}")
                return
    elif df_hist_memoria is not None and not df_hist_memoria.empty:
        st.info("💡 Usando el historial temporal del monitor en vivo. Sube un archivo arriba para analizar otros datos.")
        df_trabajo = df_hist_memoria.copy()
    else:
        st.warning("⚠️ Esperando archivo. Por favor, sube un archivo histórico para comenzar el análisis.")
        return

    # ==============================================================================
    # PRE-PROCESAMIENTO RÁPIDO PARA ARCHIVOS CRUDOS E INYECCIÓN DE PAUTAS
    # ==============================================================================
    # Limpieza de número de cuenta (quitar .0 para evitar errores visuales)
    if 'CLIENTE' in df_trabajo.columns:
        df_trabajo['CLIENTE'] = df_trabajo['CLIENTE'].astype(str).str.replace(r'\.0$', '', regex=True)

    # Si el archivo crudo no trae los tiempos calculados, los calculamos al vuelo
    if 'HORA_INI' in df_trabajo.columns and 'HORA_LIQ' in df_trabajo.columns and 'MINUTOS_CALC' not in df_trabajo.columns:
        df_trabajo['HORA_INI'] = pd.to_datetime(df_trabajo['HORA_INI'], errors='coerce')
        df_trabajo['HORA_LIQ'] = pd.to_datetime(df_trabajo['HORA_LIQ'], errors='coerce')
        df_trabajo['MINUTOS_CALC'] = (df_trabajo['HORA_LIQ'] - df_trabajo['HORA_INI']).dt.total_seconds() / 60

    # Lógica de Auditoría de Facturación vs Servicio (Añadido)
    def clasificar_auditoria(row):
        actividad = str(row.get('ACTIVIDAD', '')).upper()
        estado = str(row.get('ESTADO', '')).upper()
        comentario = str(row.get('COMENTARIO', '')).upper()
        
        ins_fallida = any(x in actividad for x in ['INS', 'NUEVA']) and any(x in estado for x in ['CANCELADO', 'DEVOLUCION', 'INACTIVO'])
        alerta_cobro = any(word in comentario for word in ['COBRO', 'FACTURA', 'SISTEMA', 'NO TIENE SERVICIO', 'RECLAMO', 'DICE QUE NO'])
        
        if ins_fallida and alerta_cobro: return "🚨 CRÍTICO: Cobro indebido en INS fallida"
        if ins_fallida: return "⚠️ ANOMALÍA: INS en estado negativo"
        if alerta_cobro: return "⚠️ ALERTA: Queja de Facturación"
        return "✅ OK"

    df_trabajo['RESULTADO_AUDITORIA'] = df_trabajo.apply(clasificar_auditoria, axis=1)

    # ==============================================================================
    # 1. BUSCADOR GLOBAL ULTRA RÁPIDO
    # ==============================================================================
    st.divider()
    with st.expander("🔍 Buscador Avanzado y Filtros", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            busqueda = st.text_input("Buscar cliente, orden, número o técnico:", placeholder="Ej: 92408321 o Darwin")
        with c2:
            rango_fechas = st.date_input("Filtrar por fechas:", value=[])
        with c3:
            if 'ESTADO' in df_trabajo.columns:
                estados_disponibles = df_trabajo['ESTADO'].dropna().unique().tolist()
                estado_h = st.multiselect("Estado:", estados_disponibles, default=estados_disponibles)

    # Motor de filtrado
    df_h_filtrado = df_trabajo.copy()
    
    if busqueda:
        mask_busqueda = df_h_filtrado.astype(str).apply(lambda x: x.str.contains(busqueda, case=False, na=False)).any(axis=1)
        df_h_filtrado = df_h_filtrado[mask_busqueda]
        
    if len(rango_fechas) == 2 and 'HORA_LIQ' in df_h_filtrado.columns:
        df_h_filtrado['HORA_LIQ'] = pd.to_datetime(df_h_filtrado['HORA_LIQ'], errors='coerce')
        mask_fechas = (df_h_filtrado['HORA_LIQ'].dt.date >= rango_fechas[0]) & (df_h_filtrado['HORA_LIQ'].dt.date <= rango_fechas[1])
        df_h_filtrado = df_h_filtrado[mask_fechas]
        
    if 'ESTADO' in df_h_filtrado.columns and 'estado_h' in locals() and estado_h:
        df_h_filtrado = df_h_filtrado[df_h_filtrado['ESTADO'].isin(estado_h)]

    # ==============================================================================
    # 2. KPIS DE AUDITORÍA
    # ==============================================================================
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Órdenes en Pantalla", len(df_h_filtrado))
    
    if 'ACTIVIDAD' in df_h_filtrado.columns and 'CLIENTE' in df_h_filtrado.columns:
        mask_sop = df_h_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', case=False, na=False)
        reincidencias = df_h_filtrado[mask_sop]['CLIENTE'].duplicated().sum()
        m2.metric("Reincidencias (SOP)", reincidencias, help="Clientes que han solicitado soporte más de una vez en esta base.")
    else:
        m2.metric("Reincidencias", "N/D")

    if 'MINUTOS_CALC' in df_h_filtrado.columns:
        promedio = df_h_filtrado[df_h_filtrado['MINUTOS_CALC'] > 0]['MINUTOS_CALC'].mean()
        m3.metric("Tiempo Promedio Liquidación", f"{int(promedio)} min" if pd.notnull(promedio) else "0 min")
    else:
        m3.metric("Tiempo Promedio", "N/D")
        
    def detectar_alerta(row):
        act = str(row.get('ACTIVIDAD', '')).upper()
        com = str(row.get('COMENTARIO', '')).upper()
        if any(e in act for e in ['INACTIVO', 'CORTEMORA', 'NOINSTALADO']): return True
        if any(j in com for j in ['NO SE PUDO', 'CANCELADA', 'NO PERMITE', 'CLIENTE NO QUISO']): return True
        return False

    alertas_adm = df_h_filtrado.apply(detectar_alerta, axis=1).sum()
    m4.metric("Alertas / Anuladas", alertas_adm, help="Órdenes no instaladas o con problemas administrativos.")
    
    casos_criticos = len(df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'].str.contains('CRÍTICO|ANOMALÍA|ALERTA')])
    m5.metric("Anomalías Facturación", casos_criticos, delta_color="inverse")

    # ==============================================================================
    # 3. TABLAS Y GRÁFICOS
    # ==============================================================================
    t_tabla, t_graficos, t_auditoria = st.tabs(["📄 Base de Datos Exploratoria", "📊 Analítica de Rendimiento", "🚨 Auditoría de Facturación"])

    with t_tabla:
        st.dataframe(df_h_filtrado, use_container_width=True, hide_index=True)

    with t_graficos:
        plt.style.use('dark_background')
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.markdown("##### 🏆 Ranking de Volumen por Técnico")
            if 'TECNICO' in df_h_filtrado.columns:
                fig_tec, ax_tec = plt.subplots(figsize=(6, 4))
                top_tecs = df_h_filtrado['TECNICO'].value_counts().head(10)
                if not top_tecs.empty:
                    top_tecs.sort_values().plot(kind='barh', color='#2ea043', ax=ax_tec)
                    ax_tec.set_xlabel("Órdenes Liquidadas")
                    ax_tec.spines['top'].set_visible(False)
                    ax_tec.spines['right'].set_visible(False)
                    st.pyplot(fig_tec)
                else:
                    st.info("Sin datos de técnicos para graficar.")
            else:
                st.warning("La columna 'TECNICO' no existe en este archivo.")

        with col_g2:
            st.markdown("##### 📈 Distribución Operativa (Tipos de Orden)")
            if 'ACTIVIDAD' in df_h_filtrado.columns:
                def clasificar_actividad(act):
                    act = str(act).upper()
                    if 'SOP' in act or 'FALLA' in act: return 'SOPORTE'
                    if 'INS' in act or 'NUEVA' in act: return 'INSTALACIÓN'
                    if 'PLEX' in act: return 'PLEX'
                    return 'OTROS'
                
                df_pie = df_h_filtrado.copy()
                df_pie['CATEGORIA'] = df_pie['ACTIVIDAD'].apply(clasificar_actividad)
                
                fig_pie = px.pie(df_pie, names='CATEGORIA', hole=0.4, 
                                 color_discrete_sequence=['#1f6feb', '#238636', '#f2cc60', '#8b949e'])
                fig_pie.update_layout(template="plotly_dark", height=350, margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.warning("La columna 'ACTIVIDAD' no existe en este archivo.")

    with t_auditoria:
        st.subheader("🚩 Rastreo de Cobros Indebidos e Instalaciones Fallidas")
        st.write("Listado de órdenes filtradas por estados inactivos/devueltos o con quejas administrativas.")
        
        df_criticos = df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'].str.contains('CRÍTICO|ANOMALÍA|ALERTA')].copy()
        
        if not df_criticos.empty:
            cols_deseadas = ['NUM', 'CLIENTE', 'HORA_LIQ', 'ACTIVIDAD', 'ESTADO', 'RESULTADO_AUDITORIA', 'COMENTARIO']
            cols_ver = [c for c in cols_deseadas if c in df_criticos.columns]
            
            st.dataframe(
                df_criticos[cols_ver].style.set_properties(
                    **{'background-color': '#4c1111', 'color': '#ff9999'}, subset=['RESULTADO_AUDITORIA']
                ),
                use_container_width=True, hide_index=True
            )
        else:
            st.success("✅ No se detectaron anomalías de facturación con los filtros actuales.")

    # ==============================================================================
    # 4. EXPORTACIÓN PROFESIONAL
    # ==============================================================================
    st.divider()
    c_exp1, c_exp2 = st.columns(2)
    
    with c_exp1:
        if st.button("💾 Exportar Toda la Base Filtrada (.xlsx)", type="primary", use_container_width=True):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_h_filtrado.to_excel(writer, index=False, sheet_name='Historial_Crudo')
            
            st.download_button(
                label="⬇️ Descargar Base General",
                data=output.getvalue(),
                file_name=f"Analisis_Crudo_Maxcom_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
    with c_exp2:
        df_criticos_export = df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'].str.contains('CRÍTICO|ANOMALÍA|ALERTA')]
        if not df_criticos_export.empty:
            if st.button("🚨 Exportar Solo Reporte de Facturación (.xlsx)", type="primary", use_container_width=True):
                out_crit = io.BytesIO()
                with pd.ExcelWriter(out_crit, engine='openpyxl') as writer:
                    df_criticos_export.to_excel(writer, index=False, sheet_name='Reclamos_Cobro')
                
                st.download_button(
                    label="⬇️ Descargar Reporte Adm.",
                    data=out_crit.getvalue(),
                    file_name=f"Auditoria_Cobros_Maxcom_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
