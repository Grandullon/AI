"""Ajuste de puntos de análisis (breakpoints) al editar una macro.

Los breakpoints son índices 0-based de pasos. Cuando se inserta, borra o
mueve un paso en el editor, los índices posteriores se desplazan y hay que
recolocar los breakpoints para que sigan apuntando a SU paso.

Funciones puras (sin Qt) para poder testearlas y ser fuente única de
verdad entre el editor y el panel de step-through.
"""
from __future__ import annotations


def breakpoints_alcanzables(breakpoints, start_idx: int, pasos) -> set[int]:
    """Breakpoints que la ejecución puede llegar a disparar de verdad.

    Descarta los que quedan ANTES del punto de arranque y los que están
    sobre pasos desactivados (que nunca se ejecutan). Sin este filtro, una
    sesión podía entrar en modo "continuo" con puntos inalcanzables y
    reproducir la macro entera sin pararse nunca.
    """
    out = set()
    for b in breakpoints or ():
        if b < start_idx or b < 0 or b >= len(pasos):
            continue
        if not getattr(pasos[b], "activo", True):
            continue
        out.add(int(b))
    return out


def decidir_run_mode(breakpoints, start_idx: int, pasos) -> str:
    """'continue' si hay algún punto de análisis alcanzable; si no 'step'.

    En 'continue' la macro se auto-reproduce hasta el siguiente punto; en
    'step' se para en cada paso. Decidirlo con los puntos ALCANZABLES
    evita el caso "no para nunca" descrito arriba.
    """
    return "continue" if breakpoints_alcanzables(breakpoints, start_idx, pasos) else "step"


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
