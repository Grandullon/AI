"""Diálogo de grabación de macro.

Flujo:
1. Aparece con un countdown 3-2-1 para que el usuario cambie de ventana.
2. Inicia el grabador (clics resueltos a selectores UI Automation y
   tecleo agrupado, sin movimientos del ratón).
3. El usuario puede:
   - Volver a MemoviPro y pulsar "Detener", o
   - Pulsar F9 estando en cualquier ventana (hotkey global).
4. Devuelve la Macro grabada.

El primer clic real del usuario sobre el botón "Grabar" no se captura
porque el listener no se inicia hasta después del countdown.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.step_model import Macro

try:
    from pynput import keyboard as _pynput_keyboard
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False


COUNTDOWN_SECS = 3


class RecordDialog(QDialog):
    macro_capturada = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grabar macro")
        self.setModal(False)  # no modal: el usuario tiene que poder cambiar a otra app
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(420, 200)

        self.macro: Optional[Macro] = None
        self._recorder = None
        self._kb_listener = None
        self._countdown_left = COUNTDOWN_SECS
        self._counter_steps = 0

        layout = QVBoxLayout(self)
        self.estado = QLabel(f"La grabación empezará en {COUNTDOWN_SECS}…")
        self.estado.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
        self.estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.estado)

        self.contador = QLabel("0 acciones capturadas")
        self.contador.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.contador.setStyleSheet("color: #7f8c8d;")
        layout.addWidget(self.contador)

        self.ayuda = QLabel(
            "Cambia ahora a tu aplicación.\n"
            "Pulsa <b>F9</b> en cualquier ventana o el botón <b>Detener</b> "
            "para finalizar."
        )
        self.ayuda.setTextFormat(Qt.TextFormat.RichText)
        self.ayuda.setWordWrap(True)
        self.ayuda.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ayuda)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_detener = QPushButton("⏹ Detener (F9)")
        self.btn_detener.setEnabled(False)
        self.btn_detener.clicked.connect(self._stop)
        btns.addWidget(self.btn_detener)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)
        btns.addWidget(self.btn_cancelar)
        btns.addStretch()
        layout.addLayout(btns)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._tick_update)

    def showEvent(self, event):
        super().showEvent(event)
        self._countdown_timer.start(1000)

    def _tick_countdown(self):
        self._countdown_left -= 1
        if self._countdown_left > 0:
            self.estado.setText(f"La grabación empezará en {self._countdown_left}…")
            return
        self._countdown_timer.stop()
        self._iniciar_grabacion()

    def _iniciar_grabacion(self):
        from core.recorder import Recorder
        self._recorder = Recorder()
        try:
            self._recorder.start()
        except Exception as exc:
            self.estado.setText(f"Error al iniciar: {exc}")
            return
        self.estado.setText("🔴 GRABANDO  —  pulsa F9 para detener")
        self.estado.setStyleSheet("font-size: 18px; font-weight: bold; color: #c0392b;")
        self.btn_detener.setEnabled(True)
        self._update_timer.start(300)
        self._start_hotkey()

    def _tick_update(self):
        if self._recorder is None:
            return
        n = len(self._recorder.pasos)
        if n != self._counter_steps:
            self._counter_steps = n
            self.contador.setText(f"{n} acciones capturadas")

    def _start_hotkey(self):
        if not _HAS_PYNPUT:
            return

        def on_press(key):
            try:
                if key == _pynput_keyboard.Key.f9:
                    # llamada al método de Qt thread-safe vía señal
                    QTimer.singleShot(0, self._stop)
                    return False  # detener listener
            except Exception:
                return
            return None

        self._kb_listener = _pynput_keyboard.Listener(on_press=on_press)
        self._kb_listener.start()

    def _stop_hotkey(self):
        if self._kb_listener is not None:
            try:
                self._kb_listener.stop()
            except Exception:
                pass
            self._kb_listener = None

    def _stop(self):
        if self._recorder is None:
            self._cancelar()
            return
        self._update_timer.stop()
        self._stop_hotkey()
        try:
            self.macro = self._recorder.stop()
        except Exception as exc:
            self.estado.setText(f"Error al detener: {exc}")
            return
        self._recorder = None
        self.macro_capturada.emit(self.macro)
        self.accept()

    def _cancelar(self):
        self._countdown_timer.stop()
        self._update_timer.stop()
        self._stop_hotkey()
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
        self.reject()

    def closeEvent(self, event):
        self._cancelar()
        super().closeEvent(event)
