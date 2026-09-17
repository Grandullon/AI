"""Identificar a qué programa pertenece una ventana.

Sirve para la comprobación "¿estoy donde creo?": antes de clicar, el
reproductor confirma que la ventana que tiene delante es del MISMO
programa en el que se grabó el paso.

Se compara el PROGRAMA y no el título porque los títulos cambian solos:
"GERHONTE - García Pérez, Juan" lleva dentro el nombre del paciente, así
que comparar títulos no casaría nunca. El ejecutable, en cambio, es
estable.
"""
from __future__ import annotations

from pathlib import Path

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_PATH = 32768


def _user32_kernel32():
    import ctypes
    return ctypes.windll.user32, ctypes.windll.kernel32


def nombre_proceso_de_hwnd(hwnd) -> str:
    """Nombre del ejecutable dueño de la ventana ('gerhonte.exe').

    Devuelve "" si no se puede averiguar (fuera de Windows, permisos,
    ventana ya cerrada). El llamador debe tratar "" como "no lo sé" y no
    sacar conclusiones.
    """
    if not hwnd:
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = _user32_kernel32()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(int(hwnd)), ctypes.byref(pid))
        if not pid.value:
            return ""
        h = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value,
        )
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(_MAX_PATH)
            tam = wintypes.DWORD(_MAX_PATH)
            if not kernel32.QueryFullProcessImageNameW(
                h, 0, buf, ctypes.byref(tam)
            ):
                return ""
            return Path(buf.value).name.lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


def proceso_en_primer_plano() -> str:
    """Nombre del ejecutable de la ventana que tiene el foco ahora."""
    try:
        user32, _ = _user32_kernel32()
        return nombre_proceso_de_hwnd(user32.GetForegroundWindow())
    except Exception:
        return ""


def mismo_programa(esperado: str, actual: str) -> bool:
    """¿Son el mismo programa?

    Si alguno de los dos se desconoce ("") devolvemos True: no se puede
    afirmar que haya un problema, y bloquear un paso por una duda sería
    peor que dejarlo pasar. La comprobación solo sirve para detectar un
    programa DISTINTO, que es el caso peligroso.
    """
    if not esperado or not actual:
        return True
    return esperado.strip().lower() == actual.strip().lower()
