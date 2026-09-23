"""Buscar el control por su NOMBRE antes que por dónde estaba.

Escrito a partir de la macro «1-INCI-GRABADAS-HOY» del usuario, que
fallaba siempre. Tenía 37 clics, TODOS con un selector bueno
(«TreeItem Incidencias», «Button Guardar», «RadioButton Todas»)... y no
se usaba ninguno, porque el selector solo entraba en juego si la macro
tenía rellenado el campo «ventana principal», que venía vacío.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Macro, Selector, Step, StepType


def _paso(name="Guardar", control_type="Button", auto_id=None,
          ventana="INFORMES (FABPINF01)"):
    return Step(
        tipo=StepType.CLICK_CONTROL,
        selector=Selector(control_type=control_type, name=name, auto_id=auto_id),
        extra={
            "fallback_xy": [100, 200],
            "win_rel": {"title": ventana, "proceso": "exped.exe",
                        "fx": .5, "fy": .5, "w": 800, "h": 600,
                        "dx": 400, "dy": 300},
        },
    )


class _Ctrl:
    def __init__(self, existe=True):
        self._existe = existe
        self.clicado = False

    def exists(self, timeout=0):
        return self._existe

    def wait(self, estado, timeout=0):
        return self

    def click_input(self, button="left"):
        self.clicado = True

    def double_click_input(self, button="left"):
        self.clicado = True


class _Spec:
    """Ventana falsa: devuelve el control solo con ciertos criterios."""
    def __init__(self, acepta):
        self.acepta = acepta
        self.pedidos = []

    def child_window(self, **kw):
        self.pedidos.append(kw)
        return _Ctrl(existe=self.acepta(kw))


# ==================== el selector manda ====================

def test_el_selector_se_usa_aunque_no_haya_ventana_principal(monkeypatch):
    """EL FALLO REPORTADO. Sin «ventana principal» se clicaba por
    coordenadas y se ignoraba el selector."""
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="")
    usados = []
    monkeypatch.setattr(Player, "_resolve_control",
                        lambda self, paso: usados.append("SELECTOR") or _Ctrl())
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: usados.append("COORDS"))
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: usados.append("VENTANA") or True)

    Player._click_control(p, _paso())
    assert usados == ["SELECTOR"]


def test_si_el_selector_falla_siguen_los_respaldos(monkeypatch):
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="")
    orden = []
    monkeypatch.setattr(Player, "_resolve_control",
                        lambda self, paso: (_ for _ in ()).throw(RuntimeError("no está")))
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: orden.append("VENTANA") or True)
    Player._click_control(p, _paso())
    assert orden == ["VENTANA"]


# ==================== identificadores que cambian ====================

def test_reintenta_sin_el_identificador_que_cambia():
    """GERHONTE es Delphi: el identificador automático es el número de
    ventana del sistema («71442») y cambia en cada ejecución. El nombre y
    el tipo, no."""
    from core.player import Player

    p = Player.__new__(Player)
    # Solo acepta la búsqueda SIN auto_id
    spec = _Spec(lambda kw: "auto_id" not in kw)
    ctrl = Player._buscar_en(p, spec, {
        "title": "Todas", "control_type": "RadioButton", "auto_id": "71494",
    }, espera=0.1)
    assert ctrl is not None
    assert len(spec.pedidos) == 2
    assert "auto_id" in spec.pedidos[0]      # primero con todo
    assert "auto_id" not in spec.pedidos[1]  # luego sin él


def test_si_casa_a_la_primera_no_reintenta():
    from core.player import Player
    p = Player.__new__(Player)
    spec = _Spec(lambda kw: True)
    ctrl = Player._buscar_en(p, spec, {
        "title": "Guardar", "control_type": "Button", "auto_id": "1",
    }, espera=0.1)
    assert ctrl is not None and len(spec.pedidos) == 1


def test_sin_nombre_no_se_quita_el_identificador():
    """Si el identificador es lo ÚNICO que distingue al control, quitarlo
    dejaría una búsqueda que casa con cualquier cosa."""
    from core.player import Player
    p = Player.__new__(Player)
    spec = _Spec(lambda kw: "auto_id" not in kw)
    ctrl = Player._buscar_en(p, spec, {"auto_id": "136866"}, espera=0.1)
    assert ctrl is None
    assert len(spec.pedidos) == 1


def test_si_no_esta_en_ningun_intento_devuelve_none():
    from core.player import Player
    p = Player.__new__(Player)
    spec = _Spec(lambda kw: False)
    assert Player._buscar_en(p, spec, {"title": "X", "control_type": "Button"},
                             espera=0.1) is None


# ==================== acotar a la ventana del paso ====================

def test_no_acota_a_ventanas_que_no_son_ventanas():
    from core.player import Player
    p = Player.__new__(Player)
    # Escritorio: no se acota ahí
    assert Player._spec_ventana_del_paso(p, _paso(ventana="Program Manager")) is None
    assert Player._spec_ventana_del_paso(p, _paso(ventana="")) is None


def test_la_macro_real_del_usuario_tiene_selectores_utiles():
    """Comprobación sobre los datos reales: los 37 clics traían selector,
    y la mayoría con nombre. Era todo aprovechable."""
    ejemplos = [
        ("TreeItem", "Incidencias", None),
        ("TreeItem", "Listado de incidencias", None),
        ("RadioButton", "Todas", "71494"),
        ("Button", "Guardar", "1"),
        ("ListItem", "EXPEDIENTES", None),
        ("MenuItem", "Archivo", None),
        ("ComboBox", "Tipo:", "FileTypeControlHost"),
    ]
    for tipo, nombre, auto_id in ejemplos:
        s = Selector(control_type=tipo, name=nombre, auto_id=auto_id)
        assert not s.is_empty()
        assert s.name        # hay nombre: se puede buscar aunque se mueva


# ==================== un selector tiene que identificar ALGO ====================
#
# Regresión grave: usar el selector SIEMPRE hizo que un tercio de los
# clics de cada macro pulsaran el control equivocado. «Button» a secas
# casa con el primer botón de la ventana, y los paneles de Delphi traen
# un identificador que cambia en cada ejecución.

def test_un_nombre_identifica():
    for tipo, nombre in (("Button", "Guardar"), ("TreeItem", "Incidencias"),
                         ("MenuItem", "Archivo"), ("ListItem", "EXPEDIENTES")):
        assert Selector(control_type=tipo, name=nombre).identifica_algo()


def test_solo_el_tipo_NO_identifica():
    """«El primer botón de la ventana» no es un destino."""
    assert not Selector(control_type="Button").identifica_algo()
    assert not Selector(control_type="Pane").identifica_algo()
    assert not Selector(control_type="Edit").identifica_algo()


def test_un_identificador_de_delphi_no_identifica():
    """En GERHONTE el identificador es el número de ventana del sistema y
    cambia en cada arranque: con él no se encuentra nada, y sin él la
    búsqueda casa con cualquier panel."""
    for aid in ("11011536", "136866", "71632", "71606"):
        assert not Selector(control_type="Pane", auto_id=aid).identifica_algo()


def test_un_identificador_estable_si_identifica():
    assert Selector(control_type="ComboBox",
                    auto_id="FileTypeControlHost").identifica_algo()
    assert Selector(control_type="Button", auto_id="1").identifica_algo()


def test_un_selector_vacio_no_identifica():
    assert not Selector().identifica_algo()
    assert not Selector(class_name="TPanel").identifica_algo()


def test_los_pasos_flojos_vuelven_a_la_posicion(monkeypatch):
    """Los nueve pasos de su macro con selector flojo deben ir por
    posición, como antes, sin tocar el buscador."""
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="")
    orden = []
    monkeypatch.setattr(Player, "_resolve_control",
                        lambda self, paso: orden.append("SELECTOR") or _Ctrl())
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: orden.append("VENTANA") or True)

    Player._click_control(p, _paso(name=None, control_type="Button"))
    assert orden == ["VENTANA"]      # ni se intenta buscar

    orden.clear()
    Player._click_control(p, _paso(name=None, control_type="Pane", auto_id="11011536"))
    assert orden == ["VENTANA"]


def test_los_pasos_buenos_siguen_usando_el_nombre(monkeypatch):
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="")
    orden = []
    monkeypatch.setattr(Player, "_resolve_control",
                        lambda self, paso: orden.append("SELECTOR") or _Ctrl())
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: orden.append("VENTANA") or True)
    Player._click_control(p, _paso(name="Guardar"))
    assert orden == ["SELECTOR"]


def test_el_reintento_sin_identificador_exige_nombre():
    """Quitar el identificador de «Pane auto_id=71606» dejaría una
    búsqueda que casa con cualquier panel."""
    from core.player import Player
    p = Player.__new__(Player)
    spec = _Spec(lambda kw: "auto_id" not in kw)
    assert Player._buscar_en(p, spec, {
        "control_type": "Pane", "auto_id": "71606"}, espera=0.1) is None
    assert len(spec.pedidos) == 1        # no hubo segundo intento
