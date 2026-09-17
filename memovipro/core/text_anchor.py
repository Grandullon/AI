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
# Un control enorme (un panel, la ventana entera) tiene su centro lejísimos
# del clic: el desplazamiento resultante no significa nada.
MAX_W = 700
MAX_H = 500
# Distancia máxima entre el texto y el clic. Más allá, la relación entre
# ambos es casualidad, no estructura.
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
