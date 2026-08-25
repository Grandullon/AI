"""Step-through debugger flotante para la pestaña Macros.

Permite ejecutar una macro paso a paso, o con PUNTOS DE ANÁLISIS
(breakpoints): se auto-reproduce hasta el siguiente punto y ahí para.
En cada parada se puede grabar un paso nuevo en medio, avanzar paso a
paso, o saltar al siguiente punto.

Atajos GLOBALES (funcionan aunque el foco esté en la app que se
automatiza, no solo con MemoviPro enfocado):
    F8 = siguiente · F7 = atrás · F6 = continuar (al siguiente punto)
    F4 = saltar el paso sin ejecutarlo · F12 = repetirlo sin avanzar
    F9 = parar
Las pulsaciones con Alt/Ctrl se ignoran (para no confundir un Alt+F4 de
la aplicación con nuestro "saltar").
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
    QInputDialog,
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
QPushButton#skip { background-color: #7f8c8d; border-color: #616a6b; }
QPushButton#skip:hover { background-color: #95a5a6; }
QPushButton#repeat { background-color: #8e44ad; border-color: #6c3483; }
QPushButton#repeat:hover { background-color: #9b59b6; }
QPushButton#edit { background-color: #16a085; border-color: #117a65; }
QPushButton#edit:hover { background-color: #1abc9c; }
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
        start_idx: int = 0,
        bp_temporales: set[int] | None = None,
        parent=None,
    ):
        # Guardamos el padre ANTES de hacernos top-level: lo necesitamos
        # para localizar la ventana principal sin buscar por nombre de clase.
        self._owner = parent
        super().__init__(parent=None)  # top-level
        self.macro = macro
        self.screenshots_dir = screenshots_dir
        self.data_dir = data_dir
        self.on_macro_modified = on_macro_modified
        self.on_step_changed = on_step_changed
        self._breakpoints = {int(b) for b in (breakpoints or set())}
        # Breakpoints puestos por la sesión (p.ej. el de "▶ Hasta aquí"),
        # NO por el usuario: se desplazan igual que los demás pero el
        # editor los resta al final para no dejarlos marcados en la tabla.
        self._bp_temporales = {int(b) for b in (bp_temporales or set())}
        self._kb_listener = None
        # Modo de arranque según los puntos ALCANZABLES: los que quedan
        # antes de start_idx o están sobre pasos desactivados no dispararían
        # nunca, y sin este filtro la sesión se auto-reproducía entera.
        from core.debug_marks import decidir_run_mode
        self._run_mode = decidir_run_mode(
            self._breakpoints, start_idx, macro.pasos,
        )
        # ¿Estamos parados esperando al usuario? Grabar/avanzar/atrás solo
        # tienen sentido en pausa (si no, se leería un step_index en
        # movimiento y se mutaría macro.pasos a mitad de iteración).
        self._en_pausa = (self._run_mode == "step")  # en 'step' se pausa ya

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
        self.stop_btn = QPushButton("⏹ F9")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self._on_stop)
        btns.addWidget(self.stop_btn)
        layout.addLayout(btns)

        # Segunda fila: herramientas de edición en el punto de parada.
        btns2 = QHBoxLayout()
        btns2.setContentsMargins(0, 4, 0, 0)
        btns2.setSpacing(6)
        self.skip_btn = QPushButton("⏭ F4")
        self.skip_btn.setObjectName("skip")
        self.skip_btn.setToolTip("Saltar este paso SIN ejecutarlo")
        self.skip_btn.clicked.connect(self._on_skip)
        btns2.addWidget(self.skip_btn)
        self.repeat_btn = QPushButton("🔁 F12")
        self.repeat_btn.setObjectName("repeat")
        self.repeat_btn.setToolTip("Repetir este paso sin avanzar (para afinarlo)")
        self.repeat_btn.clicked.connect(self._on_repeat)
        btns2.addWidget(self.repeat_btn)
        self.record_btn = QPushButton("🔴 Grabar")
        self.record_btn.setObjectName("record")
        self.record_btn.setToolTip("Grabar pasos: insertar antes/después o reemplazar")
        self.record_btn.clicked.connect(self._on_record_here)
        btns2.addWidget(self.record_btn)
        self.edit_btn = QPushButton("✏️ Editar")
        self.edit_btn.setObjectName("edit")
        self.edit_btn.setToolTip("Abrir MemoviPro para editar la tabla sin perder la sesión")
        self.edit_btn.clicked.connect(self._on_edit_here)
        btns2.addWidget(self.edit_btn)
        layout.addLayout(btns2)

        # Estado inicial: si arrancamos auto-reproduciendo (hay breakpoints),
        # las acciones de edición empiezan deshabilitadas hasta la 1ª pausa.
        for b in (self.back_btn, self.next_btn, self.record_btn,
                  self.skip_btn, self.repeat_btn, self.edit_btn):
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
            start_idx=start_idx,
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
            "skip": self._on_skip,
            "repeat": self._on_repeat,
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
            _pynput_keyboard.Key.f4: "skip",
            _pynput_keyboard.Key.f12: "repeat",
        }

        # Modificadores cuya presencia significa que la tecla es un atajo
        # del SISTEMA o de la app (Alt+F4 para cerrar, Ctrl+F5...), no
        # nuestro. Sin esto, un Alt+F4 en la app depurada disparaba además
        # "saltar paso".
        K = _pynput_keyboard.Key
        mods = {K.alt, K.alt_l, K.alt_r, K.alt_gr,
                K.ctrl, K.ctrl_l, K.ctrl_r,
                K.cmd, K.cmd_l, K.cmd_r}
        self._mods_pulsados = set()

        def on_press(key):
            if key in mods:
                self._mods_pulsados.add(key)
                return
            if self._mods_pulsados:
                return  # es un atajo con modificador: no es para nosotros
            nombre = acciones.get(key)
            if nombre is not None:
                self._hotkey.emit(nombre)

        def on_release(key):
            self._mods_pulsados.discard(key)

        try:
            self._kb_listener = _pynput_keyboard.Listener(
                on_press=on_press, on_release=on_release,
            )
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
        for b in (self.back_btn, self.next_btn, self.record_btn,
                  self.skip_btn, self.repeat_btn, self.edit_btn):
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
        self._minimizar_principal()
        self._runner.advance_step()

    def _on_continue(self):
        """Reanuda hasta el siguiente punto de análisis (o el final)."""
        if self._runner is None or not self._en_pausa:
            return
        self.bp_label.setVisible(False)
        self._minimizar_principal()
        self._runner.continue_run()

    def _on_skip(self):
        """Salta este paso SIN ejecutarlo (ya lo hiciste a mano)."""
        if self._runner is None or not self._en_pausa:
            return
        self._minimizar_principal()
        self._runner.skip_step()

    def _on_repeat(self):
        """Repite este paso sin avanzar, para afinarlo."""
        if self._runner is None or not self._en_pausa:
            return
        self._minimizar_principal()
        self._runner.repeat_step()

    def _on_edit_here(self):
        """Restaura MemoviPro para editar la tabla sin cerrar la sesión.

        La sesión sigue pausada en el paso actual: cuando el usuario pulse
        ▶/⏭/🔁, la ventana principal se vuelve a minimizar sola."""
        if self._runner is None or not self._en_pausa:
            return
        main = self._main_window()
        if main is not None:
            try:
                main.showNormal()
                main.raise_()
                main.activateWindow()
            except Exception:
                pass
        self.raise_()  # el panel debe seguir visible por encima
        self.action_label.setText(
            "<b>✏️ Edición</b> — cambia lo que necesites en la tabla y "
            "pulsa <b>▶ F8</b> (o 🔁 F5) para seguir."
        )

    def _main_window(self):
        """Ventana principal de MemoviPro.

        Primero por el padre real (el StepEditor que nos creó); el escaneo
        por nombre de clase queda como último recurso."""
        owner = getattr(self, "_owner", None)
        if owner is not None:
            try:
                w = owner.window()
                if w is not None:
                    return w
            except Exception:
                pass
        try:
            from PyQt6.QtWidgets import QApplication
            for w in QApplication.topLevelWidgets():
                if w.__class__.__name__ == "MainWindow":
                    return w
        except Exception:
            pass
        return None

    def _minimizar_principal(self):
        """Vuelve a minimizar MemoviPro si el usuario lo restauró con
        ✏️ Editar (para no estorbar a la app que se automatiza)."""
        main = self._main_window()
        if main is None:
            return
        try:
            if not main.isMinimized():
                main.showMinimized()
        except Exception:
            pass

    def _on_back(self):
        """Retrocede el puntero un paso (para revisar / reejecutar).

        No deshace lo ya hecho en la aplicación, solo re-apunta al paso
        anterior; el siguiente ▶ lo volverá a ejecutar."""
        if self._runner is None or not self._en_pausa:
            return
        self._minimizar_principal()
        self._runner.step_back()

    def _on_stop(self):
        if self._runner:
            self._runner.abort()
        self.action_label.setText("<i>Detenido</i>")

    def _on_record_here(self):
        """Pausa el step-through y abre el grabador.

        Al terminar se elige qué hacer con lo capturado: insertar antes,
        insertar después o reemplazar N pasos (ver _integrar_grabacion)."""
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
            self._integrar_grabacion(list(dlg.macro.pasos), idx_actual)
        # Reanudar las teclas globales tras la grabación.
        self._start_hotkeys()

    def _integrar_grabacion(self, nuevos: list, idx_actual: int) -> None:
        """Pregunta QUÉ hacer con los pasos grabados e integra en la macro.

        Tres opciones (lo que faltaba: antes de esto solo se insertaba
        después):
          - Insertar DESPUÉS del paso actual
          - Insertar ANTES del paso actual
          - REEMPLAZAR N pasos a partir del actual
        """
        from core.debug_marks import shift_on_insert, shift_on_remove

        n = len(nuevos)
        puntero_a = None   # a dónde llevar el puntero al terminar
        msg = QMessageBox(self)
        msg.setWindowTitle("Pasos grabados")
        msg.setText(f"Se han capturado {n} paso(s) nuevo(s).")
        msg.setInformativeText(
            f"Estás parado en el paso {idx_actual + 1}. ¿Dónde los pongo?"
        )
        b_desp = msg.addButton("Insertar DESPUÉS", QMessageBox.ButtonRole.AcceptRole)
        b_antes = msg.addButton("Insertar ANTES", QMessageBox.ButtonRole.AcceptRole)
        b_reemp = msg.addButton("REEMPLAZAR pasos…", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        clic = msg.clickedButton()

        def _insertar(pos: int, cuantos_borrar: int = 0):
            """Aplica el cambio a la macro y desplaza AMBOS conjuntos de
            breakpoints (los del usuario y los temporales de la sesión)."""
            if cuantos_borrar:
                del self.macro.pasos[pos:pos + cuantos_borrar]
                for _ in range(cuantos_borrar):
                    self._breakpoints = shift_on_remove(self._breakpoints, pos)
                    self._bp_temporales = shift_on_remove(self._bp_temporales, pos)
            self.macro.pasos[pos:pos] = nuevos
            self._breakpoints = shift_on_insert(self._breakpoints, pos, n)
            self._bp_temporales = shift_on_insert(self._bp_temporales, pos, n)

        # Nota de semántica: los pasos grabados ya los acabas de hacer a
        # mano sobre la aplicación, así que al insertarlos ANTES o al
        # REEMPLAZAR dejamos el puntero DESPUÉS de ellos — no se
        # re-ejecutan. En "DESPUÉS" el paso actual aún no ha corrido, así
        # que se ejecuta él y luego los nuevos (es lo que pides al elegir
        # esa opción).
        if clic is b_desp:
            _insertar(idx_actual + 1)
            puntero_a = None       # el paso actual aún debe ejecutarse
            texto = f"➕ {n} paso(s) insertados DESPUÉS del {idx_actual + 1}."
        elif clic is b_antes:
            _insertar(idx_actual)
            # Puntero al paso original, que ahora está n posiciones abajo.
            puntero_a = idx_actual + n
            texto = (f"➕ {n} paso(s) insertados ANTES del {idx_actual + 1} "
                     "(no se repiten: ya los hiciste al grabar).")
        elif clic is b_reemp:
            restantes = len(self.macro.pasos) - idx_actual
            cuantos, ok = QInputDialog.getInt(
                self, "Reemplazar pasos",
                f"¿Cuántos pasos reemplazo a partir del {idx_actual + 1}?\n"
                f"(se borrarán y en su lugar irán los {n} grabados)",
                1, 1, max(1, restantes),
            )
            if not ok:
                return
            _insertar(idx_actual, cuantos_borrar=cuantos)
            # Puntero DESPUÉS de los nuevos: el paso viejo ya no existe y
            # los nuevos ya los hiciste al grabar.
            puntero_a = idx_actual + n
            texto = (f"♻️ {cuantos} paso(s) reemplazados por {n} nuevo(s) "
                     f"desde el {idx_actual + 1}.")
        else:
            return  # cancelado

        # OJO al orden: publicar los breakpoints nuevos ANTES de mover el
        # puntero, porque mover_puntero despierta al hilo del player y este
        # re-evaluaría la pausa con el conjunto viejo.
        if self._runner and self._runner.player:
            self._runner.player.set_breakpoints(self._breakpoints)
        if puntero_a is not None and self._runner and self._runner.player:
            self._runner.player.mover_puntero(puntero_a)
        if self.on_macro_modified:
            self.on_macro_modified()
        self.action_label.setText(f"<b>{texto}</b> Pulsa ▶ F8 para seguir.")

    def _on_finished(self, summary: ReplaySummary):
        self.action_label.setText(
            f"<b>✓ Fin</b> · {summary.ok} OK · {summary.ko} KO"
        )
        for b in (self.next_btn, self.cont_btn, self.record_btn,
                  self.back_btn, self.skip_btn, self.repeat_btn, self.edit_btn):
            b.setEnabled(False)
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
