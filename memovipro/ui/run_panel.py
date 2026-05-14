from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.runner import MacroRunner, RunSummary
from core.step_model import Macro


class _RunThread(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished_summary = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, runner: MacroRunner, solo_pendientes: bool):
        super().__init__()
        self.runner = runner
        self.solo_pendientes = solo_pendientes
        self._dni_count = 0
        self._dni_total = 0

    def _on_dni_done(self, dni: str, exito: bool):
        self._dni_count += 1
        marca = "✓" if exito else "✗"
        self.log.emit(f"  {marca}  {dni}")
        self.progress.emit(self._dni_count, self._dni_total)

    def run(self):
        try:
            from core.dni_iterator import cargar_dnis
            todos = cargar_dnis(self.runner.excel_dnis)
            cola = self.runner.checkpoint.pendientes(todos) if self.solo_pendientes else todos
            self._dni_total = len(cola)
            self.log.emit(f"DNIs a procesar: {self._dni_total}")
            self.runner.on_dni_done = self._on_dni_done
            summary = self.runner.run(solo_pendientes=self.solo_pendientes)
            self.finished_summary.emit(summary)
        except Exception as exc:
            self.error.emit(str(exc))


class RunPanel(QWidget):
    def __init__(self, macros_dir: Path, data_dir: Path, on_finished: Callable[[RunSummary], None]):
        super().__init__()
        self.macros_dir = macros_dir
        self.data_dir = data_dir
        self.on_finished = on_finished
        self._thread: _RunThread | None = None
        self._runner: MacroRunner | None = None

        layout = QVBoxLayout(self)

        macro_row = QHBoxLayout()
        self.macro_combo = QComboBox()
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setMaximumWidth(40)
        self.refresh_btn.clicked.connect(self.refresh_macros)
        macro_row.addWidget(QLabel("Macro:"))
        macro_row.addWidget(self.macro_combo, 1)
        macro_row.addWidget(self.refresh_btn)
        layout.addLayout(macro_row)

        excel_row = QHBoxLayout()
        self.excel_path = QLineEdit()
        self.excel_path.setPlaceholderText("Excel/CSV con columna DNI")
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse_excel)
        excel_row.addWidget(QLabel("DNIs:"))
        excel_row.addWidget(self.excel_path, 1)
        excel_row.addWidget(browse)
        layout.addLayout(excel_row)

        self.solo_pendientes = QCheckBox("Solo pendientes (saltar DNIs ya completados según checkpoint)")
        self.solo_pendientes.setChecked(True)
        layout.addWidget(self.solo_pendientes)

        btns = QHBoxLayout()
        self.run_btn = QPushButton("▶  Ejecutar")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("⏹  Abortar")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.abort)
        btns.addWidget(self.run_btn)
        btns.addWidget(self.stop_btn)
        btns.addStretch()
        layout.addLayout(btns)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        self.refresh_macros()

    def refresh_macros(self):
        self.macro_combo.clear()
        for p in sorted(self.macros_dir.glob("*.yaml")):
            self.macro_combo.addItem(p.name, str(p))
        for p in sorted(self.macros_dir.glob("*.yml")):
            self.macro_combo.addItem(p.name, str(p))

    def _browse_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Excel/CSV de DNIs", "", "Datos (*.xlsx *.xls *.csv)")
        if path:
            self.excel_path.setText(path)

    def _start(self):
        macro_path = self.macro_combo.currentData()
        if not macro_path:
            QMessageBox.warning(self, "Sin macro", "Selecciona una macro YAML.")
            return
        excel_path = self.excel_path.text().strip()
        if not excel_path:
            QMessageBox.warning(self, "Sin Excel", "Selecciona un Excel/CSV de DNIs.")
            return
        try:
            macro = Macro.load(macro_path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar macro: {exc}")
            return

        self.log_view.clear()
        self.progress.setValue(0)
        self._runner = MacroRunner(
            macro=macro,
            excel_dnis=excel_path,
            screenshots_dir=self.data_dir / "screenshots",
            data_dir=self.data_dir,
        )
        self._thread = _RunThread(self._runner, solo_pendientes=self.solo_pendientes.isChecked())
        self._thread.log.connect(self._append_log)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _append_log(self, text: str):
        self.log_view.append(text)

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(done)

    def _on_finished(self, summary: RunSummary):
        self._append_log(f"\n=== FIN ===\nOK: {summary.ok}   KO: {summary.ko}   Total: {summary.total}\nLog: {summary.log_path}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.on_finished(summary)

    def _on_error(self, msg: str):
        self._append_log(f"\n❌ ERROR: {msg}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def abort(self):
        if self._runner:
            self._runner.abort()
        self._append_log("\n⏹  Abortado por el usuario")
