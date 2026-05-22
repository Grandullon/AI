"""Tests para soporte de la tecla Win y del nuevo StepType.LAUNCH_PROGRAM.

User pidió: "voy a utilizar las combinaciones de Windows: Win+D,
Win+flecha para maximizar, Win+número para abrir apps. Adapta el código
para que pueda captar todas esas cosas".
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import (
    EventoCrudo,
    Recorder,
    _construir_send_keys_token,
    _friendly_combo,
    _modifier_for,
    _modifiers_str,
)
from core.step_model import Macro, Step, StepType


# ===== _modifier_for reconoce Win =====

def test_modifier_for_reconoce_cmd():
    assert _modifier_for("cmd") == "win"
    assert _modifier_for("cmd_l") == "win"
    assert _modifier_for("cmd_r") == "win"


def test_modifier_for_reconoce_win():
    assert _modifier_for("win") == "win"
    assert _modifier_for("win_l") == "win"


def test_modifier_for_mantiene_otros():
    assert _modifier_for("ctrl") == "ctrl"
    assert _modifier_for("shift") == "shift"
    assert _modifier_for("alt") == "alt"
    assert _modifier_for("a") is None


# ===== _construir_send_keys_token =====

def test_token_solo_letra_sin_mods():
    assert _construir_send_keys_token(set(), "a") == "a"


def test_token_ctrl_a_usa_prefijo_estandar():
    assert _construir_send_keys_token({"ctrl"}, "a") == "^a"


def test_token_ctrl_shift_s_usa_prefijo_combinado():
    assert _construir_send_keys_token({"ctrl", "shift"}, "s") == "^+s"


def test_token_win_d_usa_vk_lwin():
    """Win+D no se puede expresar con prefijo SendKeys, requiere VK_LWIN."""
    out = _construir_send_keys_token({"win"}, "d")
    assert out == "{VK_LWIN down}d{VK_LWIN up}"


def test_token_win_arriba_usa_vk_lwin_y_arrow():
    out = _construir_send_keys_token({"win"}, "{UP}")
    assert out == "{VK_LWIN down}{UP}{VK_LWIN up}"


def test_token_win_numero():
    """Win+1 — para abrir la primera app fijada en la taskbar."""
    out = _construir_send_keys_token({"win"}, "1")
    assert out == "{VK_LWIN down}1{VK_LWIN up}"


def test_token_win_ctrl_d_combina_correctamente():
    """Si hay Win + Ctrl, ambos van en formato verbose envolviendo la tecla."""
    out = _construir_send_keys_token({"win", "ctrl"}, "d")
    # Orden: Ctrl envuelve por fuera, Win por dentro (o viceversa);
    # mientras down/up estén bien balanceados es válido.
    assert "{VK_CONTROL down}" in out
    assert "{VK_LWIN down}" in out
    assert "d" in out
    assert out.endswith("{VK_CONTROL up}") or out.endswith("{VK_LWIN up}")


# ===== _friendly_combo =====

def test_friendly_win_d():
    assert _friendly_combo({"win"}, "d") == "Win+D"


def test_friendly_ctrl_shift_s():
    assert _friendly_combo({"ctrl", "shift"}, "s") == "Ctrl+Shift+S"


def test_friendly_win_arrow_up():
    assert _friendly_combo({"win"}, "{UP}") == "Win+↑"


def test_friendly_alt_f4():
    assert _friendly_combo({"alt"}, "{F4}") == "Alt+F4"


# ===== Recorder captura Win + tecla =====

class _FakeKey:
    def __init__(self, n): self._n = n
    def __str__(self): return f"Key.{self._n}"
    char = None


class _FakeChar:
    def __init__(self, c):
        self.char = c
    def __str__(self):
        return f"'{self.char}'"


def _set_time(monkeypatch, valores):
    it = iter(valores)
    monkeypatch.setattr("core.recorder.time.time", lambda: next(it))


def test_recorder_captura_win_d(monkeypatch):
    """Win+D debe grabarse como send_keys con la sintaxis VK_LWIN, NO
    como un type_text de la letra 'd'."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0, 100.1])

    rec._on_press(_FakeKey("cmd"))  # pynput entrega cmd para la tecla Win
    rec._on_press(_FakeChar("d"))
    rec._on_release(_FakeKey("cmd"))

    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "send_keys"
    assert evt.valor == "{VK_LWIN down}d{VK_LWIN up}"
    assert evt.descripcion == "Tecla Win+D"


def test_recorder_captura_win_flecha_arriba(monkeypatch):
    """Win+Up (maximizar ventana actual)."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])

    rec._on_press(_FakeKey("cmd"))
    rec._on_press(_FakeKey("up"))
    rec._on_release(_FakeKey("cmd"))

    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "send_keys"
    assert evt.valor == "{VK_LWIN down}{UP}{VK_LWIN up}"


def test_recorder_captura_win_1(monkeypatch):
    """Win+1 (abrir primera app de la taskbar)."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])

    rec._on_press(_FakeKey("cmd"))
    rec._on_press(_FakeChar("1"))
    rec._on_release(_FakeKey("cmd"))

    assert len(rec.eventos_crudos) == 1
    assert rec.eventos_crudos[0].valor == "{VK_LWIN down}1{VK_LWIN up}"


def test_recorder_d_sin_win_va_al_buffer_de_texto(monkeypatch):
    """Sin Win pulsado, 'd' debe ir al buffer (texto), NO como atajo."""
    rec = Recorder()
    rec._grabando = True
    _set_time(monkeypatch, [100.0])
    rec._on_press(_FakeChar("d"))
    assert rec.eventos_crudos == []
    assert rec._buf.texto == "d"


def test_modifiers_str_incluye_win():
    assert _modifiers_str({"win"}) == "win"
    assert _modifiers_str({"win", "ctrl"}) == "ctrl+win"


# ===== LAUNCH_PROGRAM step =====

def test_launch_program_es_un_step_type():
    s = Step(tipo=StepType.LAUNCH_PROGRAM, valor=r"C:\Apps\gerhonte.exe")
    d = s.to_dict()
    assert d["tipo"] == "launch_program"
    assert d["valor"] == r"C:\Apps\gerhonte.exe"
    s2 = Step.from_dict(d)
    assert s2.tipo == StepType.LAUNCH_PROGRAM
    assert s2.valor == r"C:\Apps\gerhonte.exe"


def test_launch_program_serializa_con_args(tmp_path):
    s = Step(
        tipo=StepType.LAUNCH_PROGRAM,
        valor="notepad.exe",
        extra={"args": ["C:/tmp/file.txt"]},
    )
    m = Macro(nombre="t", pasos=[s])
    path = tmp_path / "m.yaml"
    m.save(path)
    cargada = Macro.load(path)
    assert cargada.pasos[0].tipo == StepType.LAUNCH_PROGRAM
    assert cargada.pasos[0].extra["args"] == ["C:/tmp/file.txt"]


def test_player_implementa_launch_program():
    """Inspección estática: el player debe manejar el step type."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player)
    assert "LAUNCH_PROGRAM" in src
    assert "_launch_program" in src
    assert "os.startfile" in src or "startfile" in src
    assert "subprocess.Popen" in src or "Popen" in src
