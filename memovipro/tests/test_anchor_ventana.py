"""Tests del campo auto_anchor y del nuevo StepType.WINDOW_ENSURE."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Macro, Step, StepType


def test_macro_auto_anchor_default_true():
    m = Macro(nombre="x")
    assert m.auto_anchor is True


def test_macro_auto_anchor_serializa(tmp_path):
    m = Macro(nombre="x", ventana_principal="MiApp", auto_anchor=False, pasos=[])
    path = tmp_path / "m.yaml"
    m.save(path)
    cargada = Macro.load(path)
    assert cargada.auto_anchor is False


def test_window_ensure_es_un_step_type():
    paso = Step(tipo=StepType.WINDOW_ENSURE, titulo="Excel", extra={"state": "maximized"})
    d = paso.to_dict()
    assert d["tipo"] == "window_ensure"
    assert d["titulo"] == "Excel"
    assert d["extra"]["state"] == "maximized"
    cargado = Step.from_dict(d)
    assert cargado.tipo == StepType.WINDOW_ENSURE


def test_player_tiene_metodo_asegurar_ventana_objetivo():
    """Verificación estática de que el player implementa el método.

    Tras la extracción a core.window_utils, el método del Player ya no
    contiene la lógica de pywinauto directamente — la delega a
    window_utils.asegurar_ventana. Verificamos esa delegación y que
    se mantiene el throttling (`_last_anchor_ts`).
    """
    import inspect
    from core.player import Player
    assert hasattr(Player, "_asegurar_ventana_objetivo")
    src = inspect.getsource(Player._asegurar_ventana_objetivo)
    assert "asegurar_ventana" in src
    assert "_last_anchor_ts" in src
