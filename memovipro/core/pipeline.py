"""Pipelines: cadenas de macros con políticas y pausas configurables.

Un Pipeline es una secuencia ordenada de PipelineStep. Cada paso
referencia una macro YAML por nombre y define:
  - cuántas veces ejecutar la macro
  - velocidad
  - pausa antes de empezar
  - política si esta macro falla (stop / continue / skip_rest)
  - condición opcional para ejecutar (ej. solo si las anteriores fueron OK)

Se programa como una sola tarea de Windows Task Scheduler:
    memovipro-run.exe --pipeline rutina_diaria
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class OnFailPolicy(str, Enum):
    STOP = "stop"          # parar pipeline inmediatamente
    CONTINUE = "continue"  # ignorar y seguir con la siguiente macro
    SKIP_REST = "skip_rest"  # marcar pipeline como parcial y saltar el resto


class Condicion(str, Enum):
    SIEMPRE = "siempre"
    TODOS_OK = "todos_ok"        # solo si todas las anteriores fueron OK
    ALGUNA_KO = "alguna_ko"      # solo si alguna anterior tuvo KO


@dataclass
class PipelineStep:
    macro: str  # nombre del YAML sin extensión, o ruta completa
    veces: int = 1
    velocidad: float = 1.0
    pausa_antes_s: float = 0.0
    on_fail: OnFailPolicy = OnFailPolicy.STOP
    condicion: Condicion = Condicion.SIEMPRE
    descripcion: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {"macro": self.macro}
        if self.veces != 1:
            d["veces"] = self.veces
        if self.velocidad != 1.0:
            d["velocidad"] = self.velocidad
        if self.pausa_antes_s > 0:
            d["pausa_antes_s"] = self.pausa_antes_s
        if self.on_fail != OnFailPolicy.STOP:
            d["on_fail"] = self.on_fail.value
        if self.condicion != Condicion.SIEMPRE:
            d["condicion"] = self.condicion.value
        if self.descripcion:
            d["descripcion"] = self.descripcion
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PipelineStep":
        return cls(
            macro=str(d["macro"]),
            veces=int(d.get("veces", 1)),
            velocidad=float(d.get("velocidad", 1.0)),
            pausa_antes_s=float(d.get("pausa_antes_s", 0.0)),
            on_fail=OnFailPolicy(d.get("on_fail", "stop")),
            condicion=Condicion(d.get("condicion", "siempre")),
            descripcion=d.get("descripcion", ""),
        )


@dataclass
class Pipeline:
    nombre: str
    descripcion: str = ""
    pasos: list[PipelineStep] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "pasos": [p.to_dict() for p in self.pasos],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Pipeline":
        return cls(
            version=int(d.get("version", 1)),
            nombre=d.get("nombre", "sin_nombre"),
            descripcion=d.get("descripcion", ""),
            pasos=[PipelineStep.from_dict(p) for p in d.get("pasos", [])],
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load(cls, path: str | Path) -> "Pipeline":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))
