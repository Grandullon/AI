"""Tests para core/log_config.py incluyendo el caso PyInstaller GUI (stderr=None)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_setup_logging_funciona_con_stderr_none(tmp_path, monkeypatch):
    """Reproduce el bug 'Cannot log to objects of type NoneType' de PyInstaller GUI.

    PyInstaller con console=False deja sys.stderr en None. setup_logging
    debe detectarlo y saltarse el sink de stderr en lugar de petar.
    """
    monkeypatch.setattr(sys, "stderr", None)

    # Forzar reconfiguración: importamos y reseteamos la flag idempotente
    from core import log_config
    log_config._CONFIGURED = False

    log_config.setup_logging(log_dir=tmp_path)

    # Si no ha lanzado excepción, el bug está arreglado.
    archivos = list(tmp_path.glob("run_*.log"))
    assert len(archivos) == 1


def test_setup_logging_idempotente(tmp_path):
    from core import log_config
    log_config._CONFIGURED = False
    log_config.setup_logging(log_dir=tmp_path)
    # Segunda llamada no debe duplicar sinks ni lanzar
    log_config.setup_logging(log_dir=tmp_path)
