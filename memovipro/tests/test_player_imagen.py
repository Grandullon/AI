"""Tests del fallback _click_imagen del Player y su orden en _click_control."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.player import Player


def test_click_imagen_sin_b64():
    p = Player.__new__(Player)
    p.dry_run = False
    assert Player._click_imagen(p, "") is False


def test_click_imagen_dry_run():
    p = Player.__new__(Player)
    p.dry_run = True
    assert Player._click_imagen(p, "ABC123") is True


def test_click_imagen_encuentra_y_clica(monkeypatch):
    import core.image_match as im
    monkeypatch.setattr(im, "buscar_en_pantalla", lambda b64, **kw: (500, 300))

    p = Player.__new__(Player)
    p.dry_run = False
    clicks = []
    p._click_xy = lambda x, y, button="left", double=False: clicks.append((x, y, button, double))

    ok = Player._click_imagen(p, "fake_b64", button="left", double=True)
    assert ok is True
    assert clicks == [(500, 300, "left", True)]


def test_click_imagen_no_encuentra(monkeypatch):
    import core.image_match as im
    monkeypatch.setattr(im, "buscar_en_pantalla", lambda b64, **kw: None)

    p = Player.__new__(Player)
    p.dry_run = False
    p._click_xy = lambda *a, **kw: None
    assert Player._click_imagen(p, "fake_b64") is False


def test_click_control_orden_de_fallback():
    """Inspección estática: imagen va entre win_rel y absoluto."""
    import inspect
    src = inspect.getsource(Player._click_control)
    assert "_click_imagen" in src
    idx_winrel = src.find("_click_window_relative")
    idx_img = src.find("_click_imagen")
    idx_abs = src.find("fallback[0]")
    # win_rel < imagen < absoluto
    assert idx_winrel < idx_img < idx_abs
