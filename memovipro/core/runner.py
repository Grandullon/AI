"""Orquestador: itera DNIs aplicando la macro, gestiona checkpoint y log."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from .dni_iterator import Checkpoint, cargar_dnis
from .excel_logger import ExcelLogger, default_log_path
from .notifier import SmtpConfig, construir_html, enviar_resumen
from .player import Player, RunStatus
from .step_model import Macro


@dataclass
class RunSummary:
    total: int
    ok: int
    ko: int
    log_path: str
    dnis_ok: list[str] = field(default_factory=list)
    dnis_ko: list[tuple[str, str]] = field(default_factory=list)
    checkpoint_invalidado: bool = False


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
        dry_run: bool = False,
        reintentar_ko_al_final: bool = True,
        smtp_config: SmtpConfig | None = None,
    ):
        self.macro = macro
        self.excel_dnis = Path(excel_dnis)
        self.screenshots_dir = Path(screenshots_dir)
        self.data_dir = Path(data_dir)
        self.log_path = default_log_path(self.data_dir)
        self.excel_logger = ExcelLogger(self.log_path)
        self.checkpoint = Checkpoint(
            macro=macro.nombre,
            path_dir=self.data_dir,
            macro_fingerprint=macro.fingerprint(),
        )
        if self.checkpoint.invalidado:
            logger.warning(
                "Checkpoint invalidado: la macro '{}' ha cambiado desde la última ejecución. "
                "Todos los DNIs se reintentarán.",
                macro.nombre,
            )
        self.polling_watchdog_ms = polling_watchdog_ms
        self.ignorar_popups = ignorar_popups or []
        self.on_status = on_status
        self.on_dni_done = on_dni_done
        self.dry_run = dry_run
        self.reintentar_ko_al_final = reintentar_ko_al_final and not dry_run
        self.smtp_config = smtp_config
        self._abort = threading.Event()
        self._player: Player | None = None

    def abort(self) -> None:
        self._abort.set()
        if self._player:
            self._player.abort()

    def _procesar_lote(
        self,
        cola: list[dict],
        etiqueta_pasada: str,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        ok_list: list[str] = []
        ko_list: list[tuple[str, str]] = []
        logger.info("Pasada '{}' · {} DNIs", etiqueta_pasada, len(cola))
        for fila in cola:
            if self._abort.is_set():
                logger.info("Abortado por el usuario")
                break
            dni = fila["DNI"]
            self._player = Player(
                macro=self.macro,
                screenshots_dir=self.screenshots_dir,
                logger=self.excel_logger,
                ignorar_popups=self.ignorar_popups,
                polling_watchdog_ms=self.polling_watchdog_ms,
                on_status=self.on_status,
                dry_run=self.dry_run,
            )
            try:
                exito, incidencias = self._player.ejecutar_dni(fila)
            except Exception as exc:
                logger.exception("Excepción no controlada procesando DNI {}", dni)
                exito = False
                incidencias = []

            if exito:
                self.checkpoint.marcar_ok(dni)
                if not self.dry_run:
                    self.excel_logger.append_ok(
                        dni, self.macro.nombre, detalle=f"Completado ({etiqueta_pasada})"
                    )
                ok_list.append(dni)
                logger.info("[{}] OK · DNI={}", etiqueta_pasada, dni)
            else:
                self.checkpoint.marcar_ko(dni)
                motivo = incidencias[-1].detalle if incidencias else "fallo"
                if incidencias and incidencias[-1].titulo_popup:
                    motivo = f"{incidencias[-1].titulo_popup}: {incidencias[-1].texto_popup}"[:200]
                ko_list.append((dni, motivo))
                logger.warning("[{}] KO · DNI={} · {}", etiqueta_pasada, dni, motivo)
            if self.on_dni_done:
                self.on_dni_done(dni, exito)
        return ok_list, ko_list

    def run(self, solo_pendientes: bool = True) -> RunSummary:
        todos = cargar_dnis(self.excel_dnis)
        cola = self.checkpoint.pendientes(todos) if solo_pendientes else todos
        total = len(cola)

        ok_acum, ko_acum = self._procesar_lote(cola, etiqueta_pasada="pasada-1")

        if self.reintentar_ko_al_final and ko_acum and not self._abort.is_set():
            dnis_ko = {d for d, _ in ko_acum}
            reintentar = [r for r in cola if r["DNI"] in dnis_ko]
            logger.info("Reintentando {} DNIs fallidos con timeouts ampliados", len(reintentar))
            # Multiplicar timeouts x2 en una copia de la macro
            macro_amplia = Macro.from_dict(self.macro.to_dict())
            for p in macro_amplia.pasos:
                p.timeout_s = p.timeout_s * 2
            old_macro, self.macro = self.macro, macro_amplia
            try:
                ok_extra, ko_extra = self._procesar_lote(reintentar, etiqueta_pasada="reintento")
            finally:
                self.macro = old_macro
            ok_acum.extend(ok_extra)
            ok_set = set(ok_extra)
            ko_acum = [(d, m) for d, m in ko_acum if d not in ok_set] + ko_extra

        summary = RunSummary(
            total=total,
            ok=len(ok_acum),
            ko=len(ko_acum),
            log_path=str(self.log_path),
            dnis_ok=ok_acum,
            dnis_ko=ko_acum,
            checkpoint_invalidado=self.checkpoint.invalidado,
        )

        if self.smtp_config and self.smtp_config.is_complete() and not self.dry_run:
            html = construir_html(
                macro=self.macro.nombre,
                total=summary.total,
                ok=summary.ok,
                ko=summary.ko,
                log_path=summary.log_path,
                dnis_fallidos=summary.dnis_ko,
            )
            asunto = f"[MemoviPro] {self.macro.nombre} · OK:{summary.ok} KO:{summary.ko}"
            enviar_resumen(self.smtp_config, asunto, html, adjuntar_log=self.log_path)

        return summary
