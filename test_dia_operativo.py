"""Pruebas del día operativo (corte de jornada a las 6:00)."""
import pandas as pd
from datetime import date
from fechas import a_dia_operativo


def test_escalar_mismo_dia():
    # 11:23 - 6h = 05:23 del mismo día.
    assert a_dia_operativo("2026-09-03 11:23") == date(2026, 9, 3)


def test_escalar_madrugada_cuenta_dia_anterior():
    # 02:00 - 6h = 20:00 del día anterior: pertenece a la jornada previa.
    assert a_dia_operativo("2026-09-03 02:00") == date(2026, 9, 2)


def test_nulo_devuelve_none():
    assert a_dia_operativo(None) is None
    assert a_dia_operativo("no es fecha") is None


def test_serie_vectorizada():
    s = pd.Series(["2026-09-03 11:23", "2026-09-03 02:00", None])
    r = a_dia_operativo(s)
    assert list(r) == [date(2026, 9, 3), date(2026, 9, 2), None] or \
           (r.iloc[0] == date(2026, 9, 3) and r.iloc[1] == date(2026, 9, 2) and pd.isna(r.iloc[2]))


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
