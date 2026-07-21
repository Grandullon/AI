"""Step-through debugger flotante para la pestaña Macros.

Permite ejecutar una macro paso a paso, o con PUNTOS DE ANÁLISIS
(breakpoints): se auto-reproduce hasta el siguiente punto y ahí para.
En cada parada se puede grabar un paso nuevo en medio, avanzar paso a
paso, o saltar al siguiente punto.

Atajos GLOBALES (funcionan aunque el foco esté en la app que se
automatiza, no solo con MemoviPro enfocado):
    F8 = siguiente · F7 = atrás · F6 = continuar (al siguiente punto)
    F9 = parar
Además, con MemoviPro enfocado, valen Espacio/F10/→ (siguiente),
← (atrás) y Esc (parar).

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

try:
    from pynput import keyboard as _pynput_keyboard
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False

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
QPushButton#cont { background-color: #2980b9; border-color: #1f618d; font-weight: bold; }
QPushButton#cont:hover { background-color: #3498db; }
QLabel#bp { color: #f1c40f; font-size: 11px; font-weight: bold; }
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
    # Señal interna para marshalar las teclas globales (pynput) al hilo
    # GUI. QTimer.singleShot desde el hilo de pynput NO sirve: crearía el
    # timer en un hilo sin event loop de Qt y nunca dispararía. Emitir una
    # señal es thread-safe y se encola al hilo del objeto (el GUI).
    _hotkey = pyqtSignal(str)

    def __init__(
        self,
        macro: Macro,
        screenshots_dir: Path,
        data_dir: Path,
        on_macro_modified: Callable[[], None] | None = None,
        on_step_changed: Callable[[int], None] | None = None,
        breakpoints: set[int] | None = None,
        parent=None,
    ):
        super().__init__(parent=None)  # top-level
        self.macro = macro
        self.screenshots_dir = screenshots_dir
        self.data_dir = data_dir
        self.on_macro_modified = on_macro_modified
        self.on_step_changed = on_step_changed
        self._breakpoints = {int(b) for b in (breakpoints or set())}
        self._kb_listener = None
        # Con breakpoints arrancamos en modo "continue": auto-reproduce
        # hasta el primer punto. Sin breakpoints, paso a paso clásico.
        self._run_mode = "continue" if self._breakpoints else "step"
        # ¿Estamos parados esperando al usuario? Grabar/avanzar/atrás solo
        # tienen sentido en pausa (si no, se leería un step_index en
        # movimiento y se mutaría macro.pasos a mitad de iteración).
        self._en_pausa = not self._breakpoints  # sin bp: pausa desde el paso 1

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

        n_bp = len(self._breakpoints)
        sub = f"Paso 0/{len(macro.pasos)}"
        if n_bp:
            sub += f"  ·  {n_bp} punto(s) de análisis"
        self.subtitle_label = QLabel(sub)
        self.subtitle_label.setObjectName("subtitle")
        layout.addWidget(self.subtitle_label)

        # Etiqueta destacada cuando paramos en un punto de análisis.
        self.bp_label = QLabel("")
        self.bp_label.setObjectName("bp")
        self.bp_label.setVisible(False)
        layout.addWidget(self.bp_label)

        if n_bp:
            ayuda = ("Reproduciendo hasta el primer punto…  "
                     "<b>F8</b> paso · <b>F6</b> continuar · <b>F9</b> parar")
        else:
            ayuda = ("<b>F8</b>/→ avanzar · <b>F7</b>/← atrás · "
                     "<b>F6</b> continuar · <b>F9</b> parar  (teclas globales)")
        self.action_label = QLabel(ayuda)
        self.action_label.setObjectName("action")
        self.action_label.setWordWrap(True)
        self.action_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.action_label)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 6, 0, 0)
        btns.setSpacing(6)
        self.back_btn = QPushButton("◀ F7")
        self.back_btn.setObjectName("back")
        self.back_btn.clicked.connect(self._on_back)
        btns.addWidget(self.back_btn)
        self.next_btn = QPushButton("▶ F8")
        self.next_btn.setObjectName("next")
        self.next_btn.clicked.connect(self._on_next)
        btns.addWidget(self.next_btn)
        self.cont_btn = QPushButton("▶▶ F6")
        self.cont_btn.setObjectName("cont")
        self.cont_btn.setToolTip("Continuar hasta el siguiente punto de análisis")
        self.cont_btn.clicked.connect(self._on_continue)
        btns.addWidget(self.cont_btn)
        self.record_btn = QPushButton("🔴 Grabar")
        self.record_btn.setObjectName("record")
        self.record_btn.clicked.connect(self._on_record_here)
        btns.addWidget(self.record_btn)
        self.stop_btn = QPushButton("⏹ F9")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self._on_stop)
        btns.addWidget(self.stop_btn)
        layout.addLayout(btns)
        # Estado inicial: si arrancamos auto-reproduciendo (hay breakpoints),
        # grabar/atrás/siguiente empiezan deshabilitados hasta la 1ª pausa.
        for b in (self.back_btn, self.next_btn, self.record_btn):
            b.setEnabled(self._en_pausa)

        # Atajos LOCALES de Qt (solo con MemoviPro enfocado). Los GLOBALES
        # (que funcionan con la app destino enfocada) se instalan con
        # pynput en _start_hotkeys().
        for key in ("Space", "F10", "Right"):
            QShortcut(QKeySequence(key), self).activated.connect(self._on_next)
        QShortcut(QKeySequence("Left"), self).activated.connect(self._on_back)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._on_stop)

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
            breakpoints=self._breakpoints,
            run_mode=self._run_mode,
        )
        self._thread = _StepThroughThread(self._runner)
        self._thread.step_status.connect(self._on_step_status)
        self._thread.finished_summary.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        # Las teclas globales (pynput, otro hilo) llegan por esta señal, que
        # Qt encola al hilo GUI.
        self._hotkey.connect(self._on_hotkey)

    def show_in_corner(self):
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is not None:
            self.move(scr.right() - self.width() - 20, scr.top() + 20)
        self.show()
        self.raise_()

    def start(self):
        self.show_in_corner()
        self._start_hotkeys()
        self._thread.start()

    # ===== atajos globales (pynput) =====
    def _on_hotkey(self, nombre: str):
        """Slot que corre en el hilo GUI (invocado por la señal _hotkey).

        Ignora emisiones tardías: si el listener ya se paró (p. ej. durante
        'grabar aquí'), una señal encolada no debe disparar nada."""
        if self._kb_listener is None:
            return
        {
            "next": self._on_next,
            "back": self._on_back,
            "continue": self._on_continue,
            "stop": self._on_stop,
        }.get(nombre, lambda: None)()

    def _start_hotkeys(self):
        """Instala teclas globales F6/F7/F8/F9 que funcionan aunque el foco
        esté en la app que se automatiza (los QShortcut de Qt solo valen
        con MemoviPro enfocado, por eso antes obligaban al ratón)."""
        if not _HAS_PYNPUT:
            return
        if self._kb_listener is not None:
            return  # ya instalado

        # Mapa tecla → nombre de acción. El callback corre en el hilo de
        # pynput; emite la señal (thread-safe) que se ejecuta en el GUI.
        acciones = {
            _pynput_keyboard.Key.f8: "next",
            _pynput_keyboard.Key.f7: "back",
            _pynput_keyboard.Key.f6: "continue",
            _pynput_keyboard.Key.f9: "stop",
        }

        def on_press(key):
            nombre = acciones.get(key)
            if nombre is not None:
                self._hotkey.emit(nombre)

        try:
            self._kb_listener = _pynput_keyboard.Listener(on_press=on_press)
            self._kb_listener.start()
        except Exception:
            self._kb_listener = None

    def _stop_hotkeys(self):
        lst = self._kb_listener
        self._kb_listener = None
        if lst is None:
            return
        try:
            lst.stop()
        except Exception:
            pass
        # Esperar a que el hilo del hook muera: si no, podría emitir una
        # última señal ya con el listener a None (la ignora _on_hotkey, pero
        # así cerramos la ventana del todo, igual que RecordDialog).
        try:
            if lst.is_alive():
                lst.join(timeout=1.0)
        except Exception:
            pass

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
    def _set_controls_en_pausa(self, en_pausa: bool):
        """Habilita grabar/atrás/siguiente solo cuando estamos parados.
        Continuar y parar están siempre disponibles."""
        self._en_pausa = en_pausa
        for b in (self.back_btn, self.next_btn, self.record_btn):
            b.setEnabled(en_pausa)

    def _on_step_status(self, status: RunStatus):
        n = status.paso_idx + 1
        total = len(self.macro.pasos)
        self._set_controls_en_pausa(status.en_pausa)
        if status.en_pausa:
            estado = "punto de análisis" if status.es_breakpoint else "pausa"
            self.subtitle_label.setText(f"Paso {n}/{total} · {estado}")
        else:
            self.subtitle_label.setText(f"Paso {n}/{total} · reproduciendo…")
        # Aviso destacado al parar en un punto de análisis.
        if status.es_breakpoint and status.en_pausa:
            self.bp_label.setText(
                f"⏸ Punto de análisis en el paso {n}. "
                "F8 paso · F6 siguiente punto · 🔴 grabar aquí."
            )
            self.bp_label.setVisible(True)
        else:
            self.bp_label.setVisible(False)
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
        # Solo con el loop parado: avanzar mientras auto-reproduce no tiene
        # sentido y leería un estado en movimiento.
        if self._runner is None or not self._en_pausa:
            return
        self._runner.advance_step()

    def _on_continue(self):
        """Reanuda hasta el siguiente punto de análisis (o el final)."""
        if self._runner is None or not self._en_pausa:
            return
        self.bp_label.setVisible(False)
        self._runner.continue_run()

    def _on_back(self):
        """Retrocede el puntero un paso (para revisar / reejecutar).

        No deshace lo ya hecho en la aplicación, solo re-apunta al paso
        anterior; el siguiente ▶ lo volverá a ejecutar."""
        if self._runner is None or not self._en_pausa:
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
        if not self._en_pausa:
            # Solo se puede insertar con el loop parado: si no, step_index()
            # se mueve y mutaríamos macro.pasos a mitad de iteración.
            return
        idx_actual = self._runner.player.step_index()

        # Detener nuestras teclas globales mientras se graba: si no, F6-F8
        # dispararían acciones del step-through en vez de capturarse.
        self._stop_hotkeys()

        # Lanzamos el RecordDialog modal. El step-through se queda
        # esperando porque _runner.player no recibe advance_step.
        dlg = RecordDialog(parent=self)
        result = dlg.exec()
        if result and dlg.macro is not None and dlg.macro.pasos:
            nuevos = list(dlg.macro.pasos)
            insert_at = idx_actual + 1
            self.macro.pasos[insert_at:insert_at] = nuevos
            # Desplazar los breakpoints que estaban en/tras el punto de
            # inserción: sus índices se corren `len(nuevos)` posiciones.
            from core.debug_marks import shift_on_insert
            self._breakpoints = shift_on_insert(self._breakpoints, insert_at, len(nuevos))
            if self._runner and self._runner.player:
                self._runner.player.set_breakpoints(self._breakpoints)
            if self.on_macro_modified:
                self.on_macro_modified()
            self.action_label.setText(
                f"<b>{insert_at + 1}.</b> ➕ Insertados {len(nuevos)} pasos "
                "nuevos justo después del paso actual. Pulsa F8/▶."
            )
        # Reanudar las teclas globales tras la grabación.
        self._start_hotkeys()

    def _on_finished(self, summary: ReplaySummary):
        self.action_label.setText(
            f"<b>✓ Fin</b> · {summary.ok} OK · {summary.ko} KO"
        )
        self.next_btn.setEnabled(False)
        self.cont_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.bp_label.setVisible(False)
        self._stop_hotkeys()
        self.finished.emit()

    def _on_error(self, msg: str):
        self.action_label.setText(f"<span style='color:#e74c3c'>❌ {msg}</span>")
        self._stop_hotkeys()
        self.finished.emit()

    def closeEvent(self, event):
        self._stop_hotkeys()
        if self._runner:
            self._runner.abort()
        if self._thread and self._thread.isRunning():
            self._thread.wait(1000)
        super().closeEvent(event)
