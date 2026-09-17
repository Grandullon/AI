"""Textos que se enseñan al usuario y que merecen probarse.

Viven fuera de la capa gráfica a propósito: así se pueden comprobar sin
levantar la interfaz, que es donde más fácil se cuelan descuidos como
decir "del 3 al 40" cuando en realidad se van a borrar tres pasos
sueltos.
"""
from __future__ import annotations


def confirmar_borrado(filas: list[int]) -> str:
    """Mensaje de confirmación que dice EXACTAMENTE qué se borra.

    `filas` son índices 0-based; el mensaje habla en números de paso
    (1-based), que es lo que se ve en la tabla.
    """
    nums = sorted(f + 1 for f in filas)
    if not nums:
        return "No hay pasos seleccionados."
    if len(nums) == 1:
        return f"¿Eliminar el paso {nums[0]}?"
    contiguos = nums == list(range(nums[0], nums[-1] + 1))
    if contiguos:
        detalle = f"del {nums[0]} al {nums[-1]}"
    elif len(nums) <= 12:
        detalle = "los números " + ", ".join(str(n) for n in nums)
    else:
        detalle = ("los números " + ", ".join(str(n) for n in nums[:10])
                   + f"… y {len(nums) - 10} más")
    return f"¿Eliminar {len(nums)} pasos?\n\n({detalle})"
