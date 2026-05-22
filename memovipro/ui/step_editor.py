from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.step_model import Macro, SalidaConfig, Selector, Step, StepType

from .inspector import CapturaSelector, Inspector
from .record_dialog import RecordDialog


COLS = ["#", "Tipo", "Selector", "Valor / Título", "Espera (s)", "Timeout (s)", "Opc.", "Descripción"]


class StepEditor(QWidget):
    def __init__(self, macros_dir: Path):
        super().__init__()
        self.macros_dir = macros_dir
        self.macro: Macro = Macro(nombre="nueva_macro")

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.nombre = QLineEdit(self.macro.nombre)
        self.ventana = QLineEdit()
        self.ventana.setPlaceholderText("Título de la ventana principal (regex parcial)")
        top.addWidget(QLabel("Nombre:"))
        top.addWidget(self.nombre)
        top.addWidget(QLabel("Ventana:"))
        top.addWidget(self.ventana, 1)
        layout.addLayout(top)

        salida = QHBoxLayout()
        self.carpeta_descargas = QLineEdit()
        self.carpeta_descargas.setPlaceholderText("C:/Descargas/IT")
        self.patron_renombrado = QLineEdit()
        self.patron_renombrado.setPlaceholderText("IT_{DNI}_{YYYYMMDD}.xlsx")
        salida.addWidget(QLabel("Carpeta descargas:"))
        salida.addWidget(self.carpeta_descargas, 1)
        salida.addWidget(QLabel("Patrón nombre:"))
        salida.addWidget(self.patron_renombrado, 1)
        layout.addLayout(salida)

        self.tabla = QTableWidget(0, len(COLS))
        self.tabla.setHorizontalHeaderLabels(COLS)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla, 1)

        botones = QHBoxLayout()
        botones_def = [
            ("🔴 Grabar", self._launch_recorder, "#c0392b"),
            ("Añadir paso", self._add_step, None),
            ("Editar valor", self._edit_value, None),
            ("Eliminar", self._remove_step, None),
            ("Subir", lambda: self._move(-1), None),
            ("Bajar", lambda: self._move(1), None),
            ("Inspector", self._launch_inspector, None),
            ("⚡ Plantilla arranque", self._insertar_plantilla_arranque, "#8e44ad"),
            ("🐞 Paso a paso", self._launch_step_through, "#16a085"),
            ("Cargar YAML", self._load, None),
            ("Guardar YAML", self._save, None),
        ]
        for txt, slot, color in botones_def:
            b = QPushButton(txt)
            if color:
                b.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")
            b.clicked.connect(slot)
            botones.addWidget(b)
        layout.addLayout(botones)

        self._inspector = Inspector()
        self._inspector.captured.connect(self._on_inspect_captured)
        self._inspector.error.connect(self._on_inspect_error)

    def _refresh_table(self):
        self.tabla.setRowCount(0)
        for i, paso in enumerate(self.macro.pasos):
            self.tabla.insertRow(i)
            sel_txt = ""
            if paso.selector and not paso.selector.is_empty():
                sel_txt = paso.selector.name or paso.selector.auto_id or paso.selector.class_name or ""
                if paso.selector.control_type:
                    sel_txt = f"[{paso.selector.control_type}] {sel_txt}"
            valor = paso.valor or paso.titulo or ""
            espera = f"{paso.delay_before_s:.2f}" if paso.delay_before_s > 0 else ""
            valores = [
                str(i + 1),
                paso.tipo.value,
                sel_txt,
                valor,
                espera,
                f"{paso.timeout_s:g}",
                "✓" if paso.opcional else "",
                paso.descripcion,
            ]
            for col, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tabla.setItem(i, col, item)

    def _sync_from_form(self):
        self.macro.nombre = self.nombre.text().strip() or "nueva_macro"
        self.macro.ventana_principal = self.ventana.text().strip()
        self.macro.salida = SalidaConfig(
            carpeta_descargas=self.carpeta_descargas.text().strip(),
            patron_renombrado=self.patron_renombrado.text().strip(),
        )

    def _sync_to_form(self):
        self.nombre.setText(self.macro.nombre)
        self.ventana.setText(self.macro.ventana_principal)
        self.carpeta_descargas.setText(self.macro.salida.carpeta_descargas)
        self.patron_renombrado.setText(self.macro.salida.patron_renombrado)

    def _add_step(self):
        tipos = [t.value for t in StepType]
        tipo, ok = QInputDialog.getItem(self, "Tipo de paso", "Selecciona:", tipos, 0, False)
        if not ok:
            return
        self.macro.pasos.append(Step(tipo=StepType(tipo), descripcion=f"Nuevo {tipo}"))
        self._refresh_table()

    def _edit_value(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        paso = self.macro.pasos[row]
        text, ok = QInputDialog.getText(self, "Editar valor", "Valor / título:", text=paso.valor or paso.titulo or "")
        if not ok:
            return
        if paso.tipo in (StepType.FOCUS_WINDOW, StepType.WAIT_FOR_WINDOW, StepType.CLOSE_WINDOW):
            paso.titulo = text
        else:
            paso.valor = text
        self._refresh_table()

    def _remove_step(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        del self.macro.pasos[row]
        self._refresh_table()

    def _move(self, delta: int):
        row = self.tabla.currentRow()
        if row < 0:
            return
        new = row + delta
        if not 0 <= new < len(self.macro.pasos):
            return
        self.macro.pasos[row], self.macro.pasos[new] = self.macro.pasos[new], self.macro.pasos[row]
        self._refresh_table()
        self.tabla.selectRow(new)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar macro",
            str(self.macros_dir),
            "YAML (*.yaml *.yml)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            self.macro = Macro.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar: {exc}")
            return
        self._sync_to_form()
        self._refresh_table()

    def _save(self):
        """Guarda la macro a `macros/<nombre>.yaml` sin abrir diálogo de archivo.

        Evitamos QFileDialog porque el diálogo nativo de Windows usa shell
        COM y se cuelga con cierta frecuencia en apps empaquetadas con
        PyInstaller. La carpeta y el nombre vienen del propio editor.
        """
        self._sync_from_form()
        nombre = (self.macro.nombre or "").strip() or "macro_sin_nombre"
        # Sanitizar nombre para que sea un fichero válido.
        nombre = "".join(c if c.isalnum() or c in "-_." else "_" for c in nombre)
        if not nombre.endswith((".yaml", ".yml")):
            nombre = f"{nombre}.yaml"
        self.macros_dir.mkdir(parents=True, exist_ok=True)
        path = self.macros_dir / nombre

        if path.exists():
            resp = QMessageBox.question(
                self,
                "Sobrescribir",
                f"Ya existe '{path.name}' en la carpeta macros.\n¿Sobrescribir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        try:
            self.macro.save(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {exc}")
            return
        QMessageBox.information(self, "Guardado", f"Macro guardada en:\n{path}")

    def _launch_recorder(self):
        from PyQt6.QtWidgets import QDialog
        dlg = RecordDialog(self)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted and dlg.macro is not None and dlg.macro.pasos:
            self._on_macro_recorded(dlg.macro)
        elif result == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Grabación", "No se capturó ningún paso.")

    def _launch_step_through(self):
        """Lanza el depurador paso a paso (step-through) sobre la macro.

        Abre un panel flotante con la info del paso actual y botones
        ▶ Siguiente / 🔴 Grabar aquí / ⏹. Minimiza MemoviPro mientras
        dura. Si el usuario inserta pasos nuevos con "Grabar aquí",
        se añaden a la macro en posición idx+1 y la tabla se refresca.
        """
        self._sync_from_form()
        if not self.macro.pasos:
            QMessageBox.warning(self, "Macro vacía", "Añade o graba pasos antes de usar paso a paso.")
            return
        # Resolver dirs de runtime relativos a la app
        from pathlib import Path
        root_app = Path(__file__).resolve().parents[1]
        data_dir = root_app / "data"
        screenshots_dir = data_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        from .step_through_panel import StepThroughPanel
        self._step_panel = StepThroughPanel(
            macro=self.macro,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
            on_macro_modified=self._refresh_table,
            parent=self,
        )
        self._step_panel.finished.connect(self._on_step_through_finished)

        # Minimizar MemoviPro para no estorbar a la app que se depura
        main_win = self.window()
        self._main_was_visible = main_win is not None and main_win.isVisible()
        if main_win is not None:
            try:
                main_win.showMinimized()
            except Exception:
                pass

        self._step_panel.start()

    def _on_step_through_finished(self):
        # Restaurar MemoviPro y refrescar tabla por si se insertaron pasos.
        main_win = self.window()
        if main_win is not None and getattr(self, "_main_was_visible", True):
            try:
                main_win.showNormal()
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass
        self._refresh_table()

    def _insertar_plantilla_arranque(self):
        """Inserta al PRINCIPIO de la macro la secuencia de arranque limpio.

        Abre un diálogo rico (`PlantillaArranqueDialog`) que detecta las
        ventanas abiertas, deja al usuario probar el patrón, y
        opcionalmente especificar la ruta del .exe para lanzar la app
        si no estuviera abierta.

        Pasos generados:
            [opcional] LAUNCH_PROGRAM <exe> + sleep 2s
            SEND_KEYS {VK_LWIN down}d{VK_LWIN up}   (Win+D)
            SLEEP 1s
            WINDOW_ENSURE <título> state=maximized timeout=10s
        """
        from PyQt6.QtWidgets import QDialog
        from .plantilla_arranque_dialog import PlantillaArranqueDialog

        dlg = PlantillaArranqueDialog(
            ventana_principal_actual=self.ventana.text().strip(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        titulo = dlg.titulo
        exe_path = dlg.exe_path
        if not titulo:
            QMessageBox.warning(self, "Sin título", "Necesito un patrón de título.")
            return

        nuevos: list = []
        if exe_path:
            from pathlib import Path
            nombre_exe = Path(exe_path).name or exe_path
            nuevos.append(Step(
                tipo=StepType.LAUNCH_PROGRAM,
                valor=exe_path,
                descripcion=f"Lanzar: {nombre_exe}",
                delay_before_s=0.0,
            ))
            nuevos.append(Step(
                tipo=StepType.SLEEP,
                valor="2.0",
                descripcion="Espera 2s a que arranque la aplicación",
                delay_before_s=0.0,
            ))

        nuevos += [
            Step(
                tipo=StepType.SEND_KEYS,
                valor="{VK_LWIN down}d{VK_LWIN up}",
                descripcion="Tecla Win+D  (minimizar todo)",
                delay_before_s=0.5,
            ),
            Step(
                tipo=StepType.SLEEP,
                valor="1.0",
                descripcion="Espera 1s a que se aplique Win+D",
                delay_before_s=0.0,
            ),
            Step(
                tipo=StepType.WINDOW_ENSURE,
                titulo=titulo,
                extra={"state": "maximized"},
                timeout_s=10.0,
                descripcion=f"Traer al frente + maximizar: {titulo}",
                delay_before_s=0.5,
            ),
        ]
        self.macro.pasos = nuevos + self.macro.pasos
        if not self.ventana.text().strip():
            self.ventana.setText(titulo)
        self._refresh_table()
        QMessageBox.information(
            self, "Plantilla añadida",
            f"Se insertaron {len(nuevos)} pasos al principio de la macro.\n"
            f"Patrón de ventana: '{titulo}'.",
        )

    def _on_macro_recorded(self, macro: Macro):
        if not macro or not macro.pasos:
            QMessageBox.information(self, "Grabación", "No se capturó ningún paso.")
            return
        n = len(macro.pasos)
        msg = QMessageBox(self)
        msg.setWindowTitle("Grabación completada")
        msg.setText(
            f"Se han capturado {n} pasos nuevos.\n"
            f"La macro actual tiene {len(self.macro.pasos)} pasos."
        )
        msg.setInformativeText("¿Qué quieres hacer con los pasos grabados?")
        b_anadir = msg.addButton("Añadir al final", QMessageBox.ButtonRole.AcceptRole)
        b_remplazar = msg.addButton("Reemplazar todo", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is b_anadir:
            self.macro.pasos.extend(macro.pasos)
        elif clicked is b_remplazar:
            self.macro.pasos = list(macro.pasos)
        else:
            return
        self._refresh_table()

    def _launch_inspector(self):
        QMessageBox.information(
            self,
            "Inspector",
            "Haz clic en cualquier control de la ventana objetivo.\n"
            "MemoviPro capturará su selector simbólico.",
        )
        self._inspector.empezar()

    def _on_inspect_captured(self, cap: CapturaSelector):
        row = self.tabla.currentRow()
        sel = Selector(
            control_type=cap.control_type,
            name=cap.name,
            auto_id=cap.auto_id,
            class_name=cap.class_name,
        )
        if row >= 0:
            self.macro.pasos[row].selector = sel
            self._refresh_table()
            QMessageBox.information(self, "Selector capturado", f"Aplicado al paso #{row + 1}:\n\n{cap.yaml_snippet()}")
        else:
            paso = Step(
                tipo=StepType.CLICK_CONTROL,
                selector=sel,
                descripcion=f"Click en {sel.name or sel.control_type or '?'}",
            )
            self.macro.pasos.append(paso)
            self._refresh_table()
            QMessageBox.information(self, "Selector capturado", f"Añadido como nuevo paso:\n\n{cap.yaml_snippet()}")

    def _on_inspect_error(self, msg: str):
        QMessageBox.warning(self, "Inspector", msg)
