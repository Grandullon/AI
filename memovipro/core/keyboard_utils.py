"""Utilidades de teclado para la reproducción con pywinauto.

pywinauto.keyboard.send_keys interpreta varios caracteres como
control: { } ( ) + ^ % ~. Si el usuario teclea literalmente uno de
ellos (típico en contraseñas: "P+ss%word", o textos con paréntesis),
hay que escaparlo envolviéndolo en llaves, o se teclea mal.

Esto NO aplica a los pasos `send_keys` (que usan la sintaxis especial
a propósito: {ENTER}, ^a, {VK_LWIN down}...), solo a `type_text`
(texto literal que el usuario escribió).
"""
from __future__ import annotations

# Caracteres que pywinauto.keyboard interpreta como control.
_ESPECIALES = set("{}()+^%~")


def escape_send_keys(text: str) -> str:
    """Escapa los caracteres especiales de send_keys para teclear texto literal.

    Ejemplos:
        "12345678A"   -> "12345678A"      (sin cambios)
        "P+ss%word"   -> "P{+}ss{%}word"
        "Apellido (2)" -> "Apellido {(}2{)}"
        "a{b}c"       -> "a{{}b{}}c"
    """
    if not text:
        return text
    out = []
    for ch in text:
        if ch in _ESPECIALES:
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)
