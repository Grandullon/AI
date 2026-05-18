"""Diálogo de grabación de macro.

Flujo:
1. Countdown 3-2-1 para que el usuario cambie de ventana.
2. La ventana grande del diálogo se oculta y aparece un panel flotante
   compacto (estilo UiPath Studio Robot) en una esquina, siempre encima.
   La ventana principal de MemoviPro se minimiza para no estorbar.
3. Inicia el grabador (captura cruda y rápida).
4. F9 global o botón "Parar" del panel flotante para finalizar.
5. La resolución de selectores (lenta) corre en un QThread aparte —
   la ventana sigue viva mostrando "Procesando paso X/Y".
6. Cuando termina, emite la `Macro` resultante y restaura MemoviPro.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.recorder import EventoCrudo, Recorder
from core.step_model import Macro

from .control_window import ControlWindow

try:
    from pynput import keyboard as _pynput_keyboard
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False


COUNTDOWN_SECS = 3


class _ResolveWorker(QThread):
    """Hilo que detiene el recorder y resuelve los selectores."""

    progress = pyqtSignal(int, int)
    finished_macro = pyqtSignal(object)  # Macro o None

    def __init__(self, recorder: Recorder, resolver_selectores: bool = True):
        super().__init__()
        self.recorder = recorder
        self.resolver_selectores = resolver_selectores

    def run(self):
        try:
            eventos = self.recorder.stop()
            macro = Recorder.construir_macro(
                eventos,
                resolver_selectores=self.resolver_selectores,
                on_progress=lambda i, total: self.progress.emit(i, total),
            )
        except Exception:
            macro = None
        self.finished_macro.emit(macro)


class RecordDialog(QDialog):
    macro_capturada = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grabar macro")
        # Modal app-wide pero sin AlwaysOnTop:
        # - Bloquea el resto de MemoviPro durante la grabación.
        # - El usuario sigue pudiendo alt-tab a su aplicación de trabajo.
        # - Evita que se quede oculto detrás de cualquier QMessageBox modal.
        self.setModal(True)
        self.resize(440, 220)

        self.macro: Optional[Macro] = None
        self._recorder: Optional[Recorder] = None
        self._kb_listener = None
        self._countdown_left = COUNTDOWN_SECS
        self._counter_steps = 0
        self._worker: Optional[_ResolveWorker] = None
        self._control: Optional[ControlWindow] = None
        self._main_window_was_visible = True

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
            "Pulsa <b>F9</b> en cualquier ventana o el botón <b>Detener</b> para finalizar."
        )
        self.ayuda.setTextFormat(Qt.TextFormat.RichText)
        self.ayuda.setWordWrap(True)
        self.ayuda.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.ayuda)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

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

        # Reemplazar el diálogo gordo por el panel compacto y minimizar
        # MemoviPro para no estorbar a la app que se está grabando.
        self._control = ControlWindow(parent=None)
        self._control.set_title("🔴 GRABANDO", "Pulsa F9 o el botón Parar para terminar")
        self._control.set_action("0 acciones capturadas")
        self._control.hide_progress()
        self._control.pause_btn.setVisible(False)  # no se pausa la grabación
        self._control.stop_requested.connect(self._stop)
        self._control.show_in_corner()

        self.hide()  # ocultamos el diálogo grande con countdown
        parent = self.parent()
        main_win = parent.window() if parent is not None else None
        if main_win is not None:
            self._main_window_was_visible = main_win.isVisible()
            main_win.showMinimized()

    def _tick_update(self):
        if self._recorder is None:
            return
        n = len(self._recorder.pasos)
        if n != self._counter_steps:
            self._counter_steps = n
            self.contador.setText(f"{n} acciones capturadas")
            if self._control is not None:
                self._control.set_action(f"{n} acciones capturadas")

    def _start_hotkey(self):
        if not _HAS_PYNPUT:
            return

        def on_press(key):
            try:
                if key == _pynput_keyboard.Key.f9:
                    QTimer.singleShot(0, self._stop)
                    return False
            except Exception:
                return
            return None

        try:
            self._kb_listener = _pynput_keyboard.Listener(on_press=on_press)
            self._kb_listener.start()
        except Exception:
            self._kb_listener = None

    def _stop_hotkey_async(self):
        """Detiene el listener de F9 y espera (con timeout) a que termine.

        Importante en Windows: hasta que el hilo de pynput no termina,
        sus hooks de bajo nivel siguen instalados y pueden interferir
        con QFileDialog y otros diálogos nativos.
        """
        if self._kb_listener is None:
            return
        lst = self._kb_listener
        self._kb_listener = None
        try:
            lst.stop()
        except Exception:
            pass
        try:
            if lst.is_alive():
                lst.join(timeout=1.0)
        except Exception:
            pass

    def _stop(self):
        if self._recorder is None:
            self._cancelar()
            return
        # Cambiamos la UI a estado "procesando" inmediatamente.
        self._update_timer.stop()
        self._stop_hotkey_async()
        self.estado.setText("⏳ Procesando selectores…")
        self.estado.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
        self.btn_detener.setEnabled(False)
        self.btn_cancelar.setText("Cerrar sin procesar")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # indeterminado hasta que llegue el primer progreso

        if self._control is not None:
            self._control.set_title("⏳ Procesando…", "Resolviendo selectores")
            self._control.show_progress()
            self._control.set_progress(0, 1)

        # La parte lenta corre en un hilo aparte para no bloquear la GUI.
        self._worker = _ResolveWorker(self._recorder, resolver_selectores=True)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_macro.connect(self._on_macro_ready)
        self._worker.start()

    def _on_progress(self, i: int, total: int):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(i)
            self.estado.setText(f"⏳ Resolviendo selector {i}/{total}…")
            if self._control is not None:
                self._control.set_progress(i, total)
                self._control.set_action(f"Selector {i}/{total}")

    def _on_macro_ready(self, macro):
        self._recorder = None
        if macro is None:
            macro = Macro(nombre="grabacion")
        self.macro = macro
        # Restaurar MemoviPro y cerrar el panel flotante antes de emitir,
        # para que cualquier QMessageBox del padre quede al frente.
        self._restaurar_ventanas()
        self.accept()
        self.macro_capturada.emit(self.macro)

    def _cancelar(self):
        self._countdown_timer.stop()
        self._update_timer.stop()
        self._stop_hotkey_async()
        self._restaurar_ventanas()
        if self._worker is not None and self._worker.isRunning():
            # Si el worker está corriendo, dejamos que termine; cerramos diálogo.
            self.reject()
            return
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
        self.reject()

    def _restaurar_ventanas(self):
        """Cierra el panel flotante y restaura MemoviPro."""
        if self._control is not None:
            try:
                self._control.close()
                self._control.deleteLater()
            except Exception:
                pass
            self._control = None
        parent = self.parent()
        main_win = parent.window() if parent is not None else None
        if main_win is not None and self._main_window_was_visible:
            try:
                main_win.showNormal()
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass

    def closeEvent(self, event):
        self._cancelar()
        super().closeEvent(event)
