"""Panel de control flotante para grabación y reproducción.

Inspirado en el "Studio Robot" de UiPath: una ventana pequeña siempre
encima donde el usuario ve qué está pasando y puede pausar/parar sin
tener que volver a MemoviPro y buscar el botón.

Características:
- Frameless, always-on-top, arrastrable por cualquier zona.
- Auto-posicionado en la esquina superior derecha al mostrarse.
- Muestra:
    · Título y subtítulo (estado actual)
    · Acción actual en curso (paso, iteración)
    · Barra de progreso (opcional)
    · Botones Pausa/Reanudar y Detener
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


CONTROL_STYLE = """
QWidget#ControlRoot {
    background-color: rgba(44, 62, 80, 235);
    border: 1px solid #1a252f;
    border-radius: 8px;
}
QLabel { color: white; background: transparent; }
QLabel#title { font-weight: bold; font-size: 13px; }
QLabel#subtitle { font-size: 11px; color: #bdc3c7; }
QLabel#action { font-size: 10px; color: #ecf0f1; font-style: italic; }
QPushButton {
    background-color: #34495e; color: white;
    border: 1px solid #4a6378; padding: 5px 12px;
    border-radius: 4px; font-size: 12px;
}
QPushButton:hover { background-color: #4a6378; }
QPushButton#stop { background-color: #c0392b; border-color: #922b21; }
QPushButton#stop:hover { background-color: #a93226; }
QProgressBar {
    background-color: #1e272e; border: 1px solid #4a6378;
    border-radius: 3px; text-align: center; color: white;
    font-size: 10px; max-height: 14px;
}
QProgressBar::chunk { background-color: #27ae60; }
"""


class ControlWindow(QWidget):
    """Ventana de control flotante (signals: pause_toggled, stop_requested)."""

    pause_toggled = pyqtSignal(bool)
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ControlRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet(CONTROL_STYLE)
        self._paused = False
        self._drag_offset = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)

        self.title_label = QLabel("MemoviPro")
        self.title_label.setObjectName("title")
        root.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("subtitle")
        root.addWidget(self.subtitle_label)

        self.progress = QProgressBar()
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.action_label = QLabel("")
        self.action_label.setObjectName("action")
        self.action_label.setWordWrap(True)
        root.addWidget(self.action_label)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 4, 0, 0)
        btns.setSpacing(6)
        self.pause_btn = QPushButton("⏸  Pausa")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn = QPushButton("⏹  Parar")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        btns.addWidget(self.pause_btn)
        btns.addWidget(self.stop_btn)
        btns.addStretch()
        root.addLayout(btns)

        self.setFixedWidth(340)
        self.adjustSize()

    # ---- Posicionamiento y arrastre ----

    def show_in_corner(self):
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is not None:
            self.move(scr.right() - self.width() - 20, scr.top() + 20)
        self.show()
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    # ---- API pública ----

    def set_title(self, title: str, subtitle: str = ""):
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def set_action(self, action: str):
        self.action_label.setText(action)

    def set_progress(self, value: int, maximum: int):
        self.progress.setMaximum(max(1, maximum))
        self.progress.setValue(value)
        self.progress.setFormat(f"%v / %m")

    def hide_progress(self):
        self.progress.setVisible(False)

    def show_progress(self):
        self.progress.setVisible(True)

    def set_paused(self, paused: bool):
        """Actualiza el estado del botón sin emitir señal (para sync externo)."""
        self._paused = paused
        self.pause_btn.setText("▶  Reanudar" if paused else "⏸  Pausa")

    def _toggle_pause(self):
        self._paused = not self._paused
        self.set_paused(self._paused)
        self.pause_toggled.emit(self._paused)
