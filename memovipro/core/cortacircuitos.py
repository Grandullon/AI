"""Corte automático cuando una tanda se descarrila.

Un fallo suelto es normal: ese paciente no está, el dato no cuadra, la
pantalla tardó de más. Varios fallos SEGUIDOS significan otra cosa: la
aplicación ha cambiado, la ventana se ha cerrado, la sesión ha caducado o
la macro está clicando donde no debe.

Sin este corte, una macro perdida seguía recorriendo la lista entera
tecleando sobre lo que hubiera delante. En una aplicación clínica eso no
es un rato perdido: es escribir en el historial de pacientes que no
tocaban. Más vale parar y que alguien mire.
"""
from __future__ import annotations

# Fallos consecutivos que se toleran antes de parar. Tres es suficiente
# para distinguir "estos casos no estaban" de "esto se ha descarrilado",
# sin cortar por dos incidencias sueltas seguidas por casualidad.
MAX_KO_SEGUIDOS = 3


class Cortacircuitos:
    """Cuenta fallos consecutivos y dice cuándo hay que parar."""

    def __init__(self, maximo: int = MAX_KO_SEGUIDOS):
        # 0 o negativo = desactivado (recorre la lista entera pase lo que pase).
        self.maximo = int(maximo)
        self.seguidos = 0
        self.disparado = False

    def registrar(self, exito: bool) -> None:
        if exito:
            self.seguidos = 0
            return
        self.seguidos += 1
        if self.maximo > 0 and self.seguidos >= self.maximo:
            self.disparado = True

    def debe_parar(self) -> bool:
        return self.disparado

    @property
    def motivo(self) -> str:
        return (
            f"{self.seguidos} casos seguidos han fallado. La tanda se ha "
            "detenido sola para no seguir actuando sobre una pantalla que "
            "probablemente no es la esperada.\n\n"
            "Revisa que la aplicación siga abierta y en la pantalla correcta, "
            "y reanuda con «Solo pendientes» para continuar donde se quedó."
        )
