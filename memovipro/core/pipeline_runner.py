"""PipelineRunner: ejecuta una cadena de macros con políticas y pausas."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from .pipeline import Condicion, OnFailPolicy, Pipeline, PipelineStep
from .replay_runner import ReplayRunner, ReplaySummary
from .step_model import Macro


@dataclass
class PipelineStepResult:
    nombre_macro: str
    saltado: bool = False
    motivo_salto: str = ""
    veces: int = 0
    ok: int = 0
    ko: int = 0


@dataclass
class PipelineSummary:
    nombre: str
    pasos_resultado: list[PipelineStepResult] = field(default_factory=list)
    abortado: bool = False

    @property
    def total_ok(self) -> int:
        return sum(r.ok for r in self.pasos_resultado)

    @property
    def total_ko(self) -> int:
        return sum(r.ko for r in self.pasos_resultado)


class PipelineRunner:
    def __init__(
        self,
        pipeline: Pipeline,
        macros_dir: str | Path,
        screenshots_dir: str | Path,
        data_dir: str | Path = "data",
        on_step_start: Callable[[int, PipelineStep], None] | None = None,
        on_step_done: Callable[[int, PipelineStepResult], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        settle_entre_macros_s: float = 0.8,
    ):
        self.pipeline = pipeline
        self.macros_dir = Path(macros_dir)
        self.screenshots_dir = Path(screenshots_dir)
        self.data_dir = Path(data_dir)
        self.on_step_start = on_step_start
        self.on_step_done = on_step_done
        self.on_log = on_log
        # Margen entre una macro y la siguiente: deja que el watchdog de la
        # anterior termine del todo y que las ventanas se asienten antes de
        # empezar a clicar en la siguiente (evita solapamientos en cadenas).
        self.settle_entre_macros_s = max(0.0, float(settle_entre_macros_s))
        self._abort = threading.Event()
        self._current_replay: ReplayRunner | None = None

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            self.on_log(msg)

    def abort(self) -> None:
        self._abort.set()
        if self._current_replay is not None:
            self._current_replay.abort()

    def _resolver_macro_path(self, nombre_o_ruta: str) -> Path:
        p = Path(nombre_o_ruta)
        if p.is_file():
            return p
        for sufijo in (".yaml", ".yml"):
            cand = self.macros_dir / f"{nombre_o_ruta}{sufijo}"
            if cand.exists():
                return cand
        raise FileNotFoundError(
            f"Macro no encontrada: {nombre_o_ruta} (buscado en {self.macros_dir})"
        )

    def _puede_ejecutar(self, paso: PipelineStep, hubo_ko_previo: bool, todos_ok_previo: bool) -> bool:
        if paso.condicion == Condicion.SIEMPRE:
            return True
        if paso.condicion == Condicion.TODOS_OK:
            return todos_ok_previo
        if paso.condicion == Condicion.ALGUNA_KO:
            return hubo_ko_previo
        return True

    def run(self) -> PipelineSummary:
        summary = PipelineSummary(nombre=self.pipeline.nombre)
        self._log(f"▶ Pipeline '{self.pipeline.nombre}' con {len(self.pipeline.pasos)} pasos")
        hubo_ko = False
        todos_ok = True
        skip_rest = False

        for idx, paso in enumerate(self.pipeline.pasos, start=1):
            if self._abort.is_set():
                summary.abortado = True
                self._log("⏹ Pipeline abortado por el usuario")
                break

            res = PipelineStepResult(nombre_macro=paso.macro)

            if skip_rest:
                res.saltado = True
                res.motivo_salto = "skip_rest desde paso anterior"
                summary.pasos_resultado.append(res)
                self._log(f"  ⤵ paso {idx} '{paso.macro}' — saltado (skip_rest)")
                continue

            if not self._puede_ejecutar(paso, hubo_ko_previo=hubo_ko, todos_ok_previo=todos_ok):
                res.saltado = True
                res.motivo_salto = f"condición '{paso.condicion.value}' no se cumple"
                summary.pasos_resultado.append(res)
                self._log(f"  ⤵ paso {idx} '{paso.macro}' — saltado ({res.motivo_salto})")
                continue

            if paso.pausa_antes_s > 0:
                self._log(f"  ⏳ pausa de {paso.pausa_antes_s:g}s antes de '{paso.macro}'")
                fin = time.time() + paso.pausa_antes_s
                while time.time() < fin and not self._abort.is_set():
                    time.sleep(min(0.2, fin - time.time()))
                if self._abort.is_set():
                    summary.abortado = True
                    break

            if self.on_step_start:
                self.on_step_start(idx, paso)

            try:
                macro_path = self._resolver_macro_path(paso.macro)
                macro = Macro.load(macro_path)
            except Exception as exc:
                self._log(f"  ✗ paso {idx} '{paso.macro}' — no se pudo cargar: {exc}")
                res.ko = 1
                res.veces = 1
                summary.pasos_resultado.append(res)
                hubo_ko = True
                todos_ok = False
                if paso.on_fail == OnFailPolicy.STOP:
                    break
                if paso.on_fail == OnFailPolicy.SKIP_REST:
                    skip_rest = True
                continue

            self._log(
                f"  ▶ paso {idx} '{paso.macro}' — veces={paso.veces} velocidad={paso.velocidad}"
            )
            self._current_replay = ReplayRunner(
                macro=macro,
                veces=paso.veces,
                velocidad=paso.velocidad,
                screenshots_dir=self.screenshots_dir,
                data_dir=self.data_dir,
            )
            replay_summary: ReplaySummary = self._current_replay.run()
            self._current_replay = None

            res.veces = replay_summary.total
            res.ok = replay_summary.ok
            res.ko = replay_summary.ko
            summary.pasos_resultado.append(res)

            self._log(
                f"  · paso {idx} fin: OK={res.ok} KO={res.ko} / {res.veces}"
            )

            if res.ko > 0:
                hubo_ko = True
                todos_ok = False
                if paso.on_fail == OnFailPolicy.STOP:
                    self._log(f"  ⏹ paso {idx} falló y on_fail=stop → parar pipeline")
                    break
                if paso.on_fail == OnFailPolicy.SKIP_REST:
                    self._log(f"  ⤵ paso {idx} falló y on_fail=skip_rest → saltar el resto")
                    skip_rest = True

            if self.on_step_done:
                self.on_step_done(idx, res)

            # Asentar antes de la siguiente macro (no tras la última).
            if idx < len(self.pipeline.pasos) and self.settle_entre_macros_s > 0:
                self._log(f"  ⏲ asentando {self.settle_entre_macros_s:g}s antes de la siguiente macro")
                fin = time.time() + self.settle_entre_macros_s
                while time.time() < fin and not self._abort.is_set():
                    time.sleep(min(0.1, max(0.0, fin - time.time())))

        self._log(
            f"=== Pipeline '{self.pipeline.nombre}' fin · "
            f"OK={summary.total_ok} KO={summary.total_ko}"
        )
        return summary
