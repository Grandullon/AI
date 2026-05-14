from __future__ import annotations

import threading
import time
from dataclasses import dataclass

try:
    from pynput import keyboard, mouse
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False

try:
    from pywinauto import Desktop
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False

from .step_model import Macro, Selector, Step, StepType


@dataclass
class _BufferTexto:
    texto: str = ""
    ultimo_ts: float = 0.0


def _selector_desde_punto(x: int, y: int) -> Selector | None:
    """Resuelve el control bajo (x,y) y devuelve un selector simbólico."""
    if not _HAS_PYWINAUTO:
        return None
    try:
        elem = Desktop(backend="uia").from_point(x, y)
        name = (elem.window_text() or "").strip()
        try:
            ctrl_type = elem.element_info.control_type
        except Exception:
            ctrl_type = None
        try:
            auto_id = elem.element_info.automation_id
        except Exception:
            auto_id = None
        try:
            class_name = elem.class_name()
        except Exception:
            class_name = None
        sel = Selector(
            control_type=ctrl_type,
            name=name or None,
            auto_id=auto_id or None,
            class_name=class_name or None,
        )
        return sel if not sel.is_empty() else None
    except Exception:
        return None


class Recorder:
    """Graba acciones del usuario y produce una lista de Steps simbólicos.

    Filtra movimientos del ratón, agrupa pulsaciones de teclado en `type_text`,
    y resuelve cada clic en un selector UI Automation.
    """

    FLUSH_TEXT_AFTER_S = 0.8

    def __init__(self):
        self.pasos: list[Step] = []
        self._buf = _BufferTexto()
        self._lock = threading.Lock()
        self._grabando = False
        self._mouse_listener = None
        self._kb_listener = None

    def start(self) -> None:
        if not _HAS_PYNPUT:
            raise RuntimeError("pynput no disponible")
        self._grabando = True
        self.pasos = []
        self._buf = _BufferTexto()
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener.start()
        self._kb_listener.start()

    def stop(self) -> Macro:
        self._grabando = False
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kb_listener:
            self._kb_listener.stop()
        self._flush_text(force=True)
        return Macro(nombre="grabacion", pasos=list(self.pasos))

    def _on_click(self, x, y, button, pressed):
        if not self._grabando or not pressed:
            return
        with self._lock:
            self._flush_text(force=True)
            sel = _selector_desde_punto(x, y)
            if sel:
                self.pasos.append(Step(
                    tipo=StepType.CLICK_CONTROL,
                    selector=sel,
                    descripcion=f"Click en {sel.name or sel.control_type or sel.class_name}",
                ))
            else:
                self.pasos.append(Step(
                    tipo=StepType.CLICK_AT_XY,
                    extra={"x": x, "y": y},
                    descripcion=f"Click en ({x},{y}) — sin selector",
                ))

    def _on_press(self, key):
        if not self._grabando:
            return
        with self._lock:
            char = self._tecla_a_char(key)
            if char is None:
                self._flush_text(force=True)
                token = self._tecla_a_send_keys(key)
                if token:
                    self.pasos.append(Step(
                        tipo=StepType.SEND_KEYS,
                        valor=token,
                        descripcion=f"Tecla {token}",
                    ))
                return
            self._buf.texto += char
            self._buf.ultimo_ts = time.time()

    def _on_release(self, key):
        pass

    def _flush_text(self, force: bool = False) -> None:
        if not self._buf.texto:
            return
        if not force and (time.time() - self._buf.ultimo_ts) < self.FLUSH_TEXT_AFTER_S:
            return
        self.pasos.append(Step(
            tipo=StepType.TYPE_TEXT,
            valor=self._buf.texto,
            descripcion=f'Escribir "{self._buf.texto[:30]}"',
        ))
        self._buf = _BufferTexto()

    @staticmethod
    def _tecla_a_char(key) -> str | None:
        try:
            if hasattr(key, "char") and key.char is not None and len(key.char) == 1:
                return key.char
        except Exception:
            pass
        return None

    @staticmethod
    def _tecla_a_send_keys(key) -> str | None:
        nombre = str(key).replace("Key.", "").replace("'", "")
        mapping = {
            "enter": "{ENTER}",
            "tab": "{TAB}",
            "esc": "{ESC}",
            "space": " ",
            "backspace": "{BACKSPACE}",
            "delete": "{DELETE}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
            "home": "{HOME}",
            "end": "{END}",
            "page_up": "{PGUP}",
            "page_down": "{PGDN}",
        }
        if nombre in mapping:
            return mapping[nombre]
        if nombre.startswith("f") and nombre[1:].isdigit():
            return "{" + nombre.upper() + "}"
        return None
