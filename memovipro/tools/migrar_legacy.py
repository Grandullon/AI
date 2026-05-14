"""Convierte JSON legacy de Memovi (eventos crudos pynput) a YAML de MemoviPro.

Uso:
    python tools/migrar_legacy.py ruta/grabacion_legacy.json macros/migrada.yaml

Los clics se convierten en `click_at_xy` (requieren revisión manual para
sustituirlos por `click_control` con selectores simbólicos). Los movimientos
de ratón se descartan. Las pulsaciones agrupables de teclado se fusionan en
`type_text`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Macro, Step, StepType


def _is_printable_token(token: str) -> bool:
    return len(token) == 1 and token.isprintable()


def convertir(eventos: list) -> Macro:
    pasos: list[Step] = []
    buffer_text = ""

    def flush():
        nonlocal buffer_text
        if buffer_text:
            pasos.append(Step(tipo=StepType.TYPE_TEXT, valor=buffer_text,
                              descripcion=f'Texto: "{buffer_text[:30]}"'))
            buffer_text = ""

    for tipo, detalle, _ in eventos:
        if tipo == "move":
            continue
        if tipo == "click-press":
            flush()
            x, y, _ = detalle
            pasos.append(Step(tipo=StepType.CLICK_AT_XY, extra={"x": int(x), "y": int(y)},
                              descripcion=f"Click ({x},{y}) — REVISAR: sustituir por selector"))
        elif tipo == "click-release":
            continue
        elif tipo == "scroll":
            continue
        elif tipo == "press":
            tokens = [t for t in (detalle or "").split("+") if t]
            if len(tokens) == 1 and _is_printable_token(tokens[0]):
                buffer_text += tokens[0]
            elif tokens:
                flush()
                pasos.append(Step(tipo=StepType.SEND_KEYS,
                                  valor="+".join(tokens),
                                  descripcion=f"Combinación {tokens}"))
        elif tipo == "release":
            continue

    flush()
    return Macro(nombre="migrada_legacy", pasos=pasos)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("entrada")
    parser.add_argument("salida")
    args = parser.parse_args()

    eventos = json.loads(Path(args.entrada).read_text(encoding="utf-8"))
    macro = convertir(eventos)
    macro.save(args.salida)
    print(f"OK: {len(macro.pasos)} pasos → {args.salida}")
    print("⚠ Recuerda revisar los click_at_xy y sustituirlos por click_control con selectores.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
