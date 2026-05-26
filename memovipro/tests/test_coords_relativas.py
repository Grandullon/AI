"""Tests para coordenadas relativas a ventana (DPI/multimonitor) y la
captura extendida de selectores con win_rel."""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.recorder as rec_mod
from core.recorder import EventoCrudo, Recorder
from core.step_model import Selector, StepType


# ===== construir_macro guarda win_rel =====

def test_construir_macro_guarda_win_rel_en_click_control(monkeypatch):
    def fake(x, y):
        return (
            Selector(control_type="Button", name="OK"),
            "OK",
            {"title": "INFORMES", "fx": 0.5, "fy": 0.3},
        )
    monkeypatch.setattr(rec_mod, "_selector_desde_punto", fake)

    eventos = [EventoCrudo(tipo="click", x=100, y=200, timestamp=1.0)]
    macro = Recorder.construir_macro(eventos, resolver_selectores=True)
    paso = macro.pasos[0]
    assert paso.tipo == StepType.CLICK_CONTROL
    assert paso.extra["win_rel"] == {"title": "INFORMES", "fx": 0.5, "fy": 0.3}
    assert paso.extra["fallback_xy"] == [100, 200]


def test_construir_macro_win_rel_en_click_at_xy(monkeypatch):
    """Si no hay selector pero sí win_rel, se guarda igualmente."""
    def fake(x, y):
        return (None, f"({x},{y})", {"title": "Excel", "fx": 0.1, "fy": 0.9})
    monkeypatch.setattr(rec_mod, "_selector_desde_punto", fake)

    eventos = [EventoCrudo(tipo="click", x=10, y=20, timestamp=1.0)]
    macro = Recorder.construir_macro(eventos, resolver_selectores=True)
    paso = macro.pasos[0]
    assert paso.tipo == StepType.CLICK_AT_XY
    assert paso.extra["win_rel"]["title"] == "Excel"


def test_construir_macro_sin_win_rel_no_lo_incluye():
    eventos = [EventoCrudo(tipo="click", x=10, y=20, timestamp=1.0)]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert "win_rel" not in macro.pasos[0].extra


# ===== _ventana_relativa_desde_punto =====

class _FakeRect:
    def __init__(self, left, top, w, h):
        self.left = left
        self.top = top
        self._w = w
        self._h = h
    def width(self):
        return self._w
    def height(self):
        return self._h


class _FakeTop:
    def __init__(self, titulo, rect):
        self._titulo = titulo
        self._rect = rect
    def rectangle(self):
        return self._rect
    def window_text(self):
        return self._titulo


class _FakeElem:
    def __init__(self, top):
        self._top = top
    def top_level_parent(self):
        return self._top


def test_ventana_relativa_calcula_fracciones():
    # Ventana en (100,100) de 800x600. Clic en (500, 400).
    # fx = (500-100)/800 = 0.5 ; fy = (400-100)/600 = 0.5
    top = _FakeTop("INFORMES", _FakeRect(100, 100, 800, 600))
    elem = _FakeElem(top)
    out = rec_mod._ventana_relativa_desde_punto(elem, 500, 400)
    assert out is not None
    assert out["title"] == "INFORMES"
    assert abs(out["fx"] - 0.5) < 1e-3
    assert abs(out["fy"] - 0.5) < 1e-3


def test_ventana_relativa_fuera_de_ventana_devuelve_none():
    top = _FakeTop("X", _FakeRect(0, 0, 100, 100))
    elem = _FakeElem(top)
    # Clic en (500, 500) está fuera de la ventana 100x100
    assert rec_mod._ventana_relativa_desde_punto(elem, 500, 500) is None


def test_ventana_relativa_sin_titulo_devuelve_none():
    top = _FakeTop("", _FakeRect(0, 0, 100, 100))
    elem = _FakeElem(top)
    assert rec_mod._ventana_relativa_desde_punto(elem, 50, 50) is None


# ===== Player._click_window_relative =====

def test_click_window_relative_dry_run():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = True
    ok = Player._click_window_relative(p, {"title": "INFORMES", "fx": 0.5, "fy": 0.5})
    assert ok is True


def test_click_window_relative_sin_titulo():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    assert Player._click_window_relative(p, {"fx": 0.5, "fy": 0.5}) is False
    assert Player._click_window_relative(p, {}) is False
    assert Player._click_window_relative(p, None) is False


def test_click_window_relative_calcula_y_clica(monkeypatch):
    """Verifica que calcula el punto absoluto desde las fracciones y
    delega en _click_xy."""
    from core.player import Player
    import core.player as player_mod

    class _FakeWin:
        def exists(self, timeout=None):
            return True
        def rectangle(self):
            return _FakeRect(200, 100, 1000, 800)

    class _FakeDesktop:
        def window(self, title_re):
            return _FakeWin()

    monkeypatch.setattr(player_mod, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(player_mod, "Desktop", lambda backend: _FakeDesktop())

    p = Player.__new__(Player)
    p.dry_run = False
    clicks = []
    p._click_xy = lambda x, y, button="left", double=False: clicks.append((x, y, button, double))

    ok = Player._click_window_relative(p, {"title": "X", "fx": 0.5, "fy": 0.25}, button="left")
    assert ok is True
    # x = 200 + 0.5*1000 = 700 ; y = 100 + 0.25*800 = 300
    assert clicks == [(700, 300, "left", False)]


def test_player_click_control_usa_win_rel_antes_que_absoluto():
    """Inspección estática del orden de fallback."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._click_control)
    assert "win_rel" in src
    assert "_click_window_relative" in src
    # win_rel debe intentarse antes que el fallback absoluto
    idx_winrel = src.find("_click_window_relative")
    idx_fallback = src.find("fallback[0]")
    assert idx_winrel < idx_fallback
