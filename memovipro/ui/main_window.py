from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .incidents_view import IncidentsView
from .run_panel import RunPanel
from .schedule_panel import SchedulePanel
from .step_editor import StepEditor

APP_STYLE = """
QMainWindow, QDialog { background-color: #f0f4f8; color: #2c3e50; }
QTabWidget::pane { border: 1px solid #bdc3c7; border-radius: 4px; }
QTabBar::tab {
    background: #ecf0f1; padding: 8px 16px; border: 1px solid #bdc3c7;
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #3498db; color: white; }
QPushButton {
    background-color: #3498db; color: white; border: none;
    padding: 8px 16px; font-size: 14px; border-radius: 4px;
}
QPushButton:hover { background-color: #2980b9; }
QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
QLabel, QComboBox, QListWidget, QTableWidget { font-size: 14px; color: #2c3e50; }
QLineEdit, QComboBox, QSpinBox {
    background: white; border: 1px solid #bdc3c7; padding: 4px;
    border-radius: 3px;
}
QProgressBar { border: 2px solid #3498db; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background-color: #3498db; }
"""


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path, macros_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.macros_dir = macros_dir
        self.setWindowTitle("MemoviPro — Automatización IT")
        self.setGeometry(100, 100, 1100, 700)
        self.setStyleSheet(APP_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.step_editor = StepEditor(macros_dir=self.macros_dir)
        self.run_panel = RunPanel(
            macros_dir=self.macros_dir,
            data_dir=self.data_dir,
            on_finished=self._on_run_finished,
        )
        self.incidents_view = IncidentsView(data_dir=self.data_dir)

        self.schedule_panel = SchedulePanel(macros_dir=self.macros_dir, data_dir=self.data_dir)

        self.tabs.addTab(self.step_editor, "Macros")
        self.tabs.addTab(self.run_panel, "Ejecutar")
        self.tabs.addTab(self.schedule_panel, "Programación")
        self.tabs.addTab(self.incidents_view, "Incidencias")
        layout.addWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Listo")

        panic = QShortcut(QKeySequence("Ctrl+Alt+Esc"), self)
        panic.activated.connect(self._panic)

    def _on_run_finished(self, summary):
        self.statusBar().showMessage(
            f"Ejecución terminada — Total: {summary.total} · OK: {summary.ok} · KO: {summary.ko}"
        )
        self.incidents_view.refresh()
        self.tabs.setCurrentWidget(self.incidents_view)

    def _panic(self):
        self.run_panel.abort()
        self.statusBar().showMessage("⏹  Ejecución abortada por el usuario (panic key)")
