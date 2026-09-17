"""Tests del ancla de texto ("clica donde pone X" automático) y del
borrado múltiple en la pestaña Macros."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.text_anchor import (
    construir_ancla, punto_desde_ancla, punto_desde_centro, texto_util_para_ancla,
)


# ==================== qué texto sirve como ancla ====================

def test_texto_util_acepta_etiquetas_normales():
    assert texto_util_para_ancla("Aceptar")
    assert texto_util_para_ancla("Nº de historia")
    assert texto_util_para_ancla("  Guardar   y  cerrar ")


def test_texto_util_rechaza_basura():
    assert not texto_util_para_ancla("")
    assert not texto_util_para_ancla(None)
    assert not texto_util_para_ancla("...")
    assert not texto_util_para_ancla("3")
    assert not texto_util_para_ancla("X")          # una sola letra
    assert not texto_util_para_ancla("a" * 200)    # un párrafo, no un rótulo


# ==================== construcción del ancla ====================

def test_ancla_con_clic_en_el_centro_del_texto():
    a = construir_ancla("Aceptar", (100, 50, 200, 80), 150, 65)
    assert a == {"texto": "Aceptar", "dx": 0, "dy": 0}


def test_ancla_guarda_el_desplazamiento_dentro_del_control():
    """Clic en el borde del propio botón: desplazamiento pequeño."""
    a = construir_ancla("Aceptar", (100, 50, 200, 80), 190, 60)
    assert a["texto"] == "Aceptar"
    assert a["dx"] == 40         # 190 - 150 (centro x)
    assert a["dy"] == -5


def test_ancla_rechaza_clic_fuera_del_control():
    """El campo que hay LEJOS del rótulo ya no se ancla.

    Se intentó y era peligroso: al reproducir, el desplazamiento se
    aplicaba desde el centro de otro elemento y el clic se iba a cientos
    de píxeles, muy convencido."""
    assert construir_ancla("DNI", (100, 50, 140, 70), 250, 60) is None


def test_ancla_rechaza_controles_enormes():
    """El centro de un panel gigante no dice nada sobre dónde clicaste."""
    assert construir_ancla("Panel", (0, 0, 1900, 1000), 50, 50) is None


def test_ancla_rechaza_clic_demasiado_lejos():
    assert construir_ancla("Aceptar", (0, 0, 60, 20), 1500, 10) is None


def test_ancla_rechaza_rect_invalido():
    assert construir_ancla("Aceptar", (200, 50, 100, 80), 150, 65) is None
    assert construir_ancla("Aceptar", "no es un rect", 1, 1) is None


# ==================== reconstrucción del punto ====================

def test_punto_desde_ancla_sigue_al_texto_cuando_se_mueve():
    a = construir_ancla("Aceptar", (100, 50, 200, 80), 190, 60)
    # La ventana se ha movido 300px a la derecha y 100 hacia abajo
    assert punto_desde_ancla((400, 150, 500, 180), a) == (490, 160)


def test_punto_desde_centro_ocr():
    a = {"texto": "DNI", "dx": 30, "dy": -5}
    assert punto_desde_centro(120, 60, a) == (150, 55)


def test_punto_sin_ancla_es_none():
    assert punto_desde_ancla((0, 0, 10, 10), None) is None
    assert punto_desde_centro(1, 1, {}) is None


# ==================== compatibilidad con macros antiguas ====================

def test_macro_antigua_sin_ancla_no_cambia():
    """Un paso grabado antes de esta función no gana claves nuevas."""
    from core.step_model import Step
    s = Step.from_dict({"tipo": "click_at_xy", "extra": {"x": 10, "y": 20}})
    assert "texto_ancla" not in (s.extra or {})
    assert s.to_dict()["extra"] == {"x": 10, "y": 20}


def test_click_at_xy_sin_respaldos_clica_las_coordenadas(monkeypatch):
    """Sin ancla/win_rel/imagen se comporta EXACTAMENTE como antes."""
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(
        Player, "_click_xy",
        lambda self, x, y, button="left", double=False: clics.append((x, y, button, double)),
    )
    Player._click_at_xy(p, Step(tipo=StepType.CLICK_AT_XY, extra={"x": 7, "y": 9}))
    assert clics == [(7, 9, "left", False)]


def test_macro_antigua_no_cambia_de_comportamiento(monkeypatch):
    """Un paso grabado ANTES de esto se reproduce igual que siempre.

    Sus respaldos no guardan el tamaño de la ventana, y sin ese dato no se
    puede distinguir "se ha movido" de "ha cambiado de tamaño", donde
    escalar por fracciones se equivoca. No tocamos lo que ya funciona."""
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(
        Player, "_click_xy",
        lambda self, x, y, button="left", double=False: clics.append((x, y)),
    )
    for nombre in ("_click_por_ancla", "_click_window_relative", "_click_imagen"):
        monkeypatch.setattr(
            Player, nombre,
            lambda self, *a, **k: clics.append("RESPALDO") or True,
        )
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 7, "y": 9,
        "win_rel": {"title": "GERHONTE", "fx": 0.5, "fy": 0.5},   # sin w/h
        "img_b64": "loquesea",
        "texto_ancla": {"texto": "Aceptar", "dx": 0, "dy": 0},
    })
    Player._click_at_xy(p, paso)
    assert clics == [(7, 9)]


def test_paso_nuevo_usa_la_ventana_antes_que_el_ancla(monkeypatch):
    """Orden: ventana → imagen → texto → coordenadas. El ancla es el
    último recurso, no el primero."""
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = False
    orden = []
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: orden.append("COORDS"))
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: orden.append("VENTANA") or True)
    monkeypatch.setattr(Player, "_click_imagen",
                        lambda self, *a, **k: orden.append("IMAGEN") or True)
    monkeypatch.setattr(Player, "_click_por_ancla",
                        lambda self, *a, **k: orden.append("ANCLA") or True)
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 7, "y": 9,
        "win_rel": {"title": "GERHONTE", "fx": .5, "fy": .5, "w": 800, "h": 600},
        "img_b64": "x", "texto_ancla": {"texto": "Aceptar", "dx": 0, "dy": 0},
    })
    Player._click_at_xy(p, paso)
    assert orden == ["VENTANA"]


def test_solo_coordenadas_fuerza_el_comportamiento_literal(monkeypatch):
    """Escotilla de escape si algún paso viejo se porta raro."""
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(
        Player, "_click_xy",
        lambda self, x, y, button="left", double=False: clics.append((x, y)),
    )
    monkeypatch.setattr(
        Player, "_click_por_ancla",
        lambda self, ancla, button="left", double=False: clics.append("ANCLA") or True,
    )
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 7, "y": 9, "solo_coordenadas": True,
        "texto_ancla": {"texto": "Aceptar", "dx": 0, "dy": 0},
    })
    Player._click_at_xy(p, paso)
    assert clics == [(7, 9)]


def test_ancla_vacia_no_intenta_buscar():
    from core.player import Player
    p = Player.__new__(Player)
    assert Player._click_por_ancla(p, None) is False
    assert Player._click_por_ancla(p, {"texto": ""}) is False


# ==================== borrado múltiple ====================

def test_borrado_multiple_desplaza_las_marcas():
    """Borrar varias filas a la vez deja los puntos de análisis donde toca."""
    from core.debug_marks import shift_on_remove_varios
    # Lista [0..9], borramos las filas 2 y 5, con una marca en la 7.
    assert shift_on_remove_varios({7}, [2, 5]) == {5}
    # Marca sobre una fila borrada: desaparece.
    assert shift_on_remove_varios({2, 7}, [2, 5]) == {5}
    # Orden de entrada irrelevante.
    assert shift_on_remove_varios({7}, [5, 2]) == {5}
    # Sin filas, no cambia nada.
    assert shift_on_remove_varios({3}, []) == {3}


def test_borrado_multiple_equivale_a_borrar_de_una_en_una():
    """Propiedad: el resultado coincide con borrar índices reales."""
    import random
    from core.debug_marks import shift_on_remove_varios
    random.seed(7)
    for _ in range(500):
        n = random.randint(1, 12)
        filas = sorted(random.sample(range(n), random.randint(1, n)))
        marcas = set(random.sample(range(n), random.randint(0, n)))
        # Referencia: qué posición ocupa cada marca superviviente al final.
        vivos = [i for i in range(n) if i not in filas]
        esperado = {vivos.index(m) for m in marcas if m in vivos}
        assert shift_on_remove_varios(marcas, filas) == esperado


# ==================== los fallos que encontró la revisión ====================

def test_ancla_no_casa_por_subcadena():
    """El ancla "Alta" NO debe casar con "Dar de alta al paciente".

    Con comparación laxa, y cogiendo el primero del árbol, el clic
    acababa en la barra superior en vez de en el botón grabado."""
    from core.text_anchor import puntuar_candidato
    assert puntuar_candidato("Dar de alta al paciente", "Alta", (0, 0, 200, 30)) is None
    assert puntuar_candidato("Buscar por DNI o NHC", "DNI", (0, 0, 200, 30)) is None
    # Exacto sí casa, ignorando mayúsculas y acentos
    assert puntuar_candidato("ALTA", "alta", (0, 0, 60, 20)) is not None
    assert puntuar_candidato("Informacion", "Información", (0, 0, 90, 20)) is not None


def test_entre_varios_exactos_gana_el_mas_pequeno():
    """El rótulo concreto antes que el contenedor que lo repite."""
    from core.text_anchor import puntuar_candidato
    pequeno = puntuar_candidato("Guardar", "Guardar", (0, 0, 80, 24))
    grande = puntuar_candidato("Guardar", "Guardar", (0, 0, 400, 120))
    assert pequeno < grande


def test_rect_degenerado_se_rechaza():
    """Los controles de pestañas no activas devuelven 0,0,0,0 y el clic
    se iba a la esquina de la pantalla."""
    from core.text_anchor import rect_utilizable
    assert not rect_utilizable((0, 0, 0, 0))
    assert not rect_utilizable((100, 50, 90, 40))     # invertido
    assert not rect_utilizable((0, 0, 1900, 900))     # panel gigante
    assert rect_utilizable((100, 50, 200, 80))


def test_punto_fuera_de_la_ventana_se_rechaza():
    from core.text_anchor import punto_dentro
    ventana = (100, 100, 900, 700)
    assert punto_dentro((500, 400), ventana)
    assert not punto_dentro((50, 400), ventana)       # a la izquierda
    assert not punto_dentro((-31968, -31993), ventana)  # ventana minimizada
    assert not punto_dentro(None, ventana)


def test_ocr_solo_si_clicaste_encima_del_texto():
    """El OCR parte del centro de la PALABRA y la grabación partió del
    centro del CONTROL: con desplazamientos grandes son marcos distintos
    y el clic se desvía."""
    from core.text_anchor import ancla_admite_ocr
    assert ancla_admite_ocr({"texto": "Aceptar", "dx": 0, "dy": 0})
    assert ancla_admite_ocr({"texto": "Aceptar", "dx": 20, "dy": -10})
    assert not ancla_admite_ocr({"texto": "DNI", "dx": 200, "dy": 0})
    assert not ancla_admite_ocr("no soy un diccionario")


def test_ancla_sin_ventana_de_trabajo_no_busca(monkeypatch):
    """Sin ventana definida, buscar por todo el escritorio clicaba en
    otra aplicación (o en el propio MemoviPro, que muestra el texto de
    los pasos en su tabla)."""
    from core.player import Player
    from core.step_model import Macro

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="")
    llamadas = []
    monkeypatch.setattr(Player, "_ventana_de_trabajo",
                        lambda self: llamadas.append("BUSCO") or (None, None))
    assert Player._click_por_ancla(p, {"texto": "Guardar", "dx": 0, "dy": 0}) is False
    assert llamadas == []          # ni siquiera lo intenta


def test_ancla_mal_formada_no_rompe_la_cascada():
    """Un YAML editado a mano con `texto_ancla: Guardar` (una cadena, no
    un diccionario) dejaba el paso en KO donde antes funcionaba."""
    from core.player import Player
    p = Player.__new__(Player)          # sin __init__: ni dry_run ni macro
    for malo in ("Guardar", ["Guardar"], 42, None, {}):
        assert Player._click_por_ancla(p, malo) is False


def test_ventana_redimensionada_no_escala_a_ciegas(monkeypatch):
    """Las aplicaciones Win32 clásicas anclan sus controles
    arriba-izquierda: si la ventana crece, escalar por fracciones se va
    cientos de píxeles y las coordenadas grabadas eran correctas."""
    import core.player as pl
    from core.player import Player

    class _R:
        left, top, right, bottom = 100, 100, 1500, 1100
        def width(self): return 1400
        def height(self): return 1000

    class _Win:
        def exists(self, timeout=1.0): return True
        def is_minimized(self): return False
        def is_visible(self): return True
        def rectangle(self): return _R()

    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(pl, "Desktop", lambda backend=None: type(
        "D", (), {"window": staticmethod(lambda **k: _Win())})())
    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: clics.append((x, y)))
    # Grabado con la ventana de 1000x700; ahora mide 1400x1000
    ok = Player._click_window_relative(p, {
        "title": "GERHONTE", "fx": 0.2, "fy": 0.2,
        "w": 1000, "h": 700, "dx": 200, "dy": 140,
    })
    assert ok is False and clics == []


def test_ventana_solo_movida_usa_traslacion_exacta(monkeypatch):
    """Mismo tamaño = solo se ha movido: traslación pura, sin el error de
    1 px que metía el redondeo del escalado."""
    import core.player as pl
    from core.player import Player

    class _R:
        left, top, right, bottom = 150, 150, 1150, 850
        def width(self): return 1000
        def height(self): return 700

    class _Win:
        def exists(self, timeout=1.0): return True
        def is_minimized(self): return False
        def is_visible(self): return True
        def rectangle(self): return _R()

    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(pl, "Desktop", lambda backend=None: type(
        "D", (), {"window": staticmethod(lambda **k: _Win())})())
    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: clics.append((x, y)))
    # Grabado en (300,250) con la ventana en (100,100): dx=200, dy=150
    ok = Player._click_window_relative(p, {
        "title": "GERHONTE", "fx": 0.2, "fy": 0.2143,
        "w": 1000, "h": 700, "dx": 200, "dy": 150,
    })
    assert ok is True
    assert clics == [(350, 300)]      # exacto, sin desviación de 1 px


def test_ventana_minimizada_no_clica_fuera_de_pantalla(monkeypatch):
    """Una ventana minimizada casa igual en pywinauto y su rectángulo es
    del orden de (-32000,-32000): el clic se iba fuera de la pantalla."""
    import core.player as pl
    from core.player import Player

    class _R:
        # Rectángulo REAL de una ventana minimizada en Windows.
        left, top, right, bottom = -32000, -32000, -31840, -31972
        def width(self): return 160
        def height(self): return 28

    class _Win:
        def exists(self, timeout=1.0): return True
        def is_minimized(self): return True
        def is_visible(self): return False
        def rectangle(self): return _R()

    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(pl, "Desktop", lambda backend=None: type(
        "D", (), {"window": staticmethod(lambda **k: _Win())})())
    p = Player.__new__(Player)
    p.dry_run = False
    clics = []
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: clics.append((x, y)))
    # Macro ANTIGUA (sin tamaño guardado): aquí la única defensa es
    # comprobar que la ventana está visible.
    ok = Player._click_window_relative(p, {
        "title": "GERHONTE", "fx": .5, "fy": .5,
    })
    assert ok is False and clics == []
    # Y con tamaño guardado también, por partida doble.
    assert Player._click_window_relative(p, {
        "title": "GERHONTE", "fx": .5, "fy": .5, "w": 1000, "h": 700,
    }) is False
    assert clics == []


# ==================== confirmación de borrado ====================

def test_mensaje_de_borrado_no_finge_un_rango():
    """Con la selección 3, 7 y 40, decir "del 3 al 40" se lee como 38
    pasos. Hay que listar los de verdad."""
    import re as _re
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    ns = {}
    cuerpo = src.split("def _texto_confirmar_borrado")[1].split("\n    def ")[0]
    exec("def _texto_confirmar_borrado" + cuerpo, ns)
    f = ns["_texto_confirmar_borrado"]

    assert f([4]) == "¿Eliminar el paso 5?"
    assert "del 3 al 5" in f([2, 3, 4])            # contiguos: rango real
    suelta = f([2, 6, 39])
    assert "3, 7, 40" in suelta and "al 40" not in suelta
    muchos = f(list(range(0, 30, 2)))              # 15 sueltos
    assert "y 5 más" in muchos


# ==================== rótulo sí, contenido no ====================

class _CtrlFalso:
    """Control con rótulo (Name) y contenido (Value) distintos."""
    def __init__(self, rotulo="", contenido=""):
        self._rotulo, self._contenido = rotulo, contenido

    def window_text(self):
        return self._rotulo

    def get_value(self):
        return self._contenido

    def legacy_properties(self):
        return {"Value": self._contenido}

    def descendants(self, control_type=None):
        return []


def test_el_ancla_usa_el_rotulo_no_el_contenido():
    """Un campo con el nombre de un paciente NO debe acabar en el YAML."""
    from core.text_read import texto_de_rotulo, extraer_texto_de_control
    campo = _CtrlFalso(rotulo="Primer apellido", contenido="García Pérez")
    # El ancla lee solo el rótulo…
    assert texto_de_rotulo(campo) == "Primer apellido"
    # …mientras que GET_TEXT sigue leyendo el contenido, que es su trabajo.
    assert "García Pérez" in extraer_texto_de_control(campo)


def test_campo_sin_rotulo_no_genera_ancla():
    """Si la aplicación no publica rótulo, mejor ningún ancla que un
    ancla hecha con el dato que hubiera escrito dentro."""
    from core.text_read import texto_de_rotulo
    assert texto_de_rotulo(_CtrlFalso(rotulo="", contenido="12345678A")) == ""


def test_boton_con_texto_si_genera_ancla():
    from core.text_read import texto_de_rotulo
    from core.text_anchor import construir_ancla
    boton = _CtrlFalso(rotulo="Aceptar")
    texto = texto_de_rotulo(boton)
    assert construir_ancla(texto, (100, 50, 200, 80), 150, 65) == {
        "texto": "Aceptar", "dx": 0, "dy": 0,
    }


def test_el_recorder_lee_solo_el_rotulo():
    """Blindaje: que nadie vuelva a meter el contenido en el ancla."""
    src = (ROOT / "core" / "recorder.py").read_text(encoding="utf-8")
    fn = src.split("def _ancla_desde_punto")[1].split("\ndef ")[0]
    assert "texto_de_rotulo" in fn
    assert "extraer_texto_de_control" not in fn
