"""Inspector de controles: clic en cualquier ventana y obtienes su selector."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class CapturaSelector:
    control_type: str | None
    name: str | None
    auto_id: str | None
    class_name: str | None
    x: int
    y: int

    def yaml_snippet(self) -> str:
        bits = []
        if self.control_type:
            bits.append(f"      control_type: {self.control_type}")
        if self.name:
            bits.append(f"      name: {self.name!r}".replace("'", '"'))
        if self.auto_id:
            bits.append(f"      auto_id: {self.auto_id}")
        if self.class_name:
            bits.append(f"      class_name: {self.class_name}")
        if not bits:
            return f"    # No se pudo resolver selector. Coordenadas: ({self.x},{self.y})"
        return "    selector:\n" + "\n".join(bits)


class Inspector(QObject):
    """Captura el próximo clic del usuario y emite un selector simbólico.

    Funciona en Windows con pywinauto+pynput. En el resto de plataformas
    emite un error.
    """

    captured = pyqtSignal(object)  # CapturaSelector
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._listener = None
        self._lock = threading.Lock()

    def empezar(self) -> None:
        try:
            from pynput import mouse
        except Exception as exc:
            self.error.emit(f"pynput no disponible: {exc}")
            return
        try:
            from pywinauto import Desktop  # noqa: F401
        except Exception as exc:
            self.error.emit(f"pywinauto no disponible: {exc}")
            return

        def on_click(x, y, button, pressed):
            if not pressed:
                return None
            self._resolver(int(x), int(y))
            return False  # detiene el listener

        with self._lock:
            if self._listener is not None:
                return
            self._listener = mouse.Listener(on_click=on_click)
            self._listener.start()

    def cancelar(self) -> None:
        with self._lock:
            if self._listener is not None:
                self._listener.stop()
                self._listener = None

    def _resolver(self, x: int, y: int) -> None:
        try:
            from pywinauto import Desktop
            elem = Desktop(backend="uia").from_point(x, y)
            try:
                ctrl = elem.element_info.control_type
            except Exception:
                ctrl = None
            try:
                auto_id = elem.element_info.automation_id
            except Exception:
                auto_id = None
            try:
                class_name = elem.class_name()
            except Exception:
                class_name = None
            name = (elem.window_text() or "").strip() or None
            captura = CapturaSelector(
                control_type=ctrl,
                name=name,
                auto_id=auto_id,
                class_name=class_name,
                x=x,
                y=y,
            )
            self.captured.emit(captura)
        except Exception as exc:
            self.error.emit(f"No se pudo resolver el control: {exc}")
        finally:
            with self._lock:
                self._listener = None
