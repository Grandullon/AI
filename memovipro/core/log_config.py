"""Configuración centralizada de logging con loguru.

Cada arranque añade un sink a `logs/run_YYYYMMDD.log` con rotación diaria
y retención de 30 días. El nivel se controla con la variable de entorno
`MEMOVIPRO_LOG_LEVEL` (default INFO).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


def setup_logging(log_dir: str | Path = "logs", level: str | None = None) -> None:
    """Configura loguru una sola vez. Idempotente."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    nivel = level or os.environ.get("MEMOVIPRO_LOG_LEVEL", "INFO")

    logger.remove()
    logger.add(
        sys.stderr,
        level=nivel,
        format="<green>{time:HH:mm:ss}</green> <level>{level: <7}</level> <cyan>{name}:{line}</cyan> {message}",
        colorize=True,
    )
    logger.add(
        log_dir / "run_{time:YYYYMMDD}.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        level=nivel,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}",
    )
    _CONFIGURED = True
    logger.info("Logging inicializado · nivel={} · dir={}", nivel, log_dir.resolve())
