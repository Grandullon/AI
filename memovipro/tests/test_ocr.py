"""Tests del módulo OCR (con pytesseract mockeado) y su integración
en el watchdog (PopupEvent.texto_ocr → Incidencia.texto_popup)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import ocr as ocr_mod


def test_disponible_sin_pytesseract(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", False)
    assert ocr_mod.disponible() is False


def test_ocr_imagen_sin_pytesseract(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", False)
    assert ocr_mod.ocr_imagen("cualquier.png") == ""


def test_ocr_imagen_normaliza_espacios(monkeypatch):
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        @staticmethod
        def image_to_string(img, lang=None):
            return "Error:\n\n  DNI   no    encontrado\n"

    class _FakeImage:
        @staticmethod
        def open(p):
            return object()  # objeto dummy

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", _FakeImage)

    out = ocr_mod.ocr_imagen("popup.png")
    assert out == "Error: DNI no encontrado"


def test_ocr_imagen_reintenta_sin_idioma(monkeypatch):
    """Si el idioma 'spa+eng' falla (no instalado), reintenta sin idioma."""
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    llamadas = []

    class _FakePT:
        @staticmethod
        def image_to_string(img, lang=None):
            llamadas.append(lang)
            if lang is not None:
                raise RuntimeError("idioma 'spa' no instalado")
            return "texto recuperado"

    class _FakeImage:
        @staticmethod
        def open(p):
            return object()

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", _FakeImage)

    out = ocr_mod.ocr_imagen("popup.png", idioma="spa+eng")
    assert out == "texto recuperado"
    # Primer intento con idioma, segundo sin
    assert llamadas == ["spa+eng", None]


def test_registrar_popup_combina_texto_y_ocr():
    """El Player combina texto accesible + OCR en la incidencia."""
    from core.player import Player
    from core.popup_watchdog import PopupEvent
    from core.step_model import Step, StepType

    registradas = []

    class _FakeLogger:
        def append(self, inc):
            registradas.append(inc)
            return 1

    p = Player.__new__(Player)
    p.macro = type("M", (), {"nombre": "m"})()
    p.logger = _FakeLogger()

    paso = Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 1})

    # Caso 1: hay texto accesible Y ocr → se combinan
    evt = PopupEvent(titulo="Error", texto="Aviso", class_name="#32770",
                     screenshot_path="x.png", texto_ocr="DNI no encontrado")
    inc = Player._registrar_popup(p, "iter_1", 3, paso, evt)
    assert "Aviso" in inc.texto_popup
    assert "OCR: DNI no encontrado" in inc.texto_popup

    # Caso 2: solo OCR (UIA no dio texto)
    evt2 = PopupEvent(titulo="Error", texto="", class_name="#32770",
                      screenshot_path="x.png", texto_ocr="Sin permisos")
    inc2 = Player._registrar_popup(p, "iter_1", 3, paso, evt2)
    assert "OCR: Sin permisos" in inc2.texto_popup


def test_watchdog_helper_ocr_sin_disponible(monkeypatch):
    import core.popup_watchdog as wd
    # _ocr_screenshot debe devolver "" si OCR no está disponible
    monkeypatch.setattr("core.ocr.disponible", lambda: False)
    assert wd._ocr_screenshot("x.png") == ""
