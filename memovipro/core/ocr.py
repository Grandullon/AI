"""OCR de imágenes con Tesseract (pytesseract).

Se usa para:
  1. Leer el texto de los popups de error cuando la app no expone
     ese texto vía UIA (es una imagen o un control custom).
  2. Localizar dónde está una palabra en pantalla para el paso
     CLICK_OCR_TEXT (clic sobre texto detectado por OCR).

Dependencias opcionales:
  - pytesseract (paquete Python)
  - El BINARIO de Tesseract instalado en el sistema (o bundleado).

Si falta cualquiera, las funciones devuelven "" / None silenciosamente.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
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


def _norm_para_match(s: str) -> str:
    """Normaliza una cadena para matching laxo: lower-case + sin acentos.

    Tesseract a veces lee "Aceptar" como "aceptar", a veces como "Aceptar"
    según la fuente; los acentos del usuario pueden no coincidir con los
    detectados por el motor (depende del idioma seleccionado). Esta
    normalización los iguala.
    """
    nfkd = unicodedata.normalize("NFKD", s or "")
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


@dataclass
class OcrHit:
    """Un texto encontrado por OCR con su posición y confianza."""
    texto: str               # texto detectado tal cual lo devolvió Tesseract
    x: int                   # centro horizontal del bbox (relativo a la imagen)
    y: int                   # centro vertical del bbox
    width: int
    height: int
    confidence: int          # 0-100 (Tesseract usa -1 cuando no aplica → lo mapeamos a 0)


def localizar_texto_en_imagen(
    origen,
    texto_buscado: str,
    idioma: str = IDIOMA_DEFECTO,
    min_confidence: int = 60,
) -> OcrHit | None:
    """Busca `texto_buscado` en una imagen y devuelve la primera coincidencia.

    Tolerancias del matching:
      - Case-insensitive
      - Sin acentos
      - Multi-palabra: si pides "Aceptar y cerrar" busca esa secuencia
        contigua de tokens en orden (concatena los bboxes).

    Filtra tokens con `confidence < min_confidence` (basura del OCR).

    Devuelve `None` si:
      - pytesseract no disponible
      - la imagen no se puede abrir
      - el texto no aparece con confianza suficiente
    """
    if not _HAS_PYTESSERACT or not texto_buscado:
        return None

    def _abrir(o):
        if isinstance(o, (str, Path)):
            return Image.open(str(o))
        return o

    try:
        img = _abrir(origen)
    except Exception:
        return None

    Output = getattr(pytesseract, "Output", None)
    output_type = Output.DICT if Output is not None else "dict"
    try:
        data = pytesseract.image_to_data(img, lang=idioma, output_type=output_type)
    except Exception:
        # Reintento con idioma por defecto del binario.
        try:
            data = pytesseract.image_to_data(img, output_type=output_type)
        except Exception:
            return None

    tokens_buscados = _norm_para_match(texto_buscado).split()
    if not tokens_buscados:
        return None
    n_buscados = len(tokens_buscados)

    textos = data.get("text", [])
    confs = data.get("conf", [])
    lefts = data.get("left", [])
    tops = data.get("top", [])
    widths = data.get("width", [])
    heights = data.get("height", [])
    # Coordenadas semánticas (bloque/párrafo/línea/palabra). Tesseract las
    # rellena con `image_to_data` y son la única forma fiable de saber si
    # dos tokens *consecutivos en la búsqueda* están realmente uno al
    # lado del otro en pantalla. Si no están disponibles (versión vieja
    # de Tesseract), caemos a heurística geométrica.
    blocks = data.get("block_num", [])
    pars = data.get("par_num", [])
    lines = data.get("line_num", [])
    words = data.get("word_num", [])

    # Filtramos vacíos y baja confianza, conservando el índice original.
    valid = []
    for i, t in enumerate(textos):
        if not t or not t.strip():
            continue
        try:
            c = int(confs[i])
        except (ValueError, TypeError):
            c = 0
        if c < min_confidence:
            continue
        valid.append((i, t, c))

    def _en_misma_linea_consecutivos(idxs: list[int]) -> bool:
        """¿Todos los tokens pertenecen a (block, par, line) iguales y con
        word_num consecutivos? Si Tesseract no devolvió esas columnas,
        usamos un fallback geométrico (mismo `top` aproximado y poca
        distancia horizontal entre ellos)."""
        if blocks and pars and lines and words:
            try:
                b0, p0, l0 = blocks[idxs[0]], pars[idxs[0]], lines[idxs[0]]
                for k in range(1, len(idxs)):
                    i = idxs[k]
                    if blocks[i] != b0 or pars[i] != p0 or lines[i] != l0:
                        return False
                    if words[i] - words[idxs[k - 1]] != 1:
                        return False
                return True
            except (IndexError, TypeError):
                pass  # cae al fallback geométrico
        # Fallback: misma altura ±50% y separación horizontal razonable.
        for k in range(1, len(idxs)):
            i_ant, i_act = idxs[k - 1], idxs[k]
            try:
                h_ref = max(heights[i_ant], heights[i_act], 1)
                if abs(tops[i_act] - tops[i_ant]) > h_ref * 0.5:
                    return False
                espacio = lefts[i_act] - (lefts[i_ant] + widths[i_ant])
                if espacio < 0 or espacio > widths[i_ant] * 2:
                    return False
            except (IndexError, TypeError):
                return False
        return True

    for k in range(len(valid) - n_buscados + 1):
        ventana = valid[k:k + n_buscados]
        if not all(_norm_para_match(t) == tokens_buscados[j] for j, (_, t, _) in enumerate(ventana)):
            continue
        idxs = [i for i, _, _ in ventana]
        # En multi-palabra, exigimos que los tokens estén en la misma
        # línea visual y sean consecutivos (no "Guardar" en el menú y
        # "como" en la barra de estado).
        if n_buscados > 1 and not _en_misma_linea_consecutivos(idxs):
            continue
        # Combinar bboxes (mínimo de left/top, máximo de right/bottom).
        left = min(lefts[i] for i in idxs)
        top = min(tops[i] for i in idxs)
        right = max(lefts[i] + widths[i] for i in idxs)
        bottom = max(tops[i] + heights[i] for i in idxs)
        w = right - left
        h = bottom - top
        avg_conf = sum(c for _, _, c in ventana) // n_buscados
        texto_real = " ".join(t for _, t, _ in ventana)
        return OcrHit(
            texto=texto_real,
            x=left + w // 2,
            y=top + h // 2,
            width=w,
            height=h,
            confidence=avg_conf,
        )
    return None
