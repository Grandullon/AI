"""Tests para captura/reproducción de doble clic y botones distintos."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import (
    DOUBLE_CLICK_RADIUS_PX,
    DOUBLE_CLICK_THRESHOLD_S,
    EventoCrudo,
    Recorder,
    _button_corto,
)
from core.step_model import StepType


def test_button_corto_normaliza_strings():
    assert _button_corto("Button.left") == "left"
    assert _button_corto("Button.right") == "right"
    assert _button_corto("Button.middle") == "middle"
    assert _button_corto("Button.x1") == "left"  # desconocido → left por defecto


def _click_completo(rec, x, y, button="Button.left"):
    """Helper: emite press + release en (x, y). Necesario porque ahora el
    Recorder solo genera evento al release, no al press."""
    rec._on_click(x, y, button, True)
    rec._on_click(x, y, button, False)


def test_doble_click_se_fusiona_en_un_evento(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    # Primer clic a t=100, segundo a t=100.2 (200 ms < 500 ms umbral)
    tiempos = iter([100.0, 100.2])
    monkeypatch.setattr("core.recorder.time.time", lambda: next(tiempos))
    _click_completo(rec, 50, 60)
    _click_completo(rec, 52, 61)
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.double is True
    assert evt.x == 50 and evt.y == 60  # se conserva el primer punto


def test_dos_clics_separados_no_se_fusionan(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    tiempos = iter([100.0, 101.0])
    monkeypatch.setattr("core.recorder.time.time", lambda: next(tiempos))
    _click_completo(rec, 50, 60)
    _click_completo(rec, 50, 60)
    assert len(rec.eventos_crudos) == 2
    assert all(not e.double for e in rec.eventos_crudos)


def test_dos_clics_lejos_no_se_fusionan(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    tiempos = iter([100.0, 100.2])
    monkeypatch.setattr("core.recorder.time.time", lambda: next(tiempos))
    _click_completo(rec, 50, 60)
    _click_completo(rec, 200, 60)
    # >8 px de distancia entre los DOS clics; cada uno es press+release en
    # el mismo punto (no es drag).
    assert len(rec.eventos_crudos) == 2
    assert all(not e.double for e in rec.eventos_crudos)


def test_clic_derecho_seguido_no_se_funde_con_izquierdo(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    tiempos = iter([100.0, 100.2])
    monkeypatch.setattr("core.recorder.time.time", lambda: next(tiempos))
    _click_completo(rec, 50, 60, "Button.left")
    _click_completo(rec, 50, 60, "Button.right")
    assert len(rec.eventos_crudos) == 2
    assert rec.eventos_crudos[0].button == "left"
    assert rec.eventos_crudos[1].button == "right"


def test_construir_macro_pasa_double_y_button_a_extra():
    eventos = [
        EventoCrudo(tipo="click", x=10, y=20, button="right", double=False, timestamp=1.0),
        EventoCrudo(tipo="click", x=100, y=200, button="left", double=True, timestamp=2.0),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    # El primero es CLICK_AT_XY (no resolvió selector). Botón=right.
    assert macro.pasos[0].extra.get("button") == "right"
    assert macro.pasos[0].extra.get("double", False) is False
    # El segundo es doble clic izquierdo (no incluye "button" porque es default)
    assert macro.pasos[1].extra.get("double") is True
    assert "button" not in macro.pasos[1].extra


def test_triple_click_resulta_en_doble_mas_simple(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    tiempos = iter([100.0, 100.1, 100.2])
    monkeypatch.setattr("core.recorder.time.time", lambda: next(tiempos))
    _click_completo(rec, 50, 60)  # → click simple
    _click_completo(rec, 50, 60)  # → marca el anterior como doble
    _click_completo(rec, 50, 60)  # → tercer evento, no se fusiona (anterior ya es doble)
    assert len(rec.eventos_crudos) == 2
    assert rec.eventos_crudos[0].double is True
    assert rec.eventos_crudos[1].double is False
