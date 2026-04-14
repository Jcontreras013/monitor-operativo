import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import timedelta
from tools import (
    logica_generar_pdf,
    generar_tablas_gerenciales,
    generar_pdf_trimestral_detallado,
    generar_pdf_cierre_diario,
    generar_pdf_semanal,
    generar_pdf_mensual,
    generar_pdf_primera_orden
)

def renderizar_centro_reportes(df_base, df_monitor_filtrado, hoy_date_valor, PATRON_ASIGNADAS_VIVA_STR):
    st.title("📊 Centro Único de Reportes Operativos")
    st.caption("Central de exportación gerencial de métricas y rendimiento.")
    
    tab_dinamico, tab_diario, tab_semanal, tab_mensual, tab_gerencial, tab_biometrico = st.tabs([
        "⚡ Reporte Dinámico", "📦 Cierre Diario", "🗓️ Analítico Semanal", "🏢 Macro Mensual", "💼 Gerencial (Trimestral)", "⏱️ Biométrico"
    ])

    with tab_biometrico:
        try:
            import biometrico
            biometrico.vista_biometrico()
        except Exception as e:
            st.error(f"Error al cargar la vista del biométrico: {e}")

    with tab_dinamico:
        st.subheader("📄 Reporte Dinámico en Vivo")
        col_f1, col_f2 = st.columns(2)
        m_viva_rep = df_base['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        total_off_rep = int((df_base['ES_OFFLINE'] == True & m_viva_rep).sum())
        
        with col_f1: check_criticos_rep = st.toggle(f"Filtrar solo Críticas ({total_off_rep})", key="tgg_rep")
        with col_f2: tec_filtro_rep = st.selectbox("Filtrar por Técnico:", ["Todos"] + sorted(df_base['TECNICO'].dropna().unique().tolist()), key="sel_tec_rep")
            
        df_dinamico_filtrado = df_base.copy()
        if check_criticos_rep: df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['ES_OFFLINE'] | df_dinamico_filtrado['ALERTA_TIEMPO']]
        if tec_filtro_rep != "Todos": df_dinamico_filtrado = df_dinamico_filtrado[df_dinamico_filtrado['TECNICO'] == tec_filtro_rep]
            
        if st.button("📄 GENERAR REPORTE DINÁMICO (PDF)", use_container_width=True, type="primary"):
            pdf_bytes_rendimiento = logica_generar_pdf(df_dinamico_filtrado)
            st.download_button("📥 Descargar PDF Dinámico", data=pdf_bytes_rendimiento, file_name=f"Reporte_Dinamico_{hoy_date_valor}.pdf", mime="application/pdf")

    with tab_gerencial:
        st.subheader("📊 Reporte Gerencial Unificado")
        st.caption("Sube el archivo en crudo. El sistema cruzará la productividad, tiempos y jornadas en una sola tabla maestra.")
        
        archivo_gerencial = st.file_uploader("📂 Subir Reporte de Actividades (Excel/CSV)", type=['xlsx', 'csv'], key="uploader_gerencial")
        
        if archivo_gerencial:
            with st.spinner("⏳ Analizando datos, cruzando tablas y calculando jornadas..."):
                try:
                    if archivo_gerencial.name.endswith('.csv'): df_raw = pd.read_csv(archivo_gerencial)
                    else: df_raw = pd.read_excel(archivo_gerencial)
                    
                    # Importar procesar_dataframe_base localmente para evitar dependencias circulares si es necesario
                    from tools import procesar_dataframe_base
                    df_limpio = procesar_dataframe_base(df_raw)
                    tabla_prod, tabla_efi, res_jornada = generar_tablas_gerenciales(df_limpio)
                    
                    df_merge_1 = pd.merge(tabla_prod, tabla_efi, on=['TECNICO', 'ACTIVIDAD'], how='left')
                    df_maestra = pd.merge(df_merge_1, res_jornada, on='TECNICO', how='left')
                    
                    df_maestra = df_maestra.rename(columns={
                        'TECNICO': 'Técnico',
                        'Dias_Laborados': 'Días Trabajados',
                        'Promedio_Horas_Dia': 'Hrs / Día',
                        'ACTIVIDAD': 'Actividad',
                        'Cantidad': 'Volumen',
                        'Participacion_%': '% del Total',
                        'Promedio_Minutos': 'Min. Promedio'
                    })
                    
                    columnas_ordenadas = ['Técnico', 'Días Trabajados', 'Hrs / Día', 'Actividad', 'Volumen', '% del Total', 'Min. Promedio']
                    df_maestra = df_maestra[columnas_ordenadas]
                    
                    st.success("✅ Datos procesados y unificados correctamente.")
                    
                    ordenes_con_error = df_maestra['Min. Promedio'].isna().sum()
                    if ordenes_con_error > 0:
                        st.warning(f"⚠️ Se detectaron {ordenes_con_error} órdenes con errores de tiempo (negativos/cero). Se incluyeron en el volumen de producción pero se ignoraron para el promedio de minutos.")

                    st.dataframe(
                        df_maestra,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Técnico": st.column_config.TextColumn("👨‍🔧 Técnico", width="medium"),
                            "Días Trabajados": st.column_config.NumberColumn("📅 Días", format="%d"),
                            "Hrs / Día": st.column_config.NumberColumn("⏱️ Hrs/Día", format="%.1f h"),
                            "Actividad": st.column_config.TextColumn("🛠️ Actividad", width="medium"),
                            "Volumen": st.column_config.NumberColumn("📦 Volumen", format="%d ord."),
                            "% del Total": st.column_config.ProgressColumn("📊 Participación", format="%.1f%%", min_value=0, max_value=100),
                            "Min. Promedio": st.column_config.NumberColumn("⏳ Min. Prom.", format="%.0f min")
                        }
                    )
                    
                    st.divider()
                    
                    if st.button("🚀 GENERAR PDF GERENCIAL COMPLETO", use_container_width=True, type="primary"):
                        with st.spinner("Dibujando secciones por técnico..."):
                            pdf_bytes = generar_pdf_trimestral_detallado(tabla_prod, tabla_efi, res_jornada)
                            st.download_button(
                                label="📥 Descargar Reporte PDF",
                                data=pdf_bytes,
                                file_name=f"Reporte_Gerencial_{datetime.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                                type="primary",
                                use_container_width=True
                            )
                except Exception as e:
                    st.error(f"❌ Ocurrió un error procesando el reporte: {e}")
    
    with tab_diario:
        st.subheader("📦 Archivo de Cierre de Jornada")
        fecha_cal_sel = st.date_input("Seleccione Fecha a Archivar:", value=hoy_date_valor)
        
        mask_vivas_espejo = df_monitor_filtrado['ESTADO'].astype(str).str.contains(PATRON_ASIGNADAS_VIVA_STR, na=False, case=False)
        mask_cerradas_espejo = (df_monitor_filtrado['HORA_LIQ'].dt.date == fecha_cal_sel) & (df_monitor_filtrado['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))
        
        df_vivas_espejo = df_monitor_filtrado[mask_vivas_espejo].copy()
        mask_tec_valido_esp = df_vivas_espejo['TECNICO'].notna() & (df_vivas_espejo['TECNICO'].astype(str).str.strip() != '') & (~df_vivas_espejo['TECNICO'].astype(str).str.upper().isin(['NONE', 'NAN', 'N/D', 'NULL']))
        df_asignadas_espejo = df_vivas_espejo[mask_tec_valido_esp].copy()
        df_cerradas_espejo = df_monitor_filtrado[mask_cerradas_espejo].copy()

        st.metric(f"Total Órdenes Cerradas ({fecha_cal_sel})", len(df_cerradas_espejo))
        st.markdown("### 📊 Indicadores de Avance Operativo")
        
        df_plex_asignadas_rep = df_asignadas_espejo[df_asignadas_espejo['SEGMENTO'] == 'PLEX']
        df_plex_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['SEGMENTO'] == 'PLEX']
        
        df_resi_asignadas_rep = df_asignadas_espejo[df_asignadas_espejo['SEGMENTO'] == 'RESIDENCIAL']
        df_resi_cerr_rep = df_cerradas_espejo[df_cerradas_espejo['SEGMENTO'] == 'RESIDENCIAL']

        total_p_rep = len(df_plex_asignadas_rep) + len(df_plex_cerr_rep)
        avance_plex_rep = (len(df_plex_cerr_rep) / total_p_rep * 100) if total_p_rep > 0 else 0
        
        total_r_rep = len(df_resi_asignadas_rep) + len(df_resi_cerr_rep)
        avance_resi_rep = (len(df_resi_cerr_rep) / total_r_rep * 100) if total_r_rep > 0 else 0
        
        total_v_rep = len(df_asignadas_espejo) + len(df_cerradas_espejo)
        avance_global_rep = (len(df_cerradas_espejo) / total_v_rep * 100) if total_v_rep > 0 else 0

        def crear_velocimetro_rep(valor, titulo):
            import plotly.graph_objects as go
            color_v = "#EF4444" if valor < 50 else ("#F59E0B" if valor < 80 else "#10B981") 
            fig = go.Figure(go.Pie(values=[valor, max(0, 100 - valor)], labels=['Completado', 'Pendiente'], hole=0.8, marker=dict(colors=[color_v, '#2D2F39']), textinfo='none', hoverinfo='none', direction='clockwise', sort=False))
            fig.update_layout(showlegend=False, height=160, margin=dict(l=5, r=5, t=30, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", title={'text': titulo, 'y': 1.0, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'color': '#94A3B8', 'size': 14}}, annotations=[dict(text=f"{valor:.0f}%", x=0.5, y=0.5, font_size=24, font_color=color_v, showarrow=False, font_weight="bold")])
            return fig

        col_gr1, col_gr2, col_gr3 = st.columns(3)
        with col_gr1: st.plotly_chart(crear_velocimetro_rep(avance_resi_rep, "🏠 Residencial"), use_container_width=True)
        with col_gr2: st.plotly_chart(crear_velocimetro_rep(avance_plex_rep, "🏢 PLEX"), use_container_width=True)
        with col_gr3: st.plotly_chart(crear_velocimetro_rep(avance_global_rep, "🌍 Global"), use_container_width=True)
        
        st.divider()

        if not df_cerradas_espejo.empty:
            st.markdown("### 📊 Desglose de Producción por Categoría")
            import re
            cs_col, ci_col, cp_col, co_col = st.columns(4)
            with cs_col:
                st.write("**SOP**")
                df_sop = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                st.dataframe(df_sop, hide_index=True, use_container_width=True)
                st.write(f"**Total SOP: {df_sop['Cant'].sum()}**")
            with ci_col:
                st.write("**Instalaciones**")
                txt_ins_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                mask_ins_general = txt_ins_c.str.contains('INS|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                df_ins_cierre = df_cerradas_espejo[mask_ins_general].copy()
                if not df_ins_cierre.empty:
                    def clasificar_ins_cierre(row):
                        txt = (str(row.get('ACTIVIDAD','')) + " " + str(row.get('COMENTARIO',''))).upper()
                        if re.search('ADIC', txt): return 'Adición'
                        if re.search('CAMBIO|MIGRACI', txt): return 'Cambio / Migración'
                        if re.search('RECUP', txt): return 'Recuperado'
                        return 'Nueva'
                    df_ins_cierre['SUBTIPO'] = df_ins_cierre.apply(clasificar_ins_cierre, axis=1)
                    df_ins_grouped = df_ins_cierre['SUBTIPO'].value_counts().reset_index()
                    df_ins_grouped.columns = ['Instalaciones', 'Cant']
                    st.dataframe(df_ins_grouped, hide_index=True, use_container_width=True)
                    st.write(f"**Total INS: {df_ins_grouped['Cant'].sum()}**")
                else: st.write("Sin datos")
            with cp_col:
                st.write("**Plex**")
                df_plex = df_cerradas_espejo[df_cerradas_espejo['ACTIVIDAD'].astype(str).str.contains('PLEX|PEXTERNO|SPLITTEROPT', na=False, case=False)]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                st.dataframe(df_plex, hide_index=True, use_container_width=True)
                st.write(f"**Total PLEX: {df_plex['Cant'].sum()}**")
            with co_col:
                st.write("**Otros**")
                txt_otr_c = df_cerradas_espejo['ACTIVIDAD'].astype(str).str.upper() + " " + df_cerradas_espejo['COMENTARIO'].astype(str).str.upper()
                mask_otros_c = ~txt_otr_c.str.contains('SOP|MANT|INS|PLEX|PEXTERNO|SPLITTEROPT|NUEVA|ADIC|CAMBIO|MIGRACI|RECUP', na=False)
                df_otros = df_cerradas_espejo[mask_otros_c]['ACTIVIDAD'].value_counts().reset_index(name='Cant')
                st.dataframe(df_otros, hide_index=True, use_container_width=True)
                st.write(f"**Total Otros: {df_otros['Cant'].sum()}**")

        st.divider()
        
        st.markdown("### 📈 Resumen Consolidado: Carga Asignada vs Cierres")
        
        p_rep = df_asignadas_espejo.groupby('ACTIVIDAD').size().reset_index(name='ASIGNADAS')
        c_rep = df_cerradas_espejo.groupby('ACTIVIDAD').size().reset_index(name='CERRADAS')
        
        resumen_global_rep = pd.merge(p_rep, c_rep, on='ACTIVIDAD', how='outer').fillna(0)
        
        if not resumen_global_rep.empty:
            resumen_global_rep['ASIGNADAS'] = resumen_global_rep['ASIGNADAS'].astype(int)
            resumen_global_rep['CERRADAS'] = resumen_global_rep['CERRADAS'].astype(int)
            
            resumen_global_rep.rename(columns={'ACTIVIDAD': 'TIPO'}, inplace=True)
            resumen_global_rep = resumen_global_rep[['TIPO', 'ASIGNADAS', 'CERRADAS']].sort_values(by='TIPO').reset_index(drop=True)
            
            tot_p = resumen_global_rep['ASIGNADAS'].sum()
            tot_c = resumen_global_rep['CERRADAS'].sum()
            fila_tot = pd.DataFrame([{'TIPO': 'TOTAL GENERAL', 'ASIGNADAS': tot_p, 'CERRADAS': tot_c}])
            resumen_global_rep = pd.concat([resumen_global_rep, fila_tot], ignore_index=True)
            
            st.dataframe(
                resumen_global_rep, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "TIPO": st.column_config.TextColumn("TIPO"),
                    "ASIGNADAS": st.column_config.NumberColumn("ASIGNADAS", format="%d"),
                    "CERRADAS": st.column_config.NumberColumn("CERRADAS", format="%d")
                }
            )
        else:
            st.info("No hay datos de operaciones consolidadas para esta fecha.")

        st.markdown("### ⏱️ Tiempos de Atención Promedio")
        if not df_cerradas_espejo.empty:
            df_pivot_diario = df_cerradas_espejo.groupby(['TECNICO', 'ACTIVIDAD']).agg(
                Órdenes=('NUM', 'count'),
                Prom_Duracion_Min=('MINUTOS_CALC', 'mean')
            ).round(1)
            st.dataframe(df_pivot_diario, use_container_width=True)

        st.markdown("### 🌅 Primera Orden del Día por Técnico")
        
        df_universo_diario = pd.concat([df_asignadas_espejo, df_cerradas_espejo]).drop_duplicates(subset=['NUM'])
        
        if 'HORA_INI' in df_universo_diario.columns:
            df_universo_diario['HORA_INI_DT'] = pd.to_datetime(df_universo_diario['HORA_INI'], errors='coerce')
            df_universo_diario = df_universo_diario.dropna(subset=['HORA_INI_DT'])
            
            mask_fecha_ini = df_universo_diario['HORA_INI_DT'].dt.date == pd.to_datetime(fecha_cal_sel).date()
            df_primera = df_universo_diario[mask_fecha_ini].sort_values(by='HORA_INI_DT').drop_duplicates(subset=['TECNICO'], keep='first')
            
            if not df_primera.empty:
                df_primera_mostrar = df_primera[['TECNICO', 'HORA_INI_DT', 'COLONIA', 'NUM']].copy()
                df_primera_mostrar = df_primera_mostrar.sort_values(by='HORA_INI_DT')
                df_primera_mostrar['HORA_INI'] = df_primera_mostrar['HORA_INI_DT'].dt.strftime('%H:%M:%S')
                df_primera_mostrar = df_primera_mostrar.drop(columns=['HORA_INI_DT'])
                df_primera_mostrar = df_primera_mostrar[['TECNICO', 'HORA_INI', 'COLONIA', 'NUM']]
                
                st.dataframe(
                    df_primera_mostrar, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "TECNICO": st.column_config.TextColumn("Técnico"),
                        "HORA_INI": st.column_config.TextColumn("Hora de Inicio"),
                        "COLONIA": st.column_config.TextColumn("Colonia"),
                        "NUM": st.column_config.TextColumn("N° Orden")
                    }
                )

                st.markdown("<br>", unsafe_allow_html=True)
                col_btn1, col_btn2 = st.columns([1, 2])
                with col_btn1:
                    if st.button("📄 GENERAR PDF PRIMERA ORDEN", use_container_width=True):
                        try:
                            pdf_primera = generar_pdf_primera_orden(df_base, fecha_cal_sel)
                            if pdf_primera:
                                st.download_button("📥 Descargar PDF (Inicio Jornada)", data=pdf_primera, file_name=f"Primeras_Ordenes_{fecha_cal_sel}.pdf", mime="application/pdf", type="primary", use_container_width=True)
                        except Exception as e:
                            st.error(f"Error generando PDF: {e}")
            else:
                st.info("No hay registros de inicio de órdenes para esta fecha.")
        else:
             st.info("No hay registros de inicio de órdenes para esta fecha.")

        st.markdown("### 📥 Exportación")
        if st.button("🚀 GENERAR PDF DE CIERRE DIARIO", use_container_width=True, type="primary"):
            pdf_bytes_archivo_diario = generar_pdf_cierre_diario(df_base, fecha_cal_sel)
            st.download_button("📥 Descargar Archivo (PDF)", data=pdf_bytes_archivo_diario, file_name=f"Cierre_{fecha_cal_sel}.pdf", mime="application/pdf")
        
        st.divider()
        with st.expander("Ver Lista Detallada"):
            st.dataframe(df_cerradas_espejo[['NUM', 'TECNICO', 'ACTIVIDAD', 'TIEMPO_REAL', 'COMENTARIO']], hide_index=True, use_container_width=True)

    with tab_semanal:
        st.subheader("Rendimiento y Tiempos Semanales")
        rango_fecha = st.date_input("Rango de evaluación:", value=(hoy_date_valor - timedelta(days=7), hoy_date_valor), key="date_semanal")
        if len(rango_fecha) == 2:
            df_sem = df_base[(df_base['HORA_LIQ'].dt.date >= rango_fecha[0]) & (df_base['HORA_LIQ'].dt.date <= rango_fecha[1]) & (df_base['ESTADO'].astype(str).str.contains('CERRADA', na=False, case=False))]
            
            if st.button("🚀 GENERAR PDF SEMANAL", use_container_width=True, type="primary"):
                pdf_sem_bytes = generar_pdf_semanal(df_base, rango_fecha[0], rango_fecha[1])
                st.download_button("📥 Descargar PDF Semanal", data=pdf_sem_bytes, file_name=f"Semanal_{rango_fecha[0]}_al_{rango_fecha[1]}.pdf", mime="application/pdf")

    with tab_mensual:
        st.subheader("Visión Macro Gerencial")
        col_mes, col_anio = st.columns(2)
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        with col_mes: mes_sel = st.selectbox("Mes:", meses, index=hoy_date_valor.month - 1)
        with col_anio: anio_sel = st.number_input("Año:", min_value=2024, max_value=2030, value=2026)
        
        st.markdown("### 🏢 Comparativa Segmento")
        fig_pie_mensual = px.pie(df_base, names='SEGMENTO', hole=.4, template="plotly_dark")
        st.plotly_chart(fig_pie_mensual, use_container_width=True)
        
        if st.button("🚀 GENERAR PDF MENSUAL", use_container_width=True, type="primary"):
            mes_num = meses.index(mes_sel) + 1
            pdf_men_bytes = generar_pdf_mensual(df_base, mes_num, anio_sel)
            st.download_button("📥 Descargar PDF Mensual", data=pdf_men_bytes, file_name=f"Mensual_{mes_sel}_{anio_sel}.pdf", mime="application/pdf")
