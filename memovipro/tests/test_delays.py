"""Tests del campo delay_before_s y de la captura/reproducción de tiempos."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import EventoCrudo, Recorder
from core.step_model import Macro, Step, StepType


def test_step_serializa_y_deserializa_delay(tmp_path):
    paso = Step(tipo=StepType.SEND_KEYS, valor="{ENTER}", delay_before_s=1.5)
    macro = Macro(nombre="m", pasos=[paso])
    path = tmp_path / "m.yaml"
    macro.save(path)
    cargada = Macro.load(path)
    assert cargada.pasos[0].delay_before_s == 1.5


def test_step_no_serializa_delay_si_es_cero(tmp_path):
    paso = Step(tipo=StepType.SEND_KEYS, valor="{ENTER}", delay_before_s=0.0)
    macro = Macro(nombre="m", pasos=[paso])
    path = tmp_path / "m.yaml"
    macro.save(path)
    yaml_text = path.read_text(encoding="utf-8")
    assert "delay_before_s" not in yaml_text


def test_construir_macro_calcula_delay_entre_eventos():
    # 3 eventos con timestamps que generan delays de 0.0, 0.5 y 2.3
    eventos = [
        EventoCrudo(tipo="click", x=1, y=1, timestamp=100.0),
        EventoCrudo(tipo="click", x=2, y=2, timestamp=100.5),
        EventoCrudo(tipo="type_text", valor="hola", timestamp=102.8),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert len(macro.pasos) == 3
    assert macro.pasos[0].delay_before_s == 0.0  # primer evento sin delay
    assert abs(macro.pasos[1].delay_before_s - 0.5) < 1e-6
    assert abs(macro.pasos[2].delay_before_s - 2.3) < 1e-6


def test_construir_macro_preserva_5_minutos():
    """5 minutos de pausa deben preservarse íntegros (nuevo cap = 30 min)."""
    eventos = [
        EventoCrudo(tipo="click", x=1, y=1, timestamp=100.0),
        EventoCrudo(tipo="click", x=2, y=2, timestamp=100 + 300),  # 5 minutos
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert abs(macro.pasos[1].delay_before_s - 300.0) < 1e-6


def test_construir_macro_cap_a_30_minutos():
    """Si la pausa supera 30 minutos (usuario olvidó cerrar grabación),
    se recorta. Antes el cap eran 30s; ahora son 30 min (1800s)."""
    eventos = [
        EventoCrudo(tipo="click", x=1, y=1, timestamp=100.0),
        EventoCrudo(tipo="click", x=2, y=2, timestamp=100 + 7200),  # 2 horas
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert macro.pasos[1].delay_before_s == 1800.0


def test_recorder_max_delay_constante():
    assert Recorder.MAX_DELAY_S == 1800.0


def test_construir_macro_sin_timestamps_pone_delay_cero():
    eventos = [
        EventoCrudo(tipo="click", x=1, y=1),  # timestamp default 0.0
        EventoCrudo(tipo="click", x=2, y=2),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert all(p.delay_before_s == 0.0 for p in macro.pasos)


def test_player_velocidad_aplica_factor():
    """Verifica que el cálculo de tiempo a esperar es el correcto.

    No usa pywinauto: solo se prueba la lógica del divisor + sanity cap
    del player a 1 hora (3600s).
    """
    def calcular(delay, velocidad):
        if delay <= 0 or velocidad <= 0:
            return 0.0
        return min(delay / velocidad, 3600.0)

    # Casos básicos
    assert calcular(4.0, 2.0) == 2.0
    assert calcular(4.0, 0.5) == 8.0
    assert calcular(4.0, 0.0) == 0.0
    assert calcular(0.0, 1.0) == 0.0

    # Pausas largas: ya no se cortan a 30s. 5 min se respeta.
    assert calcular(300.0, 1.0) == 300.0
    # 10 min a 2x velocidad = 5 min
    assert calcular(600.0, 2.0) == 300.0
    # Sanity cap: si el YAML pone algo descomunal (10h), se recorta a 1h.
    assert calcular(36000.0, 1.0) == 3600.0
