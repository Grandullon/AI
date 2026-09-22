"""Cada paso trabaja sobre SU ventana.

Una macro real no vive en una sola ventana. Mirando macros de verdad:
un listado de GERHONTE pasa por el menú de turnos, la pantalla de
informes, el filtro de personal, la vista previa, el diálogo de guardar y
LibreOffice — seis o siete ventanas distintas en cuarenta pasos.

Por eso el campo «ventana principal» de la macro no basta: describe una
sola, y además casi nadie lo rellena. Lo que sí tiene cada paso es la
ventana concreta en la que se grabó, anotada al capturarlo.

Con eso se resuelve el problema de "la ventana se ha abierto detrás":
antes de actuar se comprueba qué hay delante y, si no es la ventana de
ese paso, se la trae al frente. Los diálogos (guardar, abrir, imprimir)
son justo los que Windows abre detrás cuando la aplicación no tiene
permiso para robar el foco.
"""
from __future__ import annotations

# Ventanas que NUNCA hay que traer al frente aunque un paso diga que se
# grabó sobre ellas. «Program Manager» es el escritorio: activarlo
# minimiza todo lo demás y deja la macro a ciegas. Aparece en macros
# reales cuando un clic cae fuera de cualquier ventana.
NO_ACTIVABLES = {
    "program manager",
    "barra de tareas",
    "taskbar",
    "shell_traywnd",
    "",
}


def normalizar_titulo(titulo: str) -> str:
    return " ".join((titulo or "").split()).strip().lower()


def es_activable(titulo: str) -> bool:
    """¿Tiene sentido traer al frente una ventana con este título?"""
    return normalizar_titulo(titulo) not in NO_ACTIVABLES


def titulo_equivalente(esperado: str, actual: str) -> bool:
    """¿Es la misma ventana, aunque el título haya cambiado un poco?

    Los títulos llevan datos dentro: «plantilla-mensual-actual.xls •
    LibreOffice Calc» cambia con el fichero, y una ficha puede llevar el
    nombre del paciente. Por eso basta con que uno contenga al otro, sin
    distinguir mayúsculas.
    """
    e, a = normalizar_titulo(esperado), normalizar_titulo(actual)
    if not e or not a:
        return False
    return e == a or e in a or a in e


def ventana_esperada(paso) -> dict:
    """Identidad de la ventana en la que se grabó el paso.

    Devuelve {"titulo", "proceso", "clase"}; los que falten van vacíos
    (las macros grabadas antes no llevan todos).
    """
    wr = ((getattr(paso, "extra", None) or {}).get("win_rel")) or {}
    return {
        "titulo": str(wr.get("title") or ""),
        "proceso": str(wr.get("proceso") or ""),
        "clase": str(wr.get("clase") or ""),
    }


def hay_que_activar(esperada: dict, titulo_frontal: str, proceso_frontal: str) -> bool:
    """¿Hace falta traer la ventana del paso al frente?

    No se toca nada si ya está delante, para no provocar parpadeos ni
    robarle el foco a la aplicación en cada paso.
    """
    titulo = esperada.get("titulo") or ""
    if not es_activable(titulo):
        return False
    if titulo_equivalente(titulo, titulo_frontal):
        return False        # ya estamos en ella
    return True
