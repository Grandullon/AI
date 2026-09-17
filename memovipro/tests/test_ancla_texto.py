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


def test_ancla_guarda_el_desplazamiento():
    """Clic en el campo que hay a la derecha del rótulo."""
    a = construir_ancla("DNI", (100, 50, 140, 70), 250, 60)
    assert a["texto"] == "DNI"
    assert a["dx"] == 130        # 250 - 120 (centro x)
    assert a["dy"] == 0


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
    a = construir_ancla("DNI", (100, 50, 140, 70), 250, 60)
    # La ventana se ha movido 300px a la derecha y 100 hacia abajo
    assert punto_desde_ancla((400, 150, 440, 170), a) == (550, 160)


def test_punto_desde_centro_ocr():
    a = {"texto": "DNI", "dx": 130, "dy": -5}
    assert punto_desde_centro(120, 60, a) == (250, 55)


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


def test_click_at_xy_usa_el_ancla_antes_que_las_coordenadas(monkeypatch):
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
    paso = Step(tipo=StepType.CLICK_AT_XY,
                extra={"x": 7, "y": 9, "texto_ancla": {"texto": "Aceptar", "dx": 0, "dy": 0}})
    Player._click_at_xy(p, paso)
    assert clics == ["ANCLA"]       # no se usaron las coordenadas literales


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
