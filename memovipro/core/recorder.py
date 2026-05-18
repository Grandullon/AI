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

try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def debug(self, *a, **kw): pass
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def exception(self, *a, **kw): pass
    logger = _NullLogger()

from .step_model import Macro, Selector, Step, StepType


# Teclas que no deben aparecer en la macro grabada (controles del propio recorder).
TECLAS_IGNORADAS = {"f9"}

# Detección de doble clic: dos clics del mismo botón en la misma posición
# (con tolerancia DOUBLE_CLICK_RADIUS_PX) dentro de DOUBLE_CLICK_THRESHOLD_S
# se fusionan en un único evento marcado como `double=True`.
DOUBLE_CLICK_THRESHOLD_S = 0.5
DOUBLE_CLICK_RADIUS_PX = 8


@dataclass
class _BufferTexto:
    texto: str = ""
    ultimo_ts: float = 0.0


@dataclass
class EventoCrudo:
    tipo: str  # 'click' | 'type_text' | 'send_keys' | 'scroll' | 'drag'
    x: int = 0
    y: int = 0
    x2: int = 0  # destino del drag
    y2: int = 0
    dx: int = 0  # desplazamiento de rueda horizontal
    dy: int = 0  # desplazamiento de rueda vertical (positivo = arriba)
    button: str = "left"  # 'left' | 'right' | 'middle'
    double: bool = False
    modifiers: str = ""  # ej. "ctrl" | "ctrl+shift" | "" (sin modificadores)
    valor: str = ""
    descripcion: str = ""
    timestamp: float = 0.0


# Distancia mínima en píxeles para considerar que un press+release es un drag,
# no un click. Por debajo se trata como click (con tolerancia para "manos
# inestables" al hacer doble clic, p.ej.).
DRAG_DIST_THRESHOLD_PX = 8


def _button_corto(button) -> str:
    """Normaliza un botón de pynput ('Button.left') a 'left'/'right'/'middle'."""
    s = str(button).replace("Button.", "").lower().strip()
    if "right" in s:
        return "right"
    if "middle" in s:
        return "middle"
    return "left"


def _modifier_for(nombre: str) -> str | None:
    """Devuelve 'ctrl' | 'shift' | 'alt' si `nombre` es una tecla modificadora.

    pynput entrega ctrl_l, ctrl_r, shift_l, shift_r, alt_l, alt_r, alt_gr...
    Los unificamos a un solo nombre lógico por familia.
    """
    n = nombre.lower()
    if n in ("ctrl", "ctrl_l", "ctrl_r"):
        return "ctrl"
    if n in ("shift", "shift_l", "shift_r"):
        return "shift"
    if n in ("alt", "alt_l", "alt_r", "alt_gr"):
        return "alt"
    return None


def _modifiers_sendkeys_prefix(mods: set[str]) -> str:
    """Construye el prefijo SendKeys (estilo pywinauto): ^ + % para Ctrl/Shift/Alt.

    Orden estándar: Ctrl+Alt+Shift.
    """
    prefix = ""
    if "ctrl" in mods:
        prefix += "^"
    if "alt" in mods:
        prefix += "%"
    if "shift" in mods:
        prefix += "+"
    return prefix


def _modifiers_str(mods: set[str]) -> str:
    """Serializa el set a 'ctrl+shift' (orden estable)."""
    orden = ["ctrl", "alt", "shift"]
    presentes = [m for m in orden if m in mods]
    return "+".join(presentes)


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
        # Estado vivo de teclas modificadoras pulsadas. Se rellena en
        # _on_press y se vacía en _on_release. Los clics y las teclas
        # con Ctrl/Alt activo lo consultan para etiquetarse.
        self._modifiers: set[str] = set()
        # Press de ratón pendiente de release (para detectar drag).
        self._press_pendiente: dict | None = None

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
        self._modifiers = set()
        self._press_pendiente = None
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener.start()
        self._kb_listener.start()
        logger.info("Recorder.start · listeners pynput arrancados")

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
        logger.info(
            "Recorder.stop · {} eventos crudos capturados (clicks={}, type_text={}, send_keys={}, scroll={}, drag={})",
            len(self.eventos_crudos),
            sum(1 for e in self.eventos_crudos if e.tipo == "click"),
            sum(1 for e in self.eventos_crudos if e.tipo == "type_text"),
            sum(1 for e in self.eventos_crudos if e.tipo == "send_keys"),
            sum(1 for e in self.eventos_crudos if e.tipo == "scroll"),
            sum(1 for e in self.eventos_crudos if e.tipo == "drag"),
        )
        return list(self.eventos_crudos)

    # ---- Callbacks ----
    def _on_click(self, x, y, button, pressed):
        """Maneja press y release del ratón.

        En el press guardamos la posición y el botón en `_press_pendiente`.
        En el release decidimos si fue un click (release cerca del press)
        o un drag (release significativamente lejos del press).
        """
        if not self._grabando:
            return
        btn = _button_corto(button)
        if pressed:
            with self._lock:
                self._press_pendiente = {
                    "x": int(x), "y": int(y),
                    "button": btn,
                    "modifiers": _modifiers_str(self._modifiers),
                    "timestamp": time.time(),
                }
            return
        # ----- Release -----
        with self._lock:
            pendiente = self._press_pendiente
            self._press_pendiente = None
            if pendiente is None or pendiente["button"] != btn:
                return  # release huérfano: ignorar
            self._flush_text(force=True)
            dx_abs = abs(int(x) - pendiente["x"])
            dy_abs = abs(int(y) - pendiente["y"])
            if dx_abs > DRAG_DIST_THRESHOLD_PX or dy_abs > DRAG_DIST_THRESHOLD_PX:
                # Es un drag (arrastrar).
                self._emitir_drag(pendiente, int(x), int(y))
            else:
                # Click normal. Usamos la posición del press (más natural;
                # un usuario que mueve 2-3 px sin querer no debe cambiar
                # el objetivo).
                self._emitir_click(pendiente)

    def _emitir_click(self, pendiente: dict) -> None:
        """Emite un click. Asume _lock ya adquirido por el caller."""
        ahora = pendiente["timestamp"]  # usamos timestamp del press
        btn = pendiente["button"]
        mods = pendiente["modifiers"]
        x = pendiente["x"]
        y = pendiente["y"]
        # ¿Es la segunda mitad de un doble clic? (modificadores y botón coinciden)
        if self.eventos_crudos:
            ultimo = self.eventos_crudos[-1]
            if (
                ultimo.tipo == "click"
                and not ultimo.double
                and ultimo.button == btn
                and ultimo.modifiers == mods
                and (ahora - ultimo.timestamp) < DOUBLE_CLICK_THRESHOLD_S
                and abs(ultimo.x - x) <= DOUBLE_CLICK_RADIUS_PX
                and abs(ultimo.y - y) <= DOUBLE_CLICK_RADIUS_PX
            ):
                ultimo.double = True
                ultimo.descripcion = self._descripcion_click(ultimo.x, ultimo.y, btn, mods, double=True)
                return
        self.eventos_crudos.append(EventoCrudo(
            tipo="click",
            x=x, y=y,
            button=btn,
            modifiers=mods,
            descripcion=self._descripcion_click(x, y, btn, mods, double=False),
            timestamp=ahora,
        ))

    def _emitir_drag(self, pendiente: dict, x_release: int, y_release: int) -> None:
        """Emite un drag de (press.x, press.y) a (release.x, release.y)."""
        mods_label = pendiente["modifiers"].upper() + " " if pendiente["modifiers"] else ""
        btn_suffix = "" if pendiente["button"] == "left" else f" [{pendiente['button']}]"
        desc = (
            f"{mods_label}Drag {pendiente['x']},{pendiente['y']} → "
            f"{x_release},{y_release}{btn_suffix}"
        )
        self.eventos_crudos.append(EventoCrudo(
            tipo="drag",
            x=pendiente["x"], y=pendiente["y"],
            x2=x_release, y2=y_release,
            button=pendiente["button"],
            modifiers=pendiente["modifiers"],
            descripcion=desc,
            timestamp=pendiente["timestamp"],
        ))

    def _on_scroll(self, x, y, dx, dy):
        """Captura la rueda del ratón. Cada notch es un evento independiente."""
        if not self._grabando:
            return
        with self._lock:
            self._flush_text(force=True)
            mods = _modifiers_str(self._modifiers)
            direccion = "↑" if dy > 0 else ("↓" if dy < 0 else ("→" if dx > 0 else "←"))
            mods_label = mods.upper() + " " if mods else ""
            desc = f"{mods_label}Scroll {direccion} ({x},{y})"
            self.eventos_crudos.append(EventoCrudo(
                tipo="scroll",
                x=int(x), y=int(y),
                dx=int(dx), dy=int(dy),
                modifiers=mods,
                descripcion=desc,
                timestamp=time.time(),
            ))

    @staticmethod
    def _descripcion_click(x: int, y: int, btn: str, mods: str, double: bool) -> str:
        partes = []
        if mods:
            partes.append(mods.replace("+", "+").upper())
        partes.append("Doble click" if double else "Click")
        if btn != "left":
            partes.append(f"[{btn}]")
        partes.append(f"({x},{y})")
        return " ".join(partes)

    def _on_press(self, key):
        if not self._grabando:
            return
        nombre = str(key).replace("Key.", "").replace("'", "")
        if nombre in TECLAS_IGNORADAS:
            return
        # Tecla modificadora: solo actualizar estado, sin emitir evento.
        mod = _modifier_for(nombre)
        if mod is not None:
            with self._lock:
                self._modifiers.add(mod)
                # Si había buffer de texto, flush antes (un Ctrl que llega
                # interrumpe el flujo de tecleo natural).
                self._flush_text(force=True)
            return
        with self._lock:
            char = self._tecla_a_char(key)
            # Si hay Ctrl o Alt activos, es un atajo (Ctrl+A, Alt+F, ...)
            # — no texto normal. Shift solo se considera "texto en mayúscula"
            # y se deja al buffer.
            non_shift_mods = self._modifiers - {"shift"}
            if char is not None and not non_shift_mods:
                self._buf.texto += char
                self._buf.ultimo_ts = time.time()
                return
            self._flush_text(force=True)
            if char is not None:
                # Letra con Ctrl/Alt: emitir como atajo de teclado.
                token = _modifiers_sendkeys_prefix(self._modifiers) + char
            else:
                base = self._tecla_a_send_keys(key)
                if not base:
                    return
                token = _modifiers_sendkeys_prefix(self._modifiers) + base
            self.eventos_crudos.append(EventoCrudo(
                tipo="send_keys",
                valor=token,
                descripcion=f"Tecla {token}",
                timestamp=time.time(),
            ))

    def _on_release(self, key):
        if not self._grabando:
            return
        nombre = str(key).replace("Key.", "").replace("'", "")
        mod = _modifier_for(nombre)
        if mod is None:
            return
        with self._lock:
            self._modifiers.discard(mod)

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
                # Prefijos para la descripción del paso
                mods_label = evt.modifiers.upper() + " " if evt.modifiers else ""
                accion = "Doble click" if evt.double else "Click"
                btn_suffix = "" if evt.button == "left" else f" [{evt.button}]"
                if sel is not None:
                    extra: dict = {"fallback_xy": [evt.x, evt.y]}
                    if evt.button != "left":
                        extra["button"] = evt.button
                    if evt.double:
                        extra["double"] = True
                    if evt.modifiers:
                        extra["modifiers"] = evt.modifiers
                    pasos.append(Step(
                        tipo=StepType.CLICK_CONTROL,
                        selector=sel,
                        descripcion=f"{mods_label}{accion} en {desc}{btn_suffix}",
                        delay_before_s=delay,
                        extra=extra,
                    ))
                else:
                    extra = {"x": evt.x, "y": evt.y}
                    if evt.button != "left":
                        extra["button"] = evt.button
                    if evt.double:
                        extra["double"] = True
                    if evt.modifiers:
                        extra["modifiers"] = evt.modifiers
                    pasos.append(Step(
                        tipo=StepType.CLICK_AT_XY,
                        extra=extra,
                        descripcion=f"{mods_label}{accion} en ({evt.x},{evt.y}){btn_suffix} — sin selector",
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
            elif evt.tipo == "scroll":
                extra: dict = {"x": evt.x, "y": evt.y, "dx": evt.dx, "dy": evt.dy}
                if evt.modifiers:
                    extra["modifiers"] = evt.modifiers
                pasos.append(Step(
                    tipo=StepType.SCROLL,
                    extra=extra,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
            elif evt.tipo == "drag":
                extra: dict = {
                    "x1": evt.x, "y1": evt.y,
                    "x2": evt.x2, "y2": evt.y2,
                }
                if evt.button != "left":
                    extra["button"] = evt.button
                if evt.modifiers:
                    extra["modifiers"] = evt.modifiers
                pasos.append(Step(
                    tipo=StepType.DRAG,
                    extra=extra,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
        return Macro(nombre="grabacion", pasos=pasos)
