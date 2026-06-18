"""Tests del modelo Pipeline y del runner (sin pywinauto)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pipeline import Condicion, OnFailPolicy, Pipeline, PipelineStep


def test_pipeline_roundtrip_yaml(tmp_path):
    p = Pipeline(
        nombre="rutina",
        descripcion="prueba",
        pasos=[
            PipelineStep(macro="m1", veces=2, velocidad=1.5, pausa_antes_s=5),
            PipelineStep(macro="m2", on_fail=OnFailPolicy.CONTINUE),
            PipelineStep(macro="m3", condicion=Condicion.TODOS_OK),
        ],
    )
    path = tmp_path / "p.yaml"
    p.save(path)
    cargado = Pipeline.load(path)
    assert cargado.nombre == "rutina"
    assert len(cargado.pasos) == 3
    assert cargado.pasos[0].macro == "m1"
    assert cargado.pasos[0].veces == 2
    assert cargado.pasos[0].velocidad == 1.5
    assert cargado.pasos[0].pausa_antes_s == 5
    assert cargado.pasos[1].on_fail == OnFailPolicy.CONTINUE
    assert cargado.pasos[2].condicion == Condicion.TODOS_OK


def test_step_to_dict_omite_defaults():
    s = PipelineStep(macro="m1")
    d = s.to_dict()
    assert d == {"macro": "m1"}


def test_step_to_dict_solo_serializa_no_defaults():
    s = PipelineStep(macro="m1", veces=3, on_fail=OnFailPolicy.SKIP_REST, descripcion="desc")
    d = s.to_dict()
    assert d == {"macro": "m1", "veces": 3, "on_fail": "skip_rest", "descripcion": "desc"}


class _FakeReplaySummary:
    def __init__(self, total, ok, ko):
        self.total = total
        self.ok = ok
        self.ko = ko


def test_pipeline_runner_respeta_stop(monkeypatch, tmp_path):
    """Si el primer paso falla con on_fail=stop, no se ejecuta el segundo."""
    # Crear macros dummy YAML
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")

    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1", on_fail=OnFailPolicy.STOP),
        PipelineStep(macro="m2"),
    ])
    from core.pipeline_runner import PipelineRunner

    # Mockear ReplayRunner para que m1 devuelva 0 OK 1 KO
    import core.pipeline_runner as pr_mod

    class FakeRunner:
        def __init__(self, **kw):
            self.macro = kw["macro"]
        def run(self):
            if self.macro.nombre == "m1":
                return _FakeReplaySummary(total=1, ok=0, ko=1)
            return _FakeReplaySummary(total=1, ok=1, ko=0)
        def abort(self):
            pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)

    runner = PipelineRunner(
        pipeline=pipeline,
        macros_dir=tmp_path,
        screenshots_dir=tmp_path / "shots",
        data_dir=tmp_path / "data",
        settle_entre_macros_s=0,
    )
    summary = runner.run()
    assert len(summary.pasos_resultado) == 1   # solo m1, m2 no llegó a ejecutarse
    assert summary.pasos_resultado[0].ko == 1


def test_pipeline_runner_continua_si_continue(monkeypatch, tmp_path):
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")
    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1", on_fail=OnFailPolicy.CONTINUE),
        PipelineStep(macro="m2"),
    ])
    import core.pipeline_runner as pr_mod

    class FakeRunner:
        def __init__(self, **kw):
            self.macro = kw["macro"]
        def run(self):
            if self.macro.nombre == "m1":
                return _FakeReplaySummary(total=1, ok=0, ko=1)
            return _FakeReplaySummary(total=1, ok=1, ko=0)
        def abort(self):
            pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)
    runner = pr_mod.PipelineRunner(pipeline=pipeline, macros_dir=tmp_path,
                                   screenshots_dir=tmp_path / "s", data_dir=tmp_path / "d",
                                   settle_entre_macros_s=0)
    summary = runner.run()
    assert len(summary.pasos_resultado) == 2
    assert summary.pasos_resultado[0].ko == 1
    assert summary.pasos_resultado[1].ok == 1


def test_pipeline_runner_skip_rest(monkeypatch, tmp_path):
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")
    (tmp_path / "m3.yaml").write_text("nombre: m3\npasos: []\n", encoding="utf-8")
    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1", on_fail=OnFailPolicy.SKIP_REST),
        PipelineStep(macro="m2"),
        PipelineStep(macro="m3"),
    ])
    import core.pipeline_runner as pr_mod

    class FakeRunner:
        def __init__(self, **kw):
            self.macro = kw["macro"]
        def run(self):
            return _FakeReplaySummary(total=1, ok=0, ko=1)
        def abort(self):
            pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)
    runner = pr_mod.PipelineRunner(pipeline=pipeline, macros_dir=tmp_path,
                                   screenshots_dir=tmp_path / "s", data_dir=tmp_path / "d",
                                   settle_entre_macros_s=0)
    summary = runner.run()
    # m1 ejecutado y KO. m2 y m3 marcados como saltados.
    assert len(summary.pasos_resultado) == 3
    assert summary.pasos_resultado[0].ko == 1
    assert summary.pasos_resultado[1].saltado is True
    assert summary.pasos_resultado[2].saltado is True


def test_pipeline_runner_condicion_todos_ok(monkeypatch, tmp_path):
    (tmp_path / "m1.yaml").write_text("nombre: m1\npasos: []\n", encoding="utf-8")
    (tmp_path / "m2.yaml").write_text("nombre: m2\npasos: []\n", encoding="utf-8")
    pipeline = Pipeline(nombre="t", pasos=[
        PipelineStep(macro="m1", on_fail=OnFailPolicy.CONTINUE),
        PipelineStep(macro="m2", condicion=Condicion.TODOS_OK),
    ])
    import core.pipeline_runner as pr_mod

    class FakeRunner:
        def __init__(self, **kw): self.macro = kw["macro"]
        def run(self):
            return _FakeReplaySummary(total=1, ok=0, ko=1)
        def abort(self): pass

    monkeypatch.setattr(pr_mod, "ReplayRunner", FakeRunner)
    runner = pr_mod.PipelineRunner(pipeline=pipeline, macros_dir=tmp_path,
                                   screenshots_dir=tmp_path / "s", data_dir=tmp_path / "d",
                                   settle_entre_macros_s=0)
    summary = runner.run()
    assert summary.pasos_resultado[0].ko == 1
    # m2 saltado porque condición todos_ok no se cumple (m1 falló)
    assert summary.pasos_resultado[1].saltado is True
    assert "todos_ok" in summary.pasos_resultado[1].motivo_salto
