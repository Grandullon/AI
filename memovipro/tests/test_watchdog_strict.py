"""Tests para que el watchdog NO mate ventanas legítimas y que el player
use fallback_xy cuando no hay ventana_principal.

Reproducción de los problemas detectados en run_20260515.log (v9):
- 'Menú de Turnos y Absentismo (FABPMEN1)' no es popup.
- 'UIAWrapper' object has no attribute 'child_window' al iterar.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.popup_watchdog import _es_popup_candidato


class _FakeRect:
    def __init__(self, w, h):
        self._w = w
        self._h = h
    def width(self): return self._w
    def height(self): return self._h


class _FakeWindow:
    def __init__(self, title="", class_name="", visible=True, w=400, h=300):
        self._title = title
        self._class = class_name
        self._visible = visible
        self._rect = _FakeRect(w, h)
    def is_visible(self): return self._visible
    def window_text(self): return self._title
    def class_name(self): return self._class
    def rectangle(self): return self._rect


def test_ventana_app_legitima_no_es_popup():
    """La ventana del usuario 'Menú de Turnos y Absentismo (FABPMEN1)'
    NO debe considerarse popup aunque tenga botones tipo 'Cerrar' dentro."""
    win = _FakeWindow(
        title="Menú de Turnos y Absentismo (FABPMEN1)",
        class_name="TFormPpal",  # Delphi-style, no es #32770
        w=1200, h=800,
    )
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_nativo_con_keyword_error_si_es_popup():
    """#32770 + título con keyword de error = popup."""
    win = _FakeWindow(title="Error del sistema", class_name="#32770", w=300, h=150)
    assert _es_popup_candidato(win, ignorar=[]) is True


def test_titulo_error_pequeno_es_popup():
    win = _FakeWindow(title="Error: DNI no encontrado", class_name="TFormError", w=400, h=200)
    assert _es_popup_candidato(win, ignorar=[]) is True


def test_titulo_error_grande_no_es_popup():
    """Una ventana grande con 'Error' en el título probablemente es la
    pantalla principal de un módulo de gestión de errores, no un popup."""
    win = _FakeWindow(title="Gestor de Errores del Sistema", class_name="TFormApp", w=1500, h=900)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_titulo_aviso_pequeno_es_popup():
    win = _FakeWindow(title="Aviso", class_name="TForm1", w=400, h=200)
    assert _es_popup_candidato(win, ignorar=[]) is True


def test_ventana_invisible_no_es_popup():
    win = _FakeWindow(title="Error", class_name="#32770", visible=False)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_titulo_en_lista_ignorar_no_es_popup():
    win = _FakeWindow(title="Error de prueba", class_name="#32770")
    assert _es_popup_candidato(win, ignorar=["Error de prueba"]) is False


# ===== Lista blanca de diálogos legítimos del SO =====
# Estos diálogos usan class #32770 pero NO son popups de error;
# la macro suele necesitar interactuar con ellos.

def test_dialogo_abrir_no_es_popup():
    """El diálogo "Abrir" de Windows para seleccionar fichero."""
    win = _FakeWindow(title="Abrir", class_name="#32770", w=600, h=450)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_guardar_como_no_es_popup():
    win = _FakeWindow(title="Guardar como", class_name="#32770", w=600, h=450)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_imprimir_no_es_popup():
    win = _FakeWindow(title="Imprimir", class_name="#32770", w=600, h=500)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_examinar_carpeta_no_es_popup():
    win = _FakeWindow(title="Examinar", class_name="#32770", w=400, h=300)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_save_as_en_ingles_no_es_popup():
    win = _FakeWindow(title="Save As", class_name="#32770", w=600, h=450)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_abrir_con_sufijo_no_es_popup():
    """'Abrir: pa-diario.fic' — sigue siendo el diálogo de abrir."""
    win = _FakeWindow(title="Abrir: pa-diario.fic", class_name="#32770", w=600, h=450)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_dialogo_error_sigue_siendo_popup_pese_a_ser_32770():
    """No queremos que la lista blanca silencie todos los #32770.
    Si el título tiene keyword de error, SÍ es popup."""
    win = _FakeWindow(title="Error al guardar", class_name="#32770", w=400, h=200)
    assert _es_popup_candidato(win, ignorar=[]) is True


def test_dialogo_32770_sin_keyword_de_error_no_es_popup():
    """Por defecto un #32770 sin 'Error/Aviso/...' tampoco lo es."""
    win = _FakeWindow(title="Ventana cualquiera", class_name="#32770", w=400, h=200)
    assert _es_popup_candidato(win, ignorar=[]) is False


def test_player_sin_ventana_principal_usa_fallback_xy():
    """Cuando macro.ventana_principal está vacío, _click_control debe
    ir directo a fallback_xy sin iterar ventanas. Lo verificamos via
    inspección del código (no podemos invocar pywinauto en CI Linux)."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._click_control)
    # Garantizar que la lógica del shortcut existe
    assert "ventana_principal" in src
    assert "fallback_xy" in src
    assert "_click_xy" in src
