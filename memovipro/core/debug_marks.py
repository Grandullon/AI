"""Ajuste de puntos de análisis (breakpoints) al editar una macro.

Los breakpoints son índices 0-based de pasos. Cuando se inserta, borra o
mueve un paso en el editor, los índices posteriores se desplazan y hay que
recolocar los breakpoints para que sigan apuntando a SU paso.

Funciones puras (sin Qt) para poder testearlas y ser fuente única de
verdad entre el editor y el panel de step-through.
"""
from __future__ import annotations


def shift_on_insert(breakpoints: set[int], insert_at: int, n: int = 1) -> set[int]:
    """Tras insertar `n` pasos en la posición `insert_at`, los breakpoints
    en/tras ese punto se desplazan +n."""
    return {(b + n) if b >= insert_at else b for b in breakpoints}


def shift_on_remove(breakpoints: set[int], row: int) -> set[int]:
    """Tras borrar el paso `row`: se quita su breakpoint (si lo tenía) y los
    posteriores bajan 1."""
    return {(b - 1) if b > row else b for b in breakpoints if b != row}


def swap_on_move(breakpoints: set[int], row: int, new: int) -> set[int]:
    """Tras intercambiar los pasos `row` y `new`, el breakpoint viaja con
    su paso."""
    tiene_row = row in breakpoints
    tiene_new = new in breakpoints
    out = set(breakpoints)
    out.discard(row)
    out.discard(new)
    if tiene_row:
        out.add(new)
    if tiene_new:
        out.add(row)
    return out
