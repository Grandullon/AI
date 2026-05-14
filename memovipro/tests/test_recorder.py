from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import EventoCrudo, Recorder
from core.step_model import StepType


def test_construir_macro_sin_resolver_genera_click_at_xy():
    eventos = [EventoCrudo(tipo="click", x=100, y=200, button="Button.left")]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert len(macro.pasos) == 1
    assert macro.pasos[0].tipo == StepType.CLICK_AT_XY
    assert macro.pasos[0].extra == {"x": 100, "y": 200}


def test_construir_macro_agrupa_tipos():
    eventos = [
        EventoCrudo(tipo="click", x=10, y=20),
        EventoCrudo(tipo="type_text", valor="12345678A"),
        EventoCrudo(tipo="send_keys", valor="{TAB}"),
        EventoCrudo(tipo="click", x=300, y=400),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    tipos = [p.tipo for p in macro.pasos]
    assert tipos == [StepType.CLICK_AT_XY, StepType.TYPE_TEXT, StepType.SEND_KEYS, StepType.CLICK_AT_XY]
    assert macro.pasos[1].valor == "12345678A"
    assert macro.pasos[2].valor == "{TAB}"


def test_construir_macro_emite_progreso():
    eventos = [
        EventoCrudo(tipo="click", x=1, y=1),
        EventoCrudo(tipo="type_text", valor="x"),
        EventoCrudo(tipo="click", x=2, y=2),
        EventoCrudo(tipo="click", x=3, y=3),
    ]
    progresos: list[tuple[int, int]] = []
    Recorder.construir_macro(
        eventos,
        resolver_selectores=False,
        on_progress=lambda i, total: progresos.append((i, total)),
    )
    # 3 clics → 3 emisiones de progreso, con total=3 siempre
    assert progresos == [(1, 3), (2, 3), (3, 3)]


def test_construir_macro_lista_vacia():
    macro = Recorder.construir_macro([], resolver_selectores=False)
    assert macro.pasos == []


def test_tecla_a_send_keys():
    class FakeKey:
        def __init__(self, n): self._n = n
        def __str__(self): return f"Key.{self._n}"

    assert Recorder._tecla_a_send_keys(FakeKey("enter")) == "{ENTER}"
    assert Recorder._tecla_a_send_keys(FakeKey("tab")) == "{TAB}"
    assert Recorder._tecla_a_send_keys(FakeKey("f5")) == "{F5}"
    assert Recorder._tecla_a_send_keys(FakeKey("xxx")) is None
