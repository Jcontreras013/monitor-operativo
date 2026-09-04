"""Pruebas del reporte de calidad de datos."""
import pandas as pd
from calidad import reporte_calidad_datos


def _df():
    return pd.DataFrame([
        # viva sin hora de inicio -> problema
        {'NUM': '1', 'ESTADO': 'PENDIENTE', 'HORA_INI': None, 'TECNICO': 'JUAN'},
        # viva OK
        {'NUM': '2', 'ESTADO': 'ASIGNADA', 'HORA_INI': '2026-09-03 08:00', 'TECNICO': 'PEDRO'},
        # cerrada sin hora -> NO es problema (no está viva)
        {'NUM': '3', 'ESTADO': 'CERRADA', 'HORA_INI': None, 'TECNICO': 'ANA'},
        # viva sin tecnico -> problema
        {'NUM': '4', 'ESTADO': 'PROCESO', 'HORA_INI': '2026-09-03 09:00', 'TECNICO': ''},
        # NUM duplicado (con el 2) -> problema
        {'NUM': '2', 'ESTADO': 'CERRADA', 'HORA_INI': '2026-09-03 07:00', 'TECNICO': 'LUIS'},
    ])


def test_conteos():
    r = reporte_calidad_datos(_df())
    t = r['totales']
    assert t['vivas_sin_hora_inicio'] == 1, t
    assert t['vivas_sin_tecnico'] == 1, t
    assert t['num_duplicados'] == 2, t  # las dos filas con NUM '2'


def test_df_vacio_no_truena():
    r = reporte_calidad_datos(pd.DataFrame())
    assert r['totales']['vivas_sin_hora_inicio'] == 0


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    fallos = 0
    for fn in fns:
        try:
            fn(); print(f"  ✅ {fn.__name__}")
        except AssertionError as e:
            fallos += 1; print(f"  ❌ {fn.__name__}: {e}")
    print(f"\n{len(fns)-fallos}/{len(fns)} pruebas pasaron.")
    return fallos == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run() else 1)
