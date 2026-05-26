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


def _ocr_screenshot(path: str) -> str:
    """OCR del screenshot del popup (best-effort). "" si OCR no disponible."""
    try:
        from .ocr import disponible, ocr_imagen
        if not disponible():
            return ""
        return ocr_imagen(path)
    except Exception:
        return ""


@dataclass
class PopupEvent:
    titulo: str
    texto: str
    class_name: str
    screenshot_path: str
    handle: int | None = None
    texto_ocr: str = ""  # texto leído por OCR del screenshot (si UIA no dio nada)


_KEYWORDS_ERROR = (
    "error", "aviso", "atención", "atencion", "advertencia",
    "confirmar", "confirmación", "confirmacion",
    "warning", "alert", "información", "informacion",
    "fallo", "incidencia", "excepción", "excepcion",
)

_DIALOG_CLASSES = {"#32770", "Dialog", "TaskDialogWindowClass"}

# Lista blanca: diálogos del sistema operativo que la macro PUEDE necesitar
# usar (Abrir / Guardar como / Imprimir / Examinar / ...). Estos usan la
# misma clase #32770 que los popups de error nativos. Si los tratásemos
# como popups, los cerraríamos cada vez que la macro intenta abrir un
# fichero. Por eso necesitamos esta lista blanca explícita.
_TITULOS_DIALOGOS_LEGITIMOS = (
    # Archivos
    "abrir", "open",
    "guardar", "guardar como", "save", "save as",
    "guardar archivo", "exportar", "export", "importar", "import",
    # Impresión
    "imprimir", "print",
    "vista previa de impresión", "vista previa", "print preview",
    "configurar página", "configurar pagina", "page setup",
    # Búsqueda
    "buscar", "find", "find and replace",
    "buscar y reemplazar", "reemplazar", "replace",
    # Examinar
    "examinar", "browse",
    "buscar carpeta", "browse for folder",
    "seleccionar carpeta", "seleccionar archivo",
    "select folder", "select file",
    # Formato / propiedades
    "fuente", "font", "color",
    "propiedades", "properties",
    # Otros
    "configuración", "configuracion", "settings",
    "opciones", "options",
    "acerca de", "about",
)


def _titulo_es_dialogo_legitimo(title_lower: str) -> bool:
    """Comprueba si el título corresponde a un diálogo legítimo del SO.

    Acepta coincidencia exacta o que el título empiece por uno de los
    nombres conocidos seguido de ' ' o ':' (ej. "Guardar como: docs",
    "Abrir archivo PA-diario").
    """
    title_norm = title_lower.rstrip(":").strip()
    if title_norm in _TITULOS_DIALOGOS_LEGITIMOS:
        return True
    for t in _TITULOS_DIALOGOS_LEGITIMOS:
        if title_lower.startswith(t + " ") or title_lower.startswith(t + ":"):
            return True
    return False


def _es_popup_candidato(win, ignorar: list[str]) -> bool:
    """Decide si una ventana es probablemente un popup de error.

    Estrategia muy conservadora — preferimos NO marcar algo como popup
    que marcarlo erróneamente y cerrar el diálogo real que la macro
    necesita usar (por ejemplo el "Abrir" para seleccionar fichero).

    Es popup si cumple TODOS estos:
      a) Su título NO está en la lista blanca de diálogos legítimos
         (Abrir, Guardar como, Imprimir, Examinar...).
      b) Su título contiene una palabra de error
         ("Error", "Aviso", "Confirmar", "Atención"...).
      c) Adicionalmente:
         - O su clase es de diálogo nativo Windows (#32770, ...).
         - O es una ventana pequeña (<800×600).

    Las ventanas grandes (≥800 o ≥600) sin clase de diálogo nativo nunca
    se consideran popups. Las ventanas con título "Abrir", "Guardar
    como" etc. nunca se consideran popups, da igual su clase.
    """
    try:
        if not win.is_visible():
            return False
        title = (win.window_text() or "").strip()
        if not title:
            return False
        if any(pat.lower() in title.lower() for pat in ignorar):
            return False
        title_lower = title.lower()

        # 1. Lista blanca: ignorar diálogos legítimos del SO.
        if _titulo_es_dialogo_legitimo(title_lower):
            return False

        # 2. Para considerarlo popup necesitamos keyword de error.
        if not any(kw in title_lower for kw in _KEYWORDS_ERROR):
            return False

        # 3. Clase de diálogo nativo Windows → es popup.
        class_name = (win.class_name() or "").strip()
        if class_name in _DIALOG_CLASSES:
            return True

        # 4. Custom (TFormError de Delphi, etc.) → popup solo si es pequeño.
        try:
            r = win.rectangle()
            w_size = r.width()
            h_size = r.height()
            if w_size > 0 and h_size > 0 and w_size < 800 and h_size < 600:
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
        # OJO: no usar self._stop como nombre. threading.Thread tiene un
        # método interno _stop() que es invocado por join(). Si lo pisamos
        # con un Event, join() lanza "TypeError: 'Event' object is not callable".
        self._stop_event = threading.Event()
        self._baseline: set[int] = set()

    def stop(self) -> None:
        self._stop_event.set()

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
        while not self._stop_event.is_set():
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
                    # OCR del screenshot si UIA no dio texto accesible
                    # (popup que es imagen / control custom).
                    texto_ocr = ""
                    if shot and not texto:
                        texto_ocr = _ocr_screenshot(str(shot))
                    evt = PopupEvent(
                        titulo=titulo,
                        texto=texto,
                        class_name=class_name,
                        screenshot_path=str(shot) if shot else "",
                        handle=h,
                        texto_ocr=texto_ocr,
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
