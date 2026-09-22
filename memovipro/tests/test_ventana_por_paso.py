"""Cada paso trabaja sobre SU ventana.

Escrito a partir de macros reales del usuario: un listado de GERHONTE
pasa por el menú de turnos, informes, el filtro de personal, la vista
previa, el diálogo de guardar y LibreOffice — seis o siete ventanas en
cuarenta pasos. El campo «ventana principal» de la macro venía VACÍO en
las cinco macros examinadas.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Step, StepType
from core.ventana_paso import (
    es_activable, hay_que_activar, titulo_equivalente, ventana_esperada,
)


def _paso(titulo, proceso="exped.exe", clase=""):
    return Step(tipo=StepType.CLICK_CONTROL, extra={"win_rel": {
        "title": titulo, "proceso": proceso, "clase": clase,
        "fx": 0.5, "fy": 0.5, "w": 800, "h": 600, "dx": 400, "dy": 300,
    }})


# ==================== identidad de la ventana ====================

def test_lee_la_ventana_del_paso():
    v = ventana_esperada(_paso("INFORMES (FABPINF01)", clase="TFABPINF01"))
    assert v == {"titulo": "INFORMES (FABPINF01)",
                 "proceso": "exped.exe", "clase": "TFABPINF01"}


def test_un_paso_antiguo_sin_datos_no_rompe():
    assert ventana_esperada(Step(tipo=StepType.SLEEP)) == {
        "titulo": "", "proceso": "", "clase": ""}


# ==================== NUNCA activar el escritorio ====================

def test_el_escritorio_no_se_activa_jamas():
    """«Program Manager» es el escritorio, y sale en macros reales cuando
    un clic cae fuera de cualquier ventana. Traerlo al frente minimizaría
    todo lo demás y dejaría la macro a ciegas."""
    assert not es_activable("Program Manager")
    assert not es_activable("program manager")
    assert not es_activable("Barra de tareas")
    assert not es_activable("")
    assert not hay_que_activar(
        {"titulo": "Program Manager"}, "INFORMES (FABPINF01)", "exped.exe")


def test_las_ventanas_normales_si_se_activan():
    for t in ("INFORMES (FABPINF01)", "Save report", "Print Preview",
              "Elija el directorio y nombre del fichero de exportación"):
        assert es_activable(t)


# ==================== títulos que cambian ====================

def test_titulo_identico():
    assert titulo_equivalente("Save report", "Save report")
    assert titulo_equivalente("INFORMES (FABPINF01)", "informes (fabpinf01)")


def test_titulo_con_datos_dentro():
    """«plantilla-mensual-actual.xls • LibreOffice Calc» cambia con el
    fichero; una ficha puede llevar el nombre del paciente."""
    assert titulo_equivalente(
        "LibreOffice Calc", "plantilla-mensual-actual.xls • LibreOffice Calc")
    assert titulo_equivalente(
        "GERHONTE - MENU PRINCIPAL", "GERHONTE - MENU PRINCIPAL")


def test_titulos_distintos_no_casan():
    assert not titulo_equivalente("Save report", "Print Preview")
    assert not titulo_equivalente("INFORMES (FABPINF01)", "")
    assert not titulo_equivalente("", "Save report")


# ==================== cuándo hay que actuar ====================

def test_si_ya_esta_delante_no_se_toca():
    """No robar el foco en cada paso: parpadeos y lentitud."""
    assert not hay_que_activar(
        {"titulo": "Save report"}, "Save report", "exped.exe")


def test_si_esta_detras_hay_que_traerla():
    """EL CASO REPORTADO: el diálogo se abre detrás de la ventana
    principal y la macro clicaba sobre lo que hubiera delante."""
    assert hay_que_activar(
        {"titulo": "Save report"}, "INFORMES (FABPINF01)", "exped.exe")


def test_sin_titulo_no_se_hace_nada():
    assert not hay_que_activar({"titulo": ""}, "lo que sea", "x.exe")


# ==================== integración con el reproductor ====================

def test_no_activa_si_ya_esta_delante(monkeypatch):
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    intentos = []
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("exped.exe", "Save report")))
    monkeypatch.setattr(Player, "_traer_ventana_del_paso",
                        lambda self, e: intentos.append(e) or True)
    Player._comprobar_foco_esperado(p, _paso("Save report"))
    assert intentos == []


def test_trae_la_ventana_que_se_abrio_detras(monkeypatch):
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    traidas = []

    def _traer(self, esperada):
        traidas.append(esperada["titulo"])
        return True

    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("exped.exe", "INFORMES (FABPINF01)")))
    monkeypatch.setattr(Player, "_traer_ventana_del_paso", _traer)
    Player._comprobar_foco_esperado(p, _paso("Save report"))
    assert traidas == ["Save report"]      # trae la del PASO, no otra


def test_si_no_la_encuentra_comprueba_el_programa(monkeypatch):
    """Título cambiado o ventana aún sin abrir: al menos que el programa
    cuadre, como se hacía antes."""
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("exped.exe", "Otra cosa")))
    monkeypatch.setattr(Player, "_traer_ventana_del_paso", lambda self, e: False)
    Player._comprobar_foco_esperado(p, _paso("Save report"))   # no lanza


def test_si_manda_otro_programa_entra_la_escalada(monkeypatch):
    from core.player import Player
    from core.ventana_intrusa import Politica
    p = Player.__new__(Player)
    p.dry_run = False
    p.politica_intrusas = Politica(esperar_s=0.0, intervalo_s=0.0)
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("chrome.exe", "Gmail")))
    monkeypatch.setattr(Player, "_traer_ventana_del_paso", lambda self, e: False)
    monkeypatch.setattr(Player, "_cerrar_ventana_por_titulo",
                        staticmethod(lambda t: None))
    try:
        Player._comprobar_foco_esperado(p, _paso("Save report"))
        assert False, "debería impedir el paso"
    except RuntimeError as exc:
        assert "Gmail" in str(exc)


def test_nunca_activa_el_escritorio_desde_el_reproductor(monkeypatch):
    """Un paso grabado sobre «Program Manager» no debe traer el
    escritorio al frente."""
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    traidas = []
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("exped.exe", "INFORMES (FABPINF01)")))
    monkeypatch.setattr(Player, "_traer_ventana_del_paso",
                        lambda self, e: traidas.append(e) or True)
    Player._comprobar_foco_esperado(p, _paso("Program Manager", "explorer.exe"))
    assert traidas == []


def test_en_simulacion_no_toca_ventanas(monkeypatch):
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = True
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: (_ for _ in ()).throw(AssertionError)))
    Player._comprobar_foco_esperado(p, _paso("Save report"))


def test_el_grabador_apunta_la_clase_de_ventana():
    """En Delphi la clase («TFABPMEN1») no cambia con los datos, al
    contrario que el título."""
    src = (ROOT / "core" / "recorder.py").read_text(encoding="utf-8")
    fn = src.split("def _ventana_relativa_desde_punto")[1].split("\ndef ")[0]
    assert "class_name()" in fn and '"clase"' in fn
