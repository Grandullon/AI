"""Bootstrap: prepara el entorno de ejecución en la primera arrancada.

Cuando MemoviPro se ejecuta como `.exe` (PyInstaller), los archivos
incluidos como `datas` viven en `sys._MEIPASS` (carpeta temporal). Pero
el usuario espera que `macros/`, `data/`, `logs/` aparezcan junto al
`.exe`, no en una carpeta temporal que cambia en cada ejecución.

Esta función:
1. Crea `data/`, `data/screenshots/`, `logs/`, `macros/` junto al `.exe`.
2. Si `macros/` está vacío y hay macros de ejemplo bundleados en
   `_MEIPASS/macros/`, las copia a `<exe>/macros/` para que el usuario
   tenga al menos una de referencia.
3. Si no existe `config.json` junto al `.exe`, copia el bundleado.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _bundle_dir() -> Path | None:
    """Devuelve la carpeta donde PyInstaller extrae los datos, o None si no está congelado."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return None


def _copiar_si_falta(origen: Path, destino: Path) -> int:
    """Copia el contenido de `origen` a `destino` solo si destino está vacío. Devuelve nº archivos copiados."""
    if not origen.exists():
        return 0
    destino.mkdir(parents=True, exist_ok=True)
    if any(destino.iterdir()):
        return 0
    n = 0
    for item in origen.iterdir():
        if item.is_file():
            shutil.copy2(item, destino / item.name)
            n += 1
        elif item.is_dir():
            shutil.copytree(item, destino / item.name)
            n += 1
    return n


def ensure_runtime_folders(root: Path) -> dict:
    """Crea las carpetas runtime y copia los assets bundleados si procede.

    Devuelve un dict con un resumen para poder loggearlo.
    """
    root = Path(root)
    creadas = []
    for sub in ("data", "data/screenshots", "logs", "macros", "pipelines"):
        p = root / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            creadas.append(str(p))

    copiados_macros = 0
    copiados_pipelines = 0
    config_copiado = False

    bundle = _bundle_dir()
    if bundle is not None:
        copiados_macros = _copiar_si_falta(bundle / "macros", root / "macros")
        copiados_pipelines = _copiar_si_falta(bundle / "pipelines", root / "pipelines")
        bundle_cfg = bundle / "config.json"
        dest_cfg = root / "config.json"
        if bundle_cfg.exists() and not dest_cfg.exists():
            shutil.copy2(bundle_cfg, dest_cfg)
            config_copiado = True

    return {
        "root": str(root),
        "carpetas_creadas": creadas,
        "macros_copiadas": copiados_macros,
        "pipelines_copiados": copiados_pipelines,
        "config_copiado": config_copiado,
        "bundle_dir": str(bundle) if bundle else None,
    }
