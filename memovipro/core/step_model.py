from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class StepType(str, Enum):
    FOCUS_WINDOW = "focus_window"
    CLICK_CONTROL = "click_control"
    CLICK_AT_XY = "click_at_xy"
    TYPE_TEXT = "type_text"
    SEND_KEYS = "send_keys"
    WAIT_UNTIL = "wait_until"
    WAIT_FOR_WINDOW = "wait_for_window"
    SLEEP = "sleep"
    HANDLE_LIBREOFFICE_SAVE = "handle_libreoffice_save"
    CLOSE_WINDOW = "close_window"


@dataclass
class Selector:
    control_type: str | None = None
    name: str | None = None
    auto_id: str | None = None
    class_name: str | None = None
    title: str | None = None

    def is_empty(self) -> bool:
        return not any([self.control_type, self.name, self.auto_id, self.class_name, self.title])


@dataclass
class Step:
    tipo: StepType
    selector: Selector | None = None
    valor: str | None = None
    titulo: str | None = None
    timeout_s: float = 15.0
    reintentos: int = 2
    opcional: bool = False
    descripcion: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"tipo": self.tipo.value}
        if self.selector and not self.selector.is_empty():
            d["selector"] = {k: v for k, v in asdict(self.selector).items() if v is not None}
        if self.valor is not None:
            d["valor"] = self.valor
        if self.titulo is not None:
            d["titulo"] = self.titulo
        if self.timeout_s != 15.0:
            d["timeout_s"] = self.timeout_s
        if self.reintentos != 2:
            d["reintentos"] = self.reintentos
        if self.opcional:
            d["opcional"] = True
        if self.descripcion:
            d["descripcion"] = self.descripcion
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        sel_raw = d.get("selector")
        selector = Selector(**sel_raw) if sel_raw else None
        return cls(
            tipo=StepType(d["tipo"]),
            selector=selector,
            valor=d.get("valor"),
            titulo=d.get("titulo"),
            timeout_s=float(d.get("timeout_s", 15.0)),
            reintentos=int(d.get("reintentos", 2)),
            opcional=bool(d.get("opcional", False)),
            descripcion=d.get("descripcion", ""),
            extra=dict(d.get("extra", {})),
        )


@dataclass
class SalidaConfig:
    carpeta_descargas: str = ""
    patron_renombrado: str = ""


@dataclass
class Macro:
    nombre: str
    ventana_principal: str = ""
    descripcion: str = ""
    salida: SalidaConfig = field(default_factory=SalidaConfig)
    pasos: list[Step] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "ventana_principal": self.ventana_principal,
            "salida": asdict(self.salida),
            "pasos": [p.to_dict() for p in self.pasos],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Macro":
        salida_raw = d.get("salida", {}) or {}
        return cls(
            version=int(d.get("version", 1)),
            nombre=d.get("nombre", "sin_nombre"),
            descripcion=d.get("descripcion", ""),
            ventana_principal=d.get("ventana_principal", ""),
            salida=SalidaConfig(**salida_raw),
            pasos=[Step.from_dict(p) for p in d.get("pasos", [])],
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load(cls, path: str | Path) -> "Macro":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))


_PLACEHOLDER_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")


def render_placeholders(text: str, ctx: dict[str, str]) -> str:
    """Sustituye {DNI}, {YYYYMMDD}, {HHMMSS}, {NOMBRE_OPERADOR}... en una cadena.

    Placeholders auto-resueltos si no están en ctx:
        YYYYMMDD, YYYY, MM, DD, HHMMSS, HH, MM_TIME, SS
    """
    if text is None:
        return text
    now = datetime.now()
    auto = {
        "YYYYMMDD": now.strftime("%Y%m%d"),
        "YYYY": now.strftime("%Y"),
        "MM": now.strftime("%m"),
        "DD": now.strftime("%d"),
        "HHMMSS": now.strftime("%H%M%S"),
        "HH": now.strftime("%H"),
        "MM_TIME": now.strftime("%M"),
        "SS": now.strftime("%S"),
    }
    merged = {**auto, **{k: str(v) for k, v in ctx.items()}}

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return merged.get(key, m.group(0))

    return _PLACEHOLDER_RE.sub(repl, text)


def render_step(step: Step, ctx: dict[str, str]) -> Step:
    """Devuelve una copia del paso con los placeholders ya sustituidos."""
    new_selector = None
    if step.selector:
        new_selector = Selector(
            control_type=step.selector.control_type,
            name=render_placeholders(step.selector.name, ctx) if step.selector.name else None,
            auto_id=step.selector.auto_id,
            class_name=step.selector.class_name,
            title=render_placeholders(step.selector.title, ctx) if step.selector.title else None,
        )
    return Step(
        tipo=step.tipo,
        selector=new_selector,
        valor=render_placeholders(step.valor, ctx) if step.valor else None,
        titulo=render_placeholders(step.titulo, ctx) if step.titulo else None,
        timeout_s=step.timeout_s,
        reintentos=step.reintentos,
        opcional=step.opcional,
        descripcion=step.descripcion,
        extra={k: render_placeholders(v, ctx) if isinstance(v, str) else v for k, v in step.extra.items()},
    )
