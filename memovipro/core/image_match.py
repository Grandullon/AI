"""Localización de elementos por imagen (template matching con OpenCV).

Fallback de máxima robustez para la reproducción: si el selector UIA y
las coordenadas (relativas/absolutas) fallan, buscamos en pantalla un
thumbnail capturado al grabar y clicamos en su centro. Esto encuentra
el botón visualmente, esté donde esté la ventana.

Dependencias opcionales (opencv-python-headless, numpy, mss). Si no
están, las funciones devuelven None silenciosamente.

El matching se hace en escala de grises para ser inmune al orden de
canales (RGB vs BGR) entre la captura del template y la de pantalla.
"""
from __future__ import annotations

import base64

try:
    import numpy as np
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    import mss
    import mss.tools
    _HAS_MSS = True
except Exception:
    _HAS_MSS = False


# Tamaño por defecto del thumbnail alrededor del clic.
THUMB_W = 80
THUMB_H = 40
# Umbral de confianza por defecto para considerar un match válido.
UMBRAL_DEFECTO = 0.80


def disponible() -> bool:
    """¿Está el matching por imagen operativo (cv2 + mss)?"""
    return _HAS_CV2 and _HAS_MSS


def capturar_region_png(x: int, y: int, w: int = THUMB_W, h: int = THUMB_H) -> bytes | None:
    """Captura una región centrada en (x, y) y la devuelve como PNG (bytes)."""
    if not _HAS_MSS:
        return None
    try:
        left = int(x - w // 2)
        top = int(y - h // 2)
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": int(w), "height": int(h)})
            return mss.tools.to_png(shot.rgb, shot.size)
    except Exception:
        return None


def png_a_b64(png: bytes | None) -> str:
    return base64.b64encode(png).decode("ascii") if png else ""


def b64_a_png(b64: str) -> bytes:
    return base64.b64decode(b64)


def _b64_a_gray(b64: str):
    """Decodifica un PNG base64 a imagen OpenCV en escala de grises."""
    png = base64.b64decode(b64)
    arr = np.frombuffer(png, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return img


def buscar_en_pantalla(img_b64: str, umbral: float = UMBRAL_DEFECTO) -> tuple[int, int] | None:
    """Busca el thumbnail (PNG base64) en la pantalla completa.

    Devuelve (cx, cy) absolutos del CENTRO del mejor match si su
    confianza supera `umbral`, o None. Trabaja en escala de grises.
    """
    if not disponible() or not img_b64:
        return None
    try:
        templ = _b64_a_gray(img_b64)
        if templ is None:
            return None
        th, tw = templ.shape[:2]
        with mss.mss() as sct:
            mon = sct.monitors[0]  # todos los monitores combinados
            shot = sct.grab(mon)
            screen = np.array(shot)[:, :, :3]  # BGRA -> BGR
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        if screen_gray.shape[0] < th or screen_gray.shape[1] < tw:
            return None
        res = cv2.matchTemplate(screen_gray, templ, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
        if max_v < umbral:
            return None
        cx = mon["left"] + max_l[0] + tw // 2
        cy = mon["top"] + max_l[1] + th // 2
        return (int(cx), int(cy))
    except Exception:
        return None


def buscar_en_imagen(img_b64: str, screen_bgr, umbral: float = UMBRAL_DEFECTO) -> tuple[int, int] | None:
    """Como buscar_en_pantalla pero contra una imagen dada (para tests).

    `screen_bgr` es un ndarray BGR. Devuelve el centro del match relativo
    a esa imagen (no aplica offset de monitor).
    """
    if not _HAS_CV2 or not img_b64:
        return None
    try:
        templ = _b64_a_gray(img_b64)
        if templ is None:
            return None
        th, tw = templ.shape[:2]
        screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(screen_gray, templ, cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(res)
        if max_v < umbral:
            return None
        return (int(max_l[0] + tw // 2), int(max_l[1] + th // 2))
    except Exception:
        return None
