import streamlit as st
import pandas as pd
from datetime import datetime
import re

# ==============================================================================
# LÓGICA DE AUDITORÍA DE VEHÍCULOS
# ==============================================================================
def procesar_auditoria_vehiculos(df):
    try:
        cols_necesarias = ['Placa-Alias', 'Hora Ingreso', 'Hora Salida']
        if not all(col in df.columns for col in cols_necesarias):
            col_placa = next((c for c in df.columns if 'PLACA' in str(c).upper() or 'ALIAS' in str(c).upper() or 'VEHICULO' in str(c).upper()), None)
            col_ingreso = next((c for c in df.columns if 'INGRESO' in str(c).upper() or 'ENTRADA' in str(c).upper()), None)
            col_salida = next((c for c in df.columns if 'SALIDA' in str(c).upper()), None)
            
            if not (col_placa and col_ingreso and col_salida):
                return None, "El archivo no tiene el formato esperado. Faltan columnas de Placa, Ingreso o Salida."
            df = df.rename(columns={col_placa: 'Placa-Alias', col_ingreso: 'Hora Ingreso', col_salida: 'Hora Salida'})
        
        df['Placa-Alias'] = df['Placa-Alias'].astype(str).str.replace(r'\xa0', ' ', regex=True)
        df['Placa-Alias'] = df['Placa-Alias'].str.replace(r'\s+', ' ', regex=True).str.strip()
        df = df[~df['Placa-Alias'].isin(['nan', '--', 'Placa-Alias', 'None', ''])]
        
        df['Hora Ingreso'] = pd.to_datetime(df['Hora Ingreso'], errors='coerce')
        df['Hora Salida'] = pd.to_datetime(df['Hora Salida'], errors='coerce')
        
        resumen = df.groupby('Placa-Alias').agg(
            Primera_Salida=('Hora Salida', 'min'),
            Ultima_Entrada=('Hora Ingreso', 'max')
        ).reset_index()
        
        def calc_tiempo(row):
            if pd.isnull(row['Primera_Salida']): return "Sin Salida (No arrancó)"
            if pd.isnull(row['Ultima_Entrada']): return "Sin Ingreso (Falta cierre)"
            
            if row['Ultima_Entrada'] >= row['Primera_Salida']:
                diff = row['Ultima_Entrada'] - row['Primera_Salida']
                total_seconds = int(diff.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                return "Revisar (Entró antes de salir)"
                
        resumen['Tiempo Total Fuera'] = resumen.apply(calc_tiempo, axis=1)
        resumen['Primera_Salida'] = resumen['Primera_Salida'].dt.strftime('%I:%M:%S %p').fillna("---")
        resumen['Ultima_Entrada'] = resumen['Ultima_Entrada'].dt.strftime('%I:%M:%S %p').fillna("---")
        resumen.columns = ['Vehículo / Placa', 'Primera Salida', 'Última Entrada', 'Tiempo Real en Calle']
        
        return resumen, "OK"
    except Exception as e:
        return None, str(e)

# ==============================================================================
# PANTALLA VISUAL QUE SE LLAMARÁ DESDE APP.PY
# ==============================================================================
def mostrar_auditoria():
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("") 
        st.markdown("<h1 style='text-align: center;'>🚙</h1>", unsafe_allow_html=True)
    with col2:
        st.title("Auditoría de Tiempos de Ruta (GPS)")
        st.caption("Consolida el tiempo real en calle de cada vehículo a partir del reporte crudo de Zonas/Rutas.")

    st.divider()
    st.markdown("### 1. Cargar Reporte del GPS")
    archivo_gps = st.file_uploader("Arrastra aquí el archivo Excel o CSV generado por la plataforma de GPS", type=['csv', 'xlsx'])
    
    if archivo_gps is not None:
        with st.spinner("🔍 Analizando datos, limpiando duplicados y calculando tiempos..."):
            try:
                if archivo_gps.name.endswith('.csv'): df_gps = pd.read_csv(archivo_gps)
                else: df_gps = pd.read_excel(archivo_gps)
                    
                df_resumen_gps, mensaje_error = procesar_auditoria_vehiculos(df_gps)
                
                if df_resumen_gps is not None:
                    st.success("✅ ¡Análisis completado! Vehículos unificados y tiempos consolidados correctamente.")
                    
                    st.markdown("### 2. Resultados de la Auditoría")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Vehículos Activos", len(df_resumen_gps))
                    vehiculos_calle = len(df_resumen_gps[df_resumen_gps['Última Entrada'] == "---"])
                    m2.metric("Vehículos Aún en Calle", vehiculos_calle)
                    
                    st.dataframe(df_resumen_gps, use_container_width=True, hide_index=True)
                    
                    csv_gps = df_resumen_gps.to_csv(index=False).encode('utf-8')
                    st.divider()
                    st.markdown("### 3. Exportar Información")
                    st.download_button(
                        label="📥 Descargar Reporte Final (CSV)",
                        data=csv_gps,
                        file_name=f"Auditoria_Vehiculos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        type="primary",
                        use_container_width=True
                    )
                else:
                    st.error(f"❌ Ocurrió un error al procesar el formato: {mensaje_error}")
            except Exception as e:
                st.error(f"❌ Error crítico al leer el archivo: {e}")
