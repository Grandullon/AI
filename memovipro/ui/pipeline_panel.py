"""Panel para crear, editar y ejecutar pipelines (cadenas de macros)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.pipeline import Condicion, OnFailPolicy, Pipeline, PipelineStep
from core.pipeline_runner import PipelineRunner, PipelineStepResult, PipelineSummary


COLS_PASOS = ["#", "Macro", "Veces", "Velocidad", "Pausa (s)", "Si falla", "Condición", "Descripción"]


class _PasoDialog(QDialog):
    def __init__(self, macros_dir: Path, paso: PipelineStep | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paso del pipeline")
        self.macros_dir = macros_dir

        layout = QFormLayout(self)
        self.macro_combo = QComboBox()
        for p in sorted(macros_dir.glob("*.yaml")):
            self.macro_combo.addItem(p.stem)
        for p in sorted(macros_dir.glob("*.yml")):
            self.macro_combo.addItem(p.stem)
        layout.addRow("Macro:", self.macro_combo)

        self.veces = QSpinBox()
        self.veces.setRange(1, 9999)
        self.veces.setValue(1)
        layout.addRow("Veces:", self.veces)

        self.velocidad = QDoubleSpinBox()
        self.velocidad.setRange(0.0, 10.0)
        self.velocidad.setSingleStep(0.5)
        self.velocidad.setDecimals(2)
        self.velocidad.setValue(1.0)
        self.velocidad.setSpecialValueText("Sin pausas (0)")
        layout.addRow("Velocidad:", self.velocidad)

        self.pausa = QDoubleSpinBox()
        self.pausa.setRange(0.0, 3600.0)
        self.pausa.setSuffix(" s")
        layout.addRow("Pausa antes:", self.pausa)

        self.on_fail = QComboBox()
        self.on_fail.addItem("Detener cadena (stop)", OnFailPolicy.STOP.value)
        self.on_fail.addItem("Continuar (continue)", OnFailPolicy.CONTINUE.value)
        self.on_fail.addItem("Saltar resto (skip_rest)", OnFailPolicy.SKIP_REST.value)
        layout.addRow("Si falla:", self.on_fail)

        self.condicion = QComboBox()
        self.condicion.addItem("Siempre", Condicion.SIEMPRE.value)
        self.condicion.addItem("Solo si todas las anteriores fueron OK", Condicion.TODOS_OK.value)
        self.condicion.addItem("Solo si alguna anterior tuvo KO", Condicion.ALGUNA_KO.value)
        layout.addRow("Condición:", self.condicion)

        self.descripcion = QLineEdit()
        layout.addRow("Descripción:", self.descripcion)

        if paso is not None:
            i = self.macro_combo.findText(paso.macro)
            if i >= 0:
                self.macro_combo.setCurrentIndex(i)
            else:
                self.macro_combo.addItem(paso.macro)
                self.macro_combo.setCurrentIndex(self.macro_combo.count() - 1)
            self.veces.setValue(paso.veces)
            self.velocidad.setValue(paso.velocidad)
            self.pausa.setValue(paso.pausa_antes_s)
            for combo, val in (
                (self.on_fail, paso.on_fail.value),
                (self.condicion, paso.condicion.value),
            ):
                idx = combo.findData(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.descripcion.setText(paso.descripcion)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def to_paso(self) -> PipelineStep:
        return PipelineStep(
            macro=self.macro_combo.currentText(),
            veces=self.veces.value(),
            velocidad=float(self.velocidad.value()),
            pausa_antes_s=float(self.pausa.value()),
            on_fail=OnFailPolicy(self.on_fail.currentData()),
            condicion=Condicion(self.condicion.currentData()),
            descripcion=self.descripcion.text().strip(),
        )


class _PipelineThread(QThread):
    log_line = pyqtSignal(str)
    finished_summary = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, runner: PipelineRunner):
        super().__init__()
        self.runner = runner

    def run(self):
        try:
            self.runner.on_log = lambda m: self.log_line.emit(m)
            summary = self.runner.run()
            self.finished_summary.emit(summary)
        except Exception as exc:
            self.error.emit(str(exc))


class PipelinePanel(QWidget):
    def __init__(self, macros_dir: Path, pipelines_dir: Path, data_dir: Path):
        super().__init__()
        self.macros_dir = macros_dir
        self.pipelines_dir = pipelines_dir
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.pipeline = Pipeline(nombre="nueva_cadena")
        self._runner: PipelineRunner | None = None
        self._thread: _PipelineThread | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Cadena de macros (pipeline)</b>"))

        # Cabecera: nombre + carga/guardar
        cab = QHBoxLayout()
        self.nombre = QLineEdit(self.pipeline.nombre)
        cab.addWidget(QLabel("Nombre:"))
        cab.addWidget(self.nombre, 1)
        b_cargar = QPushButton("Cargar YAML")
        b_cargar.clicked.connect(self._load)
        cab.addWidget(b_cargar)
        b_guardar = QPushButton("Guardar YAML")
        b_guardar.clicked.connect(self._save)
        cab.addWidget(b_guardar)
        layout.addLayout(cab)

        self.descripcion = QLineEdit()
        self.descripcion.setPlaceholderText("Descripción opcional (ej. 'Rutina diaria 07:45')")
        layout.addWidget(self.descripcion)

        # Tabla de pasos
        self.tabla = QTableWidget(0, len(COLS_PASOS))
        self.tabla.setHorizontalHeaderLabels(COLS_PASOS)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla, 1)

        # Botones de manipulación
        botones = QHBoxLayout()
        for txt, slot in [
            ("Añadir paso", self._add_paso),
            ("Editar", self._edit_paso),
            ("Eliminar", self._del_paso),
            ("↑ Subir", lambda: self._move(-1)),
            ("↓ Bajar", lambda: self._move(1)),
        ]:
            b = QPushButton(txt)
            b.clicked.connect(slot)
            botones.addWidget(b)
        botones.addStretch()
        layout.addLayout(botones)

        # Ejecución
        ejec = QHBoxLayout()
        self.run_btn = QPushButton("▶ Ejecutar cadena")
        self.run_btn.setStyleSheet("background-color: #27ae60; font-weight: bold;")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("⏹ Detener")
        self.stop_btn.setStyleSheet("background-color: #c0392b; font-weight: bold;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.abort)
        ejec.addWidget(self.run_btn)
        ejec.addWidget(self.stop_btn)
        ejec.addStretch()
        layout.addLayout(ejec)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "background: #1e272e; color: #ecf0f1; font-family: Consolas, monospace; font-size: 12px;"
        )
        layout.addWidget(self.log_view, 1)

    # ---- modelo ↔ tabla ----
    def _refresh_table(self):
        self.tabla.setRowCount(0)
        for i, p in enumerate(self.pipeline.pasos):
            self.tabla.insertRow(i)
            valores = [
                str(i + 1),
                p.macro,
                str(p.veces),
                f"{p.velocidad:g}x" if p.velocidad > 0 else "sin pausas",
                f"{p.pausa_antes_s:g}",
                p.on_fail.value,
                p.condicion.value,
                p.descripcion,
            ]
            for c, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tabla.setItem(i, c, item)

    def _sync_from_form(self):
        self.pipeline.nombre = self.nombre.text().strip() or "nueva_cadena"
        self.pipeline.descripcion = self.descripcion.text().strip()

    def _sync_to_form(self):
        self.nombre.setText(self.pipeline.nombre)
        self.descripcion.setText(self.pipeline.descripcion)

    # ---- acciones de pasos ----
    def _add_paso(self):
        dlg = _PasoDialog(self.macros_dir, parent=self)
        if dlg.exec():
            self.pipeline.pasos.append(dlg.to_paso())
            self._refresh_table()

    def _edit_paso(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        dlg = _PasoDialog(self.macros_dir, paso=self.pipeline.pasos[row], parent=self)
        if dlg.exec():
            self.pipeline.pasos[row] = dlg.to_paso()
            self._refresh_table()

    def _del_paso(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        del self.pipeline.pasos[row]
        self._refresh_table()

    def _move(self, delta: int):
        row = self.tabla.currentRow()
        if row < 0:
            return
        new = row + delta
        if not 0 <= new < len(self.pipeline.pasos):
            return
        self.pipeline.pasos[row], self.pipeline.pasos[new] = self.pipeline.pasos[new], self.pipeline.pasos[row]
        self._refresh_table()
        self.tabla.selectRow(new)

    # ---- guardar/cargar ----
    def _save(self):
        self._sync_from_form()
        nombre = "".join(c if c.isalnum() or c in "-_." else "_" for c in self.pipeline.nombre)
        if not nombre.endswith((".yaml", ".yml")):
            nombre = f"{nombre}.yaml"
        path = self.pipelines_dir / nombre
        if path.exists():
            if QMessageBox.question(
                self, "Sobrescribir", f"Ya existe '{path.name}'. ¿Sobrescribir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            self.pipeline.save(path)
            QMessageBox.information(self, "Guardado", f"Cadena guardada en:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {exc}")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar cadena", str(self.pipelines_dir),
            "YAML (*.yaml *.yml)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            self.pipeline = Pipeline.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar: {exc}")
            return
        self._sync_to_form()
        self._refresh_table()

    # ---- ejecución ----
    def _start(self):
        if not self.pipeline.pasos:
            QMessageBox.warning(self, "Vacío", "La cadena no tiene pasos.")
            return
        self._sync_from_form()
        self.log_view.clear()
        self._runner = PipelineRunner(
            pipeline=self.pipeline,
            macros_dir=self.macros_dir,
            screenshots_dir=self.data_dir / "screenshots",
            data_dir=self.data_dir,
        )
        self._thread = _PipelineThread(self._runner)
        self._thread.log_line.connect(self.log_view.append)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def abort(self):
        if self._runner:
            self._runner.abort()
        self.log_view.append("⏹ Abortando…")

    def _on_finished(self, summary: PipelineSummary):
        self.log_view.append(
            f"\n=== FIN · OK total={summary.total_ok} · KO total={summary.total_ko} ==="
        )
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_error(self, msg: str):
        self.log_view.append(f"\n❌ ERROR: {msg}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
