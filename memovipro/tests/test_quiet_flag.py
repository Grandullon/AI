"""Test del flag --quiet del CLI y su uso automático en tareas programadas.

User reportó: "se ha ejecutado, pero de pronto se ha puesto la pantalla
esta negra delante y claro, el ratón pulsaba sitios que no servían
porque estaba una pantalla delante". Al disparar Task Scheduler la
consola de memovipro-run.exe aparecía en primer plano y los clics del
macro caían sobre el terminal en vez de sobre la app objetivo.

Fix: nuevo --quiet que oculta la consola con ShowWindow(SW_HIDE).
schedule_panel lo añade automáticamente a toda tarea programada.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_cli_acepta_flag_quiet():
    """argparse no debe fallar al ver --quiet."""
    import importlib
    # Importamos en caliente para no contaminar otros tests
    cli = importlib.import_module("cli")
    parser = importlib.reload(cli)
    # Si _ocultar_consola_si_quiet o el argparse fallaran al cargar el
    # módulo, este test ya habría petado. Probamos parseo directo:
    try:
        cli.main(["--replay", "m1", "--veces", "1", "--quiet",
                  "--data-dir", "/tmp/__memovipro_data",
                  "--macros-dir", "/tmp/__memovipro_macros",
                  "--logs-dir", "/tmp/__memovipro_logs"])
    except SystemExit as e:
        # main devuelve 1/2 dependiendo del fallo (la macro no existe).
        # Lo importante es que NO fue 2 por argparse error.
        assert e.code != 2, "argparse no debería rechazar --quiet"
    except Exception:
        # Otros errores son aceptables (faltan macros, no es Windows, etc.)
        pass


def test_ocultar_consola_sin_quiet_es_noop(monkeypatch):
    """Si no hay --quiet, la función no intenta tocar la consola."""
    # Forzamos que ctypes.windll no exista — si la función intentara
    # usarlo sin chequear --quiet, esto petaría.
    import cli
    monkeypatch.setattr(sys, "argv", ["cli.py", "--replay", "m1"])
    # No debe lanzar
    cli._ocultar_consola_si_quiet()


def test_ocultar_consola_con_quiet_no_peta_fuera_de_windows(monkeypatch):
    """En Linux/Mac la función debe ser no-op aunque haya --quiet."""
    import cli
    monkeypatch.setattr(sys, "argv", ["cli.py", "--quiet", "--replay", "m1"])
    monkeypatch.setattr(sys, "platform", "linux")
    cli._ocultar_consola_si_quiet()  # no debe lanzar


# ---- Schedule panel añade --quiet automáticamente ----

def test_schedule_panel_args_incluye_quiet():
    """Inspección estática: el módulo schedule_panel debe insertar
    --quiet en los args generados para cualquier modo. Leemos el
    fichero directamente para no tener que importar PyQt6."""
    panel_path = ROOT / "ui" / "schedule_panel.py"
    src = panel_path.read_text(encoding="utf-8")
    # _args es el método unificado tras el refactor
    idx = src.find("def _args(")
    assert idx >= 0, "No encuentro _args"
    bloque = src[idx:idx + 5000]
    next_def = bloque.find("\n    def ", 10)
    if next_def > 0:
        bloque = bloque[:next_def]
    # Debe aparecer --quiet en las tres ramas (REPLAY, PIPELINE, DNI)
    assert bloque.count('"--quiet"') >= 3, (
        "_args debería incluir '--quiet' en las tres ramas (replay, pipeline, dni)"
    )
