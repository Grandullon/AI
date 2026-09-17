"""Al clicar en una lista o tabla hay que quedarse con la FILA, no con la
celda de propiedad.

Caso real que lo destapó: en el Explorador de Windows, al pulsar sobre la
carpeta "macros", la macro guardaba «Click en Nombre» — el título de la
columna — y al reproducir habría abierto el archivo equivocado.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import _elemento_significativo


class _Info:
    def __init__(self, control_type, automation_id=""):
        self.control_type = control_type
        self.automation_id = automation_id


class _Elem:
    """Elemento de árbol UIA falso."""
    def __init__(self, control_type, nombre="", automation_id="", padre=None):
        self.element_info = _Info(control_type, automation_id)
        self._nombre = nombre
        self._padre = padre

    def window_text(self):
        return self._nombre

    def parent(self):
        return self._padre


def _explorador():
    """Árbol como el del Explorador: fila «macros» con su celda «Nombre»."""
    lista = _Elem("List", "Lista de archivos")
    fila = _Elem("ListItem", "macros", padre=lista)
    celda = _Elem("Edit", "Nombre", "System.ItemNameDisplay", padre=fila)
    return celda, fila


def test_sube_de_la_celda_a_la_fila():
    celda, fila = _explorador()
    assert celda.window_text() == "Nombre"          # lo que había antes
    assert _elemento_significativo(celda) is fila   # lo que queremos
    assert _elemento_significativo(celda).window_text() == "macros"


def test_si_ya_estamos_en_la_fila_no_se_toca():
    _, fila = _explorador()
    assert _elemento_significativo(fila) is fila


def test_celda_a_dos_niveles_de_la_fila():
    """A veces hay un contenedor intermedio entre la celda y la fila."""
    fila = _Elem("ListItem", "macros")
    grupo = _Elem("Custom", "", padre=fila)
    celda = _Elem("Edit", "Nombre", padre=grupo)
    assert _elemento_significativo(celda) is fila


def test_un_campo_de_formulario_no_se_toca():
    """Cambio acotado: sin una fila por encima, todo sigue igual."""
    ventana = _Elem("Window", "GERHONTE")
    panel = _Elem("Pane", "", padre=ventana)
    campo = _Elem("Edit", "Primer apellido", padre=panel)
    assert _elemento_significativo(campo) is campo


def test_fila_sin_nombre_se_descarta():
    """Si la fila no se llama de nada, la celda al menos dice algo."""
    fila = _Elem("ListItem", "")
    celda = _Elem("Edit", "Nombre", padre=fila)
    assert _elemento_significativo(celda) is celda


def test_no_sube_indefinidamente():
    """Una fila muy arriba no cuenta: no queremos acabar seleccionando
    media ventana."""
    fila = _Elem("ListItem", "macros")
    e = fila
    for _ in range(6):
        e = _Elem("Custom", "", padre=e)
    celda = _Elem("Edit", "Nombre", padre=e)
    assert _elemento_significativo(celda) is celda


def test_blindado_ante_arboles_rotos():
    class _Roto:
        element_info = _Info("Edit")
        def window_text(self): raise RuntimeError("boom")
        def parent(self): raise RuntimeError("boom")
    roto = _Roto()
    assert _elemento_significativo(roto) is roto
    assert _elemento_significativo(None) is None


def test_el_ancla_tambien_sale_bien():
    """El ancla se calcula sobre la fila, así que guarda «macros» y no
    «Nombre» (que casaría con cualquier fila de la lista)."""
    import core.recorder as rec
    celda, fila = _explorador()

    class _R:
        left, top, right, bottom = 200, 150, 400, 170
    fila.rectangle = lambda: _R()

    ancla = rec._ancla_desde_punto(_elemento_significativo(celda), 300, 160)
    assert ancla["texto"] == "macros"


def test_el_selector_completo_usa_la_fila(monkeypatch):
    """De punta a punta: _selector_desde_punto devuelve «macros»."""
    import core.recorder as rec
    celda, fila = _explorador()

    class _R:
        left, top, right, bottom = 200, 150, 400, 170
        def width(self): return 200
        def height(self): return 20
    fila.rectangle = lambda: _R()
    fila.class_name = lambda: "UIItem"
    fila.top_level_parent = lambda: fila
    fila.handle = 0

    monkeypatch.setattr(rec, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(
        rec, "Desktop",
        lambda backend=None: type(
            "D", (), {"from_point": staticmethod(lambda x, y: celda)})(),
        raising=False,
    )
    sel, desc, _win, ancla = rec._selector_desde_punto(300, 160)
    assert sel.name == "macros"
    assert sel.control_type == "ListItem"
    assert desc == "macros"
    assert ancla["texto"] == "macros"


# ==================== el revisor lo detecta en macros ya grabadas ====================

def test_el_revisor_avisa_de_los_selectores_de_columna():
    """Las macros grabadas antes del arreglo llevan este fallo dentro; el
    revisor tiene que decirlo en vez de dejarlas pasar."""
    from core.revisor_macro import ALTO, revisar
    from core.step_model import Macro, Selector, Step, StepType

    paso = Step(
        tipo=StepType.CLICK_CONTROL,
        selector=Selector(control_type="Edit", name="Nombre",
                          auto_id="System.ItemNameDisplay",
                          class_name="UIProperty"),
        descripcion="Click en Nombre",
    )
    macro = Macro(nombre="m", pasos=[paso], ventana_principal="Explorador")
    aviso = next(a for a in revisar(macro).avisos
                 if "columna" in a.titulo)
    assert aviso.gravedad == ALTO
    assert aviso.paso == 1
    assert "Nombre" in aviso.detalle


def test_el_revisor_no_se_queja_de_un_selector_de_fila():
    from core.revisor_macro import revisar
    from core.step_model import Macro, Selector, Step, StepType

    paso = Step(
        tipo=StepType.CLICK_CONTROL,
        selector=Selector(control_type="ListItem", name="macros",
                          class_name="UIItem"),
    )
    macro = Macro(nombre="m", pasos=[paso], ventana_principal="Explorador")
    assert not any("columna" in a.titulo for a in revisar(macro).avisos)
