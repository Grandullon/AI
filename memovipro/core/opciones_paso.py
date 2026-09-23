"""Opciones de ejecución de un paso, sin dependencias de interfaz."""
from __future__ import annotations

METODO_RATON = "raton"
METODO_SIMULADO = "simular"


def aplicar_opciones(paso, metodo: str, reintentos: int, espera_s: float) -> None:
    """Escribe las opciones en el paso sin ensuciar el YAML: lo que queda
    en su valor por defecto no se guarda, así las macros que no usan
    estas opciones no cambian ni de huella."""
    extra = dict(paso.extra or {})
    if metodo == METODO_SIMULADO:
        extra["metodo"] = METODO_SIMULADO
    else:
        extra.pop("metodo", None)
    if espera_s and espera_s > 0:
        extra["reintento_espera_s"] = round(float(espera_s), 1)
    else:
        extra.pop("reintento_espera_s", None)
    paso.extra = extra
    paso.reintentos = max(0, int(reintentos))


def marcas_del_paso(paso) -> str:
    """Texto corto para la tabla: se ve de un vistazo qué pasos van
    simulados o con reintentos distintos de los normales."""
    extra = paso.extra or {}
    partes = []
    if str(extra.get("metodo") or "").lower() == METODO_SIMULADO:
        partes.append("⚡simulado")
    espera = extra.get("reintento_espera_s")
    if paso.reintentos != 2 or espera:
        txt = f"↻{paso.reintentos}"
        if espera:
            txt += f"/{float(espera):g}s"
        partes.append(txt)
    return "  ".join(partes)
