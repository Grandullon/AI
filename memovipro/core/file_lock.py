"""Lock de fichero entre procesos (cross-process).

Necesario porque una tarea programada (`memovipro-run.exe`) y una
ejecución manual desde la GUI pueden escribir a la vez en el mismo
`incidencias_YYYYMMDD.xlsx` o `checkpoint_*.json` y corromperlo. El
`threading.Lock` solo protege dentro de un proceso.

Implementación: creación atómica de un `<fichero>.lock` con
O_CREAT|O_EXCL (atómico en Windows y POSIX). Si ya existe, reintenta
hasta `timeout`. Un lock más viejo que `stale_after_s` se considera
abandonado (proceso muerto) y se rompe.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def debug(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
    logger = _NullLogger()


@contextmanager
def file_lock(target: str | Path, timeout: float = 15.0, poll: float = 0.1, stale_after_s: float = 120.0):
    """Context manager que adquiere un lock cross-process sobre `target`.

    Uso:
        with file_lock("data/incidencias.xlsx"):
            ... escribir el fichero ...
    """
    lock_path = Path(str(target) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    inicio = time.time()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode())
            except Exception:
                pass
            break
        except FileExistsError:
            # ¿Lock abandonado por un proceso muerto?
            try:
                edad = time.time() - lock_path.stat().st_mtime
                if edad > stale_after_s:
                    logger.warning("Rompiendo lock stale ({}s) de {}", round(edad), target)
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue  # el otro proceso lo soltó justo ahora
            except Exception:
                pass
            if time.time() - inicio > timeout:
                # No bloqueamos eternamente: dejamos pasar y avisamos.
                logger.warning("Timeout esperando lock de {} — continúo sin lock", target)
                fd = None
                break
            time.sleep(poll)
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass
