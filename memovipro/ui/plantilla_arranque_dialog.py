"""Diálogo de la plantilla "arranque limpio".

Sustituye el QInputDialog simple del editor por un formulario que:
- Lista las ventanas Windows actualmente abiertas (combo).
- Pre-selecciona la ventana en foreground.
- Permite editar el patrón de título a mano.
- Permite opcionalmente especificar la ruta de un .exe para lanzar la
  app si no estuviera abierta.
- Tiene un botón "🔍 Probar patrón" que llama a window_utils.asegurar_ventana
  inmediatamente y reporta si la encuentra (con sugerencias si no).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.window_utils import asegurar_ventana, listar_ventanas_visibles


class PlantillaArranqueDialog(QDialog):
    """Diálogo para configurar los pasos de arranque limpio.

    Devuelve `titulo` y `exe_path` via propiedades tras `exec()`.
    """

    def __init__(self, ventana_principal_actual: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ Plantilla: arranque limpio")
        self.resize(680, 460)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "<b>Configura el arranque limpio de tu macro</b><br>"
            "MemoviPro insertará al principio: <code>Win+D</code> "
            "(minimizar todo) + esperar 1s + traer al frente y maximizar "
            "la ventana que indiques aquí."
        ))

        # === Selector de ventanas detectadas ===
        layout.addWidget(QLabel("<b>1. Elige la ventana objetivo</b>"))
        fila_combo = QHBoxLayout()
        fila_combo.addWidget(QLabel("Ventana detectada:"))
        self.ventanas_combo = QComboBox()
        self.ventanas_combo.setMinimumWidth(420)
        fila_combo.addWidget(self.ventanas_combo, 1)
        refresh_btn = QPushButton("🔄 Refrescar")
        refresh_btn.clicked.connect(self._refresh_ventanas)
        fila_combo.addWidget(refresh_btn)
        layout.addLayout(fila_combo)

        # Campo título editable (patrón regex parcial)
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(QLabel("Patrón título:"))
        self.titulo_edit = QLineEdit(ventana_principal_actual)
        self.titulo_edit.setPlaceholderText(
            "Ej. 'Menú de Turnos' · acepta regex con |: 'GERHONTE|FABPMEN1'"
        )
        fila_titulo.addWidget(self.titulo_edit, 1)
        layout.addLayout(fila_titulo)

        # Botón probar
        fila_probar = QHBoxLayout()
        probar_btn = QPushButton("🔍 Probar patrón ahora")
        probar_btn.clicked.connect(self._probar)
        probar_btn.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        fila_probar.addWidget(probar_btn)
        fila_probar.addStretch()
        layout.addLayout(fila_probar)

        self.resultado_label = QLabel(
            "<i style='color:#7f8c8d'>Pulsa \"Probar\" para verificar que el "
            "patrón encuentra la ventana correcta antes de aceptar.</i>"
        )
        self.resultado_label.setWordWrap(True)
        self.resultado_label.setTextFormat(Qt.TextFormat.RichText)
        self.resultado_label.setStyleSheet(
            "background:#ecf0f1; padding:8px; border-radius:3px;"
        )
        layout.addWidget(self.resultado_label)

        # === Sección .exe opcional ===
        layout.addWidget(QLabel(
            "<b>2. Opcional: lanzar el .exe si la app no estuviera abierta</b>"
        ))
        fila_exe = QHBoxLayout()
        fila_exe.addWidget(QLabel("Ruta del .exe:"))
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText(
            "Vacío = se asume que la app ya está abierta"
        )
        fila_exe.addWidget(self.exe_edit, 1)
        browse_btn = QPushButton("Examinar…")
        browse_btn.clicked.connect(self._browse_exe)
        fila_exe.addWidget(browse_btn)
        layout.addLayout(fila_exe)

        layout.addStretch()

        # === OK / Cancel ===
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        # Conectar combo después de poblarlo
        self.ventanas_combo.currentIndexChanged.connect(self._on_ventana_seleccionada)
        self._refresh_ventanas()

    # ===== Refrescar combo de ventanas =====
    def _refresh_ventanas(self):
        self.ventanas_combo.blockSignals(True)
        self.ventanas_combo.clear()
        ventanas = listar_ventanas_visibles()
        if not ventanas:
            self.ventanas_combo.addItem(
                "(no se detectan ventanas — pywinauto no disponible)", ""
            )
            self.ventanas_combo.blockSignals(False)
            return
        for v in ventanas:
            marca = "★ " if v.is_foreground else "   "
            label = f"{marca}{v.titulo}    [{v.class_name}]"
            self.ventanas_combo.addItem(label, v.titulo)
        self.ventanas_combo.blockSignals(False)
        # Pre-seleccionar la foreground (es la primera por orden)
        if ventanas and ventanas[0].is_foreground:
            self.ventanas_combo.setCurrentIndex(0)
            # Solo auto-rellenamos si el campo está vacío
            if not self.titulo_edit.text().strip():
                self.titulo_edit.setText(ventanas[0].titulo)

    def _on_ventana_seleccionada(self):
        titulo = self.ventanas_combo.currentData()
        if titulo:
            self.titulo_edit.setText(titulo)

    # ===== Probar patrón =====
    def _probar(self):
        patron = self.titulo_edit.text().strip()
        if not patron:
            self.resultado_label.setText(
                "<span style='color:#e67e22'>⚠ Escribe un patrón primero "
                "(o elige una ventana del combo).</span>"
            )
            return
        ok, msg = asegurar_ventana(patron, state="maximized", timeout_s=2.0)
        if ok:
            self.resultado_label.setText(
                f"<span style='color:#27ae60'><b>✓</b> {msg}<br>"
                f"<i>Patrón válido. La ventana se ha traído al frente y "
                f"maximizado correctamente.</i></span>"
            )
        else:
            # Sugerir 5 ventanas abiertas
            ventanas = listar_ventanas_visibles()
            sug_html = ""
            if ventanas:
                items = "".join(
                    f"<li><code>{v.titulo[:90]}</code></li>"
                    for v in ventanas[:5]
                )
                sug_html = (
                    f"<br><br><i>Ventanas abiertas que podrías usar:</i>"
                    f"<ul>{items}</ul>"
                )
            self.resultado_label.setText(
                f"<span style='color:#c0392b'><b>✗</b> {msg}</span>{sug_html}"
            )

    # ===== Examinar .exe =====
    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar ejecutable", "",
            "Ejecutables (*.exe *.lnk *.bat *.cmd);;Todos (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.exe_edit.setText(path)

    # ===== Resultados =====
    @property
    def titulo(self) -> str:
        return self.titulo_edit.text().strip()

    @property
    def exe_path(self) -> str:
        return self.exe_edit.text().strip()
