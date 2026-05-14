from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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


class SchedulePanel(QWidget):
    """Programa, lista y elimina tareas en Windows Task Scheduler.

    Solo funcional en Windows. En el resto de plataformas el panel se
    muestra con un aviso pero no permite alta.
    """

    def __init__(self, macros_dir: Path, data_dir: Path):
        super().__init__()
        self.macros_dir = macros_dir
        self.data_dir = data_dir

        layout = QVBoxLayout(self)

        if not sys.platform.startswith("win"):
            warn = QLabel("⚠ La programación con Task Scheduler solo está disponible en Windows.")
            warn.setStyleSheet("color: #c0392b; font-weight: bold;")
            layout.addWidget(warn)

        layout.addWidget(QLabel("<b>Crear nueva tarea programada</b>"))

        fila_nombre = QHBoxLayout()
        self.tarea_nombre = QLineEdit()
        self.tarea_nombre.setPlaceholderText("Ej. descarga_it_diaria")
        fila_nombre.addWidget(QLabel("Nombre tarea:"))
        fila_nombre.addWidget(self.tarea_nombre, 1)
        layout.addLayout(fila_nombre)

        fila_macro = QHBoxLayout()
        self.macro_combo = QComboBox()
        self._refresh_macros()
        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(40)
        refresh_btn.clicked.connect(self._refresh_macros)
        fila_macro.addWidget(QLabel("Macro:"))
        fila_macro.addWidget(self.macro_combo, 1)
        fila_macro.addWidget(refresh_btn)
        layout.addLayout(fila_macro)

        fila_excel = QHBoxLayout()
        self.excel_path = QLineEdit()
        self.excel_path.setPlaceholderText("Ruta absoluta al Excel/CSV de DNIs")
        browse = QPushButton("Examinar…")
        browse.clicked.connect(self._browse)
        fila_excel.addWidget(QLabel("Excel DNIs:"))
        fila_excel.addWidget(self.excel_path, 1)
        fila_excel.addWidget(browse)
        layout.addLayout(fila_excel)

        fila_freq = QHBoxLayout()
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["Diaria", "Semanal", "Al iniciar sesión"])
        self.hora = QTimeEdit(QTime(8, 0))
        self.hora.setDisplayFormat("HH:mm")
        fila_freq.addWidget(QLabel("Frecuencia:"))
        fila_freq.addWidget(self.freq_combo)
        fila_freq.addWidget(QLabel("Hora:"))
        fila_freq.addWidget(self.hora)
        layout.addLayout(fila_freq)

        fila_dias = QHBoxLayout()
        fila_dias.addWidget(QLabel("Días (solo semanal):"))
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

        fila_extras = QHBoxLayout()
        self.no_retry = QCheckBox("--no-retry")
        self.no_notify = QCheckBox("--no-notify")
        self.all_dnis = QCheckBox("--all (ignorar checkpoint)")
        fila_extras.addWidget(QLabel("Flags:"))
        fila_extras.addWidget(self.no_retry)
        fila_extras.addWidget(self.no_notify)
        fila_extras.addWidget(self.all_dnis)
        fila_extras.addStretch()
        layout.addLayout(fila_extras)

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

        self.refresh_tareas()

    def _refresh_macros(self):
        self.macro_combo.clear()
        for p in sorted(self.macros_dir.glob("*.yaml")):
            self.macro_combo.addItem(p.stem)
        for p in sorted(self.macros_dir.glob("*.yml")):
            self.macro_combo.addItem(p.stem)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Excel/CSV", "", "Datos (*.xlsx *.xls *.csv)")
        if path:
            self.excel_path.setText(path)

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar memovipro-run.exe", "", "Ejecutables (*.exe)")
        if path:
            self.exe_path.setText(path)

    def _crear(self):
        nombre = self.tarea_nombre.text().strip()
        macro = self.macro_combo.currentText().strip()
        excel = self.excel_path.text().strip()
        if not nombre or not macro or not excel:
            QMessageBox.warning(self, "Faltan datos", "Rellena nombre, macro y Excel.")
            return

        modo = self.freq_combo.currentText()
        hora_qt = self.hora.time()
        from datetime import time as dtime
        hora = dtime(hora_qt.hour(), hora_qt.minute())

        if modo == "Diaria":
            freq = Frecuencia(diaria=True, hora=hora)
        elif modo == "Semanal":
            dias = tuple(code for cb, code in self.checks_dias if cb.isChecked())
            if not dias:
                QMessageBox.warning(self, "Días", "Selecciona al menos un día para la frecuencia semanal.")
                return
            freq = Frecuencia(semanal=True, dias_semana=dias, hora=hora)
        else:
            freq = Frecuencia(al_iniciar_sesion=True)

        extras: list[str] = []
        if self.no_retry.isChecked():
            extras.append("--no-retry")
        if self.no_notify.isChecked():
            extras.append("--no-notify")
        if self.all_dnis.isChecked():
            extras.append("--all")

        ok = crear_tarea(
            nombre=nombre,
            macro=macro,
            excel=excel,
            frecuencia=freq,
            ejecutable=self.exe_path.text().strip() or None,
            extra_args=extras,
        )
        if ok:
            QMessageBox.information(self, "Tarea creada", f"Programada: MemoviPro_{nombre}")
            self.refresh_tareas()
        else:
            QMessageBox.warning(
                self, "Error",
                "No se pudo crear la tarea. Revisa el log y confirma que tienes permisos."
                " En Windows puede que necesites ejecutar MemoviPro como Administrador.",
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
