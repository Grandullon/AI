"""Pulsar en el MISMO SITIO del control, no en su centro.

Caso real: en «1-INCI-GRABADAS-HOY», el paso 11 es un selector de fecha
de GERHONTE (TDateTimePicker). El usuario pulsa la FLECHITA para
desplegar el calendario y luego «Hoy». Al buscar el control por su
nombre se pulsaba en su centro —el texto de la fecha—, el calendario no
se desplegaba y el clic en «Hoy» caía en el vacío.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Selector, Step, StepType


class _R:
    def __init__(self, l, t, r, b):
        self.left, self.top, self.right, self.bottom = l, t, r, b


class _Ctrl:
    def __init__(self, rect):
        self._r = rect
        self.centro = False

    def rectangle(self):
        return self._r

    def click_input(self, button="left"):
        self.centro = True

    def double_click_input(self, button="left"):
        self.centro = True


def _player():
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    return p


def _paso(**extra):
    return Step(tipo=StepType.CLICK_CONTROL,
                selector=Selector(control_type="Pane", name="Orden:"), extra=extra)


# ==================== nombres que son datos ====================

def test_una_fecha_no_es_un_nombre():
    """El selector de fecha se «llama» como la fecha que tiene puesta:
    mañana se llamará distinto."""
    for n in ("01/09/2026", "23/09/2026", "Hoy: 23/09/2026", "12:30", "23", "1.250,00 €"):
        assert not Selector(control_type="Pane", name=n).identifica_algo(), n


def test_los_rotulos_si_son_nombres():
    for n in ("Guardar", "Orden:", "Incidencias", "Listado de incidencias", "Archivo"):
        assert Selector(control_type="Pane", name=n).identifica_algo(), n


# ==================== grabaciones nuevas: saben dónde cayó ====================

def test_pulsa_donde_se_grabo_aunque_el_control_se_haya_movido():
    from core.player import Player
    p = _player()
    ctrl = _Ctrl(_R(500, 300, 700, 330))          # se ha movido
    paso = _paso(en_control={"dx": 190, "dy": 15, "w": 200, "h": 30})
    assert Player._punto_dentro_del_control(p, ctrl, paso) == (690, 315)


def test_si_cambia_de_tamano_mantiene_la_proporcion():
    from core.player import Player
    p = _player()
    ctrl = _Ctrl(_R(0, 0, 400, 60))                # el doble de grande
    paso = _paso(en_control={"dx": 190, "dy": 15, "w": 200, "h": 30})
    assert Player._punto_dentro_del_control(p, ctrl, paso) == (380, 30)


# ==================== grabaciones antiguas ====================

def test_antigua_usa_el_punto_grabado_si_sigue_dentro(monkeypatch):
    """Es exactamente lo que se hacía antes por posición, pero sabiendo
    que el control es el correcto."""
    from core.player import Player
    p = _player()
    monkeypatch.setattr(Player, "_punto_ventana_relativa", lambda self, wr: None)
    ctrl = _Ctrl(_R(900, 540, 1100, 620))          # el grupo «Orden:»
    paso = _paso(fallback_xy=[938, 575])
    assert Player._punto_dentro_del_control(p, ctrl, paso) == (938, 575)


def test_antigua_sigue_a_la_ventana_si_se_movio(monkeypatch):
    from core.player import Player
    p = _player()
    monkeypatch.setattr(Player, "_punto_ventana_relativa",
                        lambda self, wr: (1038, 675))   # ventana +100,+100
    ctrl = _Ctrl(_R(1000, 640, 1200, 720))
    paso = _paso(fallback_xy=[938, 575], win_rel={"title": "INFORMES"})
    assert Player._punto_dentro_del_control(p, ctrl, paso) == (1038, 675)


def test_control_pequeno_sin_datos_pulsa_en_el_centro(monkeypatch):
    """Un botón: pulsar en su centro ES pulsar el botón."""
    from core.player import Player
    p = _player()
    monkeypatch.setattr(Player, "_punto_ventana_relativa", lambda self, wr: None)
    ctrl = _Ctrl(_R(500, 500, 580, 525))
    paso = _paso(fallback_xy=[10, 10])            # el punto viejo ya no cae dentro
    assert Player._punto_dentro_del_control(p, ctrl, paso) is None


def test_control_grande_sin_datos_no_adivina(monkeypatch):
    """Un calendario o un grupo: el centro sería un sitio cualquiera. Mejor
    volver a la posición, como antes."""
    from core.player import Player
    p = _player()
    monkeypatch.setattr(Player, "_punto_ventana_relativa", lambda self, wr: None)
    ctrl = _Ctrl(_R(500, 300, 760, 480))          # 260x180
    paso = _paso(fallback_xy=[10, 10])
    assert Player._punto_dentro_del_control(p, ctrl, paso) is False


# ==================== de punta a punta ====================

def test_el_clic_va_al_sitio_y_no_al_centro(monkeypatch):
    from core.player import Player
    from core.step_model import Macro
    p = _player()
    p.macro = Macro(nombre="m", pasos=[])
    ctrl = _Ctrl(_R(900, 540, 1100, 620))
    clics = []
    monkeypatch.setattr(Player, "_resolve_control", lambda self, paso: ctrl)
    monkeypatch.setattr(Player, "_punto_ventana_relativa", lambda self, wr: None)
    monkeypatch.setattr(Player, "_click_xy",
                        lambda self, x, y, **k: clics.append((x, y)))
    Player._click_control(p, _paso(fallback_xy=[938, 575]))
    assert clics == [(938, 575)]
    assert ctrl.centro is False


def test_grande_sin_datos_vuelve_a_la_posicion(monkeypatch):
    from core.player import Player
    from core.step_model import Macro
    p = _player()
    p.macro = Macro(nombre="m", pasos=[])
    ctrl = _Ctrl(_R(500, 300, 760, 480))
    orden = []
    monkeypatch.setattr(Player, "_resolve_control", lambda self, paso: ctrl)
    monkeypatch.setattr(Player, "_punto_ventana_relativa", lambda self, wr: None)
    monkeypatch.setattr(Player, "_click_window_relative",
                        lambda self, *a, **k: orden.append("VENTANA") or True)
    Player._click_control(p, _paso(fallback_xy=[10, 10], win_rel={"title": "X"}))
    assert orden == ["VENTANA"] and ctrl.centro is False


def test_el_grabador_apunta_donde_cayo_el_clic():
    src = (ROOT / "core" / "recorder.py").read_text(encoding="utf-8")
    assert 'extra["en_control"] = en_control' in src
