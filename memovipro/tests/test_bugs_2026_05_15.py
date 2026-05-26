"""Tests que reproducen los 3 bugs detectados en el .exe del 2026-05-15.

1. PopupWatchdog: self._stop pisaba Thread._stop() → join() petaba.
2. capturar_pantalla_completa: API mss mal usada (sct.grab()[:] inválido).
3. construir_macro: los click_control deben incluir fallback_xy.
"""
import threading
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.popup_watchdog import PopupWatchdog
from core.recorder import EventoCrudo, Recorder, Selector
from core.step_model import StepType


def test_popup_watchdog_stop_y_join_no_petan(tmp_path):
    """Bug 1: si self._stop = Event(), join() lanza 'Event' object is not callable."""
    wd = PopupWatchdog(screenshots_dir=tmp_path, on_popup=lambda evt: None, polling_ms=50)
    # Verificar que el atributo NO pisa el método interno de Thread.
    assert not isinstance(getattr(wd, "_stop", None), threading.Event), \
        "self._stop no debe ser un Event (pisaría Thread._stop)"
    # start + stop + join debe ir limpio.
    wd.start()
    wd.stop()
    wd.join(timeout=2.0)
    assert not wd.is_alive()


def test_screenshot_no_subscriptable_error(tmp_path):
    """Bug 2: 'ScreenShot' object is not subscriptable.

    No queremos hacer una captura real (no hay display en CI), pero sí
    queremos que la función no lance TypeError aunque mss falle: debe
    devolver None silenciosamente.
    """
    from core.screenshot import capturar_pantalla_completa
    out = capturar_pantalla_completa(tmp_path, prefijo="test")
    # Sin display en Linux es None; con display sería un Path. Lo importante
    # es que NO lance TypeError.
    assert out is None or out.exists()


def test_construir_macro_guarda_fallback_xy_en_click_control():
    """Bug 3 (no era un crash, era falta de robustez): los click_control
    deben llevar siempre fallback_xy con las coordenadas originales.
    """
    eventos = [
        EventoCrudo(tipo="click", x=123, y=456, timestamp=100.0),
    ]
    # Forzamos selector ficticio sustituyendo _selector_desde_punto temporalmente.
    import core.recorder as rec_mod
    original = rec_mod._selector_desde_punto

    def fake(x, y):
        return Selector(control_type="Button", name="OK"), "OK", None

    rec_mod._selector_desde_punto = fake
    try:
        macro = Recorder.construir_macro(eventos, resolver_selectores=True)
    finally:
        rec_mod._selector_desde_punto = original

    assert macro.pasos[0].tipo == StepType.CLICK_CONTROL
    assert macro.pasos[0].extra.get("fallback_xy") == [123, 456]


def test_step_serializa_fallback_xy(tmp_path):
    from core.step_model import Macro, Selector, Step

    macro = Macro(nombre="m", pasos=[
        Step(
            tipo=StepType.CLICK_CONTROL,
            selector=Selector(control_type="Button", name="OK"),
            extra={"fallback_xy": [100, 200]},
        ),
    ])
    path = tmp_path / "m.yaml"
    macro.save(path)
    cargada = Macro.load(path)
    assert cargada.pasos[0].extra["fallback_xy"] == [100, 200]
