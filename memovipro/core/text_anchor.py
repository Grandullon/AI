"""Ancla de texto: "clica donde pone X", automático y al grabar.

Es lo que hace UiPath cuando le señalas un sitio de la pantalla: además de
las coordenadas, se queda con el TEXTO que hay ahí (y a qué distancia del
texto caía tu clic). Al reproducir, busca ese texto y clica relativo a él,
así que el paso sobrevive a que la ventana se mueva, cambie de tamaño o se
recoloque el formulario.

El texto se lee del árbol de accesibilidad (UIA), no con OCR: es
instantáneo y exacto. En la reproducción esa MISMA cadena sirve para dos
búsquedas distintas — primero por el árbol y, si la aplicación no expone
nada, por OCR sobre la pantalla.

Aquí vive solo la lógica pura (decidir si un texto sirve, calcular el
desplazamiento y rehacer el punto). Leer controles y clicar es cosa del
recorder y del player.
"""
from __future__ import annotations

# Un texto demasiado largo no es una etiqueta, es un párrafo: ni identifica
# un sitio concreto ni lo encuentra bien el OCR.
MAX_LEN = 60
# Un control grande (un panel, un diálogo entero) tiene su centro lejos del
# clic, y al reproducir el punto se recalcula desde un marco de referencia
# distinto. Solo anclamos en cosas del tamaño de un botón o un rótulo.
MAX_W = 600
MAX_H = 200
# Distancia máxima entre el centro del rótulo y el clic. Admite el caso
# "el campo que hay a la derecha de «Primer apellido»": es seguro porque
# el rectángulo guardado es el del PROPIO rótulo, y al reproducir se
# busca un control con ese mismo rótulo — los dos lados miden desde el
# mismo sitio. Medir desde el contenedor fue lo que desviaba los clics.
MAX_OFFSET = 400


def normalizar(texto: str) -> str:
    return " ".join((texto or "").split())


def texto_util_para_ancla(texto: str) -> bool:
    """¿Sirve este texto para identificar un sitio de la pantalla?

    Descarta vacíos, párrafos y cadenas sin letras ("...", "3", "—"), que
    ni identifican nada ni sobreviven al OCR.
    """
    t = normalizar(texto)
    if not t or len(t) > MAX_LEN:
        return False
    return sum(1 for c in t if c.isalpha()) >= 2


def construir_ancla(texto: str, rect, x: int, y: int) -> dict | None:
    """Ancla para un clic en (x, y) sobre un control con ese texto.

    `rect` es (izq, arriba, der, abajo) del control. Devuelve
    {"texto", "dx", "dy"} donde (dx, dy) es el desplazamiento desde el
    CENTRO del texto hasta el punto clicado — 0,0 si clicaste encima.
    Devuelve None si el ancla no sería fiable.
    """
    t = normalizar(texto)
    if not texto_util_para_ancla(t):
        return None
    try:
        izq, arriba, der, abajo = (int(v) for v in rect)
    except Exception:
        return None
    ancho, alto = der - izq, abajo - arriba
    if ancho <= 0 or alto <= 0 or ancho > MAX_W or alto > MAX_H:
        return None
    dx = int(x) - (izq + der) // 2
    dy = int(y) - (arriba + abajo) // 2
    if abs(dx) > MAX_OFFSET or abs(dy) > MAX_OFFSET:
        return None
    return {"texto": t, "dx": dx, "dy": dy}


def punto_desde_ancla(rect, ancla: dict) -> tuple[int, int] | None:
    """Punto a clicar ahora, dado dónde está AHORA el texto del ancla."""
    if not ancla:
        return None
    try:
        izq, arriba, der, abajo = (int(v) for v in rect)
        dx = int(ancla.get("dx", 0))
        dy = int(ancla.get("dy", 0))
    except Exception:
        return None
    return ((izq + der) // 2 + dx, (arriba + abajo) // 2 + dy)


def punto_desde_centro(cx: int, cy: int, ancla: dict) -> tuple[int, int] | None:
    """Igual que `punto_desde_ancla` pero partiendo del centro ya calculado
    (lo que devuelve el OCR)."""
    if not ancla:
        return None
    try:
        return (int(cx) + int(ancla.get("dx", 0)),
                int(cy) + int(ancla.get("dy", 0)))
    except Exception:
        return None


# Al reproducir por OCR, el punto se calcula desde el centro de la PALABRA
# pintada, mientras que al grabar se calculó desde el centro del CONTROL.
# Son dos marcos de referencia distintos: coinciden cuando clicaste encima
# del texto, y divergen mucho cuando el control es bastante mayor que su
# rótulo (un grupo con el título arriba a la izquierda). Por eso el camino
# OCR solo se usa para anclas "clicaste encima".
MAX_OFFSET_OCR = 60


def rect_utilizable(rect) -> bool:
    """¿Es un rectángulo con el que se puede calcular un punto?

    Al reproducir hay que exigir lo mismo que al grabar. Sin esta
    comprobación, un control de una pestaña no activa (que pywinauto
    devuelve como 0,0,0,0) daba un clic en la esquina de la pantalla, y un
    panel gigante daba un clic a cientos de píxeles del sitio.
    """
    try:
        izq, arriba, der, abajo = (int(v) for v in rect)
    except Exception:
        return False
    ancho, alto = der - izq, abajo - arriba
    return 0 < ancho <= MAX_W and 0 < alto <= MAX_H


def ancla_admite_ocr(ancla: dict) -> bool:
    """¿Se puede buscar este ancla por OCR sin desviar el clic?

    Solo si el clic cayó prácticamente encima del texto (ver
    MAX_OFFSET_OCR). Con desplazamientos grandes, el OCR situaría el punto
    a partir de un marco de referencia distinto al de la grabación.
    """
    if not isinstance(ancla, dict):
        return False
    try:
        return (abs(int(ancla.get("dx", 0))) <= MAX_OFFSET_OCR
                and abs(int(ancla.get("dy", 0))) <= MAX_OFFSET_OCR)
    except Exception:
        return False


def punto_dentro(punto, rect) -> bool:
    """¿Cae el punto dentro del rectángulo? (para no clicar fuera de la
    ventana objetivo)."""
    if punto is None:
        return False
    try:
        x, y = int(punto[0]), int(punto[1])
        izq, arriba, der, abajo = (int(v) for v in rect)
    except Exception:
        return False
    return izq <= x <= der and arriba <= y <= abajo


def puntuar_candidato(texto_control: str, buscado: str, rect) -> tuple | None:
    """Ordena los controles que casan. Devuelve None si NO casa.

    Exige coincidencia EXACTA del texto (sin distinguir mayúsculas ni
    acentos). La comparación laxa "contiene" era peligrosa: el ancla
    "Alta" casaba con "Dar de alta al paciente" de la barra superior, y
    como se cogía el primero del árbol, el clic acababa allí. El orden del
    árbol no tiene nada que ver con el parecido.

    Entre varios aciertos exactos gana el más pequeño (el rótulo concreto
    antes que el contenedor que lo repite).
    """
    from .ocr import _norm_para_match
    if not rect_utilizable(rect):
        return None
    t = _norm_para_match(normalizar(texto_control))
    b = _norm_para_match(normalizar(buscado))
    if not b or t != b:
        return None
    try:
        izq, arriba, der, abajo = (int(v) for v in rect)
        area = (der - izq) * (abajo - arriba)
    except Exception:
        return None
    return (area,)
