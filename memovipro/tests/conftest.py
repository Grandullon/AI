"""Configuración común de los tests.

Incluye un interruptor para ejecutar la suite COMO SI FUERA WINDOWS en
lo que se refiere a la consulta del estado del teclado:

    MEMOVIPRO_SIMULAR_WINDOWS=1 python -m pytest

Hace falta porque `_modificadores_realmente_pulsados()` devuelve None
fuera de Windows (no hay ctypes.windll), así que en Linux ese camino no
se ejercita nunca: la suite pasaba en verde aquí y fallaba en el build.
Con el interruptor puesto, la consulta responde "ninguna tecla pulsada",
que es justo lo que ocurre en el runner de Windows, donde nadie está
tocando el teclado de verdad.
"""
import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _simular_windows():
    if os.environ.get("MEMOVIPRO_SIMULAR_WINDOWS") != "1":
        yield
        return
    import core.recorder as rec
    from core.player import Player

    original = rec._modificadores_realmente_pulsados
    rec._modificadores_realmente_pulsados = lambda: set()
    # En Windows hay SIEMPRE una ventana delante (en el runner, la
    # terminal). En Linux la consulta devuelve vacío y eso se interpreta
    # como "no lo sé", que deja pasar cualquier comprobación: por eso un
    # test que olvide simular esta consulta pasaba aquí y fallaba en el
    # build. Simulamos una ventana ajena para que salte antes.
    original_frontal = Player._ventana_frontal
    Player._ventana_frontal = staticmethod(
        lambda: ("desconocido.exe", "Ventana cualquiera"))
    try:
        yield
    finally:
        rec._modificadores_realmente_pulsados = original
        Player._ventana_frontal = original_frontal


# Nota para quien desarrolle en Linux: la suite se ejecuta también con
#   MEMOVIPRO_SIMULAR_WINDOWS=1 python -m pytest
# antes de subir nada que toque la captura de teclado. Sin eso, el camino
# que solo existe en Windows no se prueba aquí y el fallo aparece en el
# build, no en tu máquina.
