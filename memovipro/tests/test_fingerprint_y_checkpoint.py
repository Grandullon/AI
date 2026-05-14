from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.dni_iterator import Checkpoint
from core.step_model import Macro, Selector, Step, StepType


def _macro_base() -> Macro:
    return Macro(
        nombre="m",
        ventana_principal="App",
        pasos=[
            Step(tipo=StepType.FOCUS_WINDOW, titulo="App"),
            Step(tipo=StepType.TYPE_TEXT, valor="{DNI}", selector=Selector(control_type="Edit", name="txt")),
        ],
    )


def test_fingerprint_estable_ignora_descripcion():
    m1 = _macro_base()
    m2 = _macro_base()
    m2.pasos[0].descripcion = "lo que sea"
    m2.descripcion = "otra cosa"
    assert m1.fingerprint() == m2.fingerprint()


def test_fingerprint_cambia_si_cambia_valor():
    m1 = _macro_base()
    m2 = _macro_base()
    m2.pasos[1].valor = "otro_valor"
    assert m1.fingerprint() != m2.fingerprint()


def test_checkpoint_se_invalida_si_cambia_fingerprint(tmp_path):
    cp1 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514", macro_fingerprint="hashAAA")
    cp1.marcar_ok("X")
    cp1.marcar_ok("Y")

    cp2 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514", macro_fingerprint="hashAAA")
    assert cp2.hechos() == {"X", "Y"}
    assert cp2.invalidado is False

    cp3 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514", macro_fingerprint="hashBBB")
    assert cp3.hechos() == set()
    assert cp3.invalidado is True


def test_checkpoint_sin_fingerprint_es_compatible(tmp_path):
    cp1 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514")
    cp1.marcar_ok("A")

    cp2 = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514", macro_fingerprint="ahora_si")
    assert cp2.hechos() == {"A"}
    assert cp2.invalidado is False
