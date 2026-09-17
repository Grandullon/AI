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

from .about_panel import AboutPanel
from .theme import APP_STYLE
from .dashboard_panel import DashboardPanel
from .incidents_view import IncidentsView
from .pipeline_panel import PipelinePanel
from .replay_panel import ReplayPanel
from .run_panel import RunPanel
from .schedule_panel import SchedulePanel
from .secrets_panel import SecretsPanel
from .step_editor import StepEditor



def _version() -> str:
    """Versión del paquete, si está disponible."""
    try:
        from core import __version__
        return str(__version__)
    except Exception:
        return ""


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path, macros_dir: Path, pipelines_dir: Path | None = None):
        super().__init__()
        self.data_dir = data_dir
        self.macros_dir = macros_dir
        self.pipelines_dir = pipelines_dir or (macros_dir.parent / "pipelines")
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle("MemoviPro — Automatización de tareas")
        # La autoría vive en la pestaña "ℹ" (ui/about_panel.py).
        self.setGeometry(100, 100, 1280, 780)
        self.setMinimumSize(1060, 640)
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
        self.about_panel = AboutPanel(version=_version())

        self.tabs.addTab(self.step_editor, "Macros")
        self.tabs.addTab(self.replay_panel, "Reproducir")
        self.tabs.addTab(self.pipeline_panel, "Cadenas")
        self.tabs.addTab(self.run_panel, "Ejecutar por lista")
        self.tabs.addTab(self.schedule_panel, "Programación")
        self.tabs.addTab(self.secrets_panel, "Credenciales")
        self.tabs.addTab(self.incidents_view, "Incidencias")
        self.tabs.addTab(self.dashboard_panel, "Resumen")
        self.tabs.addTab(self.about_panel, "Acerca de")
        self.tabs.setTabToolTip(
            self.tabs.count() - 1,
            "Autoría, licencia y cómo funciona")
        layout.addWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            "Listo  ·  Ctrl+Alt+Esc detiene cualquier ejecución")

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
        """Aborta cualquier ejecución en marcha en todos los paneles.

        Incluye el editor de Macros (StepEditor), cuyos hilos de "▶ Hasta
        aquí/Desde aquí" y "paso a paso" tienen otros nombres y antes se
        quedaban fuera del cierre limpio y de la tecla de pánico."""
        for panel in (self.run_panel, self.replay_panel,
                      self.pipeline_panel, self.step_editor):
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
        # El editor de Macros tiene hilos con otros nombres (rango, paso a
        # paso); los expone por su propio método.
        try:
            hilos.extend(self.step_editor.hilos_en_marcha())
        except Exception:
            pass
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
