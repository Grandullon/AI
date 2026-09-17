"""Pestaña "Acerca de": autoría, versión y un resumen de qué hace esto."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

AUTOR = "Francisco J. Vidal Gázquez"

ESTILO = """
QWidget#AboutRoot { background: #f0f4f8; }
QLabel#marca {
    font-size: 30px; font-weight: bold; color: #2c3e50;
}
QLabel#autor {
    font-size: 17px; color: #ffffff; background-color: #2c3e50;
    border-radius: 6px; padding: 14px 18px;
}
QLabel#seccion { font-size: 15px; font-weight: bold; color: #2980b9; }
QLabel#cuerpo { font-size: 13px; color: #34495e; }
QLabel#pie { font-size: 11px; color: #7f8c8d; }
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
        col.addWidget(self._seccion("Qué hace"))
        col.addWidget(self._texto(
            "Graba lo que haces con el ratón y el teclado sobre una "
            "aplicación y lo repite tantas veces como haga falta, sobre "
            "una lista de casos. Pensado para el trabajo diario contra "
            "aplicaciones de escritorio que no tienen forma de "
            "automatizarse por sí solas."
        ))

        col.addWidget(self._seccion("Cómo encuentra las cosas en pantalla"))
        col.addWidget(self._texto(
            "Al grabar no guarda solo la posición del ratón: identifica el "
            "elemento en el árbol de accesibilidad de Windows, anota el "
            "rótulo que hay en ese sitio, su posición dentro de la ventana "
            "y una miniatura. Al reproducir prueba esas vías por orden, de "
            "la más fiable a la menos, antes de recurrir a las "
            "coordenadas. Por eso una macro sigue funcionando aunque la "
            "ventana haya cambiado de sitio."
        ))

        col.addWidget(self._seccion("Herramientas"))
        col.addWidget(self._texto(
            "Modo depuración paso a paso con puntos de análisis, grabación "
            "de pasos sueltos en mitad de un proceso, cadenas de macros, "
            "programación por horarios, registro de incidencias y "
            "reanudación desde donde se quedó."
        ))

        col.addSpacing(18)
        pie = QLabel(
            "Herramienta de uso personal. Quien la utilice es responsable "
            "de lo que automatice con ella y de los datos que maneje."
        )
        pie.setObjectName("pie")
        pie.setWordWrap(True)
        col.addWidget(pie)
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
    def _texto(texto: str) -> QLabel:
        lab = QLabel(texto)
        lab.setObjectName("cuerpo")
        lab.setWordWrap(True)
        return lab
