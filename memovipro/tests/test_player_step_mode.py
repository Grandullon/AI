"""Tests del modo step-through del Player.

Verifica que:
- step_mode=True bloquea el loop esperando advance_step() en cada paso
- abort() despierta el wait inmediatamente
- El while con índice dinámico recoge pasos insertados en runtime
- step_index() refleja el paso actual
"""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_player_step_mode_state_inicial():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._paused = threading.Event()
    p._step_mode = True
    p._step_continue = threading.Event()
    p._step_idx = 0

    assert Player.step_index(p) == 0


def test_advance_step_libera_el_wait():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._step_mode = True
    p._step_continue = threading.Event()

    resultado = {"completado": False}

    def worker():
        Player._esperar_step(p)
        resultado["completado"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not resultado["completado"]

    Player.advance_step(p)
    t.join(timeout=1.0)
    assert resultado["completado"], "advance_step debe liberar el wait"


def test_abort_libera_el_step_wait_aunque_no_se_avance():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._paused = threading.Event()
    p._step_mode = True
    p._step_continue = threading.Event()

    resultado = {"completado": False}

    def worker():
        Player._esperar_step(p)
        resultado["completado"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not resultado["completado"]

    Player.abort(p)
    t.join(timeout=1.0)
    assert resultado["completado"], "abort debe despertar el step-wait"


def test_esperar_step_no_bloquea_si_no_step_mode():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._step_mode = False
    p._step_continue = threading.Event()

    # Si step_mode es False, debe retornar inmediatamente
    inicio = time.time()
    Player._esperar_step(p)
    duracion = time.time() - inicio
    assert duracion < 0.1, "sin step_mode, _esperar_step debe ser no-op"


def test_replay_runner_propaga_step_mode():
    """ReplayRunner debe pasar step_mode al Player que crea."""
    import inspect
    from core.replay_runner import ReplayRunner
    src = inspect.getsource(ReplayRunner.__init__)
    assert "step_mode" in src
    src_run = inspect.getsource(ReplayRunner.run)
    assert "step_mode=self.step_mode" in src_run


def test_replay_runner_advance_step_propaga_al_player():
    from core.replay_runner import ReplayRunner
    r = ReplayRunner.__new__(ReplayRunner)
    r._abort = threading.Event()
    calls = {"advance": 0}

    class _FakePlayer:
        def advance_step(self): calls["advance"] += 1
        def abort(self): pass

    r._player = _FakePlayer()
    r.advance_step()
    assert calls["advance"] == 1


def test_player_loop_usa_while_con_indice_dinamico():
    """Inspección estática: el loop principal debe usar `while` (no for)
    para soportar inserción de pasos en runtime."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player.ejecutar_dni)
    # Antes era `for idx, paso in enumerate(...)`. Ahora `while self._step_idx ...`
    assert "while self._step_idx" in src
    assert "self.macro.pasos[" in src
    # Y debe incrementar _step_idx al final del paso
    assert "self._step_idx += 1" in src
