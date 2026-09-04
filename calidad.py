"""
Chequeos de calidad de datos para el monitor operativo.

Detecta las condiciones que hacen que una orden "no aparezca" o se cuente mal:
  - órdenes vivas SIN hora de inicio (no se dibujan en el Gantt),
  - NUM duplicados (una versión puede tapar a la otra en la deduplicación),
  - órdenes válidas SIN técnico asignado.

Es una función pura sobre un DataFrame para poder probarla sin streamlit.
"""

import pandas as pd

# Estados que indican que la orden sigue viva (asignada / en proceso).
_PATRON_VIVAS = ('PENDIENTE|INICIADA|PROCESO|ASIGNADA|DESPACHO|RUTA|SITIO|'
                 'VIAJANDO|CAMINO|LLEGADA|ABIERTA|EJECUCION|ATENDIENDO|TRABAJANDO')
_TECNICOS_INVALIDOS = {'', 'NONE', 'NAN', 'N/D', 'NULL', '0'}


def reporte_calidad_datos(df: pd.DataFrame) -> dict:
    """
    Devuelve un diccionario con los conteos y las filas problemáticas:
      {
        'vivas_sin_hora_inicio': DataFrame,
        'num_duplicados': DataFrame,
        'vivas_sin_tecnico': DataFrame,
        'totales': {...}
      }
    """
    if df is None or df.empty:
        vacio = pd.DataFrame()
        return {
            'vivas_sin_hora_inicio': vacio,
            'num_duplicados': vacio,
            'vivas_sin_tecnico': vacio,
            'totales': {'vivas_sin_hora_inicio': 0, 'num_duplicados': 0, 'vivas_sin_tecnico': 0},
        }

    estado = df['ESTADO'].astype(str).str.upper() if 'ESTADO' in df.columns else pd.Series([''] * len(df), index=df.index)
    es_viva = estado.str.contains(_PATRON_VIVAS, na=False, regex=True)

    # 1) Vivas sin hora de inicio.
    if 'HORA_INI' in df.columns:
        sin_hora = df['HORA_INI'].isna() | (df['HORA_INI'].astype(str).str.strip().isin(['', 'NaT', 'nan']))
    else:
        sin_hora = pd.Series([True] * len(df), index=df.index)
    vivas_sin_hora = df[es_viva & sin_hora]

    # 2) NUM duplicados (ignorando los N/D, que son marcadores de faltante).
    if 'NUM' in df.columns:
        num_norm = df['NUM'].astype(str).str.strip()
        reales = num_norm[(num_norm != '') & (num_norm != 'N/D')]
        dup_nums = reales[reales.duplicated(keep=False)]
        num_duplicados = df.loc[dup_nums.index]
    else:
        num_duplicados = df.iloc[0:0]

    # 3) Vivas sin técnico asignado.
    if 'TECNICO' in df.columns:
        tec_norm = df['TECNICO'].fillna('').astype(str).str.strip().str.upper()
        sin_tec = tec_norm.isin(_TECNICOS_INVALIDOS)
    else:
        sin_tec = pd.Series([True] * len(df), index=df.index)
    vivas_sin_tecnico = df[es_viva & sin_tec]

    return {
        'vivas_sin_hora_inicio': vivas_sin_hora,
        'num_duplicados': num_duplicados,
        'vivas_sin_tecnico': vivas_sin_tecnico,
        'totales': {
            'vivas_sin_hora_inicio': int(len(vivas_sin_hora)),
            'num_duplicados': int(len(num_duplicados)),
            'vivas_sin_tecnico': int(len(vivas_sin_tecnico)),
        },
    }
