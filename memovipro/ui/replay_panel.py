"""Panel "Reproducir": ejecuta una macro N veces con velocidad ajustable.

Versión simple — sin Excel de DNIs ni checkpoints. Solo:
  - elegir macro
  - cuántas veces
  - velocidad (0.5x, 1x, 1.5x, 2x o "sin pausas")
  - watchdog de popups (on/off)
  - botón Ejecutar / Detener
  - progreso por iteración con log
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.replay_runner import ReplayRunner, ReplaySummary
from core.step_model import Macro


VELOCIDADES = [
    ("0.5x  (mitad de velocidad)", 0.5),
    ("1x  (original — recomendado)", 1.0),
    ("1.5x", 1.5),
    ("2x  (el doble de rápido)", 2.0),
    ("Máxima  (sin pausas)", 0.0),
]


class _ReplayThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished_summary = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, runner: ReplayRunner):
        super().__init__()
        self.runner = runner

    def _on_iter_done(self, n: int, ok: bool, motivo: str):
        marca = "✓" if ok else "✗"
        if ok:
            self.log_line.emit(f"  {marca}  iter {n:04d}   ok")
        else:
            self.log_line.emit(f"  {marca}  iter {n:04d}   KO — {motivo}")
        self.progress.emit(n, self.runner.veces)

    def run(self):
        try:
            self.runner.on_iter_done = self._on_iter_done
            summary = self.runner.run()
            self.finished_summary.emit(summary)
        except Exception as exc:
            self.error.emit(str(exc))


class ReplayPanel(QWidget):
    def __init__(self, macros_dir: Path, data_dir: Path):
        super().__init__()
        self.macros_dir = macros_dir
        self.data_dir = data_dir
        self._thread: _ReplayThread | None = None
        self._runner: ReplayRunner | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Reproducir una macro N veces</b>"))

        fila_macro = QHBoxLayout()
        self.macro_combo = QComboBox()
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setMaximumWidth(40)
        self.refresh_btn.clicked.connect(self.refresh_macros)
        fila_macro.addWidget(QLabel("Macro:"))
        fila_macro.addWidget(self.macro_combo, 1)
        fila_macro.addWidget(self.refresh_btn)
        layout.addLayout(fila_macro)

        fila_params = QHBoxLayout()
        self.veces_spin = QSpinBox()
        self.veces_spin.setRange(1, 9999)
        self.veces_spin.setValue(1)
        self.veces_spin.setMaximumWidth(110)
        self.velocidad_combo = QComboBox()
        for label, _ in VELOCIDADES:
            self.velocidad_combo.addItem(label)
        self.velocidad_combo.setCurrentIndex(1)  # 1x por defecto
        fila_params.addWidget(QLabel("Veces:"))
        fila_params.addWidget(self.veces_spin)
        fila_params.addSpacing(20)
        fila_params.addWidget(QLabel("Velocidad:"))
        fila_params.addWidget(self.velocidad_combo, 1)
        layout.addLayout(fila_params)

        self.watchdog_chk = QCheckBox(
            "Detectar ventanas emergentes durante la reproducción "
            "(registra título, texto y screenshot en el Excel de incidencias)"
        )
        self.watchdog_chk.setChecked(True)
        layout.addWidget(self.watchdog_chk)

        botones = QHBoxLayout()
        self.run_btn = QPushButton("▶ Ejecutar")
        self.run_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("⏹ Detener")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.stop_btn.clicked.connect(self.abort)
        botones.addWidget(self.run_btn)
        botones.addWidget(self.stop_btn)
        botones.addStretch()
        layout.addLayout(botones)

        layout.addWidget(QLabel("Progreso:"))
        self.progress = QProgressBar()
        self.progress.setFormat("Iteración %v de %m")
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "background: #1e272e; color: #ecf0f1; font-family: Consolas, monospace; font-size: 12px;"
        )
        layout.addWidget(self.log_view, 1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        self.refresh_macros()

    def refresh_macros(self):
        self.macro_combo.clear()
        for p in sorted(self.macros_dir.glob("*.yaml")):
            self.macro_combo.addItem(p.name, str(p))
        for p in sorted(self.macros_dir.glob("*.yml")):
            self.macro_combo.addItem(p.name, str(p))

    def _start(self):
        path = self.macro_combo.currentData()
        if not path:
            QMessageBox.warning(self, "Sin macro", "Selecciona una macro YAML.")
            return
        try:
            macro = Macro.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar la macro: {exc}")
            return
        if not macro.pasos:
            QMessageBox.warning(self, "Macro vacía", "La macro no tiene pasos.")
            return

        veces = self.veces_spin.value()
        velocidad = VELOCIDADES[self.velocidad_combo.currentIndex()][1]
        watchdog = self.watchdog_chk.isChecked()

        self.log_view.clear()
        self.progress.setValue(0)
        self.progress.setMaximum(veces)
        self.summary_label.setText("")

        self._runner = ReplayRunner(
            macro=macro,
            veces=veces,
            velocidad=velocidad if velocidad > 0 else 0.0,
            screenshots_dir=self.data_dir / "screenshots",
            data_dir=self.data_dir,
            watchdog_activo=watchdog,
        )
        self._thread = _ReplayThread(self._runner)
        self._thread.log_line.connect(self.log_view.append)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self.log_view.append(
            f"▶  Macro: {macro.nombre} · {len(macro.pasos)} pasos · {veces} iteraciones"
        )
        self.log_view.append(f"   Velocidad: {self.velocidad_combo.currentText()}")
        self.log_view.append(f"   Watchdog popups: {'ON' if watchdog else 'OFF'}")
        self.log_view.append("")
        self._thread.start()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_progress(self, done: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_finished(self, summary: ReplaySummary):
        self.log_view.append("")
        self.log_view.append(f"=== FIN === Total: {summary.total}  ·  OK: {summary.ok}  ·  KO: {summary.ko}")
        self.log_view.append(f"Log incidencias: {summary.log_path}")
        color = "#27ae60" if summary.ko == 0 else "#c0392b"
        self.summary_label.setText(
            f"<span style='color:{color}'>Terminado · {summary.ok}/{summary.total} OK · {summary.ko} KO</span>"
        )
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_error(self, msg: str):
        self.log_view.append(f"\n❌ ERROR: {msg}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def abort(self):
        if self._runner:
            self._runner.abort()
        self.log_view.append("\n⏹  Abortando…")
