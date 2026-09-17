"""Pestaña "Acerca de": autoría, versión y un resumen de qué hace esto."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

AUTOR = "Francisco J. Vidal Gázquez"

from .theme import AZUL, BLANCO, LIENZO, PIZARRA, TEXTO, TEXTO_SUAVE

ESTILO = f"""
QWidget#AboutRoot {{ background: {LIENZO}; }}
QLabel#marca {{ font-size: 32px; font-weight: 700; color: {PIZARRA}; }}
QLabel#autor {{
    font-size: 15px; color: {BLANCO}; background-color: {PIZARRA};
    border-radius: 8px; padding: 18px 22px;
}}
QLabel#seccion {{
    font-size: 11px; font-weight: 700; color: {AZUL};
    letter-spacing: 0.8px;
}}
QLabel#cuerpo {{ font-size: 13px; color: {TEXTO}; line-height: 150%; }}
QLabel#pie {{ font-size: 11px; color: {TEXTO_SUAVE}; }}
"""


class AboutPanel(QWidget):
    def __init__(self, version: str = ""):
        super().__init__()
        self.setObjectName("AboutRoot")
        self.setStyleSheet(ESTILO)

        cuerpo = QWidget()
        col = QVBoxLayout(cuerpo)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(12)

        marca = QLabel("MemoviPro")
        marca.setObjectName("marca")
        col.addWidget(marca)

        sub = QLabel("Automatización de tareas repetitivas en el escritorio")
        sub.setObjectName("cuerpo")
        col.addWidget(sub)

        col.addSpacing(10)
        autor = QLabel(
            f"Diseñado y desarrollado por<br><b style='font-size:22px'>{AUTOR}</b>"
        )
        autor.setObjectName("autor")
        autor.setTextFormat(Qt.TextFormat.RichText)
        col.addWidget(autor)

        if version:
            v = QLabel(f"Versión {version}")
            v.setObjectName("pie")
            col.addWidget(v)

        col.addSpacing(16)
        col.addWidget(self._seccion("QUÉ HACE"))
        col.addWidget(self._texto(
            "Graba lo que haces con el ratón y el teclado sobre una "
            "aplicación y lo repite tantas veces como haga falta, sobre "
            "una lista de casos. Pensado para el trabajo diario contra "
            "aplicaciones de escritorio que no tienen forma de "
            "automatizarse por sí solas."
        ))

        col.addWidget(self._seccion("CÓMO ENCUENTRA LAS COSAS EN PANTALLA"))
        col.addWidget(self._texto(
            "Al grabar no guarda solo la posición del ratón: identifica el "
            "elemento en el árbol de accesibilidad de Windows, anota el "
            "rótulo que hay en ese sitio, su posición dentro de la ventana "
            "y una miniatura. Al reproducir prueba esas vías por orden, de "
            "la más fiable a la menos, antes de recurrir a las "
            "coordenadas. Por eso una macro sigue funcionando aunque la "
            "ventana haya cambiado de sitio."
        ))

        col.addWidget(self._seccion("HERRAMIENTAS"))
        col.addWidget(self._texto(
            "Modo depuración paso a paso con puntos de análisis, grabación "
            "de pasos sueltos en mitad de un proceso, cadenas de macros, "
            "programación por horarios, registro de incidencias y "
            "reanudación desde donde se quedó."
        ))

        col.addSpacing(14)
        col.addWidget(self._seccion("ACCESO"))
        col.addWidget(self._texto(
            "La pantalla de entrada evita que alguien use el programa si "
            "te levantas del sitio. No cifra nada: quien tenga acceso a "
            "los ficheros del equipo puede llegar a las macros y a los "
            "registros por su cuenta. Si manejas datos de pacientes, la "
            "protección de verdad es la del equipo — sesión de Windows "
            "bloqueada y disco cifrado.\n\n"
            "Las contraseñas se guardan cifradas de forma irreversible. "
            "Si se olvida una que se haya cambiado, basta con borrar el "
            "archivo «usuarios.json» de la carpeta data para volver a las "
            "de origen."
        ))

        col.addSpacing(18)
        col.addWidget(self._seccion("LICENCIA Y DERECHOS"))
        col.addWidget(self._texto(
            f"© 2026 {AUTOR}. <b>Todos los derechos reservados.</b><br><br>"
            "Este programa, su código y su diseño son obra original del "
            "autor, que ostenta su titularidad y todos los derechos de "
            "explotación conforme al texto refundido de la Ley de "
            "Propiedad Intelectual (Real Decreto Legislativo 1/1996).<br><br>"
            "Queda prohibida sin autorización previa y por escrito su "
            "copia, distribución, modificación, cesión a terceros o "
            "ingeniería inversa, así como la retirada o alteración de este "
            "aviso de autoría. El texto completo está en el archivo "
            "<b>LICENSE</b> que acompaña al programa.",
            rico=True,
        ))

        col.addSpacing(14)
        col.addWidget(self._seccion("RESPONSABILIDAD"))
        col.addWidget(self._texto(
            "El programa se entrega «tal cual», sin garantía de ningún "
            "tipo. Automatiza acciones de teclado y ratón sobre otras "
            "aplicaciones: quien lo utiliza es responsable de las tareas "
            "que automatice, de tener autorización para operar sobre esos "
            "sistemas y del tratamiento de los datos que maneje."
        ))
        col.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(cuerpo)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    @staticmethod
    def _seccion(texto: str) -> QLabel:
        lab = QLabel(texto)
        lab.setObjectName("seccion")
        return lab

    @staticmethod
    def _texto(texto: str, rico: bool = False) -> QLabel:
        lab = QLabel(texto)
        lab.setObjectName("cuerpo")
        lab.setWordWrap(True)
        if rico:
            lab.setTextFormat(Qt.TextFormat.RichText)
        return lab
