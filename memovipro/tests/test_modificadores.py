"""Tests para captura/reproducción de modificadores (Ctrl/Shift/Alt).

Cubre el bug reportado por el usuario: "intento grabar Ctrl+Click para
selección múltiple y no lo reproduce". También verifica que los atajos
de teclado (Ctrl+A, Ctrl+S, Alt+F4...) se graben como send_keys con la
combinación correcta y no como letras sueltas en el buffer de texto.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import (
    EventoCrudo,
    Recorder,
    _modifier_for,
    _modifiers_sendkeys_prefix,
    _modifiers_str,
)
from core.step_model import Step, StepType


def test_modifier_for_normaliza_variantes():
    assert _modifier_for("ctrl") == "ctrl"
    assert _modifier_for("ctrl_l") == "ctrl"
    assert _modifier_for("ctrl_r") == "ctrl"
    assert _modifier_for("shift") == "shift"
    assert _modifier_for("alt") == "alt"
    assert _modifier_for("alt_gr") == "alt"
    assert _modifier_for("a") is None
    assert _modifier_for("enter") is None


def test_modifiers_sendkeys_prefix():
    assert _modifiers_sendkeys_prefix(set()) == ""
    assert _modifiers_sendkeys_prefix({"ctrl"}) == "^"
    assert _modifiers_sendkeys_prefix({"shift"}) == "+"
    assert _modifiers_sendkeys_prefix({"alt"}) == "%"
    assert _modifiers_sendkeys_prefix({"ctrl", "shift"}) == "^+"
    assert _modifiers_sendkeys_prefix({"ctrl", "alt"}) == "^%"


def test_modifiers_str_orden_estable():
    assert _modifiers_str({"shift", "ctrl"}) == "ctrl+shift"
    assert _modifiers_str({"alt"}) == "alt"
    assert _modifiers_str(set()) == ""


def _set_time(monkeypatch, valores):
    it = iter(valores)
    monkeypatch.setattr("core.recorder.time.time", lambda: next(it))


class _FakeCtrlKey:
    def __init__(self, name): self._n = name
    def __str__(self): return f"Key.{self._n}"
    char = None  # como pynput para teclas especiales


class _FakeChar:
    def __init__(self, char):
        self.char = char
    def __str__(self):
        return f"'{self.char}'"


def _click_completo(rec, x, y, button="Button.left"):
    rec._on_click(x, y, button, True)
    rec._on_click(x, y, button, False)


def test_ctrl_click_se_etiqueta_con_modifier(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])

    rec._on_press(_FakeCtrlKey("ctrl"))
    _click_completo(rec, 50, 60)

    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "click"
    assert evt.modifiers == "ctrl"


def test_ctrl_release_quita_modifier(monkeypatch):
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.2])

    rec._on_press(_FakeCtrlKey("ctrl"))
    _click_completo(rec, 50, 60)
    rec._on_release(_FakeCtrlKey("ctrl"))
    _click_completo(rec, 70, 80)

    assert rec.eventos_crudos[0].modifiers == "ctrl"
    assert rec.eventos_crudos[1].modifiers == ""


def test_ctrl_a_se_graba_como_atajo_no_como_texto(monkeypatch):
    """Ctrl+A no debe acumularse en el buffer como letra 'a'."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.05, 100.1])

    rec._on_press(_FakeCtrlKey("ctrl"))
    rec._on_press(_FakeChar("a"))
    rec._on_release(_FakeCtrlKey("ctrl"))

    assert len(rec.eventos_crudos) == 1
    assert rec.eventos_crudos[0].tipo == "send_keys"
    assert rec.eventos_crudos[0].valor == "^a"


def test_shift_a_va_al_buffer_de_texto(monkeypatch):
    """Shift+A es texto en mayúscula, NO un atajo."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.05, 100.06])

    rec._on_press(_FakeCtrlKey("shift"))
    rec._on_press(_FakeChar("A"))
    rec._on_release(_FakeCtrlKey("shift"))
    # Buffer debe seguir abierto (no se ha emitido aún)
    assert rec.eventos_crudos == []
    assert rec._buf.texto == "A"


def test_ctrl_click_no_se_funde_con_click_normal_como_doble(monkeypatch):
    """Ctrl+Click seguido de Click normal son DOS clicks, no un doble click."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.2])

    rec._on_press(_FakeCtrlKey("ctrl"))
    _click_completo(rec, 50, 60)
    rec._on_release(_FakeCtrlKey("ctrl"))
    _click_completo(rec, 50, 60)

    assert len(rec.eventos_crudos) == 2
    assert all(not e.double for e in rec.eventos_crudos)
    assert rec.eventos_crudos[0].modifiers == "ctrl"
    assert rec.eventos_crudos[1].modifiers == ""


def test_multiples_ctrl_click_consecutivos(monkeypatch):
    """30 Ctrl+Click consecutivos: el caso real del usuario."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0 + i * 0.6 for i in range(30)])

    rec._on_press(_FakeCtrlKey("ctrl"))
    for i in range(30):
        _click_completo(rec, 100, 200 + i * 20)
    rec._on_release(_FakeCtrlKey("ctrl"))

    assert len(rec.eventos_crudos) == 30
    for e in rec.eventos_crudos:
        assert e.modifiers == "ctrl"
        assert e.double is False


def test_construir_macro_pasa_modifiers_a_extra():
    eventos = [
        EventoCrudo(tipo="click", x=10, y=20, modifiers="ctrl", timestamp=1.0),
        EventoCrudo(tipo="click", x=100, y=200, modifiers="ctrl+shift", timestamp=2.0),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert macro.pasos[0].extra.get("modifiers") == "ctrl"
    assert macro.pasos[1].extra.get("modifiers") == "ctrl+shift"


def test_player_target_modifiers_lee_extra():
    from core.player import Player
    s = Step(tipo=StepType.CLICK_AT_XY, extra={"x": 0, "y": 0, "modifiers": "ctrl+shift"})
    assert Player._target_modifiers(s) == {"ctrl", "shift"}
    s2 = Step(tipo=StepType.CLICK_AT_XY, extra={"x": 0, "y": 0})
    assert Player._target_modifiers(s2) == set()


def test_player_metodo_adjust_modifiers_existe():
    """Verificación estática: el player implementa la lógica de mantener
    modificadores entre pasos."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._adjust_modifiers)
    assert "VK_CONTROL" in src or "_MOD_VK" in src
    assert "self._modifiers_held" in src
    # Si ya están pulsados los target, no debe rehacerlo:
    assert "target == self._modifiers_held" in src
