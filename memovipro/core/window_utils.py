"""Utilidades para enumerar y asegurar ventanas top-level del sistema.

Funciones libres usadas tanto por `core.player.Player` (para el
auto-anchor antes de cada paso) como por el diálogo "Plantilla arranque"
del editor (para listar al usuario las ventanas detectadas y para
ofrecer un botón "Probar patrón").

Antes la lógica vivía solo en `Player._asegurar_ventana_objetivo`;
ahora hay una función pura `asegurar_ventana()` que no depende del
Player (sin throttling ni dry_run), y el Player la envuelve añadiendo
esa lógica de caching.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def debug(self, *a, **kw): pass
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
    logger = _NullLogger()

try:
    from pywinauto import Desktop
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False
    Desktop = None  # placeholder para que los tests puedan monkeypatcharlo


@dataclass
class VentanaInfo:
    titulo: str
    class_name: str
    handle: int = 0
    is_foreground: bool = False


def _get_foreground_handle() -> int:
    """Devuelve el handle de la ventana en foreground, o 0 si no se puede."""
    try:
        import win32gui  # type: ignore[import-not-found]
        return int(win32gui.GetForegroundWindow())
    except Exception:
        return 0


def listar_ventanas_visibles(excluir_propio: bool = True) -> list[VentanaInfo]:
    """Lista ventanas top-level visibles con título no vacío.

    Si `excluir_propio` es True, filtra ventanas cuyo título empiece por
    "MemoviPro" para no traerse a uno mismo al frente.

    Devuelve la lista ordenada: foreground primero, luego alfabético.
    """
    out: list[VentanaInfo] = []
    if not _HAS_PYWINAUTO:
        return out
    fg_handle = _get_foreground_handle()
    try:
        for w in Desktop(backend="uia").windows():
            try:
                if not w.is_visible():
                    continue
                titulo = (w.window_text() or "").strip()
                if not titulo:
                    continue
                if excluir_propio and titulo.lower().startswith("memovipro"):
                    continue
                try:
                    handle = int(w.handle)
                except Exception:
                    handle = 0
                try:
                    class_name = w.class_name() or ""
                except Exception:
                    class_name = ""
                out.append(VentanaInfo(
                    titulo=titulo,
                    class_name=class_name,
                    handle=handle,
                    is_foreground=(handle != 0 and handle == fg_handle),
                ))
            except Exception:
                continue
    except Exception as exc:
        logger.debug("listar_ventanas_visibles falló: {}", exc)
    out.sort(key=lambda v: (not v.is_foreground, v.titulo.lower()))
    return out


def existe_ventana(title_re: str, timeout_s: float = 0.5) -> bool:
    """¿Existe alguna ventana cuyo título matchee el patrón (regex parcial)?"""
    if not _HAS_PYWINAUTO or not title_re:
        return False
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_re}.*")
        return bool(win.exists(timeout=timeout_s))
    except Exception:
        return False


def asegurar_ventana(
    title_re: str,
    state: str = "maximized",
    timeout_s: float = 5.0,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Trae la ventana al frente y la pone en el estado pedido.

    Devuelve (éxito, mensaje). El mensaje es legible para mostrarlo en
    diálogos del usuario:
      - Si OK: "✓ Encontrada: '<título real>'"
      - Si falla: explicación del por qué.

    `title_re` se usa como regex parcial: `.*<title_re>.*`. Acepta
    alternativas regex con `|`, por ejemplo "GERHONTE|FABPMEN1".

    `state`: 'maximized' | 'normal' | 'minimized'
    """
    if not title_re:
        return False, "Sin patrón de título"
    if dry_run:
        return True, f"[dry-run] window_ensure '{title_re}' state={state}"
    if not _HAS_PYWINAUTO:
        return False, "pywinauto no disponible (solo Windows)"
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_re}.*")
    except Exception as exc:
        return False, f"Error creando WindowSpecification: {exc}"
    try:
        if not win.exists(timeout=min(timeout_s, 2.0)):
            return False, f"No se encontró ninguna ventana con patrón '{title_re}'"
    except Exception as exc:
        return False, f"Error buscando ventana: {exc}"
    try:
        titulo_real = (win.window_text() or "").strip() or "<sin título>"
    except Exception:
        titulo_real = "<sin título>"
    try:
        if win.is_minimized() and state != "minimized":
            win.restore()
    except Exception as exc:
        logger.debug("No se pudo restaurar la ventana '{}': {}", title_re, exc)
    if state == "maximized":
        try:
            if not win.is_maximized():
                win.maximize()
        except Exception as exc:
            logger.debug("No se pudo maximizar la ventana '{}': {}", title_re, exc)
    elif state == "minimized":
        try:
            win.minimize()
        except Exception as exc:
            logger.debug("No se pudo minimizar la ventana '{}': {}", title_re, exc)
    elif state == "normal":
        try:
            if win.is_maximized() or win.is_minimized():
                win.restore()
        except Exception as exc:
            logger.debug("No se pudo poner en estado normal la ventana '{}': {}", title_re, exc)
    try:
        win.set_focus()
    except Exception as exc:
        logger.debug("No se pudo poner foco en la ventana '{}': {}", title_re, exc)
    return True, f"Encontrada y traída al frente: '{titulo_real}'"
