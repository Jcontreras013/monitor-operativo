import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import re

def extraer_horas(tiempo_str):
    if not isinstance(tiempo_str, str): return 0
    m = re.match(r'(?i)(\d+)h\s*(\d+)m', tiempo_str.strip().replace('O','0'))
    if m:
        return int(m.group(1)) + round(int(m.group(2))/60, 2)
    return 0

def mostrar_tiempos_tecnicos():
    st.subheader("Análisis de Eficiencia: Tiempo Muerto vs Pausas Reportadas")
    
    try:
        df_pausas = pd.read_excel("Atrasos 29.04.2026.xlsx", sheet_name='Hoja1', header=2)
        df_pausas = df_pausas.dropna(axis=1, how='all')
        df_pausas['TECNICO'] = df_pausas['TECNICO5'].str.strip().str.upper()
        
        df_pausas['FECHA_INICIO'] = pd.to_datetime(df_pausas['FECHA_INICIO'], errors='coerce')
        df_pausas['FECHA_FIN'] = pd.to_datetime(df_pausas['FECHA_FIN'], errors='coerce')
        
        df_29 = df_pausas[(df_pausas['FECHA_INICIO'].dt.day == 29) | (df_pausas['FECHA_FIN'].dt.day == 29)].copy()
        df_29['DURACION_HORAS'] = (df_29['FECHA_FIN'] - df_29['FECHA_INICIO']).dt.total_seconds() / 3600
        pausas_agrupadas = df_29.groupby('TECNICO')['DURACION_HORAS'].sum().reset_index()
        
    except Exception as e:
        st.error(f"Error al leer archivo de Excel: {e}")
        return

    datos_pdf = [
        {'TECNICO': 'DANIEL EZEQUIEL PONCE GUZMAN', 'TIEMPO_MUERTO': '1h 21m'},
        {'TECNICO': 'DARREN HENLEY WEBSTER BENNETT', 'TIEMPO_MUERTO': '4h 47m'},
        {'TECNICO': 'DARWIN RAUL AGUILAR BENITEZ', 'TIEMPO_MUERTO': '0h 18m'},
        {'TECNICO': 'EDGARDO DANIEL CASTRO SALGADO', 'TIEMPO_MUERTO': '3h 33m'},
        {'TECNICO': 'EDY FLORENTINO GUZMAN PEREZ', 'TIEMPO_MUERTO': '0h 0m'},
        {'TECNICO': 'FRANKLIN ALONZO DELARCA ZELAYA', 'TIEMPO_MUERTO': '0h 0m'},
        {'TECNICO': 'MARVIN DARREL BODDEN SANCHEZ', 'TIEMPO_MUERTO': '1h 26m'},
        {'TECNICO': 'OLVIN JOSUE PINEDA CASTELLANOS', 'TIEMPO_MUERTO': '1h 52m'},
        {'TECNICO': 'QUIEN CHARLEE FRITZ MATUTE', 'TIEMPO_MUERTO': '5h 44m'},
        {'TECNICO': 'RAYAM ORLIN MACLIN ALVAREZ', 'TIEMPO_MUERTO': '1h 24m'},
        {'TECNICO': 'ROBERTO CARLOS JUAREZ PADILLA', 'TIEMPO_MUERTO': '1h 50m'},
        {'TECNICO': 'VICTOR MANUEL CASTELLANOS DURON', 'TIEMPO_MUERTO': '0h 50m'}
    ]
    
    df_muerto = pd.DataFrame(datos_pdf)
    df_muerto['MUERTO_HORAS'] = df_muerto['TIEMPO_MUERTO'].apply(extraer_horas)

    df_final = pd.merge(df_muerto, pausas_agrupadas, on='TECNICO', how='left').fillna(0)
    df_final.rename(columns={'DURACION_HORAS': 'PAUSAS_HORAS'}, inplace=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_final['TECNICO'], 
        y=df_final['MUERTO_HORAS'],
        name='Tiempo Muerto (Órdenes)',
        marker_color='#ef4444'
    ))
    fig.add_trace(go.Bar(
        x=df_final['TECNICO'], 
        y=df_final['PAUSAS_HORAS'],
        name='Pausas (Reportadas a Supervisor)',
        marker_color='#3b82f6'
    ))
    fig.update_layout(
        barmode='group',
        xaxis_tickangle=-45,
        height=550
    )
    st.plotly_chart(fig, use_container_width=True)
