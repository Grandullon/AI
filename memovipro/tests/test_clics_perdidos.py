"""Clics que se perdían al grabar.

Causa principal: la miniatura se capturaba DENTRO del enganche del ratón.
Windows desengancha los hooks de bajo nivel que tardan de más, y a partir
de ahí la grabación seguía "en marcha" sin captar nada.
"""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import EventoCrudo, Recorder


def _recorder_minimo():
    r = Recorder.__new__(Recorder)
    r._lock = threading.Lock()
    r._grabando = True
    r.eventos_crudos = []
    r.zonas_excluidas = []
    r.clics_descartados = 0
    r._press_pendiente = None
    r._modifiers = set()
    r._modifiers_desde = {}
    import core.recorder as rec
    r._buf = rec._BufferTexto()
    return r


# ==================== el enganche no se bloquea ====================

def test_el_callback_del_raton_no_espera_a_la_captura(monkeypatch):
    """LA CAUSA DEL FALLO. El callback debe volver al instante aunque la
    captura de pantalla tarde: si tarda dentro del enganche, Windows lo
    desengancha y se dejan de recibir pulsaciones."""
    import core.image_match as im

    def captura_lenta(x, y, **kw):
        time.sleep(0.3)
        return b"PNG"

    monkeypatch.setattr(im, "capturar_region_png", captura_lenta)
    r = _recorder_minimo()
    r._arrancar_miniaturas()

    t0 = time.perf_counter()
    r._on_click_impl(100, 200, _Boton(), True)     # press
    tardanza = time.perf_counter() - t0
    assert tardanza < 0.05, f"el callback bloqueó {tardanza*1000:.0f} ms"

    r._parar_miniaturas()
    # Y la miniatura llega igualmente, solo que por detrás
    assert r._press_pendiente["img_holder"]["png"] == b"PNG"


def test_la_miniatura_llega_al_evento(monkeypatch):
    import core.image_match as im
    monkeypatch.setattr(im, "capturar_region_png", lambda x, y, **kw: b"MINI")
    r = _recorder_minimo()
    r._arrancar_miniaturas()
    r._on_click_impl(10, 20, _Boton(), True)
    r._on_click_impl(10, 20, _Boton(), False)
    r._parar_miniaturas()

    evt = r.eventos_crudos[-1]
    assert evt.tipo == "click"
    assert evt.img_holder["png"] == b"MINI"


def test_si_la_captura_falla_el_clic_se_graba_igual(monkeypatch):
    """Una miniatura es un respaldo; un clic perdido rompe la macro."""
    import core.image_match as im

    def revienta(x, y, **kw):
        raise RuntimeError("sin pantalla")

    monkeypatch.setattr(im, "capturar_region_png", revienta)
    r = _recorder_minimo()
    r._arrancar_miniaturas()
    r._on_click_impl(10, 20, _Boton(), True)
    r._on_click_impl(10, 20, _Boton(), False)
    r._parar_miniaturas()

    assert len(r.eventos_crudos) == 1
    assert r.eventos_crudos[0].img_holder["png"] is None


def test_sin_hilo_de_miniaturas_no_revienta():
    """El recorder tiene que aguantar que no se haya arrancado la cola."""
    r = _recorder_minimo()
    sobre = r._encolar_miniatura(5, 5)
    assert sobre == {"png": None}


def test_construir_macro_saca_la_miniatura_del_sobre(monkeypatch):
    import core.recorder as rec
    monkeypatch.setattr(rec, "_selector_desde_punto",
                        lambda x, y: (None, "sitio", None, None))
    evt = EventoCrudo(tipo="click", x=1, y=2, timestamp=1.0,
                      img_holder={"png": b"\x89PNG-falso"})
    macro = Recorder.construir_macro([evt], resolver_selectores=True)
    assert macro.pasos[0].extra["img_b64"]


def test_una_miniatura_directa_sigue_valiendo(monkeypatch):
    """Compatibilidad: eventos construidos a mano o de antes."""
    import core.recorder as rec
    monkeypatch.setattr(rec, "_selector_desde_punto",
                        lambda x, y: (None, "sitio", None, None))
    evt = EventoCrudo(tipo="click", x=1, y=2, timestamp=1.0, img_png=b"\x89PNG")
    macro = Recorder.construir_macro([evt], resolver_selectores=True)
    assert macro.pasos[0].extra["img_b64"]


# ==================== clics tapados por el propio programa ====================

def test_un_clic_sobre_memovipro_se_cuenta(monkeypatch):
    """Segunda causa de "he pulsado y no lo ha grabado": el panel
    flotante tapa el botón. Antes se descartaba en silencio."""
    import core.image_match as im
    monkeypatch.setattr(im, "capturar_region_png", lambda x, y, **kw: None)
    r = _recorder_minimo()
    r.zonas_excluidas = [(0, 0, 300, 200)]     # el panel
    r._arrancar_miniaturas()

    r._on_click_impl(150, 100, _Boton(), True)   # cae sobre el panel
    assert r.eventos_crudos == []
    assert r.clics_descartados == 1

    r._on_click_impl(800, 600, _Boton(), True)   # fuera del panel
    r._on_click_impl(800, 600, _Boton(), False)
    r._parar_miniaturas()
    assert len(r.eventos_crudos) == 1
    assert r.clics_descartados == 1              # no sube de más


def test_el_contador_de_descartados_sale_en_pantalla():
    src = (ROOT / "ui" / "record_dialog.py").read_text(encoding="utf-8")
    assert "clics_descartados" in src
    assert "sobre esta" in src          # el aviso al usuario


# ==================== umbral de doble clic ====================

def test_el_umbral_de_doble_clic_es_el_del_sistema():
    """Fusionar dos clics en un doble clic tiene que usar el mismo tiempo
    que aplica la aplicación grabada, no un número inventado."""
    from core.recorder import _umbral_doble_clic_s, DOUBLE_CLICK_THRESHOLD_S
    v = _umbral_doble_clic_s()
    assert 0.1 <= v <= 5.0
    assert DOUBLE_CLICK_THRESHOLD_S == v


def test_fuera_de_windows_medio_segundo(monkeypatch):
    from core.recorder import _umbral_doble_clic_s
    assert _umbral_doble_clic_s() == 0.5     # aquí no hay windll


class _Boton:
    """Botón izquierdo tal como lo imprime pynput."""
    def __str__(self):
        return "Button.left"


# ==================== la ventana que hay DE VERDAD debajo ====================

def test_clic_sobre_la_app_que_tapa_nuestra_ventana_se_graba(monkeypatch):
    """EL CASO GORDO. La ventana de grabación no está siempre encima, así
    que la aplicación puede estar por delante. Comparando rectángulos,
    esos clics —que son de la aplicación— se descartaban igual."""
    r = _recorder_minimo()
    r.zonas_excluidas = [(0, 0, 1920, 1080)]   # nuestra ventana, detrás
    r.hwnds_propios = [1111]
    # Windows dice que bajo el cursor está la ventana de la aplicación
    monkeypatch.setattr(Recorder, "_ventana_propia_bajo",
                        lambda self, x, y: False)
    assert r._punto_excluido(500, 500) is False


def test_clic_sobre_nuestra_ventana_se_descarta(monkeypatch):
    r = _recorder_minimo()
    r.hwnds_propios = [1111]
    monkeypatch.setattr(Recorder, "_ventana_propia_bajo",
                        lambda self, x, y: True)
    assert r._punto_excluido(10, 10) is True


def test_si_no_se_puede_preguntar_se_usan_los_rectangulos(monkeypatch):
    """Fuera de Windows, o si la consulta falla, el método de siempre."""
    r = _recorder_minimo()
    r.zonas_excluidas = [(0, 0, 300, 200)]
    monkeypatch.setattr(Recorder, "_ventana_propia_bajo",
                        lambda self, x, y: None)
    assert r._punto_excluido(150, 100) is True
    assert r._punto_excluido(800, 600) is False


def test_sin_identificadores_no_se_pregunta():
    """Sin la lista de ventanas propias no hay nada que comparar."""
    r = _recorder_minimo()
    r.hwnds_propios = []
    assert r._ventana_propia_bajo(10, 10) is None


def test_el_dialogo_se_aparta_y_se_devuelve():
    """440x220 en mitad de la pantalla es justo encima de lo que quieres
    pulsar. Se aparta a una esquina mientras se graba."""
    src = (ROOT / "ui" / "record_dialog.py").read_text(encoding="utf-8")
    ini = src.split("def _iniciar_grabacion")[1].split("\n    @staticmethod")[0]
    assert "_geom_original" in ini and "scr.bottom()" in ini
    stop = src.split("def _stop(")[1].split("\n    def ")[0]
    assert "setGeometry(geom)" in stop      # y se devuelve a su sitio


def test_el_editor_publica_los_identificadores():
    src = (ROOT / "ui" / "record_dialog.py").read_text(encoding="utf-8")
    fn = src.split("def _actualizar_zonas_excluidas")[1].split("\n    def ")[0]
    assert "hwnds_propios" in fn and "winId()" in fn


# ==================== identificar al PULSAR, no al soltar ====================

def test_un_desplegable_que_se_cierra_con_el_clic_se_graba_bien(monkeypatch):
    """Caso real: el calendario de GERHONTE se cierra al pulsar «Hoy».
    Identificando el elemento al SOLTAR, el calendario ya no está y se
    guardaba lo que había detrás."""
    import time as _t
    import core.recorder as rec
    import core.image_match as im
    from core.step_model import Selector

    monkeypatch.setattr(im, "capturar_region_png", lambda x, y, **kw: None)
    pantalla = {"ahora": "Hoy"}
    monkeypatch.setattr(
        rec, "_selector_desde_punto",
        lambda x, y: (Selector(control_type="Button", name=pantalla["ahora"]),
                      pantalla["ahora"], None, None, None),
    )
    r = _recorder_minimo()
    r._arrancar_miniaturas()
    r._arrancar_resolutor()

    r._on_click_impl(10, 20, _Boton(), True)            # pulsar sobre «Hoy»
    sobre = r._press_pendiente["res_holder"]
    t0 = _t.time()
    while sobre["res"] is None and _t.time() - t0 < 2:
        _t.sleep(0.01)
    pantalla["ahora"] = "Borradas"                      # el calendario se cierra
    r._on_click_impl(10, 20, _Boton(), False)           # soltar

    r._parar_resolutor()
    r._parar_miniaturas()
    macro = Recorder.construir_macro(r.eventos_crudos, resolver_selectores=True)
    assert macro.pasos[0].selector.name == "Hoy"


def test_si_no_hubo_resolucion_al_pulsar_se_hace_al_soltar(monkeypatch):
    """Red de seguridad: eventos sin sobre siguen resolviéndose."""
    import core.recorder as rec
    from core.step_model import Selector
    monkeypatch.setattr(
        rec, "_selector_desde_punto",
        lambda x, y: (Selector(control_type="Button", name="Tarde"), "Tarde",
                      None, None, None))
    evt = EventoCrudo(tipo="click", x=1, y=2, timestamp=1.0,
                      res_holder={"res": None})
    macro = Recorder.construir_macro([evt], resolver_selectores=True)
    assert macro.pasos[0].selector.name == "Tarde"
