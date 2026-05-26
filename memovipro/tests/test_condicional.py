"""Tests de la lógica condicional IF_VENTANA."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.player import Player
from core.step_model import Macro, Step, StepType


def _player_para_if(dry_run=False):
    p = Player.__new__(Player)
    p.dry_run = dry_run
    return p


def test_if_ventana_es_step_type():
    s = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "Error", "saltar_si_no": 2})
    d = s.to_dict()
    assert d["tipo"] == "if_ventana"
    cargado = Step.from_dict(d)
    assert cargado.tipo == StepType.IF_VENTANA
    assert cargado.extra["ventana"] == "Error"


def test_evaluar_if_dry_run_siempre_ejecuta():
    p = _player_para_if(dry_run=True)
    paso = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "X", "saltar_si_no": 5})
    # En dry-run devuelve 1 (ejecutar el bloque, no saltar)
    assert Player._evaluar_if(p, paso) == 1


def test_evaluar_if_ventana_existe_ejecuta_bloque(monkeypatch):
    import core.window_utils as wu
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.5: True)
    p = _player_para_if(dry_run=False)
    paso = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "Error", "saltar_si_no": 3})
    # Existe → condición True → avanzar 1 (ejecutar bloque)
    assert Player._evaluar_if(p, paso) == 1


def test_evaluar_if_ventana_no_existe_salta_bloque(monkeypatch):
    import core.window_utils as wu
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.5: False)
    p = _player_para_if(dry_run=False)
    paso = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "Error", "saltar_si_no": 3})
    # No existe → condición False → saltar el bloque (1 + 3)
    assert Player._evaluar_if(p, paso) == 4


def test_evaluar_if_negado_invierte(monkeypatch):
    import core.window_utils as wu
    # La ventana NO existe...
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.5: False)
    p = _player_para_if(dry_run=False)
    # ...pero con negar=True, la condición es "NO existe" → True → ejecutar
    paso = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "X", "negar": True, "saltar_si_no": 2})
    assert Player._evaluar_if(p, paso) == 1


def test_evaluar_if_negado_con_ventana_presente_salta(monkeypatch):
    import core.window_utils as wu
    monkeypatch.setattr(wu, "existe_ventana", lambda title_re, timeout_s=0.5: True)
    p = _player_para_if(dry_run=False)
    # negar=True + ventana existe → condición "NO existe" = False → saltar
    paso = Step(tipo=StepType.IF_VENTANA, extra={"ventana": "X", "negar": True, "saltar_si_no": 2})
    assert Player._evaluar_if(p, paso) == 3


def test_evaluar_if_sin_patron_no_existe(monkeypatch):
    p = _player_para_if(dry_run=False)
    paso = Step(tipo=StepType.IF_VENTANA, extra={"saltar_si_no": 2})
    # Sin patrón → existe=False → condición False → saltar
    assert Player._evaluar_if(p, paso) == 3


def test_loop_maneja_if_ventana():
    """Inspección estática: el loop trata IF_VENTANA como control de flujo."""
    import inspect
    src = inspect.getsource(Player.ejecutar_dni)
    assert "IF_VENTANA" in src
    assert "_evaluar_if" in src


def test_macro_con_if_roundtrip(tmp_path):
    macro = Macro(nombre="m", pasos=[
        Step(tipo=StepType.IF_VENTANA, extra={"ventana": "Error", "negar": False, "saltar_si_no": 2}),
        Step(tipo=StepType.SEND_KEYS, valor="{ESC}"),
        Step(tipo=StepType.SEND_KEYS, valor="{ENTER}"),
        Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 1}),
    ])
    path = tmp_path / "m.yaml"
    macro.save(path)
    cargada = Macro.load(path)
    assert cargada.pasos[0].tipo == StepType.IF_VENTANA
    assert cargada.pasos[0].extra["saltar_si_no"] == 2
