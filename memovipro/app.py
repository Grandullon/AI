"""MemoviPro - punto de entrada de la GUI."""
from __future__ import annotations

import sys
from pathlib import Path

# Permitir importar `core.*` y `ui.*` cuando se ejecuta `python app.py`
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication

from core.log_config import setup_logging
from ui.main_window import MainWindow


def main() -> int:
    data_dir = ROOT / "data"
    macros_dir = ROOT / "macros"
    logs_dir = ROOT / "logs"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "screenshots").mkdir(exist_ok=True)
    macros_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    setup_logging(logs_dir)

    app = QApplication(sys.argv)
    win = MainWindow(data_dir=data_dir, macros_dir=macros_dir)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
