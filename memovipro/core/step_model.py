from __future__ import annotations

import hashlib
import json
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
    WINDOW_ENSURE = "window_ensure"  # Asegura ventana al frente + estado (max/normal/min)
    SCROLL = "scroll"                # Rueda del ratón (vertical / horizontal)
    DRAG = "drag"                    # Arrastrar de (x1,y1) a (x2,y2)
    LAUNCH_PROGRAM = "launch_program"  # Ejecuta un .exe / shortcut / comando
    IF_VENTANA = "if_ventana"        # Condicional: si existe (o no) una ventana,
                                     # ejecuta el bloque siguiente o lo salta
    CLICK_OCR_TEXT = "click_ocr_text"  # Clica sobre la palabra/frase indicada
                                       # buscándola en pantalla con OCR. Robusto
                                       # frente a cambios de UI (no depende de
                                       # coordenadas ni de selectores).


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
    delay_before_s: float = 0.0  # segundos de espera antes de ejecutar este paso
    # Verificación post-paso: tras ejecutar el paso, esperar a que
    # aparezca una ventana cuyo título matchee este patrón (regex
    # parcial). Si no aparece en verificar_timeout_s, el paso se marca
    # como fallido → incidencia clara en vez de fallo en cascada.
    verificar_ventana: str = ""
    verificar_timeout_s: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"tipo": self.tipo.value}
        if self.selector and not self.selector.is_empty():
            d["selector"] = {k: v for k, v in asdict(self.selector).items() if v is not None}
        if self.valor is not None:
            d["valor"] = self.valor
        if self.titulo is not None:
            d["titulo"] = self.titulo
        if self.delay_before_s > 0:
            d["delay_before_s"] = round(self.delay_before_s, 3)
        if self.timeout_s != 15.0:
            d["timeout_s"] = self.timeout_s
        if self.reintentos != 2:
            d["reintentos"] = self.reintentos
        if self.opcional:
            d["opcional"] = True
        if self.verificar_ventana:
            d["verificar_ventana"] = self.verificar_ventana
            if self.verificar_timeout_s != 10.0:
                d["verificar_timeout_s"] = self.verificar_timeout_s
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
            delay_before_s=float(d.get("delay_before_s", 0.0)),
            verificar_ventana=d.get("verificar_ventana", ""),
            verificar_timeout_s=float(d.get("verificar_timeout_s", 10.0)),
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
    # Si True y hay ventana_principal, el player se asegura antes de cada
    # paso de que la ventana esté al frente + maximizada. Resuelve el
    # problema de "se abrió Excel en otra posición que ayer".
    auto_anchor: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "ventana_principal": self.ventana_principal,
            "auto_anchor": self.auto_anchor,
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
            auto_anchor=bool(d.get("auto_anchor", True)),
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

    def fingerprint(self) -> str:
        """Hash estable del contenido funcional de la macro (sin descripciones).

        Cambia si: cambia un paso, su tipo, selector, valor o timeout.
        NO cambia si solo cambia la descripción o el nombre del archivo.
        """
        payload = {
            "version": self.version,
            "ventana_principal": self.ventana_principal,
            "pasos": [
                {k: v for k, v in p.to_dict().items() if k != "descripcion"}
                for p in self.pasos
            ],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


def nombre_archivo_macro(nombre: str) -> str:
    """Convierte el nombre de una macro en un nombre de archivo YAML válido.

    Sanitiza caracteres no válidos y garantiza la extensión .yaml. Fuente
    única de verdad para el guardado (evita que el editor y otros sitios
    sanitizen de forma distinta).

        "Rutina Diaria" → "Rutina_Diaria.yaml"
        "informe.yml"   → "informe.yml"   (respeta .yml existente)
        ""              → "macro_sin_nombre.yaml"
    """
    base = (nombre or "").strip() or "macro_sin_nombre"
    base = "".join(c if c.isalnum() or c in "-_." else "_" for c in base)
    if not base.endswith((".yaml", ".yml")):
        base = f"{base}.yaml"
    return base


_PLACEHOLDER_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")
_SECRET_RE = re.compile(r"\{SECRET:([A-Za-z_][A-Za-z0-9_\-]*)\}")


def _resolve_secret(name: str) -> str:
    """Resuelve un placeholder {SECRET:nombre} contra el almacén DPAPI/keyring.

    Si no existe o el backend no está disponible, devuelve un marcador
    visible para que el operador detecte el fallo en lugar de teclear
    una cadena vacía.
    """
    try:
        from .secrets import get_secret
        v = get_secret(name)
        if v is None:
            return f"<<SECRET_NOT_FOUND:{name}>>"
        return v
    except Exception:
        return f"<<SECRET_ERROR:{name}>>"


def render_placeholders(text: str, ctx: dict[str, str]) -> str:
    """Sustituye {DNI}, {YYYYMMDD}, ... y {SECRET:nombre} en una cadena.

    Placeholders auto-resueltos si no están en ctx:
        YYYYMMDD, YYYY, MM, DD, HHMMSS, HH, MM_TIME, SS

    Placeholders especiales:
        {SECRET:nombre} → valor desde el almacén nativo (DPAPI/Keychain)
    """
    if text is None:
        return text

    # 1. Secretos primero (no aparecen en logs porque el log usa la versión sin renderizar)
    text = _SECRET_RE.sub(lambda m: _resolve_secret(m.group(1)), text)

    # 2. Placeholders normales
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


def limpiar_raw_si_editado(paso: Step, nuevo_valor: str) -> None:
    """Quita el flag raw de un paso grabado cuando el usuario edita su valor.

    Los pasos grabados llevan `extra: {raw: true}` para que el texto
    capturado se reproduzca literal (sin sustituir {DNI} ni {SECRET:...}).
    Pero si el usuario cambia el valor a mano, asume la semántica de
    placeholders documentada ("edita el valor y pon {DNI}") — mantener
    raw teclearía el literal "{DNI}". Solo se limpia si el valor CAMBIA:
    abrir el editor y aceptar sin tocar no debe reactivar placeholders
    sobre un literal grabado.
    """
    if nuevo_valor != (paso.valor or "") and paso.extra:
        paso.extra.pop("raw", None)


def render_step(step: Step, ctx: dict[str, str]) -> Step:
    """Devuelve una copia del paso con los placeholders ya sustituidos.

    Los pasos con `extra: {raw: true}` (los que produce el grabador para
    texto/teclas capturados literalmente) NO pasan su `valor` por el motor
    de placeholders: lo tecleado debe reproducirse tal cual, sin sustituir
    {DNI}/{MM}/... ni resolver {SECRET:...} (que teclearía un secreto real).
    """
    raw = bool((step.extra or {}).get("raw"))
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
        valor=step.valor if raw else (render_placeholders(step.valor, ctx) if step.valor else None),
        titulo=render_placeholders(step.titulo, ctx) if step.titulo else None,
        timeout_s=step.timeout_s,
        reintentos=step.reintentos,
        opcional=step.opcional,
        descripcion=step.descripcion,
        extra={k: render_placeholders(v, ctx) if isinstance(v, str) else v for k, v in step.extra.items()},
        delay_before_s=step.delay_before_s,
        verificar_ventana=render_placeholders(step.verificar_ventana, ctx) if step.verificar_ventana else "",
        verificar_timeout_s=step.verificar_timeout_s,
    )
