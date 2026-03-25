import streamlit as st
from tools import es_alerta_administrativa

def main_historico(df_h):
    st.title("📚 Centro de Auditoría (Histórico)")
    
    if df_h is not None:
        df_h['ALERTA'] = df_h.apply(es_alerta_administrativa, axis=1)
        
        col1, col2 = st.columns(2)
        with col1:
            st.error(f"🚨 Casos con Riesgo de Facturación: {df_h['ALERTA'].sum()}")
        with col2:
            busqueda = st.text_input("🔍 Buscar Cliente o Número:")

        df_view = df_h.copy()
        if busqueda:
            df_view = df_view[df_view.apply(lambda r: busqueda.lower() in str(r).lower(), axis=1)]

        st.dataframe(df_view, use_container_width=True, hide_index=True)
    else:
        st.info("Carga los archivos en la pantalla del Monitor para activar el Histórico.")