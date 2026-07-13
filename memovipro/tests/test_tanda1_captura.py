"""Tests de la Tanda 1 de la auditoría de captura (docs/auditoria-captura-2026-06.md).

Cubre:
  A1 — espacios: no fragmentan el texto y no se pierden en atajos
  A2 — AltGr (teclado español): @ # € [ { son texto, no atajos
  A3 — callbacks de pynput blindados (una excepción no mata el listener)
  A4 — escape de metacaracteres en la base de atajos (Ctrl+'+' → "^{+}")
  A5 — Ctrl+letra como carácter de control (\\x01 → "^a")
  A7 — zonas excluidas: los clics sobre MemoviPro no se graban
  B1 — re.escape del título en el fallback win_rel del player
  B2 — pasos grabados marcados raw=True y respetados por render_step
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.recorder import EventoCrudo, Recorder


class FakeSpecial:
    """Simula una tecla especial de pynput (Key.space, Key.ctrl_l...)."""
    char = None

    def __init__(self, nombre):
        self._n = nombre

    def __str__(self):
        return f"Key.{self._n}"


class FakeChar:
    """Simula un KeyCode de pynput con carácter."""

    def __init__(self, c):
        self.char = c

    def __str__(self):
        return f"'{self.char}'"


def _recorder_grabando() -> Recorder:
    rec = Recorder()
    rec._grabando = True
    return rec


def _teclear(rec: Recorder, *teclas):
    for t in teclas:
        rec._on_press(t)
        rec._on_release(t)


def _flush(rec: Recorder):
    with rec._lock:
        rec._flush_text(force=True)


# ==================== A1: espacios ====================

def test_a1_espacio_no_fragmenta_el_texto():
    """'hola mundo' debe ser UN solo type_text, no 3 pasos."""
    rec = _recorder_grabando()
    for c in "hola":
        _teclear(rec, FakeChar(c))
    _teclear(rec, FakeSpecial("space"))
    for c in "mundo":
        _teclear(rec, FakeChar(c))
    _flush(rec)
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "type_text"
    assert evt.valor == "hola mundo"


def test_a1_ctrl_espacio_genera_token_valido():
    """Ctrl+Espacio debe ser '^{SPACE}', no el token roto '^ '."""
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeSpecial("space"))
    rec._on_release(FakeSpecial("ctrl_l"))
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "send_keys"
    assert evt.valor == "^{SPACE}"


# ==================== A2: AltGr ====================

def test_a2_altgr_arroba_es_texto():
    """AltGr+2 = '@' en teclado ES. Windows envía ctrl sintético + alt_gr.
    El '@' debe ir al buffer de texto, no grabarse como atajo Ctrl+Alt+@."""
    rec = _recorder_grabando()
    # Secuencia real de Windows: ctrl_l sintético, luego alt_gr.
    rec._on_press(FakeSpecial("ctrl_l"))
    rec._on_press(FakeSpecial("alt_gr"))
    _teclear(rec, FakeChar("@"))
    rec._on_release(FakeSpecial("alt_gr"))
    rec._on_release(FakeSpecial("ctrl_l"))
    _flush(rec)
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "type_text"
    assert evt.valor == "@"


def test_a2_email_completo_con_altgr():
    """Un email tecleado con AltGr para la @ queda como un único texto."""
    rec = _recorder_grabando()
    for c in "user":
        _teclear(rec, FakeChar(c))
    rec._on_press(FakeSpecial("ctrl_l"))
    rec._on_press(FakeSpecial("alt_gr"))
    _teclear(rec, FakeChar("@"))
    rec._on_release(FakeSpecial("alt_gr"))
    rec._on_release(FakeSpecial("ctrl_l"))
    for c in "sas.es":
        _teclear(rec, FakeChar(c))
    _flush(rec)
    assert len(rec.eventos_crudos) == 1
    assert rec.eventos_crudos[0].valor == "user@sas.es"


def test_a2_ctrl_solo_sigue_siendo_atajo():
    """Ctrl+A (sin AltGr) debe seguir grabándose como atajo '^a'."""
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeChar("a"))
    rec._on_release(FakeSpecial("ctrl_l"))
    assert len(rec.eventos_crudos) == 1
    evt = rec.eventos_crudos[0]
    assert evt.tipo == "send_keys"
    assert evt.valor == "^a"


# ==================== A3: callbacks blindados ====================

def test_a3_excepcion_en_click_no_propaga(monkeypatch):
    """pynput mata el listener si un callback lanza: el wrapper debe tragar
    y loguear, nunca propagar."""
    rec = _recorder_grabando()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rec, "_emitir_click", boom)
    rec._on_click(10, 10, "Button.left", True)
    rec._on_click(10, 10, "Button.left", False)  # release → _emitir_click → boom
    # No propaga y no hay evento a medias.
    assert rec.eventos_crudos == []


def test_a3_excepcion_en_press_no_propaga(monkeypatch):
    rec = _recorder_grabando()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rec, "_flush_text", boom)
    rec._on_press(FakeSpecial("enter"))  # flush dentro del impl → boom
    assert rec.eventos_crudos == []


def test_a3_excepcion_en_scroll_no_propaga(monkeypatch):
    rec = _recorder_grabando()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rec, "_flush_text", boom)
    rec._on_scroll(10, 10, 0, 1)
    assert rec.eventos_crudos == []


# ==================== A4: escape de la base del atajo ====================

def test_a4_ctrl_mas_se_escapa():
    """Ctrl+'+' debe ser '^{+}' — '^+' es un prefijo roto (Ctrl+Shift sin tecla)."""
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeChar("+"))
    rec._on_release(FakeSpecial("ctrl_l"))
    assert rec.eventos_crudos[0].valor == "^{+}"


def test_a4_ctrl_parentesis_se_escapa():
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeChar("("))
    rec._on_release(FakeSpecial("ctrl_l"))
    assert rec.eventos_crudos[0].valor == "^{(}"


# ==================== A5: Ctrl+letra como control char ====================

def test_a5_ctrl_letra_recupera_la_letra():
    """En Windows pynput entrega '\\x01' para Ctrl+A: debe grabarse '^a'."""
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeChar("\x01"))  # Ctrl+A
    rec._on_release(FakeSpecial("ctrl_l"))
    assert rec.eventos_crudos[0].valor == "^a"


def test_a5_ctrl_z_recupera_la_letra():
    rec = _recorder_grabando()
    rec._on_press(FakeSpecial("ctrl_l"))
    _teclear(rec, FakeChar("\x1a"))  # Ctrl+Z
    rec._on_release(FakeSpecial("ctrl_l"))
    assert rec.eventos_crudos[0].valor == "^z"


# ==================== A7: zonas excluidas ====================

def test_a7_click_en_zona_excluida_no_se_graba():
    rec = _recorder_grabando()
    rec.zonas_excluidas = [(100, 100, 200, 150)]
    rec._on_click(150, 120, "Button.left", True)
    rec._on_click(150, 120, "Button.left", False)
    assert rec.eventos_crudos == []


def test_a7_click_fuera_de_zona_si_se_graba():
    rec = _recorder_grabando()
    rec.zonas_excluidas = [(100, 100, 200, 150)]
    rec._on_click(500, 500, "Button.left", True)
    rec._on_click(500, 500, "Button.left", False)
    assert len(rec.eventos_crudos) == 1
    assert rec.eventos_crudos[0].tipo == "click"


def test_a7_scroll_en_zona_excluida_no_se_graba():
    rec = _recorder_grabando()
    rec.zonas_excluidas = [(0, 0, 300, 300)]
    rec._on_scroll(50, 50, 0, 1)
    assert rec.eventos_crudos == []


def test_a7_release_sobre_zona_descarta_pendiente():
    """Un arrastre que termina sobre el panel flotante no debe emitir nada."""
    rec = _recorder_grabando()
    rec.zonas_excluidas = [(100, 100, 200, 150)]
    rec._on_click(500, 500, "Button.left", True)   # press fuera
    rec._on_click(150, 120, "Button.left", False)  # release dentro del panel
    assert rec.eventos_crudos == []


# ==================== B1: re.escape del título win_rel ====================

def test_b1_titulo_con_regex_specials_se_escapa(monkeypatch):
    import core.player as pl

    captured = {}

    class FakeWin:
        def exists(self, timeout=0):
            return False

    class FakeDesktop:
        def __init__(self, backend):
            pass

        def window(self, **kw):
            captured.update(kw)
            return FakeWin()

    monkeypatch.setattr(pl, "Desktop", FakeDesktop)
    monkeypatch.setattr(pl, "_HAS_PYWINAUTO", True)
    p = pl.Player.__new__(pl.Player)
    p.dry_run = False

    titulo = "Doc1 [Modo compatibilidad] (v2)+"
    ok = pl.Player._click_window_relative(p, {"title": titulo, "fx": 0.5, "fy": 0.5})
    assert ok is False  # la ventana fake no existe
    assert re.escape(titulo) in captured["title_re"]
    # El patrón resultante debe compilar sin error (Notepad++ etc.)
    re.compile(captured["title_re"])


# ==================== B2: raw en pasos grabados ====================

def test_b2_construir_macro_marca_raw():
    eventos = [
        EventoCrudo(tipo="type_text", valor="hola {DNI}", timestamp=1.0),
        EventoCrudo(tipo="send_keys", valor="{ENTER}", timestamp=2.0),
    ]
    macro = Recorder.construir_macro(eventos, resolver_selectores=False)
    assert macro.pasos[0].extra.get("raw") is True
    assert macro.pasos[1].extra.get("raw") is True


def test_b2_render_step_respeta_raw():
    from core.step_model import Step, StepType, render_step

    paso = Step(
        tipo=StepType.TYPE_TEXT,
        valor="literal {DNI} y {SECRET:clave_gerhonte}",
        extra={"raw": True},
    )
    out = render_step(paso, {"DNI": "12345678Z"})
    # Con raw, el valor queda EXACTAMENTE igual: ni {DNI} ni {SECRET:...}
    assert out.valor == "literal {DNI} y {SECRET:clave_gerhonte}"


def test_b2_sin_raw_los_placeholders_siguen_funcionando():
    from core.step_model import Step, StepType, render_step

    paso = Step(tipo=StepType.TYPE_TEXT, valor="dni={DNI}")
    out = render_step(paso, {"DNI": "12345678Z"})
    assert out.valor == "dni=12345678Z"


def test_b2_send_keys_raw_no_colisiona_con_columna_enter():
    """Si el Excel tiene una columna 'enter', el token {ENTER} de un paso
    grabado NO debe sustituirse."""
    from core.step_model import Step, StepType, render_step

    paso = Step(tipo=StepType.SEND_KEYS, valor="{ENTER}", extra={"raw": True})
    out = render_step(paso, {"ENTER": "valor_de_la_celda"})
    assert out.valor == "{ENTER}"


# ==================== Ronda 2: fixes de la revisión ====================

def test_editar_valor_de_paso_grabado_quita_raw():
    """Flujo documentado: grabar y luego editar el valor poniendo {DNI}.
    Al cambiar el valor a mano, el flag raw debe desaparecer para que el
    placeholder vuelva a sustituirse."""
    from core.step_model import Step, StepType, limpiar_raw_si_editado, render_step

    paso = Step(tipo=StepType.TYPE_TEXT, valor="12345678Z", extra={"raw": True})
    limpiar_raw_si_editado(paso, "{DNI}")
    paso.valor = "{DNI}"
    assert "raw" not in paso.extra
    out = render_step(paso, {"DNI": "87654321X"})
    assert out.valor == "87654321X"


def test_aceptar_sin_cambiar_valor_conserva_raw():
    """Abrir el editor y aceptar sin tocar NO debe reactivar los
    placeholders sobre un literal grabado."""
    from core.step_model import Step, StepType, limpiar_raw_si_editado

    paso = Step(tipo=StepType.TYPE_TEXT, valor="literal {DNI}", extra={"raw": True})
    limpiar_raw_si_editado(paso, "literal {DNI}")  # mismo valor
    assert paso.extra.get("raw") is True


def test_zonas_excluidas_usan_coordenadas_fisicas():
    """record_dialog debe publicar rects en píxeles FÍSICOS (GetWindowRect
    en Windows / frameGeometry×devicePixelRatio como fallback), porque
    pynput entrega coords físicas y Qt lógicas — con escalado 125/150%
    las zonas quedarían desplazadas."""
    # Inspección sobre el fichero (importar ui.record_dialog requiere
    # PyQt6, no disponible en todos los entornos de test).
    src = (ROOT / "ui" / "record_dialog.py").read_text(encoding="utf-8")
    assert "GetWindowRect" in src
    assert "devicePixelRatio" in src
    assert "_rect_fisico" in src
    # _actualizar_zonas_excluidas debe usar el rect físico, no frameGeometry directo
    zona_fn = src.split("def _actualizar_zonas_excluidas")[1].split("def _tick_update")[0]
    assert "_rect_fisico" in zona_fn
