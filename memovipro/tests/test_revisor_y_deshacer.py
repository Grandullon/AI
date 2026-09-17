"""Revisor de macros, deshacer/rehacer y la comprobación "¿estoy donde
creo?" antes de clicar."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.revisor_macro import ALTO, MEDIO, INFO, revisar
from core.step_model import Macro, Selector, Step, StepType


def _macro(pasos, ventana="GERHONTE"):
    return Macro(nombre="m", pasos=pasos, ventana_principal=ventana)


def _titulos(inf):
    return [a.titulo for a in inf.avisos]


# ==================== revisor ====================

def test_macro_correcta_no_da_avisos():
    pasos = [
        Step(tipo=StepType.CLICK_CONTROL,
             selector=Selector(control_type="Button", name="Aceptar")),
        Step(tipo=StepType.TYPE_TEXT, valor="{DNI}"),
        Step(tipo=StepType.CLICK_AT_XY, extra={
            "x": 1, "y": 2,
            "win_rel": {"title": "G", "w": 800, "h": 600},
        }, verificar_ventana="Resultado"),
    ]
    assert revisar(_macro(pasos)).avisos == []


def test_detecta_dni_grabado_a_fuego():
    """Lo más valioso: un dato de un paciente concreto que se quedó en la
    macro se repetiría para toda la lista."""
    pasos = [Step(tipo=StepType.TYPE_TEXT, valor="12345678Z")]
    inf = revisar(_macro(pasos))
    aviso = next(a for a in inf.avisos if "paciente concreto" in a.titulo)
    assert aviso.gravedad == ALTO
    assert aviso.paso == 1
    assert "un DNI" in aviso.detalle


def test_detecta_nie_y_numeros_largos():
    for valor, esperado in (("X1234567L", "un NIE"),
                            ("910123456789", "un número largo")):
        inf = revisar(_macro([Step(tipo=StepType.TYPE_TEXT, valor=valor)]))
        aviso = next(a for a in inf.avisos if "paciente concreto" in a.titulo)
        assert esperado in aviso.detalle


def test_un_hueco_no_es_un_dato_fijo():
    """{DNI} se rellena en cada ejecución: eso está bien."""
    pasos = [Step(tipo=StepType.TYPE_TEXT, valor="{DNI}"),
             Step(tipo=StepType.TYPE_TEXT, valor="Nº {NUHSA}")]
    assert not any("paciente" in t for t in _titulos(revisar(_macro(pasos))))


def test_detecta_clics_a_ciegas():
    pasos = [Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 2})
             for _ in range(3)]
    inf = revisar(_macro(pasos))
    aviso = next(a for a in inf.avisos if "a ciegas" in a.titulo)
    assert aviso.gravedad == ALTO
    assert "3 clic(s)" in aviso.titulo
    assert "pasos 1, 2, 3" in aviso.detalle


def test_un_clic_con_respaldos_no_es_a_ciegas():
    pasos = [Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 1, "y": 2, "win_rel": {"title": "G", "w": 800, "h": 600}})]
    assert not any("ciegas" in t for t in _titulos(revisar(_macro(pasos))))


def test_detecta_ventana_de_trabajo_vacia():
    pasos = [Step(tipo=StepType.SLEEP, valor="1")]
    inf = revisar(_macro(pasos, ventana=""))
    aviso = next(a for a in inf.avisos if "Sin ventana" in a.titulo)
    assert aviso.gravedad == ALTO and aviso.paso == 0


def test_detecta_atajos_peligrosos():
    pasos = [Step(tipo=StepType.SEND_KEYS, valor="%{F4}")]
    aviso = next(a for a in revisar(_macro(pasos)).avisos
                 if a.titulo == "Atajo peligroso")
    assert aviso.gravedad == ALTO
    assert "cierra la ventana" in aviso.detalle


def test_detecta_pausas_absurdas():
    pasos = [Step(tipo=StepType.SLEEP, valor="1", delay_before_s=600.0)]
    aviso = next(a for a in revisar(_macro(pasos)).avisos
                 if "Pausa muy larga" in a.titulo)
    assert aviso.gravedad == MEDIO and "10 minutos" in aviso.detalle


def test_los_pasos_desactivados_no_se_revisan_pero_se_avisan():
    pasos = [Step(tipo=StepType.TYPE_TEXT, valor="12345678Z", activo=False)]
    titulos = _titulos(revisar(_macro(pasos)))
    assert "Paso desactivado" in titulos
    assert not any("paciente" in t for t in titulos)


def test_avisos_ordenados_por_gravedad():
    pasos = [
        Step(tipo=StepType.SLEEP, valor="1", activo=False),          # info
        Step(tipo=StepType.SLEEP, valor="1", delay_before_s=600.0),  # medio
        Step(tipo=StepType.TYPE_TEXT, valor="12345678Z"),            # alto
    ]
    gravedades = [a.gravedad for a in revisar(_macro(pasos)).avisos]
    assert gravedades == sorted(gravedades, key=[ALTO, MEDIO, INFO].index)


def test_macro_vacia():
    inf = revisar(_macro([]))
    assert inf.avisos[0].titulo == "La macro no tiene pasos"


def test_resumen_legible():
    pasos = [Step(tipo=StepType.TYPE_TEXT, valor="12345678Z")]
    assert "importante" in revisar(_macro(pasos)).resumen()
    pasos_ok = [Step(tipo=StepType.TYPE_TEXT, valor="{DNI}")]
    assert "Todo correcto" in revisar(_macro(pasos_ok)).resumen()


# ==================== ¿estoy donde creo? ====================

def test_mismo_programa_compara_ejecutables():
    from core.proceso import mismo_programa
    assert mismo_programa("gerhonte.exe", "GERHONTE.EXE")
    assert not mismo_programa("gerhonte.exe", "chrome.exe")


def test_si_no_se_sabe_el_programa_no_se_bloquea():
    """Una duda no debe impedir un paso: la comprobación solo sirve para
    detectar un programa DISTINTO."""
    from core.proceso import mismo_programa
    assert mismo_programa("", "chrome.exe")
    assert mismo_programa("gerhonte.exe", "")


def test_paso_antiguo_sin_proceso_no_se_comprueba(monkeypatch):
    import core.player as pl
    from core.player import Player

    p = Player.__new__(Player)
    p.dry_run = False
    monkeypatch.setattr("core.proceso.proceso_en_primer_plano",
                        lambda: (_ for _ in ()).throw(AssertionError("no tocar")))
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 2})
    Player._comprobar_foco_esperado(p, paso)      # no lanza


def test_ventana_equivocada_impide_el_clic(monkeypatch):
    """El escenario que se quiere evitar: la sesión caducó y delante hay
    otra cosa que no se quita. Antes se clicaba igual."""
    from core.player import Player
    from core.step_model import Macro
    from core.ventana_intrusa import Politica

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="GERHONTE")
    p.politica_intrusas = Politica(esperar_s=0.0, intervalo_s=0.0)
    monkeypatch.setattr("core.proceso.proceso_en_primer_plano", lambda: "chrome.exe")
    monkeypatch.setattr(Player, "_ventana_frontal",
                        staticmethod(lambda: ("chrome.exe", "Gmail - Chrome")))
    monkeypatch.setattr(Player, "_activar_ventana", staticmethod(lambda t: None))
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 1, "y": 2, "win_rel": {"title": "GERHONTE", "proceso": "gerhonte.exe"}})
    try:
        Player._comprobar_foco_esperado(p, paso)
        assert False, "debería impedir el paso"
    except RuntimeError as exc:
        # El mensaje tiene que decir QUÉ estorbaba, para poder apuntarlo
        assert "Gmail - Chrome" in str(exc)
        assert "gerhonte.exe" in str(exc)
        assert "cerrar_titulos" in str(exc)


def test_si_el_programa_coincide_sigue_adelante(monkeypatch):
    from core.player import Player
    from core.step_model import Macro

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="GERHONTE")
    monkeypatch.setattr("core.proceso.proceso_en_primer_plano", lambda: "gerhonte.exe")
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 1, "y": 2, "win_rel": {"proceso": "gerhonte.exe"}})
    Player._comprobar_foco_esperado(p, paso)      # no lanza


def test_una_ventana_pasajera_no_tumba_el_paso(monkeypatch):
    """Lo más habitual: un aviso aparece y se va solo en unos segundos.
    Antes eso tumbaba un paso que habría funcionado sin hacer nada."""
    from core.player import Player
    from core.step_model import Macro
    from core.ventana_intrusa import Politica

    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[], ventana_principal="GERHONTE")
    p.politica_intrusas = Politica(esperar_s=5.0, intervalo_s=0.0)
    vistas = ["chrome.exe", "chrome.exe", "gerhonte.exe"]
    monkeypatch.setattr("core.proceso.proceso_en_primer_plano", lambda: "chrome.exe")
    monkeypatch.setattr(
        Player, "_ventana_frontal",
        staticmethod(lambda: (vistas.pop(0) if vistas else "gerhonte.exe", "Aviso")),
    )
    monkeypatch.setattr(Player, "_activar_ventana", staticmethod(lambda t: None))
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 1, "y": 2, "win_rel": {"title": "GERHONTE", "proceso": "gerhonte.exe"}})
    Player._comprobar_foco_esperado(p, paso)      # no lanza: se recuperó


def test_en_simulacion_no_bloquea(monkeypatch):
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = True
    paso = Step(tipo=StepType.CLICK_AT_XY, extra={
        "x": 1, "y": 2, "win_rel": {"proceso": "gerhonte.exe"}})
    Player._comprobar_foco_esperado(p, paso)


# ==================== deshacer ====================

def test_el_editor_guarda_copia_profunda():
    """Copia superficial no vale: los pasos llevan diccionarios dentro y
    deshacer restauraría objetos ya modificados."""
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    fn = src.split("def _snapshot")[1].split("\n    def ")[0]
    assert "copy.deepcopy" in fn


def test_las_acciones_destructivas_hacen_snapshot():
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    for metodo in ("_remove_step", "_add_step", "_move", "_toggle_activo_uno"):
        fn = src.split(f"def {metodo}(")[1].split("\n    def ")[0]
        assert "_snapshot(" in fn, f"{metodo} no permite deshacer"
