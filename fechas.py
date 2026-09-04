"""
Ayudantes de fecha SIN dependencias pesadas (solo pandas), para poder
probarlos de forma aislada — a diferencia de tools.py, que al importarse
arrastra google.cloud y otras librerías de despliegue.
"""

import pandas as pd

# Horas que se restan para definir el DÍA OPERATIVO. La jornada arranca a las
# 6:00: un cierre de las 02:00 pertenece al día anterior, no al que empieza.
HORAS_DIA_OPERATIVO = 6


def a_dia_operativo(valor):
    """
    Convierte una fecha/hora (o una columna entera) al DÍA OPERATIVO al que
    pertenece, restándole HORAS_DIA_OPERATIVO. Devuelve la parte de fecha.

    Este criterio estaba escrito a mano (con '- pd.Timedelta(hours=6)') en
    ~17 lugares de app.py; centralizarlo evita que una vista use un corte de
    día distinto al de las demás.

    Acepta un escalar (datetime/str) -> devuelve un datetime.date o None, o
    una Serie/columna de pandas -> devuelve una Serie de datetime.date.
    """
    desfase = pd.Timedelta(hours=HORAS_DIA_OPERATIVO)
    if isinstance(valor, pd.Series):
        return (pd.to_datetime(valor, errors='coerce') - desfase).dt.date
    ts = pd.to_datetime(valor, errors='coerce')
    if pd.isna(ts):
        return None
    return (ts - desfase).date()
