"""Esperar a que la aplicación esté lista antes de actuar.

Es lo que UiPath llama «WaitForReady». Sin esto, si GERHONTE tarda ocho
segundos en pintar un informe, la macro clica o teclea a los dos: el clic
cae en una pantalla a medio dibujar y lo tecleado se pierde, porque una
aplicación ocupada no atiende al teclado. Y como depende de lo cargado que
vaya el equipo, falla "en algún punto" sin patrón.

Se consideran tres señales de "está ocupada", las tres baratas de mirar:

  - La ventana NO RESPONDE (Windows la marca como colgada cuando lleva
    unos segundos sin atender mensajes).
  - La ventana está DESHABILITADA: las aplicaciones Delphi deshabilitan
    su formulario mientras trabajan o mientras hay un diálogo encima.
  - El puntero es el RELOJ DE ARENA o el de "arrancando".

Nunca hace fallar un paso: si se agota la espera, se sigue como se hacía
antes y queda anotado. Esperar solo puede retrasar, no cambiar a dónde
va el clic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

# Tiempo máximo de espera por paso. Un informe pesado de GERHONTE puede
# tardar; más de esto ya no es "ocupada", es otra cosa.
ESPERA_LISTO_S = 10.0
INTERVALO_S = 0.15

_IDC_WAIT = 32514
_IDC_APPSTARTING = 32650


@dataclass
class Resultado:
    listo: bool
    segundos: float = 0.0
    motivo: str = ""        # la última señal de ocupada que se vio


def sondear_ventana_frontal() -> str:
    """¿Está ocupada la ventana que hay delante? Devuelve el motivo, o ""
    si está lista. Fuera de Windows (o si la consulta falla), "" — no se
    puede saber y no se frena nada."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
    except Exception:
        return ""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        if user32.IsHungAppWindow(hwnd):
            return "no responde"
        if not user32.IsWindowEnabled(hwnd):
            return "deshabilitada mientras trabaja"

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]

        ci = CURSORINFO()
        ci.cbSize = ctypes.sizeof(CURSORINFO)
        if user32.GetCursorInfo(ctypes.byref(ci)) and ci.hCursor:
            # Solo los 32 bits bajos de un identificador de cursor son
            # significativos; compararlos enteros puede fallar en 64 bits
            # según cómo venga extendido el signo.
            actual = int(ci.hCursor) & 0xFFFFFFFF
            for idc in (_IDC_WAIT, _IDC_APPSTARTING):
                h = user32.LoadCursorW(None, idc)
                if h and actual == (int(h) & 0xFFFFFFFF):
                    return "reloj de arena"
    except Exception:
        return ""
    return ""


def esperar_listo(
    sondear=sondear_ventana_frontal,
    timeout_s: float = ESPERA_LISTO_S,
    intervalo_s: float = INTERVALO_S,
    dormir=time.sleep,
    reloj=time.monotonic,
) -> Resultado:
    """Espera hasta que la aplicación esté lista o se agote el tiempo.

    Si está lista a la primera, vuelve AL INSTANTE: en el caso normal no
    añade ni un milisegundo a la macro. Si se la ha visto ocupada, exige
    dos lecturas seguidas de "lista" antes de seguir, porque al cargar
    un informe el reloj de arena parpadea entre fases.
    """
    if timeout_s <= 0:
        return Resultado(True)
    t0 = reloj()
    motivo = sondear()
    if not motivo:
        return Resultado(True)
    ultimo = motivo
    listas_seguidas = 0
    while reloj() - t0 < timeout_s:
        dormir(intervalo_s)
        motivo = sondear()
        if motivo:
            ultimo = motivo
            listas_seguidas = 0
            continue
        listas_seguidas += 1
        if listas_seguidas >= 2:
            return Resultado(True, reloj() - t0, ultimo)
    return Resultado(False, reloj() - t0, ultimo)
