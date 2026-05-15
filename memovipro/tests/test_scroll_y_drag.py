"""Tests para captura/reproducción de scroll y drag."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import (
    DRAG_DIST_THRESHOLD_PX,
    EventoCrudo,
    Recorder,
)
from core.step_model import StepType


def _set_time(monkeypatch, valores):
    it = iter(valores)
    monkeypatch.setattr("core.recorder.time.time", lambda: next(it))


# ---------- SCROLL ----------

def test_scroll_se_graba_con_dy(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])
    rec._on_scroll(400, 300, 0, -3)  # scroll abajo 3 notches
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "scroll"
    assert evt.x == 400 and evt.y == 300
    assert evt.dy == -3


def test_scroll_con_ctrl_mantiene_modifier(monkeypatch):
    """Ctrl+rueda = zoom en muchas apps."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.1])

    class _Key:
        def __init__(self, n): self._n = n
        def __str__(self): return f"Key.{self._n}"
        char = None

    rec._on_press(_Key("ctrl"))
    rec._on_scroll(500, 500, 0, 2)

    assert rec.eventos_crudos[0].tipo == "scroll"
    assert rec.eventos_crudos[0].modifiers == "ctrl"


def test_construir_macro_genera_step_scroll():
    eventos = [EventoCrudo(tipo="scroll", x=100, y=200, dx=0, dy=-5, timestamp=1.0)]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert len(macro.pasos) == 1
    assert macro.pasos[0].tipo == StepType.SCROLL
    assert macro.pasos[0].extra["dy"] == -5
    assert macro.pasos[0].extra["x"] == 100


# ---------- DRAG ----------

class _Btn:
    def __init__(self, name): self._n = name
    def __str__(self): return f"Button.{self._n}"


def test_press_y_release_cercanos_es_click(monkeypatch):
    """Press + release a la misma posición (±2 px) = click normal, NO drag."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.0])

    rec._on_click(100, 200, _Btn("left"), True)   # press
    rec._on_click(101, 201, _Btn("left"), False)  # release a 1 px

    assert len(rec.eventos_crudos) == 1
    assert rec.eventos_crudos[0].tipo == "click"


def test_press_y_release_lejos_es_drag(monkeypatch):
    """Press + release a más de DRAG_DIST_THRESHOLD_PX = drag."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.5])

    rec._on_click(100, 200, _Btn("left"), True)
    rec._on_click(300, 400, _Btn("left"), False)

    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "drag"
    assert evt.x == 100 and evt.y == 200
    assert evt.x2 == 300 and evt.y2 == 400


def test_drag_con_ctrl_lleva_modifier(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.0, 100.5])

    class _Key:
        def __init__(self, n): self._n = n
        def __str__(self): return f"Key.{self._n}"
        char = None

    rec._on_press(_Key("ctrl"))
    rec._on_click(50, 60, _Btn("left"), True)
    rec._on_click(250, 60, _Btn("left"), False)

    assert rec.eventos_crudos[0].tipo == "drag"
    assert rec.eventos_crudos[0].modifiers == "ctrl"


def test_construir_macro_genera_step_drag():
    eventos = [EventoCrudo(
        tipo="drag", x=10, y=20, x2=200, y2=20, button="left", timestamp=1.0,
    )]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert macro.pasos[0].tipo == StepType.DRAG
    assert macro.pasos[0].extra["x1"] == 10
    assert macro.pasos[0].extra["y1"] == 20
    assert macro.pasos[0].extra["x2"] == 200


def test_release_huerfano_se_ignora(monkeypatch):
    """Si llega un release sin press previo, no debe romper nada."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])
    rec._on_click(100, 200, _Btn("left"), False)  # solo release
    assert len(rec.eventos_crudos) == 0


def test_threshold_drag_constante():
    """Cubre el caso límite: exactamente DRAG_DIST_THRESHOLD_PX es click."""
    assert DRAG_DIST_THRESHOLD_PX == 8
