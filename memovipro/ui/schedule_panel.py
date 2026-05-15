"""Panel de programación de tareas con Windows Task Scheduler.

Soporta tres modos de tarea:
  1. Reproducir N veces (replay) — el caso más común: macro → N veces.
     No requiere Excel.
  2. Pipeline (cadena) — ejecuta una cadena completa por nombre.
     No requiere Excel, los detalles van en el YAML del pipeline.
  3. Por DNI desde Excel — iterar una macro sobre una lista de DNIs.

El usuario selecciona el modo arriba y la UI muestra solo los campos
relevantes. Internamente se construye la línea CLI adecuada para el
.exe (`memovipro-run.exe --replay ...`, `--pipeline ...` o
`--macro ... --excel ...`).
"""
from __future__ import annotations

import sys
from datetime import time as dtime
from pathlib import Path

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core.scheduler import (
    Frecuencia,
    crear_tarea,
    eliminar_tarea,
    listar_tareas,
)


DIAS = [("LUN", "MON"), ("MAR", "TUE"), ("MIE", "WED"), ("JUE", "THU"),
        ("VIE", "FRI"), ("SAB", "SAT"), ("DOM", "SUN")]


MODO_REPLAY = "replay"
MODO_PIPELINE = "pipeline"
MODO_DNI = "dni"


VELOCIDADES = [
    ("0.5x  (mitad)", 0.5),
    ("1x  (original)", 1.0),
    ("1.5x", 1.5),
    ("2x", 2.0),
    ("Máxima (sin pausas)", 0.0),
]


class SchedulePanel(QWidget):
    def __init__(self, macros_dir: Path, data_dir: Path, pipelines_dir: Path | None = None):
        super().__init__()
        self.macros_dir = macros_dir
        self.data_dir = data_dir
        self.pipelines_dir = pipelines_dir or (macros_dir.parent / "pipelines")

        layout = QVBoxLayout(self)

        if not sys.platform.startswith("win"):
            warn = QLabel("⚠ La programación con Task Scheduler solo está disponible en Windows.")
            warn.setStyleSheet("color: #c0392b; font-weight: bold;")
            layout.addWidget(warn)

        layout.addWidget(QLabel("<b>Crear tarea programada</b>"))

        fila_modo = QHBoxLayout()
        fila_modo.addWidget(QLabel("Tipo de tarea:"))
        self.modo_combo = QComboBox()
        self.modo_combo.addItem("Reproducir macro N veces  (sin Excel)", MODO_REPLAY)
        self.modo_combo.addItem("Pipeline / cadena de macros  (sin Excel)", MODO_PIPELINE)
        self.modo_combo.addItem("Macro iterada por Excel de DNIs", MODO_DNI)
        self.modo_combo.currentIndexChanged.connect(self._on_modo_changed)
        fila_modo.addWidget(self.modo_combo, 1)
        layout.addLayout(fila_modo)

        fila_nombre = QHBoxLayout()
        fila_nombre.addWidget(QLabel("Nombre tarea:"))
        self.tarea_nombre = QLineEdit()
        self.tarea_nombre.setPlaceholderText("Ej. descarga_pa_diaria")
        fila_nombre.addWidget(self.tarea_nombre, 1)
        layout.addLayout(fila_nombre)

        # === Paneles específicos por modo (uno visible a la vez) ===
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # --- Modo Replay ---
        replay_widget = QWidget()
        replay_lay = QVBoxLayout(replay_widget)
        replay_lay.setContentsMargins(0, 0, 0, 0)
        fila_r1 = QHBoxLayout()
        fila_r1.addWidget(QLabel("Macro:"))
        self.macro_combo_replay = QComboBox()
        fila_r1.addWidget(self.macro_combo_replay, 1)
        replay_lay.addLayout(fila_r1)
        fila_r2 = QHBoxLayout()
        fila_r2.addWidget(QLabel("Veces:"))
        self.veces_spin = QSpinBox()
        self.veces_spin.setRange(1, 9999)
        self.veces_spin.setValue(1)
        self.veces_spin.setMaximumWidth(110)
        fila_r2.addWidget(self.veces_spin)
        fila_r2.addSpacing(15)
        fila_r2.addWidget(QLabel("Velocidad:"))
        self.velocidad_combo = QComboBox()
        for label, _ in VELOCIDADES:
            self.velocidad_combo.addItem(label)
        self.velocidad_combo.setCurrentIndex(1)
        fila_r2.addWidget(self.velocidad_combo, 1)
        replay_lay.addLayout(fila_r2)
        self.stack.addWidget(replay_widget)

        # --- Modo Pipeline ---
        pipeline_widget = QWidget()
        pipeline_lay = QVBoxLayout(pipeline_widget)
        pipeline_lay.setContentsMargins(0, 0, 0, 0)
        fila_p = QHBoxLayout()
        fila_p.addWidget(QLabel("Pipeline:"))
        self.pipeline_combo = QComboBox()
        fila_p.addWidget(self.pipeline_combo, 1)
        pipeline_lay.addLayout(fila_p)
        pipeline_lay.addWidget(QLabel(
            "<i>El número de iteraciones, la velocidad y la política on_fail "
            "se definen dentro del YAML del pipeline.</i>"
        ))
        self.stack.addWidget(pipeline_widget)

        # --- Modo DNI por Excel ---
        dni_widget = QWidget()
        dni_lay = QVBoxLayout(dni_widget)
        dni_lay.setContentsMargins(0, 0, 0, 0)
        fila_d1 = QHBoxLayout()
        fila_d1.addWidget(QLabel("Macro:"))
        self.macro_combo_dni = QComboBox()
        fila_d1.addWidget(self.macro_combo_dni, 1)
        dni_lay.addLayout(fila_d1)
        fila_d2 = QHBoxLayout()
        fila_d2.addWidget(QLabel("Excel DNIs:"))
        self.excel_path = QLineEdit()
        self.excel_path.setPlaceholderText("Ruta absoluta al Excel/CSV con columna DNI")
        fila_d2.addWidget(self.excel_path, 1)
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse_excel)
        fila_d2.addWidget(browse)
        dni_lay.addLayout(fila_d2)
        self.stack.addWidget(dni_widget)

        # === Frecuencia / hora / días ===
        fila_freq = QHBoxLayout()
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["Diaria", "Semanal", "Al iniciar sesión"])
        self.hora = QTimeEdit(QTime(8, 0))
        self.hora.setDisplayFormat("HH:mm")
        fila_freq.addWidget(QLabel("Frecuencia:"))
        fila_freq.addWidget(self.freq_combo)
        fila_freq.addWidget(QLabel("Hora:"))
        fila_freq.addWidget(self.hora)
        fila_freq.addStretch()
        layout.addLayout(fila_freq)

        fila_dias = QHBoxLayout()
        fila_dias.addWidget(QLabel("Días (semanal):"))
        self.checks_dias: list[tuple[QCheckBox, str]] = []
        for etiqueta, code in DIAS:
            cb = QCheckBox(etiqueta)
            fila_dias.addWidget(cb)
            self.checks_dias.append((cb, code))
        fila_dias.addStretch()
        layout.addLayout(fila_dias)

        fila_exe = QHBoxLayout()
        self.exe_path = QLineEdit()
        self.exe_path.setPlaceholderText("Opcional: ruta a memovipro-run.exe (si vacío, usa python cli.py)")
        browse_exe = QPushButton("Examinar…")
        browse_exe.clicked.connect(self._browse_exe)
        fila_exe.addWidget(QLabel(".exe:"))
        fila_exe.addWidget(self.exe_path, 1)
        fila_exe.addWidget(browse_exe)
        layout.addLayout(fila_exe)

        fila_flags = QHBoxLayout()
        self.flag_no_notify = QCheckBox("--no-notify")
        self.flag_no_retry = QCheckBox("--no-retry  (solo modo DNI)")
        self.flag_all = QCheckBox("--all  (solo modo DNI: ignora checkpoint)")
        fila_flags.addWidget(QLabel("Flags:"))
        fila_flags.addWidget(self.flag_no_notify)
        fila_flags.addWidget(self.flag_no_retry)
        fila_flags.addWidget(self.flag_all)
        fila_flags.addStretch()
        layout.addLayout(fila_flags)

        crear = QPushButton("Programar tarea")
        crear.clicked.connect(self._crear)
        layout.addWidget(crear)

        layout.addWidget(QLabel("<b>Tareas MemoviPro programadas</b>"))
        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "Próximo", "Estado", "Acción"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla, 1)

        fila_btns = QHBoxLayout()
        refresh_tareas = QPushButton("↻ Refrescar")
        refresh_tareas.clicked.connect(self.refresh_tareas)
        eliminar = QPushButton("Eliminar seleccionada")
        eliminar.clicked.connect(self._eliminar)
        fila_btns.addWidget(refresh_tareas)
        fila_btns.addWidget(eliminar)
        fila_btns.addStretch()
        layout.addLayout(fila_btns)

        self._refresh_macros_y_pipelines()
        self.refresh_tareas()
        self._on_modo_changed()

    # ---- helpers ----
    def _refresh_macros_y_pipelines(self):
        macros = [p.stem for p in sorted(self.macros_dir.glob("*.yaml"))]
        macros += [p.stem for p in sorted(self.macros_dir.glob("*.yml"))]
        self.macro_combo_replay.clear()
        self.macro_combo_dni.clear()
        for m in macros:
            self.macro_combo_replay.addItem(m)
            self.macro_combo_dni.addItem(m)

        pipelines = [p.stem for p in sorted(self.pipelines_dir.glob("*.yaml"))]
        pipelines += [p.stem for p in sorted(self.pipelines_dir.glob("*.yml"))]
        self.pipeline_combo.clear()
        for p in pipelines:
            self.pipeline_combo.addItem(p)

    def _on_modo_changed(self):
        idx = self.modo_combo.currentIndex()
        self.stack.setCurrentIndex(idx)
        modo = self.modo_combo.currentData()
        # Habilitar/deshabilitar flags según relevancia
        self.flag_no_retry.setEnabled(modo == MODO_DNI)
        self.flag_all.setEnabled(modo == MODO_DNI)

    def _browse_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Excel/CSV", "",
            "Datos (*.xlsx *.xls *.csv)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.excel_path.setText(path)

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar memovipro-run.exe", "",
            "Ejecutables (*.exe)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.exe_path.setText(path)

    # ---- construir args CLI según el modo elegido ----
    def _args_para_modo_actual(self) -> list[str] | None:
        modo = self.modo_combo.currentData()
        if modo == MODO_REPLAY:
            macro = self.macro_combo_replay.currentText().strip()
            if not macro:
                QMessageBox.warning(self, "Falta macro", "Selecciona una macro.")
                return None
            veces = self.veces_spin.value()
            velocidad = VELOCIDADES[self.velocidad_combo.currentIndex()][1]
            args = ["--replay", macro, "--veces", str(veces), "--velocidad", str(velocidad)]
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            return args
        if modo == MODO_PIPELINE:
            pipeline = self.pipeline_combo.currentText().strip()
            if not pipeline:
                QMessageBox.warning(self, "Falta pipeline", "Crea primero un pipeline en la pestaña Cadenas.")
                return None
            args = ["--pipeline", pipeline]
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            return args
        if modo == MODO_DNI:
            macro = self.macro_combo_dni.currentText().strip()
            excel = self.excel_path.text().strip()
            if not macro or not excel:
                QMessageBox.warning(self, "Faltan datos", "En modo DNI hay que indicar macro y Excel.")
                return None
            args = ["--macro", macro, "--excel", excel]
            if self.flag_no_retry.isChecked():
                args.append("--no-retry")
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            if self.flag_all.isChecked():
                args.append("--all")
            return args
        return None

    def _crear(self):
        nombre = self.tarea_nombre.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Sin nombre", "Pon un nombre a la tarea.")
            return

        args = self._args_para_modo_actual()
        if args is None:
            return

        modo_txt = self.freq_combo.currentText()
        hora_qt = self.hora.time()
        hora = dtime(hora_qt.hour(), hora_qt.minute())

        if modo_txt == "Diaria":
            freq = Frecuencia(diaria=True, hora=hora)
        elif modo_txt == "Semanal":
            dias = tuple(code for cb, code in self.checks_dias if cb.isChecked())
            if not dias:
                QMessageBox.warning(self, "Días", "Selecciona al menos un día.")
                return
            freq = Frecuencia(semanal=True, dias_semana=dias, hora=hora)
        else:
            freq = Frecuencia(al_iniciar_sesion=True)

        ok = crear_tarea(
            nombre=nombre,
            args=args,
            frecuencia=freq,
            ejecutable=self.exe_path.text().strip() or None,
        )
        if ok:
            QMessageBox.information(
                self, "Tarea creada",
                f"Programada: MemoviPro_{nombre}\n\nComando:\n{' '.join(args)}",
            )
            self.refresh_tareas()
        else:
            QMessageBox.warning(
                self, "Error",
                "No se pudo crear la tarea. Revisa el log y confirma que tienes permisos.",
            )

    def _eliminar(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        nombre = self.tabla.item(row, 0).text()
        if QMessageBox.question(self, "Confirmar", f"¿Eliminar la tarea {nombre}?") != QMessageBox.StandardButton.Yes:
            return
        if eliminar_tarea(nombre):
            self.refresh_tareas()
        else:
            QMessageBox.warning(self, "Error", "No se pudo eliminar la tarea.")

    def refresh_tareas(self):
        self.tabla.setRowCount(0)
        for t in listar_tareas():
            r = self.tabla.rowCount()
            self.tabla.insertRow(r)
            for col, val in enumerate([t.nombre, t.proximo, t.estado, t.accion]):
                self.tabla.setItem(r, col, QTableWidgetItem(val))
