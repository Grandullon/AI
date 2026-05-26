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
    Desktop = None  # placeholder para tests (monkeypatch)
    pwkeyboard = None

from loguru import logger

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
        dry_run: bool = False,
        velocidad: float = 1.0,
        step_mode: bool = False,
    ):
        self.macro = macro
        self.screenshots_dir = Path(screenshots_dir)
        self.logger = logger
        self.ignorar_popups = ignorar_popups or []
        self.polling_watchdog_ms = polling_watchdog_ms
        self.on_status = on_status
        self.dry_run = dry_run
        # velocidad: 1.0 = original. 2.0 = el doble de rápido (delays /2).
        # 0.5 = el doble de lento. 0 o negativo = sin pausas.
        self.velocidad = velocidad
        self._popup_lock = threading.Lock()
        self._popup_pendiente: PopupEvent | None = None
        self._watchdog: PopupWatchdog | None = None
        self._abort = threading.Event()
        # Cache del último anchor para no machacar UIA en cada paso.
        self._last_anchor_ts: float = 0.0
        self._anchor_min_interval_s: float = 0.5
        # Modificadores pulsados actualmente (entre pasos). Permite mantener
        # Ctrl/Shift/Alt presionado durante secuencias largas como
        # "Ctrl+Click en 30 elementos" sin soltarlo entre clic y clic.
        self._modifiers_held: set[str] = set()
        # Pausa solicitada externamente (panel de control). El loop principal
        # se queda esperando aquí sin avanzar.
        self._paused = threading.Event()
        # Modo step-through: si True, el loop bloquea antes de cada paso
        # esperando a que alguien llame a advance_step(). Usado por la
        # pestaña Macros → "🐞 Paso a paso" para que el usuario pueda
        # añadir nuevos pasos en mitad del recorrido.
        self._step_mode = bool(step_mode)
        self._step_continue = threading.Event()
        self._step_idx: int = 0

    def abort(self) -> None:
        self._abort.set()
        # Si está pausado, despertar para que vea el abort.
        self._paused.clear()
        # En modo step, desbloquear el wait inmediatamente.
        self._step_continue.set()

    def pause(self) -> None:
        """Solicita pausa. El loop esperará antes del siguiente paso."""
        self._paused.set()
        logger.info("Player pausado")

    def resume(self) -> None:
        """Cancela la pausa."""
        self._paused.clear()
        logger.info("Player reanudado")

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def advance_step(self) -> None:
        """En modo step-through, indica al loop que avance al siguiente paso."""
        self._step_continue.set()

    def step_index(self) -> int:
        """Índice del paso actualmente apuntado (0-based)."""
        return self._step_idx

    def _esperar_si_pausado(self) -> None:
        """Bloquea (con tramos cortos) mientras esté pausado."""
        while self._paused.is_set() and not self._abort.is_set():
            time.sleep(0.1)

    def _esperar_step(self) -> None:
        """En modo step, espera a que advance_step() / abort() suelte el wait."""
        if not self._step_mode:
            return
        self._step_continue.clear()
        # Timeout largo: 1h. Si en una hora no se ha pulsado "Siguiente"
        # ni "Parar", asumimos abandono.
        self._step_continue.wait(timeout=3600.0)
        self._step_continue.clear()

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
            cerrar_automaticamente=not self.dry_run,
        )
        self._watchdog.start()
        logger.info("Iniciando DNI={} · macro={} · dry_run={}", dni, self.macro.nombre, self.dry_run)

        try:
            # Anchor inicial: traer la ventana objetivo al frente y maximizar.
            if self.macro.auto_anchor and self.macro.ventana_principal:
                self._asegurar_ventana_objetivo(force=True)

            # Bucle con índice dinámico (en vez de for+enumerate) para
            # soportar inserción/borrado en self.macro.pasos durante la
            # ejecución (caso del step-through: el usuario añade pasos
            # nuevos en mitad del flujo).
            self._step_idx = 0
            while self._step_idx < len(self.macro.pasos):
                idx = self._step_idx
                paso = self.macro.pasos[idx]
                if self._abort.is_set():
                    break
                # Esperar si está en pausa.
                self._esperar_si_pausado()
                if self._abort.is_set():
                    break
                # En modo step, esperar a que el usuario pulse "Siguiente".
                # Notificamos ANTES del wait para que la UI pueda mostrar
                # qué paso está a punto de ejecutarse.
                paso_render = render_step(paso, ctx)
                if self._step_mode and self.on_status:
                    self.on_status(RunStatus(dni=dni, paso_idx=idx, descripcion=paso_render.descripcion or paso_render.tipo.value))
                self._esperar_step()
                if self._abort.is_set():
                    break
                # Control de flujo: IF_VENTANA decide cuántos pasos avanzar
                # (ejecutar el bloque "then" o saltarlo). No es una acción
                # de UI, así que se resuelve aquí y saltamos el resto.
                if paso_render.tipo == StepType.IF_VENTANA:
                    self._step_idx += self._evaluar_if(paso_render)
                    continue
                # Respetar el delay grabado, ajustado por velocidad.
                self._esperar_delay(paso_render)
                if self._abort.is_set():
                    break
                # Re-anchor antes de cada paso (con throttling).
                if self.macro.auto_anchor and self.macro.ventana_principal:
                    self._asegurar_ventana_objetivo()
                # Ajustar modificadores pulsados al objetivo del paso.
                target_mods = self._target_modifiers(paso_render)
                self._adjust_modifiers(target_mods)
                if not self._step_mode and self.on_status:
                    self.on_status(RunStatus(dni=dni, paso_idx=idx, descripcion=paso_render.descripcion or paso_render.tipo.value))
                try:
                    self._ejecutar_paso(paso_render, idx)
                except StepFailed as exc:
                    if paso.opcional:
                        self._step_idx += 1
                        continue
                    inc = self._registrar_fallo(dni, idx, paso_render, exc)
                    incidencias.append(inc)
                    return False, incidencias

                evt = self._consumir_popup()
                if evt is not None:
                    inc = self._registrar_popup(dni, idx, paso_render, evt)
                    incidencias.append(inc)
                    return False, incidencias

                # Verificación post-paso: si el paso pide esperar a que
                # aparezca una ventana, lo hacemos. Si no aparece a tiempo,
                # es una incidencia clara (en vez de seguir clicando en
                # vacío y fallar 5 pasos después sin saber por qué).
                if paso_render.verificar_ventana and not self._abort.is_set():
                    if not self._esperar_aparezca_ventana(
                        paso_render.verificar_ventana, paso_render.verificar_timeout_s
                    ):
                        if not paso.opcional:
                            exc = StepFailed(
                                motivo=(
                                    f"Verificación fallida: la ventana "
                                    f"'{paso_render.verificar_ventana}' no apareció "
                                    f"en {paso_render.verificar_timeout_s:g}s"
                                ),
                                paso_idx=idx, paso=paso_render,
                            )
                            inc = self._registrar_fallo(dni, idx, paso_render, exc)
                            incidencias.append(inc)
                            return False, incidencias

                # Avanzar al siguiente paso (si durante la ejecución se
                # insertaron pasos en macro.pasos en posición idx+1, el
                # bucle los recogerá automáticamente).
                self._step_idx += 1

            return True, incidencias
        finally:
            # Soltar siempre cualquier modificador que hayamos dejado pulsado.
            try:
                self._adjust_modifiers(set())
            except Exception:
                pass
            if self._watchdog:
                self._watchdog.stop()
                self._watchdog.join(timeout=1.0)
                self._watchdog = None

    def _esperar_delay(self, paso: Step) -> None:
        """Espera `paso.delay_before_s / velocidad` antes del paso.

        Si velocidad <= 0 se omiten las pausas. El sleep se hace en
        tramos cortos para poder responder a abort sin esperas largas.
        Cap de seguridad: nunca más de 1 hora entre dos pasos (por si
        alguien edita el YAML a mano con un valor descomunal).
        """
        if paso.delay_before_s <= 0 or self.velocidad <= 0:
            return
        restante = paso.delay_before_s / self.velocidad
        # Sanity cap: 1 hora. El cap "razonable" para grabaciones está
        # en Recorder.MAX_DELAY_S (30 min). Este es por si el YAML viene
        # editado a mano con algo absurdo.
        restante = min(restante, 3600.0)
        if restante > 5.0:
            logger.info(
                "Esperando {:.1f}s antes del siguiente paso ({})",
                restante, paso.descripcion or paso.tipo.value,
            )
        while restante > 0:
            if self._abort.is_set():
                return
            paso_t = min(0.2, restante)
            time.sleep(paso_t)
            restante -= paso_t

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
            extra = paso.extra or {}
            x, y = int(extra.get("x", 0)), int(extra.get("y", 0))
            button = str(extra.get("button", "left"))
            double = bool(extra.get("double", False))
            self._click_xy(x, y, button=button, double=double)
            return
        if tipo == StepType.TYPE_TEXT:
            self._type_text(paso)
            return
        if tipo == StepType.SEND_KEYS:
            if self.dry_run:
                logger.info("[dry-run] send_keys → {}", paso.valor)
                return
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
        if tipo == StepType.WINDOW_ENSURE:
            extra = paso.extra or {}
            title_re = paso.titulo or self.macro.ventana_principal
            state = str(extra.get("state", "maximized"))
            self._asegurar_ventana_objetivo(
                title_re=title_re, state=state, force=True, timeout_s=paso.timeout_s,
            )
            return
        if tipo == StepType.SCROLL:
            extra = paso.extra or {}
            x, y = int(extra.get("x", 0)), int(extra.get("y", 0))
            dx, dy = int(extra.get("dx", 0)), int(extra.get("dy", 0))
            self._scroll_xy(x, y, dx, dy)
            return
        if tipo == StepType.DRAG:
            extra = paso.extra or {}
            x1, y1 = int(extra.get("x1", 0)), int(extra.get("y1", 0))
            x2, y2 = int(extra.get("x2", 0)), int(extra.get("y2", 0))
            button = str(extra.get("button", "left"))
            self._drag_xy(x1, y1, x2, y2, button=button)
            return
        if tipo == StepType.LAUNCH_PROGRAM:
            cmd = (paso.valor or "").strip()
            if not cmd:
                raise ValueError("launch_program sin valor (ruta al .exe)")
            extra = paso.extra or {}
            args = list(extra.get("args", []))
            self._launch_program(cmd, args)
            return
        raise ValueError(f"Tipo de paso no soportado: {tipo}")

    def _launch_program(self, cmd: str, args: list) -> None:
        """Lanza un programa externo. Si hay args usa subprocess; si no,
        os.startfile() (que entiende .exe, .lnk, .url, .bat, ...)."""
        if self.dry_run:
            logger.info("[dry-run] launch_program: {} {}", cmd, args)
            return
        try:
            if args:
                import subprocess
                subprocess.Popen([cmd, *args])
                logger.info("Lanzado (subprocess): {} {}", cmd, args)
            else:
                import os as _os
                _os.startfile(cmd)
                logger.info("Lanzado (startfile): {}", cmd)
        except Exception as exc:
            raise RuntimeError(f"No se pudo lanzar '{cmd}': {exc}")

    def _scroll_xy(self, x: int, y: int, dx: int, dy: int) -> None:
        if self.dry_run:
            logger.info("[dry-run] scroll en ({}, {}) dx={} dy={}", x, y, dx, dy)
            time.sleep(0.15)
            return
        from pywinauto import mouse
        # pywinauto.mouse.scroll: wheel_dist positivo = arriba, negativo = abajo.
        # Usamos dy como cantidad principal (vertical es 99% del scroll real).
        wheel = dy if dy != 0 else dx
        try:
            mouse.scroll(coords=(x, y), wheel_dist=wheel)
        except Exception as exc:
            logger.warning("Fallo scroll en ({},{}): {}", x, y, exc)

    def _drag_xy(self, x1: int, y1: int, x2: int, y2: int, button: str = "left") -> None:
        if self.dry_run:
            logger.info(
                "[dry-run] drag de ({},{}) a ({},{}) [button={}]",
                x1, y1, x2, y2, button,
            )
            time.sleep(0.3)
            return
        from pywinauto import mouse
        try:
            mouse.press(button=button, coords=(x1, y1))
            time.sleep(0.05)
            mouse.move(coords=(x2, y2))
            time.sleep(0.05)
            mouse.release(button=button, coords=(x2, y2))
        except Exception as exc:
            logger.warning("Fallo drag de ({},{}) a ({},{}): {}", x1, y1, x2, y2, exc)
            # Asegurar release si press tuvo éxito
            try:
                mouse.release(button=button, coords=(x2, y2))
            except Exception:
                pass

    def _asegurar_ventana_objetivo(
        self,
        title_re: str | None = None,
        state: str = "maximized",
        force: bool = False,
        timeout_s: float = 5.0,
    ) -> None:
        """Asegura que la ventana objetivo está al frente y en el estado pedido.

        Wrapper sobre `core.window_utils.asegurar_ventana` que añade el
        cache/throttling (no rehacer si pasaron <0.5s) y el manejo de
        dry-run. La lógica real de pywinauto vive en el módulo
        `window_utils` para que pueda usarse también desde la UI (botón
        "Probar patrón" de la plantilla arranque).
        """
        title = title_re or self.macro.ventana_principal
        if not title:
            return
        ahora = time.time()
        if not force and (ahora - self._last_anchor_ts) < self._anchor_min_interval_s:
            return
        from .window_utils import asegurar_ventana
        ok, msg = asegurar_ventana(title, state=state, timeout_s=timeout_s, dry_run=self.dry_run)
        if ok:
            self._last_anchor_ts = ahora
            logger.debug("Anchor OK: {}", msg)
        else:
            logger.debug("Anchor falló para '{}': {}", title, msg)

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

    def _evaluar_if(self, paso: Step) -> int:
        """Evalúa un paso IF_VENTANA y devuelve cuántas posiciones avanzar.

        extra:
          - ventana: patrón de título (regex parcial)
          - negar: si True, la condición es "NO existe la ventana"
          - saltar_si_no: nº de pasos del bloque "then" a saltar si la
            condición NO se cumple.

        Devuelve:
          - 1  → la condición se cumple: ejecutar el bloque siguiente.
          - 1 + saltar_si_no → no se cumple: saltar el bloque.
        """
        extra = paso.extra or {}
        patron = str(extra.get("ventana", ""))
        negar = bool(extra.get("negar", False))
        saltar = max(0, int(extra.get("saltar_si_no", 0)))
        if self.dry_run:
            logger.info("[dry-run] if_ventana '{}' negar={} saltar={}", patron, negar, saltar)
            return 1
        from .window_utils import existe_ventana
        existe = existe_ventana(patron, timeout_s=0.5) if patron else False
        condicion = (existe != negar)  # XOR: negar invierte
        logger.info(
            "if_ventana '{}': existe={} negar={} → condicion={} ({})",
            patron, existe, negar, condicion,
            "ejecuta bloque" if condicion else f"salta {saltar} pasos",
        )
        return 1 if condicion else (1 + saltar)

    def _esperar_aparezca_ventana(self, title_re: str, timeout_s: float) -> bool:
        """Espera (polling) a que exista una ventana que matchee el patrón.

        Devuelve True si aparece, False si se agota el timeout. Si no hay
        pywinauto (no Windows), devuelve True para no bloquear (no podemos
        verificar). Respeta abort.
        """
        if self.dry_run:
            logger.info("[dry-run] verificar ventana '{}'", title_re)
            return True
        from .window_utils import existe_ventana, _HAS_PYWINAUTO as _HAS
        if not _HAS:
            return True
        fin = time.time() + max(0.5, timeout_s)
        while time.time() < fin:
            if self._abort.is_set():
                return False
            if existe_ventana(title_re, timeout_s=0.3):
                logger.debug("Verificación OK: apareció '{}'", title_re)
                return True
            time.sleep(0.3)
        logger.warning("Verificación: '{}' NO apareció en {}s", title_re, timeout_s)
        return False

    def _resolve_control(self, paso: Step):
        """Resuelve el control objetivo por selector simbólico.

        Solo se llama cuando hay `ventana_principal` configurada en la
        macro. Sin ventana de referencia, la API de pywinauto no es
        fiable (Desktop().windows() devuelve UIAWrapper sin
        child_window), así que en ese caso usamos directamente las
        coordenadas (`fallback_xy`) en `_click_control`.
        """
        sel = paso.selector
        if sel is None or sel.is_empty():
            raise ValueError("Paso click_control sin selector")

        kwargs = {}
        if sel.name:
            kwargs["title"] = sel.name
        if sel.control_type:
            kwargs["control_type"] = sel.control_type
        if sel.auto_id:
            kwargs["auto_id"] = sel.auto_id
        if sel.class_name:
            kwargs["class_name"] = sel.class_name

        desktop = Desktop(backend="uia")

        if self.macro.ventana_principal:
            win_spec = desktop.window(title_re=f".*{self.macro.ventana_principal}.*")
            ctrl = win_spec.child_window(**kwargs)
            ctrl.wait("visible enabled", timeout=paso.timeout_s)
            return ctrl

        # Sin ventana_principal: iterar y pasar handle a Desktop().window()
        # para obtener un WindowSpecification válido (que sí tiene child_window).
        last_err: Exception | None = None
        for w in desktop.windows():
            try:
                if not w.is_visible():
                    continue
                handle = w.handle
            except Exception:
                continue
            try:
                spec = desktop.window(handle=handle)
                ctrl = spec.child_window(**kwargs)
                if ctrl.exists(timeout=0.3):
                    try:
                        ctrl.wait("visible enabled", timeout=min(paso.timeout_s, 3.0))
                    except Exception:
                        pass
                    return ctrl
            except Exception as exc:
                last_err = exc
                continue
        raise RuntimeError(f"No se encontró control {kwargs}: {last_err}")

    def _click_control(self, paso: Step) -> None:
        """Hace clic respetando una jerarquía de estrategias:

        1. Si la macro tiene `ventana_principal`: probar resolución
           simbólica (más robusta a cambios de posición/tamaño).
        2. Si no, o si la resolución falla, ir a `fallback_xy` (las
           coordenadas exactas que se grabaron).
        3. Si no hay ni una cosa ni la otra, lanzar excepción.

        Honra `extra.button` ('left' / 'right' / 'middle') y
        `extra.double` (bool) para reproducir el clic exacto que se
        capturó: doble clic, clic derecho, etc.
        """
        extra = paso.extra or {}
        fallback = extra.get("fallback_xy")
        win_rel = extra.get("win_rel")
        img_b64 = extra.get("img_b64")
        button = str(extra.get("button", "left"))
        double = bool(extra.get("double", False))

        # Sin ventana_principal: usar la mejor estrategia disponible.
        # Orden: relativas a ventana → matching por imagen → absolutas.
        if not self.macro.ventana_principal:
            if win_rel and self._click_window_relative(win_rel, button=button, double=double):
                return
            if img_b64 and self._click_imagen(img_b64, button=button, double=double):
                return
            if fallback and len(fallback) == 2:
                x, y = int(fallback[0]), int(fallback[1])
                self._click_xy(x, y, button=button, double=double)
                return

        try:
            ctrl = self._resolve_control(paso)
        except Exception as exc:
            # Fallback en cascada: relativa a ventana → imagen → absoluta.
            if win_rel and self._click_window_relative(win_rel, button=button, double=double):
                logger.warning("Selector no resuelto, fallback a coords relativas a ventana: {}", exc)
                return
            if img_b64 and self._click_imagen(img_b64, button=button, double=double):
                logger.warning("Selector no resuelto, fallback a matching por imagen: {}", exc)
                return
            if fallback and len(fallback) == 2:
                x, y = int(fallback[0]), int(fallback[1])
                logger.warning("Selector no resuelto, fallback a ({},{}): {}", x, y, exc)
                self._click_xy(x, y, button=button, double=double)
                return
            raise
        if self.dry_run:
            try:
                ctrl.draw_outline(colour="red", thickness=3)
            except Exception:
                pass
            logger.info(
                "[dry-run] {} {} → {}",
                "double_click_input" if double else "click_input",
                f"button={button}",
                paso.descripcion or paso.selector,
            )
            time.sleep(0.4)
            return
        if double:
            ctrl.double_click_input(button=button)
        else:
            ctrl.click_input(button=button)

    def _click_window_relative(self, win_rel: dict, button: str = "left", double: bool = False) -> bool:
        """Hace clic usando coordenadas relativas a una ventana.

        Busca la ventana por título (regex parcial), obtiene su rectángulo
        ACTUAL y calcula el punto absoluto a partir de las fracciones
        fx/fy capturadas al grabar. Sobrevive a que la ventana se haya
        movido, redimensionado o cambiado de escalado DPI.

        Devuelve True si pudo clicar, False si no encontró la ventana
        (para que el caller pase al siguiente fallback).
        """
        if not win_rel:
            return False
        title = str(win_rel.get("title", ""))
        if not title:
            return False
        try:
            fx = float(win_rel.get("fx", 0.0))
            fy = float(win_rel.get("fy", 0.0))
        except (TypeError, ValueError):
            return False
        if self.dry_run:
            logger.info("[dry-run] click relativo a ventana '{}' fx={} fy={}", title, fx, fy)
            return True
        if not _HAS_PYWINAUTO:
            return False
        try:
            win = Desktop(backend="uia").window(title_re=f".*{title}.*")
            if not win.exists(timeout=1.0):
                return False
            r = win.rectangle()
            x = int(r.left + fx * r.width())
            y = int(r.top + fy * r.height())
        except Exception as exc:
            logger.debug("click_window_relative falló para '{}': {}", title, exc)
            return False
        self._click_xy(x, y, button=button, double=double)
        return True

    def _click_imagen(self, img_b64: str, button: str = "left", double: bool = False) -> bool:
        """Busca el thumbnail en pantalla y clica en su centro.

        Devuelve True si lo encontró y clicó, False si no (para seguir
        con el siguiente fallback). El más robusto: encuentra el control
        visualmente esté donde esté la ventana.
        """
        if not img_b64:
            return False
        if self.dry_run:
            logger.info("[dry-run] click por imagen (matching)")
            return True
        try:
            from .image_match import buscar_en_pantalla
        except Exception:
            return False
        punto = buscar_en_pantalla(img_b64)
        if punto is None:
            return False
        x, y = punto
        logger.info("Matching por imagen encontró el control en ({}, {})", x, y)
        self._click_xy(x, y, button=button, double=double)
        return True

    def _click_xy(self, x: int, y: int, button: str = "left", double: bool = False) -> None:
        if self.dry_run:
            logger.info(
                "[dry-run] {} at ({}, {}) [button={}]",
                "double_click" if double else "click", x, y, button,
            )
            time.sleep(0.2)
            return
        from pywinauto import mouse
        if double:
            mouse.double_click(button=button, coords=(x, y))
        else:
            mouse.click(button=button, coords=(x, y))

    def _type_text(self, paso: Step) -> None:
        if paso.selector and not paso.selector.is_empty():
            ctrl = self._resolve_control(paso)
            if self.dry_run:
                try:
                    ctrl.draw_outline(colour="blue", thickness=3)
                except Exception:
                    pass
                logger.info('[dry-run] type_text "{}" en {}', paso.valor, paso.selector)
                time.sleep(0.4)
                return
            ctrl.set_focus()
        elif self.dry_run:
            logger.info('[dry-run] type_text "{}"', paso.valor)
            return
        from .keyboard_utils import escape_send_keys
        # Escapar { } ( ) + ^ % ~ para teclear el texto LITERAL (no como
        # sintaxis de send_keys). Crítico para contraseñas con símbolos.
        pwkeyboard.send_keys(escape_send_keys(paso.valor or ""), with_spaces=True, pause=0.02)

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

    # ---- Modificadores (Ctrl/Shift/Alt) mantenidos entre pasos ----

    _MOD_VK = {"ctrl": "VK_CONTROL", "shift": "VK_SHIFT", "alt": "VK_MENU"}

    @staticmethod
    def _target_modifiers(paso: Step) -> set[str]:
        """Lee el campo `extra.modifiers` ('ctrl+shift') y lo convierte a set."""
        if not paso.extra:
            return set()
        raw = str(paso.extra.get("modifiers", "")).lower()
        if not raw:
            return set()
        return {m.strip() for m in raw.split("+") if m.strip() in ("ctrl", "shift", "alt")}

    def _adjust_modifiers(self, target: set[str]) -> None:
        """Pulsa/suelta solo los modificadores que cambian.

        Antes de cada paso, el player se asegura de que estén pulsadas
        exactamente las teclas del set `target`. Si `target == self._modifiers_held`
        no hace nada — esa es la clave para que un Ctrl+Click ×30 mantenga
        Ctrl pulsado durante toda la secuencia.
        """
        if not _HAS_PYWINAUTO:
            return
        if target == self._modifiers_held:
            return
        a_soltar = self._modifiers_held - target
        a_pulsar = target - self._modifiers_held
        for m in a_soltar:
            vk = self._MOD_VK.get(m)
            if not vk:
                continue
            try:
                pwkeyboard.send_keys("{" + vk + " up}")
                logger.debug("Soltar modificador {}", m)
            except Exception as exc:
                logger.debug("Error soltando {}: {}", m, exc)
        for m in a_pulsar:
            vk = self._MOD_VK.get(m)
            if not vk:
                continue
            try:
                pwkeyboard.send_keys("{" + vk + " down}")
                logger.debug("Pulsar modificador {}", m)
            except Exception as exc:
                logger.debug("Error pulsando {}: {}", m, exc)
        self._modifiers_held = set(target)

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
