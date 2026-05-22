"""Tests del módulo core.window_utils.

Cubre las funciones libres `listar_ventanas_visibles` y `asegurar_ventana`
extraídas de Player para que las pueda usar también el diálogo de la
plantilla arranque. Los tests usan mocks de pywinauto para correr en
Linux sin necesidad de Windows.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import window_utils
from core.window_utils import VentanaInfo, asegurar_ventana, listar_ventanas_visibles


# ===== listar_ventanas_visibles =====

def test_listar_sin_pywinauto_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", False)
    assert listar_ventanas_visibles() == []


class _FakeWin:
    def __init__(self, titulo, class_name="TForm", visible=True, handle=1234):
        self._titulo = titulo
        self._class = class_name
        self._visible = visible
        self.handle = handle

    def is_visible(self):
        return self._visible

    def window_text(self):
        return self._titulo

    def class_name(self):
        return self._class


class _FakeDesktop:
    def __init__(self, ventanas):
        self._ventanas = ventanas

    def windows(self):
        return self._ventanas


def test_listar_filtra_invisibles_y_sin_titulo(monkeypatch):
    fakes = [
        _FakeWin("Excel"),
        _FakeWin("", visible=True),         # sin título
        _FakeWin("Notepad", visible=False),  # invisible
        _FakeWin("Chrome"),
    ]
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(fakes))
    monkeypatch.setattr(window_utils, "_get_foreground_handle", lambda: 0)

    out = listar_ventanas_visibles()
    titulos = [v.titulo for v in out]
    assert "Excel" in titulos
    assert "Chrome" in titulos
    assert "" not in titulos
    assert "Notepad" not in titulos


def test_listar_excluye_memovipro(monkeypatch):
    fakes = [
        _FakeWin("MemoviPro — Automatización IT"),
        _FakeWin("memovipro v2"),
        _FakeWin("Excel"),
    ]
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(fakes))
    monkeypatch.setattr(window_utils, "_get_foreground_handle", lambda: 0)
    titulos = [v.titulo for v in listar_ventanas_visibles()]
    assert "Excel" in titulos
    assert all("memovipro" not in t.lower() for t in titulos)


def test_listar_pre_marca_foreground(monkeypatch):
    fakes = [
        _FakeWin("Excel", handle=111),
        _FakeWin("Chrome", handle=222),
        _FakeWin("GERHONTE", handle=333),
    ]
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(fakes))
    monkeypatch.setattr(window_utils, "_get_foreground_handle", lambda: 222)

    out = listar_ventanas_visibles()
    # Chrome es foreground → debe estar primero
    assert out[0].titulo == "Chrome"
    assert out[0].is_foreground is True
    assert all(not v.is_foreground for v in out[1:])


def test_listar_orden_alfabetico_si_no_hay_foreground(monkeypatch):
    fakes = [
        _FakeWin("Zoom"),
        _FakeWin("Acrobat"),
        _FakeWin("Notepad"),
    ]
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(fakes))
    monkeypatch.setattr(window_utils, "_get_foreground_handle", lambda: 0)
    out = [v.titulo for v in listar_ventanas_visibles()]
    assert out == ["Acrobat", "Notepad", "Zoom"]


def test_listar_excluir_propio_false_incluye_memovipro(monkeypatch):
    fakes = [_FakeWin("MemoviPro v1"), _FakeWin("Excel")]
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(fakes))
    monkeypatch.setattr(window_utils, "_get_foreground_handle", lambda: 0)
    titulos = [v.titulo for v in listar_ventanas_visibles(excluir_propio=False)]
    assert "MemoviPro v1" in titulos
    assert "Excel" in titulos


# ===== asegurar_ventana =====

def test_asegurar_sin_pywinauto(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", False)
    ok, msg = asegurar_ventana("Excel")
    assert ok is False
    assert "pywinauto" in msg.lower()


def test_asegurar_sin_titulo():
    ok, msg = asegurar_ventana("")
    assert ok is False
    assert "patrón" in msg.lower() or "titulo" in msg.lower() or "título" in msg.lower()


def test_asegurar_dry_run_no_toca_nada(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    # Si Desktop es llamado en dry-run sería un error: dry-run debe retornar
    # antes de llegar ahí.
    def _no_debe_usarse(backend):
        raise AssertionError("Desktop no debe llamarse en dry-run")
    monkeypatch.setattr(window_utils, "Desktop", _no_debe_usarse)
    ok, msg = asegurar_ventana("Excel", state="maximized", dry_run=True)
    assert ok is True
    assert "dry-run" in msg.lower()


class _FakeWinSpec:
    """Mock de pywinauto WindowSpecification."""

    def __init__(self, titulo, existe=True, minimizada=False, maximizada=False):
        self._titulo = titulo
        self._existe = existe
        self._minimizada = minimizada
        self._maximizada = maximizada
        self.calls = []

    def exists(self, timeout=None):
        self.calls.append(("exists", timeout))
        return self._existe

    def window_text(self):
        return self._titulo

    def is_minimized(self):
        return self._minimizada

    def is_maximized(self):
        return self._maximizada

    def restore(self):
        self.calls.append(("restore",))
        self._minimizada = False
        self._maximizada = False

    def maximize(self):
        self.calls.append(("maximize",))
        self._maximizada = True

    def minimize(self):
        self.calls.append(("minimize",))
        self._minimizada = True

    def set_focus(self):
        self.calls.append(("set_focus",))


class _FakeDesktopWindow:
    def __init__(self, win_spec):
        self._spec = win_spec

    def window(self, title_re):
        self.last_title_re = title_re
        return self._spec


def test_asegurar_encuentra_y_maximiza(monkeypatch):
    spec = _FakeWinSpec("Menú de Turnos y Absentismo (FABPMEN1)")
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktopWindow(spec))

    ok, msg = asegurar_ventana("Menú de Turnos", state="maximized")
    assert ok is True
    assert "Menú de Turnos" in msg
    # Comprueba que pidió maximize + set_focus
    nombres_calls = [c[0] for c in spec.calls]
    assert "maximize" in nombres_calls
    assert "set_focus" in nombres_calls


def test_asegurar_no_encuentra_devuelve_mensaje(monkeypatch):
    spec = _FakeWinSpec("X", existe=False)
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktopWindow(spec))

    ok, msg = asegurar_ventana("GERHONTE", state="maximized")
    assert ok is False
    assert "GERHONTE" in msg
    assert "no se encontr" in msg.lower()


def test_asegurar_minimizada_se_restaura_si_pedimos_maximized(monkeypatch):
    spec = _FakeWinSpec("Excel", minimizada=True, maximizada=False)
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktopWindow(spec))

    ok, _ = asegurar_ventana("Excel", state="maximized")
    assert ok is True
    nombres = [c[0] for c in spec.calls]
    assert "restore" in nombres
    assert "maximize" in nombres


def test_asegurar_state_minimized(monkeypatch):
    spec = _FakeWinSpec("Excel", maximizada=True)
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktopWindow(spec))

    ok, _ = asegurar_ventana("Excel", state="minimized")
    assert ok is True
    nombres = [c[0] for c in spec.calls]
    assert "minimize" in nombres


def test_asegurar_state_normal(monkeypatch):
    spec = _FakeWinSpec("Excel", maximizada=True)
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktopWindow(spec))

    ok, _ = asegurar_ventana("Excel", state="normal")
    assert ok is True
    nombres = [c[0] for c in spec.calls]
    # Estaba maximizada → restore para volver a normal
    assert "restore" in nombres
