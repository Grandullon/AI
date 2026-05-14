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
from .replay_panel import ReplayPanel
from .run_panel import RunPanel
from .schedule_panel import SchedulePanel
from .step_editor import StepEditor

APP_STYLE = """
QMainWindow, QDialog, QWidget { background-color: #f0f4f8; color: #2c3e50; }
QTabWidget::pane { border: 1px solid #bdc3c7; border-radius: 4px; background: #f0f4f8; }
QTabBar::tab {
    background: #ecf0f1; color: #2c3e50;
    padding: 8px 16px; border: 1px solid #bdc3c7;
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #3498db; color: white; }
QTabBar::tab:!selected:hover { background: #d6dbdf; }
QPushButton {
    background-color: #3498db; color: white; border: none;
    padding: 8px 16px; font-size: 14px; border-radius: 4px;
}
QPushButton:hover { background-color: #2980b9; }
QPushButton:disabled { background-color: #bdc3c7; color: #7f8c8d; }
QLabel { font-size: 14px; color: #2c3e50; background: transparent; }
QLineEdit, QComboBox, QSpinBox, QTimeEdit, QTextEdit, QPlainTextEdit {
    background: white; color: #2c3e50;
    border: 1px solid #bdc3c7; padding: 4px;
    border-radius: 3px;
    selection-background-color: #3498db; selection-color: white;
}
QComboBox QAbstractItemView {
    background: white; color: #2c3e50;
    selection-background-color: #3498db; selection-color: white;
}
QTableWidget, QListWidget {
    background-color: white; color: #2c3e50;
    border: 1px solid #bdc3c7; gridline-color: #ecf0f1;
    alternate-background-color: #fafbfc;
    selection-background-color: #3498db; selection-color: white;
}
QTableWidget::item, QListWidget::item { color: #2c3e50; }
QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #3498db; color: white;
}
QHeaderView::section {
    background-color: #2c3e50; color: white;
    padding: 6px; border: 1px solid #34495e; font-weight: bold;
}
QHeaderView { background-color: #2c3e50; }
QProgressBar {
    border: 2px solid #3498db; border-radius: 5px; text-align: center;
    background: white; color: #2c3e50;
}
QProgressBar::chunk { background-color: #3498db; }
QStatusBar { color: #2c3e50; background: #ecf0f1; }
QCheckBox { color: #2c3e50; background: transparent; }
QMessageBox { background-color: #f0f4f8; color: #2c3e50; }
QMessageBox QLabel { color: #2c3e50; }
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
        self.replay_panel = ReplayPanel(macros_dir=self.macros_dir, data_dir=self.data_dir)
        self.run_panel = RunPanel(
            macros_dir=self.macros_dir,
            data_dir=self.data_dir,
            on_finished=self._on_run_finished,
        )
        self.incidents_view = IncidentsView(data_dir=self.data_dir)
        self.schedule_panel = SchedulePanel(macros_dir=self.macros_dir, data_dir=self.data_dir)

        self.tabs.addTab(self.step_editor, "Macros")
        self.tabs.addTab(self.replay_panel, "Reproducir")
        self.tabs.addTab(self.run_panel, "Ejecutar (por DNI)")
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
        self.replay_panel.abort()
        self.statusBar().showMessage("⏹  Ejecución abortada por el usuario (panic key)")
