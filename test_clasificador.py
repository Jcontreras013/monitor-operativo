"""
Pruebas de la clasificación de actividades.

Se ejecutan sin streamlit ni pandas:  python -m pytest test_clasificador.py
o simplemente:  python test_clasificador.py

Incluye los casos concretos que fallaron en producción, para que esos bugs
no puedan volver a colarse (regresión).
"""

from clasificador import (
    es_plex,
    es_sop,
    es_instalacion,
    subtipo_instalacion,
    clasificar_tablero,
)


def test_es_plex_por_actividad():
    assert es_plex("PEXTERNO")
    assert es_plex("SPLITTEROPT")
    assert es_plex("PLEXISCA")
    assert not es_plex("SOPFIBRA")
    assert not es_plex("INSFIBRA")
    assert not es_plex("")
    assert not es_plex(None)


def test_es_sop_y_instalacion():
    assert es_sop("SOPFIBRACORP")
    assert es_sop("SOP")
    assert not es_sop("INSFIBRA")
    assert es_instalacion("INSFIBRA")
    assert es_instalacion("orden NUEVA de cliente")
    assert not es_instalacion("PEXTERNO")


def test_subtipo_instalacion():
    assert subtipo_instalacion("INS ADIC") == "Adición"
    assert subtipo_instalacion("CAMBIO de plan") == "Cambio / Migración"
    assert subtipo_instalacion("MIGRACION") == "Cambio / Migración"
    assert subtipo_instalacion("RECUPERADO") == "Recuperado"
    assert subtipo_instalacion("INSFIBRA nueva") == "Nueva"


def test_regresion_pexterno_no_se_fuga_a_ins_o_sop():
    # EL BUG DE ESTA SESIÓN: un PEXTERNO cuyo comentario menciona instalación,
    # nueva, falla, cambio, etc. NO debe salir de "OTROS".
    casos = [
        ("PEXTERNO", "instalacion de nueva acometida"),
        ("PEXTERNO", "falla en poste"),
        ("PEXTERNO", "revision de cambio de ruta"),
        ("SPLITTEROPT", "nueva caja splitter"),
        ("SPLITTEROPT", "mantenimiento preventivo"),
        ("PLEXISCA", "cliente reporta falla"),
    ]
    for act, com in casos:
        grupo, _ = clasificar_tablero(act, com)
        assert grupo == "OTROS", f"{act} / {com} -> {grupo} (debía ser OTROS)"


def test_clasificacion_normal_se_mantiene():
    # Un soporte real sigue siendo SOP.
    assert clasificar_tablero("SOPFIBRA", "sin internet")[0] == "SOP"
    # Una instalación real sigue siendo INS.
    assert clasificar_tablero("INSFIBRA", "instalacion nueva")[0] == "INS"
    # Un SOP cuyo comentario dice "instalada" NO se va a INS (la actividad manda).
    assert clasificar_tablero("SOPFIBRA", "antena recien instalada")[0] == "SOP"


def test_offline_tiene_prioridad_en_subtipo_sop():
    grupo, subtipo = clasificar_tablero("SOPFIBRA", "ONU OFFLINE", es_offline=True)
    assert grupo == "SOP"
    assert subtipo == "ONT/ONU Offline"


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    fallos = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"  ❌ {fn.__name__}: {e}")
    print(f"\n{len(fns) - fallos}/{len(fns)} pruebas pasaron.")
    return fallos == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run() else 1)
