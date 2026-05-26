"""Tests de la verificación post-paso y el helper existe_ventana."""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import window_utils
from core.step_model import Macro, Step, StepType, render_step


# ===== Serialización de verificar_ventana =====

def test_step_serializa_verificar_ventana(tmp_path):
    paso = Step(
        tipo=StepType.CLICK_AT_XY,
        extra={"x": 1, "y": 2},
        verificar_ventana="INFORMES",
        verificar_timeout_s=15.0,
    )
    macro = Macro(nombre="m", pasos=[paso])
    path = tmp_path / "m.yaml"
    macro.save(path)
    cargada = Macro.load(path)
    assert cargada.pasos[0].verificar_ventana == "INFORMES"
    assert cargada.pasos[0].verificar_timeout_s == 15.0


def test_step_no_serializa_verificar_si_vacio(tmp_path):
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 2})
    macro = Macro(nombre="m", pasos=[paso])
    path = tmp_path / "m.yaml"
    macro.save(path)
    yaml_text = path.read_text(encoding="utf-8")
    assert "verificar_ventana" not in yaml_text


def test_render_step_sustituye_placeholder_en_verificar():
    paso = Step(
        tipo=StepType.CLICK_AT_XY,
        extra={"x": 1, "y": 2},
        verificar_ventana="Ficha {DNI}",
    )
    out = render_step(paso, {"DNI": "12345678A"})
    assert out.verificar_ventana == "Ficha 12345678A"


# ===== existe_ventana =====

def test_existe_ventana_sin_pywinauto(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", False)
    assert window_utils.existe_ventana("Excel") is False


def test_existe_ventana_titulo_vacio():
    assert window_utils.existe_ventana("") is False


class _FakeWinSpec:
    def __init__(self, existe):
        self._existe = existe
    def exists(self, timeout=None):
        return self._existe


class _FakeDesktop:
    def __init__(self, existe):
        self._existe = existe
    def window(self, title_re):
        return _FakeWinSpec(self._existe)


def test_existe_ventana_true(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(True))
    assert window_utils.existe_ventana("INFORMES") is True


def test_existe_ventana_false(monkeypatch):
    monkeypatch.setattr(window_utils, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(window_utils, "Desktop", lambda backend: _FakeDesktop(False))
    assert window_utils.existe_ventana("NoExiste") is False


# ===== Player._esperar_aparezca_ventana =====

def test_esperar_aparezca_ventana_dry_run():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = True
    p._abort = threading.Event()
    # En dry-run devuelve True sin tocar pywinauto
    assert Player._esperar_aparezca_ventana(p, "INFORMES", 5.0) is True


def test_esperar_aparezca_ventana_aparece(monkeypatch):
    from core.player import Player
    import core.window_utils as wu
    monkeypatch.setattr(wu, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.3: True)

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()
    assert Player._esperar_aparezca_ventana(p, "INFORMES", 2.0) is True


def test_esperar_aparezca_ventana_no_aparece(monkeypatch):
    from core.player import Player
    import core.window_utils as wu
    monkeypatch.setattr(wu, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.3: False)

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()
    # timeout corto para que el test sea rápido
    assert Player._esperar_aparezca_ventana(p, "NoExiste", 0.6) is False


def test_esperar_aparezca_ventana_abort_corta(monkeypatch):
    from core.player import Player
    import core.window_utils as wu
    monkeypatch.setattr(wu, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.3: False)

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()
    p._abort.set()  # ya abortado
    assert Player._esperar_aparezca_ventana(p, "X", 10.0) is False


def test_player_loop_verifica_post_paso():
    """Inspección estática: el loop comprueba verificar_ventana."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player.ejecutar_dni)
    assert "verificar_ventana" in src
    assert "_esperar_aparezca_ventana" in src
