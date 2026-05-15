"""MemoviPro - punto de entrada de la GUI."""
from __future__ import annotations

import sys
from pathlib import Path

# Cuando se ejecuta como script .py: ROOT es la carpeta del repo.
# Cuando se ejecuta como .exe (PyInstaller): ROOT es la carpeta del .exe,
# para que data/, logs/, macros/ se creen junto al ejecutable y no en el
# directorio temporal _MEI*.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication

from core.bootstrap import ensure_runtime_folders
from core.log_config import setup_logging
from ui.main_window import MainWindow


def main() -> int:
    info = ensure_runtime_folders(ROOT)
    data_dir = ROOT / "data"
    macros_dir = ROOT / "macros"
    pipelines_dir = ROOT / "pipelines"
    pipelines_dir.mkdir(exist_ok=True)
    logs_dir = ROOT / "logs"

    setup_logging(logs_dir)
    from loguru import logger
    logger.info("Bootstrap: {}", info)

    app = QApplication(sys.argv)
    win = MainWindow(data_dir=data_dir, macros_dir=macros_dir, pipelines_dir=pipelines_dir)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
