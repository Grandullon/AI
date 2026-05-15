"""Tests para los bugs reportados del panel Programación:

1. Las tareas se creaban con `python cli.py` desde la carpeta temp de
   PyInstaller — al disparar Task Scheduler abría memovipro-gui.exe en
   vez de ejecutar la macro.
2. El parser CSV de listar_tareas no entendía el separador `;` que usa
   schtasks en Windows con locale español, dejando la tabla vacía
   aunque la tarea sí existiera.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.scheduler import (
    _auto_detect_run_exe,
    _detectar_delimiter,
    construir_accion,
)


def test_auto_detect_no_es_frozen_devuelve_none(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _auto_detect_run_exe() is None


def test_auto_detect_frozen_encuentra_run_exe(monkeypatch, tmp_path):
    """Si memovipro-run.exe vive al lado del .exe actual, se detecta."""
    gui = tmp_path / "memovipro-gui.exe"
    gui.write_bytes(b"MZ")
    run = tmp_path / "memovipro-run.exe"
    run.write_bytes(b"MZ")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))
    detectado = _auto_detect_run_exe()
    assert detectado is not None
    assert detectado.name == "memovipro-run.exe"


def test_auto_detect_frozen_sin_run_exe_devuelve_none(monkeypatch, tmp_path):
    gui = tmp_path / "memovipro-gui.exe"
    gui.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))
    assert _auto_detect_run_exe() is None


def test_construir_accion_frozen_sin_run_exe_lanza_error_claro(monkeypatch, tmp_path):
    """Antes caía a python cli.py (que apunta a temp folder y no funciona).
    Ahora debe lanzar RuntimeError con mensaje útil."""
    gui = tmp_path / "memovipro-gui.exe"
    gui.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))

    try:
        construir_accion(["--replay", "m1"])
    except RuntimeError as e:
        assert "memovipro-run.exe" in str(e)
    else:
        raise AssertionError("Debería haber lanzado RuntimeError")


def test_construir_accion_frozen_con_run_exe_lo_usa(monkeypatch, tmp_path):
    gui = tmp_path / "memovipro-gui.exe"
    gui.write_bytes(b"MZ")
    run = tmp_path / "memovipro-run.exe"
    run.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(gui))

    prog, args = construir_accion(["--replay", "m1"])
    assert prog == str(run.resolve())
    assert "--replay" in args


# ---- CSV delimiter sniff ----

def test_detectar_delimiter_csv_ingles():
    sample = '"\\MemoviPro_4","Listo","08:00:00","Lista","..."\n'
    assert _detectar_delimiter(sample) == ","


def test_detectar_delimiter_csv_espanol():
    sample = '"\\MemoviPro_4";"Listo";"08:00:00";"Lista";"..."\n'
    assert _detectar_delimiter(sample) == ";"


def test_detectar_delimiter_lineas_vacias_iniciales():
    sample = '\n\n"\\MemoviPro_4";"Listo"\n'
    assert _detectar_delimiter(sample) == ";"


def test_listar_tareas_parsea_csv_con_semicolon(monkeypatch):
    """Reproduce el bug del usuario: schtasks con ';' como separador
    debe procesarse igual y devolver las tareas MemoviPro_*."""
    from core import scheduler as sched

    salida_csv_es = (
        '"\\MemoviPro_4";"08/05/2026 12:57:00";"Listo";"Solo en sesión interactiva";'
        '"5/13/2026 10:15:00";"0";"VIDALF";"C:\\memovipro-run.exe --replay probado --veces 1";"";""\n'
        '"\\MemoviPro_descarga_diaria";"09/05/2026 07:45:00";"Listo";"Solo en sesión interactiva";'
        '"5/13/2026 07:45:00";"0";"VIDALF";"C:\\memovipro-run.exe --pipeline rutina";"";""\n'
    )

    class _FakeResult:
        returncode = 0
        stdout = salida_csv_es
        stderr = ""

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    monkeypatch.setattr(sched, "_correr", lambda cmd: _FakeResult())

    tareas = sched.listar_tareas()
    nombres = {t.nombre for t in tareas}
    assert "MemoviPro_4" in nombres
    assert "MemoviPro_descarga_diaria" in nombres
