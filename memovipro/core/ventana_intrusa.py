"""Qué hacer cuando se cuela una ventana delante en plena ejecución.

Pasa constantemente en un equipo de trabajo: un aviso de Windows, un
mensaje de Teams, el antivirus, una actualización. La macro iba a clicar
en un sitio concreto y de pronto hay otra cosa encima.

Hay tres respuestas posibles y solo una es buena por defecto:

  - Clicar igual → NUNCA. Es lo que hacía antes de comprobar la ventana,
    y significa pulsar a ciegas en una aplicación que no es la tuya.
  - Fallar al instante → demasiado impaciente. La mayoría de estas
    ventanas son pasajeras: un aviso que se va solo en tres segundos
    tumbaba un paso que habría funcionado sin hacer nada.
  - Tener paciencia y volver a mirar → esto.

La escalada va de lo más suave a lo más brusco:

  1. Esperar y mirar otra vez, sin tocar nada (los avisos se van solos).
  2. Traer nuestra ventana al frente (otra se puso encima sin cerrarse).
  3. Repetir 1 y 2 hasta agotar la paciencia.
  4. Cerrar la intrusa, SOLO si quien usa el programa la ha apuntado
     como "esta se puede cerrar". Nunca por nuestra cuenta: podría ser
     un diálogo importante.
  5. Rendirse, diciendo el título EXACTO de la ventana que estorbaba,
     para poder apuntarla y que la próxima vez se resuelva sola.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Politica:
    """Cuánta paciencia tener y qué ventanas se pueden cerrar."""
    # Tiempo total antes de rendirse. 15 s cubre de sobra los avisos del
    # sistema sin dejar una tanda colgada demasiado rato.
    esperar_s: float = 15.0
    intervalo_s: float = 0.8
    # Títulos (trozo, sin distinguir mayúsculas) de ventanas que se
    # pueden cerrar sin preguntar. Vacío = no cerrar nada.
    cerrar_titulos: list[str] = field(default_factory=list)


@dataclass
class Intrusa:
    proceso: str
    titulo: str

    def __str__(self) -> str:
        if self.titulo and self.proceso:
            return f"«{self.titulo}» ({self.proceso})"
        return self.titulo or self.proceso or "desconocida"


@dataclass
class Resultado:
    ok: bool
    intrusa: Intrusa | None = None
    segundos: float = 0.0
    acciones: list[str] = field(default_factory=list)

    def explicacion(self, esperado: str) -> str:
        """Mensaje para el usuario: qué estorbaba y qué puede hacer."""
        quien = str(self.intrusa) if self.intrusa else "otra ventana"
        texto = (
            f"Se puso otra ventana delante: {quien}.\n"
            f"Esperé {self.segundos:.0f} segundos e intenté recuperar "
            f"'{esperado}', pero seguía estorbando, así que el paso no se "
            "ejecuta (clicar a ciegas sería peor).\n\n"
        )
        if self.intrusa and self.intrusa.titulo:
            texto += (
                "Si esta ventana aparece a menudo y se puede cerrar sin "
                "problema, añádela en config.json:\n"
                '  "ventanas_intrusas": { "cerrar_titulos": '
                f'["{self.intrusa.titulo}"] }}\n'
                "y la próxima vez se cerrará sola."
            )
        return texto


def titulo_coincide(titulo: str, patrones) -> bool:
    """¿El título contiene alguno de los patrones? (sin distinguir
    mayúsculas, por trozo de texto — no hace falta el título entero)."""
    t = (titulo or "").lower()
    if not t:
        return False
    return any(str(p).strip().lower() in t for p in (patrones or ()) if str(p).strip())


def resolver(
    esperado: str,
    mirar,
    activar,
    cerrar,
    politica: Politica | None = None,
    dormir=time.sleep,
    reloj=time.monotonic,
) -> Resultado:
    """Intenta recuperar la ventana esperada. Devuelve qué pasó.

    `mirar()` → (proceso, titulo) de lo que está delante ahora.
    `activar()` → trae nuestra ventana al frente.
    `cerrar(titulo)` → cierra la ventana que estorba.

    Las tres se pasan como parámetro para poder probar la escalada sin
    tocar ninguna ventana de verdad.
    """
    from .proceso import mismo_programa

    pol = politica or Politica()
    t0 = reloj()
    acciones: list[str] = []
    intrusa: Intrusa | None = None
    primera_vuelta = True

    while True:
        try:
            proceso, titulo = mirar()
        except Exception:
            proceso, titulo = "", ""
        if mismo_programa(esperado, proceso):
            return Resultado(True, intrusa, reloj() - t0, acciones)

        if intrusa is None:
            intrusa = Intrusa(proceso or "", titulo or "")

        if titulo_coincide(titulo, pol.cerrar_titulos):
            acciones.append(f"cerrar:{titulo}")
            try:
                cerrar(titulo)
            except Exception:
                pass
        elif primera_vuelta:
            # Primera vuelta: solo esperar. Muchos avisos se van solos, y
            # forcejear con el foco mientras aparece un diálogo del
            # sistema no lleva a ninguna parte.
            acciones.append("esperar")
        else:
            acciones.append("activar")
            try:
                activar()
            except Exception:
                pass

        primera_vuelta = False
        if reloj() - t0 >= pol.esperar_s:
            return Resultado(False, intrusa, reloj() - t0, acciones)
        dormir(pol.intervalo_s)


def politica_desde_config(cfg) -> Politica:
    """Lee la política de config.json, con valores por defecto sensatos."""
    pol = Politica()
    try:
        seccion = (cfg or {}).get("ventanas_intrusas") or {}
        if "esperar_s" in seccion:
            pol.esperar_s = max(0.0, float(seccion["esperar_s"]))
        if "intervalo_s" in seccion:
            pol.intervalo_s = max(0.1, float(seccion["intervalo_s"]))
        titulos = seccion.get("cerrar_titulos") or []
        if isinstance(titulos, list):
            pol.cerrar_titulos = [str(t) for t in titulos if str(t).strip()]
    except Exception:
        pass
    return pol
