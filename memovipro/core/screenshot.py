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
    with mss.mss() as sct:
        mss.tools.to_png(sct.grab(sct.monitors[0])[:], sct.grab(sct.monitors[0]).size, output=str(out))
    return out


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
