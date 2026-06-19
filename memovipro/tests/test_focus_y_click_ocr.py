"""Tests de la activación agresiva de ventanas (anti focus-stealing) y del
nuevo paso CLICK_OCR_TEXT.

Diseñados para no requerir Windows reales: las funciones de pywinauto y de
Tesseract se inyectan vía monkeypatch.
"""
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ==================== Activación agresiva ====================

def test_activar_agresivo_devuelve_false_si_hwnd_es_cero():
    from core.window_utils import _activar_agresivo
    assert _activar_agresivo(0) is False


def test_activar_agresivo_devuelve_false_si_no_hay_win32(monkeypatch):
    """Si pywin32 no está instalado, _activar_agresivo no debe explotar."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name in ("win32api", "win32con", "win32gui"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from core.window_utils import _activar_agresivo
    assert _activar_agresivo(123) is False


def test_activar_agresivo_llama_a_alt_y_setforeground(monkeypatch):
    """Verifica la secuencia: Alt down + Alt up + SetForegroundWindow."""
    eventos = []

    fake_win32api = types.SimpleNamespace(
        keybd_event=lambda vk, scan, flags, extra: eventos.append(
            ("keybd_event", vk, flags)
        ),
    )
    fake_win32con = types.SimpleNamespace(
        VK_MENU=0x12,
        KEYEVENTF_KEYUP=0x0002,
        SW_RESTORE=9,
    )
    fake_win32gui = types.SimpleNamespace(
        IsIconic=lambda hwnd: False,
        ShowWindow=lambda hwnd, cmd: eventos.append(("ShowWindow", hwnd, cmd)),
        SetForegroundWindow=lambda hwnd: eventos.append(("SetForegroundWindow", hwnd)),
        GetForegroundWindow=lambda: 555,  # devuelve el hwnd que pediremos
    )
    monkeypatch.setitem(sys.modules, "win32api", fake_win32api)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    from core.window_utils import _activar_agresivo
    assert _activar_agresivo(555) is True
    # Debe haber: Alt down, Alt up, SetForegroundWindow
    tipos = [e[0] for e in eventos]
    assert tipos == ["keybd_event", "keybd_event", "SetForegroundWindow"]
    # Alt down (flags=0), Alt up (flags=KEYEVENTF_KEYUP)
    assert eventos[0] == ("keybd_event", 0x12, 0)
    assert eventos[1] == ("keybd_event", 0x12, 0x0002)
    assert eventos[2] == ("SetForegroundWindow", 555)


def test_activar_agresivo_restaura_si_minimizada(monkeypatch):
    eventos = []
    fake_win32api = types.SimpleNamespace(keybd_event=lambda *a, **k: None)
    fake_win32con = types.SimpleNamespace(
        VK_MENU=0x12, KEYEVENTF_KEYUP=0x0002, SW_RESTORE=9,
    )
    fake_win32gui = types.SimpleNamespace(
        IsIconic=lambda hwnd: True,
        ShowWindow=lambda hwnd, cmd: eventos.append(("ShowWindow", hwnd, cmd)),
        SetForegroundWindow=lambda hwnd: eventos.append(("SetForegroundWindow", hwnd)),
        GetForegroundWindow=lambda: 777,
    )
    monkeypatch.setitem(sys.modules, "win32api", fake_win32api)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    from core.window_utils import _activar_agresivo
    assert _activar_agresivo(777) is True
    # ShowWindow(SW_RESTORE) debe haberse llamado antes de SetForegroundWindow
    asunto = [e for e in eventos if e[0] in ("ShowWindow", "SetForegroundWindow")]
    assert asunto[0] == ("ShowWindow", 777, 9)
    assert asunto[1] == ("SetForegroundWindow", 777)


def test_activar_agresivo_devuelve_false_si_setforeground_no_aplica(monkeypatch):
    """Si GetForegroundWindow después de SetForegroundWindow no devuelve el
    hwnd esperado, _activar_agresivo debe devolver False (sigue habiendo
    focus stealing)."""
    fake_win32api = types.SimpleNamespace(keybd_event=lambda *a, **k: None)
    fake_win32con = types.SimpleNamespace(
        VK_MENU=0x12, KEYEVENTF_KEYUP=0x0002, SW_RESTORE=9,
    )
    fake_win32gui = types.SimpleNamespace(
        IsIconic=lambda hwnd: False,
        ShowWindow=lambda hwnd, cmd: None,
        SetForegroundWindow=lambda hwnd: None,
        GetForegroundWindow=lambda: 999,  # NO es 111
    )
    monkeypatch.setitem(sys.modules, "win32api", fake_win32api)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    from core.window_utils import _activar_agresivo
    assert _activar_agresivo(111) is False


def test_asegurar_ventana_usa_agresivo_como_fallback(monkeypatch):
    """Si set_focus deja la ventana fuera de foreground, asegurar_ventana
    debe disparar la activación agresiva."""
    import core.window_utils as wu

    llamadas_agresivo = []

    monkeypatch.setattr(wu, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(wu, "_get_foreground_handle", lambda: 12345)
    monkeypatch.setattr(
        wu, "_activar_agresivo",
        lambda hwnd: (llamadas_agresivo.append(hwnd), True)[-1],
    )

    class _FakeWin:
        handle = 99999

        def exists(self, timeout=0): return True
        def window_text(self): return "GERHONTE"
        def is_minimized(self): return False
        def is_maximized(self): return True
        def maximize(self): pass
        def restore(self): pass
        def minimize(self): pass
        def set_focus(self): pass  # silenciosamente "no hace nada"

    class _FakeDesktop:
        def __init__(self, backend): pass
        def window(self, **kw): return _FakeWin()

    monkeypatch.setattr(wu, "Desktop", _FakeDesktop)
    ok, msg = wu.asegurar_ventana("GERHONTE")
    assert ok is True
    # foreground (12345) != handle (99999) → debió llamar al agresivo
    assert llamadas_agresivo == [99999]


def test_asegurar_ventana_no_usa_agresivo_si_set_focus_funciono(monkeypatch):
    """Si tras set_focus la ventana ya es foreground, no se llama al
    fallback agresivo (evita keybd_event innecesario)."""
    import core.window_utils as wu

    llamadas_agresivo = []
    monkeypatch.setattr(wu, "_HAS_PYWINAUTO", True)
    monkeypatch.setattr(wu, "_get_foreground_handle", lambda: 99999)
    monkeypatch.setattr(
        wu, "_activar_agresivo",
        lambda hwnd: llamadas_agresivo.append(hwnd) or True,
    )

    class _FakeWin:
        handle = 99999

        def exists(self, timeout=0): return True
        def window_text(self): return "GERHONTE"
        def is_minimized(self): return False
        def is_maximized(self): return True
        def maximize(self): pass
        def restore(self): pass
        def minimize(self): pass
        def set_focus(self): pass

    class _FakeDesktop:
        def __init__(self, backend): pass
        def window(self, **kw): return _FakeWin()

    monkeypatch.setattr(wu, "Desktop", _FakeDesktop)
    ok, _ = wu.asegurar_ventana("GERHONTE")
    assert ok is True
    assert llamadas_agresivo == []


# ==================== CLICK_OCR_TEXT ====================

def test_step_type_click_ocr_text_existe():
    from core.step_model import StepType
    assert StepType.CLICK_OCR_TEXT.value == "click_ocr_text"


def test_step_click_ocr_text_serializa_y_carga():
    from core.step_model import Step, StepType
    paso = Step(
        tipo=StepType.CLICK_OCR_TEXT,
        valor="Aceptar",
        extra={"min_confidence": 70, "double": True},
        descripcion='Clic en "Aceptar"',
    )
    d = paso.to_dict()
    assert d["tipo"] == "click_ocr_text"
    assert d["valor"] == "Aceptar"
    assert d["extra"]["min_confidence"] == 70
    cargado = Step.from_dict(d)
    assert cargado.tipo == StepType.CLICK_OCR_TEXT
    assert cargado.valor == "Aceptar"


def test_localizar_texto_normaliza_acentos_y_mayusculas(monkeypatch):
    """Buscar 'INFORME' debe encontrar 'informe' o 'Informe' en el OCR."""
    import core.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        Output = types.SimpleNamespace(DICT="dict")

        @staticmethod
        def image_to_data(img, lang=None, output_type=None):
            # Simula la salida real de Tesseract: 5 tokens, uno coincide
            return {
                "text": ["", "header", "Informe", "del", "día", ""],
                "conf": [0, 90, 85, 80, 88, 0],
                "left": [0, 10, 100, 200, 250, 0],
                "top": [0, 50, 50, 50, 50, 0],
                "width": [0, 60, 70, 30, 40, 0],
                "height": [0, 20, 22, 20, 20, 0],
            }

    class _FakeImage:
        @staticmethod
        def open(p): return object()

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", _FakeImage)

    hit = ocr_mod.localizar_texto_en_imagen("ventana.png", "INFORME")
    assert hit is not None
    assert hit.texto == "Informe"
    assert hit.confidence == 85
    # Centro del bbox (100..170, 50..72)
    assert hit.x == 135
    assert hit.y == 61


def test_localizar_texto_multipalabra(monkeypatch):
    """'Guardar como' debe encontrarse cuando los 2 tokens están en la
    misma línea con word_num consecutivos."""
    import core.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        Output = types.SimpleNamespace(DICT="dict")

        @staticmethod
        def image_to_data(img, lang=None, output_type=None):
            return {
                "text":       ["File", "Guardar", "como", "PDF"],
                "conf":       [80,     90,        85,     75],
                "left":       [0,      100,       200,    300],
                "top":        [10,     10,        10,     10],
                "width":      [40,     70,        50,     40],
                "height":     [20,     20,        20,     20],
                # Mismo bloque/párrafo/línea, word_num consecutivos.
                "block_num":  [1,      1,         1,      1],
                "par_num":    [1,      1,         1,      1],
                "line_num":   [1,      1,         1,      1],
                "word_num":   [1,      2,         3,      4],
            }

    class _FakeImage:
        @staticmethod
        def open(p): return object()

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", _FakeImage)

    hit = ocr_mod.localizar_texto_en_imagen("x.png", "guardar como")
    assert hit is not None
    # bbox combinado: 100..250 ancho, 10..30 alto → centro (175, 20)
    assert hit.x == 175
    assert hit.y == 20


def test_localizar_texto_multipalabra_rechaza_lineas_distintas(monkeypatch):
    """'Guardar como' NO debe casar si 'Guardar' está en una línea y 'como'
    en otra (ej: 'Guardar' en menú + 'como' en barra de estado)."""
    import core.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        Output = types.SimpleNamespace(DICT="dict")

        @staticmethod
        def image_to_data(img, lang=None, output_type=None):
            return {
                "text":       ["Guardar", "como"],
                "conf":       [90,        85],
                "left":       [10,        500],
                "top":        [20,        500],    # bien lejos verticalmente
                "width":      [70,        50],
                "height":     [20,        20],
                # Líneas DISTINTAS — el filtro debe rechazar el match.
                "block_num":  [1,         2],
                "par_num":    [1,         1],
                "line_num":   [1,         5],
                "word_num":   [1,         1],
            }

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", types.SimpleNamespace(open=lambda p: object()))

    hit = ocr_mod.localizar_texto_en_imagen("x.png", "guardar como")
    assert hit is None, "no debe matchear tokens de líneas distintas"


def test_localizar_texto_multipalabra_fallback_geometrico(monkeypatch):
    """Si Tesseract no devuelve block/par/line/word_num (versión vieja),
    cae a fallback geométrico (misma altura, separación razonable)."""
    import core.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        Output = types.SimpleNamespace(DICT="dict")

        @staticmethod
        def image_to_data(img, lang=None, output_type=None):
            # Sin columnas semánticas. Tokens contiguos horizontalmente
            # y a misma altura → deben matchear.
            return {
                "text":   ["Guardar", "como"],
                "conf":   [90,        85],
                "left":   [100,       180],
                "top":    [10,        10],
                "width":  [70,        50],
                "height": [20,        20],
            }

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", types.SimpleNamespace(open=lambda p: object()))

    hit = ocr_mod.localizar_texto_en_imagen("x.png", "guardar como")
    assert hit is not None


def test_localizar_texto_descarta_baja_confianza(monkeypatch):
    """Tokens con confianza por debajo del umbral se ignoran."""
    import core.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", True)

    class _FakePT:
        Output = types.SimpleNamespace(DICT="dict")

        @staticmethod
        def image_to_data(img, lang=None, output_type=None):
            return {
                "text": ["Aceptar"],  # único token, pero confianza 30
                "conf": [30],
                "left": [50], "top": [50], "width": [60], "height": [20],
            }

    monkeypatch.setattr(ocr_mod, "pytesseract", _FakePT)
    monkeypatch.setattr(ocr_mod, "Image", types.SimpleNamespace(open=lambda p: object()))

    # Con min_confidence=60 (default) → no encontrado
    assert ocr_mod.localizar_texto_en_imagen("x.png", "Aceptar") is None
    # Con min_confidence=20 → sí encontrado
    hit = ocr_mod.localizar_texto_en_imagen("x.png", "Aceptar", min_confidence=20)
    assert hit is not None


def test_localizar_texto_devuelve_none_sin_pytesseract(monkeypatch):
    import core.ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "_HAS_PYTESSERACT", False)
    assert ocr_mod.localizar_texto_en_imagen("x.png", "Aceptar") is None


def test_norm_para_match_quita_acentos_y_baja_caja():
    from core.ocr import _norm_para_match
    assert _norm_para_match("Atención") == "atencion"
    assert _norm_para_match("Información!") == "informacion!"
    assert _norm_para_match("   GERHONTE  ") == "gerhonte"


def test_player_click_ocr_text_dispatch_existe():
    """Inspección estática: _dispatch del Player debe manejar CLICK_OCR_TEXT."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._dispatch)
    assert "CLICK_OCR_TEXT" in src
    assert "_click_ocr_text" in src


def test_player_click_ocr_text_requiere_valor():
    """Llamar a _click_ocr_text con paso.valor vacío debe lanzar ValueError."""
    import threading
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = False
    p._abort = threading.Event()

    paso_vacio = Step(tipo=StepType.CLICK_OCR_TEXT, valor="")
    try:
        Player._click_ocr_text(p, paso_vacio)
        assert False, "debió lanzar ValueError"
    except ValueError as exc:
        assert "click_ocr_text" in str(exc).lower()


def test_capturar_pantalla_completa_con_offset_existe():
    """El helper para multi-monitor existe y devuelve la firma correcta."""
    import inspect
    from core import screenshot
    fn = screenshot.capturar_pantalla_completa_con_offset
    sig = inspect.signature(fn)
    assert "dest_dir" in sig.parameters
    src = inspect.getsource(fn)
    # Debe usar mss.monitors[0] (virtual desktop, no monitor primario).
    assert "monitors[0]" in src
    # Debe devolver una tupla (path, left, top), no solo el path.
    assert "out, int(monitor" in src


def test_click_ocr_text_no_arrastra_offset_si_captura_ventana_falla(monkeypatch):
    """Bug que la auditoría 1 reportó: si la captura de la ventana fallaba
    DESPUÉS de fijar offset_x/offset_y, el fallback a pantalla completa
    sumaba un offset stale a coords relativas a pantalla. Aquí
    verificamos por inspección que offset_x/offset_y solo se asignan
    tras una captura exitosa."""
    import inspect
    from core.player import Player
    src = inspect.getsource(Player._click_ocr_text)
    # La línea que fija offset al rect debe estar bajo `if shot:`
    # (i.e., solo si la captura tuvo éxito).
    idx_if_shot = src.find("if shot:")
    idx_offset = src.find("offset_x, offset_y = int(rect.left)")
    assert idx_if_shot != -1 and idx_offset != -1
    assert idx_offset > idx_if_shot, (
        "offset_x/offset_y deben asignarse DESPUÉS de confirmar éxito "
        "(if shot:), no antes."
    )
    # Y el fallback fullscreen debe usar el helper con offset.
    assert "capturar_pantalla_completa_con_offset" in src


def test_player_click_ocr_text_dry_run_no_explora_ocr(monkeypatch):
    """En dry_run, _click_ocr_text no debe tocar el OCR ni hacer clic real."""
    import threading
    from core.player import Player
    from core.step_model import Step, StepType

    p = Player.__new__(Player)
    p.dry_run = True
    p._abort = threading.Event()

    llamadas = {"ocr": 0, "click": 0}

    def fake_disponible():
        llamadas["ocr"] += 1
        return True

    monkeypatch.setattr("core.ocr.disponible", fake_disponible)

    paso = Step(tipo=StepType.CLICK_OCR_TEXT, valor="Aceptar")
    Player._click_ocr_text(p, paso)
    # En dry-run no debe llamar a disponible() (ni siquiera importar OCR)
    assert llamadas["ocr"] == 0
