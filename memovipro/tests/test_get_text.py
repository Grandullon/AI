"""Tests de la lectura/verificación de texto (GET_TEXT + verificar_texto).

Cubre el motor core.text_read (con controles pywinauto simulados), el
round-trip del modelo (StepType.GET_TEXT y campo verificar_texto), y el
cableado del Player por inspección.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.text_read import extraer_texto_de_control, texto_contiene, normalizar
from core.step_model import Step, StepType, render_step


# ---- controles fake estilo pywinauto ----
class _FakeText:
    def __init__(self, t): self._t = t
    def window_text(self): return self._t


class _FakeCtrl:
    def __init__(self, name="", value=None, hijos_texto=None, legacy=None):
        self._name = name
        self._value = value
        self._hijos = [_FakeText(t) for t in (hijos_texto or [])]
        self._legacy = legacy

    def window_text(self): return self._name

    def get_value(self):
        if self._value is None:
            raise Exception("sin value pattern")
        return self._value

    def legacy_properties(self):
        return self._legacy or {}

    def descendants(self, control_type=None):
        return self._hijos


# ==================== extraer_texto_de_control ====================

def test_lee_name():
    c = _FakeCtrl(name="Aceptar")
    assert extraer_texto_de_control(c) == "Aceptar"


def test_lee_value_pattern():
    c = _FakeCtrl(name="", value="12345678Z")
    assert extraer_texto_de_control(c) == "12345678Z"


def test_lee_value_legacy_si_no_hay_get_value():
    c = _FakeCtrl(name="", value=None, legacy={"Value": "hola"})
    assert extraer_texto_de_control(c) == "hola"


def test_combina_name_value_y_descendientes_sin_duplicar():
    c = _FakeCtrl(name="Informe", value="OK", hijos_texto=["Informe", "generado", "OK"])
    # "Informe" y "OK" no se duplican; orden preservado
    assert extraer_texto_de_control(c) == "Informe OK generado"


def test_control_sin_texto_devuelve_vacio():
    class _Mudo:
        def window_text(self): return ""
        def get_value(self): raise Exception()
        def legacy_properties(self): return {}
        def descendants(self, control_type=None): return []
    assert extraer_texto_de_control(_Mudo()) == ""


def test_fuente_que_lanza_no_rompe_el_resto():
    class _Roto:
        def window_text(self): raise Exception("boom")
        def get_value(self): raise Exception()
        def legacy_properties(self): raise Exception()
        def descendants(self, control_type=None): return [_FakeText("recuperado")]
    assert extraer_texto_de_control(_Roto()) == "recuperado"


def test_sin_descendientes_si_se_pide():
    c = _FakeCtrl(name="A", hijos_texto=["B", "C"])
    assert extraer_texto_de_control(c, incluir_descendientes=False) == "A"


# ==================== texto_contiene ====================

def test_contiene_case_insensitive_sin_acentos():
    assert texto_contiene("Guardado correctamente", "guardado")
    assert texto_contiene("Informe generado", "INFORME")
    assert texto_contiene("Atención: revisar", "atencion")
    assert not texto_contiene("todo bien", "error")


def test_contiene_vacio_es_true():
    assert texto_contiene("lo que sea", "") is True


def test_normalizar_colapsa_espacios():
    assert normalizar("a\n\n  b   c\t") == "a b c"


# ==================== modelo: round-trip ====================

def test_get_text_step_type_existe():
    assert StepType.GET_TEXT.value == "get_text"


def test_verificar_texto_roundtrip():
    paso = Step(
        tipo=StepType.CLICK_CONTROL,
        verificar_texto="Guardado",
        verificar_timeout_s=8.0,
    )
    d = paso.to_dict()
    assert d["verificar_texto"] == "Guardado"
    assert d["verificar_timeout_s"] == 8.0
    cargado = Step.from_dict(d)
    assert cargado.verificar_texto == "Guardado"
    assert cargado.verificar_timeout_s == 8.0


def test_get_text_extra_roundtrip():
    paso = Step(
        tipo=StepType.GET_TEXT,
        extra={"guardar_en": "TEXTO_LEIDO", "contiene": "OK"},
        descripcion="Leer texto",
    )
    cargado = Step.from_dict(paso.to_dict())
    assert cargado.tipo == StepType.GET_TEXT
    assert cargado.extra["guardar_en"] == "TEXTO_LEIDO"
    assert cargado.extra["contiene"] == "OK"


def test_render_step_sustituye_verificar_texto():
    paso = Step(tipo=StepType.CLICK_CONTROL, verificar_texto="DNI {DNI}")
    out = render_step(paso, {"DNI": "12345678Z"})
    assert out.verificar_texto == "DNI 12345678Z"


def test_verificar_texto_no_colisiona_con_verificar_ventana_en_timeout():
    """Si hay verificar_ventana, el timeout se serializa una vez; si solo
    hay verificar_texto, también se serializa correctamente."""
    p1 = Step(tipo=StepType.CLICK_CONTROL, verificar_texto="X", verificar_timeout_s=5.0)
    d1 = p1.to_dict()
    assert d1.get("verificar_timeout_s") == 5.0
    assert Step.from_dict(d1).verificar_timeout_s == 5.0


# ==================== Player: cableado ====================

def test_player_dispatch_get_text():
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._dispatch)
    assert "GET_TEXT" in src
    assert "_get_text" in src


def test_player_loop_verifica_texto():
    import inspect
    from core.player import Player
    src = inspect.getsource(Player.ejecutar_dni)
    assert "verificar_texto" in src
    assert "_verificar_texto_en_paso" in src


def test_get_text_guarda_en_ctx():
    """_get_text guarda el texto leído en self._ctx en MAYÚSCULAS."""
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    p._ctx = {}
    p._leer_texto = lambda paso: "Informe generado"
    paso = Step(tipo=StepType.GET_TEXT, extra={"guardar_en": "texto_leido"})
    Player._get_text(p, paso)
    assert p._ctx["TEXTO_LEIDO"] == "Informe generado"


def test_get_text_contiene_falla_si_no_aparece():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    p._ctx = {}
    p._leer_texto = lambda paso: "todo mal"
    paso = Step(tipo=StepType.GET_TEXT, extra={"contiene": "correcto"})
    try:
        Player._get_text(p, paso)
        assert False, "debió lanzar por no contener el texto"
    except ValueError as exc:
        assert "correcto" in str(exc)


def test_get_text_dry_run_no_lee():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = True
    p._ctx = {}
    llamado = {"n": 0}
    p._leer_texto = lambda paso: llamado.__setitem__("n", 1)
    Player._get_text(p, Step(tipo=StepType.GET_TEXT, extra={"guardar_en": "X"}))
    assert llamado["n"] == 0  # en dry-run no lee
