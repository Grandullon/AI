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
    args = ["--macro", "m1", "--excel", str(tmp_path / "x.xlsx")]
    prog, cmdline = construir_accion(args)
    assert "python" in prog.lower()
    assert "--macro" in cmdline and "m1" in cmdline


def test_construir_accion_con_exe(tmp_path):
    fake_exe = tmp_path / "memovipro-run.exe"
    fake_exe.write_bytes(b"MZ\x00\x00")
    args = ["--macro", "m1", "--excel", str(tmp_path / "x.xlsx")]
    prog, cmdline = construir_accion(args, ejecutable=fake_exe)
    assert prog == str(fake_exe.resolve())
    assert "--macro" in cmdline


def test_construir_accion_modo_replay():
    args = ["--replay", "pa-activo", "--veces", "100", "--velocidad", "1.5"]
    _, cmdline = construir_accion(args)
    assert "--replay" in cmdline
    assert "--veces" in cmdline
    assert "100" in cmdline


def test_construir_accion_modo_pipeline():
    args = ["--pipeline", "rutina_diaria"]
    _, cmdline = construir_accion(args)
    assert "--pipeline" in cmdline
    assert "rutina_diaria" in cmdline


def test_construir_accion_propaga_extras():
    args = ["--replay", "m1", "--veces", "3", "--dry-run", "--no-notify"]
    _, cmdline = construir_accion(args)
    assert "--dry-run" in cmdline
    assert "--no-notify" in cmdline
