"""Tests del soporte de pausa en Player y ReplayRunner.

El panel de control flotante (UI) emite pause_toggled. El test prueba
la cadena: ReplayRunner.pause() → Player.pause() → loop bloqueado en
_esperar_si_pausado, y Player.resume() lo libera.
"""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_player_pause_y_resume_modifican_estado():
    # Importamos sin PyQt6 — basta con Player
    from core.player import Player
    from core.step_model import Macro
    # No iniciamos pywinauto, solo manipulamos el estado interno.
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._paused = threading.Event()

    assert p.is_paused() is False
    Player.pause(p)
    assert p.is_paused() is True
    Player.resume(p)
    assert p.is_paused() is False


def test_esperar_si_pausado_bloquea_hasta_resume():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._paused = threading.Event()
    p._paused.set()

    resultado = {"completado": False}

    def worker():
        Player._esperar_si_pausado(p)
        resultado["completado"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not resultado["completado"], "Debería estar bloqueado por pausa"

    Player.resume(p)
    t.join(timeout=1.0)
    assert resultado["completado"], "Debió completar tras resume"


def test_abort_desbloquea_pausa():
    """abort() debe despertar al loop aunque esté en pausa."""
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._paused = threading.Event()
    p._paused.set()

    resultado = {"completado": False}

    def worker():
        Player._esperar_si_pausado(p)
        resultado["completado"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not resultado["completado"]

    Player.abort(p)
    t.join(timeout=1.0)
    assert resultado["completado"]


def test_replay_runner_forward_pause(monkeypatch):
    """ReplayRunner.pause() debe llamar al pause del Player en curso."""
    from core.replay_runner import ReplayRunner

    r = ReplayRunner.__new__(ReplayRunner)
    r._abort = threading.Event()

    eventos = {"pause": 0, "resume": 0}

    class _FakePlayer:
        def pause(self): eventos["pause"] += 1
        def resume(self): eventos["resume"] += 1
        def abort(self): pass

    r._player = _FakePlayer()
    r.pause()
    r.resume()
    assert eventos == {"pause": 1, "resume": 1}


def test_replay_runner_pause_sin_player_es_noop():
    from core.replay_runner import ReplayRunner
    r = ReplayRunner.__new__(ReplayRunner)
    r._player = None
    r._abort = threading.Event()
    # No debe lanzar
    r.pause()
    r.resume()
