"""Repaso automático de una macro antes de lanzarla contra una lista.

Comprueba de una pasada las cosas que, si no, se descubren con la tanda
ya lanzada: pasos que clican a ciegas, datos de un paciente concreto que
se quedaron grabados, atajos peligrosos, pausas absurdas...

No modifica nada: solo mira y avisa. Cada aviso dice en qué paso está,
qué pasa y qué hacer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .step_model import Macro, Step, StepType

# Gravedad: "alto" = puede hacer daño o fallar seguro; "medio" = va a dar
# problemas tarde o temprano; "info" = conviene saberlo.
ALTO, MEDIO, INFO = "alto", "medio", "info"

# DNI (8 cifras + letra) y NIE (X/Y/Z + 7 cifras + letra).
_DNI = re.compile(r"\b\d{8}\s*[A-Za-z]\b")
_NIE = re.compile(r"\b[XYZxyz]\s*\d{7}\s*[A-Za-z]\b")
# Número largo suelto: tarjeta sanitaria, nº de historia, teléfono...
_NUMERO_LARGO = re.compile(r"\b\d{9,}\b")

# Atajos que no deberían estar dentro de una macro desatendida.
_ATAJOS_PELIGROSOS = {
    "%{F4}": "cierra la ventana (Alt+F4)",
    "{VK_LWIN down}l{VK_LWIN up}": "bloquea el equipo (Win+L)",
    "^%{DELETE}": "abre la pantalla de seguridad (Ctrl+Alt+Supr)",
}

# Una pausa mayor que esto casi siempre es que te fuiste a hacer otra cosa
# mientras grababas, y al reproducir se queda ahí parada.
PAUSA_SOSPECHOSA_S = 120.0


@dataclass
class Aviso:
    gravedad: str
    paso: int            # 1-based; 0 = la macro en conjunto
    titulo: str
    detalle: str


@dataclass
class Informe:
    avisos: list[Aviso] = field(default_factory=list)

    @property
    def altos(self) -> list[Aviso]:
        return [a for a in self.avisos if a.gravedad == ALTO]

    @property
    def hay_problemas(self) -> bool:
        return any(a.gravedad in (ALTO, MEDIO) for a in self.avisos)

    def resumen(self) -> str:
        if not self.avisos:
            return "Todo correcto: no he encontrado nada que avisar."
        n_alto = sum(1 for a in self.avisos if a.gravedad == ALTO)
        n_medio = sum(1 for a in self.avisos if a.gravedad == MEDIO)
        n_info = sum(1 for a in self.avisos if a.gravedad == INFO)
        partes = []
        if n_alto:
            partes.append(f"{n_alto} importante(s)")
        if n_medio:
            partes.append(f"{n_medio} a revisar")
        if n_info:
            partes.append(f"{n_info} informativo(s)")
        return " · ".join(partes)


def _texto_con_datos_personales(texto: str) -> str:
    """Devuelve qué tipo de dato personal parece contener, o ""."""
    if _DNI.search(texto):
        return "un DNI"
    if _NIE.search(texto):
        return "un NIE"
    if _NUMERO_LARGO.search(texto):
        return "un número largo (¿tarjeta sanitaria, nº de historia?)"
    return ""


def _tiene_placeholder(texto: str) -> bool:
    """¿Usa un hueco tipo {DNI} que se rellena en cada ejecución?"""
    return "{" in (texto or "") and "}" in (texto or "")


def _clic_a_ciegas(paso: Step) -> bool:
    """Un clic por coordenadas sin ninguna forma de recuperarse."""
    if paso.tipo != StepType.CLICK_AT_XY:
        return False
    extra = paso.extra or {}
    win_rel = extra.get("win_rel") or {}
    return not (win_rel.get("w") or extra.get("img_b64") or extra.get("texto_ancla"))


def revisar(macro: Macro) -> Informe:
    """Repasa la macro entera y devuelve el informe."""
    inf = Informe()
    pasos = list(macro.pasos or [])

    if not pasos:
        inf.avisos.append(Aviso(
            MEDIO, 0, "La macro no tiene pasos",
            "No hay nada que reproducir.",
        ))
        return inf

    if not (macro.ventana_principal or "").strip():
        inf.avisos.append(Aviso(
            ALTO, 0, "Sin ventana de trabajo",
            "El campo «Ventana» está vacío. Sin él no se puede acotar la "
            "búsqueda de texto a la aplicación correcta, y se pierden "
            "comprobaciones de seguridad. Escribe una parte del título de "
            "la ventana (por ejemplo «GERHONTE»).",
        ))

    a_ciegas = []
    sin_verificacion = True

    for i, paso in enumerate(pasos, start=1):
        if not paso.activo:
            inf.avisos.append(Aviso(
                INFO, i, "Paso desactivado",
                "Se saltará al reproducir. Si ya no hace falta, bórralo.",
            ))
            continue

        if paso.verificar_ventana or paso.verificar_texto:
            sin_verificacion = False

        if _clic_a_ciegas(paso):
            a_ciegas.append(i)

        if paso.tipo == StepType.CLICK_CONTROL and (
            paso.selector is None or paso.selector.is_empty()
        ):
            inf.avisos.append(Aviso(
                MEDIO, i, "Clic sin forma de identificar el destino",
                "Este paso dice ser un clic sobre un control, pero no "
                "guarda cómo encontrarlo. Vuelve a grabarlo.",
            ))

        if paso.tipo == StepType.TYPE_TEXT:
            texto = paso.valor or ""
            tipo_dato = _texto_con_datos_personales(texto)
            if tipo_dato and not _tiene_placeholder(texto):
                inf.avisos.append(Aviso(
                    ALTO, i, "Dato de un paciente concreto grabado en la macro",
                    f"Este paso escribe {tipo_dato} fijo. Se repetirá "
                    "igual para todos los casos de la lista, que casi "
                    "seguro no es lo que quieres — y además queda guardado "
                    "en el fichero de la macro. Sustitúyelo por un hueco "
                    "como {DNI}.",
                ))

        if paso.tipo == StepType.SEND_KEYS:
            token = (paso.valor or "").strip()
            for peligroso, que_hace in _ATAJOS_PELIGROSOS.items():
                if token == peligroso:
                    inf.avisos.append(Aviso(
                        ALTO, i, "Atajo peligroso",
                        f"Este paso {que_hace}. Si se coló sin querer al "
                        "grabar, bórralo: dejaría la tanda a medias.",
                    ))

        if paso.delay_before_s and paso.delay_before_s > PAUSA_SOSPECHOSA_S:
            inf.avisos.append(Aviso(
                MEDIO, i, "Pausa muy larga",
                f"Espera {int(paso.delay_before_s // 60)} minutos antes de "
                "este paso. Si fue que te distrajiste mientras grababas, "
                "bájala: se repetirá en cada caso de la lista.",
            ))

    if a_ciegas:
        muestra = ", ".join(str(n) for n in a_ciegas[:10])
        if len(a_ciegas) > 10:
            muestra += f"… y {len(a_ciegas) - 10} más"
        inf.avisos.append(Aviso(
            ALTO, a_ciegas[0], f"{len(a_ciegas)} clic(s) a ciegas",
            "Estos pasos clican en unas coordenadas fijas y no guardan "
            "ninguna forma de recuperarse si la ventana se ha movido: "
            f"pasos {muestra}. Vuelve a grabarlos para que guarden el "
            "rótulo del sitio y la posición dentro de la ventana.",
        ))

    if sin_verificacion and len(pasos) > 5:
        inf.avisos.append(Aviso(
            INFO, 0, "Ningún paso comprueba que la pantalla responde",
            "La macro actúa sin confirmar en ningún momento que la "
            "aplicación ha reaccionado. Añadir una verificación en los "
            "puntos críticos (con el botón «✓ Verificación») hace que "
            "falle a tiempo en vez de seguir a ciegas.",
        ))

    inf.avisos.sort(key=lambda a: ({ALTO: 0, MEDIO: 1, INFO: 2}[a.gravedad], a.paso))
    return inf
