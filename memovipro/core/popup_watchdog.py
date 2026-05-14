from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from pywinauto import Desktop
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False

from .screenshot import capturar_ventana_pywinauto


@dataclass
class PopupEvent:
    titulo: str
    texto: str
    class_name: str
    screenshot_path: str
    handle: int | None = None


def _es_popup_candidato(win, ignorar: list[str]) -> bool:
    try:
        if not win.is_visible():
            return False
        title = (win.window_text() or "").strip()
        if not title:
            return False
        if any(pat.lower() in title.lower() for pat in ignorar):
            return False
        class_name = win.class_name() or ""
        if class_name in {"#32770", "Dialog", "TaskDialogWindowClass"}:
            return True
        try:
            buttons = win.descendants(control_type="Button")
            names = {(b.window_text() or "").strip().lower() for b in buttons}
            ok_hits = {"aceptar", "ok", "cerrar", "cancelar", "sí", "si", "no", "yes"}
            if ok_hits & names:
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False


def _texto_completo(win) -> str:
    partes: list[str] = []
    try:
        for txt in win.descendants(control_type="Text"):
            try:
                t = (txt.window_text() or "").strip()
                if t:
                    partes.append(t)
            except Exception:
                continue
    except Exception:
        pass
    return " | ".join(partes)


def _cerrar_popup(win) -> bool:
    for nombre in ("Aceptar", "OK", "Cerrar", "Cancelar"):
        try:
            btn = win.child_window(title=nombre, control_type="Button")
            if btn.exists():
                btn.click_input()
                return True
        except Exception:
            continue
    try:
        win.close()
        return True
    except Exception:
        return False


class PopupWatchdog(threading.Thread):
    """Vigila la aparición de ventanas emergentes durante la reproducción.

    Mantiene una baseline de ventanas top-level conocidas. Cualquier ventana nueva
    que cumpla heurísticas de "popup" dispara el callback.
    """

    def __init__(
        self,
        screenshots_dir: str | Path,
        on_popup: Callable[[PopupEvent], None],
        polling_ms: int = 300,
        ignorar_titulos: list[str] | None = None,
        cerrar_automaticamente: bool = True,
    ):
        super().__init__(daemon=True)
        self.screenshots_dir = Path(screenshots_dir)
        self.on_popup = on_popup
        self.polling_ms = polling_ms
        self.ignorar = ignorar_titulos or []
        self.cerrar_automaticamente = cerrar_automaticamente
        self._stop = threading.Event()
        self._baseline: set[int] = set()

    def stop(self) -> None:
        self._stop.set()

    def reset_baseline(self) -> None:
        if not _HAS_PYWINAUTO:
            return
        try:
            self._baseline = {w.handle for w in Desktop(backend="uia").windows()}
        except Exception:
            self._baseline = set()

    def run(self) -> None:
        if not _HAS_PYWINAUTO:
            return
        self.reset_baseline()
        while not self._stop.is_set():
            try:
                actuales = Desktop(backend="uia").windows()
                for w in actuales:
                    try:
                        h = w.handle
                    except Exception:
                        continue
                    if h in self._baseline:
                        continue
                    if not _es_popup_candidato(w, self.ignorar):
                        self._baseline.add(h)
                        continue
                    titulo = (w.window_text() or "").strip()
                    texto = _texto_completo(w)
                    class_name = w.class_name() or ""
                    shot = capturar_ventana_pywinauto(self.screenshots_dir, w, prefijo="popup")
                    evt = PopupEvent(
                        titulo=titulo,
                        texto=texto,
                        class_name=class_name,
                        screenshot_path=str(shot) if shot else "",
                        handle=h,
                    )
                    try:
                        self.on_popup(evt)
                    finally:
                        if self.cerrar_automaticamente:
                            _cerrar_popup(w)
                        self._baseline.add(h)
            except Exception:
                pass
            time.sleep(self.polling_ms / 1000.0)
