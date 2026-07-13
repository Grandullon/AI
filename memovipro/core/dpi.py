"""Declaración explícita de DPI awareness (Windows).

pynput captura coordenadas en PÍXELES FÍSICOS. Para que pywinauto
(`rectangle()`, clics) y Qt vean el mismo espacio de coordenadas, el
proceso debe declararse "per-monitor DPI aware". Hoy funciona de rebote
porque pywinauto lo declara al importarse y Qt6 es per-monitor aware por
defecto, pero conviene hacerlo EXPLÍCITO y PRONTO (antes de crear
ventanas): si el import de pywinauto fallara o cambiara, seguiríamos
grabando y reproduciendo en el mismo espacio de coordenadas.

En pantallas con escalado 125/150%, un proceso NO aware recibe
coordenadas "virtualizadas" (Windows miente sobre el tamaño real), y las
coordenadas grabadas divergirían de las de reproducción.

No-op fuera de Windows.
"""
from __future__ import annotations

try:
    from loguru import logger
except Exception:  # pragma: no cover
    class _NullLogger:
        def debug(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
    logger = _NullLogger()


def set_dpi_awareness() -> bool:
    """Declara el proceso Per-Monitor-V2 DPI aware. Devuelve True si se
    aplicó (o ya estaba), False si no se pudo / no es Windows."""
    try:
        import ctypes
    except Exception:
        return False
    # 1º intento: SetProcessDpiAwarenessContext (Win10 1703+), el más
    # completo (Per-Monitor-V2). El valor -4 es
    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
    try:
        user32 = ctypes.windll.user32
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception as exc:
        logger.debug("SetProcessDpiAwarenessContext no disponible: {}", exc)
    # 2º intento: SetProcessDpiAwareness(2) = PROCESS_PER_MONITOR_DPI_AWARE
    # (Win8.1+). Puede lanzar si ya se fijó antes (E_ACCESSDENIED) → OK.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except OSError:
        return True  # ya estaba fijado por otro (p.ej. pywinauto/Qt)
    except Exception as exc:
        logger.debug("SetProcessDpiAwareness no disponible: {}", exc)
    # 3º intento (legacy): SetProcessDPIAware (Vista+), system-DPI aware.
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False
