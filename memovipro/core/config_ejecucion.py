"""Lectura de config.json para las ejecuciones.

Existe porque la lista de ventanas a ignorar solo llegaba a la línea de
comandos: desde la aplicación siempre iba vacía, así que configurarla no
servía de nada. Ahora lo leen los dos por el mismo sitio.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


def leer_config(config_path) -> dict:
    """Contenido de config.json, o {} si no está o está mal."""
    try:
        ruta = Path(config_path)
        if not ruta.is_file():
            return {}
        with ruta.open(encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except Exception as exc:
        logger.debug("No se pudo leer {}: {}", config_path, exc)
        return {}


def opciones_ejecucion(config_path) -> dict:
    """Opciones comunes a todas las formas de ejecutar una macro.

    Devuelve un diccionario listo para pasar como argumentos:
      - ignorar_popups: títulos que el vigilante NO debe tratar como
        incidencia (avisos normales de la aplicación).
      - politica_intrusas: qué hacer si se cuela una ventana delante.
    """
    cfg = leer_config(config_path)
    from .ventana_intrusa import politica_desde_config
    return {
        "ignorar_popups": list(cfg.get("popup_titulos_ignorar", []) or []),
        "politica_intrusas": politica_desde_config(cfg),
    }
