"""Panel para gestionar credenciales cifradas.

Las contraseñas se almacenan en el Credential Manager de Windows (DPAPI)
vía keyring. El panel solo muestra los nombres de los secretos, NUNCA
los valores. En las macros se usan como placeholder `{SECRET:nombre}`.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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

from core import secrets as secrets_mod


class SecretsPanel(QWidget):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.index_path = data_dir / "secrets_index.json"

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Credenciales cifradas (Windows Credential Manager)</b>"))

        info = QLabel(
            "Los valores se cifran con DPAPI y se almacenan a nivel de usuario "
            "Windows. En tus macros, usa el placeholder "
            "<code>{SECRET:nombre}</code> donde quieras que se inyecte la "
            "contraseña al reproducir."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(info)

        if not secrets_mod.is_available():
            warn = QLabel(
                "⚠ No se ha detectado un backend de keyring funcional. "
                "En Linux puede faltar gnome-keyring o KWallet. En Windows "
                "esto no debería pasar — instala 'keyring' con pip."
            )
            warn.setStyleSheet("color: #c0392b; font-weight: bold;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # Tabla con un único campo: nombre
        self.tabla = QTableWidget(0, 1)
        self.tabla.setHorizontalHeaderLabels(["Nombre del secreto"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla, 1)

        botones = QHBoxLayout()
        for txt, slot in [
            ("Añadir / Sobrescribir", self._add_or_replace),
            ("Probar (resolver y mostrar longitud)", self._test_secret),
            ("Eliminar", self._delete),
            ("↻ Refrescar", self.refresh),
        ]:
            b = QPushButton(txt)
            b.clicked.connect(slot)
            botones.addWidget(b)
        layout.addLayout(botones)

        self.refresh()

    def refresh(self):
        nombres = secrets_mod.list_secrets(self.index_path)
        self.tabla.setRowCount(0)
        for n in nombres:
            r = self.tabla.rowCount()
            self.tabla.insertRow(r)
            self.tabla.setItem(r, 0, QTableWidgetItem(n))

    def _add_or_replace(self):
        nombre, ok = QInputDialog.getText(
            self, "Nombre del secreto",
            "Nombre (lo que pondrás dentro de {SECRET:...}):",
            QLineEdit.EchoMode.Normal, "",
        )
        if not ok or not nombre.strip():
            return
        nombre = nombre.strip()
        valor, ok = QInputDialog.getText(
            self, f"Valor de '{nombre}'",
            "Valor (no se mostrará en pantalla):",
            QLineEdit.EchoMode.Password, "",
        )
        if not ok:
            return
        if not valor:
            QMessageBox.warning(self, "Vacío", "El valor está vacío. Cancelado.")
            return
        success = secrets_mod.set_secret(nombre, valor, self.index_path)
        if success:
            QMessageBox.information(
                self, "Guardado",
                f"Secreto '{nombre}' guardado.\nÚsalo en macros como: "
                f"{{SECRET:{nombre}}}",
            )
            self.refresh()
        else:
            QMessageBox.warning(self, "Error", "No se pudo guardar el secreto. Revisa logs.")

    def _test_secret(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        nombre = self.tabla.item(row, 0).text()
        v = secrets_mod.get_secret(nombre)
        if v is None:
            QMessageBox.warning(self, "No encontrado", f"'{nombre}' no devuelve valor.")
            return
        QMessageBox.information(
            self, "OK",
            f"'{nombre}' resuelve correctamente.\nLongitud del valor: {len(v)} caracteres.",
        )

    def _delete(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        nombre = self.tabla.item(row, 0).text()
        if QMessageBox.question(
            self, "Confirmar", f"¿Eliminar el secreto '{nombre}'?",
        ) != QMessageBox.StandardButton.Yes:
            return
        secrets_mod.delete_secret(nombre, self.index_path)
        self.refresh()
