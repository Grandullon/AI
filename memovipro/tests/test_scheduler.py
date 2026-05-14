from datetime import time as dtime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.scheduler import Frecuencia, construir_accion


def test_frecuencia_diaria():
    args = Frecuencia(diaria=True, hora=dtime(8, 30)).to_schtasks_args()
    assert args == ["/SC", "DAILY", "/ST", "08:30"]


def test_frecuencia_semanal_multiples_dias():
    args = Frecuencia(semanal=True, dias_semana=("MON", "WED", "FRI"), hora=dtime(7, 0)).to_schtasks_args()
    assert "/SC" in args and "WEEKLY" in args
    assert "/D" in args
    assert args[args.index("/D") + 1] == "MON,WED,FRI"
    assert args[-1] == "07:00"


def test_frecuencia_logon():
    args = Frecuencia(al_iniciar_sesion=True).to_schtasks_args()
    assert args == ["/SC", "ONLOGON"]


def test_frecuencia_default_es_diaria():
    args = Frecuencia(hora=dtime(9, 15)).to_schtasks_args()
    assert args == ["/SC", "DAILY", "/ST", "09:15"]


def test_construir_accion_usa_python_si_no_hay_exe(tmp_path):
    excel = tmp_path / "x.xlsx"
    excel.write_text("dummy")
    prog, args = construir_accion(macro="m1", excel=excel)
    assert prog.lower().endswith(("python", "python.exe", "python3", "python3.exe", "memovipro_run", "memovipro-run", "memovipro-run.exe")) or "python" in prog.lower()
    assert "--macro" in args and "m1" in args
    assert str(excel.resolve()) in args


def test_construir_accion_con_exe(tmp_path):
    excel = tmp_path / "x.xlsx"
    excel.write_text("dummy")
    fake_exe = tmp_path / "memovipro-run.exe"
    fake_exe.write_bytes(b"MZ\x00\x00")
    prog, args = construir_accion(macro="m1", excel=excel, ejecutable=fake_exe)
    assert prog == str(fake_exe.resolve())
    assert "--macro" in args


def test_construir_accion_propaga_extras(tmp_path):
    excel = tmp_path / "x.xlsx"
    excel.write_text("dummy")
    _, args = construir_accion(macro="m1", excel=excel, extra_args=["--dry-run", "--no-retry"])
    assert "--dry-run" in args
    assert "--no-retry" in args
