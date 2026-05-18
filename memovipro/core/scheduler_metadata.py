"""Persistencia de la configuración de cada tarea programada.

Windows Task Scheduler no almacena nada más allá del comando a ejecutar
y la frecuencia. Para poder editar una tarea o mostrar su modo (replay,
pipeline, DNI), guardamos un JSON paralelo por cada tarea bajo
`data/scheduled_tasks/<nombre_sanitizado>.json`.
"""
from __future__ import annotations

import json
from pathlib import Path


def _sanitize(nombre: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in nombre)


class TaskMetadata:
    """Almacén simple JSON por nombre de tarea."""

    def __init__(self, base_dir: str | Path):
        self.dir = Path(base_dir) / "scheduled_tasks"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, nombre: str) -> Path:
        return self.dir / f"{_sanitize(nombre)}.json"

    def save(self, nombre: str, data: dict) -> None:
        path = self._path(nombre)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def load(self, nombre: str) -> dict | None:
        path = self._path(nombre)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def delete(self, nombre: str) -> None:
        path = self._path(nombre)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    def all_names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))
