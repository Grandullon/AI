"""Tests de la Tanda 3 (pulido) de la auditoría de captura.

B7 — Win como modificador de clic (antes se perdía en el replay)
B6 — suelo mínimo entre pasos a velocidad 0 (no fundir clics en doble clic)
B4 — scroll horizontal separado del vertical + errores propagados
B5 — drag con puntos intermedios
A9 — timestamp del type_text = primer carácter (delay correcto)
A14 — _flush_text sin el parámetro muerto force
Checkpoint — fusión cross-process + reset preserva fingerprint
DPI — set_dpi_awareness existe y es no-op seguro fuera de Windows
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ==================== B7: Win modifier ====================

def test_b7_win_en_mod_vk_y_target_modifiers():
    from core.player import Player
    from core.step_model import Step, StepType

    assert Player._MOD_VK.get("win") == "VK_LWIN"
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={"modifiers": "win"})
    assert Player._target_modifiers(paso) == {"win"}
    paso2 = Step(tipo=StepType.CLICK_AT_XY, extra={"modifiers": "ctrl+win"})
    assert Player._target_modifiers(paso2) == {"ctrl", "win"}


# ==================== B6: suelo mínimo a velocidad 0 ====================

def test_b6_velocidad_cero_con_delay_duerme_suelo(monkeypatch):
    import threading
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.velocidad = 0.0
    p._abort = threading.Event()

    dormido = {"s": 0.0}
    monkeypatch.setattr("core.player.time.sleep", lambda s: dormido.__setitem__("s", s))

    paso = Step(tipo=StepType.CLICK_AT_XY, delay_before_s=1.5)
    Player._esperar_delay(p, paso)
    assert dormido["s"] == Player._SUELO_MIN_S  # suelo, no 1.5s ni 0


def test_b6_velocidad_cero_sin_delay_no_duerme(monkeypatch):
    import threading
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.velocidad = 0.0
    p._abort = threading.Event()
    llamado = {"n": 0}
    monkeypatch.setattr("core.player.time.sleep", lambda s: llamado.__setitem__("n", llamado["n"] + 1))

    paso = Step(tipo=StepType.CLICK_AT_XY, delay_before_s=0.0)
    Player._esperar_delay(p, paso)
    assert llamado["n"] == 0  # sin delay grabado → 0 pausa


# ==================== B4: scroll horizontal ====================

def test_b4_scroll_separa_ejes(monkeypatch):
    import threading
    from core.player import Player
    from core.step_model import Step

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()

    llamadas = {"vert": [], "horiz": []}
    monkeypatch.setattr(p, "_scroll_horizontal",
                        lambda x, y, dx: llamadas["horiz"].append((x, y, dx)))

    import types
    fake_mouse = types.SimpleNamespace(
        scroll=lambda coords, wheel_dist: llamadas["vert"].append((coords, wheel_dist))
    )
    monkeypatch.setitem(sys.modules, "pywinauto", types.SimpleNamespace(mouse=fake_mouse))

    # Solo vertical
    Player._scroll_xy(p, 10, 20, 0, 3)
    assert llamadas["vert"] == [((10, 20), 3)]
    assert llamadas["horiz"] == []

    # Solo horizontal → NO debe ir a la rueda vertical
    Player._scroll_xy(p, 5, 6, -2, 0)
    assert llamadas["vert"] == [((10, 20), 3)]  # sin cambios
    assert llamadas["horiz"] == [(5, 6, -2)]


def test_b4_scroll_propaga_error(monkeypatch):
    import threading
    import types
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()

    def scroll_falla(coords, wheel_dist):
        raise RuntimeError("scroll KO")

    fake_mouse = types.SimpleNamespace(scroll=scroll_falla)
    monkeypatch.setitem(sys.modules, "pywinauto", types.SimpleNamespace(mouse=fake_mouse))

    try:
        Player._scroll_xy(p, 1, 1, 0, 1)
        assert False, "debió propagar el error del scroll"
    except RuntimeError:
        pass


# ==================== B5: drag interpolado ====================

def test_b5_drag_usa_puntos_intermedios(monkeypatch):
    import threading
    import types
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()

    moves = []
    fake_mouse = types.SimpleNamespace(
        press=lambda button, coords: None,
        move=lambda coords: moves.append(coords),
        release=lambda button, coords: None,
    )
    monkeypatch.setitem(sys.modules, "pywinauto", types.SimpleNamespace(mouse=fake_mouse))
    monkeypatch.setattr("core.player.time.sleep", lambda s: None)

    Player._drag_xy(p, 0, 0, 100, 50, button="left")
    # Debe haber MUCHOS moves intermedios (no 1 solo salto)
    assert len(moves) >= 10
    # El último move llega al destino
    assert moves[-1] == (100, 50)
    # Y hay puntos intermedios reales
    assert any(0 < mx < 100 for (mx, my) in moves)


# ==================== A9: timestamp primer carácter ====================

def test_a9_type_text_usa_timestamp_del_primer_caracter():
    from core.recorder import Recorder, _BufferTexto

    rec = Recorder()
    rec._grabando = True
    rec._buf = _BufferTexto(texto="hola", primer_ts=100.0, ultimo_ts=105.0)
    with rec._lock:
        rec._flush_text()
    assert len(rec.eventos_crudos) == 1
    # El ts del evento es el del PRIMER carácter (100), no el último (105)
    assert rec.eventos_crudos[0].timestamp == 100.0


# ==================== A14: _flush_text sin force ====================

def test_a14_flush_text_no_acepta_force():
    import inspect
    from core.recorder import Recorder
    sig = inspect.signature(Recorder._flush_text)
    assert "force" not in sig.parameters


# ==================== Checkpoint: fusión + reset ====================

def test_checkpoint_reset_preserva_fingerprint(tmp_path):
    from core.dni_iterator import Checkpoint

    cp = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="FP1")
    cp.marcar_ok("A")
    cp.reset()
    assert cp._data.get("fingerprint") == "FP1"
    # Recargar: como el fingerprint coincide, NO se invalida ni descarta.
    cp2 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="FP1")
    assert cp2.invalidado is False
    assert cp2.hechos() == set()  # reset lo vació


def test_checkpoint_fusion_no_pierde_ok_de_otro_proceso(tmp_path):
    """Simula dos procesos: cp_b marca un DNI que cp_a no conoce; cuando
    cp_a guarda, debe FUSIONAR (no machacar) el OK de cp_b."""
    from core.dni_iterator import Checkpoint

    cp_a = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="FP")
    cp_b = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="FP")

    cp_a.marcar_ok("A")  # A en disco
    # cp_b tiene su copia en memoria (sin A). Marca B → al guardar, fusiona.
    cp_b.marcar_ok("B")

    # cp_b debe tener A (de disco) y B (suyo)
    assert cp_b.hechos() == {"A", "B"}
    # Y en disco están los dos
    cp_c = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="FP")
    assert cp_c.hechos() == {"A", "B"}


def test_checkpoint_invalidacion_no_reincorpora_por_fusion(tmp_path):
    """Cambiar el fingerprint debe descartar los OK viejos pese a la
    fusión (regresión que introdujo el fix de fusión)."""
    from core.dni_iterator import Checkpoint

    cp1 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="OLD")
    cp1.marcar_ok("X")
    cp1.marcar_ok("Y")

    cp2 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260101", macro_fingerprint="NEW")
    assert cp2.invalidado is True
    assert cp2.hechos() == set()  # NO reincorpora X, Y por la fusión


# ==================== DPI ====================

def test_dpi_set_awareness_falso_fuera_de_windows():
    import sys as _sys
    from core.dpi import set_dpi_awareness
    r = set_dpi_awareness()
    if _sys.platform.startswith("win"):
        assert r is True
    else:
        # Sin ctypes.windll → False, sin lanzar (no tautológico).
        assert r is False


def test_dpi_usa_per_monitor_v2_en_windows(monkeypatch):
    """Simula Windows: debe llamar SetProcessDpiAwarenessContext(-4)."""
    import ctypes
    import core.dpi as dpi_mod

    llamadas = {}

    class _FakeUser32:
        def SetProcessDpiAwarenessContext(self, ctx):
            llamadas["ctx"] = ctx
            return 1  # éxito

    class _FakeWinDLL:
        user32 = _FakeUser32()

    monkeypatch.setattr(ctypes, "windll", _FakeWinDLL(), raising=False)
    assert dpi_mod.set_dpi_awareness() is True
    # ctypes.c_void_p(-4) = PER_MONITOR_AWARE_V2
    assert llamadas["ctx"].value == ctypes.c_void_p(-4).value


# ==================== B7 fix: tap neutro antes de soltar Win ====================

def test_b7_soltar_win_emite_tap_neutro_antes(monkeypatch):
    """Al soltar Win, se emite un tap neutro (F13) ANTES del VK_LWIN up,
    para no abrir el menú Inicio si el paso Win+X falló sin emitir input."""
    import core.player as pl

    p = pl.Player.__new__(pl.Player)
    p._modifiers_held = {"win"}

    enviados = []
    fake_kb = type("K", (), {"send_keys": staticmethod(lambda s: enviados.append(s))})()
    monkeypatch.setattr(pl, "pwkeyboard", fake_kb)
    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)

    pl.Player._adjust_modifiers(p, set())  # soltar todo (Win)

    # El tap neutro {VK_F13} debe ir ANTES del {VK_LWIN up}
    assert "{VK_F13}" in enviados
    assert "{VK_LWIN up}" in enviados
    assert enviados.index("{VK_F13}") < enviados.index("{VK_LWIN up}")


def test_b7_soltar_ctrl_no_emite_tap_neutro(monkeypatch):
    """Soltar Ctrl/Shift/Alt en vacío es inocuo: no debe emitir el tap
    neutro (solo Win lo necesita)."""
    import core.player as pl

    p = pl.Player.__new__(pl.Player)
    p._modifiers_held = {"ctrl"}
    enviados = []
    fake_kb = type("K", (), {"send_keys": staticmethod(lambda s: enviados.append(s))})()
    monkeypatch.setattr(pl, "pwkeyboard", fake_kb)
    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)

    pl.Player._adjust_modifiers(p, set())
    assert "{VK_F13}" not in enviados
    assert enviados == ["{VK_CONTROL up}"]


def test_b4_scroll_horizontal_propaga_fallo_real(monkeypatch):
    """En 'Windows' (windll presente), un fallo de mouse_event en el scroll
    horizontal debe propagarse (no tragarse)."""
    import ctypes
    import core.player as pl

    p = pl.Player.__new__(pl.Player)

    class _FakeUser32:
        def SetCursorPos(self, x, y): return 1
        def mouse_event(self, *a): raise OSError("mouse_event KO")

    class _FakeWinDLL:
        user32 = _FakeUser32()

    monkeypatch.setattr(ctypes, "windll", _FakeWinDLL(), raising=False)
    try:
        pl.Player._scroll_horizontal(p, 1, 2, 3)
        assert False, "debió propagar el fallo real de mouse_event"
    except OSError:
        pass
