"""ReplayRunner: ejecuta la misma macro N veces a una velocidad dada.

Versión "simple" del MacroRunner: sin Excel, sin checkpoints, sin
sustitución de DNIs. Cada iteración produce un OK o un KO, con la
información del popup (si lo hubo) registrada en
`incidencias_YYYYMMDD.xlsx`.

Sigue usando:
- El watchdog de popups, que es el corazón del proyecto.
- El ExcelLogger acumulativo de incidencias.
- La columna "DNI" del log se rellena con "iter_<n>" para que sea
  trazable a qué pasada falló.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from .excel_logger import ExcelLogger, default_log_path
from .player import Player, RunStatus
from .step_model import Macro


@dataclass
class ReplaySummary:
    total: int
    ok: int
    ko: int
    log_path: str
    iters_ok: list[int] = field(default_factory=list)
    iters_ko: list[tuple[int, str]] = field(default_factory=list)


class ReplayRunner:
    def __init__(
        self,
        macro: Macro,
        veces: int,
        velocidad: float,
        screenshots_dir: str | Path,
        data_dir: str | Path = "data",
        polling_watchdog_ms: int = 300,
        ignorar_popups: list[str] | None = None,
        watchdog_activo: bool = True,
        on_status: Callable[[RunStatus], None] | None = None,
        on_iter_done: Callable[[int, bool, str], None] | None = None,
        step_mode: bool = False,
    ):
        self.macro = macro
        self.veces = max(1, int(veces))
        self.velocidad = velocidad
        self.screenshots_dir = Path(screenshots_dir)
        self.data_dir = Path(data_dir)
        self.log_path = default_log_path(self.data_dir)
        self.excel_logger = ExcelLogger(self.log_path)
        self.polling_watchdog_ms = polling_watchdog_ms if watchdog_activo else 60_000
        self.watchdog_activo = watchdog_activo
        self.ignorar_popups = ignorar_popups or []
        self.on_status = on_status
        self.on_iter_done = on_iter_done
        self.step_mode = bool(step_mode)
        self._abort = threading.Event()
        self._player: Player | None = None

    def abort(self) -> None:
        self._abort.set()
        if self._player:
            self._player.abort()

    def pause(self) -> None:
        if self._player:
            self._player.pause()

    def resume(self) -> None:
        if self._player:
            self._player.resume()

    def advance_step(self) -> None:
        """En modo step-through, indica al player que avance al siguiente paso."""
        if self._player:
            self._player.advance_step()

    @property
    def player(self) -> Player | None:
        """Acceso al Player en curso (para inserciones de pasos en
        runtime desde la UI de step-through)."""
        return self._player

    def run(self) -> ReplaySummary:
        ok_list: list[int] = []
        ko_list: list[tuple[int, str]] = []
        logger.info(
            "Replay '{}' · veces={} · velocidad={} · watchdog={}",
            self.macro.nombre, self.veces, self.velocidad, self.watchdog_activo,
        )
        for n in range(1, self.veces + 1):
            if self._abort.is_set():
                logger.info("Replay abortado por el usuario en la iteración {}", n)
                break
            ctx = {"ITERACION": str(n), "DNI": f"iter_{n:04d}"}
            self._player = Player(
                macro=self.macro,
                screenshots_dir=self.screenshots_dir,
                logger=self.excel_logger,
                ignorar_popups=self.ignorar_popups,
                polling_watchdog_ms=self.polling_watchdog_ms,
                on_status=self.on_status,
                dry_run=False,
                velocidad=self.velocidad,
                step_mode=self.step_mode,
            )
            try:
                exito, incidencias = self._player.ejecutar_dni(ctx)
            except Exception as exc:
                logger.exception("Excepción procesando iteración {}", n)
                exito = False
                incidencias = []

            if exito:
                ok_list.append(n)
                self.excel_logger.append_ok(
                    dni=ctx["DNI"],
                    macro=self.macro.nombre,
                    detalle=f"Iteración {n}/{self.veces} ok",
                )
                logger.info("[replay] iter {}/{} OK", n, self.veces)
                if self.on_iter_done:
                    self.on_iter_done(n, True, "")
            else:
                motivo = ""
                if incidencias:
                    inc = incidencias[-1]
                    motivo = f"{inc.titulo_popup}: {inc.texto_popup}".strip(": ") or inc.detalle
                    motivo = motivo[:200]
                ko_list.append((n, motivo))
                logger.warning("[replay] iter {}/{} KO · {}", n, self.veces, motivo)
                if self.on_iter_done:
                    self.on_iter_done(n, False, motivo)

        return ReplaySummary(
            total=len(ok_list) + len(ko_list),
            ok=len(ok_list),
            ko=len(ko_list),
            log_path=str(self.log_path),
            iters_ok=ok_list,
            iters_ko=ko_list,
        )
