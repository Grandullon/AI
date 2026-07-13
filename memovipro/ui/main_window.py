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

from .dashboard_panel import DashboardPanel
from .incidents_view import IncidentsView
from .pipeline_panel import PipelinePanel
from .replay_panel import ReplayPanel
from .run_panel import RunPanel
from .schedule_panel import SchedulePanel
from .secrets_panel import SecretsPanel
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
    def __init__(self, data_dir: Path, macros_dir: Path, pipelines_dir: Path | None = None):
        super().__init__()
        self.data_dir = data_dir
        self.macros_dir = macros_dir
        self.pipelines_dir = pipelines_dir or (macros_dir.parent / "pipelines")
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle("MemoviPro — Automatización IT")
        self.setGeometry(100, 100, 1100, 700)
        self.setStyleSheet(APP_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.step_editor = StepEditor(macros_dir=self.macros_dir)
        self.replay_panel = ReplayPanel(macros_dir=self.macros_dir, data_dir=self.data_dir)
        self.pipeline_panel = PipelinePanel(
            macros_dir=self.macros_dir,
            pipelines_dir=self.pipelines_dir,
            data_dir=self.data_dir,
        )
        self.run_panel = RunPanel(
            macros_dir=self.macros_dir,
            data_dir=self.data_dir,
            on_finished=self._on_run_finished,
        )
        self.incidents_view = IncidentsView(data_dir=self.data_dir)
        self.schedule_panel = SchedulePanel(
            macros_dir=self.macros_dir,
            data_dir=self.data_dir,
            pipelines_dir=self.pipelines_dir,
        )
        self.secrets_panel = SecretsPanel(data_dir=self.data_dir)
        self.dashboard_panel = DashboardPanel(data_dir=self.data_dir)

        self.tabs.addTab(self.step_editor, "Macros")
        self.tabs.addTab(self.replay_panel, "Reproducir")
        self.tabs.addTab(self.pipeline_panel, "Cadenas")
        self.tabs.addTab(self.run_panel, "Ejecutar (por DNI)")
        self.tabs.addTab(self.schedule_panel, "Programación")
        self.tabs.addTab(self.secrets_panel, "Secretos")
        self.tabs.addTab(self.incidents_view, "Incidencias")
        self.tabs.addTab(self.dashboard_panel, "Dashboard")
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
        self.dashboard_panel.refresh()
        self.tabs.setCurrentWidget(self.incidents_view)

    def _abortar_todo(self):
        """Aborta cualquier ejecución en marcha en todos los paneles."""
        for panel in (self.run_panel, self.replay_panel, self.pipeline_panel):
            try:
                panel.abort()
            except Exception:
                pass

    def _panic(self):
        # Incluye pipeline_panel: una cadena de macros en marcha (que puede
        # durar mucho y controla el ratón) debe poder pararse con la tecla
        # de emergencia igual que una ejecución por DNI o un replay.
        self._abortar_todo()
        self.statusBar().showMessage("⏹  Ejecución abortada por el usuario (panic key)")

    def _hilos_en_marcha(self):
        """Lista de QThreads de ejecución actualmente corriendo."""
        hilos = []
        for panel in (self.run_panel, self.replay_panel, self.pipeline_panel):
            th = getattr(panel, "_thread", None)
            if th is not None and th.isRunning():
                hilos.append(th)
        return hilos

    def _detener_hilos(self, hilos) -> None:
        """Aborta todo y espera (con tope) a que los workers terminen."""
        self._abortar_todo()
        for th in hilos:
            try:
                th.wait(3000)  # dar 3s a que el worker vea el abort y salga
            except Exception:
                pass

    def closeEvent(self, event):
        """Al cerrar la ventana, aborta y espera a los hilos de ejecución.

        Sin esto, cerrar MemoviPro con una macro en marcha dejaba el hilo
        worker automatizando el escritorio (clicando/tecleando) mientras
        el bucle de Qt ya había terminado — comportamiento impredecible y
        potencialmente peligroso sobre la app destino.

        La decisión (qué hilos hay, abortarlos, esperar) vive en
        `_hilos_en_marcha`/`_detener_hilos` para poder testearla sin
        instanciar QMainWindow (super() aquí lo impediría)."""
        hilos = self._hilos_en_marcha()
        if hilos:
            from PyQt6.QtWidgets import QMessageBox
            resp = QMessageBox.question(
                self, "Ejecución en marcha",
                "Hay una ejecución en curso. ¿Detenerla y salir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._detener_hilos(hilos)
        super().closeEvent(event)
