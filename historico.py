import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
from datetime import datetime, timedelta
import io

def main_historico(df_hist):
    st.title("📚 Centro de Inteligencia Histórica")
    st.caption("Auditoría de operaciones, reincidencias y análisis a largo plazo.")

    if df_hist is None or df_hist.empty:
        st.warning("⚠️ El sistema no detecta datos históricos. Asegúrese de procesar los archivos en el panel principal.")
        return

    # --- 1. BUSCADOR GLOBAL ULTRA RÁPIDO ---
    with st.expander("🔍 Buscador Avanzado y Filtros", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            busqueda = st.text_input("Buscar cliente, orden, número o técnico:", placeholder="Ej: 92408321 o Darwin")
        with c2:
            rango_fechas = st.date_input("Filtrar por fechas:", value=[] )
        with c3:
            if 'ESTADO' in df_hist.columns:
                estados_disponibles = df_hist['ESTADO'].dropna().unique().tolist()
                estado_h = st.multiselect("Estado:", estados_disponibles, default=estados_disponibles)

    # Motor de filtrado
    df_h_filtrado = df_hist.copy()
    
    if busqueda:
        # Busca la palabra en absolutamente todas las columnas del dataframe
        mask_busqueda = df_h_filtrado.astype(str).apply(lambda x: x.str.contains(busqueda, case=False, na=False)).any(axis=1)
        df_h_filtrado = df_h_filtrado[mask_busqueda]
        
    if len(rango_fechas) == 2 and 'HORA_LIQ' in df_h_filtrado.columns:
        df_h_filtrado['HORA_LIQ'] = pd.to_datetime(df_h_filtrado['HORA_LIQ'], errors='coerce')
        mask_fechas = (df_h_filtrado['HORA_LIQ'].dt.date >= rango_fechas[0]) & (df_h_filtrado['HORA_LIQ'].dt.date <= rango_fechas[1])
        df_h_filtrado = df_h_filtrado[mask_fechas]
        
    if 'ESTADO' in df_h_filtrado.columns and 'estado_h' in locals() and estado_h:
        df_h_filtrado = df_h_filtrado[df_h_filtrado['ESTADO'].isin(estado_h)]

    # --- 2. KPIS DE AUDITORÍA COMPLEJA ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Órdenes en Pantalla", len(df_h_filtrado))
    
    # Lógica de Reincidencias (Garantías): Mismos clientes pidiendo SOP múltiples veces
    if 'ACTIVIDAD' in df_h_filtrado.columns and 'CLIENTE' in df_h_filtrado.columns:
        mask_sop = df_h_filtrado['ACTIVIDAD'].astype(str).str.contains('SOP|FALLA|MANT', case=False, na=False)
        reincidencias = df_h_filtrado[mask_sop]['CLIENTE'].duplicated().sum()
        m2.metric("Reincidencias (Garantías)", reincidencias, help="Clientes que han solicitado soporte más de una vez en el periodo.")
    else:
        m2.metric("Reincidencias", "N/D")

    # Lógica de Tiempos Promedio
    if 'MINUTOS_CALC' in df_h_filtrado.columns:
        promedio = df_h_filtrado[df_h_filtrado['MINUTOS_CALC'] > 0]['MINUTOS_CALC'].mean()
        m3.metric("Tiempo Promedio Liquidación", f"{int(promedio)} min" if pd.notnull(promedio) else "0 min")
    else:
        m3.metric("Tiempo Promedio", "N/D")
        
    # Lógica interna de Alertas (para no depender de tools.py)
    def detectar_alerta(row):
        act = str(row.get('ACTIVIDAD', '')).upper()
        com = str(row.get('COMENTARIO', '')).upper()
        if any(e in act for e in ['INACTIVO', 'CORTEMORA', 'NOINSTALADO']): return True
        if any(j in com for j in ['NO SE PUDO', 'CANCELADA', 'NO PERMITE', 'CLIENTE NO QUISO']): return True
        return False

    alertas_adm = df_h_filtrado.apply(detectar_alerta, axis=1).sum()
    m4.metric("Alertas / Anuladas", alertas_adm, help="Órdenes no instaladas o con problemas administrativos.")

    # --- 3. TABLAS Y GRÁFICOS MATPLOTLIB/PLOTLY ---
    t_tabla, t_graficos = st.tabs(["📄 Base de Datos", "📊 Analítica de Rendimiento"])

    with t_tabla:
        columnas_ver = ['NUM', 'CLIENTE', 'TECNICO', 'ACTIVIDAD', 'ESTADO', 'HORA_LIQ', 'COMENTARIO']
        cols_existentes = [c for c in columnas_ver if c in df_h_filtrado.columns]
        st.dataframe(df_h_filtrado[cols_existentes] if cols_existentes else df_h_filtrado, use_container_width=True, hide_index=True)

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
                    st.info("Sin datos técnicos.")

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

    # --- 4. EXPORTACIÓN PROFESIONAL ---
    st.divider()
    if st.button("💾 Exportar Histórico Completo a Excel", type="primary", use_container_width=True):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_h_filtrado.to_excel(writer, index=False, sheet_name='Historial_Auditoria')
        
        st.download_button(
            label="⬇️ Descargar Archivo (.xlsx)",
            data=output.getvalue(),
            file_name=f"Auditoria_Maxcom_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
