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

from loguru import logger

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
            logger.info("Recorder.stop devolvió {} eventos crudos", len(eventos))
            macro = Recorder.construir_macro(
                eventos,
                resolver_selectores=self.resolver_selectores,
                on_progress=lambda i, total: self.progress.emit(i, total),
            )
            logger.info(
                "construir_macro: {} pasos resultantes (resolver_selectores={})",
                len(macro.pasos) if macro else 0,
                self.resolver_selectores,
            )
        except Exception:
            logger.exception("Error en _ResolveWorker.run")
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
        # Nombre consistente con el que usan _iniciar_grabacion y
        # _restaurar_ventanas (antes había un _main_window_was_visible
        # muerto que confundía).
        self._main_was_visible = True

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

        # Panel flotante en la esquina (resumen visual). Mantenemos este
        # diálogo grande VISIBLE — ocultarlo rompió la captura en una
        # iteración anterior (5aa9ba5). Solo minimizamos la ventana
        # PRINCIPAL de MemoviPro para no estorbar a la app que graba.
        self._control = ControlWindow(parent=None)
        self._control.set_title("🔴 GRABANDO", "Pulsa F9 o el botón Parar para terminar")
        self._control.set_action("0 acciones capturadas")
        self._control.hide_progress()
        self._control.pause_btn.setVisible(False)  # no se pausa la grabación
        self._control.stop_requested.connect(self._stop)
        self._control.show_in_corner()

        # Minimizar la ventana PRINCIPAL (no este diálogo modal) para
        # que MemoviPro no estorbe al automatizar. La diferencia clave
        # respecto al intento fallido anterior: NO ocultamos el modal.
        parent = self.parent()
        main_win = parent.window() if parent is not None else None
        if main_win is not None and main_win is not self:
            self._main_was_visible = main_win.isVisible()
            try:
                main_win.showMinimized()
            except Exception:
                pass

        # Que el recorder ignore los clics sobre nuestras propias ventanas
        # (este diálogo y el panel flotante): sin esto, el clic en
        # "Detener" o un arrastre del panel acaban grabados como pasos.
        self._actualizar_zonas_excluidas()

    @staticmethod
    def _rect_fisico(w) -> tuple[int, int, int, int] | None:
        """Rectángulo de la ventana en píxeles FÍSICOS de pantalla.

        pynput entrega coordenadas físicas, pero `frameGeometry()` de Qt
        devuelve píxeles lógicos (escalados por DPI): con escalado de
        Windows al 125/150% las zonas quedarían desplazadas y encogidas.
        En Windows usamos GetWindowRect (físico, mismo espacio de
        coordenadas que pynput); fuera de Windows, aproximamos con la
        geometría lógica × devicePixelRatio.
        """
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(int(w.winId()), ctypes.byref(rect)):
                return (
                    int(rect.left), int(rect.top),
                    int(rect.right - rect.left), int(rect.bottom - rect.top),
                )
        except Exception:
            pass  # no-Windows o fallo de ctypes → fallback Qt
        try:
            g = w.frameGeometry()
            try:
                dpr = float(w.screen().devicePixelRatio()) if w.screen() else 1.0
            except Exception:
                dpr = 1.0
            return (
                int(g.left() * dpr), int(g.top() * dpr),
                int(g.width() * dpr), int(g.height() * dpr),
            )
        except Exception:
            return None

    def _actualizar_zonas_excluidas(self):
        """Publica en el recorder los rectángulos de las ventanas propias.

        Se llama al iniciar y en cada tick del timer (300 ms), así las
        zonas siguen al panel flotante si el usuario lo arrastra."""
        if self._recorder is None:
            return
        zonas: list[tuple[int, int, int, int]] = []
        for w in (self, self._control):
            if w is None:
                continue
            try:
                if not w.isVisible():
                    continue
            except Exception:
                continue
            rect = self._rect_fisico(w)
            if rect is not None:
                zonas.append(rect)
        self._recorder.zonas_excluidas = zonas

    def _tick_update(self):
        if self._recorder is None:
            return
        self._actualizar_zonas_excluidas()
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
        """Cierra el panel flotante y restaura la ventana principal
        de MemoviPro si la hemos minimizado durante la grabación."""
        if self._control is not None:
            try:
                self._control.close()
                self._control.deleteLater()
            except Exception:
                pass
            self._control = None
        parent = self.parent()
        main_win = parent.window() if parent is not None else None
        if (
            main_win is not None
            and main_win is not self
            and getattr(self, "_main_was_visible", False)
        ):
            try:
                main_win.showNormal()
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass

    def closeEvent(self, event):
        self._cancelar()
        super().closeEvent(event)
