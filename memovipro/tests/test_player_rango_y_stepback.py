"""Tests de las mejoras del paso a paso y ejecución por rango:

- Player acepta start_idx / stop_after_idx y los guarda.
- ReplayRunner los propaga al Player.
- step_back() marca la intención de retroceder y despierta el wait.
- El loop de ejecución respeta el corte por stop_after_idx (inspección).
- PipelineRunner asienta entre macros (settle) de forma interrumpible.
"""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_player_guarda_start_y_stop():
    from core.player import Player
    p = Player.__new__(Player)
    Player.__init__(
        p,
        macro=type("M", (), {"nombre": "m", "pasos": []})(),
        screenshots_dir=".",
        logger=None,
        start_idx=3,
        stop_after_idx=7,
    )
    assert p._start_idx == 3
    assert p._stop_after_idx == 7


def test_player_start_idx_negativo_se_normaliza():
    from core.player import Player
    p = Player.__new__(Player)
    Player.__init__(
        p,
        macro=type("M", (), {"nombre": "m", "pasos": []})(),
        screenshots_dir=".",
        logger=None,
        start_idx=-5,
    )
    assert p._start_idx == 0
    assert p._stop_after_idx is None


def test_step_back_marca_flag_y_despierta_wait():
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    p._step_mode = True
    p._step_continue = threading.Event()
    p._step_back_flag = False

    resultado = {"completado": False}

    def worker():
        Player._esperar_step(p)
        resultado["completado"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not resultado["completado"]

    Player.step_back(p)
    assert p._step_back_flag is True
    t.join(timeout=1.0)
    assert resultado["completado"], "step_back debe liberar el wait"


def test_advance_step_limpia_el_flag_de_back():
    from core.player import Player
    p = Player.__new__(Player)
    p._step_continue = threading.Event()
    p._step_back_flag = True
    Player.advance_step(p)
    assert p._step_back_flag is False


def test_loop_respeta_stop_after_idx_inspeccion():
    """El loop debe cortar cuando _step_idx supera stop_after_idx."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player.ejecutar_dni)
    assert "_stop_after_idx" in src
    assert "self._step_idx = min(self._start_idx" in src


def test_replay_runner_propaga_rango():
    import inspect
    from core.replay_runner import ReplayRunner
    src = inspect.getsource(ReplayRunner.run)
    assert "start_idx=self.start_idx" in src
    assert "stop_after_idx=self.stop_after_idx" in src


def test_replay_runner_step_back_propaga_al_player():
    from core.replay_runner import ReplayRunner
    r = ReplayRunner.__new__(ReplayRunner)
    calls = {"back": 0}

    class _FakePlayer:
        def step_back(self): calls["back"] += 1

    r._player = _FakePlayer()
    r.step_back()
    assert calls["back"] == 1


class _FakeReplaySummary:
    def __init__(self, total, ok, ko):
        self.total = total
        self.ok = ok
        self.ko = ko


def test_pipeline_settle_se_aplica_entre_macros(monkeypatch, tmp_path):
    """Con 2 macros y settle pequeño, el runner duerme una vez (entre ambas),
    no tras la última."""
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")
    from core.pipeline import Pipeline, PipelineStep
    import core.pipeline_runner as pr_mod

    class FakeRunner:
        def __init__(self, **kw): self.macro = kw["macro"]
        def run(self): return _FakeReplaySummary(total=1, ok=1, ko=0)
        def abort(self): pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)
    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1"), PipelineStep(macro="m2"),
    ])
    runner = pr_mod.PipelineRunner(
        pipeline=pipeline, macros_dir=tmp_path,
        screenshots_dir=tmp_path / "s", data_dir=tmp_path / "d",
        settle_entre_macros_s=0.3,
    )
    inicio = time.time()
    summary = runner.run()
    dur = time.time() - inicio
    assert summary.total_ok == 2
    # Una sola pausa de ~0.3s (entre m1 y m2), no dos.
    assert 0.25 <= dur < 0.9, f"settle inesperado: {dur:.2f}s"


def test_pipeline_settle_interrumpible_por_abort(monkeypatch, tmp_path):
    """Abortar durante el settle no debe esperar el settle completo."""
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")
    from core.pipeline import Pipeline, PipelineStep
    import core.pipeline_runner as pr_mod

    estado = {"runner": None}

    class FakeRunner:
        def __init__(self, **kw): self.macro = kw["macro"]
        def run(self):
            # Abortar el pipeline justo al terminar la primera macro, de modo
            # que el settle posterior deba cortarse de inmediato.
            if self.macro.nombre == "m1" and estado["runner"]:
                estado["runner"]._abort.set()
            return _FakeReplaySummary(total=1, ok=1, ko=0)
        def abort(self): pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)
    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1"), PipelineStep(macro="m2"),
    ])
    runner = pr_mod.PipelineRunner(
        pipeline=pipeline, macros_dir=tmp_path,
        screenshots_dir=tmp_path / "s", data_dir=tmp_path / "d",
        settle_entre_macros_s=5.0,
    )
    estado["runner"] = runner
    inicio = time.time()
    runner.run()
    dur = time.time() - inicio
    assert dur < 1.0, f"el settle no se interrumpió con abort: {dur:.2f}s"
