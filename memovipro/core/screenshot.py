from __future__ import annotations

from datetime import datetime
from pathlib import Path

try:
    import mss
    import mss.tools
    _HAS_MSS = True
except Exception:
    _HAS_MSS = False

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def capturar_pantalla_completa(dest_dir: str | Path, prefijo: str = "screen") -> Path | None:
    if not _HAS_MSS:
        return None
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = dest / f"{prefijo}_{ts}.png"
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # monitor 0 = todos los monitores combinados
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(out))
    except Exception:
        return None
    return out


def capturar_pantalla_completa_con_offset(
    dest_dir: str | Path, prefijo: str = "screen",
) -> tuple[Path, int, int] | None:
    """Captura todos los monitores y devuelve `(path, left, top)`.

    El `(left, top)` es el origen del virtual desktop (`mss.monitors[0]`),
    que en multi-monitor con un monitor secundario a la izquierda del
    principal puede ser negativo. Esencial para mapear coordenadas de la
    imagen capturada a coordenadas de pantalla absolutas.
    """
    if not _HAS_MSS:
        return None
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = dest / f"{prefijo}_{ts}.png"
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(out))
            return out, int(monitor["left"]), int(monitor["top"])
    except Exception:
        return None


def capturar_region(
    dest_dir: str | Path,
    rect: tuple[int, int, int, int],
    prefijo: str = "popup",
) -> Path | None:
    """Captura una región (left, top, width, height) y la guarda como PNG."""
    if not _HAS_MSS:
        return None
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out = dest / f"{prefijo}_{ts}.png"
    left, top, w, h = rect
    monitor = {"left": left, "top": top, "width": max(1, w), "height": max(1, h)}
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        mss.tools.to_png(shot.rgb, shot.size, output=str(out))
    return out


def capturar_ventana_pywinauto(dest_dir: str | Path, win, prefijo: str = "popup") -> Path | None:
    """Captura una ventana de pywinauto leyendo su rectángulo."""
    try:
        r = win.rectangle()
        return capturar_region(dest_dir, (r.left, r.top, r.width(), r.height()), prefijo)
    except Exception:
        return None
