"""Opciones de ejecución de uno o varios pasos: cómo actuar y cuántas
veces reintentar."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

METODO_RATON = "raton"
METODO_SIMULADO = "simular"


class OpcionesPasoDialog(QDialog):
    def __init__(self, n_pasos: int, metodo: str = METODO_RATON,
                 reintentos: int = 2, espera_s: float = 0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opciones del paso" if n_pasos == 1
                            else f"Opciones de {n_pasos} pasos")
        self.setMinimumWidth(520)
        col = QVBoxLayout(self)

        if n_pasos > 1:
            aviso = QLabel(f"Se aplicará a los <b>{n_pasos} pasos</b> seleccionados.")
            col.addWidget(aviso)

        form = QFormLayout()
        self.metodo = QComboBox()
        self.metodo.addItem("Con el ratón (normal)", METODO_RATON)
        self.metodo.addItem("Simulado — sin ratón ni traer la ventana al frente",
                            METODO_SIMULADO)
        self.metodo.setCurrentIndex(1 if metodo == METODO_SIMULADO else 0)
        form.addRow("Cómo actuar:", self.metodo)

        self.reintentos = QSpinBox()
        self.reintentos.setRange(0, 10)
        self.reintentos.setValue(max(0, min(10, int(reintentos))))
        form.addRow("Reintentos si falla:", self.reintentos)

        self.espera = QDoubleSpinBox()
        self.espera.setRange(0.0, 60.0)
        self.espera.setDecimals(1)
        self.espera.setSingleStep(0.5)
        self.espera.setSuffix(" s")
        self.espera.setSpecialValueText("automática (0,5 s, 1 s, 2 s…)")
        self.espera.setValue(max(0.0, float(espera_s or 0.0)))
        form.addRow("Espera entre reintentos:", self.espera)
        col.addLayout(form)

        ayuda = QLabel(
            "<b>Simulado</b> pulsa el control «por dentro», como hace UiPath: "
            "no mueve el ratón ni necesita que la ventana esté delante, así "
            "que no le afectan las ventanas abiertas por detrás. Funciona con "
            "controles que tienen nombre (botones, menús, casillas, "
            "elementos de lista). Si en algún paso no se puede, se usa el "
            "ratón automáticamente.<br><br>"
            "<b>Reintentos:</b> solo se repite la acción, nunca la "
            "comprobación que va detrás, así que un «Guardar» no se "
            "duplica por fallar la verificación. Con una aplicación lenta, "
            "sube la espera: un reintento no sirve si llega antes de que la "
            "pantalla esté lista."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: #5b6b7c; font-size: 12px;")
        col.addWidget(ayuda)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        col.addWidget(botones)

    def valores(self) -> tuple[str, int, float]:
        return (self.metodo.currentData(), self.reintentos.value(),
                float(self.espera.value()))


from core.opciones_paso import aplicar_opciones, marcas_del_paso  # noqa: E402,F401
