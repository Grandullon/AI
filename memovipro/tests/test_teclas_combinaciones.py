"""Combinaciones de teclado: Win+flechas, Alt+F4, AltGr, y el problema de
los modificadores que se quedan "pegados" cuando se pierde una suelta."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import (
    Recorder,
    _construir_send_keys_token,
    _friendly_combo,
    _modifier_for,
    _modifiers_str,
)


# ==================== Win + flechas ====================

def test_win_flecha_arriba():
    """Win+↑ maximiza la ventana. pywinauto no acepta '#' para Win, así
    que hay que bajar/subir la tecla explícitamente."""
    t = _construir_send_keys_token({"win"}, "{UP}")
    assert t == "{VK_LWIN down}{UP}{VK_LWIN up}"
    assert _friendly_combo({"win"}, "{UP}") == "Win+↑"


def test_win_todas_las_flechas():
    for base, flecha in (("{UP}", "↑"), ("{DOWN}", "↓"),
                         ("{LEFT}", "←"), ("{RIGHT}", "→")):
        t = _construir_send_keys_token({"win"}, base)
        assert t.startswith("{VK_LWIN down}") and t.endswith("{VK_LWIN up}")
        assert base in t
        assert _friendly_combo({"win"}, base) == f"Win+{flecha}"


def test_win_shift_flecha_mueve_de_monitor():
    """Win+Mayús+← mueve la ventana al monitor de la izquierda."""
    t = _construir_send_keys_token({"win", "shift"}, "{LEFT}")
    assert t == "{VK_SHIFT down}{VK_LWIN down}{LEFT}{VK_LWIN up}{VK_SHIFT up}"
    # Las bajadas y subidas se cierran en el orden inverso correcto
    assert t.index("{VK_SHIFT down}") < t.index("{VK_LWIN down}")
    assert t.index("{VK_LWIN up}") < t.index("{VK_SHIFT up}")


def test_win_d_escritorio():
    assert _construir_send_keys_token({"win"}, "d") == "{VK_LWIN down}d{VK_LWIN up}"


# ==================== Alt+F4 y compañía ====================

def test_alt_f4():
    assert _construir_send_keys_token({"alt"}, "{F4}") == "%{F4}"
    assert _friendly_combo({"alt"}, "{F4}") == "Alt+F4"


def test_alt_tab_y_ctrl_combos():
    assert _construir_send_keys_token({"alt"}, "{TAB}") == "%{TAB}"
    assert _construir_send_keys_token({"ctrl"}, "a") == "^a"
    assert _construir_send_keys_token({"ctrl", "shift"}, "s") == "^+s"
    assert _construir_send_keys_token({"ctrl", "alt"}, "{DELETE}") == "^%{DELETE}"


def test_ctrl_mas_simbolo_se_escapa():
    """Ctrl++ debe salir como ^{+}: '^+' a secas es Ctrl+Shift sin tecla
    y revienta al reproducir."""
    from core.keyboard_utils import escape_send_keys
    assert _construir_send_keys_token({"ctrl"}, escape_send_keys("+")) == "^{+}"


# ==================== AltGr sigue siendo transparente ====================

def test_altgr_no_es_alt():
    assert _modifier_for("alt_gr") == "altgr"
    assert _modifier_for("alt_l") == "alt"
    assert _modifier_for("cmd") == "win"


def test_altgr_como_atajo_se_expande_a_ctrl_alt():
    """Si AltGr llega a formar parte de un atajo, Windows lo entiende
    como Ctrl+Alt."""
    assert _modifiers_str({"altgr"}) == "ctrl+alt"


# ==================== teclas especiales que antes se perdían ====================

class _TeclaEspecial:
    """Imita cómo pynput imprime una tecla especial: 'Key.insert'."""
    def __init__(self, nombre):
        self.nombre = nombre

    def __str__(self):
        return f"Key.{self.nombre}"


def test_teclas_especiales_mapeadas():
    """Antes se descartaban en silencio: la macro salía incompleta sin
    decir por qué."""
    esperado = {
        "insert": "{INSERT}", "menu": "{VK_APPS}", "apps": "{VK_APPS}",
        "print_screen": "{PRTSC}", "caps_lock": "{CAPSLOCK}",
        "num_lock": "{VK_NUMLOCK}", "scroll_lock": "{VK_SCROLL}",
        "pause": "{BREAK}",
    }
    for nombre, token in esperado.items():
        assert Recorder._tecla_a_send_keys(_TeclaEspecial(nombre)) == token


def test_teclas_de_siempre_siguen_igual():
    """Las que ya funcionaban no cambian (macros existentes intactas)."""
    for nombre, token in (("enter", "{ENTER}"), ("tab", "{TAB}"),
                          ("esc", "{ESC}"), ("up", "{UP}"),
                          ("page_down", "{PGDN}"), ("delete", "{DELETE}")):
        assert Recorder._tecla_a_send_keys(_TeclaEspecial(nombre)) == token


def test_espacio_como_atajo_no_es_un_espacio_suelto():
    """Ctrl+Espacio debe ser '^{SPACE}', no '^ ' (que no significa nada)."""
    assert Recorder._tecla_a_send_keys(_TeclaEspecial("space")) == "{SPACE}"
    assert _construir_send_keys_token({"ctrl"}, "{SPACE}") == "^{SPACE}"


def test_teclas_de_funcion_altas():
    for n in (1, 4, 5, 12):
        assert Recorder._tecla_a_send_keys(_TeclaEspecial(f"f{n}")) == "{F%d}" % n


def test_tecla_desconocida_sigue_devolviendo_none():
    assert Recorder._tecla_a_send_keys(_TeclaEspecial("media_play_pause")) is None


# ==================== modificadores "pegados" ====================

def test_modificadores_pegados_se_descartan(monkeypatch):
    """Si Windows dice que Alt ya no está pulsado, no debe seguir
    convirtiendo todo lo que se teclea en atajos."""
    import core.recorder as rec

    r = Recorder.__new__(Recorder)
    import threading
    r._lock = threading.Lock()
    r._grabando = True
    r._modifiers = {"alt", "ctrl"}
    r._buf = rec._BufferTexto()
    r.eventos_crudos = []

    # El sistema dice que solo sigue pulsado Ctrl
    monkeypatch.setattr(rec, "_modificadores_realmente_pulsados", lambda: {"ctrl"})
    r._on_press_impl(_TeclaFalsa("a"))
    assert r._modifiers == {"ctrl"}      # el Alt fantasma desapareció
    # Y se grabó Ctrl+A, no Ctrl+Alt+A
    assert r.eventos_crudos[-1].valor == "^a"


def test_sin_windows_se_respeta_el_estado_propio(monkeypatch):
    """Fuera de Windows (o si la consulta falla) no se toca nada."""
    import core.recorder as rec
    import threading

    r = Recorder.__new__(Recorder)
    r._lock = threading.Lock()
    r._grabando = True
    r._modifiers = {"alt"}
    r._buf = rec._BufferTexto()
    r.eventos_crudos = []
    monkeypatch.setattr(rec, "_modificadores_realmente_pulsados", lambda: None)
    r._on_press_impl(_TeclaFalsa("a"))
    assert r._modifiers == {"alt"}
    assert r.eventos_crudos[-1].valor == "%a"


def test_nunca_se_anaden_modificadores_que_no_vimos(monkeypatch):
    """Solo QUITAMOS modificadores fantasma; añadir los que el enganche no
    vio cambiaría el comportamiento cuando todo funciona bien."""
    import core.recorder as rec
    import threading

    r = Recorder.__new__(Recorder)
    r._lock = threading.Lock()
    r._grabando = True
    r._modifiers = set()
    r._buf = rec._BufferTexto()
    r.eventos_crudos = []
    monkeypatch.setattr(rec, "_modificadores_realmente_pulsados",
                        lambda: {"ctrl", "alt", "win"})
    r._on_press_impl(_TeclaFalsa("a"))
    assert r._modifiers == set()
    assert r._buf.texto == "a"           # texto normal, no un atajo


class _TeclaFalsa:
    def __init__(self, char):
        self.char = char

    def __str__(self):
        return f"'{self.char}'"


# ==================== no dejar teclas hundidas al reproducir ====================

def test_atajo_fallido_suelta_la_tecla_windows(monkeypatch):
    """Si Win+↑ revienta a medias, Win se queda hundida y a partir de ahí
    cada letra es un atajo del sistema."""
    import core.player as pl
    from core.player import Player

    enviados = []

    class _FakeKb:
        @staticmethod
        def send_keys(t):
            enviados.append(t)
            if t == "{VK_LWIN down}{UP}{VK_LWIN up}":
                raise RuntimeError("la ventana desapareció")

    monkeypatch.setattr(pl, "pwkeyboard", _FakeKb)
    p = Player.__new__(Player)
    try:
        Player._send_keys_seguro(p, "{VK_LWIN down}{UP}{VK_LWIN up}")
        assert False, "debería propagar el fallo"
    except RuntimeError:
        pass
    # Tras el fallo: tecla neutra (para no abrir Inicio) y suelta de Win
    assert "{VK_F13}" in enviados
    assert "{VK_LWIN up}" in enviados


def test_atajo_correcto_no_suelta_nada_de_mas(monkeypatch):
    import core.player as pl
    from core.player import Player

    enviados = []
    monkeypatch.setattr(pl, "pwkeyboard",
                        type("K", (), {"send_keys": staticmethod(enviados.append)}))
    p = Player.__new__(Player)
    Player._send_keys_seguro(p, "%{F4}")
    assert enviados == ["%{F4}"]


def test_atajo_sin_modificadores_colgables_no_intenta_soltar(monkeypatch):
    """Un token que falla pero no baja ninguna tecla no necesita rescate."""
    import core.player as pl
    from core.player import Player

    enviados = []

    class _FakeKb:
        @staticmethod
        def send_keys(t):
            enviados.append(t)
            raise RuntimeError("boom")

    monkeypatch.setattr(pl, "pwkeyboard", _FakeKb)
    p = Player.__new__(Player)
    try:
        Player._send_keys_seguro(p, "^a")
    except RuntimeError:
        pass
    assert enviados == ["^a"]
