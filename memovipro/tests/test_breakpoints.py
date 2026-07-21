"""Tests del motor de puntos de análisis (breakpoints) del step-through.

Verifican la lógica de _debe_pausar y los modos step/continue del Player,
y la propagación por ReplayRunner. La UI (StepThroughPanel/StepEditor) se
cubre por inspección donde no hay PyQt6.
"""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _player_min(step_mode=True, run_mode="step", breakpoints=None):
    from core.player import Player
    p = Player.__new__(Player)
    p._step_mode = step_mode
    p._run_mode = run_mode
    p._breakpoints = set(breakpoints or set())
    p._step_continue = threading.Event()
    p._step_back_flag = False
    return p


# ==================== _debe_pausar ====================

def test_debe_pausar_modo_step_siempre():
    from core.player import Player
    p = _player_min(run_mode="step", breakpoints={5})
    # En modo step pausa en CUALQUIER paso, sea o no breakpoint.
    assert Player._debe_pausar(p, 0) is True
    assert Player._debe_pausar(p, 5) is True
    assert Player._debe_pausar(p, 99) is True


def test_debe_pausar_modo_continue_solo_en_breakpoint():
    from core.player import Player
    p = _player_min(run_mode="continue", breakpoints={5, 8})
    assert Player._debe_pausar(p, 0) is False
    assert Player._debe_pausar(p, 4) is False
    assert Player._debe_pausar(p, 5) is True    # breakpoint
    assert Player._debe_pausar(p, 8) is True    # breakpoint
    assert Player._debe_pausar(p, 9) is False


def test_debe_pausar_fuera_de_step_mode_nunca():
    from core.player import Player
    p = _player_min(step_mode=False, run_mode="continue", breakpoints={5})
    assert Player._debe_pausar(p, 5) is False


# ==================== transiciones de modo ====================

def test_advance_step_pone_modo_step():
    from core.player import Player
    p = _player_min(run_mode="continue")
    Player.advance_step(p)
    assert p._run_mode == "step"
    assert p._step_continue.is_set()


def test_continue_run_pone_modo_continue():
    from core.player import Player
    p = _player_min(run_mode="step")
    Player.continue_run(p)
    assert p._run_mode == "continue"
    assert p._step_continue.is_set()


def test_step_back_pone_modo_step_y_flag():
    from core.player import Player
    p = _player_min(run_mode="continue")
    Player.step_back(p)
    assert p._run_mode == "step"
    assert p._step_back_flag is True
    assert p._step_continue.is_set()


def test_set_breakpoints_actualiza_en_caliente():
    from core.player import Player
    p = _player_min(breakpoints={1})
    Player.set_breakpoints(p, {3, 7})
    assert p._breakpoints == {3, 7}
    Player.set_breakpoints(p, None)
    assert p._breakpoints == set()


# ==================== constructor ====================

def test_player_guarda_breakpoints_y_run_mode():
    from core.player import Player
    p = Player.__new__(Player)
    Player.__init__(
        p,
        macro=type("M", (), {"nombre": "m", "pasos": []})(),
        screenshots_dir=".",
        logger=None,
        breakpoints={2, 4},
        run_mode="continue",
    )
    assert p._breakpoints == {2, 4}
    assert p._run_mode == "continue"


def test_player_run_mode_invalido_cae_a_step():
    from core.player import Player
    p = Player.__new__(Player)
    Player.__init__(
        p,
        macro=type("M", (), {"nombre": "m", "pasos": []})(),
        screenshots_dir=".",
        logger=None,
        run_mode="loquesea",
    )
    assert p._run_mode == "step"


# ==================== RunStatus ====================

def test_runstatus_tiene_campos_breakpoint():
    from core.player import RunStatus
    s = RunStatus(dni="d", paso_idx=3, descripcion="x", es_breakpoint=True, en_pausa=True)
    assert s.es_breakpoint is True
    assert s.en_pausa is True
    # Defaults hacia atrás-compatibles
    s2 = RunStatus(dni="d", paso_idx=0, descripcion="y")
    assert s2.es_breakpoint is False
    assert s2.en_pausa is False


# ==================== ReplayRunner propaga ====================

def test_replay_runner_propaga_breakpoints_y_run_mode():
    import inspect
    from core.replay_runner import ReplayRunner
    src = inspect.getsource(ReplayRunner.run)
    assert "breakpoints=self.breakpoints" in src
    assert "run_mode=self.run_mode" in src


def test_replay_runner_continue_run_propaga_al_player():
    from core.replay_runner import ReplayRunner
    r = ReplayRunner.__new__(ReplayRunner)
    llam = {"c": 0}

    class _FakePlayer:
        def continue_run(self): llam["c"] += 1

    r._player = _FakePlayer()
    r.continue_run()
    assert llam["c"] == 1


# ==================== integración: loop real con breakpoints ====================

def test_loop_continue_para_en_breakpoint_y_ejecuta_resto(monkeypatch):
    """Ejecuta el loop real (dry_run) con breakpoints en modo continue:
    debe pausar en cada breakpoint y, al soltarlo, seguir hasta el
    siguiente. Simulamos el usuario con un hilo que suelta continue."""
    import time
    # El loop exige pywinauto aunque sea dry-run; lo activamos (los pasos
    # SLEEP con valor 0 no llegan a llamar a ninguna API de pywinauto).
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player, RunStatus
    from core.step_model import Macro, Step, StepType

    pasos = [Step(tipo=StepType.SLEEP, valor="0") for _ in range(6)]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)

    pausas = []

    def on_status(st: RunStatus):
        if st.en_pausa:
            pausas.append(st.paso_idx)

    p = Player(
        macro=macro, screenshots_dir=".", logger=None,
        dry_run=True, step_mode=True, run_mode="continue",
        breakpoints={2, 4}, on_status=on_status,
    )

    # Hilo "usuario": cuando detecte una pausa nueva, pulsa continuar.
    parar = threading.Event()

    def usuario():
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                vistas = len(pausas)
                time.sleep(0.05)
                p.continue_run()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()

    assert exito is True
    # Debe haber parado exactamente en los breakpoints 2 y 4 (en orden).
    assert pausas == [2, 4]


# ==================== _esperar_step: sin lost-wakeup ====================

def test_esperar_step_no_pierde_set_previo():
    """Regresión: si el usuario pulsa (set) DESPUÉS de anunciarse la pausa
    pero ANTES de que el loop entre al wait, _esperar_step no debe borrar
    ese set (antes lo hacía con un clear() de entrada) ni colgarse."""
    import time
    from core.player import Player
    p = _player_min()
    p._step_continue.set()  # pulsación ya presente al entrar
    inicio = time.time()
    Player._esperar_step(p)   # NO debe bloquear ~3600s
    assert time.time() - inicio < 1.0
    assert not p._step_continue.is_set()  # se consumió (clear final)


def test_esperar_step_bloquea_si_no_hay_set(monkeypatch):
    """Sin set previo, espera (verificamos que llama a wait con timeout)."""
    from core.player import Player
    p = _player_min()
    llam = {}
    p._step_continue.wait = lambda timeout=None: llam.setdefault("t", timeout) or True
    p._step_continue.clear = lambda: llam.__setitem__("cleared", True)
    Player._esperar_step(p)
    assert llam.get("t") == 3600.0
    assert llam.get("cleared") is True


def test_handlers_gated_en_pausa_por_inspeccion():
    """Los handlers de avanzar/atrás/continuar/grabar comprueban _en_pausa."""
    src = (ROOT / "ui" / "step_through_panel.py").read_text(encoding="utf-8")
    for fn in ("_on_next", "_on_back", "_on_continue"):
        cuerpo = src.split(f"def {fn}(self")[1].split("def ")[0]
        assert "self._en_pausa" in cuerpo, f"{fn} no comprueba _en_pausa"
    rec = src.split("def _on_record_here")[1].split("def ")[0]
    assert "self._en_pausa" in rec
    # El loop del player descarta pulsaciones previas a la pausa.
    psrc = (ROOT / "core" / "player.py").read_text(encoding="utf-8")
    assert "Descartar pulsaciones PREVIAS" in psrc


# ==================== ajuste de breakpoints al editar ====================

def test_shift_on_insert():
    from core.debug_marks import shift_on_insert
    # Insertar 1 paso en la posición 3: los breakpoints >=3 suben 1.
    assert shift_on_insert({1, 3, 5}, 3, 1) == {1, 4, 6}
    # Insertar varios.
    assert shift_on_insert({2, 4}, 2, 3) == {5, 7}
    # Insertar al final no afecta a los previos.
    assert shift_on_insert({0, 1}, 5, 1) == {0, 1}


def test_shift_on_remove():
    from core.debug_marks import shift_on_remove
    # Borrar el paso 3: se quita su breakpoint, los >3 bajan 1.
    assert shift_on_remove({1, 3, 5}, 3) == {1, 4}
    # Borrar un paso sin breakpoint: los posteriores bajan 1.
    assert shift_on_remove({2, 5}, 4) == {2, 4}
    # Borrar antes de todos.
    assert shift_on_remove({2, 3}, 0) == {1, 2}


def test_swap_on_move():
    from core.debug_marks import swap_on_move
    # El breakpoint en 3 viaja al 4 al intercambiar 3<->4.
    assert swap_on_move({3}, 3, 4) == {4}
    assert swap_on_move({4}, 3, 4) == {3}
    # Ambos con breakpoint → se intercambian (siguen ambos).
    assert swap_on_move({3, 4}, 3, 4) == {3, 4}
    # Ninguno afectado.
    assert swap_on_move({1, 7}, 3, 4) == {1, 7}


def test_editor_y_panel_usan_debug_marks():
    """El editor y el panel delegan en las funciones puras (fuente única)."""
    ed = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    assert "shift_on_insert" in ed
    assert "shift_on_remove" in ed
    assert "swap_on_move" in ed
    panel = (ROOT / "ui" / "step_through_panel.py").read_text(encoding="utf-8")
    assert "shift_on_insert" in panel


def test_loop_sin_breakpoints_continue_no_para(monkeypatch):
    """Modo continue sin breakpoints = corre entero sin pausas."""
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player, RunStatus
    from core.step_model import Macro, Step, StepType

    pasos = [Step(tipo=StepType.SLEEP, valor="0") for _ in range(4)]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    pausas = []
    p = Player(
        macro=macro, screenshots_dir=".", logger=None,
        dry_run=True, step_mode=True, run_mode="continue",
        breakpoints=set(),
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    assert exito is True
    assert pausas == []  # nunca paró
