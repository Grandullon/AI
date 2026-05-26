"""OCR de imágenes con Tesseract (pytesseract).

Se usa para leer el texto de los popups de error cuando la app no
expone ese texto de forma accesible (es una imagen o un control
custom). Complementa la lectura vía UIA del watchdog.

Dependencias opcionales:
  - pytesseract (paquete Python)
  - El BINARIO de Tesseract instalado en el sistema (o bundleado).

Si falta cualquiera, las funciones devuelven "" silenciosamente y la
captura de incidencias sigue funcionando con el texto accesible.
"""
from __future__ import annotations

from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    _HAS_PYTESSERACT = True
except Exception:
    _HAS_PYTESSERACT = False
    pytesseract = None  # placeholders para tests (monkeypatch)
    Image = None


# Idioma por defecto: español + inglés. Requiere los traineddata
# correspondientes instalados con Tesseract.
IDIOMA_DEFECTO = "spa+eng"


def disponible() -> bool:
    """¿Está OCR operativo (pytesseract + binario Tesseract)?"""
    if not _HAS_PYTESSERACT:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _normalizar(texto: str) -> str:
    """Colapsa espacios/saltos de línea múltiples en espacios simples."""
    return " ".join((texto or "").split())


def ocr_imagen(origen, idioma: str = IDIOMA_DEFECTO) -> str:
    """Extrae texto de una imagen (ruta str/Path o PIL.Image).

    Si el idioma pedido no está instalado (error de Tesseract), reintenta
    con el idioma por defecto del binario. Devuelve "" ante cualquier
    fallo para no romper la captura de incidencias.
    """
    if not _HAS_PYTESSERACT:
        return ""

    def _abrir(o):
        if isinstance(o, (str, Path)):
            return Image.open(str(o))
        return o

    try:
        img = _abrir(origen)
        return _normalizar(pytesseract.image_to_string(img, lang=idioma))
    except Exception:
        # Reintento sin especificar idioma (usa el por defecto del binario)
        try:
            img = _abrir(origen)
            return _normalizar(pytesseract.image_to_string(img))
        except Exception:
            return ""
