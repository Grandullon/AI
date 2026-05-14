"""Orquestador: itera DNIs aplicando la macro, gestiona checkpoint y log."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .dni_iterator import Checkpoint, cargar_dnis
from .excel_logger import ExcelLogger, default_log_path
from .player import Player, RunStatus
from .step_model import Macro


@dataclass
class RunSummary:
    total: int
    ok: int
    ko: int
    log_path: str


class MacroRunner:
    def __init__(
        self,
        macro: Macro,
        excel_dnis: str | Path,
        screenshots_dir: str | Path,
        data_dir: str | Path = "data",
        polling_watchdog_ms: int = 300,
        ignorar_popups: list[str] | None = None,
        on_status: Callable[[RunStatus], None] | None = None,
        on_dni_done: Callable[[str, bool], None] | None = None,
    ):
        self.macro = macro
        self.excel_dnis = Path(excel_dnis)
        self.screenshots_dir = Path(screenshots_dir)
        self.data_dir = Path(data_dir)
        self.log_path = default_log_path(self.data_dir)
        self.logger = ExcelLogger(self.log_path)
        self.checkpoint = Checkpoint(macro=macro.nombre, path_dir=self.data_dir)
        self.polling_watchdog_ms = polling_watchdog_ms
        self.ignorar_popups = ignorar_popups or []
        self.on_status = on_status
        self.on_dni_done = on_dni_done
        self._abort = threading.Event()
        self._player: Player | None = None

    def abort(self) -> None:
        self._abort.set()
        if self._player:
            self._player.abort()

    def run(self, solo_pendientes: bool = True) -> RunSummary:
        todos = cargar_dnis(self.excel_dnis)
        cola = self.checkpoint.pendientes(todos) if solo_pendientes else todos

        ok = 0
        ko = 0
        for fila in cola:
            if self._abort.is_set():
                break
            dni = fila["DNI"]
            self._player = Player(
                macro=self.macro,
                screenshots_dir=self.screenshots_dir,
                logger=self.logger,
                ignorar_popups=self.ignorar_popups,
                polling_watchdog_ms=self.polling_watchdog_ms,
                on_status=self.on_status,
            )
            exito, _ = self._player.ejecutar_dni(fila)
            if exito:
                self.checkpoint.marcar_ok(dni)
                self.logger.append_ok(dni, self.macro.nombre, detalle="Completado sin incidencias")
                ok += 1
            else:
                self.checkpoint.marcar_ko(dni)
                ko += 1
            if self.on_dni_done:
                self.on_dni_done(dni, exito)

        return RunSummary(total=len(cola), ok=ok, ko=ko, log_path=str(self.log_path))
