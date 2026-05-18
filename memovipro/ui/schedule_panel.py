"""Panel de programación de tareas con Windows Task Scheduler.

Funcionalidades:
- Tres modos: Reproducir N veces / Pipeline / DNI Excel.
- Validación previa: comprueba que la macro o pipeline existen antes
  de crear la tarea, para evitar tareas "fantasma" que apuntan a algo
  que no existe.
- Auto-detecta `memovipro-run.exe` junto al GUI cuando se ejecuta como
  empaquetado (PyInstaller).
- Vista previa del comando que se programará.
- Panel "Avanzado" plegado por defecto (.exe y flags raros).
- Días de la semana solo visibles si la frecuencia es semanal.
- Flags ocultos según el modo elegido.

Sobre cada tarea existente se puede:
- ▶ Ejecutar ahora (lanza inmediatamente con schtasks /Run).
- ✏ Editar (carga la config en el formulario; al guardar reemplaza).
- 🟢 Habilitar / 🔴 Deshabilitar (sin perder la configuración).
- 📂 Abrir logs de hoy.
- ✕ Eliminar.
- Menú contextual con botón derecho con las mismas opciones.

La configuración de cada tarea se guarda paralelamente en
`data/scheduled_tasks/<nombre>.json` (Task Scheduler no almacena
nada más que el comando + frecuencia).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, time as dtime
from pathlib import Path

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core.scheduler import (
    Frecuencia,
    _auto_detect_run_exe,
    construir_accion,
    crear_tarea,
    ejecutar_ahora,
    eliminar_tarea,
    habilitar_tarea,
    listar_tareas,
    validar_args,
)
from core.scheduler_metadata import TaskMetadata


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


# Columnas de la tabla
COL_NOMBRE = 0
COL_PROXIMO = 1
COL_ULTIMA = 2
COL_RESULT = 3
COL_ESTADO = 4
COL_ACCION = 5
NUM_COLS = 6


class SchedulePanel(QWidget):
    def __init__(self, macros_dir: Path, data_dir: Path, pipelines_dir: Path | None = None):
        super().__init__()
        self.macros_dir = macros_dir
        self.data_dir = data_dir
        self.pipelines_dir = pipelines_dir or (macros_dir.parent / "pipelines")
        self.metadata = TaskMetadata(self.data_dir)

        layout = QVBoxLayout(self)

        if not sys.platform.startswith("win"):
            warn = QLabel("⚠ La programación con Task Scheduler solo está disponible en Windows.")
            warn.setStyleSheet("color: #c0392b; font-weight: bold;")
            layout.addWidget(warn)

        layout.addWidget(QLabel("<b>Crear / editar tarea programada</b>"))

        fila_modo = QHBoxLayout()
        fila_modo.addWidget(QLabel("Tipo de tarea:"))
        self.modo_combo = QComboBox()
        self.modo_combo.addItem("Reproducir macro N veces  (sin Excel)", MODO_REPLAY)
        self.modo_combo.addItem("Pipeline / cadena de macros  (sin Excel)", MODO_PIPELINE)
        self.modo_combo.addItem("Macro iterada por Excel de DNIs", MODO_DNI)
        fila_modo.addWidget(self.modo_combo, 1)
        layout.addLayout(fila_modo)

        fila_nombre = QHBoxLayout()
        fila_nombre.addWidget(QLabel("Nombre tarea:"))
        self.tarea_nombre = QLineEdit()
        self.tarea_nombre.setPlaceholderText("Ej. descarga_pa_diaria")
        fila_nombre.addWidget(self.tarea_nombre, 1)
        layout.addLayout(fila_nombre)

        fila_desc = QHBoxLayout()
        fila_desc.addWidget(QLabel("Descripción:"))
        self.descripcion = QLineEdit()
        self.descripcion.setPlaceholderText("Opcional, ej. \"Descarga PA y avisa por email\"")
        fila_desc.addWidget(self.descripcion, 1)
        layout.addLayout(fila_desc)

        # === Paneles específicos por modo ===
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
            "<i>El número de iteraciones, velocidad y política on_fail se "
            "definen dentro del YAML del pipeline.</i>"
        ))
        self.stack.addWidget(pipeline_widget)

        # --- Modo DNI ---
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
        self.hora_label = QLabel("Hora:")
        fila_freq.addWidget(self.hora_label)
        fila_freq.addWidget(self.hora)
        fila_freq.addStretch()
        layout.addLayout(fila_freq)

        # Días (solo visible cuando es semanal)
        self.fila_dias_widget = QWidget()
        fila_dias_lay = QHBoxLayout(self.fila_dias_widget)
        fila_dias_lay.setContentsMargins(0, 0, 0, 0)
        fila_dias_lay.addWidget(QLabel("Días (semanal):"))
        self.checks_dias: list[tuple[QCheckBox, str]] = []
        for etiqueta, code in DIAS:
            cb = QCheckBox(etiqueta)
            fila_dias_lay.addWidget(cb)
            self.checks_dias.append((cb, code))
        fila_dias_lay.addStretch()
        layout.addWidget(self.fila_dias_widget)

        # === Panel avanzado (plegable) ===
        self.adv_group = QGroupBox("Avanzado (.exe, flags)")
        self.adv_group.setCheckable(True)
        self.adv_group.setChecked(False)
        adv_lay = QVBoxLayout(self.adv_group)

        fila_exe = QHBoxLayout()
        self.exe_path = QLineEdit()
        auto_exe = _auto_detect_run_exe()
        if auto_exe is not None:
            self.exe_path.setText(str(auto_exe))
            self.exe_path.setPlaceholderText("Detectado automáticamente")
        else:
            self.exe_path.setPlaceholderText(
                "Ruta a memovipro-run.exe (en desarrollo se usa python cli.py)"
            )
        browse_exe = QPushButton("Examinar…")
        browse_exe.clicked.connect(self._browse_exe)
        fila_exe.addWidget(QLabel(".exe:"))
        fila_exe.addWidget(self.exe_path, 1)
        fila_exe.addWidget(browse_exe)
        adv_lay.addLayout(fila_exe)

        # Flags
        self.fila_flags_widget = QWidget()
        fila_flags_lay = QHBoxLayout(self.fila_flags_widget)
        fila_flags_lay.setContentsMargins(0, 0, 0, 0)
        self.flag_no_notify = QCheckBox("--no-notify")
        self.flag_no_retry = QCheckBox("--no-retry  (DNI)")
        self.flag_all = QCheckBox("--all  (DNI: ignora checkpoint)")
        fila_flags_lay.addWidget(QLabel("Flags:"))
        fila_flags_lay.addWidget(self.flag_no_notify)
        fila_flags_lay.addWidget(self.flag_no_retry)
        fila_flags_lay.addWidget(self.flag_all)
        fila_flags_lay.addStretch()
        adv_lay.addWidget(self.fila_flags_widget)

        layout.addWidget(self.adv_group)

        # === Preview del comando ===
        self.preview_label = QLabel(
            "<i>Completa los campos para ver el comando que se programará.</i>"
        )
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "background:#1e272e; color:#ecf0f1; padding:6px; "
            "font-family:Consolas, monospace; font-size:11px; border-radius:3px;"
        )
        layout.addWidget(self.preview_label)

        # === Botones acción ===
        fila_botones = QHBoxLayout()
        self.programar_btn = QPushButton("Programar tarea")
        self.programar_btn.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold;"
        )
        self.programar_btn.clicked.connect(self._crear)
        fila_botones.addWidget(self.programar_btn)

        self.cancelar_edit_btn = QPushButton("Cancelar edición")
        self.cancelar_edit_btn.setVisible(False)
        self.cancelar_edit_btn.clicked.connect(self._cancelar_edicion)
        fila_botones.addWidget(self.cancelar_edit_btn)
        fila_botones.addStretch()
        layout.addLayout(fila_botones)

        # === Tareas existentes ===
        layout.addWidget(QLabel("<b>Tareas MemoviPro programadas</b>"))
        self.tabla = QTableWidget(0, NUM_COLS)
        self.tabla.setHorizontalHeaderLabels(
            ["Nombre", "Próximo", "Última ejec.", "Resultado", "Estado", "Acción"]
        )
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(COL_RESULT, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(COL_ACCION, QHeaderView.ResizeMode.Interactive)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.tabla.doubleClicked.connect(self._doble_clic_tarea)
        layout.addWidget(self.tabla, 1)

        # Botones bajo la tabla
        fila_acc = QHBoxLayout()
        for txt, slot, color in [
            ("▶ Ejecutar ahora", self._ejecutar_ahora_seleccionada, "#3498db"),
            ("✏ Editar", self._editar_seleccionada, None),
            ("🟢/🔴 Habilitar/Deshabilitar", self._toggle_habilitar_seleccionada, None),
            ("📂 Logs hoy", self._abrir_logs_hoy, None),
            ("✕ Eliminar", self._eliminar_seleccionada, "#c0392b"),
            ("↻ Refrescar", self.refresh_tareas, None),
        ]:
            b = QPushButton(txt)
            if color:
                b.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")
            b.clicked.connect(slot)
            fila_acc.addWidget(b)
        fila_acc.addStretch()
        layout.addLayout(fila_acc)

        # Estado interno
        self._editando_nombre: str | None = None  # nombre que se está editando, o None

        # Conexiones para refrescar preview / visibilidad
        self.modo_combo.currentIndexChanged.connect(self._on_modo_changed)
        self.freq_combo.currentIndexChanged.connect(self._on_frecuencia_changed)
        for w in (
            self.macro_combo_replay, self.macro_combo_dni, self.pipeline_combo,
            self.exe_path,
        ):
            w.currentIndexChanged.connect(self._update_preview) if isinstance(w, QComboBox) \
                else w.textChanged.connect(self._update_preview)
        self.veces_spin.valueChanged.connect(self._update_preview)
        self.velocidad_combo.currentIndexChanged.connect(self._update_preview)
        self.excel_path.textChanged.connect(self._update_preview)
        for cb in (self.flag_no_notify, self.flag_no_retry, self.flag_all):
            cb.stateChanged.connect(self._update_preview)

        self._refresh_macros_y_pipelines()
        self.refresh_tareas()
        self._on_modo_changed()
        self._on_frecuencia_changed()
        self._update_preview()

    # ===== helpers =====
    def _refresh_macros_y_pipelines(self):
        macros = [p.stem for p in sorted(self.macros_dir.glob("*.yaml"))]
        macros += [p.stem for p in sorted(self.macros_dir.glob("*.yml"))]
        for combo in (self.macro_combo_replay, self.macro_combo_dni):
            combo.clear()
            for m in macros:
                combo.addItem(m)

        pipelines = [p.stem for p in sorted(self.pipelines_dir.glob("*.yaml"))]
        pipelines += [p.stem for p in sorted(self.pipelines_dir.glob("*.yml"))]
        self.pipeline_combo.clear()
        for p in pipelines:
            self.pipeline_combo.addItem(p)

    def _on_modo_changed(self):
        idx = self.modo_combo.currentIndex()
        self.stack.setCurrentIndex(idx)
        modo = self.modo_combo.currentData()
        # Flags relevantes según modo
        self.flag_no_retry.setVisible(modo == MODO_DNI)
        self.flag_all.setVisible(modo == MODO_DNI)
        self._update_preview()

    def _on_frecuencia_changed(self):
        modo = self.freq_combo.currentText()
        self.hora_label.setVisible(modo != "Al iniciar sesión")
        self.hora.setVisible(modo != "Al iniciar sesión")
        self.fila_dias_widget.setVisible(modo == "Semanal")
        self._update_preview()

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

    # ===== Construir args CLI =====
    def _args(self, silent: bool = True) -> list[str] | None:
        """Construye la lista de args CLI según el modo elegido.

        Si `silent`, no muestra diálogos cuando faltan campos (se usa
        para la previsualización en vivo).
        """
        modo = self.modo_combo.currentData()
        if modo == MODO_REPLAY:
            macro = self.macro_combo_replay.currentText().strip()
            if not macro:
                if not silent:
                    QMessageBox.warning(self, "Falta macro", "Selecciona una macro.")
                return None
            veces = self.veces_spin.value()
            velocidad = VELOCIDADES[self.velocidad_combo.currentIndex()][1]
            args = ["--quiet", "--replay", macro, "--veces", str(veces), "--velocidad", str(velocidad)]
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            return args
        if modo == MODO_PIPELINE:
            pipeline = self.pipeline_combo.currentText().strip()
            if not pipeline:
                if not silent:
                    QMessageBox.warning(self, "Falta pipeline", "Crea primero un pipeline en la pestaña Cadenas.")
                return None
            args = ["--quiet", "--pipeline", pipeline]
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            return args
        if modo == MODO_DNI:
            macro = self.macro_combo_dni.currentText().strip()
            excel = self.excel_path.text().strip()
            if not macro or not excel:
                if not silent:
                    QMessageBox.warning(self, "Faltan datos", "En modo DNI hay que indicar macro y Excel.")
                return None
            args = ["--quiet", "--macro", macro, "--excel", excel]
            if self.flag_no_retry.isChecked():
                args.append("--no-retry")
            if self.flag_no_notify.isChecked():
                args.append("--no-notify")
            if self.flag_all.isChecked():
                args.append("--all")
            return args
        return None

    def _update_preview(self):
        args = self._args(silent=True)
        if args is None:
            self.preview_label.setText(
                "<i style='color:#e67e22'>Faltan campos por rellenar.</i>"
            )
            return
        try:
            programa, cmdline = construir_accion(args, self.exe_path.text().strip() or None)
        except (FileNotFoundError, RuntimeError) as exc:
            self.preview_label.setText(f"<span style='color:#e74c3c'>⚠ {exc}</span>")
            return
        self.preview_label.setText(
            f"<b>Programa:</b> {programa}<br><b>Args:</b> {cmdline}"
        )

    # ===== Construir Frecuencia =====
    def _frecuencia_actual(self) -> Frecuencia | None:
        modo_txt = self.freq_combo.currentText()
        hora_qt = self.hora.time()
        hora = dtime(hora_qt.hour(), hora_qt.minute())
        if modo_txt == "Diaria":
            return Frecuencia(diaria=True, hora=hora)
        if modo_txt == "Semanal":
            dias = tuple(code for cb, code in self.checks_dias if cb.isChecked())
            if not dias:
                QMessageBox.warning(self, "Días", "Selecciona al menos un día para 'Semanal'.")
                return None
            return Frecuencia(semanal=True, dias_semana=dias, hora=hora)
        return Frecuencia(al_iniciar_sesion=True)

    # ===== Crear tarea =====
    def _crear(self):
        nombre = self.tarea_nombre.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Sin nombre", "Pon un nombre a la tarea.")
            return

        args = self._args(silent=False)
        if args is None:
            return

        # Validación previa: macro/pipeline/Excel referenciados deben existir.
        errores = validar_args(args, self.macros_dir, self.pipelines_dir)
        if errores:
            QMessageBox.warning(
                self, "Referencias rotas",
                "No puedo crear la tarea porque:\n\n• " + "\n• ".join(errores),
            )
            return

        freq = self._frecuencia_actual()
        if freq is None:
            return

        try:
            programa, cmdline = construir_accion(args, self.exe_path.text().strip() or None)
        except (FileNotFoundError, RuntimeError) as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return

        ok = crear_tarea(
            nombre=nombre,
            args=args,
            frecuencia=freq,
            ejecutable=self.exe_path.text().strip() or None,
        )
        if not ok:
            QMessageBox.warning(
                self, "Error",
                "No se pudo crear la tarea. Revisa el log y comprueba permisos.",
            )
            return

        # Guardar metadata para poder editar después.
        self.metadata.save(nombre, self._snapshot_form())

        QMessageBox.information(
            self, "Tarea creada",
            f"Programada: MemoviPro_{nombre}\n\nPrograma: {programa}\nArgs: {cmdline}",
        )
        self._cancelar_edicion()
        self.refresh_tareas()

    # ===== Editar tarea existente =====
    def _editar_seleccionada(self):
        nombre = self._nombre_seleccionado()
        if not nombre:
            return
        meta = self.metadata.load(nombre)
        if meta is None:
            QMessageBox.warning(
                self, "Sin datos para editar",
                "Esta tarea no tiene metadatos guardados por MemoviPro. "
                "Probablemente se creó antes de añadir esta funcionalidad. "
                "Bórrala y créala de nuevo.",
            )
            return

        # Cargar campos
        self.tarea_nombre.setText(nombre)
        self.tarea_nombre.setEnabled(False)  # no permitimos cambiar el nombre al editar
        self.descripcion.setText(meta.get("descripcion", ""))

        modo = meta.get("modo", MODO_REPLAY)
        idx_modo = max(0, self.modo_combo.findData(modo))
        self.modo_combo.setCurrentIndex(idx_modo)

        if modo == MODO_REPLAY:
            i = self.macro_combo_replay.findText(meta.get("macro", ""))
            if i >= 0:
                self.macro_combo_replay.setCurrentIndex(i)
            self.veces_spin.setValue(int(meta.get("veces", 1)))
            vel = float(meta.get("velocidad", 1.0))
            for j, (_, v) in enumerate(VELOCIDADES):
                if abs(v - vel) < 1e-6:
                    self.velocidad_combo.setCurrentIndex(j)
                    break
        elif modo == MODO_PIPELINE:
            i = self.pipeline_combo.findText(meta.get("pipeline", ""))
            if i >= 0:
                self.pipeline_combo.setCurrentIndex(i)
        elif modo == MODO_DNI:
            i = self.macro_combo_dni.findText(meta.get("macro", ""))
            if i >= 0:
                self.macro_combo_dni.setCurrentIndex(i)
            self.excel_path.setText(meta.get("excel", ""))

        # Frecuencia
        freq_txt = meta.get("frecuencia", "Diaria")
        j = self.freq_combo.findText(freq_txt)
        if j >= 0:
            self.freq_combo.setCurrentIndex(j)
        hora_str = meta.get("hora", "08:00")
        try:
            h, m = hora_str.split(":")
            self.hora.setTime(QTime(int(h), int(m)))
        except Exception:
            pass
        dias = set(meta.get("dias", []))
        for cb, code in self.checks_dias:
            cb.setChecked(code in dias)

        # Flags
        self.flag_no_notify.setChecked(bool(meta.get("no_notify", False)))
        self.flag_no_retry.setChecked(bool(meta.get("no_retry", False)))
        self.flag_all.setChecked(bool(meta.get("all", False)))

        # Avanzado
        if meta.get("ejecutable"):
            self.exe_path.setText(meta["ejecutable"])

        # Modo edición visual
        self._editando_nombre = nombre
        self.programar_btn.setText(f"💾 Guardar cambios en '{nombre}'")
        self.cancelar_edit_btn.setVisible(True)

    def _cancelar_edicion(self):
        self._editando_nombre = None
        self.tarea_nombre.clear()
        self.tarea_nombre.setEnabled(True)
        self.descripcion.clear()
        self.programar_btn.setText("Programar tarea")
        self.cancelar_edit_btn.setVisible(False)

    def _snapshot_form(self) -> dict:
        """Captura el estado actual del formulario para guardarlo como metadata."""
        modo = self.modo_combo.currentData()
        hora_qt = self.hora.time()
        d = {
            "modo": modo,
            "descripcion": self.descripcion.text().strip(),
            "frecuencia": self.freq_combo.currentText(),
            "hora": f"{hora_qt.hour():02d}:{hora_qt.minute():02d}",
            "dias": [code for cb, code in self.checks_dias if cb.isChecked()],
            "no_notify": self.flag_no_notify.isChecked(),
            "no_retry": self.flag_no_retry.isChecked(),
            "all": self.flag_all.isChecked(),
            "ejecutable": self.exe_path.text().strip() or None,
        }
        if modo == MODO_REPLAY:
            d["macro"] = self.macro_combo_replay.currentText().strip()
            d["veces"] = self.veces_spin.value()
            d["velocidad"] = VELOCIDADES[self.velocidad_combo.currentIndex()][1]
        elif modo == MODO_PIPELINE:
            d["pipeline"] = self.pipeline_combo.currentText().strip()
        elif modo == MODO_DNI:
            d["macro"] = self.macro_combo_dni.currentText().strip()
            d["excel"] = self.excel_path.text().strip()
        return d

    # ===== Acciones sobre tareas existentes =====
    def _nombre_seleccionado(self) -> str | None:
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecciona una tarea", "Pincha en una fila primero.")
            return None
        item = self.tabla.item(row, COL_NOMBRE)
        return item.text() if item else None

    def _ejecutar_ahora_seleccionada(self):
        nombre = self._nombre_seleccionado()
        if not nombre:
            return
        ok, msg = ejecutar_ahora(nombre)
        if ok:
            QMessageBox.information(self, "Tarea lanzada", msg + "\n\nRevisa los logs para ver el resultado.")
        else:
            QMessageBox.warning(self, "No se pudo ejecutar", msg)
        self.refresh_tareas()

    def _toggle_habilitar_seleccionada(self):
        nombre = self._nombre_seleccionado()
        if not nombre:
            return
        # No sabemos el estado actual sin parsearlo; preguntamos.
        resp = QMessageBox.question(
            self, "Habilitar / Deshabilitar",
            f"¿Qué quieres hacer con '{nombre}'?\n\n"
            "Sí = Habilitar  ·  No = Deshabilitar",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if resp == QMessageBox.StandardButton.Cancel:
            return
        habilitar = resp == QMessageBox.StandardButton.Yes
        if habilitar_tarea(nombre, habilitar):
            self.refresh_tareas()
        else:
            QMessageBox.warning(self, "Error", "No se pudo cambiar el estado.")

    def _eliminar_seleccionada(self):
        nombre = self._nombre_seleccionado()
        if not nombre:
            return
        if QMessageBox.question(self, "Confirmar", f"¿Eliminar la tarea '{nombre}'?") != QMessageBox.StandardButton.Yes:
            return
        if eliminar_tarea(nombre):
            self.metadata.delete(nombre)
            self.refresh_tareas()
        else:
            QMessageBox.warning(self, "Error", "No se pudo eliminar la tarea.")

    def _abrir_logs_hoy(self):
        nombre = self._nombre_seleccionado()
        # nombre no es estrictamente necesario, pero lo mostramos como contexto.
        logs_dir = self.data_dir.parent / "logs"
        if not logs_dir.exists():
            QMessageBox.information(self, "Sin logs", "Aún no se han generado logs.")
            return
        archivos = sorted(logs_dir.glob("run_*.log"), reverse=True)
        if not archivos:
            QMessageBox.information(self, "Sin logs", f"No hay archivos run_*.log en {logs_dir}.")
            return
        path = str(archivos[0].resolve())
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo abrir: {exc}")

    def _doble_clic_tarea(self):
        self._ejecutar_ahora_seleccionada()

    def _menu_contextual(self, point):
        if self.tabla.rowCount() == 0:
            return
        menu = QMenu(self)
        a_run = QAction("▶  Ejecutar ahora", self)
        a_run.triggered.connect(self._ejecutar_ahora_seleccionada)
        menu.addAction(a_run)
        a_edit = QAction("✏  Editar", self)
        a_edit.triggered.connect(self._editar_seleccionada)
        menu.addAction(a_edit)
        a_toggle = QAction("🟢/🔴  Habilitar/Deshabilitar", self)
        a_toggle.triggered.connect(self._toggle_habilitar_seleccionada)
        menu.addAction(a_toggle)
        a_logs = QAction("📂  Abrir log de hoy", self)
        a_logs.triggered.connect(self._abrir_logs_hoy)
        menu.addAction(a_logs)
        menu.addSeparator()
        a_del = QAction("✕  Eliminar", self)
        a_del.triggered.connect(self._eliminar_seleccionada)
        menu.addAction(a_del)
        menu.exec(self.tabla.viewport().mapToGlobal(point))

    # ===== Refrescar tabla =====
    def refresh_tareas(self):
        self.tabla.setRowCount(0)
        for t in listar_tareas():
            r = self.tabla.rowCount()
            self.tabla.insertRow(r)
            # Resultado coloreado
            res_text = t.ultimo_resultado or "—"
            res_item = QTableWidgetItem(res_text)
            ok = t.ok_ultima_ejecucion
            if ok is True:
                res_item.setForeground(QColor("#1e8449"))
                res_item.setText("✓ 0  (OK)")
            elif ok is False:
                res_item.setForeground(QColor("#c0392b"))
                res_item.setText(f"✗ {res_text}")
            self.tabla.setItem(r, COL_NOMBRE, QTableWidgetItem(t.nombre))
            self.tabla.setItem(r, COL_PROXIMO, QTableWidgetItem(t.proximo))
            self.tabla.setItem(r, COL_ULTIMA, QTableWidgetItem(t.ultima_ejecucion or "—"))
            self.tabla.setItem(r, COL_RESULT, res_item)
            self.tabla.setItem(r, COL_ESTADO, QTableWidgetItem(t.estado))
            self.tabla.setItem(r, COL_ACCION, QTableWidgetItem(t.accion))
