from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Macro, Selector, Step, StepType, render_placeholders, render_step


def test_render_placeholders_basico():
    out = render_placeholders("IT_{DNI}_{YYYYMMDD}.xlsx", {"DNI": "12345678A"})
    assert out.startswith("IT_12345678A_")
    assert out.endswith(".xlsx")
    assert len(out) == len("IT_12345678A_20251104.xlsx")


def test_render_placeholders_desconocido_se_mantiene():
    assert render_placeholders("hola {NO_EXISTE}", {}) == "hola {NO_EXISTE}"


def test_render_step_sustituye_valor_y_selector_name():
    paso = Step(
        tipo=StepType.TYPE_TEXT,
        selector=Selector(control_type="Edit", name="campo_{DNI}"),
        valor="{DNI}",
    )
    out = render_step(paso, {"DNI": "Y9999999Z"})
    assert out.valor == "Y9999999Z"
    assert out.selector.name == "campo_Y9999999Z"


def test_macro_roundtrip_yaml(tmp_path):
    macro = Macro(
        nombre="m",
        ventana_principal="AppX",
        pasos=[
            Step(tipo=StepType.FOCUS_WINDOW, titulo="AppX"),
            Step(tipo=StepType.TYPE_TEXT, valor="hola", selector=Selector(control_type="Edit", name="txt")),
        ],
    )
    p = tmp_path / "m.yaml"
    macro.save(p)
    loaded = Macro.load(p)
    assert loaded.nombre == "m"
    assert loaded.ventana_principal == "AppX"
    assert len(loaded.pasos) == 2
    assert loaded.pasos[1].valor == "hola"
    assert loaded.pasos[1].selector.name == "txt"
