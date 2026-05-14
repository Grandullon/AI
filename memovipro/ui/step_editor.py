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


COLS = ["#", "Tipo", "Selector", "Valor / Título", "Timeout (s)", "Opc.", "Descripción"]


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
        layout.addWidget(self.tabla, 1)

        botones = QHBoxLayout()
        for txt, slot in [
            ("Añadir paso", self._add_step),
            ("Editar valor", self._edit_value),
            ("Eliminar", self._remove_step),
            ("Subir", lambda: self._move(-1)),
            ("Bajar", lambda: self._move(1)),
            ("Inspector", self._launch_inspector),
            ("Cargar YAML", self._load),
            ("Guardar YAML", self._save),
        ]:
            b = QPushButton(txt)
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
            valores = [
                str(i + 1),
                paso.tipo.value,
                sel_txt,
                valor,
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
        path, _ = QFileDialog.getOpenFileName(self, "Cargar macro", str(self.macros_dir), "YAML (*.yaml *.yml)")
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
        self._sync_from_form()
        default = self.macros_dir / f"{self.macro.nombre}.yaml"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar macro", str(default), "YAML (*.yaml)")
        if not path:
            return
        try:
            self.macro.save(path)
            QMessageBox.information(self, "Guardado", f"Macro guardada en {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {exc}")

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
