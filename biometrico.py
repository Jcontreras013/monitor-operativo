import pandas as pd
import streamlit as st
import io

def limpiar_marcas(records_str):
    """Toma la cadena '08:00;08:00;12:00;17:00' y elimina los dedazos repetidos"""
    if pd.isna(records_str) or str(records_str).strip() == '':
        return []
    
    tiempos_crudos = [t.strip() for t in str(records_str).split(';') if t.strip()]
    tiempos_limpios = []
    
    for t in tiempos_crudos:
        try:
            # Convertimos a formato de tiempo para comparar diferencias
            dt = pd.to_datetime(t, format='%H:%M')
            
            if not tiempos_limpios:
                tiempos_limpios.append(dt)
            else:
                # Si la diferencia con la marca anterior es mayor a 15 minutos, es una marca real
                diff_mins = (dt - tiempos_limpios[-1]).total_seconds() / 60
                if diff_mins > 15:
                    tiempos_limpios.append(dt)
        except:
            pass
            
    # Devolvemos la lista en el formato innegociable HH:mm:ss
    return [dt.strftime('%H:%M:%S') for dt in tiempos_limpios]

def asignar_columnas(marcas):
    """Distribuye las marcas limpias en el formato de tabla visual"""
    res = {'Entrada': '-', 'S. Almuerzo': '-', 'E. Almuerzo': '-', 'Salida': '-'}
    n = len(marcas)
    
    if n == 1:
        res['Entrada'] = marcas[0]
    elif n == 2:
        res['Entrada'] = marcas[0]
        res['Salida'] = marcas[-1]
    elif n == 3:
        res['Entrada'] = marcas[0]
        res['S. Almuerzo'] = marcas[1]
        res['Salida'] = marcas[-1]
    elif n >= 4:
        res['Entrada'] = marcas[0]
        res['S. Almuerzo'] = marcas[1]
        res['E. Almuerzo'] = marcas[2]
        res['Salida'] = marcas[-1]
        
    return pd.Series(res)

def vista_biometrico():
    st.title("📊 Reporte de Asistencia (Time Card)")
    st.markdown("Sube tu archivo **`Time Card.csv`**. El sistema limpiará las marcas repetidas y generará la tabla consolidada por departamento.")
    
    archivo = st.file_uploader("📥 Cargar Time Card.csv", type=['csv'])
    
    if archivo:
        try:
            with st.spinner("Procesando y limpiando marcas..."):
                # 1. Lectura antibasura (eliminando encabezados del reloj)
                content = archivo.getvalue().decode('utf-8-sig', errors='replace')
                lineas = content.splitlines()
                
                inicio_datos = -1
                for i, linea in enumerate(lineas):
                    if "ID" in linea.upper() and "DEPARTMENT" in linea.upper():
                        inicio_datos = i
                        break
                        
                if inicio_datos == -1:
                    st.error("❌ Archivo incorrecto. Por favor, sube el archivo 'Time Card.csv' exportado del reloj.")
                    return
                    
                csv_valido = "\n".join(lineas[inicio_datos:])
                df = pd.read_csv(io.StringIO(csv_valido), sep=',', skipinitialspace=True, on_bad_lines='skip')
                df.columns = [str(col).strip() for col in df.columns]
                
                # 2. Unir nombres y filtrar vacíos
                if 'First Name' in df.columns and 'Last Name' in df.columns:
                    df['Nombre Completo'] = df['First Name'].astype(str) + " " + df['Last Name'].astype(str)
                else:
                    st.error("❌ El archivo no tiene las columnas 'First Name' y 'Last Name'.")
                    return
                
                df = df.dropna(subset=['Records'])
                
                # 3. Limpiar marcas (eliminar repeticiones de 1 minuto)
                df['Marcas_Limpias'] = df['Records'].apply(limpiar_marcas)
                
                # 4. Expandir en columnas (Entrada, Almuerzo, Salida)
                df_columnas = df['Marcas_Limpias'].apply(asignar_columnas)
                df_final = pd.concat([df, df_columnas], axis=1)
                
                # Seleccionar solo las columnas que queremos mostrar
                columnas_mostrar = ['ID', 'Nombre Completo', 'Date', 'Weekday', 'Entrada', 'S. Almuerzo', 'E. Almuerzo', 'Salida']
                df_final = df_final[columnas_mostrar]
                df_final = df_final.rename(columns={'Date': 'Fecha', 'Weekday': 'Día'})
                
                # 5. Renderizar por pestañas según el Departamento
                st.write("---")
                st.write("### 📋 Resumen de Horas por Departamento")
                
                # Obtener departamentos únicos (limpiando posibles errores del CSV)
                departamentos = [d for d in df['Department'].dropna().unique() if str(d).strip() != ""]
                
                if departamentos:
                    tabs = st.tabs([str(d).upper() for d in departamentos])
                    for i, depto in enumerate(departamentos):
                        with tabs[i]:
                            df_depto = df_final[df['Department'] == depto].drop(columns=['ID']).reset_index(drop=True)
                            st.dataframe(df_depto, use_container_width=True, hide_index=True)
                else:
                    st.dataframe(df_final.drop(columns=['ID']), use_container_width=True, hide_index=True)
                    
        except Exception as e:
            st.error(f"❌ Ocurrió un error al procesar la tabla: {e}")
