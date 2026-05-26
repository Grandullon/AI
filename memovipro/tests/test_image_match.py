"""Tests del matching por imagen (core.image_match).

Usan imágenes sintéticas: creamos una "pantalla" con numpy, recortamos
un trozo como template, y verificamos que buscar_en_imagen lo encuentra
en la posición correcta.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from core import image_match

# Si cv2/numpy no están, saltamos toda la suite.
pytestmark = pytest.mark.skipif(
    not image_match._HAS_CV2, reason="cv2/numpy no disponibles"
)

import numpy as np
import cv2


def _png_b64_de_array(arr_bgr) -> str:
    ok, buf = cv2.imencode(".png", arr_bgr)
    assert ok
    return image_match.png_a_b64(buf.tobytes())


def test_b64_roundtrip():
    datos = b"\x89PNG\r\n fake"
    b64 = image_match.png_a_b64(datos)
    assert image_match.b64_a_png(b64) == datos


def test_png_a_b64_vacio():
    assert image_match.png_a_b64(None) == ""
    assert image_match.png_a_b64(b"") == ""


def test_buscar_en_imagen_encuentra_template():
    # Pantalla 200x300 (alto x ancho) gris con un cuadrado blanco distintivo
    screen = np.zeros((200, 300, 3), dtype=np.uint8)
    # Dibujar un patrón reconocible en (x=150, y=80), 40x20
    cv2.rectangle(screen, (150, 80), (190, 100), (255, 255, 255), -1)
    cv2.putText(screen, "OK", (152, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)

    # Template = recorte exacto de esa zona
    templ = screen[80:100, 150:190].copy()
    b64 = _png_b64_de_array(templ)

    punto = image_match.buscar_en_imagen(b64, screen, umbral=0.8)
    assert punto is not None
    cx, cy = punto
    # El centro del template está en (150+20, 80+10) = (170, 90)
    assert abs(cx - 170) <= 2
    assert abs(cy - 90) <= 2


def test_buscar_en_imagen_no_encuentra_si_no_esta():
    screen = np.zeros((200, 300, 3), dtype=np.uint8)
    cv2.rectangle(screen, (10, 10), (50, 30), (255, 255, 255), -1)

    # Template totalmente distinto (patrón de ruido)
    templ = np.full((20, 40, 3), 128, dtype=np.uint8)
    cv2.putText(templ, "ZZ", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    b64 = _png_b64_de_array(templ)

    punto = image_match.buscar_en_imagen(b64, screen, umbral=0.95)
    assert punto is None


def test_buscar_en_imagen_b64_vacio():
    screen = np.zeros((50, 50, 3), dtype=np.uint8)
    assert image_match.buscar_en_imagen("", screen) is None


def test_disponible():
    # En el entorno de test con cv2+mss instalados, debería ser True.
    # Solo comprobamos que devuelve un bool.
    assert isinstance(image_match.disponible(), bool)
