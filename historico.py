import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
from datetime import datetime, timedelta
import io

# Importamos las herramientas necesarias de tools
from tools import es_alerta_administrativa, logica_generar_pdf

def main_historico(df_hist):
    st.title("📚 Centro de Inteligencia Histórica - Maxcom")
    st.caption("Análisis profundo de rendimientos, garantías y reincidencias.")

    if df_hist is None or df_hist.empty:
        st.warning("⚠️ No hay datos históricos disponibles. Cargue los archivos en el panel lateral.")
        return

    # --- 1. BUSCADOR INTEGRADO ---
    with st.container():
        c1, c2 = st.columns([3, 1])
        with c1:
            busqueda = st.text_input("🔍 Buscador Global (Nombre, Orden, Técnico):", placeholder="Ej: Darwin Aguilar")
        with c2:
            st.write("") # Espaciador
            st.write(f"**Registros:** {len(df_hist)}")

    # Filtrado lógico del buscador
    df_h_filtrado = df_hist.copy()
    if busqueda:
        mask = df_h_filtrado.astype(str).apply(lambda x: x.str.contains(busqueda, case=False)).any(axis=1)
        df_h_filtrado = df_h_filtrado[mask]

    # --- 2. MÉTRICAS CLAVE ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Órdenes Totales", len(df_h_filtrado))
    
    # Cálculo de Garantías/Reincidencias (SOP repetidos en el mismo cliente)
    reincidencias = df_h_filtrado[df_h_filtrado['ACTIVIDAD'].str.contains('SOP', na=False, case=False)]['CLIENTE'].duplicated().sum()
    m2.metric("Posibles Garantías", reincidencias, help="Clientes que aparecen más de una vez con soporte")
    
    promedio = df_h_filtrado['MINUTOS_CALC'].mean() if 'MINUTOS_CALC' in df_h_filtrado.columns else 0
    m3.metric("Tiempo Promedio", f"{int(promedio)} min")
    
    alertas_adm = df_h_filtrado.apply(es_alerta_administrativa, axis=1).sum()
    m4.metric("Alertas Adm.", alertas_adm)

    # --- 3. PESTAÑAS DE ANÁLISIS ---
    t_tabla, t_graficos = st.tabs(["📄 Listado Histórico", "📊 Analítica de Rendimiento"])

    with t_tabla:
        st.dataframe(df_h_filtrado, use_container_width=True, hide_index=True)

    with t_graficos:
        plt.style.use('dark_background')
        g1, g2 = st.columns(2)

        with g1:
            st.markdown("##### 🏆 Top 10 Técnicos (Volumen)")
            fig_tec, ax_tec = plt.subplots(figsize=(8, 5))
            top_tecs = df_h_filtrado['TECNICO'].value_counts().head(10)
            if not top_tecs.empty:
                top_tecs.plot(kind='barh', color='#1f6feb', ax=ax_tec)
                ax_tec.invert_yaxis()
                st.pyplot(fig_tec)

        with g2:
            st.markdown("##### 📈 Composición de Actividades")
            # Agrupar actividades por tipo principal
            def agrupar_act(x):
                x = str(x).upper()
                if 'SOP' in x: return 'SOPORTE'
                if 'INS' in x or 'NUEVA' in x: return 'INSTALACIÓN'
                if 'PLEX' in x: return 'PLEX'
                return 'OTROS'
            
            df_h_filtrado['TIPO_GRUP'] = df_h_filtrado['ACTIVIDAD'].apply(agrupar_act)
            fig_pie = px.pie(df_h_filtrado, names='TIPO_GRUP', hole=0.4, 
                             color_discrete_sequence=['#238636', '#1f6feb', '#f2cc60', '#8b949e'])
            fig_pie.update_layout(template="plotly_dark", height=350, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- 4. EXPORTACIÓN ---
    st.divider()
    if st.button("💾 Generar Reporte de Auditoría (Excel)", use_container_width=True):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_h_filtrado.to_excel(writer, index=False, sheet_name='Historico')
        st.download_button(
            label="⬇️ Descargar Excel",
            data=output.getvalue(),
            file_name=f"Historico_Maxcom_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
