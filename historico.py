import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
from datetime import datetime
import io

def main_historico(df_hist_memoria):
    st.title("📚 Centro de Inteligencia Histórica")
    st.caption("Auditoría estricta de facturación, reincidencias y rendimiento técnico.")

    # ==============================================================================
    # 0. CARGADOR EN CRUDO
    # ==============================================================================
    st.markdown("### 📥 Cargar Base de Datos Histórica")
    archivo_historico = st.file_uploader(
        "Sube aquí el archivo Excel o CSV crudo (ignora los datos del monitor en vivo)", 
        type=['xlsx', 'csv']
    )

    df_trabajo = None

    if archivo_historico is not None:
        with st.spinner("Procesando archivo..."):
            try:
                if archivo_historico.name.lower().endswith('.csv'):
                    df_trabajo = pd.read_csv(archivo_historico, low_memory=False)
                else:
                    df_trabajo = pd.read_excel(archivo_historico)
                
                df_trabajo.columns = df_trabajo.columns.str.upper().str.strip()
                st.success(f"✅ Archivo cargado: {len(df_trabajo)} registros.")
            except Exception as e:
                st.error(f"❌ Error al leer el archivo: {e}")
                return
    elif df_hist_memoria is not None and not df_hist_memoria.empty:
        st.info("💡 Usando el historial del monitor en vivo.")
        df_trabajo = df_hist_memoria.copy()
    else:
        st.warning("⚠️ Esperando archivo...")
        return

    # ==============================================================================
    # PRE-PROCESAMIENTO Y MOTOR DE AUDITORÍA ULTRA-PRECISO
    # ==============================================================================
    if 'CLIENTE' in df_trabajo.columns:
        df_trabajo['CLIENTE'] = df_trabajo['CLIENTE'].astype(str).str.replace(r'\.0$', '', regex=True)

    if 'HORA_INI' in df_trabajo.columns and 'HORA_LIQ' in df_trabajo.columns and 'MINUTOS_CALC' not in df_trabajo.columns:
        df_trabajo['HORA_INI'] = pd.to_datetime(df_trabajo['HORA_INI'], errors='coerce')
        df_trabajo['HORA_LIQ'] = pd.to_datetime(df_trabajo['HORA_LIQ'], errors='coerce')
        df_trabajo['MINUTOS_CALC'] = (df_trabajo['HORA_LIQ'] - df_trabajo['HORA_INI']).dt.total_seconds() / 60

    # LÓGICA ESTRICTA (FRANCOTIRADOR) PARA ÓRDENES FANTASMA
    def clasificar_auditoria_estricta(row):
        actividad = str(row.get('ACTIVIDAD', '')).upper()
        estado = str(row.get('ESTADO', '')).upper()
        comentario = str(row.get('COMENTARIO', '')).upper()
        
        # 1. Debe ser una instalación
        es_ins = any(x in actividad for x in ['INS', 'NUEVA', 'ADICIONAL', 'TRASLADO'])
        
        # 2. Debe haber terminado en estado negativo
        termino_mal = any(x in estado for x in ['CANCELAD', 'DEVOLUCION', 'INACTIVO', 'NOINSTALADO'])
        
        # 3. Palabras EXCLUSIVAS de facturación o cobros indebidos (sin basura como "sistema")
        palabras_criticas = ['COBRO', 'FACTURA', 'COBRANDO', 'PAGANDO', 'MENSUALIDAD', 'SIN TENER SERVICIO', 'APARECE ACTIVO']
        queja_dinero = any(w in comentario for w in palabras_criticas)
        
        if es_ins and termino_mal and queja_dinero: 
            return "🚨 FANTASMA: Cobro en INS no realizada"
        elif es_ins and termino_mal: 
            return "⚠️ ANOMALÍA: INS fallida (Revisar cobro)"
        elif queja_dinero: 
            return "⚠️ ALERTA: Queja de cobro general"
        
        return "✅ NORMAL"

    df_trabajo['RESULTADO_AUDITORIA'] = df_trabajo.apply(clasificar_auditoria_estricta, axis=1)

    # ==============================================================================
    # 1. BUSCADOR GLOBAL
    # ==============================================================================
    st.divider()
    with st.expander("🔍 Buscador Avanzado y Filtros", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            busqueda = st.text_input("Buscar cliente, orden, número o técnico:", placeholder="Ej: 92408321")
        with c2:
            rango_fechas = st.date_input("Filtrar por fechas:", value=[])
        with c3:
            if 'ESTADO' in df_trabajo.columns:
                estados_disponibles = df_trabajo['ESTADO'].dropna().unique().tolist()
                estado_h = st.multiselect("Estado:", estados_disponibles, default=estados_disponibles)

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
    # 2. KPIS
    # ==============================================================================
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Órdenes en Pantalla", len(df_h_filtrado))
    
    if 'ACTIVIDAD' in df_h_filtrado.columns and 'CLIENTE' in df_h_filtrado.columns:
        mask_sop = df_h_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', case=False, na=False)
        m2.metric("Posibles Garantías (SOP)", df_h_filtrado[mask_sop]['CLIENTE'].duplicated().sum())
    else:
        m2.metric("Garantías", "N/D")
        
    # Solo contamos los casos FANTASMA exactos para no inflar los números
    casos_fantasma = len(df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'] == '🚨 FANTASMA: Cobro en INS no realizada'])
    m3.metric("🚨 Órdenes Fantasma (Cobros indebidos)", casos_fantasma, delta_color="inverse")
    
    anomalias_ins = len(df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'] == '⚠️ ANOMALÍA: INS fallida (Revisar cobro)'])
    m4.metric("Instalaciones Canceladas/Devueltas", anomalias_ins)

    # ==============================================================================
    # 3. TABLAS Y GRÁFICOS
    # ==============================================================================
    t_tabla, t_graficos, t_auditoria = st.tabs(["📄 Base General", "📊 Rendimiento Técnico", "🚨 Auditoría de Facturación"])

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
                    st.info("Sin datos para graficar.")

        with col_g2:
            st.markdown("##### 📈 Composición Operativa")
            if 'ACTIVIDAD' in df_h_filtrado.columns:
                def clasificar_act(act):
                    act = str(act).upper()
                    if 'SOP' in act or 'FALLA' in act: return 'SOPORTE'
                    if 'INS' in act or 'NUEVA' in act: return 'INSTALACIÓN'
                    if 'PLEX' in act: return 'PLEX'
                    return 'OTROS'
                
                df_pie = df_h_filtrado.copy()
                df_pie['CATEGORIA'] = df_pie['ACTIVIDAD'].apply(clasificar_act)
                fig_pie = px.pie(df_pie, names='CATEGORIA', hole=0.4, color_discrete_sequence=['#1f6feb', '#238636', '#f2cc60', '#8b949e'])
                fig_pie.update_layout(template="plotly_dark", height=350, margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig_pie, use_container_width=True)

    # --- PESTAÑA DE AUDITORÍA SÚPER PRECISA ---
    with t_auditoria:
        st.subheader("🚩 Rastreo Quirúrgico de Órdenes Fantasma")
        
        # Filtro controlado por el usuario para mayor precisión
        tipo_auditoria = st.radio(
            "Seleccione qué nivel de riesgo desea visualizar:",
            ["🚨 Mostrar SOLO Órdenes Fantasma (Cobros explícitos en INS fallidas)", 
             "⚠️ Mostrar TODAS las Instalaciones Devueltas/Canceladas (Riesgo potencial)"]
        )
        
        if "SOLO Órdenes Fantasma" in tipo_auditoria:
            df_mostrar_auditoria = df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'] == '🚨 FANTASMA: Cobro en INS no realizada']
        else:
            df_mostrar_auditoria = df_h_filtrado[df_h_filtrado['RESULTADO_AUDITORIA'].isin([
                '🚨 FANTASMA: Cobro en INS no realizada', 
                '⚠️ ANOMALÍA: INS fallida (Revisar cobro)'
            ])]
        
        if not df_mostrar_auditoria.empty:
            cols_ver = [c for c in ['NUM', 'CLIENTE', 'TECNICO', 'HORA_LIQ', 'ACTIVIDAD', 'ESTADO', 'RESULTADO_AUDITORIA', 'COMENTARIO'] if c in df_mostrar_auditoria.columns]
            
            st.dataframe(
                df_mostrar_auditoria[cols_ver].style.set_properties(
                    **{'background-color': '#4c1111', 'color': '#ff9999'}, subset=['RESULTADO_AUDITORIA']
                ),
                use_container_width=True, hide_index=True
            )
            
            # Exportación dedicada solo para lo que estás viendo en la tabla
            out_crit = io.BytesIO()
            with pd.ExcelWriter(out_crit, engine='openpyxl') as writer:
                df_mostrar_auditoria[cols_ver].to_excel(writer, index=False, sheet_name='Auditoria_Facturacion')
            st.download_button("🚨 Descargar Esta Tabla (Excel)", out_crit.getvalue(), f"Auditoria_Facturacion_{datetime.now().strftime('%Y%m%d')}.xlsx", type="primary")
        else:
            st.success("✅ La base de datos está limpia. No se encontraron registros bajo estos criterios.")
