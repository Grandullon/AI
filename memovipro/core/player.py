from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from pywinauto import Desktop, keyboard as pwkeyboard
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False

from .excel_logger import ExcelLogger, Incidencia
from .popup_watchdog import PopupEvent, PopupWatchdog
from .screenshot import capturar_pantalla_completa
from .step_model import Macro, Step, StepType, render_step


class StepFailed(Exception):
    def __init__(self, motivo: str, paso_idx: int, paso: Step, popup: PopupEvent | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.paso_idx = paso_idx
        self.paso = paso
        self.popup = popup


@dataclass
class RunStatus:
    dni: str
    paso_idx: int
    descripcion: str


class Player:
    """Reproductor paso a paso de una macro para un único DNI.

    El watchdog corre en hilo aparte y, si detecta un popup, lo anota en
    una cola interna que el bucle de pasos consulta tras cada paso.
    """

    def __init__(
        self,
        macro: Macro,
        screenshots_dir: str | Path,
        logger: ExcelLogger,
        ignorar_popups: list[str] | None = None,
        polling_watchdog_ms: int = 300,
        on_status: Callable[[RunStatus], None] | None = None,
    ):
        self.macro = macro
        self.screenshots_dir = Path(screenshots_dir)
        self.logger = logger
        self.ignorar_popups = ignorar_popups or []
        self.polling_watchdog_ms = polling_watchdog_ms
        self.on_status = on_status
        self._popup_lock = threading.Lock()
        self._popup_pendiente: PopupEvent | None = None
        self._watchdog: PopupWatchdog | None = None
        self._abort = threading.Event()

    def abort(self) -> None:
        self._abort.set()

    def _on_popup(self, evt: PopupEvent) -> None:
        with self._popup_lock:
            self._popup_pendiente = evt

    def _consumir_popup(self) -> PopupEvent | None:
        with self._popup_lock:
            evt = self._popup_pendiente
            self._popup_pendiente = None
            return evt

    def ejecutar_dni(self, fila: dict) -> tuple[bool, list[Incidencia]]:
        """Reproduce la macro para un DNI. Devuelve (exito, incidencias_generadas)."""
        if not _HAS_PYWINAUTO:
            raise RuntimeError("pywinauto no disponible (solo Windows)")

        ctx = {k.upper(): str(v) for k, v in fila.items()}
        dni = ctx.get("DNI", "")
        incidencias: list[Incidencia] = []

        self._watchdog = PopupWatchdog(
            screenshots_dir=self.screenshots_dir,
            on_popup=self._on_popup,
            polling_ms=self.polling_watchdog_ms,
            ignorar_titulos=self.ignorar_popups,
            cerrar_automaticamente=True,
        )
        self._watchdog.start()

        try:
            for idx, paso in enumerate(self.macro.pasos):
                if self._abort.is_set():
                    break
                paso_render = render_step(paso, ctx)
                if self.on_status:
                    self.on_status(RunStatus(dni=dni, paso_idx=idx, descripcion=paso_render.descripcion or paso_render.tipo.value))
                try:
                    self._ejecutar_paso(paso_render, idx)
                except StepFailed as exc:
                    if paso.opcional:
                        continue
                    inc = self._registrar_fallo(dni, idx, paso_render, exc)
                    incidencias.append(inc)
                    return False, incidencias

                evt = self._consumir_popup()
                if evt is not None:
                    inc = self._registrar_popup(dni, idx, paso_render, evt)
                    incidencias.append(inc)
                    return False, incidencias

            return True, incidencias
        finally:
            if self._watchdog:
                self._watchdog.stop()
                self._watchdog.join(timeout=1.0)
                self._watchdog = None

    def _ejecutar_paso(self, paso: Step, idx: int) -> None:
        intentos = paso.reintentos + 1
        last_err: Exception | None = None
        for intento in range(intentos):
            try:
                self._dispatch(paso)
                return
            except Exception as exc:
                last_err = exc
                time.sleep(min(0.5 * (2 ** intento), 4.0))
        raise StepFailed(motivo=f"{type(last_err).__name__}: {last_err}", paso_idx=idx, paso=paso)

    def _dispatch(self, paso: Step) -> None:
        tipo = paso.tipo
        if tipo == StepType.SLEEP:
            time.sleep(float(paso.valor or "0"))
            return
        if tipo == StepType.FOCUS_WINDOW:
            self._focus_window(paso.titulo or self.macro.ventana_principal)
            return
        if tipo == StepType.WAIT_FOR_WINDOW:
            self._wait_for_window(paso.titulo or "", paso.timeout_s)
            return
        if tipo == StepType.CLICK_CONTROL:
            self._click_control(paso)
            return
        if tipo == StepType.CLICK_AT_XY:
            x, y = int(paso.extra.get("x", 0)), int(paso.extra.get("y", 0))
            self._click_xy(x, y)
            return
        if tipo == StepType.TYPE_TEXT:
            self._type_text(paso)
            return
        if tipo == StepType.SEND_KEYS:
            pwkeyboard.send_keys(paso.valor or "")
            return
        if tipo == StepType.WAIT_UNTIL:
            self._wait_until(paso)
            return
        if tipo == StepType.CLOSE_WINDOW:
            self._focus_window(paso.titulo or self.macro.ventana_principal).close()
            return
        if tipo == StepType.HANDLE_LIBREOFFICE_SAVE:
            from .libreoffice import handle_save_as
            handle_save_as(
                nombre_destino=paso.valor or "",
                carpeta=paso.extra.get("carpeta", ""),
                timeout_s=paso.timeout_s,
            )
            return
        raise ValueError(f"Tipo de paso no soportado: {tipo}")

    def _focus_window(self, titulo: str):
        win = Desktop(backend="uia").window(title_re=f".*{titulo}.*") if titulo else None
        if win is None or not win.exists():
            raise RuntimeError(f"Ventana no encontrada: {titulo}")
        win.set_focus()
        return win

    def _wait_for_window(self, titulo: str, timeout_s: float) -> None:
        win = Desktop(backend="uia").window(title_re=f".*{titulo}.*")
        win.wait("visible", timeout=timeout_s)
        win.set_focus()

    def _resolve_control(self, paso: Step):
        sel = paso.selector
        if sel is None or sel.is_empty():
            raise ValueError("Paso click_control sin selector")
        win = self._focus_window(self.macro.ventana_principal) if self.macro.ventana_principal else Desktop(backend="uia")
        kwargs = {}
        if sel.name:
            kwargs["title"] = sel.name
        if sel.control_type:
            kwargs["control_type"] = sel.control_type
        if sel.auto_id:
            kwargs["auto_id"] = sel.auto_id
        if sel.class_name:
            kwargs["class_name"] = sel.class_name
        ctrl = win.child_window(**kwargs)
        ctrl.wait("visible enabled", timeout=paso.timeout_s)
        return ctrl

    def _click_control(self, paso: Step) -> None:
        ctrl = self._resolve_control(paso)
        ctrl.click_input()

    def _click_xy(self, x: int, y: int) -> None:
        from pywinauto import mouse
        mouse.click(coords=(x, y))

    def _type_text(self, paso: Step) -> None:
        if paso.selector and not paso.selector.is_empty():
            ctrl = self._resolve_control(paso)
            ctrl.set_focus()
        pwkeyboard.send_keys(paso.valor or "", with_spaces=True, pause=0.02)

    def _wait_until(self, paso: Step) -> None:
        cond = paso.extra.get("condicion") or {}
        kind = cond.get("tipo", "control_visible")
        if kind == "control_visible":
            tmp = Step(
                tipo=StepType.CLICK_CONTROL,
                selector=paso.selector,
                timeout_s=paso.timeout_s,
            )
            self._resolve_control(tmp)
            return
        time.sleep(float(cond.get("segundos", 1.0)))

    def _registrar_fallo(self, dni: str, idx: int, paso: Step, exc: StepFailed) -> Incidencia:
        shot = capturar_pantalla_completa(self.screenshots_dir, prefijo=f"fallo_{dni}_{idx}")
        inc = Incidencia(
            dni=dni,
            macro=self.macro.nombre,
            paso_idx=idx,
            paso_tipo=paso.tipo.value,
            tipo_error="EXCEPCION_PASO",
            titulo_popup="",
            texto_popup="",
            screenshot_path=str(shot) if shot else "",
            estado="ERROR",
            detalle=exc.motivo,
        )
        self.logger.append(inc)
        return inc

    def _registrar_popup(self, dni: str, idx: int, paso: Step, evt: PopupEvent) -> Incidencia:
        inc = Incidencia(
            dni=dni,
            macro=self.macro.nombre,
            paso_idx=idx,
            paso_tipo=paso.tipo.value,
            tipo_error="POPUP",
            titulo_popup=evt.titulo,
            texto_popup=evt.texto,
            screenshot_path=evt.screenshot_path,
            estado="ERROR",
            detalle=f"class={evt.class_name}",
        )
        self.logger.append(inc)
        return inc
