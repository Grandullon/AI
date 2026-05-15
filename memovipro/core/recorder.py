"""Grabador de macros.

Diseño en dos fases para no bloquear la GUI:

1) **Captura cruda (rápida)** — los listeners de `pynput` solo almacenan
   coordenadas y teclas. No se llama a pywinauto durante la grabación.
   Esto hace que:
   - El usuario no note retardo entre clics.
   - `stop()` retorne casi al instante (no espera resolución de selectores).

2) **Resolución de selectores (lenta)** — una vez detenida la grabación,
   `Recorder.construir_macro(eventos, resolver_selectores=True)` recorre
   los clics e intenta resolver cada uno a `click_control` con selector
   simbólico vía pywinauto UI Automation. Esto debe ejecutarse en un
   QThread aparte (lo hace `RecordDialog`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

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


# Teclas que no deben aparecer en la macro grabada (controles del propio recorder).
TECLAS_IGNORADAS = {"f9"}


@dataclass
class _BufferTexto:
    texto: str = ""
    ultimo_ts: float = 0.0


@dataclass
class EventoCrudo:
    tipo: str  # 'click' | 'type_text' | 'send_keys'
    x: int = 0
    y: int = 0
    button: str = ""
    valor: str = ""
    descripcion: str = ""
    timestamp: float = 0.0  # time.time() del evento, para calcular delays al reproducir


def _selector_desde_punto(x: int, y: int) -> tuple[Selector | None, str]:
    """Resuelve (x,y) a un selector simbólico vía UI Automation.

    Devuelve (selector_o_None, descripción). Si falla cualquier paso,
    devuelve (None, "(x,y)") para que el llamador caiga a click_at_xy.
    """
    if not _HAS_PYWINAUTO:
        return None, f"({x},{y})"
    try:
        elem = Desktop(backend="uia").from_point(x, y)
    except Exception:
        return None, f"({x},{y})"
    try:
        name = (elem.window_text() or "").strip()
    except Exception:
        name = ""
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
    if sel.is_empty():
        return None, f"({x},{y})"
    desc = name or ctrl_type or class_name or f"({x},{y})"
    return sel, desc


class Recorder:
    """Captura eventos crudos sin tocar pywinauto durante la grabación.

    Para obtener la `Macro` resuelta hay que llamar después a
    `Recorder.construir_macro(events, resolver_selectores=True)`.
    """

    FLUSH_TEXT_AFTER_S = 0.8

    def __init__(self):
        self.eventos_crudos: list[EventoCrudo] = []
        self._buf = _BufferTexto()
        self._lock = threading.Lock()
        self._grabando = False
        self._mouse_listener = None
        self._kb_listener = None

    # Propiedad usada por la GUI para el contador en vivo.
    @property
    def pasos(self) -> list[EventoCrudo]:
        return self.eventos_crudos

    def start(self) -> None:
        if not _HAS_PYNPUT:
            raise RuntimeError("pynput no disponible")
        self._grabando = True
        self.eventos_crudos = []
        self._buf = _BufferTexto()
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=lambda k: None)
        self._mouse_listener.start()
        self._kb_listener.start()

    def stop(self) -> list[EventoCrudo]:
        """Detiene los listeners y devuelve los eventos crudos.

        Espera a que los hilos de pynput finalicen antes de retornar
        (timeout 2s cada uno). Esto es importante en Windows: los
        WH_KEYBOARD_LL / WH_MOUSE_LL siguen instalados hasta que el
        hilo dueño termina, y mientras estén instalados los diálogos
        nativos de Windows (file dialog, etc.) pueden congelarse.
        """
        self._grabando = False
        listeners = [l for l in (self._mouse_listener, self._kb_listener) if l is not None]
        for lst in listeners:
            try:
                lst.stop()
            except Exception:
                pass
        for lst in listeners:
            try:
                if lst.is_alive():
                    lst.join(timeout=2.0)
            except Exception:
                pass
        self._mouse_listener = None
        self._kb_listener = None
        with self._lock:
            self._flush_text(force=True)
        return list(self.eventos_crudos)

    # ---- Callbacks ----
    def _on_click(self, x, y, button, pressed):
        if not self._grabando or not pressed:
            return
        with self._lock:
            self._flush_text(force=True)
            self.eventos_crudos.append(EventoCrudo(
                tipo="click",
                x=int(x), y=int(y),
                button=str(button),
                descripcion=f"Click ({x},{y})",
                timestamp=time.time(),
            ))

    def _on_press(self, key):
        if not self._grabando:
            return
        nombre = str(key).replace("Key.", "").replace("'", "")
        if nombre in TECLAS_IGNORADAS:
            return
        with self._lock:
            char = self._tecla_a_char(key)
            if char is not None:
                self._buf.texto += char
                self._buf.ultimo_ts = time.time()
                return
            self._flush_text(force=True)
            token = self._tecla_a_send_keys(key)
            if token:
                self.eventos_crudos.append(EventoCrudo(
                    tipo="send_keys",
                    valor=token,
                    descripcion=f"Tecla {token}",
                    timestamp=time.time(),
                ))

    def _flush_text(self, force: bool = False) -> None:
        if not self._buf.texto:
            return
        if not force and (time.time() - self._buf.ultimo_ts) < self.FLUSH_TEXT_AFTER_S:
            return
        # Para texto agrupado, el timestamp es el del último carácter tecleado.
        ts = self._buf.ultimo_ts or time.time()
        self.eventos_crudos.append(EventoCrudo(
            tipo="type_text",
            valor=self._buf.texto,
            descripcion=f'Escribir "{self._buf.texto[:30]}"',
            timestamp=ts,
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
            "enter": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}",
            "space": " ", "backspace": "{BACKSPACE}", "delete": "{DELETE}",
            "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
            "home": "{HOME}", "end": "{END}", "page_up": "{PGUP}", "page_down": "{PGDN}",
        }
        if nombre in mapping:
            return mapping[nombre]
        if nombre.startswith("f") and nombre[1:].isdigit():
            return "{" + nombre.upper() + "}"
        return None

    # ---- Construcción de la Macro (puede ser lenta si se resuelven selectores) ----
    # Cap a la pausa entre eventos: nadie quiere reproducir una pausa de varios
    # minutos porque el usuario se fue a por café a mitad de la grabación.
    MAX_DELAY_S = 30.0

    @staticmethod
    def construir_macro(
        eventos: list[EventoCrudo],
        resolver_selectores: bool = True,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Macro:
        """Convierte eventos crudos en una `Macro` con delays preservados.

        El campo `delay_before_s` de cada paso refleja el tiempo real
        transcurrido entre el evento anterior y éste (limitado a
        MAX_DELAY_S para evitar pausas absurdamente largas).
        """
        total_clicks = sum(1 for e in eventos if e.tipo == "click")
        n_click = 0
        pasos: list[Step] = []
        prev_ts: float | None = None
        for evt in eventos:
            delay = 0.0
            if prev_ts is not None and evt.timestamp > 0:
                delay = max(0.0, evt.timestamp - prev_ts)
                if delay > Recorder.MAX_DELAY_S:
                    delay = Recorder.MAX_DELAY_S
            if evt.timestamp > 0:
                prev_ts = evt.timestamp

            if evt.tipo == "click":
                n_click += 1
                sel = None
                desc = evt.descripcion
                if resolver_selectores:
                    sel, desc = _selector_desde_punto(evt.x, evt.y)
                if sel is not None:
                    pasos.append(Step(
                        tipo=StepType.CLICK_CONTROL,
                        selector=sel,
                        descripcion=f"Click en {desc}",
                        delay_before_s=delay,
                        # Guardamos coordenadas originales como fallback:
                        # si el selector simbólico no se resuelve al reproducir,
                        # el player hace click_at_xy en estas coordenadas.
                        extra={"fallback_xy": [evt.x, evt.y]},
                    ))
                else:
                    pasos.append(Step(
                        tipo=StepType.CLICK_AT_XY,
                        extra={"x": evt.x, "y": evt.y},
                        descripcion=f"Click en ({evt.x},{evt.y}) — sin selector",
                        delay_before_s=delay,
                    ))
                if on_progress is not None:
                    on_progress(n_click, total_clicks)
            elif evt.tipo == "type_text":
                pasos.append(Step(
                    tipo=StepType.TYPE_TEXT,
                    valor=evt.valor,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
            elif evt.tipo == "send_keys":
                pasos.append(Step(
                    tipo=StepType.SEND_KEYS,
                    valor=evt.valor,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
        return Macro(nombre="grabacion", pasos=pasos)
