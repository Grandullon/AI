"""Borrado de capturas antiguas.

Cada incidencia guarda una captura de la pantalla para poder ver luego
qué pasó. En una aplicación clínica esas capturas llevan dentro datos de
pacientes, así que no pueden quedarse en el disco para siempre: son útiles
unos días, mientras se revisa lo que falló, y a partir de ahí son solo un
riesgo.

No había ninguna rutina de limpieza en el programa; las capturas se
acumulaban desde la primera ejecución.
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

# Días que se conservan las capturas. Coincide con la retención de los
# ficheros de registro (core/log_config), para no tener dos criterios.
DIAS_RETENCION = 30


def limpiar_capturas(directorio, dias: int = DIAS_RETENCION) -> int:
    """Borra las capturas con más de `dias` días. Devuelve cuántas borró.

    Blindado: si una no se puede borrar (abierta, permisos), se salta y
    sigue con el resto. Nunca interrumpe una ejecución.
    """
    if dias <= 0:
        return 0
    try:
        carpeta = Path(directorio)
        if not carpeta.is_dir():
            return 0
    except Exception:
        return 0

    limite = time.time() - dias * 86400
    borradas = 0
    for patron in ("*.png", "*.jpg"):
        try:
            candidatos = list(carpeta.glob(patron))
        except Exception:
            continue
        for f in candidatos:
            try:
                if f.stat().st_mtime < limite:
                    f.unlink()
                    borradas += 1
            except Exception:
                continue
    if borradas:
        logger.info(
            "Limpieza: {} captura(s) de más de {} días borradas de {}",
            borradas, dias, carpeta,
        )
    return borradas
