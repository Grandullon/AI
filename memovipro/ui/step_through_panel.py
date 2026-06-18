"""Step-through debugger flotante para la pestaña Macros.

Permite ejecutar una macro paso a paso, mostrando el paso actual y
esperando a que el usuario pulse "▶ Siguiente" (o Espacio/F10) para
avanzar. En cualquier momento puede pulsar "🔴 Grabar pasos aquí" para
insertar nuevos pasos en la macro en la posición actual, y luego
seguir reproduciendo. Es lo que UiPath llama "step into".

Reutiliza el patrón de ControlWindow (frameless, always on top, drag a
corner). Pone MemoviPro minimizado durante la sesión y lo restaura al
salir.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.player import RunStatus
from core.recorder import Recorder
from core.replay_runner import ReplayRunner, ReplaySummary
from core.step_model import Macro

from .record_dialog import RecordDialog


CONTROL_STYLE = """
QWidget#StepRoot {
    background-color: rgba(44, 62, 80, 235);
    border: 1px solid #1a252f;
    border-radius: 8px;
}
QLabel { color: white; background: transparent; }
QLabel#title { font-weight: bold; font-size: 13px; }
QLabel#subtitle { font-size: 11px; color: #bdc3c7; }
QLabel#action { font-size: 11px; color: #ecf0f1; font-style: italic; }
QPushButton {
    background-color: #34495e; color: white;
    border: 1px solid #4a6378; padding: 6px 12px;
    border-radius: 4px; font-size: 12px;
}
QPushButton:hover { background-color: #4a6378; }
QPushButton#next { background-color: #27ae60; border-color: #1e8449; font-weight: bold; }
QPushButton#next:hover { background-color: #2ecc71; }
QPushButton#stop { background-color: #c0392b; border-color: #922b21; }
QPushButton#stop:hover { background-color: #a93226; }
QPushButton#record { background-color: #e67e22; border-color: #ba6411; }
QPushButton#record:hover { background-color: #f39c12; }
QPushButton#back { background-color: #2c3e50; border-color: #1a252f; }
QPushButton#back:hover { background-color: #34495e; }
"""


class _StepThroughThread(QThread):
    """Hilo que ejecuta un ReplayRunner con step_mode=True."""

    step_status = pyqtSignal(object)  # RunStatus
    finished_summary = pyqtSignal(object)  # ReplaySummary
    error = pyqtSignal(str)

    def __init__(self, runner: ReplayRunner):
        super().__init__()
        self.runner = runner

    def run(self):
        try:
            self.runner.on_status = lambda s: self.step_status.emit(s)
            summary = self.runner.run()
            self.finished_summary.emit(summary)
        except Exception as exc:
            self.error.emit(str(exc))


class StepThroughPanel(QWidget):
    """Panel flotante para el debugger paso a paso."""

    # Señal emitida cuando el panel termina (para que el editor restaure
    # la ventana principal y refresque la tabla).
    finished = pyqtSignal()

    def __init__(
        self,
        macro: Macro,
        screenshots_dir: Path,
        data_dir: Path,
        on_macro_modified: Callable[[], None] | None = None,
        on_step_changed: Callable[[int], None] | None = None,
        parent=None,
    ):
        super().__init__(parent=None)  # top-level
        self.macro = macro
        self.screenshots_dir = screenshots_dir
        self.data_dir = data_dir
        self.on_macro_modified = on_macro_modified
        self.on_step_changed = on_step_changed

        self.setObjectName("StepRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet(CONTROL_STYLE)
        self.setFixedWidth(380)
        self._drag_offset = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.title_label = QLabel(f"🐞 Step-through · {macro.nombre}")
        self.title_label.setObjectName("title")
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(f"Paso 0/{len(macro.pasos)}")
        self.subtitle_label.setObjectName("subtitle")
        layout.addWidget(self.subtitle_label)

        self.action_label = QLabel(
            "Pulsa <b>▶</b> o <b>→</b> para avanzar · <b>◀</b> o <b>←</b> "
            "para retroceder."
        )
        self.action_label.setObjectName("action")
        self.action_label.setWordWrap(True)
        self.action_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.action_label)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 6, 0, 0)
        btns.setSpacing(6)
        self.back_btn = QPushButton("◀ Atrás")
        self.back_btn.setObjectName("back")
        self.back_btn.clicked.connect(self._on_back)
        btns.addWidget(self.back_btn)
        self.next_btn = QPushButton("▶ Siguiente")
        self.next_btn.setObjectName("next")
        self.next_btn.clicked.connect(self._on_next)
        btns.addWidget(self.next_btn)
        self.record_btn = QPushButton("🔴 Grabar aquí")
        self.record_btn.setObjectName("record")
        self.record_btn.clicked.connect(self._on_record_here)
        btns.addWidget(self.record_btn)
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self._on_stop)
        btns.addWidget(self.stop_btn)
        layout.addLayout(btns)

        # Atajos teclado:
        #   Espacio / F10 / → (flecha derecha) = Siguiente
        #   ← (flecha izquierda) = Atrás
        #   Esc = Parar
        for key in ("Space", "F10", "Right"):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(self._on_next)
        sc_back = QShortcut(QKeySequence("Left"), self)
        sc_back.activated.connect(self._on_back)
        sc_esc = QShortcut(QKeySequence("Escape"), self)
        sc_esc.activated.connect(self._on_stop)

        self.adjustSize()

        # Crear runner y thread
        self._runner = ReplayRunner(
            macro=macro,
            veces=1,
            velocidad=1.0,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
            watchdog_activo=False,  # paso a paso no necesita auto-cierre de popups
            step_mode=True,
        )
        self._thread = _StepThroughThread(self._runner)
        self._thread.step_status.connect(self._on_step_status)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.error.connect(self._on_error)

    def show_in_corner(self):
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is not None:
            self.move(scr.right() - self.width() - 20, scr.top() + 20)
        self.show()
        self.raise_()

    def start(self):
        self.show_in_corner()
        self._thread.start()

    # ===== drag =====
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    # ===== callbacks =====
    def _on_step_status(self, status: RunStatus):
        n = status.paso_idx + 1
        total = len(self.macro.pasos)
        self.subtitle_label.setText(f"Paso {n}/{total} (próximo)")
        self.action_label.setText(
            f"<b>{n}.</b> {status.descripcion or '(sin descripción)'}"
        )
        # Marcar el paso en la tabla del editor (para que el usuario sepa
        # dónde se ha parado si quiere modificar algo en ese punto).
        if self.on_step_changed is not None:
            try:
                self.on_step_changed(status.paso_idx)
            except Exception:
                pass

    def _on_next(self):
        if self._runner is None:
            return
        self._runner.advance_step()

    def _on_back(self):
        """Retrocede el puntero un paso (para revisar / reejecutar).

        No deshace lo ya hecho en la aplicación, solo re-apunta al paso
        anterior; el siguiente ▶ lo volverá a ejecutar."""
        if self._runner is None:
            return
        self._runner.step_back()

    def _on_stop(self):
        if self._runner:
            self._runner.abort()
        self.action_label.setText("<i>Detenido</i>")

    def _on_record_here(self):
        """Pausa el step-through y abre el grabador. Los pasos
        capturados se insertan en la macro JUSTO DESPUÉS del paso actual."""
        if self._runner is None or self._runner.player is None:
            QMessageBox.information(self, "Aún no", "Pulsa primero ▶ Siguiente al menos una vez.")
            return
        idx_actual = self._runner.player.step_index()

        # Lanzamos el RecordDialog modal. El step-through se queda
        # esperando porque _runner.player no recibe advance_step.
        dlg = RecordDialog(parent=self)
        result = dlg.exec()
        if result and dlg.macro is not None and dlg.macro.pasos:
            nuevos = list(dlg.macro.pasos)
            insert_at = idx_actual + 1
            self.macro.pasos[insert_at:insert_at] = nuevos
            if self.on_macro_modified:
                self.on_macro_modified()
            self.action_label.setText(
                f"<b>{insert_at + 1}.</b> ➕ Insertados {len(nuevos)} pasos "
                "nuevos justo después del paso actual. Pulsa ▶ Siguiente."
            )

    def _on_finished(self, summary: ReplaySummary):
        self.action_label.setText(
            f"<b>✓ Fin</b> · {summary.ok} OK · {summary.ko} KO"
        )
        self.next_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.finished.emit()

    def _on_error(self, msg: str):
        self.action_label.setText(f"<span style='color:#e74c3c'>❌ {msg}</span>")
        self.finished.emit()

    def closeEvent(self, event):
        if self._runner:
            self._runner.abort()
        if self._thread and self._thread.isRunning():
            self._thread.wait(1000)
        super().closeEvent(event)
